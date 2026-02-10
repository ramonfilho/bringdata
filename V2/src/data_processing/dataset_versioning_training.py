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

    print(f"Dataset original: {len(df)} registros, {len(df.columns)} colunas")

    # Converter coluna de data para datetime se não estiver
    if 'Data' in df.columns:
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True)

    # Definir cutoff de data (quando as features críticas começaram a ser preenchidas)
    cutoff_date = pd.to_datetime('2025-03-01')

    # Dataset pós-cutoff (período com menor missing das features críticas)
    df_pos_cutoff = df[df['Data'] >= cutoff_date].copy()

    # Remover manualmente a coluna "Qual o seu nível em programação?"
    coluna_remover = 'Qual o seu nível em programação?'
    if coluna_remover in df_pos_cutoff.columns:
        df_pos_cutoff = df_pos_cutoff.drop(columns=[coluna_remover])
        print(f"Coluna removida: '{coluna_remover}'")

    print(f"Registros pós {cutoff_date.strftime('%Y-%m-%d')}: {len(df_pos_cutoff)}")

    # Definir features com missing crítico para análise
    features_missing_critico = [
        'Já estudou programação?',
        'Você já fez/faz/pretende fazer',
        'Você já fez/faz/pretende fazer faculdade?',
        'Tem computador/notebook?',
        'Qual o seu nível em programação?'
    ]

    # Verificar quais features existem no dataset
    features_existentes = [col for col in features_missing_critico if col in df.columns]
    features_nao_existentes = [col for col in features_missing_critico if col not in df.columns]

    print(f"\nFeatures de missing crítico encontradas: {len(features_existentes)}")
    for feature in features_existentes:
        print(f"  ✓ {feature}")

    if features_nao_existentes:
        print(f"\nFeatures de missing crítico NÃO encontradas: {len(features_nao_existentes)}")
        for feature in features_nao_existentes:
            print(f"  ✗ {feature}")

    print("VERSÃO 1: MENOR MISSING RATE (pós 2025-03-01)")
    print(f"Registros: {len(df_pos_cutoff):,}")
    print(f"Features críticas MANTIDAS (período com menor missing)")

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

    print(f"\nTaxa de missing por coluna (ordenado):")
    print(f"{'COLUNA':<45} {'VÁLIDOS':<8} {'MISSING':<8} {'% MISS':<7}")
    print("-" * 70)

    for col, stats in missing_sorted:
        print(f"{col[:42]:<45} {stats['valid_count']:<8,} {stats['missing_count']:<8,} {stats['missing_rate']:<7.1f}%")

    # Missing rate médio
    avg_missing = sum(stats['missing_rate'] for stats in missing_stats.values()) / len(missing_stats) if missing_stats else 0

    print(f"\nResumo do dataset pós-cutoff:")
    print(f"  Registros: {len(df_pos_cutoff):,}")
    print(f"  Colunas: {len(df_pos_cutoff.columns)}")
    print(f"  Missing rate médio: {avg_missing:.1f}%")

    # Análise específica das features críticas
    features_criticas_presentes = [f for f in features_existentes if f in df_pos_cutoff.columns]
    if features_criticas_presentes:
        print(f"\nAnálise das features críticas:")
        for feature in features_criticas_presentes:
            missing_count = df_pos_cutoff[feature].isnull().sum()
            missing_rate = (missing_count / len(df_pos_cutoff)) * 100
            print(f"  {feature}: {missing_rate:.1f}% missing")

    return df_pos_cutoff


def disponibilizar_dataset(df_pos_cutoff: pd.DataFrame):
    """
    Gera relatório final de disponibilização do dataset.

    Args:
        df_pos_cutoff: DataFrame pós-cutoff
    """
    print("DISPONIBILIZAÇÃO DO DATASET")

    print(f"Dataset disponível em: pesquisa_v1_menor_missing")
    print(f"  Período: 2025-02-11 em diante")
    print(f"  Todas as features mantidas")
    print(f"  Registros: {len(df_pos_cutoff):,}")
    print(f"  Colunas: {len(df_pos_cutoff.columns)}")
