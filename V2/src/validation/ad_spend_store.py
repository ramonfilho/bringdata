"""ad_spend_store.py — upsert de gasto de anúncio → analytics.ad_spend.

Idempotente com `ON CONFLICT DO UPDATE` na chave natural (client_id, platform,
campaign_id, spend_date). É **DO UPDATE** (≠ do sales_store, que faz DO NOTHING)
porque a Meta REESCREVE o gasto de um dia por ~28d (janela de atribuição): re-rodar
a mesma janela deve SOBRESCREVER, não pular. Espelha a estrutura do sales_store.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection

_COLS = ("client_id", "platform", "account_id", "campaign_id", "campaign_name",
         "spend_date", "spend", "leads", "impressions", "clicks")

# colunas sobrescritas quando a chave natural já existe (a Meta restata)
_UPDATE_COLS = ("campaign_name", "spend", "leads", "impressions", "clicks", "account_id")


def _f(x) -> Optional[float]:
    try:
        return None if x is None or (isinstance(x, float) and pd.isna(x)) else float(x)
    except (TypeError, ValueError):
        return None


def _i(x) -> Optional[int]:
    v = _f(x)
    return None if v is None else int(v)


def _s(x) -> Optional[str]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).strip()
    return s or None


def _d(x) -> Optional[str]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, (date, datetime)):
        return x.strftime("%Y-%m-%d")
    return str(x)[:10]


def _row_params(r, client_id: str):
    """Linha do loader → dict pronto. Descarta sem plataforma/data/gasto (não dá
    pra dedup nem somar)."""
    platform = _s(r.get("platform"))
    spend_date = _d(r.get("spend_date") or r.get("date"))
    spend = _f(r.get("spend"))
    if not platform or not spend_date or spend is None:
        return None
    return {
        "client_id": client_id, "platform": platform.lower(),
        "account_id": _s(r.get("account_id")), "campaign_id": _s(r.get("campaign_id")),
        "campaign_name": _s(r.get("campaign_name")), "spend_date": spend_date,
        "spend": spend, "leads": _i(r.get("leads")),
        "impressions": _i(r.get("impressions")), "clicks": _i(r.get("clicks")),
    }


def _insert_chunk(conn, chunk) -> None:
    """INSERT multi-row (1 round-trip), ON CONFLICT DO UPDATE (Meta restata)."""
    values, params = [], {}
    for i, p in enumerate(chunk):
        cells = []
        for col in _COLS:
            key = f"{col}_{i}"
            params[key] = p[col]
            cells.append(f"CAST(:{key} AS date)" if col == "spend_date" else f":{key}")
        values.append("(" + ", ".join(cells) + ")")
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATE_COLS) + ", ingested_at = now()"
    sql = (
        f"INSERT INTO ad_spend ({', '.join(_COLS)}) VALUES " + ", ".join(values)
        + " ON CONFLICT (client_id, platform, campaign_id, spend_date) DO UPDATE SET "
        + set_clause
    )
    conn.run(sql, **params)


def upsert_ad_spend(df: pd.DataFrame, client_id: str = "devclub", conn=None,
                    batch_size: int = 500) -> dict:
    """Grava gasto por campanha×dia em analytics.ad_spend (idempotente, em lote).
    Retorna {attempted, written, filtered, intra_dup, by_platform}. `written` conta
    linhas enviadas (insert OU update — não dá pra distinguir com DO UPDATE)."""
    empty = {"attempted": 0, "written": 0, "filtered": 0, "intra_dup": 0, "by_platform": {}}
    if df is None or getattr(df, "empty", True):
        return empty

    rows, filtered, intra_dup, seen, by_pf = [], 0, 0, set(), {}
    for _, r in df.iterrows():
        p = _row_params(r, client_id)
        if p is None:
            filtered += 1
            continue
        key = (p["platform"], p["campaign_id"], p["spend_date"])
        if key in seen:
            intra_dup += 1
            continue
        seen.add(key)
        rows.append(p)
        by_pf[p["platform"]] = by_pf.get(p["platform"], 0) + 1

    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        for start in range(0, len(rows), batch_size):
            _insert_chunk(conn, rows[start:start + batch_size])
    finally:
        if own:
            conn.close()
    return {"attempted": len(df), "written": len(rows), "filtered": filtered,
            "intra_dup": intra_dup, "by_platform": by_pf}
