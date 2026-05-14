"""
build_audience_direction_map.py — direction map por (feature, categoria) usado
pelo `_check_audience_profile_drift` pra classificar drift como BOM vs RUIM
(ao invés de só "perto/longe da baseline").

DEFINIÇÃO OPERACIONAL
─────────────────────
Pra cada (feature, valor_canônico):

  lift = P(compra | valor)  /  P(compra | baseline)

  Onde:
    - baseline = pool Top 5 ROAS atribuível 60d (ver docs/METODOLOGIA_TOP5_ROAS.md)
    - P(compra | valor) = compradores_v / leads_v  no pool baseline
    - P(compra | baseline) = compradores_total / leads_total  no pool

  CI 95% do lift (log-normal):
    SE(log lift) = sqrt(1/buyers_v + 1/buyers_base - 1/n_v - 1/n_base)
    CI = exp( log(lift) ± 1.96 × SE )

  CLASSIFICAÇÃO de "direction":
    1) n_grupo < 1000             → "insufficient_data"  (≥10 compradores esperados)
    2) CI 95% cruza 1.0           → "uncertain"
    3) lift ≥ 1.15                → "positive"
    4) 0.85 ≤ lift < 1.15         → "neutral"
    5) 0.50 ≤ lift < 0.85         → "negative"
    6) lift < 0.50                → "very_negative"

USO no _check_audience_profile_drift:
─────────────────────────────────────
  Δpp +  &  positive/very_positive   → "bom"  🟢
  Δpp +  &  negative/very_negative   → "ruim" 🔴
  Δpp −  &  negative/very_negative   → "bom"  🟢
  Δpp −  &  positive/very_positive   → "ruim" 🔴
  qualquer &  neutral/insufficient   → ⚪

FONTES
──────
  - outputs/analysis/matched_dataset_2026-05-09.parquet  (com `target` 20d)
  - configs/launches.yaml                                (cap_windows)

CAVEAT JANELA
─────────────
  matched_dataset usa janela de conversão 20d (`conversion_window_days` em
  configs/clients/devclub.yaml). Direction map é robusto a essa escolha —
  features que convertem em 20d também convertem em 60d, lift muda pouco.

OUTPUT
──────
  configs/audience_direction_map.json
  Stdout: tabela direção × lift por feature

USO
───
  python -m scripts.build_audience_direction_map
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from perfil_audiencia import normalize_series, UNIFICATION

MATCHED_PARQUET = REPO_ROOT / 'outputs' / 'analysis' / 'matched_dataset_2026-05-09.parquet'
LAUNCHES_YAML = REPO_ROOT / 'configs' / 'launches.yaml'
OUTPUT_JSON = REPO_ROOT / 'configs' / 'audience_direction_map.json'

# Top 5 canonical — ver docs/METODOLOGIA_TOP5_ROAS.md
TOP5 = ['LF45', 'LF44', 'LF46', 'LF41', 'LF43']

CATEGORICAL_FEATURES = [
    'O seu gênero:',
    'Qual a sua idade?',
    'O que você faz atualmente?',
    'Atualmente, qual a sua faixa salarial?',
    'Você possui cartão de crédito?',
    'Já estudou programação?',
    'Tem computador/notebook?',
    'Você já fez/faz/pretende fazer faculdade?',
]

# Parâmetros estatísticos
N_MIN = 1000
Z_95 = 1.96
TH_POS = 1.15
TH_NEG = 0.85
TH_VERY_NEG = 0.50


def map_leads_to_lf(df: pd.DataFrame, launches: dict) -> pd.Series:
    """Atribui cada lead ao primeiro LF cuja cap_window contém Data."""
    out = pd.Series([None] * len(df), index=df.index, dtype='object')
    df_dt = pd.to_datetime(df['Data'], errors='coerce')
    items = sorted(launches.items(), key=lambda kv: kv[1].get('cap_start', '9999'))
    for name, cfg in items:
        cs = pd.to_datetime(cfg.get('cap_start'))
        ce = pd.to_datetime(cfg.get('cap_end'))
        if pd.isna(cs) or pd.isna(ce):
            continue
        mask = out.isna() & (df_dt >= cs) & (df_dt <= ce + pd.Timedelta(days=1))
        out.loc[mask] = name
    return out


def compute_lift_ci(buyers_v: int, n_v: int, buyers_base: int, n_base: int) -> dict:
    """Lift + CI 95% (log-normal)."""
    if n_v == 0 or buyers_base == 0 or n_base == 0:
        return {'lift': None, 'ci_low': None, 'ci_high': None, 'se_log': None}
    p_v = buyers_v / n_v
    p_base = buyers_base / n_base
    if p_v == 0:
        return {'lift': 0.0, 'ci_low': 0.0, 'ci_high': None, 'se_log': None}
    lift = p_v / p_base
    # SE log-normal: 1/buyers - 1/n
    if buyers_v == 0:
        return {'lift': lift, 'ci_low': None, 'ci_high': None, 'se_log': None}
    se_log = math.sqrt(
        max(1e-9, 1/buyers_v - 1/n_v) + max(1e-9, 1/buyers_base - 1/n_base)
    )
    log_lift = math.log(lift)
    ci_low = math.exp(log_lift - Z_95 * se_log)
    ci_high = math.exp(log_lift + Z_95 * se_log)
    return {
        'lift': round(lift, 4),
        'ci_low': round(ci_low, 4),
        'ci_high': round(ci_high, 4),
        'se_log': round(se_log, 4),
    }


def classify_direction(n_v: int, lift: float, ci_low: float, ci_high: float) -> str:
    if n_v < N_MIN:
        return 'insufficient_data'
    if lift is None or ci_low is None or ci_high is None:
        return 'uncertain'
    # CI cruza 1.0?
    if ci_low <= 1.0 <= ci_high:
        return 'uncertain'
    # Classifica por magnitude
    if lift >= TH_POS:
        return 'positive'
    elif lift >= TH_NEG:
        return 'neutral'
    elif lift >= TH_VERY_NEG:
        return 'negative'
    else:
        return 'very_negative'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--launches', default=','.join(TOP5),
                        help=f'Pool baseline (default Top 5 canonical: {",".join(TOP5)})')
    args = parser.parse_args()
    pool = [x.strip() for x in args.launches.split(',') if x.strip()]

    # Load
    print(f'Carregando matched_dataset...')
    df = pd.read_parquet(MATCHED_PARQUET)
    launches = yaml.safe_load(LAUNCHES_YAML.read_text())
    print(f'  {len(df):,} leads')

    # Atribui LF
    df['_lf'] = map_leads_to_lf(df, launches)
    df_pool = df[df['_lf'].isin(pool)].copy()
    n_total = len(df_pool)
    buyers_total = int(df_pool['target'].sum())
    p_base = buyers_total / n_total
    print(f'\n  Pool {",".join(pool)}: {n_total:,} leads, {buyers_total} compradores '
          f'(baseline {p_base*100:.3f}%)\n')

    # Direction map por feature
    direction_map = {}
    print(f"{'feature':<45} {'valor':<30} {'n':>6} {'buy':>4} {'lift':>6} {'CI95':>18} {'direction':<18}")
    print('-' * 130)
    for col in CATEGORICAL_FEATURES:
        if col not in df_pool.columns:
            continue
        # Normaliza para canônico
        s = normalize_series(df_pool[col], col)
        df_pool[f'_norm_{col}'] = s
        df_feat = df_pool[[f'_norm_{col}', 'target']].copy()
        df_feat.columns = ['v', 't']
        df_feat = df_feat[df_feat['v'] != '(nulo)']  # exclui nulos
        groups = df_feat.groupby('v').agg(n=('t', 'size'), buyers=('t', 'sum')).reset_index()
        groups = groups.sort_values('n', ascending=False)

        cat = {}
        for _, row in groups.iterrows():
            v = row['v']
            n_v = int(row['n'])
            b_v = int(row['buyers'])
            stats = compute_lift_ci(b_v, n_v, buyers_total, n_total)
            direction = classify_direction(n_v, stats['lift'], stats['ci_low'], stats['ci_high'])
            cat[v] = {
                'n_leads': n_v,
                'n_buyers': b_v,
                'p_buy_pct': round(b_v / n_v * 100, 3),
                'lift': stats['lift'],
                'ci_low': stats['ci_low'],
                'ci_high': stats['ci_high'],
                'direction': direction,
            }
            ci_str = f"[{stats['ci_low']:.2f}, {stats['ci_high']:.2f}]" if stats['ci_low'] is not None else 'N/A'
            print(f"  {col[:43]:<43} {v[:28]:<28} {n_v:>6,} {b_v:>4} {stats['lift']!s:>6} {ci_str:>18} {direction:<18}")
        direction_map[col] = cat

    # Output JSON
    out = {
        'client_id': 'devclub',
        'generated_at': '2026-05-14',
        'reference_pool': {
            'label': 'Top 5 ROAS atribuível 60d',
            'launches': pool,
            'n_leads': int(n_total),
            'n_buyers': int(buyers_total),
            'baseline_buy_rate_pct': round(p_base * 100, 4),
        },
        'methodology': {
            'n_minimum': N_MIN,
            'ci_confidence': '95%',
            'thresholds': {
                'positive': f'lift >= {TH_POS}',
                'neutral': f'{TH_NEG} <= lift < {TH_POS}',
                'negative': f'{TH_VERY_NEG} <= lift < {TH_NEG}',
                'very_negative': f'lift < {TH_VERY_NEG}',
            },
            'rule_summary': (
                'Δpp+ & positive → bom; Δpp+ & negative → ruim; '
                'Δpp− & negative → bom; Δpp− & positive → ruim'
            ),
            'doc': 'docs/METODOLOGIA_TOP5_ROAS.md',
        },
        'direction_map': direction_map,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f'\n→ Salvo em {OUTPUT_JSON.relative_to(REPO_ROOT)}')

    # Resumo por direction
    print('\n  Resumo:')
    from collections import Counter
    counts = Counter()
    for feat, cats in direction_map.items():
        for v, d in cats.items():
            counts[d['direction']] += 1
    for k, n in sorted(counts.items()):
        print(f'    {k:<20} {n}')


if __name__ == '__main__':
    main()
