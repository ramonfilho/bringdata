"""
core/category_unification.py — Normalização semântica de categorias.

Migra category_unification.py (já compartilhado entre treino, produção e
monitoring — sem divergência). A migração formaliza o contrato e remove
os hardcodes #27–#33 para CategoryConfig.

Dois passos:
  1. limpar_texto em todas as colunas de config.categorical_columns (#27)
     (lowercase + unidecode + remove pontuação)
  2. Mapeamento semântico por coluna via config.category_mappings (#28–#33)
     {column_name: {old_value: new_value}}
"""

from __future__ import annotations

import re
import logging
from typing import Optional

import pandas as pd
from unidecode import unidecode

from .client_config import CategoryConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilitário de normalização de texto (candidato a core/utils.py)
# ---------------------------------------------------------------------------

def _limpar_texto(texto) -> object:
    """
    Normalização canônica de texto para categorias.

    Remove caracteres invisíveis, aplica lowercase, remove acentos via unidecode,
    remove pontuação e normaliza espaços múltiplos.

    Crítico para paridade treino/produção: garante que variantes de case e acentuação
    ('autônomo' vs 'autonomo', 'SIM' vs 'sim') sejam tratadas identicamente.
    """
    if pd.isna(texto):
        return texto
    s = str(texto)
    s = s.replace('\u2060', '').replace('\xa0', ' ').replace('\u200b', '')
    s = s.strip().lower()
    s = unidecode(s)
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ---------------------------------------------------------------------------
# Função pública
# ---------------------------------------------------------------------------

def unify_categories(df: pd.DataFrame, config: CategoryConfig) -> pd.DataFrame:
    """
    Normaliza colunas categóricas: limpar_texto + mapeamentos semânticos.

    Passo 1 — limpar_texto em config.categorical_columns (#27):
        Aplica lowercase + unidecode + remove pontuação às colunas listadas.
        Colunas NÃO incluídas intencionalmente: E-mail, Telefone, Data, Medium,
        Source, e colunas binárias Sim/Não cujos feature names dependem do acento
        original ('Não' → sufixo '_N_o'; 'nao' → sufixo '_nao' — ERRADO).

    Passo 2 — mapeamentos semânticos via config.category_mappings (#28–#33):
        Dict {column_name: {old_value: new_value}}.
        Aplicado APÓS limpar_texto para que as chaves do mapa usem valores
        já normalizados.

    Args:
        df:     DataFrame com colunas categóricas a normalizar.
        config: CategoryConfig carregado de configs/clients/{client}.yaml.

    Returns:
        Novo DataFrame com categorias unificadas.
    """
    df = df.copy()

    # ------------------------------------------------------------------
    # Passo 1 — limpar_texto nas colunas configuradas
    # ------------------------------------------------------------------
    cols_to_clean = [c for c in (config.categorical_columns or []) if c in df.columns]
    for col in cols_to_clean:
        df[col] = df[col].apply(_limpar_texto)
    logger.info(f"  Categorias passo 1 (limpar_texto): {len(cols_to_clean)} colunas normalizadas")

    # ------------------------------------------------------------------
    # Passo 2 — mapeamentos semânticos por coluna
    # ------------------------------------------------------------------
    mappings = config.category_mappings or {}
    mapped_cols = 0
    for col_name, mapa in mappings.items():
        if mapa and col_name in df.columns:
            df[col_name] = df[col_name].replace(mapa)
            mapped_cols += 1
            logger.debug(f"  Categorias passo 2: {col_name} — {len(mapa)} mapeamentos")
    logger.info(f"  Categorias passo 2 (mapeamentos semânticos): {mapped_cols} colunas")

    return df
