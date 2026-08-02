"""Escrita de CADASTROS (todos os leads, respondentes da pesquisa ou não) em
`analytics.cadastros` — a espinha de identidade do warehouse.

Diferença deliberada para `leads_store.upsert_leads` (que usa `ON CONFLICT DO
NOTHING`): aqui a fonte é VIVA (a `Client` do Railway muda o tempo todo), então
o upsert é `ON CONFLICT (email) DO UPDATE` — re-rodar reflete o estado novo em
vez de ignorar. Por isso é uma store irmã, não uma refatoração da de treino (que
não pode mudar de semântica sob risco de paridade).

Chave natural: `email` (lower). Uma linha por pessoa. `source` rotula a origem
(`client` / `leads_capi` / `client+leads_capi`); `is_respondent` marca se a
pessoa também respondeu a pesquisa (existe em `analytics.leads`). Rollback:
`DROP TABLE analytics.cadastros` ou `DELETE WHERE source=...`.
"""
from __future__ import annotations

import logging
import math
from typing import Iterable, Optional

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

# colunas gravadas (email é a PK; ingested_at/refreshed_at têm default no banco)
_COLS = (
    "email", "phone", "first_name", "last_name", "is_buyer",
    "first_seen_at", "last_activity_at",
    "campaign_key", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "has_computer", "fbp", "fbc", "ip", "user_agent", "page_source", "referrer", "event_id",
    "lead_score", "decil", "is_respondent", "source", "updated_at_src",
)
_TS_COLS = {"first_seen_at", "last_activity_at", "updated_at_src"}
_BOOL_COLS = {"is_buyer", "is_respondent"}
_FLOAT_COLS = {"lead_score"}

