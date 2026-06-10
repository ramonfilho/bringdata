"""Verificação empírica: a fórmula (prob × ticket / CPL) melhora ROAS no top decil
do Champion no LF56? E quanto isso muda o ROAS global?

Sequência:
  1. Carrega matched_champion.parquet (saída do pipeline /validate_ml_performance --lf LF56).
  2. Filtra leads capturados na janela oficial LF56 (25-31/05) — onde caem todas
     as vendas matched.
  3. Pull Meta spend diário por campanha 22/05-31/05 (3 dias antes pra D-3).
  4. Constrói duas atribuições de CPL por lead:
       - CPL_D1: spend e leads do dia ANTERIOR à captura, na mesma campanha.
       - CPL_3d: rolling 3 dias anteriores à captura.
  5. Ticket = média realizada das 34 vendas do LF56 Champion.
  6. Reranquia o pool por 3 fórmulas:
       A) baseline = lead_score
       B) ROAS_V1_D1 = lead_score × ticket / CPL_D1
       C) ROAS_V1_3d = lead_score × ticket / CPL_3d
  7. Pra cada fórmula: decil (qcut 10), n_leads, vendas, revenue, custo, ROAS, lift.
  8. ROAS global cumulativo top-X% sob cada fórmula (impacto se cortássemos cauda).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

import json
import os
import time

import numpy as np
import pandas as pd
import requests
import yaml

# Carrega .env manualmente (dotenv falha com $ no ASAAS_API_KEY)
for line in (_V2 / ".env").read_text().splitlines():
    if line.startswith("META_ACCESS_TOKEN="):
        os.environ["META_ACCESS_TOKEN"] = line.split("=", 1)[1].strip()
        break
TOKEN = os.environ["META_ACCESS_TOKEN"]
API_VERSION = "v23.0"

PARQUET = _V2 / "outputs/validation/2026-06/matched_champion.parquet"
CONFIG = _V2 / "configs/clients/devclub.yaml"
CAP_START = "2026-05-25"
CAP_END = "2026-05-31"
SPEND_START = "2026-05-22"  # 3 dias antes pra D-3
SPEND_END = "2026-05-31"


def _extract_campaign_id(campaign_str: str) -> str | None:
    """campaign vem como 'DEVLF | CAP | ... | 2026-05-25|120244621534140390'
    O id da campanha Meta fica após o último '|'."""
    if not isinstance(campaign_str, str):
        return None
    parts = campaign_str.split("|")
    last = parts[-1].strip()
    return last if last.isdigit() else None


def _norm_email(s):
    if pd.isna(s):
        return None
    return str(s).strip().lower()


def _norm_phone(s):
    if pd.isna(s):
        return None
    digits = "".join(c for c in str(s) if c.isdigit())
    if len(digits) < 8:
        return None
    return digits[-8:]  # match por últimos 8 dígitos (DDD pode variar)


def _norm_name(s):
    if pd.isna(s):
        return None
    return " ".join(str(s).strip().lower().split())


def _load_pool() -> pd.DataFrame:
    df = pd.read_parquet(PARQUET)
    df["data_captura"] = pd.to_datetime(df["data_captura"])
    df["captura_date"] = df["data_captura"].dt.normalize()
    mask = (df["captura_date"] >= CAP_START) & (df["captura_date"] <= CAP_END)
    pool = df[mask].copy()
    pool["campaign_id"] = pool["campaign"].apply(_extract_campaign_id)
    pool = pool[pool["campaign_id"].notna()].copy()
    return pool


def _rematch_with_fresh_sales(pool: pd.DataFrame) -> pd.DataFrame:
    """Re-attribui converted/sale_value/sale_value_realizado usando os caches
    atualizados de hoje (Guru fechamento + Hotmart + Asaas + Boletex,
    semana de carrinho 08-14/06).

    Match cascata: email → telefone (últimos 8) → nome normalizado.
    Vendas com prioridade Guru fechamento > Boletex > Hotmart > Asaas
    (Guru fechamento é o snapshot mais atualizado das vendas reais).
    """
    sales = pd.read_parquet(_V2 / "outputs/_lf56_vendas_consolidadas.parquet")

    sales["_email"] = sales["email"].apply(_norm_email)
    sales["_phone"] = sales.get("telefone").apply(_norm_phone) if "telefone" in sales.columns else None
    sales["_name"] = sales.get("nome").apply(_norm_name) if "nome" in sales.columns else None
    # Boletex tem received_value (caixa real), demais usam sale_value
    if "_boletex_received_value" in sales.columns:
        sales["_realizado"] = sales["_boletex_received_value"].fillna(sales["sale_value"])
    else:
        sales["_realizado"] = sales["sale_value"]

    by_email = sales.dropna(subset=["_email"]).drop_duplicates("_email").set_index("_email")
    by_phone = sales.dropna(subset=["_phone"]).drop_duplicates("_phone").set_index("_phone")
    by_name = sales.dropna(subset=["_name"]).drop_duplicates("_name").set_index("_name")

    pool["_email"] = pool["email"].apply(_norm_email)
    pool["_phone"] = pool["telefone"].apply(_norm_phone)
    pool["_name"] = pool["nome"].apply(_norm_name)

    converted, sv, svr, method = [], [], [], []
    for _, row in pool.iterrows():
        hit = None; how = None
        e, p, n = row["_email"], row["_phone"], row["_name"]
        if e and e in by_email.index:
            hit = by_email.loc[e]; how = "email"
        elif p and p in by_phone.index:
            hit = by_phone.loc[p]; how = "phone"
        elif n and n in by_name.index:
            hit = by_name.loc[n]; how = "name"
        if hit is not None:
            converted.append(1)
            sv.append(float(hit["sale_value"]))
            svr.append(float(hit["_realizado"]))
            method.append(how)
        else:
            converted.append(0); sv.append(0.0); svr.append(0.0); method.append(None)
    pool["converted"] = converted
    pool["sale_value"] = sv
    pool["sale_value_realizado"] = svr
    pool["match_method"] = method
    return pool


ACCOUNTS = [
    "act_188005769808959",  # Rodolfo Mori
    "act_786790755803474",  # Gestor de IA
]


def _async_insights(account_id: str) -> list[dict]:
    """Kicka job assíncrono, espera completar, pagina results.

    Daily campaign-level: spend + actions (leads count)."""
    base = f"https://graph.facebook.com/{API_VERSION}/{account_id}/insights"
    body = {
        "access_token": TOKEN,
        "time_range": json.dumps({"since": SPEND_START, "until": SPEND_END}),
        "level": "campaign",
        "time_increment": 1,
        "fields": "campaign_id,campaign_name,date_start,spend,actions",
    }
    r = requests.post(base, data=body, timeout=60)
    r.raise_for_status()
    run_id = r.json().get("report_run_id")
    if not run_id:
        raise RuntimeError(f"Sem report_run_id: {r.text}")
    # Polling
    status_url = f"https://graph.facebook.com/{API_VERSION}/{run_id}"
    for _ in range(120):
        s = requests.get(status_url, params={"access_token": TOKEN}, timeout=30).json()
        st = s.get("async_status")
        pct = s.get("async_percent_completion", 0)
        if st == "Job Completed":
            break
        if st in ("Job Failed", "Job Skipped"):
            raise RuntimeError(f"Async job falhou: {s}")
        time.sleep(2)
    # Paginar resultados
    url = f"https://graph.facebook.com/{API_VERSION}/{run_id}/insights"
    rows = []
    params = {"access_token": TOKEN, "limit": 500}
    while url:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        rows.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}
    return rows


def _parse_leads(actions: list[dict] | None) -> float:
    """Soma todas as ações de tipo Lead/LeadQualified."""
    if not actions:
        return 0.0
    keys = {"lead", "offsite_conversion.fb_pixel_lead", "onsite_conversion.lead_grouped"}
    total = 0.0
    for a in actions or []:
        if a.get("action_type") in keys:
            total += float(a.get("value", 0))
    return total


def _pull_meta_spend() -> pd.DataFrame:
    """Pull daily spend per campaign pelas duas contas DevClub.

    Retorna: campaign_id, campaign_name, date, spend_dia, leads_dia."""
    frames = []
    for acc in ACCOUNTS:
        try:
            rows = _async_insights(acc)
            if not rows:
                print(f"  {acc}: vazio.")
                continue
            d = pd.DataFrame([{
                "campaign_id": r.get("campaign_id"),
                "campaign_name": r.get("campaign_name"),
                "date": r.get("date_start"),
                "spend_dia": float(r.get("spend", 0)),
                "leads_dia": _parse_leads(r.get("actions")),
            } for r in rows])
            d["date"] = pd.to_datetime(d["date"]).dt.normalize()
            d["campaign_id"] = d["campaign_id"].astype(str)
            d["account_id"] = acc
            frames.append(d)
            print(f"  {acc}: {len(d):,} linhas, spend R$ {d['spend_dia'].sum():,.0f}, "
                  f"leads {int(d['leads_dia'].sum()):,}")
        except Exception as e:
            print(f"  {acc} falhou: {e}")
    if not frames:
        raise RuntimeError("Nenhuma conta Meta retornou dados.")
    return pd.concat(frames, ignore_index=True)


def _attribute_cpl(pool: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Atribui CPL_D1 e CPL_3d a cada lead.

    CPL_D1[lead] = spend(campaign, captura_date-1d) / leads(campaign, captura_date-1d)
    CPL_3d[lead] = sum spend nos 3 dias anteriores / sum leads nos 3 dias anteriores
    """
    daily = daily.sort_values(["campaign_id", "date"]).copy()
    # Para cada campanha, gera índice diário cheio e calcula rolling 1d e 3d ANTERIORES
    rows = []
    for cid, g in daily.groupby("campaign_id"):
        g = g.set_index("date")
        idx = pd.date_range(g.index.min(), g.index.max(), freq="D")
        g = g.reindex(idx).fillna({"spend_dia": 0.0, "leads_dia": 0.0})
        spend_d1 = g["spend_dia"].shift(1)
        leads_d1 = g["leads_dia"].shift(1)
        spend_3d = g["spend_dia"].rolling(3, min_periods=1, closed="left").sum()
        leads_3d = g["leads_dia"].rolling(3, min_periods=1, closed="left").sum()
        cpl_d1 = np.where(leads_d1 > 0, spend_d1 / leads_d1, np.nan)
        cpl_3d = np.where(leads_3d > 0, spend_3d / leads_3d, np.nan)
        rows.append(pd.DataFrame({
            "campaign_id": cid,
            "captura_date": idx,
            "cpl_d1": cpl_d1,
            "cpl_3d": cpl_3d,
            "spend_d1": spend_d1.values,
            "leads_d1": leads_d1.values,
        }))
    cpl_table = pd.concat(rows, ignore_index=True)

    pool = pool.merge(cpl_table, on=["campaign_id", "captura_date"], how="left")
    return pool


