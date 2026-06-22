#!/usr/bin/env python3
"""Migração — coluna `google_ads_status` no `registros_ml` (frente Google Ads, Fase B).

Adiciona 1 coluna aditiva que registra o desfecho do envio da conversão pro
Google Ads, análoga ao par `base_status`/`capi_sent_at` do Meta:

  - `google_ads_status TEXT`
      Desfecho do envio Google por lead:
        sent    → conversão aceita pela Data Manager API (events:ingest 200)
        error   → falha no envio
        skipped → não enviado (ex.: não elegível) — raro neste caminho
      NULL pra todo lead que não passou pelo canal Google (Meta, orgânico,
      pré-ativação). `base_status` continua sendo o desfecho Meta; este campo
      é a dimensão Google, independente.

⚠️ DEPLOY — ordem obrigatória: rodar esta migração ANTES de deployar o código
da Fase B. O consumer Pub/Sub passa a escrever `google_ads_status` em TODO
INSERT do ledger; se a coluna não existir, o INSERT quebra. Como o ledger é
DUAL (Railway + Cloud SQL), a coluna tem que existir nos DOIS — rodar com
--target railway E --target cloudsql (ou um de cada vez).

Idempotente: ALTER TABLE ADD COLUMN IF NOT EXISTS. Não-destrutivo.
Rollback: ALTER TABLE registros_ml DROP COLUMN google_ads_status;

Credenciais (lê do ambiente; cai pra .env via RAILWAY_ENV_FILE ou scripts/../.env):
  --target railway  → RAILWAY_DB_HOST/PORT/USER/PASSWORD/NAME
  --target cloudsql → LEDGER_DB_HOST/PORT/USER/PASSWORD/NAME

Uso:
  python scripts/add_google_ads_status_column.py --target railway
  python scripts/add_google_ads_status_column.py --target cloudsql
  python scripts/add_google_ads_status_column.py --target railway --verify-only
"""
import argparse
import os
import sys

import pg8000.native

COLUMN = ("google_ads_status", "TEXT")

# Prefixo de env var por alvo do ledger (PLANO_LEDGER_CLOUDSQL.md).
TARGET_ENV = {
    "railway":  "RAILWAY_DB_",
    "cloudsql": "LEDGER_DB_",
}


def _load_env() -> None:
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


def _connect(prefix: str) -> pg8000.native.Connection:
    required = [f"{prefix}{s}" for s in ("HOST", "PORT", "USER", "PASSWORD", "NAME")]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[FAIL] variáveis de ambiente ausentes: {missing}", file=sys.stderr)
        sys.exit(2)
    return pg8000.native.Connection(
        host=os.environ[f"{prefix}HOST"],
        port=int(os.environ[f"{prefix}PORT"]),
        user=os.environ[f"{prefix}USER"],
        password=os.environ[f"{prefix}PASSWORD"],
        database=os.environ[f"{prefix}NAME"],
    )


def _execute(conn: pg8000.native.Connection, *, verify_only: bool) -> int:
    col, typ = COLUMN
    if verify_only:
        rows = conn.run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'registros_ml' "
            "AND column_name = :col",
            col=col,
        )
        if rows:
            print(f"[OK] coluna '{col}' presente.")
            return 0
        print(f"[FAIL] coluna '{col}' ausente.")
        return 1
    print(f"ALTER TABLE registros_ml ADD COLUMN IF NOT EXISTS {col} {typ}…")
    conn.run(f"ALTER TABLE registros_ml ADD COLUMN IF NOT EXISTS {col} {typ}")
    print("[OK] migração idempotente concluída.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", choices=list(TARGET_ENV), required=True,
                   help="qual ledger alterar (rodar nos DOIS antes do deploy)")
    p.add_argument("--verify-only", action="store_true",
                   help="não altera — só verifica que a coluna existe")
    args = p.parse_args()

    _load_env()
    conn = _connect(TARGET_ENV[args.target])
    print(f"[{args.target}] {os.environ[TARGET_ENV[args.target] + 'HOST']}")
    try:
        return _execute(conn, verify_only=args.verify_only)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
