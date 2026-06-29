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
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _cloudsql_conn():
    """Conexão pg8000 no Cloud SQL ledger — delega pro conector único em
    `ledger_connection` (fonte única do literal de conexão Cloud SQL). Usada pelo
    lado da TABELA `scores_historicos` (nossa, só Cloud SQL): leitura do JOIN com
    `registros_ml` e escrita do upsert."""
    from src.data.ledger_connection import open_cloudsql_ledger_connection
    return open_cloudsql_ledger_connection()


# ---------------------------------------------------------------------------
# Lado de ESCRITA — contrato da tabela + upsert idempotente.
# Fonte única do schema de `scores_historicos` num dir que VAI pra imagem (o
# Dockerfile copia src/, não scripts/), pra que o refresh online (api/) possa
# gravar. Os scripts CLI de backfill mantêm cópia própria por rodarem só local;
# consolidá-los pra importar daqui é follow-up (não fazer de passagem).
# ---------------------------------------------------------------------------

SCORES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS scores_historicos (
    id                 BIGSERIAL PRIMARY KEY,
    email              TEXT NOT NULL,
    lf                 TEXT NOT NULL,
    mes_lancamento     TEXT,
    vendas_inicio      DATE,
    vendas_estimada    BOOLEAN,
    data_captura       TIMESTAMP,
    semana_captacao    TEXT,
    score_champion     DOUBLE PRECISION,
    decil_champion     TEXT,
    score_challenger   DOUBLE PRECISION,
    decil_challenger   TEXT,
    champion_run_id    TEXT NOT NULL,
    challenger_run_id  TEXT NOT NULL,
    core_commit        TEXT,
    generated_at       TIMESTAMP,
    UNIQUE (email, lf, champion_run_id, challenger_run_id)
)
"""
SCORES_TABLE_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_scores_hist_lf ON scores_historicos (lf)"
)

INSERT_COLS = [
    "email", "lf", "mes_lancamento", "vendas_inicio", "vendas_estimada",
    "data_captura", "semana_captacao", "score_champion", "decil_champion",
    "score_challenger", "decil_challenger", "champion_run_id",
    "challenger_run_id", "core_commit", "generated_at",
]


def _multi_insert_sql(n: int) -> str:
    tuples = [
        "(" + ", ".join(f":{c}_{i}" for c in INSERT_COLS) + ")"
        for i in range(n)
    ]
    return (
        f"INSERT INTO scores_historicos ({', '.join(INSERT_COLS)}) "
        f"VALUES {', '.join(tuples)} "
        f"ON CONFLICT (email, lf, champion_run_id, challenger_run_id) DO NOTHING"
    )


def existing_score_emails(conn, lf_name, champion_run_id, challenger_run_id) -> set:
    """Emails já gravados pro (lf, par de run_ids) — base do delta incremental
    (o refresh só re-scoreia quem falta). Levanta em erro de leitura: o chamador
    decide abortar (melhor pular o refresh do que re-scorear o lançamento todo)."""
    rows = conn.run(
        "SELECT email FROM scores_historicos "
        "WHERE lf = :lf AND champion_run_id = :cr AND challenger_run_id = :chr",
        lf=lf_name, cr=champion_run_id, chr=challenger_run_id,
    )
    return {row[0] for row in rows}


def upsert_scores(conn, rows, *, batch: int = 500, ensure_table: bool = True) -> int:
    """Insere linhas em `scores_historicos` (idempotente: ON CONFLICT DO NOTHING).

    Args:
        conn: conexão pg8000 no Cloud SQL ledger (injetada).
        rows: iterável de dicts; chaves de INSERT_COLS são lidas via .get (ausente
            → None). Valores com .isoformat (datetime/date/Timestamp) viram ISO.
        batch: tamanho do lote por INSERT multi-VALUES.
        ensure_table: roda CREATE TABLE/INDEX IF NOT EXISTS antes (idempotente).

    Returns:
        nº de linhas ENVIADAS (conflitos são ignorados em silêncio pelo ON
        CONFLICT, então não reflete necessariamente o nº inserido). 0 se vazio.
    """
    recs = list(rows)
    if not recs:
        return 0
    if ensure_table:
        conn.run(SCORES_TABLE_DDL)
        conn.run(SCORES_TABLE_IDX)
    enviadas = 0
    for i in range(0, len(recs), batch):
        chunk = recs[i:i + batch]
        params = {}
        for j, rec in enumerate(chunk):
            for col in INSERT_COLS:
                v = rec.get(col)
                if hasattr(v, "isoformat"):
                    v = v.isoformat()
                params[f"{col}_{j}"] = v
        conn.run(_multi_insert_sql(len(chunk)), **params)
        enviadas += len(chunk)
    return enviadas


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


# Mapeia o nível pedido pra coluna física de registros_ml. Whitelist: o nome
# entra INTERPOLADO na query (nome de coluna não dá pra parametrizar), então
# nunca aceitar valor fora deste dict (proteção contra injeção).
_UTM_LEVEL_COL = {
    'creative': 'utm_content',
    'campaign': 'utm_campaign',
}


def challenger_quality_by_utm(
    lf_name: Optional[str],
    *,
    level: str,
    challenger_run_id: str,
    win_start,
    win_end,
    conn=None,
) -> list:
    """Qualidade Challenger (pct_d9_d10 + decil médio) por criativo ou campanha
    no lançamento — `scores_historicos` ⋈ `registros_ml`.

    A `scores_historicos` tem o `decil_challenger` (régua única) mas não guarda
    UTM; o UTM vem do `registros_ml` (mesmo banco Cloud SQL), juntado por email.
    Anti fan-out: `DISTINCT ON (email)` pega 1 UTM por lead (o mais recente na
    janela do LF).

    Filtra `challenger_run_id = :run_id` pra NÃO misturar réguas — o caller passa
    o run_id do baseline TOP5 (mesmo modelo). Reusa o predicado de decil do
    `launch_score_geral` ('D09'/'D10' zero-padded).

    Args:
        lf_name: lançamento. None/'' → [].
        level: 'creative' (utm_content) ou 'campaign' (utm_campaign).
        challenger_run_id: run_id do Challenger a casar (= run_id do baseline TOP5).
        win_start, win_end: janela UTC do LF — limita o `registros_ml` lido e
            prende o UTM ao período do lançamento (evita pegar UTM de outro LF de
            um lead recorrente).
        conn: conexão Cloud SQL opcional (injetada); None → abre e fecha.

    Returns:
        list[dict] {utm, n, pct_d9_d10, avg_decil}, ordenada por n desc. []
        quando não há dados / lf|level inválido / falha (degrada silencioso — o
        relatório só omite a seção vs-TOP5, nunca quebra). min-N e significância
        ficam na montagem, não aqui (read-model devolve cru).
    """
    if not lf_name or not challenger_run_id:
        return []
    col = _UTM_LEVEL_COL.get(level)
    if col is None:
        logger.warning("[challenger_quality_by_utm] level inválido: %r", level)
        return []

    own = conn is None
    if own:
        try:
            conn = _cloudsql_conn()
        except Exception as e:
            logger.warning("[challenger_quality_by_utm] conexão falhou: %s", e)
            return []
    try:
        sql = (
            "WITH utm_por_lead AS ("
            f"  SELECT DISTINCT ON (lower(email)) lower(email) AS email_k, {col} AS utm "
            "  FROM registros_ml "
            f"  WHERE {col} IS NOT NULL AND {col} <> '' "
            "    AND created_at >= :ws AND created_at < :we "
            "  ORDER BY lower(email), created_at DESC"
            ") "
            "SELECT u.utm, COUNT(*) AS n, "
            "AVG(CASE WHEN s.decil_challenger IN ('D09','D10') THEN 1.0 ELSE 0.0 END) AS pct, "
            "AVG(CAST(REPLACE(s.decil_challenger,'D','') AS INTEGER)) AS avg_decil "
            "FROM scores_historicos s "
            "JOIN utm_por_lead u ON u.email_k = lower(s.email) "
            "WHERE s.lf = :lf AND s.challenger_run_id = :run_id "
            "  AND s.decil_challenger IS NOT NULL "
            "GROUP BY u.utm "
            "ORDER BY n DESC"
        )
        rows = conn.run(sql, lf=lf_name, run_id=challenger_run_id,
                        ws=win_start, we=win_end)
        out = [
            {
                'utm': r[0],
                'n': int(r[1]),
                'pct_d9_d10': round(float(r[2]) * 100, 1),
                'avg_decil': round(float(r[3]), 2),
            }
            for r in rows
        ]
        # Fail-loud: há população Challenger pro LF mas o join não casou nenhum
        # UTM → registros_ml sem UTM na janela, ou chave de email divergindo.
        if not out:
            chk = conn.run(
                "SELECT COUNT(*) FROM scores_historicos "
                "WHERE lf = :lf AND challenger_run_id = :run_id "
                "  AND decil_challenger IS NOT NULL",
                lf=lf_name, run_id=challenger_run_id,
            )
            if int(chk[0][0] or 0) > 0:
                logger.warning(
                    "[challenger_quality_by_utm] LF=%s tem %s leads na régua mas o "
                    "join por email não casou nenhum UTM (%s) — registros_ml sem UTM "
                    "na janela?", lf_name, chk[0][0], level,
                )
        return out
    except Exception as e:
        logger.warning("[challenger_quality_by_utm] query falhou (lf=%s, level=%s): %s",
                       lf_name, level, e)
        return []
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass
