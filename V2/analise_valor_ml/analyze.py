#!/usr/bin/env python3
"""
Análise de valor de ML — contrafactual por grupo, sobre a fonte única (resolver).

Eixos:
  base   = contratado | recebido
  janela = semana (7d) | 60d
  cenário= piso (exclui órfãs) | teto (distribui órfãs nos grupos Meta)   [só na semana]

Método (por LF):
  - grupos Meta = Champion / Challenger / Controle  (resolver)
  - CORTE DE COORTE: vendas atribuídas com data_captura na janela de captação do LF
    (remove vendas que casaram com leads de outros lançamentos — anti-dupla-contagem)
  - 60d: só coorte (órfãs nos 60d = ruído de fundo, fora)
  - semana: coorte + banda das órfãs (órfã logo após lançamento = comprador real não-rastreado)
  - gasto por grupo = captação (Comparação ML)

Métricas:
  - ROAS_grupo = receita / gasto
  - ROAS a mais % = ROAS_ML / ROAS_Controle - 1     (Champion, Challenger, e ML pool)
  - Dinheiro novo R$ = receita_ML - gasto_ML * ROAS_Controle
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import yaml

BASE = Path("/Users/ramonmoreira/bring_data.worktrees/ab-arm/V2")
OUT = BASE / "analise_valor_ml"
L = yaml.safe_load(open(BASE / "configs/launches.yaml"))

META = ["Champion", "Challenger", "Controle"]
ML = ["Champion", "Challenger"]
ORPHAN = ["None", "Indeterminado", ""]      # desconhecido p/ banda
OUTLIERS = ["LF40", "LF41", "LF53"]  # removidos só na análise agregada


def _d(x):
    return datetime.fromisoformat(str(x)[:19]) if x is not None and str(x) else None


def lf_windows(lf):
    c = L[lf]
    cs = _d(c["cap_start"])
    ce = _d(c["cap_end"]) + timedelta(days=1)   # exclusivo
    vs = _d(c["vendas_start"])
    return cs, ce, vs


def revenue_by_group(df, base):
    return df.groupby("grupo")[base].sum().to_dict()


def roas(rev, spend):
    return (rev / spend) if spend else float("nan")


def analyze_lf(sales, spend_df, lf, base, janela_dias):
    cs, ce, vs = lf_windows(lf)
    we = vs + timedelta(days=janela_dias)
    d = sales[sales.lf == lf].copy()
    d["dc"] = pd.to_datetime(d.data_captura)
    d["dv"] = pd.to_datetime(d.data_venda)

    # atribuídas Meta + coorte + janela
    meta = d[d.grupo.isin(META)]
    coorte = meta[(meta.dc >= cs) & (meta.dc < ce)]
    win = coorte[(coorte.dv >= vs) & (coorte.dv < we)]
    rev = revenue_by_group(win, base)

    sp = spend_df[spend_df.lf == lf].set_index("grupo")["gasto"].to_dict()

    # órfãs na semana (p/ banda) — só janela=7
    orf = 0.0
    if janela_dias == 7:
        orw = d[d.grupo.isin(ORPHAN) & (d.dv >= vs) & (d.dv < we)]
        orf = float(orw[base].sum())

    out = {}
    for cenario in (["piso", "teto"] if janela_dias == 7 else ["piso"]):
        rg = dict(rev)
        if cenario == "teto" and orf > 0:
            ml_total = sum(rg.get(g, 0) for g in META)
            if ml_total > 0:
                for g in META:
                    rg[g] = rg.get(g, 0) + orf * rg.get(g, 0) / ml_total
        rec_ctrl = rg.get("Controle", 0.0)
        sp_ctrl = sp.get("Controle", 0.0)
        r_ctrl = roas(rec_ctrl, sp_ctrl)
        sp_ml = sum(sp.get(g, 0) for g in ML)
        rec_ml = sum(rg.get(g, 0) for g in ML)
        r_ml = roas(rec_ml, sp_ml)
        row = dict(
            lf=lf, base=base, janela=f"{janela_dias}d", cenario=cenario,
            n_champ=int((win.grupo == "Champion").sum()),
            n_chall=int((win.grupo == "Challenger").sum()),
            n_ctrl=int((win.grupo == "Controle").sum()),
            rec_champ=rg.get("Champion", 0.0), rec_chall=rg.get("Challenger", 0.0),
            rec_ctrl=rec_ctrl, rec_ml=rec_ml, orf_semana=orf,
            sp_champ=sp.get("Champion", 0.0), sp_chall=sp.get("Challenger", 0.0),
            sp_ctrl=sp_ctrl, sp_ml=sp_ml,
            roas_champ=roas(rg.get("Champion", 0.0), sp.get("Champion", 0.0)),
            roas_chall=roas(rg.get("Challenger", 0.0), sp.get("Challenger", 0.0)),
            roas_ctrl=r_ctrl, roas_ml=r_ml,
        )
        # ROAS a mais % e dinheiro novo (precisa Controle válido)
        if r_ctrl and r_ctrl == r_ctrl and r_ctrl > 0:
            row["roas_mais_champ_%"] = (row["roas_champ"] / r_ctrl - 1) * 100 if row["roas_champ"] == row["roas_champ"] else None
            row["roas_mais_chall_%"] = (row["roas_chall"] / r_ctrl - 1) * 100 if row["roas_chall"] == row["roas_chall"] else None
            row["roas_mais_ml_%"] = (r_ml / r_ctrl - 1) * 100 if r_ml == r_ml else None
            row["dinheiro_novo"] = rec_ml - sp_ml * r_ctrl
        else:
            row["roas_mais_champ_%"] = row["roas_mais_chall_%"] = row["roas_mais_ml_%"] = None
            row["dinheiro_novo"] = None
        out[cenario] = row
    return list(out.values())


def main():
    sales = pd.read_parquet(OUT / "sales_tidy.parquet")
    spend_df = pd.read_csv(OUT / "spend_grupo.csv")
    lfs = sorted(sales.lf.unique(), key=lambda x: (x[:3], int("".join(filter(str.isdigit, x)) or 0)))
    rows = []
    for lf in lfs:
        for base in ("contratado", "recebido"):
            for jd in (7, 60):
                rows.extend(analyze_lf(sales, spend_df, lf, base, jd))
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "resultados.csv", index=False)
    res["outlier"] = res.lf.isin(OUTLIERS)
    # resumo: recebido, semana, piso, sem outliers
    print("\n=== RECEBIDO | SEMANA | PISO (sem outliers) ===")
    v = res[(res.base == "recebido") & (res.janela == "7d") & (res.cenario == "piso") & (~res.outlier)]
    cols = ["lf", "n_champ", "n_chall", "n_ctrl", "roas_champ", "roas_chall", "roas_ctrl", "roas_mais_ml_%", "dinheiro_novo"]
    with pd.option_context("display.width", 200, "display.max_columns", 30, "display.float_format", lambda x: f"{x:,.2f}"):
        print(v[cols].to_string(index=False))
    print(f"\n  -> resultados.csv ({len(res)} linhas)")


if __name__ == "__main__":
    main()
