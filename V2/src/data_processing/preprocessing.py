"""
Módulo de pré-processamento de dados para o pipeline de lead scoring.
Mantém a lógica EXATA do notebook original para garantir reprodutibilidade.
"""

import pandas as pd
from typing import Dict, Tuple, List
import logging

logger = logging.getLogger(__name__)


def remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove linhas duplicadas mantendo a primeira ocorrência.

    Mantém comportamento IDÊNTICO ao notebook original:
    - df.drop_duplicates(keep='first')

    Args:
        df: DataFrame com possíveis duplicatas

    Returns:
        DataFrame sem duplicatas
    """
    return df.drop_duplicates(keep='first')


def get_columns_to_remove() -> List[str]:
    """
    Lista de colunas para remover em produção.

    Como em produção trabalharemos apenas com arquivos no formato LF24,
    removemos:
    - Colunas de scoring/faixas (geradas pelo modelo, não features)
    - Colunas técnicas que estão sempre vazias no arquivo de produção

    Returns:
        Lista com nomes das colunas a remover
    """
    return [
        # Colunas de score/faixa (resultado do modelo, não features)
        'Pontuação',
        'Score',
        'Faixa',
        'Faixa A',
        'Faixa B',
        'Faixa C',
        'Faixa D',
        # Colunas técnicas (sempre vazias no arquivo de produção)
        'Remote IP',
        'User Agent',
        'fbc',
        'fbp',
        'cidade',
        'estado',
        'pais',
        'cep',
        'externalid',
        'Page URL',
        'Qual estado você mora?'
    ]


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove colunas desnecessárias do DataFrame.

    Segue lógica adaptada da Seção 3 do notebook original:
    - Remove colunas de scoring/faixas (resultado do modelo, não features)
    - Remove colunas Unnamed (se existirem)

    Args:
        df: DataFrame com colunas a limpar

    Returns:
        DataFrame sem as colunas desnecessárias
    """
    # Print do cabeçalho para comparação com notebook
    logger.info("LIMPEZA DE COLUNAS DESNECESSÁRIAS - ARQUIVOS FILTRADOS")
    logger.info("=" * 60)

    df_clean = df.copy()
    colunas_antes = len(df_clean.columns)

    # Lista de colunas para remover
    columns_to_remove = get_columns_to_remove()
    columns_to_remove_lower = [col.lower() for col in columns_to_remove]

    # Prefixos de colunas de score/faixa que devem ser removidas (incluindo variantes com sufixo)
    score_prefixes = ['score', 'faixa', 'pontuação', 'pontuacao', 'lead_score', 'decil']

    # Identificar colunas presentes no DataFrame para remover
    columns_to_drop = []

    for col in df_clean.columns:
        col_lower = str(col).lower()
        # Remover se está na lista exata (case-insensitive)
        if col_lower in columns_to_remove_lower:
            columns_to_drop.append(col)
        # Remover colunas Unnamed
        elif str(col).startswith('Unnamed:'):
            columns_to_drop.append(col)
        # Remover qualquer coluna que comece com prefixos de score/faixa
        elif any(col_lower.startswith(prefix) for prefix in score_prefixes):
            columns_to_drop.append(col)

    # Aplicar remoção se houver colunas para remover
    if columns_to_drop:
        df_clean = df_clean.drop(columns=columns_to_drop)

    colunas_depois = len(df_clean.columns)
    colunas_removidas = len(columns_to_drop)

    # Print do relatório similar ao notebook
    logger.info(f"{'ARQUIVO':<35} {'ABA':<20} {'ANTES':>8} {'DEPOIS':>8} {'REMOVIDAS':>10}")
    logger.info("-" * 90)
    logger.info(f"{'pipeline_input':<35} {'dados':<20} {colunas_antes:>8} {colunas_depois:>8} {colunas_removidas:>10}")
    logger.info("-" * 90)
    logger.info(f"Total de colunas removidas: {colunas_removidas}")
    if columns_to_drop:
        logger.info(f"Colunas removidas: {columns_to_drop}")
    logger.info(f"\nDados limpos disponíveis na variável 'arquivos_filtrados_limpos'")

    # DEBUG: Listar colunas exatas após limpeza
    logger.info(f"\n🔍 DEBUG - COLUNAS APÓS LIMPEZA PIPELINE V2:")
    logger.info(f"Total de colunas: {len(df_clean.columns)}")
    logger.info("Colunas restantes após limpeza:")
    for i, col in enumerate(sorted(df_clean.columns), 1):
        logger.info(f"  {i:2d}. {col}")

    return df_clean


