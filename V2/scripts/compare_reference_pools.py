"""
Compara o perfil de leads TOTAIS de dois pools de referência candidatos
para o `audience_quality_signal`:

  OLD: [LF40, LF41, LF45, LF50, LF53] (Top5 do PDF antigo)
  NEW: [LF44, LF45, LF41, LF46]       (Top4 reais por ROAS atribuível 60d)

Saída: por feature categórica (7 features da pesquisa), distribuição
percentual em cada pool e delta (NEW - OLD) por categoria.

Reusa o carregador unificado e o normalizador de scripts/perfil_audiencia.py
para garantir 1:1 com o que o daily-check usa.

Uso:
    python -m scripts.compare_reference_pools
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from perfil_audiencia import (
    load_launches,
    load_launch,
    normalize_series,
    SURVEY_MAP,
)
from ml_evolution_report import load_sheets_data


# Histórico de pools candidatos. CANONICAL é o atual em produção
# (ver docs/METODOLOGIA_TOP5_ROAS.md; regerar com
# `python -m scripts.compute_top5_roas_attributable`).
OLD_POOL = ['LF40', 'LF41', 'LF45', 'LF50', 'LF53']
NEW4_POOL = ['LF44', 'LF45', 'LF41', 'LF46']
NEW6_POOL = ['LF44', 'LF45', 'LF41', 'LF46', 'LF43', 'LF47']
CANONICAL_POOL = ['LF45', 'LF44', 'LF46', 'LF41', 'LF43']

POOLS = [('OLD', OLD_POOL), ('NEW4', NEW4_POOL), ('NEW6', NEW6_POOL),
         ('CANONICAL', CANONICAL_POOL)]

PESQUISA_COLS = [c for c, _ in SURVEY_MAP]


def load_pool(launches_cfg: dict, names: list[str], sheets_cache: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Concatena leads totais dos LFs do pool. Retorna df e contagem por LF."""
    frames = []
    counts = {}
    for n in names:
        df, src = load_launch(n, launches_cfg, sheets_cache)
        counts[n] = (len(df), src)
        keep = [c for c in PESQUISA_COLS if c in df.columns]
        sub = df[keep].copy()
        sub['_lf'] = n
        frames.append(sub.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True), counts


def distribution(df: pd.DataFrame, col: str) -> pd.Series:
    """Normaliza coluna e retorna % por categoria (soma=100)."""
    s = normalize_series(df[col], col) if col in df.columns else pd.Series(dtype=str)
    if len(s) == 0:
        return pd.Series(dtype=float)
    vc = s.value_counts(normalize=True) * 100
    return vc.sort_values(ascending=False)


def main():
    launches_cfg = load_launches()
    print('[1/3] Carregando Sheets cache (pode demorar ~30s)...')
    sheets = load_sheets_data()
    print(f'      Sheets cache: {len(sheets):,} linhas')

    print('[2/3] Carregando pools...')
    pool_dfs = {}
    for label, names in POOLS:
        df, counts = load_pool(launches_cfg, names, sheets)
        pool_dfs[label] = df
        print(f'      {label} pool ({len(names)} LFs): {len(df):,} leads totais')
        for n, (c, src) in counts.items():
            print(f'        - {n} ({src}): {c:,}')

    print('[3/3] Computando distribuições e deltas...\n')
    hdr = f'{"Feature / Categoria":<45} {"OLD %":>9} {"NEW4 %":>9} {"NEW6 %":>9} {"Δ4-OLD":>9} {"Δ6-OLD":>9} {"Δ6-NEW4":>9}'
    print('=' * len(hdr))
    print(hdr)
    print('=' * len(hdr))

    all_rows = []
    for col, label in SURVEY_MAP:
        d_old = distribution(pool_dfs['OLD'], col)
        d_new4 = distribution(pool_dfs['NEW4'], col)
        d_new6 = distribution(pool_dfs['NEW6'], col)
        all_cats = sorted(set(d_old.index) | set(d_new4.index) | set(d_new6.index))
        print(f'\n[{label}]')
        for cat in all_cats:
            o = float(d_old.get(cat, 0))
            n4 = float(d_new4.get(cat, 0))
            n6 = float(d_new6.get(cat, 0))
            print(f'  {cat:<43} {o:>8.2f}% {n4:>8.2f}% {n6:>8.2f}% {n4-o:>+8.2f} {n6-o:>+8.2f} {n6-n4:>+8.2f}')
            all_rows.append({
                'feature': label, 'categoria': cat,
                'old_pct': o, 'new4_pct': n4, 'new6_pct': n6,
                'delta_new4_old': n4 - o,
                'delta_new6_old': n6 - o,
                'delta_new6_new4': n6 - n4,
            })

    df_all = pd.DataFrame(all_rows)
    print('\n' + '=' * 90)
    print('TOP 10 DELTAS NEW6 vs NEW4 (efeito de adicionar LF43+LF47)')
    print('=' * 90)
    df_all['abs_d6_4'] = df_all['delta_new6_new4'].abs()
    for _, r in df_all.sort_values('abs_d6_4', ascending=False).head(10).iterrows():
        sign = '+' if r['delta_new6_new4'] >= 0 else ''
        print(f"  {r['feature']:<25} {r['categoria']:<25} NEW4={r['new4_pct']:>5.1f}%  NEW6={r['new6_pct']:>5.1f}%  Δ={sign}{r['delta_new6_new4']:.2f}pp")

    print('\n' + '=' * 90)
    print('TOP 10 DELTAS NEW6 vs OLD (alavanca total para regenerar baseline com 6 LFs)')
    print('=' * 90)
    df_all['abs_d6_o'] = df_all['delta_new6_old'].abs()
    for _, r in df_all.sort_values('abs_d6_o', ascending=False).head(10).iterrows():
        sign = '+' if r['delta_new6_old'] >= 0 else ''
        print(f"  {r['feature']:<25} {r['categoria']:<25} OLD={r['old_pct']:>5.1f}%  NEW6={r['new6_pct']:>5.1f}%  Δ={sign}{r['delta_new6_old']:.2f}pp")

    out = REPO_ROOT / 'docs' / 'compare_reference_pools_3way.csv'
    df_all.drop(columns=['abs_d6_4', 'abs_d6_o']).to_csv(out, index=False)
    print(f'\nCSV salvo: {out.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
