"""Acesso à tabela `scores_historicos` (Cloud SQL ledger).

A tabela guarda score+decil dos DOIS modelos do A/B (champion e challenger) por
lead, por lançamento (`lf`). É a fonte do **"score geral do lançamento"** — a
nota única de qualidade da população exibida na seção de decis do relatório.

Por que a régua do Challenger: é o modelo mais preciso e foi treinado na
população que o Champion trouxe, então aplicá-lo a TODA a população é dentro da
distribuição e dá uma escala consistente (um decil só, comparável entre
lançamentos). É sobre a população INTEIRA — a tabela não guarda `source`.

Conexão: Cloud SQL ledger via LEDGER_DB_* (mesmas credenciais de
load_scores_historicos_cloudsql / ledger_connection).
"""
from __future__ import annotations

import logging
import os
import ssl
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _cloudsql_conn():
    """Abre conexão pg8000 no Cloud SQL ledger (SSL sem verificação — cert
    self-signed do proxy, mesmo padrão de load_scores_historicos_cloudsql)."""
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


def launch_score_geral(lf_name: Optional[str], *, conn=None) -> Optional[Dict[str, Any]]:
    """Score geral do lançamento = decil médio da população pela régua do
    Challenger, lido da `scores_historicos`.

    Args:
        lf_name: nome do lançamento (ex: 'LF59'). None/'' → retorna None.
        conn: conexão Cloud SQL opcional (injetada); se None, abre e fecha uma.

    Returns:
        dict {decil_medio, pct_d9_d10, n, modelo, populacao} ou None quando não
        há dados pro lf, lf inválido, ou a consulta/conexão falha (degrada
        silencioso — o relatório só omite a nota, nunca quebra por causa disso).
    """
    if not lf_name:
        return None
    own = conn is None
    if own:
        try:
            conn = _cloudsql_conn()
        except Exception as e:
            logger.warning("[score_geral] conexão Cloud SQL falhou: %s", e)
            return None
    try:
        r = conn.run(
            "SELECT COUNT(*), "
            "AVG(CAST(REPLACE(decil_challenger, 'D', '') AS INTEGER)), "
            "AVG(CASE WHEN decil_challenger IN ('D09', 'D10') THEN 1.0 ELSE 0.0 END) "
            "FROM scores_historicos "
            "WHERE lf = :lf AND decil_challenger IS NOT NULL",
            lf=lf_name,
        )
        n = int(r[0][0] or 0)
        if n == 0:
            return None
        return {
            "decil_medio": round(float(r[0][1]), 2),
            "pct_d9_d10": round(float(r[0][2]) * 100, 1),
            "n": n,
            "modelo": "Challenger",
            "populacao": "todas as fontes",
        }
    except Exception as e:
        logger.warning("[score_geral] query falhou (lf=%s): %s", lf_name, e)
        return None
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass
