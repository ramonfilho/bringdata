#!/usr/bin/env python3
"""
copy_lead_legado_cloudsql.py — cópia de segurança da tabela `Lead` (Railway,
morta ~17/05) para `lead_legado` no nosso Cloud SQL, ANTES da Etapa 5 anular
`leadScore`/`decil` no Railway (PLANO_LEDGER_CLOUDSQL.md Etapa 5 — "dump completo
pro nosso lado").

Por que: o decil DA ÉPOCA (produção) de DEV20/LF54/LF55 só existe na `Lead` viva
do Railway — não está em parquet nem no ledger. Os parquets de backtest cobrem
LF45–53, o ledger cobre LF56+; a janela 30/04–17/05 (DEV20/LF54/LF55) só na Lead.
Esta cópia preserva a Lead INTEIRA (142.943 linhas), que é o material cru da
`leads_historico`.

Fiel: mesmas colunas da Lead (camelCase → snake_case), `pesquisa` como JSONB,
`decil` INTEGER. Idempotente: ON CONFLICT (id) DO NOTHING.

    python scripts/copy_lead_legado_cloudsql.py [--verify]
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# (coluna na Lead [camelCase, quoted no SELECT], coluna em lead_legado [snake], tipo DDL)
COLS = [
    ('id',            'id',            'TEXT PRIMARY KEY'),
    ('data',          'data',          'TIMESTAMP'),
    ('hora',          'hora',          'TEXT'),
    ('nomeCompleto',  'nome_completo', 'TEXT'),
    ('email',         'email',         'TEXT'),
    ('telefone',      'telefone',      'TEXT'),
    ('pesquisa',      'pesquisa',      'JSONB'),
    ('source',        'source',        'TEXT'),
    ('campaign',      'campaign',      'TEXT'),
    ('medium',        'medium',        'TEXT'),
    ('content',       'content',       'TEXT'),
    ('term',          'term',          'TEXT'),
    ('remoteIp',      'remote_ip',     'TEXT'),
    ('userAgent',     'user_agent',    'TEXT'),
    ('fbc',           'fbc',           'TEXT'),
    ('fbp',           'fbp',           'TEXT'),
    ('pageUrl',       'page_url',      'TEXT'),
    ('leadScore',     'lead_score',    'DOUBLE PRECISION'),
    ('decil',         'decil',         'INTEGER'),
    ('createdAt',     'created_at',    'TIMESTAMP'),
    ('updatedAt',     'updated_at',    'TIMESTAMP'),
    ('capiSentAt',    'capi_sent_at',  'TIMESTAMP'),
    ('capiStatus',    'capi_status',   'TEXT'),
]
SRC_COLS = [c[0] for c in COLS]   # nomes na Lead
DST_COLS = [c[1] for c in COLS]   # nomes em lead_legado
JSONB_COLS = {'pesquisa'}
BATCH = 500

DDL = (
    "CREATE TABLE IF NOT EXISTS lead_legado (\n  "
    + ",\n  ".join(f"{dst} {ddl}" for _, dst, ddl in COLS)
    + "\n)"
)
DDL_IDX = "CREATE INDEX IF NOT EXISTS idx_lead_legado_email ON lead_legado (lower(email))"


def _load_dotenv() -> None:
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def _railway():
    import pg8000.native
    return pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"], port=int(os.environ["RAILWAY_DB_PORT"]),
        database=os.environ["RAILWAY_DB_NAME"], user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"], timeout=120,
    )


def _cloudsql():
    import pg8000.native
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"], port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"], ssl_context=c, timeout=120,
    )


def _multi_insert_sql(n: int) -> str:
    tuples = []
    for i in range(n):
        vals = [
            (f":{dst}_{i}::jsonb" if dst in JSONB_COLS else f":{dst}_{i}")
            for dst in DST_COLS
        ]
        tuples.append("(" + ", ".join(vals) + ")")
    return (
        f"INSERT INTO lead_legado ({', '.join(DST_COLS)}) "
        f"VALUES {', '.join(tuples)} "
        f"ON CONFLICT (id) DO NOTHING"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="só compara contagens, não copia")
    args = ap.parse_args()
    _load_dotenv()

    rw, cs = _railway(), _cloudsql()
    try:
        src_total = rw.run('SELECT count(*) FROM "Lead"')[0][0]
        src_decil = rw.run('SELECT count(decil) FROM "Lead"')[0][0]
        if args.verify:
            cs.run(DDL)
            dst_total = cs.run("SELECT count(*) FROM lead_legado")[0][0]
            dst_decil = cs.run("SELECT count(decil) FROM lead_legado")[0][0]
            print(f"Railway Lead : {src_total} linhas · {src_decil} c/decil")
            print(f"lead_legado  : {dst_total} linhas · {dst_decil} c/decil")
            print("PARIDADE OK" if (src_total, src_decil) == (dst_total, dst_decil)
                  else "DIVERGE — re-rodar a cópia")
            return 0

        cs.run(DDL)
        cs.run(DDL_IDX)
        antes = cs.run("SELECT count(*) FROM lead_legado")[0][0]

        sel = ", ".join(f'"{src}"' for src in SRC_COLS)
        rows = rw.run(f'SELECT {sel} FROM "Lead" ORDER BY "id"')
        print(f"Railway Lead: {len(rows)} linhas a copiar (já em lead_legado: {antes})")

        feitas = 0
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            params = {}
            for j, row in enumerate(chunk):
                for k, dst in enumerate(DST_COLS):
                    v = row[k]
                    if dst in JSONB_COLS and v is not None and not isinstance(v, str):
                        v = json.dumps(v)
                    elif hasattr(v, "isoformat"):
                        v = v.isoformat()
                    params[f"{dst}_{j}"] = v
            cs.run(_multi_insert_sql(len(chunk)), **params)
            feitas += len(chunk)
            if feitas % 5000 < BATCH:
                print(f"  {feitas}/{len(rows)}...", flush=True)

        depois = cs.run("SELECT count(*) FROM lead_legado")[0][0]
        dst_decil = cs.run("SELECT count(decil) FROM lead_legado")[0][0]
        print(f"\n✅ lead_legado: {antes} → {depois} (+{depois - antes}) · {dst_decil} c/decil")
        print(f"   origem Railway: {src_total} linhas · {src_decil} c/decil")
        print("   PARIDADE OK" if (depois, dst_decil) == (src_total, src_decil)
              else "   ⚠️ DIVERGE — investigar")
        return 0
    finally:
        rw.close()
        cs.close()


if __name__ == "__main__":
    sys.exit(main())
