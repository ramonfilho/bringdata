"""
core/column_unification.py — Unificação e filtro temporal de colunas.

Consolida column_unification_refactored.py:
  - unify_survey_columns: unifica colunas duplicadas da pesquisa (#13–#15)
  - unify_sales_columns: unifica colunas de vendas (#16–#20)
  - aplicar_filtro_temporal: filtra vendas até data máxima dos leads (#25)
  - remover_colunas_utm_ausentes: remove colunas UTM das vendas (#61)

Hardcodes migrados para config:
  #13–#15  ingestion.column_unification.pesquisa_merges
  #16      ingestion.column_unification.valor_columns
  #17      ingestion.column_unification.produto_columns
  #18      ingestion.column_unification.nome_columns
  #19      ingestion.column_unification.email_columns
  #20      ingestion.column_unification.telefone_columns
  #25      ingestion.pesquisa_date_column
  #61      ingestion.vendas_utm_columns_to_remove

Constantes de detecção de data (não variam por cliente):
  DATE_KEYWORDS = ['data', 'date', 'criado', 'aprovacao', 'efetivado', 'pago']
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from .client_config import IngestionConfig

logger = logging.getLogger(__name__)

# Palavras-chave para detectar colunas de data nas vendas — constantes de domínio
DATE_KEYWORDS = ['data', 'date', 'criado', 'aprovacao', 'efetivado', 'pago']


# ---------------------------------------------------------------------------
# Pesquisa
# ---------------------------------------------------------------------------

def unify_survey_columns(df_pesquisa: pd.DataFrame,
                          config: IngestionConfig) -> pd.DataFrame:
    """
    Unifica colunas duplicadas no dataset de pesquisa.

    Usa config.column_unification.pesquisa_merges (#13–#15): lista de regras,
    cada uma com 'cols' (lista de colunas-fonte) e 'target' (nome canônico).

    Comportamento por caso:
      - target é uma das colunas-fonte: usa target como base, preenche das demais.
      - Apenas uma coluna-fonte presente (não é target): renomeia para target.
      - Múltiplas colunas-fonte presentes (nenhuma é target): fillna chain → target.

    Args:
        df_pesquisa: DataFrame de pesquisa.
        config:      IngestionConfig carregado de configs/clients/{client}.yaml.

    Returns:
        DataFrame com colunas unificadas.
    """
    cu = config.column_unification or {}
    merges: List[Dict[str, Any]] = cu.get('pesquisa_merges') or []

    df = df_pesquisa.copy()
    colunas_antes = len(df.columns)

    for rule in merges:
        cols: List[str] = rule.get('cols') or []
        target: Optional[str] = rule.get('target')
        if not cols or not target:
            continue

        present = [c for c in cols if c in df.columns]
        if not present:
            continue

        if target in present:
            # target é uma das fontes — usa como base, preenche das demais
            others = [c for c in present if c != target]
            for col in others:
                df[target] = df[target].fillna(df[col])
                df = df.drop(columns=[col])
        elif len(present) == 1:
            # Uma única fonte presente — renomeia para target
            df = df.rename(columns={present[0]: target})
        else:
            # Múltiplas fontes, nenhuma é target — chain fillna → target
            result = df[present[0]].copy()
            for col in present[1:]:
                result = result.fillna(df[col])
            df = df.drop(columns=present)
            df[target] = result

    colunas_depois = len(df.columns)
    logger.info(
        f"  Pesquisa - Colunas antes: {colunas_antes}, depois: {colunas_depois}"
        f" (unificadas: {colunas_antes - colunas_depois})"
    )
    return df


# ---------------------------------------------------------------------------
# Vendas
# ---------------------------------------------------------------------------

def unify_sales_columns(df_vendas: pd.DataFrame,
                         config: IngestionConfig) -> pd.DataFrame:
    """
    Unifica colunas duplicadas no dataset de vendas.

    Mapeia colunas de fonte variável para nomes canônicos do pipeline:
      valor_columns   (#16) → 'valor'
      produto_columns (#17) → 'produto'  (preserva 'produto' existente como base)
      nome_columns    (#18) → 'nome'
      email_columns   (#19) → 'email'    (preserva 'email' existente como fallback)
      [dinâmico]           → 'data'     (detecta por dtype/palavra-chave)
      telefone_columns(#20) → 'telefone' (preserva 'telefone' existente; NA se ausente)
      [fixo]               → UTMs        (utm_last_* + utm_* → source/medium/etc.)

    Args:
        df_vendas: DataFrame de vendas.
        config:    IngestionConfig carregado de configs/clients/{client}.yaml.

    Returns:
        DataFrame com colunas unificadas.
    """
    cu = config.column_unification or {}
    valor_columns:    List[str] = cu.get('valor_columns')    or []
    produto_columns:  List[str] = cu.get('produto_columns')  or []
    nome_columns:     List[str] = cu.get('nome_columns')     or []
    email_columns:    List[str] = cu.get('email_columns')    or []
    telefone_columns: List[str] = cu.get('telefone_columns') or []

    df = df_vendas.copy()
    colunas_antes = len(df.columns)

    logger.debug("VENDAS - Unificando colunas:")

    # ------------------------------------------------------------------
    # valor
    # ------------------------------------------------------------------
    present_valor = [c for c in valor_columns if c in df.columns]
    if present_valor:
        df['valor'] = df[present_valor[0]].copy()
        for col in present_valor[1:]:
            df['valor'] = df['valor'].fillna(df[col])
        df = df.drop(columns=present_valor)
        logger.debug(f"  {' + '.join(present_valor)} → valor")

    # ------------------------------------------------------------------
    # produto — preserva 'produto' existente com valores como base
    # ------------------------------------------------------------------
    if 'produto' in df.columns and df['produto'].notna().sum() > 0:
        for col in [c for c in produto_columns if c in df.columns]:
            df['produto'] = df['produto'].fillna(df[col])
            df = df.drop(columns=[col])
        logger.debug("  produto (preservado) + fontes (fill) → produto")
    else:
        present_prod = [c for c in produto_columns if c in df.columns]
        if present_prod:
            result = df[present_prod[0]].copy()
            for col in present_prod[1:]:
                result = result.fillna(df[col])
            df = df.drop(columns=present_prod)
            df['produto'] = result
            logger.debug(f"  {' + '.join(present_prod)} → produto")

    # ------------------------------------------------------------------
    # nome
    # ------------------------------------------------------------------
    present_nome = [c for c in nome_columns if c in df.columns]
    if present_nome:
        df['nome'] = df[present_nome[0]].copy()
        for col in present_nome[1:]:
            df['nome'] = df['nome'].fillna(df[col])
        df = df.drop(columns=present_nome)
        logger.debug(f"  {' + '.join(present_nome)} → nome")

    # ------------------------------------------------------------------
    # email — preserva 'email' existente como fallback final
    # ------------------------------------------------------------------
    _email_fallback = df['email'].copy() if 'email' in df.columns else None

    present_email = [c for c in email_columns if c in df.columns]
    if present_email:
        df['email'] = df[present_email[0]].copy()
        for col in present_email[1:]:
            df['email'] = df['email'].fillna(df[col])
        df = df.drop(columns=present_email)
        logger.debug(f"  {' + '.join(present_email)} → email")

    if _email_fallback is not None:
        col_email = df['email'] if 'email' in df.columns else pd.Series(dtype=object)
        antes = int(col_email.isna().sum())
        if 'email' not in df.columns:
            df['email'] = _email_fallback
        else:
            df['email'] = df['email'].fillna(_email_fallback)
        recuperados = antes - int(df['email'].isna().sum())
        if recuperados > 0:
            logger.debug(f"  email fallback: recuperados {recuperados:,} de coluna pré-existente")

    # ------------------------------------------------------------------
    # data — detecção dinâmica por dtype / palavra-chave
    # ------------------------------------------------------------------
    candidatas_data = []
    for col in df.columns:
        if col == 'data':
            continue
        col_lower = col.lower()
        if (pd.api.types.is_datetime64_any_dtype(df[col]) or
                any(kw in col_lower for kw in DATE_KEYWORDS)):
            candidatas_data.append((col, int(df[col].notna().sum())))
    candidatas_data.sort(key=lambda x: x[1], reverse=True)

    logger.debug("  Colunas de data candidatas (ordenadas por completude):")
    for col, nn in candidatas_data:
        pct_miss = (1 - nn / len(df)) * 100 if len(df) > 0 else 0
        logger.debug(f"    '{col}': {nn:,} preenchidos ({pct_miss:.1f}% missing)")

    if 'data' not in df.columns:
        df['data'] = pd.NaT

    for col, _ in candidatas_data:
        mask_vazio = df['data'].isna()
        if mask_vazio.sum() > 0:
            col_dt = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
            df.loc[mask_vazio, 'data'] = col_dt[mask_vazio]
            filled = int(mask_vazio.sum()) - int(df['data'].isna().sum())
            logger.debug(f"  '{col}' → data: preencheu {filled:,} vazios")
        else:
            logger.debug(f"  'data' completa, descartando '{col}' sem usar")
        df = df.drop(columns=[col])

    # ------------------------------------------------------------------
    # telefone — preserva 'telefone' existente como fallback; NA se ausente
    # ------------------------------------------------------------------
    _telefone_fallback = df['telefone'].copy() if 'telefone' in df.columns else None

    present_tel = [c for c in telefone_columns if c in df.columns]
    if present_tel:
        df['telefone'] = df[present_tel[0]].copy()
        for col in present_tel[1:]:
            df['telefone'] = df['telefone'].fillna(df[col])
        df = df.drop(columns=present_tel)
        logger.debug(f"  {' + '.join(present_tel)} → telefone")
    else:
        df['telefone'] = pd.NA
        logger.warning(
            "  (sem coluna de telefone em df_vendas) → telefone=NA"
            " — matching por telefone desabilitado"
        )

    if _telefone_fallback is not None:
        antes = int(df['telefone'].isna().sum())
        df['telefone'] = df['telefone'].fillna(_telefone_fallback)
        recuperados = antes - int(df['telefone'].isna().sum())
        if recuperados > 0:
            logger.debug(
                f"  telefone fallback: recuperados {recuperados:,} de coluna pré-existente"
            )

    # ------------------------------------------------------------------
    # UTMs — mapa fixo: utm_last_* + utm_* → source/medium/campaign/content
    # ------------------------------------------------------------------
    utms_map = [
        ('utm_last_source',   'utm_source',   'source'),
        ('utm_last_medium',   'utm_medium',   'medium'),
        ('utm_last_campaign', 'utm_campaign', 'campaign'),
        ('utm_last_content',  'utm_content',  'content'),
    ]
    for utm_last, utm_regular, utm_final in utms_map:
        if utm_last in df.columns and utm_regular in df.columns:
            df[utm_final] = df[utm_last].fillna(df[utm_regular])
            df = df.drop(columns=[utm_last, utm_regular])
            logger.debug(f"  {utm_last} + {utm_regular} → {utm_final}")

    # ------------------------------------------------------------------
    # Resumo
    # ------------------------------------------------------------------
    if 'data' in df.columns:
        logger.debug(
            f"  data: dtype={df['data'].dtype}, "
            f"non-null={df['data'].notna().sum()}/{len(df)}, "
            f"max={df['data'].max()}"
        )

    colunas_depois = len(df.columns)
    logger.info(
        f"  Vendas - Colunas antes: {colunas_antes}, depois: {colunas_depois}"
        f" (unificadas: {colunas_antes - colunas_depois})"
    )
    logger.info("")
    return df


# ---------------------------------------------------------------------------
# Filtro temporal
# ---------------------------------------------------------------------------

def aplicar_filtro_temporal(df_vendas: pd.DataFrame,
                              df_pesquisa: pd.DataFrame,
                              config: IngestionConfig) -> pd.DataFrame:
    """
    Remove vendas com data posterior à data máxima dos leads.

    Usa config.pesquisa_date_column (#25) para identificar a coluna de data
    no DataFrame de pesquisa (default: 'Data').

    Args:
        df_vendas:  DataFrame de vendas já unificado (com coluna 'data').
        df_pesquisa: DataFrame de pesquisa (para calcular data máxima).
        config:     IngestionConfig carregado de configs/clients/{client}.yaml.

    Returns:
        DataFrame de vendas sem registros com data futura.
    """
    pesquisa_date_col = config.pesquisa_date_column or 'Data'
    df = df_vendas.copy()

    if 'data' not in df.columns or pesquisa_date_col not in df_pesquisa.columns:
        logger.debug("Filtro temporal não aplicado (colunas de data não encontradas)")
        return df

    logger.debug(f"  DEBUG ANTES filtro_temporal: data max = {df['data'].max()}, "
                 f"non-null = {df['data'].notna().sum()}")

    vendas_antes = len(df)

    df_pes_temp = df_pesquisa[[pesquisa_date_col]].copy()
    df_pes_temp[pesquisa_date_col] = pd.to_datetime(
        df_pes_temp[pesquisa_date_col], errors='coerce'
    )
    data_max_leads = df_pes_temp[pesquisa_date_col].max()

    if pd.isna(data_max_leads):
        data_max_leads = pd.Timestamp.now()
        logger.info(f"  Data máxima dos leads não calculada — usando hoje: "
                    f"{data_max_leads.strftime('%Y-%m-%d')}")

    df = df[(df['data'].isna()) | (df['data'] <= data_max_leads)].copy()
    vendas_depois = len(df)
    removidas = vendas_antes - vendas_depois

    if removidas > 0:
        logger.warning("")
        logger.warning("=" * 80)
        logger.warning("ALERTA DE QUALIDADE DE DADOS: VENDAS FUTURAS DETECTADAS")
        logger.warning("=" * 80)
        logger.warning(f"Data máxima dos leads: {data_max_leads.strftime('%Y-%m-%d')}")
        logger.warning(f"Vendas com data futura (removidas): {removidas:,}")
        logger.warning(f"Vendas após validação: {vendas_depois:,}")
        logger.warning("AÇÃO RECOMENDADA: Verificar fonte de dados de vendas")
        logger.warning("=" * 80)
        logger.warning("")
    else:
        logger.debug(
            f"Validação temporal OK: nenhuma venda futura "
            f"(max lead date: {data_max_leads.strftime('%Y-%m-%d')})"
        )

    logger.debug(f"  DEBUG DEPOIS filtro_temporal: data max = {df['data'].max()}, "
                 f"non-null = {df['data'].notna().sum()}")
    return df


# ---------------------------------------------------------------------------
# Remoção de UTMs das vendas
# ---------------------------------------------------------------------------

def remover_colunas_utm_ausentes(df_vendas: pd.DataFrame,
                                  config: IngestionConfig) -> pd.DataFrame:
    """
    Remove colunas UTM do dataset de vendas.

    Usa config.vendas_utm_columns_to_remove (#61).
    Default: ['source', 'medium', 'campaign', 'content'].

    Args:
        df_vendas: DataFrame de vendas.
        config:    IngestionConfig carregado de configs/clients/{client}.yaml.

    Returns:
        DataFrame sem as colunas UTM listadas.
    """
    colunas_remover = config.vendas_utm_columns_to_remove or [
        'source', 'medium', 'campaign', 'content'
    ]

    df = df_vendas.copy()
    colunas_antes = len(df.columns)

    presentes = [c for c in colunas_remover if c in df.columns]
    if presentes:
        missing_info = {
            col: (df[col].isna().sum() / len(df)) * 100
            for col in presentes
        }
        df = df.drop(columns=presentes)
        logger.info("  Colunas removidas (UTM — alta % ausentes):")
        for col in presentes:
            logger.info(f"    - {col}: {missing_info[col]:.1f}% ausentes")
    else:
        logger.info("  Nenhuma coluna UTM encontrada para remover")

    colunas_depois = len(df.columns)
    logger.info(
        f"  Colunas antes: {colunas_antes} | depois: {colunas_depois}"
        f" (removidas: {colunas_antes - colunas_depois})"
    )
    logger.info(f"  Vendas: {len(df)} registros, {colunas_depois} colunas")
    logger.info("")
    return df
