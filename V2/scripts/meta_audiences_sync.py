"""scripts/meta_audiences_sync.py — CLI da automação de Públicos da Meta.

Lê os membros (leads e/ou alunos) das tabelas frescas, hasheia e SUBSTITUI o(s)
público(s) na conta do cliente. DRY-RUN por padrão: monta o payload e resume sem
enviar. A escrita real tem DUPLA trava (config.enabled + flag explícita).

Uso:
    # dry-run (não envia nada) — o default seguro:
    python -m scripts.meta_audiences_sync --audience both

    # confirmar o alvo (GET dos públicos, read-only):
    python -m scripts.meta_audiences_sync --audience both --show-target

    # escrita REAL (exige enabled:true no yaml + a flag longa; e ads_management no token):
    python -m scripts.meta_audiences_sync --audience leads --execute --yes-write-to-client-meta

Requer no ambiente (V2/.env): LEDGER_DB_* (Cloud SQL), RAILWAY_DB_* (Client),
META_ACCESS_TOKEN.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import ssl
import sys
from pathlib import Path

# V2 root no path + .env (mesma cerimônia do etl_sales)
_V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2_ROOT))
_ENV = _V2_ROOT / ".env"
if _ENV.exists():
    for _line in _ENV.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from src.core.client_config import ClientConfig
from src.data.audience_reader import read_buyers_audience, read_leads_audience
from api.meta_audiences import MetaCustomAudienceClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _open_analytics_long():
    """Conexão Cloud SQL com timeout longo — o pull de leads é ~341k linhas e o
    default de 30s do open_analytics_connection estoura."""
    import pg8000.native
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"],
        port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"],
        ssl_context=ctx,
        timeout=300,
    )
    conn.run("SET search_path TO analytics, public")
    return conn


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync de Públicos Personalizados da Meta")
    ap.add_argument("--client", default="devclub")
    ap.add_argument("--audience", choices=["leads", "buyers", "both"], default="both")
    ap.add_argument("--show-target", action="store_true",
                    help="GET dos públicos-alvo (read-only) pra confirmar antes de escrever")
    ap.add_argument("--execute", action="store_true",
                    help="Executa a escrita real (default é dry-run). Exige também --yes-write-to-client-meta")
    ap.add_argument("--yes-write-to-client-meta", action="store_true",
                    help="Confirmação explícita de que a escrita é na conta do cliente (irreversível)")
    args = ap.parse_args()

    cfg = ClientConfig.from_yaml(_V2_ROOT / "configs" / "clients" / f"{args.client}.yaml")
    ma = cfg.meta_audiences
    token = os.environ.get("META_ACCESS_TOKEN")

    # Dupla trava da escrita: precisa das 2 flags E do enabled no yaml.
    dry_run = True
    if args.execute:
        if not args.yes_write_to_client_meta:
            logger.error("❌ --execute exige também --yes-write-to-client-meta (escrita externa irreversível). Abortado.")
            return 2
        if not ma.enabled:
            logger.error("❌ meta_audiences.enabled=false no yaml — ligue explicitamente antes de escrever. Abortado.")
            return 2
        dry_run = False

    client = MetaCustomAudienceClient(token, api_version=ma.api_version)

    targets = []
    if args.audience in ("leads", "both"):
        targets.append(("leads", ma.leads_audience_id))
    if args.audience in ("buyers", "both"):
        targets.append(("buyers", ma.buyers_audience_id))

    if args.show_target:
        for label, aid in targets:
            logger.info("\n=== alvo %s (%s) ===", label, aid)
            logger.info(json.dumps(client.get_audience(aid), ensure_ascii=False, indent=2, default=str))

    conn_a = _open_analytics_long()
    try:
        for label, aid in targets:
            logger.info("\n=== público %s → %s ===", label, aid)
            if not aid:
                logger.error("sem audience_id configurado pra %s — pulando.", label)
                continue
            if label == "leads":
                members = read_leads_audience(
                    client_id=args.client, conn_analytics=conn_a,
                    respondents_source=ma.leads_source,
                )
            else:
                members = read_buyers_audience(client_id=args.client, conn=conn_a)
            summary = client.replace_users(aid, members, dry_run=dry_run)
            logger.info(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    finally:
        conn_a.close()

    if dry_run:
        logger.info("\n✅ DRY-RUN concluído — NADA foi enviado à Meta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
