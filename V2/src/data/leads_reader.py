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

# Data a partir da qual a leitura point-in-time é CONFIÁVEL.
#
# `first_seen_at` foi criado em 02/08/2026 e o histórico anterior foi preenchido com
# `ingested_at` — que para 312.677 linhas (86% da tabela) é a data do rebuild completo de
# 30/06/2026, não a data real em que o lead entrou. Logo, pedir o universo de uma data
# ANTERIOR a esse rebuild devolveria um recorte errado: leads capturados em 2025 só
# apareceriam a partir de 30/06.
#
# Levantar é melhor que responder errado: um universo silenciosamente torto vira um
# baseline torto, que vira uma decisão de modelo tomada em cima de nada.
_ASOF_CONFIAVEL_DESDE = "2026-06-30"


def _assert_asof_confiavel(as_of: str) -> None:
    if str(as_of) < _ASOF_CONFIAVEL_DESDE:
        raise ValueError(
            f"[leads_reader] as_of={as_of} é anterior a {_ASOF_CONFIAVEL_DESDE}, quando o "
            f"universo de treino foi reconstruído por inteiro. Antes dessa data a linhagem "
            f"não existe (o rebuild recarimbou tudo) e o recorte sairia errado — leads "
            f"antigos apareceriam como se tivessem entrado em 30/06. Reprodução de modelo "
            f"treinado antes disso não é possível com os dados atuais."
        )


def read_pesquisa(
    source: str = "train_pesquisa",
    client_id: str = "devclub",
    conn=None,
    include_utm: bool = False,
    as_of: Optional[str] = None,
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

        as_of: leitura POINT-IN-TIME (YYYY-MM-DD) — devolve o universo COMO ELE ERA
            naquele dia, filtrando por `first_seen_at` da sidecar de linhagem.
            None = agora (contrato inalterado).

            Existe porque `analytics.leads` é uma tabela DERIVADA que o `leads_unify`
            reescreve (DELETE+INSERT). Sem lineage preservado não dá pra saber o que a
            tabela continha num dia passado — e sem isso nenhum modelo treinado no
            passado é reproduzível. Foi o que inviabilizou reproduzir o jul_24.

            LIMITE DURO: só vale de `_ASOF_CONFIAVEL_DESDE` em diante (ver constante).
            Data anterior levanta, em vez de devolver um universo errado em silêncio.

    Returns:
        DataFrame com as mesmas colunas do df_pesquisa dumpado. Vazio se nada.
    """
    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        # utm_source viaja junto do utm_campaign: o peso de controle precisa
        # saber o CANAL do lead — sem isso, google/orgânico (campanha genérica
        # 'devlf' ou vazia) caíam no grupo CONTROLE do reweighting como se
        # fossem captação fria da Meta (~102k leads, medido em 16/08/2026).
        cols = "survey_responses, utm_campaign, utm_source" if include_utm else "survey_responses"
        _params = {"c": client_id, "s": source}
        _join = _where = ""
        if as_of:
            _assert_asof_confiavel(as_of)
            # A linhagem mora na sidecar (analytics.leads é do usuário `postgres`; o job
            # roda como `ledger_app` e não pode ALTER). Auditado 02/08/2026: 1:1 exato,
            # zero órfãos, zero event_id nulo — o join não perde lead.
            _join = (" JOIN analytics.leads_provenance p "
                     "ON p.source = l.source AND p.event_id = l.event_id")
            _where = " AND p.first_seen_at < CAST(:a AS timestamptz) + interval '1 day'"
            _params["a"] = as_of
        _cols_q = ", ".join(f"l.{c.strip()}" for c in cols.split(","))
        rows = conn.run(
            f"SELECT {_cols_q} FROM leads l{_join} "
            "WHERE l.client_id = :c AND l.source = :s "
            f"AND l.survey_responses IS NOT NULL{_where}",
            **_params,
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
        df['__utm_source__'] = [r[2] for r in rows]
        _n_utm = int(df['__utm_campaign__'].notna().sum())
        logger.info("[leads_reader] __utm_campaign__ + __utm_source__ anexadas p/ peso "
                    "de controle (%d/%d linhas com utm_campaign)", _n_utm, len(df))
    logger.info("[leads_reader] %d linhas de pesquisa reconstruídas (source=%s, %d colunas)",
                len(df), source, len(df.columns))
    return df
