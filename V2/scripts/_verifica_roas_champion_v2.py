"""Verificação ROAS V1 Champion LF56 — CPL do relatório oficial.

CPLs vêm da aba "Investimento x Conversao" do LF56_Conversao_Listas.xlsx
(gerenciador Meta, com 13% imposto incluso). Atribuídos por classe de campanha.

Vendas: caches consolidados de 10/06 (outputs/_lf56_vendas_consolidadas.parquet).
"""
from __future__ import annotations
import sys
from pathlib import Path
_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

import numpy as np
import pandas as pd

PARQUET = _V2 / "outputs/validation/2026-06/matched_champion.parquet"
SALES = _V2 / "outputs/_lf56_vendas_consolidadas.parquet"
CAP_START = "2026-05-25"
CAP_END = "2026-05-31"

# CPLs oficiais do relatório SEM imposto (gasto / leads do gerenciador).
# Champion ML = classe LEADQUALIFIED; Challenger ML = LEADHQLB.
# Controle e Google Ads não usam ML — fora do escopo desta verificação.
CPL_POR_CLASSE = {
    "leadqualified":   9.53,   # Champion ML — R$ 20.169 / 2.117 leads
    "lead_hqlb":       8.81,   # Challenger ML — R$ 2.739 / 311 leads
    "outras_meta_cap": 4.17,   # Controle (sem ML) — R$ 18.922 / 4.542 leads
    "google":          8.04,   # Google Ads
    "outro":           None,
}
# Receita esperada por venda: cartão = ticket_avista; boleto = 50% do contratado
TICKET_CARTAO = 1997.0   # ticket Guru pago à vista
TICKET_BOLETO_50PCT = 1150.0  # 50% do ticket contratado (R$ 2.300)


def _classify(c):
    if not isinstance(c, str):
        return "outro"
    cu = c.upper()
    if "LEADHQLB" in cu or "LEAD HQLB" in cu:
        return "lead_hqlb"
    if "LEADQUALIFIED" in cu:
        return "leadqualified"
    if "GOOGLE" in cu:
        return "google"
    if "DEVLF" in cu and "CAP" in cu:
        return "outras_meta_cap"
    return "outro"


def _norm_email(s):
    return None if pd.isna(s) else str(s).strip().lower()


def _norm_phone(s):
    if pd.isna(s):
        return None
    d = "".join(c for c in str(s) if c.isdigit())
    return d[-8:] if len(d) >= 8 else None


def _norm_name(s):
    return None if pd.isna(s) else " ".join(str(s).strip().lower().split())


def _rematch(pool, sales):
    sales["_email"] = sales["email"].apply(_norm_email)
    sales["_phone"] = sales.get("telefone").apply(_norm_phone) if "telefone" in sales.columns else None
    sales["_name"] = sales.get("nome").apply(_norm_name) if "nome" in sales.columns else None
    if "_boletex_received_value" in sales.columns:
        sales["_real"] = sales["_boletex_received_value"].fillna(sales["sale_value"])
    else:
        sales["_real"] = sales["sale_value"]
    by_e = sales.dropna(subset=["_email"]).drop_duplicates("_email").set_index("_email")
    by_p = sales.dropna(subset=["_phone"]).drop_duplicates("_phone").set_index("_phone")
    by_n = sales.dropna(subset=["_name"]).drop_duplicates("_name").set_index("_name")

    pool["_email"] = pool["email"].apply(_norm_email)
    pool["_phone"] = pool["telefone"].apply(_norm_phone)
    pool["_name"] = pool["nome"].apply(_norm_name)

    conv, sv, real, how = [], [], [], []
    for _, r in pool.iterrows():
        e, p, n = r["_email"], r["_phone"], r["_name"]
        hit = None; meth = None
        if e and e in by_e.index:
            hit = by_e.loc[e]; meth = "email"
        elif p and p in by_p.index:
            hit = by_p.loc[p]; meth = "phone"
        elif n and n in by_n.index:
            hit = by_n.loc[n]; meth = "name"
        if hit is not None:
            conv.append(1); sv.append(float(hit["sale_value"])); real.append(float(hit["_real"])); how.append(meth)
        else:
            conv.append(0); sv.append(0.0); real.append(0.0); how.append(None)
    pool["converted"] = conv
    pool["sale_value"] = sv
    pool["sale_value_realizado"] = real
    pool["match_method"] = how
    return pool


def _decile(df, rank_col, cost_col, label):
    valid = df.dropna(subset=[rank_col, cost_col]).copy()
    valid = valid[valid[cost_col] > 0]
    valid["decil"] = pd.qcut(valid[rank_col], q=10, labels=False, duplicates="drop") + 1
    rev_col = "revenue"
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

    print(f"\n=== {label} ===")
    print(f"n_leads={len(valid):,}  n_vendas={int(valid['converted'].sum())}  "
          f"revenue=R$ {valid[rev_col].sum():,.0f}  cost=R$ {valid[cost_col].sum():,.0f}  "
          f"ROAS_global={valid[rev_col].sum() / valid[cost_col].sum():.3f}x")
    print(" decil | n_leads | n_vendas | revenue   | cost      | ROAS    | conv%  | CPL_mean | score_mean")
    for d in sorted(g.index):
        r = g.loc[d]
        print(f"  D{int(d):02d}   | {int(r.n_leads):>7,} | {int(r.n_vendas):>8} | "
              f"R$ {r.revenue:>7,.0f} | R$ {r.cost:>6,.0f} | {r.roas:>5.2f}x | "
              f"{r.conv_rate*100:>4.2f}% | R$ {r.cpl_mean:>5.2f} | {r.score_mean:.3f}")

    def _top(ds):
        rev = sum(g.loc[d, "revenue"] for d in ds if d in g.index)
        cost = sum(g.loc[d, "cost"] for d in ds if d in g.index)
        n = sum(g.loc[d, "n_vendas"] for d in ds if d in g.index)
        return (rev / cost if cost > 0 else None, int(n))

    return {
        "label": label,
        "roas_global": valid[rev_col].sum() / valid[cost_col].sum(),
        "d10": _top([10]),
        "d9_10": _top([9, 10]),
        "d8_10": _top([8, 9, 10]),
        "d7_10": _top([7, 8, 9, 10]),
    }