DDL = """
CREATE TABLE IF NOT EXISTS analytics.cadastros (
    email            text PRIMARY KEY,
    phone            text,
    first_name       text,
    last_name        text,
    is_buyer         boolean,
    first_seen_at    timestamptz,
    last_activity_at timestamptz,
    campaign_key     text,
    utm_source       text,
    utm_medium       text,
    utm_campaign     text,
    utm_content      text,
    utm_term         text,
    has_computer     text,
    fbp              text,
    fbc              text,
    ip               text,
    user_agent       text,
    page_source      text,
    referrer         text,
    event_id         text,
    lead_score       numeric,
    decil            text,
    is_respondent    boolean,
    source           text NOT NULL,
    updated_at_src   timestamptz,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    refreshed_at     timestamptz NOT NULL DEFAULT now()
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_cadastros_first_seen ON analytics.cadastros(first_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_cadastros_is_respondent ON analytics.cadastros(is_respondent)",
    "CREATE INDEX IF NOT EXISTS idx_cadastros_source ON analytics.cadastros(source)",
)


def ensure_table(conn=None) -> None:
    """Cria `analytics.cadastros` + índices se não existirem (idempotente)."""
    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        conn.run(DDL)
        for ix in _INDEXES:
            conn.run(ix)
    finally:
        if own:
            conn.close()


def _s(x) -> Optional[str]:
    if x is None:
        return None
    try:
        if isinstance(x, float) and math.isnan(x):
            return None
    except (TypeError, ValueError):
        pass
    s = str(x).strip()
    return s or None


def _f(x) -> Optional[float]:
    try:
        if x is None:
            return None
        xf = float(x)
        return None if math.isnan(xf) else xf
    except (TypeError, ValueError):
        return None


def _bool(x) -> Optional[bool]:
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    if s in ("true", "t", "1", "yes", "sim"):
        return True
    if s in ("false", "f", "0", "no", "nao", "não"):
        return False
    return None


def _cell(col, val):
    if col in _BOOL_COLS:
        return _bool(val)
    if col in _FLOAT_COLS:
        return _f(val)
    if col in _TS_COLS:
        # deixa como está (ISO string ou datetime); o CAST no placeholder resolve
        return val if val not in ("", None) else None
    return _s(val)


def _placeholder(col, key):
    if col in _TS_COLS:
        return f"CAST(:{key} AS timestamptz)"
    if col in _BOOL_COLS:
        return f"CAST(:{key} AS boolean)"
    return f":{key}"


# no conflito por email: nunca apaga valor existente com null; datas pegam o
# extremo certo (primeiro contato = menor; última atividade = maior).
#
# `mode` decide o tratamento de `source`/`is_respondent`/`is_buyer` — as colunas
# que o ETL calcula a partir do conjunto de fontes visto naquela rodada:
#   - "full": o build_rows vê as 3 fontes (Client+leads_capi+leads) e recalcula o
#     valor autoritativo → EXCLUDED sobrescreve (pode inclusive rebaixar, é o certo).
#   - "incremental": o build_rows só viu a Client (leads_capi/leads vêm vazios), então
#     EXCLUDED traria "source=client" e flags=false — o que REBAIXARIA quem já estava
#     como client+leads_capi+leads e apagaria flags. Por isso, no conflito, essas 3
#     colunas são PRESERVADAS (mantém o valor existente); a verdade das flags é
#     reafirmada depois, server-side, por reconcile_flags. Linha NOVA ainda entra
#     com o valor calculado (source=client, flags=false → reconcile promove).
def _update_clause(mode: str = "full") -> str:
    preserve = mode == "incremental"
    parts = []
    for col in _COLS:
        if col == "email":
            continue
        if col == "first_seen_at":
            parts.append("first_seen_at = LEAST(cadastros.first_seen_at, EXCLUDED.first_seen_at)")
        elif col == "last_activity_at":
            parts.append("last_activity_at = GREATEST(cadastros.last_activity_at, EXCLUDED.last_activity_at)")
        elif col in ("is_respondent", "source", "is_buyer"):
            # incremental preserva (não rebaixa); full sobrescreve com o recálculo autoritativo
            parts.append(f"{col} = cadastros.{col}" if preserve else f"{col} = EXCLUDED.{col}")
        elif col == "updated_at_src":
            # sempre reflete o updatedAt novo da Client (marca d'água do incremental)
            parts.append("updated_at_src = EXCLUDED.updated_at_src")
        else:
            parts.append(f"{col} = COALESCE(EXCLUDED.{col}, cadastros.{col})")
    parts.append("refreshed_at = now()")
    return ", ".join(parts)


_UPDATE = {"full": _update_clause("full"), "incremental": _update_clause("incremental")}


def _insert_chunk(conn, chunk, mode: str = "full") -> None:
    values, params = [], {}
    for i, row in enumerate(chunk):
        cells = []
        for col in _COLS:
            key = f"{col}_{i}"
            params[key] = row.get(col)
            cells.append(_placeholder(col, key))
        values.append("(" + ", ".join(cells) + ")")
    sql = (
        f"INSERT INTO cadastros ({', '.join(_COLS)}) VALUES " + ", ".join(values)
        + f" ON CONFLICT (email) DO UPDATE SET {_UPDATE[mode]}"
    )
    conn.run(sql, **params)


def upsert_cadastros(rows: Iterable[dict], conn=None, batch_size: int = 500,
                     mode: str = "full") -> dict:
    """Grava/atualiza cadastros (lista de dicts no shape canônico `_COLS`).

    Idempotente: `ON CONFLICT (email) DO UPDATE` (COALESCE nos campos de
    enriquecimento, LEAST/GREATEST nas datas). `mode` = "full" (recálculo
    autoritativo de source/flags) | "incremental" (preserva source/flags no
    conflito pra não rebaixar — ver `_update_clause`). Retorna {attempted,
    table_before, table_after, inserted_net}.
    """
    if mode not in _UPDATE:
        raise ValueError(f"mode inválido: {mode!r} (use 'full' ou 'incremental')")
    clean = []
    for r in rows:
        email = _s(r.get("email"))
        if not email:
            continue
        rr = {c: _cell(c, r.get(c)) for c in _COLS}
        rr["email"] = email.lower()
        if not rr.get("source"):
            rr["source"] = "client"
        clean.append(rr)

    own = conn is None
    conn = conn or open_analytics_connection(timeout=300)
    try:
        before = conn.run("SELECT count(*) FROM cadastros")[0][0]
        # Conexão longa cai em cargas grandes (Cloud SQL derruba socket ocioso). Como o
        # upsert é idempotente (ON CONFLICT DO UPDATE), re-aplicar um lote é seguro:
        # em falha de rede, reconecta e re-tenta o mesmo lote.
        for start in range(0, len(clean), batch_size):
            chunk = clean[start:start + batch_size]
            for attempt in range(5):
                try:
                    _insert_chunk(conn, chunk, mode=mode)
                    break
                except Exception as e:  # noqa: BLE001 — rede instável; reconecta e re-tenta
                    if attempt == 4:
                        raise
                    logger.warning("[cadastros_store] lote em %d falhou (%s); reconectando",
                                   start, str(e)[:70])
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    conn = open_analytics_connection(timeout=300)
                    own = True
        after = conn.run("SELECT count(*) FROM cadastros")[0][0]
        res = {"attempted": len(clean), "table_before": before,
               "table_after": after, "inserted_net": after - before}
        logger.info("[cadastros_store] %s", res)
        return res
    finally:
        if own:
            conn.close()
