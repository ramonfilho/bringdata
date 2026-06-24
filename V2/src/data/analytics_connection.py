"""Conexão com o schema `analytics` (Cloud SQL, database `ledger`).

Leitura E escrita das tabelas analytics.* (leads / sales / validation_runs /
validation_metrics / meta_insights) da frente de consolidação.

Diferente de `ledger_connection.py` — aquele é LEITURA do `registros_ml` e pode
apontar pro Railway durante a migração (env `LEDGER_READ_SOURCE`), e o próprio
docstring de lá proíbe usá-lo para escrita. Aqui é sempre o nosso Cloud SQL
(envs `LEDGER_DB_*`), com `search_path` já apontado pro schema `analytics`.

O chamador é dono da conexão (deve fechá-la).
"""
from __future__ import annotations

import logging
import os
import ssl

logger = logging.getLogger(__name__)


def open_analytics_connection():
    """Abre uma `pg8000.native.Connection` no schema analytics do Cloud SQL.

    Raises:
        KeyError: se `LEDGER_DB_HOST`/`LEDGER_DB_PASSWORD` não estiverem no ambiente.
    """
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
        timeout=30,
    )
    conn.run("SET search_path TO analytics, public")
    logger.debug("[analytics_connection] conectado ao schema analytics")
    return conn
