"""launch_calendar_store.py — upsert do calendário de LFs → analytics.launch_calendar.

Grava o calendário MERGEADO (datas da planilha + curadoria do yaml, produzido por
`launch_calendar.merge_for_write`) na tabela `analytics.launch_calendar`. Cada LF é
uma linha; a coluna `entry` (jsonb) guarda o dict COMPLETO do LF — exatamente o
shape que `core.launches.load_launches()` devolve — pra que o leitor da tabela
reconstrua o mesmo contrato do yaml sem perda.

Idempotente com `ON CONFLICT (client_id, lf_name) DO UPDATE`: re-rodar o sync
SOBRESCREVE (a planilha é fonte única das datas; curadoria vem do yaml). Nunca
apaga LF (histórico preservado, igual ao merge_for_write). Espelha ad_spend_store.

Escrita SEMPRE no nosso Cloud SQL (schema analytics) — nunca no Railway.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

# DDL idempotente — espelha api/db/analytics_schema.sql (fonte canônica). Aqui
# pra o job de sync poder criar a tabela sozinho no 1º run, sem depender de
# aplicar o .sql à mão antes.
_DDL = """
CREATE TABLE IF NOT EXISTS launch_calendar (
    client_id    VARCHAR(64)  NOT NULL DEFAULT 'devclub',
    lf_name      VARCHAR(32)  NOT NULL,
    cap_start    DATE,
    cap_end      DATE,
    vendas_start DATE,
    vendas_end   DATE,
    entry        JSONB        NOT NULL,
    source       VARCHAR(32)  NOT NULL DEFAULT 'sheet_sync',
    synced_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, lf_name)
)
"""

_COLS = ("client_id", "lf_name", "cap_start", "cap_end", "vendas_start",
         "vendas_end", "entry", "source")
# Colunas sobrescritas quando o LF já existe (a planilha restata as datas / curadoria muda).
_UPDATE_COLS = ("cap_start", "cap_end", "vendas_start", "vendas_end", "entry", "source")
_DATE_COLS = ("cap_start", "cap_end", "vendas_start", "vendas_end")


def ensure_launch_calendar_table(conn) -> None:
    """Cria analytics.launch_calendar se não existir (idempotente)."""
    conn.run(_DDL)


def _row_params(lf_name: str, entry: dict, client_id: str, source: str) -> Optional[dict]:
    """LF + entry (dict do calendário) → dict de params. Descarta sem nome."""
    name = str(lf_name).strip()
    if not name:
        return None
    p = {"client_id": client_id, "lf_name": name, "source": source,
         "entry": json.dumps(entry, ensure_ascii=False, sort_keys=True)}
    for c in _DATE_COLS:
        v = entry.get(c)
        p[c] = str(v)[:10] if v else None
    return p


def _insert_chunk(conn, chunk) -> None:
    """INSERT multi-row (1 round-trip), ON CONFLICT DO UPDATE."""
    values, params = [], {}
    for i, p in enumerate(chunk):
        cells = []
        for col in _COLS:
            key = f"{col}_{i}"
            params[key] = p[col]
            if col in _DATE_COLS:
                cells.append(f"CAST(:{key} AS date)")
            elif col == "entry":
                cells.append(f"CAST(:{key} AS jsonb)")
            else:
                cells.append(f":{key}")
        values.append("(" + ", ".join(cells) + ")")
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATE_COLS) + ", synced_at = now()"
    sql = (
        f"INSERT INTO launch_calendar ({', '.join(_COLS)}) VALUES " + ", ".join(values)
        + " ON CONFLICT (client_id, lf_name) DO UPDATE SET " + set_clause
    )
    conn.run(sql, **params)


def upsert_launch_calendar(merged: dict, client_id: str = "devclub", conn=None,
                           source: str = "sheet_sync") -> dict:
    """Grava o calendário mergeado em analytics.launch_calendar (idempotente).

    Args:
        merged: `{lf_name: entry}` de launch_calendar.merge_for_write (datas +
            curadoria). `entry` é gravado cru em jsonb — é o contrato de leitura.
        client_id: cliente (default 'devclub').
        conn: conexão analytics já aberta (opcional). Se None, abre/fecha.
        source: proveniência gravada na coluna `source`.

    Returns:
        {attempted, written} — `written` conta LFs enviados (insert OU update).
    """
    if not merged:
        return {"attempted": 0, "written": 0}
    rows = [p for lf, e in merged.items() if (p := _row_params(lf, e, client_id, source))]

    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        ensure_launch_calendar_table(conn)
        if rows:
            _insert_chunk(conn, rows)
    finally:
        if own:
            conn.close()
    logger.info("[launch_calendar_store] %d LFs gravados (client_id=%s)", len(rows), client_id)
    return {"attempted": len(merged), "written": len(rows)}
