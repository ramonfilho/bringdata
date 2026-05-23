"""[DEPRECATED 2026-05-23 — não usado pelo caminho Pub/Sub]

Arquitetura antiga (I3 da frente capi-lead-surveys, paused 2026-05-19):
enriquecia survey leads por parse de `integration_logs` no Railway, recuperando
computador/fbp/fbc/telefone/nome/ip/user_agent. Foi tornado obsoleto quando o
sistema novo do dono passou a publicar TODOS esses campos diretamente no
payload Pub/Sub — eliminando o JOIN frágil + parse de JSON de log.

Não é importado por nada no caminho Pub/Sub. Mantido temporariamente para
referência histórica do design (commits I3 da frente capi-lead-surveys).

— histórico original abaixo —

I3 — Enriquecimento em lote dos survey leads (read-only).

Dado um lote de linhas da `lead_surveys`, recupera por lead:
  - `utm`    : {source, medium, campaign, content, term, url}  ← `UTMTracking`
  - `enrich` : {computador, telefone, nome, fbp, fbc, ip, user_agent}
               ← `integration_logs` (meta_capi / n8n_onboarding / activecampaign)
  - `meta_eligible` : bool — `source` ∈ {facebook-ads, fb, ig}. Só esses vão
                      ao Meta (resto é bloqueado pela allowlist no envio).

Decisões fixadas (PROCESSO_CAPI_LEAD_SURVEYS §9 / sessão 18/05):
  1. fbp/fbc/ip/ua: JOIN preciso por `eventId`
     (`lead_surveys.eventId` == meta_capi `requestPayload#>>'{data,0,event_id}'`,
     1:1, ~99,7%); fallback meta_capi mais recente por email (~99,9%).
     `UTMTracking`/`n8n_onboarding` não têm eventId → sempre por email.
  2. UTM: linha mais recente do `UTMTracking` com `trackedAt <= submittedAt`;
     se não houver, a mais recente do email.
  3. Cobertura: `fbpfbc` medido **só sobre Meta-elegíveis** (fb/ig) — google-ads
     não tem `fbc` por natureza e é bloqueado no envio; medi-lo globalmente
     daria alarme crônico falso (medido 18/05: fb/ig 242/242=100%, google-ads
     0%). `utm`/`computador` continuam globais.

**Sem alarme aqui.** O I3 só calcula o stat do lote e loga (informativo). O
fail-loud sistêmico ("sinal sumindo") é rolling no tempo sobre o ledger
`registros_ml` e vive no I5 — imune a tamanho de lote (lotes do polling são
pequenos, ~1-3 leads; um guard per-batch cegaria a detecção).

Computador: `n8n_onboarding.tem_computador` precede; fallback `activecampaign`
campo 144 (validado 1011/1011 == tem_computador, 18/05).

`enrich_survey_batch` faz só SELECTs read-only e reaproveita a conexão pg8000
do endpoint (não abre conexão nova). `_assemble` é puro e testável offline.
Nada é importado pelo fluxo `Lead`; wiring só no I4.
"""
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 30  # janela p/ buscar UTMTracking/integration_logs do lote
META_SOURCES = {"facebook-ads", "fb", "ig"}  # mesmo predicado Meta usado no resto do código


def _norm_email(e) -> Optional[str]:
    if e is None:
        return None
    s = str(e).strip().lower()
    return s or None


def _is_meta(source) -> bool:
    return str(source or "").strip().lower() in META_SOURCES


def _pick_utm(cands: List[Tuple], submitted_at) -> Dict:
    """cands: lista de (trackedAt, dict_utm). Mais recente com trackedAt <=
    submittedAt; senão a mais recente no geral; senão {}."""
    if not cands:
        return {}
    le = [c for c in cands if submitted_at is not None and c[0] is not None and c[0] <= submitted_at]
    chosen = max(le, key=lambda c: c[0]) if le else max(
        cands, key=lambda c: (c[0] is not None, c[0])
    )
    return chosen[1] or {}