def _decile_report(df: pd.DataFrame, rank_col: str, cost_col: str, ticket: float, label: str):
    """Imprime tabela de decil e devolve dict com KPIs do top."""
    valid = df.dropna(subset=[rank_col, cost_col]).copy()
    valid = valid[valid[cost_col] > 0]
    if valid.empty:
        print(f"\n[{label}] sem dados válidos.")
        return None

    valid["decil"] = pd.qcut(valid[rank_col], q=10, labels=False, duplicates="drop") + 1

    rev_col = "sale_value_realizado"
    g = valid.groupby("decil").agg(
        n_leads=("email", "size"),
        n_vendas=("converted", "sum"),
        revenue=(rev_col, "sum"),
        cost=(cost_col, "sum"),
        cpl_mean=(cost_col, "mean"),
        score_mean=("lead_score", "mean"),
    )
    g["roas"] = np.where(g["cost"] > 0, g["revenue"] / g["cost"], 0.0)
    g["conv_rate"] = g["n_vendas"] / g["n_leads"]
    g["lift_vendas"] = g["n_vendas"] / valid["converted"].sum() * 10 if valid["converted"].sum() > 0 else 0
    print(f"\n=== {label} (rerank por '{rank_col}', cost = '{cost_col}') ===")
    print(f"n_leads={len(valid):,}  n_vendas={int(valid['converted'].sum())}  "
          f"revenue=R${valid[rev_col].sum():,.0f}  cost=R${valid[cost_col].sum():,.0f}  "
          f"ROAS_global={valid[rev_col].sum() / valid[cost_col].sum():.3f}x")
    print(" decil | n_leads | n_vendas | revenue   | cost     | ROAS    | conv%   | lift vendas")
    for d in sorted(g.index):
        r = g.loc[d]
        print(f"  D{int(d):02d}   | {int(r.n_leads):>7,} | {int(r.n_vendas):>8} | "
              f"R${r.revenue:>8,.0f} | R${r.cost:>6,.0f} | {r.roas:>5.2f}x | "
              f"{r.conv_rate*100:>5.2f}% | {r.lift_vendas:>5.2f}x")

    # Cumulativo top-down
    cum = valid.sort_values(rank_col, ascending=False).copy()
    cum["cum_rev"] = cum[rev_col].cumsum()
    cum["cum_cost"] = cum[cost_col].cumsum()
    cum["cum_roas"] = cum["cum_rev"] / cum["cum_cost"]
    cum["pct"] = (np.arange(len(cum)) + 1) / len(cum)
    print("\n  ROAS cumulativo top-X% (sob essa fórmula de ranking):")
    for pct in [0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 1.00]:
        i = int(len(cum) * pct) - 1
        if i < 0:
            continue
        r = cum.iloc[i]
        print(f"    top {pct*100:>4.0f}% | n={int(np.ceil(len(cum)*pct)):>5,} | "
              f"rev=R${r.cum_rev:>8,.0f} | cost=R${r.cum_cost:>6,.0f} | ROAS={r.cum_roas:.3f}x")

    def _roas_top(ds):
        rev = sum(g.loc[d, "revenue"] for d in ds if d in g.index)
        cost = sum(g.loc[d, "cost"] for d in ds if d in g.index)
        vendas = sum(g.loc[d, "n_vendas"] for d in ds if d in g.index)
        return float(rev / cost) if cost > 0 else None, int(vendas)

    r10, v10 = _roas_top([10])
    r9_10, v9_10 = _roas_top([9, 10])
    r8_10, v8_10 = _roas_top([8, 9, 10])
    r7_10, v7_10 = _roas_top([7, 8, 9, 10])

    return {
        "label": label,
        "n_total": len(valid),
        "vendas_total": int(valid["converted"].sum()),
        "rev_total": float(valid[rev_col].sum()),
        "cost_total": float(valid[cost_col].sum()),
        "roas_global": float(valid[rev_col].sum() / valid[cost_col].sum()),
        "roas_d10": r10, "vendas_d10": v10,
        "roas_d9_d10": r9_10, "vendas_d9_d10": v9_10,
        "roas_d8_d10": r8_10, "vendas_d8_d10": v8_10,
        "roas_d7_d10": r7_10, "vendas_d7_d10": v7_10,
    }


