"""
api/google_ads_integration.py — envio de conversão de lead ao Google Ads via
**Data Manager API** (datamanager.googleapis.com, método `events:ingest`).

Análogo ao `api/capi_integration.py` (Meta), mas é um módulo SEPARADO por design:
é outra API e outro fluxo de auth (service account com escopo `datamanager`, sem
developer token em runtime). Misturar com o CAPI acoplaria dois SDKs/auths num
arquivo só.

Mecanismo: **Enhanced Conversions for Leads**. A conversão casa por email/telefone
hasheados em SHA-256 — que o ledger `registros_ml` já guarda. O `gclid` é OPCIONAL
(eleva match rate/atribuição, não é pré-requisito); quando o front passar a popular
`gclid` no payload, ele entra no mesmo evento. Fonte: developers.google.com/data-manager
(events:ingest exige "pelo menos um" identificador; `userData` sozinho satisfaz).

────────────────────────────────────────────────────────────────────────────
ESTADO: INERTE. Nenhum path de produção importa este módulo ainda. Quem vai
chamá-lo é o despachante único por canal (etapa de paridade separada, ainda não
feita), quando `GoogleAdsConfig.enabled` e o lead passar na `source_allowlist`.

⚠️ Antes do canary: rodar `send_batch_events(..., dry_run=True)` (vira
`validateOnly=true` na API) pra confirmar os NOMES DE CAMPO do payload contra a
referência da Data Manager API — a forma do request abaixo é a melhor conhecida
da doc, mas só o validate_only confirma. Ver docs/google_ads_pendencias.md.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Endpoint da Data Manager API (sem data de sunset; substitui a UploadClickConversions
# legada da Google Ads API, que fecha pra novos integradores em 2026-06-15).
DATA_MANAGER_ENDPOINT = "https://datamanager.googleapis.com/v1/events:ingest"
DATA_MANAGER_SCOPE = "https://www.googleapis.com/auth/datamanager"

# Default de país pra normalizar telefone em E.164 quando vier sem DDI (DevClub = BR).
_DEFAULT_PHONE_CC = "55"


# ---------------------------------------------------------------------------
# Normalização + hash (espelha a regra do Meta: SHA-256 de valor normalizado)
# ---------------------------------------------------------------------------

def _normalize_email(email: Optional[str]) -> Optional[str]:
    """lowercase + trim. (Google ignora pontos/+ só em gmail; não normalizamos
    isso pra não divergir do que o lead form coletou.)"""
    if not email:
        return None
    e = email.strip().lower()
    return e or None


def _normalize_phone_e164(phone: Optional[str]) -> Optional[str]:
    """Telefone em E.164 (+55DDDNNNNNNNNN). Best-effort:
    - tira tudo que não é dígito
    - se já vier com DDI 55 (12-13 dígitos), mantém
    - se vier só com DDD+número (10-11 dígitos), prepend 55
    Retorna com '+' na frente. None se não der pra normalizar.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    if len(digits) in (10, 11):           # DDD + número, sem DDI
        digits = _DEFAULT_PHONE_CC + digits
    elif digits.startswith(_DEFAULT_PHONE_CC) and len(digits) in (12, 13):
        pass                               # já tem DDI
    else:
        return None                        # formato inesperado — não arrisca match errado
    return "+" + digits


