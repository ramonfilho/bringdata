"""Conexão de LEITURA do ledger `registros_ml` — ponto único de escolha de fonte.

PLANO_LEDGER_CLOUDSQL.md. O ledger migrou do Railway do cliente para o nosso
Cloud SQL (proteção do modelo). A migração ENCERROU em 24/06/2026: a tabela
`registros_ml` foi DROPADA do Railway — agora só existe no Cloud SQL. A query
`FROM registros_ml` é a mesma; só a conexão muda.

Este helper centraliza essa escolha num lugar só, controlada pela env
`LEDGER_READ_SOURCE`:
    - 'cloudsql' (default desde 29/06/2026): nosso Cloud SQL `ledger`.
    - 'railway': banco do cliente — alavanca de emergência só; a tabela não
      existe mais lá, então na prática este ramo está morto.

Cada leitor do ledger (camada `LeadRepository`, `load_ml_ledger`, regras de
alerta, refresh da `scores_historicos`) abre a conexão por aqui. É o ÚNICO ponto
de entrada de leitura do `registros_ml` — nenhum consumidor deve abrir conexão
crua pra essa tabela (foi isso que quebrou o refresh em 28/06: ele apontava
Railway na mão e não seguiu a virada de fonte).

NÃO usar para escrita (o consumer Pub/Sub tem seu próprio caminho) nem para ler
tabelas que só existem no Railway (`Lead`, `Client`, `UTMTracking`). Para a
tabela derivada `scores_historicos` (nossa, só Cloud SQL), use o conector
`open_cloudsql_ledger_connection` direto — é leitura+escrita no mesmo banco.
"""
from __future__ import annotations

import logging
import os
import ssl

logger = logging.getLogger(__name__)


def ledger_read_source() -> str:
    """'cloudsql' (default) ou 'railway'. Valor inválido cai no default.

    Default virou 'cloudsql' em 29/06/2026: a migração terminou (tabela dropada
    do Railway em 24/06). Um default 'railway' era mina — qualquer caminho sem a
    env setada leria uma tabela que não existe mais."""
    s = os.environ.get("LEDGER_READ_SOURCE", "cloudsql").strip().lower()
    return s if s in ("railway", "cloudsql") else "cloudsql"


def open_cloudsql_ledger_connection():
    """Conector ÚNICO do Cloud SQL ledger (LEDGER_DB_*, SSL sem verificação —
    cert self-signed do proxy). Fonte única do literal de conexão Cloud SQL:
    tanto a leitura do `registros_ml` (ramo cloudsql de open_ledger_read_connection)
    quanto a tabela derivada `scores_historicos` (read+write) entram por aqui.

    Raises:
        KeyError: se LEDGER_DB_HOST/PASSWORD não estiverem no ambiente.
    """
    import pg8000.native

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"],
        port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"],
        ssl_context=ctx,
        timeout=30,
    )


def open_ledger_read_connection():
    """Abre uma `pg8000.native.Connection` pro ledger, na fonte escolhida pela
    env `LEDGER_READ_SOURCE`. O chamador é dono da conexão (deve fechá-la).

    Raises:
        KeyError: se a senha da fonte escolhida não estiver no ambiente.
    """
    import pg8000.native

    source = ledger_read_source()
    if source == "cloudsql":
        conn = open_cloudsql_ledger_connection()
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
