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


# ---------------------------------------------------------------------------
# [T2-1] Filtragem, dedup e consolidação — implementações portadas de
# src/data_processing/ingestion.py para seguir o princípio de core/ como
# Single Source of Truth. Assinatura config-driven (IngestionConfig).
# ---------------------------------------------------------------------------

_DEFAULT_TERMOS_MANTER = ["Pesquisa", "Vendas", "tmb", "Sheet", "LEADS"]
_DEFAULT_TERMOS_REMOVER = ["Pontuação", "Lead Score", "DEBUG_LOG",
                            "Tabela Dinâmica 1", "Detalhe1", "Alunos", "Guru", "TMB"]
_DEFAULT_PESQUISA_KEYWORDS = ["pesquisa", "leads"]
_DEFAULT_VENDAS_KEYWORDS = ["vendas", "sheet1"]


def filter_sheets(files_data: Dict[str, Dict[str, pd.DataFrame]],
                  config: IngestionConfig
                  ) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], List[Dict]]:
    """
    Filtra abas de múltiplos arquivos Excel baseado em critérios do IngestionConfig.

    Critérios (em ordem):
      1. Aba tem pelo menos uma linha
      2. Aba NÃO contém nenhum termo de `config.filter_termos_remover`
      3. Aba tem >10 colunas preenchidas (exceto fontes [API], que bypass)
      4. Aba contém pelo menos um termo de `config.filter_termos_manter` OU
         tem >= `config.filter_min_linhas` linhas OU é fonte [API]
      5. Heurísticas específicas DevClub: aba TMB/Guru em arquivo LF (exceto LF06)
         é removida; arquivos locais 'guru' são removidos; aba LEADS em arquivo
         com Pesquisa é redundante

    Args:
        files_data: Dict {filename: {sheet_name: DataFrame}}
        config:    IngestionConfig do cliente

    Returns:
        (arquivos_filtrados, relatório com status por aba)
    """
    termos_manter  = config.filter_termos_manter  or _DEFAULT_TERMOS_MANTER
    termos_remover = config.filter_termos_remover or _DEFAULT_TERMOS_REMOVER
    min_linhas     = config.filter_min_linhas or 230

    if not config.filter_termos_manter:
        logger.warning(f"  filter_sheets: config.filter_termos_manter None — usando defaults {_DEFAULT_TERMOS_MANTER}")

    logger.debug("  Filtrando abas por critérios...")
    arquivos_filtrados: Dict[str, Dict[str, pd.DataFrame]] = {}
    relatorio: List[Dict] = []

    for filename, sheets in files_data.items():
        abas_filtradas: Dict[str, pd.DataFrame] = {}
        arquivo_tem_pesquisa = any('pesquisa' in s.lower() for s in sheets.keys())

        for sheet_name, df in sheets.items():
            linhas_original = len(df)
            nome_lower = sheet_name.lower()

            deve_remover = any(t.lower() in nome_lower for t in termos_remover)
            tem_permitido = any(t.lower() in nome_lower for t in termos_manter)
            tem_linhas = linhas_original >= min_linhas
            nao_vazia = linhas_original > 0 and not df.empty

            # Heurísticas DevClub (documentadas no notebook original)
            eh_lf_com_vendas = (
                'LF' in filename
                and any(vt in nome_lower for vt in ['tmb', 'guru'])
                and 'LF06' not in filename
            )
            eh_guru_local = 'guru' in filename.lower() and '[API]' not in filename
            eh_leads_redundante = 'leads' in nome_lower and arquivo_tem_pesquisa
            colunas_preenchidas = int(df.notna().any().sum())
            tem_colunas = colunas_preenchidas > 10
            eh_api_data = '[API]' in filename or '[Railway]' in filename

            manter = (
                nao_vazia
                and not deve_remover
                and not eh_lf_com_vendas
                and not eh_guru_local
                and not eh_leads_redundante
                and (tem_colunas or eh_api_data)
                and (tem_permitido or tem_linhas or eh_api_data)
            )

            relatorio.append({
                'arquivo': filename,
                'aba': sheet_name,
                'linhas_original': linhas_original,
                'status': 'MANTIDA' if manter else 'REMOVIDA',
            })
            if manter:
                abas_filtradas[sheet_name] = df

        if abas_filtradas:
            arquivos_filtrados[filename] = abas_filtradas

    mantidas = sum(1 for r in relatorio if r['status'] == 'MANTIDA')
    removidas = len(relatorio) - mantidas
    logger.debug(f"  filter_sheets: {mantidas} abas mantidas, {removidas} removidas")
    return arquivos_filtrados, relatorio


