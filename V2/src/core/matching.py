"""
core/matching.py — Matching leads→vendas (consolida 6 arquivos atuais).

Substitui:
  - matching_email_only.py
  - matching_email_telefone.py
  - matching_email_with_validation.py
  - matching_robusto.py
  - matching_training.py
  - matching_unified.py

A estratégia é controlada por config.strategy:
  - 'email_only'
  - 'email_telefone'
  - 'robusto'
  - 'email_with_validation'

Hardcodes a migrar: #41–#46 → MatchingConfig.
"""

from __future__ import annotations

import pandas as pd

from .client_config import MatchingConfig


def match_leads(df_leads: pd.DataFrame, df_vendas: pd.DataFrame,
                config: MatchingConfig) -> pd.DataFrame:
    """
    Faz matching entre leads da pesquisa e vendas.
    Estratégia definida por config.strategy.
    Usa config.pesquisa_email_column (#41), pesquisa_phone_column (#42),
    country_code (#43), phone_digits (#43).
    """
    raise NotImplementedError
