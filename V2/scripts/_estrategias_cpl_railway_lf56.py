"""Re-roda as 12 estratégias de CPL no LF56 usando leads do Railway
(UTMTracking) como denominador do CPL, em vez dos leads que a Meta API reporta.

Pergunta: o pool oficial de leads que entrou no sistema (~7.880 leads no xlsx
[LF56] Leads.xlsx, ~6.867 com campaign_id no UTMTracking) é diferente do que
a Meta reporta (action_type='lead'). Trocar o denominador muda o ranking?

Spend continua da Meta API (single source pro custo).
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
CAP_START = "2026-05-25"
CAP_END = "2026-05-31"
TICKET_CARTAO = 1997.0
TICKET_BOLETO = 1150.0


def _classify(c):
    if not isinstance(c, str): return "outro"
    cu = c.upper()
    if "LEADHQLB" in cu or "LEAD HQLB" in cu: return "lead_hqlb"
    if "LEADQUALIFIED" in cu: return "leadqualified"
    if "DEVLF" in cu and "CAP" in cu: return "outras_meta_cap"
    return "outro"


def _build_railway_leads():
    """Constrói tabelas (entity, date) → N leads do Railway pra 3 granularidades."""
    utm = pd.read_parquet(_V2 / "outputs/_railway_leads_lf56_window.parquet")
    # Cada linha já é (email, date, campaign_id, content)
    # campaign: granularidade campanha
    camp = utm.groupby(["campaign_id", "date"]).size().reset_index(name="leads_railway")
    camp = camp.rename(columns={"date": "date_railway"})

    # Pra adset e ad: precisa mapear via content → ad_id → adset_id (mesma lógica do script original).
    # Como o mapping vem da Meta API, vou só preparar o utm_content por lead aqui.
    import re
    utm["ad_code"] = utm["content"].astype(str).str.upper().str.extract(r"(AD\d{4})")
    return utm, camp


def _async_insights(account_id, level, fields, since, until, label):
    body = {"access_token": TOKEN,
            "time_range": json.dumps({"since": since, "until": until}),
            "level": level, "time_increment": 1, "fields": ",".join(fields)}
    r = requests.post(f"https://graph.facebook.com/{API}/{account_id}/insights", data=body, timeout=60)
    r.raise_for_status()
    rid = r.json().get("report_run_id")
    if not rid:
        raise RuntimeError(f"sem report_run_id: {r.text}")
    for _ in range(240):
        s = requests.get(f"https://graph.facebook.com/{API}/{rid}",
                         params={"access_token": TOKEN}, timeout=30).json()
        if s.get("async_status") == "Job Completed": break
        if s.get("async_status") in ("Job Failed", "Job Skipped"):
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


def _pull_daily(level):
    """Pula daily metrics ad/campaign — reusa cache do script anterior."""
    cache = _V2 / f"outputs/_cache_meta_{level}_daily_lf56.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    raise FileNotFoundError(f"{cache} não existe — rodar _estrategias_cpl_lf56.py primeiro pra popular cache")


def _build_cpl_table(daily, key_col, window, leads_override=None):
    """Constrói CPL por (entity, date) ou agg.
    leads_override: dict {(entity_id, date): N_leads_railway}. Se passado,
    substitui o leads_dia da Meta API pelo do Railway."""
    daily = daily.sort_values([key_col, "date"]).copy()

    # Se leads_override passado, sobrescreve a coluna leads
    if leads_override is not None:
        idx_keys = list(zip(daily[key_col].astype(str), daily["date"]))
        daily["leads"] = [leads_override.get(k, 0.0) for k in idx_keys]

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
        n_leads=("email", "size"), n_vendas=("converted", "sum"),
        revenue=("revenue", "sum"), cost=(cost_col, "sum"))
    g["roas"] = np.where(g["cost"] > 0, g["revenue"] / g["cost"], 0.0)
    def top(ds):
        rev = sum(g.loc[d, "revenue"] for d in ds if d in g.index)
        cost = sum(g.loc[d, "cost"] for d in ds if d in g.index)
        n = sum(g.loc[d, "n_vendas"] for d in ds if d in g.index)
        return (rev / cost if cost > 0 else None, int(n))
    return {
        "label": label, "n": len(valid), "vendas": int(valid["converted"].sum()),
        "global_roas": valid["revenue"].sum() / valid[cost_col].sum(),
        "d10": top([10]), "d9_10": top([9, 10]),
        "d8_10": top([8, 9, 10]), "d7_10": top([7, 8, 9, 10]),
    }


def main():
    # Pool (mesmo do script anterior)
    frames = []
    for f in ["matched_champion", "matched_challenger", "matched_fora_do_ab"]:
        d = pd.read_parquet(f"outputs/validation/2026-06/{f}.parquet")
        frames.append(d)
    allp = pd.concat(frames, ignore_index=True, sort=False)
    allp["data_captura"] = pd.to_datetime(allp["data_captura"])
    allp["captura_date"] = allp["data_captura"].dt.normalize()
    allp["classe"] = allp["campaign"].apply(_classify)
    pool = allp[(allp["classe"] == "leadqualified") &
                (allp["captura_date"] >= CAP_START) &
                (allp["captura_date"] <= CAP_END) &
                allp["lead_score"].notna()].copy()
    def _cid(s):
        if not isinstance(s, str): return None
        parts = s.split("|"); last = parts[-1].strip()
        return last if last.isdigit() else None
    pool["campaign_id"] = pool["campaign"].apply(_cid)
    def _rev(r):
        if r["converted"] != 1: return 0.0
        sv = r.get("sale_value", 0)
        if pd.isna(sv) or sv == 0: return 0.0
        return TICKET_BOLETO if sv > 2200 else TICKET_CARTAO
    pool["revenue"] = pool.apply(_rev, axis=1)
    ticket = pool.loc[pool["converted"] == 1, "revenue"].mean()
    print(f"Pool LEADQUALIFIED 25-31/05: {len(pool):,} leads, {int(pool['converted'].sum())} vendas, "
          f"ticket R$ {ticket:.0f}")

    # Carrega caches Meta
    camp_daily = _pull_daily("campaign")
    ad_daily = _pull_daily("ad")
    print(f"campanha cache: {len(camp_daily):,} rows | ad cache: {len(ad_daily):,} rows")

    # Pool de leads do Railway por (entity, date)
    utm, camp_railway = _build_railway_leads()
    leads_camp_railway = {(str(r["campaign_id"]), pd.Timestamp(r["date_railway"])): r["leads_railway"]
                          for _, r in camp_railway.iterrows()}
    print(f"\nLeads Railway: {len(utm):,} eventos, {sum(leads_camp_railway.values()):,.0f} leads atribuíveis "
          f"a (camp, dia)")

    # Comparativa campanha-level: leads Meta vs leads Railway na janela LF
    camp_win = camp_daily[(camp_daily["date"] >= CAP_START) & (camp_daily["date"] <= CAP_END)]
    leads_meta = camp_win.groupby("campaign_id")["leads"].sum()
    leads_rw = camp_railway.groupby("campaign_id")["leads_railway"].sum()
    print(f"\nTotal Meta leads (janela LF): {leads_meta.sum():,.0f}")
    print(f"Total Railway leads (janela LF, c/ campaign_id): {leads_rw.sum():,.0f}")

    # Ad-level leads do Railway: usa mapping ad_code → ad_id do cache da Meta
    aw = ad_daily[(ad_daily["date"] >= CAP_START) & (ad_daily["date"] <= CAP_END)].copy()
    import re
    aw["code"] = aw["ad_name"].astype(str).str.upper().str.extract(r"(AD\d{4})")
    aw = aw.dropna(subset=["code"])
    code_to_ad = aw.groupby(["code","ad_id"], as_index=False)["spend"].sum() \
                   .sort_values("spend", ascending=False).drop_duplicates("code")
    ad_index_code = dict(zip(code_to_ad["code"], code_to_ad["ad_id"]))
    utm["ad_id"] = utm["ad_code"].map(ad_index_code)
    cov_ad = utm["ad_id"].notna().sum()
    print(f"Cobertura mapping Railway → ad_id: {cov_ad:,}/{len(utm):,} ({cov_ad/len(utm)*100:.1f}%)")
    leads_ad_railway = utm.dropna(subset=["ad_id"]).groupby(["ad_id", "date"]).size().to_dict()
    leads_ad_railway = {(str(k[0]), pd.Timestamp(k[1])): v for k, v in leads_ad_railway.items()}

    # Mapear ad_id no pool (mesmo método: utm_content → ad_code → ad_id)
    def _match_ad(content):
        if not isinstance(content, str): return None
        m = re.search(r"AD\d{4}", content, re.IGNORECASE)
        if not m: return None
        return ad_index_code.get(m.group(0).upper())
    pool["ad_id"] = pool["content"].apply(_match_ad)

    # Estratégias: 8 (campanha × 4 + ad × 4), cada uma com 3 variantes de denominador:
    #   meta:    leads = Meta API action_type='lead'
    #   railway: leads = UTMTracking do dia
    strategies_8 = [
        ("camp_agg", "campaign_id", camp_daily, "agg"),
        ("camp_d1",  "campaign_id", camp_daily, "d1"),
        ("camp_3d",  "campaign_id", camp_daily, "3d"),
        ("camp_30d", "campaign_id", camp_daily, "30d"),
        ("ad_agg",   "ad_id",       ad_daily,   "agg"),
        ("ad_d1",    "ad_id",       ad_daily,   "d1"),
        ("ad_3d",    "ad_id",       ad_daily,   "3d"),
        ("ad_30d",   "ad_id",       ad_daily,   "30d"),
    ]

    summaries = []
    # Baseline
    cpl_camp_agg = _build_cpl_table(camp_daily, "campaign_id", "agg")
    base = pool.merge(cpl_camp_agg, on="campaign_id", how="left").rename(columns={"cpl": "cpl_base"})
    summaries.append(_decile_summary(base, "lead_score", "cpl_base", "BASELINE"))

    for name, key, daily, window in strategies_8:
        for source, leads_map in [("META", None),
                                   ("RAILWAY", leads_camp_railway if key == "campaign_id" else leads_ad_railway)]:
            tbl = _build_cpl_table(daily, key, window, leads_override=leads_map)
            col = f"cpl_{name}_{source.lower()}"
            tbl = tbl.rename(columns={"cpl": col})
            if window == "agg":
                p = pool.merge(tbl, on=key, how="left")
            else:
                p = pool.merge(tbl, left_on=[key, "captura_date"],
                               right_on=[key, "date"], how="left").drop(columns=["date"])
            p["roas_v1"] = p["lead_score"] * ticket / p[col]
            s = _decile_summary(p, "roas_v1", col, f"{name}_{source}")
            cov = p[col].notna().sum()
            s["cobertura_pct"] = cov / len(p) * 100
            summaries.append(s)

    print("\n" + "=" * 160)
    print("COMPARATIVA — denominador Meta vs Railway")
    print("=" * 160)
    print(f"{'Estratégia':<22} | {'cov%':>5} | {'global':>7} | {'D10':>15} | {'D9+D10':>15} | {'D8-D10':>15} | {'D7-D10':>15}")
    print("-" * 160)
    for s in summaries:
        if "msg" in s:
            print(f"{s['label']:<22} | (vazio)"); continue
        fmt = lambda t: f"{t[0]:>5.2f}x ({t[1]:>2}v)" if t[0] is not None else "        n/a"
        print(f"{s['label'][:22]:<22} | {s.get('cobertura_pct',100):>4.0f}% | "
              f"{s['global_roas']:>5.2f}x | "
              f"{fmt(s['d10']):>15} | {fmt(s['d9_10']):>15} | "
              f"{fmt(s['d8_10']):>15} | {fmt(s['d7_10']):>15}")


if __name__ == "__main__":
    main()