def _assemble(
    survey_rows: List[Dict],
    utm_by_email: Dict[str, List[Tuple]],
    mc_by_eventid: Dict[str, Dict],
    mc_by_email: Dict[str, Dict],
    n8_by_email: Dict[str, Dict],
    ac_by_email: Dict[str, str],
) -> Tuple[Dict[str, Dict], Dict]:
    """Pura. Monta por lead {'utm','enrich','meta_eligible'} + stat de cobertura
    do lote (informativo; NÃO decide alarme — isso é do I5 sobre o ledger)."""
    by_id: Dict[str, Dict] = {}
    n_utm = n_comp = 0
    meta_n = meta_fbpfbc = 0

    for row in survey_rows:
        lid = row.get("id")
        em = _norm_email(row.get("clientEmail"))
        ev = row.get("eventId")
        sub = row.get("submittedAt")

        utm = _pick_utm(utm_by_email.get(em, []), sub) if em else {}

        mc = (mc_by_eventid.get(ev) if ev else None) or (mc_by_email.get(em) if em else None) or {}
        n8 = (n8_by_email.get(em) if em else None) or {}
        computador = n8.get("tem_computador") or (ac_by_email.get(em) if em else None)

        enrich = {
            "computador": computador or None,
            "telefone": n8.get("telefone") or None,
            "nome": n8.get("nome") or None,
            "fbp": mc.get("fbp") or None,
            "fbc": mc.get("fbc") or None,
            "ip": mc.get("ip") or row.get("ip") or None,
            "user_agent": mc.get("user_agent") or None,
        }
        meta_eligible = _is_meta(utm.get("source"))

        if utm.get("source"):
            n_utm += 1
        if enrich["computador"]:
            n_comp += 1
        if meta_eligible:
            meta_n += 1
            if enrich["fbp"] and enrich["fbc"]:
                meta_fbpfbc += 1

        by_id[lid] = {"utm": utm, "enrich": enrich, "meta_eligible": meta_eligible}

    n = len(survey_rows)
    cov = {
        "n": n,
        "meta_n": meta_n,
        "utm_pct": round(n_utm / n, 4) if n else 0.0,
        "computador_pct": round(n_comp / n, 4) if n else 0.0,
        # fbp+fbc só faz sentido entre Meta-elegíveis; None se não há nenhum no lote
        "fbpfbc_meta_pct": round(meta_fbpfbc / meta_n, 4) if meta_n else None,
    }
    logger.info(
        "[survey_enrichment] lote n=%d meta=%d | utm=%.0f%% computador=%.0f%% "
        "fbp+fbc(meta)=%s — stat informativo; alarme sistêmico é do I5 (ledger rolling).",
        n, meta_n, cov["utm_pct"] * 100, cov["computador_pct"] * 100,
        f"{cov['fbpfbc_meta_pct'] * 100:.0f}%" if cov["fbpfbc_meta_pct"] is not None else "n/a",
    )
    return by_id, cov


