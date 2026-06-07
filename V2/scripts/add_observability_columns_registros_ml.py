#!/usr/bin/env python3
"""Migração — colunas de observabilidade no `registros_ml` (Bloco E).

Adiciona 5 colunas aditivas em `registros_ml` que registram as decisões
de cada estratégia de decil e os eventos efetivamente disparados pra
Meta — base da observabilidade pro A/B implícito entre Propensão e
RoasV1 (Bloco F).

Colunas adicionadas:

  - `decile_propensity INTEGER`
      Decil que a estratégia de propensão atribuiu — o que existe hoje na
      coluna `decil`, mas explicitado como "vindo da propensão". Sempre
      populado pra todo lead que chega a ser scoreado.

  - `decile_roas_v1 INTEGER`
      Decil que a estratégia ROAS V1 atribuiu pelo retorno esperado por
      real gasto. NULL enquanto a estratégia estiver desabilitada
      (default até Bloco F entrar). Quando habilitada, permite comparar
      offline o ranking propensão × ranking ROAS no mesmo lead, pareado.

  - `cpl_source TEXT`
      Origem do CPL usado no cálculo da fórmula ROAS:
        adset    → encontrou linha no `cpl_adset` (caso bom)
        campaign → adset novo, caiu pra média da campanha
        global   → campanha também é nova, média do cliente
        missing  → lead sem campaign_id no UTM, fórmula não roda
      Mede cobertura da atribuição em produção. NULL pra leads
      pré-ativação ou que não rodaram pela estratégia ROAS.

  - `events_fired TEXT[]`
      Array com os nomes dos eventos primários efetivamente enviados pra
      Meta (`LeadQualified`, `LeadQualifiedHighQuality`,
      `LeadQualifiedHighQuality_ROAS_V1`, …). Auditoria do que saiu —
      complementa `base_status` e `hq_status` que ficam por evento.

  - `extra_hq_destinations_fired JSONB`
      Sub-array das cópias de fan-out que saíram, com `event_name` e
      `pixel_id` de cada cópia. Resolve a pendência §11.2 do
      `FAN_OUT_CAPI.md` — hoje o fan-out grava o resultado no retorno
      mas ninguém consome; passa a virar coluna queryable.
      Ex.: [{"event_name": "LeadQualifiedHighQuality", "pixel_id":
      "241752320666130"}].

Idempotente: usa ALTER TABLE ADD COLUMN IF NOT EXISTS — rodar N vezes =
mesmo estado. Não-destrutivo: nenhuma coluna existente é tocada.
Rollback: ALTER TABLE registros_ml DROP COLUMN <coluna>;

Credenciais: lê RAILWAY_DB_* do ambiente; se ausentes, carrega de um .env
apontado por RAILWAY_ENV_FILE, ou de scripts/../.env. Sem hardcode.

Uso:
  RAILWAY_ENV_FILE=/abs/V2/.env python scripts/add_observability_columns_registros_ml.py
  python scripts/add_observability_columns_registros_ml.py --verify-only
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


# Lista (coluna, tipo) — preserva ordem das migrações
NEW_COLUMNS = (
    ("decile_propensity",            "INTEGER"),
    ("decile_roas_v1",               "INTEGER"),
    ("cpl_source",                   "TEXT"),
    ("events_fired",                 "TEXT[]"),
    ("extra_hq_destinations_fired",  "JSONB"),
)


def _execute_ddl(conn: pg8000.native.Connection, *, verify_only: bool) -> int:
    if verify_only:
        rows = conn.run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'registros_ml' "
            "AND column_name IN ('decile_propensity','decile_roas_v1','cpl_source',"
            "'events_fired','extra_hq_destinations_fired') "
            "ORDER BY column_name"
        )
        found = [r[0] for r in rows]
        expected = sorted(c for c, _ in NEW_COLUMNS)
        missing = [c for c in expected if c not in found]
        if missing:
            print(f"[FAIL] colunas ausentes: {missing}")
            return 1
        print(f"[OK] {len(found)}/5 colunas presentes: {found}")
        return 0

    for i, (col, typ) in enumerate(NEW_COLUMNS, start=1):
        print(f"[{i}/{len(NEW_COLUMNS)}] ALTER TABLE registros_ml ADD COLUMN IF NOT EXISTS {col} {typ}…")
        conn.run(f"ALTER TABLE registros_ml ADD COLUMN IF NOT EXISTS {col} {typ}")
    print("[OK] migração idempotente concluída.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--verify-only", action="store_true",
        help="Não altera nada — só verifica que as colunas existem.",
    )
    args = p.parse_args()

    _load_env()
    required = ("RAILWAY_DB_HOST", "RAILWAY_DB_PORT", "RAILWAY_DB_USER",
                "RAILWAY_DB_PASSWORD", "RAILWAY_DB_NAME")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[FAIL] variáveis de ambiente ausentes: {missing}")
        return 2

    conn = pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ["RAILWAY_DB_PORT"]),
        user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"],
        database=os.environ["RAILWAY_DB_NAME"],
    )
    try:
        return _execute_ddl(conn, verify_only=args.verify_only)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
