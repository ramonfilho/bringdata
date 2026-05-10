"""
backtest_data.py — Orquestra "carrega leads + vendas + match + spend" para
backtests offline e qualquer validação secundária que precise da mesma base
de dados de um lançamento.

Reusa os helpers existentes de src/validation/ para garantir paridade com
validate_ml_performance.py (mesma fonte de leads, mesmas funções de match,
mesma normalização de campanha pro spend).

Uso típico:

    from src.validation.backtest_data import load_match_spend_for_lf
    df = load_match_spend_for_lf("LF52")
    # df contém leads do período de captação, com:
    #   - colunas brutas do formulário (Source, Medium, Campaign, Term, Content,
    #     "Qual a sua idade?", "Atualmente, qual a sua faixa salarial?", etc.)
    #   - colunas normalizadas: email, telefone, data_captura
    #   - colunas de match: converted, sale_value, sale_date, sale_origin, match_method
    #   - coluna de spend imputado: spend_imputado (CPL = spend_camp / leads_camp)

A função NÃO scoreia — quem scoreia é quem chama (cada modelo tem seu pipeline).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# Caminho relativo ao pacote — robust contra qualquer cwd
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parents[1]  # V2/
LAUNCHES_PATH = PROJECT_ROOT / "configs" / "launches.yaml"
VALIDATION_CONFIG_PATH = PROJECT_ROOT / "configs" / "validation_config.yaml"


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #

def load_match_spend_for_lf(
    lf_name: str,
    *,
    output_path: Optional[Path] = None,
    tmb_paths: Optional[List[str]] = None,
    include_production_decil: bool = True,
    exclude_utm_substrings: Optional[List[str]] = None,
    cap_start_override: Optional[str] = None,
    cap_end_override: Optional[str] = None,
    sales_start_override: Optional[str] = None,
    sales_end_override: Optional[str] = None,
) -> pd.DataFrame:
    """Pipeline completo "load + match + spend" para um lançamento.

    Args:
        lf_name: Identificador do lançamento (ex: "LF52", "DEV20"). Datas vêm
            de configs/launches.yaml.
        output_path: Se fornecido, persiste o DataFrame final como parquet.
        tmb_paths: Lista de caminhos para arquivos TMB locais (.xlsx). Se None,
            TMB não é incluído. (GCS fallback intencionalmente desabilitado —
            TMB sempre via arquivo local.)
        include_production_decil: Se True, busca o decil/leadScore que produção
            atribuiu a cada lead (gravados no Railway na tabela "Lead") e
            adiciona como colunas `decil_production` / `lead_score_production`.
            Útil pra usar o modelo Champion atual como baseline sem precisar
            rescore-lo localmente. Default True.
        exclude_utm_substrings: Lista de substrings (case-insensitive) — leads
            cuja `campaign` contenha qualquer uma delas são removidos antes do
            match. Útil pra excluir, ex.: leads roteados a um Challenger
            durante A/B test ativo (`ML_MAR`).

    Returns:
        DataFrame de leads do período de captação, com colunas adicionadas:
        email, telefone, data_captura, converted, sale_value, sale_date,
        sale_origin, match_method, spend_imputado.
        Se include_production_decil: + decil_production, lead_score_production.
    """
    lf = _load_launch_dates(lf_name)
    cap_start = cap_start_override or lf["cap_start"]
    cap_end = cap_end_override or lf["cap_end"]
    sales_start = sales_start_override or lf["vendas_start"]
    sales_end = sales_end_override or lf["vendas_end"]
    overridden = any([cap_start_override, cap_end_override, sales_start_override, sales_end_override])
    if overridden:
        logger.info(
            f"[backtest_data] LF={lf_name} cap={cap_start}→{cap_end} "
            f"vendas={sales_start}→{sales_end} (OVERRIDES aplicados — "
            f"original cap={lf['cap_start']}→{lf['cap_end']}, "
            f"vendas={lf['vendas_start']}→{lf['vendas_end']})"
        )
    else:
        logger.info(
            f"[backtest_data] LF={lf_name} cap={cap_start}→{cap_end} "
            f"vendas={sales_start}→{sales_end}"
        )

    leads_df = _load_leads(cap_start, cap_end)
    sales_df = _load_sales(
        sales_start, sales_end,
        cap_start=cap_start, cap_end=cap_end,
        tmb_paths=tmb_paths,
    )

    leads_df = _normalize_lead_columns(leads_df)

    if exclude_utm_substrings:
        n_before = len(leads_df)
        camp_str = leads_df["campaign"].astype(str).str.lower()
        mask = pd.Series([False] * len(leads_df), index=leads_df.index)
        for s in exclude_utm_substrings:
            mask = mask | camp_str.str.contains(s.lower(), na=False)
        leads_df = leads_df[~mask].copy()
        logger.info(
            f"[backtest_data] excluídos {n_before - len(leads_df)} leads por UTM "
            f"({exclude_utm_substrings}) — restaram {len(leads_df)}"
        )

    # Filtros de período (defensivo — Railway/Sheets podem retornar fora)
    from src.validation.matching import (
        match_leads_to_sales,
        filter_by_period,
        filter_conversions_by_capture_period,
        deduplicate_conversions,
    )
    leads_df = filter_by_period(leads_df, cap_start, cap_end, "data_captura")
    sales_df = filter_by_period(sales_df, sales_start, sales_end, "sale_date")
    logger.info(f"[backtest_data] após filtro: {len(leads_df)} leads, {len(sales_df)} vendas")

    matched_df = match_leads_to_sales(leads_df, sales_df, use_temporal_validation=False)
    matched_df = filter_conversions_by_capture_period(
        matched_df, cap_start, cap_end
    )
    matched_df = deduplicate_conversions(matched_df)
    n_conv = matched_df["converted"].sum()
    logger.info(f"[backtest_data] match: {n_conv} conversões em {len(matched_df)} leads")

    matched_df = _attach_imputed_spend(matched_df, cap_start, cap_end)

    if include_production_decil:
        matched_df = _attach_production_decil(matched_df, cap_start, cap_end)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        matched_df.to_parquet(output_path, index=False)
        logger.info(f"[backtest_data] persistido em {output_path}")

    return matched_df


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #

def _load_launch_dates(lf_name: str) -> Dict[str, str]:
    if not LAUNCHES_PATH.exists():
        raise FileNotFoundError(f"{LAUNCHES_PATH} não encontrado")
    with open(LAUNCHES_PATH) as f:
        launches = yaml.safe_load(f)
    if lf_name not in launches:
        raise ValueError(f"Lançamento {lf_name} não está em {LAUNCHES_PATH}")
    return launches[lf_name]


def _load_leads(cap_start: str, cap_end: str) -> pd.DataFrame:
    """Railway primário (única fonte com dados pós-2026-03-27). Sheets como fallback.

    Sheets é chamado com training_mode=True para preservar nomes originais do
    formulário (PT-BR canônico, igual ao train_pipeline) — sem isso, leads pré-Railway
    (LF≤41 / nov-dez 2025) chegam em schema lowercase incompatível com o pipeline
    de scoring.
    """
    from src.validation.data_loader import LeadDataLoader, SalesDataLoader

    sales_loader = SalesDataLoader()
    leads_df = sales_loader.load_railway_leads(start_date=cap_start, end_date=cap_end)
    if len(leads_df) > 0:
        logger.info(f"[backtest_data] {len(leads_df)} leads do Railway")
        return leads_df

    logger.warning("[backtest_data] Railway vazio — fallback Sheets (training_mode=True)")
    leads_df = LeadDataLoader().load_leads_from_sheets(
        start_date=cap_start, end_date=cap_end, training_mode=True
    )
    logger.info(f"[backtest_data] {len(leads_df)} leads do Sheets (fallback)")
    return leads_df


def _load_sales(
    sales_start: str,
    sales_end: str,
    *,
    cap_start: Optional[str] = None,
    cap_end: Optional[str] = None,
    tmb_paths: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Guru API + Hotmart API + Asaas API (+ TMB local se tmb_paths fornecido).

    Asaas exige cap_start/cap_end — usados como filtro `customer_created`
    pra excluir clientes que entraram em outros LFs mas pagaram nesta janela.
    """
    from src.validation.data_loader import SalesDataLoader

    sales_loader = SalesDataLoader()

    guru_df = sales_loader.load_guru_sales_from_api(
        start_date=sales_start, end_date=sales_end, save_excel=False
    )
    logger.info(f"[backtest_data] Guru: {0 if guru_df is None else len(guru_df)} vendas")

    try:
        hotmart_df = sales_loader.load_hotmart_sales_from_api(
            start_date=sales_start, end_date=sales_end
        )
        logger.info(
            f"[backtest_data] Hotmart: {0 if hotmart_df is None else len(hotmart_df)} vendas"
        )
    except Exception as e:
        logger.warning(f"[backtest_data] Hotmart API falhou ({type(e).__name__}: {e})")
        hotmart_df = None

    asaas_df = None
    try:
        # product_value vem do business_config (DevClub default).
        # customer_created_from='2020-01-01' desliga o filtro automático do
        # asaas_sales_extractor (que usa start_date como default e exclui
        # clientes mais antigos). Pra backtest queremos TODAS as vendas Asaas
        # no período — match_leads_to_sales depois já restringe a leads do
        # nosso pool. Sem isso, perdíamos ~9 vendas/janela de clientes Asaas
        # que se cadastraram antes do sales_start mas pagaram dentro.
        from api.business_config import PRODUCT_VALUE
        asaas_df = sales_loader.load_asaas_sales(
            start_date=sales_start, end_date=sales_end,
            product_value=PRODUCT_VALUE,
            customer_created_from='2020-01-01',
        )
        logger.info(
            f"[backtest_data] Asaas: {0 if asaas_df is None else len(asaas_df)} vendas"
        )
    except Exception as e:
        logger.warning(f"[backtest_data] Asaas API falhou ({type(e).__name__}: {e})")
        asaas_df = None

    tmb_df = None
    if tmb_paths:
        # Validar que os arquivos existem antes de chamar (load_tmb_sales pode
        # cair em GCS fallback se não, e queremos exclusivamente local).
        existing = [p for p in tmb_paths if Path(p).exists()]
        if not existing:
            logger.warning(f"[backtest_data] tmb_paths fornecidos mas nenhum existe: {tmb_paths}")
        else:
            tmb_df = sales_loader.load_tmb_sales(
                tmb_paths=existing, report_type="fechamento"
            )
            logger.info(
                f"[backtest_data] TMB local: {0 if tmb_df is None else len(tmb_df)} vendas "
                f"(arquivos: {[Path(p).name for p in existing]})"
            )

    sales_df = sales_loader.combine_sales(
        guru_df=guru_df,
        hotmart_df=hotmart_df,
        tmb_df=tmb_df,
        asaas_df=asaas_df,
        # tmb_paths=[] explicitamente para impedir GCS fallback no combine_sales
        tmb_paths=[],
    )
    if sales_df is None or len(sales_df) == 0:
        raise RuntimeError("Nenhuma venda carregada — abortando")
    logger.info(f"[backtest_data] vendas combinadas: {len(sales_df)}")
    return sales_df


