#!/usr/bin/env python3
"""
Rebuild da análise sobre a aba 'Comparação ML' (fonte VALIDADA, consistente com o
gasto Meta) — substitui o caminho Detalhes, que super-creditava o grupo maior.

Por LF e janela (semana/60d), lê do 1º bloco da Comparação ML, por grupo:
  gasto, leads, conversões, receita (contratado), roas.

Casa arquivo->janela pela data fim no nome ("DD:MM a DD:MM").
"""
import sys, re
from pathlib import Path
from datetime import datetime, timedelta
import openpyxl
import pandas as pd
import yaml

BASE = Path("/Users/ramonmoreira/bring_data.worktrees/ab-arm/V2")
V = BASE / "outputs/validation"
OUT = BASE / "analise_valor_ml"
L = yaml.safe_load(open(BASE / "configs/launches.yaml"))
LFS = ['LF40','LF41','LF42','LF43','LF44','LF45','LF46','LF47','LF48','LF49',
       'LF50','LF51','LF52','LF53','LF54','LF55','LF56','DEV19']
OUTLIERS = ['LF40','LF41','LF53']


def _end_from_name(name, vendas_start):
    # "LF44 - 09:02 a 10:04.xlsx" -> end date (infer year from vendas_start)
    m = re.search(r"a (\d{2}):(\d{2})\.xlsx$", name)
    if not m:
        return None
    dd, mm = int(m.group(1)), int(m.group(2))
    yr = vendas_start.year
    cand = datetime(yr, mm, dd)
    if cand < vendas_start - timedelta(days=5):   # cruzou o ano
        cand = datetime(yr + 1, mm, dd)
    return cand


def files_for(lf):
    vs = datetime.fromisoformat(str(L[lf]['vendas_start']))
    ve = datetime.fromisoformat(str(L[lf]['vendas_end']))
    e60 = vs + timedelta(days=60)
    cands = list(V.glob(f"{lf} - *.xlsx")) + list(V.glob(f"*/{lf} - *.xlsx"))
    week = wk_d = sixty = sx_d = None
    for p in cands:
        end = _end_from_name(p.name, vs)
        if end is None:
            continue
        dw = abs((end - ve).days)
        d6 = abs((end - e60).days)
        if dw <= d6:
            if week is None or dw < wk_d:
                week, wk_d = p, dw
        else:
            if sixty is None or d6 < sx_d:
                sixty, sx_d = p, d6
    return week, sixty


def read_comparacao(path):
    """1º bloco da Comparação ML -> {grupo: {gasto,leads,conv,receita,roas}}."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Comparação ML"]
    grid = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    hdr = None
    colmap = {}
    for i, row in enumerate(grid):
        cells = [str(c).strip() if c is not None else "" for c in row]
        if cells and cells[0] == "Métrica" and any(c.startswith("Champion") for c in cells):
            hdr = i
            for j, c in enumerate(cells):
                lc = c.lower()
                if lc.startswith("champion"):
                    colmap[j] = "Champion"
                elif lc.startswith("challenger"):
                    colmap[j] = "Challenger"
                elif lc.startswith("controle"):
                    colmap[j] = "Controle"
            break
    res = {g: {} for g in colmap.values()}
    if hdr is None:
        return res
    keymap = {"gasto": "gasto", "leads": "leads", "conversões": "conv",
              "conversoes": "conv", "receita": "receita", "roas": "roas"}
    for row in grid[hdr + 1: hdr + 16]:
        c0 = str(row[0]).strip().lower() if row and row[0] is not None else ""
        if c0 in keymap:
            for j, g in colmap.items():
                try:
                    res[g][keymap[c0]] = float(row[j])
                except (TypeError, ValueError):
                    pass
    return res


def main():
    rows = []
    for lf in LFS:
        wk, sx = files_for(lf)
        for jan, p in [("semana", wk), ("60d", sx)]:
            if p is None:
                continue
            comp = read_comparacao(p)
            for g, d in comp.items():
                if not d:
                    continue
                rows.append(dict(lf=lf, janela=jan, grupo=g, arquivo=p.name,
                                 gasto=d.get("gasto", 0), leads=d.get("leads", 0),
                                 conv=d.get("conv", 0), receita=d.get("receita", 0),
                                 roas=d.get("roas", float("nan"))))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "comparacao_grupos.csv", index=False)

    def agg(jan, drop_outliers=True, drop_lf44=False, only_with_ctrl=False):
        d = df[df.janela == jan].copy()
        if drop_outliers:
            d = d[~d.lf.isin(OUTLIERS)]
        if drop_lf44:
            d = d[d.lf != "LF44"]
        # LFs com controle
        ctrl_lfs = set(d[(d.grupo == "Controle") & (d.gasto > 0)].lf)
        base = d[d.lf.isin(ctrl_lfs)] if only_with_ctrl else d
        ml = base[base.grupo.isin(["Champion", "Challenger"])]
        ct = d[(d.grupo == "Controle") & d.lf.isin(ctrl_lfs)]
        ml_rev, ml_sp = ml.receita.sum(), ml.gasto.sum()
        c_rev, c_sp = ct.receita.sum(), ct.gasto.sum()
        r_ml = ml_rev / ml_sp if ml_sp else float("nan")
        r_c = c_rev / c_sp if c_sp else float("nan")
        dn = ml_rev - ml_sp * r_c
        return dict(jan=jan, n_lf=base.lf.nunique(), n_ctrl_lf=len(ctrl_lfs),
                    roas_ml=r_ml, roas_ctrl=r_c, mais_pct=(r_ml / r_c - 1) * 100,
                    ml_sp=ml_sp, dinheiro_novo=dn)

    print("\n=== REBUILD sobre Comparação ML (contratado) — sem outliers ===")
    print("PORTFÓLIO (baseline=controle pooled aplicado a todo ML):")
    for drop44 in (False, True):
        tag = "SEM LF44" if drop44 else "COM LF44"
        for jan in ("semana", "60d"):
            a = agg(jan, drop_lf44=drop44)
            print(f"  {tag:9} {jan:7} | LFs={a['n_lf']:2} (ctrl={a['n_ctrl_lf']}) | "
                  f"ROAS_ML={a['roas_ml']:.2f} ctrl={a['roas_ctrl']:.2f} | "
                  f"+{a['mais_pct']:.0f}% | gasto_ML=R${a['ml_sp']:,.0f} | "
                  f"DINHEIRO NOVO=R${a['dinheiro_novo']:,.0f}")
    print("\nMEDIDO (só os LFs com controle interno):")
    for jan in ("semana", "60d"):
        a = agg(jan, only_with_ctrl=True)
        print(f"  {jan:7} | LFs c/ctrl={a['n_ctrl_lf']} | ROAS_ML={a['roas_ml']:.2f} "
              f"ctrl={a['roas_ctrl']:.2f} | +{a['mais_pct']:.0f}% | DINHEIRO NOVO=R${a['dinheiro_novo']:,.0f}")
    print(f"\n  -> comparacao_grupos.csv ({len(df)} linhas)")


if __name__ == "__main__":
    main()
