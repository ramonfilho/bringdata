#!/usr/bin/env python3
"""Corrige no ledger os decis gravados durante o bug do público (10-14/08/2026).

CONTEXTO: em 10/08 a Meta trocou o utm_medium do rótulo de público para
'[ADVTG_ABERTO]<nome do anúncio>'. O modelo parou de enxergar a categoria
'Aberto' (49,9% do treino), a penalidade de público frio deixou de ser
aplicada e as notas INFLARAM (~54,7% dos leads no decil errado, quase todos
para cima). O fix (PR #190, passo 3b) entrou em produção em 14/08 ~10:23 UTC,
mas os decis GRAVADOS no período seguiram errados — inflando a previsão de
faturamento por ML (~+10%), o baseline de decis e qualquer análise do período.

DECISÃO (Ramon, 16/08): corrigir no banco, com backup do valor antigo.

O QUE FAZ:
1. Re-scoreia TODOS os leads scoreados da janela 09/08→15/08 (UTC) com o
   pipeline de produção ATUAL (pattern_mappings vivo) — o mesmo caminho, o
   mesmo primitivo (`score_leads_from_payloads`) do script validado do
   incidente (`analise_qualidade_publico.py`).
2. CONTROLE FAIL-LOUD: os leads scoreados APÓS o fix (>= 14/08 12:00 UTC)
   têm que reproduzir o decil gravado em 100%. Qualquer divergência = a
   reconstrução do payload não é fiel = ABORTA sem escrever nada.
3. Atualiza SOMENTE as linhas cujo recompute divergiu (por construção, as
   scoreadas antes do fix com o medium novo), gravando o valor antigo em
   `pre_correcao_advtg` (jsonb) ANTES — idempotente: o backup só é escrito
   uma vez (COALESCE), rodar de novo não o sobrescreve.

O QUE NÃO FAZ: não mexe em `variant` (o roteamento não mudou), não reenvia
evento ao Meta (o que foi enviado é história), não toca leads fora da janela.

Uso:
    python3 scripts/corrigir_decis_advtg_1008.py            # dry-run (só mede)
    python3 scripts/corrigir_decis_advtg_1008.py --execute  # aplica
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("corrigir_decis")

JANELA_INI = "2026-08-09 00:00:00+00"
JANELA_FIM = "2026-08-15 00:00:00+00"
# O fix (PR #190) foi promovido 14/08 10:23 UTC; 12:00 dá folga de sobra.
CONTROLE_INI = "2026-08-14 12:00:00+00"
LOTE = 400

META = {"id", "ip", "clientEmail", "submittedAt"}


def payload(r):
    """Reconstrói o payload original do lead — MESMA função do script validado
    do incidente (analise_qualidade_publico.py), que fechou controle em 100%."""
    sr = r[1] if not isinstance(r[1], str) else json.loads(r[1])
    return {
        "eventId": r[16] or sr.get("id"), "submittedAt": sr.get("submittedAt"),
        "email": r[0], "ip4": r[12] or sr.get("ip"), "phone": r[13],
        "firstName": r[14], "lastName": r[15], "hasComputer": r[8],
        "fbp": r[9], "fbc": r[10], "userAgent": r[11],
        "survey": {k: v for k, v in sr.items() if k not in META},
        "utm": {"source": r[2], "medium": r[3], "campaign": r[4],
                "content": r[5], "term": r[6], "url": r[7]},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="aplica as correções (default: dry-run, só mede)")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    from src.data.ledger_connection import open_cloudsql_ledger_connection
    from src.production_pipeline import LeadScoringPipeline
    from src.scoring.service import score_leads_from_payloads, LinhasPerdidasNoPreprocess

    conn = open_cloudsql_ledger_connection()

    brutos = conn.run(f"""
        SELECT email, survey_responses, utm_source, utm_medium, utm_campaign, utm_content,
               utm_term, utm_url, has_computer, fbp, fbc, user_agent, ip, phone,
               first_name, last_name, event_id, created_at,
               lead_score, decil, score_champion, decil_champion,
               score_challenger, decil_challenger
        FROM registros_ml
        WHERE created_at >= '{JANELA_INI}' AND created_at < '{JANELA_FIM}'
          AND survey_responses IS NOT NULL AND lead_score IS NOT NULL
        ORDER BY created_at
    """)
    logger.info("Leads scoreados na janela %s → %s: %d",
                JANELA_INI[:10], JANELA_FIM[:10], len(brutos))

    pipeline = LeadScoringPipeline()
    ctrl_ini = datetime.fromisoformat(CONTROLE_INI)

    novos = {}   # event_id -> exp
    for i in range(0, len(brutos), LOTE):
        chunk = brutos[i:i + LOTE]
        try:
            exps = score_leads_from_payloads([payload(r) for r in chunk], pipeline)
        except LinhasPerdidasNoPreprocess:
            exps = []
            for r in chunk:
                try:
                    exps += score_leads_from_payloads([payload(r)], pipeline)
                except Exception:  # noqa: BLE001
                    exps.append(None)
        for r, e in zip(chunk, exps):
            if e is not None and r[16]:
                novos[r[16]] = e
        logger.info("  re-scoreados %d/%d", min(i + LOTE, len(brutos)), len(brutos))

    # ── CONTROLE: pós-fix tem que reproduzir 100% ─────────────────────────────
    ctrl_tot = ctrl_ok = 0
    for r in brutos:
        created = r[17] if r[17].tzinfo else r[17].replace(tzinfo=timezone.utc)
        if created < ctrl_ini:
            continue
        e = novos.get(r[16])
        if e is None or r[19] is None:
            continue
        ctrl_tot += 1
        ctrl_ok += int(int(e.decil) == int(r[19]))
    logger.info("CONTROLE pós-fix: %d/%d decis reproduzidos", ctrl_ok, ctrl_tot)
    if ctrl_tot == 0 or ctrl_ok != ctrl_tot:
        logger.error("[ABORTADO] Controle não fechou 100%% — a reconstrução não é "
                     "fiel ao que a produção fez. NADA foi escrito.")
        conn.close()
        return 1

    # ── Diferenças ────────────────────────────────────────────────────────────
    difere, desceu, subiu = [], 0, 0
    for r in brutos:
        e = novos.get(r[16])
        if e is None:
            continue
        muda = (
            (r[19] is not None and int(e.decil) != int(r[19]))
            or (r[21] is not None and e.decil_champion is not None
                and int(e.decil_champion) != int(r[21]))
            or (r[23] is not None and e.decil_challenger is not None
                and int(e.decil_challenger) != int(r[23]))
        )
        if muda:
            difere.append((r, e))
            if r[19] is not None:
                desceu += int(int(e.decil) < int(r[19]))
                subiu += int(int(e.decil) > int(r[19]))

    def _pct_d910(valores):
        v = [d for d in valores if d is not None]
        return 100.0 * sum(1 for d in v if int(d) >= 9) / len(v) if v else 0.0

    antes = _pct_d910([r[19] for r in brutos])
    depois = _pct_d910([
        (novos[r[16]].decil if r[16] in novos else r[19]) for r in brutos])
    logger.info("")
    logger.info("A CORRIGIR: %d leads (decil roteado: %d descem, %d sobem)",
                len(difere), desceu, subiu)
    logger.info("%%D9-D10 da janela: %.2f%% gravado → %.2f%% corrigido", antes, depois)

    if not args.execute:
        logger.info("\n[dry-run] Nada escrito. Rode com --execute para aplicar.")
        conn.close()
        return 0

    # ── Escrita: backup uma vez (COALESCE) + seis colunas ────────────────────
    conn.run("ALTER TABLE registros_ml ADD COLUMN IF NOT EXISTS pre_correcao_advtg jsonb")
    agora = datetime.now(timezone.utc).isoformat()
    n = 0
    for r, e in difere:
        backup = json.dumps({
            "lead_score": r[18], "decil": r[19],
            "score_champion": r[20], "decil_champion": r[21],
            "score_challenger": r[22], "decil_challenger": r[23],
            "corrigido_em": agora, "motivo": "advtg_1008",
        })
        conn.run(
            """
            UPDATE registros_ml SET
              pre_correcao_advtg = COALESCE(pre_correcao_advtg, :b::jsonb),
              lead_score = :ls, decil = :d,
              score_champion = :sc, decil_champion = :dc,
              score_challenger = :sl, decil_challenger = :dl
            WHERE event_id = :e
            """,
            b=backup, ls=float(e.lead_score), d=int(e.decil),
            sc=(float(e.score_champion) if e.score_champion is not None else None),
            dc=(int(e.decil_champion) if e.decil_champion is not None else None),
            sl=(float(e.score_challenger) if e.score_challenger is not None else None),
            dl=(int(e.decil_challenger) if e.decil_challenger is not None else None),
            e=r[16],
        )
        n += 1
        if n % LOTE == 0:
            conn.run("COMMIT")
            logger.info("  gravados %d/%d", n, len(difere))
    conn.run("COMMIT")
    logger.info("CONCLUÍDO: %d leads corrigidos, backup em pre_correcao_advtg.", n)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
