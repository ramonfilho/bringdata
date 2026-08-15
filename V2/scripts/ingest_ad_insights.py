"""Ingestão de insights POR ANÚNCIO da Meta — o grão do produto (passo 2).

Por que existe: o banco só tinha gasto por CAMPANHA (`ad_spend`/`meta_insights`),
e "o único grão que importa é o anúncio" (Ramon, 15/08): sem gasto por anúncio não
há CPL nem assertividade no grão criativo×campanha. A mesma resposta da API traz o
mapeamento nome↔ad_id, que mata o split de encoding (o mesmo criativo partido em
duas linhas por bytes diferentes do nome).

Escreve:
  analytics.ad_insights       1 linha por anúncio por dia (gasto, leads, imp, cliques)
  analytics.criativo_id_map   ad_id → último nome visto (derivada da própria carga)

Reuso: `MetaAdsIntegration.get_insights` (api/meta_integration.py), que já tem o
retry do erro transiente code 2. Nada de cliente novo.

Uso:
  python -m scripts.ingest_ad_insights --backfill 2026-02-01 2026-08-16
  python -m scripts.ingest_ad_insights                 # ontem (rodada diária)
  ... --check                                          # calcula, não grava
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)

CLIENTE = "devclub"

DDL = """
SET lock_timeout = '5s';
CREATE TABLE IF NOT EXISTS ad_insights (
    client_id    text    NOT NULL,
    ad_id        text    NOT NULL,
    insight_date date    NOT NULL,
    ad_name      text    NULL,
    campaign_id  text    NULL,
    spend        numeric NOT NULL DEFAULT 0,
    leads        integer NOT NULL DEFAULT 0,
    impressions  bigint  NOT NULL DEFAULT 0,
    clicks       integer NOT NULL DEFAULT 0,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, ad_id, insight_date)
);
CREATE TABLE IF NOT EXISTS criativo_id_map (
    client_id  text NOT NULL,
    ad_id      text NOT NULL,
    ad_name    text NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, ad_id)
);
"""

_UP_INS = """
INSERT INTO ad_insights (client_id, ad_id, insight_date, ad_name, campaign_id,
                         spend, leads, impressions, clicks, ingested_at)
VALUES (:c, :ad, :d, :nome, :camp, :sp, :ld, :imp, :cl, now())
ON CONFLICT (client_id, ad_id, insight_date) DO UPDATE SET
  ad_name=EXCLUDED.ad_name, campaign_id=EXCLUDED.campaign_id,
  spend=EXCLUDED.spend, leads=EXCLUDED.leads,
  impressions=EXCLUDED.impressions, clicks=EXCLUDED.clicks,
  ingested_at=EXCLUDED.ingested_at
"""

_UP_MAP = """
INSERT INTO criativo_id_map (client_id, ad_id, ad_name, updated_at)
VALUES (:c, :ad, :nome, now())
ON CONFLICT (client_id, ad_id) DO UPDATE SET
  ad_name=EXCLUDED.ad_name, updated_at=now()
