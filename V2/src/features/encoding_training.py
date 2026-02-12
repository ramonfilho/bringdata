"""
Módulo para encoding estratégico - PIPELINE DE TREINO.

Reproduz a célula 20 do notebook DevClub.
Aplica encoding ordinal e one-hot.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def aplicar_encoding_estrategico(df_devclub_fe: pd.DataFrame, medium_strategy: str = 'binary_top3') -> pd.DataFrame:
    """
    Aplica encoding seguindo a estratégia recomendada.

    Reproduz a lógica da célula 20 do notebook DevClub.

    Args:
        df_devclub_fe: DataFrame V1 DevClub com feature engineering
        medium_strategy: Estratégia para Medium
            - 'binary_top3': Features binárias para 3 categorias mais estáveis (Linguagem programação, Aberto, Lookalike 2%) - PADRÃO

    Returns:
        DataFrame com encoding aplicado
    """
    logger.debug("ENCODING ESTRATÉGICO")
    logger.debug(f"Estratégia Medium: {medium_strategy}")

    df = df_devclub_fe.copy()

    logger.debug(f"\nProcessando DATASET V1 DEVCLUB...")

    # NORMAL: Colunas antes do encoding (número)
    logger.info(f"Colunas antes do encoding: {len(df.columns)}")

    # DEBUG: Lista de colunas antes do encoding
    logger.debug(f"\nColunas ANTES do encoding:")
    for i, col in enumerate(df.columns, 1):
        logger.debug(f"  {i:2d}. {col}")

    # 1. ENCODING ORDINAL para variáveis com ordem natural
    # IMPORTANTE: Usar valores NORMALIZADOS (após unificar_categorias_completo)
    # Estes valores devem dar match com o que está em categorias_esperadas.json
    variaveis_ordinais = {
        'Qual a sua idade?': ['menos de 18 anos', '18 24 anos', '25 34 anos',
                              '35 44 anos', '45 54 anos', 'mais de 55 anos'],
        'Atualmente, qual a sua faixa salarial?': ['nao tenho renda', 'entre r1000 a r2000 reais ao mes',
                                                   'entre r2001 a r3000 reais ao mes',
                                                   'entre r3001 a r5000 reais ao mes',
                                                   'mais de r5001 reais ao mes'],
        'dia_semana': [0, 1, 2, 3, 4, 5, 6]  # Já é numérico
    }

    # DEBUG: Aplicando ORDINAL ENCODING
    logger.debug(f"\nAplicando ORDINAL ENCODING:")
    for var, ordem in variaveis_ordinais.items():
        if var in df.columns:
            if var == 'dia_semana':
                # Já é numérico, apenas reportar
                logger.debug(f"  {var}: mantido como numérico (0-6)")
            else:
                # Criar mapeamento ordinal
                mapeamento = {categoria: i for i, categoria in enumerate(ordem)}
                df[var] = df[var].map(mapeamento)
                logger.debug(f"  {var}: {len(ordem)} categorias → 0-{len(ordem)-1}")

    # 1.5. DEBUG: PROCESSAR MEDIUM COM BINARY_TOP3
    if 'Medium' in df.columns:
        logger.debug(f"\nProcessando Medium com estratégia: {medium_strategy}")

        # Criar features binárias para as 3 categorias mais estáveis temporalmente
        df['Medium_Linguagem_programacao'] = (df['Medium'] == 'Linguagem de programação').astype(int)
        df['Medium_Aberto'] = (df['Medium'] == 'Aberto').astype(int)
        df['Medium_Lookalike_2pct_Cadastrados'] = (df['Medium'] == 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses').astype(int)
        df = df.drop(columns=['Medium'])

        logger.debug(f"  ✓ Criadas 3 features binárias:")
        logger.debug(f"    Medium_Linguagem_programacao: {df['Medium_Linguagem_programacao'].sum():,} ({df['Medium_Linguagem_programacao'].mean()*100:.1f}%)")
        logger.debug(f"    Medium_Aberto: {df['Medium_Aberto'].sum():,} ({df['Medium_Aberto'].mean()*100:.1f}%)")
        logger.debug(f"    Medium_Lookalike_2pct_Cadastrados: {df['Medium_Lookalike_2pct_Cadastrados'].sum():,} ({df['Medium_Lookalike_2pct_Cadastrados'].mean()*100:.1f}%)")
        logger.debug(f"  ✓ Categorias não cobertas (outros) → [0, 0, 0]")

    # 2. ONE-HOT ENCODING para variáveis categóricas nominais
    variaveis_one_hot = []

    # Identificar variáveis categóricas (excluindo ordinais já processadas e target)
    for col in df.columns:
        if col not in ['target'] and col not in variaveis_ordinais and col != 'nome_comprimento':
            # Excluir features Medium_ já criadas (são binárias, não precisam de one-hot)
            if col.startswith('Medium_'):
                continue
            # Verificar se é categórica (object ou poucos valores únicos)
            if df[col].dtype == 'object' or df[col].nunique() <= 20:
                variaveis_one_hot.append(col)

    # DEBUG: Aplicando ONE-HOT ENCODING
    logger.debug(f"\nAplicando ONE-HOT ENCODING para {len(variaveis_one_hot)} variáveis:")

    # Aplicar one-hot encoding
    df_encoded = pd.get_dummies(df, columns=variaveis_one_hot, prefix_sep='_', dtype=int)

    # REMOVER telefone_comprimento_8
    if 'telefone_comprimento_8' in df_encoded.columns:
        df_encoded = df_encoded.drop(columns=['telefone_comprimento_8'])

    # DEBUG: Lista de colunas depois do encoding
    logger.debug(f"\nColunas DEPOIS do encoding:")
    for i, col in enumerate(df_encoded.columns, 1):
        logger.debug(f"  {i:2d}. {col}")

    # DEBUG: Reportar criação de colunas
    colunas_criadas = len(df_encoded.columns) - len(df.columns)
    for var in variaveis_one_hot:
        categorias_unicas = df[var].nunique()
        logger.debug(f"  {var}: {categorias_unicas} categorias → {categorias_unicas} colunas binárias")

    logger.debug(f"\nResultado:")
    logger.debug(f"  Colunas one-hot originais: {len(variaveis_one_hot)}")
    logger.debug(f"  Colunas binárias criadas: {colunas_criadas}")
    logger.debug(f"  Total de colunas final: {len(df_encoded.columns)}")

    # NORMAL: Verificar tipos de dados finais
    tipos_dados = df_encoded.dtypes.value_counts()
    logger.info("")
    logger.info(f"Tipos de dados no dataset final:")
    for tipo, count in tipos_dados.items():
        logger.info(f"  {tipo}: {count} colunas")

    # NORMAL: Resumo final
    logger.info("")
    logger.info(f"Dataset final encodado:")
    logger.info(f"  Registros: {len(df_encoded):,}")
    logger.info(f"  Colunas: {len(df_encoded.columns)}")
    logger.info(f"  Target positivo: {df_encoded['target'].sum():,} ({df_encoded['target'].mean()*100:.2f}%)")

    # DEBUG: Verificar presença da feature telefone_comprimento_8
    logger.debug(f"\nVERIFICAÇÃO DA FEATURE telefone_comprimento_8:")
    status = "PRESENTE" if 'telefone_comprimento_8' in df_encoded.columns else "AUSENTE"
    logger.debug(f"  DATASET V1 DEVCLUB: {status}")

    logger.debug(f"\nDataset encodado está pronto para modelagem!")

    logger.info(f"✅ Encoding estratégico completo")

    return df_encoded
