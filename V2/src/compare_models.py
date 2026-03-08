"""
Compara RF vs LightGBM vs XGBoost no dataset encodado DevClub.

Uso:
  # 1. Gerar dataset encodado:
  python src/train_pipeline.py --save-encoded --no-api-data

  # 2. Comparar modelos:
  python src/compare_models.py

Configuração equivalente entre os três modelos:
  - RF:    n_estimators=300, max_depth=8, class_weight='balanced'
  - LGBM:  n_estimators=300, max_depth=8, is_unbalance=True
  - XGB:   n_estimators=300, max_depth=8, scale_pos_weight=n_neg/n_pos
"""

import os
import sys
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

# Adicionar raiz do projeto ao path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

PARQUET_PATH = os.path.join(ROOT, 'compare_encoded.parquet')


def temporal_leads_split(df: pd.DataFrame, date_col: str = '__Data__', train_pct: float = 0.7):
    """Split temporal por leads: primeiros 70% (ordenados por data) para treino."""
    df_sorted = df.sort_values(date_col).reset_index(drop=True)
    n_train = int(len(df_sorted) * train_pct)
    return df_sorted.iloc[:n_train].copy(), df_sorted.iloc[n_train:].copy()


def compute_metrics(y_test, y_prob):
    """Calcula AUC, Top-3, Lift máximo e Monotonia."""
    auc = roc_auc_score(y_test, y_prob)

    df = pd.DataFrame({'prob': y_prob, 'target': y_test.values})
    df['decil'] = pd.qcut(df['prob'], q=10, labels=[f'D{i}' for i in range(1, 11)], duplicates='drop')

    analise = df.groupby('decil', observed=True)['target'].agg(['count', 'sum', 'mean'])
    analise.columns = ['total', 'conversoes', 'taxa']
    analise['pct_conv'] = analise['conversoes'] / analise['conversoes'].sum() * 100

    taxa_base = y_test.mean()
    analise['lift'] = analise['taxa'] / taxa_base

    top3 = analise['pct_conv'].tail(3).sum()
    lift_max = analise['lift'].max()

    taxas = analise['taxa'].values
    crescimentos = sum(1 for i in range(1, len(taxas)) if taxas[i] >= taxas[i - 1])
    monotonia = crescimentos / (len(taxas) - 1) * 100 if len(taxas) > 1 else 100.0

    return {
        'auc': auc,
        'top3': top3,
        'lift_max': lift_max,
        'monotonia': monotonia,
        'decil_table': analise,
    }


def print_decil_table(name: str, analise: pd.DataFrame, taxa_base: float):
    print(f"\n  Decis — {name}")
    print(f"  {'Decil':<6} {'Leads':>7} {'Conv':>5} {'Taxa':>7} {'Lift':>6} {'%Conv':>7}")
    print("  " + "-" * 46)
    for decil, row in analise.iterrows():
        print(f"  {str(decil):<6} {int(row['total']):>7,} {int(row['conversoes']):>5} "
              f"{row['taxa']*100:>6.2f}% {row['lift']:>5.2f}x {row['pct_conv']:>6.1f}%")


def main():
    if not os.path.exists(PARQUET_PATH):
        print(f"Arquivo não encontrado: {PARQUET_PATH}")
        print("Execute primeiro: python src/train_pipeline.py --save-encoded --no-api-data")
        sys.exit(1)

    print("Carregando dataset encodado...")
    df = pd.read_parquet(PARQUET_PATH)
    print(f"  {len(df):,} registros, {len(df.columns)} colunas")
    print(f"  Target positivo: {df['target'].sum():,} ({df['target'].mean()*100:.2f}%)")

    # Split temporal por leads
    df_train, df_test = temporal_leads_split(df)
    print(f"\nSplit temporal_leads (70/30):")
    print(f"  Treino: {len(df_train):,} leads  ({df_train['__Data__'].min().date()} → {df_train['__Data__'].max().date()})")
    print(f"  Teste:  {len(df_test):,} leads  ({df_test['__Data__'].min().date()} → {df_test['__Data__'].max().date()})")

    # Preparar features (remover target e __Data__)
    feature_cols = [c for c in df.columns if c not in ('target', '__Data__')]
    X_train = df_train[feature_cols]
    y_train = df_train['target']
    X_test  = df_test[feature_cols]
    y_test  = df_test['target']

    # Normalizar nomes (mesmo que training_model.py)
    X_train.columns = X_train.columns.str.replace('[^A-Za-z0-9_]', '_', regex=True)
    X_train.columns = X_train.columns.str.replace('__+', '_', regex=True)
    X_train.columns = X_train.columns.str.strip('_')
    X_test.columns  = X_train.columns  # mesma ordem

    n_pos = int(y_train.sum())
    n_neg = int((y_train == 0).sum())
    scale_pos = n_neg / n_pos

    print(f"\nClasse positiva treino: {n_pos:,} / {len(y_train):,} ({n_pos/len(y_train)*100:.2f}%)")
    print(f"scale_pos_weight (XGBoost): {scale_pos:.1f}x\n")

    resultados = {}

    # ── Random Forest ──────────────────────────────────────────────────────────
    print("Treinando Random Forest...")
    rf = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_split=2,
        min_samples_leaf=1,
        max_features='sqrt',
        class_weight='balanced',
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)
    resultados['RF'] = compute_metrics(y_test, rf.predict_proba(X_test)[:, 1])
    print(f"  AUC: {resultados['RF']['auc']:.4f}")

    # ── LightGBM ───────────────────────────────────────────────────────────────
    try:
        import lightgbm as lgb
        print("Treinando LightGBM...")
        lgbm = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=8,
            is_unbalance=True,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        lgbm.fit(X_train, y_train)
        resultados['LGBM'] = compute_metrics(y_test, lgbm.predict_proba(X_test)[:, 1])
        print(f"  AUC: {resultados['LGBM']['auc']:.4f}")
    except ImportError:
        print("  LightGBM não instalado — ignorando. (pip install lightgbm)")

    # ── XGBoost ────────────────────────────────────────────────────────────────
    try:
        import xgboost as xgb
        print("Treinando XGBoost...")
        xgboost = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=8,
            scale_pos_weight=scale_pos,
            random_state=42,
            n_jobs=-1,
            eval_metric='logloss',
            verbosity=0,
        )
        xgboost.fit(X_train, y_train)
        resultados['XGB'] = compute_metrics(y_test, xgboost.predict_proba(X_test)[:, 1])
        print(f"  AUC: {resultados['XGB']['auc']:.4f}")
    except ImportError:
        print("  XGBoost não instalado — ignorando. (pip install xgboost)")

    # ── Tabela comparativa ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("COMPARAÇÃO DE MODELOS")
    print("=" * 60)
    print(f"  {'Modelo':<8} {'AUC':>7} {'Top-3':>7} {'Lift':>7} {'Mono':>7}")
    print("  " + "-" * 40)
    for nome, m in resultados.items():
        print(f"  {nome:<8} {m['auc']:>7.4f} {m['top3']:>6.1f}% {m['lift_max']:>6.2f}x {m['monotonia']:>6.1f}%")
    print("=" * 60)

    # ── Tabelas de decis por modelo ────────────────────────────────────────────
    taxa_base = y_test.mean()
    for nome, m in resultados.items():
        print_decil_table(nome, m['decil_table'], taxa_base)

    print()


if __name__ == '__main__':
    main()
