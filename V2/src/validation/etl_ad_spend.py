"""ETL de gasto de anúncio → analytics.ad_spend (campanha×dia, Meta + Google).

REUSA os loaders que já existem (não escreve API nova):
  - Meta:   MetaAPIClient.get_daily_adset_metrics (mesma chamada diária que o
            cost_attribution usa p/ o cpl_adset) → agrega adset→campanha×dia.
  - Google: GoogleAdsReportingClient.get_campaign_metrics por dia (a chamada é
            agregada na janela, então rodo dia-a-dia p/ ter grão diário).

Materializa via ad_spend_store (upsert DO UPDATE — Meta restata o passado).
O relatório LÊ da tabela; NÃO bate API viva. Cada plataforma é isolada em
try/except: uma fora não derruba a outra.

Uso:
    python -m src.validation.etl_ad_spend --start 2026-06-01 --end 2026-06-30
    python -m src.validation.etl_ad_spend --start ... --end ... --platforms meta
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_V2_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_V2_ROOT))
_ENV = _V2_ROOT / ".env"
if _ENV.exists():
    for _line in _ENV.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import pandas as pd

from src.validation.ad_spend_store import upsert_ad_spend

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def load_meta_spend(start: str, end: str, account_id=None) -> pd.DataFrame:
    """Gasto Meta por campanha×dia (agrega o diário por adset do MetaAPIClient)."""
    from src.validation.meta_api_client import MetaAPIClient

    daily = MetaAPIClient(account_id=account_id).get_daily_adset_metrics(start, end)
    if daily is None or daily.empty:
        return pd.DataFrame()
    df = daily.copy()
    date_col = "date" if "date" in df.columns else ("date_start" if "date_start" in df.columns else None)
    name_col = "campaign_name" if "campaign_name" in df.columns else None
    spend_col = "spend_dia" if "spend_dia" in df.columns else "spend"
    leads_col = "leads_dia" if "leads_dia" in df.columns else "leads"
    imp_col = "impressions_dia" if "impressions_dia" in df.columns else "impressions"
    if not date_col:
        logger.warning("[meta] sem coluna de data no retorno diário — pulando")
        return pd.DataFrame()
    agg = {spend_col: "sum"}
    if leads_col in df.columns:
        agg[leads_col] = "sum"
    if imp_col in df.columns:
        agg[imp_col] = "sum"
    keys = ["campaign_id", date_col] + ([name_col] if name_col else [])
    g = df.groupby(keys, dropna=False).agg(agg).reset_index()
    out = pd.DataFrame({
        "platform": "meta",
        "account_id": account_id,
        "campaign_id": g["campaign_id"].astype(str),
        "campaign_name": g[name_col] if name_col else g["campaign_id"].astype(str),
        "spend_date": g[date_col],
        "spend": g[spend_col],
        "leads": g[leads_col] if leads_col in g.columns else None,
        "impressions": g[imp_col] if imp_col in g.columns else None,
        "clicks": None,
    })
    return out


def load_google_spend(start: date, end: date, customer_id=None) -> pd.DataFrame:
    """Gasto Google por campanha×dia (a API agrega na janela → loop dia-a-dia).
    statuses=None p/ pegar campanhas hoje pausadas que gastaram no passado."""
    from src.validation.google_ads_api_client import GoogleAdsReportingClient

    cid = customer_id or os.environ.get("GOOGLE_ADS_CUSTOMER_ID")
    if not cid:
        logger.warning("[google] GOOGLE_ADS_CUSTOMER_ID ausente — pulando Google")
        return pd.DataFrame()
    client = GoogleAdsReportingClient(customer_id=cid)
    rows = []
    for d in _daterange(start, end):
        ds = d.isoformat()
        for r in client.get_campaign_metrics(ds, ds, statuses=None):
            rows.append({
                "platform": "google", "account_id": cid,
                "campaign_id": str(r.get("campaign_id")), "campaign_name": r.get("campaign_name"),
                "spend_date": d, "spend": r.get("spend"),
                "leads": r.get("conversions"), "impressions": None, "clicks": r.get("clicks"),
            })
    return pd.DataFrame(rows)


def run_ad_spend_etl(start: str, end: str, *, platforms=("meta", "google"),
                     account_id=None, customer_id=None, client_id="devclub") -> dict:
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    frames, loaded = [], {}

    if "meta" in platforms:
        try:
            df = load_meta_spend(start, end, account_id=account_id)
            loaded["meta"] = 0 if df is None else len(df)
            if df is not None and not df.empty:
                frames.append(df)
            logger.info("  meta:   %d linhas (campanha×dia)", loaded["meta"])
        except Exception as ex:  # noqa: BLE001 — plataforma isolada
            loaded["meta"] = f"ERRO: {ex}"
            logger.warning("  meta:   FALHOU: %s", ex)

    if "google" in platforms:
        try:
            df = load_google_spend(s, e, customer_id=customer_id)
            loaded["google"] = 0 if df is None else len(df)
            if df is not None and not df.empty:
                frames.append(df)
            logger.info("  google: %d linhas (campanha×dia)", loaded["google"])
        except Exception as ex:  # noqa: BLE001
            loaded["google"] = f"ERRO: {ex}"
            logger.warning("  google: FALHOU: %s", ex)

    if not frames:
        logger.warning("Nenhum gasto carregado — nada a gravar.")
        return {"loaded": loaded, "upsert": {"attempted": 0, "written": 0}}

    all_df = pd.concat(frames, ignore_index=True)
    res = upsert_ad_spend(all_df, client_id=client_id)
    logger.info("ETL gasto: %d linhas gravadas (de %d). Por plataforma: %s",
                res["written"], res["attempted"], res["by_platform"])
    return {"loaded": loaded, "upsert": res}


def main():
    p = argparse.ArgumentParser(description="ETL de gasto de anúncio → analytics.ad_spend")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--platforms", nargs="+", default=["meta", "google"], choices=["meta", "google"])
    p.add_argument("--account-id", default=None, help="Meta account_id (default: do MetaAPIClient)")
    p.add_argument("--customer-id", default=None, help="Google Ads customer_id (default: env GOOGLE_ADS_CUSTOMER_ID)")
    p.add_argument("--client", default="devclub")
    args = p.parse_args()
    run_ad_spend_etl(args.start, args.end, platforms=tuple(args.platforms),
                     account_id=args.account_id, customer_id=args.customer_id, client_id=args.client)


if __name__ == "__main__":
    main()
