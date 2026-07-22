"""Leitura da pesquisa consolidada (analytics.leads) → df_pesquisa (Fase 3, leitura).

Reconstrói o `df_pesquisa` que o treino consome a partir do snapshot jsonb
verbatim gravado por `etl_leads.pesquisa_to_leads`. Como o jsonb guarda a linha
INTEIRA (chaves = colunas originais), a reconstrução é `pd.DataFrame(lista de
dicts)` → mesmas colunas, mesmos valores → paridade por construção.

Não transforma nada: o treino aplica unify/cutoff/FE/encoding em cima, igual ao
caminho de arquivo.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)


def read_pesquisa(
    source: str = "train_pesquisa",
    client_id: str = "devclub",
    conn=None,
    include_utm: bool = False,
) -> pd.DataFrame:
    """Reconstrói o df_pesquisa do snapshot jsonb em analytics.leads.

    Args:
        source: proveniência do snapshot (default 'train_pesquisa').
        client_id: cliente.
        include_utm: se True, anexa a coluna técnica `__utm_campaign__` com o
            valor da coluna `utm_campaign` da linha (alinhada por linha, mesma
            query). Serve SÓ pro peso de controle enxergar campanhas recentes do
            A/B (LEADHQLB/LEADQUALIFIED) que moram em `utm_campaign` e não no
            jsonb 'Campaign'. Nome dunder → não é confundida com feature; o
            treino a resolve em `__campaign_for_weights__` e a dropa antes do FE.
            Default False → contrato inalterado pros demais consumidores.

    Returns:
        DataFrame com as mesmas colunas do df_pesquisa dumpado. Vazio se nada.
    """
    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        cols = "survey_responses, utm_campaign" if include_utm else "survey_responses"
        rows = conn.run(
            f"SELECT {cols} FROM leads "
            "WHERE client_id = :c AND source = :s AND survey_responses IS NOT NULL",
            c=client_id, s=source,
        )
    finally:
        if own:
            conn.close()

    if not rows:
        logger.warning("[leads_reader] 0 linhas de pesquisa (source=%s)", source)
        return pd.DataFrame()

    dicts = []
    for r in rows:
        v = r[0]
        dicts.append(json.loads(v) if isinstance(v, str) else v)
    df = pd.DataFrame(dicts)
    if include_utm:
        # Alinhada por linha à mesma query (sem join por email) → sem risco de
        # descasar. Reset do índice garante alinhamento posicional com `dicts`.
        df = df.reset_index(drop=True)
        df['__utm_campaign__'] = [r[1] for r in rows]
        _n_utm = int(df['__utm_campaign__'].notna().sum())
        logger.info("[leads_reader] __utm_campaign__ anexada p/ peso de controle "
                    "(%d/%d linhas com utm_campaign)", _n_utm, len(df))
    logger.info("[leads_reader] %d linhas de pesquisa reconstruídas (source=%s, %d colunas)",
                len(df), source, len(df.columns))
    return df
