"""
Gera o snapshot de referência `devclub_quality_signal.json` por cliente, usado
pelo check `audience_quality_signal` em `DataQualityMonitor`.

Lê scored_abr28.parquet de cada LF do pool e calcula:
  - score_mean      média do lead_score (Challenger)
  - pct_d10         fração em D10
  - pct_d9_d10      fração em D9 ou D10
  - pct_d8_d10      fração em D8/D9/D10

Métricas finais = média ponderada (por n_leads) através dos LFs do pool.

Uso:
    python -m scripts.build_quality_signal_baseline \
        --client devclub \
        --launches LF44,LF45,LF41,LF46,LF43,LF47 \
        --label "Top 6 ROAS atribuível 60d" \
        --run-id 5d158f0aa6e54b489498470446194a6c \
        --model-label challenger_abr28 \
        --scored-name scored_abr28.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
VAL_DIR = REPO_ROOT / 'files' / 'validation'


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--client', default='devclub')
    p.add_argument('--launches', required=True,
                   help='LFs do pool, vírgula-separado (ex Top 5 canonical: LF45,LF44,LF46,LF41,LF43 — '
                        'ver docs/METODOLOGIA_TOP5_ROAS.md)')
    p.add_argument('--label', default='Top 5 ROAS atribuível 60d')
    p.add_argument('--run-id', required=True, help='MLflow run_id do modelo Challenger usado pra scorear')
    p.add_argument('--model-label', default='challenger_abr28')
    p.add_argument('--model-trained-at', default=None, help='ISO timestamp do treino (opcional, herdado do JSON anterior)')
    p.add_argument('--model-rationale', default=None, help='Razão da escolha do modelo (opcional)')
    p.add_argument('--scored-name', default='scored_abr28.parquet',
                   help='Nome do parquet scored em files/validation/backtest_<lf>/')
    p.add_argument('--output', default=None,
                   help='Caminho do JSON (default configs/reference_audience_profiles/{client}_quality_signal.json)')
    # Thresholds — mantidos os mesmos do baseline anterior por default
    p.add_argument('--delta-pct-d9-d10-warn', type=float, default=-0.03)
    p.add_argument('--delta-pct-d9-d10-alert', type=float, default=-0.05)
    p.add_argument('--delta-score-mean-pct-warn', type=float, default=-0.05)
    p.add_argument('--delta-score-mean-pct-alert', type=float, default=-0.10)
    return p.parse_args()


def lf_metrics(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {'n_leads': 0, 'score_mean': 0.0, 'pct_d10': 0.0, 'pct_d9_d10': 0.0, 'pct_d8_d10': 0.0}
    decis = df['decil'].astype(str)
    return {
        'n_leads': n,
        'score_mean': float(df['lead_score'].mean()),
        'pct_d10': float((decis == 'D10').sum() / n),
        'pct_d9_d10': float(decis.isin(['D09', 'D10']).sum() / n),
        'pct_d8_d10': float(decis.isin(['D08', 'D09', 'D10']).sum() / n),
    }


def main():
    args = parse_args()
    pool_names = [x.strip() for x in args.launches.split(',') if x.strip()]

    per_lf = {}
    print(f'Lendo scored parquets ({args.scored_name}) de {len(pool_names)} LFs...')
    for lf in pool_names:
        folder = lf.lower()
        path = VAL_DIR / f'backtest_{folder}' / args.scored_name
        if not path.exists():
            sys.exit(f'ERRO: {path.relative_to(REPO_ROOT)} não existe. '
                     f'Rode prepare-dataset + score em {folder} antes.')
        df = pd.read_parquet(path)
        m = lf_metrics(df)
        per_lf[lf] = m
        print(f'  {lf}: n={m["n_leads"]:,}  score_mean={m["score_mean"]:.4f}  '
              f'pct_d10={m["pct_d10"]*100:.1f}%  pct_d9_d10={m["pct_d9_d10"]*100:.1f}%')

    # Média ponderada por n_leads
    total_n = sum(m['n_leads'] for m in per_lf.values())
    if total_n == 0:
        sys.exit('ERRO: nenhum LF carregado.')
    def wavg(key):
        return sum(m[key] * m['n_leads'] for m in per_lf.values()) / total_n

    metrics = {
        'score_mean': round(wavg('score_mean'), 4),
        'pct_d10': round(wavg('pct_d10'), 4),
        'pct_d9_d10': round(wavg('pct_d9_d10'), 4),
        'pct_d8_d10': round(wavg('pct_d8_d10'), 4),
    }

    print(f'\n[baseline {args.label}, n={total_n:,}]:')
    for k, v in metrics.items():
        print(f'  {k} = {v}')

    # Read model metadata to enrich JSON
    snapshot = {
        'client_id': args.client,
        'generated_at': date.today().isoformat(),
        'model': {
            'label': args.model_label,
            'run_id': args.run_id,
            **({'trained_at': args.model_trained_at} if args.model_trained_at else {}),
            **({'rationale': args.model_rationale} if args.model_rationale else {}),
        },
        'reference_pool': {
            'label': args.label,
            'launches': pool_names,
            'n_leads': total_n,
        },
        'metrics': metrics,
        'thresholds': {
            'delta_pct_d9_d10_warn': args.delta_pct_d9_d10_warn,
            'delta_pct_d9_d10_alert': args.delta_pct_d9_d10_alert,
            'delta_score_mean_pct_warn': args.delta_score_mean_pct_warn,
            'delta_score_mean_pct_alert': args.delta_score_mean_pct_alert,
        },
        'per_lf_metrics': per_lf,
    }

    out = Path(args.output) if args.output else (
        REPO_ROOT / 'configs' / 'reference_audience_profiles' / f'{args.client}_quality_signal.json'
    )
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f'\nSnapshot salvo em {out.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
