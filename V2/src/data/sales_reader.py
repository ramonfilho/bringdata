"""Leitura de vendas consolidadas (analytics.sales) → DataFrame no shape dos
loaders (Fase 2, lado de leitura).

Adaptador: traduz a tabela `analytics.sales` para o MESMO formato que os
loaders do `SalesDataLoader` já produzem (colunas email/telefone/nome/
sale_value/sale_date/origem/status/product_name). Assim é drop-in para o
`df_vendas` do pipeline — `core/matching.match_leads` e os filtros downstream
não mudam.

NÃO transforma nada (nem dedup cross-gateway, nem sale_value_realizado): isso
continua em src/core / no consumidor. Aqui só troca a FONTE (banco em vez de
puxar arquivos + N APIs por execução).

Default lê todos os gateways (é o enriquecimento). `gateways=['guru','tmb']`
reproduz o universo de vendas do treino atual — útil pro parity audit.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

import pandas as pd

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

# tabela.coluna  ->  nome no shape dos loaders (df_vendas do pipeline)
_COL_MAP = {
    "email": "email",
    "phone": "telefone",
    "nome": "nome",
    "sale_value": "sale_value",
    "sale_date": "sale_date",
    "gateway": "origem",
    "status": "status",
    "produto": "product_name",
}


def read_sales(
    start: Optional[str] = None,
    end: Optional[str] = None,
    *,
    client_id: str = "devclub",
    gateways: Optional[Sequence[str]] = None,
    conn=None,
) -> pd.DataFrame:
    """Lê vendas de analytics.sales no shape dos loaders.

    Args:
        start, end: janela em `sale_date` (YYYY-MM-DD), inclusive. None = sem corte.
        client_id:  cliente (multi-cliente desde o dia 1).
        gateways:   None = todos (enriquecimento). Lista = só esses (ex.: ['guru','tmb']
                    reproduz o treino atual, pro parity audit).

    Returns:
        DataFrame com colunas email, telefone, nome, sale_value, sale_date,
        origem, status, product_name. Vazio se não houver vendas.
    """
    where = ["client_id = :client_id"]
    params = {"client_id": client_id}
    if start:
        where.append("sale_date >= CAST(:start AS timestamptz)")
        params["start"] = start
    if end:
        where.append("sale_date < CAST(:end AS timestamptz) + interval '1 day'")
        params["end"] = end
    if gateways:
        # placeholders nomeados :gw0, :gw1, ... (pg8000.native não aceia lista direta)
        ph = []
        for i, gw in enumerate(gateways):
            key = f"gw{i}"
            params[key] = gw
            ph.append(f":{key}")
        where.append(f"gateway IN ({', '.join(ph)})")

    select_cols = ", ".join(_COL_MAP.keys())
    sql = f"SELECT {select_cols} FROM sales WHERE {' AND '.join(where)}"

    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        rows = conn.run(sql, **params)
    finally:
        if own:
            conn.close()

    cols = list(_COL_MAP.values())
    if not rows:
        logger.info("[sales_reader] 0 vendas (client=%s, gateways=%s)", client_id, gateways or "todos")
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows, columns=cols)
    df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
    logger.info(
        "[sales_reader] %d vendas (client=%s, gateways=%s, %s→%s)",
        len(df), client_id, gateways or "todos", start or "-", end or "-",
    )
    return df
