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

Reuso total: `score_lead_from_payload` (casa do scoring em src/scoring/),
`pipeline.get_ab_variant`, `send_batch_events`. Nenhuma transformação
reimplementada — paridade byte-a-byte com o consumer antigo, validada
pelo scripts/validar_paridade_scoring.py.
"""
import json
import logging
import os
import time
from typing import Dict, Iterable, List, Optional, Tuple

from src.core.payload_normalization import (
    payload_to_enrich,
    payload_to_survey_dict,
    payload_to_utm,
)
from src.scoring.service import score_lead_from_payload

# send_batch_events é importado lazy dentro de process_pending_pubsub —
# evita puxar o SDK do Facebook (init no import de capi_integration) só
# pra testar as funções puras.

logger = logging.getLogger(__name__)

DEFAULT_BATCH = 25
PUBSUB_PROJECT_ID = "smart-ads-451319"
PUBSUB_SUBSCRIPTION_ID = "lead-capture-ingest-sub"


def _event_ts_iso(skew_seconds: int = 60) -> str:
    """Timestamp RFC3339 (UTC) com o mesmo recuo de ~60s do CAPI Meta —
    formato exigido pelo `eventTimestamp` do Data Manager API (Google Ads)."""
    import datetime
    return datetime.datetime.fromtimestamp(
        time.time() - skew_seconds, datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_enabled() -> bool:
    """Chave geral. Off por padrão — deploy/promover NÃO liga."""
    return os.environ.get("PUBSUB_CAPI_ENABLED", "false").strip().lower() == "true"


def score_all_leads() -> bool:
    """Desacoplamento scoring × Meta CAPI.

    `true` (default): todo lead com `has_computer` é scoreado, independente
    de utm_source. Decisão de envio Meta CAPI (allowlist + fbp/fbc) acontece
    DEPOIS do scoring. Habilita decis Google no ledger.

    `false`: comportamento antigo — só Meta-eligible com fbp/fbc scoreia.

    Interruptor de comportamento via env. Flip em ~2min via
    `gcloud run services update --update-env-vars SCORE_ALL_LEADS=false`,
    sem precisar de novo build. Critério de remoção da flag: 7-14 dias
    sem incident + decis Google estabilizados no relatório.
    """
    return os.environ.get("SCORE_ALL_LEADS", "true").strip().lower() == "true"


def subscription_path() -> str:
    return f"projects/{PUBSUB_PROJECT_ID}/subscriptions/{PUBSUB_SUBSCRIPTION_ID}"


def ledger_target() -> str:
    """Destino do ledger registros_ml (PLANO_LEDGER_CLOUDSQL.md, Etapas 1-4).

    'railway' (default): comportamento atual — grava só no Railway do cliente.
    'dual':    Cloud SQL nosso é o primário (falha → mensagem NÃO é ackada,
               Pub/Sub reentrega; ON CONFLICT dedupa a regravação) + espelho
               tolerante no Railway. Estágio de migração.
    'cloudsql': só Cloud SQL (Etapa 4 — Railway fora).

    Flip via `gcloud run services update --update-env-vars LEDGER_TARGET=...`
    sem novo build. Valor inválido cai no default (não derruba o consumer).
    """
    t = os.environ.get("LEDGER_TARGET", "railway").strip().lower()
    return t if t in ("railway", "dual", "cloudsql") else "railway"


# ---------------------------------------------------------------------------
# Funções puras (testáveis sem Pub/Sub nem DB)
# ---------------------------------------------------------------------------

def parse_pubsub_payload(raw_data) -> Dict:
    """bytes/str → dict. Levanta json.JSONDecodeError em corpo inválido."""
    if isinstance(raw_data, bytes):
        raw_data = raw_data.decode("utf-8")
    return json.loads(raw_data)


# payload_to_survey_dict, payload_to_enrich, payload_to_utm vivem em
# src/core/payload_normalization.py (camada de tradução slug → PT-Long).
# Re-exportados no topo deste módulo pra não quebrar imports antigos.


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
    survey: Optional[Dict] = None,
    enrich: Optional[Dict] = None,
    has_computer: Optional[bool] = None,
) -> Dict:
    """Pura. Monta dict do INSERT em `registros_ml`. PK = `event_id`.

    `utm` (opcional): dict no formato do payload (`{source, medium, campaign,
    content, term, url}`). Cada campo vira coluna `utm_*` no ledger.

    `survey` (opcional): dict com as respostas do lead (formato PT-Long
    canônico vindo de `payload_to_survey_dict`, ou slug raw em casos de
    falha de tradução). Vai pra coluna `survey_responses` (JSONB). Habilita
    monitoramento de drift de categorias sem JOIN com `lead_surveys`.

    `enrich` (opcional): dict do `payload_to_enrich(payload)` com identidade,
    Meta tracking e sessão. Cada chave vira coluna no ledger:
      - `nome` → split em `first_name` + `last_name`
      - `telefone` → `phone`
      - `fbp`, `fbc`, `user_agent`, `ip` → colunas homônimas

    `has_computer` (opcional): valor de `payload['hasComputer']` — feature
    crítica do modelo, vem top-level no payload (não dentro de `survey`).
    """
    utm = utm or {}
    enrich = enrich or {}
    # Split do nome em primeiro/restante. Não confio no espaço único — usa
    # split max 1 pra cobrir "Maria das Dores".
    full_name = (enrich.get("nome") or "").strip()
    name_parts = full_name.split(" ", 1) if full_name else []
    first_name = name_parts[0] if name_parts else None
    last_name = name_parts[1] if len(name_parts) > 1 else None
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
        "survey_responses": survey,
        "first_name": first_name,
        "last_name":  last_name,
        "phone":      enrich.get("telefone"),
        "fbp":        enrich.get("fbp"),
        "fbc":        enrich.get("fbc"),
        "user_agent": enrich.get("user_agent"),
        "ip":         enrich.get("ip"),
        "has_computer": has_computer,
    }


def _insert_ledger(conn, r: Dict) -> None:
    import json as _json
    # Cópia: o dual-write insere a MESMA linha em 2 bancos — os pops abaixo
    # não podem mutilar o dict do caller entre o 1º e o 2º INSERT.
    r = dict(r)
    # JSONB precisa de string serializada — pg8000 não converte dict
    # diretamente. None vira NULL no SQL.
    survey_raw = r.pop("survey_responses", None)
    survey_json = _json.dumps(survey_raw) if survey_raw is not None else None
    conn.run(
        'INSERT INTO registros_ml '
        '(event_id, email, variant, lead_score, decil, base_meta_event_id, '
        ' base_status, hq_meta_event_id, hq_status, capi_sent_at, error_message, '
        ' utm_source, utm_medium, utm_campaign, utm_content, utm_term, utm_url, '
        ' survey_responses, '
        ' first_name, last_name, phone, fbp, fbc, user_agent, ip, has_computer) '
        'VALUES (:event_id, :email, :variant, :lead_score, :decil, '
        ' :base_meta_event_id, :base_status, :hq_meta_event_id, :hq_status, '
        + ('NOW()' if r.pop("capi_sent_at_now", False) else 'NULL')
        + ', :error_message, :utm_source, :utm_medium, :utm_campaign, '
        ' :utm_content, :utm_term, :utm_url, '
        ' CAST(:survey_responses AS JSONB), '
        ' :first_name, :last_name, :phone, :fbp, :fbc, :user_agent, :ip, '
        ' :has_computer) '
        'ON CONFLICT (event_id) DO NOTHING',
        survey_responses=survey_json,
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
    ledger_conn=None,
) -> Dict:
    """Pull → parse → score → CAPI → ledger → ack. Não levanta pra fora;
    erros por mensagem são contidos, logados e (no caminho real) ackados
    para não reciclar — payload inválido/slug desconhecido não vai melhorar
    sendo reentregue.

    Destino do ledger (PLANO_LEDGER_CLOUDSQL.md): `ledger_target()` decide.
    Com `ledger_conn` (Cloud SQL nosso) em modo 'dual'/'cloudsql', o Cloud SQL
    é o PRIMÁRIO fail-loud: INSERT que falhar deixa a mensagem sem ack →
    Pub/Sub reentrega e o ON CONFLICT dedupa a regravação. (O CAPI já foi
    enviado antes da persistência — reentrega pode re-disparar o evento, mas
    a Meta dedupa por event_id; mesmo trade-off at-least-once que já existia
    no ack em lote.) O Railway vira espelho tolerante (warning) até a Etapa 4.
    """
    from api.capi_integration import send_batch_events
    from api import google_ads_integration as google_ads

    allowlist = set(pipeline._client_config.capi.utm_source_allowlist or [])
    google_cfg = pipeline._client_config.google_ads
    score_all = score_all_leads()
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

    # 2. Parse — payload inválido vira erro mas é ackado (não vai melhorar reciclando).
    # Dedup in-batch: se o mesmo eventId aparecer 2x no mesmo pull (publisher
    # re-publicou ou Pub/Sub re-entregou dentro do ackDeadline), ackamos a 2ª
    # sem reprocessar. Sem isso o consumer dispara CAPI 2x com o mesmo event_id
    # — a Meta dedupa nas conversões, mas o "Eventos recebidos" do Events
    # Manager infla (foi como o gestor de tráfego notou a divergência).
    parsed: List[Tuple[str, Dict]] = []   # (ack_id, payload)
    error_ack_ids: List[str] = []
    duplicate_ack_ids: List[str] = []
    seen_event_ids: set = set()
    n_err = 0
    n_dup_in_batch = 0
    for m in received:
        ack_id = m.ack_id
        try:
            payload = parse_pubsub_payload(m.message.data)
            eid = payload.get("eventId")
            if not eid:
                raise ValueError("payload sem eventId")
            if eid in seen_event_ids:
                n_dup_in_batch += 1
                duplicate_ack_ids.append(ack_id)
                logger.warning(
                    f"[pubsub_branch] dup in-batch event_id={eid} "
                    f"(msg_id={getattr(m.message, 'message_id', '?')}) — "
                    f"ackando sem reprocessar"
                )
                continue
            seen_event_ids.add(eid)
            parsed.append((ack_id, payload))
        except Exception as e:
            n_err += 1
            logger.error(
                f"[pubsub_branch] payload inválido "
                f"(msg_id={getattr(m.message, 'message_id', '?')}): {e}"
            )
            error_ack_ids.append(ack_id)

    # 3. Classify + montar inputs do scoring
    #
    # Desacoplamento scoring × Meta CAPI:
    #   Quando `score_all=True` (default):
    #     - Gate técnico: precisa de `has_computer` (feature do modelo). fbp/fbc
    #       NÃO entram aqui — são tracking Meta, só relevantes pro dispatch.
    #     - Sem `has_computer` → status='skipped_missing_data', não scoreia.
    #     - Com `has_computer` → entra na fila de scoring (independente de
    #       utm_source). Decisão de destino (Meta CAPI / não-Meta) acontece
    #       no passo 5 abaixo, após o scoring.
    #
    #   Quando `score_all=False` (legacy):
    #     - classify() original — só Meta-eligible com fbp+fbc+computador
    #       scoreia. Mantido pra rollback rápido via env.
    # (linha do ledger, ack_id da mensagem que a originou) — o pareamento
    # permite NÃO ackar a mensagem cujo INSERT primário falhou (dual/cloudsql).
    pending_ledger: List[Tuple[Dict, Optional[str]]] = []
    # (ack_id, payload, survey_dict, utm, enrich, meta_elig)
    to_score: List[Tuple[str, Dict, Dict, Dict, Dict, bool]] = []
    handled_ack_ids: List[str] = []
    n_allow = n_missing = 0

    for ack_id, payload in parsed:
        event_id = payload["eventId"]
        # Pré-computa utm e enrich pra que TODOS os pending_ledger gravem
        # tudo que o payload trouxer (inclusive os de erro de slug, que
        # falham antes do classify).
        utm = payload_to_utm(payload)
        enrich = payload_to_enrich(payload)
        has_computer = payload.get("hasComputer")
        # Tradução slug→PT pode levantar (fail-loud em slug desconhecido)
        try:
            survey_dict = payload_to_survey_dict(payload)
        except ValueError as e:
            n_err += 1
            logger.error(
                f"[pubsub_branch] slug desconhecido em event_id={event_id}: {e}"
            )
            # Sem survey_dict (falhou na tradução). Grava o raw slug do payload
            # pra preservar o que veio (consumidores filtram se precisar).
            pending_ledger.append((ledger_row(
                event_id, payload.get("email"), None, None, None, "error",
                error_message=str(e)[:500], utm=utm,
                survey=payload.get("survey"),
                enrich=enrich, has_computer=has_computer), ack_id))
            handled_ack_ids.append(ack_id)
            continue

        meta_elig = is_meta_eligible(utm.get("source"), allowlist)

        if score_all:
            # Gate técnico — só has_computer (feature do modelo). fbp/fbc
            # decidem no dispatch.
            if not enrich.get("computador"):
                n_missing += 1
                pending_ledger.append((ledger_row(
                    event_id, payload.get("email"), None, None, None,
                    "skipped_missing_data", utm=utm, survey=survey_dict,
                    enrich=enrich, has_computer=has_computer), ack_id))
                handled_ack_ids.append(ack_id)
                continue
            # Entra na fila de scoring; meta_elig decide destino depois.
            to_score.append((ack_id, payload, survey_dict, utm, enrich, meta_elig))
        else:
            # Comportamento legacy — classify checa tudo de uma vez.
            verdict = classify(meta_elig, enrich)
            if verdict == "skipped_allowlist":
                n_allow += 1
                pending_ledger.append((ledger_row(
                    event_id, payload.get("email"), None, None, None,
                    "skipped_allowlist", utm=utm, survey=survey_dict,
                    enrich=enrich, has_computer=has_computer), ack_id))
                handled_ack_ids.append(ack_id)
            elif verdict == "skipped_missing_data":
                n_missing += 1
                pending_ledger.append((ledger_row(
                    event_id, payload.get("email"), None, None, None,
                    "skipped_missing_data", utm=utm, survey=survey_dict,
                    enrich=enrich, has_computer=has_computer), ack_id))
                handled_ack_ids.append(ack_id)
            else:
                to_score.append((ack_id, payload, survey_dict, utm, enrich, meta_elig))

    # 4. Scoring — uma chamada da casa do scoring (src/scoring/service.py)
    # por lead. A casa faz payload→sheets_row→preprocess→predict em memória,
    # sem CSV temporário, e devolve score+decil+variant. O ab_variant_config
    # (objeto da variante A/B, usado abaixo pra montar CAPI) é resolvido
    # de novo aqui — chamada barata, evita inflar o DTO.
    scored: Dict[str, Tuple[float, str, object, Optional[str]]] = {}
    for _, payload, survey_dict, utm, enrich, _meta_elig in to_score:
        eid = payload["eventId"]
        try:
            exp = score_lead_from_payload(payload, pipeline)
        except Exception as e:
            n_err += 1
            logger.warning(f"[pubsub_branch] erro score {eid}: {e}")
            continue
        ab_v = pipeline.get_ab_variant(
            {"utm_campaign": utm.get("campaign"),
             "utm_content":  utm.get("content"),
             "utm_source":   utm.get("source"),
             "utm_medium":   utm.get("medium"),
             "utm_term":     utm.get("term")},
            event_source_url=utm.get("url"),
        )
        dc = f"D{exp.decil:02d}"
        # Bloco F do EVENTOS_E_DECIS_PLANO — também guarda lead_score_calibrated
        # (None quando variante não declarou calibrated_run_id). Caminho de
        # propensão (lead_score raw + decil) intocado.
        scored[eid] = (exp.lead_score, dc, ab_v, exp.variant, exp.lead_score_calibrated)

    # 5. Montar CAPI + ledger dos enviáveis
    #
    # Quando score_all=True, esta etapa também trata leads scoreados que NÃO
    # vão pro Meta:
    #   - não-Meta (Google etc.) → status='skipped_allowlist' (scoreado, decil
    #     preenchido, mas sem CAPI Meta).
    #   - Meta-eligible sem fbp/fbc → status='skipped_missing_data' (scoreado
    #     mas sem tracking Meta).
    # Quando score_all=False, todo lead em to_score é Meta-eligible com tracking
    # OK (classify garantiu), então esses dois caminhos novos não são exercitados.
    capi_leads: List[Dict] = []
    # (event_id, decil_str, decil_int, vname, ack_id, payload, utm, survey_dict, enrich)
    capi_meta: List[Tuple[str, str, Optional[int], Optional[str], str, Dict, Dict, Dict, Dict]] = []
    google_leads: List[Dict] = []   # canal paralelo Google Ads (Fase A) — só populado quando google_ads.enabled
    n_scored_no_meta = 0
    for ack_id, payload, survey_dict, utm, enrich, meta_elig in to_score:
        eid = payload["eventId"]
        if eid not in scored:
            n_err += 1
            pending_ledger.append((ledger_row(
                eid, payload.get("email"), None, None, None, "error",
                error_message="sem score", utm=utm, survey=survey_dict,
                enrich=enrich, has_computer=payload.get("hasComputer")), ack_id))
            handled_ack_ids.append(ack_id)
            continue
        sc, dc, ab_v, vn, sc_cal = scored[eid]
        _di_int = int(dc[1:]) if dc else None

        # Gates de dispatch (só ativos quando score_all=True — caso contrário,
        # classify já filtrou antes do scoring):
        if score_all and not meta_elig:
            # Não vai pro Meta. Pode ir pro Google Ads (canal paralelo — Fase A).
            # is_eligible cobre enabled + source na allowlist Google. O ledger e o
            # ack seguem IDÊNTICOS a hoje (o rastro googleAdsStatus vem na Fase B).
            # Com google_ads.enabled=false → is_eligible=False → nada coletado →
            # comportamento byte-a-byte igual ao de antes.
            _g_ok, _g_reason = google_ads.is_eligible({"source": utm.get("source")}, google_cfg)
            if _g_ok:
                google_leads.append({
                    "email": payload.get("email"),
                    "phone": enrich.get("telefone"),
                    "decil": dc,
                    "event_id": eid,
                    "event_timestamp_iso": _event_ts_iso(),
                    "source": utm.get("source"),
                    "gclid": payload.get("gclid"),          # None até o front popular
                    "ab_conversion_rates": (ab_v.conversion_rates if ab_v else None),
                })
            n_allow += 1
            n_scored_no_meta += 1
            pending_ledger.append((ledger_row(
                eid, payload.get("email"), vn, sc, _di_int,
                "skipped_allowlist", utm=utm, survey=survey_dict,
                enrich=enrich, has_computer=payload.get("hasComputer")), ack_id))
            handled_ack_ids.append(ack_id)
            continue
        if score_all and not (enrich.get("fbp") and enrich.get("fbc")):
            # Meta-eligible MAS sem tracking Meta — scoreado, não enviado.
            n_missing += 1
            pending_ledger.append((ledger_row(
                eid, payload.get("email"), vn, sc, _di_int,
                "skipped_missing_data", utm=utm, survey=survey_dict,
                enrich=enrich, has_computer=payload.get("hasComputer")), ack_id))
            handled_ack_ids.append(ack_id)
            continue
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
            cl["ab_high_quality_decils"] = ab_v.capi_high_quality_decils
            # Bloco F do EVENTOS_E_DECIS_PLANO — popula ingredientes da
            # RoasV1DecileStrategy quando TODOS estão presentes:
            #   (a) variante declarou roas_v1 e está enabled
            #   (b) score calibrado existe (variant tem calibrated_run_id)
            #   (c) cpl_lookup global foi inicializado no startup do app.py
            # send_both_lead_events só monta 2ª atribuição quando os 3 chegam.
            if ab_v.roas_v1 and ab_v.roas_v1.enabled and sc_cal is not None:
                from api.app import get_cpl_lookup  # global do startup
                cpl_lookup = get_cpl_lookup()
                if cpl_lookup is not None:
                    cl["ab_variant_config"]         = ab_v
                    cl["ab_lead_score_calibrated"]  = sc_cal
                    cl["ab_cost_context"]           = cpl_lookup.cost_context_for(
                        utm.get("campaign"), utm.get("content"),
                    )
        capi_leads.append(cl)
        capi_meta.append(
            (eid, dc, int(dc[1:]) if dc else None, vn, ack_id, payload, utm, survey_dict, enrich)
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
        for i, (eid, dc, di, vn, ack_id, payload, utm, survey_dict, enrich) in enumerate(capi_meta):
            ok = i < len(details) and details[i].get("status") == "success"
            st = "success" if ok else "error"
            # hq_status vem do resultado real do envio HQ — antes era hardcoded di>=9,
            # mas agora a faixa de decis HQ é por variante (Challenger inclui D8).
            # 'skipped' do send_lead_qualified_high_quality vira NULL no ledger
            # (decil fora da faixa HQ da variante → HQ não aplicável).
            hq_res = details[i].get("evento_high_quality") if i < len(details) else None
            hq_st = hq_res.get("status") if hq_res else None
            hq_ok = hq_st == "success"
            hq = "success" if hq_ok else ("error" if hq_st == "error" else None)
            pending_ledger.append((ledger_row(
                eid, payload.get("email"), vn,
                capi_leads[i]["lead_score"], di, st,
                base_meta_event_id=f"qualified_{capi_leads[i]['event_id']}",
                hq_meta_event_id=(f"hq_{capi_leads[i]['event_id']}"
                                  if hq_ok or hq_st == "error" else None),
                hq_status=hq, capi_sent_at_now=ok,
                error_message=(None if ok else
                               (details[i].get("error")
                                if i < len(details) else "sem retorno")),
                utm=utm, survey=survey_dict,
                enrich=enrich, has_computer=payload.get("hasComputer"),
            ), ack_id))
            handled_ack_ids.append(ack_id)
    elif capi_leads and dry_run:
        logger.info(
            f"🧪 [pubsub_branch] dry_run — {len(capi_leads)} CAPI montados, "
            f"NÃO enviados, NÃO gravados, NÃO ackados"
        )

    # 5b. Envio paralelo Google Ads (Fase A) — canal INDEPENDENTE do Meta.
    # Não toca capi_leads nem o ledger Meta. google_leads só tem itens quando
    # google_ads.enabled (is_eligible filtrou na coleta). O rastro no ledger
    # (googleAdsStatus) vem na Fase B; aqui só envia + loga.
    google_sent = 0
    if google_leads and not dry_run:
        gres = google_ads.send_batch_events(
            google_leads,
            google_config=google_cfg,
            business_config=pipeline._client_config.business,
            client_id=pipeline._client_config.client_id,
        )
        google_sent = gres.get("sent", 0)
        logger.info(
            f"📈 [pubsub_branch] Google Ads: sent={gres.get('sent')} "
            f"skipped={gres.get('skipped')} errors={gres.get('errors')}"
        )
    elif google_leads and dry_run:
        logger.info(
            f"🧪 [pubsub_branch] dry_run — {len(google_leads)} Google leads montados, NÃO enviados"
        )

    # 6. Persistir ledger + Ack (dry_run não grava nem acka)
    #
    # Destino por ledger_target() (PLANO_LEDGER_CLOUDSQL.md):
    #   railway  → comportamento original: Railway tolerante (warning).
    #   dual     → Cloud SQL PRIMÁRIO fail-loud (falha = mensagem sem ack,
    #              Pub/Sub reentrega; ON CONFLICT dedupa) + espelho Railway
    #              tolerante.
    #   cloudsql → só Cloud SQL, fail-loud.
    # Sem ledger_conn, qualquer modo degrada pra 'railway' com erro no log —
    # melhor gravar na fonte antiga do que perder linha de ledger.
    n_ledger_err = 0
    target = ledger_target()
    if target in ("dual", "cloudsql") and ledger_conn is None:
        logger.error(
            f"[pubsub_branch] LEDGER_TARGET={target} mas ledger_conn ausente — "
            f"degradando pra railway neste batch"
        )
        target = "railway"

    failed_acks: set = set()
    if not dry_run:
        for r, r_ack in pending_ledger:
            if target in ("dual", "cloudsql"):
                try:
                    _insert_ledger(ledger_conn, r)
                except Exception as e:
                    n_ledger_err += 1
                    if r_ack:
                        failed_acks.add(r_ack)
                    logger.error(
                        f"[pubsub_branch] ledger Cloud SQL FALHOU "
                        f"{r.get('event_id')}: {e} — mensagem NÃO ackada"
                    )
            if target in ("railway", "dual"):
                try:
                    _insert_ledger(conn, r)
                except Exception as e:
                    logger.warning(
                        f"[pubsub_branch] erro ledger railway {r.get('event_id')}: {e}"
                    )

        ack_ids = list(
            set(handled_ack_ids + error_ack_ids + duplicate_ack_ids) - failed_acks
        )
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
        "google_sent": google_sent,
        "scored_no_meta": n_scored_no_meta,
        "skipped_allowlist": n_allow,
        "skipped_missing_data": n_missing,
        "dup_in_batch": n_dup_in_batch,
        "errors": n_err,
        "dry_run": dry_run,
        "score_all": score_all,
        "ledger_target": target,
        "ledger_errors": n_ledger_err,
        "unacked_for_retry": len(failed_acks),
    }
    logger.info(f"📨 [pubsub_branch] {summary}")
    return summary
