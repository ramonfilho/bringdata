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


def open_analytics_connection(*, timeout: int = 30):
    """Abre uma `pg8000.native.Connection` no schema analytics do Cloud SQL.

    Args:
        timeout: timeout de socket em segundos (default 30). Scans pesados de 200k+
            linhas / jsonb precisam de ≥180s — o default estoura neles.

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
        timeout=timeout,
    )
    conn.run("SET search_path TO analytics, public")
    # `statement_timeout` casado com o timeout de socket. Isto conserta uma CLASSE de
    # incidente, não um detalhe de estilo.
    #
    # Quando o socket estoura, o CLIENTE morre e a query CONTINUA VIVA no servidor: o
    # Postgres só descobre que ninguém está ouvindo quando tenta devolver o resultado. Uma
    # consulta analítica de 10 minutos vira uma órfã de horas segurando snapshot, e
    # snapshot aberto FAZ DDL ESPERAR.
    #
    # Duas vezes já: em 30/07/2026 uma órfã de 31,5h travou um ALTER na `registros_ml` e
    # derrubou leitura nova (um ALTER na fila bloqueia quem chega depois); em 11/08/2026
    # duas órfãs minhas, de 4h e 1h, impediram a criação de um índice único na `captacoes`
    # e a tabela ficou um tempo sem proteção de unicidade.
    #
    # Com o timeout do lado do SERVIDOR, a órfã se mata sozinha, sem depender de alguém
    # lembrar de rodar `pg_cancel_backend`. Um pouco maior que o socket de propósito: quem
    # deve reclamar primeiro é o cliente, que sabe dizer em que linha do script parou.
    conn.run(f"SET statement_timeout = '{int(timeout) + 60}s'")
    logger.debug("[analytics_connection] conectado ao schema analytics")
    return conn
