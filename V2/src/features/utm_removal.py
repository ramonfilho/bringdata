"""
import logging

logger = logging.getLogger(__name__)
Componente para remoção de features UTM EXATAMENTE como no notebook original.
Baseado nas linhas 5223-5229 e 7696-7702 do smart_ads_devclub_eda_v3.py
"""

import pandas as pd
from typing import List


def remove_utm_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove features relacionadas a UTM EXATAMENTE como no notebook original.

    Lógica EXATA das linhas 7696-7702 do notebook:
    - colunas_utm = ['Source', 'Medium', 'Term']
    - Remove colunas que começam com '{utm}_' ou são igual a utm
    - Usa errors='ignore' no drop

    Args:
        df: DataFrame com features UTM

    Returns:
        DataFrame sem features UTM
    """
    df_clean = df.copy()

    # LÓGICA EXATA DO NOTEBOOK (linhas 7696-7702)
    colunas_utm = ['Source', 'Medium', 'Term']
    colunas_remover = []

    for col in df_clean.columns:
        for utm in colunas_utm:
            if col.startswith(f'{utm}_') or col == utm:
                colunas_remover.append(col)

    # Aplicar remoção EXATA do notebook
    df_clean = df_clean.drop(columns=colunas_remover, errors='ignore')

    logger.info(f"    Features UTM removidas: {len(colunas_remover)}")
    if colunas_remover:
        logger.info(f"    Colunas removidas: {', '.join(colunas_remover[:5])}{'...' if len(colunas_remover) > 5 else ''}")

    return df_clean


def get_utm_feature_names(df: pd.DataFrame) -> List[str]:
    """
    Identifica nomes de features UTM no DataFrame.

    Args:
        df: DataFrame para análise

    Returns:
        Lista com nomes das features UTM
    """
    utm_patterns = ['Source_', 'Medium_', 'Term_']
    utm_columns = ['Source', 'Medium', 'Term']

    utm_features = []

    # Colunas UTM originais
    for col in utm_columns:
        if col in df.columns:
            utm_features.append(col)

    # Colunas one-hot de UTM
    for col in df.columns:
        for pattern in utm_patterns:
            if col.startswith(pattern):
                utm_features.append(col)

    return utm_features


def count_utm_features(df: pd.DataFrame) -> int:
    """
    Conta quantas features UTM existem no DataFrame.

    Args:
        df: DataFrame para análise

    Returns:
        Número de features UTM
    """
    return len(get_utm_feature_names(df))