"""api/hotleads_integration.py — HotLeads (lead scoring da Hotmart) → evento CAPI.

A Hotmart classifica um lead como QUENTE ou FRIO cruzando a base transacional
dela (compras reais na plataforma) com o email/telefone que enviamos. É um sinal
EXTERNO e independente do nosso modelo: não olha a pesquisa nem o comportamento
na LP, olha o histórico de compra da pessoa no ecossistema Hotmart.

Fluxo (3 tempos, assíncrono):
  1. SUBMIT   — job recorrente pega leads recentes do ledger e POSTa no
                `batch_enrich` (até 1.000 por chamada). Marca 'submitted'.
  2. WEBHOOK  — ~2 min depois a Hotmart devolve o selo lead a lead. Gravamos
                em `hotleads_hot` e marcamos 'scored'.
  3. CAPI     — os quentes viram evento `LeadScoringHot` no pixel do cliente,
                pela NOSSA CAPI. Marca 'sent'.

⚠️ POR QUE NÃO DEIXAR A HOTMART ENVIAR PRO META: o `batch_enrich` aceita um
bloco `meta` (campaign_name + pixel_id + pixel_token) e, se preenchido, ela
mesma dispara um evento "LeadScoring" no pixel. NÃO usamos esse caminho de
propósito: (a) entregaria o token do Meta do cliente pra um terceiro, (b) o
envio vira caixa-preta — sem dedup por event_id nosso, sem user_data
enriquecido (estado/cidade/gênero), sem os logs e o match quality que a gente
já monitora. Submetemos SEM o bloco `meta`, tratando o HotLeads como scorer
puro. Se um dia alguém preencher `meta` aqui, o evento nativo passa a coexistir
com o nosso no mesmo pixel — daí o nome distinto (`LeadScoringHot`).

CHAVE DE JUNÇÃO: o `custom_label` de cada lead é ecoado intacto no webhook, e é
lá que colocamos o nosso `event_id`. Sem isso, casar a resposta com o ledger
exigiria lookup por email (ambíguo: o mesmo email reaparece em várias captações).

Camada anti-corrupção: o vocabulário da Hotmart (`score`, `executionId`,
`custom_label`) morre em `parse_webhook`. Do parse pra dentro só existe o nosso
(`event_id`, `hot`, `execution_id`).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

from src.core.client_config import ClientConfig, HotLeadsConfig
from src.core.hotmart_auth import get_hotmart_access_token

logger = logging.getLogger(__name__)

# Host real das chamadas. A landing da documentação (hotleads.hotmart.com) NÃO
# serve a API — bate 404. Confirmado em teste real 30/07/2026.
API_BASE = "https://developers.hotmart.com/send/api/v1/leadscoring"

# Teto do Meta pra event_time retroativo. Evento mais velho que isso é rejeitado,
# então lead que passou desse ponto não vira evento (fica 'scored' e pronto).
META_MAX_EVENT_AGE_DAYS = 7


# =============================================================================
# 1. CLIENTE DA API (anti-corrupção — só aqui se fala "hotmartês")
# =============================================================================

class HotLeadsClient:
    """Cliente fino do batch_enrich. Não conhece ledger nem CAPI — recebe leads
    já no nosso formato e devolve o `execution_id` da submissão."""

    def __init__(self, cfg: HotLeadsConfig, token: Optional[str] = None):
        self._cfg = cfg
        self._token = token

    def _ensure_token(self) -> Optional[str]:
        if not self._token:
            self._token = get_hotmart_access_token(self._cfg.basic_auth_env_var)
        return self._token

    def submit_batch(self, leads: List[Dict], webhook_url: str,
                     launch_date: Optional[str] = None,
                     timeout: int = 60) -> Dict:
        """POST /batch_enrich. `leads` no NOSSO formato:
            {event_id, email, phone, utm_source, utm_medium, utm_campaign,
             utm_term, utm_content}
        A tradução pro formato da Hotmart acontece aqui e em lugar nenhum mais.

        Retorna {"status": "ok"|"error", "execution_id": str|None, ...}.
        """
        if not leads:
            return {"status": "ok", "execution_id": None, "submitted": 0}

        token = self._ensure_token()
        if not token:
            return {"status": "error", "message": "sem token Hotmart", "submitted": 0}

        payload = {
            "webhook": webhook_url,
            "leads": [
                {
                    # O event_id volta intacto no webhook — é a chave de junção.
                    "custom_label": lead["event_id"],
                    "email": lead.get("email") or "",
                    "phone": str(lead.get("phone") or ""),
                    "utm": {
                        "source":   lead.get("utm_source") or "",
                        "medium":   lead.get("utm_medium") or "",
                        "campaign": lead.get("utm_campaign") or "",
                        "term":     lead.get("utm_term") or "",
                        "content":  lead.get("utm_content") or "",
                    },
                }
                for lead in leads
            ],
            "campaign": {
                "launch_date": launch_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "expected_ticket": self._cfg.expected_ticket,
                "currency_code_type": self._cfg.currency,
            },
            # `meta` OMITIDO de propósito — ver docstring do módulo.
        }

        try:
            resp = requests.post(
                f"{API_BASE}/batch_enrich",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            if resp.status_code not in (200, 201):
                return {"status": "error", "submitted": 0,
                        "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}
            execution_id = (resp.json() or {}).get("executionId")
            return {"status": "ok", "execution_id": execution_id,
                    "submitted": len(leads)}
        except Exception as e:
            logger.error(f"[hotleads] falha no batch_enrich: {e}")
            return {"status": "error", "message": str(e), "submitted": 0}


# =============================================================================
# 2. LEDGER — seleção de elegíveis e persistência do selo
# =============================================================================

def select_eligible_leads(conn, cfg: HotLeadsConfig,
                          source_allowlist: Optional[List[str]] = None,
                          limit: Optional[int] = None) -> List[Dict]:
    """Leads da janela que ainda não têm selo.

    Elegível = dentro de `submit_window_days`, com email, de um utm_source que a
    gente manda pro Meta, e ou nunca submetido (status NULL) ou submetido há mais
    de `resubmit_after_hours` sem retorno (webhook perdido — a Hotmart não
    reenvia).

    A allowlist é a MESMA do CAPI de propósito: o selo só vira evento no pixel do
    Meta, então lead que nunca iria pro Meta não precisa ser enriquecido (nem
    consome cota do lote).
    """
    limit = limit or cfg.batch_limit
    params = {
        "window_days": cfg.submit_window_days,
        "stale_hours": cfg.resubmit_after_hours,
        "lim": limit,
    }
    source_filter = ""
    if source_allowlist:
        # pg8000 não expande lista em IN — gera um placeholder por item.
        keys = []
        for i, src in enumerate(source_allowlist):
            k = f"src{i}"
            params[k] = src
            keys.append(f":{k}")
        source_filter = f"AND utm_source IN ({', '.join(keys)})"

    rows = conn.run(
        f"""
        SELECT event_id, email, phone, first_name, last_name,
               utm_source, utm_medium, utm_campaign, utm_term, utm_content,
               utm_url, fbp, fbc, user_agent, ip, survey_responses, created_at
        FROM registros_ml
        WHERE created_at >= NOW() - (:window_days * INTERVAL '1 day')
          AND email IS NOT NULL AND email <> ''
          {source_filter}
          AND (
                hotleads_status IS NULL
             OR (hotleads_status = 'submitted'
                 AND hotleads_submitted_at < NOW() - (:stale_hours * INTERVAL '1 hour'))
          )
        ORDER BY created_at DESC
        LIMIT :lim
        """,
        **params,
    )
    cols = ["event_id", "email", "phone", "first_name", "last_name",
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "utm_url", "fbp", "fbc", "user_agent", "ip", "survey_responses",
            "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def mark_submitted(conn, event_ids: List[str], execution_id: Optional[str]) -> int:
    """Marca os leads como 'submitted' (aguardando webhook)."""
    if not event_ids:
        return 0
    keys = []
    params = {"exec_id": execution_id}
    for i, eid in enumerate(event_ids):
        k = f"e{i}"
        params[k] = eid
        keys.append(f":{k}")
    conn.run(
        f"""
        UPDATE registros_ml
        SET hotleads_status = 'submitted',
            hotleads_execution_id = :exec_id,
            hotleads_submitted_at = NOW(),
            hotleads_error = NULL
        WHERE event_id IN ({', '.join(keys)})
        """,
        **params,
    )
    return len(event_ids)


def store_seal(conn, event_id: str, hot: bool,
               execution_id: Optional[str] = None) -> None:
    """Grava o selo e move o lead pra 'scored'.

    Não sobrescreve 'sent': se o evento já foi disparado, um webhook repetido
    (a Hotmart pode reentregar) não deve regredir o estado nem re-disparar.
    """
    conn.run(
        """
        UPDATE registros_ml
        SET hotleads_hot = :hot,
            hotleads_scored_at = NOW(),
            hotleads_status = 'scored',
            hotleads_execution_id = COALESCE(:exec_id, hotleads_execution_id)
        WHERE event_id = :event_id
          AND (hotleads_status IS DISTINCT FROM 'sent')
        """,
        event_id=event_id, hot=hot, exec_id=execution_id,
    )


def mark_capi_sent(conn, event_id: str, ok: bool,
                   error: Optional[str] = None) -> None:
    """Fecha o ciclo: 'sent' em sucesso, 'error' (com a mensagem) em falha."""
    conn.run(
        """
        UPDATE registros_ml
        SET hotleads_status = :status,
            hotleads_capi_sent_at = CASE WHEN :ok THEN NOW() ELSE hotleads_capi_sent_at END,
            hotleads_error = :err
        WHERE event_id = :event_id
        """,
        event_id=event_id, ok=ok,
        status=("sent" if ok else "error"),
        err=(None if ok else (error or "")[:1000]),
    )


def fetch_lead_for_capi(conn, event_id: str) -> Optional[Dict]:
    """Dados do lead necessários pro evento CAPI (PII + contexto de browser)."""
    rows = conn.run(
        """
        SELECT event_id, email, phone, first_name, last_name, fbp, fbc,
               user_agent, ip, utm_url, survey_responses, created_at,
               hotleads_status
        FROM registros_ml
        WHERE event_id = :event_id
        LIMIT 1
        """,
        event_id=event_id,
    )
    if not rows:
        return None
    cols = ["event_id", "email", "phone", "first_name", "last_name", "fbp", "fbc",
            "user_agent", "ip", "utm_url", "survey_responses", "created_at",
            "hotleads_status"]
    return dict(zip(cols, rows[0]))


# =============================================================================
# 3. WEBHOOK — tradução do payload da Hotmart
# =============================================================================

def parse_webhook(body: Dict) -> Tuple[Optional[str], List[Dict]]:
    """Payload do HotLeads → (execution_id, [{event_id, hot}]).

    Formato de entrada (confirmado em teste real):
        {"executionId": "...", "leads_processed": 10,
         "leads": [{"email": ..., "phone": ..., "score": 0|1,
                    "custom_label": "<nosso event_id>", "utm": {...}}, ...]}

    Fronteira anti-corrupção: `score` (0/1) vira `hot` (bool) e `custom_label`
    vira `event_id`. Lead sem `custom_label` utilizável é descartado — sem a
    chave de junção não há o que atualizar (e casar por email seria ambíguo).
    """
    if not isinstance(body, dict):
        return None, []
    execution_id = body.get("executionId") or body.get("execution_id")
    out: List[Dict] = []
    for lead in (body.get("leads") or []):
        if not isinstance(lead, dict):
            continue
        event_id = (lead.get("custom_label") or "").strip()
        if not event_id:
            continue
        try:
            hot = int(lead.get("score") or 0) == 1
        except (TypeError, ValueError):
            hot = False
        out.append({"event_id": event_id, "hot": hot,
                    "email": (lead.get("email") or "").strip().lower()})
    return execution_id, out


# Rótulo que marca lead do ENRIQUECIMENTO EM LOTE da base histórica. Esses não
# são leads correntes: não têm `event_id`, não entram no ciclo do ledger e NÃO
# geram evento no pixel (seriam recusados pela regra dos 7 dias do Meta de
# qualquer forma). Vão para `analytics.hotleads_seal`, por email.
BULK_LABEL = "bulk"


def store_bulk_seals(conn, seals: List[Dict], execution_id: Optional[str] = None) -> int:
    """Grava selos do enriquecimento histórico (upsert por email).

    Sobrescreve `hot`/`sealed_at` num re-enriquecimento de propósito: o selo é um
    retrato datado, e o retrato mais novo é o que vale.
    """
    n = 0
    for s in seals:
        email = (s.get("email") or "").strip().lower()
        if not email:
            continue
        conn.run(
            """
            INSERT INTO analytics.hotleads_seal (email, hot, sealed_at, execution_id)
            VALUES (:email, :hot, NOW(), :exec_id)
            ON CONFLICT (email) DO UPDATE
              SET hot = EXCLUDED.hot,
                  sealed_at = EXCLUDED.sealed_at,
                  execution_id = EXCLUDED.execution_id
            """,
            email=email, hot=bool(s.get("hot")), exec_id=execution_id,
        )
        n += 1
    return n


# =============================================================================
# 4. CAPI — evento dos leads quentes
# =============================================================================

def lead_event_timestamp(created_at) -> int:
    """`created_at` do ledger → epoch UNIX para o `event_time` do Meta.

    ⚠️ A coluna é `timestamp WITHOUT time zone` guardando UTC. Um naive
    datetime.timestamp() interpreta o valor como horário LOCAL — no Cloud Run,
    onde TZ=America/Sao_Paulo, isso joga o evento 3h no FUTURO e a Meta rejeita
    o lote inteiro ("Call was not successful"). Foi assim que os 18 primeiros
    eventos quentes falharam em 30/07. Por isso o tzinfo é explicitado aqui.

    Guarda extra de 60s no fim: mesmo com o fuso certo, um lead capturado no
    exato instante da chamada poderia arredondar pra frente. Os outros senders
    do projeto resolvem o mesmo risco com `int(time.time()) - 60`.
    """
    now = int(time.time())
    if not created_at:
        return now - 60
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return min(int(created_at.timestamp()), now - 60)


def send_lead_scoring_hot(
    lead: Dict,
    cfg: HotLeadsConfig,
    capi_config=None,
    test_event_code: Optional[str] = None,
    dry_run: bool = False,
) -> Dict:
    """Dispara o evento do selo quente pela NOSSA CAPI.

    Reusa o miolo compartilhado de `capi_integration` (build_lead_user_data +
    parse_meta_capi_response) — não reimplementa hashing nem parse de resposta.
    Sem valor monetário: o selo é binário, atribuir R$ seria inventar número.

    `event_time` é o do lead original (não o de agora); lead mais velho que a
    janela do Meta é pulado em vez de rejeitado.
    """
    from api.capi_integration import (ACCESS_TOKEN, build_lead_user_data,
                                      parse_meta_capi_response)
    from facebook_business.adobjects.serverside.action_source import ActionSource
    from facebook_business.adobjects.serverside.custom_data import CustomData
    from facebook_business.adobjects.serverside.event import Event
    from facebook_business.adobjects.serverside.event_request import EventRequest

    event_id = lead["event_id"]
    # Pixel próprio do HotLeads tem prioridade; sem ele, herda o padrão do
    # cliente. O selo é sinal EXTERNO ao nosso modelo, então o operador pode
    # querer o evento num conjunto de dados separado (no DevClub: DEVLF-API).
    pixel_id = (cfg.pixel_id
                or (capi_config.pixel_id if capi_config and capi_config.pixel_id
                    else None)
                or os.getenv("META_PIXEL_ID"))
    if not ACCESS_TOKEN:
        return {"status": "error", "event_id": event_id,
                "message": "META_ACCESS_TOKEN não configurado"}
    if not pixel_id:
        return {"status": "error", "event_id": event_id,
                "message": "pixel_id não configurado"}

    event_timestamp = lead_event_timestamp(lead.get("created_at"))
    age_days = (time.time() - event_timestamp) / 86400
    if age_days > META_MAX_EVENT_AGE_DAYS:
        return {"status": "skipped", "event_id": event_id,
                "reason": f"lead com {age_days:.1f}d — fora da janela do Meta"}

    survey = lead.get("survey_responses")
    if isinstance(survey, str):
        try:
            survey = json.loads(survey)
        except Exception:
            survey = None

    country_code = (capi_config.country_code
                    if capi_config and capi_config.country_code else "br")
    try:
        user_data = build_lead_user_data(
            email=lead.get("email"), phone=lead.get("phone"),
            first_name=lead.get("first_name"), last_name=lead.get("last_name"),
            survey_data=survey if isinstance(survey, dict) else None,
            country_code=country_code,
            client_ip=lead.get("ip"), user_agent=lead.get("user_agent"),
            fbp=lead.get("fbp"), fbc=lead.get("fbc"),
        )
        custom_data = CustomData(
            currency=(capi_config.currency if capi_config and capi_config.currency
                      else cfg.currency),
            custom_properties={"fonte_sinal": "hotleads", "selo": "quente"},
        )
        event = Event(
            event_name=cfg.event_name,
            event_time=event_timestamp,
            # Prefixo próprio: o mesmo lead já gerou `qualified_<id>` e `hq_<id>`;
            # sem prefixo distinto a Meta deduparia contra os eventos existentes.
            event_id=f"hotleads_{event_id}",
            user_data=user_data,
            custom_data=custom_data,
            event_source_url=lead.get("utm_url"),
            action_source=ActionSource.WEBSITE,
        )

        if dry_run:
            logger.info(f"🧪 [DRY_RUN] {cfg.event_name}: {lead.get('email')} "
                        f"(pixel: {pixel_id})")
            return {"status": "dry_run", "event_id": event_id,
                    "event_name": cfg.event_name, "pixel_id": pixel_id}

        params = {"events": [event], "pixel_id": pixel_id,
                  "access_token": ACCESS_TOKEN}
        if test_event_code:
            params["test_event_code"] = test_event_code
        parsed = parse_meta_capi_response(EventRequest(**params).execute())
        logger.info(f"✅ {cfg.event_name} enviado: {lead.get('email')} "
                    f"(status: {parsed['status']})")
        return {"status": parsed["status"], "event_id": event_id,
                "capi_response": parsed}
    except Exception as e:
        logger.error(f"❌ Erro ao enviar {cfg.event_name}: {e}")
        return {"status": "error", "event_id": event_id, "message": str(e)}


# =============================================================================
# 5. ORQUESTRAÇÃO (consumida pelos endpoints)
# =============================================================================

def run_submit_batch(conn, client_config: ClientConfig, webhook_url: str,
                     limit: Optional[int] = None, dry_run: bool = False) -> Dict:
    """Passo 1: seleciona elegíveis, submete, marca 'submitted'."""
    cfg = client_config.hotleads
    if not cfg.enabled:
        return {"status": "disabled", "submitted": 0}

    leads = select_eligible_leads(
        conn, cfg,
        source_allowlist=client_config.capi.utm_source_allowlist,
        limit=limit,
    )
    if not leads:
        return {"status": "ok", "submitted": 0, "execution_id": None,
                "message": "nenhum lead elegível"}

    if dry_run:
        return {"status": "dry_run", "submitted": 0, "eligible": len(leads),
                "sample": [l["event_id"] for l in leads[:3]]}

    result = HotLeadsClient(cfg).submit_batch(leads, webhook_url=webhook_url)
    if result.get("status") != "ok":
        return result

    marked = mark_submitted(conn, [l["event_id"] for l in leads],
                            result.get("execution_id"))
    logger.info(f"[hotleads] submetidos {marked} leads "
                f"(execution_id={result.get('execution_id')})")
    return {"status": "ok", "submitted": marked,
            "execution_id": result.get("execution_id")}


def select_failed_sends(conn, limit: int = 500) -> List[Dict]:
    """Leads QUENTES cujo selo já chegou mas cujo evento não saiu ('error').

    Sem este caminho, qualquer falha no envio (soluço da Meta, token expirado,
    bug como o do fuso em 30/07) deixaria o lead órfão pra sempre: o seletor de
    submissão não o pega de volta (status não é NULL nem 'submitted') e o
    webhook não repete. O selo já está no ledger, então reenviar NÃO custa nova
    chamada à Hotmart — é só refazer o passo do CAPI.
    """
    rows = conn.run(
        """
        SELECT event_id, email, phone, first_name, last_name, fbp, fbc,
               user_agent, ip, utm_url, survey_responses, created_at,
               hotleads_status
        FROM registros_ml
        WHERE hotleads_status = 'error'
          AND hotleads_hot IS TRUE
          AND hotleads_capi_sent_at IS NULL
        ORDER BY hotleads_scored_at DESC
        LIMIT :lim
        """,
        lim=limit,
    )
    cols = ["event_id", "email", "phone", "first_name", "last_name", "fbp", "fbc",
            "user_agent", "ip", "utm_url", "survey_responses", "created_at",
            "hotleads_status"]
    return [dict(zip(cols, r)) for r in rows]


def run_retry_failed(conn, client_config: ClientConfig, limit: int = 500,
                     dry_run: bool = False) -> Dict:
    """Refaz o envio CAPI dos quentes que ficaram em 'error'."""
    cfg = client_config.hotleads
    if not cfg.enabled:
        return {"status": "disabled", "retried": 0}

    leads = select_failed_sends(conn, limit=limit)
    stats = {"candidates": len(leads), "sent": 0, "skipped": 0, "errors": 0}
    for lead in leads:
        res = send_lead_scoring_hot(lead, cfg, capi_config=client_config.capi,
                                    dry_run=dry_run)
        if res.get("status") in ("success", "partial", "dry_run"):
            if not dry_run:
                mark_capi_sent(conn, lead["event_id"], ok=True)
            stats["sent"] += 1
        elif res.get("status") == "skipped":
            stats["skipped"] += 1
        else:
            stats["errors"] += 1
    if leads:
        logger.info(f"[hotleads] retry de falhas | {stats}")
    return {"status": "ok", **stats}


def run_process_webhook(conn, client_config: ClientConfig, body: Dict,
                        dry_run: bool = False) -> Dict:
    """Passos 2 e 3: grava os selos e dispara o evento dos quentes.

    Falha de um lead não derruba o lote: cada um é contido e registrado em
    `hotleads_error`. O webhook responde 200 mesmo com falhas parciais — a
    Hotmart não reentrega, e devolver erro só perderia os selos que deram certo.
    """
    cfg = client_config.hotleads
    if not cfg.enabled:
        return {"status": "disabled", "received": 0}

    execution_id, seals = parse_webhook(body)

    # Lote HISTÓRICO: só persiste o selo por email. Nunca dispara evento — são
    # leads antigos, fora da janela do Meta, e o objetivo é medir/segmentar.
    bulk = [s for s in seals if s.get("event_id") == BULK_LABEL]
    if bulk:
        from src.data.analytics_connection import open_analytics_connection
        aconn = open_analytics_connection()
        try:
            gravados = store_bulk_seals(aconn, bulk, execution_id)
        finally:
            try:
                aconn.close()
            except Exception:
                pass
        logger.info(f"[hotleads] lote historico execution_id={execution_id} | "
                    f"{gravados} selos gravados ({sum(1 for b in bulk if b['hot'])} quentes)")
        return {"status": "ok", "execution_id": execution_id, "bulk": True,
                "received": len(bulk), "gravados": gravados,
                "hot": sum(1 for b in bulk if b["hot"])}

    stats = {"received": len(seals), "hot": 0, "cold": 0,
             "sent": 0, "skipped": 0, "errors": 0}

    for seal in seals:
        event_id = seal["event_id"]
        try:
            store_seal(conn, event_id, seal["hot"], execution_id)
            if not seal["hot"]:
                stats["cold"] += 1
                continue
            stats["hot"] += 1

            lead = fetch_lead_for_capi(conn, event_id)
            if not lead:
                # Selo de um event_id que não está no ledger: nada a fazer.
                stats["skipped"] += 1
                continue
            if lead.get("hotleads_status") == "sent":
                stats["skipped"] += 1   # webhook repetido — não re-dispara
                continue

            res = send_lead_scoring_hot(lead, cfg,
                                        capi_config=client_config.capi,
                                        dry_run=dry_run)
            if res.get("status") in ("success", "partial", "dry_run"):
                if not dry_run:
                    mark_capi_sent(conn, event_id, ok=True)
                stats["sent"] += 1
            elif res.get("status") == "skipped":
                stats["skipped"] += 1
            else:
                if not dry_run:
                    mark_capi_sent(conn, event_id, ok=False,
                                   error=res.get("message"))
                stats["errors"] += 1
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"[hotleads] erro no lead {event_id}: {e}")
            try:
                mark_capi_sent(conn, event_id, ok=False, error=str(e))
            except Exception:
                pass

    logger.info(f"[hotleads] webhook execution_id={execution_id} | {stats}")
    return {"status": "ok", "execution_id": execution_id, **stats}
