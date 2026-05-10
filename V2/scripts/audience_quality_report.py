"""
Relatório de qualidade de audiência por lançamento.

Para um lançamento em curso/recente (LF54, DEV20...), compara o mix de audiência
contra a referência Top5 ROAS realized (LF40, LF41, LF45, LF50, LF53) e:

  - Decompõe drift por (feature, valor) com lift = P(target|v) / baseline
  - Calcula expected_conv via lookup univariado da referência
  - Projeta Δconversion vs baseline e Δfaturamento estimado

LIMITAÇÕES (transparência):
  - Decomposição é aditiva (assume independência entre features).
    Soma das contribuições aproxima Δscore agregado, não substitui SHAP.
  - Lift por categoria estimado com Empirical Bayes (prior = 5 leads do baseline).
  - Δfaturamento depende de ticket médio assumido (--ticket, default R$ 1.500).
  - LF54 é parcial (captação ainda em curso até 11/05).

Uso:
  python -m scripts.audience_quality_report --launch LF54
  python -m scripts.audience_quality_report --launch DEV20 --ticket 1500
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHED_PARQUET = REPO_ROOT / 'outputs' / 'analysis' / 'matched_dataset_2026-05-09.parquet'
RAILWAY_CACHE = REPO_ROOT / 'files' / 'validation' / 'cache' / 'railway_leads_2024-12-30_2026-05-08.parquet'
LAUNCHES_YAML = REPO_ROOT / 'configs' / 'launches.yaml'

REFERENCE_LFS = ['LF40', 'LF41', 'LF45', 'LF50', 'LF53']

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


def build_reference_lookup(df_ref: pd.DataFrame, prior_n: int = 5) -> Dict:
    """Para cada (feature, valor): retorna mix, P(target|v), lift, n.
       Empirical Bayes pra suavizar valores raros."""
    baseline = df_ref['target'].mean()
    lookup = {'__baseline__': baseline, '__n_ref__': len(df_ref)}
    for col in CATEGORICAL_FEATURES:
        if col not in df_ref.columns:
            continue
        gp = df_ref.groupby(col, dropna=False)['target']
        agg = gp.agg(['sum', 'count']).rename(columns={'sum': 'n_buyers', 'count': 'n_leads'})
        agg['p_target'] = (agg['n_buyers'] + prior_n * baseline) / (agg['n_leads'] + prior_n)
        agg['mix_ref'] = agg['n_leads'] / agg['n_leads'].sum()
        agg['lift'] = agg['p_target'] / baseline
        lookup[col] = agg
    return lookup


def expected_conv_aggregate(df_launch: pd.DataFrame, lookup: Dict) -> tuple[float, Dict]:
    """expected_conv = média_features( Σ_v mix_v_em_LF × P(target|v_em_REF) ).
       Retorna (escalar, dict por feature)."""
    baseline = lookup['__baseline__']
    feat_ec = {}
    for col in CATEGORICAL_FEATURES:
        if col not in df_launch.columns or col not in lookup:
            continue
        ref_p = lookup[col]['p_target']
        # mix do launch
        counts = df_launch[col].value_counts(dropna=False)
        mix = counts / counts.sum()
        # ec_feat = Σ_v mix_v × P(target|v); valores não vistos no ref → baseline
        ec = sum(p * ref_p.get(v, baseline) for v, p in mix.items())
        feat_ec[col] = ec
    overall = sum(feat_ec.values()) / len(feat_ec) if feat_ec else baseline
    return overall, feat_ec


def decompose_drift(df_launch: pd.DataFrame, lookup: Dict, top_n: int = 8) -> pd.DataFrame:
    """Decompõe drift por (feature, valor): mix, Δpp, P(target|v), contribuição."""
    baseline = lookup['__baseline__']
    rows = []
    for col in CATEGORICAL_FEATURES:
        if col not in df_launch.columns or col not in lookup:
            continue
        n_launch = len(df_launch)
        counts = df_launch[col].value_counts(dropna=False)
        mix_launch = (counts / counts.sum()).to_dict()
        ref_agg = lookup[col]
        all_values = set(mix_launch.keys()) | set(ref_agg.index)
        for v in all_values:
            ref_pct = float(ref_agg.loc[v, 'mix_ref']) if v in ref_agg.index else 0.0
            launch_pct = float(mix_launch.get(v, 0.0))
            delta_pp = (launch_pct - ref_pct) * 100
            p_target = float(ref_agg.loc[v, 'p_target']) if v in ref_agg.index else baseline
            lift = p_target / baseline
            n_in_launch = int(counts.get(v, 0))
            n_in_ref = int(ref_agg.loc[v, 'n_leads']) if v in ref_agg.index else 0
            # Contribuição de v pra Δconv: (mix_launch - mix_ref) × P(target|v)
            delta_contrib = (launch_pct - ref_pct) * p_target
            rows.append({
                'feature': col,
                'value': str(v),
                'ref_pct': ref_pct * 100,
                'launch_pct': launch_pct * 100,
                'delta_pp': delta_pp,
                'p_target': p_target * 100,
                'lift': lift,
                'n_in_ref': n_in_ref,
                'n_in_launch': n_in_launch,
                'delta_contrib_pp': delta_contrib * 100,
            })
    df = pd.DataFrame(rows)
    df = df.sort_values('delta_contrib_pp', key=abs, ascending=False)
    return df


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--launch', required=True, help='Nome do LF (ex: LF54, DEV20)')
    parser.add_argument('--ticket', type=float, default=1500.0,
                        help='Ticket médio para projeção R$ (default 1500)')
    parser.add_argument('--top-decomp', type=int, default=10,
                        help='Quantos drivers mostrar na decomposição (default 10)')
    parser.add_argument('--filter-na-features', type=str,
                        default='Você já fez/faz/pretende fazer faculdade?',
                        help='Features (separadas por ";") onde leads com NA serão filtrados '
                             'do baseline. Default: filtra "faculdade" (bug de formulário '
                             'em LF45 16-20/02/2026 deixou 2803 leads sem essa resposta). '
                             'Passe "" pra desativar.')
    args = parser.parse_args()

    launches = yaml.safe_load(LAUNCHES_YAML.read_text())
    if args.launch not in launches:
        logger.error(f'Launch {args.launch} não está em launches.yaml')
        return
    cfg = launches[args.launch]
    cs = pd.to_datetime(cfg['cap_start'])
    ce = pd.to_datetime(cfg['cap_end']) + pd.Timedelta(days=1)

    # Reference (matched parquet com target)
    df_matched = pd.read_parquet(MATCHED_PARQUET)
    df_matched['_lf'] = map_lead_to_lf(launches, df_matched)
    df_ref = df_matched[df_matched['_lf'].isin(REFERENCE_LFS)].copy()
    n_ref_raw = len(df_ref)

    # Filtragem de leads com NA em features bugadas (default: faculdade — bug
    # de formulário em LF45 16-20/02/2026, 2803 leads afetados)
    filter_features = [f.strip() for f in args.filter_na_features.split(';') if f.strip()]
    if filter_features:
        for feat in filter_features:
            if feat not in df_ref.columns:
                logger.warning(f'Filter-NA: feature "{feat}" não existe no parquet')
                continue
            mask_na = df_ref[feat].isna() | (
                df_ref[feat].astype(str).str.lower().isin(['none', 'nan', '<na>', ''])
            )
            n_before = len(df_ref)
            df_ref = df_ref[~mask_na].copy()
            removed = n_before - len(df_ref)
            logger.info(f'Filter-NA "{feat[:50]}": removidos {removed:,} leads do baseline '
                        f'({removed/n_before*100:.1f}%)')

    logger.info(f'Referência: {REFERENCE_LFS}, {len(df_ref):,} leads (de {n_ref_raw:,} brutos), '
                f'{int(df_ref["target"].sum())} compradores '
                f'(taxa {df_ref["target"].mean()*100:.3f}%)')
    lookup = build_reference_lookup(df_ref)
    baseline = lookup['__baseline__']

    # Launch (railway cache até 08/05; pode estar parcial pra LF em curso)
    df_railway = pd.read_parquet(RAILWAY_CACHE)
    df_railway['Data'] = pd.to_datetime(df_railway['Data'], errors='coerce')
    df_launch = df_railway[(df_railway['Data'] >= cs) & (df_railway['Data'] < ce)].copy()
    if len(df_launch) == 0:
        logger.error(f'Sem leads de {args.launch} no cache Railway')
        return
    last_lead_dt = df_launch['Data'].max()
    is_partial = last_lead_dt < ce - pd.Timedelta(days=1)

    print()
    print('═' * 90)
    print(f'  AUDIENCE QUALITY REPORT — {args.launch}')
    print('═' * 90)
    print(f'  Janela captação: {cfg["cap_start"]} → {cfg["cap_end"]}')
    print(f'  Leads no relatório: {len(df_launch):,}  '
          f'(último captado: {last_lead_dt.strftime("%Y-%m-%d %H:%M")}'
          f'{" — PARCIAL" if is_partial else ""})')
    print(f'  Referência: Top5 ROAS realized {REFERENCE_LFS}')
    print(f'    n_leads={lookup["__n_ref__"]:,} · taxa baseline={baseline*100:.3f}%')
    print('═' * 90)

    # Aggregate prediction
    expected, feat_expected = expected_conv_aggregate(df_launch, lookup)
    delta_conv_pp = (expected - baseline) * 100
    delta_buyers = (expected - baseline) * len(df_launch)
    delta_revenue = delta_buyers * args.ticket

    print()
    print('  PREDIÇÃO AGREGADA (univariado, independência idealizada)')
    print('  ' + '-' * 86)
    print(f'  Expected conversion (audience-only)  : {expected*100:>7.3f}%  vs baseline {baseline*100:.3f}%')
    print(f'  Δ conversion vs baseline              : {delta_conv_pp:>+7.3f} pp')
    print(f'  Δ compradores esperados (em {len(df_launch):,} leads)  : {delta_buyers:>+7.1f}')
    print(f'  Δ faturamento esperado (ticket R$ {args.ticket:,.0f}): {delta_revenue:>+10,.0f} R$')
    print()
    print('  Por feature (expected_conv usando o lookup da referência):')
    for col, ec in sorted(feat_expected.items(), key=lambda x: -abs(x[1] - baseline)):
        d_pp = (ec - baseline) * 100
        print(f'    {col:<55} {ec*100:>6.3f}%  ({d_pp:+.3f} pp)')

    # Decomposição por (feature, valor)
    df_dec = decompose_drift(df_launch, lookup, top_n=args.top_decomp)
    print()
    print('═' * 90)
    print(f'  DECOMPOSIÇÃO — top {args.top_decomp} (feature, valor) por |contribuição ao Δconv|')
    print('═' * 90)
    print(f'  {"Feature":<40}{"Valor":<32}{"Ref%":>7}{"LF%":>7}{"Δpp":>7}{"P(buy|v)":>10}{"Lift":>6}{"Δcontrib":>10}')
    print('-' * 130)
    for _, r in df_dec.head(args.top_decomp).iterrows():
        feat_short = r['feature'][:38]
        val_short = r['value'][:30]
        print(f"  {feat_short:<40}{val_short:<32}{r['ref_pct']:>6.1f}%{r['launch_pct']:>6.1f}%"
              f"{r['delta_pp']:>+6.1f}{r['p_target']:>9.3f}%{r['lift']:>5.2f}{r['delta_contrib_pp']:>+9.4f}pp")

    # Sanity: soma das delta_contrib aproxima Δconv aggregate?
    sum_contrib_pp = df_dec['delta_contrib_pp'].sum() / len(CATEGORICAL_FEATURES)
    print()
    print(f'  Sanity: soma de Δcontrib (aritm. média entre features) = {sum_contrib_pp:+.3f} pp '
          f'(vs Δconv agregado {delta_conv_pp:+.3f} pp)')

    out = REPO_ROOT / 'outputs' / 'analysis' / f'audience_quality_{args.launch}.csv'
    df_dec.to_csv(out, index=False)
    print()
    print(f'→ Decomposição completa salva em: {out.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
