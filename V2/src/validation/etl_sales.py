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

from datetime import date, timedelta

import pandas as pd

from src.data.analytics_connection import open_analytics_connection
from src.validation.data_loader import SalesDataLoader
from src.validation.sales_store import upsert_sales

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_API_GATEWAYS = ("guru", "hotmart", "asaas", "boletex")
_FILE_GATEWAYS = ("tmb", "hotpay")
_DEFAULT_GATEWAYS = _API_GATEWAYS + ("tmb",)  # hotpay é legado, só se pedido


def tmb_drop_dir(client_id: str = "devclub") -> Path:
    """Pasta local (gitignored, V2/data/) onde o operador larga o xlsx do tmb baixado.
    O tmb não tem API — este é o ponto de entrada manual: baixou → joga aqui → roda o ETL."""
    return _V2_ROOT / "data" / client_id / "tmb"


def _resolve_tmb_paths(tmb_paths, tmb_dir: Path):
    """Se veio --tmb-paths explícito, usa. Senão, descobre os *.xlsx na pasta de drop."""
    if tmb_paths:
        return list(tmb_paths)
    if tmb_dir and tmb_dir.is_dir():
        found = sorted(str(p) for p in tmb_dir.glob("*.xlsx"))
        if found:
            logger.info("  tmb: %d arquivo(s) descoberto(s) em %s", len(found), tmb_dir)
            return found
        logger.info("  tmb: nenhum .xlsx em %s (largue o relatório lá)", tmb_dir)
    return None


def run_sales_etl(
    start: str, end: str, *,
    gateways=None, tmb_paths=None, tmb_dir=None, hotpay_paths=None,
    report_type: str = "fechamento", client_id: str = "devclub",
) -> dict:
    """Carrega os gateways pedidos e faz upsert em analytics.sales. Retorna o
    resumo do upsert + contagem carregada por gateway. Para o tmb (manual, sem API), se
    `tmb_paths` não vier, descobre os xlsx na pasta de drop (tmb_drop_dir)."""
    loader = SalesDataLoader()
    gws = list(gateways) if gateways else list(_DEFAULT_GATEWAYS)
    frames = []
    loaded = {}

    if "tmb" in gws:
        tmb_paths = _resolve_tmb_paths(tmb_paths, Path(tmb_dir) if tmb_dir else tmb_drop_dir(client_id))

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


def sales_coverage(conn=None, client_id: str = "devclub") -> list:
    """Auditoria de cobertura por gateway: contagem + última venda + dias parados.
    data-architect: nenhuma ingestão está pronta sem provar cobertura."""
    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        rows = conn.run(
            "SELECT gateway, count(*), max(sale_date), (CURRENT_DATE - max(sale_date)::date) "
            "FROM analytics.sales WHERE client_id = :c GROUP BY gateway ORDER BY 2 DESC", c=client_id)
    finally:
        if own:
            conn.close()
    return [{"gateway": g, "n": n, "ultima_venda": str(mx), "dias_parado": ds} for g, n, mx, ds in rows]


def check_and_alert_tmb_staleness(coverage: list, *, threshold_days: int = 5, notify: bool = True) -> dict:
    """tmb é arquivo manual (54% das vendas). Se a última venda tmb atrasar além do limite, alerta no
    Slack — senão o label de treino perde silenciosamente a maioria das vendas (caso fundador)."""
    tmb = next((c for c in coverage if c["gateway"] == "tmb"), None)
    dias = tmb["dias_parado"] if tmb else None
    stale = dias is not None and dias > threshold_days
    if stale and notify:
        msg = (f"Vendas *tmb* desatualizadas: última venda em {tmb['ultima_venda']} "
               f"({dias} dias atrás, limite {threshold_days}). tmb é arquivo manual — rode "
               f"`etl_sales --start ... --end ... --gateways tmb --tmb-paths <xlsx>` com o export novo.")
        try:
            from src.validation.slack_notifier import ValidationSlackNotifier
            ValidationSlackNotifier().send_error_notification(msg)
            logger.warning("[sales] ALERTA tmb stale enviado ao Slack: %s", msg)
        except Exception as e:  # noqa: BLE001 — alerta não pode derrubar o ETL
            logger.warning("[sales] falha ao enviar alerta de staleness tmb: %s", e)
    return {"tmb": tmb, "stale": stale, "threshold_days": threshold_days}


def run_daily(*, window_days: int = 14, client_id: str = "devclub", tmb_threshold_days: int = 7) -> dict:
    """Modo do Cloud Run Job diário: puxa só os 4 gateways de API (tmb é manual) numa janela móvel,
    reporta a cobertura e alerta se o tmb estiver parado. Idempotente (upsert ON CONFLICT)."""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=window_days)).isoformat()
    logger.info("[sales daily] janela %s → %s | gateways API: %s", start, end, ", ".join(_API_GATEWAYS))
    etl = run_sales_etl(start, end, gateways=list(_API_GATEWAYS), client_id=client_id)
    cov = sales_coverage(client_id=client_id)
    logger.info("[sales daily] cobertura por gateway:")
    for c in cov:
        logger.info("  %-8s n=%-6d última=%s (%s d atrás)", c["gateway"], c["n"], c["ultima_venda"], c["dias_parado"])
    staleness = check_and_alert_tmb_staleness(cov, threshold_days=tmb_threshold_days)
    return {"etl": etl, "coverage": cov, "tmb_staleness": staleness}


def main():
    p = argparse.ArgumentParser(description="ETL de vendas → analytics.sales")
    p.add_argument("--daily", action="store_true",
                   help="modo automação: 4 gateways API em janela móvel + cobertura + alerta tmb stale")
    p.add_argument("--window-days", type=int, default=14, help="janela móvel do --daily (default 14)")
    p.add_argument("--tmb-threshold-days", type=int, default=7, help="limite de dias parado do tmb p/ alertar (default 7)")
    p.add_argument("--start", help="Data início das vendas (YYYY-MM-DD) — obrigatório fora do --daily")
    p.add_argument("--end", help="Data fim das vendas (YYYY-MM-DD) — obrigatório fora do --daily")
    p.add_argument("--gateways", nargs="+", default=None,
                   help=f"Gateways a puxar (default: {' '.join(_DEFAULT_GATEWAYS)})")
    p.add_argument("--tmb-paths", nargs="+", default=None,
                   help="Arquivos TMB (xlsx) explícitos; se omitido, descobre na pasta de drop")
    p.add_argument("--tmb-dir", default=None,
                   help="Pasta com os xlsx do TMB (default: V2/data/<client>/tmb)")
    p.add_argument("--hotpay-paths", nargs="+", default=None, help="Arquivos HotPay (legado)")
    p.add_argument("--report-type", default="fechamento", choices=["fechamento", "pos-devolucoes"])
    p.add_argument("--client", default="devclub")
    args = p.parse_args()
    if args.daily:
        run_daily(window_days=args.window_days, client_id=args.client,
                  tmb_threshold_days=args.tmb_threshold_days)
        return
    if not args.start or not args.end:
        p.error("--start e --end são obrigatórios (ou use --daily)")
    run_sales_etl(
        args.start, args.end, gateways=args.gateways,
        tmb_paths=args.tmb_paths, tmb_dir=args.tmb_dir, hotpay_paths=args.hotpay_paths,
        report_type=args.report_type, client_id=args.client,
    )


if __name__ == "__main__":
    main()
