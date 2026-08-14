"""Recupera leads cujo nome de campanha chegou CORTADO em 100 caracteres.

CONTEXTO (11/08/2026). O backend do cliente corta o campo de campanha em 100
caracteres no momento em que publica o lead na nossa fila. Como as etiquetas de
roteamento do A/B (ABR_28_TOP30, JUL_24_TOP30, JUL_24_TOP50, LEADHQLB) ficam no
FINAL do nome, elas morrem no corte. Sem etiqueta, `match_variant` não casa
variante nenhuma, o lead cai no pega-tudo e os eventos do modelo nunca saem.

O nome INTEIRO existe: a tabela `UTMTracking` do Railway (banco do cliente)
guarda o valor completo, 132 caracteres, com etiqueta e id da campanha. Este
script cruza as duas pontas pelo email e desfaz o estrago:

    PARTE A  grava a `variant` correta no nosso ledger (`registros_ml`).
             Não fala com o Meta. Devolve a medição do A/B nesses leads.

    PARTE B  dispara os eventos de qualidade que deveriam ter saído na hora,
             pelo MESMO caminho da produção (`send_batch_events`), com o
             carimbo de tempo da captura original.

NÃO reescora nada: os dois modelos já pontuaram esses leads no dia, os decis
estão gravados. O que faltou foi só o roteamento saber para quem mandar.

DEDUPLICAÇÃO. O envio reusa o `event_id` que o lead já tem no ledger. O Meta
deduplica por (pixel, nome do evento, event_id), então rodar a Parte B duas
vezes não duplica evento. É a rede de segurança contra dedo errado.

PRAZO. O Meta recusa evento com data de mais de 7 dias. Por isso a janela
default é de 7 dias e o script recusa lead fora dela.

Uso:
    # relatório, não escreve nem envia nada
    python -m scripts.recuperar_leads_cortados

    # Parte A de verdade
    python -m scripts.recuperar_leads_cortados --parte A --executar

    # Parte B em ensaio (mostra o que sairia) e depois de verdade
    python -m scripts.recuperar_leads_cortados --parte B
    python -m scripts.recuperar_leads_cortados --parte B --executar
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import ssl
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

logger = logging.getLogger("recuperar_leads_cortados")

# O Meta recusa evento com data anterior a este limite.
LIMITE_META_DIAS = 7

# Corte que o backend do cliente aplica. Lead com exatamente este tamanho é
# candidato a ter sido decapitado.
TAMANHO_DO_CORTE = 100


# ─────────────────────────────────────────────────────────────────────────────
# Conexões
# ─────────────────────────────────────────────────────────────────────────────

def _abrir_ledger():
    """Cloud SQL `ledger` (nosso). Timeout largo: as consultas aqui são pesadas
    e o helper de produção fixa 30s, que estoura em janela de vários dias."""
    import pg8000.native

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"],
        port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"],
        ssl_context=ctx,
        timeout=300,
    )


def _abrir_railway():
    """Railway (banco do cliente) — só leitura da `UTMTracking`, que é a única
    ponta do sistema onde o nome completo da campanha sobreviveu."""
    import pg8000.native

    return pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ["RAILWAY_DB_PORT"]),
        database=os.environ["RAILWAY_DB_NAME"],
        user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"],
        timeout=300,
    )


def _linhas(conn, sql: str, **params) -> List[Dict[str, Any]]:
    rows = conn.run(sql, **params)
    cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Leitura das duas pontas
# ─────────────────────────────────────────────────────────────────────────────

def carregar_cortados(conn, dias: int) -> List[Dict[str, Any]]:
    """Leads do nosso ledger cujo nome de campanha chegou no tamanho exato do
    corte. Traz tudo que o envio CAPI precisa, para não voltar ao banco depois."""
    return _linhas(conn, f"""
        SELECT event_id, lower(trim(email)) AS email, email AS email_original,
               created_at, variant, utm_campaign, utm_url,
               first_name, last_name, phone, fbp, fbc, user_agent, ip,
               survey_responses,
               score_champion, score_challenger,
               decil_champion, decil_challenger,
               champion_run_id, challenger_run_id
        FROM registros_ml
        WHERE created_at >= (now() AT TIME ZONE 'UTC') - interval '{int(dias)} days'
          AND length(utm_campaign) = {TAMANHO_DO_CORTE}
        ORDER BY created_at
    """)


def carregar_nomes_completos(conn, dias: int) -> Dict[str, List[Dict[str, Any]]]:
    """Nomes de campanha inteiros do banco do cliente, agrupados por email.

    Margem de 2 dias na janela porque o registro de UTM acontece na visita e a
    resposta da pesquisa pode vir bem depois."""
    linhas = _linhas(conn, """
        SELECT lower(trim("clientEmail")) AS email, campaign AS nome_completo, "trackedAt"
        FROM "UTMTracking"
        WHERE "trackedAt" >= now() - interval '%d days'
          AND campaign IS NOT NULL
        ORDER BY "trackedAt"
    """ % (int(dias) + 2))
    por_email: Dict[str, List[Dict[str, Any]]] = {}
    for l in linhas:
        por_email.setdefault(l["email"], []).append(l)
    return por_email


def casar_nome_completo(lead: Dict, candidatos: List[Dict]) -> Optional[str]:
    """Devolve o nome inteiro da campanha do lead, ou None.

    CONTROLE DE INTEGRIDADE, e é o que faz este script ser confiável: o nome
    completo tem que COMEÇAR exatamente com o pedaço que chegou cortado. Se não
    começar, é outra campanha da mesma pessoa (quem visita duas vezes tem duas
    linhas de UTM) e casar seria inventar roteamento. Entre os que passam no
    teste, vence o registrado mais perto da captura."""
    cortado = lead["utm_campaign"] or ""
    validos = [c for c in candidatos if (c["nome_completo"] or "").startswith(cortado)]
    if not validos:
        return None
    # As duas pontas gravam UTC sem fuso declarado (conferido: o último
    # `trackedAt` bate com o now() UTC do servidor). Carimbo o fuso nas duas
    # para poder subtrair.
    captura = lead["created_at"].replace(tzinfo=timezone.utc)
    validos.sort(key=lambda c: abs(
        (c["trackedAt"].replace(tzinfo=timezone.utc) - captura).total_seconds()))
    return validos[0]["nome_completo"]


# ─────────────────────────────────────────────────────────────────────────────
# Roteamento e decil — os dois pelo caminho da produção
# ─────────────────────────────────────────────────────────────────────────────

def carregar_configs(cliente: str):
    from src.core.client_config import ABTestConfig, ClientConfig

    cfg = ClientConfig.from_yaml(str(_RAIZ / "configs" / "clients" / f"{cliente}.yaml"))
    ab = ABTestConfig.from_active_model_yaml(
        str(_RAIZ / "configs" / "active_models" / f"{cliente}.yaml")
    )
    return cfg, ab


def decil_e_score(lead: Dict, run_id: str):
    """Decil e score do modelo pedido, resolvidos por identificador de execução.

    Ler `decil_champion` direto seria errado: o papel de cada modelo muda com o
    tempo (o abr_28 já foi challenger), então a mesma coluna guarda modelos
    diferentes em dias diferentes."""
    if lead.get("champion_run_id") == run_id:
        return lead.get("decil_champion"), lead.get("score_champion")
    if lead.get("challenger_run_id") == run_id:
        return lead.get("decil_challenger"), lead.get("score_challenger")
    return None, None


def preparar(leads: List[Dict], nomes: Dict[str, List[Dict]], ab_config) -> Dict[str, list]:
    """Cruza, resolve variante e decil, e separa em baldes explicáveis."""
    recuperados, sem_etiqueta, sem_casamento, sem_decil = [], [], [], []

    for lead in leads:
        completo = casar_nome_completo(lead, nomes.get(lead["email"], []))
        if completo is None:
            sem_casamento.append(lead)
            continue

        variante = ab_config.match_variant(
            {"utm_campaign": completo}, event_source_url=lead.get("utm_url")
        )
        if variante is None:
            sem_etiqueta.append(lead)
            continue

        nome_variante = next(
            (n for n, v in ab_config.variants.items() if v is variante), None
        )
        decil, score = decil_e_score(lead, variante.run_id)
        if decil is None:
            # O modelo da campanha não pontuou este lead (entrou em produção
            # depois dele). Sem decil não há evento honesto a mandar.
            sem_decil.append(lead)
            continue

        recuperados.append({
            **lead,
            "nome_completo": completo,
            "variante": variante,
            "nome_variante": nome_variante,
            "decil_num": int(decil),
            "decil_str": f"D{int(decil):02d}",
            "score": float(score) if score is not None else 0.0,
        })

    return {
        "recuperados": recuperados,
        "sem_etiqueta": sem_etiqueta,
        "sem_casamento": sem_casamento,
        "sem_decil": sem_decil,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PARTE A — gravar a variante no ledger
# ─────────────────────────────────────────────────────────────────────────────

def parte_a(conn, recuperados: List[Dict], executar: bool, restaurar_utm: bool) -> Dict:
    # Idempotência: só entra quem ainda tem algo desatualizado. Com
    # `--restaurar-utm` o nome cortado também conta, senão uma segunda passada
    # (variante já gravada na primeira) não restauraria nome nenhum.
    def pendente(r: Dict) -> bool:
        if r["variant"] != r["nome_variante"]:
            return True
        return restaurar_utm and r["utm_campaign"] != r["nome_completo"]

    a_gravar = [r for r in recuperados if pendente(r)]
    print(f"\n=== PARTE A — variante no ledger ===")
    print(f"leads a corrigir: {len(a_gravar)} de {len(recuperados)}")
    for nome in sorted({r["nome_variante"] for r in a_gravar}):
        n = sum(1 for r in a_gravar if r["nome_variante"] == nome)
        print(f"  {nome:24s} {n:3d}")
    if restaurar_utm:
        print("  (+ restaurando o nome completo da campanha em utm_campaign)")

    if not executar:
        print("  ENSAIO — nada foi gravado. Use --executar.")
        return {"gravados": 0, "a_gravar": len(a_gravar)}

    gravados = 0
    for r in a_gravar:
        if restaurar_utm:
            conn.run(
                "UPDATE registros_ml SET variant = :v, utm_campaign = :c "
                "WHERE event_id = :e",
                v=r["nome_variante"], c=r["nome_completo"], e=r["event_id"],
            )
        else:
            conn.run(
                "UPDATE registros_ml SET variant = :v WHERE event_id = :e",
                v=r["nome_variante"], e=r["event_id"],
            )
        gravados += 1
    print(f"  gravados: {gravados}")
    return {"gravados": gravados, "a_gravar": len(a_gravar)}


# ─────────────────────────────────────────────────────────────────────────────
# PARTE B — disparar os eventos que faltaram
# ─────────────────────────────────────────────────────────────────────────────

def _survey(valor) -> Optional[Dict]:
    if valor is None:
        return None
    if isinstance(valor, dict):
        return valor
    try:
        return json.loads(valor)
    except (TypeError, ValueError):
        return None


def montar_pacotes(recuperados: List[Dict]) -> List[Dict]:
    """Monta o dict por lead no formato que `send_batch_events` espera.

    Os campos `ab_*` são os mesmos que o app.py preenche quando o roteamento
    funciona — é por eles que a variante impõe pixel, nome de evento, faixa de
    decis e a lista de eventos secundários."""
    pacotes = []
    for r in recuperados:
        v = r["variante"]
        captura = r["created_at"].replace(tzinfo=timezone.utc)
        pacotes.append({
            "email": r["email_original"],
            "phone": r.get("phone"),
            "first_name": r.get("first_name"),
            "last_name": r.get("last_name"),
            "lead_score": r["score"],
            "decil": r["decil_str"],
            # Mesmo event_id do ledger: é o que faz o Meta deduplicar se este
            # script rodar duas vezes.
            "event_id": r["event_id"],
            "fbp": r.get("fbp"),
            "fbc": r.get("fbc"),
            "user_agent": r.get("user_agent"),
            "client_ip": r.get("ip"),
            "event_source_url": r.get("utm_url"),
            # Carimbo da captura ORIGINAL, não de agora.
            "event_timestamp": int(captura.timestamp()),
            "survey_data": _survey(r.get("survey_responses")),
            "ab_event_name": v.capi_event_name,
            "ab_event_name_hq": v.capi_event_name_high_quality,
            "ab_conversion_rates": v.conversion_rates,
            "ab_pixel_id": v.pixel_id_override,
            "ab_high_quality_decils": v.capi_high_quality_decils,
            "ab_variant_config": v,
            "ab_secondary_hq_events": v.capi_secondary_hq_events,
        })
    return pacotes


def prever_eventos(recuperados: List[Dict]) -> Dict[str, int]:
    """Conta quais eventos de qualidade vão sair, aplicando a faixa de decis de
    cada destino. Serve para o operador conferir ANTES de mandar."""
    contagem: Dict[str, int] = {}
    for r in recuperados:
        v, d = r["variante"], r["decil_str"]
        if d in (v.capi_high_quality_decils or []):
            chave = f"{v.capi_event_name_high_quality} @ {v.pixel_id_override}"
            contagem[chave] = contagem.get(chave, 0) + 1
        for dest in (v.capi_secondary_hq_events or []):
            if d in list(dest.decils):
                chave = f"{dest.event_name} @ {dest.pixel_id}"
                contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


def parte_b(recuperados: List[Dict], cfg, cliente: str, executar: bool) -> Dict:
    from api.capi_integration import send_batch_events

    print(f"\n=== PARTE B — eventos retroativos no Meta ===")
    print(f"leads: {len(recuperados)}")
    previsao = prever_eventos(recuperados)
    for chave in sorted(previsao):
        print(f"  {chave:42s} {previsao[chave]:3d}")
    print(f"  total de eventos de qualidade: {sum(previsao.values())}")
    print("  (+ 1 evento base por lead, que o Meta ignora por não estar cadastrado)")

    pacotes = montar_pacotes(recuperados)
    resultado = send_batch_events(
        pacotes,
        db=None,                     # a marcação no ledger é da Parte A, não daqui
        capi_config=cfg.capi,
        business_config=cfg.business,
        client_id=cliente,
        dry_run=not executar,
    )
    print(f"  {'ENVIADOS' if executar else 'ENSAIO'}: "
          f"{resultado['success']}/{resultado['total']} leads sem erro, "
          f"{resultado['errors']} com erro")
    return resultado


# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cliente", default="devclub")
    p.add_argument("--dias", type=int, default=LIMITE_META_DIAS,
                   help=f"janela de captura (máx {LIMITE_META_DIAS}, limite do Meta)")
    p.add_argument("--parte", choices=["A", "B", "AB", "nenhuma"], default="nenhuma",
                   help="A = variante no ledger; B = eventos no Meta; nenhuma = só relatório")
    p.add_argument("--executar", action="store_true",
                   help="sem esta flag tudo roda em ensaio")
    p.add_argument("--restaurar-utm", action="store_true",
                   help="na Parte A, também devolve o nome completo da campanha "
                        "(recupera o id da campanha para o relatório de gasto)")
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.dias > LIMITE_META_DIAS:
        print(f"[ERRO] --dias {args.dias} passa do limite de {LIMITE_META_DIAS} "
              f"dias do Meta. Evento mais velho que isso é recusado.")
        return 1

    from dotenv import load_dotenv
    load_dotenv(_RAIZ / ".env")

    cfg, ab_config = carregar_configs(args.cliente)

    led = _abrir_ledger()
    try:
        cortados = carregar_cortados(led, args.dias)
        print(f"leads com nome cortado em {TAMANHO_DO_CORTE} caracteres "
              f"({args.dias}d): {len(cortados)}")
        if not cortados:
            return 0

        rw = _abrir_railway()
        try:
            nomes = carregar_nomes_completos(rw, args.dias)
        finally:
            rw.close()
        print(f"emails com nome completo na UTMTracking: {len(nomes)}")

        baldes = preparar(cortados, nomes, ab_config)
        rec = baldes["recuperados"]
        print(f"\nrecuperados (etiqueta + decil): {len(rec)}")
        print(f"  sem casamento na UTMTracking : {len(baldes['sem_casamento'])}")
        print(f"  campanha sem etiqueta        : {len(baldes['sem_etiqueta'])}")
        print(f"  sem decil do modelo da campanha: {len(baldes['sem_decil'])}")
        if not rec:
            return 0

        mais_velho = min(r["created_at"] for r in rec).replace(tzinfo=timezone.utc)
        idade = datetime.now(timezone.utc) - mais_velho
        print(f"  captura mais antiga: {mais_velho:%d/%m %H:%M} UTC "
              f"({idade.days}d{idade.seconds // 3600}h atrás)")
        if idade > timedelta(days=LIMITE_META_DIAS):
            print(f"[ERRO] lead mais velho que {LIMITE_META_DIAS} dias — "
                  f"o Meta recusaria. Reduza --dias.")
            return 1

        if args.parte in ("A", "AB"):
            parte_a(led, rec, args.executar, args.restaurar_utm)
        if args.parte in ("B", "AB"):
            parte_b(rec, cfg, args.cliente, args.executar)
        if args.parte == "nenhuma":
            print("\n(relatório apenas — escolha --parte A, B ou AB)")
            parte_b_previsao = prever_eventos(rec)
            print("eventos que a Parte B mandaria:")
            for chave in sorted(parte_b_previsao):
                print(f"  {chave:42s} {parte_b_previsao[chave]:3d}")
    finally:
        led.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
