"""
Backtest da metodologia P(target|feature) para predizer faturamento.

Mecânica (test set = todos os LFs fora da REFERÊNCIA):
  1. Constrói lookup P(target=1|feature=v) usando leads dos 5 LFs de referência
     (Top5 ROAS realized: LF40, LF41, LF45, LF50, LF53), EXCLUINDO leads com NA
     em 'faculdade' (form bug 16-20/02/2026 cria viés)
  2. Para cada LF alvo (10 LFs fora da ref):
       expected_conv  = média_features( média_leads( P(target|v_lead) ) )
       expected_buyers = expected_conv × n_leads
       expected_receita = expected_buyers × ticket_realizado_global_REF
       expected_roas   = expected_receita / spend_LF
  3. Compara com observado:
       MAE, MAPE, Pearson, Spearman para conv / receita / ROAS

Métricas reportadas:
  - corr_conv (Pearson, Spearman) — quão bem ranqueia LFs por conversão
  - corr_roas (Pearson, Spearman) — quão bem ranqueia LFs por ROAS realizado
  - MAPE_receita — erro % médio na predição de R$
  - MAPE_roas — erro % médio na predição de ROAS

Saídas:
  - outputs/analysis/audience_quality_backtest.csv (tabela LF × métricas)
  - print da tabela formatada + métricas agregadas
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHED_PARQUET = REPO_ROOT / 'outputs' / 'analysis' / 'matched_dataset_2026-05-09.parquet'
ROAS_CSV = REPO_ROOT / 'outputs' / 'analysis' / 'roas_realized.csv'
LAUNCHES_YAML = REPO_ROOT / 'configs' / 'launches.yaml'

# Top 5 ROAS atribuível 60d (definido em docs/METODOLOGIA_TOP5_ROAS.md).
# Última recalibragem: 2026-05-14.
# Pra regerar: `python -m scripts.compute_top5_roas_attributable`
REFERENCE_LFS = ['LF45', 'LF44', 'LF46', 'LF41', 'LF43']
NA_FILTER_FEATURE = 'Você já fez/faz/pretende fazer faculdade?'
PRIOR_N = 5

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


def build_lookup(baseline_df: pd.DataFrame) -> tuple[dict, float]:
    """P(target=1|valor) por feature, com Empirical Bayes leve (prior_n=5)."""
    baseline_conv = baseline_df['target'].mean()
    lookup = {}
    for col in CATEGORICAL_FEATURES:
        if col not in baseline_df.columns:
            continue
        gp = baseline_df.groupby(col, dropna=False)['target']
        agg = gp.agg(['sum', 'count'])
        agg['p'] = (agg['sum'] + PRIOR_N * baseline_conv) / (agg['count'] + PRIOR_N)
        lookup[col] = agg['p'].to_dict()
    return lookup, baseline_conv


def predict_conv_mean(df_lf: pd.DataFrame, lookup: dict, baseline_conv: float) -> float:
    """v1 — média entre features de média entre leads de P(t|v). Suaviza demais."""
    feat_avgs = []
    for col in CATEGORICAL_FEATURES:
        if col not in df_lf.columns or col not in lookup:
            continue
        ps = df_lf[col].map(lookup[col]).fillna(baseline_conv)
        feat_avgs.append(ps.mean())
    return float(np.mean(feat_avgs)) if feat_avgs else baseline_conv


def predict_conv_naive_bayes(df_lf: pd.DataFrame, lookup: dict, baseline_conv: float) -> float:
    """v2 — Naive Bayes em log-odds: combina lifts por feature multiplicativamente.
    Capta interações (independente) e amplia amplitude sem explodir (média entre leads
    no espaço log)."""
    eps = 1e-9
    log_baseline = np.log(baseline_conv + eps)
    log_ratios_per_lead = np.zeros(len(df_lf))
    n_feats = 0
    for col in CATEGORICAL_FEATURES:
        if col not in df_lf.columns or col not in lookup:
            continue
        ps = df_lf[col].map(lookup[col]).fillna(baseline_conv)
        log_ratios_per_lead = log_ratios_per_lead + (np.log(ps + eps) - log_baseline)
        n_feats += 1
    if n_feats == 0:
        return baseline_conv
    # log_lift por lead = soma de log(P(t|v_i) / baseline)
    # expected_lift = média_leads(exp(log_lift)) — geometric-ish média
    # Cap pra evitar valores absurdos (ex: lifts muito altos por baixa amostragem)
    log_ratios_per_lead = np.clip(log_ratios_per_lead, -3, 3)
    lifts = np.exp(log_ratios_per_lead)
    return float(baseline_conv * lifts.mean())


def main():
    launches = yaml.safe_load(LAUNCHES_YAML.read_text())
    df = pd.read_parquet(MATCHED_PARQUET)
    df['_lf'] = map_lead_to_lf(launches, df)
    df_roas = pd.read_csv(ROAS_CSV).set_index('lf')

    # Baseline: REF, sem NA em faculdade (filtra bug 16-20/02/2026)
    baseline = df[df['_lf'].isin(REFERENCE_LFS)].copy()
    n_baseline_pre = len(baseline)
    mask_na = baseline[NA_FILTER_FEATURE].isna() | (
        baseline[NA_FILTER_FEATURE].astype(str).str.lower().isin(['none', 'nan', '<na>', ''])
    )
    baseline = baseline[~mask_na]
    n_baseline_post = len(baseline)

    # Ticket realized médio na REF (R$/comprador) — usado como proxy do ticket esperado
    receita_ref = df_roas.loc[REFERENCE_LFS, 'receita_realized'].sum()
    n_vendas_ref = df_roas.loc[REFERENCE_LFS, 'n_vendas_realized'].sum()
    ticket_global_ref = receita_ref / n_vendas_ref

    print('=' * 96)
    print('  BACKTEST — metodologia P(target|feature) com referência Top5 ROAS realized')
    print('=' * 96)
    print(f'  Referência: {REFERENCE_LFS}')
    print(f'  Baseline antes do filtro NA(faculdade): {n_baseline_pre:,} leads')
    print(f'  Baseline após filtro:                   {n_baseline_post:,} leads  '
          f'({n_baseline_pre - n_baseline_post:,} removidos)')
    print(f'  Ticket realized médio na REF:           R$ {ticket_global_ref:,.2f}/comprador')
    print(f'  ({receita_ref:,.2f} / {n_vendas_ref:,} compradores)')
    print()

    lookup, baseline_conv = build_lookup(baseline)
    print(f'  Conversão baseline (REF s/NA): {baseline_conv*100:.3f}%')
    print()

    # Test set: LFs com ROAS realizado E NÃO em REF (10 LFs)
    test_lfs = [lf for lf in df_roas.index if lf not in REFERENCE_LFS]
    rows = []
    for lf in test_lfs:
        sub = df[df['_lf'] == lf]
        if len(sub) == 0:
            continue
        n_leads = len(sub)
        pred_conv_v1 = predict_conv_mean(sub, lookup, baseline_conv)
        pred_conv_v2 = predict_conv_naive_bayes(sub, lookup, baseline_conv)
        # default usado no relatório principal: NB (mais discriminante)
        pred_conv = pred_conv_v2
        expected_buyers = pred_conv * n_leads
        pred_receita = expected_buyers * ticket_global_ref
        spend_lf = df_roas.loc[lf, 'spend']
        pred_roas = pred_receita / spend_lf if spend_lf else np.nan

        actual_conv = sub['target'].mean()
        actual_buyers = int(sub['target'].sum())
        actual_receita = df_roas.loc[lf, 'receita_realized']
        actual_roas = df_roas.loc[lf, 'roas_realized']

        rows.append({
            'lf': lf,
            'n_leads': n_leads,
            'pred_conv_v1_mean_pct': pred_conv_v1 * 100,
            'pred_conv_v2_NB_pct': pred_conv_v2 * 100,
            'pred_conv_pct': pred_conv * 100,
            'actual_conv_pct': actual_conv * 100,
            'pred_buyers': expected_buyers,
            'actual_buyers': actual_buyers,
            'pred_receita': pred_receita,
            'actual_receita': actual_receita,
            'pred_roas': pred_roas,
            'actual_roas': actual_roas,
            'spend': spend_lf,
            'erro_receita_pct': (pred_receita - actual_receita) / actual_receita * 100,
            'erro_roas_pct': (pred_roas - actual_roas) / actual_roas * 100,
        })

    res = pd.DataFrame(rows).set_index('lf')

    # Comparativo v1 vs v2 (conversão)
    pearson_v1 = res['pred_conv_v1_mean_pct'].corr(res['actual_conv_pct'])
    spearman_v1 = res['pred_conv_v1_mean_pct'].corr(res['actual_conv_pct'], method='spearman')
    pearson_v2 = res['pred_conv_v2_NB_pct'].corr(res['actual_conv_pct'])
    spearman_v2 = res['pred_conv_v2_NB_pct'].corr(res['actual_conv_pct'], method='spearman')

    print()
    print('=' * 96)
    print('  COMPARATIVO V1 (média) vs V2 (Naive Bayes log-odds) — predição de conversão')
    print('=' * 96)
    print(f'  V1 (média p/ feature):   range pred={res["pred_conv_v1_mean_pct"].min():.3f}-{res["pred_conv_v1_mean_pct"].max():.3f}%   '
          f'Pearson={pearson_v1:+.3f}  Spearman={spearman_v1:+.3f}')
    print(f'  V2 (Naive Bayes log):    range pred={res["pred_conv_v2_NB_pct"].min():.3f}-{res["pred_conv_v2_NB_pct"].max():.3f}%   '
          f'Pearson={pearson_v2:+.3f}  Spearman={spearman_v2:+.3f}')
    print(f'  Realizado:               range actl={res["actual_conv_pct"].min():.3f}-{res["actual_conv_pct"].max():.3f}%')

    # Métricas agregadas (V2 NB é o default)
    pearson_conv = res['pred_conv_pct'].corr(res['actual_conv_pct'])
    spearman_conv = res['pred_conv_pct'].corr(res['actual_conv_pct'], method='spearman')
    pearson_receita = res['pred_receita'].corr(res['actual_receita'])
    spearman_receita = res['pred_receita'].corr(res['actual_receita'], method='spearman')
    pearson_roas = res['pred_roas'].corr(res['actual_roas'])
    spearman_roas = res['pred_roas'].corr(res['actual_roas'], method='spearman')

    mae_receita = (res['pred_receita'] - res['actual_receita']).abs().mean()
    mape_receita = (res['erro_receita_pct'].abs()).mean()
    mae_roas = (res['pred_roas'] - res['actual_roas']).abs().mean()
    mape_roas = (res['erro_roas_pct'].abs()).mean()

    # Print tabela
    print('=' * 110)
    print('  PREDIÇÕES POR LF — predicted vs actual (test set: 10 LFs fora da REF)')
    print('=' * 110)
    print(f'  {"LF":<6} {"n_leads":>8}  '
          f'{"conv_p":>7} {"conv_a":>7}  '
          f'{"R$_pred":>13} {"R$_actl":>13} {"err%":>7}  '
          f'{"ROAS_p":>7} {"ROAS_a":>7} {"err%":>7}')
    print('-' * 110)
    res_sorted = res.sort_values('actual_roas', ascending=False)
    for lf, r in res_sorted.iterrows():
        print(f'  {lf:<6} {r["n_leads"]:>8,.0f}  '
              f'{r["pred_conv_pct"]:>7.3f} {r["actual_conv_pct"]:>7.3f}  '
              f'R$ {r["pred_receita"]:>10,.0f} R$ {r["actual_receita"]:>10,.0f} {r["erro_receita_pct"]:>+6.1f}%  '
              f'{r["pred_roas"]:>7.2f} {r["actual_roas"]:>7.2f} {r["erro_roas_pct"]:>+6.1f}%')

    print()
    print('=' * 96)
    print('  MÉTRICAS AGREGADAS — n =', len(res), 'LFs avaliados')
    print('=' * 96)
    print(f'  CONVERSÃO   →  Pearson:  {pearson_conv:+.3f}    Spearman: {spearman_conv:+.3f}')
    print(f'  RECEITA R$  →  Pearson:  {pearson_receita:+.3f}    Spearman: {spearman_receita:+.3f}')
    print(f'  ROAS        →  Pearson:  {pearson_roas:+.3f}    Spearman: {spearman_roas:+.3f}')
    print()
    print(f'  MAE  receita: R$ {mae_receita:>10,.0f}        MAPE  receita: {mape_receita:.1f}%')
    print(f'  MAE  ROAS:        {mae_roas:.3f}              MAPE  ROAS:    {mape_roas:.1f}%')
    print()

    # Direcional: quantas vezes acertou se LF foi melhor/pior que mediana?
    pred_median = res['pred_roas'].median()
    actual_median = res['actual_roas'].median()
    res['pred_above'] = res['pred_roas'] > pred_median
    res['actual_above'] = res['actual_roas'] > actual_median
    accuracy_dir = (res['pred_above'] == res['actual_above']).mean()
    print(f'  ACURÁCIA DIRECIONAL (acima/abaixo da mediana): {accuracy_dir*100:.1f}% '
          f'({int((res["pred_above"] == res["actual_above"]).sum())}/{len(res)})')
    print()

    out_path = REPO_ROOT / 'outputs' / 'analysis' / 'audience_quality_backtest.csv'
    res.to_csv(out_path)
    print(f'→ CSV salvo em: {out_path.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
