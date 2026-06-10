"""Replica a verificação das 8 estratégias de CPL no LF53 (captação 13-20/abr/2026).

Fonte: snapshot 120d em `bring_data-roas/V2/outputs/roas/analise_roas_matched.parquet`
(já tem matched_ad_id, leadScore, converted, realized_revenue). Spend ad-level
puxado fresh da Meta API porque o snapshot só tem adset+campaign.

Em LF53 o A/B Champion vs Challenger não existia ainda (Challenger só entrou
em 28/abr) — todo o pool é Champion por construção. Por isso não há filtro por
classe LEADQUALIFIED como no LF56; usa-se todo o pool de captação do LF53.
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

import numpy as np
import pandas as pd
import requests

for line in (_V2 / ".env").read_text().splitlines():
    if line.startswith("META_ACCESS_TOKEN="):
        os.environ["META_ACCESS_TOKEN"] = line.split("=", 1)[1].strip()
        break
TOKEN = os.environ["META_ACCESS_TOKEN"]
API = "v23.0"
ACCOUNTS = ["act_188005769808959"]
SNAPSHOT = Path("/Users/ramonmoreira/Desktop/bring_data-roas/V2/outputs/roas/analise_roas_matched.parquet")

CAP_START = "2026-04-13"
CAP_END = "2026-04-20"
SPEND_START = "2026-03-14"  # 30d antes de CAP_START
SPEND_END = "2026-04-20"


def _async_insights(account_id, level, fields, label):
    body = {
        "access_token": TOKEN,
        "time_range": json.dumps({"since": SPEND_START, "until": SPEND_END}),
        "level": level,
        "time_increment": 1,
        "fields": ",".join(fields),
    }
    r = requests.post(f"https://graph.facebook.com/{API}/{account_id}/insights",
                      data=body, timeout=60)
    r.raise_for_status()
    rid = r.json().get("report_run_id")
    if not rid:
        raise RuntimeError(f"sem report_run_id: {r.text}")
    for _ in range(180):
        s = requests.get(f"https://graph.facebook.com/{API}/{rid}",
                         params={"access_token": TOKEN}, timeout=30).json()
        st = s.get("async_status")
        if st == "Job Completed":
            break
        if st in ("Job Failed", "Job Skipped"):
            raise RuntimeError(f"{label} falhou: {s}")
        time.sleep(2)
    rows = []
    url = f"https://graph.facebook.com/{API}/{rid}/insights"
    params = {"access_token": TOKEN, "limit": 500}
    while url:
        r = requests.get(url, params=params, timeout=60); r.raise_for_status()
        d = r.json()
        rows.extend(d.get("data", []))
        url = d.get("paging", {}).get("next"); params = {}
    return rows


def _parse_leads(actions):
    if not actions: return 0.0
    for a in actions:
        if a.get("action_type") == "lead":
            return float(a.get("value", 0))
    return 0.0


def _pull_daily(level, fields_extra):
    cache = _V2 / f"outputs/_cache_meta_{level}_daily_lf53.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    fields = ["campaign_id", "date_start", "spend", "actions"] + fields_extra
    if level == "ad":
        fields = ["ad_id", "ad_name"] + fields
    frames = []
    for acc in ACCOUNTS:
        rows = _async_insights(acc, level, fields, f"{level} {acc}")
        for r in rows:
            base = {
                "campaign_id": str(r.get("campaign_id")),
                "date": pd.to_datetime(r.get("date_start")).normalize(),
                "spend": float(r.get("spend", 0)),
                "leads": _parse_leads(r.get("actions")),
            }
            if level == "ad":
                base["ad_id"] = str(r.get("ad_id"))
                base["ad_name"] = r.get("ad_name")
            elif level == "adset":
                base["adset_id"] = str(r.get("adset_id"))
                base["adset_name"] = r.get("adset_name")
            frames.append(base)
    df = pd.DataFrame(frames)
    df.to_parquet(cache, index=False)
    return df


def _build_cpl_table(daily, key_col, window):
    daily = daily.sort_values([key_col, "date"]).copy()
    if window == "agg":
        win = daily[(daily["date"] >= CAP_START) & (daily["date"] <= CAP_END)]
        agg = win.groupby(key_col).agg(spend=("spend", "sum"), leads=("leads", "sum")).reset_index()
        agg["cpl"] = np.where(agg["leads"] > 0, agg["spend"] / agg["leads"], np.nan)
        return agg[[key_col, "cpl"]]
    rows = []
    for k, g in daily.groupby(key_col):
        g = g.set_index("date").sort_index()
        idx = pd.date_range(g.index.min(), g.index.max(), freq="D")
        g = g.reindex(idx).fillna({"spend": 0.0, "leads": 0.0})
        if window == "d1":
            sp = g["spend"].shift(1); ld = g["leads"].shift(1)
        elif window == "3d":
            sp = g["spend"].rolling(3, min_periods=1, closed="left").sum()
            ld = g["leads"].rolling(3, min_periods=1, closed="left").sum()
        elif window == "30d":
            sp = g["spend"].rolling(30, min_periods=1, closed="left").sum()
            ld = g["leads"].rolling(30, min_periods=1, closed="left").sum()
        cpl = np.where(ld > 0, sp / ld, np.nan)
        rows.append(pd.DataFrame({key_col: k, "date": idx, "cpl": cpl}))
    return pd.concat(rows, ignore_index=True)


def _decile_summary(df, rank_col, cost_col, label):
    valid = df.dropna(subset=[rank_col, cost_col, "revenue"]).copy()
    valid = valid[valid[cost_col] > 0]
    if valid.empty:
        return {"label": label, "msg": "vazio"}
    valid["decil"] = pd.qcut(valid[rank_col], q=10, labels=False, duplicates="drop") + 1
    g = valid.groupby("decil").agg(
        n_leads=("lead_id", "size"),
        n_vendas=("converted", "sum"),
        revenue=("revenue", "sum"),
        cost=(cost_col, "sum"),
    )
    g["roas"] = np.where(g["cost"] > 0, g["revenue"] / g["cost"], 0.0)

    def top(ds):
        rev = sum(g.loc[d, "revenue"] for d in ds if d in g.index)
        cost = sum(g.loc[d, "cost"] for d in ds if d in g.index)
        n = sum(g.loc[d, "n_vendas"] for d in ds if d in g.index)
        return (rev / cost if cost > 0 else None, int(n))
    return {
        "label": label,
        "n": len(valid),
        "vendas": int(valid["converted"].sum()),
        "global_roas": valid["revenue"].sum() / valid[cost_col].sum(),
        "d10": top([10]),
        "d9_10": top([9, 10]),
        "d8_10": top([8, 9, 10]),
        "d7_10": top([7, 8, 9, 10]),
    }


def main():
    df = pd.read_parquet(SNAPSHOT)
    df["captura_date"] = pd.to_datetime(df["captura_date"])
    pool = df[(df["captura_date"] >= CAP_START) & (df["captura_date"] <= CAP_END)].copy()
    pool = pool.rename(columns={
        "matched_ad_id": "ad_id",
        "matched_adset_id": "adset_id",
        "matched_campaign_id": "campaign_id",
        "leadScore": "lead_score",
        "realized_revenue": "revenue",
    })
    # Garantir string e dropar nans
    for c in ["ad_id", "adset_id", "campaign_id"]:
        pool[c] = pool[c].astype(str).replace("None", None)
    pool = pool[pool["lead_score"].notna()].copy()

    print(f"Pool LF53 captação 13-20/04: {len(pool):,} leads, {int(pool['converted'].sum())} vendas, "
          f"R$ {pool['revenue'].sum():,.0f} receita")
    ticket = pool.loc[pool["converted"] == 1, "revenue"].mean()
    print(f"Ticket médio das vendas: R$ {ticket:.0f}")

    print("\nPuxando Meta API LF53...")
    camp_daily = _pull_daily("campaign", ["campaign_name"])
    print(f"  campanha: {len(camp_daily):,} rows, spend total {camp_daily['spend'].sum():,.0f}")
    adset_daily = _pull_daily("adset", ["adset_id", "adset_name"])
    print(f"  adset: {len(adset_daily):,} rows, spend total {adset_daily['spend'].sum():,.0f}")
    ad_daily = _pull_daily("ad", [])
    print(f"  ad: {len(ad_daily):,} rows, spend total {ad_daily['spend'].sum():,.0f}")

    strategies = [
        ("camp_agg",  "campaign_id", camp_daily, "agg"),
        ("camp_d1",   "campaign_id", camp_daily, "d1"),
        ("camp_3d",   "campaign_id", camp_daily, "3d"),
        ("camp_30d",  "campaign_id", camp_daily, "30d"),
        ("adset_agg", "adset_id",    adset_daily, "agg"),
        ("adset_d1",  "adset_id",    adset_daily, "d1"),
        ("adset_3d",  "adset_id",    adset_daily, "3d"),
        ("adset_30d", "adset_id",    adset_daily, "30d"),
        ("ad_agg",    "ad_id",       ad_daily,    "agg"),
        ("ad_d1",     "ad_id",       ad_daily,    "d1"),
        ("ad_3d",     "ad_id",       ad_daily,    "3d"),
        ("ad_30d",    "ad_id",       ad_daily,    "30d"),
    ]

    summaries = []
    # Baseline: rank score puro, custo p/ ROAS = cost_campaign agregado
    cpl_camp_agg = _build_cpl_table(camp_daily, "campaign_id", "agg")
    base = pool.merge(cpl_camp_agg, on="campaign_id", how="left").rename(columns={"cpl": "cpl_base"})
    summaries.append(_decile_summary(base, "lead_score", "cpl_base", "BASELINE (score puro)"))

    for name, key, daily, window in strategies:
        tbl = _build_cpl_table(daily, key, window)
        col = f"cpl_{name}"
        tbl = tbl.rename(columns={"cpl": col})
        if window == "agg":
            p = pool.merge(tbl, on=key, how="left")
        else:
            p = pool.merge(tbl, left_on=[key, "captura_date"],
                           right_on=[key, "date"], how="left").drop(columns=["date"])
        p["roas_v1"] = p["lead_score"] * ticket / p[col]
        s = _decile_summary(p, "roas_v1", col, f"V1 {name}")
        cov = p[col].notna().sum()
        s["cobertura"] = f"{cov}/{len(p)} ({cov/len(p)*100:.0f}%)"
        summaries.append(s)

    print("\n" + "=" * 130)
    print(f"COMPARATIVA LF53 — ROAS por estratégia (ticket médio R$ {ticket:.0f})")
    print("=" * 130)
    print(f"{'Estratégia':<26} | {'cobertura':>14} | {'global':>8} | {'D10':>14} | {'D9+D10':>14} | {'D8-D10':>14} | {'D7-D10':>14}")
    print("-" * 130)
    for s in summaries:
        if "msg" in s:
            print(f"{s['label']:<26} | {s.get('cobertura','-'):>14} | (vazio)")
            continue
        fmt = lambda t: f"{t[0]:>5.2f}x ({t[1]:>2}v)" if t[0] is not None else "       (n/a)"
        print(f"{s['label'][:26]:<26} | {s.get('cobertura','-'):>14} | "
              f"{s['global_roas']:>5.2f}x  | "
              f"{fmt(s['d10']):>14} | {fmt(s['d9_10']):>14} | "
              f"{fmt(s['d8_10']):>14} | {fmt(s['d7_10']):>14}")


if __name__ == "__main__":
    main()