def remove_duplicates_per_sheet(files_data: Dict[str, Dict[str, pd.DataFrame]],
                                 config: IngestionConfig = None
                                 ) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], Dict[str, Dict[str, int]]]:
    """
    Remove duplicatas dentro de cada aba individualmente (não deduplica entre abas/arquivos).

    Args:
        files_data: Dict {filename: {sheet_name: DataFrame}}
        config:    IngestionConfig (não usado — mantido na assinatura para consistência com outras funções core/)

    Returns:
        (arquivos_limpos, estatísticas {filename: {sheet_name: n_duplicatas_removidas}})
    """
    logger.debug("  Removendo duplicatas por aba...")
    arquivos_limpos: Dict[str, Dict[str, pd.DataFrame]] = {}
    estatisticas: Dict[str, Dict[str, int]] = {}

    for filename, sheets in files_data.items():
        abas_limpas: Dict[str, pd.DataFrame] = {}
        stats_arquivo: Dict[str, int] = {}

        for sheet_name, df in sheets.items():
            antes = len(df)
            df_limpo = df.drop_duplicates(keep='first')
            depois = len(df_limpo)
            removidas = antes - depois
            abas_limpas[sheet_name] = df_limpo
            stats_arquivo[sheet_name] = removidas

        arquivos_limpos[filename] = abas_limpas
        estatisticas[filename] = stats_arquivo

    total = sum(sum(s.values()) for s in estatisticas.values())
    logger.debug(f"  remove_duplicates_per_sheet: {total:,} duplicatas removidas no total")
    return arquivos_limpos, estatisticas


def _dedup_cross_source_por_email(df: pd.DataFrame) -> pd.DataFrame:
    """
    Dedup cross-source por email — evita que o mesmo lead apareça em Sheets E Railway.

    Prioridade de origem: Railway (webhook) > API > arquivos locais. Leads sem email
    são preservados (não participam da dedup).
    """
    if len(df) == 0 or 'E-mail' not in df.columns:
        return df

    def _source_priority(arquivo: str) -> int:
        if '[Railway]' in str(arquivo):
            return 0
        if '[API]' in str(arquivo):
            return 1
        return 2

    df = df.copy()
    df['_email_norm'] = (
        df['E-mail'].astype(str).str.strip().str.lower()
        .replace({'nan': None, 'none': None, '': None})
    )
    df['_source_priority'] = df['arquivo_origem'].apply(_source_priority)

    has_email = df['_email_norm'].notna()
    df_com_email = df[has_email].sort_values('_source_priority').drop_duplicates(subset=['_email_norm'], keep='first')
    df_sem_email = df[~has_email]

    return (
        pd.concat([df_com_email, df_sem_email], ignore_index=True)
        .drop(columns=['_email_norm', '_source_priority'])
    )


def _tmb_dual_source_split(dados_vendas: List[pd.DataFrame]) -> Tuple[List[pd.DataFrame], dict]:
    """
    TMB dual-source: quando pedidos + parcelas estão presentes, usa pedidos como fonte
    primária (email + telefone) e retorna lookup de risco separado para ser aplicado
    pós-matching. Se só parcelas: comportamento legado preservado.

    Returns: (dados_vendas_finais, tmb_risk_lookup {email_norm → grau_de_risco})
    """
    parcelas_frames = [df for df in dados_vendas if '_tmb_tipo' in df.columns and len(df) > 0 and df['_tmb_tipo'].iloc[0] == 'parcelas']
    pedidos_frames  = [df for df in dados_vendas if '_tmb_tipo' in df.columns and len(df) > 0 and df['_tmb_tipo'].iloc[0] == 'pedidos']
    outros_frames   = [df for df in dados_vendas if '_tmb_tipo' not in df.columns]

    tmb_risk_lookup: dict = {}
    if parcelas_frames and pedidos_frames:
        df_parcelas_all = pd.concat(parcelas_frames, ignore_index=True)
        tmb_risk_lookup = (
            df_parcelas_all
            .dropna(subset=['Cliente Email'])
            .assign(**{'_email_norm': lambda x: x['Cliente Email'].str.strip().str.lower()})
            .groupby('_email_norm')['Grau de risco']
            .first()
            .to_dict()
        )
        logger.info(f"  TMB dual-source: {len(tmb_risk_lookup):,} emails com grau de risco (lookup para pós-matching)")
        df_pedidos_all = pd.concat(pedidos_frames, ignore_index=True)
        dados_vendas_final = [df_pedidos_all] + outros_frames
    else:
        if parcelas_frames:
            logger.debug("  TMB: usando apenas arquivo de parcelas (comportamento legado)")
        dados_vendas_final = dados_vendas

    for df in dados_vendas_final:
        if '_tmb_tipo' in df.columns:
            df.drop(columns=['_tmb_tipo'], inplace=True)

    return dados_vendas_final, tmb_risk_lookup


