"""
Qualidade de UTM (source, medium, content) por modelo Champion vs Challenger.

Para cada UTM em cada nível, agrega leads scoreados em duas janelas:
- Últimas N horas (default 24h)
- LF ativo (cap_start → hoje BRT); fallback no LF mais recente encerrado.

Métricas por (UTM × modelo × janela):
- n  (volume)
- avg_decil
- pct_d9_d10

Ranking unificado por avg_decil combinado (ponderado por n) na janela 24h;
filtragem por `min_volume` na janela 24h. Split por modelo visível em cada
linha (mesma fonte de verdade da atribuição em produção — reusa
`ABTestConfig.match_variant`).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))


# ──────────────────────────────────────────────────────────────────────────
# Variant attribution (reusa ABTestConfig.match_variant)
# ──────────────────────────────────────────────────────────────────────────

def _classify_variant_from_record(record, ab_cfg,
                                   champion_name: str, challenger_name: str) -> str:
    """Atribui variante de um `LeadRecord`.

    Prefere `record.variant` quando preenchido (ledger novo registra a variante
    direto). Cai no match histórico via UTMs+URL apenas quando o ledger não
    carrega (adaptador legado, leads pré-Pub/Sub).

    Migrado em 2026-05-24 (Etapa 6 do refator). Antes era tupla de strings;
    agora consome `LeadRecord` por injeção de dependência.
    """
    if record.variant in (champion_name, challenger_name):
        return record.variant

    # Fallback: match histórico via UTMs (mesmo critério de produção).
    src = (record.utm_source or '').strip().lower()
    med = (record.utm_medium or '').strip().lower()
    cnt = (record.utm_content or '').strip().lower()
    utms = {
        'utm_source':   src if src else '',
        'utm_medium':   med if med else '',
        'utm_campaign': record.utm_campaign or '',
        'utm_content':  cnt if cnt else '',
        'utm_term':     record.utm_term or '',
    }
    matched = ab_cfg.match_variant(utms, event_source_url=record.utm_url or '')
    if matched is None:
        return champion_name
    name = next((n for n, v in ab_cfg.variants.items() if v is matched), None)
    return name or champion_name


# ──────────────────────────────────────────────────────────────────────────
# Aggregation
# ──────────────────────────────────────────────────────────────────────────

def _utm_key(record, level_col: str) -> str:
    """Pega o valor do UTM no nível pedido. Normaliza vazios pra 'sem_utm'.

    Hoje só o nível 'ad' (= utm_content). source/medium foram removidos: na conta
    do DevClub adset é sempre "ABERTO" e campaign ≈ variante (já no split A/B), e
    source/medium não interessam. O ad é o único com sinal de criativo.
    """
    raw = {
        'ad': record.utm_content,
    }[level_col]
    val = (raw or '').strip().lower()
    return val if val else 'sem_utm'


def _aggregate(records, level_col: str, ab_cfg,
               champion_name: str, challenger_name: str) -> Dict[str, Dict[str, dict]]:
    """Agrega por (UTM × variante). Consome `List[LeadRecord]`.

    Ignora records sem score ou decil — corresponde ao filtro
    `leadScore IS NOT NULL AND decil IS NOT NULL` da query SQL antiga.
    """
    buckets: Dict[str, Dict[str, dict]] = {}
    for r in records:
        if r.score is None or r.decil is None:
            continue
        key = _utm_key(r, level_col)
        variant = _classify_variant_from_record(
            r, ab_cfg, champion_name, challenger_name,
        )
        b = buckets.setdefault(key, {})
        v = b.setdefault(variant, {'n': 0, 'sum_decil': 0, 'n_d9_d10': 0})
        v['n'] += 1
        v['sum_decil'] += r.decil
        if r.decil >= 9:
            v['n_d9_d10'] += 1

    out: Dict[str, Dict[str, dict]] = {}
    for utm_val, variants in buckets.items():
        out[utm_val] = {}
        for var_name, v in variants.items():
            out[utm_val][var_name] = {
                'n': v['n'],
                'avg_decil':  v['sum_decil'] / v['n'] if v['n'] else None,
                'pct_d9_d10': (v['n_d9_d10'] / v['n'] * 100) if v['n'] else None,
            }
    return out


def _combined_avg_decil(ch: dict, cl: dict) -> Optional[float]:
    n_ch = (ch or {}).get('n', 0) or 0
    n_cl = (cl or {}).get('n', 0) or 0
    n_total = n_ch + n_cl
    if n_total == 0:
        return None
    sum_ch = ((ch or {}).get('avg_decil') or 0) * n_ch
    sum_cl = ((cl or {}).get('avg_decil') or 0) * n_cl
    return (sum_ch + sum_cl) / n_total


# ──────────────────────────────────────────────────────────────────────────
# LF window resolution
# ──────────────────────────────────────────────────────────────────────────

def _resolve_lf_window(anchor_utc: Optional[datetime] = None) -> Tuple[Optional[str], Optional[datetime], Optional[datetime], bool]:
    """
    Retorna (lf_label, start_utc, end_utc, is_active), resolvido relativo a
    `anchor_utc` (default = agora).

    Permite snapshot point-in-time: ao olhar um dia passado, o LF e seu
    acumulado são recortados até aquele dia (`end = min(cap_end, âncora)` e a
    detecção ativo/encerrado usa a data da âncora), sem vazar dados futuros.

    - LF ativo na âncora (cap_start ≤ data_âncora ≤ cap_end): janela =
      [cap_start 00:00 BRT, min(cap_end 23:59 BRT, âncora)].
    - Senão: fallback no LF mais recente encerrado (ce < data_âncora BRT).
    - Sem nenhum: (None, None, None, False).
    """
    from src.core.launches import resolve_active_launch_brt, load_launches

    ref_utc = anchor_utc or datetime.now(timezone.utc)
    ref_date = ref_utc.astimezone(BRT).date()
    active = resolve_active_launch_brt(today=ref_date)
    if active is not None:
        start = datetime(active.cap_start.year, active.cap_start.month, active.cap_start.day,
                         0, 0, 0, tzinfo=BRT).astimezone(timezone.utc)
        end_brt = datetime(active.cap_end.year, active.cap_end.month, active.cap_end.day,
                           23, 59, 59, tzinfo=BRT)
        end = min(end_brt.astimezone(timezone.utc), ref_utc)
        return (active.name, start, end, True)

    launches = load_launches()
    candidates = []
    for name, cfg in launches.items():
        try:
            cs = datetime.strptime(cfg.get('cap_start', ''), '%Y-%m-%d').date()
            ce = datetime.strptime(cfg.get('cap_end', ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        if ce < ref_date:
            candidates.append((ce, name, cs, ce))
    if not candidates:
        return (None, None, None, False)
    candidates.sort(reverse=True)
    _, name, cs, ce = candidates[0]
    start = datetime(cs.year, cs.month, cs.day, 0, 0, 0,
                     tzinfo=BRT).astimezone(timezone.utc)
    end = datetime(ce.year, ce.month, ce.day, 23, 59, 59,
                   tzinfo=BRT).astimezone(timezone.utc)
    return (name, start, end, False)


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class UtmQualityResult:
    window: dict     # janela pedida: {start, end, label, n_total}
    window_lf: dict  # contexto do lançamento (LF): {label, start, end, is_active, n_total}
    champion_name: str
    challenger_name: str
    ranking: dict    # {split_mode, ranked, worst, best, total_distinct_creatives, qualifying}
    min_volume: int = 20  # N mínimo de leads na janela pra um criativo aparecer
    challenger_run_id: Optional[str] = None  # run_id do Challenger (p/ casar a barra TOP5)


def compute_utm_quality(
    repo,
    *,
    start_utc: datetime,
    end_utc: datetime,
    client_id: str = 'devclub',
    top_n: int = 5,
    min_volume: int = 20,
) -> UtmQualityResult:
    """
    Args:
        repo:       `LeadRepository` injetado pelo caller (endpoint /monitoring/utm-quality
                    em app.py compõe via compose_repository).
        start_utc:  início da janela (obrigatório). end_utc: fim. Um dia/intervalo
                    específico (até 90d, validado no endpoint) — o ranking usa essa
                    janela e o LF é recortado até `end_utc`.
        client_id:  id do cliente (carrega `configs/active_models/{id}.yaml`).
        top_n:      tamanho do Top piores e Top melhores.
        min_volume: N mínimo de leads (na janela) para entrar no ranking.

    Os decis já estão pré-computados no ledger (`registros_ml`); aqui só lemos os
    leads da janela e agregamos por UTM — nenhum scoring de modelo roda.

    Migrado em 2026-05-24 (Etapa 6 do refator do monitoramento). Antes abria
    conexão Railway própria e fazia JOIN entre `Lead × leads_capi` (ambas
    mortas desde 17/05). Agora consome `LeadRecord`s via repositório.
    """
    from src.core.client_config import ABTestConfig

    yaml_path = f'configs/active_models/{client_id}.yaml'
    ab_cfg = ABTestConfig.from_active_model_yaml(yaml_path)
    if not ab_cfg.enabled:
        raise RuntimeError(f'A/B test not enabled in {yaml_path}')

    variant_names = list(ab_cfg.variants.keys())
    champion_name = next(
        (n for n in variant_names if 'champion' in n.lower()),
        variant_names[0] if variant_names else 'champion',
    )
    challenger_name = next(
        (n for n in variant_names if 'challenger' in n.lower()),
        variant_names[1] if len(variant_names) > 1 else 'challenger',
    )
    _cv = ab_cfg.variants.get(challenger_name)
    challenger_run_id = getattr(_cv, 'run_id', None)

    win_start, win_end, anchor = start_utc, end_utc, end_utc
    _s_brt, _e_brt = start_utc.astimezone(BRT), end_utc.astimezone(BRT)
    if _s_brt.date() == _e_brt.date():
        win_label = _s_brt.strftime('%d/%m')
    else:
        win_label = f"{_s_brt.strftime('%d/%m')} a {_e_brt.strftime('%d/%m')}"

    lf_label, lf_start, lf_end, lf_is_active = _resolve_lf_window(anchor)

    records_win = repo.leads_in_range(win_start, win_end)
    records_lf = repo.leads_in_range(lf_start, lf_end) if lf_start else []

    # Hint de origem por content — pra rotular criativos sem nome (utm_content
    # numérico cru, ex: ID de anúncio do Google Ads/Demand Gen ou Meta não
    # nomeado). Guarda a origem dominante de cada content nas últimas 24h.
    _content_src: Dict[str, Dict[str, int]] = {}
    for rec in records_win:
        if rec.score is None or rec.decil is None:
            continue
        ck = _utm_key(rec, 'ad')
        sv = (rec.utm_source or '').strip().lower() or 'sem_source'
        _content_src.setdefault(ck, {})
        _content_src[ck][sv] = _content_src[ck].get(sv, 0) + 1
    content_source_hint: Dict[str, str] = {
        ck: max(counts, key=counts.get) for ck, counts in _content_src.items()
    }

    agg_win = _aggregate(records_win, 'ad', ab_cfg, champion_name, challenger_name)
    agg_lf  = _aggregate(records_lf,  'ad', ab_cfg, champion_name, challenger_name)

    all_creatives = set(agg_win.keys()) | set(agg_lf.keys())
    entries: List[dict] = []
    for utm in all_creatives:
        ch_win = agg_win.get(utm, {}).get(champion_name)
        cl_win = agg_win.get(utm, {}).get(challenger_name)
        ch_lf  = agg_lf.get(utm, {}).get(champion_name)
        cl_lf  = agg_lf.get(utm, {}).get(challenger_name)

        n_win = ((ch_win or {}).get('n') or 0) + ((cl_win or {}).get('n') or 0)
        n_lf  = ((ch_lf  or {}).get('n') or 0) + ((cl_lf  or {}).get('n') or 0)
        avg_combined = _combined_avg_decil(ch_win or {}, cl_win or {})

        entries.append({
            'utm': utm,
            'n': n_win,
            'n_lf': n_lf,
            'avg_decil_combined': avg_combined,
            'champion': ch_win,
            'challenger': cl_win,
            'champion_lf': ch_lf,
            'challenger_lf': cl_lf,
            'source_hint': content_source_hint.get(utm),
        })

    qualifying = [e for e in entries
                  if e['n'] >= min_volume
                  and e['avg_decil_combined'] is not None]
    qualifying.sort(key=lambda e: e['avg_decil_combined'])  # pior → melhor

    # Split só faz sentido quando há criativos suficientes pra "piores" e
    # "melhores" serem conjuntos disjuntos. Com poucos (≤ 2×top_n) o split
    # sobrepõe — então expõe uma lista única ranqueada.
    n_qual = len(qualifying)
    if n_qual <= 2 * top_n:
        split_mode = 'single'
        ranked = qualifying            # pior → melhor, sem corte
        worst, best = [], []
    else:
        split_mode = 'extremes'
        ranked = qualifying
        worst = qualifying[:top_n]
        best = list(reversed(qualifying[-top_n:]))

    ranking = {
        'split_mode': split_mode,
        'ranked': ranked,
        'worst': worst,
        'best':  best,
        'total_distinct_creatives': len(entries),
        'qualifying': n_qual,
    }

    return UtmQualityResult(
        window={
            'start': win_start.isoformat(),
            'end': win_end.isoformat(),
            'label': win_label,
            'n_total': len(records_win),
        },
        window_lf={
            'label': lf_label,
            'start': lf_start.isoformat() if lf_start else None,
            'end':   lf_end.isoformat()   if lf_end   else None,
            'is_active': lf_is_active,
            'n_total': len(records_lf),
        },
        champion_name=champion_name,
        challenger_name=challenger_name,
        ranking=ranking,
        min_volume=min_volume,
        challenger_run_id=challenger_run_id,
    )


# ──────────────────────────────────────────────────────────────────────────
# Comparação vs barra TOP5 ROAS (régua única Challenger, via scores_historicos)
# ──────────────────────────────────────────────────────────────────────────

def _load_top5_baseline(client_id: str = 'devclub') -> Optional[dict]:
    """Lê a barra TOP5 ROAS de configs/reference_audience_profiles/{id}_quality_signal.json.

    Devolve {pct_d9_d10 (em %), avg_decil, decil_std, run_id, pool_label,
    generated_at} ou None. O pct vem do baseline como fração (0-1) e é convertido
    pra % aqui; avg_decil/decil_std (nota-alvo na régua Challenger) vêm direto.
    """
    from pathlib import Path
    candidates = [
        Path(f'configs/reference_audience_profiles/{client_id}_quality_signal.json'),
        Path(__file__).resolve().parents[2] / 'configs' / 'reference_audience_profiles'
        / f'{client_id}_quality_signal.json',
    ]
    for c in candidates:
        try:
            if not c.exists():
                continue
            with open(c) as f:
                d = json.load(f)
            m = d.get('metrics', {})
            pct = m.get('pct_d9_d10')
            return {
                'pct_d9_d10': float(pct) * 100 if pct is not None else None,
                'avg_decil': m.get('avg_decil'),
                'decil_std': m.get('decil_std'),
                'run_id': d.get('model', {}).get('run_id'),
                'pool_label': d.get('reference_pool', {}).get('label', 'Top5 ROAS'),
                'generated_at': d.get('generated_at'),
            }
        except Exception as e:
            logger.warning('[top5_baseline] erro ao ler %s: %s', c, e)
    return None


def build_top5_comparison(
    *,
    lf_name: Optional[str],
    challenger_run_id: Optional[str],
    win_start,
    win_end,
    client_id: str = 'devclub',
    min_n: int = 100,
    conn=None,
) -> Optional[dict]:
    """Monta a comparação por criativo e por campanha vs a barra TOP5 ROAS.

    Régua única do Challenger (lê decil_challenger da scores_historicos via
    challenger_quality_by_utm). Para cada UTM com N ≥ min_n, deriva o Δpp vs a
    barra e classifica acima/abaixo SÓ quando o Δ supera ~2 erros-padrão (senão
    'neutro' — evita falso-alarme de amostra pequena).

    Guard de run_id: a barra e o decil gravado têm que ser do MESMO modelo;
    se divergirem, suprime (régua diferente). Degrada pra None (seção omitida)
    em qualquer indisponibilidade — nunca quebra o relatório.
    """
    import math

    baseline = _load_top5_baseline(client_id)
    if not baseline or baseline.get('pct_d9_d10') is None:
        logger.info('[top5] baseline indisponível — seção vs-TOP5 omitida.')
        return None
    bar = baseline['pct_d9_d10']
    bar_decil = baseline.get('avg_decil')
    decil_std = baseline.get('decil_std')

    if (baseline.get('run_id') and challenger_run_id
            and baseline['run_id'] != challenger_run_id):
        logger.warning(
            '[top5] suprimido: baseline run_id %s ≠ challenger ativo %s — régua '
            'diferente, regenerar baseline.', baseline['run_id'], challenger_run_id)
        return None

    from src.data.scores_historicos import challenger_quality_by_utm, _cloudsql_conn

    own = conn is None
    if own:
        try:
            conn = _cloudsql_conn()
        except Exception as e:
            logger.warning('[top5] conexão Cloud SQL falhou: %s', e)
            return None

    def _enrich(rows):
        shown, hidden = [], 0
        for e in rows:
            if e['n'] < min_n:
                hidden += 1
                continue
            # Significância na proporção D9-D10 (mantida p/ JSON/compat)
            p = e['pct_d9_d10'] / 100.0
            se_pp = math.sqrt(max(p * (1 - p), 0.0) / e['n']) * 100 if e['n'] else None
            delta = e['pct_d9_d10'] - bar
            if se_pp is not None and abs(delta) > 2 * se_pp:
                status = 'acima' if delta > 0 else 'abaixo'
            else:
                status = 'neutro'
            # Significância na NOTA (média de decil) — usada pela cor do relatório.
            # SE pela std do pool TOP5 (aprox.); 2·SE = mesma régua de ruído do pct.
            delta_decil = se_decil = status_decil = None
            if bar_decil is not None and e.get('avg_decil') is not None:
                delta_decil = e['avg_decil'] - bar_decil
                if decil_std and e['n']:
                    se_decil = decil_std / math.sqrt(e['n'])
                if se_decil is not None and abs(delta_decil) > 2 * se_decil:
                    status_decil = 'acima' if delta_decil > 0 else 'abaixo'
                else:
                    status_decil = 'neutro'
            shown.append({
                **e,
                'delta_pp': round(delta, 1),
                'se_pp': round(se_pp, 1) if se_pp is not None else None,
                'status': status,
                'delta_decil': round(delta_decil, 2) if delta_decil is not None else None,
                'se_decil': round(se_decil, 2) if se_decil is not None else None,
                'status_decil': status_decil,
            })
        return shown, hidden

    try:
        out = {
            'bar_pct': round(bar, 1),
            'bar_decil': bar_decil,
            'pool_label': baseline['pool_label'],
            'generated_at': baseline.get('generated_at'),
            'min_n': min_n,
            'levels': {},
        }
        for level in ('creative', 'campaign'):
            rows = challenger_quality_by_utm(
                lf_name, level=level, challenger_run_id=challenger_run_id,
                win_start=win_start, win_end=win_end, conn=conn,
            )
            shown, hidden = _enrich(rows)
            out['levels'][level] = {'rows': shown, 'hidden_below_min_n': hidden}
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass

    if not any(out['levels'][lv]['rows'] for lv in out['levels']):
        return None
    return out


# ──────────────────────────────────────────────────────────────────────────
# Slack renderer — só criativo (ad), mini-tabela alinhada
# ──────────────────────────────────────────────────────────────────────────

def _combine(ch: Optional[dict], cl: Optional[dict], key: str) -> Optional[float]:
    """Média ponderada por n de `key` entre Champion e Challenger."""
    ch = ch or {}
    cl = cl or {}
    n_ch = ch.get('n', 0) or 0
    n_cl = cl.get('n', 0) or 0
    n = n_ch + n_cl
    if n == 0:
        return None
    return ((ch.get(key) or 0) * n_ch + (cl.get(key) or 0) * n_cl) / n


def _challenger_note(entry: dict) -> Optional[str]:
    """Linha de Challenger só quando tem ≥10 leads na janela (em criativo ~nunca)."""
    cl = entry.get('challenger') or {}
    if (cl.get('n') or 0) < 10:
        return None
    d = cl.get('avg_decil')
    p = cl.get('pct_d9_d10')
    d_s = f"{d:.1f}" if d is not None else "–"
    p_s = f"{p:.0f}%" if p is not None else "–"
    return f"_Challenger: decil {d_s} · {p_s} em D9–D10 · {cl.get('n')} leads_"


_BARE_ID_RE = re.compile(r'^\d{8,}$')


def _display_creative(entry: dict) -> str:
    """Nome exibido do criativo no ranking.

    Quando o `utm_content` é um ID numérico cru — criativo que o gestor não
    nomeou (comum no Google Ads/Demand Gen, às vezes no Meta) — troca o número
    solto por um rótulo legível com a origem dominante. Source-aware: não assume
    Google, mostra a plataforma real (`google-ads`, `fb`, etc.).
    """
    v = (entry.get('utm') or '').strip()
    if _BARE_ID_RE.match(v):
        src = (entry.get('source_hint') or '').strip()
        prefix = f"{src} · " if src and src != 'sem_source' else ''
        return f"{prefix}criativo sem nome (ID {v})"
    return entry.get('utm', '')


_CAMP_AUDIENCE = ('FRIO', 'QUENTE', 'MORNO')
_DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')


def _short_campaign_name(utm: str) -> str:
    """Encurta a UTM de campanha (pipe-delimitada, longona) pro essencial:
    público + data + tag de optimization_goal. Ex.:
    'DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-26 | LEADHQLB|120244...'
    → 'FRIO · 2026-05-26 · LEADHQLB'. Sem tag legível, desambígua pelo fim do ID.
    A UTM completa continua no endpoint JSON; aqui é só leitura no Slack.

    A tag é o token 'LEAD…' imediatamente antes do ID numérico (LEADQUALIFIED =
    Champion, LEADHQLB = Challenger, ver campaign_classifier); o 'LEAD' solto da
    taxonomia da campanha é ignorado de propósito."""
    raw = (utm or '').strip()
    if not raw:
        return 'sem_utm'
    if '{{' in raw:
        return 'macro não resolvido'
    if _BARE_ID_RE.match(raw):
        return f"campanha sem nome (#{raw[-6:]})"
    parts = [p.strip() for p in raw.split('|') if p.strip()]
    if len(parts) <= 2:
        return raw  # já curta (ex.: 'devlf')
    aud = next((p.upper() for p in parts if p.upper() in _CAMP_AUDIENCE), None)
    date = next((m.group(0) for p in parts for m in [_DATE_RE.search(p)] if m), None)
    tag = None
    if re.fullmatch(r'\d+', parts[-1]) and len(parts) >= 2:
        cand = re.sub(r'[^A-Za-z]', '', parts[-2]).upper()
        if re.fullmatch(r'LEAD[A-Z]+', cand) and cand != 'LEAD':
            tag = cand
    idtail = None
    if not tag:
        m = re.search(r'(\d{6,})\D*$', raw)
        idtail = f"#{m.group(1)[-6:]}" if m else None
    bits = [b for b in (aud, date, tag or idtail) if b]
    return ' · '.join(bits) if bits else raw


def _mini_table_block(entry: dict, lf_label: str, marker: str, win_row_label: str = 'janela') -> dict:
    """Section mrkdwn: nome + mini-tabela monoespaçada (janela vs LF).

    `win_row_label` rotula a 1ª linha com a data/intervalo (ex: '12/06', '12/06–13/06').
    """
    d_win = _combine(entry.get('champion'), entry.get('challenger'), 'avg_decil')
    p_win = _combine(entry.get('champion'), entry.get('challenger'), 'pct_d9_d10')
    dlf = _combine(entry.get('champion_lf'), entry.get('challenger_lf'), 'avg_decil')
    plf = _combine(entry.get('champion_lf'), entry.get('challenger_lf'), 'pct_d9_d10')

    def fd(v): return f"{v:.1f}" if v is not None else "–"
    def fp(v): return f"{v:.0f}%" if v is not None else "–"

    table = (
        "```\n"
        f"{'':<15}média de decil   %D9, D10   leads\n"
        f"{win_row_label[:14]:<15}{fd(d_win):<16} {fp(p_win):<10} {entry['n']}\n"
        f"{'Lançamento':<15}{fd(dlf):<16} {fp(plf):<10} {entry['n_lf']}\n"
        "```"
    )
    text = f"{marker} *{_display_creative(entry)}*\n{table}"
    note = _challenger_note(entry)
    if note:
        text += f"\n{note}"
    return {'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}


_TOP5_MARK = {'acima': '🟢', 'abaixo': '🔴', 'neutro': '⚪'}
_TOP5_LEVEL_LABEL = {'creative': 'Criativos', 'campaign': 'Campanhas'}


def _top5_line(e: dict, level: str) -> str:
    """Linha alinhada (code block): status, %D9-D10, Δ vs barra, n, nome. O nome
    vai no FIM pra os números ficarem sempre alinhados (nome é o campo variável,
    e nomes de campanha compartilham prefixo — alinhar pelo nome quebraria)."""
    mark = _TOP5_MARK.get(e['status'], '⚪')
    if e['status'] == 'neutro':
        delta = '~padrão'
    else:
        sign = '+' if e['delta_pp'] >= 0 else ''
        delta = f"{sign}{e['delta_pp']:.0f}pp"
    name = _display_creative(e) if level == 'creative' else _short_campaign_name(e.get('utm') or '')
    return f"{mark} {e['pct_d9_d10']:>3.0f}% D9-D10  {delta:>8}  n={e['n']:<6} {name}"


def _render_unified_top5(top5: dict, lf_label: str, lf_state: str, nlf: int) -> List[dict]:
    """Lista única por criativo (e por campanha) com o vs-TOP5 embutido — leitura
    ABSOLUTA na régua do Challenger. Sem mini-tabela, sem seção à parte. Ordenada
    por %D9-D10 (melhor → pior)."""
    bar = top5['bar_pct']
    pool = top5.get('pool_label') or 'Top5 ROAS'
    gen = (top5.get('generated_at') or '')[:10] or '?'
    min_n = top5.get('min_n')
    blocks: List[dict] = [{'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': (
        f"*{nlf}* leads no {lf_label} ({lf_state}). Barra TOP5 = *{bar:.0f}%* em "
        f"D9–D10 — qualidade *prevista* pelo Challenger das audiências dos melhores "
        f"lançamentos ({pool}, de {gen}); não é conversão real. "
        f"🟢 acima · 🔴 abaixo · ⚪ dentro do ruído · só N ≥ {min_n}."
    )}]}]
    CAP = 25
    for level in ('creative', 'campaign'):
        lv = top5['levels'].get(level) or {}
        rows = lv.get('rows') or []
        if not rows:
            continue
        rows_sorted = sorted(rows, key=lambda e: e['pct_d9_d10'], reverse=True)
        extra = max(0, len(rows_sorted) - CAP)
        body = "\n".join(_top5_line(e, level) for e in rows_sorted[:CAP])
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn',
            'text': f"*{_TOP5_LEVEL_LABEL[level]}*\n```\n{body}\n```"}})
        notes = []
        if extra:
            notes.append(f"+{extra} não listados")
        if lv.get('hidden_below_min_n'):
            notes.append(f"{lv['hidden_below_min_n']} abaixo de N≥{min_n} ocultos")
        if notes:
            blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn',
                'text': '_' + ' · '.join(notes) + '_'}]})
    return blocks


def _twoline_entry(name: str, marker: str, ontem: Optional[dict], lf: Optional[dict],
                   win_label: str) -> str:
    """Bloco de 3 linhas pra um criativo/campanha: nome + linha da janela (ontem)
    + linha do lançamento, cada uma com a NOTA (média de decil na régua Challenger)
    e o volume. Linha sem volume mínimo vira '— sem N suficiente'."""
    def fmt(label: str, row: Optional[dict]) -> str:
        if not row or row.get('avg_decil') is None:
            return f"   {label:<11}— Poucos leads"
        return f"   {label:<11}nota {row['avg_decil']:>4.1f}   Leads={row['n']}"
    return "\n".join([f"{marker} {name}", fmt(win_label[:10], ontem), fmt('Lançamento', lf)])


def _render_twoline_top5(top5_window: Optional[dict], top5_lf: Optional[dict], *,
                         win_label: str, lf_label: str, lf_state: str,
                         n_win: int, nlf: int) -> List[dict]:
    """Por criativo/campanha, DUAS linhas — janela (ontem) e lançamento — cada uma
    com a NOTA (média de decil, régua Challenger). No topo, a nota-alvo dos TOP5.
    Cor pela nota do lançamento vs alvo. Ordenado pela nota do lançamento."""
    base = top5_lf or top5_window
    bar_decil = base.get('bar_decil')
    alvo = f"{bar_decil:.1f}" if bar_decil is not None else "—"
    blocks: List[dict] = [{'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': (
        f"Nota-alvo TOP5 = {alvo}"
    )}]}]
    CAP = 20

    def _key(e):  # ordena pela nota; cai pro pct se nota ausente
        return (e.get('avg_decil') if e.get('avg_decil') is not None else e.get('pct_d9_d10', 0))
    for level in ('creative', 'campaign'):
        wmap = {e['utm']: e for e in (((top5_window or {}).get('levels', {}).get(level) or {}).get('rows') or [])}
        lrows = ((top5_lf or {}).get('levels', {}).get(level) or {}).get('rows') or []
        order = sorted(lrows, key=_key, reverse=True) if lrows else \
            sorted(wmap.values(), key=_key, reverse=True)
        if not order:
            continue
        lmap = {e['utm']: e for e in lrows}
        extra = max(0, len(order) - CAP)
        entries = []
        for e in order[:CAP]:
            utm = e['utm']
            name = _display_creative(e) if level == 'creative' else _short_campaign_name(utm)
            ref = lmap.get(utm) or e
            marker = _TOP5_MARK.get(ref.get('status_decil') or ref.get('status'), '⚪')
            entries.append(_twoline_entry(name, marker, wmap.get(utm), lmap.get(utm), win_label))
        body = "\n".join(entries)
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn',
            'text': f"*{_TOP5_LEVEL_LABEL[level]}*\n```\n{body}\n```"}})
        if extra:
            blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn',
                'text': f"_+{extra} não listados_"}]})
    return blocks


def render_slack_blocks(r: UtmQualityResult, top5_lf: Optional[dict] = None,
                        top5_window: Optional[dict] = None) -> List[dict]:
    """Relatório de criativo.

    Caminho normal (há barra TOP5): por criativo e campanha, DUAS linhas — janela
    (ontem) e lançamento — cada uma com %D9-D10 na régua Challenger e Δ vs a barra
    TOP5. Caminho degradado (sem scores_historicos pro LF / run_id divergente):
    cai no ranking relativo da janela (mini-tabela), pra não ficar sem nada.
    """
    blocks: List[dict] = []
    lf_label = r.window_lf.get('label') or 'LF'
    lf_state = 'em captação' if r.window_lf.get('is_active') else 'encerrado'
    nlf = r.window_lf.get('n_total', 0)
    win_label = r.window.get('label') or 'janela'

    blocks.append({
        'type': 'header',
        'text': {'type': 'plain_text', 'text': f'Qualidade de Criativo — {lf_label}'},
    })

    if top5_lf or top5_window:
        blocks.extend(_render_twoline_top5(
            top5_window, top5_lf, win_label=win_label, lf_label=lf_label,
            lf_state=lf_state, n_win=r.window.get('n_total', 0), nlf=nlf))
        return blocks

    # ── Degradado: sem barra TOP5 (scores_historicos indisponível pro LF) ──
    n_win = r.window.get('n_total', 0)
    data = r.ranking
    qual = data.get('qualifying', 0)
    total = data.get('total_distinct_creatives', 0)
    split_mode = data.get('split_mode', 'single')
    min_vol = r.min_volume
    row_label = win_label

    blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': (
        f"_Comparação vs TOP5 indisponível pro {lf_label} — mostrando ranking "
        f"relativo da janela ({win_label})._"
    )}]})
    blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': (
        f"*{n_win}* leads em {win_label} · *{nlf}* no {lf_label} ({lf_state}) · "
        f"*{qual}* de {total} criativos com *N ≥ {min_vol}*"
    )}]})
    blocks.append({'type': 'divider'})

    if qual == 0:
        blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn',
            'text': f'_nenhum criativo com volume mínimo na janela ({win_label})._'}]})
        return blocks

    if split_mode == 'single':
        ranked = data.get('ranked') or []
        blocks.append({'type': 'section',
                       'text': {'type': 'mrkdwn', 'text': '*Ranking — pior → melhor*'}})
        for i, e in enumerate(ranked):
            marker = '🔴' if i == 0 else ('🟢' if i == len(ranked) - 1 else '⚪')
            blocks.append(_mini_table_block(e, lf_label, marker, row_label))
    else:
        worst = data.get('worst') or []
        best = data.get('best') or []
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '🔴 *Piores*'}})
        for e in worst:
            blocks.append(_mini_table_block(e, lf_label, '🔴', row_label))
        blocks.append({'type': 'divider'})
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '🟢 *Melhores*'}})
        for e in best:
            blocks.append(_mini_table_block(e, lf_label, '🟢', row_label))

    return blocks


# ──────────────────────────────────────────────────────────────────────────
# Slack dispatch
# ──────────────────────────────────────────────────────────────────────────

def post_to_slack(channel: str, blocks: List[dict], fallback_text: str) -> dict:
    """Posta via chat.postMessage. Retorna {ok, channel, ts?, error?}."""
    token = os.environ.get('SLACK_BOT_TOKEN')
    if not token:
        return {'ok': False, 'channel': channel, 'error': 'SLACK_BOT_TOKEN missing'}
    import urllib.request
    body = json.dumps({
        'channel': channel,
        'blocks': blocks,
        'text': fallback_text,
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://slack.com/api/chat.postMessage',
        data=body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Authorization': f'Bearer {token}',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.load(r)
        if not resp.get('ok'):
            return {'ok': False, 'channel': channel, 'error': resp.get('error')}
        return {'ok': True, 'channel': channel, 'ts': resp.get('ts')}
    except Exception as e:
        return {'ok': False, 'channel': channel, 'error': str(e)}
