"""Consumer Pub/Sub — sistema novo (formato slug) → CAPI scoreado.

Arquitetura nova (2026-05-23). Substitui:
  - api/survey_branch.py     (lia lead_surveys no Railway)            [DEPRECATED]
  - api/survey_enrichment.py (parse de integration_logs/JOIN frágil)  [DEPRECATED]

Fluxo por chamada (Cloud Scheduler aciona N vezes ao dia):
  1. subscriber.pull(batch=N) na sub `lead-capture-ingest-sub`.
  2. Para cada mensagem:
       parse JSON → traduz_slugs(survey) → monta dict-Lead via I2
       → classifica (meta_eligible / missing_data / send)
       → scoreia (pipeline.run — mesmo do fluxo Lead)
       → CAPI (send_batch_events — mesmo do fluxo Lead)
       → ledger registros_ml (PK event_id, ON CONFLICT DO NOTHING)
       → ack a mensagem na sub.

`dry_run`: scoreia + monta CAPI + loga, NÃO envia Meta, NÃO grava ledger,
NÃO acka mensagens — permite re-rodar contra o mesmo backlog em canary.

Off por padrão via env `PUBSUB_CAPI_ENABLED`. Deploy ≠ ligar.

Reuso total: `pipeline.run`, `pipeline.get_ab_variant`,
`pipeline.get_variant_predictor`, `atribuir_decil_por_threshold`,
`send_batch_events`. Nenhuma transformação reimplementada — paridade
byte-a-byte com o fluxo Lead (Gate C.1/C.2 trivial).
"""
import json
import logging
import os
import tempfile
import time
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from api.railway_mapping import traduzir_survey_slugs
from api.survey_mapping import survey_lead_to_sheets_row

# pandas, send_batch_events e atribuir_decil_por_threshold são importados
# lazy dentro de process_pending_pubsub — evita puxar o SDK do Facebook
# (init no import de capi_integration) só pra testar as funções puras.

logger = logging.getLogger(__name__)

DEFAULT_BATCH = 25
PUBSUB_PROJECT_ID = "smart-ads-451319"
PUBSUB_SUBSCRIPTION_ID = "lead-capture-ingest-sub"


def is_enabled() -> bool:
    """Chave geral. Off por padrão — deploy/promover NÃO liga."""
    return os.environ.get("PUBSUB_CAPI_ENABLED", "false").strip().lower() == "true"


def subscription_path() -> str:
    return f"projects/{PUBSUB_PROJECT_ID}/subscriptions/{PUBSUB_SUBSCRIPTION_ID}"


# ---------------------------------------------------------------------------
# Funções puras (testáveis sem Pub/Sub nem DB)
# ---------------------------------------------------------------------------

def parse_pubsub_payload(raw_data) -> Dict:
    """bytes/str → dict. Levanta json.JSONDecodeError em corpo inválido."""
    if isinstance(raw_data, bytes):
        raw_data = raw_data.decode("utf-8")
    return json.loads(raw_data)


def payload_to_survey_dict(payload: Dict) -> Dict:
    """Mapeia payload Pub/Sub → dict no shape `lead_surveys row` que o I2 espera.

    Aplica `traduzir_survey_slugs` no objeto `survey` antes de retornar.
    Pode levantar `ValueError` se o payload trouxer slug fora do vocabulário.
    """
    survey_in = payload.get("survey") or {}
    survey_traduzido = traduzir_survey_slugs(survey_in)
    return {
        "id":          payload.get("eventId"),
        "submittedAt": payload.get("submittedAt"),
        "clientEmail": payload.get("email"),
        "ip":          payload.get("ip4"),
        **survey_traduzido,
    }


def payload_to_enrich(payload: Dict) -> Dict:
    """Payload Pub/Sub já carrega hasComputer/fbp/fbc/etc direto.

    Nenhum JOIN, nenhum parse de log — só renomeia campos pra forma `enrich`
    que `survey_lead_to_sheets_row` espera (compat com I2).
    """
    fn = (payload.get("firstName") or "").strip()
    ln = (payload.get("lastName") or "").strip()
    nome = f"{fn} {ln}".strip() or None
    return {
        "computador": payload.get("hasComputer"),
        "telefone":   payload.get("phone"),
        "nome":       nome,
        "fbp":        payload.get("fbp"),
        "fbc":        payload.get("fbc"),
        "ip":         payload.get("ip4"),
        "user_agent": payload.get("userAgent"),
    }


def payload_to_utm(payload: Dict) -> Dict:
    return dict(payload.get("utm") or {})


