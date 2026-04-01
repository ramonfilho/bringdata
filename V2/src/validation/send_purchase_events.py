"""
Módulo para envio de eventos Purchase ao Meta CAPI após fechamento de lançamento.

Fontes de venda:
  - Guru:    sempre via API
  - Hotmart: sempre via API (mesmo período de sales_start/end)
  - TMB:     auto-detectado em V2/data/devclub/ por estrutura de colunas
  - ASAS:    a adicionar
"""

import json
import logging
import urllib.request
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

API_URL = "https://bring-data-api-12955519745.us-central1.run.app/capi/send_purchase_events"
VENDAS_DIR = "V2/data/devclub"


def _detect_tmb_files(vendas_dir: str) -> list:
    """Auto-detecta arquivos TMB na pasta de dados por estrutura de colunas."""
    tmb_files = []
    folder = Path(vendas_dir)
    if not folder.exists():
        logger.warning(f"Pasta de dados não encontrada: {vendas_dir}")
        return tmb_files

    for fpath in folder.glob("*.xls*"):
        try:
            cols = pd.read_excel(fpath, nrows=0).columns.tolist()
            if "Pedido" in cols and "Parcela" in cols and "Grau de risco" in cols:
                tmb_files.append(str(fpath))
                logger.info(f"  TMB detectado: {fpath.name}")
        except Exception:
            pass

    return tmb_files


def _build_sales_payload(df) -> list:
    """Converte DataFrame de vendas para lista de dicts esperada pelo endpoint."""
    sales = []
    for _, row in df.iterrows():
        email = row.get("email")
        if not email:
            continue

        sale_date = row.get("sale_date")
        sale_date_str = (
            sale_date.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(sale_date, "strftime")
            else str(sale_date)
        )

        item = {
            "email": email,
            "valor_venda": float(row.get("sale_value") or 0),
            "sale_date": sale_date_str,
        }

        nome = row.get("nome")
        if nome and str(nome) != "nan":
            item["nome"] = str(nome)

        telefone = row.get("telefone")
        if telefone and str(telefone) != "nan":
            item["telefone"] = str(telefone)

        sales.append(item)

    return sales


def _call_endpoint(sales: list, dry_run: bool, test_event_code: str = None) -> dict:
    payload = {"sales": sales, "dry_run": dry_run}
    if test_event_code:
        payload["test_event_code"] = test_event_code

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_purchase_events(
    sales_start_date: str,
    sales_end_date: str,
    dry_run: bool = False,
    test_event_code: str = None,
) -> dict:
    """
    Carrega vendas do período e envia eventos Purchase ao Meta CAPI.

    Args:
        sales_start_date: Início do período de vendas (YYYY-MM-DD)
        sales_end_date:   Fim do período de vendas (YYYY-MM-DD)
        dry_run:          Se True, simula sem enviar ao Meta
        test_event_code:  Código de teste do Meta (ex: TEST51740)

    Returns:
        Dict com total, enviados, anomalias, erros, dry_run
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from src.validation.data_loader import SalesDataLoader

    loader = SalesDataLoader()

    # Guru via API
    logger.info(f" Purchase events — Guru API: {sales_start_date} → {sales_end_date}")
    guru_df = loader.load_guru_sales_from_api(
        start_date=sales_start_date,
        end_date=sales_end_date,
        save_excel=False,
        include_canceled=False,
    )

    # TMB — auto-detecção na pasta fixa
    tmb_files = _detect_tmb_files(VENDAS_DIR)
    if not tmb_files:
        logger.info(" Purchase events — nenhum arquivo TMB encontrado.")

    # Combinar (Guru + TMB + Hotmart API)
    df = loader.combine_sales(
        guru_df=guru_df,
        tmb_paths=tmb_files if tmb_files else None,
        hotmart_api_start=sales_start_date,
        hotmart_api_end=sales_end_date,
        include_canceled=False,
    )

    if df.empty:
        logger.warning(" Purchase events — nenhuma venda carregada.")
        return {"total": 0, "enviados": 0, "anomalias": 0, "erros": 0, "dry_run": dry_run}

    logger.info(f" Purchase events — {len(df)} vendas combinadas")
    if "origem" in df.columns:
        for origem, count in df["origem"].value_counts().items():
            logger.info(f"    {origem}: {count} vendas")

    sales = _build_sales_payload(df)
    logger.info(f" Purchase events — {len(sales)} vendas com email válido para envio")

    if dry_run:
        logger.info(" Purchase events — DRY RUN, nenhum evento será enviado.")
    if test_event_code:
        logger.info(f" Purchase events — test_event_code={test_event_code}")

    result = _call_endpoint(sales, dry_run=dry_run, test_event_code=test_event_code)

    logger.info(
        f" Purchase events — resultado: enviados={result.get('enviados')}, "
        f"anomalias={result.get('anomalias')}, erros={result.get('erros')}"
    )

    return result
