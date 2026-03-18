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
from typing import Optional

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
