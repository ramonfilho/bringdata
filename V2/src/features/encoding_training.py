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
            - 'binary_top3': Features binárias para 3 categorias mais estáveis (Linguagem programação, Aberto, Lookalike 2%) - PADRÃO RECOMENDADO
            - 'full': One-hot completo (mantém temporal leakage)
            - 'binary_aberto': Apenas feature binária Medium_Aberto
            - 'binary_aberto_dgen': Features binárias Medium_Aberto + Medium_dgen
            - 'remove': Medium já foi removido na célula 8

    Returns:
        DataFrame com encoding aplicado
    """
    print("ENCODING ESTRATÉGICO")
    print("=" * 20)
    print(f"Estratégia Medium: {medium_strategy}")

    df = df_devclub_fe.copy()

    print(f"\nProcessando DATASET V1 DEVCLUB...")
    print(f"Colunas antes do encoding: {len(df.columns)}")

    # Lista de colunas antes do encoding
    print(f"\nColunas ANTES do encoding:")
    for i, col in enumerate(df.columns, 1):
        print(f"  {i:2d}. {col}")

    # 1. ENCODING ORDINAL para variáveis com ordem natural
    variaveis_ordinais = {
        'Qual a sua idade?': ['Menos de 18 anos', '18 - 24 anos', '25 - 34 anos',
                              '35 - 44 anos', '45 - 54 anos', 'Mais de 55 anos'],
        'Atualmente, qual a sua faixa salarial?': ['Não tenho renda', 'Entre R$1.000 a R$2.000 reais ao mês',
                                                   'Entre R$2.001 a R$3.000 reais ao mês',
                                                   'Entre R$3.001 a R$5.000 reais ao mês',
                                                   'Mais de R$5.001 reais ao mês'],
        'dia_semana': [0, 1, 2, 3, 4, 5, 6]  # Já é numérico
    }

    print(f"\nAplicando ORDINAL ENCODING:")
    for var, ordem in variaveis_ordinais.items():
        if var in df.columns:
            if var == 'dia_semana':
                # Já é numérico, apenas reportar
                print(f"  {var}: mantido como numérico (0-6)")
            else:
                # Criar mapeamento ordinal
                mapeamento = {categoria: i for i, categoria in enumerate(ordem)}
                df[var] = df[var].map(mapeamento)
                print(f"  {var}: {len(ordem)} categorias → 0-{len(ordem)-1}")

    # 1.5. PROCESSAR MEDIUM CONFORME ESTRATÉGIA
    if 'Medium' in df.columns and medium_strategy != 'full':
        print(f"\nProcessando Medium com estratégia: {medium_strategy}")

        if medium_strategy == 'binary_aberto':
            # Criar apenas Medium_Aberto (1 se Aberto, 0 caso contrário)
            df['Medium_Aberto'] = (df['Medium'] == 'Aberto').astype(int)
            df = df.drop(columns=['Medium'])
            print(f"  ✓ Criada feature binária: Medium_Aberto")
            print(f"    Aberto: {df['Medium_Aberto'].sum():,} registros ({df['Medium_Aberto'].mean()*100:.1f}%)")

        elif medium_strategy == 'binary_aberto_dgen':
            # Criar Medium_Aberto e Medium_dgen
            df['Medium_Aberto'] = (df['Medium'] == 'Aberto').astype(int)
            df['Medium_dgen'] = (df['Medium'] == 'dgen').astype(int)
            df = df.drop(columns=['Medium'])
            print(f"  ✓ Criadas features binárias: Medium_Aberto, Medium_dgen")
            print(f"    Aberto: {df['Medium_Aberto'].sum():,} registros ({df['Medium_Aberto'].mean()*100:.1f}%)")
            print(f"    dgen: {df['Medium_dgen'].sum():,} registros ({df['Medium_dgen'].mean()*100:.1f}%)")

        elif medium_strategy == 'binary_top3':
            # Criar features para as 3 categorias mais estáveis temporalmente
            df['Medium_Linguagem_programacao'] = (df['Medium'] == 'Linguagem de programação').astype(int)
            df['Medium_Aberto'] = (df['Medium'] == 'Aberto').astype(int)
            df['Medium_Lookalike_2pct_Cadastrados'] = (df['Medium'] == 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses').astype(int)
            df = df.drop(columns=['Medium'])
            print(f"  ✓ Criadas features binárias (top 3 mais estáveis):")
            print(f"    Linguagem de programação: {df['Medium_Linguagem_programacao'].sum():,} registros ({df['Medium_Linguagem_programacao'].mean()*100:.1f}%)")
            print(f"    Aberto: {df['Medium_Aberto'].sum():,} registros ({df['Medium_Aberto'].mean()*100:.1f}%)")
            print(f"    Lookalike 2% Cadastrados: {df['Medium_Lookalike_2pct_Cadastrados'].sum():,} registros ({df['Medium_Lookalike_2pct_Cadastrados'].mean()*100:.1f}%)")

        elif medium_strategy == 'remove':
            # Medium já foi removido na célula 8, nada a fazer
            if 'Medium' in df.columns:
                print(f"  ⚠️  Medium ainda presente (deveria ter sido removido na célula 8)")
            else:
                print(f"  ✓ Medium removido (célula 8)")

    # 2. ONE-HOT ENCODING para variáveis categóricas nominais
    variaveis_one_hot = []

    # Identificar variáveis categóricas (excluindo ordinais já processadas e target)
    for col in df.columns:
        if col not in ['target'] and col not in variaveis_ordinais and col != 'nome_comprimento':
            # Verificar se é categórica (object ou poucos valores únicos)
            if df[col].dtype == 'object' or df[col].nunique() <= 20:
                variaveis_one_hot.append(col)

    print(f"\nAplicando ONE-HOT ENCODING para {len(variaveis_one_hot)} variáveis:")

    # Aplicar one-hot encoding
    df_encoded = pd.get_dummies(df, columns=variaveis_one_hot, prefix_sep='_', dtype=int)

    # REMOVER telefone_comprimento_8
    if 'telefone_comprimento_8' in df_encoded.columns:
        df_encoded = df_encoded.drop(columns=['telefone_comprimento_8'])

    # Lista de colunas depois do encoding
    print(f"\nColunas DEPOIS do encoding:")
    for i, col in enumerate(df_encoded.columns, 1):
        print(f"  {i:2d}. {col}")

    # Reportar criação de colunas
    colunas_criadas = len(df_encoded.columns) - len(df.columns)
    for var in variaveis_one_hot:
        categorias_unicas = df[var].nunique()
        print(f"  {var}: {categorias_unicas} categorias → {categorias_unicas} colunas binárias")

    print(f"\nResultado:")
    print(f"  Colunas one-hot originais: {len(variaveis_one_hot)}")
    print(f"  Colunas binárias criadas: {colunas_criadas}")
    print(f"  Total de colunas final: {len(df_encoded.columns)}")

    # Verificar tipos de dados finais
    tipos_dados = df_encoded.dtypes.value_counts()
    print(f"\nTipos de dados no dataset final:")
    for tipo, count in tipos_dados.items():
        print(f"  {tipo}: {count} colunas")

    # Resumo final
    print(f"\n" + "=" * 60)
    print("DATASET FINAL ENCODADO")
    print("=" * 60)

    print(f"\nDATASET V1 DEVCLUB:")
    print(f"  Registros: {len(df_encoded):,}")
    print(f"  Colunas: {len(df_encoded.columns)}")
    print(f"  Target positivo: {df_encoded['target'].sum():,} ({df_encoded['target'].mean()*100:.2f}%)")

    # Verificar presença da feature telefone_comprimento_8
    print(f"\nVERIFICAÇÃO DA FEATURE telefone_comprimento_8:")
    status = "PRESENTE" if 'telefone_comprimento_8' in df_encoded.columns else "AUSENTE"
    print(f"  DATASET V1 DEVCLUB: {status}")

    print(f"\nDataset encodado está pronto para modelagem!")

    logger.info(f"✅ Encoding estratégico completo")

    return df_encoded
