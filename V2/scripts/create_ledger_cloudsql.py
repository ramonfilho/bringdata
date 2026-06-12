#!/usr/bin/env python3
"""
create_ledger_cloudsql.py — DDL do ledger `registros_ml` no Cloud SQL nosso.

Etapa 0 do PLANO_LEDGER_CLOUDSQL.md: o ledger sai do Railway do cliente
(proteção do modelo — score+decil+features juntos na infra dele permitem
clonar o modelo por regressão) e passa a viver no database `ledger` da
instância `smart-ads-db` (smart-ads-451319, us-central1).

Este DDL é o ESPELHO do schema live do Railway em 12/06/2026 (32 colunas) e
consolida as três gerações de migração que estavam espalhadas:
  - 12 colunas base + índice created_at  (scripts/create_registros_ml.py)
  - 6 colunas UTM                        (idem, ALTER posteriores)
  - 5 colunas de observabilidade         (scripts/add_observability_columns_registros_ml.py)
  - 9 colunas de enriquecimento que NUNCA tiveram migração no repo
    (survey_responses, first_name, last_name, phone, fbp, fbc,
     user_agent, ip, has_computer — criadas direto no banco)

Idempotente (IF NOT EXISTS). Roda como `ledger_app` (dono da tabela):

    python scripts/create_ledger_cloudsql.py            # cria
    python scripts/create_ledger_cloudsql.py --verify   # só confere

Env vars: LEDGER_DB_HOST / PORT / NAME / USER / PASSWORD (V2/.env;
senha também no Secret Manager `ledger-db-password`).
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # V2/

DDL_TABLE = """
CREATE TABLE IF NOT EXISTS registros_ml (
    -- núcleo (ledger original, 23/05/2026)
    event_id            TEXT PRIMARY KEY,
    email               TEXT,
    variant             TEXT,
    lead_score          DOUBLE PRECISION,
    decil               INTEGER,
    base_meta_event_id  TEXT,
    base_status         TEXT,
    hq_meta_event_id    TEXT,
    hq_status           TEXT,
    capi_sent_at        TIMESTAMP,
    error_message       TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT now(),
    -- UTM (single-table, decisão 24/05/2026)
    utm_source          TEXT,
    utm_medium          TEXT,
    utm_campaign        TEXT,
    utm_content         TEXT,
    utm_term            TEXT,
    utm_url             TEXT,
    -- enriquecimento do payload Pub/Sub (sem migração no repo até 12/06/2026)
    survey_responses    JSONB,
    first_name          TEXT,
    last_name           TEXT,
    phone               TEXT,
    fbp                 TEXT,
    fbc                 TEXT,
    user_agent          TEXT,
    ip                  TEXT,
    has_computer        TEXT,
    -- observabilidade (Bloco E)
    decile_propensity   INTEGER,
    decile_roas_v1      INTEGER,
    cpl_source          TEXT,
    events_fired        TEXT[],
    extra_hq_destinations_fired JSONB
)
"""

DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_registros_ml_created_at ON registros_ml (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_registros_ml_email_lower ON registros_ml (lower(email))",
]

EXPECTED_COLUMNS = 32


def _connect():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    import pg8000.native
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"],
        port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"],
        ssl_context=ctx,
        timeout=30,
    )


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip("'").strip('"'))


def verify(conn) -> bool:
    cols = conn.run(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='registros_ml' ORDER BY ordinal_position"
    )
    idx = conn.run("SELECT indexname FROM pg_indexes WHERE tablename='registros_ml'")
    print(f"colunas: {len(cols)}/{EXPECTED_COLUMNS}")
    print(f"índices: {sorted(i[0] for i in idx)}")
    ok = len(cols) == EXPECTED_COLUMNS and len(idx) >= 3  # pkey + 2 índices
    print("✅ schema ok" if ok else "❌ schema divergente")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="só confere, não cria")
    args = ap.parse_args()

    _load_dotenv()
    conn = _connect()
    try:
        if not args.verify:
            conn.run(DDL_TABLE)
            for ddl in DDL_INDEXES:
                conn.run(ddl)
            print("DDL aplicado (idempotente)")
        return 0 if verify(conn) else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
