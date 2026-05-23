"""[DEPRECATED 2026-05-23 — substituído por api/pubsub_branch.py]

Arquitetura antiga (I4 da frente capi-lead-surveys, paused 2026-05-19):
lia a `lead_surveys` no Railway, dependia de `api/survey_enrichment.py`
(parse de `integration_logs`). Foi substituída pela arquitetura Pub/Sub
quando o sistema novo do dono passou a publicar todos os campos no payload
(hasComputer/fbp/fbc/firstName/lastName/phone/userAgent/ip), eliminando a
necessidade de leitura Railway + parse de log.

Não é importado por nada no caminho Pub/Sub. Mantido temporariamente para
referência histórica do design (commits I1–I4 da frente capi-lead-surveys).

— histórico original abaixo —

I4 — Ramo isolado `lead_surveys` → CAPI scoreado.

Roda DENTRO de `/railway/process-pending`, depois do fluxo `Lead` (intocado),
chamado por um helper em `app.py` envolto em try/except que NUNCA propaga.
Off por padrão via env `SURVEY_CAPI_ENABLED` (deploy ≠ ligar).

Fluxo por ciclo de polling:
  1. SELECT lead_surveys não no ledger `registros_ml`, `submittedAt` nas
     últimas `cutoff_hours` (recuperação de 24h + forward), LIMIT `batch`.
  2. `enrich_survey_batch` (I3) → utm/enrich/meta_eligible.
  3. Classifica cada lead:
       - não meta_eligible            → ledger `skipped_allowlist`
       - meta sem computador/fbp/fbc  → ledger `skipped_missing_data`
       - senão                        → scoreia e envia
  4. Mapa I2 → MESMO pipeline.run()/A-B/atribuir_decil + MESMO
     send_batch_events do `Lead` (nada de scoring/CAPI reimplementado).
  5. event_id determinístico `survey_<id>` → send_batch_events prefixa
     `qualified_`/`hq_` → `qualified_survey_<id>` / `hq_survey_<id>`.
  6. Grava desfecho no ledger `registros_ml` (por lead).

`dry_run`: scoreia + monta + loga, NÃO chama Meta e NÃO grava ledger
(idêntico em espírito ao dry_run do fluxo Lead). Para validação no canary 0%.

Reuso total: `pipeline.run`, `pipeline.get_ab_variant`,
`pipeline.get_variant_predictor`, `atribuir_decil_por_threshold`,
`send_batch_events` — os mesmos do `Lead`. Garante Gate C.1/C.2.
"""
import logging
import os
import tempfile
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from api.survey_enrichment import enrich_survey_batch
from api.survey_mapping import survey_lead_to_sheets_row

# pandas, send_batch_events e atribuir_decil_por_threshold são importados
# lazy dentro de process_pending_surveys — evita puxar o SDK do Facebook
# (init no import de capi_integration) só pra testar as funções puras.

logger = logging.getLogger(__name__)

DEFAULT_BATCH = 25
DEFAULT_CUTOFF_HOURS = 24

# Colunas de resposta da pesquisa lidas da lead_surveys (entram no I2).
_SURVEY_COLS = (
    "genero", "idade", "ocupacao", "faixaSalarial", "cartaoCredito",
    "estudouProgramacao", "faculdade", "investiuCurso", "atracaoProfissao",
    "interesseEvento",
)


def is_enabled() -> bool:
    """Chave geral. Off por padrão — deploy/promover NÃO liga."""
    return os.environ.get("SURVEY_CAPI_ENABLED", "false").strip().lower() == "true"


def classify(meta_eligible: bool, enrich: Dict) -> str:
    """Pura. 'skipped_allowlist' | 'skipped_missing_data' | 'send'."""
    if not meta_eligible:
        return "skipped_allowlist"
    if not (enrich.get("computador") and enrich.get("fbp") and enrich.get("fbc")):
        return "skipped_missing_data"
    return "send"


def survey_event_id(lead_id: str) -> str:
    """Determinístico e namespaced. send_batch_events prefixa qualified_/hq_."""
    return f"survey_{lead_id}"


def ledger_row(
    lead_id: str,
    email: Optional[str],
    variant: Optional[str],
    lead_score: Optional[float],
    decil: Optional[int],
    base_status: str,
    *,
    base_meta_event_id: Optional[str] = None,
    hq_meta_event_id: Optional[str] = None,
    hq_status: Optional[str] = None,
    capi_sent_at_now: bool = False,
    error_message: Optional[str] = None,
) -> Dict:
    """Pura. Monta o dict do INSERT em registros_ml."""
    return {
        "lead_id": lead_id,
        "email": email,
        "variant": variant,
        "lead_score": lead_score,
        "decil": decil,
        "base_meta_event_id": base_meta_event_id,
        "base_status": base_status,
        "hq_meta_event_id": hq_meta_event_id,
        "hq_status": hq_status,
        "capi_sent_at_now": capi_sent_at_now,
        "error_message": error_message,
    }