def get_campaign_features_to_remove() -> List[str]:
    """
    Lista de features relacionadas a campanhas específicas para remover.

    Adaptado da Seção 8 do notebook original:
    - Campaign: lançamento específico, não útil para modelo generalizado
    - Content: anúncios individuais, características específicas do lançamento

    Returns:
        Lista com nomes das features de campanha a remover
    """
    return [
        'Campaign',  # Lançamento específico
        'Content'    # Anúncios individuais
    ]


def remove_campaign_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove features relacionadas a campanhas específicas.

    Segue lógica EXATA da Seção 8 do notebook original:
    - Remove colunas Campaign e Content
    - Remove colunas problemáticas (vazias, None, etc.) se existirem

    Args:
        df: DataFrame com features de campanha

    Returns:
        DataFrame sem features de campanha
    """
    # Print do cabeçalho para comparação com notebook
    logger.info("REMOÇÃO DE FEATURES DESNECESSÁRIAS")
    logger.info("=" * 38)

    df_clean = df.copy()
    logger.info(f"Dataset inicial: {len(df_clean)} registros, {len(df_clean.columns)} colunas")

    # Features de campanha para remover
    campaign_features = get_campaign_features_to_remove()

    # Identificar colunas problemáticas (como no notebook original)
    problematic_columns = []
    for col in df_clean.columns:
        if col == '' or pd.isna(col) or col is None:
            problematic_columns.append(col)
        elif isinstance(col, str) and col.strip() == '':
            problematic_columns.append(col)

    # Combinar todas as colunas para remover
    columns_to_remove = campaign_features + problematic_columns

    logger.info(f"\nFeatures marcadas para remoção:")
    for feature in columns_to_remove:
        if feature == '' or pd.isna(feature) or feature is None:
            logger.info(f"  - Coluna problemática: {repr(feature)}")
        else:
            logger.info(f"  - {feature}")

    # Identificar quais colunas existem no DataFrame
    columns_to_drop = []
    for col in columns_to_remove:
        if col in df_clean.columns:
            columns_to_drop.append(col)

    # Aplicar remoção se houver colunas para remover
    if columns_to_drop:
        logger.info(f"\nColunas encontradas e removidas:")
        for coluna in columns_to_drop:
            if coluna == '' or pd.isna(coluna) or coluna is None:
                logger.info(f"  ✓ Coluna problemática removida: {repr(coluna)}")
            else:
                logger.info(f"  ✓ {coluna} removida")
        df_clean = df_clean.drop(columns=columns_to_drop)

        logger.info(f"\nDataset após remoção: {len(df_clean)} registros, {len(df_clean.columns)} colunas")

    # DEBUG: Listar colunas restantes após Sessão 8 (ordem real)
    logger.info(f"\n🔍 COLUNAS RESTANTES NO DATASET:")
    logger.info("-" * 40)
    for i, col in enumerate(df_clean.columns, 1):
        logger.info(f"{i:2d}. {col}")

    return df_clean


def remove_technical_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove campos técnicos que não são features para o modelo.

    Baseado na lista de colunas removidas no notebook original (linha 145-170).
    Esses campos são metadados técnicos ou informações não relevantes para o modelo.

    Args:
        df: DataFrame com campos técnicos

    Returns:
        DataFrame sem campos técnicos
    """
    df_clean = df.copy()

    # Lista de campos técnicos para remover (baseada no notebook linha 145-170)
    technical_fields = [
        'Page URL',
        'Remote IP',
        'User Agent',
        'cep',
        'cidade',
        'estado',
        'pais',
        'externalid',
        'fbc',
        'fbp',
        'Qual estado você mora?'  # Campo que deveria ser removido segundo o notebook
    ]

    # Identificar quais campos existem no DataFrame
    columns_to_drop = []
    for col in technical_fields:
        if col in df_clean.columns:
            columns_to_drop.append(col)

    # Aplicar remoção se houver colunas para remover
    if columns_to_drop:
        df_clean = df_clean.drop(columns=columns_to_drop)

    return df_clean


def rename_long_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renomeia colunas com nomes longos para versões simplificadas.

    Baseado no notebook original (linhas 355-385) onde as colunas com nomes longos
    são renomeadas para versões mais curtas e as originais são removidas.

    Args:
        df: DataFrame com colunas de nomes longos

    Returns:
        DataFrame com colunas renomeadas
    """
    df_clean = df.copy()

    # Mapeamento de nomes longos para nomes curtos (baseado no notebook)
    rename_mapping = {
        'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?': 'investiu_curso_online',
        'O que mais te chama atenção na profissão de Programador?': 'interesse_programacao'
    }

    # Aplicar renomeação se as colunas existirem
    for old_name, new_name in rename_mapping.items():
        if old_name in df_clean.columns:
            df_clean[new_name] = df_clean[old_name]
            df_clean = df_clean.drop(columns=[old_name])

    return df_clean