"""
Módulo de matching unificado com suporte a ÚLTIMOS 6 DÍGITOS do telefone.

Este módulo adiciona uma nova estratégia de matching que serve tanto o pipeline
de validação quanto o de treino, mantendo compatibilidade com os métodos existentes.

Estratégia de matching (ordem de prioridade):
1. Email (100% confiável)
2. Telefone completo normalizado (10-11 dígitos)
3. Últimos 6 dígitos do telefone (fallback para casos não matcheados)

Baseado em: matching_email_telefone.py (método padrão atual)
"""

import pandas as pd
import numpy as np
from datetime import timedelta
from typing import Dict, Optional
import logging

# Importar funções de normalização existentes (reutilização)
from src.matching.matching_email_telefone import normalizar_email, normalizar_telefone_robusto

logger = logging.getLogger(__name__)


def extrair_ultimos_6_digitos(telefone: str) -> Optional[str]:
    """
    Extrai os últimos 6 dígitos de um telefone normalizado.

    Args:
        telefone: Telefone normalizado (apenas dígitos)

    Returns:
        String com últimos 6 dígitos, ou None se inválido

    Examples:
        >>> extrair_ultimos_6_digitos('37999610179')
        '610179'
        >>> extrair_ultimos_6_digitos('11987610179')
        '610179'
        >>> extrair_ultimos_6_digitos('999610179')
        '610179'
        >>> extrair_ultimos_6_digitos('12345')  # Muito curto
        None
    """
    if pd.isna(telefone) or not telefone:
        return None

    telefone_norm = normalizar_telefone_robusto(telefone)
    if not telefone_norm:
        return None

    # Só extrair se tem pelo menos 6 dígitos
    if len(telefone_norm) < 6:
        return None

    return telefone_norm[-6:]


def _get_column_name(df: pd.DataFrame, options: list) -> str:
    """
    Detecta nome de coluna automaticamente (suporta diferentes nomenclaturas).

    Args:
        df: DataFrame para buscar coluna
        options: Lista de nomes possíveis (ex: ['email', 'E-mail'])

    Returns:
        Nome da coluna encontrada

    Raises:
        ValueError: Se nenhuma das opções for encontrada
    """
    for option in options:
        if option in df.columns:
            return option
    raise ValueError(f"Nenhuma das colunas {options} encontrada no DataFrame")