def main():
    print("=" * 100)
    print("Verificação ROAS V1 — Champion LF56 (captura 25-31/05)")
    print("=" * 100)

    pool = _load_pool()
    print(f"\nPool Champion LF56: {len(pool):,} leads")
    print(f"  Vendas matched (pipeline antigo de 09/06): {int(pool['converted'].sum())}")
    pool = _rematch_with_fresh_sales(pool)
    print(f"  Vendas matched (caches frescos de 10/06):   {int(pool['converted'].sum())}")
    print(f"  Métodos de match:", pool["match_method"].value_counts().to_dict())
    ticket = pool.loc[pool["converted"] == 1, "sale_value_realizado"].mean()
    print(f"Ticket realizado médio (das vendas matched): R$ {ticket:.2f}")

    print(f"\nPuxando Meta spend diário {SPEND_START}..{SPEND_END}...")
    daily = _pull_meta_spend()
    print(f"  {len(daily):,} (campanha, dia) pares; "
          f"spend total na janela: R$ {daily['spend_dia'].sum():,.0f}")

    pool = _attribute_cpl(pool, daily)
    # CPL agregado por campanha na janela 25-31/05 (método antigo, suspeito de gerar
    # o 7.16x que eu havia reportado antes)
    agg = (
        daily[(daily["date"] >= CAP_START) & (daily["date"] <= CAP_END)]
        .groupby("campaign_id", as_index=False)
        .agg(spend_total=("spend_dia", "sum"), leads_total=("leads_dia", "sum"))
    )
    agg["cpl_agg"] = np.where(agg["leads_total"] > 0, agg["spend_total"] / agg["leads_total"], np.nan)
    pool = pool.merge(agg[["campaign_id", "cpl_agg"]], on="campaign_id", how="left")
    cov_d1 = pool["cpl_d1"].notna().sum()
    cov_3d = pool["cpl_3d"].notna().sum()
    cov_agg = pool["cpl_agg"].notna().sum()
    print(f"Cobertura CPL_AGG (janela toda): {cov_agg:,}/{len(pool):,} ({cov_agg/len(pool)*100:.1f}%)")
    print(f"\nCobertura CPL_D1: {cov_d1:,}/{len(pool):,} ({cov_d1/len(pool)*100:.1f}%)")
    print(f"Cobertura CPL_3d: {cov_3d:,}/{len(pool):,} ({cov_3d/len(pool)*100:.1f}%)")
    print(f"CPL_D1 mediana = R$ {pool['cpl_d1'].median():.2f} | "
          f"CPL_3d mediana = R$ {pool['cpl_3d'].median():.2f}")

    # Fórmulas de ranking
    pool["roas_v1_d1"] = pool["lead_score"] * ticket / pool["cpl_d1"]
    pool["roas_v1_3d"] = pool["lead_score"] * ticket / pool["cpl_3d"]
    pool["roas_v1_agg"] = pool["lead_score"] * ticket / pool["cpl_agg"]

    # Pra ranking baseline (score puro) precisamos do mesmo custo p/ comparação justa.
    # Vamos usar CPL_D1 como cost denominator no baseline também (mesma escala).
    print("\n" + "=" * 100)
    a = _decile_report(pool, "lead_score", "cpl_d1", ticket, "A) Baseline — rank por score, custo D-1")
    b = _decile_report(pool, "roas_v1_d1", "cpl_d1", ticket, "B) ROAS V1 — rank por score×ticket/CPL_D1")
    c = _decile_report(pool, "roas_v1_3d", "cpl_3d", ticket, "C) ROAS V1 — rank por score×ticket/CPL_3d")
    d = _decile_report(pool, "roas_v1_agg", "cpl_agg", ticket, "D) ROAS V1 AGG — rank por score×ticket/CPL_agg_LF56 (método antigo, p/ checagem)")

    print("\n" + "=" * 100)
    print("RESUMO")
    print("=" * 100)
    print(f"\n{'Cenário':<55} | {'global':>7} | {'D10':>14} | {'D9+D10':>14} | {'D8-D10':>14} | {'D7-D10':>14}")
    print("-" * 130)
    for s in [a, b, c, d]:
        if s is None:
            continue
        f = lambda r, v: f"{r:>5.2f}x ({v:>2}v)" if r is not None else "       (n/a)"
        print(f"{s['label'][:55]:<55} | {s['roas_global']:>5.2f}x | "
              f"{f(s['roas_d10'], s['vendas_d10']):>14} | "
              f"{f(s['roas_d9_d10'], s['vendas_d9_d10']):>14} | "
              f"{f(s['roas_d8_d10'], s['vendas_d8_d10']):>14} | "
              f"{f(s['roas_d7_d10'], s['vendas_d7_d10']):>14}")
    if a and b:
        print(f"\nDelta D10:    A→B (CPL_D1): {b['roas_d10']/a['roas_d10']:.2f}x | A→C (CPL_3d): {c['roas_d10']/a['roas_d10']:.2f}x" if a['roas_d10'] else "")
        if a['roas_d9_d10'] and b['roas_d9_d10']:
            print(f"Delta D9-D10: A→B (CPL_D1): {b['roas_d9_d10']/a['roas_d9_d10']:.2f}x | A→C (CPL_3d): {c['roas_d9_d10']/a['roas_d9_d10']:.2f}x")
        if a['roas_d8_d10'] and b['roas_d8_d10']:
            print(f"Delta D8-D10: A→B (CPL_D1): {b['roas_d8_d10']/a['roas_d8_d10']:.2f}x | A→C (CPL_3d): {c['roas_d8_d10']/a['roas_d8_d10']:.2f}x")


if __name__ == "__main__":
    main()
