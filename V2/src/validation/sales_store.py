"""Upsert de vendas no `analytics.sales` (Fase 2 da consolidação).

Recebe o DataFrame normalizado que os loaders de gateway do `SalesDataLoader`
já produzem (colunas: origem, email, telefone, nome, sale_value, sale_date,
product_name, status) e grava por gateway.

NÃO dedupa cross-gateway — isso é trabalho da LEITURA (o consumidor aplica a
prioridade guru>… na hora de ler). Aqui guardamos dado cru por proveniência.

Idempotente: `ON CONFLICT DO NOTHING` na chave natural (gateway+email+data+valor),
já que os loaders não expõem id de transação. Re-rodar o ETL não duplica; o
`ingested_at` fica no "primeiro visto" (preserva o timing do label).

Guarda só o valor CRU (`sale_value`). `sale_value_realizado` é derivado (fator
por gateway) e continua sendo calculado na leitura/`src/core` — banco não guarda
transform (paridade).
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)


def _f(x) -> Optional[float]:
    try:
        if x is None:
            return None
        xf = float(x)
        return None if math.isnan(xf) else xf
    except (TypeError, ValueError):
        return None


def _s(x) -> Optional[str]:
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    s = str(x).strip()
    return s or None


def _dt(x) -> Optional[str]:
    try:
        if x is None or pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(x).isoformat()
    except Exception:
        return None


# Colunas gravadas (na ordem). external_id e sale_value_realizado ficam NULL
# (loaders não expõem id; realizado é transform de leitura).
_COLS = ("client_id", "gateway", "email", "phone", "nome",
         "sale_value", "sale_date", "produto", "status")


def _row_params(r, client_id: str):
    """Normaliza uma linha do loader → dict pronto pra gravar, ou None se a linha
    não tem gateway/data/identidade (não dá pra dedup → descartada)."""
    gw = _s(r.get("origem")) or _s(r.get("gateway"))
    sale_date = _dt(r.get("sale_date"))
    email = _s(r.get("email"))
    phone = _s(r.get("telefone"))
    if not gw or not sale_date or not (email or phone):
        return None
    return {
        "client_id": client_id, "gateway": gw, "email": email, "phone": phone,
        "nome": _s(r.get("nome")), "sale_value": _f(r.get("sale_value")),
        "sale_date": sale_date, "produto": _s(r.get("product_name")),
        "status": _s(r.get("status")),
    }


def _insert_chunk(conn, chunk) -> None:
    """INSERT multi-row de um lote (1 round-trip), ON CONFLICT DO NOTHING."""
    values, params = [], {}
    for i, p in enumerate(chunk):
        cells = []
        for col in _COLS:
            key = f"{col}_{i}"
            params[key] = p[col]
            cells.append(f"CAST(:{key} AS timestamptz)" if col == "sale_date" else f":{key}")
        values.append("(" + ", ".join(cells) + ")")
    sql = (
        f"INSERT INTO sales ({', '.join(_COLS)}) VALUES " + ", ".join(values)
        + " ON CONFLICT (client_id, gateway, email, sale_date, sale_value)"
        + " WHERE external_id IS NULL DO NOTHING"
    )
    conn.run(sql, **params)


def upsert_sales(df: pd.DataFrame, client_id: str = "devclub", conn=None,
                 batch_size: int = 500) -> dict:
    """Grava as vendas do DataFrame em analytics.sales (idempotente, em lote).

    Retorna {attempted, inserted, skipped, filtered, intra_dup, by_gateway}.
      - inserted:  linhas novas gravadas.
      - skipped:   já existiam (ON CONFLICT na chave natural).
      - filtered:  descartadas ANTES de tentar (sem gateway/data/identidade).
      - intra_dup: mesma chave natural repetida no próprio lote (deduplicada
                   pra não conflitar dentro do mesmo INSERT).
    Tudo exposto de propósito — não dropa em silêncio.
    """
    empty = {"attempted": 0, "inserted": 0, "skipped": 0, "filtered": 0,
             "intra_dup": 0, "by_gateway": {}}
    if df is None or getattr(df, "empty", True):
        return empty

    rows, filtered, intra_dup, seen, by_gw = [], 0, 0, set(), {}
    for _, r in df.iterrows():
        p = _row_params(r, client_id)
        if p is None:
            filtered += 1
            continue
        key = (p["gateway"], p["email"], p["sale_date"], p["sale_value"])
        if key in seen:
            intra_dup += 1
            continue
        seen.add(key)
        rows.append(p)
        by_gw[p["gateway"]] = by_gw.get(p["gateway"], 0) + 1

    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        before = conn.run(
            "SELECT count(*) FROM sales WHERE client_id = :c", c=client_id
        )[0][0]
        for start in range(0, len(rows), batch_size):
            _insert_chunk(conn, rows[start:start + batch_size])
        after = conn.run(
            "SELECT count(*) FROM sales WHERE client_id = :c", c=client_id
        )[0][0]
        inserted = after - before
        res = {
            "attempted": len(rows),
            "inserted": inserted,
            "skipped": len(rows) - inserted,
            "filtered": filtered,
            "intra_dup": intra_dup,
            "by_gateway": by_gw,
        }
        logger.info("[sales_store] %s", res)
        return res
    finally:
        if own:
            conn.close()
