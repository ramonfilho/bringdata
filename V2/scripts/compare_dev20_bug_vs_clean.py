"""
Compara o perfil categórico de leads captados no DEV20 dentro de duas
janelas:

  CLEAN: 2026-04-21 → 2026-04-28 (pré-bug do Champion shim)
  BUG:   2026-04-29 → 2026-05-04 (com bug encoding_overrides — Erro 11)

Hipótese: se o modelo classificou errado boa parte dos leads na janela BUG,
a otimização Meta convergiu pra perfil diferente.

Saída: tabela por característica + chi² + CSV.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
from scipy.stats import chi2_contingency

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from perfil_audiencia import query_lead_railway, normalize_series, SURVEY_MAP


WINDOWS = [
    ('CLEAN', '2026-04-21', '2026-04-28'),
    ('BUG',   '2026-04-29', '2026-05-04'),
]


def load_window(start: str, end: str) -> pd.DataFrame:
    df = query_lead_railway(start, end)
    return df


def distribution(df: pd.DataFrame, col: str) -> pd.Series:
    s = normalize_series(df[col], col) if col in df.columns else pd.Series(dtype=str)
    s = s[s != '(nulo)']
    if len(s) == 0:
        return pd.Series(dtype=float)
    return (s.value_counts(normalize=True) * 100).sort_values(ascending=False), len(s)


def main():
    dfs = {}
    print('Carregando Railway por janela do DEV20...')
    for name, s, e in WINDOWS:
        df = load_window(s, e)
        dfs[name] = df
        print(f'  {name} ({s}→{e}): {len(df):,} leads')

    print('\n' + '=' * 95)
    hdr = f'{"Feature / Categoria":<46} {"CLEAN %":>10} {"BUG %":>10} {"Δ pp":>9}'
    print(hdr)
    print('=' * 95)

    all_rows = []
    chi_results = []
    for col, label in SURVEY_MAP:
        clean_dist, n_clean = distribution(dfs['CLEAN'], col)
        bug_dist, n_bug = distribution(dfs['BUG'], col)
        all_cats = sorted(set(clean_dist.index) | set(bug_dist.index))
        print(f'\n[{label}]')
        # build contingency table for chi2
        c_clean = []
        c_bug = []
        for cat in all_cats:
            c = float(clean_dist.get(cat, 0))
            b = float(bug_dist.get(cat, 0))
            d = b - c
            print(f'  {cat:<44} {c:>9.2f}% {b:>9.2f}% {d:>+8.2f}')
            all_rows.append({'feature': label, 'categoria': cat,
                             'clean_pct': c, 'bug_pct': b, 'delta_pp': d})
            # counts
            c_clean.append(c / 100 * n_clean)
            c_bug.append(b / 100 * n_bug)
        # chi² test
        contingency = pd.DataFrame({'clean': c_clean, 'bug': c_bug}, index=all_cats)
        if contingency.sum().min() > 0 and contingency.shape[0] >= 2:
            chi2, p, dof, exp = chi2_contingency(contingency.T)
            chi_results.append({'feature': label, 'n_clean': n_clean, 'n_bug': n_bug,
                                'chi2': chi2, 'p': p,
                                'verdict': 'SHIFT' if p < 0.001 else ('weak shift' if p < 0.05 else 'stable')})

    print('\n' + '=' * 95)
    print('CHI² (CLEAN vs BUG) por característica')
    print('=' * 95)
    for r in chi_results:
        print(f'  {r["feature"]:<28}  n_clean={r["n_clean"]:>6,}  n_bug={r["n_bug"]:>6,}  '
              f'chi²={r["chi2"]:>8.1f}  p={r["p"]:>9.2e}  → {r["verdict"]}')

    print('\n' + '=' * 95)
    print('TOP 10 DELTAS (maior magnitude)')
    print('=' * 95)
    df_d = pd.DataFrame(all_rows)
    df_d['abs_delta'] = df_d['delta_pp'].abs()
    for _, r in df_d.sort_values('abs_delta', ascending=False).head(10).iterrows():
        sign = '+' if r['delta_pp'] >= 0 else ''
        print(f"  {r['feature']:<26} {r['categoria']:<28} CLEAN={r['clean_pct']:>5.1f}%  "
              f"BUG={r['bug_pct']:>5.1f}%  Δ={sign}{r['delta_pp']:.2f}pp")

    out = REPO_ROOT / 'docs' / 'compare_dev20_bug_vs_clean.csv'
    df_d.drop(columns=['abs_delta']).to_csv(out, index=False)
    print(f'\nCSV salvo: {out.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
