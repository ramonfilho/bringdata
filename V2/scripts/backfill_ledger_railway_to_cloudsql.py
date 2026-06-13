#!/usr/bin/env python3
"""
backfill_ledger_railway_to_cloudsql.py — Etapa 2a do PLANO_LEDGER_CLOUDSQL.md.

Copia o ledger `registros_ml` do Railway do cliente (~20k linhas desde
23/05/2026) para o nosso Cloud SQL `ledger`, fechando o buraco anterior ao
dual-write (que só começou a gravar nos dois bancos em 12/06).

Idempotente: ON CONFLICT (event_id) DO NOTHING — pode rodar quantas vezes
quiser; linhas já presentes (inclusive as do dual-write) são ignoradas.
NÃO escreve no Railway — só lê. NÃO toca produção.

    python scripts/backfill_ledger_railway_to_cloudsql.py            # copia
    python scripts/backfill_ledger_railway_to_cloudsql.py --verify   # só confere
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 32 colunas, ordem do schema (espelho idêntico nas duas pontas)
COLS = [
    "event_id", "email", "variant", "lead_score", "decil", "base_meta_event_id",
    "base_status", "hq_meta_event_id", "hq_status", "capi_sent_at", "error_message",
    "created_at", "utm_source", "utm_medium", "utm_campaign", "utm_content",
    "utm_term", "utm_url", "survey_responses", "first_name", "last_name", "phone",
    "fbp", "fbc", "user_agent", "ip", "has_computer", "decile_propensity",
    "decile_roas_v1", "cpl_source", "events_fired", "extra_hq_destinations_fired",
]
JSONB_COLS = {"survey_responses", "extra_hq_destinations_fired"}
BATCH = 500


def _load_dotenv() -> None:
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _railway():
    import pg8000.native
    return pg8000.native.Connection(
        host=os.environ.get("RAILWAY_DB_HOST", "shortline.proxy.rlwy.net"),
        port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
        database=os.environ.get("RAILWAY_DB_NAME", "railway"),
        user=os.environ.get("RAILWAY_DB_USER", "postgres"),
        password=os.environ["RAILWAY_DB_PASSWORD"], ssl_context=_ctx(), timeout=60,
    )


def _cloudsql():
    import pg8000.native
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"],
        port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"], ssl_context=_ctx(), timeout=60,
    )


def _row_params(row: dict) -> dict:
    params = {}
    for col, val in zip(COLS, row):
        if col in JSONB_COLS and val is not None and not isinstance(val, str):
            val = json.dumps(val)
        params[col] = val
    return params


def _multi_insert_sql(n_rows: int) -> str:
    """1 statement com n_rows tuplas — corta round-trips de N para N/BATCH.
    Placeholders por linha sufixados pelo índice (:event_id_0, :event_id_1...)."""
    tuples = []
    for i in range(n_rows):
        ph = [
            (f"CAST(:{c}_{i} AS JSONB)" if c in JSONB_COLS else f":{c}_{i}")
            for c in COLS
        ]
        tuples.append(f"({', '.join(ph)})")
    return (
        f"INSERT INTO registros_ml ({', '.join(COLS)}) "
        f"VALUES {', '.join(tuples)} "
        f"ON CONFLICT (event_id) DO NOTHING"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    _load_dotenv()

    rw, cs = _railway(), _cloudsql()
    try:
        rwc = rw.run("SELECT count(*) FROM registros_ml")[0][0]
        csc_antes = cs.run("SELECT count(*) FROM registros_ml")[0][0]
        print(f"Railway: {rwc} | Cloud SQL: {csc_antes}")
        if args.verify:
            return 0

        rows = rw.run(f"SELECT {', '.join(COLS)} FROM registros_ml ORDER BY created_at")
        copiadas = 0
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            sql = _multi_insert_sql(len(chunk))
            params = {}
            for j, row in enumerate(chunk):
                for col, val in _row_params(row).items():
                    params[f"{col}_{j}"] = val
            cs.run(sql, **params)
            copiadas += len(chunk)
            print(f"  {copiadas}/{len(rows)}...", flush=True)

        csc_depois = cs.run("SELECT count(*) FROM registros_ml")[0][0]
        print(f"\n✅ Cloud SQL: {csc_antes} → {csc_depois} "
              f"(+{csc_depois - csc_antes} novas; {len(rows)} lidas do Railway)")
        # Conferência: todo event_id do Railway existe no Cloud SQL?
        rw_ids = {r[0] for r in rw.run("SELECT event_id FROM registros_ml")}
        cs_ids = {r[0] for r in cs.run("SELECT event_id FROM registros_ml")}
        faltam = rw_ids - cs_ids
        print(f"event_ids do Railway ausentes no Cloud SQL: {len(faltam)}")
        return 0 if not faltam else 1
    finally:
        rw.close(); cs.close()


if __name__ == "__main__":
    sys.exit(main())