def _sha256(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_user_identifiers(email: Optional[str], phone: Optional[str]) -> List[Dict]:
    """Lista de userIdentifiers hasheados pro bloco `userData` do evento.
    Pelo menos um basta pra ingestão ser aceita."""
    ids: List[Dict] = []
    eh = _sha256(_normalize_email(email))
    ph = _sha256(_normalize_phone_e164(phone))
    if eh:
        ids.append({"emailAddress": eh})
    if ph:
        ids.append({"phoneNumber": ph})
    return ids


# ---------------------------------------------------------------------------
# Valor por decil — MESMA regra do CAPI (product_value × conversion_rate[decil])
# ---------------------------------------------------------------------------

def compute_value(
    decil: str,
    business_config=None,
    conversion_rates_override: Optional[Dict[str, float]] = None,
) -> float:
    """Valor monetário esperado do lead naquele decil. Idêntico ao Meta:
    `business.product_value × conversion_rate[decil]`, com override por variante A/B.
    Mantém paridade — o sinal enviado ao Google é o mesmo decil/valor do Meta."""
    rates = conversion_rates_override or (
        business_config.conversion_rates if business_config and business_config.conversion_rates else None
    )
    if rates and business_config:
        return round(business_config.product_value * rates.get(decil, 0.0), 2)
    return 0.0


# ---------------------------------------------------------------------------
# Roteamento (allowlist) — thin; o despachante único é quem decide de fato
# ---------------------------------------------------------------------------

def is_eligible(lead: Dict, google_config) -> tuple:
    """(allowed, reason). Espelha should_send_to_destination do CAPI, mas pro Google.
    enabled=False ou source fora da allowlist ⇒ não envia. Match exato no source RAW
    (mesma regra do Meta — substring causaria falso positivo)."""
    if google_config is None or not getattr(google_config, "enabled", False):
        return False, "disabled"
    allowlist = google_config.source_allowlist or []
    if not allowlist:
        return False, "empty_allowlist"
    src = (lead.get("source") or lead.get("utm_source") or "").lower()
    if not any(s.lower() == src for s in allowlist):
        return False, "skipped_by_allowlist"
    return True, "allowed"


# ---------------------------------------------------------------------------
# Auth — token OAuth2 da service account (escopo datamanager)
# ---------------------------------------------------------------------------

def _get_access_token() -> str:
    """Token via Application Default Credentials com escopo datamanager.
    No Cloud Run, usa a service account anexada ao serviço (sem chave baixada —
    impersonation, como a doc recomenda). Falha alto e claro se faltar lib/cred."""
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError as e:
        raise RuntimeError(
            "google-auth ausente — necessário pro envio Google Ads (Data Manager API). "
            "pip install google-auth"
        ) from e
    creds, _ = google.auth.default(scopes=[DATA_MANAGER_SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


# ---------------------------------------------------------------------------
# Construção do payload events:ingest
# ---------------------------------------------------------------------------

def build_event(
    *,
    email: Optional[str],
    phone: Optional[str],
    value: float,
    currency: str,
    event_timestamp_iso: str,
    transaction_id: str,
    gclid: Optional[str] = None,
) -> Dict:
    """Monta um Event do events:ingest.

    ⚠️ FORMA SUJEITA A CONFIRMAÇÃO via validateOnly antes do canary — os nomes de
    campo abaixo seguem a doc da Data Manager API, mas só a chamada validate_only
    garante que casam com a versão atual da API. Centralizado aqui de propósito:
    se algum nome divergir, conserta-se num lugar só.
    """
    event: Dict = {
        "transactionId": transaction_id,        # dedupe
        "eventTimestamp": event_timestamp_iso,  # RFC3339
        "conversion": {
            "value": value,
            "currencyCode": currency,
        },
    }
    user_ids = hash_user_identifiers(email, phone)
    if user_ids:
        event["userData"] = {"userIdentifiers": user_ids}
    if gclid:
        event["adIdentifiers"] = {"gclid": gclid}
    # Sem bloco `consent`: DevClub é tráfego BR (fora do EEA). Para clientes EEA,
    # preencher consent.adUserData / consent.adPersonalization aqui.
    return event


def build_ingest_request(
    *,
    events: List[Dict],
    customer_id: str,
    conversion_action_id: str,
    login_customer_id: Optional[str] = None,
    validate_only: bool = False,
) -> Dict:
    """Corpo do POST events:ingest. `productDestinationId` = a conversion action.
    `operatingAccount` = a conta Google Ads (DevClub). ⚠️ Confirmar nomes via
    validate_only (ver build_event)."""
    operating = {"product": "GOOGLE_ADS", "accountId": customer_id}
    if login_customer_id:
        operating["loginAccountId"] = login_customer_id
    return {
        "destinations": [{
            "operatingAccount": operating,
            "productDestinationId": conversion_action_id,
        }],
        "events": events,
        "validateOnly": validate_only,
    }


def _post_ingest(request_body: Dict) -> Dict:
    """POST autenticado. Retorna dict de resultado padronizado (mesmo vocabulário
    de status do CAPI: sent / error)."""
    try:
        token = _get_access_token()
        resp = requests.post(
            DATA_MANAGER_ENDPOINT,
            json=request_body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.error("Google Ads ingest falhou (%s): %s", resp.status_code, resp.text[:500])
            return {"status": "error", "http_status": resp.status_code, "message": resp.text[:500]}
        return {"status": "sent", "http_status": resp.status_code, "response": resp.json() if resp.content else {}}
    except Exception as e:  # noqa: BLE001 — borda de rede; loga e devolve erro estruturado
        logger.error("Google Ads ingest exceção: %s", e)
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Interface pública — espelha capi_integration.send_batch_events
# ---------------------------------------------------------------------------

def send_batch_events(
    leads: List[Dict],
    google_config=None,
    business_config=None,
    client_id: str = "devclub",
    dry_run: bool = False,
) -> Dict:
    """Envia conversões de um lote de leads ao Google Ads.

    Espelha a assinatura de `capi_integration.send_batch_events`. Para cada lead
    elegível (passou na allowlist): dispara o evento value-weighted (todos os decis)
    e, se o decil estiver em `high_quality_decils`, o evento HQ — paridade com o Meta.

    `dry_run=True` ⇒ `validateOnly=true` na API (valida sem gravar). USE isto antes
    do primeiro canary pra confirmar a forma do payload.

    Cada lead deve ter: email, phone, decil, event_id (transaction_id),
    event_timestamp_iso e, opcionalmente, gclid.

    INERTE até `google_config.enabled` — sem isso, retorna tudo como skipped.
    """
    out = {"sent": 0, "skipped": 0, "errors": 0, "results": []}
    if google_config is None or not getattr(google_config, "enabled", False):
        out["skipped"] = len(leads)
        return out

    customer_id = (google_config.customer_id or "").replace("-", "")
    ca_value = google_config.conversion_action_id_with_value
    ca_hq = google_config.conversion_action_id_high_quality
    currency = google_config.currency or "BRL"
    hq_decils = set(google_config.high_quality_decils or [])

    if not customer_id or not ca_value:
        logger.error("GoogleAdsConfig incompleto (customer_id/conversion_action_id_with_value) — não envia.")
        out["errors"] = len(leads)
        return out

    for lead in leads:
        allowed, reason = is_eligible(lead, google_config)
        if not allowed:
            out["skipped"] += 1
            out["results"].append({"event_id": lead.get("event_id"), "status": "skipped", "reason": reason})
            continue

        decil = lead.get("decil")
        value = compute_value(decil, business_config, lead.get("ab_conversion_rates"))
        event = build_event(
            email=lead.get("email"),
            phone=lead.get("phone"),
            value=value,
            currency=currency,
            event_timestamp_iso=lead.get("event_timestamp_iso"),
            transaction_id=lead.get("event_id"),
            gclid=lead.get("gclid"),   # opcional — None até o front popular
        )

        # 1) evento value-weighted (todos os decis)
        req = build_ingest_request(
            events=[event], customer_id=customer_id, conversion_action_id=ca_value,
            login_customer_id=google_config.login_customer_id, validate_only=dry_run,
        )
        res = _post_ingest(req)
        out["results"].append({"event_id": lead.get("event_id"), "destination": "value", "decil": decil, **res})
        out["sent" if res["status"] == "sent" else "errors"] += 1

        # 2) evento HQ (só decis altos) — paralelo ao high_quality do Meta
        if ca_hq and decil in hq_decils:
            req_hq = build_ingest_request(
                events=[event], customer_id=customer_id, conversion_action_id=ca_hq,
                login_customer_id=google_config.login_customer_id, validate_only=dry_run,
            )
            res_hq = _post_ingest(req_hq)
            out["results"].append({"event_id": lead.get("event_id"), "destination": "high_quality", "decil": decil, **res_hq})
            out["sent" if res_hq["status"] == "sent" else "errors"] += 1

    return out
