"""
core/encoding.py — Encoding categórico e ordinal (versão produção é canônica).

Consolida encoding_training.py e encoding.py.
Divergências ativas:
  - Produção tem feature registry + reordenação; treino não
  - Treino usa nomes normalizados ('idade', 'faixa_salarial') no ordinal;
    produção usa nomes longos ('Qual a sua idade?', 'Atualmente, qual a sua faixa salarial?')

A versão de produção (encoding.py) é a canônica. A versão de treino
passa a usar esta após a migração.

Componente 3 da Fase 2.
Hardcodes a migrar: #49, #50, #51, #64, #70, #71 → EncodingConfig.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .client_config import EncodingConfig


def apply_encoding(df: pd.DataFrame, config: EncodingConfig,
                   artifacts: Dict[str, Any]) -> pd.DataFrame:
    """
    Aplica encoding estratégico: ordinal, binary_top3, one-hot.
    Inclui feature registry e reordenação (versão canônica da produção).

    artifacts: dict com encoders e mapeamentos carregados do modelo ativo.

    Usa config.ordinal_variables (#49), config.binary_top3_categories (#50, via MediumConfig),
    config.features_to_drop_after_encoding (#51),
    config.categorical_detection_max_unique (#64),
    config.column_name_corrections (#70).
    """
    raise NotImplementedError
