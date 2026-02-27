"""
core/ingestion.py — Ingestão e filtragem de dados brutos.

Consolida funções de ingestion.py e column_unification_refactored.py:
  - filter_sheets: ingestion.py
  - remove_duplicates_per_sheet: ingestion.py / preprocessing.py
  - consolidate_datasets: ingestion.py
  - filter_sales_by_product: column_unification_refactored.py:536
  - aplicar_filtro_status_risco: column_unification_refactored.py (guarded por has_tmb)
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

from .client_config import IngestionConfig


def filter_sheets(sheets: Dict[str, pd.DataFrame],
                  config: IngestionConfig) -> Dict[str, pd.DataFrame]:
    """
    Filtra abas do Excel mantendo apenas as relevantes para treino.
    Usa config.ingestion (termos_manter, termos_remover, min_survey_columns).
    """
    raise NotImplementedError


def remove_duplicates_per_sheet(sheets: Dict[str, pd.DataFrame],
                                 config: IngestionConfig) -> Dict[str, pd.DataFrame]:
    """Remove duplicatas dentro de cada aba individualmente."""
    raise NotImplementedError


def consolidate_datasets(sheets: Dict[str, pd.DataFrame],
                          config: IngestionConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Consolida abas em dois DataFrames: pesquisa e vendas.
    Retorna (df_pesquisa, df_vendas).
    """
    raise NotImplementedError


def filter_sales_by_product(df_vendas: pd.DataFrame,
                              config: IngestionConfig) -> pd.DataFrame:
    """
    Filtra vendas pelo produto do cliente.
    Usa config.product_filter_keyword (#24).
    """
    raise NotImplementedError


def aplicar_filtro_status_risco(df: pd.DataFrame,
                                 config: IngestionConfig) -> pd.DataFrame:
    """
    Filtra leads por grau de risco TMB.
    Executada apenas se config.has_tmb is True (#12).
    Usa config.tmb_risk_column (#23) e config.tmb_risk_values (#62).
    """
    raise NotImplementedError
