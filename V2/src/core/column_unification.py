"""
core/column_unification.py — Unificação e filtro temporal de colunas.

Consolida column_unification_refactored.py:
  - unify_columns: unifica colunas de pesquisa e vendas por merge_rules (#13–#20)
  - aplicar_filtro_temporal: filtra por data de corte (#38)
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .client_config import IngestionConfig


def unify_columns(df: pd.DataFrame,
                  merge_rules: Dict[str, Any]) -> pd.DataFrame:
    """
    Unifica colunas com nomes distintos em uma coluna canônica.
    merge_rules vem de config.ingestion.column_unification (#13–#20).
    """
    raise NotImplementedError


def aplicar_filtro_temporal(df: pd.DataFrame,
                             config: IngestionConfig) -> pd.DataFrame:
    """
    Remove linhas anteriores ao dataset_cutoff_date (#38).
    Usa config.pesquisa_date_column (#25).
    """
    raise NotImplementedError
