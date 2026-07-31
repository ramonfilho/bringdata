"""ETL de CADASTROS (todos os leads, respondentes ou não) do Railway → `analytics.cadastros`.

Fontes (Railway):
  - `Client`  : fonte VIVA do front (identidade + isBuyer + firstSeenAt + campaignKey…),
                20/03/2026 → hoje, ~1 linha por email.
  - `leads_capi`: log de eventos CAPI (histórico), 26/02 → jul, ~2,3 linhas/email
                (colapsado a 1 = evento mais recente + primeiro contato); traz utm_*/fbp/decil.

Merge por email (COALESCE: identidade da Client, atribuição da leads_capi). `is_respondent`
= email existe em `analytics.leads` (respondeu a pesquisa). Rótulo `source` = client /
leads_capi / client+leads_capi. Alvo = `analytics.cadastros` (Cloud SQL), upsert idempotente.

Uso:
  python -m src.data.cadastros_ingest --full            # carga cheia (Client + leads_capi)
  python -m src.data.cadastros_ingest --since <ISO>     # incremental (Client alterada)
  python -m src.data.cadastros_ingest --full --dry-run  # só audita, não escreve
"""
from __future__ import annotations

import argparse
import logging
from collections import Counter

from src.data.analytics_connection import open_analytics_connection
from src.data.cadastro_records import open_railway_connection
from src.data.cadastros_store import ensure_table, upsert_cadastros

logger = logging.getLogger(__name__)


def _e(x):
    if x is None:
        return None
    s = str(x).strip().lower()
    return s or None


def pull_client(rw, since: str | None = None) -> dict:
    """Snapshot da `Client` (1 por email). since = só `updatedAt` > since (incremental)."""
    # isBuyer da Client é IGNORADA de propósito: vem 100% False (o front não popula).
    # A verdade de comprador vem de analytics.sales (ver pull_buyers).
    sql = (
        'SELECT lower(email), phone, "firstName", "lastName", '
        '"firstSeenAt", "lastActivityAt", "campaignKey", "hasComputer", '
        'fbp, fbc, ip4, "userAgent", "pageSource", referrer, "eventId", "updatedAt" '
        'FROM "Client" WHERE email IS NOT NULL'
    )
    params = {}
    if since:
        sql += ' AND "updatedAt" > CAST(:since AS timestamptz)'
        params["since"] = since
    out = {}
    for r in rw.run(sql, **params):
        e = _e(r[0])
        if not e:
            continue
        # mantém o mais recente por updatedAt se houver email duplicado
        prev = out.get(e)
        if prev is not None and prev["updated_at_src"] and r[15] and r[15] < prev["updated_at_src"]:
            continue
        out[e] = {
            "email": e, "phone": r[1], "first_name": r[2], "last_name": r[3],
            "first_seen_at": r[4], "last_activity_at": r[5], "campaign_key": r[6], "has_computer": r[7],
            "fbp": r[8], "fbc": r[9], "ip": r[10], "user_agent": r[11], "page_source": r[12],
            "referrer": r[13], "event_id": r[14], "updated_at_src": r[15],
        }
    return out


def pull_capi(rw) -> dict:
    """leads_capi colapsada a 1 por email: evento MAIS RECENTE + primeiro contato (min created_at)."""
    latest = rw.run(
        'SELECT DISTINCT ON (lower(email)) lower(email), created_at, updated_at, fbp, fbc, '
        'event_id, user_agent, client_ip, utm_source, utm_medium, utm_campaign, utm_content, '
        'utm_term, lead_score, decil, first_name, last_name, phone '
        'FROM leads_capi WHERE email IS NOT NULL '
        'ORDER BY lower(email), created_at DESC'
    )
    first = {_e(r[0]): r[1] for r in rw.run(
        'SELECT lower(email), min(created_at) FROM leads_capi WHERE email IS NOT NULL GROUP BY 1'
    )}
    out = {}
    for r in latest:
        e = _e(r[0])
        if not e:
            continue
        out[e] = {
            "email": e, "first_seen_at": first.get(e) or r[1], "updated_at_src": r[2],
            "fbp": r[3], "fbc": r[4], "event_id": r[5], "user_agent": r[6], "ip": r[7],
            "utm_source": r[8], "utm_medium": r[9], "utm_campaign": r[10], "utm_content": r[11],
            "utm_term": r[12], "lead_score": r[13], "decil": r[14],
            "first_name": r[15], "last_name": r[16], "phone": r[17],
        }
    return out


def pull_respondents(led) -> set:
    """Emails que responderam a pesquisa (universo de treino) — pra marcar is_respondent."""
    resp = {_e(r[0]) for r in led.run("SELECT email FROM analytics.leads") if r[0]}
    resp |= {_e(r[0]) for r in led.run(
        "SELECT email FROM registros_ml WHERE survey_responses IS NOT NULL") if r[0]}
    resp.discard(None)
    return resp


