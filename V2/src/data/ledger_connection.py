"""Conexão de LEITURA do ledger `registros_ml` — ponto único de escolha de fonte.

PLANO_LEDGER_CLOUDSQL.md Etapa 3. O ledger está migrando do Railway do cliente
para o nosso Cloud SQL (proteção do modelo). Durante a transição a tabela
`registros_ml` existe IDÊNTICA nos dois bancos (dual-write do consumer +
backfill), então "trocar a fonte de leitura" é só trocar a conexão — a query
`FROM registros_ml` é a mesma.

Este helper centraliza essa escolha num lugar só, controlada pela env
`LEDGER_READ_SOURCE`:
    - 'railway'  (default durante a migração): banco do cliente, comportamento atual.
    - 'cloudsql': nosso Cloud SQL `ledger`.

Cada leitor do ledger (camada `LeadRepository`, `load_ml_ledger`, regras de
alerta) abre a conexão por aqui. Virar a env reaponta TODOS de uma vez;
reverter é trocar a env de volta — sem deploy.

NÃO usar para escrita (o consumer Pub/Sub tem seu próprio caminho de dual-write)
nem para ler tabelas que só existem no Railway (`Lead`, `Client`, `UTMTracking`).
"""
from __future__ import annotations

import logging
import os
import ssl

logger = logging.getLogger(__name__)


def ledger_read_source() -> str:
    """'cloudsql' ou 'railway' (default). Valor inválido cai no default."""
    s = os.environ.get("LEDGER_READ_SOURCE", "railway").strip().lower()
    return s if s in ("railway", "cloudsql") else "railway"


def open_ledger_read_connection():
    """Abre uma `pg8000.native.Connection` pro ledger, na fonte escolhida pela
    env `LEDGER_READ_SOURCE`. O chamador é dono da conexão (deve fechá-la).

    Raises:
        KeyError: se a senha da fonte escolhida não estiver no ambiente.
    """
    import pg8000.native

    source = ledger_read_source()
    if source == "cloudsql":
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
            timeout=30,
        )
    else:
        conn = pg8000.native.Connection(
            host=os.environ.get("RAILWAY_DB_HOST", "shortline.proxy.rlwy.net"),
            port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
            database=os.environ.get("RAILWAY_DB_NAME", "railway"),
            user=os.environ.get("RAILWAY_DB_USER", "postgres"),
            password=os.environ["RAILWAY_DB_PASSWORD"],
            timeout=30,
        )
    logger.info("[ledger_connection] leitura do ledger via fonte=%s", source)
    return conn
