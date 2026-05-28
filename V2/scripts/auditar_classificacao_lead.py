#!/usr/bin/env python3
"""Auditoria da classificação Lead vs ML por campanha.

Pra cada campaign_id presente em registros_ml (LF57), lista TODOS os adsets
com: status, optimization_goal, spend ~24h, e o evento custom. Mostra:
  1. Como cada campanha foi classificada por 4 critérios diferentes
  2. Quantos leads cada critério atribui a "Lead padrão"
  3. Onde os critérios divergem (campanhas mistas)

Critérios testados:
  A. count_majority      → maioria dos adsets é não-ML (atual)
  B. count_strict_majority → maioria *estrita* (≥60%)
  C. all_non_ml          → TODOS os adsets são não-ML (mais conservador)
  D. spend_majority      → maior parte do SPEND é não-ML (24h)

Uso:
    eval "$(grep -E '^(RAILWAY_DB_|META_ACCESS_TOKEN)' V2/.env | sed 's/^/export /')"
    python3 V2/scripts/auditar_classificacao_lead.py
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
import requests

from api.meta_integration import MetaAdsIntegration


ML_GOALS = frozenset({'LeadQualified', 'LeadQualifiedHighQuality', 'HQLB', 'HQLB_LQ'})
_CID_RE = re.compile(r"(\d{15,18})\s*$")


def connect_railway():
    return pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ["RAILWAY_DB_PORT"]),
        user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"],
        database=os.environ["RAILWAY_DB_NAME"],
        ssl_context=True,
    )


def extract_cid(utm_campaign):
    if not utm_campaign:
        return None
    m = _CID_RE.search(str(utm_campaign).strip())
    return m.group(1) if m else None


def fetch_leads_with_cid(conn, since_iso, until_iso):
    """Devolve {cid: n_leads} no LF57."""
    rows = conn.run(
        """
        SELECT utm_campaign, COUNT(*) AS n
        FROM registros_ml
        WHERE created_at >= :since
          AND created_at <  :until
          AND decil IS NOT NULL
        GROUP BY utm_campaign
        """,
        since=since_iso, until=until_iso,
    )
    cid_counts: dict[str, int] = defaultdict(int)
    for utm_campaign, n in rows:
        cid = extract_cid(utm_campaign)
        if cid:
            cid_counts[cid] += int(n)
    return cid_counts


def get_campaign_adsets(meta, cid):
    """Lista adsets de uma campanha com status + optimization_goal."""
    url = f"{meta.base_url}/{cid}/adsets"
    params = {
        'access_token': meta.access_token,
        'fields': 'id,name,status,effective_status,optimization_goal,promoted_object',
        'limit': 100,
    }
    r = requests.get(url, params=params, timeout=8)
    r.raise_for_status()
    return r.json().get('data', [])


def get_campaign_spend_by_adset(meta, cid, since_date, until_date):
    """Spend por adset no range. Devolve {adset_id: spend_brl}."""
    url = f"{meta.base_url}/{cid}/insights"
    params = {
        'access_token': meta.access_token,
        'fields': 'adset_id,spend',
        'level': 'adset',
        'time_range[since]': since_date,
        'time_range[until]': until_date,
        'limit': 200,
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json().get('data', [])
    except Exception as e:
        print(f"  [warn] insights de {cid} falhou: {e}", file=sys.stderr)
        return {}
    out = {}
    for row in data:
        aid = row.get('adset_id')
        sp = float(row.get('spend') or 0)
        if aid:
            out[aid] = sp
    return out


def classify_count_majority(adsets):
    n_ml = n_lp = 0
    for a in adsets:
        promoted = a.get('promoted_object') or {}
        goal = promoted.get('custom_event_str') or a.get('optimization_goal')
        if goal in ML_GOALS: n_ml += 1
        else: n_lp += 1
    return 'Lead' if n_lp > n_ml else 'ML'


def classify_strict_majority(adsets):
    """≥60% dos adsets não-ML."""
    n_ml = n_lp = 0
    for a in adsets:
        promoted = a.get('promoted_object') or {}
        goal = promoted.get('custom_event_str') or a.get('optimization_goal')
        if goal in ML_GOALS: n_ml += 1
        else: n_lp += 1
    total = n_ml + n_lp
    if total == 0: return 'Lead'
    return 'Lead' if (n_lp / total) >= 0.6 else 'ML'


def classify_all_non_ml(adsets):
    """Todos os adsets sem evento ML."""
    for a in adsets:
        promoted = a.get('promoted_object') or {}
        goal = promoted.get('custom_event_str') or a.get('optimization_goal')
        if goal in ML_GOALS:
            return 'ML'
    return 'Lead'


def classify_spend_majority(adsets, spend_by_aid):
    """Maioria do spend (~24h) em adsets não-ML."""
    spend_ml = spend_lp = 0.0
    for a in adsets:
        aid = a.get('id')
        promoted = a.get('promoted_object') or {}
        goal = promoted.get('custom_event_str') or a.get('optimization_goal')
        sp = spend_by_aid.get(aid, 0.0)
        if goal in ML_GOALS:
            spend_ml += sp
        else:
            spend_lp += sp
    total = spend_ml + spend_lp
    if total == 0:
        # Sem spend → fallback pra count_majority
        return classify_count_majority(adsets)
    return 'Lead' if spend_lp > spend_ml else 'ML'


def main():
    for v in ("RAILWAY_DB_HOST", "RAILWAY_DB_PORT", "RAILWAY_DB_USER",
              "RAILWAY_DB_PASSWORD", "RAILWAY_DB_NAME", "META_ACCESS_TOKEN"):
        if not os.environ.get(v):
            print(f"✗ env {v} não definida.", file=sys.stderr); sys.exit(2)

    now = datetime.now(timezone.utc)
    brt = timezone(timedelta(hours=-3))
    lf_start = datetime(2026, 5, 25, 0, 0, 0, tzinfo=brt).astimezone(timezone.utc).isoformat()
    lf_end = now.isoformat()

    # Spend window: últimas 24h
    spend_since = (now - timedelta(hours=24)).strftime('%Y-%m-%d')
    spend_until = now.strftime('%Y-%m-%d')

    print(f"LF57 window: [{lf_start}  →  {lf_end})")
    print(f"Spend window: {spend_since} → {spend_until}\n")

    conn = connect_railway()
    cid_counts = fetch_leads_with_cid(conn, lf_start, lf_end)
    print(f"Campanhas com leads LF57: {len(cid_counts)}\n")

    meta = MetaAdsIntegration(access_token=os.environ["META_ACCESS_TOKEN"])

    # Audita cada campanha
    per_cid: list[dict] = []
    for cid, n_leads in sorted(cid_counts.items(), key=lambda x: -x[1]):
        try:
            adsets = get_campaign_adsets(meta, cid)
        except Exception as e:
            print(f"  [skip] {cid}: {e}", file=sys.stderr)
            continue
        spend_by_aid = get_campaign_spend_by_adset(meta, cid, spend_since, spend_until)

        # Resumo dos adsets
        active_adsets = [a for a in adsets if (a.get('effective_status') or a.get('status')) == 'ACTIVE']
        breakdown = []
        for a in adsets:
            aid = a.get('id')
            promoted = a.get('promoted_object') or {}
            goal = promoted.get('custom_event_str') or a.get('optimization_goal') or '?'
            st = (a.get('effective_status') or a.get('status') or '?')
            sp = spend_by_aid.get(aid, 0.0)
            breakdown.append((aid, st, goal, sp))

        classifications = {
            'A_count':       classify_count_majority(adsets),
            'B_strict':      classify_strict_majority(adsets),
            'C_all_non_ml':  classify_all_non_ml(adsets),
            'D_spend':       classify_spend_majority(adsets, spend_by_aid),
            'A_count_active':       classify_count_majority(active_adsets) if active_adsets else 'ML',
            'C_all_non_ml_active':  classify_all_non_ml(active_adsets) if active_adsets else 'ML',
        }
        per_cid.append({
            'cid': cid,
            'n_leads': n_leads,
            'n_adsets': len(adsets),
            'n_active': len(active_adsets),
            'classifications': classifications,
            'breakdown': breakdown,
        })

    # Detalhe por campanha
    print(f"{'CID':<20} {'leads':>6} {'adsets':>6} {'active':>6}  {'A':>4} {'B':>4} {'C':>4} {'D':>4} {'C_act':>5}")
    print("-" * 80)
    for c in per_cid:
        cls = c['classifications']
        print(f"{c['cid']:<20} {c['n_leads']:>6} {c['n_adsets']:>6} {c['n_active']:>6}  "
              f"{cls['A_count'][0]:>4} {cls['B_strict'][0]:>4} {cls['C_all_non_ml'][0]:>4} "
              f"{cls['D_spend'][0]:>4} {cls['C_all_non_ml_active'][0]:>5}")
        for aid, st, goal, sp in c['breakdown']:
            print(f"    {aid:<18} {st:<10} {goal:<35} R${sp:>8.2f}")

    # Sumário: n_leads em Lead por critério
    print("\n━━━ Quantos leads cada critério atribui a 'Lead padrão' ━━━")
    for crit in ('A_count', 'B_strict', 'C_all_non_ml', 'D_spend', 'A_count_active', 'C_all_non_ml_active'):
        n_lead = sum(c['n_leads'] for c in per_cid if c['classifications'][crit] == 'Lead')
        n_total = sum(c['n_leads'] for c in per_cid)
        n_cid_lead = sum(1 for c in per_cid if c['classifications'][crit] == 'Lead')
        print(f"  {crit:<22}: {n_cid_lead:>2}/{len(per_cid)} campanhas, "
              f"{n_lead:,} leads ({n_lead/n_total*100:.1f}% do total LF57)")

    # Divergências entre critérios
    print("\n━━━ Campanhas onde os critérios divergem ━━━")
    for c in per_cid:
        cls = c['classifications']
        vals = set(cls.values())
        if len(vals) > 1:
            print(f"  {c['cid']:<18} leads={c['n_leads']:>4} "
                  f"adsets={c['n_adsets']} active={c['n_active']}  "
                  f"A={cls['A_count']} B={cls['B_strict']} C={cls['C_all_non_ml']} "
                  f"D={cls['D_spend']} C_act={cls['C_all_non_ml_active']}")


if __name__ == "__main__":
    main()
