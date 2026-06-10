"""Rod a verificação de 12 estratégias CPL em vários LFs (48-53).

Pra cada LF: pool do snapshot 120d (já tem matched_*_id, leadScore, converted,
realized_revenue), Meta API pull diário no nível campaign/adset/ad pra
30d antes do cap_start até cap_end. Decis qcut 10, comparativa.

Em LF48-53 só Champion estava ativo (Challenger entrou em 28/abr).
Pool = todo lead capturado, sem filtro de classe.

Saída: tabela consolidada por LF e por estratégia.
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

LFS = {
    "LF48": ("2026-03-10", "2026-03-16"),
    "LF49": ("2026-03-17", "2026-03-23"),
    "LF50": ("2026-03-24", "2026-03-29"),
    "LF51": ("2026-03-30", "2026-04-06"),
    "LF52": ("2026-04-07", "2026-04-12"),
    "LF53": ("2026-04-13", "2026-04-20"),
}


def _async_insights(account_id, level, fields, since, until, label):
    body = {
        "access_token": TOKEN,
        "time_range": json.dumps({"since": since, "until": until}),
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
    for _ in range(240):
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


def _pull_daily(level, since, until, lf_name):
    """Cache por LF×level."""
    cache = _V2 / f"outputs/_cache_meta_{level}_daily_{lf_name}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    if level == "campaign":
        fields = ["campaign_id", "campaign_name", "date_start", "spend", "actions"]
    elif level == "adset":
        fields = ["adset_id", "adset_name", "campaign_id", "date_start", "spend", "actions"]
    elif level == "ad":
        fields = ["ad_id", "ad_name", "campaign_id", "date_start", "spend", "actions"]
    frames = []
    for acc in ACCOUNTS:
        rows = _async_insights(acc, level, fields, since, until, f"{level} {acc}")
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


def _build_cpl_table(daily, key_col, window, cap_start, cap_end):
    daily = daily.sort_values([key_col, "date"]).copy()
    if window == "agg":
        win = daily[(daily["date"] >= cap_start) & (daily["date"] <= cap_end)]
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
        return {"label": label, "msg": "vazio", "cobertura": "0%"}
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


def run_lf(lf_name, cap_start, cap_end, snapshot_df):
    # Janela spend: 30d antes do cap_start até cap_end
    spend_start = (pd.to_datetime(cap_start) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    spend_end = cap_end

    pool = snapshot_df[(snapshot_df["captura_date"] >= cap_start) &
                       (snapshot_df["captura_date"] <= cap_end)].copy()
    pool = pool.rename(columns={
        "matched_ad_id": "ad_id",
        "matched_adset_id": "adset_id",
        "matched_campaign_id": "campaign_id",
        "leadScore": "lead_score",
        "realized_revenue": "revenue",
    })
    for c in ["ad_id", "adset_id", "campaign_id"]:
        pool[c] = pool[c].astype(str).replace("None", None)
    pool = pool[pool["lead_score"].notna()].copy()

    print(f"\n{'='*100}\n{lf_name} captação {cap_start} a {cap_end}: "
          f"{len(pool):,} leads, {int(pool['converted'].sum())} vendas, "
          f"R$ {pool['revenue'].sum():,.0f} receita")
    if pool["converted"].sum() < 5:
        print("  (vendas < 5, pulando)")
        return None
    ticket = pool.loc[pool["converted"] == 1, "revenue"].mean()
    print(f"  ticket médio: R$ {ticket:.0f}")

    print(f"  puxando Meta API pra janela {spend_start}..{spend_end}...")
    camp_daily = _pull_daily("campaign", spend_start, spend_end, lf_name)
    adset_daily = _pull_daily("adset", spend_start, spend_end, lf_name)
    ad_daily = _pull_daily("ad", spend_start, spend_end, lf_name)
    print(f"  campaign: {len(camp_daily):,}rows | adset: {len(adset_daily):,}rows | "
          f"ad: {len(ad_daily):,}rows | spend campaign R$ {camp_daily['spend'].sum():,.0f}")

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
    cpl_camp_agg = _build_cpl_table(camp_daily, "campaign_id", "agg", cap_start, cap_end)
    base = pool.merge(cpl_camp_agg, on="campaign_id", how="left").rename(columns={"cpl": "cpl_base"})
    summaries.append(_decile_summary(base, "lead_score", "cpl_base", "BASELINE"))

    for name, key, daily, window in strategies:
        tbl = _build_cpl_table(daily, key, window, cap_start, cap_end)
        col = f"cpl_{name}"
        tbl = tbl.rename(columns={"cpl": col})
        if window == "agg":
            p = pool.merge(tbl, on=key, how="left")
        else:
            p = pool.merge(tbl, left_on=[key, "captura_date"],
                           right_on=[key, "date"], how="left").drop(columns=["date"])
        p["roas_v1"] = p["lead_score"] * ticket / p[col]
        s = _decile_summary(p, "roas_v1", col, name)
        cov = p[col].notna().sum()
        s["cobertura_pct"] = cov / len(p) * 100
        summaries.append(s)

    return {"lf": lf_name, "n_leads": len(pool), "n_vendas": int(pool["converted"].sum()),
            "ticket": ticket, "summaries": summaries}


def print_consolidated(results):
    """Tabela: linhas = LFs, colunas = D10/D9-D10/D8-D10/D7-D10 por estratégia."""
    METRICS = ["BASELINE", "camp_d1", "adset_d1", "ad_d1", "camp_30d", "adset_30d", "ad_30d"]
    print("\n\n" + "=" * 130)
    print("CONSOLIDADO — ROAS top 10% (D10) por LF e estratégia")
    print("=" * 130)
    header = f"{'LF':<6} | {'leads':>6} | {'vd':>3} | " + " | ".join(f"{m:>13}" for m in METRICS)
    print(header)
    print("-" * len(header))
    for r in results:
        if r is None: continue
        ss = {s["label"]: s for s in r["summaries"]}
        row = f"{r['lf']:<6} | {r['n_leads']:>6,} | {r['n_vendas']:>3} | "
        cells = []
        for m in METRICS:
            s = ss.get(m, {})
            if "msg" in s or "d10" not in s:
                cells.append("        n/a")
            else:
                t = s["d10"]
                cells.append(f"{t[0]:>5.2f}x ({t[1]:>2}v)" if t[0] is not None else "        n/a")
        print(row + " | ".join(f"{c:>13}" for c in cells))

    print("\n" + "=" * 130)
    print("CONSOLIDADO — ROAS top 20% (D9+D10)")
    print("=" * 130)
    print(header)
    print("-" * len(header))
    for r in results:
        if r is None: continue
        ss = {s["label"]: s for s in r["summaries"]}
        row = f"{r['lf']:<6} | {r['n_leads']:>6,} | {r['n_vendas']:>3} | "
        cells = []
        for m in METRICS:
            s = ss.get(m, {})
            if "msg" in s or "d9_10" not in s:
                cells.append("        n/a")
            else:
                t = s["d9_10"]
                cells.append(f"{t[0]:>5.2f}x ({t[1]:>2}v)" if t[0] is not None else "        n/a")
        print(row + " | ".join(f"{c:>13}" for c in cells))

    print("\n" + "=" * 130)
    print("CONSOLIDADO — ROAS top 30% (D8-D10)")
    print("=" * 130)
    print(header)
    print("-" * len(header))
    for r in results:
        if r is None: continue
        ss = {s["label"]: s for s in r["summaries"]}
        row = f"{r['lf']:<6} | {r['n_leads']:>6,} | {r['n_vendas']:>3} | "
        cells = []
        for m in METRICS:
            s = ss.get(m, {})
            if "msg" in s or "d8_10" not in s:
                cells.append("        n/a")
            else:
                t = s["d8_10"]
                cells.append(f"{t[0]:>5.2f}x ({t[1]:>2}v)" if t[0] is not None else "        n/a")
        print(row + " | ".join(f"{c:>13}" for c in cells))

    # Salva JSON pra análise posterior
    out = []
    for r in results:
        if r is None: continue
        for s in r["summaries"]:
            out.append({
                "lf": r["lf"], "n_leads": r["n_leads"], "n_vendas": r["n_vendas"],
                "ticket": r["ticket"], "estrategia": s["label"],
                "global_roas": s.get("global_roas"),
                "d10_roas": s["d10"][0] if "d10" in s else None,
                "d10_vendas": s["d10"][1] if "d10" in s else None,
                "d9_10_roas": s["d9_10"][0] if "d9_10" in s else None,
                "d9_10_vendas": s["d9_10"][1] if "d9_10" in s else None,
                "d8_10_roas": s["d8_10"][0] if "d8_10" in s else None,
                "d8_10_vendas": s["d8_10"][1] if "d8_10" in s else None,
                "d7_10_roas": s["d7_10"][0] if "d7_10" in s else None,
                "d7_10_vendas": s["d7_10"][1] if "d7_10" in s else None,
                "cobertura_pct": s.get("cobertura_pct"),
            })
    out_path = _V2 / "outputs/_estrategias_cpl_multi_lf.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nResultado salvo em {out_path}")


def main():
    df = pd.read_parquet(SNAPSHOT)
    df["captura_date"] = pd.to_datetime(df["captura_date"])
    print(f"Snapshot 120d: {len(df):,} leads, {int(df['converted'].sum())} vendas")
    print(f"Range captação: {df['captura_date'].min().date()} → {df['captura_date'].max().date()}")

    results = []
    for lf, (s, e) in LFS.items():
        try:
            results.append(run_lf(lf, s, e, df))
        except Exception as ex:
            print(f"\n{lf} falhou: {ex}")
            results.append(None)

    print_consolidated(results)


if __name__ == "__main__":
    main()
