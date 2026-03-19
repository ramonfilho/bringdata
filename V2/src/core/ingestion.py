"""
core/ingestion.py — Ingestão e filtragem de dados brutos.

Consolida funções de ingestion.py e column_unification_refactored.py:
  - filter_sheets: ingestion.py
  - remove_duplicates_per_sheet: ingestion.py / preprocessing.py
  - consolidate_datasets: ingestion.py
  - filter_sales_by_product: column_unification_refactored.py:536
  - aplicar_filtro_status_risco: column_unification_refactored.py (guarded por has_tmb)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import pandas as pd

from .client_config import IngestionConfig

logger = logging.getLogger(__name__)


def filter_sheets(sheets: Dict[str, pd.DataFrame],
                  config: IngestionConfig) -> Dict[str, pd.DataFrame]:
    """
    Filtra abas do Excel mantendo apenas as relevantes para treino.
    Usa config.ingestion (termos_manter, termos_remover, min_survey_columns).
    """
    raise NotImplementedError


def remove_duplicates_per_sheet(sheets: Dict[str, pd.DataFrame],
                                 config: IngestionConfig) -> Dict[str, pd.DataFrame]:
    """Remove duplicatas dentro de cada aba individualmente."""
    raise NotImplementedError


def consolidate_datasets(sheets: Dict[str, pd.DataFrame],
                          config: IngestionConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Consolida abas em dois DataFrames: pesquisa e vendas.
    Retorna (df_pesquisa, df_vendas).
    """
    raise NotImplementedError


def filter_sales_by_product(df_vendas: pd.DataFrame,
                              config: IngestionConfig) -> pd.DataFrame:
    """
    Filtra vendas pelo produto do cliente.

    Usa config.product_filter_keyword (#24) — ex: 'devclub'.
    Se a coluna 'produto' não existir ou keyword for None, retorna sem filtrar.

    Args:
        df_vendas: DataFrame de vendas com coluna 'produto'.
        config:    IngestionConfig carregado de configs/clients/{client}.yaml.

    Returns:
        DataFrame de vendas filtrado.
    """
    keyword = config.product_filter_keyword
    if not keyword:
        logger.debug("  filter_sales_by_product: product_filter_keyword não configurado — sem filtro")
        return df_vendas

    df = df_vendas.copy()
    if 'produto' not in df.columns:
        logger.warning("  Coluna 'produto' não encontrada — filtro de produto não aplicado")
        return df

    vendas_antes = len(df)
    mask = df['produto'].fillna('').str.lower().str.contains(keyword.lower(), na=False)
    df = df[mask].copy()
    vendas_depois = len(df)
    removidas = vendas_antes - vendas_depois

    produtos_mantidos = df['produto'].value_counts()
    logger.info(f"  Vendas antes: {vendas_antes:,}")
    logger.info(f"  Vendas removidas (outros produtos): {removidas:,}")
    logger.info(f"  Produtos únicos mantidos: {len(produtos_mantidos)}")
    logger.info(f"  TOTAL FINAL: {vendas_depois:,} vendas")
    logger.info("")
    return df


