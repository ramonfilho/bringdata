"""
Módulo para unificação completa de categorias.

Reproduz a célula 7 do notebook DevClub.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def limpar_texto(texto):
    """
    Limpa caracteres invisíveis e normaliza texto.

    Args:
        texto: String a ser limpa

    Returns:
        String limpa ou valor original se NaN
    """
    if pd.isna(texto):
        return texto

    # Converter para string e limpar caracteres invisíveis
    texto_limpo = str(texto)
    texto_limpo = texto_limpo.replace('\u2060', '')  # Word joiner
    texto_limpo = texto_limpo.replace('\xa0', ' ')   # Non-breaking space
    texto_limpo = texto_limpo.replace('\u200b', '')  # Zero width space
    texto_limpo = texto_limpo.strip()

    return texto_limpo


def unificar_categorias_completo(df_pesquisa: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica categorias com limpeza e mappings robustos.

    Reproduz a lógica da célula 7 do notebook DevClub.

    Args:
        df_pesquisa: DataFrame de pesquisa

    Returns:
        DataFrame com categorias unificadas
    """
    df = df_pesquisa.copy()

    print("Aplicando limpeza e unificação completa...")

    # 1. INTERESSE PROGRAMAÇÃO
    print("\n1. Unificando interesse_programacao...")
    if 'interesse_programacao' in df.columns:
        # Limpar textos primeiro
        df['interesse_programacao'] = df['interesse_programacao'].apply(limpar_texto)

        # Mapping após limpeza
        df.loc[df['interesse_programacao'] == 'Todas as alternativas.', 'interesse_programacao'] = 'Todas as alternativas'
        df.loc[df['interesse_programacao'] == 'Poder trabalhar de qualquer lugar do mundo.', 'interesse_programacao'] = 'Poder trabalhar de qualquer lugar do mundo'
        df.loc[df['interesse_programacao'] == 'A possibilidade de ganhar altos salários.', 'interesse_programacao'] = 'A possibilidade de ganhar altos salários'
        df.loc[df['interesse_programacao'] == 'Trabalhar para outros países e ganhar em outra moeda.', 'interesse_programacao'] = 'Trabalhar para outros países e ganhar em outra moeda'
        df.loc[df['interesse_programacao'] == 'A ideia de nunca faltar emprego na área.', 'interesse_programacao'] = 'A ideia de nunca faltar emprego na área'

        valores_unicos = df['interesse_programacao'].nunique()
        print(f"   Resultado: {valores_unicos} valores únicos")

    # 2. TEM COMPUTADOR/NOTEBOOK
    print("\n2. Unificando Tem computador/notebook?...")
    if 'Tem computador/notebook?' in df.columns:
        df['Tem computador/notebook?'] = df['Tem computador/notebook?'].apply(limpar_texto)

        df.loc[df['Tem computador/notebook?'] == 'SIM', 'Tem computador/notebook?'] = 'Sim'
        df.loc[df['Tem computador/notebook?'] == 'não', 'Tem computador/notebook?'] = 'Não'

        valores_unicos = df['Tem computador/notebook?'].nunique()
        print(f"   Resultado: {valores_unicos} valores únicos")

    # 3. O QUE MAIS VOCÊ QUER VER NO EVENTO
    print("\n3. Unificando O que mais você quer ver no evento?...")
    if 'O que mais você quer ver no evento?' in df.columns:
        df['O que mais você quer ver no evento?'] = df['O que mais você quer ver no evento?'].apply(limpar_texto)

        # Unificar "conseguir" vs "consegui"
        df.loc[df['O que mais você quer ver no evento?'] == 'Fazer transição de carreira e consegui meu primeiro emprego na área', 'O que mais você quer ver no evento?'] = 'Fazer transição de carreira e conseguir meu primeiro emprego na área'

        # Unificar "Quero saber se é para mim" (com espaços especiais)
        df.loc[df['O que mais você quer ver no evento?'].str.contains('Quero saber.*é.*para.*mim', na=False, regex=True), 'O que mais você quer ver no evento?'] = 'Quero saber se é para mim'

        # Unificar recrutadora
        df.loc[df['O que mais você quer ver no evento?'] == 'A aula com a recrutadora;', 'O que mais você quer ver no evento?'] = 'A aula com a recrutadora'

        valores_unicos = df['O que mais você quer ver no evento?'].nunique()
        print(f"   Resultado: {valores_unicos} valores únicos")

    # 4. VOCÊ POSSUI CARTÃO DE CRÉDITO
    print("\n4. Unificando Você possui cartão de crédito?...")
    if 'Você possui cartão de crédito?' in df.columns:
        df['Você possui cartão de crédito?'] = df['Você possui cartão de crédito?'].apply(limpar_texto)

        # Todos os "Sim" (com ou sem caracteres especiais)
        df.loc[df['Você possui cartão de crédito?'].str.contains('Sim', na=False), 'Você possui cartão de crédito?'] = 'Sim'

        valores_unicos = df['Você possui cartão de crédito?'].nunique()
        print(f"   Resultado: {valores_unicos} valores únicos")

    # 5. ATUALMENTE, QUAL A SUA FAIXA SALARIAL
    print("\n5. Unificando Atualmente, qual a sua faixa salarial?...")
    if 'Atualmente, qual a sua faixa salarial?' in df.columns:
        df['Atualmente, qual a sua faixa salarial?'] = df['Atualmente, qual a sua faixa salarial?'].apply(limpar_texto)

        # Remover pontos finais
        df.loc[df['Atualmente, qual a sua faixa salarial?'] == 'Não tenho renda.', 'Atualmente, qual a sua faixa salarial?'] = 'Não tenho renda'
        df.loc[df['Atualmente, qual a sua faixa salarial?'] == 'Entre R$1.000 a R$2.000 reais ao mês.', 'Atualmente, qual a sua faixa salarial?'] = 'Entre R$1.000 a R$2.000 reais ao mês'
        df.loc[df['Atualmente, qual a sua faixa salarial?'] == 'Entre R$2.001 a R$3.000 reais ao mês.', 'Atualmente, qual a sua faixa salarial?'] = 'Entre R$2.001 a R$3.000 reais ao mês'
        df.loc[df['Atualmente, qual a sua faixa salarial?'] == 'Entre R$3.001 a R$5.000 reais ao mês.', 'Atualmente, qual a sua faixa salarial?'] = 'Entre R$3.001 a R$5.000 reais ao mês'
        df.loc[df['Atualmente, qual a sua faixa salarial?'] == 'Mais de R$5.001 reais ao mês.', 'Atualmente, qual a sua faixa salarial?'] = 'Mais de R$5.001 reais ao mês'

        valores_unicos = df['Atualmente, qual a sua faixa salarial?'].nunique()
        print(f"   Resultado: {valores_unicos} valores únicos")

    # 6. O QUE VOCÊ FAZ ATUALMENTE
    print("\n6. Unificando O que você faz atualmente?...")
    if 'O que você faz atualmente?' in df.columns:
        df['O que você faz atualmente?'] = df['O que você faz atualmente?'].apply(limpar_texto)

        # Corrigir "autonomo" para "autônomo"
        df.loc[df['O que você faz atualmente?'] == 'Sou autonomo', 'O que você faz atualmente?'] = 'Sou autônomo'

        # Unificar "autônomo" com descrição
        df.loc[df['O que você faz atualmente?'] == 'Sou autônomo (Uber, freela, vendedor, etc).', 'O que você faz atualmente?'] = 'Sou autônomo'

        # Unificar "não trabalho"
        df.loc[df['O que você faz atualmente?'] == 'Atualmente não trabalho e nem estudo.', 'O que você faz atualmente?'] = 'Não trabalho e nem estudo'

        # Remover ponto final de "Trabalho em outra área"
        df.loc[df['O que você faz atualmente?'] == 'Trabalho em outra área e quero fazer transição para tecnologia.', 'O que você faz atualmente?'] = 'Trabalho em outra área e quero fazer transição para tecnologia'

        # Remover ponto final de outras categorias
        df.loc[df['O que você faz atualmente?'] == 'Estou no ensino médio ou acabei de sair e quero entrar na programação.', 'O que você faz atualmente?'] = 'Estou no ensino médio ou acabei de sair e quero entrar na programação'
        df.loc[df['O que você faz atualmente?'] == 'Estudo T.I. na faculdade mas quero aprender mais por fora.', 'O que você faz atualmente?'] = 'Estudo T.I. na faculdade mas quero aprender mais por fora'
        df.loc[df['O que você faz atualmente?'] == 'Faço outro curso na faculdade e quero mudar para T.I.', 'O que você faz atualmente?'] = 'Faço outro curso na faculdade e quero mudar para T.I'

        valores_unicos = df['O que você faz atualmente?'].nunique()
        print(f"   Resultado: {valores_unicos} valores únicos")

    # 7. QUAL A SUA IDADE
    print("\n7. Unificando Qual a sua idade?...")
    if 'Qual a sua idade?' in df.columns:
        df['Qual a sua idade?'] = df['Qual a sua idade?'].apply(limpar_texto)

        # Remover pontos finais
        df.loc[df['Qual a sua idade?'] == 'Menos de 18 anos.', 'Qual a sua idade?'] = 'Menos de 18 anos'
        df.loc[df['Qual a sua idade?'] == 'Mais de 55 anos.', 'Qual a sua idade?'] = 'Mais de 55 anos'

        valores_unicos = df['Qual a sua idade?'].nunique()
        print(f"   Resultado: {valores_unicos} valores únicos")

    print(f"\nRESULTADO FINAL:")
    print(f"Dataset unificado: {len(df)} registros, {len(df.columns)} colunas")


    return df


