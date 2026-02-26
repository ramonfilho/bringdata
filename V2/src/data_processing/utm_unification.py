"""
Módulo de unificação de categorias UTM (Source e Term).
Mantém a lógica EXATA do notebook original para garantir reprodutibilidade.
"""

import pandas as pd
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


def unify_utm_source(df: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica categorias da coluna Source.

    Segue lógica EXATA da Seção 10 do notebook original:
    - Mantém "facebook-ads" e "google-ads" (principais)
    - Converte valores minoritários para "outros"

    Args:
        df: DataFrame com coluna Source

    Returns:
        DataFrame com Source unificado
    """
    df_unified = df.copy()

    if 'Source' not in df_unified.columns:
        return df_unified

    # Garantir tipo object
    df_unified['Source'] = df_unified['Source'].astype('object')

    # Normalizar para lowercase para unificação consistente
    df_unified['Source'] = df_unified['Source'].str.lower()

    # Strings vazias → NaN (evita coluna 'Source_' → 'Source' após encoding)
    df_unified['Source'] = df_unified['Source'].replace('', None)

    # Valores minoritários para unificar em "outros"
    outras_sources = ['fb', 'teste', '[field id="utm_source"]', 'facebook-ads-sitelink', 'youtube', 'youtube-bio', 'bio', 'organico', 'ig', 'manychat', 'org']

    # Aplicar unificação e logar conversões
    conversoes = []
    for source in outras_sources:
        if source in df_unified['Source'].values:
            count = (df_unified['Source'] == source).sum()
            conversoes.append(f"'{source}' ({count} leads)")
            df_unified.loc[df_unified['Source'] == source, 'Source'] = 'outros'

    if conversoes:
        logger.info(f"    Source convertidas para 'outros': {', '.join(conversoes)}")

    return df_unified


def unify_utm_term(df: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica categorias da coluna Term.

    Segue lógica EXATA da Seção 10 do notebook original:
    - 'ig' -> 'instagram'
    - 'fb' -> 'facebook'
    - IDs numéricos (com --) -> 'outros'
    - Parâmetros dinâmicos (com {}) -> 'outros'

    Args:
        df: DataFrame com coluna Term

    Returns:
        DataFrame com Term unificado
    """
    df_unified = df.copy()

    if 'Term' not in df_unified.columns:
        return df_unified

    # Garantir tipo object
    df_unified['Term'] = df_unified['Term'].astype('object')

    conversoes_term = []

    # 1. Instagram: 'ig' -> 'instagram'
    count_ig = (df_unified['Term'] == 'ig').sum()
    if count_ig > 0:
        conversoes_term.append(f"'ig' -> 'instagram' ({count_ig} leads)")
        df_unified.loc[df_unified['Term'] == 'ig', 'Term'] = 'instagram'

    # 2. Facebook: 'fb' -> 'facebook'
    count_fb = (df_unified['Term'] == 'fb').sum()
    if count_fb > 0:
        conversoes_term.append(f"'fb' -> 'facebook' ({count_fb} leads)")
        df_unified.loc[df_unified['Term'] == 'fb', 'Term'] = 'facebook'

    # 3. IDs numéricos (padrão com --) -> 'outros'
    mask_ids_numericos = df_unified['Term'].str.contains('--', na=False)
    count_ids = mask_ids_numericos.sum()
    if count_ids > 0:
        conversoes_term.append(f"IDs numéricos com '--' -> 'outros' ({count_ids} leads)")
        df_unified.loc[mask_ids_numericos, 'Term'] = 'outros'

    # 4. Parâmetros dinâmicos -> 'outros'
    mask_parametros = df_unified['Term'].str.contains('{', na=False)
    count_params = mask_parametros.sum()
    if count_params > 0:
        conversoes_term.append(f"Parâmetros dinâmicos -> 'outros' ({count_params} leads)")
        df_unified.loc[mask_parametros, 'Term'] = 'outros'

    # 5. Outros valores específicos -> 'outros'
    # Pegar valores que não são instagram, facebook, outros ou NaN
    outros_terms = df_unified['Term'].notna() & (~df_unified['Term'].isin(['instagram', 'facebook', 'outros']))
    valores_outros = df_unified.loc[outros_terms, 'Term'].unique()

    valores_convertidos = []
    # Converter valores restantes para 'outros'
    for valor in valores_outros:
        if isinstance(valor, str) and valor not in ['instagram', 'facebook']:
            # IDs longos ou textos especiais viram 'outros'
            if not valor.isdigit() or len(valor) > 10:
                count = (df_unified['Term'] == valor).sum()
                valores_convertidos.append(f"'{valor}' ({count})")
                df_unified.loc[df_unified['Term'] == valor, 'Term'] = 'outros'

    if valores_convertidos:
        conversoes_term.append(f"Outros valores -> 'outros': {', '.join(valores_convertidos[:5])}" +
                              (f" (+ {len(valores_convertidos)-5} mais)" if len(valores_convertidos) > 5 else ""))

    if conversoes_term:
        logger.info(f"    Term convertidas:")
        for conv in conversoes_term:
            logger.info(f"      - {conv}")

    return df_unified


def unify_utm_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica colunas UTM Source e Term.

    Combina as unificações das funções específicas seguindo
    a lógica completa da Seção 10 do notebook original.

    Args:
        df: DataFrame com colunas UTM

    Returns:
        DataFrame com UTMs unificados
    """
    # Print do cabeçalho para comparação com notebook
    logger.info("UNIFICAÇÃO DE UTM SOURCE E TERM")
    logger.info("=" * 35)

    df_unified = df.copy()
    logger.info(f"Dataset inicial: {len(df_unified)} registros")

    # 1. Unificar Source
    logger.info(f"\n1. UNIFICANDO COLUNA SOURCE:")
    logger.info("-" * 35)

    if 'Source' in df_unified.columns:
        source_antes = df_unified['Source'].nunique()
        logger.info(f"Valores únicos antes: {source_antes}")

        # Mostrar distribuição antes
        source_counts = df_unified['Source'].value_counts(dropna=False)
        logger.info("Distribuição antes:")
        for valor, count in source_counts.head(5).items():
            pct = count / len(df_unified) * 100
            valor_str = str(valor) if pd.notna(valor) else 'nan'
            logger.info(f"  {valor_str:<25} {count:>6,} ({pct:>5.1f}%)")

    df_unified = unify_utm_source(df_unified)

    if 'Source' in df_unified.columns:
        source_depois = df_unified['Source'].nunique()
        logger.info(f"\nApós unificação:")
        logger.info(f"Valores únicos depois: {source_depois}")
        source_counts = df_unified['Source'].value_counts(dropna=False)
        for valor, count in source_counts.items():
            pct = count / len(df_unified) * 100
            valor_str = str(valor) if pd.notna(valor) else 'nan'
            logger.info(f"  {valor_str:<25} {count:>6,} ({pct:>5.1f}%)")

    # 2. Unificar Term
    logger.info(f"\n2. UNIFICANDO COLUNA TERM:")
    logger.info("-" * 35)

    if 'Term' in df_unified.columns:
        term_antes = df_unified['Term'].nunique()
        logger.info(f"Valores únicos antes: {term_antes}")

        # Mostrar distribuição antes (top 10)
        term_counts = df_unified['Term'].value_counts(dropna=False)
        logger.info("Distribuição antes (top 10):")
        for valor, count in term_counts.head(10).items():
            pct = count / len(df_unified) * 100
            valor_str = str(valor) if pd.notna(valor) else 'nan'
            logger.info(f"  {valor_str:<35} {count:>6,} ({pct:>5.1f}%)")

    df_unified = unify_utm_term(df_unified)

    if 'Term' in df_unified.columns:
        term_depois = df_unified['Term'].nunique()
        logger.info(f"\nApós unificação:")
        logger.info(f"Valores únicos depois: {term_depois}")
        term_counts = df_unified['Term'].value_counts(dropna=False)
        for valor, count in term_counts.items():
            pct = count / len(df_unified) * 100
            valor_str = str(valor) if pd.notna(valor) else 'nan'
            logger.info(f"  {valor_str:<35} {count:>6,} ({pct:>5.1f}%)")

    return df_unified


def get_utm_summary(df: pd.DataFrame) -> Dict:
    """
    Gera resumo das colunas UTM após unificação.

    Args:
        df: DataFrame com colunas UTM unificadas

    Returns:
        Dicionário com estatísticas das colunas UTM
    """
    summary = {}

    if 'Source' in df.columns:
        summary['source'] = {
            'unique_count': df['Source'].nunique(),
            'value_counts': df['Source'].value_counts(dropna=False).to_dict()
        }

    if 'Term' in df.columns:
        summary['term'] = {
            'unique_count': df['Term'].nunique(),
            'value_counts': df['Term'].value_counts(dropna=False).to_dict()
        }

    return summary