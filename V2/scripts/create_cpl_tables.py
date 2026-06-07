#!/usr/bin/env python3
"""Migração — tabelas de atribuição de custo por lead (idempotente).

Tabelas NOSSAS (não Prisma) — base do lookup que alimenta a fórmula
`retorno_esperado = (probabilidade × ticket à vista) ÷ custo_por_lead`
da estratégia de decil por ROAS (Bloco F do EVENTOS_E_DECIS_PLANO).

  - `cpl_adset`  — custo médio por adset nos últimos 30 dias, 1 linha por
                   (cliente, adset). Refrescada 1×/dia por job batch.
  - `ad_to_adset_map` — tradutor (campaign_id, ad_name) → adset_id. UTM
                        que o lead carrega só dá esses dois primeiros; o
                        adset_id (granularidade da economia Meta) sai daqui.

Por que essas duas tabelas e não uma só: o mapeamento ad→adset muda
estruturalmente (gestor cria/move anúncio), o CPL muda diariamente. Razões
diferentes pra mudar = tabelas separadas. Vários anúncios compartilham um
CPL (porque competem pelo budget do mesmo adset); não vale repetir o número.

Por que Railway e não Cloud SQL `smart-ads-db`: scoring container já conecta
no Railway pra ler `registros_ml`. `smart-ads-db` fica parado entre treinos —
obrigá-lo a 24/7 só pra servir CPL custaria ~R$ 35/mês sem ganho operacional.

Idempotente: usa CREATE TABLE/INDEX IF NOT EXISTS — rodar N vezes = mesmo
estado. Não-destrutivo: não toca nenhuma tabela existente.
Rollback: DROP TABLE cpl_adset; DROP TABLE ad_to_adset_map;

Credenciais: lê RAILWAY_DB_* do ambiente; se ausentes, carrega de um .env
apontado por RAILWAY_ENV_FILE, ou de scripts/../.env. Sem hardcode de path.

Uso:
  RAILWAY_ENV_FILE=/abs/V2/.env python scripts/create_cpl_tables.py
  python scripts/create_cpl_tables.py --verify-only
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


DDL_CPL_ADSET = """
CREATE TABLE IF NOT EXISTS cpl_adset (
    client_id      TEXT          NOT NULL,
    adset_id       TEXT          NOT NULL,
    cpl_30d        NUMERIC       NOT NULL,                    -- R$ gastos ÷ leads trazidos na janela
    n_leads_30d    INTEGER       NOT NULL,
    spend_30d      NUMERIC       NOT NULL,
    campaign_id    TEXT          NOT NULL,                    -- referência p/ fallback "média da campanha"
    window_start   DATE          NOT NULL,
    window_end     DATE          NOT NULL,
    updated_at     TIMESTAMP     NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, adset_id)
);
"""

DDL_CPL_ADSET_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_cpl_adset_client_campaign "
    "ON cpl_adset (client_id, campaign_id);"
)

DDL_AD_TO_ADSET_MAP = """
CREATE TABLE IF NOT EXISTS ad_to_adset_map (
    client_id      TEXT          NOT NULL,
    campaign_id    TEXT          NOT NULL,
    ad_name        TEXT          NOT NULL,                    -- humano, vindo do UTM utm_content
    adset_id       TEXT          NOT NULL,                    -- Meta ad_set_id, joina em cpl_adset
    updated_at     TIMESTAMP     NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, campaign_id, ad_name)
);
"""

DDL_AD_TO_ADSET_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_ad_to_adset_client_adset "
    "ON ad_to_adset_map (client_id, adset_id);"
)


def _execute_ddl(conn: pg8000.native.Connection, *, verify_only: bool) -> int:
    if verify_only:
        rows = conn.run(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN ('cpl_adset', 'ad_to_adset_map') "
            "ORDER BY table_name"
        )
        found = [r[0] for r in rows]
        missing = [t for t in ('ad_to_adset_map', 'cpl_adset') if t not in found]
        if missing:
            print(f"[FAIL] tabelas ausentes: {missing}")
            return 1
        print(f"[OK] tabelas presentes: {found}")
        return 0

    print("[1/4] CREATE TABLE cpl_adset…")
    conn.run(DDL_CPL_ADSET)
    print("[2/4] CREATE INDEX idx_cpl_adset_client_campaign…")
    conn.run(DDL_CPL_ADSET_INDEX)
    print("[3/4] CREATE TABLE ad_to_adset_map…")
    conn.run(DDL_AD_TO_ADSET_MAP)
    print("[4/4] CREATE INDEX idx_ad_to_adset_client_adset…")
    conn.run(DDL_AD_TO_ADSET_INDEX)
    print("[OK] migração idempotente concluída.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--verify-only", action="store_true",
        help="Não cria nada — só verifica que as tabelas existem.",
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