def pull_buyers(led) -> set:
    """Emails que compraram (existem em analytics.sales) — pra marcar is_buyer.
    `Client.isBuyer` vem 100% False (o front não popula), então a verdade de comprador
    é a venda consolidada em analytics.sales."""
    b = {_e(r[0]) for r in led.run("SELECT email FROM analytics.sales") if r[0]}
    b.discard(None)
    return b


def _min(a, b):
    xs = [x for x in (a, b) if x is not None]
    return min(xs) if xs else None


def _max(a, b):
    xs = [x for x in (a, b) if x is not None]
    return max(xs) if xs else None


def build_rows(client: dict, capi: dict, respondents: set, buyers: set) -> list:
    """Merge por email: identidade da Client, atribuição da leads_capi, is_respondent
    (respondeu pesquisa) e is_buyer (comprou, de analytics.sales), source rotulado."""
    rows = []
    for e in set(client) | set(capi):
        c = client.get(e, {})
        k = capi.get(e, {})
        in_c, in_k = bool(c), bool(k)
        source = "client+leads_capi" if (in_c and in_k) else ("client" if in_c else "leads_capi")
        rows.append({
            "email": e,
            "phone": c.get("phone") or k.get("phone"),
            "first_name": c.get("first_name") or k.get("first_name"),
            "last_name": c.get("last_name") or k.get("last_name"),
            "is_buyer": e in buyers,
            "first_seen_at": _min(c.get("first_seen_at"), k.get("first_seen_at")),
            "last_activity_at": c.get("last_activity_at"),
            "campaign_key": c.get("campaign_key"),
            "utm_source": k.get("utm_source"),
            "utm_medium": k.get("utm_medium"),
            "utm_campaign": k.get("utm_campaign"),
            "utm_content": k.get("utm_content"),
            "utm_term": k.get("utm_term"),
            "has_computer": c.get("has_computer"),
            "fbp": c.get("fbp") or k.get("fbp"),
            "fbc": c.get("fbc") or k.get("fbc"),
            "ip": c.get("ip") or k.get("ip"),
            "user_agent": c.get("user_agent") or k.get("user_agent"),
            "page_source": c.get("page_source"),
            "referrer": c.get("referrer"),
            "event_id": c.get("event_id") or k.get("event_id"),
            "lead_score": k.get("lead_score"),
            "decil": k.get("decil"),
            "is_respondent": e in respondents,
            "source": source,
            "updated_at_src": _max(c.get("updated_at_src"), k.get("updated_at_src")),
        })
    return rows


def _audit(rows: list) -> None:
    src = Counter(r["source"] for r in rows)
    resp = sum(1 for r in rows if r["is_respondent"])
    buyers = sum(1 for r in rows if r["is_buyer"])
    ds = [r["first_seen_at"] for r in rows if r["first_seen_at"]]
    print(f"  cadastros construídos: {len(rows)}")
    print(f"  por source: {dict(src)}")
    print(f"  respondentes={resp}  não-respondentes={len(rows)-resp}  compradores={buyers}")
    if ds:
        print(f"  janela first_seen: {min(ds).date()} .. {max(ds).date()}")


def main(full: bool = True, since: str | None = None, dry_run: bool = False) -> dict:
    led = open_analytics_connection(timeout=300)
    rw = open_railway_connection(timeout=300)
    try:
        print("[cadastros_ingest] puxando Client…", flush=True)
        client = pull_client(rw, since=None if full else since)
        capi = pull_capi(rw) if full else {}
        print(f"[cadastros_ingest] Client={len(client)} leads_capi={len(capi)}", flush=True)
        print("[cadastros_ingest] puxando respondentes + compradores…", flush=True)
        respondents = pull_respondents(led)
        buyers = pull_buyers(led)
        print(f"[cadastros_ingest] respondentes={len(respondents)} compradores={len(buyers)}", flush=True)
        rows = build_rows(client, capi, respondents, buyers)
        _audit(rows)
        if dry_run:
            print("[cadastros_ingest] DRY-RUN — nada escrito.")
            return {"rows": len(rows), "dry_run": True}
        ensure_table(led)
        res = upsert_cadastros(rows, conn=led)
        print(f"[cadastros_ingest] upsert: {res}")
        return res
    finally:
        rw.close()
        led.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="carga cheia (Client + leads_capi)")
    ap.add_argument("--since", default=None, help="incremental: Client com updatedAt > ISO")
    ap.add_argument("--dry-run", action="store_true", help="audita, não escreve")
    a = ap.parse_args()
    main(full=a.full or a.since is None, since=a.since, dry_run=a.dry_run)
