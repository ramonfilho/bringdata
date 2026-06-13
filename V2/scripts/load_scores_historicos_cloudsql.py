#!/usr/bin/env python3
"""
load_scores_historicos_cloudsql.py — Etapa 2b (parte scores) do
PLANO_LEDGER_CLOUDSQL.md.

Carrega os re-scores de 2026 (scores_2026_por_lead.csv, gerado por
scripts/gerar_scores_2026.py com o código ATUAL) na tabela `scores_historicos`
do Cloud SQL `ledger`, COM CHAVE DE VERSÃO (run_ids dos modelos + commit do
core/). É a materialização versionada do cache que o item L5 do plano de
remediação de score pede — e a fonte do baseline da regra de desvio de score
quando a tabela morta `Lead` secar (PLANO_LEDGER_CLOUDSQL.md §5 #1).

Re-rodar com novo modelo/código cria linhas novas (UNIQUE por
email+lf+run_ids) — versões coexistem, nada é sobrescrito.

    python scripts/load_scores_historicos_cloudsql.py \
        --champion-run d51757f5041c44b7ab1a056fce8c3c35 \
        --challenger-run 5d158f0aa6e54b489498470446194a6c \
        --core-commit 3227eed
"""
from __future__ import annotations

import argparse
import os
import ssl
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_DEFAULT = PROJECT_ROOT / "outputs" / "validation" / "scores_2026" / "scores_2026_por_lead.csv"

DDL = """
CREATE TABLE IF NOT EXISTS scores_historicos (
    id                 BIGSERIAL PRIMARY KEY,
    email              TEXT NOT NULL,
    lf                 TEXT NOT NULL,
    mes_lancamento     TEXT,
    vendas_inicio      DATE,
    vendas_estimada    BOOLEAN,
    data_captura       TIMESTAMP,
    semana_captacao    TEXT,
    score_champion     DOUBLE PRECISION,
    decil_champion     TEXT,
    score_challenger   DOUBLE PRECISION,
    decil_challenger   TEXT,
    champion_run_id    TEXT NOT NULL,
    challenger_run_id  TEXT NOT NULL,
    core_commit        TEXT,
    generated_at       TIMESTAMP,
    UNIQUE (email, lf, champion_run_id, challenger_run_id)
)
"""
DDL_IDX = "CREATE INDEX IF NOT EXISTS idx_scores_hist_lf ON scores_historicos (lf)"

INSERT_COLS = [
    "email", "lf", "mes_lancamento", "vendas_inicio", "vendas_estimada",
    "data_captura", "semana_captacao", "score_champion", "decil_champion",
    "score_challenger", "decil_challenger", "champion_run_id",
    "challenger_run_id", "core_commit", "generated_at",
]
BATCH = 500


def _load_dotenv() -> None:
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def _cloudsql():
    import pg8000.native
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"],
        port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"], ssl_context=c, timeout=60,
    )


def _multi_insert_sql(n: int) -> str:
    tuples = [
        "(" + ", ".join(f":{c}_{i}" for c in INSERT_COLS) + ")"
        for i in range(n)
    ]
    return (
        f"INSERT INTO scores_historicos ({', '.join(INSERT_COLS)}) "
        f"VALUES {', '.join(tuples)} "
        f"ON CONFLICT (email, lf, champion_run_id, challenger_run_id) DO NOTHING"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(CSV_DEFAULT))
    ap.add_argument("--champion-run", required=True)
    ap.add_argument("--challenger-run", required=True)
    ap.add_argument("--core-commit", required=True)
    args = ap.parse_args()
    _load_dotenv()

    df = pd.read_csv(args.csv)
    gen = pd.Timestamp.fromtimestamp(Path(args.csv).stat().st_mtime)
    df = df.assign(
        champion_run_id=args.champion_run,
        challenger_run_id=args.challenger_run,
        core_commit=args.core_commit,
        generated_at=gen,
    )
    # NaN/NaT → None pro driver; datas como string ISO (pg8000 + CAST implícito)
    df["data_captura"] = pd.to_datetime(df["data_captura"], errors="coerce")
    df = df.astype(object).where(pd.notna(df), None)
    print(f"{len(df)} linhas do CSV ({df['lf'].nunique()} LFs)")

    cs = _cloudsql()
    try:
        cs.run(DDL)
        cs.run(DDL_IDX)
        antes = cs.run("SELECT count(*) FROM scores_historicos")[0][0]
        recs = df[INSERT_COLS].to_dict("records")
        feitas = 0
        for i in range(0, len(recs), BATCH):
            chunk = recs[i:i + BATCH]
            params = {}
            for j, rec in enumerate(chunk):
                for col in INSERT_COLS:
                    v = rec[col]
                    if hasattr(v, "isoformat"):
                        v = v.isoformat()
                    params[f"{col}_{j}"] = v
            cs.run(_multi_insert_sql(len(chunk)), **params)
            feitas += len(chunk)
            print(f"  {feitas}/{len(recs)}...", flush=True)
        depois = cs.run("SELECT count(*) FROM scores_historicos")[0][0]
        print(f"\n✅ scores_historicos: {antes} → {depois} (+{depois - antes})")
        print("  por LF:")
        for r in cs.run("SELECT lf, count(*) FROM scores_historicos GROUP BY lf ORDER BY min(vendas_inicio)"):
            print(f"    {r[0]}: {r[1]}")
        return 0
    finally:
        cs.close()


if __name__ == "__main__":
    sys.exit(main())
