"""Upsert de leads no `analytics.leads` (Fase 3 da consolidação, lado de escrita).

Recebe um DataFrame de leads já normalizado (uma linha por lead, com as colunas
do shape interno abaixo) e grava em lote, idempotente.

A pesquisa vai em `survey_responses` como **jsonb com chaves = os textos das
perguntas** (os nomes canônicos que o treino consome) — independente da fonte.
Quem traduz o ledger (camelCase) → perguntas é o chamador (ETL), via
`api/railway_mapping.railway_lead_to_sheets_row`. Aqui não traduzimos nada:
gravamos o dict como veio. Round-trip lossless → paridade de feature por
construção.

Idempotente: `ON CONFLICT DO NOTHING` (pega os dois índices únicos da tabela —
por event_id quando presente, por email+capturado_em quando não). Re-rodar não
duplica; `ingested_at` fica no "primeiro visto".
"""
from __future__ import annotations

import json
import logging
import math
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

# colunas da tabela analytics.leads gravadas (na ordem). id/ingested_at = default.
_COLS = (
    "client_id", "source", "event_id", "email", "phone", "first_name", "last_name",
    "capturado_em", "status_envio", "decil", "score", "variant",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "utm_url",
    "capi_enviado_em", "erro", "survey_responses", "fbp", "fbc", "user_agent",
    "ip", "has_computer",
)
# colunas que recebem CAST específico no INSERT
_TS_COLS = {"capturado_em", "capi_enviado_em"}
_JSONB_COLS = {"survey_responses"}
_INT_COLS = {"decil"}
_FLOAT_COLS = {"score"}


def _s(x) -> Optional[str]:
    try:
        if x is None or pd.isna(x):  # pega None, NaN e NaT
            return None
    except (TypeError, ValueError):
        pass  # x não-escalar (ex: dict) — segue
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


def _i(x) -> Optional[int]:
    xf = _f(x)
    return None if xf is None else int(round(xf))


def _ts(x) -> Optional[str]:
    try:
        if x is None or pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(x).isoformat()
    except Exception:
        return None


def _jsonb(x) -> Optional[str]:
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, str):
        return x if x.strip() else None
    if isinstance(x, dict):
        return json.dumps(x, ensure_ascii=False, default=str) if x else None
    return None


def _cell(col, val):
    if col in _TS_COLS:
        return _ts(val)
    if col in _JSONB_COLS:
        return _jsonb(val)
    if col in _INT_COLS:
        return _i(val)
    if col in _FLOAT_COLS:
        return _f(val)
    return _s(val)


def _placeholder(col, key):
    if col in _TS_COLS:
        return f"CAST(:{key} AS timestamptz)"
    if col in _JSONB_COLS:
        return f"CAST(:{key} AS jsonb)"
    return f":{key}"


def _insert_chunk(conn, chunk) -> None:
    values, params = [], {}
    for i, row in enumerate(chunk):
        cells = []
        for col in _COLS:
            key = f"{col}_{i}"
            params[key] = row[col]
            cells.append(_placeholder(col, key))
        values.append("(" + ", ".join(cells) + ")")
    sql = (
        f"INSERT INTO leads ({', '.join(_COLS)}) VALUES " + ", ".join(values)
        + " ON CONFLICT DO NOTHING"
    )
    conn.run(sql, **params)


def upsert_leads(df: pd.DataFrame, source: str, client_id: str = "devclub",
                 conn=None, batch_size: int = 500) -> dict:
    """Grava leads de uma fonte em analytics.leads (idempotente, em lote).

    Args:
        df: DataFrame de leads. Colunas lidas (todas opcionais menos identidade):
            email, telefone/phone, first_name, last_name, event_id, data_captura/
            capturado_em, status_envio, decil, score, variant, utm_source/medium/
            campaign/content/term/url, capi_enviado_em, erro, survey_responses (dict),
            fbp, fbc, user_agent, ip, has_computer.
        source: proveniência ('sheets_prod'|'sheets_backup'|'registros_ml'|
                'railway_lead'|'cloudsql_backup'|'vip').

    Retorna {attempted, inserted, skipped, filtered}.
    """
    empty = {"attempted": 0, "inserted": 0, "skipped": 0, "filtered": 0}
    if df is None or getattr(df, "empty", True):
        return empty

    rows, filtered = [], 0
    for _, r in df.iterrows():
        rd = r.to_dict()
        email = _s(rd.get("email"))
        phone = _s(rd.get("telefone") or rd.get("phone"))
        event_id = _s(rd.get("event_id"))
        # precisa de alguma identidade pra dedup/uso
        if not (email or phone or event_id):
            filtered += 1
            continue
        raw = {
            "client_id": client_id,
            "source": source,
            "event_id": event_id,
            "email": email,
            "phone": phone,
            "first_name": rd.get("first_name") or rd.get("nome"),
            "last_name": rd.get("last_name"),
            "capturado_em": rd.get("capturado_em") or rd.get("data_captura") or rd.get("Data"),
            "status_envio": rd.get("status_envio"),
            "decil": rd.get("decil") or rd.get("decile"),
            "score": rd.get("score") or rd.get("lead_score"),
            "variant": rd.get("variant"),
            "utm_source": rd.get("utm_source") or rd.get("source"),
            "utm_medium": rd.get("utm_medium") or rd.get("medium"),
            "utm_campaign": rd.get("utm_campaign") or rd.get("campaign"),
            "utm_content": rd.get("utm_content") or rd.get("content"),
            "utm_term": rd.get("utm_term") or rd.get("term"),
            "utm_url": rd.get("utm_url") or rd.get("url"),
            "capi_enviado_em": rd.get("capi_enviado_em"),
            "erro": rd.get("erro"),
            "survey_responses": rd.get("survey_responses"),
            "fbp": rd.get("fbp"),
            "fbc": rd.get("fbc"),
            "user_agent": rd.get("user_agent"),
            "ip": rd.get("ip"),
            "has_computer": rd.get("has_computer") or rd.get("tem_computador"),
        }
        rows.append({c: _cell(c, raw[c]) for c in _COLS})

    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        before = conn.run(
            "SELECT count(*) FROM leads WHERE client_id = :c AND source = :s",
            c=client_id, s=source,
        )[0][0]
        for start in range(0, len(rows), batch_size):
            _insert_chunk(conn, rows[start:start + batch_size])
        after = conn.run(
            "SELECT count(*) FROM leads WHERE client_id = :c AND source = :s",
            c=client_id, s=source,
        )[0][0]
        inserted = after - before
        res = {"attempted": len(rows), "inserted": inserted,
               "skipped": len(rows) - inserted, "filtered": filtered}
        logger.info("[leads_store] source=%s %s", source, res)
        return res
    finally:
        if own:
            conn.close()
