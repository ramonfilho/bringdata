#!/usr/bin/env python3
"""Análise one-shot: distribuição de decis por categoria de otimização Meta.

Cruza leads scoreados em registros_ml com optimization_goal dos adsets na Meta
API, classificando cada lead em 3 buckets:

  - Lead       → adset optimiza pra evento Lead padrão Meta (não-ML)
  - Champion   → adset optimiza pra LeadQualified / LeadQualifiedHighQuality
  - Challenger → adset optimiza pra HQLB / HQLB_LQ

Saída: tabela markdown por janela (Ontem + LF57) com n, avg_decil, %D9-D10
e distribuição completa D01..D10 por bucket.

Uso:
    eval "$(grep -E '^(RAILWAY_DB_|META_ACCESS_TOKEN)' V2/.env | sed 's/^/export /')"
    python3 V2/scripts/analise_decis_por_optimization_goal.py
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pg8000.native

from api.meta_integration import MetaAdsIntegration


META_ACCOUNT_ID = "act_582814730252892"  # DevClub

# Bucketing dos optimization_goals
CHAMPION_GOALS  = {"LeadQualified", "LeadQualifiedHighQuality"}
CHALLENGER_GOALS = {"HQLB", "HQLB_LQ"}
# Tudo que não casar = "Lead" (LEAD, OFFSITE_CONVERSIONS sem custom_event, etc.)


def connect_railway():
    return pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ["RAILWAY_DB_PORT"]),
        user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"],
        database=os.environ["RAILWAY_DB_NAME"],
        ssl_context=True,
    )


_CAMPAIGN_ID_RE = re.compile(r"(\d{15,18})\s*$")


def extract_campaign_id(utm_campaign: str | None) -> str | None:
    """Extrai o trailing 15-18-digit ID do utm_campaign.

    Exemplo: 'DEVLF | ... | 2025-04-30|120243354440640390' → '120243354440640390'.
    Retorna None se não casar.
    """
    if not utm_campaign:
        return None
    m = _CAMPAIGN_ID_RE.search(utm_campaign.strip())
    return m.group(1) if m else None


def fetch_leads(conn, since_iso: str, until_iso: str) -> list[tuple]:
    """SELECT decil, utm_campaign FROM registros_ml WHERE janela + decil populado."""
    return conn.run(
        """
        SELECT decil, utm_campaign, utm_source
        FROM registros_ml
        WHERE created_at >= :since
          AND created_at <  :until
          AND decil IS NOT NULL
        """,
        since=since_iso, until=until_iso,
    )


def classify_goal(goal: str | None) -> str:
    """optimization_goal → bucket {Lead, Champion, Challenger}."""
    if not goal:
        return "Lead"
    if goal in CHAMPION_GOALS:
        return "Champion"
    if goal in CHALLENGER_GOALS:
        return "Challenger"
    return "Lead"


def get_campaign_classification(meta: MetaAdsIntegration, campaign_id: str) -> str:
    """Pra uma campanha, lista os adsets e devolve o bucket dominante.

    Estratégia: pega todos os adsets ACTIVE/PAUSED da campanha, classifica
    cada um, e devolve o bucket com mais adsets. Se empate, prioriza
    Challenger > Champion > Lead (porque o sinal mais raro é o mais
    informativo — se a campanha tem QUALQUER adset Challenger, é
    razoável classificar a campanha como Challenger).
    """
    url = f"{meta.base_url}/{campaign_id}/adsets"
    params = {
        "access_token": meta.access_token,
        "fields": "id,name,status,optimization_goal,promoted_object",
        "limit": 100,
    }
    import requests
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        adsets = r.json().get("data", [])
    except Exception as e:
        print(f"  ⚠️  campaign {campaign_id} falhou: {e}", file=sys.stderr)
        return "Lead"  # default conservador

    if not adsets:
        return "Lead"

    buckets = defaultdict(int)
    for a in adsets:
        promoted = a.get("promoted_object") or {}
        goal = promoted.get("custom_event_str") or a.get("optimization_goal")
        buckets[classify_goal(goal)] += 1

    # Empate: Challenger > Champion > Lead
    for preferred in ("Challenger", "Champion", "Lead"):
        if buckets.get(preferred, 0) == max(buckets.values()):
            return preferred
    return "Lead"


def compute_dist(rows: list[tuple], classification: dict[str, str]) -> dict[str, dict]:
    """Agrega leads em buckets baseado na classification por campaign_id.

    rows = list of (decil, utm_campaign, utm_source).
    classification = {campaign_id: bucket}.

    Retorna {bucket: {distribution: {D01..D10: count}, n, avg_decil, pct_d9_d10}}.
    """
    out = {b: {"distribution": {f"D{i:02d}": 0 for i in range(1, 11)},
               "n": 0, "decil_sum": 0, "d9_d10": 0}
           for b in ("Lead", "Champion", "Challenger", "_unknown")}

    for decil, utm_campaign, _utm_source in rows:
        cid = extract_campaign_id(utm_campaign)
        bucket = classification.get(cid, "_unknown") if cid else "_unknown"
        b = out[bucket]
        key = f"D{int(decil):02d}"
        b["distribution"][key] += 1
        b["n"] += 1
        b["decil_sum"] += int(decil)
        if int(decil) >= 9:
            b["d9_d10"] += 1

    for b in out.values():
        if b["n"] > 0:
            b["avg_decil"] = b["decil_sum"] / b["n"]
            b["pct_d9_d10"] = b["d9_d10"] / b["n"] * 100
        else:
            b["avg_decil"] = None
            b["pct_d9_d10"] = None

    return out


def print_report(label: str, dist: dict[str, dict]):
    print(f"\n━━━ {label} ━━━")
    print(f"{'Bucket':<12} {'n':>6} {'avg_decil':>10} {'%D9-D10':>10}  Distribuição D01..D10")
    for bucket in ("Lead", "Champion", "Challenger", "_unknown"):
        b = dist[bucket]
        if b["n"] == 0:
            continue
        keys = [f"D{i:02d}" for i in range(1, 11)]
        dist_str = " ".join(f"{int(b['distribution'].get(k, 0) / b['n'] * 100):>3d}%" for k in keys)
        print(f"{bucket:<12} {b['n']:>6} {b['avg_decil']:>10.2f} {b['pct_d9_d10']:>9.1f}%  {dist_str}")


def main():
    for v in ("RAILWAY_DB_HOST", "RAILWAY_DB_PORT", "RAILWAY_DB_USER",
              "RAILWAY_DB_PASSWORD", "RAILWAY_DB_NAME", "META_ACCESS_TOKEN"):
        if not os.environ.get(v):
            print(f"✗ env {v} não definida.", file=sys.stderr)
            sys.exit(2)

    # Janelas
    now = datetime.now(timezone.utc)
    brt = timezone(timedelta(hours=-3))
    today_brt_mid = datetime.now(brt).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_brt_mid = today_brt_mid - timedelta(days=1)
    yest_start = yesterday_brt_mid.astimezone(timezone.utc).isoformat()
    yest_end = today_brt_mid.astimezone(timezone.utc).isoformat()

    lf_start = datetime(2026, 5, 25, 0, 0, 0, tzinfo=brt).astimezone(timezone.utc).isoformat()
    lf_end = now.isoformat()

    print(f"Janela Ontem:  [{yest_start}  →  {yest_end})")
    print(f"Janela LF57:   [{lf_start}  →  {lf_end})")

    # Pull leads
    conn = connect_railway()
    rows_yest = fetch_leads(conn, yest_start, yest_end)
    rows_lf   = fetch_leads(conn, lf_start, lf_end)
    print(f"\nLeads scoreados: Ontem={len(rows_yest)}  LF57={len(rows_lf)}")

    # Unique campaign_ids
    all_rows = rows_yest + rows_lf
    cids = set()
    no_cid = 0
    for _, utm_campaign, _ in all_rows:
        cid = extract_campaign_id(utm_campaign)
        if cid:
            cids.add(cid)
        else:
            no_cid += 1
    print(f"Campaign IDs únicos: {len(cids)}  ·  leads sem cid: {no_cid}")

    # Classify via Meta API
    meta = MetaAdsIntegration(access_token=os.environ["META_ACCESS_TOKEN"])
    classification: dict[str, str] = {}
    print(f"\nClassificando {len(cids)} campanhas via Meta API...")
    for i, cid in enumerate(sorted(cids), 1):
        classification[cid] = get_campaign_classification(meta, cid)
        if i % 10 == 0 or i == len(cids):
            print(f"  [{i:3d}/{len(cids)}]")

    # Sumário por classification
    from collections import Counter
    cnt_class = Counter(classification.values())
    print(f"\nClassificação das {len(cids)} campanhas: {dict(cnt_class)}")

    # Distribuições
    dist_yest = compute_dist(rows_yest, classification)
    dist_lf   = compute_dist(rows_lf, classification)
    print_report("Ontem (BRT day anterior)", dist_yest)
    print_report("LF57 (25/05 → hoje)",      dist_lf)


if __name__ == "__main__":
    main()