def _insert_ledger(conn, r: Dict) -> None:
    conn.run(
        'INSERT INTO registros_ml '
        '(lead_id, email, variant, lead_score, decil, base_meta_event_id, '
        ' base_status, hq_meta_event_id, hq_status, capi_sent_at, error_message) '
        'VALUES (:lead_id, :email, :variant, :lead_score, :decil, '
        ' :base_meta_event_id, :base_status, :hq_meta_event_id, :hq_status, '
        + ('NOW()' if r.pop("capi_sent_at_now", False) else 'NULL')
        + ', :error_message) ON CONFLICT (lead_id) DO NOTHING',
        **r,
    )


def _variant_name(pipeline, ab_variant) -> Optional[str]:
    if not ab_variant:
        return None
    return next(
        (n for n, v in pipeline._ab_test_config.variants.items() if v is ab_variant),
        None,
    )


def process_pending_surveys(
    conn,
    pipeline,
    *,
    dry_run: bool = False,
    batch: int = DEFAULT_BATCH,
    cutoff_hours: int = DEFAULT_CUTOFF_HOURS,
) -> Dict:
    """Lê → enriquece → classifica → scoreia → envia → grava ledger.
    Não levanta pra fora (o helper do app.py captura), mas erros por-lead
    são contidos e logados; o lote segue."""
    import pandas as pd
    from api.capi_integration import send_batch_events
    from src.model.decil_thresholds import atribuir_decil_por_threshold

    cols = ", ".join(f's."{c}"' for c in _SURVEY_COLS)
    rows = conn.run(
        f'SELECT s.id, s."clientEmail", s."eventId", s."submittedAt", s.ip, {cols} '
        'FROM lead_surveys s '
        'LEFT JOIN registros_ml r ON r.lead_id = s.id '
        'WHERE r.lead_id IS NULL '
        f'  AND s."submittedAt" >= NOW() - INTERVAL \'{int(cutoff_hours)} hours\' '
        f'ORDER BY s."submittedAt" ASC LIMIT {int(batch)}'
    )
    if not rows:
        return {"processed": 0, "sent": 0, "skipped_allowlist": 0,
                "skipped_missing_data": 0, "errors": 0, "dry_run": dry_run}

    colnames = ["id", "clientEmail", "eventId", "submittedAt", "ip", *_SURVEY_COLS]
    survey_rows = [dict(zip(colnames, r)) for r in rows]

    by_id, cov = enrich_survey_batch(conn, [
        {"id": s["id"], "clientEmail": s["clientEmail"], "eventId": s["eventId"],
         "submittedAt": s["submittedAt"], "ip": s["ip"]} for s in survey_rows
    ])

    # Classificar + separar quem vai scorear
    to_score: List[Tuple[Dict, Dict]] = []   # (survey_row, enr)
    pending_ledger: List[Dict] = []
    n_allow = n_missing = n_err = 0
    for s in survey_rows:
        enr = by_id.get(s["id"]) or {"utm": {}, "enrich": {}, "meta_eligible": False}
        verdict = classify(enr["meta_eligible"], enr["enrich"])
        if verdict == "skipped_allowlist":
            n_allow += 1
            pending_ledger.append(ledger_row(
                s["id"], s.get("clientEmail"), None, None, None, "skipped_allowlist"))
        elif verdict == "skipped_missing_data":
            n_missing += 1
            pending_ledger.append(ledger_row(
                s["id"], s.get("clientEmail"), None, None, None, "skipped_missing_data"))
        else:
            to_score.append((s, enr))

    # Scoring por variante (mesmo padrão do fluxo Lead)
    scored: Dict[str, Tuple[float, str, object, Optional[str]]] = {}  # id → (score, decil_str, ab_v, vname)
    if to_score:
        sheets, idmap, ab_per, vname_per = [], [], [], []
        for s, enr in to_score:
            sr = survey_lead_to_sheets_row(s, enr["utm"], enr["enrich"],
                                           client_config=pipeline._client_config)
            utm = enr["utm"] or {}
            ab_v = pipeline.get_ab_variant(
                {"utm_campaign": utm.get("campaign"), "utm_content": utm.get("content"),
                 "utm_source": utm.get("source"), "utm_medium": utm.get("medium"),
                 "utm_term": utm.get("term")},
                event_source_url=utm.get("url"),
            )
            sheets.append(sr)
            idmap.append(s["id"])
            ab_per.append(ab_v)
            vname_per.append(_variant_name(pipeline, ab_v))

        groups = defaultdict(list)
        for i, vn in enumerate(vname_per):
            groups[vn].append(i)
        for vn, idxs in groups.items():
            predictor_ov = pipeline.get_variant_predictor(vn) if vn else pipeline.predictor
            if vn:
                vcfg = pipeline._ab_test_config.variants.get(vn)
            else:
                crid = getattr(pipeline.predictor, "mlflow_run_id", None)
                vcfg = next((v for v in pipeline._ab_test_config.variants.values()
                             if v.run_id == crid), None) if crid else None
            enc_ov = vcfg.encoding_overrides if vcfg else None
            gdf = pd.DataFrame([sheets[i] for i in idxs])
            tmp = None
            res = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
                    gdf.to_csv(f, index=False)
                    tmp = f.name
                res = pipeline.run(tmp, with_predictions=True,
                                   predictor_override=predictor_ov, encoding_overrides=enc_ov)
            finally:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            if res is None or len(res) == 0:
                logger.warning(f"[survey_branch] pipeline vazio p/ grupo {vn}")
                continue
            thr = predictor_ov.metadata.get("decil_thresholds", {}).get("thresholds", {})
            for j, oi in enumerate(idxs):
                try:
                    sc = float(res["lead_score"].iloc[j])
                    dc = atribuir_decil_por_threshold(sc, thr) if thr else "D05"
                    scored[idmap[oi]] = (sc, dc, ab_per[oi], vname_per[oi])
                except Exception as e:
                    n_err += 1
                    logger.warning(f"[survey_branch] erro score {idmap[oi]}: {e}")

    # Montar CAPI + linhas de ledger dos enviáveis
    capi_leads: List[Dict] = []
    capi_meta: List[Tuple[Dict, str, Optional[int], Optional[str]]] = []  # (survey, decil_str, decil_int, vname)
    for s, enr in to_score:
        sid = s["id"]
        if sid not in scored:
            n_err += 1
            pending_ledger.append(ledger_row(
                sid, s.get("clientEmail"), None, None, None, "error",
                error_message="sem score"))
            continue
        sc, dc, ab_v, vn = scored[sid]
        nome = (enr["enrich"].get("nome") or "").strip()
        parts = nome.split(" ", 1)
        cl = {
            "_railway_id": sid,
            "email": s.get("clientEmail"),
            "phone": enr["enrich"].get("telefone"),
            "first_name": parts[0] if parts and parts[0] else None,
            "last_name": parts[1] if len(parts) > 1 else None,
            "lead_score": sc,
            "decil": dc,
            "event_id": survey_event_id(sid),
            "fbp": enr["enrich"].get("fbp"),
            "fbc": enr["enrich"].get("fbc"),
            "user_agent": enr["enrich"].get("user_agent"),
            "client_ip": enr["enrich"].get("ip"),
            "event_source_url": (enr["utm"] or {}).get("url"),
            "event_timestamp": int(time.time()) - 60,
            "survey_data": None,
        }
        if ab_v:
            cl["ab_event_name"] = ab_v.capi_event_name
            cl["ab_event_name_hq"] = ab_v.capi_event_name_high_quality
            cl["ab_conversion_rates"] = ab_v.conversion_rates
            cl["ab_pixel_id"] = ab_v.pixel_id_override
        capi_leads.append(cl)
        capi_meta.append((s, dc, int(dc[1:]) if dc else None, vn))

    sent = 0
    if capi_leads and not dry_run:
        res = send_batch_events(capi_leads, db=None,
                                capi_config=pipeline._client_config.capi,
                                business_config=pipeline._client_config.business,
                                client_id=pipeline._client_config.client_id)
        details = res.get("details", [])
        sent = res.get("success", 0)
        for i, (s, dc, di, vn) in enumerate(capi_meta):
            ok = i < len(details) and details[i].get("status") == "success"
            st = "success" if ok else "error"
            hq = "success" if (ok and di and di >= 9) else (None if not (di and di >= 9) else "error")
            pending_ledger.append(ledger_row(
                s["id"], s.get("clientEmail"), vn,
                capi_leads[i]["lead_score"], di, st,
                base_meta_event_id=f"qualified_{capi_leads[i]['event_id']}",
                hq_meta_event_id=(f"hq_{capi_leads[i]['event_id']}" if di and di >= 9 else None),
                hq_status=hq, capi_sent_at_now=ok,
                error_message=(None if ok else (details[i].get("error") if i < len(details) else "sem retorno")),
            ))
    elif capi_leads and dry_run:
        logger.info(f"🧪 [survey_branch] dry_run — {len(capi_leads)} CAPI montados, NÃO enviados")

    # Persistir ledger (dry_run não grava — permite re-rodar a validação)
    if not dry_run:
        for r in pending_ledger:
            try:
                _insert_ledger(conn, r)
            except Exception as e:
                logger.warning(f"[survey_branch] erro ledger {r.get('lead_id')}: {e}")

    summary = {
        "processed": len(survey_rows),
        "sent": sent,
        "skipped_allowlist": n_allow,
        "skipped_missing_data": n_missing,
        "errors": n_err,
        "dry_run": dry_run,
        "coverage": cov,
    }
    logger.info(f"🧩 [survey_branch] {summary}")
    return summary