def main():
    df = pd.read_parquet(PARQUET)
    df["data_captura"] = pd.to_datetime(df["data_captura"])
    df["captura_date"] = df["data_captura"].dt.normalize()
    df["classe"] = df["campaign"].apply(_classify)
    # FILTRO CHAMPION ML = classe leadqualified + captação 25-31/05 (como o relatório)
    pool = df[
        (df["classe"] == "leadqualified") &
        (df["captura_date"] >= "2026-05-25") &
        (df["captura_date"] <= "2026-05-31")
    ].copy()
    pool["cpl"] = pool["classe"].map(CPL_POR_CLASSE)

    print("=" * 100)
    print("VERIFICAÇÃO ROAS V1 CHAMPION LF56 — CPL OFICIAL DO RELATÓRIO")
    print("=" * 100)
    print(f"\nCPLs por classe (fonte: LF56_Conversao_Listas.xlsx, gerenciador Meta, c/ 13% imposto):")
    for c, v in CPL_POR_CLASSE.items():
        n = (pool["classe"] == c).sum()
        print(f"  {c:<20} CPL=R$ {str(v):<7} | {n:>5,} leads no pool Champion")
    print()
    print(f"Pool: {len(pool):,} leads, cobertura CPL: "
          f"{pool['cpl'].notna().sum():,}/{len(pool):,} ({pool['cpl'].notna().sum()/len(pool)*100:.1f}%)")

    # Receita por regra do relatório: cartão = R$ 1.997, boleto = R$ 1.150
    def _receita(row):
        if row["converted"] != 1:
            return 0.0
        sv = row.get("sale_value", 0)
        if pd.isna(sv) or sv == 0:
            return 0.0
        # boleto tem ticket contratado mais alto (R$ 2.300+); cartão = ~R$ 1.997-2.000
        return TICKET_BOLETO_50PCT if sv > 2200 else TICKET_CARTAO
    pool["revenue"] = pool.apply(_receita, axis=1)
    print(f"Vendas matched no pool Champion ML (LEADQUALIFIED, captação 25-31/05): "
          f"{int(pool['converted'].sum())}")
    n_cartao = ((pool["converted"]==1) & (pool["sale_value"]<=2200)).sum()
    n_boleto = ((pool["converted"]==1) & (pool["sale_value"]>2200)).sum()
    print(f"  cartão: {n_cartao}, boleto: {n_boleto}, receita total: R$ {pool['revenue'].sum():,.0f}")
    print(f"  gasto Champion ML (oficial): R$ {pool['cpl'].sum():,.0f}")

    # Ticket esperado por lead (pra fórmula ROAS V1): receita média por VENDA
    ticket = pool.loc[pool["converted"] == 1, "revenue"].mean()
    print(f"  ticket esperado por venda (pra fórmula V1): R$ {ticket:.2f}")

    pool["roas_v1"] = pool["lead_score"] * ticket / pool["cpl"]

    print("\n" + "=" * 100)
    a = _decile(pool, "lead_score", "cpl", "A) BASELINE — rank por score, custo = CPL oficial por classe")
    b = _decile(pool, "roas_v1", "cpl", "B) ROAS V1 — rank por (score × ticket / CPL oficial)")

    print("\n" + "=" * 100)
    print("RESUMO")
    print("=" * 100)
    print(f"\n{'Cenário':<60} | {'global':>8} | {'D10':>14} | {'D9+D10':>14} | {'D8-D10':>14} | {'D7-D10':>14}")
    print("-" * 142)
    for s in [a, b]:
        def fmt(t): return f"{t[0]:>5.2f}x ({t[1]:>2}v)" if t[0] is not None else "       (n/a)"
        print(f"{s['label'][:60]:<60} | {s['roas_global']:>6.2f}x | "
              f"{fmt(s['d10']):>14} | {fmt(s['d9_10']):>14} | "
              f"{fmt(s['d8_10']):>14} | {fmt(s['d7_10']):>14}")

    print(f"\nDelta (B vs A):")
    for k, name in [("d10", "D10"), ("d9_10", "D9-D10"), ("d8_10", "D8-D10"), ("d7_10", "D7-D10")]:
        if a[k][0] and b[k][0]:
            print(f"  {name}:  {b[k][0]/a[k][0]:.2f}x  ({a[k][0]:.2f}x → {b[k][0]:.2f}x)")


if __name__ == "__main__":
    main()
