"""Fase 4 (backfill por CÓPIA) — traz o decil dos dois modelos que a
`scores_historicos` já calculou pra dentro do ledger `registros_ml`.

NÃO re-scoreia: a `scores_historicos` já tem `decil_champion`/`decil_challenger`
(mesmo scorer, mesmos run_ids pinados). Este script só COPIA esses valores pras
colunas dual do `registros_ml`, casando por email DENTRO DA JANELA DE CADA LF —
assim um lead que voltou em 2 lançamentos recebe, em cada evento, o decil do LF
correto (o `registros_ml` não tem coluna `lf`; a janela vem do `launches.yaml`).

Propriedades (data-architect):
  - Idempotente: só preenche onde `decil_challenger IS NULL` (não sobrescreve o
    que a Fase 2 já gravou ao vivo, nem uma cópia anterior).
  - Reversível: cada linha copiada leva `core_commit = 'backfill_fase4_copy'`;
    rollback = UPDATE ... = NULL WHERE core_commit = esse rótulo.
  - Escopo: só a JANELA DO LEDGER (leads de ~23/05/2026 pra frente já existem no
    registros_ml). LFs anteriores ao ledger NÃO têm linha aqui → não são
    alcançados (ficam na scores_historicos como arquivo). Sem INSERT de lead.
  - Régua única: copia só as linhas da scores_historicos no `challenger_run_id`
    pinado (abr28) — o mesmo que os relatórios filtram.

Modos:
  --dry-run   conta, por LF, quantas linhas SERIAM atualizadas + resíduo. Não escreve.
  (default)   aplica os UPDATEs.
  --audit     reconciliação de cobertura registros_ml × scores_historicos.
  --rollback  desfaz (zera as colunas onde core_commit = rótulo do backfill).

Rodar local:  carregar V2/.env; python scripts/backfill_dual_decil_from_scores_historicos.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import ssl
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pg8000.native

from src.core.launches import load_launches

BRT = timezone(timedelta(hours=-3))

# Run_ids pinados (o A/B vigente) — os MESMOS que os relatórios filtram. Copiar só
# estas linhas garante régua única. Champion jan30 / Challenger abr28.
CHAMPION_RUN_ID = "d51757f5041c44b7ab1a056fce8c3c35"
CHALLENGER_RUN_ID = "5d158f0aa6e54b489498470446194a6c"

CORE_COMMIT_LABEL = "backfill_fase4_copy"

# Colunas que a cópia preenche (decis TEXT 'D0x' → INT; scores DOUBLE diretos).
_SET_CLAUSE = (
    "decil_challenger = CAST(REPLACE(s.decil_challenger,'D','') AS INTEGER), "
    "decil_champion   = CASE WHEN s.decil_champion IS NULL THEN NULL "
    "                        ELSE CAST(REPLACE(s.decil_champion,'D','') AS INTEGER) END, "
    "score_challenger = s.score_challenger, "
    "score_champion   = s.score_champion, "
    "challenger_run_id = s.challenger_run_id, "
    "champion_run_id   = s.champion_run_id, "
    "core_commit = :label, "
    "scored_at = COALESCE(s.generated_at, NOW())"
)

# Subquery: 1 linha por email no LF (a mais recente), só no run_id pinado.
_SRC_SUBQUERY = (
    "( SELECT DISTINCT ON (lower(email)) lower(email) AS email_k, "
    "         decil_challenger, decil_champion, score_challenger, score_champion, "
    "         challenger_run_id, champion_run_id, generated_at "
    "  FROM scores_historicos "
    "  WHERE lf = :lf AND challenger_run_id = :crun AND decil_challenger IS NOT NULL "
    "  ORDER BY lower(email), generated_at DESC ) s"
)


def _conn():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"], port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"], ssl_context=ctx, timeout=120,
    )


def _lf_windows_utc():
    """[(lf_name, ws_utc_iso, we_utc_iso)] — janelas de captação BRT→UTC (fim exclusivo).
    Só LFs com cap_start/cap_end válidos. Ordena por cap_start."""
    out = []
    for name, cfg in (load_launches() or {}).items():
        cs_str, ce_str = cfg.get("cap_start"), cfg.get("cap_end")
        if not (cs_str and ce_str):
            continue
        try:
            cs = datetime.strptime(cs_str, "%Y-%m-%d").date()
            ce = datetime.strptime(ce_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        ws = datetime(cs.year, cs.month, cs.day, 0, 0, 0, tzinfo=BRT).astimezone(timezone.utc)
        we = (datetime(ce.year, ce.month, ce.day, 0, 0, 0, tzinfo=BRT)
              + timedelta(days=1)).astimezone(timezone.utc)
        out.append((name, ws.strftime("%Y-%m-%d %H:%M:%S"), we.strftime("%Y-%m-%d %H:%M:%S")))
    out.sort(key=lambda t: t[1])
    return out


def _count_would_update(c, lf, ws, we):
    """Quantos registros_ml (decil_challenger NULL) na janela do LF casam por email."""
    r = c.run(
        "SELECT count(*) FROM registros_ml r JOIN " + _SRC_SUBQUERY +
        " ON lower(r.email) = s.email_k "
        "WHERE r.created_at >= :ws AND r.created_at < :we AND r.decil_challenger IS NULL",
        lf=lf, crun=CHALLENGER_RUN_ID, ws=ws, we=we,
    )
    return int(r[0][0] or 0)


def _apply_lf(c, lf, ws, we):
    c.run(
        "UPDATE registros_ml r SET " + _SET_CLAUSE + " FROM " + _SRC_SUBQUERY +
        " WHERE lower(r.email) = s.email_k "
        "AND r.created_at >= :ws AND r.created_at < :we AND r.decil_challenger IS NULL",
        lf=lf, crun=CHALLENGER_RUN_ID, ws=ws, we=we, label=CORE_COMMIT_LABEL,
    )


def cmd_dry_run(c):
    wins = _lf_windows_utc()
    print(f"LFs no calendário: {len(wins)}\n")
    print(f"{'LF':10} {'janela (UTC)':40} {'copiaria':>9}")
    total = 0
    for lf, ws, we in wins:
        n = _count_would_update(c, lf, ws, we)
        total += n
        flag = "" if n else "  (0 — pré-ledger ou já preenchido)"
        print(f"{lf:10} {ws} → {we}  {n:>9}{flag}")
    print(f"\nTOTAL que a cópia preencheria: {total}")
    # resíduo: leads com pesquisa na janela do ledger que NÃO seriam cobertos
    resid = c.run(
        "SELECT count(*) FROM registros_ml "
        "WHERE survey_responses IS NOT NULL AND decil_challenger IS NULL "
        "AND created_at >= (SELECT min(created_at) FROM registros_ml)"
    )[0][0]
    print(f"(leads com pesquisa ainda sem decil_challenger no ledger inteiro, "
          f"pré-cópia: {resid} — o resíduo pós-cópia = estes menos o total acima)")


def cmd_apply(c):
    wins = _lf_windows_utc()
    print(f"Aplicando cópia em {len(wins)} LFs...\n")
    total = 0
    for lf, ws, we in wins:
        before = _count_would_update(c, lf, ws, we)
        if before == 0:
            continue
        _apply_lf(c, lf, ws, we)
        total += before
        print(f"  {lf:10} copiado ~{before}")
    print(f"\nTotal copiado: {total}")
    _audit(c)


def cmd_rollback(c):
    r = c.run(
        "UPDATE registros_ml SET decil_challenger=NULL, decil_champion=NULL, "
        "score_challenger=NULL, score_champion=NULL, challenger_run_id=NULL, "
        "champion_run_id=NULL, scored_at=NULL, core_commit=NULL "
        "WHERE core_commit = :label RETURNING 1",
        label=CORE_COMMIT_LABEL,
    )
    print(f"Rollback: {len(r) if r else 0} linhas revertidas (core_commit='{CORE_COMMIT_LABEL}').")


def _audit(c):
    print("\n=== Auditoria de cobertura ===")
    filled = c.run("SELECT count(*) FROM registros_ml WHERE decil_challenger IS NOT NULL")[0][0]
    by_online = c.run("SELECT count(*) FROM registros_ml WHERE decil_challenger IS NOT NULL "
                      "AND (core_commit IS NULL OR core_commit <> :label)", label=CORE_COMMIT_LABEL)[0][0]
    by_copy = c.run("SELECT count(*) FROM registros_ml WHERE core_commit = :label",
                    label=CORE_COMMIT_LABEL)[0][0]
    print(f"decil_challenger preenchido: {filled}  (cópia={by_copy}, online/Fase2={by_online})")
    # fill-rate por semana (pega buraco no meio)
    rows = c.run(
        "SELECT date_trunc('week', created_at)::date w, "
        "count(*) tot, count(decil_challenger) fill "
        "FROM registros_ml WHERE survey_responses IS NOT NULL "
        "GROUP BY 1 ORDER BY 1")
    print("fill-rate por semana (leads com pesquisa):")
    for w, tot, fill in rows:
        pct = (100 * fill // tot) if tot else 0
        bar = "" if pct >= 90 else "  <-- buraco" if pct < 50 else ""
        print(f"  {w}: {fill}/{tot} ({pct}%){bar}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--audit", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()
    c = _conn()
    try:
        if args.dry_run:
            cmd_dry_run(c)
        elif args.audit:
            _audit(c)
        elif args.rollback:
            cmd_rollback(c)
        else:
            cmd_apply(c)
    finally:
        c.close()


if __name__ == "__main__":
    main()
