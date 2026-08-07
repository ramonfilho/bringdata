"""Leitura do grau de risco da TMB (satélite `analytics.sales_tmb_risk`).

Lado de LEITURA, irmão do `sales_reader`. Devolve o `tmb_risk_lookup`
({email_norm → grau_de_risco}) que o treino usa para (a) filtrar vendas TMB por
risco e (b) ponderar compradores TMB — o MESMO dicionário que o caminho de
arquivos monta a partir do relatório de contas a receber, agora servido do banco
quando `sales_source='db'`.

Mantém o `sales_reader` puro (só vendas): risco é um conceito à parte, com sua
própria tabela e seu próprio reader.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

TABLE = "analytics.sales_tmb_risk"


def read_tmb_risk(client_id: str = "devclub", conn=None) -> dict:
    """Devolve {email_norm → grau_de_risco} da satélite. {} se a tabela não existe
    (satélite ainda não populada → treino trata como 'sem lookup')."""
    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        exists = conn.run("SELECT to_regclass(:t)", t=TABLE)[0][0]
        if exists is None:
            logger.info("[tmb_risk_reader] %s não existe ainda — lookup vazio", TABLE)
            return {}
        rows = conn.run(
            f"SELECT email, risk_grade FROM {TABLE} WHERE client_id = :c AND risk_grade IS NOT NULL",
            c=client_id,
        )
        lookup = {str(e).strip().lower(): g for e, g in rows}
        logger.info("[tmb_risk_reader] %d emails com grau de risco (client=%s)", len(lookup), client_id)
        return lookup
    finally:
        if own:
            conn.close()
