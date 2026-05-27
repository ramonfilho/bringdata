#!/usr/bin/env python3
"""scripts/backfill_google_scoring.py

Retro-score Google leads em `registros_ml` que entraram antes do
desacoplamento scoring × Meta CAPI (deploy 2026-05-27, revisão 00609-xot).

Esses leads foram gravados pelo Pub/Sub consumer com `status_envio =
'skipped_allowlist'` e `score = NULL` porque o gate antigo abortava o scoring
antes de chamar o modelo. O `survey_responses` ficou preservado — então dá
pra recalcular o score retroativamente.

Estratégia:
    1. Query Railway: Google leads com score=NULL em [LF57_start, now].
    2. Para cada event_id, chama POST /predict/explain (sem efeitos colaterais
       — apenas re-roda o pipeline em memória e devolve score+decil).
    3. UPDATE registros_ml SET lead_score, decil, variant WHERE event_id=...
       (preserva status_envio='skipped_allowlist' — backfill NÃO envia CAPI).

Idempotente: pula leads que já têm score (`AND lead_score IS NULL` na query).
Re-rodar não re-scoreia o que já foi backfilado.

Uso:
    eval "$(grep -E '^RAILWAY_DB_' V2/.env | sed 's/^/export /')"
    python3 V2/scripts/backfill_google_scoring.py --dry-run   # 1ª passada
    python3 V2/scripts/backfill_google_scoring.py             # de verdade

Args opcionais:
    --since YYYY-MM-DD    início da janela (default: 2026-05-25, cap_start LF57)
    --until YYYY-MM-DD    fim da janela    (default: hoje)
    --dry-run             só lista o que faria; não chama API nem UPDATE
    --api-url             override do endpoint (default: Cloud Run prod)
    --limit N             corta em N leads (debug)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pg8000.native


DEFAULT_API_URL = "https://smart-ads-api-12955519745.us-central1.run.app"
DEFAULT_SINCE = "2026-05-25"  # cap_start LF57

# utm_source que classificamos como "Google" — mesma frozenset usada em
# daily_check_aggregations._classify_source. Mantém o backfill alinhado com
# o que o monitoramento conta como `ggl` no funil.
_GOOGLE_SOURCES = ("google-ads",)


def _connect_railway() -> pg8000.native.Connection:
    return pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ["RAILWAY_DB_PORT"]),
        user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"],
        database=os.environ["RAILWAY_DB_NAME"],
        ssl_context=True,
    )


def fetch_pending(conn, *, since_iso: str, until_iso: str) -> list[tuple]:
    """Devolve (event_id, created_at, utm_source, has_computer) dos leads
    que precisam de backfill — Google, sem score, com survey preenchido."""
    rows = conn.run(
        """
        SELECT event_id, created_at, utm_source, has_computer
        FROM registros_ml
        WHERE LOWER(COALESCE(utm_source, '')) = ANY(:sources)
          AND created_at >= :since
          AND created_at <  :until
          AND lead_score IS NULL
          AND survey_responses IS NOT NULL
        ORDER BY created_at ASC
        """,
        sources=list(_GOOGLE_SOURCES),
        since=since_iso,
        until=until_iso,
    )
    return rows


def call_explain(api_url: str, event_id: str, timeout: int = 30) -> dict | None:
    """POST /predict/explain — retorna o dict de scoring ou None em erro."""
    body = json.dumps({
        "event_id": event_id,
        "source": "registros_ml",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{api_url}/predict/explain",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:200]
        print(f"  ✗ HTTP {e.code} pra {event_id}: {detail}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ✗ erro {type(e).__name__} pra {event_id}: {e}", file=sys.stderr)
        return None


def update_ledger(conn, event_id: str, lead_score: float, decil: int,
                  variant: str | None) -> int:
    """UPDATE com guarda `WHERE lead_score IS NULL` — não sobrescreve leads
    já scoreados (proteção extra além do filtro da query inicial, caso outro
    processo escreva entre o SELECT e o UPDATE)."""
    res = conn.run(
        """
        UPDATE registros_ml
           SET lead_score = :score,
               decil      = :decil,
               variant    = :variant
         WHERE event_id   = :eid
           AND lead_score IS NULL
        """,
        score=lead_score, decil=decil, variant=variant, eid=event_id,
    )
    # pg8000 não devolve rowcount via .run() — checamos via SELECT (caro pra
    # cada lead). Confiamos no WHERE e o resumo final usa o contador local.
    return 1 if res is not None else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default=DEFAULT_SINCE,
                    help=f"YYYY-MM-DD início (default {DEFAULT_SINCE} = cap_start LF57)")
    ap.add_argument("--until", default=None,
                    help="YYYY-MM-DD fim (default: amanhã, pra pegar tudo até agora)")
    ap.add_argument("--api-url", default=DEFAULT_API_URL,
                    help=f"endpoint base (default {DEFAULT_API_URL})")
    ap.add_argument("--dry-run", action="store_true",
                    help="não chama API nem UPDATE; só lista o que faria")
    ap.add_argument("--limit", type=int, default=None,
                    help="máximo de leads processados (debug)")
    args = ap.parse_args()

    # Janela inclui o dia "until" inteiro — usa <until 00:00 do dia seguinte
    if args.until is None:
        until_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        until_date = (datetime.strptime(args.until, "%Y-%m-%d")
                      + timedelta(days=1)).strftime("%Y-%m-%d")

    since_iso = f"{args.since}T00:00:00+00:00"
    until_iso = f"{until_date}T00:00:00+00:00"

    print(f"━━━ backfill_google_scoring ━━━")
    print(f"  janela:  [{since_iso}  →  {until_iso})")
    print(f"  fontes:  {_GOOGLE_SOURCES}")
    print(f"  api:     {args.api_url}")
    print(f"  dry-run: {args.dry_run}")
    print()

    for v in ("RAILWAY_DB_HOST", "RAILWAY_DB_PORT", "RAILWAY_DB_USER",
              "RAILWAY_DB_PASSWORD", "RAILWAY_DB_NAME"):
        if not os.environ.get(v):
            print(f"✗ env {v} não definida. Rode:", file=sys.stderr)
            print(f'  eval "$(grep -E \'^RAILWAY_DB_\' V2/.env | sed \'s/^/export /\')"', file=sys.stderr)
            sys.exit(2)

    conn = _connect_railway()
    pending = fetch_pending(conn, since_iso=since_iso, until_iso=until_iso)
    print(f"  encontrados: {len(pending)} leads")
    if args.limit:
        pending = pending[:args.limit]
        print(f"  cortado em: {len(pending)} (--limit)")

    if not pending:
        print("  nada a fazer.")
        return

    if args.dry_run:
        print()
        print("  amostra (primeiros 10):")
        for eid, created, src, hc in pending[:10]:
            print(f"    {eid}  {created}  src={src}  has_computer={hc}")
        print()
        print(f"  [dry-run] terminaria aqui. Re-rode sem --dry-run pra valer.")
        return

    n_ok = n_err = n_skip = 0
    t0 = time.time()
    for i, (eid, created, src, hc) in enumerate(pending, 1):
        explain = call_explain(args.api_url, eid)
        if explain is None:
            n_err += 1
            continue
        pred = explain.get("prediction_recalculada") or {}
        sc = pred.get("lead_score")
        di = pred.get("decil")
        vn = pred.get("variant")
        if sc is None or di is None:
            n_err += 1
            print(f"  ✗ resposta sem score/decil pra {eid}: {pred}", file=sys.stderr)
            continue

        update_ledger(conn, eid, float(sc), int(di), vn)
        n_ok += 1
        if i % 25 == 0 or i == len(pending):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  [{i:4d}/{len(pending)}] ok={n_ok} err={n_err} ({rate:.1f}/s)")

    elapsed = time.time() - t0
    print()
    print(f"━━━ fim ━━━")
    print(f"  ok:       {n_ok}")
    print(f"  errors:   {n_err}")
    print(f"  skipped:  {n_skip}")
    print(f"  tempo:    {elapsed:.1f}s ({n_ok/elapsed:.1f}/s)" if elapsed > 0 else "")


if __name__ == "__main__":
    main()
