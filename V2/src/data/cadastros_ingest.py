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


def backfill_leads(buyers) -> dict:
    """Adiciona os respondentes ANTIGOS (analytics.leads) que ainda não estão em cadastros,
    100% SERVER-SIDE (INSERT ... SELECT no próprio Cloud SQL): nada de trazer 357k linhas pro
    Python — só a contagem volta, então é robusto a queda de socket. `ON CONFLICT DO NOTHING`
    não toca quem já veio de Client/leads_capi. is_buyer é reafirmado por PK (lista pequena)."""
    # Chunk em 16 baldes por md5(email): cada ~22k linhas → rápido, o socket não estoura.
    # md5 é determinístico por email, então TODOS os registros de uma pessoa caem no MESMO
    # balde → DISTINCT ON e min(capturado_em) continuam corretos (1 linha por pessoa).
    insert_sql = (
        "INSERT INTO cadastros "
        "(email, phone, first_name, last_name, is_buyer, first_seen_at, "
        " utm_source, utm_medium, utm_campaign, utm_content, utm_term, "
        " has_computer, fbp, fbc, ip, user_agent, decil, lead_score, is_respondent, source) "
        "SELECT DISTINCT ON (lower(email)) "
        "  lower(email), phone, first_name, last_name, false, "
        "  min(capturado_em) OVER (PARTITION BY lower(email)), "
        "  utm_source, utm_medium, utm_campaign, utm_content, utm_term, "
        "  has_computer, fbp, fbc, ip, user_agent, decil, score, true, 'leads' "
        "FROM analytics.leads WHERE email IS NOT NULL AND left(md5(lower(email)), 1) = :bkt "
        "ORDER BY lower(email), capturado_em DESC NULLS LAST "
        "ON CONFLICT (email) DO NOTHING"
    )
    led = open_analytics_connection(timeout=600)
    try:
        before = led.run("SELECT count(*) FROM cadastros")[0][0]
        for bkt in "0123456789abcdef":
            for attempt in range(5):
                try:
                    led.run(insert_sql, bkt=bkt)
                    break
                except Exception as e:  # noqa: BLE001 — rede instável; reconecta e re-tenta o balde
                    if attempt == 4:
                        raise
                    logger.warning("[backfill_leads] balde %s falhou (%s); reconectando", bkt, str(e)[:60])
                    try:
                        led.close()
                    except Exception:  # noqa: BLE001
                        pass
                    led = open_analytics_connection(timeout=600)
        blist = sorted(e for e in buyers if e)
        if blist:
            led.run("UPDATE cadastros SET is_buyer = true WHERE email = ANY(:b)", b=blist)
        after = led.run("SELECT count(*) FROM cadastros")[0][0]
        return {"before": before, "after": after, "inserted": after - before}
    finally:
        led.close()


def _naive(x):
    # analytics.leads.capturado_em é timestamptz (aware); Client/leads_capi são naive.
    # Compara/grava tudo como wall-clock naive (o sistema opera em UTC).
    if x is not None and getattr(x, "tzinfo", None) is not None:
        return x.replace(tzinfo=None)
    return x


def _min(a, b):
    xs = [_naive(x) for x in (a, b) if x is not None]
    return min(xs) if xs else None


def _max(a, b):
    xs = [_naive(x) for x in (a, b) if x is not None]
    return max(xs) if xs else None


def build_rows(client: dict, capi: dict, leads: dict, respondents: set, buyers: set) -> list:
    """Merge por email de 3 fontes: Client (identidade+front), leads_capi (atribuição),
    analytics.leads (respondentes antigos). COALESCE na ordem client > leads_capi > leads.
    is_respondent (respondeu pesquisa), is_buyer (comprou, de analytics.sales), source rotulado."""
    rows = []
    allem = set(client) | set(capi) | set(leads)
    for e in allem:
        c = client.get(e, {})
        k = capi.get(e, {})
        l = leads.get(e, {})
        present = [n for n, d in (("client", c), ("leads_capi", k), ("leads", l)) if d]
        pick = lambda f: c.get(f) or k.get(f) or l.get(f)  # COALESCE client > capi > leads
        rows.append({
            "email": e,
            "phone": pick("phone"),
            "first_name": pick("first_name"),
            "last_name": pick("last_name"),
            "is_buyer": e in buyers,
            "first_seen_at": _min(_min(c.get("first_seen_at"), k.get("first_seen_at")), l.get("first_seen_at")),
            "last_activity_at": c.get("last_activity_at"),
            "campaign_key": c.get("campaign_key"),
            "utm_source": k.get("utm_source") or l.get("utm_source"),
            "utm_medium": k.get("utm_medium") or l.get("utm_medium"),
            "utm_campaign": k.get("utm_campaign") or l.get("utm_campaign"),
            "utm_content": k.get("utm_content") or l.get("utm_content"),
            "utm_term": k.get("utm_term") or l.get("utm_term"),
            "has_computer": c.get("has_computer") or l.get("has_computer"),
            "fbp": pick("fbp"),
            "fbc": pick("fbc"),
            "ip": pick("ip"),
            "user_agent": pick("user_agent"),
            "page_source": c.get("page_source"),
            "referrer": c.get("referrer"),
            "event_id": c.get("event_id") or k.get("event_id"),
            "lead_score": k.get("lead_score") or l.get("lead_score"),
            "decil": k.get("decil") or l.get("decil"),
            "is_respondent": e in respondents,
            "source": "+".join(present),
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
    led = open_analytics_connection(timeout=600)
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
        # Front-era (Client + leads_capi, Railway) montada no Python:
        rows = build_rows(client, capi, {}, respondents, buyers)
        _audit(rows)
        if dry_run:
            print("[cadastros_ingest] DRY-RUN — nada escrito.")
            return {"rows": len(rows), "dry_run": True}
        ensure_table(led)
    finally:
        rw.close()
        try:
            led.close()
        except Exception:  # noqa: BLE001
            pass

    # Escrita separada da leitura: cada store abre a própria conexão (resiliente a queda).
    # Front-era via upsert Python; respondentes ANTIGOS via backfill server-side no Cloud SQL.
    res = upsert_cadastros(rows)
    print(f"[cadastros_ingest] upsert front-era: {res}")
    if full:
        bf = backfill_leads(buyers)
        print(f"[cadastros_ingest] backfill leads (server-side): {bf}")
        res["backfill_leads"] = bf
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="carga cheia (Client + leads_capi)")
    ap.add_argument("--since", default=None, help="incremental: Client com updatedAt > ISO")
    ap.add_argument("--dry-run", action="store_true", help="audita, não escreve")
    a = ap.parse_args()
    main(full=a.full or a.since is None, since=a.since, dry_run=a.dry_run)
