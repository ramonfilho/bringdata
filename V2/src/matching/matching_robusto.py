"""
Módulo para matching robusto por email e telefone - MÉTODO 2 (ROBUSTO).

Reproduz a célula 15 do notebook DevClub usando normalização robusta de telefone.
Diferente do Método 1, não gera variantes múltiplas, fazendo matching direto.
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
    Faz matching robusto por email E telefone - MÉTODO 2 (ROBUSTO).

    Reproduz a lógica da célula 15 do notebook DevClub usando normalização
    robusta (sem variantes múltiplas).

    Args:
        df_pesquisa_v1: DataFrame de pesquisa (versão 1 pós-cutoff)
        df_vendas: DataFrame de vendas

    Returns:
        DataFrame com target adicionado
    """
    print("MATCHING ROBUSTO POR EMAIL E TELEFONE - MÉTODO 2 (ROBUSTO)")

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

    # 2. NORMALIZAR TELEFONES (MÉTODO ROBUSTO)
    telefones_pesquisa = {}
    telefones_validos_count = 0
    for idx, telefone in df_pesquisa['Telefone'].items():
        telefone_norm = normalizar_telefone_robusto(telefone)
        if telefone_norm:
            telefones_pesquisa[idx] = telefone_norm
            telefones_validos_count += 1

    telefones_vendas = set()
    for telefone in df_vendas_copy['telefone']:
        telefone_norm = normalizar_telefone_robusto(telefone)
        if telefone_norm:
            telefones_vendas.add(telefone_norm)

    total_telefones_pesquisa = len(df_pesquisa)
    pct_telefones_validos = (telefones_validos_count / total_telefones_pesquisa) * 100

    print(f"  Telefones válidos na pesquisa: {telefones_validos_count:,}/{total_telefones_pesquisa:,} ({pct_telefones_validos:.1f}%)")
    print(f"  Telefones únicos nas vendas: {len(telefones_vendas):,}")

    # 3. FAZER MATCHING
    matches_email = set()
    matches_telefone = set()

    # Matching por email
    for idx, email in emails_pesquisa.items():
        if email in emails_vendas:
            matches_email.add(idx)

    # Matching por telefone (comparação direta, sem variantes)
    for idx, telefone_norm in telefones_pesquisa.items():
        if telefone_norm in telefones_vendas:
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
    print(f"\n📋 VARIÁVEIS DO DATASET V1 ({len(df_resultado.columns)} colunas):")
    for i, col in enumerate(df_resultado.columns, 1):
        print(f"  {i:2d}. {col}")

    return df_resultado
