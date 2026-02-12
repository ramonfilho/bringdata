"""
Módulo para filtragem de vendas DevClub - PIPELINE DE TREINO.

FILTRO (não refaz matching):
- Mantém o target da célula 15 (matching inicial)
- Filtra apenas matches que correspondem a vendas DevClub
- Zera target para matches de outros produtos
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

    # Verificar se é um email válido básico
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


def criar_dataset_devclub(df_v1_final: pd.DataFrame, df_vendas_unificado: pd.DataFrame, method: str = 'filter') -> pd.DataFrame:
    """
    Filtra dataset V1 para manter apenas vendas DevClub.

    NÃO REFAZ MATCHING. Apenas filtra os matches existentes (target=1)
    para manter apenas aqueles que compraram produtos DevClub.

    Args:
        df_v1_final: DataFrame V1 com target do matching inicial (célula 15)
        df_vendas_unificado: DataFrame de vendas unificado
        method: 'filter' - mantém target existente e filtra por produtos DevClub

    Returns:
        DataFrame V1 com target filtrado apenas para DevClub
    """
    # DEBUG: Título da filtragem
    logger.debug("FILTRAGEM DEVCLUB - MANTENDO TARGET DO MATCHING INICIAL")

    # 1. PRODUTOS DEVCLUB A MANTER
    produtos_devclub_manter = [
        'DevClub - Full Stack 2025',
        'DevClub FullStack Pro - OFICIAL',
        'Formação DevClub FullStack Pro - OFICI',
        'Formação DevClub FullStack Pro - OFICIAL',  # Nome completo (não truncado)
        'DevClub - Full Stack 2025 - EV',
        'DevClub - FS - Vitalício',
        '[Vitalício] Formação DevClub FullStack',
        '[Vitalício] Formação DevClub FullStack Pro - OFICIAL',  # Vitalício completo
        'Formação DevClub FullStack Pro - COMER',
        'Formação DevClub FullStack Pro - COMERCIAL',  # Nome completo (não truncado)
        'Formação DevClub FullStack Pro',  # Sem sufixo
        'DevClub Vitalício',
        'DevClub 3.0 - 2024',
        '(Desativado) DevClub 3.0 - 2024',
        '(Desativado) DevClub 3.0 - 2024 - Novo'
    ]

    # 2. IDENTIFICAR COMPRADORES DEVCLUB
    df_vendas_devclub = df_vendas_unificado[df_vendas_unificado['produto'].isin(produtos_devclub_manter)].copy()

    # Normalizar emails
    df_vendas_devclub['email_clean'] = df_vendas_devclub['email'].apply(normalizar_email)
    emails_compradores_devclub = set(df_vendas_devclub['email_clean'].dropna())

    # Normalizar telefones
    df_vendas_devclub['telefone_clean'] = df_vendas_devclub['telefone'].apply(normalizar_telefone_robusto)
    telefones_compradores_devclub = set(df_vendas_devclub['telefone_clean'].dropna())

    logger.debug(f"Produtos DevClub identificados: {len(produtos_devclub_manter)}")
    logger.debug(f"Vendas DevClub: {len(df_vendas_devclub):,}")
    logger.debug(f"Emails únicos compradores DevClub: {len(emails_compradores_devclub):,}")
    logger.debug(f"Telefones únicos compradores DevClub: {len(telefones_compradores_devclub):,}")

    # 3. FILTRAR TARGET EXISTENTE
    df_devclub = df_v1_final.copy()

    # Verificar se target existe
    if 'target' not in df_devclub.columns:
        raise ValueError("Dataset não possui coluna 'target'. Execute matching inicial primeiro (célula 15).")

    # Pegar índices com target=1 (matches do matching inicial)
    indices_matches = df_devclub[df_devclub['target'] == 1].index

    logger.debug(f"\nMatches do matching inicial (célula 15): {len(indices_matches):,}")

    # 4. VERIFICAR QUAIS DESSES MATCHES SÃO DEVCLUB
    # Normalizar dados do dataset de pesquisa
    df_devclub['email_temp'] = df_devclub['E-mail'].apply(normalizar_email)
    df_devclub['telefone_temp'] = df_devclub['Telefone'].apply(normalizar_telefone_robusto)

    # Verificar quais matches são DevClub
    devclub_matches = set()
    matches_por_email = 0
    matches_por_telefone = 0
    matches_por_ambos = 0

    for idx in indices_matches:
        email_match = df_devclub.loc[idx, 'email_temp'] in emails_compradores_devclub
        telefone_match = df_devclub.loc[idx, 'telefone_temp'] in telefones_compradores_devclub

        if email_match or telefone_match:
            devclub_matches.add(idx)
            if email_match and telefone_match:
                matches_por_ambos += 1
            elif email_match:
                matches_por_email += 1
            else:
                matches_por_telefone += 1

    # 4.5. ANALISAR PRODUTOS DOS MATCHES DESCARTADOS
    indices_descartados = set(indices_matches) - devclub_matches

    if len(indices_descartados) > 0:
        logger.debug(f"\n ANALISANDO {len(indices_descartados):,} MATCHES DESCARTADOS:")
        logger.debug("-" * 70)

        # Normalizar vendas para busca
        df_vendas_unificado['email_clean'] = df_vendas_unificado['email'].apply(normalizar_email)
        df_vendas_unificado['telefone_clean'] = df_vendas_unificado['telefone'].apply(normalizar_telefone_robusto)

        # Coletar produtos dos descartados
        produtos_descartados = []

        for idx in indices_descartados:
            email = df_devclub.loc[idx, 'email_temp']
            telefone = df_devclub.loc[idx, 'telefone_temp']

            # Buscar vendas dessa pessoa
            vendas_pessoa = df_vendas_unificado[
                (df_vendas_unificado['email_clean'] == email) |
                (df_vendas_unificado['telefone_clean'] == telefone)
            ]

            produtos_pessoa = vendas_pessoa['produto'].dropna().unique().tolist()
            produtos_descartados.extend(produtos_pessoa)

        # Contar produtos
        from collections import Counter
        produtos_count = Counter(produtos_descartados)
        produtos_sorted = produtos_count.most_common()

        logger.debug(f"\n{'PRODUTO':<60} {'QUANTIDADE':>10}")
        logger.debug("-" * 70)
        for produto, qtd in produtos_sorted:
            logger.debug(f"{str(produto)[:58]:<60} {qtd:>10}")

        logger.debug(f"\n{'TOTAL DE PRODUTOS DIFERENTES:':<60} {len(produtos_sorted):>10}")
        logger.debug(f"{'TOTAL DE COMPRAS (pode haver duplicatas):':<60} {len(produtos_descartados):>10}")

    # 5. ATUALIZAR TARGET - ZERAR NÃO-DEVCLUB
    df_devclub['target_devclub'] = 0
    df_devclub.loc[list(devclub_matches), 'target_devclub'] = 1

    # Limpar colunas temporárias
    df_devclub = df_devclub.drop(columns=['email_temp', 'telefone_temp', 'target'])
    df_devclub = df_devclub.rename(columns={'target_devclub': 'target'})

    # 6. ESTATÍSTICAS
    total_registros = len(df_devclub)
    leads_qualificados = df_devclub['target'].sum()
    taxa_conversao = (leads_qualificados / total_registros * 100) if total_registros > 0 else 0

    matches_perdidos = len(indices_matches) - leads_qualificados

    logger.debug(f"\nRESULTADO DA FILTRAGEM:")
    logger.debug(f"  Matches iniciais: {len(indices_matches):,}")
    logger.debug(f"  Matches DevClub mantidos: {leads_qualificados:,}")
    logger.debug(f"  Matches descartados (outros produtos): {matches_perdidos:,}")
    logger.debug(f"  Taxa de retenção: {(leads_qualificados/len(indices_matches)*100):.1f}%" if len(indices_matches) > 0 else "0.0%")

    logger.debug(f"\nDETALHAMENTO DOS MATCHES DEVCLUB:")
    logger.debug(f"  Matches apenas por email: {matches_por_email:,}")
    logger.debug(f"  Matches apenas por telefone: {matches_por_telefone:,}")
    logger.debug(f"  Matches por ambos (email E telefone): {matches_por_ambos:,}")

    # NORMAL: Resumo final
    logger.info("")
    logger.info("DATASET V1 DEVCLUB:")
    logger.info(f"  Total de registros: {total_registros:,}")
    logger.info(f"  Leads qualificados DevClub: {leads_qualificados:,}")
    logger.info(f"  Taxa de conversão DevClub: {taxa_conversao:.2f}%")


    return df_devclub
