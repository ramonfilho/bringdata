"""
Quão 'outlier' cada LF é em composição de audiência?

Mecânica:
  1. Mix(LF) = vetor de proporções (feature, valor) — para cada LF
  2. Centroide = média ponderada por n_leads de todos os LFs (ou unweighted)
  3. Distância L1 (Manhattan) de Mix(LF) ao centroide
  4. Variance per feature: quais features distinguem LFs mais?

Ranking de distância revela se LF40/41/53 estão fora do padrão (audiência outlier)
ou dentro (sazonalidade BF/multi-produto afeta SALES, não AUDIÊNCIA).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHED_PARQUET = REPO_ROOT / 'outputs' / 'analysis' / 'matched_dataset_2026-05-09.parquet'
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
    out = pd.Series([None] * len(df), index=df.index, dtype='object')
    df_dt = pd.to_datetime(df['Data'], errors='coerce')
    for name, cfg in launches.items():
        cs = pd.to_datetime(cfg.get('cap_start'))
        ce = pd.to_datetime(cfg.get('cap_end')) + pd.Timedelta(days=1)
        if pd.isna(cs) or pd.isna(ce):
            continue
        out.loc[(df_dt >= cs) & (df_dt < ce)] = name
    return out


def mix_per_lf(df: pd.DataFrame) -> pd.DataFrame:
    """Devolve DF wide: index=LF, cols=(feature, valor) tuples → proporção."""
    rows = []
    for lf, sub in df.dropna(subset=['_lf']).groupby('_lf'):
        n = len(sub)
        row = {'lf': lf, 'n_leads': n}
        for col in CATEGORICAL_FEATURES:
            if col not in sub.columns:
                continue
            counts = sub[col].value_counts(dropna=False)
            for val, c in counts.items():
                key = f'{col}|{val}'
                row[key] = c / n
        rows.append(row)
    return pd.DataFrame(rows).set_index('lf').fillna(0)


def main():
    launches = yaml.safe_load(LAUNCHES_YAML.read_text())
    df = pd.read_parquet(MATCHED_PARQUET)
    df['_lf'] = map_lead_to_lf(launches, df)

    df_mix = mix_per_lf(df)
    n_leads = df_mix.pop('n_leads')

    # Centroide unweighted (cada LF pesa igual — testa "padrão típico de LF")
    centroid_unweighted = df_mix.mean(axis=0)
    # Centroide weighted (cada LF pesa pelo n_leads — "padrão da população")
    centroid_weighted = df_mix.mul(n_leads, axis=0).sum(axis=0) / n_leads.sum()

    # Distância L1 de cada LF aos dois centroides
    out = pd.DataFrame({
        'n_leads': n_leads,
        'L1_to_centroid_unweighted': (df_mix - centroid_unweighted).abs().sum(axis=1),
        'L1_to_centroid_weighted': (df_mix - centroid_weighted).abs().sum(axis=1),
    })
    out['rank_unweighted'] = out['L1_to_centroid_unweighted'].rank(ascending=False).astype(int)
    out['rank_weighted'] = out['L1_to_centroid_weighted'].rank(ascending=False).astype(int)
    out['outlier_flag'] = out.index.map(
        lambda x: launches.get(x, {}).get('excluded_from_reference') or ''
    )

    # Ordem cronológica
    chrono = [lf for lf in launches.keys() if lf in out.index]
    out = out.reindex(chrono)

    print()
    print('=' * 90)
    print('  AUDIÊNCIA OUTLIER CHECK — distância L1 do mix de cada LF ao centroide')
    print('=' * 90)
    print(f'  {"LF":<8}{"n_leads":>9}  {"L1 vs unw.":>12}{"rank":>5}  {"L1 vs wgt.":>12}{"rank":>5}  {"flag":<15}')
    print('-' * 90)
    for lf, r in out.iterrows():
        print(f'  {lf:<8}{r["n_leads"]:>9,.0f}  {r["L1_to_centroid_unweighted"]:>12.3f}{r["rank_unweighted"]:>5d}  '
              f'{r["L1_to_centroid_weighted"]:>12.3f}{r["rank_weighted"]:>5d}  {r["outlier_flag"]:<15}')

    # Top features mais discriminantes (maior variância entre LFs)
    print()
    print('=' * 90)
    print('  FEATURES QUE MAIS DIFERENCIAM LFs — variância das proporções')
    print('=' * 90)
    var = df_mix.var(axis=0).sort_values(ascending=False).head(15)
    for k, v in var.items():
        print(f'  {k:<70} std={v**0.5:.4f}')

    out_path = REPO_ROOT / 'outputs' / 'analysis' / 'audience_outlier_check.csv'
    out.to_csv(out_path)
    print()
    print(f'→ CSV salvo em: {out_path.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
