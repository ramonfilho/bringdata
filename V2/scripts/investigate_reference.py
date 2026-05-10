"""
Testa qual subconjunto de lançamentos serve melhor como REFERÊNCIA pra
inferir qualidade de audiência via mix de features categoricas.

Mecânica:
  Para cada candidato R (set de LFs):
    1. Calcula P(target=1 | feature=v) usando leads de R   → lookup univariado
    2. Para cada LF L fora de R:
       expected_conv(L) = média_features( Σ_v mix_v_em_L × P(target | v_em_R) )
       actual_conv(L)   = mean(target) em L
    3. Correlação entre expected_conv vs ROAS_realized e actual_conv através dos LFs

  Maior |correlação| ⇒ melhor poder discriminante da referência.

Usa:
  - outputs/analysis/matched_dataset_2026-05-09.parquet  (213k leads matched)
  - outputs/analysis/roas_realized.csv                   (ROAS realized per LF)
  - configs/launches.yaml                                (cap_start/cap_end + excluded_from_reference)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHED_PARQUET = REPO_ROOT / 'outputs' / 'analysis' / 'matched_dataset_2026-05-09.parquet'
ROAS_CSV = REPO_ROOT / 'outputs' / 'analysis' / 'roas_realized.csv'
LAUNCHES_YAML = REPO_ROOT / 'configs' / 'launches.yaml'

CATEGORICAL_FEATURES = [
    'O seu gênero:',
    'Qual a sua idade?',
    'O que você faz atualmente?',
    'Atualmente, qual a sua faixa salarial?',
    'Você possui cartão de crédito?',
    'O que mais você quer ver no evento?',
    'Tem computador/notebook?',
    'Já estudou programação?',
    'Você já fez/faz/pretende fazer faculdade?',
]

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def map_lead_to_lf(launches: dict, df: pd.DataFrame) -> pd.Series:
    """Atribui cada lead a um LF baseado em Data dentro de [cap_start, cap_end]."""
    out = pd.Series([None] * len(df), index=df.index, dtype='object')
    df_dt = pd.to_datetime(df['Data'], errors='coerce')
    for name, cfg in launches.items():
        cs = pd.to_datetime(cfg.get('cap_start'))
        ce = pd.to_datetime(cfg.get('cap_end')) + pd.Timedelta(days=1)  # inclusive
        if pd.isna(cs) or pd.isna(ce):
            continue
        mask = (df_dt >= cs) & (df_dt < ce)
        out.loc[mask] = name
    return out


def compute_p_target_given_value(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Para cada (feature, valor): P(target=1 | feature=valor). Inclui baseline geral."""
    lookup = {'__baseline__': df['target'].mean()}
    for col in CATEGORICAL_FEATURES:
        if col not in df.columns:
            continue
        # Empirical Bayes leve: 5 priors da baseline geral
        baseline = df['target'].mean()
        prior_n = 5
        gp = df.groupby(col, dropna=False)['target']
        agg = gp.agg(['sum', 'count'])
        agg['p'] = (agg['sum'] + prior_n * baseline) / (agg['count'] + prior_n)
        lookup[col] = agg['p'].to_dict()
    return lookup


def predict_expected_conv(df_lf: pd.DataFrame, lookup: Dict) -> float:
    """Predicted conversion: média entre features de Σ_v mix_v × P(target|v).
    Equivalente a: para cada lead, médio P(target|v_lead) entre features, e média
    entre leads. Independência idealizada — interpretação aproximativa."""
    baseline = lookup.get('__baseline__', 0.0)
    feature_avgs = []
    for col in CATEGORICAL_FEATURES:
        if col not in df_lf.columns or col not in lookup:
            continue
        # Map valor → P(target|v); fallback baseline pra valores não vistos
        ps = df_lf[col].map(lookup[col]).fillna(baseline)
        feature_avgs.append(ps.mean())
    return sum(feature_avgs) / len(feature_avgs) if feature_avgs else baseline


