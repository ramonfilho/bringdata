"""
Sensibilidade: a instabilidade de Estudante some se eu remover algum LF?

Roda jackknife (remove cada LF uma vez) e mostra CV resultante.
Também avalia se o n por célula é suficiente.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.perfil_audiencia import normalize_series

HIST_DIR = REPO_ROOT / 'files' / 'validation' / 'backtest_historico'
LFS = ['LF46', 'LF47', 'LF48', 'LF49', 'LF50', 'LF51', 'LF52']


def load_all() -> pd.DataFrame:
    frames = []
    for lf in LFS:
        df = pd.read_parquet(HIST_DIR / lf / 'base_with_tmb.parquet')
        df['lf'] = lf
        df['idade']    = normalize_series(df['Qual a sua idade?'], 'Qual a sua idade?')
        df['ocupacao'] = normalize_series(df['O que você faz atualmente?'], 'O que você faz atualmente?')
        frames.append(df[['lf', 'idade', 'ocupacao', 'converted', 'sale_value']])
    return pd.concat(frames, ignore_index=True)


def conv_per_lf(df: pd.DataFrame, group_col: str, val: str) -> pd.Series:
    out = {}
    for lf, sub in df.groupby('lf'):
        seg = sub[sub[group_col] == val]
        if len(seg) >= 50:
            out[lf] = seg['converted'].mean() * 100
    return pd.Series(out)


def cv(s: pd.Series) -> float:
    return float(s.std() / s.mean()) if s.mean() else float('nan')


def jackknife(df: pd.DataFrame, group_col: str, val: str):
    full = conv_per_lf(df, group_col, val)
    print(f"\n══════ {val} ({group_col}) ══════")
    print(f"  CV completo: {cv(full):.2f}  (n_LFs={len(full)})")
    print(f"  Conv por LF:")
    for lf, v in full.sort_values().items():
        n_seg = ((df['lf'] == lf) & (df[group_col] == val)).sum()
        n_vendas = ((df['lf'] == lf) & (df[group_col] == val) & df['converted']).sum()
        print(f"    {lf}:  {v:.2f}%   (n_leads={n_seg:,}  vendas={n_vendas})")
    print(f"  Jackknife (remove cada LF):")
    for lf_rem in full.index:
        kept = full.drop(lf_rem)
        c = cv(kept)
        flag = ' ← cai pra estável' if c < 0.30 else ''
        print(f"    sem {lf_rem}:  CV={c:.2f}{flag}")


def main():
    df = load_all()
    print(f"Base: {len(df):,} leads, {df['lf'].nunique()} LFs")

    for val in ['Estudante', 'Não trabalho/nem estudo', 'Autônomo']:
        jackknife(df, 'ocupacao', val)
    for val in ['<18', '45-54']:
        jackknife(df, 'idade', val)


if __name__ == '__main__':
    main()