def gerar_relatorio_final_categorias(df: pd.DataFrame):
    """
    Gera relatório final após unificação de categorias.

    Args:
        df: DataFrame com categorias unificadas
    """
    print(f"\nRELATÓRIO FINAL - UNIFICAÇÃO COMPLETA")
    print("=" * 50)

    colunas_analisadas = [
        'interesse_programacao',
        'Tem computador/notebook?',
        'O que mais você quer ver no evento?',
        'Você possui cartão de crédito?',
        'Atualmente, qual a sua faixa salarial?',
        'O que você faz atualmente?',
        'Qual a sua idade?'
    ]

    for coluna in colunas_analisadas:
        if coluna in df.columns:
            print(f"\nCOLUNA: {coluna}")
            print("-" * 50)

            valores_unicos = df[coluna].nunique()
            nulos = df[coluna].isnull().sum()
            pct_nulos = (nulos / len(df)) * 100

            print(f"Valores únicos: {valores_unicos}")
            print(f"Valores nulos: {nulos:,} ({pct_nulos:.1f}%)")

            distribuicao = df[coluna].value_counts(dropna=False)
            print(f"Distribuição (Todas as categorias):")

            for valor, count in distribuicao.items():
                pct = (count / len(df)) * 100
                valor_str = str(valor) if valor is not None else 'nan'
                print(f"  {valor_str:<40} {count:>6,} ({pct:>5.1f}%)")
