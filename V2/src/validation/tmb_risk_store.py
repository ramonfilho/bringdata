"""Ingestão do grau de risco da TMB para a tabela-satélite `analytics.sales_tmb_risk`.

Por que uma satélite (e não uma coluna em `analytics.sales`):
- A tabela `analytics.sales` tem um conjunto FIXO e agnóstico de gateway de colunas
  (identidade + valor + data + status). "Grau de risco" é específico da TMB e não
  entrou nesse desenho — o `sales_store` grava só as colunas canônicas.
- Além disso, o dono da tabela é `postgres`; a conexão de aplicação (`ledger_app`)
  NÃO pode `ALTER TABLE analytics.sales` ("must be owner"). Mas PODE `CREATE` no
  schema `analytics`. Então o risco vira uma tabela irmã, chaveada por email —
  mesmo padrão da linhagem de leads (`analytics.leads_provenance`).

De onde vem o dado: o "Grau de risco" (Baixo/Médio/Alto) é uma coluna que a própria
TMB põe no relatório de **contas a receber** (uma linha por parcela). É um export
DIFERENTE do de fechamento (que vira as vendas em `analytics.sales`). Este módulo
lê esse relatório, agrega email → grau (paridade com `core/ingestion`: mesmo
strip/lower no email e `.first()` por email) e grava idempotente na satélite.

Consumidor: `src/data/tmb_risk_reader.read_tmb_risk` (lado de leitura, para o treino
montar o `tmb_risk_lookup` quando lê vendas do banco).
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

TABLE = "analytics.sales_tmb_risk"

# Variantes de nome da coluna de risco vistas nos exports da TMB.
_RISK_COL_CANDIDATES = ("Grau de risco", "Grau de Risco", "grau de risco", "Risco", "risco")
_EMAIL_COL_CANDIDATES = ("Cliente Email", "Cliente E-mail", "Email", "E-mail")
_STATUS_COL_CANDIDATES = ("Status Pedido", "Status")


def _pick(df: pd.DataFrame, candidates) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def read_tmb_risk_report(path: str) -> dict:
    """Lê o relatório de contas a receber da TMB e devolve {email_norm → grau_de_risco}.

    Mantém só parcelas de pedidos efetivados (quando há coluna de status), normaliza o
    email (strip + lower) e agrega por email com `.first()` — exatamente como o
    `core/ingestion._tmb_dual_source_split` faz no caminho de arquivos (paridade).
    """
    df = pd.read_excel(path)
    total_bruto = len(df)

    status_col = _pick(df, _STATUS_COL_CANDIDATES)
    if status_col is not None:
        df = df[df[status_col] == "Efetivado"]

    email_col = _pick(df, _EMAIL_COL_CANDIDATES)
    risk_col = _pick(df, _RISK_COL_CANDIDATES)
    if email_col is None or risk_col is None:
        raise ValueError(
            f"Relatório TMB sem coluna de email/risco (email={email_col}, risco={risk_col}). "
            f"Esperado o export de 'contas a receber' (parcelas), que tem 'Grau de risco'. "
            f"Colunas vistas: {list(df.columns)[:15]}"
        )

    df = df.dropna(subset=[email_col, risk_col]).copy()
    df["_em"] = df[email_col].astype(str).str.strip().str.lower()
    df = df[df["_em"] != ""]
    risk_map = df.groupby("_em")[risk_col].first().to_dict()

    logger.info(
        "[tmb_risk] %s: %d parcelas → %d emails com grau de risco",
        path, total_bruto, len(risk_map),
    )
    return risk_map


def _ensure_table(conn) -> None:
    """Cria a satélite se não existir (ledger_app tem CREATE no schema analytics)."""
    conn.run(
        f"CREATE TABLE IF NOT EXISTS {TABLE} ("
        " client_id   varchar NOT NULL,"
        " email       varchar NOT NULL,"
        " risk_grade  varchar,"
        " ingested_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (client_id, email))"
    )


def upsert_tmb_risk(risk_map: dict, client_id: str = "devclub", conn=None,
                    batch_size: int = 500) -> dict:
    """Grava {email → grau} na satélite (idempotente; o grau mais recente vence).

    Retorna {attempted, upserted}. `ON CONFLICT (client_id, email) DO UPDATE` mantém
    o grau em dia se o relatório for re-largado com reclassificação.
    """
    pairs = [(str(e).strip().lower(), str(g).strip())
             for e, g in (risk_map or {}).items()
             if e and str(e).strip() and g and str(g).strip()]
    if not pairs:
        return {"attempted": 0, "upserted": 0}

    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        _ensure_table(conn)
        before = conn.run(f"SELECT count(*) FROM {TABLE} WHERE client_id = :c", c=client_id)[0][0]
        for start in range(0, len(pairs), batch_size):
            chunk = pairs[start:start + batch_size]
            values, params = [], {"c": client_id}
            for i, (em, gr) in enumerate(chunk):
                params[f"e_{i}"], params[f"g_{i}"] = em, gr
                values.append(f"(:c, :e_{i}, :g_{i})")
            conn.run(
                f"INSERT INTO {TABLE} (client_id, email, risk_grade) VALUES "
                + ", ".join(values)
                + " ON CONFLICT (client_id, email) DO UPDATE"
                + " SET risk_grade = excluded.risk_grade, ingested_at = now()",
                **params,
            )
        after = conn.run(f"SELECT count(*) FROM {TABLE} WHERE client_id = :c", c=client_id)[0][0]
        res = {"attempted": len(pairs), "upserted": len(pairs), "novos": after - before}
        logger.info("[tmb_risk_store] %s", res)
        return res
    finally:
        if own:
            conn.close()
