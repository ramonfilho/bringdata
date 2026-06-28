"""ETL de vendas → analytics.sales (Fase 2 da consolidação).

Puxa cada gateway pelos loaders que já existem no `SalesDataLoader` e grava por
gateway (proveniência preservada, SEM dedup cross-gateway — dedup é leitura).

  APIs:     guru, hotmart, asaas, boletex
  Arquivo:  tmb (download manual / GCS), hotpay (legado)

Idempotente (sales_store.upsert_sales → ON CONFLICT DO NOTHING). Rodar de novo a
mesma janela não duplica.

Uso:
    python -m src.validation.etl_sales --start 2026-06-01 --end 2026-06-25
    python -m src.validation.etl_sales --start ... --end ... --gateways guru asaas
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# V2 root no path + .env (creds dos gateways e do Cloud SQL)
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

from src.validation.data_loader import SalesDataLoader
from src.validation.sales_store import upsert_sales

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_API_GATEWAYS = ("guru", "hotmart", "asaas", "boletex")
_FILE_GATEWAYS = ("tmb", "hotpay")
_DEFAULT_GATEWAYS = _API_GATEWAYS + ("tmb",)  # hotpay é legado, só se pedido


def run_sales_etl(
    start: str, end: str, *,
    gateways=None, tmb_paths=None, hotpay_paths=None,
    report_type: str = "fechamento", client_id: str = "devclub",
) -> dict:
    """Carrega os gateways pedidos e faz upsert em analytics.sales. Retorna o
    resumo do upsert + contagem carregada por gateway."""
    loader = SalesDataLoader()
    gws = list(gateways) if gateways else list(_DEFAULT_GATEWAYS)
    frames = []
    loaded = {}

    def _try(name, fn):
        if name not in gws:
            return
        try:
            df = fn()
            n = 0 if df is None else len(df)
            loaded[name] = n
            if n:
                frames.append(df)
            logger.info("  %-8s %d vendas", name + ":", n)
        except Exception as e:  # noqa: BLE001 — um gateway fora não derruba o resto
            loaded[name] = f"ERRO: {e}"
            logger.warning("  %-8s FALHOU: %s", name + ":", e)

    _try("guru", lambda: loader.load_guru_sales_from_api(start, end))
    _try("hotmart", lambda: loader.load_hotmart_sales_from_api(start, end))
    _try("asaas", lambda: loader.load_asaas_sales(start, end))
    _try("boletex", lambda: loader.load_boletex_sales_from_api(start, end))
    _try("tmb", lambda: loader.load_tmb_sales(tmb_paths, report_type=report_type))
    _try("hotpay", lambda: loader.load_hotpay_sales(hotpay_paths) if hotpay_paths else None)

    if not frames:
        logger.warning("Nenhuma venda carregada — nada a gravar.")
        return {"loaded": loaded, "upsert": {"attempted": 0, "inserted": 0, "skipped": 0, "by_gateway": {}}}

    all_df = pd.concat(frames, ignore_index=True)
    logger.info("Total carregado: %d vendas → upsert em analytics.sales", len(all_df))
    res = upsert_sales(all_df, client_id=client_id)
    logger.info(
        "ETL concluído: %d inseridas, %d já existiam (de %d). Por gateway: %s",
        res["inserted"], res["skipped"], res["attempted"], res["by_gateway"],
    )
    return {"loaded": loaded, "upsert": res}


def main():
    p = argparse.ArgumentParser(description="ETL de vendas → analytics.sales")
    p.add_argument("--start", required=True, help="Data início das vendas (YYYY-MM-DD)")
    p.add_argument("--end", required=True, help="Data fim das vendas (YYYY-MM-DD)")
    p.add_argument("--gateways", nargs="+", default=None,
                   help=f"Gateways a puxar (default: {' '.join(_DEFAULT_GATEWAYS)})")
    p.add_argument("--tmb-paths", nargs="+", default=None, help="Arquivos TMB (xlsx)")
    p.add_argument("--hotpay-paths", nargs="+", default=None, help="Arquivos HotPay (legado)")
    p.add_argument("--report-type", default="fechamento", choices=["fechamento", "pos-devolucoes"])
    p.add_argument("--client", default="devclub")
    args = p.parse_args()
    run_sales_etl(
        args.start, args.end, gateways=args.gateways,
        tmb_paths=args.tmb_paths, hotpay_paths=args.hotpay_paths,
        report_type=args.report_type, client_id=args.client,
    )


if __name__ == "__main__":
    main()
