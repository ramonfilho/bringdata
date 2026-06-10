"""Testa estratégias de mapeamento CPL no pool Champion ML do LF56.

Pool: leads em campanha LEADQUALIFIED capturados 25-31/05 — junta os 3 parquets
(Champion + Challenger + fora_do_ab) pra bater com o relatório oficial.

Estratégias avaliadas (8 = 4 janelas × 2 granularidades):
  granularidade: campanha | adset
  janela:        agregado LF (25-31/05) | D-1 | rolling 3d | rolling 30d

Para cada estratégia: rerank por (score × ticket ÷ CPL), decis qcut 10,
ROAS no D10, D9+D10, D8-D10, D7-D10. Imprime tabela comparativa.
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

# Carrega token
for line in (_V2 / ".env").read_text().splitlines():
    if line.startswith("META_ACCESS_TOKEN="):
        os.environ["META_ACCESS_TOKEN"] = line.split("=", 1)[1].strip()
        break
TOKEN = os.environ["META_ACCESS_TOKEN"]
API = "v23.0"
ACCOUNTS = ["act_188005769808959"]  # Rodolfo Mori — única com dados pro DevClub
CAP_START = "2026-05-25"
CAP_END = "2026-05-31"
SPEND_START = "2026-04-25"  # 30d antes pra rolling 30d
SPEND_END = "2026-05-31"
TICKET_CARTAO = 1997.0
TICKET_BOLETO = 1150.0   # 50% de R$ 2.300


def _classify(c):
    if not isinstance(c, str):
        return "outro"
    cu = c.upper()
    if "LEADHQLB" in cu or "LEAD HQLB" in cu: return "lead_hqlb"
    if "LEADQUALIFIED" in cu: return "leadqualified"
    if "DEVLF" in cu and "CAP" in cu: return "outras_meta_cap"
    return "outro"


def _async_insights(account_id, level, fields, label):
    """Helper: async insight job pra qualquer level (campaign/adset/ad)."""
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
        if st == "Job Completed": break
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
    # Meta retorna uma linha por action_type, todas pro mesmo lead.
    # Pra evitar duplicação: usar apenas "lead" (canônico do gerenciador).
    for a in actions:
        if a.get("action_type") == "lead":
            return float(a.get("value", 0))
    return 0.0


def _pull_campaign_daily():
    """Daily campaign-level: spend + leads."""
    cache = _V2 / "outputs/_cache_meta_campaign_daily_lf56.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    frames = []
    for acc in ACCOUNTS:
        rows = _async_insights(acc, "campaign",
                               ["campaign_id", "campaign_name", "date_start", "spend", "actions"],
                               f"camp {acc}")
        for r in rows:
            frames.append({
                "campaign_id": str(r.get("campaign_id")),
                "campaign_name": r.get("campaign_name"),
                "date": pd.to_datetime(r.get("date_start")).normalize(),
                "spend": float(r.get("spend", 0)),
                "leads": _parse_leads(r.get("actions")),
            })
    df = pd.DataFrame(frames)
    df.to_parquet(cache, index=False)
    return df


def _pull_adset_daily():
    """Daily adset-level: spend + leads."""
    cache = _V2 / "outputs/_cache_meta_adset_daily_lf56.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    frames = []
    for acc in ACCOUNTS:
        rows = _async_insights(acc, "adset",
                               ["adset_id", "adset_name", "campaign_id", "date_start", "spend", "actions"],
                               f"adset {acc}")
        for r in rows:
            frames.append({
                "adset_id": str(r.get("adset_id")),
                "adset_name": r.get("adset_name"),
                "campaign_id": str(r.get("campaign_id")),
                "date": pd.to_datetime(r.get("date_start")).normalize(),
                "spend": float(r.get("spend", 0)),
                "leads": _parse_leads(r.get("actions")),
            })
    df = pd.DataFrame(frames)
    df.to_parquet(cache, index=False)
    return df


def _pull_ad_daily():
    """Daily ad-level: spend + leads + ad_name + campaign_id."""
    cache = _V2 / "outputs/_cache_meta_ad_daily_lf56.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    frames = []
    for acc in ACCOUNTS:
        rows = _async_insights(acc, "ad",
                               ["ad_id", "ad_name", "campaign_id", "date_start", "spend", "actions"],
                               f"ad {acc}")
        for r in rows:
            frames.append({
                "ad_id": str(r.get("ad_id")),
                "ad_name": r.get("ad_name"),
                "campaign_id": str(r.get("campaign_id")),
                "date": pd.to_datetime(r.get("date_start")).normalize(),
                "spend": float(r.get("spend", 0)),
                "leads": _parse_leads(r.get("actions")),
            })
    df = pd.DataFrame(frames)
    df.to_parquet(cache, index=False)
    return df


def _match_adset_via_adname(content, campaign_id, adset_index):
    """Mapping (code, campaign_id) → adset_id.

    code = AD0027 extraído de utm_content. adset_index = dict {(code, cid) → adset_id}.
    Fallback: usa o adset com mais spend dentro do mesmo code, ignorando campanha."""
    if not isinstance(content, str):
        return None
    import re
    m = re.search(r"AD\d{4}", content, re.IGNORECASE)
    if not m:
        return None
    code = m.group(0).upper()
    if campaign_id:
        v = adset_index.get((code, str(campaign_id)))
        if v: return v
    # Fallback: maior spend pro código
    return adset_index.get(("__any__", code))


def _build_adset_index(adset_daily):
    """Constrói {(code, campaign_id) → adset_id} usando SÓ a janela LF56 (25-31/05),
    porque o adset_id ativo no LF56 é o que importa pra atribuir CPL aos leads
    capturados nesse período. Adsets antigos com o mesmo código mas inativos no LF
    seriam atribuídos erroneamente.
    """
    import re
    df = adset_daily[(adset_daily["date"] >= CAP_START) &
                     (adset_daily["date"] <= CAP_END)].copy()
    df["code"] = df["adset_name"].astype(str).str.upper().str.extract(r"(AD\d{4})")
    df = df.dropna(subset=["code"])
    df["campaign_id"] = df["campaign_id"].astype(str)
    agg = df.groupby(["code", "campaign_id", "adset_id"], as_index=False)["spend"].sum()
    best = agg.sort_values("spend", ascending=False).drop_duplicates(["code", "campaign_id"])
    idx = {(r["code"], r["campaign_id"]): r["adset_id"] for _, r in best.iterrows()}
    # Fallback global por code (também só janela LF)
    fb = df.groupby(["code", "adset_id"], as_index=False)["spend"].sum()
    fb_best = fb.sort_values("spend", ascending=False).drop_duplicates("code")
    for _, r in fb_best.iterrows():
        idx[("__any__", r["code"])] = r["adset_id"]
    return idx


def _build_cpl_table(daily, key_col, window):
    """Pra cada (key, date), CPL na janela.
    window = 'agg' | 'd1' | '3d' | '30d'.
    """
    daily = daily.sort_values([key_col, "date"]).copy()
    if window == "agg":
        # Agregado na janela LF inteira (25-31/05). Usa só dias LF.
        win = daily[(daily["date"] >= CAP_START) & (daily["date"] <= CAP_END)]
        agg = win.groupby(key_col).agg(spend=("spend", "sum"), leads=("leads", "sum")).reset_index()
        agg["cpl"] = np.where(agg["leads"] > 0, agg["spend"] / agg["leads"], np.nan)
        return agg[[key_col, "cpl"]]
    # Estratégias temporais — precisam de (key, date) → CPL
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


def _attribute(pool, cpl_table, key_col, window):
    if window == "agg":
        return pool.merge(cpl_table, on=key_col, how="left")
    out = pool.merge(cpl_table, left_on=[key_col, "captura_date"],
                     right_on=[key_col, "date"], how="left").drop(columns=["date"])
    return out


def _decile_summary(df, rank_col, cost_col, label):
    valid = df.dropna(subset=[rank_col, cost_col, "revenue"]).copy()
    valid = valid[valid[cost_col] > 0]
    if valid.empty:
        return {"label": label, "n": 0, "msg": "sem cobertura"}
    valid["decil"] = pd.qcut(valid[rank_col], q=10, labels=False, duplicates="drop") + 1
    g = valid.groupby("decil").agg(
        n_leads=("email", "size"),
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
    # Pool unificado
    frames = []
    for f, who in [("matched_champion", "champion"),
                    ("matched_challenger", "challenger"),
                    ("matched_fora_do_ab", "fora_ab")]:
        d = pd.read_parquet(f"outputs/validation/2026-06/{f}.parquet")
        d["_origem_parquet"] = who
        frames.append(d)
    allp = pd.concat(frames, ignore_index=True, sort=False)
    allp["data_captura"] = pd.to_datetime(allp["data_captura"])
    allp["captura_date"] = allp["data_captura"].dt.normalize()
    allp["classe"] = allp["campaign"].apply(_classify)

    pool = allp[(allp["classe"] == "leadqualified") &
                (allp["captura_date"] >= CAP_START) &
                (allp["captura_date"] <= CAP_END)].copy()

    # campaign_id do nome
    def _cid(s):
        if not isinstance(s, str): return None
        parts = s.split("|"); last = parts[-1].strip()
        return last if last.isdigit() else None
    pool["campaign_id"] = pool["campaign"].apply(_cid)

    # Receita oficial por venda
    def _rev(r):
        if r["converted"] != 1: return 0.0
        sv = r.get("sale_value", 0)
        if pd.isna(sv) or sv == 0: return 0.0
        return TICKET_BOLETO if sv > 2200 else TICKET_CARTAO
    pool["revenue"] = pool.apply(_rev, axis=1)
    # Filtra leads sem score (não dá pra rerankear)
    pool = pool[pool["lead_score"].notna()].copy()

    print(f"Pool LEADQUALIFIED 25-31/05 com score: {len(pool):,} leads, {int(pool['converted'].sum())} vendas, "
          f"R$ {pool['revenue'].sum():,.0f} receita")
    ticket = pool.loc[pool["converted"] == 1, "revenue"].mean()
    print(f"Ticket médio das vendas: R$ {ticket:.0f}")

    # Pull Meta API
    print("\nPuxando Meta API...")
    camp_daily = _pull_campaign_daily()
    print(f"  campanha daily: {len(camp_daily):,} rows, spend total {camp_daily['spend'].sum():,.0f}")
    ad_daily = _pull_ad_daily()
    print(f"  ad daily: {len(ad_daily):,} rows, spend total {ad_daily['spend'].sum():,.0f}")

    # Mapping utm_content → ad_id via ad_name (match exato lower) ou via código DEV-ADxxxx
    ad_index_exact = dict(zip(ad_daily["ad_name"].astype(str).str.lower().dropna(),
                              ad_daily["ad_id"]))
    # Fallback: por código AD0xxx (escolhe ad com mais spend na janela LF)
    import re
    aw = ad_daily[(ad_daily["date"] >= CAP_START) & (ad_daily["date"] <= CAP_END)].copy()
    aw["code"] = aw["ad_name"].astype(str).str.upper().str.extract(r"(AD\d{4})")
    aw = aw.dropna(subset=["code"])
    fb = aw.groupby(["code", "ad_id"], as_index=False)["spend"].sum()
    fb_best = fb.sort_values("spend", ascending=False).drop_duplicates("code")
    ad_index_code = dict(zip(fb_best["code"], fb_best["ad_id"]))

    def _match_ad(content):
        if not isinstance(content, str):
            return None
        v = ad_index_exact.get(content.lower())
        if v:
            return v
        m = re.search(r"AD\d{4}", content, re.IGNORECASE)
        if not m:
            return None
        return ad_index_code.get(m.group(0).upper())

    pool["ad_id"] = pool["content"].apply(_match_ad)
    cov_ad = pool["ad_id"].notna().sum()
    print(f"\nCobertura mapping utm_content → ad_id: {cov_ad:,}/{len(pool):,} "
          f"({cov_ad/len(pool)*100:.1f}%)")

    # Estratégias: campanha × 4 janelas + ad × 4 janelas
    strategies = [
        ("camp_agg",  "campaign_id", camp_daily, "agg"),
        ("camp_d1",   "campaign_id", camp_daily, "d1"),
        ("camp_3d",   "campaign_id", camp_daily, "3d"),
        ("camp_30d",  "campaign_id", camp_daily, "30d"),
        ("ad_agg",    "ad_id",       ad_daily,   "agg"),
        ("ad_d1",     "ad_id",       ad_daily,   "d1"),
        ("ad_3d",     "ad_id",       ad_daily,   "3d"),
        ("ad_30d",    "ad_id",       ad_daily,   "30d"),
    ]

    summaries = []
    # Baseline (rank por score puro, custo = CPL agregado por campanha pra reportar ROAS)
    base_pool = pool.copy()
    cpl_camp_agg = _build_cpl_table(camp_daily, "campaign_id", "agg")
    base_pool = _attribute(base_pool, cpl_camp_agg, "campaign_id", "agg")
    base_pool = base_pool.rename(columns={"cpl": "cpl_base"})
    summaries.append(_decile_summary(base_pool, "lead_score", "cpl_base", "BASELINE (score puro)"))

    for name, key, daily, window in strategies:
        cpl_table = _build_cpl_table(daily, key, window)
        cpl_col = f"cpl_{name}"
        cpl_table = cpl_table.rename(columns={"cpl": cpl_col})
        p = _attribute(pool.copy(), cpl_table, key, window)
        p["roas_v1"] = p["lead_score"] * ticket / p[cpl_col]
        s = _decile_summary(p, "roas_v1", cpl_col, f"V1 {name}")
        cov = p[cpl_col].notna().sum()
        s["cobertura"] = f"{cov}/{len(p)} ({cov/len(p)*100:.0f}%)"
        summaries.append(s)

    print("\n" + "=" * 130)
    print("COMPARATIVA — ROAS por estratégia (ticket médio R$ {:.0f})".format(ticket))
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