def aplicar_filtro_status_risco(
    df: pd.DataFrame,
    config: IngestionConfig,
    tmb_risk_filter: str = 'all',
    tmb_risk_lookup: dict = None,
) -> pd.DataFrame:
    """
    Filtra vendas por status (Guru) e grau de risco (TMB).

    Usa:
      config.approved_status_value (#22) — status de venda aprovada (ex: 'Aprovada')
      config.tmb_risk_column       (#23) — coluna de risco TMB (ex: 'Grau de risco')
      config.tmb_risk_values       (#62) — valores de risco ordenados por permissividade
                                          (ex: ['Baixo', 'Médio'])
                                          'low'        → tmb_risk_values[0:1]
                                          'low_medium' → tmb_risk_values (todos)

    tmb_risk_filter:
      'all'        — todos os TMB mantidos
      'none'       — nenhum TMB (apenas Guru)
      'low'        — apenas primeiro valor de tmb_risk_values
      'low_medium' — todos os valores de tmb_risk_values

    tmb_risk_lookup: dict {email_norm → grau_de_risco} — modo dual-source.

    Se a coluna 'arquivo_origem' não estiver presente, retorna sem filtrar.

    Args:
        df:               DataFrame de vendas.
        config:           IngestionConfig carregado de configs/clients/{client}.yaml.
        tmb_risk_filter:  Nível de filtro TMB (CLI pode sobrescrever o default do config).
        tmb_risk_lookup:  Lookup de risco por email (modo dual-source).

    Returns:
        DataFrame de vendas filtrado.
    """
    approved_status = config.approved_status_value or 'Aprovada'
    risk_col        = config.tmb_risk_column or 'Grau de risco'
    risk_values     = config.tmb_risk_values or []

    if 'arquivo_origem' not in df.columns:
        logger.info("  Coluna 'arquivo_origem' não encontrada — filtro não aplicado")
        return df

    df = df.copy()
    before = len(df)

    is_guru = df['arquivo_origem'].str.lower().str.contains('guru', na=False)
    is_tmb  = ~is_guru

    # Filtro Guru: apenas aprovadas
    if 'status' in df.columns:
        mask_guru = is_guru & (df['status'] == approved_status)
    else:
        mask_guru = is_guru

    # Filtro TMB: por grau de risco
    mask_tmb = pd.Series([False] * len(df), index=df.index)

    if tmb_risk_filter == 'none':
        pass  # mask_tmb permanece False

    elif tmb_risk_filter == 'all':
        mask_tmb = is_tmb

    elif risk_col in df.columns:
        # Coluna de risco presente no DataFrame
        if tmb_risk_filter == 'low':
            allowed = risk_values[:1]
        elif tmb_risk_filter == 'low_medium':
            allowed = risk_values
        else:
            logger.warning(f"  tmb_risk_filter '{tmb_risk_filter}' inválido, usando 'all'")
            allowed = None

        if allowed is not None:
            mask_tmb = is_tmb & df[risk_col].isin(allowed)
        else:
            mask_tmb = is_tmb

    elif tmb_risk_lookup and tmb_risk_filter in ('low', 'low_medium'):
        # Modo dual-source: lookup por email
        allowed_risk = (
            set(risk_values[:1]) if tmb_risk_filter == 'low'
            else set(risk_values)
        )
        if 'email' in df.columns:
            def _risk_ok(row):
                if not is_tmb[row.name]:
                    return False
                email = str(row['email']).strip().lower() if pd.notna(row['email']) else ''
                risk = tmb_risk_lookup.get(email)
                return risk is None or risk in allowed_risk
            mask_tmb = df.apply(_risk_ok, axis=1)
        else:
            logger.warning("  TMB: coluna 'email' não encontrada — mantendo todas as TMB")
            mask_tmb = is_tmb

    else:
        mask_tmb = is_tmb

    df = df[mask_guru | mask_tmb].copy()
    after = len(df)

    guru_total   = int(is_guru.sum())
    guru_mantidas = int(mask_guru.sum())
    tmb_total    = int(is_tmb.sum())
    tmb_mantidas = int(mask_tmb.sum())

    logger.info(f"  GURU: {guru_mantidas:,} aprovadas (de {guru_total:,} total)")
    if tmb_risk_filter == 'none':
        logger.info("  TMB: 0 mantidas (filtro: nenhum TMB)")
    elif tmb_risk_filter == 'all':
        logger.info(f"  TMB: {tmb_mantidas:,} mantidas (filtro: todos)")
    else:
        logger.info(f"  TMB: {tmb_mantidas:,} mantidas (filtro: {tmb_risk_filter.replace('_', ' + ')})")
    logger.info(f"  TOTAL FINAL: {after:,} vendas")
    logger.info("")
    return df
