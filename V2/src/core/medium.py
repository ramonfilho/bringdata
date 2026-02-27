"""
core/medium.py — Unificação de Medium (consolida 3 arquivos atuais).

Substitui:
  - medium_training.py
  - medium_production_training.py
  - medium_unification.py

Divergências ativas:
  - mapping_dict difere entre treino e produção (#7)
  - aplicar_unificacao_robusta com lógicas distintas
  - manual_unifications: produção tem subset do treino (#37)

Componente 4 da Fase 2 — etapa mais trabalhosa.
Hardcodes a migrar: #7, #36, #37 → MediumConfig.
"""

from __future__ import annotations

import pandas as pd

from .client_config import MediumConfig


def unify_medium(df: pd.DataFrame, config: MediumConfig) -> pd.DataFrame:
    """
    Unifica coluna Medium em categorias canônicas.

    Operações:
    - Remove prefixo ADV do cliente (config.adv_prefix, #36)
    - Aplica mapeamento de categorias históricas (config.category_mappings, #7)
    - Aplica unificações manuais de case (config.manual_unifications, #37)
    - Classifica categorias descontinuadas (config.discontinued_categories, #7)
    - Aplica estratégia binary_top3 (config.binary_top3_categories, #50)
    """
    raise NotImplementedError
