"""
Verifica se a conversão de cada célula (ocupação, idade) é estável entre LFs.

Usa os parquets em files/validation/backtest_historico/<LF>/base_with_tmb.parquet
que já vêm com leads + matching contra Guru/TMB/Hotmart/Asaas.

Saída: stdout com tabela conv_rate por LF para Estudante, 18-24, células-chave,
+ desvio padrão entre LFs e flag "estável / instável".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.perfil_audiencia import UNIFICATION, normalize_series

HIST_DIR = REPO_ROOT / 'files' / 'validation' / 'backtest_historico'
LFS = ['LF46', 'LF47', 'LF48', 'LF49', 'LF50', 'LF51', 'LF52']

COL_IDADE    = 'Qual a sua idade?'
COL_OCUPACAO = 'O que você faz atualmente?'


def load_lf(lf: str) -> pd.DataFrame:
    p = HIST_DIR / lf / 'base_with_tmb.parquet'
    df = pd.read_parquet(p)
    df['lf'] = lf
    df['idade']    = normalize_series(df[COL_IDADE],    COL_IDADE)
    df['ocupacao'] = normalize_series(df[COL_OCUPACAO], COL_OCUPACAO)
    return df[['lf', 'idade', 'ocupacao', 'converted', 'sale_value']]


def conv_table(df: pd.DataFrame, group_col: str, focus_values: list[str]) -> pd.DataFrame:
    rows = []
    for lf, sub in df.groupby('lf'):
        for val in focus_values + ['__overall__']:
            if val == '__overall__':
                seg = sub
                label = 'TODOS'
            else:
                seg = sub[sub[group_col] == val]
                label = val
            n = len(seg)
            c = int(seg['converted'].sum()) if n else 0
            cr = c / n * 100 if n else float('nan')
            tk = seg.loc[seg['converted'], 'sale_value'].mean() if c else float('nan')
            rev_per_lead = c / n * (tk if c else 0) if n else float('nan')
            rows.append({'lf': lf, 'segmento': label, 'n_leads': n,
                         'vendas': c, 'conv_%': cr, 'ticket': tk,
                         'rev/lead': rev_per_lead})
    return pd.DataFrame(rows)


def summary(tbl: pd.DataFrame) -> pd.DataFrame:
    out = []
    for seg, sub in tbl.groupby('segmento'):
        # ignora LF com n<50 para não poluir desvio
        sub_valid = sub[sub['n_leads'] >= 50]
        out.append({
            'segmento': seg,
            'n_LFs_valid': len(sub_valid),
            'n_total':     int(sub_valid['n_leads'].sum()),
            'conv_min':    sub_valid['conv_%'].min(),
            'conv_med':    sub_valid['conv_%'].median(),
            'conv_max':    sub_valid['conv_%'].max(),
            'conv_std':    sub_valid['conv_%'].std(),
            'conv_cv':     sub_valid['conv_%'].std() / sub_valid['conv_%'].mean()
                           if sub_valid['conv_%'].mean() else float('nan'),
        })
    return pd.DataFrame(out)


def main():
    print(f"Carregando {len(LFS)} LFs ({', '.join(LFS)})...\n")
    dfs = []
    for lf in LFS:
        try:
            dfs.append(load_lf(lf))
        except Exception as e:
            print(f"  ⚠ {lf}: {e}")
    df = pd.concat(dfs, ignore_index=True)
    print(f"Total: {len(df):,} leads em {df['lf'].nunique()} LFs\n")

    # ════════ Ocupação ════════
    print("═" * 90)
    print("  CONVERSÃO POR OCUPAÇÃO × LF")
    print("═" * 90)
    foco_ocup = ['Estudante', 'CLT/funcionário público', 'Autônomo', 'Não trabalho/nem estudo']
    tbl_ocup = conv_table(df, 'ocupacao', foco_ocup)
    pivot = tbl_ocup.pivot(index='segmento', columns='lf', values='conv_%').round(2)
    pivot = pivot.reindex(['TODOS'] + foco_ocup)
    print("conv_% por LF:")
    print(pivot.to_string())
    print()
    print("Resumo (LFs com n≥50):")
    print(summary(tbl_ocup).round(2).to_string(index=False))
    print()

    # ════════ Idade ════════
    print("═" * 90)
    print("  CONVERSÃO POR IDADE × LF")
    print("═" * 90)
    foco_idade = ['<18', '18-24', '25-34', '35-44', '45-54', '55+']
    tbl_idade = conv_table(df, 'idade', foco_idade)
    pivot = tbl_idade.pivot(index='segmento', columns='lf', values='conv_%').round(2)
    pivot = pivot.reindex(['TODOS'] + foco_idade)
    print("conv_% por LF:")
    print(pivot.to_string())
    print()
    print("Resumo (LFs com n≥50):")
    print(summary(tbl_idade).round(2).to_string(index=False))
    print()

    # ════════ Receita por lead — combinado ════════
    print("═" * 90)
    print("  RECEITA POR LEAD (conv_% × ticket) — Ocupação × LF")
    print("═" * 90)
    pivot_rev = tbl_ocup.pivot(index='segmento', columns='lf', values='rev/lead').round(2)
    pivot_rev = pivot_rev.reindex(['TODOS'] + foco_ocup)
    print(pivot_rev.to_string())
    print()

    print("═" * 90)
    print("  RECEITA POR LEAD (conv_% × ticket) — Idade × LF")
    print("═" * 90)
    pivot_rev = tbl_idade.pivot(index='segmento', columns='lf', values='rev/lead').round(2)
    pivot_rev = pivot_rev.reindex(['TODOS'] + foco_idade)
    print(pivot_rev.to_string())
    print()

    # ════════ Veredito ════════
    print("═" * 90)
    print("  VEREDITO — estabilidade temporal das células")
    print("═" * 90)
    s_o = summary(tbl_ocup)
    s_i = summary(tbl_idade)
    for _, r in pd.concat([s_o, s_i]).iterrows():
        cv = r['conv_cv']
        flag = '✓ estável  ' if cv < 0.30 else ('⚠ variável  ' if cv < 0.60 else '✗ instável  ')
        print(f"  {flag} {r['segmento']:<35} CV={cv:.2f}  "
              f"(min={r['conv_min']:.1f}%  med={r['conv_med']:.1f}%  max={r['conv_max']:.1f}%)")
    print()
    print("Convenção CV (coef. de variação = std/mean):")
    print("  < 0.30  → estável,  pode poolar LFs como referência")
    print("  0.30–0.60 → variável, pondere por LFs recentes (LF50–52)")
    print("  > 0.60  → instável, não dá pra extrapolar para LF54 só com composição")


if __name__ == '__main__':
    main()
