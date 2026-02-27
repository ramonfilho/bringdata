"""
core/preprocessing.py — Sequência canônica de pré-processamento.

Define a ordem garantida por construção:
  remove_duplicates → clean_columns → remove_campaign_features →
  rename_long_column_names → remove_technical_fields

Treino e produção chamam preprocess(df, config) — sequência idêntica.
Monitoring chama com wrapper de preservação de decil/lead_score.

Elimina as implementações paralelas em:
  - train_pipeline.py (inline)
  - preprocessing.py (produção)
  - feature_removal.py

Componente 5 da Fase 2.
Hardcodes a migrar: #34, #68, #69 → IngestionConfig / FeatureConfig.
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from .client_config import FeatureConfig, IngestionConfig
from . import utils


def preprocess(df: pd.DataFrame,
               ingestion_config: IngestionConfig,
               feature_config: FeatureConfig) -> pd.DataFrame:
    """
    Aplica a sequência canônica de pré-processamento.
    Chama internamente utils.remove_columns com listas do config.
    """
    raise NotImplementedError


def preprocess_for_monitoring(df: pd.DataFrame,
                               ingestion_config: IngestionConfig,
                               feature_config: FeatureConfig) -> pd.DataFrame:
    """
    Wrapper para monitoring: preserva colunas 'decil' e 'lead_score'
    em torno de preprocess().
    """
    raise NotImplementedError
