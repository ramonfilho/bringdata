#!/usr/bin/env python3
"""
backfill_scores_lf57_59.py — backfill pontual (1×) da tabela scores_historicos
(Cloud SQL) pros lançamentos que ficaram de fora do backfill de 12/06: LF57,
LF58 e LF59. Reusa as funções já provadas de gerar_scores_2026 (load + re-score
dos 2 modelos) e o upsert idempotente de load_scores_historicos_cloudsql.

NÃO regenera LF43-56 (já estão na tabela). ON CONFLICT DO NOTHING garante que
re-rodar é seguro. Depois disso o job online (06:00) mantém incremental.

    python scripts/backfill_scores_lf57_59.py --core-commit 7fa8019
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from gerar_scores_2026 import (  # noqa: E402
    CHAMPION_RUN, CHALLENGER_RUN, load_leads_for_launch, score_with_model,
)
from load_scores_historicos_cloudsql import (  # noqa: E402
    BATCH, INSERT_COLS, _cloudsql, _load_dotenv, _multi_insert_sql, DDL, DDL_IDX,
)

# (nome, cap_start, cap_end, vendas_start, vendas_estimada) — fonte sempre ledger.
# Mesmas janelas de gerar_scores_2026.LAUNCHES; LF59 adicionado (cadência semanal,
# captação 15-21/06; vendas estimadas +14d). LF59 ainda em captação → pega o que
# houver até agora; o job online completa.
LAUNCHES = [
    ("LF57", "2026-06-01", "2026-06-07", "2026-06-15", True),
    ("LF58", "2026-06-08", "2026-06-14", "2026-06-22", True),
    ("LF59", "2026-06-15", "2026-06-21", "2026-06-29", True),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core-commit", required=True)
    args = ap.parse_args()
    _load_dotenv()

    gen = pd.Timestamp.now()
    frames = []
    for nome, cap_s, cap_e, ven_s, ven_est in LAUNCHES:
        print(f"\n=== {nome} (captação {cap_s} a {cap_e} | ledger) ===", flush=True)
        leads = load_leads_for_launch(nome, cap_s, cap_e, "ledger")
        if len(leads) == 0:
            print(f"  ⚠️ {nome}: 0 leads — pulando", flush=True)
            continue
        print(f"  {len(leads)} leads únicos", flush=True)
        champion = score_with_model(leads, CHAMPION_RUN, "champion")
        print(f"  champion scorado: {champion['score_champion'].notna().sum()}", flush=True)
        challenger = score_with_model(leads, CHALLENGER_RUN, "challenger")
        print(f"  challenger scorado: {challenger['score_challenger'].notna().sum()}", flush=True)

        out = leads[["email", "data_captura"]].copy()
        out["lf"] = nome
        out["mes_lancamento"] = ven_s[:7]
        out["vendas_inicio"] = ven_s
        out["vendas_estimada"] = ven_est
        iso = out["data_captura"].dt.isocalendar()
        out["semana_captacao"] = (
            iso["year"].astype("Int64").astype(str) + "-W"
            + iso["week"].astype("Int64").astype(str).str.zfill(2)
        )
        out = out.merge(champion, on="email", how="left")
        out = out.merge(challenger, on="email", how="left")
        out["champion_run_id"] = CHAMPION_RUN
        out["challenger_run_id"] = CHALLENGER_RUN
        out["core_commit"] = args.core_commit
        out["generated_at"] = gen
        frames.append(out)

    if not frames:
        print("Nenhum lead pra inserir.")
        return 1

    df = pd.concat(frames, ignore_index=True)
    df["data_captura"] = pd.to_datetime(df["data_captura"], errors="coerce")
    df = df.astype(object).where(pd.notna(df), None)
    print(f"\n{len(df)} linhas pra upsert ({df['lf'].nunique()} LFs)")

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
        for r in cs.run("SELECT lf, count(*) FROM scores_historicos WHERE lf IN ('LF57','LF58','LF59') GROUP BY lf ORDER BY lf"):
            print(f"    {r[0]}: {r[1]}")
        return 0
    finally:
        cs.close()


if __name__ == "__main__":
    sys.exit(main())
