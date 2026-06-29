"""ETL de recuperação de `analytics.leads` (frente `recuperacao-leads-ua`).

Duas operações idempotentes, dry-run por padrão:

  Parte A — leads recentes (pós-migração 23/05) do ledger `registros_ml` →
            `analytics.leads` com `source='registros_ml'`. Traz pesquisa
            (traduzida pelo MESMO `railway_lead_to_sheets_row` que o
            `scores_refresh` usa) + decil + score + variant + utm + fbp/fbc +
            **user_agent**. Reusa o writer multi-fonte `leads_store.upsert_leads`.

  Parte B — backfill de `user_agent` nos leads `source='train_pesquisa'`
            (pré-migração, ~132k de 2026) cuja coluna está vazia. O UA vem das
            tabelas antigas do front no Railway (`Lead.userAgent`,
            `leads_capi.user_agent`), casado por email + **data mais próxima**
            (point-in-time: um email pode ter vários UA ao longo do tempo).

Decisão de arquitetura (/sw-architect): estende-se o writer multi-fonte que já
existe (`leads_store`), em vez de ETL paralelo — a tabela foi desenhada pra
consolidar fontes (coluna `source`, dedup por fonte, 'registros_ml' já válido).

Rollback (minutos):
  A: DELETE FROM leads WHERE source='registros_ml';
  B: UPDATE leads SET user_agent=NULL WHERE source='train_pesquisa';

Uso:
  python -m src.data.etl_leads_recovery --part A          # dry-run
  python -m src.data.etl_leads_recovery --part A --execute
  python -m src.data.etl_leads_recovery --part B --execute
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import ssl
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection
from src.data.leads_store import upsert_leads

logger = logging.getLogger(__name__)

CLIENT_ID = "devclub"


# ---------------------------------------------------------------------------
# Conexão Railway (front antigo: Lead.userAgent / leads_capi.user_agent)
# ---------------------------------------------------------------------------
def _open_railway_connection():
    """pg8000 no Railway do front (envs RAILWAY_DB_*). Só leitura aqui."""
    import pg8000.native

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ.get("RAILWAY_DB_PORT", "5432")),
        database=os.environ.get("RAILWAY_DB_NAME"),
        user=os.environ.get("RAILWAY_DB_USER"),
        password=os.environ["RAILWAY_DB_PASSWORD"],
        ssl_context=ctx,
        timeout=120,
    )


# ===========================================================================
# PARTE A — recuperar leads recentes do registros_ml
# ===========================================================================
def _registros_ml_to_records(conn) -> list[dict]:
    """Lê `public.registros_ml` (mesma instância Cloud SQL) e devolve registros no
    shape que `upsert_leads` consome. `survey_responses` é o dict no formato
    pesquisa (chaves = textos das perguntas), via `railway_lead_to_sheets_row`."""
    from api.railway_mapping import railway_lead_to_sheets_row

    rows = conn.run(
        """
        SELECT email, phone, first_name, last_name, created_at, survey_responses,
               utm_source, utm_medium, utm_campaign, utm_content, utm_term, utm_url,
               has_computer, decil, lead_score, variant, fbp, fbc, user_agent, ip,
               event_id
        FROM public.registros_ml
        WHERE email IS NOT NULL AND survey_responses IS NOT NULL
        ORDER BY created_at
        """
    )
    records = []
    for (email, phone, fn, ln, created, sr, src, med, camp, cont, term, url,
         has_comp, decil, lead_score, variant, fbp, fbc, user_agent, ip,
         event_id) in rows:
        pesq = json.loads(sr) if isinstance(sr, str) else dict(sr or {})
        pesq["computador"] = has_comp  # mesma injeção do scores_refresh
        nome = " ".join(p for p in [fn, ln] if p) or None
        sheets_row = railway_lead_to_sheets_row({
            "email": email, "nomeCompleto": nome, "telefone": phone,
            "data": created, "source": src, "medium": med, "campaign": camp,
            "content": cont, "term": term, "pesquisa": pesq,
        })
        records.append({
            "email": email, "phone": phone, "first_name": fn, "last_name": ln,
            "capturado_em": created, "decil": decil, "score": lead_score,
            "variant": variant,
            "utm_source": src, "utm_medium": med, "utm_campaign": camp,
            "utm_content": cont, "utm_term": term, "utm_url": url,
            "fbp": fbp, "fbc": fbc, "user_agent": user_agent, "ip": ip,
            "has_computer": has_comp, "event_id": event_id,
            "survey_responses": sheets_row,
        })
    return records


def recuperar_leads_registros_ml(dry_run: bool = True) -> dict:
    conn = open_analytics_connection()  # Cloud SQL; search_path analytics,public
    try:
        records = _registros_ml_to_records(conn)
        df = pd.DataFrame(records)
        total = len(df)
        # quantos desses emails JÁ existem em analytics.leads (qualquer source)
        ja = conn.run(
            "SELECT count(DISTINCT lower(trim(email))) FROM leads "
            "WHERE email IS NOT NULL AND email <> ''"
        )[0][0]
        emails = {str(e).strip().lower() for e in df["email"].dropna()}
        existentes = conn.run(
            "SELECT DISTINCT lower(trim(email)) FROM leads WHERE email IS NOT NULL AND email<>''"
        )
        existentes = {r[0] for r in existentes if r[0]}
        novos = len(emails - existentes)
        com_ua = int(df["user_agent"].apply(lambda x: bool(x) and str(x).strip() != "").sum())
        com_decil = int(df["decil"].notna().sum())
        logger.info("[recuperar A] registros_ml=%d | emails novos p/ a tabela=%d | "
                    "com user_agent=%d | com decil=%d", total, novos, com_ua, com_decil)
        if dry_run:
            print(f"[DRY-RUN A] registros_ml lidos: {total}")
            print(f"  emails ainda ausentes de analytics.leads: {novos}")
            print(f"  com user_agent: {com_ua} | com decil: {com_decil}")
            if total:
                amostra = df.iloc[0]
                print("  amostra survey_responses keys:",
                      list(amostra['survey_responses'].keys())[:8])
                print("  amostra:", {k: amostra[k] for k in
                      ['email', 'capturado_em', 'decil', 'score', 'user_agent']})
            return {"lidos": total, "novos": novos, "com_ua": com_ua, "executado": False}
        res = upsert_leads(df, source="registros_ml", client_id=CLIENT_ID, conn=conn)
        print(f"[EXEC A] upsert source=registros_ml: {res}")
        return {**res, "executado": True}
    finally:
        conn.close()


# ===========================================================================
# PARTE B — backfill de user_agent nos leads train_pesquisa
# ===========================================================================
def _norm_email(x) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip().lower()
    return s or None


def _carregar_ua_railway(rail) -> dict:
    """email_norm → lista de (data, user_agent), das tabelas antigas do front."""
    from collections import defaultdict
    lookup: dict[str, list] = defaultdict(list)
    queries = [
        ('SELECT email, COALESCE(data, "createdAt") d, "userAgent" ua FROM "Lead" '
         'WHERE "userAgent" IS NOT NULL AND "userAgent" <> \'\' AND email IS NOT NULL'),
        ("SELECT email, created_at d, user_agent ua FROM leads_capi "
         "WHERE user_agent IS NOT NULL AND user_agent <> '' AND email IS NOT NULL"),
    ]
    for q in queries:
        for email, d, ua in rail.run(q):
            e = _norm_email(email)
            if e and ua:
                lookup[e].append((d, ua))
    return lookup


def _pick_nearest(cand: list, ref) -> Optional[str]:
    """UA da captação mais próxima de `ref` (point-in-time). Sem ref → primeiro."""
    if not cand:
        return None
    if ref is None:
        return cand[0][1]
    ref_ts = pd.Timestamp(ref)
    if ref_ts.tzinfo is not None:
        ref_ts = ref_ts.tz_localize(None)
    best, best_delta = None, None
    for d, ua in cand:
        if d is None:
            continue
        dt = pd.Timestamp(d)
        if dt.tzinfo is not None:
            dt = dt.tz_localize(None)
        delta = abs((dt - ref_ts).total_seconds())
        if best_delta is None or delta < best_delta:
            best, best_delta = ua, delta
    return best if best is not None else cand[0][1]


def backfill_user_agent(dry_run: bool = True, batch_size: int = 500) -> dict:
    led = open_analytics_connection()
    rail = _open_railway_connection()
    try:
        alvos = led.run(
            "SELECT id, lower(trim(email)) email, capturado_em FROM leads "
            "WHERE source = 'train_pesquisa' AND (user_agent IS NULL OR user_agent = '') "
            "AND email IS NOT NULL AND email <> ''"
        )
        logger.info("[backfill B] alvos (train_pesquisa, UA nulo): %d", len(alvos))
        lookup = _carregar_ua_railway(rail)
        logger.info("[backfill B] emails com UA no Railway: %d", len(lookup))

        updates = []  # (id, ua)
        for lead_id, email, cap in alvos:
            cand = lookup.get(email)
            if not cand:
                continue
            ua = _pick_nearest(cand, cap)
            if ua:
                updates.append((lead_id, ua))

        print(f"[{'DRY-RUN' if dry_run else 'EXEC'} B] alvos sem UA: {len(alvos)} | "
              f"casados no Railway: {len(updates)} | "
              f"taxa: {len(updates)/max(len(alvos),1)*100:.1f}%")
        if dry_run:
            for lead_id, ua in updates[:3]:
                print("  amostra:", lead_id, "->", ua[:70])
            return {"alvos": len(alvos), "casados": len(updates), "executado": False}

        # UPDATE em lote via VALUES, só onde ainda está nulo (re-rodável)
        atualizados = 0
        for start in range(0, len(updates), batch_size):
            chunk = updates[start:start + batch_size]
            values, params = [], {}
            for i, (lead_id, ua) in enumerate(chunk):
                params[f"id_{i}"] = lead_id
                params[f"ua_{i}"] = ua
                values.append(f"(:id_{i}, :ua_{i})")
            sql = (
                "UPDATE leads SET user_agent = v.ua "
                "FROM (VALUES " + ", ".join(values) + ") AS v(id, ua) "
                "WHERE leads.id = v.id::bigint AND (leads.user_agent IS NULL OR leads.user_agent = '')"
            )
            led.run(sql, **params)
            atualizados += len(chunk)
        print(f"[EXEC B] linhas atualizadas: {atualizados}")
        return {"alvos": len(alvos), "casados": len(updates),
                "atualizados": atualizados, "executado": True}
    finally:
        led.close()
        rail.close()


# ===========================================================================
def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Recuperação de leads/UA em analytics.leads")
    ap.add_argument("--part", choices=["A", "B", "all"], required=True)
    ap.add_argument("--execute", action="store_true",
                    help="Sem esta flag = dry-run (não escreve).")
    args = ap.parse_args()
    dry = not args.execute

    if args.part in ("A", "all"):
        print("=== PARTE A: recuperar leads do registros_ml ===")
        recuperar_leads_registros_ml(dry_run=dry)
    if args.part in ("B", "all"):
        print("=== PARTE B: backfill user_agent ===")
        backfill_user_agent(dry_run=dry)


if __name__ == "__main__":
    main()
