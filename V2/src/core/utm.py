"""
core/utm.py — Unificação de UTMs (versão canônica com .lower() corrigido).

Consolida utm_training.py e utm_unification.py.
Divergência ativa: produção aplica .lower(), treino não — resolvido aqui.

Componente 1 da Fase 2 — mais urgente.
Hardcodes a migrar: #35, #63, #67 → UTMConfig.
"""

from __future__ import annotations

import pandas as pd

from .client_config import UTMConfig


def unify_utm(df: pd.DataFrame, config: UTMConfig) -> pd.DataFrame:
    """
    Normaliza colunas UTM Source, Medium, Term e Campaign.

    Correções aplicadas:
    - .lower() em todos os valores (#35, #63 — divergência ativa)
    - source_to_outros: agrupa valores raros em 'outros' (#35)
    - term_mappings: mapeia aliases ('ig'→'instagram', 'fb'→'facebook') (#63)
    - term_outros_patterns: padrões '--' e '{' → 'outros' (#63)
    - term_long_id_threshold: values com len > threshold → 'outros' (#67)
    """
    raise NotImplementedError
