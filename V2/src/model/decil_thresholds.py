"""
Módulo para calcular thresholds fixos de decis baseados nas probabilidades do test set.

Este módulo calcula os limites (min/max) de probabilidade para cada decil D1-D10,
permitindo atribuição consistente de decis em produção sem depender de pd.qcut.

Autor: Claude
Data: 2025-11-11
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def calcular_thresholds_decis(y_prob: np.ndarray, decis: pd.Series) -> dict:
    """
    Calcula thresholds de probabilidade para cada decil baseado no test set.

    Args:
        y_prob: Array de probabilidades preditas (test set)
        decis: Series com decis atribuídos (D1-D10) via pd.qcut

    Returns:
        Dict com thresholds por decil:
        {
            'D1': {'min': 0.000, 'max': 0.045, 'count': 3276, 'mean_prob': 0.023},
            'D2': {'min': 0.045, 'max': 0.082, 'count': 3275, 'mean_prob': 0.064},
            ...
        }
    """
    logger.info("Calculando thresholds fixos de decis...")

    # Criar DataFrame para análise
    df_analise = pd.DataFrame({
        'probabilidade': y_prob,
        'decil': decis
    })

    thresholds = {}

    # Calcular limites para cada decil
    for i in range(1, 11):
        decil_label = f'D{i}'
        decil_probs = df_analise[df_analise['decil'] == decil_label]['probabilidade']

        if len(decil_probs) == 0:
            logger.warning(f"⚠️  Decil {decil_label} vazio! Pulando...")
            continue

        thresholds[decil_label] = {
            'threshold_min': float(decil_probs.min()),
            'threshold_max': float(decil_probs.max()),
            'count': int(len(decil_probs)),
            'mean_probability': float(decil_probs.mean()),
            'std_probability': float(decil_probs.std())
        }

        logger.info(f"   {decil_label}: [{decil_probs.min():.4f}, {decil_probs.max():.4f}] "
                   f"(n={len(decil_probs)}, mean={decil_probs.mean():.4f})")

    # Validar thresholds
    _validar_thresholds(thresholds)

    logger.info(f"✅ Thresholds calculados para {len(thresholds)} decis")

    return thresholds


def _validar_thresholds(thresholds: dict):
    """
    Valida que os thresholds estão bem formados e não têm gaps.

    Args:
        thresholds: Dict com thresholds por decil

    Raises:
        ValueError: Se thresholds inválidos
    """
    # Verificar ordem crescente
    decis_ordenados = sorted(thresholds.keys(), key=lambda x: int(x[1:]))

    for i in range(len(decis_ordenados) - 1):
        decil_atual = decis_ordenados[i]
        decil_prox = decis_ordenados[i + 1]

        max_atual = thresholds[decil_atual]['threshold_max']
        min_prox = thresholds[decil_prox]['threshold_min']

        # Gap muito grande entre decis (>0.01) pode indicar problema
        gap = min_prox - max_atual
        if gap > 0.01:
            logger.warning(f"⚠️  Gap detectado entre {decil_atual} e {decil_prox}: {gap:.4f}")

        # Overlap entre decis
        if max_atual > min_prox:
            logger.warning(f"⚠️  Overlap detectado entre {decil_atual} e {decil_prox}: "
                         f"{decil_atual}_max={max_atual:.4f} > {decil_prox}_min={min_prox:.4f}")


def normalizar_thresholds(thresholds: dict) -> dict:
    """
    Normaliza chaves de thresholds para formato com zeros (D1 -> D01, D9 -> D09).

    Args:
        thresholds: Dict com thresholds (pode ter chaves D1-D10 ou D01-D10)

    Returns:
        Dict com chaves normalizadas (D01-D10)
    """
    thresholds_normalizados = {}

    for key, value in thresholds.items():
        # Converter D1-D9 para D01-D09, manter D10 como D10
        decil_formatado = formatar_decil(key)
        thresholds_normalizados[decil_formatado] = value

    return thresholds_normalizados


def formatar_decil(decil: str) -> str:
    """
    Formata decil com zero à esquerda (D1 -> D01, D2 -> D02, ..., D10 -> D10).

    Args:
        decil: Decil no formato D1-D10 ou D01-D10

    Returns:
        Decil formatado (D01-D10)
    """
    num = int(decil.replace('D', ''))
    return f'D{num:02d}'


def atribuir_decil_por_threshold(score: float, thresholds: dict) -> str:
    """
    Atribui decil baseado em thresholds fixos.

    Args:
        score: Probabilidade predita (0-1)
        thresholds: Dict com thresholds por decil (chaves devem estar normalizadas D01-D10)

    Returns:
        Label do decil formatado (D01-D10)
    """
    # Ordenar decis por threshold_min
    decis_ordenados = sorted(
        thresholds.items(),
        key=lambda x: x[1]['threshold_min']
    )

    # Buscar decil apropriado
    for decil, limits in decis_ordenados:
        if limits['threshold_min'] <= score <= limits['threshold_max']:
            return decil  # Já está formatado

    # Fallback: se score > max(D10), retornar D10
    # Aceitar tanto D10 quanto D1-D9 (normalizar se necessário)
    d10_key = 'D10' if 'D10' in thresholds else formatar_decil('D10')
    d1_key = 'D01' if 'D01' in thresholds else 'D1'

    if d10_key in thresholds and score > thresholds[d10_key]['threshold_max']:
        return d10_key

    # Fallback: se score < min(D1), retornar D1
    if d1_key in thresholds and score < thresholds[d1_key]['threshold_min']:
        return d1_key

    # Caso extremo: buscar decil mais próximo
    logger.warning(f"⚠️  Score {score:.4f} não encontrado em nenhum threshold, usando decil mais próximo")

    distancias = []
    for decil, limits in thresholds.items():
        mid_point = (limits['threshold_min'] + limits['threshold_max']) / 2
        distancias.append((decil, abs(score - mid_point)))

    decil_mais_proximo = min(distancias, key=lambda x: x[1])[0]
    return decil_mais_proximo  # Já está formatado


def atribuir_decis_batch(scores: np.ndarray, thresholds: dict) -> list:
    """
    Atribui decis para um batch de scores usando thresholds fixos.

    Args:
        scores: Array de probabilidades preditas
        thresholds: Dict com thresholds por decil

    Returns:
        Lista de labels de decis formatados (D01-D10)
    """
    return [atribuir_decil_por_threshold(score, thresholds) for score in scores]


def comparar_distribuicoes(decis_qcut: pd.Series, decis_threshold: list, verbose: bool = True) -> dict:
    """
    Compara distribuição de decis entre pd.qcut (treino) e thresholds fixos (produção).

    Args:
        decis_qcut: Decis originais via pd.qcut
        decis_threshold: Decis via thresholds fixos
        verbose: Se True, imprime comparação

    Returns:
        Dict com estatísticas de comparação
    """
    dist_qcut = decis_qcut.value_counts().sort_index()
    dist_threshold = pd.Series(decis_threshold).value_counts().sort_index()

    if verbose:
        print("COMPARAÇÃO: pd.qcut vs Thresholds Fixos")
        print(f"{'Decil':<8} {'pd.qcut':<12} {'Threshold':<12} {'Diferença':<12} {'% Diff':<10}")
        print("-" * 80)

        for decil in [f'D{i}' for i in range(1, 11)]:
            count_qcut = dist_qcut.get(decil, 0)
            count_threshold = dist_threshold.get(decil, 0)
            diff = count_threshold - count_qcut
            pct_diff = (diff / count_qcut * 100) if count_qcut > 0 else 0

            print(f"{decil:<8} {count_qcut:<12} {count_threshold:<12} "
                  f"{diff:+12} {pct_diff:+9.1f}%")


    # Calcular estatísticas
    total = len(decis_qcut)
    diferencas = []

    for decil in [f'D{i}' for i in range(1, 11)]:
        count_qcut = dist_qcut.get(decil, 0)
        count_threshold = dist_threshold.get(decil, 0)
        diff_abs = abs(count_threshold - count_qcut)
        diferencas.append(diff_abs)

    return {
        'total_leads': total,
        'max_diferenca_absoluta': max(diferencas),
        'media_diferenca_absoluta': sum(diferencas) / len(diferencas),
        'max_diferenca_percentual': max(diferencas) / (total / 10) * 100,
        'distribuicao_qcut': dist_qcut.to_dict(),
        'distribuicao_threshold': dist_threshold.to_dict()
    }
