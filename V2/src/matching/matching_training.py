"""
Módulo para matching robusto por email e telefone - PIPELINE DE TREINO.

Reproduz a célula 15 do notebook DevClub.
Faz matching entre pesquisa e vendas para criar target.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def normalizar_telefone_completo(telefone):
    """Normaliza telefone brasileiro e cria todas as variantes possíveis"""
    if pd.isna(telefone):
        return set()

    # Extrair apenas dígitos
    digitos = ''.join(filter(str.isdigit, str(telefone)))

    if len(digitos) < 8:  # Muito curto para ser válido
        return set()

    variantes = set()

    # Remover código do país (55) se presente
    if digitos.startswith('55') and len(digitos) > 10:
        digitos_sem_pais = digitos[2:]
    else:
        digitos_sem_pais = digitos

    # Casos baseados no comprimento após remover código do país
    if len(digitos_sem_pais) == 11:  # Formato: DDD + 9 + 8 dígitos
        variantes.add(digitos_sem_pais)  # 37999610179
        variantes.add(digitos_sem_pais[3:])  # 99610179 (sem DDD)
        # Formato antigo (sem o 9)
        if digitos_sem_pais[2] == '9':
            formato_antigo = digitos_sem_pais[:2] + digitos_sem_pais[3:]  # 3799610179
            variantes.add(formato_antigo)
            variantes.add(formato_antigo[2:])  # 99610179 (sem DDD, sem 9)

    elif len(digitos_sem_pais) == 10:  # Formato: DDD + 8 dígitos (antigo)
        variantes.add(digitos_sem_pais)  # 3799610179
        variantes.add(digitos_sem_pais[2:])  # 99610179 (sem DDD)
        # Formato novo (com o 9)
        if digitos_sem_pais[2] in ['8', '9']:
            formato_novo = digitos_sem_pais[:2] + '9' + digitos_sem_pais[2:]  # 37999610179
            variantes.add(formato_novo)

    elif len(digitos_sem_pais) == 9:  # Formato: 9 + 8 dígitos (sem DDD)
        variantes.add(digitos_sem_pais)  # 999610179
        # Formato antigo (sem o 9)
        if digitos_sem_pais[0] == '9':
            formato_antigo = digitos_sem_pais[1:]  # 99610179
            variantes.add(formato_antigo)

    elif len(digitos_sem_pais) == 8:  # Formato: 8 dígitos (sem DDD, sem 9)
        variantes.add(digitos_sem_pais)  # 99610179
        # Formato novo (com o 9)
        if digitos_sem_pais[0] in ['8', '9']:
            formato_novo = '9' + digitos_sem_pais  # 999610179
            variantes.add(formato_novo)

    # Remover variantes muito curtas ou inválidas
    variantes_validas = {v for v in variantes if len(v) >= 8}

    return variantes_validas


def normalizar_email(email):
    """Normaliza email para matching"""
    if pd.isna(email):
        return None

    email_str = str(email).strip().lower()

    # Verificar se é um email válido básico
    if '@' in email_str and email_str != 'nan' and len(email_str) > 5:
        return email_str

    return None


def fazer_matching_robusto(df_pesquisa_v1: pd.DataFrame, df_vendas: pd.DataFrame) -> pd.DataFrame:
    """
    Faz matching robusto por email E telefone.

    Reproduz a lógica da célula 15 do notebook DevClub.

    Args:
        df_pesquisa_v1: DataFrame de pesquisa (versão 1 pós-cutoff)
        df_vendas: DataFrame de vendas

    Returns:
        DataFrame com target adicionado
    """
    print("MATCHING ROBUSTO POR EMAIL E TELEFONE")

    df_pesquisa = df_pesquisa_v1.copy()
    df_vendas_copy = df_vendas.copy()

    print(f"\nProcessando DATASET V1...")

    # 1. NORMALIZAR EMAILS
    emails_pesquisa = {}
    for idx, email in df_pesquisa['E-mail'].items():
        email_norm = normalizar_email(email)
        if email_norm:
            emails_pesquisa[idx] = email_norm

    emails_vendas = set()
    for email in df_vendas_copy['email']:
        email_norm = normalizar_email(email)
        if email_norm:
            emails_vendas.add(email_norm)

    print(f"  Emails únicos na pesquisa: {len(emails_pesquisa):,}")
    print(f"  Emails únicos nas vendas: {len(emails_vendas):,}")

    # 2. NORMALIZAR TELEFONES
    telefones_pesquisa = {}
    for idx, telefone in df_pesquisa['Telefone'].items():
        variantes = normalizar_telefone_completo(telefone)
        if variantes:
            telefones_pesquisa[idx] = variantes

    telefones_vendas = set()
    for telefone in df_vendas_copy['telefone']:
        variantes = normalizar_telefone_completo(telefone)
        telefones_vendas.update(variantes)

    print(f"  Telefones válidos na pesquisa: {len(telefones_pesquisa):,}")
    print(f"  Variantes de telefone nas vendas: {len(telefones_vendas):,}")

    # 3. FAZER MATCHING
    matches_email = set()
    matches_telefone = set()

    # Matching por email
    for idx, email in emails_pesquisa.items():
        if email in emails_vendas:
            matches_email.add(idx)

    # Matching por telefone
    for idx, variantes in telefones_pesquisa.items():
        if variantes & telefones_vendas:  # Interseção de conjuntos
            matches_telefone.add(idx)

    # 4. CRIAR TARGET
    df_resultado = df_pesquisa.copy()
    df_resultado['target'] = 0

    # Marcar matches
    for idx in matches_email | matches_telefone:  # União dos conjuntos
        df_resultado.loc[idx, 'target'] = 1

    # 5. ESTATÍSTICAS
    total_registros = len(df_resultado)
    total_matches = df_resultado['target'].sum()
    matches_apenas_email = len(matches_email - matches_telefone)
    matches_apenas_telefone = len(matches_telefone - matches_email)
    matches_ambos = len(matches_email & matches_telefone)
    taxa_conversao = (total_matches / total_registros) * 100

    print(f"  Total de registros: {total_registros:,}")
    print(f"  Total de matches: {total_matches:,}")
    print(f"  Taxa de conversão: {taxa_conversao:.2f}%")
    print(f"  Matches apenas por email: {matches_apenas_email:,}")
    print(f"  Matches apenas por telefone: {matches_apenas_telefone:,}")
    print(f"  Matches por ambos: {matches_ambos:,}")

    print("DATASET FINAL CRIADO!")
    print(f"dataset_v1_final: {len(df_resultado):,} registros, {len(df_resultado.columns)} colunas")
    print("Dataset contém apenas colunas originais + target")

    # Listar variáveis
    print(f"\n VARIÁVEIS DO DATASET V1 ({len(df_resultado.columns)} colunas):")
    for i, col in enumerate(df_resultado.columns, 1):
        print(f"  {i:2d}. {col}")

    return df_resultado
