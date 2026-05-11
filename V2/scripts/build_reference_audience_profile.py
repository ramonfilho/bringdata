"""
Gera o snapshot de referência `reference_audience_profile` por cliente, usado
pelo check `audience_profile_drift` em `DataQualityMonitor` (T1-13).

Output:
    configs/reference_audience_profiles/{client_id}.json

Estrutura do JSON:
{
  "client_id": "devclub",
  "generated_at": "2026-05-08",
  "reference_pool": {
    "label": "Top 5 ROAS",
    "launches": ["LF40", "LF41", "LF44", "LF45", "LF47"],
    "n_leads": 39771
  },
  "categorical_features": {
    "O seu gênero:": {
      "n_responses": 39600,
      "proportions": {"Masculino": 0.817, "Feminino": 0.183}
    },
    ...
  },
  "is_critical": ["O seu gênero:", "O que você faz atualmente?", ...]
}

Uso:
    python -m scripts.build_reference_audience_profile
    python -m scripts.build_reference_audience_profile --client devclub --launches LF40,LF41,LF44,LF45,LF47

A lista de "features críticas" (aquelas que disparam severity HIGH no drift)
pode ser sobrescrita via --critical, default = 5 features socioeconômicas.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from ml_evolution_report import load_sheets_data
from scripts.perfil_audiencia import (
    SURVEY_MAP, slice_sheets, normalize_series, load_launch,
)

DEFAULT_TOP5 = ['LF40', 'LF41', 'LF44', 'LF45', 'LF47']
DEFAULT_LABEL = 'Top 5 ROAS'

DEFAULT_CRITICAL_FEATURES = [
    'O seu gênero:',
    'O que você faz atualmente?',
    'Você possui cartão de crédito?',
    'Já estudou programação?',
    'Tem computador/notebook?',
]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--client', default='devclub', help='client_id (default devclub)')
    p.add_argument('--launches', default=','.join(DEFAULT_TOP5),
                   help=f'Lançamentos do pool de referência, vírgula-separado (default {",".join(DEFAULT_TOP5)})')
    p.add_argument('--label', default=DEFAULT_LABEL, help='Label do pool')
    p.add_argument('--critical', default=','.join(DEFAULT_CRITICAL_FEATURES),
                   help='Features que disparam severity HIGH se Δ ≥ threshold')
    p.add_argument('--output', default=None,
                   help='Caminho do JSON (default configs/reference_audience_profiles/{client}.json)')
    return p.parse_args()


def build_categorical_distribution(df: pd.DataFrame, col: str) -> dict:
    s = normalize_series(df[col], col) if col in df.columns else pd.Series(dtype=str)
    s = s[s != '(nulo)']
    n = len(s)
    if n == 0:
        return {'n_responses': 0, 'proportions': {}}
    proportions = (s.value_counts() / n).round(6).to_dict()
    return {'n_responses': int(n), 'proportions': proportions}


def main():
    args = parse_args()
    launches_path = REPO_ROOT / 'configs' / 'launches.yaml'
    with open(launches_path) as f:
        launches = yaml.safe_load(f)

    pool_names = [x.strip() for x in args.launches.split(',') if x.strip()]
    for n in pool_names:
        if n not in launches:
            sys.exit(f'ERRO: {n} não está em {launches_path.relative_to(REPO_ROOT)}')

    critical = [x.strip() for x in args.critical.split(',') if x.strip()]
    valid_cols = {col for col, _ in SURVEY_MAP}
    for c in critical:
        if c not in valid_cols:
            sys.exit(f'ERRO: feature crítica "{c}" não está em SURVEY_MAP')

    print('Carregando Sheets...')
    sheets = load_sheets_data()
    sheets['data'] = pd.to_datetime(sheets['data'], errors='coerce')
    sheets = sheets.loc[:, ~sheets.columns.duplicated()]

    # load_launch route por cap_start vs RAILWAY_CUTOVER:
    # LFs pré-cutover (Sheets) usam slice_sheets(); pós-cutover (Railway) usam SQL direto.
    # Sem isso, LF50/LF53 (pós-cutover) saem com 0 leads do Sheets.
    pool_frames = []
    for n in pool_names:
        df, src = load_launch(n, launches, sheets)
        print(f'  {n}: {len(df):,} leads ({src})')
        pool_frames.append(df)
    pool = pd.concat(pool_frames, ignore_index=True)
    print(f'Pool {args.label}: {len(pool):,} leads')

    categorical = {}
    for col, label in SURVEY_MAP:
        dist = build_categorical_distribution(pool, col)
        categorical[col] = {
            'label': label,
            **dist,
        }

    snapshot = {
        'client_id': args.client,
        'generated_at': date.today().isoformat(),
        'reference_pool': {
            'label': args.label,
            'launches': pool_names,
            'n_leads': int(len(pool)),
        },
        'is_critical': critical,
        'categorical_features': categorical,
    }

    out = Path(args.output) if args.output else (
        REPO_ROOT / 'configs' / 'reference_audience_profiles' / f'{args.client}.json'
    )
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f'\nSnapshot salvo em {out.relative_to(REPO_ROOT)}')
    print(f'  {len(categorical)} features categóricas')
    print(f'  {len(critical)} features críticas (severity HIGH se |Δ| ≥ threshold)')


if __name__ == '__main__':
    main()
