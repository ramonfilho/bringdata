"""
core/feature_engineering.py — Criação de features derivadas.

Consolida feature_engineering_training.py e engineering.py.
Divergência ativa: produção tem guard 'arquivo_origem' (engineering.py:183)
para detectar contexto treino vs monitoring — some ao migrar para core/
com FeatureConfig.

Componente 2 da Fase 2.
Hardcodes a migrar: #41, #42, #47, #48 → FeatureConfig.
"""

from __future__ import annotations

import pandas as pd

from .client_config import FeatureConfig


def create_features(df: pd.DataFrame, config: FeatureConfig) -> pd.DataFrame:
    """
    Cria features derivadas: nome, email, telefone, dia da semana, etc.
    Remove colunas desnecessárias após o engineering.
    Usa config.pesquisa_name_column (#47) e config.columns_to_drop_after_fe (#48).
    Guards de colunas unificados — sem divergência entre treino e produção.
    """
    raise NotImplementedError
