"""
Módulo para remoção de features desnecessárias.

Reproduz a célula 8 do notebook DevClub.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def remover_features_desnecessarias(df_pesquisa: pd.DataFrame, remover_medium: bool = False) -> pd.DataFrame:
    """
    Remove features que não serão utilizadas no modelo.

    Reproduz a lógica da célula 8 do notebook DevClub.

    Args:
        df_pesquisa: DataFrame de pesquisa
        remover_medium: Se True, remove Medium junto com Campaign e Content

    Returns:
        DataFrame sem features desnecessárias
    """
    df = df_pesquisa.copy()

    print(f"Dataset inicial: {len(df)} registros, {len(df.columns)} colunas")
    if remover_medium:
        print(f"⚠️  Modo: Remover Medium (junto com Campaign e Content)")

    # DEBUG: Identificar colunas vazias ou com nomes problemáticos
    print(f"\nDEBUG - Análise de nomes de colunas:")
    print("-" * 50)

    colunas_problematicas = []
    for i, coluna in enumerate(df.columns):
        coluna_repr = repr(coluna)  # Mostra representação exata
        comprimento = len(str(coluna)) if coluna is not None else 0

        # Identificar possíveis problemas
        problemas = []
        if coluna == '':
            problemas.append('VAZIA')
        if coluna is None:
            problemas.append('NONE')
        if pd.isna(coluna):
            problemas.append('NAN')
        if isinstance(coluna, str) and coluna.strip() == '':
            problemas.append('APENAS_ESPACOS')
        if comprimento == 0:
            problemas.append('COMPRIMENTO_ZERO')

        if problemas:
            print(f"  {i+1:2d}. {coluna_repr:<30} - PROBLEMA: {', '.join(problemas)}")
            colunas_problematicas.append(coluna)
        elif comprimento < 3 or not isinstance(coluna, str):
            print(f"  {i+1:2d}. {coluna_repr:<30} - SUSPEITA (len={comprimento})")

    if not colunas_problematicas:
        print("  Nenhuma coluna problemática encontrada através de análise automática")

        # Verificar manualmente se alguma coluna parece vazia
        print("\n  Verificando colunas que podem parecer vazias:")
        for i, coluna in enumerate(df.columns):
            if len(str(coluna).strip()) <= 2:  # Muito curta
                print(f"    {i+1:2d}. '{coluna}' (comprimento: {len(str(coluna))})")
                colunas_problematicas.append(coluna)

    # Features a serem removidas (incluindo as encontradas no debug)
    features_remover = [
        'Campaign',  # Lançamento específico (data leakage temporal)
        'Content',   # Anúncios individuais
    ]

    # Adicionar Medium se solicitado (opção 3: remover completamente)
    if remover_medium:
        features_remover.append('Medium')  # Públicos-alvo (data leakage temporal)

    # Adicionar colunas problemáticas encontradas
    features_remover.extend(colunas_problematicas)

    print(f"\nFeatures marcadas para remoção:")
    for feature in features_remover:
        if feature == '' or pd.isna(feature) or feature is None:
            print(f"  - Coluna problemática: {repr(feature)}")
        else:
            print(f"  - {feature}")

    # Verificar quais colunas existem no dataset
    colunas_existentes = []
    colunas_nao_encontradas = []

    for feature in features_remover:
        if feature in df.columns:
            colunas_existentes.append(feature)
        else:
            colunas_nao_encontradas.append(feature)

    # Remover colunas existentes
    if len(colunas_existentes) > 0:
        print(f"\nColunas encontradas e removidas:")
        for coluna in colunas_existentes:
            if coluna == '' or pd.isna(coluna) or coluna is None:
                print(f"  ✓ Coluna problemática removida: {repr(coluna)}")
            else:
                print(f"  ✓ {coluna} removida")

        df = df.drop(columns=colunas_existentes)

    # Reportar colunas não encontradas
    if len(colunas_nao_encontradas) > 0:
        print(f"\nColunas não encontradas no dataset:")
        for coluna in colunas_nao_encontradas:
            if coluna == '' or pd.isna(coluna) or coluna is None:
                print(f"  ! Coluna problemática não encontrada: {repr(coluna)}")
            else:
                print(f"  ! {coluna} não encontrada")

    print(f"\nDataset final: {len(df)} registros, {len(df.columns)} colunas")
    print(f"Colunas removidas: {len(colunas_existentes)}")

    logger.info(f"✅ Features desnecessárias removidas: {len(colunas_existentes)}")

    return df


def listar_colunas_restantes(df: pd.DataFrame):
    """
    Lista as colunas que restaram no dataset.

    Args:
        df: DataFrame processado
    """
    print(f"\nCOLUNAS RESTANTES NO DATASET:")
    print("-" * 40)

    for i, coluna in enumerate(df.columns, 1):
        print(f"{i:2d}. {coluna}")

    print(f"\nTotal de colunas: {len(df.columns)}")
