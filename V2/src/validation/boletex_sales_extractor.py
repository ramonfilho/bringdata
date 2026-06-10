"""Extrator de vendas da API Boletex (boletos parcelados).

API Boletex tem auth via header `X-API-Key`, paginação `page`/`pageSize` (max 100),
e suporta filtro `dateStart`/`dateEnd` (formato YYYY-MM-DD).
Resposta: `{data: [Sale...], pagination: {...}}`.

Schema Sale relevante:
  customer.email/name/phone
  product.description, product.offer.name
  totals.total (valor total), totals.received (efetivamente recebido)
  createdAt (ISO 8601 UTC)
  status (PENDING_DOWN_PAYMENT, INSTALLMENTS_CREATED, ...)
"""
from __future__ import annotations

import os
from pathlib import Path
import requests
import pandas as pd
from typing import List, Dict, Any
import time
import logging

_env_file = Path(__file__).parent.parent.parent / '.env'
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from src.core.utils import normalizar_email, normalizar_telefone_robusto

logger = logging.getLogger(__name__)

BOLETEX_BASE_URL = 'https://backend-production-77b8.up.railway.app/api/v1'

# Status que NÃO contam como venda válida (vendas perdidas).
# Conservador: tudo que não está aqui é considerado venda em curso ou efetivada.
INVALID_STATUSES = {'REFUNDED', 'CHARGEBACK', 'CANCELLED', 'CANCELED'}


class BoletexSalesExtractor:
    """Pull paginado de `/sales` da API Boletex."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('BOLETEX_API_KEY')
        if not self.api_key:
            raise ValueError(
                "BOLETEX_API_KEY não encontrada. Defina no .env ou passe no construtor."
            )
        self.headers = {
            'X-API-Key': self.api_key,
            'Accept': 'application/json',
        }

    def fetch_sales(self, start_date: str, end_date: str, page_size: int = 100) -> List[Dict[str, Any]]:
        """Lista vendas no intervalo [start_date, end_date]. Filtra status inválidos.

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD (inclusive — API trata como dia inteiro)
        """
        all_sales: List[Dict[str, Any]] = []
        page = 1
        url = f"{BOLETEX_BASE_URL}/sales"

        while True:
            params = {
                'dateStart': start_date,
                'dateEnd': end_date,
                'page': page,
                'pageSize': page_size,
            }
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=30)
            except Exception as e:
                logger.error(f" Boletex: erro na requisição página {page}: {e}")
                break
            if r.status_code != 200:
                logger.error(f" Boletex HTTP {r.status_code} página {page}: {r.text[:200]}")
                break

            d = r.json()
            batch = d.get('data', [])
            all_sales.extend(batch)
            pag = d.get('pagination', {})
            total_pages = pag.get('totalPages', 1)
            if page >= total_pages or not batch:
                break
            page += 1
            time.sleep(0.1)  # rate limit é 100/min — folgado

        logger.info(f" Boletex: {len(all_sales)} vendas brutas ({start_date} → {end_date})")
        return all_sales


def fetch_boletex_sales_from_api(start_date: str, end_date: str) -> pd.DataFrame:
    """Função pública usada pelo `SalesDataLoader`. Retorna DataFrame normalizado.

    Colunas: email, nome, telefone, sale_value, sale_date, utm_campaign, origem,
    product_name, _boletex_received_value (pro cálculo de sale_value_realizado).
    """
    ex = BoletexSalesExtractor()
    raw = ex.fetch_sales(start_date, end_date)
    if not raw:
        return pd.DataFrame(columns=[
            'email', 'nome', 'telefone', 'sale_value', 'sale_date',
            'utm_campaign', 'origem', 'product_name', '_boletex_received_value',
        ])

    rows = []
    n_dropped = 0
    for s in raw:
        status = (s.get('status') or '').upper()
        if status in INVALID_STATUSES:
            n_dropped += 1
            continue
        cust = s.get('customer') or {}
        prod = s.get('product') or {}
        offer = prod.get('offer') or {}
        totals = s.get('totals') or {}

        email_raw = cust.get('email')
        if not email_raw:
            n_dropped += 1
            continue

        rows.append({
            'email': normalizar_email(email_raw),
            'nome': cust.get('name'),
            'telefone': normalizar_telefone_robusto(str(cust.get('phone'))) if cust.get('phone') else None,
            'sale_value': float(totals.get('total') or 0),
            # API entrega ISO 8601 UTC; pipeline usa tz-naive (igual TMB/Guru).
            # Converte pra UTC e dropa tzinfo pra match com filter_by_period.
            'sale_date': pd.to_datetime(s.get('createdAt'), errors='coerce', utc=True).tz_localize(None) if s.get('createdAt') else pd.NaT,
            'utm_campaign': None,  # API não expõe UTMs por venda
            'origem': 'boletex',
            'product_name': offer.get('name') or prod.get('description'),
            '_boletex_received_value': float(totals.get('received') or 0),
        })

    df = pd.DataFrame(rows)
    if n_dropped:
        logger.info(f"   Boletex: descartadas {n_dropped} (refunded/chargeback/sem email)")
    logger.info(f"   Boletex: {len(df)} vendas válidas normalizadas")
    return df
