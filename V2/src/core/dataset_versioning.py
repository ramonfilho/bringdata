"""
core/dataset_versioning.py — Versionamento e janela de conversão.

Usado apenas no treino (produção não aplica).
Consolida dataset_versioning_training.py e conversion_window.py.
Executado após todas as unificações anteriores.

Hardcodes a migrar: #9, #38, #39, #40 → IngestionConfig / FeatureConfig / MonitoringConfig.
"""

from __future__ import annotations

import pandas as pd

from .client_config import FeatureConfig, IngestionConfig, MonitoringConfig


def criar_dataset_pos_cutoff(df: pd.DataFrame,
                              config: IngestionConfig,
                              feature_config: FeatureConfig) -> pd.DataFrame:
    """
    Remove linhas anteriores ao cutoff e colunas com alto missing pós-cutoff.
    Usa config.dataset_cutoff_date (#38) e feature_config.columns_to_remove_post_cutoff (#39).
    Monitora feature_config.critical_columns (#3, #40).
    """
    raise NotImplementedError


def aplicar_janela_conversao(df: pd.DataFrame,
                              config: MonitoringConfig) -> pd.DataFrame:
    """
    Aplica janela de conversão para definir o target de compra.
    Usa config.conversion_window_days (#9).
    """
    raise NotImplementedError
