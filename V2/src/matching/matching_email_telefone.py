"""
Módulo para matching por EMAIL + TELEFONE com validações rigorosas.

Estratégia:
1. Matching primário: email (100% confiável)
2. Matching secundário: telefone (com validações para evitar falsos positivos)
   - Telefone deve ter 10-11 dígitos válidos
   - Não matchear se já foi matcheado por email
"""

import pandas as pd
import re
import logging

logger = logging.getLogger(__name__)


def normalizar_email(email):
    """Normaliza email para matching"""
    if pd.isna(email):
        return None

    email_str = str(email).strip().lower()

    if '@' in email_str and email_str != 'nan' and len(email_str) > 5:
        return email_str

    return None


def normalizar_telefone_robusto(telefone):
    """Normaliza telefone considerando notação científica e padrões brasileiros"""
    if pd.isna(telefone):
        return None

    # Converter para string e lidar com notação científica
    if isinstance(telefone, float):
        tel_str = str(int(telefone))
    else:
        tel_str = str(telefone)

    # Se está em notação científica, converter
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


def fazer_matching_email_telefone(df_pesquisa_v1: pd.DataFrame, df_vendas: pd.DataFrame) -> pd.DataFrame:
    """
    Faz matching por EMAIL (primário) + TELEFONE (secundário com validações).

    Prioriza email (100% confiável), depois usa telefone com validações
    rigorosas para evitar falsos positivos.

    Args:
        df_pesquisa_v1: DataFrame de pesquisa (versão 1 pós-cutoff)
        df_vendas: DataFrame de vendas

    Returns:
        DataFrame com target adicionado
    """
    # DEBUG: Título do matching
    logger.debug("MATCHING: EMAIL (PRIMÁRIO) + TELEFONE (SECUNDÁRIO)")

    df_pesquisa = df_pesquisa_v1.copy()
    df_vendas_copy = df_vendas.copy()

    logger.debug("")
    logger.debug("Processando DATASET V1...")

    # 1. NORMALIZAR DADOS
    # Pesquisa
    emails_pesquisa = {}
    telefones_pesquisa = {}

    for idx, row in df_pesquisa.iterrows():
        email_norm = normalizar_email(row['E-mail'])
        if email_norm:
            emails_pesquisa[idx] = email_norm

        tel_norm = normalizar_telefone_robusto(row['Telefone'])
        if tel_norm and len(tel_norm) >= 10:  # Só telefones com 10+ dígitos
            telefones_pesquisa[idx] = tel_norm

    # Vendas
    emails_vendas = set()
    telefones_vendas = set()

    for _, row in df_vendas_copy.iterrows():
        email_norm = normalizar_email(row['email'])
        if email_norm:
            emails_vendas.add(email_norm)

        tel_norm = normalizar_telefone_robusto(row['telefone'])
        if tel_norm and len(tel_norm) >= 10:  # Só telefones com 10+ dígitos
            telefones_vendas.add(tel_norm)

    # DEBUG: Estatísticas de normalização
    logger.debug(f"  Emails únicos na pesquisa: {len(emails_pesquisa):,}")
    logger.debug(f"  Emails únicos nas vendas: {len(emails_vendas):,}")
    logger.debug(f"  Telefones únicos na pesquisa (≥10 dígitos): {len(telefones_pesquisa):,}")
    logger.debug(f"  Telefones únicos nas vendas (≥10 dígitos): {len(telefones_vendas):,}")

    # 2. MATCHING PRIMÁRIO POR EMAIL
    matches_email = set()

    for idx, email in emails_pesquisa.items():
        if email in emails_vendas:
            matches_email.add(idx)

    logger.debug("")
    logger.debug(f"📧 MATCHES POR EMAIL: {len(matches_email):,}")

    # 3. MATCHING SECUNDÁRIO POR TELEFONE (APENAS NÃO MATCHEADOS)
    matches_telefone = set()
    indices_nao_matcheados = set(telefones_pesquisa.keys()) - matches_email

    for idx in indices_nao_matcheados:
        if idx in telefones_pesquisa:
            tel = telefones_pesquisa[idx]
            if tel in telefones_vendas:
                matches_telefone.add(idx)

    logger.debug(f"📞 MATCHES POR TELEFONE (novos): {len(matches_telefone):,}")

    # 4. CONSOLIDAR MATCHES
    matches_total = matches_email | matches_telefone

    logger.debug("")
    logger.debug(f"✅ TOTAL DE MATCHES: {len(matches_total):,}")
    logger.debug(f"   Email: {len(matches_email):,} ({len(matches_email)/len(matches_total)*100:.1f}%)")
    logger.debug(f"   Telefone: {len(matches_telefone):,} ({len(matches_telefone)/len(matches_total)*100:.1f}%)")

    # 5. CRIAR TARGET
    df_resultado = df_pesquisa.copy()
    df_resultado['target'] = 0

    for idx in matches_total:
        df_resultado.loc[idx, 'target'] = 1

    # 6. ESTATÍSTICAS
    total_registros = len(df_resultado)
    total_matches = df_resultado['target'].sum()
    taxa_conversao = (total_matches / total_registros) * 100

    # NORMAL: Resumo final
    logger.info("")
    logger.info("DATASET FINAL:")
    logger.info(f"  Total de registros: {total_registros:,}")
    logger.info(f"  Total de matches: {total_matches:,}")
    logger.info(f"  Taxa de conversão: {taxa_conversao:.2f}%")

    # DEBUG: Ganho vs email_only
    logger.debug(f"  Ganho vs email_only: +{len(matches_telefone):,} matches")

    return df_resultado
