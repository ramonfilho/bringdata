"""
Módulo para feature engineering - PIPELINE DE TREINO.

Reproduz a célula 18 do notebook DevClub.
Cria features derivadas e remove colunas desnecessárias.
"""

import pandas as pd
import re
import logging

logger = logging.getLogger(__name__)


def normalizar_telefone_robusto(telefone):
    """Normaliza telefone considerando notação científica e padrões brasileiros"""
    if pd.isna(telefone):
        return None

    # Converter para string e lidar com notação científica
    # CORREÇÃO: Se é float, converter diretamente para int para remover .0
    if isinstance(telefone, float):
        tel_str = str(int(telefone))
    else:
        tel_str = str(telefone)

    # Se está em notação científica, converter para número inteiro
    if 'e+' in tel_str.lower() or 'E+' in tel_str:
        try:
            tel_str = str(int(float(tel_str)))
        except:
            pass

    # Remover .0 de strings (comum quando CSV é lido com dtype=str)
    # Ex: '5551998784135.0' -> '5551998784135'
    if '.0' in tel_str:
        tel_str = tel_str.replace('.0', '')

    # Extrair apenas dígitos
    digitos = re.sub(r'\D', '', tel_str)

    if len(digitos) < 8:
        return None

    # Remover código do país (55) se presente
    if digitos.startswith('55') and len(digitos) > 10:
        digitos = digitos[2:]

    # Verificar se é um telefone válido brasileiro
    if len(digitos) in [10, 11]:  # DDD + 8 ou 9 dígitos
        return digitos
    elif len(digitos) in [8, 9]:  # Sem DDD
        return digitos

    return None


def validar_email_robusto(email):
    """Valida email com regex rigoroso"""
    if pd.isna(email):
        return False

    email_str = str(email).strip().lower()

    # Regex básico para email
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    return bool(re.match(pattern, email_str))


def validar_nome_robusto(nome):
    """Valida se nome não é apenas números ou caracteres especiais"""
    if pd.isna(nome):
        return False

    nome_str = str(nome).strip()

    # Verificar se tem pelo menos algumas letras
    tem_letras = bool(re.search(r'[a-zA-ZÀ-ÿ]', nome_str))

    # Verificar se não é só números
    nao_so_numeros = not nome_str.replace(' ', '').replace('.', '').replace('-', '').isdigit()

    return tem_letras and nao_so_numeros and len(nome_str) >= 2


