"""
core/utm.py — Unificação de UTMs (versão canônica).

Consolida utm_training.py (treino) e utm_unification.py (produção).

Decisões canônicas do audit de paridade (2026-03-08):
- .lower() em Source: produção é canônica — normaliza antes de qualquer mapeamento
- source_to_channel_mapping: treino é canônico — youtube-bio → youtube (não → outros)
- source_to_outros: treino é canônico — lista mais completa (inclui utm_source, BIO, livesemanal)
- Term: lógica idêntica nas duas implementações

Hardcodes migrados: #35, #63, #67 + source_to_channel_mapping (dev/retreino)
"""

from __future__ import annotations

import logging

import pandas as pd

from .client_config import UTMConfig

logger = logging.getLogger(__name__)


def unify_utm(df: pd.DataFrame, config: UTMConfig) -> pd.DataFrame:
    """
    Normaliza colunas UTM Source e Term.

    Args:
        df: DataFrame com colunas Source e/ou Term.
        config: UTMConfig com as regras de unificação do cliente.

    Returns:
        DataFrame com UTMs normalizadas. Não modifica o DataFrame original.
    """
    df = df.copy()

    if 'Source' in df.columns:
        df = _unify_source(df, config)

    if 'Term' in df.columns:
        df = _unify_term(df, config)

    return df


# ---------------------------------------------------------------------------
# Privadas
# ---------------------------------------------------------------------------

def _unify_source(df: pd.DataFrame, config: UTMConfig) -> pd.DataFrame:
    df['Source'] = df['Source'].astype('object')

    # Strings vazias → NaN (evita coluna 'Source_' no encoding)
    df['Source'] = df['Source'].replace('', None)

    # 1. Normalizar para lowercase (produção canônica — garante consistência)
    df['Source'] = df['Source'].str.lower()

    source_antes = df['Source'].nunique()

    # 2. Mapear sources para canal específico antes de agrupar em outros
    #    Ex: youtube-bio → youtube (mesmo canal, variante orgânica)
    channel_mapping = config.source_to_channel_mapping or {}
    for source_val, channel in channel_mapping.items():
        mask = df['Source'] == source_val.lower()
        if mask.any():
            logger.debug(f"  Source '{source_val}' → '{channel}' ({mask.sum()} leads)")
            df.loc[mask, 'Source'] = channel

    # 3. Agrupar sources raras em 'outros'
    outras_sources = [s.lower() for s in (config.source_to_outros or [])]
    conversoes = []
    for source_val in outras_sources:
        mask = df['Source'] == source_val
        if mask.any():
            conversoes.append(f"'{source_val}' ({mask.sum()})")
            df.loc[mask, 'Source'] = 'outros'

    source_depois = df['Source'].nunique()
    logger.info(f"  Source: {source_antes} → {source_depois} valores únicos")
    if conversoes:
        logger.debug(f"  Agrupadas em 'outros': {', '.join(conversoes)}")

    return df


def _unify_term(df: pd.DataFrame, config: UTMConfig) -> pd.DataFrame:
    df['Term'] = df['Term'].astype('object')

    term_antes = df['Term'].nunique()

    # 1. Mapeamentos diretos (ex: ig → instagram, fb → facebook)
    direct_mappings = config.term_mappings or {}
    for origem, destino in direct_mappings.items():
        mask = df['Term'] == origem
        if mask.any():
            logger.debug(f"  Term '{origem}' → '{destino}' ({mask.sum()} leads)")
            df.loc[mask, 'Term'] = destino

    # 2. Padrões que viram 'outros' (ex: '--', '{')
    for pattern in (config.term_outros_patterns or []):
        mask = df['Term'].str.contains(pattern, na=False)
        if mask.any():
            logger.debug(f"  Term com '{pattern}' → 'outros' ({mask.sum()} leads)")
            df.loc[mask, 'Term'] = 'outros'

    # 3. Valores restantes não reconhecidos → 'outros' (whitelist canônica)
    valores_conhecidos = set(direct_mappings.values()) | {'outros'}
    df.loc[df['Term'].notna() & ~df['Term'].isin(valores_conhecidos), 'Term'] = 'outros'

    term_depois = df['Term'].nunique()
    logger.info(f"  Term:   {term_antes} → {term_depois} valores únicos")

    return df
