#!/usr/bin/env python3
"""Migração — tabela-ledger `registros_ml` (idempotente).

Tabela NOSSA (não Prisma) — fonte única de verdade dos eventos CAPI scoreados
por ML disparados a partir das mensagens Pub/Sub do sistema novo:

  - Dedup/idempotência: 1 linha por lead (PK `event_id` = UUID v7 do payload
    Pub/Sub, estável entre reenvios). O consumer não reprocessa lead que já
    tem linha.
  - Registro dos até 2 eventos por lead: base (LeadQualified / HQLB_LQ) e
    high-quality (LeadQualifiedHighQuality / HQLB, só D9-D10). O nome do evento
    é derivável de `variant`, por isso não é gravado (sem redundância).
  - Fonte de leitura do monitoramento (digest/alertas) da esteira nova.

Idempotente: usa CREATE TABLE/INDEX IF NOT EXISTS — rodar N vezes = mesmo estado.
Não-destrutivo: não toca nenhuma tabela existente.
Migração de instâncias anteriores: se a tabela já existir com a coluna `lead_id`
(esquema antigo da arquitetura Railway, antes da virada pra Pub/Sub), o script
renomeia `lead_id` → `event_id` (ALTER TABLE RENAME). A semântica é equivalente:
ambas TEXT, ambas PK, ambas "id estável do lead".
Rollback: DROP TABLE registros_ml;

Histórico:
  - Criada como `survey_capi_sent` no I1 (ledger da arquitetura Railway).
  - Renomeada para `registros_ml` a pedido do usuário (commit 31d1151).
  - Coluna PK renomeada `lead_id` → `event_id` na virada pra Pub/Sub
    (arquitetura nova, descarta leitura Railway + parsing de log).
  - 2026-05-24: adicionadas 6 colunas UTM (`utm_source`, `utm_medium`,
    `utm_campaign`, `utm_content`, `utm_term`, `utm_url`) via ALTER TABLE
    IF NOT EXISTS. Single-table substitui JOIN com lead_surveys×UTMTracking
    pro monitoramento. Decisão P12 do PROCESSO_CAPI_LEAD_SURVEYS.

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
    event_id           TEXT PRIMARY KEY,           -- UUID v7 do payload Pub/Sub (estável p/ dedup)
    email              TEXT,
    variant            TEXT,                       -- champion | challenger (deriva nome do evento)
    lead_score         DOUBLE PRECISION,
    decil              INTEGER,                    -- 1..10
    base_meta_event_id TEXT,                       -- event_id enviado ao Meta no evento base
    base_status        TEXT,                       -- success|error|blocked|skipped_*
    hq_meta_event_id   TEXT,                       -- event_id enviado ao Meta no high-quality (NULL se decil<9)
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

# Migração in-place: instâncias criadas antes da virada pra Pub/Sub têm a PK
# chamada `lead_id`. Renomeia pra `event_id` se for o caso. Equivalência total:
# ambas TEXT, ambas PK, ambas "id estável do lead p/ dedup".
SQL_RENAME_LEAD_ID = (
    "ALTER TABLE registros_ml RENAME COLUMN lead_id TO event_id;"
)

# Migração 2026-05-24: 6 colunas UTM. Permite que o monitoramento (utm quality,
# source missing, ranking de UTM por decil etc) leia tudo de `registros_ml` em
# vez de fazer JOIN com `lead_surveys × UTMTracking`. ALTER ADD COLUMN IF NOT
# EXISTS é idempotente desde PostgreSQL 9.6.
SQL_ADD_UTM_COLUMNS = (
    "ALTER TABLE registros_ml "
    "ADD COLUMN IF NOT EXISTS utm_source   TEXT,"
    "ADD COLUMN IF NOT EXISTS utm_medium   TEXT,"
    "ADD COLUMN IF NOT EXISTS utm_campaign TEXT,"
    "ADD COLUMN IF NOT EXISTS utm_content  TEXT,"
    "ADD COLUMN IF NOT EXISTS utm_term     TEXT,"
    "ADD COLUMN IF NOT EXISTS utm_url      TEXT;"
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
            # Se a tabela já existir com a coluna antiga `lead_id`, renomeia
            # ANTES do CREATE — assim o CREATE IF NOT EXISTS encontra o estado
            # esperado (PK chamada event_id) e vira no-op idempotente.
            existing_cols = conn.run(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='registros_ml'"""
            )
            existing_names = {r[0] for r in existing_cols}
            if "lead_id" in existing_names and "event_id" not in existing_names:
                conn.run(SQL_RENAME_LEAD_ID)
                print("[OK] coluna lead_id renomeada para event_id (migração Pub/Sub).")
            elif "lead_id" in existing_names and "event_id" in existing_names:
                sys.exit(
                    "[FALHA] estado ambíguo: tabela tem AMBAS as colunas lead_id e event_id. "
                    "Investigar manualmente antes de prosseguir."
                )

            conn.run(DDL_TABLE)
            conn.run(DDL_INDEX)
            conn.run(SQL_ADD_UTM_COLUMNS)
            print("[OK] CREATE TABLE/INDEX + ADD COLUMN UTM aplicados (idempotente).")

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