def main():
    launches = yaml.safe_load(LAUNCHES_YAML.read_text())
    df = pd.read_parquet(MATCHED_PARQUET)
    df['_lf'] = map_lead_to_lf(launches, df)
    df_roas = pd.read_csv(ROAS_CSV)

    # Stats por LF
    df_lf_stats = (
        df.dropna(subset=['_lf'])
        .groupby('_lf')
        .agg(n_leads=('target', 'count'), n_buyers=('target', 'sum'))
    )
    df_lf_stats['conv_rate'] = df_lf_stats['n_buyers'] / df_lf_stats['n_leads']
    df_lf_stats = df_lf_stats.merge(df_roas[['lf', 'roas_realized', 'roas_atual']],
                                     left_index=True, right_on='lf', how='left').set_index('lf')

    # Identificar LFs excluidos por config
    excluded_bf = [n for n, c in launches.items() if c.get('excluded_from_reference') == 'BF']
    excluded_outliers = [n for n, c in launches.items() if c.get('excluded_from_reference')]

    # Top5 por ROAS realized geral
    top5_roas_real = df_lf_stats.sort_values('roas_realized', ascending=False).head(5).index.tolist()
    # Top5 por ROAS realized excluindo outliers (BF + LF53)
    df_lf_clean = df_lf_stats[~df_lf_stats.index.isin(excluded_outliers)]
    top5_roas_real_clean = df_lf_clean.sort_values('roas_realized', ascending=False).head(5).index.tolist()
    # Top5 por ROAS atual
    top5_roas_atual = df_lf_stats.sort_values('roas_atual', ascending=False).head(5).index.tolist()
    top5_roas_atual_clean = df_lf_clean.sort_values('roas_atual', ascending=False).head(5).index.tolist()
    # Top5 por % conversão observada
    top5_conv = df_lf_clean.sort_values('conv_rate', ascending=False).head(5).index.tolist()
    # Mediana
    mid_5 = df_lf_clean.sort_values('roas_realized').iloc[len(df_lf_clean)//2-2:len(df_lf_clean)//2+3].index.tolist()
    # Última 5 móvel (cronológica)
    lf_chrono_in_data = [lf for lf in launches.keys() if lf in df_lf_stats.index]
    last_5 = lf_chrono_in_data[-5:]
    # Interseção sólida
    intersec = sorted(set(top5_roas_real_clean) & set(top5_roas_atual_clean))

    # Top5 ROAS realized excluindo APENAS LF53 (mantém BF)
    df_no_lf53 = df_lf_stats[df_lf_stats.index != 'LF53']
    top5_real_no_lf53 = df_no_lf53.sort_values('roas_realized', ascending=False).head(5).index.tolist()
    # Top5 ROAS realized excluindo APENAS BF (mantém LF53)
    df_no_bf = df_lf_stats[~df_lf_stats.index.isin(excluded_bf)]
    top5_real_no_bf = df_no_bf.sort_values('roas_realized', ascending=False).head(5).index.tolist()

    candidates = {
        'Top5 ROAS atual': top5_roas_atual,
        'Top5 ROAS atual (excl BF+LF53)': top5_roas_atual_clean,
        'Top5 ROAS realized': top5_roas_real,
        'Top5 ROAS realized (excl LF53 só)': top5_real_no_lf53,
        'Top5 ROAS realized (excl BF só)': top5_real_no_bf,
        'Top5 ROAS realized (excl BF+LF53)': top5_roas_real_clean,
        'Top5 % Conversão observada (excl outliers)': top5_conv,
        f'Interseção atual & realized clean ({len(intersec)} LFs)': intersec,
        'Mediana ROAS realized (5 mid)': mid_5,
        f'Últimos 5 LFs cronológicos': last_5,
    }

    print()
    print('=' * 90)
    print('  CANDIDATOS A REFERÊNCIA — composição')
    print('=' * 90)
    for name, lfs in candidates.items():
        n_leads = df_lf_stats.loc[lfs, 'n_leads'].sum() if all(l in df_lf_stats.index for l in lfs) else 'n/a'
        print(f'  {name:<55} {sorted(lfs)}  (n_leads={n_leads:,})' if isinstance(n_leads, int) else f'  {name:<55} {sorted(lfs)}')

    # Por candidato: P(target|v) lookup → predição em outras LFs → correlação
    print()
    print('=' * 90)
    print('  PODER DISCRIMINANTE — corr(predicted_conv vs ROAS_realized) e (vs actual_conv)')
    print('=' * 90)
    print(f'  {"Candidato":<50} {"corr_ROAS":>11}{"corr_conv":>12}{"n_LFs_eval":>12}{"n_leads_ref":>13}')
    print('-' * 90)
    results = []
    for name, ref_lfs in candidates.items():
        ref_leads = df[df['_lf'].isin(ref_lfs)]
        if len(ref_leads) == 0:
            continue
        lookup = compute_p_target_given_value(ref_leads)
        eval_lfs = [lf for lf in df_lf_stats.index if lf not in ref_lfs]
        rows = []
        for lf in eval_lfs:
            sub = df[df['_lf'] == lf]
            if len(sub) == 0:
                continue
            ec = predict_expected_conv(sub, lookup)
            rows.append({
                'lf': lf,
                'expected_conv': ec,
                'actual_conv': sub['target'].mean(),
                'roas_realized': df_lf_stats.loc[lf, 'roas_realized'],
            })
        df_e = pd.DataFrame(rows)
        if len(df_e) < 3:
            continue
        corr_r = df_e['expected_conv'].corr(df_e['roas_realized'], method='spearman')
        corr_c = df_e['expected_conv'].corr(df_e['actual_conv'], method='spearman')
        results.append({
            'reference': name, 'corr_roas': corr_r, 'corr_conv': corr_c,
            'n_lfs_eval': len(df_e), 'n_leads_ref': len(ref_leads),
        })
        print(f'  {name:<50} {corr_r:>+11.3f}{corr_c:>+12.3f}{len(df_e):>12d}{len(ref_leads):>13,}')

    df_results = pd.DataFrame(results).sort_values('corr_roas', ascending=False)
    print()
    print('=' * 90)
    print('  RANKING — referências mais discriminantes (Spearman ↓):')
    print('=' * 90)
    for _, r in df_results.iterrows():
        print(f"  corr_ROAS={r['corr_roas']:+.3f}  corr_conv={r['corr_conv']:+.3f}  "
              f"n_eval={r['n_lfs_eval']}  n_leads_ref={r['n_leads_ref']:,}  ← {r['reference']}")

    out_path = REPO_ROOT / 'outputs' / 'analysis' / 'reference_discriminant_power.csv'
    df_results.to_csv(out_path, index=False)
    print()
    print(f'→ CSV salvo em: {out_path.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
