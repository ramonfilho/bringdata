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
    print("FEATURE ENGINEERING COMPLETO")
    print("=" * 29)

    df = df_devclub.copy()

    print(f"\nProcessando DATASET V1 DEVCLUB...")
    print(f"Registros: {len(df):,}")
    print(f"Colunas antes: {len(df.columns)}")

    # Imprimir nomes das colunas antes
    print("Nomes das colunas antes:")
    for i, col in enumerate(df.columns, 1):
        print(f"  {i:2d}. {col}")

    # 1. FEATURES TEMPORAIS
    print(f"\n📅 Processando feature temporal (dia_semana):")
    print(f"   Tipo original da coluna Data: {df['Data'].dtype}")

    # Detectar formato automaticamente baseado na primeira data válida
    if len(df) > 0:
        sample_date = df['Data'].iloc[0]
        print(f"   Primeira data (amostra): {sample_date}")

        if sample_date and isinstance(sample_date, str):
            # Detectar formato: se começa com 4 dígitos = YYYY-MM-DD, senão = DD/MM/YYYY
            if sample_date.strip()[0:4].isdigit():
                # Formato ISO: YYYY-MM-DD ou YYYY-MM-DD HH:MM:SS
                print(f"   ✓ Formato detectado: ISO (YYYY-MM-DD)")
                df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
            else:
                # Formato brasileiro: DD/MM/YYYY
                print(f"   ✓ Formato detectado: BR (DD/MM/YYYY)")
                df['Data'] = pd.to_datetime(df['Data'], format='%d/%m/%Y', errors='coerce')
        else:
            # Já é datetime ou fallback
            print(f"   ✓ Data já é datetime ou fallback para auto-detect")
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
    else:
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce')

    # Verificar parsing
    nans_after_parse = df['Data'].isna().sum()
    print(f"   Datas inválidas após parsing: {nans_after_parse} / {len(df)} ({nans_after_parse/len(df)*100:.1f}%)")

    df['dia_semana'] = df['Data'].dt.dayofweek
    print(f"   ✓ Feature dia_semana criada")

    # 2. FEATURES DE QUALIDADE DOS IDENTIFICADORES

    # Nome
    df['nome_comprimento'] = df['Nome Completo'].astype(str).str.len()
    df['nome_tem_sobrenome'] = df['Nome Completo'].astype(str).str.split().str.len() >= 2
    df['nome_valido'] = df['Nome Completo'].apply(validar_nome_robusto)

    # Email
    df['email_valido'] = df['E-mail'].apply(validar_email_robusto)

    # Telefone
    df['telefone_normalizado'] = df['Telefone'].apply(normalizar_telefone_robusto)
    df['telefone_valido'] = df['telefone_normalizado'].notna()
    df['telefone_comprimento'] = df['telefone_normalizado'].astype(str).str.len()

    # ANÁLISE DE TELEFONES VÁLIDOS POR ARQUIVO DE ORIGEM
    if 'arquivo_origem' in df.columns:
        print(f"\n% de telefones válidos por arquivo de origem:")
        telefone_por_arquivo = df.groupby('arquivo_origem')['telefone_valido'].agg(['count', 'sum', 'mean']).round(3)
        telefone_por_arquivo['pct_valido'] = (telefone_por_arquivo['mean'] * 100).round(1)
        telefone_por_arquivo = telefone_por_arquivo.sort_values('pct_valido', ascending=False)

        for arquivo in telefone_por_arquivo.index:
            total = telefone_por_arquivo.loc[arquivo, 'count']
            validos = telefone_por_arquivo.loc[arquivo, 'sum']
            pct = telefone_por_arquivo.loc[arquivo, 'pct_valido']
            print(f"  {arquivo}: {validos:,}/{total:,} ({pct}%)")

    # 3. REMOVER COLUNAS DESNECESSÁRIAS
    colunas_remover = [
        'aba_origem', 'arquivo_origem', 'Data',
        'Nome Completo', 'E-mail', 'Telefone', 'telefone_normalizado'
    ]

    # Verificar quais colunas existem antes de remover
    colunas_existentes = [col for col in colunas_remover if col in df.columns]

    if colunas_existentes:
        df = df.drop(columns=colunas_existentes)
        print(f"Colunas removidas: {len(colunas_existentes)}")
        for col in colunas_existentes:
            print(f"  - {col}")

    print(f"Colunas depois: {len(df.columns)}")

    # Imprimir nomes das colunas depois
    print("Nomes das colunas depois:")
    for i, col in enumerate(df.columns, 1):
        print(f"  {i:2d}. {col}")

    # 4. ESTATÍSTICAS DAS NOVAS FEATURES
    print(f"\nEstatísticas das features criadas:")
    print(f"Nome válido: {df['nome_valido'].sum():,} ({df['nome_valido'].mean()*100:.1f}%)")
    print(f"Nome com sobrenome: {df['nome_tem_sobrenome'].sum():,} ({df['nome_tem_sobrenome'].mean()*100:.1f}%)")
    print(f"Email válido: {df['email_valido'].sum():,} ({df['email_valido'].mean()*100:.1f}%)")
    print(f"Telefone válido: {df['telefone_valido'].sum():,} ({df['telefone_valido'].mean()*100:.1f}%)")

    # 5. DISTRIBUIÇÃO DA FEATURE TEMPORAL
    print(f"\nDistribuição da feature temporal:")
    dia_semana_counts = df['dia_semana'].value_counts().sort_index()
    nomes_dias = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    for dia, count in dia_semana_counts.items():
        pct = (count / len(df)) * 100
        print(f"  {dia} ({nomes_dias[dia]}): {count:,} ({pct:.1f}%)")

    # 6. RESUMO FINAL
    print(f"\n" + "=" * 60)
    print("DATASET FINAL PARA MODELAGEM")
    print("=" * 60)

    print(f"\nDATASET V1 DEVCLUB:")
    print(f"  Registros: {len(df):,}")
    print(f"  Colunas: {len(df.columns)}")
    print(f"  Target positivo: {df['target'].sum():,} ({df['target'].mean()*100:.2f}%)")

    print(f"\nDataset pronto para encoding e modelagem!")

    logger.info(f"✅ Feature engineering completo")

    return df