def is_meta_eligible(utm_source: Optional[str], allowlist: Iterable[str]) -> bool:
    """Match exato contra `utm_source_allowlist` (sem normalização) — como em
    `api/capi_integration.py`. Sources que não casam não disparam Meta.
    """
    if not utm_source:
        return False
    return utm_source in set(allowlist)


def classify(meta_eligible: bool, enrich: Dict) -> str:
    """Pura. 'skipped_allowlist' | 'skipped_missing_data' | 'send'.

    Mesma semântica do `api/survey_branch.classify`: não Meta-elegível pula
    direto; Meta-elegível sem computador/fbp/fbc é skip duro (regra acordada
    em 17/05 — modelo nunca rodou sem essas features).
    """
    if not meta_eligible:
        return "skipped_allowlist"
    if not (enrich.get("computador") and enrich.get("fbp") and enrich.get("fbc")):
        return "skipped_missing_data"
    return "send"


def ledger_row(
    event_id: str,
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
    utm: Optional[Dict] = None,
) -> Dict:
    """Pura. Monta dict do INSERT em `registros_ml`. PK = `event_id`.

    `utm` (opcional): dict no formato do payload (`{source, medium, campaign,
    content, term, url}`). Cada campo vira coluna `utm_*` no ledger. Permite
    que o monitoramento leia tudo do `registros_ml` (single-table) em vez de
    fazer JOIN com `lead_surveys × UTMTracking`.
    """
    utm = utm or {}
    return {
        "event_id": event_id,
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
        "utm_source":   utm.get("source"),
        "utm_medium":   utm.get("medium"),
        "utm_campaign": utm.get("campaign"),
        "utm_content":  utm.get("content"),
        "utm_term":     utm.get("term"),
        "utm_url":      utm.get("url"),
    }


def _insert_ledger(conn, r: Dict) -> None:
    conn.run(
        'INSERT INTO registros_ml '
        '(event_id, email, variant, lead_score, decil, base_meta_event_id, '
        ' base_status, hq_meta_event_id, hq_status, capi_sent_at, error_message, '
        ' utm_source, utm_medium, utm_campaign, utm_content, utm_term, utm_url) '
        'VALUES (:event_id, :email, :variant, :lead_score, :decil, '
        ' :base_meta_event_id, :base_status, :hq_meta_event_id, :hq_status, '
        + ('NOW()' if r.pop("capi_sent_at_now", False) else 'NULL')
        + ', :error_message, :utm_source, :utm_medium, :utm_campaign, '
        ' :utm_content, :utm_term, :utm_url) '
        'ON CONFLICT (event_id) DO NOTHING',
        **r,
    )


def _variant_name(pipeline, ab_variant) -> Optional[str]:
    if not ab_variant:
        return None
    return next(
        (n for n, v in pipeline._ab_test_config.variants.items() if v is ab_variant),
        None,
    )


# ---------------------------------------------------------------------------
# Orquestração (recebe subscriber, conn, pipeline)
# ---------------------------------------------------------------------------