def criar_features_derivadas(df_devclub: pd.DataFrame) -> pd.DataFrame:
    """
    Cria features derivadas e remove colunas desnecessárias.

    Reproduz a lógica da célula 18 do notebook DevClub.

    Args:
        df_devclub: DataFrame V1 DevClub com target

    Returns:
        DataFrame com features derivadas
    """
    logger.debug("FEATURE ENGINEERING COMPLETO")

    df = df_devclub.copy()

    logger.debug(f"\nProcessando DATASET V1 DEVCLUB...")
    logger.debug(f"Registros: {len(df):,}")

    # NORMAL: Número de colunas antes
    colunas_antes = len(df.columns)
    logger.info(f"Colunas antes: {colunas_antes}")

    # NORMAL: Lista de nomes das colunas antes
    logger.info("Nomes das colunas antes:")
    for i, col in enumerate(df.columns, 1):
        logger.info(f"  {i:2d}. {col}")

    # 1. FEATURES TEMPORAIS
    # DEBUG: Processamento de feature temporal
    logger.debug(f"\n Processando feature temporal (dia_semana):")
    logger.debug(f"   Tipo original da coluna Data: {df['Data'].dtype}")

    # Detectar formato automaticamente baseado na primeira data válida
    if len(df) > 0:
        sample_date = df['Data'].iloc[0]
        logger.debug(f"   Primeira data (amostra): {sample_date}")

        if sample_date and isinstance(sample_date, str):
            # Detectar formato: se começa com 4 dígitos = YYYY-MM-DD, senão = DD/MM/YYYY
            if sample_date.strip()[0:4].isdigit():
                # Formato ISO: YYYY-MM-DD ou YYYY-MM-DD HH:MM:SS
                logger.debug(f"    Formato detectado: ISO (YYYY-MM-DD)")
                df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
            else:
                # Formato brasileiro: DD/MM/YYYY
                logger.debug(f"    Formato detectado: BR (DD/MM/YYYY)")
                df['Data'] = pd.to_datetime(df['Data'], format='%d/%m/%Y', errors='coerce')
        else:
            # Já é datetime ou fallback
            logger.debug(f"    Data já é datetime ou fallback para auto-detect")
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
    else:
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce')

    # Verificar parsing
    nans_after_parse = df['Data'].isna().sum()
    logger.debug(f"   Datas inválidas após parsing: {nans_after_parse} / {len(df)} ({nans_after_parse/len(df)*100:.1f}%)")

    df['dia_semana'] = df['Data'].dt.dayofweek
    logger.debug(f"    Feature dia_semana criada")

    # 2. FEATURES DE QUALIDADE DOS IDENTIFICADORES

    # Nome
    df['nome_comprimento'] = df['Nome Completo'].astype(str).str.len()
    df['nome_tem_sobrenome'] = df['Nome Completo'].astype(str).str.split().str.len() >= 2

    # Telefone
    df['telefone_normalizado'] = df['Telefone'].apply(normalizar_telefone_robusto)
    df['telefone_comprimento'] = df['telefone_normalizado'].astype(str).str.len()
    # Agrupar comprimentos raros (4=inválido, 10=obsoleto) em 'outros'
    df['telefone_comprimento'] = df['telefone_comprimento'].apply(
        lambda x: x if x in [9, 11] else 'outros'
    )

    # DEBUG: ANÁLISE DE TELEFONES VÁLIDOS POR ARQUIVO DE ORIGEM
    if 'arquivo_origem' in df.columns:
        logger.debug(f"\n% de telefones válidos por arquivo de origem:")
        tel_valido = df['telefone_normalizado'].notna()
        telefone_por_arquivo = df.groupby('arquivo_origem').apply(
            lambda g: pd.Series({'total': len(g), 'validos': g['telefone_normalizado'].notna().sum()})
        )
        telefone_por_arquivo['pct_valido'] = (telefone_por_arquivo['validos'] / telefone_por_arquivo['total'] * 100).round(1)
        telefone_por_arquivo = telefone_por_arquivo.sort_values('pct_valido', ascending=False)

        for arquivo in telefone_por_arquivo.index:
            total = telefone_por_arquivo.loc[arquivo, 'total']
            validos = telefone_por_arquivo.loc[arquivo, 'validos']
            pct = telefone_por_arquivo.loc[arquivo, 'pct_valido']
            logger.debug(f"  {arquivo}: {validos:,}/{total:,} ({pct}%)")

    # 3. REMOVER COLUNAS DESNECESSÁRIAS
    colunas_remover = [
        'aba_origem', 'arquivo_origem', 'Data',
        'Nome Completo', 'E-mail', 'Telefone', 'telefone_normalizado',
        # Variantes de identificadores de formatos alternativos (sheets CRM antigos + Guru API)
        # Já usados no matching (Célula 15) — não entram no encoding
        'Nome', 'Email', 'EMAIL',
    ]

    # Verificar quais colunas existem antes de remover
    colunas_existentes = [col for col in colunas_remover if col in df.columns]

    if colunas_existentes:
        df = df.drop(columns=colunas_existentes)
        # DEBUG: Colunas removidas
        logger.debug(f"Colunas removidas: {len(colunas_existentes)}")
        for col in colunas_existentes:
            logger.debug(f"  - {col}")

    # NORMAL: Número de colunas depois
    colunas_depois = len(df.columns)
    logger.info(f"Colunas depois: {colunas_depois}")

    # NORMAL: Lista de nomes das colunas depois
    logger.info("Nomes das colunas depois:")
    for i, col in enumerate(df.columns, 1):
        logger.info(f"  {i:2d}. {col}")
    logger.info("")

    # NORMAL: Features removidas e adicionadas
    features_removidas = colunas_antes - colunas_depois + len(colunas_existentes)
    features_adicionadas = colunas_depois - colunas_antes + len(colunas_existentes)
    logger.info(f"  Features removidas: {features_removidas}")
    logger.info(f"  Features adicionadas: {features_adicionadas}")
    logger.info("")

    # 4. DEBUG: ESTATÍSTICAS DAS NOVAS FEATURES
    logger.debug(f"\nEstatísticas das features criadas:")
    logger.debug(f"Nome com sobrenome: {df['nome_tem_sobrenome'].sum():,} ({df['nome_tem_sobrenome'].mean()*100:.1f}%)")

    # 5. DEBUG: DISTRIBUIÇÃO DA FEATURE TEMPORAL
    logger.debug(f"\nDistribuição da feature temporal:")
    dia_semana_counts = df['dia_semana'].value_counts().sort_index()
    nomes_dias = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    for dia, count in dia_semana_counts.items():
        pct = (count / len(df)) * 100
        logger.debug(f"  {dia} ({nomes_dias[dia]}): {count:,} ({pct:.1f}%)")

    # 6. RESUMO FINAL
    logger.debug("DATASET FINAL PARA MODELAGEM")

    logger.debug(f"\nDATASET V1 DEVCLUB:")
    logger.debug(f"  Registros: {len(df):,}")
    logger.debug(f"  Colunas: {len(df.columns)}")
    logger.debug(f"  Target positivo: {df['target'].sum():,} ({df['target'].mean()*100:.2f}%)")

    logger.debug(f"\nDataset pronto para encoding e modelagem!")
    logger.info("")

    return df