def consolidate_datasets(files_data: Dict[str, Dict[str, pd.DataFrame]],
                          config: IngestionConfig
                          ) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Consolida abas de múltiplos arquivos em dois DataFrames: pesquisa e vendas,
    mais um lookup de risco TMB dual-source.

    Classificação de aba por nome (case-insensitive):
      - Se nome contém termo de `config.consolidate_pesquisa_keywords` → pesquisa
      - Se nome contém termo de `config.consolidate_vendas_keywords` → vendas
      - Caso contrário: ignorada

    Pós-processamento:
      1. Adiciona colunas `arquivo_origem` e `aba_origem` em cada DataFrame
      2. Dedup cross-source por email no df_pesquisa (Railway > API > locais)
      3. TMB dual-source: separa parcelas (lookup de risco) de pedidos (matching)

    Args:
        files_data: Dict {filename: {sheet_name: DataFrame}}
        config:    IngestionConfig com consolidate_pesquisa_keywords e
                   consolidate_vendas_keywords

    Returns:
        (df_pesquisa, df_vendas, tmb_risk_lookup)
    """
    pesquisa_kws = config.consolidate_pesquisa_keywords or _DEFAULT_PESQUISA_KEYWORDS
    vendas_kws   = config.consolidate_vendas_keywords   or _DEFAULT_VENDAS_KEYWORDS

    if not config.consolidate_pesquisa_keywords:
        logger.warning(f"  consolidate_datasets: pesquisa_keywords None — usando defaults {_DEFAULT_PESQUISA_KEYWORDS}")

    dados_pesquisa: List[pd.DataFrame] = []
    dados_vendas: List[pd.DataFrame] = []

    for arquivo, abas_dict in files_data.items():
        for aba_nome, df in abas_dict.items():
            df_copia = df.copy()
            df_copia['arquivo_origem'] = arquivo
            df_copia['aba_origem'] = aba_nome
            nome_lower = aba_nome.lower()

            if any(t in nome_lower for t in pesquisa_kws):
                dados_pesquisa.append(df_copia)
            elif any(t in nome_lower for t in vendas_kws):
                dados_vendas.append(df_copia)

    df_pesquisa = pd.concat(dados_pesquisa, ignore_index=True) if dados_pesquisa else pd.DataFrame()

    # Dedup cross-source por email no df_pesquisa
    _antes = len(df_pesquisa)
    df_pesquisa = _dedup_cross_source_por_email(df_pesquisa)
    if _antes != len(df_pesquisa):
        logger.info(f"  Dedup cross-source por email: {_antes:,} → {len(df_pesquisa):,} leads ({_antes - len(df_pesquisa):,} duplicatas removidas)")

    # TMB dual-source split
    dados_vendas_final, tmb_risk_lookup = _tmb_dual_source_split(dados_vendas)
    df_vendas = pd.concat(dados_vendas_final, ignore_index=True) if dados_vendas_final else pd.DataFrame()

    logger.debug(f"  consolidate_datasets: pesquisa={len(df_pesquisa):,}, vendas={len(df_vendas):,}, tmb_lookup={len(tmb_risk_lookup):,}")
    return df_pesquisa, df_vendas, tmb_risk_lookup


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


def filtrar_risco_tmb(
    df_vendas: pd.DataFrame,
    tmb_risk_filter: str,
    tmb_risk_lookup: dict,
    risk_values: list,
    *,
    origem_col: str = 'origem',
    email_col: str = 'email',
) -> pd.DataFrame:
    """Filtro de risco TMB para quando as vendas vêm do banco (`sales_source='db'`).

    Diferente de `aplicar_filtro_status_risco`: aqui o STATUS já foi filtrado no ETL
    (guru=aprovadas, asaas=pagos, boletex=sem refund, tmb=efetivado). Este aplica SÓ o
    grau de risco TMB, mantendo intactos todos os outros gateways. O grau vem do
    `tmb_risk_lookup` (satélite `analytics.sales_tmb_risk`, servido por `tmb_risk_reader`).

    Semântica idêntica ao caminho de arquivos (paridade):
      all        → mantém todas as vendas
      none       → remove todas as TMB (mantém guru/asaas/boletex/hotmart)
      low        → TMB só com grau em risk_values[:1]  (+ risco desconhecido, igual files)
      low_medium → TMB só com grau em risk_values      (+ risco desconhecido, igual files)

    Manter TMB de risco desconhecido em low/low_medium espelha `_risk_ok` do modo files
    (`risk is None or risk in allowed`) — paridade acima de opinião.
    """
    if tmb_risk_filter == 'all' or origem_col not in df_vendas.columns:
        return df_vendas

    df = df_vendas.copy()
    is_tmb = df[origem_col].astype(str).str.lower().eq('tmb')

    if tmb_risk_filter == 'none':
        keep_tmb = pd.Series(False, index=df.index)
    elif tmb_risk_filter in ('low', 'low_medium'):
        allowed = set(risk_values[:1] if tmb_risk_filter == 'low' else risk_values)
        emails = df[email_col].astype(str).str.strip().str.lower() if email_col in df.columns else pd.Series('', index=df.index)
        grau = emails.map(lambda e: (tmb_risk_lookup or {}).get(e))
        keep_tmb = is_tmb & (grau.isna() | grau.isin(allowed))
    else:
        logger.warning(f"  filtrar_risco_tmb: filtro '{tmb_risk_filter}' inválido — mantendo todas TMB")
        return df_vendas

    keep = (~is_tmb) | keep_tmb
    before, tmb_before = len(df), int(is_tmb.sum())
    df = df[keep].copy()
    tmb_after = int((keep & is_tmb).sum())
    logger.info(f"  [db] filtro risco TMB '{tmb_risk_filter}': TMB {tmb_after:,}/{tmb_before:,} mantidas; "
                f"total {len(df):,} (de {before:,})")
    return df
