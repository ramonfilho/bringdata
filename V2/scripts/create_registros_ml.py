#!/usr/bin/env python3
"""Migração I1 — tabela-ledger `registros_ml` (idempotente).

Tabela NOSSA (não Prisma) — fonte única de verdade dos eventos CAPI scoreados
por ML disparados a partir de `lead_surveys`:

  - Dedup/idempotência: 1 linha por survey lead (PK `lead_id` = lead_surveys.id);
    o polling não reprocessa lead que já tem linha.
  - Registro dos até 2 eventos por lead: base (LeadQualified / HQLB_LQ) e
    high-quality (LeadQualifiedHighQuality / HQLB, só D9-D10). O nome do evento
    é derivável de `variant`, por isso não é gravado (sem redundância).
  - Fonte de leitura do monitoramento (digest/alertas) da esteira nova.

Idempotente: usa CREATE TABLE/INDEX IF NOT EXISTS — rodar N vezes = mesmo estado.
Não-destrutivo: não toca nenhuma tabela existente.
Rollback: DROP TABLE registros_ml;

Histórico: criada como `survey_capi_sent` no I1 e renomeada para `registros_ml`
a pedido do usuário antes de qualquer consumidor (nada lê/escreve até o I4).

Credenciais: lê RAILWAY_DB_* do ambiente; se ausentes, carrega de um .env
apontado por RAILWAY_ENV_FILE, ou de scripts/../.env. Sem hardcode de path.

Uso:
  RAILWAY_ENV_FILE=/abs/V2/.env python scripts/create_registros_ml.py
  python scripts/create_registros_ml.py --verify-only
"""
import argparse
import os
import sys

import pg8000.native


def _load_env() -> None:
    if os.environ.get("RAILWAY_DB_HOST") and os.environ.get("RAILWAY_DB_PASSWORD"):
        return
    candidates = []
    if os.environ.get("RAILWAY_ENV_FILE"):
        candidates.append(os.environ["RAILWAY_ENV_FILE"])
    candidates.append(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    )
    for path in candidates:
        if path and os.path.isfile(path):
            for line in open(path):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


DDL_TABLE = """
CREATE TABLE IF NOT EXISTS registros_ml (
    lead_id            TEXT PRIMARY KEY,           -- = lead_surveys.id (dedup)
    email              TEXT,
    variant            TEXT,                       -- champion | challenger (deriva nome do evento)
    lead_score         DOUBLE PRECISION,
    decil              INTEGER,                    -- 1..10
    base_meta_event_id TEXT,                       -- event_id do evento base
    base_status        TEXT,                       -- success|error|blocked|skipped_*
    hq_meta_event_id   TEXT,                       -- event_id do high-quality (NULL se decil<9)
    hq_status          TEXT,                       -- NULL se não aplicável
    capi_sent_at       TIMESTAMP,                  -- quando saiu (NULL se skip/blocked)
    error_message      TEXT,
    created_at         TIMESTAMP NOT NULL DEFAULT now()
);
"""

DDL_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_registros_ml_created_at "
    "ON registros_ml (created_at);"
)


def main() -> None:
    ap = argparse.ArgumentParser(description="Cria/verifica a tabela registros_ml.")
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="só inspeciona o estado atual; não roda DDL",
    )
    args = ap.parse_args()

    _load_env()
    try:
        host = os.environ["RAILWAY_DB_HOST"]
        password = os.environ["RAILWAY_DB_PASSWORD"]
    except KeyError as e:
        sys.exit(
            f"[FALHA] credencial ausente: {e}. Exporte RAILWAY_DB_* ou aponte "
            f"RAILWAY_ENV_FILE para um .env válido."
        )

    conn = pg8000.native.Connection(
        host=host,
        port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
        database=os.environ.get("RAILWAY_DB_NAME", "railway"),
        user=os.environ.get("RAILWAY_DB_USER", "postgres"),
        password=password,
        ssl_context=True,
        timeout=40,
    )
    try:
        if not args.verify_only:
            conn.run(DDL_TABLE)
            conn.run(DDL_INDEX)
            print("[OK] CREATE TABLE/INDEX IF NOT EXISTS aplicado (idempotente).")

        cols = conn.run(
            """SELECT column_name, data_type, is_nullable, column_default
               FROM information_schema.columns
               WHERE table_schema='public' AND table_name='registros_ml'
               ORDER BY ordinal_position"""
        )
        if not cols:
            sys.exit("[FALHA] tabela registros_ml NÃO existe após o DDL.")

        print(f"\nregistros_ml — {len(cols)} colunas:")
        for cn, dt, nul, dflt in cols:
            print(f"  {cn:20s} {dt:18s} null={nul:3s} default={dflt}")

        pk = conn.run(
            """SELECT a.attname FROM pg_index i
               JOIN pg_attribute a
                 ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey)
               WHERE i.indrelid='registros_ml'::regclass AND i.indisprimary"""
        )
        idx = conn.run(
            """SELECT indexname FROM pg_indexes
               WHERE schemaname='public' AND tablename='registros_ml'
               ORDER BY indexname"""
        )
        n = conn.run("SELECT count(*) FROM registros_ml")[0][0]
        print(f"  PK: {[r[0] for r in pk]}")
        print(f"  índices: {[r[0] for r in idx]}")
        print(f"  linhas: {n}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
