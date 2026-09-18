"""Fase 1 do refator 'decil dos 2 modelos no ledger' (V2/docs/interno/plano_decis_dois_modelos_ledger.md).

Adiciona ao `registros_ml` as colunas para gravar o score/decil dos DOIS modelos
(champion + challenger) + run_ids + auditoria, no momento do scoreamento online.
Additivo e nulo — NENHUM comportamento muda (nada escreve/lê essas colunas ainda).
Tipos casam com as colunas existentes (decil=integer, score=double precision).

Idempotente (ADD COLUMN IF NOT EXISTS). Reversível: `--rollback` dropa as 8 colunas.

Uso:
  python scripts/migrate_registros_ml_dual_decil.py            # aplica
  python scripts/migrate_registros_ml_dual_decil.py --rollback # desfaz
  python scripts/migrate_registros_ml_dual_decil.py --check    # só lista o estado
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# .env (creds do ledger Cloud SQL)
_envp = os.path.join(os.path.dirname(__file__), "..", ".env")
with open(_envp) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from src.data.ledger_connection import open_cloudsql_ledger_connection

# (coluna, tipo). Ordem = ordem de ADD. decil_* como INTEGER (casa com o `decil`
# roteado já existente — evita a classe de bug 'D01' vs 'D1'; formatação 'D0x' fica
# na renderização). run_id por LINHA (o ledger é 1 linha por event_id).
COLS = [
    ("score_champion",     "double precision"),
    ("score_challenger",   "double precision"),
    ("decil_champion",     "integer"),
    ("decil_challenger",   "integer"),
    ("champion_run_id",    "text"),
    ("challenger_run_id",  "text"),
    ("scored_at",          "timestamp without time zone"),
    ("core_commit",        "text"),
]


def _existing(conn) -> set:
    rows = conn.run(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='registros_ml'"
    )
    return {r[0] for r in rows}


def apply(conn):
    for name, typ in COLS:
        # ADD COLUMN IF NOT EXISTS: nulo, sem default → metadata-only no Postgres
        # (instantâneo, sem rewrite da tabela, mesmo grande).
        conn.run(f"ALTER TABLE registros_ml ADD COLUMN IF NOT EXISTS {name} {typ}")
    print("✅ aplicado (ADD COLUMN IF NOT EXISTS x%d)" % len(COLS))


def rollback(conn):
    for name, _ in COLS:
        conn.run(f"ALTER TABLE registros_ml DROP COLUMN IF EXISTS {name}")
    print("↩️  rollback (DROP COLUMN IF EXISTS x%d)" % len(COLS))


def check(conn):
    ex = _existing(conn)
    print("estado das 8 colunas no registros_ml:")
    for name, typ in COLS:
        print(f"  {'✓' if name in ex else '✗'} {name:<18} ({typ})")


if __name__ == "__main__":
    conn = open_cloudsql_ledger_connection()
    mode = sys.argv[1] if len(sys.argv) > 1 else "--apply"
    if mode == "--rollback":
        rollback(conn)
    elif mode == "--check":
        pass
    else:
        apply(conn)
    check(conn)
    print("DONE")
