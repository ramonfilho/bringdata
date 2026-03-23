"""
core/matching.py — Matching leads → vendas.

Consolida a estratégia email_telefone de matching_email_telefone.py,
que é a única estratégia ativa no pipeline de treino (default).

Estratégia email_telefone:
  1. Matching primário por email (100% confiável)
  2. Matching secundário por telefone (apenas leads sem match de email,
     com validação de comprimento mínimo via config.phone_digits)

Hardcodes migrados: #41–#43 → MatchingConfig.
  #41 pesquisa_email_column  → coluna de email nos leads
  #42 pesquisa_phone_column  → coluna de telefone nos leads
  #43 country_code + phone_digits
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from .client_config import MatchingConfig
from .utils import normalizar_email, normalizar_telefone_robusto

logger = logging.getLogger(__name__)

# Colunas canônicas no df_vendas após column_unification
_VENDAS_EMAIL_COL = 'email'
_VENDAS_PHONE_COL = 'telefone'


def match_leads(
    df_leads: pd.DataFrame,
    df_vendas: pd.DataFrame,
    config: MatchingConfig,
) -> pd.DataFrame:
    """
    Faz matching entre leads da pesquisa e vendas por email + telefone.

    Passo 1 — matching primário por email (100% confiável).
    Passo 2 — matching secundário por telefone apenas para leads sem match
               de email, com validação de comprimento mínimo.

    Args:
        df_leads:  DataFrame pós-cutoff (saída de criar_dataset_pos_cutoff).
        df_vendas: DataFrame de vendas normalizado (colunas 'email', 'telefone').
        config:    MatchingConfig carregado de configs/clients/{client}.yaml.

    Returns:
        df_leads com coluna 'target' adicionada (0 = não comprou, 1 = comprou).
    """
    email_col  = config.pesquisa_email_column or 'E-mail'
    phone_col  = config.pesquisa_phone_column or 'Telefone'
    country    = config.country_code or 55
    # phone_digits: comprimentos mínimos para matching (ex: [10, 11])
    # None → normalizar_telefone_robusto aceita [8,9,10,11], mas o filtro
    # de comprimento mínimo abaixo usa o menor valor de phone_digits.
    min_digits = min(config.phone_digits) if config.phone_digits else 10

    logger.debug("MATCHING: EMAIL (PRIMÁRIO) + TELEFONE (SECUNDÁRIO)")

    df = df_leads.copy()
    dv = df_vendas.copy()

    # ------------------------------------------------------------------
    # 1. Normalizar leads
    # ------------------------------------------------------------------
    emails_leads:   dict = {}   # idx → email normalizado
    telefones_leads: dict = {}  # idx → telefone normalizado

    for idx, row in df.iterrows():
        em = normalizar_email(row.get(email_col))
        if em:
            emails_leads[idx] = em

        tel = normalizar_telefone_robusto(row.get(phone_col), country_code=country)
        if tel and len(tel) >= min_digits:
            telefones_leads[idx] = tel

    # ------------------------------------------------------------------
    # 2. Normalizar vendas
    # ------------------------------------------------------------------
    emails_vendas:   set = set()
    telefones_vendas: set = set()

    for _, row in dv.iterrows():
        em = normalizar_email(row.get(_VENDAS_EMAIL_COL))
        if em:
            emails_vendas.add(em)

        tel = normalizar_telefone_robusto(row.get(_VENDAS_PHONE_COL), country_code=country)
        if tel and len(tel) >= min_digits:
            telefones_vendas.add(tel)

    logger.debug(f"  Emails leads: {len(emails_leads):,} | vendas: {len(emails_vendas):,}")
    logger.debug(f"  Telefones leads: {len(telefones_leads):,} | vendas: {len(telefones_vendas):,}")

    # ------------------------------------------------------------------
    # 3. Matching primário — email
    # ------------------------------------------------------------------
    matches_email = {idx for idx, em in emails_leads.items() if em in emails_vendas}
    logger.debug(f"  Matches por email: {len(matches_email):,}")

    # ------------------------------------------------------------------
    # 4. Matching secundário — telefone (apenas não matcheados)
    # ------------------------------------------------------------------
    nao_matcheados = set(telefones_leads) - matches_email
    matches_telefone = {idx for idx in nao_matcheados
                        if telefones_leads[idx] in telefones_vendas}
    logger.debug(f"  Matches por telefone (novos): {len(matches_telefone):,}")

    # ------------------------------------------------------------------
    # 5. Criar target
    # ------------------------------------------------------------------
    matches_total = matches_email | matches_telefone

    df['target'] = 0
    df.loc[list(matches_total), 'target'] = 1

    total = len(df)
    n_match = int(df['target'].sum())
    logger.info(f"  Total de registros: {total:,}")
    logger.info(f"  Total de matches: {n_match:,}")
    logger.info(f"  Taxa de conversão: {n_match / total * 100:.2f}%")

    logger.debug(f"  Email: {len(matches_email):,} | Telefone: {len(matches_telefone):,}")

    return df


# ---------------------------------------------------------------------------
# match_leads_to_sales_unified — para pipeline de validação
# (migrado de src/matching/matching_unified.py)
# ---------------------------------------------------------------------------

def _extrair_ultimos_6_digitos(telefone: str) -> Optional[str]:
    """Extrai os últimos 6 dígitos de um telefone (apenas dígitos)."""
    if not telefone:
        return None
    telefone_norm = ''.join(c for c in str(telefone) if c.isdigit())
    if len(telefone_norm) < 6:
        return None
    return telefone_norm[-6:]


def _get_col(df: pd.DataFrame, options: list) -> str:
    """Detecta nome de coluna automaticamente dentre opções."""
    for option in options:
        if option in df.columns:
            return option
    raise ValueError(f"Nenhuma das colunas {options} encontrada no DataFrame")


def _is_valid_match(lead_date: pd.Timestamp, sale_date: pd.Timestamp) -> bool:
    """Venda deve ser >= data de captura do lead."""
    if pd.isna(lead_date) or pd.isna(sale_date):
        return False
    return sale_date >= lead_date


def match_leads_to_sales_unified(
    leads_df: pd.DataFrame,
    sales_df: pd.DataFrame,
    mode: str = 'validation',
    use_temporal_validation: bool = False,
) -> pd.DataFrame:
    """
    Matching unificado para o pipeline de validação.

    Estratégia (prioridade):
    1. Email (100% confiável)
    2. Telefone completo normalizado (10-11 dígitos)
    3. Últimos 6 dígitos do telefone (fallback)

    Args:
        leads_df: DataFrame de leads (validação) ou pesquisa (treino)
        sales_df: DataFrame de vendas
        mode: 'validation' ou 'training' (determina colunas de retorno)
        use_temporal_validation: Se True, venda deve ser >= data_captura

    Returns:
        DataFrame com colunas adicionadas conforme mode:
        - 'validation': converted, sale_value, sale_date, sale_origin, match_method
        - 'training':   target (0/1)
    """
    mode_str = "VALIDAÇÃO" if mode == 'validation' else "TREINO"
    logger.info(f" Matching unificado ({mode_str}) - EMAIL + TELEFONE + ÚLTIMOS 6 DÍGITOS")
    logger.info(f"   Leads: {len(leads_df):,}")
    logger.info(f"   Vendas: {len(sales_df):,}")

    leads = leads_df.copy()
    sales = sales_df.copy()

    email_col_leads = _get_col(leads, ['email', 'E-mail'])
    telefone_col_leads = _get_col(leads, ['telefone', 'Telefone'])
    email_col_sales = _get_col(sales, ['email'])
    telefone_col_sales = _get_col(sales, ['telefone'])

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

    matched_by_email = 0
    matched_by_phone_full = 0
    matched_by_phone_last6 = 0

    sales_by_email: Dict[str, list] = {}
    sales_by_phone_full: Dict[str, list] = {}
    sales_by_phone_last6: Dict[str, list] = {}

    for _, sale in sales.iterrows():
        sale_data = (
            {
                'sale_value': sale['sale_value'],
                'sale_date': sale['sale_date'],
                'sale_origin': sale['origem'],
            }
            if mode == 'validation'
            else {}
        )
        em = normalizar_email(sale[email_col_sales])
        if em:
            sales_by_email.setdefault(em, []).append(sale_data)
        ph = normalizar_telefone_robusto(sale[telefone_col_sales])
        if ph and len(ph) >= 10:
            sales_by_phone_full.setdefault(ph, []).append(sale_data)
        last6 = _extrair_ultimos_6_digitos(sale[telefone_col_sales])
        if last6:
            sales_by_phone_last6.setdefault(last6, []).append(sale_data)

    logger.info(f"   Índices criados: emails={len(sales_by_email):,} "
                f"tel_full={len(sales_by_phone_full):,} "
                f"last6={len(sales_by_phone_last6):,}")

    for idx, lead in leads.iterrows():
        lead_date = (
            lead.get('data_captura')
            if mode == 'validation' and use_temporal_validation
            else None
        )
        if mode == 'validation' and use_temporal_validation and pd.isna(lead_date):
            continue

        em = normalizar_email(lead[email_col_leads])
        ph = normalizar_telefone_robusto(lead[telefone_col_leads])
        last6 = _extrair_ultimos_6_digitos(lead[telefone_col_leads])
        matched = False

        # 1. Email
        if em and em in sales_by_email:
            for sale in sales_by_email[em]:
                if mode != 'validation' or not use_temporal_validation or _is_valid_match(lead_date, sale['sale_date']):
                    if mode == 'validation':
                        leads.at[idx, 'converted'] = True
                        leads.at[idx, 'sale_value'] = sale['sale_value']
                        leads.at[idx, 'sale_date'] = sale['sale_date']
                        leads.at[idx, 'sale_origin'] = sale['sale_origin']
                        leads.at[idx, 'match_method'] = 'email'
                    else:
                        leads.at[idx, 'target'] = 1
                    matched_by_email += 1
                    matched = True
                    break
        if matched:
            continue

        # 2. Telefone completo
        if ph and len(ph) >= 10 and ph in sales_by_phone_full:
            for sale in sales_by_phone_full[ph]:
                if mode != 'validation' or not use_temporal_validation or _is_valid_match(lead_date, sale['sale_date']):
                    if mode == 'validation':
                        leads.at[idx, 'converted'] = True
                        leads.at[idx, 'sale_value'] = sale['sale_value']
                        leads.at[idx, 'sale_date'] = sale['sale_date']
                        leads.at[idx, 'sale_origin'] = sale['sale_origin']
                        leads.at[idx, 'match_method'] = 'telefone'
                    else:
                        leads.at[idx, 'target'] = 1
                    matched_by_phone_full += 1
                    matched = True
                    break
        if matched:
            continue

        # 3. Últimos 6 dígitos
        if last6 and last6 in sales_by_phone_last6:
            for sale in sales_by_phone_last6[last6]:
                if mode != 'validation' or not use_temporal_validation or _is_valid_match(lead_date, sale['sale_date']):
                    if mode == 'validation':
                        leads.at[idx, 'converted'] = True
                        leads.at[idx, 'sale_value'] = sale['sale_value']
                        leads.at[idx, 'sale_date'] = sale['sale_date']
                        leads.at[idx, 'sale_origin'] = sale['sale_origin']
                        leads.at[idx, 'match_method'] = 'ultimos_6_digitos'
                    else:
                        leads.at[idx, 'target'] = 1
                    matched_by_phone_last6 += 1
                    matched = True  # noqa: F841
                    break

    total_matched = matched_by_email + matched_by_phone_full + matched_by_phone_last6
    match_rate = (total_matched / len(leads) * 100) if len(leads) > 0 else 0
    logger.info(f"    Matching concluído: {total_matched:,} matches ({match_rate:.2f}%)")
    logger.info(f"      Email: {matched_by_email:,} | Tel: {matched_by_phone_full:,} | Last6: {matched_by_phone_last6:,}")

    if mode == 'training':
        n = int(leads['target'].sum())
        logger.info(f"  Taxa de conversão: {n / len(leads) * 100:.2f}%")

    return leads
