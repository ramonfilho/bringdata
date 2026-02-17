"""
Módulo para criação de versão do dataset por missing rate - PIPELINE DE TREINO.

Reproduz a célula 13 do notebook DevClub.
Cria dataset pós-cutoff (2025-03-01) com menor missing rate.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def criar_dataset_pos_cutoff(df_medium_producao: pd.DataFrame) -> pd.DataFrame:
    """
    Cria dataset pós-cutoff (2025-03-01) com menor missing rate.

    Reproduz a lógica da célula 13 do notebook DevClub.

    Args:
        df_medium_producao: DataFrame com Medium unificado para produção

    Returns:
        DataFrame pós-cutoff com features críticas mantidas
    """
    df = df_medium_producao.copy()

    # Converter coluna de data para datetime se não estiver
    if 'Data' in df.columns:
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True)

    # Definir cutoff de data (quando as features críticas começaram a ser preenchidas)
    cutoff_date = pd.to_datetime('2025-03-01')

    # NORMAL: Data de cutoff
    logger.info(f"  Data de cutoff: {cutoff_date.strftime('%Y-%m-%d')}")

    # Calcular missing rate médio do dataset completo (pré-cutoff)
    missing_stats_pre = {}
    for col in df.columns:
        if col != 'Data':
            missing_count = df[col].isnull().sum()
            missing_rate = (missing_count / len(df)) * 100
            missing_stats_pre[col] = missing_rate

    avg_missing_pre = sum(missing_stats_pre.values()) / len(missing_stats_pre) if missing_stats_pre else 0

    # NORMAL: Resumo pré-cutoff
    logger.info(f"  Dataset pesquisa pré-cutoff: {len(df):,} registros, {len(df.columns)} colunas, missing rate {avg_missing_pre:.1f}%")

    # Dataset pós-cutoff (período com menor missing das features críticas)
    df_pos_cutoff = df[df['Data'] >= cutoff_date].copy()

    # Remover manualmente a coluna "nivel_programacao"
    coluna_remover = 'nivel_programacao'
    if coluna_remover in df_pos_cutoff.columns:
        df_pos_cutoff = df_pos_cutoff.drop(columns=[coluna_remover])
        logger.debug(f"Coluna removida: '{coluna_remover}'")

    logger.debug(f"Registros pós {cutoff_date.strftime('%Y-%m-%d')}: {len(df_pos_cutoff)}")

    # Definir features com missing crítico para análise
    features_missing_critico = [
        'estudou_programacao',
        'fez_faculdade',
        'tem_computador',
        'nivel_programacao',
    ]

    # Verificar quais features existem no dataset
    features_existentes = [col for col in features_missing_critico if col in df.columns]
    features_nao_existentes = [col for col in features_missing_critico if col not in df.columns]

    # DEBUG: Features de missing crítico
    logger.debug("")
    logger.debug(f"Features de missing crítico encontradas: {len(features_existentes)}")
    for feature in features_existentes:
        logger.debug(f"   {feature}")

    if features_nao_existentes:
        logger.debug("")
        logger.debug(f"Features de missing crítico NÃO encontradas: {len(features_nao_existentes)}")
        for feature in features_nao_existentes:
            logger.debug(f"   {feature}")

    logger.debug("")
    logger.debug("VERSÃO 1: MENOR MISSING RATE (pós 2025-03-01)")
    logger.debug(f"Registros: {len(df_pos_cutoff):,}")
    logger.debug(f"Features críticas MANTIDAS (período com menor missing)")

    # Análise de missing rate
    missing_stats = {}
    for col in df_pos_cutoff.columns:
        if col != 'Data':
            missing_count = df_pos_cutoff[col].isnull().sum()
            missing_rate = (missing_count / len(df_pos_cutoff)) * 100
            missing_stats[col] = {
                'missing_count': missing_count,
                'missing_rate': missing_rate,
                'valid_count': len(df_pos_cutoff) - missing_count
            }

    # Ordenar por taxa de missing
    missing_sorted = sorted(missing_stats.items(), key=lambda x: x[1]['missing_rate'])

    # DEBUG: Tabela completa de missing rate por coluna
    logger.debug("")
    logger.debug("Taxa de missing por coluna (ordenado):")
    logger.debug(f"{'COLUNA':<45} {'VÁLIDOS':<8} {'MISSING':<8} {'% MISS':<7}")
    logger.debug("-" * 70)

    for col, stats in missing_sorted:
        logger.debug(f"{col[:42]:<45} {stats['valid_count']:<8,} {stats['missing_count']:<8,} {stats['missing_rate']:<7.1f}%")

    # Missing rate médio
    avg_missing = sum(stats['missing_rate'] for stats in missing_stats.values()) / len(missing_stats) if missing_stats else 0

    # NORMAL: Resumo final apenas
    logger.info(f"  Dataset pesquisa pós-cutoff: {len(df_pos_cutoff):,} registros, {len(df_pos_cutoff.columns)} colunas, missing rate {avg_missing:.1f}%")
    logger.info("")

    # DEBUG: Análise específica das features críticas
    features_criticas_presentes = [f for f in features_existentes if f in df_pos_cutoff.columns]
    if features_criticas_presentes:
        logger.debug("")
        logger.debug("Análise das features críticas:")
        for feature in features_criticas_presentes:
            missing_count = df_pos_cutoff[feature].isnull().sum()
            missing_rate = (missing_count / len(df_pos_cutoff)) * 100
            logger.debug(f"  {feature}: {missing_rate:.1f}% missing")

    return df_pos_cutoff


def disponibilizar_dataset(df_pos_cutoff: pd.DataFrame):
    """
    Gera relatório final de disponibilização do dataset.

    Args:
        df_pos_cutoff: DataFrame pós-cutoff
    """
    # DEBUG: Disponibilização é detalhe técnico
    logger.debug("")
    logger.debug("DISPONIBILIZAÇÃO DO DATASET")

    logger.debug(f"Dataset disponível em: pesquisa_v1_menor_missing")
    logger.debug(f"  Período: 2025-02-11 em diante")
    logger.debug(f"  Todas as features mantidas")
    logger.debug(f"  Registros: {len(df_pos_cutoff):,}")
    logger.debug(f"  Colunas: {len(df_pos_cutoff.columns)}")
