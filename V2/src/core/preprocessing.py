"""
core/preprocessing.py — Sequência canônica de pré-processamento.

Define a ordem garantida por construção:
  remove_duplicates → clean_columns → remove_campaign_features →
  rename_long_column_names

Treino e produção chamam preprocess(df, config) — sequência idêntica.
Monitoring chama preprocess_for_monitoring() com wrapper de preservação
de decil/lead_score.

Elimina as implementações paralelas em:
  - train_pipeline.py (inline)
  - preprocessing.py (produção)
  - feature_removal.py

Componente 5 da Fase 2.
Hardcodes migrados para config: #34 (feature.columns_to_remove),
#68 (ingestion.column_rename_mapping), #69 (ingestion.columns_to_remove).
"""

from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from .client_config import FeatureConfig, IngestionConfig
from . import utils

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults — usados quando o YAML ainda não tem esses campos preenchidos.
# Permitem que preprocessing.py funcione durante a migração incremental.
# Remover quando devclub.yaml estiver completamente preenchido.
# ---------------------------------------------------------------------------

# #69 — colunas a remover (score/faixa + técnicas)
_DEFAULT_COLUMNS_TO_REMOVE: List[str] = [
    # Score/faixa (resultado do modelo, não features de entrada)
    'Pontuação', 'Score', 'Faixa', 'Faixa A', 'Faixa B', 'Faixa C', 'Faixa D',
    # Campos técnicos (vazios ou irrelevantes para o modelo)
    'Remote IP', 'User Agent', 'fbc', 'fbp',
    'cidade', 'estado', 'pais', 'cep', 'externalid',
    'Page URL', 'Qual estado você mora?',
]

# Prefixos de colunas de score a remover por pattern matching (#60)
_SCORE_PREFIXES: List[str] = [
    'score', 'faixa', 'pontuação', 'pontuacao', 'lead_score', 'decil',
]

# #34 — features com data leakage temporal a remover
_DEFAULT_CAMPAIGN_FEATURES: List[str] = ['Campaign', 'Content']

# #68 — renomeação de colunas com nomes longos (mesmas strings de #13 e #14)
_DEFAULT_RENAME_MAPPING = {
    'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?': 'investiu_curso_online',
    'O que mais te chama atenção na profissão de Programador?': 'interesse_programacao',
}


# ---------------------------------------------------------------------------
# Funções internas
# ---------------------------------------------------------------------------

def _remove_score_columns(df: pd.DataFrame,
                           columns_to_remove: List[str]) -> pd.DataFrame:
    """
    Remove colunas de score/faixa/técnicas.
    Usa lista explícita + pattern matching por prefixo + colunas Unnamed.
    """
    remove_lower = {c.lower() for c in columns_to_remove}
    cols_to_drop = []

    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower in remove_lower:
            cols_to_drop.append(col)
        elif str(col).startswith('Unnamed:'):
            cols_to_drop.append(col)
        elif any(col_lower.startswith(p) for p in _SCORE_PREFIXES):
            cols_to_drop.append(col)

    if cols_to_drop:
        logger.debug(f"  clean_columns: removendo {len(cols_to_drop)} colunas: {cols_to_drop}")

    return utils.remove_columns(df, cols_to_drop)


def _remove_campaign_and_problematic(df: pd.DataFrame,
                                      campaign_cols: List[str]) -> pd.DataFrame:
    """Remove colunas de campanha (data leakage) e colunas com nomes problemáticos."""
    problematic = utils.detect_problematic_columns(df)
    to_drop = [c for c in (campaign_cols + problematic) if c in df.columns]

    if to_drop:
        logger.debug(f"  remove_campaign_features: removendo {len(to_drop)} colunas: {to_drop}")

    return utils.remove_columns(df, to_drop)


def _rename_long_columns(df: pd.DataFrame,
                          rename_mapping: dict) -> pd.DataFrame:
    """Renomeia colunas com nomes longos de formulário para versões curtas."""
    cols_to_rename = {k: v for k, v in rename_mapping.items() if k in df.columns}
    if cols_to_rename:
        logger.debug(f"  rename_columns: {list(cols_to_rename.keys())}")
        df = df.rename(columns=cols_to_rename)
    return df


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def preprocess(df: pd.DataFrame,
               ingestion_config: IngestionConfig,
               feature_config: FeatureConfig,
               extra_columns_to_remove: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Aplica a sequência canônica de pré-processamento.

    Sequência:
      1. remove_duplicates
      2. clean_columns  (score/faixa/técnicas via ingestion_config.columns_to_remove)
      3. remove_campaign_features  (Campaign/Content via feature_config.columns_to_remove)
      4. rename_long_column_names  (via ingestion_config.column_rename_mapping)

    extra_columns_to_remove: colunas adicionais a remover no step 3 (ex: ['Medium']
        quando medium_strategy='remove' no train_pipeline).
    """
    n_inicio = len(df)

    # 1. Remover duplicatas
    df = df.drop_duplicates(keep='first')
    n_apos_dedup = len(df)
    if n_apos_dedup < n_inicio:
        logger.debug(f"  remove_duplicates: {n_inicio - n_apos_dedup} removidas")

    # 2. Remover colunas de score/faixa/técnicas
    columns_to_remove = ingestion_config.columns_to_remove or _DEFAULT_COLUMNS_TO_REMOVE
    df = _remove_score_columns(df, columns_to_remove)

    # 3. Remover colunas de campanha (data leakage) + problemáticas + extras
    campaign_cols = list(feature_config.columns_to_remove or _DEFAULT_CAMPAIGN_FEATURES)
    if extra_columns_to_remove:
        campaign_cols = campaign_cols + [c for c in extra_columns_to_remove if c not in campaign_cols]
    df = _remove_campaign_and_problematic(df, campaign_cols)

    # 4. Renomear colunas longas
    rename_mapping = ingestion_config.column_rename_mapping or _DEFAULT_RENAME_MAPPING
    df = _rename_long_columns(df, rename_mapping)

    return df


def preprocess_for_monitoring(df: pd.DataFrame,
                               ingestion_config: IngestionConfig,
                               feature_config: FeatureConfig) -> pd.DataFrame:
    """
    Wrapper para monitoring: preserva 'decil' e 'lead_score' em torno de preprocess().

    O monitoring recebe dados do Google Sheets que já têm decil/lead_score atribuídos
    pelo pipeline de produção. preprocess() remove essas colunas (prefixo 'decil',
    'lead_score'). Este wrapper as salva antes e restaura depois, garantindo que o
    monitoring possa comparar o score atual com o histórico.
    """
    # Salvar colunas de score antes do preprocessing
    decil_col = df['decil'].copy() if 'decil' in df.columns else None
    lead_score_col = df['lead_score'].copy() if 'lead_score' in df.columns else None

    # Aplicar sequência canônica (remove decil/lead_score como efeito colateral)
    df = preprocess(df, ingestion_config, feature_config)

    # Restaurar — alinha por índice para sobreviver ao drop_duplicates
    if decil_col is not None:
        df['decil'] = decil_col.reindex(df.index)
    if lead_score_col is not None:
        df['lead_score'] = lead_score_col.reindex(df.index)

    return df