def process_pending_pubsub(
    subscriber,
    conn,
    pipeline,
    *,
    dry_run: bool = False,
    batch: int = DEFAULT_BATCH,
) -> Dict:
    """Pull → parse → score → CAPI → ledger → ack. Não levanta pra fora;
    erros por mensagem são contidos, logados e (no caminho real) ackados
    para não reciclar — payload inválido/slug desconhecido não vai melhorar
    sendo reentregue.
    """
    import pandas as pd
    from api.capi_integration import send_batch_events
    from src.model.decil_thresholds import atribuir_decil_por_threshold

    allowlist = set(pipeline._client_config.capi.utm_source_allowlist or [])
    sub_path = subscription_path()

    # 1. Pull. Em fila vazia, o servidor do Pub/Sub bloqueia até o deadline
    # do RPC e então levanta DeadlineExceeded em vez de devolver lista vazia
    # (comportamento documentado quando `return_immediately` não está setado).
    # Aqui tratamos isso como "0 mensagens" — comportamento esperado da poll.
    from google.api_core import exceptions as _gax_exc

    try:
        response = subscriber.pull(
            request={"subscription": sub_path, "max_messages": int(batch)},
            timeout=10.0,
        )
        received = list(response.received_messages)
    except _gax_exc.DeadlineExceeded:
        received = []

    if not received:
        return {"processed": 0, "sent": 0, "skipped_allowlist": 0,
                "skipped_missing_data": 0, "errors": 0, "dry_run": dry_run}

    # 2. Parse — payload inválido vira erro mas é ackado (não vai melhorar reciclando)
    parsed: List[Tuple[str, Dict]] = []   # (ack_id, payload)
    error_ack_ids: List[str] = []
    n_err = 0
    for m in received:
        ack_id = m.ack_id
        try:
            payload = parse_pubsub_payload(m.message.data)
            if not payload.get("eventId"):
                raise ValueError("payload sem eventId")
            parsed.append((ack_id, payload))
        except Exception as e:
            n_err += 1
            logger.error(
                f"[pubsub_branch] payload inválido "
                f"(msg_id={getattr(m.message, 'message_id', '?')}): {e}"
            )
            error_ack_ids.append(ack_id)

    # 3. Classify + montar inputs do scoring
    pending_ledger: List[Dict] = []
    # (ack_id, payload, survey_dict, utm, enrich)
    to_score: List[Tuple[str, Dict, Dict, Dict, Dict]] = []
    handled_ack_ids: List[str] = []
    n_allow = n_missing = 0

    for ack_id, payload in parsed:
        event_id = payload["eventId"]
        # Pré-computa utm pra que TODOS os pending_ledger gravem utm_*
        # (inclusive os de erro de slug, que falham antes do classify).
        utm = payload_to_utm(payload)
        # Tradução slug→PT pode levantar (fail-loud em slug desconhecido)
        try:
            survey_dict = payload_to_survey_dict(payload)
        except ValueError as e:
            n_err += 1
            logger.error(
                f"[pubsub_branch] slug desconhecido em event_id={event_id}: {e}"
            )
            pending_ledger.append(ledger_row(
                event_id, payload.get("email"), None, None, None, "error",
                error_message=str(e)[:500], utm=utm))
            handled_ack_ids.append(ack_id)
            continue

        enrich = payload_to_enrich(payload)
        meta_elig = is_meta_eligible(utm.get("source"), allowlist)
        verdict = classify(meta_elig, enrich)

        if verdict == "skipped_allowlist":
            n_allow += 1
            pending_ledger.append(ledger_row(
                event_id, payload.get("email"), None, None, None,
                "skipped_allowlist", utm=utm))
            handled_ack_ids.append(ack_id)
        elif verdict == "skipped_missing_data":
            n_missing += 1
            pending_ledger.append(ledger_row(
                event_id, payload.get("email"), None, None, None,
                "skipped_missing_data", utm=utm))
            handled_ack_ids.append(ack_id)
        else:
            to_score.append((ack_id, payload, survey_dict, utm, enrich))

    # 4. Scoring por variante (mesmo padrão de survey_branch — reuso total)
    scored: Dict[str, Tuple[float, str, object, Optional[str]]] = {}
    if to_score:
        sheets, idmap, ab_per, vname_per = [], [], [], []
        for _, payload, survey_dict, utm, enrich in to_score:
            sr = survey_lead_to_sheets_row(
                survey_dict, utm, enrich, client_config=pipeline._client_config)
            ab_v = pipeline.get_ab_variant(
                {"utm_campaign": utm.get("campaign"),
                 "utm_content":  utm.get("content"),
                 "utm_source":   utm.get("source"),
                 "utm_medium":   utm.get("medium"),
                 "utm_term":     utm.get("term")},
                event_source_url=utm.get("url"),
            )
            sheets.append(sr)
            idmap.append(payload["eventId"])
            ab_per.append(ab_v)
            vname_per.append(_variant_name(pipeline, ab_v))

        groups = defaultdict(list)
        for i, vn in enumerate(vname_per):
            groups[vn].append(i)
        for vn, idxs in groups.items():
            predictor_ov = (pipeline.get_variant_predictor(vn) if vn
                            else pipeline.predictor)
            if vn:
                vcfg = pipeline._ab_test_config.variants.get(vn)
            else:
                crid = getattr(pipeline.predictor, "mlflow_run_id", None)
                vcfg = next(
                    (v for v in pipeline._ab_test_config.variants.values()
                     if v.run_id == crid), None
                ) if crid else None
            enc_ov = vcfg.encoding_overrides if vcfg else None
            gdf = pd.DataFrame([sheets[i] for i in idxs])
            tmp = None
            res = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".csv", delete=False
                ) as f:
                    gdf.to_csv(f, index=False)
                    tmp = f.name
                res = pipeline.run(
                    tmp, with_predictions=True,
                    predictor_override=predictor_ov,
                    encoding_overrides=enc_ov,
                )
            finally:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            if res is None or len(res) == 0:
                logger.warning(f"[pubsub_branch] pipeline vazio p/ grupo {vn}")
                continue
            thr = predictor_ov.metadata.get(
                "decil_thresholds", {}).get("thresholds", {})
            for j, oi in enumerate(idxs):
                try:
                    sc = float(res["lead_score"].iloc[j])
                    dc = (atribuir_decil_por_threshold(sc, thr)
                          if thr else "D05")
                    scored[idmap[oi]] = (sc, dc, ab_per[oi], vname_per[oi])
                except Exception as e:
                    n_err += 1
                    logger.warning(
                        f"[pubsub_branch] erro score {idmap[oi]}: {e}"
                    )

    # 5. Montar CAPI + ledger dos enviáveis
    capi_leads: List[Dict] = []
    # (event_id, decil_str, decil_int, vname, ack_id, payload, utm)
    capi_meta: List[Tuple[str, str, Optional[int], Optional[str], str, Dict, Dict]] = []
    for ack_id, payload, _, utm, enrich in to_score:
        eid = payload["eventId"]
        if eid not in scored:
            n_err += 1
            pending_ledger.append(ledger_row(
                eid, payload.get("email"), None, None, None, "error",
                error_message="sem score", utm=utm))
            handled_ack_ids.append(ack_id)
            continue
        sc, dc, ab_v, vn = scored[eid]
        nome = (enrich.get("nome") or "").strip()
        parts = nome.split(" ", 1)
        cl = {
            "_railway_id": eid,
            "email": payload.get("email"),
            "phone": enrich.get("telefone"),
            "first_name": parts[0] if parts and parts[0] else None,
            "last_name":  parts[1] if len(parts) > 1 else None,
            "lead_score": sc,
            "decil": dc,
            "event_id": eid,
            "fbp": enrich.get("fbp"),
            "fbc": enrich.get("fbc"),
            "user_agent": enrich.get("user_agent"),
            "client_ip":  enrich.get("ip"),
            "event_source_url": utm.get("url"),
            "event_timestamp": int(time.time()) - 60,
            "survey_data": None,
        }
        if ab_v:
            cl["ab_event_name"]        = ab_v.capi_event_name
            cl["ab_event_name_hq"]     = ab_v.capi_event_name_high_quality
            cl["ab_conversion_rates"]  = ab_v.conversion_rates
            cl["ab_pixel_id"]          = ab_v.pixel_id_override
        capi_leads.append(cl)
        capi_meta.append(
            (eid, dc, int(dc[1:]) if dc else None, vn, ack_id, payload, utm)
        )

    sent = 0
    if capi_leads and not dry_run:
        res = send_batch_events(
            capi_leads, db=None,
            capi_config=pipeline._client_config.capi,
            business_config=pipeline._client_config.business,
            client_id=pipeline._client_config.client_id,
        )
        details = res.get("details", [])
        sent = res.get("success", 0)
        for i, (eid, dc, di, vn, ack_id, payload, utm) in enumerate(capi_meta):
            ok = i < len(details) and details[i].get("status") == "success"
            st = "success" if ok else "error"
            hq = ("success" if (ok and di and di >= 9)
                  else (None if not (di and di >= 9) else "error"))
            pending_ledger.append(ledger_row(
                eid, payload.get("email"), vn,
                capi_leads[i]["lead_score"], di, st,
                base_meta_event_id=f"qualified_{capi_leads[i]['event_id']}",
                hq_meta_event_id=(f"hq_{capi_leads[i]['event_id']}"
                                  if di and di >= 9 else None),
                hq_status=hq, capi_sent_at_now=ok,
                error_message=(None if ok else
                               (details[i].get("error")
                                if i < len(details) else "sem retorno")),
                utm=utm,
            ))
            handled_ack_ids.append(ack_id)
    elif capi_leads and dry_run:
        logger.info(
            f"🧪 [pubsub_branch] dry_run — {len(capi_leads)} CAPI montados, "
            f"NÃO enviados, NÃO gravados, NÃO ackados"
        )

    # 6. Persistir ledger + Ack (dry_run não grava nem acka)
    if not dry_run:
        for r in pending_ledger:
            try:
                _insert_ledger(conn, r)
            except Exception as e:
                logger.warning(
                    f"[pubsub_branch] erro ledger {r.get('event_id')}: {e}"
                )

        ack_ids = list(set(handled_ack_ids + error_ack_ids))
        if ack_ids:
            try:
                subscriber.acknowledge(
                    request={"subscription": sub_path, "ack_ids": ack_ids}
                )
            except Exception as e:
                logger.error(
                    f"[pubsub_branch] erro ack ({len(ack_ids)} ids): {e}"
                )

    summary = {
        "processed": len(parsed),
        "sent": sent,
        "skipped_allowlist": n_allow,
        "skipped_missing_data": n_missing,
        "errors": n_err,
        "dry_run": dry_run,
    }
    logger.info(f"📨 [pubsub_branch] {summary}")
    return summary
