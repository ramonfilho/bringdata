"""
Módulo para unificação de colunas duplicadas.

NOTA: A função principal `unificar_colunas_datasets` foi refatorada e movida para
column_unification_refactored.py, dividida em 4 sub-células (5, 5.1, 5.2, 5.3).

Este arquivo mantém apenas funções auxiliares que ainda são utilizadas.
"""

import pandas as pd
from typing import Tuple, List
import logging

logger = logging.getLogger(__name__)


def identificar_colunas_duplicadas_pesquisa(df: pd.DataFrame) -> List[Tuple[str, str]]:
    """
    Identifica todas as colunas duplicadas no dataset de pesquisa.

    Args:
        df: DataFrame de pesquisa

    Returns:
        Lista de tuplas (col1, col2) de colunas duplicadas
    """
    colunas = df.columns.tolist()
    duplicadas = []

    # Verificar padrões de duplicação
    for i, col1 in enumerate(colunas):
        for j, col2 in enumerate(colunas[i+1:], i+1):
            # Comparar início das strings (truncadas podem ser iguais)
            if col1[:30] == col2[:30] and col1 != col2:
                duplicadas.append((col1, col2))

    return duplicadas