def match_leads_to_sales_unified(
    leads_df: pd.DataFrame,
    sales_df: pd.DataFrame,
    mode: str = 'validation',
    use_temporal_validation: bool = False
) -> pd.DataFrame:
    """
    Matching unificado com suporte a ÚLTIMOS 6 DÍGITOS.

    Serve tanto pipeline de validação quanto de treino.

    Estratégia de matching (prioridade):
    1. Email (100% confiável)
    2. Telefone completo normalizado (10-11 dígitos)
    3. Últimos 6 dígitos (fallback para não matcheados)

    Args:
        leads_df: DataFrame de leads (validação) ou pesquisa (treino)
        sales_df: DataFrame de vendas
        mode: 'validation' ou 'training' (determina colunas de retorno)
        use_temporal_validation: Se True, venda deve ser >= data_captura

    Returns:
        DataFrame com colunas adicionadas conforme mode:
        - mode='validation': converted, sale_value, sale_date, sale_origin, match_method
        - mode='training': target (0/1)
    """
    mode_str = "VALIDAÇÃO" if mode == 'validation' else "TREINO"
    logger.info(f" Matching unificado ({mode_str}) - EMAIL + TELEFONE + ÚLTIMOS 6 DÍGITOS")
    logger.info(f"   Leads: {len(leads_df):,}")
    logger.info(f"   Vendas: {len(sales_df):,}")

    # Criar cópias
    leads = leads_df.copy()
    sales = sales_df.copy()

    # Auto-detectar nomes de colunas
    email_col_leads = _get_column_name(leads, ['email', 'E-mail'])
    telefone_col_leads = _get_column_name(leads, ['telefone', 'Telefone'])
    email_col_sales = _get_column_name(sales, ['email'])
    telefone_col_sales = _get_column_name(sales, ['telefone'])

    # Inicializar colunas de resultado conforme mode
    if mode == 'validation':
        leads['converted'] = False
        leads['sale_value'] = 0.0
        leads['sale_date'] = pd.NaT
        leads['sale_origin'] = None
        leads['match_method'] = None
    elif mode == 'training':
        leads['target'] = 0
    else:
        raise ValueError(f"Mode inválido: {mode}. Use 'validation' ou 'training'")

    # Contadores de matching
    matched_by_email = 0
    matched_by_phone_full = 0
    matched_by_phone_last6 = 0

    # 1. NORMALIZAR E INDEXAR VENDAS
    sales_by_email = {}
    sales_by_phone_full = {}
    sales_by_phone_last6 = {}

    for idx, sale in sales.iterrows():
        email = sale[email_col_sales]
        phone = sale[telefone_col_sales]

        # Dados da venda (apenas para mode='validation')
        if mode == 'validation':
            sale_data = {
                'sale_value': sale['sale_value'],
                'sale_date': sale['sale_date'],
                'sale_origin': sale['origem']
            }
        else:
            sale_data = {}

        # Indexar por email
        email_norm = normalizar_email(email)
        if email_norm:
            if email_norm not in sales_by_email:
                sales_by_email[email_norm] = []
            sales_by_email[email_norm].append(sale_data)

        # Indexar por telefone completo
        phone_norm = normalizar_telefone_robusto(phone)
        if phone_norm and len(phone_norm) >= 10:  # Apenas 10-11 dígitos
            if phone_norm not in sales_by_phone_full:
                sales_by_phone_full[phone_norm] = []
            sales_by_phone_full[phone_norm].append(sale_data)

        # Indexar por últimos 6 dígitos
        last6 = extrair_ultimos_6_digitos(phone)
        if last6:
            if last6 not in sales_by_phone_last6:
                sales_by_phone_last6[last6] = []
            sales_by_phone_last6[last6].append(sale_data)

    logger.info(f"   Índices criados:")
    logger.info(f"      Emails: {len(sales_by_email):,}")
    logger.info(f"      Telefones completos: {len(sales_by_phone_full):,}")
    logger.info(f"      Últimos 6 dígitos: {len(sales_by_phone_last6):,}")

    # 2. MATCHING POR PRIORIDADE
    for idx, lead in leads.iterrows():
        lead_email = lead[email_col_leads]
        lead_phone = lead[telefone_col_leads]

        # Validação temporal (apenas para mode='validation')
        lead_date = None
        if mode == 'validation' and use_temporal_validation:
            lead_date = lead.get('data_captura')
            if pd.isna(lead_date):
                continue  # Pular leads sem data de captura

        # Normalizar dados do lead
        email_norm = normalizar_email(lead_email)
        phone_norm = normalizar_telefone_robusto(lead_phone)
        phone_last6 = extrair_ultimos_6_digitos(lead_phone)

        matched = False

        # PRIORIDADE 1: Matching por EMAIL
        if email_norm and email_norm in sales_by_email:
            for sale in sales_by_email[email_norm]:
                if mode == 'validation':
                    if not use_temporal_validation or _is_valid_match(lead_date, sale['sale_date']):
                        leads.at[idx, 'converted'] = True
                        leads.at[idx, 'sale_value'] = sale['sale_value']
                        leads.at[idx, 'sale_date'] = sale['sale_date']
                        leads.at[idx, 'sale_origin'] = sale['sale_origin']
                        leads.at[idx, 'match_method'] = 'email'
                        matched_by_email += 1
                        matched = True
                        break
                else:  # training
                    leads.at[idx, 'target'] = 1
                    matched_by_email += 1
                    matched = True
                    break

        if matched:
            continue

        # PRIORIDADE 2: Matching por TELEFONE COMPLETO (10-11 dígitos)
        if phone_norm and len(phone_norm) >= 10 and phone_norm in sales_by_phone_full:
            for sale in sales_by_phone_full[phone_norm]:
                if mode == 'validation':
                    if not use_temporal_validation or _is_valid_match(lead_date, sale['sale_date']):
                        leads.at[idx, 'converted'] = True
                        leads.at[idx, 'sale_value'] = sale['sale_value']
                        leads.at[idx, 'sale_date'] = sale['sale_date']
                        leads.at[idx, 'sale_origin'] = sale['sale_origin']
                        leads.at[idx, 'match_method'] = 'telefone'
                        matched_by_phone_full += 1
                        matched = True
                        break
                else:  # training
                    leads.at[idx, 'target'] = 1
                    matched_by_phone_full += 1
                    matched = True
                    break

        if matched:
            continue

        # PRIORIDADE 3: Matching por ÚLTIMOS 6 DÍGITOS (fallback)
        if phone_last6 and phone_last6 in sales_by_phone_last6:
            for sale in sales_by_phone_last6[phone_last6]:
                if mode == 'validation':
                    if not use_temporal_validation or _is_valid_match(lead_date, sale['sale_date']):
                        leads.at[idx, 'converted'] = True
                        leads.at[idx, 'sale_value'] = sale['sale_value']
                        leads.at[idx, 'sale_date'] = sale['sale_date']
                        leads.at[idx, 'sale_origin'] = sale['sale_origin']
                        leads.at[idx, 'match_method'] = 'ultimos_6_digitos'
                        matched_by_phone_last6 += 1
                        matched = True
                        break
                else:  # training
                    leads.at[idx, 'target'] = 1
                    matched_by_phone_last6 += 1
                    matched = True
                    break

    # 3. ESTATÍSTICAS
    total_matched = matched_by_email + matched_by_phone_full + matched_by_phone_last6
    match_rate = (total_matched / len(leads) * 100) if len(leads) > 0 else 0

    logger.info(f"    Matching concluído:")
    logger.info(f"      Total de matches: {total_matched:,}")
    logger.info(f"      Taxa de matching: {match_rate:.2f}%")
    logger.info(f"      Por método:")
    logger.info(f"         Email: {matched_by_email:,} ({matched_by_email/total_matched*100:.1f}%)" if total_matched > 0 else "         Email: 0")
    logger.info(f"         Telefone completo: {matched_by_phone_full:,} ({matched_by_phone_full/total_matched*100:.1f}%)" if total_matched > 0 else "         Telefone completo: 0")
    logger.info(f"         Últimos 6 dígitos: {matched_by_phone_last6:,} ({matched_by_phone_last6/total_matched*100:.1f}%)" if total_matched > 0 else "         Últimos 6 dígitos: 0")

    # Log adicional para mode='training'
    if mode == 'training':
        total_registros = len(leads)
        total_conversoes = leads['target'].sum()
        taxa_conversao = (total_conversoes / total_registros * 100) if total_registros > 0 else 0

        logger.info(f"")
        logger.info(f"DATASET FINAL:")
        logger.info(f"  Total de registros: {total_registros:,}")
        logger.info(f"  Total de matches: {total_conversoes:,}")
        logger.info(f"  Taxa de conversão: {taxa_conversao:.2f}%")

    return leads


def _is_valid_match(lead_date: pd.Timestamp, sale_date: pd.Timestamp) -> bool:
    """
    Valida se uma venda é válida para um lead (temporal).

    Args:
        lead_date: Data de captura do lead
        sale_date: Data da venda

    Returns:
        True se é um match válido (venda >= lead)
    """
    if pd.isna(lead_date) or pd.isna(sale_date):
        return False

    return sale_date >= lead_date
