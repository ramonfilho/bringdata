"""
Hyperparameter tuning para RandomForest - DevClub Lead Scoring

Busca configurações que otimizem:
- AUC (discriminação geral)
- Concentração nos top decis (D8-D10)
- Separação D10/D1 (crítico para CAPI)
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import ParameterGrid
import time
import logging

logger = logging.getLogger(__name__)


def calcular_metricas_ranking(y_test, y_prob):
    """Calcula métricas de ranking focadas no caso de uso"""

    df_analise = pd.DataFrame({
        'probabilidade': y_prob,
        'target_real': y_test.reset_index(drop=True)
    })

    # Decis
    try:
        df_analise['decil'] = pd.qcut(
            df_analise['probabilidade'],
            q=10,
            labels=[f'D{i}' for i in range(1, 11)],
            duplicates='drop'
        )
    except ValueError as e:
        logger.warning(f"Erro ao criar decis: {e}")
        return None

    analise_decis = df_analise.groupby('decil', observed=True).agg({
        'target_real': ['count', 'sum', 'mean']
    }).round(4)

    analise_decis.columns = ['total_leads', 'conversoes', 'taxa_conversao']

    if analise_decis['conversoes'].sum() == 0:
        return None

    analise_decis['pct_total_conversoes'] = (
        analise_decis['conversoes'] / analise_decis['conversoes'].sum() * 100
    ).round(2)

    taxa_base = y_test.mean()
    analise_decis['lift'] = (analise_decis['taxa_conversao'] / taxa_base).round(2)

    # Métricas
    top3_conversoes = analise_decis.tail(3)['pct_total_conversoes'].sum()
    top5_conversoes = analise_decis.tail(5)['pct_total_conversoes'].sum()
    lift_maximo = analise_decis['lift'].max()

    # Monotonia
    taxas = analise_decis['taxa_conversao'].values
    crescimentos = sum(1 for i in range(1, len(taxas)) if taxas[i] >= taxas[i-1])
    monotonia = crescimentos / (len(taxas) - 1) if len(taxas) > 1 else 1.0

    # AUC
    auc = roc_auc_score(y_test, y_prob)

    # Separação D10/D1 (crítico para CAPI)
    d10_rate = analise_decis.loc['D10', 'taxa_conversao']
    d1_rate = analise_decis.loc['D1', 'taxa_conversao']
    separacao_d10_d1 = d10_rate / d1_rate if d1_rate > 0 else 0

    return {
        'auc': auc,
        'top3_conv': top3_conversoes,
        'top5_conv': top5_conversoes,
        'lift_max': lift_maximo,
        'monotonia': monotonia * 100,
        'separacao_d10_d1': separacao_d10_d1,
        'n_conversoes': analise_decis['conversoes'].sum(),
        'analise_decis': analise_decis
    }


def hyperparameter_tuning(
    dataset_encoded: pd.DataFrame,
    dataset_original: pd.DataFrame,
    baseline_params: dict = None,
    grid_size: str = 'medium',
    buyer_weights: pd.Series = None,
):
    """
    Executa hyperparameter tuning focado e rápido.

    Args:
        dataset_encoded: Dataset com features encoded e target
        dataset_original: Dataset original com coluna 'Data' para split temporal
        baseline_params: Hiperparâmetros baseline (default: config atual)
        grid_size: Tamanho do grid ('small', 'medium', 'large')

    Returns:
        dict com resultados do tuning
    """

    print("HYPERPARAMETER TUNING - RANDOMFOREST")

    # Baseline padrão
    if baseline_params is None:
        baseline_params = {
            'n_estimators': 100,
            'max_depth': 10,
            'min_samples_split': 2,
            'min_samples_leaf': 1,
            'max_features': 'sqrt',
            'class_weight': 'balanced',
            'random_state': 42,
            'n_jobs': -1
        }

    # Split temporal_leads 70/30 para tuning (igual ao pipeline principal)
    print("\n Criando split temporal_leads para tuning...")

    data_dt = pd.to_datetime(dataset_original['Data'], errors='coerce')
    data_min = data_dt.min()
    data_max = data_dt.max()

    df_indices = pd.DataFrame({'index': range(len(dataset_original)), 'Data': data_dt}).sort_values('Data').reset_index(drop=True)
    n_total = len(df_indices)
    n_train = int(n_total * 0.7)
    train_indices = df_indices['index'].iloc[:n_train].values
    test_indices = df_indices['index'].iloc[n_train:].values
    data_corte = df_indices['Data'].iloc[n_train - 1]

    X = dataset_encoded.drop(columns=['target'])
    y = dataset_encoded['target']

    # Limpar nomes das colunas
    X.columns = X.columns.str.replace('[^A-Za-z0-9_]', '_', regex=True)
    X.columns = X.columns.str.replace('__+', '_', regex=True)
    X.columns = X.columns.str.strip('_')

    X_train = X.iloc[train_indices]
    X_test = X.iloc[test_indices]
    y_train = y.iloc[train_indices]
    y_test = y.iloc[test_indices]

    # Sample weights alinhados com o treino
    w_train = buyer_weights.iloc[train_indices].values if buyer_weights is not None else None

    print(f"  Período: {data_min.date()} a {data_max.date()}")
    print(f"  Corte: {data_corte.date()}")
    print(f"  Treino: {len(X_train):,} leads | Taxa: {y_train.mean()*100:.2f}%")
    print(f"  Teste: {len(X_test):,} leads | Taxa: {y_test.mean()*100:.2f}%")

    # Definir grid de hiperparâmetros
    print(f"\n Definindo grid de hiperparâmetros (size={grid_size})...")

    if grid_size == 'small':
        # Grid focado - teste rápido
        param_grid = {
            'n_estimators': [100],
            'max_depth': [8, 10, 12],
            'min_samples_split': [2, 5],
            'min_samples_leaf': [1],
            'max_features': ['sqrt']
        }
    elif grid_size == 'medium':
        # Grid médio - baseado no experimento original
        param_grid = {
            'n_estimators': [100, 200],
            'max_depth': [8, 10, 12],
            'min_samples_split': [2, 5],
            'min_samples_leaf': [1, 3],
            'max_features': ['sqrt', 'log2']
        }
    else:  # large
        # Grid completo
        param_grid = {
            'n_estimators': [100, 200, 300],
            'max_depth': [8, 10, 12, None],
            'min_samples_split': [2, 5],
            'min_samples_leaf': [1, 3],
            'max_features': ['sqrt', 'log2']
        }

    fixed_params = {
        'class_weight': 'balanced',
        'random_state': 42,
        'n_jobs': -1
    }

    total_combinations = 1
    for values in param_grid.values():
        total_combinations *= len(values)

    print(f"  Total de combinações: {total_combinations}")
    for param, values in param_grid.items():
        print(f"    {param}: {values}")

    # Treinar baseline
    print("BASELINE")

    start_time = time.time()

    baseline_rf = RandomForestClassifier(**baseline_params)
    baseline_rf.fit(X_train, y_train, sample_weight=w_train)
    baseline_prob = baseline_rf.predict_proba(X_test)[:, 1]
    baseline_metricas = calcular_metricas_ranking(y_test, baseline_prob)

    baseline_time = time.time() - start_time

    print(f"\nBaseline treinado em {baseline_time:.1f}s")
    print(f"  AUC: {baseline_metricas['auc']:.4f}")
    print(f"  Top 3 decis: {baseline_metricas['top3_conv']:.1f}%")
    print(f"  Top 5 decis: {baseline_metricas['top5_conv']:.1f}%")
    print(f"  Lift máximo: {baseline_metricas['lift_max']:.2f}x")
    print(f"  Separação D10/D1: {baseline_metricas['separacao_d10_d1']:.2f}x")
    print(f"  Monotonia: {baseline_metricas['monotonia']:.1f}%")

    # Grid search
    print("GRID SEARCH")

    resultados = []
    melhor_auc = baseline_metricas['auc']

    start_grid = time.time()

    for i, params in enumerate(ParameterGrid(param_grid), 1):
        full_params = {**params, **fixed_params}

        try:
            start_model = time.time()
            rf = RandomForestClassifier(**full_params)
            rf.fit(X_train, y_train, sample_weight=w_train)
            y_prob = rf.predict_proba(X_test)[:, 1]
            model_time = time.time() - start_model

            metricas = calcular_metricas_ranking(y_test, y_prob)

            if metricas:
                resultado = {
                    'combinacao': i,
                    'params': full_params.copy(),
                    'tempo': model_time,
                    **metricas
                }
                resultados.append(resultado)

                if metricas['auc'] > melhor_auc:
                    melhor_auc = metricas['auc']

                # Progress
                if i % 5 == 0 or i == total_combinations:
                    print(f"[{i:2d}/{total_combinations}] "
                          f"AUC: {metricas['auc']:.4f} | "
                          f"Top3: {metricas['top3_conv']:.1f}% | "
                          f"Sep: {metricas['separacao_d10_d1']:.1f}x | "
                          f"Mono: {metricas['monotonia']:.0f}%")

        except Exception as e:
            logger.warning(f"Erro na combinação {i}: {str(e)[:50]}")
            continue

    grid_time = time.time() - start_grid

    print(f"\nGrid search concluído em {grid_time:.1f}s")
    print(f"Modelos válidos: {len(resultados)}/{total_combinations}")

    # Análise dos resultados
    if len(resultados) == 0:
        print(" Nenhum modelo válido treinado")
        return None

    print("TOP 10 CONFIGURAÇÕES")

    # Ordenar por AUC
    resultados_sorted = sorted(resultados, key=lambda x: x['auc'], reverse=True)

    print(f"{'#':<3} {'AUC':<7} {'Top3':<6} {'Sep':<6} {'Mono':<6} {'Params'}")
    print("-" * 90)

    for i, r in enumerate(resultados_sorted[:10], 1):
        params_str = f"depth:{r['params']['max_depth']}, " \
                     f"split:{r['params']['min_samples_split']}, " \
                     f"leaf:{r['params']['min_samples_leaf']}, " \
                     f"n_est:{r['params']['n_estimators']}"

        print(f"{i:<3} {r['auc']:.4f}  {r['top3_conv']:5.1f}% "
              f"{r['separacao_d10_d1']:5.1f}x {r['monotonia']:5.0f}% {params_str}")

    # Melhor resultado
    melhor = resultados_sorted[0]

    print("COMPARAÇÃO: BASELINE vs MELHOR")

    print(f"\nBASELINE:")
    print(f"  AUC: {baseline_metricas['auc']:.4f}")
    print(f"  Top 3 decis: {baseline_metricas['top3_conv']:.1f}%")
    print(f"  Lift máximo: {baseline_metricas['lift_max']:.2f}x")
    print(f"  Separação D10/D1: {baseline_metricas['separacao_d10_d1']:.2f}x")
    print(f"  Monotonia: {baseline_metricas['monotonia']:.1f}%")

    print(f"\nMELHOR:")
    print(f"  AUC: {melhor['auc']:.4f}")
    print(f"  Top 3 decis: {melhor['top3_conv']:.1f}%")
    print(f"  Lift máximo: {melhor['lift_max']:.2f}x")
    print(f"  Separação D10/D1: {melhor['separacao_d10_d1']:.2f}x")
    print(f"  Monotonia: {melhor['monotonia']:.1f}%")

    # Melhorias
    melhoria_auc = ((melhor['auc'] - baseline_metricas['auc']) / baseline_metricas['auc']) * 100
    sep_base = baseline_metricas['separacao_d10_d1']
    melhoria_separacao = ((melhor['separacao_d10_d1'] - sep_base) / sep_base) * 100 if sep_base != 0 else 0.0

    print(f"\nMELHORIAS:")
    print(f"  AUC: {melhoria_auc:+.2f}%")
    print(f"  Separação D10/D1: {melhoria_separacao:+.1f}%")
    print(f"  Top 3 decis: {melhor['top3_conv'] - baseline_metricas['top3_conv']:+.1f} pp")

    # Hiperparâmetros recomendados
    print("HIPERPARÂMETROS RECOMENDADOS")

    for param, value in melhor['params'].items():
        if param not in ['random_state', 'n_jobs']:
            baseline_value = baseline_params.get(param, 'N/A')
            mudou = '' if value != baseline_value else '  '
            print(f"{mudou} {param}: {value}")

    # Recomendação
    print("RECOMENDAÇÃO")

    if melhoria_auc > 1.0:
        print(f" RECOMENDADO: Usar hiperparâmetros tunados")
        print(f"   Melhoria significativa: AUC +{melhoria_auc:.2f}%, Separação +{melhoria_separacao:.1f}%")
    elif melhoria_auc > 0.3:
        print(f"  CONSIDERAR: Melhoria marginal (+{melhoria_auc:.2f}%)")
        print(f"   Avaliar se vale o trade-off")
    else:
        print(f" NÃO RECOMENDADO: Melhoria insignificante (+{melhoria_auc:.2f}%)")
        print(f"   Manter baseline")

    return {
        'baseline': baseline_metricas,
        'melhor': melhor,
        'top_10': resultados_sorted[:10],
        'todos': resultados_sorted,
        'melhores_params': melhor['params'],
        'usar_tunado': melhoria_auc > 0.3
    }
