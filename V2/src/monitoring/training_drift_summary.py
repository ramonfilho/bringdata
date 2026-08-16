"""Sumário de paridade treino × produção (T1-16) — alimenta o bloco
"🎯 Features zeradas em batch" do resumo diário do Slack.

A salvaguarda T1-16 em `src/core/feature_validator.py` é executada a cada
batch que o pipeline processa. Sempre que uma coluna one-hot fica com
taxa de zero acima do esperado pelo treino, ela emite um log textual
`[T1-16] (observa, NÃO bloqueia) ...` listando as features afetadas com
seus pares `(obs vs exp)`.

Esses logs ficam no Cloud Logging e ninguém os lê rotineiramente. Este
módulo é o agregador: lê logs T1-16 das últimas 24h, deduplica, confirma
contra o AGREGADO DO DIA e entrega ao digest do Slack um sumário curto.

HISTÓRICO DE DEFEITOS que moldou o desenho atual (auditoria 16/08/2026):

1. O stream de logs é CONTAMINADO: o T1-16 roda em qualquer chamada de
   scoring — Pub/Sub real, canário com 0% de tráfego, gate de equivalência
   do deploy — e nada na linha distingue a origem. Medido em 7 dias:
   61 linhas = só 29 batches reais; 55,7% vieram de revisão que NÃO servia
   tráfego. Todo deploy loga o MESMO batch em dupla (revisão servindo +
   candidata, ~0,7s), e há triplicatas no mesmo segundo.
2. A versão anterior resumia com MÉDIA DAS LINHAS FLAGRADAS: batch
   saudável não gera linha, então não entra no denominador — média
   condicionada ao disparo apresentada como média do dia. Em 14/08 isso
   suprimiu por 0,0007 o único bug real (Medium_Aberto, razão 0,1007) e
   mostrou 3 features benignas vindas do tráfego de gate.

DESENHO ATUAL (espelha o princípio do fix de 24/06: filtrar na EXIBIÇÃO,
nunca na detecção — feature_validator/encoding ficam intocados):

- DEDUP temporal: mesma (run_id, batch, conteúdo) a <=5s colapsa em um
  evento. Par do gate e triplicatas somem; batches reais repetidos com
  minutos de distância continuam distintos (em produção sai ~1 batch/min,
  então 5s não engole dia de bug real).
- CONFIRMAÇÃO NO AGREGADO DO DIA: quem decide se a feature aparece é a
  taxa REAL do dia inteiro (`taxas_do_dia`, computada pelo monitoramento
  com o MESMO encoding do core sobre os leads reais), não a média das
  linhas. Gate pode inflar linhas à vontade — não muda o agregado.
- FALLBACK POR FEATURE: sem taxa disponível para aquele (run_id, coluna)
  — call site sem df, modelo fora do active_models, registry ausente —
  cai na heurística antiga COM marcação, feature a feature.
- CONTEXTO anti-cegueira: feature suprimida como "saudável no agregado"
  mas com muitos eventos deduplicados vira linha de CONTEXTO no digest
  (não alerta cheio). Cobre o único cenário em que o desenho novo enxerga
  menos que o velho: colapso PARCIAL persistente (taxa entre 10% e 30% do
  treino) e divergência de paridade scoring×monitoramento.

Sem regras de negócio aqui — só agregação e formatação. Criado em
2026-05-25 (registro_erros_ml.md § V.5); reescrito em 2026-08-16.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


WINDOW_HOURS = 24
TOP_FEATURES_LIMIT = 5

# Só mostra no digest uma feature EFETIVAMENTE ZERADA — a assinatura de bug
# de encoding/ingestão (categoria sumiu, parse JSONB quebrou, casing mudou).
# Com `taxas_do_dia`, o fator é aplicado à taxa REAL do dia; no fallback,
# à média das linhas flagradas (herda o viés de seleção — por isso é só
# fallback, e marcado como tal).
ZEROED_OBS_FACTOR = 0.10

# Dedup: ocorrências da MESMA (run_id, batch, conteúdo) a até este intervalo
# são o mesmo evento físico logado mais de uma vez (par servindo+candidata do
# gate ~0,7s; triplicatas no mesmo segundo). Batches reais consecutivos em
# produção distam ~1 min (≈1.300/dia), então 5s não colapsa dia de bug real.
DEDUP_JANELA_S = 5.0

# Feature suprimida como "saudável no agregado" com este nº de eventos
# DEDUPLICADOS ou mais ganha linha de contexto no digest: produção gritando
# com agregado saudável é assinatura de colapso parcial persistente ou de
# divergência de paridade scoring×monitoramento, não de ruído. O gate gera
# no máximo 1-3 eventos dedup por feature/dia; um colapso parcial real gera
# dezenas.
CONTEXTO_MIN_EVENTOS = 5

# Casa o conteúdo "Exemplos: FEATURE_A (obs=0.060 vs exp=0.223), ..." do log
# T1-16 WARNING. Captura todos os triples (feature, obs, exp) por linha.
_FEATURE_OBS_EXP_RE = re.compile(
    r"([A-Za-z_][\w]*) \(obs=([\d.]+) vs exp=([\d.]+)\)"
)
_RUN_ID_RE = re.compile(r"mlflow_run_id=([0-9a-f]+)")
_BATCH_RE = re.compile(r"batch=(\d+)")


def _parse_linha(texto: str) -> Optional[Dict[str, Any]]:
    """Extrai (run_id8, batch, features) de uma linha T1-16. None se não parseia."""
    feats = [(m.group(1), float(m.group(2)), float(m.group(3)))
             for m in _FEATURE_OBS_EXP_RE.finditer(texto)]
    if not feats:
        return None
    run_m = _RUN_ID_RE.search(texto)
    batch_m = _BATCH_RE.search(texto)
    return {
        'run_id8': run_m.group(1)[:8] if run_m else None,
        'batch': int(batch_m.group(1)) if batch_m else None,
        'features': feats,
    }


def _aggregate_t116(entradas: List[Dict[str, Any]],
                    taxas_do_dia: Optional[Dict[str, Dict[str, float]]] = None,
                    *,
                    hours: int = WINDOW_HOURS) -> Dict[str, Any]:
    """Agregação PURA das linhas T1-16 — separada da leitura do Cloud Logging
    exatamente para ser testável (antes desta separação o módulo tinha zero
    testes).

    Args:
        entradas: [{'texto': str, 'revisao': str|None, 'ts': datetime|None}]
            na ordem que vier (ordenamos aqui).
        taxas_do_dia: {run_id8: {coluna_ohe: taxa_float}} — a taxa agregada
            REAL do dia por variante, computada dos leads reais. None ou {}
            = indisponível (fallback heurístico marcado).
        hours: janela, só para o payload.

    Returns:
        Dict com contrato ESTÁVEL (todas as chaves sempre presentes — o
        payload_schema do daily-check declara cada uma e falha alto em chave
        produzida sem declaração).
    """
    taxas_do_dia = taxas_do_dia or {}
    tem_taxas = bool(taxas_do_dia)
    confirmacao = 'agregado_do_dia' if tem_taxas else 'heuristica_fallback'

    base = {
        'window_hours': hours,
        'batches_com_drift': 0,
        'total_observacoes': 0,
        'top_features': [],
        'suppressed_features': 0,
        'observacao': '',
        'confirmacao': confirmacao,
        'linhas_brutas': len(entradas),
        'eventos_dedup': 0,
        'revisoes': sorted({e['revisao'] for e in entradas if e.get('revisao')}),
        'suprimidas_saudaveis': [],
    }

    if not entradas:
        base['observacao'] = ('sem warnings T1-16 na janela — modelo recebendo '
                              'dados consistentes com o treino')
        return base

    # ── 1. Parse + DEDUP temporal ────────────────────────────────────────────
    # Mesmo (run_id, batch, conteúdo) a <=DEDUP_JANELA_S do último visto é o
    # mesmo evento físico relogado (par do gate, triplicata). Janela DESLIZANTE
    # sobre timestamps ordenados — bucket fixo cortaria o par do gate (~0,7s)
    # quando ele cruza a fronteira do segundo.
    parseadas = []
    for e in entradas:
        p = _parse_linha(e['texto'])
        if p is None:
            continue
        parseadas.append({**p, 'revisao': e.get('revisao'), 'ts': e.get('ts')})

    def _ordem(item):
        ts = item['ts']
        return ts if ts is not None else datetime.min.replace(tzinfo=timezone.utc)
    parseadas.sort(key=_ordem)

    eventos: List[Dict[str, Any]] = []
    ultimo_visto: Dict[tuple, datetime] = {}
    for item in parseadas:
        chave = (item['run_id8'], item['batch'],
                 tuple(sorted((f, f"{o:.3f}", f"{x:.3f}")
                              for f, o, x in item['features'])))
        ts = item['ts']
        anterior = ultimo_visto.get(chave)
        if (ts is not None and anterior is not None
                and (ts - anterior).total_seconds() <= DEDUP_JANELA_S):
            # Encadeia a janela: triplicata colapsa inteira, e o par do gate
            # (~0,7s) colapsa mesmo cruzando fronteira de segundo. A revisão
            # da linha colapsada não se perde — `revisoes` do payload vem de
            # TODAS as entradas, antes do dedup.
            ultimo_visto[chave] = ts
            continue
        if ts is not None:
            ultimo_visto[chave] = ts
        eventos.append(item)

    base['eventos_dedup'] = len(eventos)

    # ── 2. Acumula por (run_id8, feature) sobre eventos DEDUPLICADOS ────────
    grupos: Dict[tuple, List[tuple]] = defaultdict(list)
    for ev in eventos:
        for feat, obs, exp in ev['features']:
            grupos[(ev['run_id8'], feat)].append((obs, exp))

    # ── 3. Decide por feature: confirmada / saudável-no-agregado / ruído ────
    confirmadas: Dict[tuple, tuple] = {}   # (run,feat) -> (obs_mean, exp, n, taxa)
    saudaveis: Dict[tuple, tuple] = {}     # (run,feat) -> (taxa, exp, n)
    ruido: Dict[tuple, tuple] = {}         # fallback suprimida
    for (run_id8, feat), pairs in grupos.items():
        obs_mean = sum(p[0] for p in pairs) / len(pairs)
        exp_value = pairs[0][1]  # `exp` é fixo por feature (vem do treino)
        n = len(pairs)
        taxa = None
        if run_id8 is not None:
            taxa = (taxas_do_dia.get(run_id8) or {}).get(feat)
        if taxa is not None and exp_value > 0:
            # O agregado do dia é o juiz: linhas de gate/canário não o movem.
            if taxa <= ZEROED_OBS_FACTOR * exp_value:
                confirmadas[(run_id8, feat)] = (obs_mean, exp_value, n, taxa)
            else:
                saudaveis[(run_id8, feat)] = (taxa, exp_value, n)
        else:
            # Fallback por FEATURE (não tudo-ou-nada): sem taxa para este
            # (run_id, coluna), vale a heurística antiga — média das linhas
            # flagradas, com o viés de seleção conhecido.
            if exp_value > 0 and obs_mean <= ZEROED_OBS_FACTOR * exp_value:
                confirmadas[(run_id8, feat)] = (obs_mean, exp_value, n, None)
            else:
                ruido[(run_id8, feat)] = (obs_mean, exp_value, n)

    base['suppressed_features'] = len(saudaveis) + len(ruido)
    base['suprimidas_saudaveis'] = [
        {'feature': feat, 'taxa_dia': round(taxa, 4),
         'exp': round(exp, 4), 'eventos': n}
        for (_r, feat), (taxa, exp, n) in
        sorted(saudaveis.items(), key=lambda kv: kv[1][2], reverse=True)
    ]

    if saudaveis:
        logger.info(
            "[training_drift] %d feature(s) suprimida(s): flagradas em batch "
            "mas SAUDÁVEIS no agregado do dia (tráfego de gate/canário não move "
            "o agregado): %s",
            len(saudaveis),
            ', '.join(f"{feat}(dia={v[0]:.3f} vs exp={v[1]:.3f}, {v[2]} eventos)"
                      for (_r, feat), v in saudaveis.items()),
        )
    if ruido:
        logger.info(
            "[training_drift] %d feature(s) suprimida(s) como ruído sem "
            "confirmação de agregado (obs média acima de %.0f%% do treino): %s",
            len(ruido), ZEROED_OBS_FACTOR * 100,
            ', '.join(f"{feat}(obs={v[0]:.3f} vs exp={v[1]:.3f}, {v[2]}x)"
                      for (_r, feat), v in ruido.items()),
        )

    if not confirmadas:
        partes = []
        if saudaveis:
            partes.append(f'{len(saudaveis)} feature(s) flagrada(s) em batch mas '
                          f'saudável(is) no agregado do dia')
        if ruido:
            partes.append(f'{len(ruido)} feature(s) apenas reduzida(s) '
                          f'(drift/ruído de amostragem)')
        base['observacao'] = ('; '.join(partes) + ' — suprimidas; nenhuma '
                             'efetivamente zerada') if partes else (
                             'linhas T1-16 sem features parseáveis na janela')
        return base

    # ── 4. Recontagem restrita às confirmadas (sobre eventos DEDUPLICADOS) ──
    chaves_conf = set(confirmadas)
    batches_reais = 0
    total_obs_reais = 0
    for ev in eventos:
        no_evento = {(ev['run_id8'], f) for f, _o, _x in ev['features']}
        inter = no_evento & chaves_conf
        if inter:
            batches_reais += 1
            total_obs_reais += len(inter)

    ranked = sorted(confirmadas.items(), key=lambda kv: kv[1][2], reverse=True)
    top_features = []
    for (_run, feat), (obs_mean, exp_value, n, taxa) in ranked[:TOP_FEATURES_LIMIT]:
        top_features.append({
            'feature': feat,
            'obs_media': round(obs_mean, 4),
            'exp': round(exp_value, 4),
            'delta_pp': round(100 * ((taxa if taxa is not None else obs_mean)
                                     - exp_value), 1),
            'count': n,
            'taxa_dia': round(taxa, 4) if taxa is not None else None,
        })

    algum_confirmado_por_agregado = any(
        f['taxa_dia'] is not None for f in top_features)
    if algum_confirmado_por_agregado:
        base['observacao'] = (
            'ATENÇÃO: feature(s) ZERADA(S) confirmada(s) no AGREGADO DO DIA '
            '(taxa real ~0% vs treino) — bug de encoding/ingestão; investigar')
    else:
        base['observacao'] = (
            'ATENÇÃO: feature(s) com obs ~0% nas linhas flagradas — NÃO '
            'confirmado no agregado do dia (taxas indisponíveis nesta janela); '
            'possível bug de encoding/ingestão; investigar')

    base['batches_com_drift'] = batches_reais
    base['total_observacoes'] = total_obs_reais
    base['top_features'] = top_features
    return base


def compute_training_drift_summary(
    *,
    hours: int = WINDOW_HOURS,
    project: str = 'smart-ads-451319',
    service: str = 'smart-ads-api',
    revision: Optional[str] = None,
    taxas_do_dia: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Sumariza warnings T1-16 das últimas N horas.

    Casca de I/O: lê via Cloud Logging API e delega a agregação à função pura
    `_aggregate_t116` (a lógica e os testes moram lá).

    Args:
        hours: janela em horas (default 24).
        project: projeto GCP.
        service: nome do Cloud Run service.
        revision: filtra só uma revisão se passado.
        taxas_do_dia: {run_id8: {coluna_ohe: taxa}} do agregado do dia por
            variante ativa (ver DataQualityMonitor.compute_ohe_daily_rates).
            None/{} = confirmar pelo fallback heurístico, marcado no payload.
            O call site do early-return (api/app.py, janela sem lead scoreado)
            NUNCA tem df — a assinatura precisa funcionar sem ele.

    Returns:
        Dict do `_aggregate_t116`, mais `erro` quando a leitura falha.
    """
    try:
        from google.cloud import logging as gcp_logging
    except ImportError:
        out = _aggregate_t116([], taxas_do_dia, hours=hours)
        out['observacao'] = 'google-cloud-logging não disponível'
        out['erro'] = 'ImportError'
        return out

    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=hours)
    since_iso = since_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    filter_parts = [
        'resource.type="cloud_run_revision"',
        f'resource.labels.service_name="{service}"',
        # Captura só o WARNING legível que tem `(obs=... vs exp=...)`.
        # O ERROR companheiro tem formato diferente e os mesmos números —
        # contar os dois infla a contagem.
        'textPayload:"[T1-16] (observa"',
        f'timestamp>="{since_iso}"',
    ]
    if revision:
        filter_parts.append(f'resource.labels.revision_name="{revision}"')
    filter_str = ' AND '.join(filter_parts)

    try:
        log_client = gcp_logging.Client(project=project)
        log_entries = log_client.list_entries(
            filter_=filter_str,
            order_by=gcp_logging.DESCENDING,
            max_results=5000,
        )
        # Entry inteira descartada se o payload não é texto — nunca listas
        # paralelas desalinhadas de texto/revisão/timestamp.
        entradas = []
        for e in log_entries:
            if not isinstance(e.payload, str):
                continue
            revisao = None
            try:
                revisao = (e.resource.labels or {}).get('revision_name')
            except Exception:
                pass
            entradas.append({'texto': e.payload, 'revisao': revisao,
                             'ts': e.timestamp})
    except Exception as e:
        logger.warning(f"[training_drift] Cloud Logging API falhou: {e}")
        out = _aggregate_t116([], taxas_do_dia, hours=hours)
        out['observacao'] = 'falha ao consultar Cloud Logging'
        out['erro'] = f'{type(e).__name__}: {str(e)[:200]}'
        return out

    return _aggregate_t116(entradas, taxas_do_dia, hours=hours)
