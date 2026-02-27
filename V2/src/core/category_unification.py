"""
core/category_unification.py — Normalização semântica de categorias.

Migra category_unification.py (já compartilhado entre treino, produção e
monitoring — sem divergência). A migração formaliza o contrato e remove
os hardcodes #27–#33 para CategoryConfig.
"""

from __future__ import annotations

import pandas as pd

from .client_config import CategoryConfig


def unify_categories(df: pd.DataFrame, config: CategoryConfig) -> pd.DataFrame:
    """
    Normaliza colunas categóricas removendo variantes de case e aliases.
    Usa config.categorical_columns (#27) e config.category_mappings (#28–#33).
    """
    raise NotImplementedError