# --------------------------------------------------------------------------- #
# Normalização
# --------------------------------------------------------------------------- #

_LEAD_COLUMN_ALIASES: Dict[str, List[str]] = {
    "email": ["email", "E-mail", "e-mail", "E-Mail", "Email"],
    "telefone": ["telefone", "Telefone", "phone", "Phone"],
    "data_captura": ["data_captura", "Data", "data", "DATA", "createdAt", "Data Cadastro"],
    "campaign": ["campaign", "Campaign", "utm_campaign"],
}


def _normalize_lead_columns(leads_df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona colunas canônicas (email/telefone/data_captura/campaign) se ausentes,
    copiando de aliases conhecidos do schema Railway/Sheets. Mantém colunas
    originais — a pipeline de scoring precisa delas pra preprocessar."""
    df = leads_df.copy()
    for canonical, aliases in _LEAD_COLUMN_ALIASES.items():
        if canonical in df.columns:
            continue
        for alias in aliases:
            if alias in df.columns:
                df[canonical] = df[alias]
                break

    if "email" not in df.columns:
        raise RuntimeError(
            f"Coluna email não encontrada. Procurei {_LEAD_COLUMN_ALIASES['email']}; "
            f"achei: {[c for c in df.columns if 'mail' in c.lower()]}"
        )

    df["email"] = df["email"].astype(str).str.lower().str.strip()
    if "telefone" in df.columns:
        df["telefone"] = (
            df["telefone"].astype(str).str.replace(r"\D", "", regex=True)
        )
        df.loc[df["telefone"].isin(["", "nan", "<NA>", "None"]), "telefone"] = pd.NA
    if "data_captura" in df.columns:
        df["data_captura"] = pd.to_datetime(df["data_captura"], errors="coerce")
    return df


# --------------------------------------------------------------------------- #
# Spend imputado
# --------------------------------------------------------------------------- #

def _attach_imputed_spend(
    matched_df: pd.DataFrame, cap_start: str, cap_end: str
) -> pd.DataFrame:
    """Calcula spend por campanha via Meta API e imputa CPL = spend/n_leads
    a cada lead. Casa nomes via _normalize_campaign_name (mesma normalização
    que CampaignMetricsCalculator usa). Falha graciosamente — deixa NaN se
    Meta API indisponível ou nomes não casarem."""
    df = matched_df.copy()
    df["spend_imputado"] = pd.NA

    if "campaign" not in df.columns:
        logger.warning("[backtest_data] coluna 'campaign' ausente — spend NaN")
        return df

    account_ids = _read_meta_account_ids()
    if not account_ids:
        logger.warning("[backtest_data] meta_account_ids vazio — spend NaN")
        return df

    meta_token = os.environ.get("META_ACCESS_TOKEN")
    if not meta_token:
        logger.warning("[backtest_data] META_ACCESS_TOKEN ausente — spend NaN")
        return df

    try:
        from api.meta_integration import MetaAdsIntegration
    except Exception as e:
        logger.warning(f"[backtest_data] import MetaAdsIntegration falhou: {e}")
        return df

    try:
        meta = MetaAdsIntegration(access_token=meta_token)
    except Exception as e:
        logger.warning(f"[backtest_data] MetaAdsIntegration init falhou: {e}")
        return df

    # until é exclusivo na API — somar 1 dia
    until_inclusive = (
        datetime.strptime(cap_end, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    # Meta API entrega campaign_id em campo separado; lead.campaign tem o id
    # concatenado ao final do nome UTM. Casamos pelo id (chave estável).
    spend_by_campaign: Dict[str, float] = {}
    for acc in account_ids:
        try:
            insights = meta.get_insights(
                account_id=acc,
                level="campaign",
                since_date=cap_start,
                until_date=until_inclusive,
                fields=["campaign_id", "campaign_name", "spend"],
            )
        except Exception as e:
            logger.warning(f"[backtest_data] get_insights({acc}) falhou: {e}")
            continue
        for row in insights:
            cid = row.get("campaign_id")
            try:
                spend = float(row.get("spend", 0) or 0)
            except (TypeError, ValueError):
                spend = 0.0
            if cid:
                spend_by_campaign[str(cid)] = spend_by_campaign.get(str(cid), 0.0) + spend
    logger.info(f"[backtest_data] spend coletado: {len(spend_by_campaign)} campanhas")

    if not spend_by_campaign:
        return df

    # CPL por campanha (chave = campaign_id extraído do final do UTM do lead)
    df["_camp_norm"] = df["campaign"].apply(_extract_campaign_id)
    leads_per_camp = df.groupby("_camp_norm").size().to_dict()
    cpl_per_camp = {
        k: spend_by_campaign[k] / leads_per_camp[k]
        for k in spend_by_campaign
        if leads_per_camp.get(k, 0) > 0
    }
    df["spend_imputado"] = df["_camp_norm"].map(cpl_per_camp)
    df = df.drop(columns=["_camp_norm"])

    n_attributed = df["spend_imputado"].notna().sum()
    logger.info(
        f"[backtest_data] spend imputado: {n_attributed}/{len(df)} leads "
        f"({100 * n_attributed / max(len(df), 1):.1f}%)"
    )
    return df


def _attach_production_decil(
    matched_df: pd.DataFrame, cap_start: str, cap_end: str
) -> pd.DataFrame:
    """Busca decil + leadScore que produção atribuiu, gravados na tabela "Lead"
    do Railway, e anexa ao matched_df como `decil_production` e
    `lead_score_production`. Match por email lowercased.

    Útil pra usar o modelo Champion ativo (que scorou os leads em runtime) como
    baseline em backtests, sem precisar rescore. Se Railway indisponível, deixa
    NaN e segue.

    Normaliza decil pra D01..D10 (formato canônico) caso esteja como D1..D9.
    """
    df = matched_df.copy()
    df["decil_production"] = pd.NA
    df["lead_score_production"] = pd.NA

    try:
        import pg8000.native
    except ImportError:
        logger.warning("[backtest_data] pg8000 não instalado — decil_production NaN")
        return df

    pwd = os.environ.get("RAILWAY_DB_PASSWORD")
    if not pwd:
        logger.warning("[backtest_data] RAILWAY_DB_PASSWORD ausente — decil_production NaN")
        return df

    end_excl = (
        datetime.strptime(cap_end, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    try:
        conn = pg8000.native.Connection(
            host=os.environ.get("RAILWAY_DB_HOST", "shortline.proxy.rlwy.net"),
            port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
            database=os.environ.get("RAILWAY_DB_NAME", "railway"),
            user=os.environ.get("RAILWAY_DB_USER", "postgres"),
            password=pwd,
        )
        rows = conn.run(
            """
            SELECT email, decil, "leadScore"
            FROM "Lead"
            WHERE "createdAt" >= :start_date
              AND "createdAt" <  :end_excl
              AND email IS NOT NULL
            """,
            start_date=cap_start,
            end_excl=end_excl,
        )
        conn.close()
    except Exception as e:
        logger.warning(f"[backtest_data] Railway query falhou: {e}")
        return df

    if not rows:
        logger.warning("[backtest_data] decil_production: nenhum lead retornado do Railway")
        return df

    prod = pd.DataFrame(rows, columns=["email", "decil_prod_raw", "lead_score_prod_raw"])
    prod["email"] = prod["email"].astype(str).str.lower().str.strip()

    def _normalize_decil(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        if not s:
            return None
        try:
            num = int(s.lstrip("D"))
            return f"D{num:02d}"
        except (ValueError, AttributeError):
            return s

    prod["decil_production"] = prod["decil_prod_raw"].apply(_normalize_decil)
    prod["lead_score_production"] = pd.to_numeric(
        prod["lead_score_prod_raw"], errors="coerce"
    )
    # Dedup por email — fica com o último (mais recente) caso de duplicatas
    prod = prod.drop_duplicates("email", keep="last")[
        ["email", "decil_production", "lead_score_production"]
    ]

    df = df.drop(columns=["decil_production", "lead_score_production"])
    df = df.merge(prod, on="email", how="left")

    n = df["decil_production"].notna().sum()
    logger.info(
        f"[backtest_data] decil_production: {n}/{len(df)} leads enriquecidos "
        f"({100 * n / max(len(df), 1):.1f}%)"
    )
    return df


def _read_meta_account_ids() -> List[str]:
    if not VALIDATION_CONFIG_PATH.exists():
        return []
    with open(VALIDATION_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("meta_account_ids", []) or []


def _extract_campaign_id(name: object) -> Optional[str]:
    """Extrai o campaign_id (string numérica >=12 dígitos) do final do UTM.

    Padrão observado nos leads: `DEVLF | ... | <campaign_id>` (id colado ao
    último token, separado por `|`). Retorna o ID como string ou None.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    import re
    m = re.search(r"(\d{12,})\s*$", str(name).strip())
    return m.group(1) if m else None