def enrich_survey_batch(
    conn,
    survey_rows: List[Dict],
    *,
    lookback_days: int = LOOKBACK_DAYS,
) -> Tuple[Dict[str, Dict], Dict]:
    """Read-only. `survey_rows` precisa de: id, clientEmail, eventId,
    submittedAt (ip opcional). Reaproveita `conn` (pg8000.native). Não escreve."""
    if not survey_rows:
        return {}, {"n": 0, "meta_n": 0, "utm_pct": 0.0,
                    "computador_pct": 0.0, "fbpfbc_meta_pct": None}

    emails = sorted({e for e in (_norm_email(r.get("clientEmail")) for r in survey_rows) if e})
    eventids = sorted({r.get("eventId") for r in survey_rows if r.get("eventId")})
    win = f"now() - interval '{int(lookback_days)} days'"

    # UTMTracking — todas as linhas do lote na janela (recência resolvida em _assemble)
    utm_by_email: Dict[str, List[Tuple]] = {}
    for r in conn.run(
        f'''SELECT lower(trim("clientEmail")) em, source, medium, campaign,
                   content, term, url, "trackedAt"
            FROM "UTMTracking"
            WHERE lower(trim("clientEmail")) = ANY(:ems) AND "trackedAt" >= {win}''',
        ems=emails,
    ):
        utm_by_email.setdefault(r[0], []).append(
            (r[7], {"source": r[1], "medium": r[2], "campaign": r[3],
                    "content": r[4], "term": r[5], "url": r[6]})
        )

    # meta_capi por eventId (preciso) — mais recente por event_id com fbp/fbc
    mc_by_eventid: Dict[str, Dict] = {}
    if eventids:
        for r in conn.run(
            f'''SELECT DISTINCT ON (ev) ev, fbp, fbc, ip, ua FROM (
                  SELECT "requestPayload" #>> '{{data,0,event_id}}' ev,
                         "requestPayload" #>> '{{data,0,user_data,fbp}}' fbp,
                         "requestPayload" #>> '{{data,0,user_data,fbc}}' fbc,
                         "requestPayload" #>> '{{data,0,user_data,client_ip_address}}' ip,
                         "requestPayload" #>> '{{data,0,user_data,client_user_agent}}' ua,
                         "createdAt"
                  FROM integration_logs
                  WHERE integration='meta_capi' AND "createdAt" >= {win}
                ) s
                WHERE ev = ANY(:evs) AND fbp IS NOT NULL AND fbp <> ''
                ORDER BY ev, "createdAt" DESC''',
            evs=eventids,
        ):
            mc_by_eventid[r[0]] = {"fbp": r[1], "fbc": r[2], "ip": r[3], "user_agent": r[4]}

    # meta_capi por email (fallback) — mais recente por email com fbp/fbc
    mc_by_email: Dict[str, Dict] = {}
    for r in conn.run(
        f'''SELECT DISTINCT ON (em) em, fbp, fbc, ip, ua FROM (
              SELECT lower(trim("clientEmail")) em,
                     "requestPayload" #>> '{{data,0,user_data,fbp}}' fbp,
                     "requestPayload" #>> '{{data,0,user_data,fbc}}' fbc,
                     "requestPayload" #>> '{{data,0,user_data,client_ip_address}}' ip,
                     "requestPayload" #>> '{{data,0,user_data,client_user_agent}}' ua,
                     "createdAt"
              FROM integration_logs
              WHERE integration='meta_capi' AND "createdAt" >= {win}
            ) s
            WHERE em = ANY(:ems) AND fbp IS NOT NULL AND fbp <> ''
            ORDER BY em, "createdAt" DESC''',
        ems=emails,
    ):
        mc_by_email[r[0]] = {"fbp": r[1], "fbc": r[2], "ip": r[3], "user_agent": r[4]}

    # n8n_onboarding por email — mais recente
    n8_by_email: Dict[str, Dict] = {}
    for r in conn.run(
        f'''SELECT DISTINCT ON (em) em, tc, tel, nm FROM (
              SELECT lower(trim("clientEmail")) em,
                     upper(trim("requestPayload" ->> 'tem_computador')) tc,
                     "requestPayload" ->> 'telefone' tel,
                     "requestPayload" ->> 'nome' nm,
                     "createdAt"
              FROM integration_logs
              WHERE integration='n8n_onboarding' AND "createdAt" >= {win}
            ) s
            WHERE em = ANY(:ems)
            ORDER BY em, "createdAt" DESC''',
        ems=emails,
    ):
        n8_by_email[r[0]] = {"tem_computador": r[1] or None,
                             "telefone": r[2], "nome": r[3]}

    # activecampaign campo 144 (fallback computador) por email — mais recente
    ac_by_email: Dict[str, str] = {}
    for r in conn.run(
        f'''SELECT DISTINCT ON (em) em, v FROM (
              SELECT lower(trim(il."clientEmail")) em,
                     upper(trim((SELECT fv->>'value'
                       FROM jsonb_array_elements(
                              il."requestPayload" #> '{{contact,contact,fieldValues}}') fv
                       WHERE fv->>'field'='144' LIMIT 1))) v,
                     il."createdAt"
              FROM integration_logs il
              WHERE il.integration='activecampaign' AND il."createdAt" >= {win}
            ) s
            WHERE em = ANY(:ems) AND v IS NOT NULL AND v <> ''
            ORDER BY em, "createdAt" DESC''',
        ems=emails,
    ):
        ac_by_email[r[0]] = r[1]

    return _assemble(
        survey_rows, utm_by_email, mc_by_eventid, mc_by_email,
        n8_by_email, ac_by_email,
    )