"""


def _leads_de(actions) -> int:
    """A contagem de lead vem na lista `actions` da Meta; o tipo é 'lead'."""
    for a in (actions or []):
        if a.get("action_type") == "lead":
            try:
                return int(float(a.get("value") or 0))
            except (TypeError, ValueError):
                return 0
    return 0


def puxa_dia(meta, account_id: str, dia: date) -> list[dict]:
    """Insights level=ad de UM dia (since=until). Dia a dia de propósito: bloco
    mensal com time_increment=1 toma 500 subcode 99 da Meta e passaria do
    limit=1000 sem paginação no cliente. Sem `actions`: leads por anúncio saem
    do NOSSO banco (utm_content), a régua honesta — o pixel conta 3,1 eventos
    por lead real."""
    rows = meta.get_insights(
        account_id=account_id,
        level="ad",
        fields=["ad_id", "ad_name", "campaign_id", "spend",
                "impressions", "clicks"],
        since_date=dia.isoformat(),
        until_date=dia.isoformat(),
        timeout_s=60,
    )
    out = []
    for r in rows or []:
        out.append(dict(
            ad=str(r.get("ad_id") or ""), nome=r.get("ad_name"),
            camp=str(r.get("campaign_id") or "") or None,
            d=r.get("date_start") or dia.isoformat(),
            sp=float(r.get("spend") or 0), ld=0,
            imp=int(r.get("impressions") or 0), cl=int(r.get("clicks") or 0),
        ))
    return [x for x in out if x["ad"] and x["d"]]


def grava(conn, linhas: list[dict], lote: int = 500) -> int:
    """Upsert em LOTES multi-VALUES: 12 mil round-trips um a um derrubaram a
    primeira carga no meio, sem barulho. ~25 comandos aguentam qualquer coisa."""
    for stmt in DDL.strip().split(";"):
        if stmt.strip():
            conn.run(stmt)
    cols = "(client_id, ad_id, insight_date, ad_name, campaign_id, spend, leads, impressions, clicks, ingested_at)"
    upd = ("ad_name=EXCLUDED.ad_name, campaign_id=EXCLUDED.campaign_id, "
           "spend=EXCLUDED.spend, leads=EXCLUDED.leads, "
           "impressions=EXCLUDED.impressions, clicks=EXCLUDED.clicks, "
           "ingested_at=EXCLUDED.ingested_at")
    for i in range(0, len(linhas), lote):
        chunk = linhas[i:i + lote]
        vals, par = [], {}
        for j, x in enumerate(chunk):
            for k, v in (("ad", x["ad"]), ("d", x["d"]), ("no", x["nome"]),
                         ("ca", x["camp"]), ("sp", x["sp"]), ("ld", x["ld"]),
                         ("im", x["imp"]), ("cl", x["cl"])):
                par[f"{k}{j}"] = v
            vals.append(f"('{CLIENTE}', :ad{j}, :d{j}, :no{j}, :ca{j}, "
                        f":sp{j}, :ld{j}, :im{j}, :cl{j}, now())")
        conn.run(f"INSERT INTO ad_insights {cols} VALUES " + ",".join(vals)
                 + f" ON CONFLICT (client_id, ad_id, insight_date) DO UPDATE SET {upd}",
                 **par)
    vistos = {x["ad"]: x["nome"] for x in linhas}
    itens = list(vistos.items())
    for i in range(0, len(itens), lote):
        chunk = itens[i:i + lote]
        par = {}
        vals = []
        for j, (ad, nome) in enumerate(chunk):
            par[f"a{j}"], par[f"n{j}"] = ad, nome
            vals.append(f"('{CLIENTE}', :a{j}, :n{j}, now())")
        conn.run("INSERT INTO criativo_id_map (client_id, ad_id, ad_name, updated_at) VALUES "
                 + ",".join(vals)
                 + " ON CONFLICT (client_id, ad_id) DO UPDATE SET "
                   "ad_name=EXCLUDED.ad_name, updated_at=now()", **par)
    return len(linhas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backfill", nargs=2, metavar=("INI", "FIM"),
                    help="AAAA-MM-DD AAAA-MM-DD, em blocos mensais")
    ap.add_argument("--check", action="store_true", help="puxa e mostra, não grava")
    a = ap.parse_args()

    from api.meta_integration import MetaAdsIntegration
    token = os.getenv("META_ACCESS_TOKEN")
    account = os.getenv("META_ACCOUNT_ID", "act_188005769808959")
    if not token:
        raise SystemExit("sem META_ACCESS_TOKEN no ambiente")
    meta = MetaAdsIntegration(access_token=token)

    if a.backfill:
        ini = datetime.strptime(a.backfill[0], "%Y-%m-%d").date()
        fim = datetime.strptime(a.backfill[1], "%Y-%m-%d").date()
    else:
        ini = fim = date.today() - timedelta(days=1)  # rodada diária: ontem completo

    todas, vazios = [], 0
    d = ini
    while d <= fim:
        linhas = puxa_dia(meta, account, d)
        if not linhas:
            vazios += 1   # entre lançamentos a conta pode pausar; vazio não aborta
            print(f"  {d}: vazio")
        else:
            gasto = sum(x["sp"] for x in linhas)
            print(f"  {d}: {len(linhas)} anúncios · R$ {gasto:,.0f}")
        todas += linhas
        d += timedelta(days=1)
    if todas == [] :
        raise SystemExit("TODOS os dias vazios — API falhou; nada gravado")

    ads = {x['ad'] for x in todas}
    print(f"TOTAL: {len(todas)} linhas · {len(ads)} anúncios · "
          f"R$ {sum(x['sp'] for x in todas):,.0f} de gasto")
    if a.check:
        print("--check: nada gravado.")
        return 0

    from src.data.analytics_connection import open_analytics_connection
    conn = open_analytics_connection(timeout=600)
    try:
        n = grava(conn, todas)
    finally:
        conn.close()
    print(f"OK: {n} linhas em analytics.ad_insights · {len(ads)} em criativo_id_map")

    # RESOLVEDOR DE ÓRFÃOS (roda toda rodada diária): utm_content numérico visto
    # nos últimos 7 dias e ausente do mapa ganha nome via GET /{id} da Meta.
    # Só os recentes: os ~288 mortos do histórico não voltam a ser tentados, e um
    # UTM quebrado na origem (número que nem é objeto da Meta) falha barato
    # (1 chamada/dia) até o tráfego consertar o template.
    import requests
    conn2 = open_analytics_connection(timeout=120)
    try:
        orfaos = [r[0] for r in conn2.run(
            "SELECT DISTINCT c.utm_content FROM captacoes c "
            "WHERE c.utm_content ~ '^[0-9]{10,}$' "
            "  AND c.captured_at >= CURRENT_DATE - 7 "
            "  AND NOT EXISTS (SELECT 1 FROM criativo_id_map m "
            "                  WHERE m.ad_id = c.utm_content)")]
        ok = 0
        for i in orfaos:
            try:
                r = requests.get(f"https://graph.facebook.com/v24.0/{i}",
                                 params={"fields": "name", "access_token": token},
                                 timeout=20)
                nome = r.json().get("name") if r.status_code == 200 else None
            except Exception:
                nome = None
            if nome:
                conn2.run("INSERT INTO criativo_id_map (client_id, ad_id, ad_name, updated_at) "
                          "VALUES (:c, :a, :n, now()) ON CONFLICT (client_id, ad_id) "
                          "DO UPDATE SET ad_name=EXCLUDED.ad_name, updated_at=now()",
                          c=CLIENTE, a=str(i), n=" ".join(str(nome).split()))
                ok += 1
        if orfaos:
            print(f"resolvedor: {ok}/{len(orfaos)} órfãos recentes ganharam nome")
    finally:
        conn2.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
