"""buyer_profile — perfil de característica dos COMPRADORES recentes (janela rolante).

Referência NOVA que roda EM PARALELO ao snapshot legado (Top5 ROAS de leads) nas
tabelas de característica do relatório. O alvo é COMPRADOR por DATA DE COMPRA (não
lead capturado): a referência tem que refletir quem comprou de fato, não quem
entrou. Decisão travada com o cliente ("o alvo não são os leads, são os
compradores").

Fonte do survey = ledger vivo (`registros_ml`), o MESMO de onde o drift observado
lê. Cobertura é MEDIDA e logada, e vazio é fail-loud (princípio /data-architect:
prove a cobertura, nunca declare completo sem SELECT). Comprador capturado antes
do cutover do ledger não tem survey aqui — some da distribuição e é reportado no
`coverage`, jamais em silêncio.

Reuso (mandato /sw-architect): a régua de categoria (`normalize_audience_series`) e
o mapa de chave da pesquisa (`survey_to_canonical`) vêm de `data_quality` — as
duas referências (legado e rolante) e o observado passam pela MESMA normalização,
logo são comparáveis. O join comprador→survey é por email (identidade), NÃO o
matcher point-in-time de conversão: aqui não rotulamos venda, só buscamos a
característica de quem já é comprador conhecido. Cobertura por email foi ~99% dos
matches na rotulagem de conversão; telefone/last6 fica como reforço futuro.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from src.monitoring.data_quality import normalize_audience_series, survey_to_canonical

logger = logging.getLogger(__name__)

# As 7 features de característica (colunas canônicas) — mesmas do snapshot legado
# (configs/reference_audience_profiles/{client}.json), pra comparar maçã com maçã.
PROFILE_FEATURES = [
    'O seu gênero:',
    'Qual a sua idade?',
    'O que você faz atualmente?',
    'Atualmente, qual a sua faixa salarial?',
    'Você possui cartão de crédito?',
    'Já estudou programação?',
    'Tem computador/notebook?',
]


def _read_buyer_surveys(conn, ws: date, we: date):
    """Compradores por data de compra em [ws, we) ⋈ survey mais recente do ledger.

    Devolve (df_canonical, n_buyers_total, n_surveyed). `df_canonical` tem as 7
    colunas de PROFILE_FEATURES (uma linha por comprador com survey).
    """
    total = conn.run(
        "SELECT count(DISTINCT lower(email)) FROM analytics.sales "
        "WHERE sale_date >= :ws AND sale_date < :we",
        ws=ws, we=we,
    )
    n_total = int(total[0][0]) if total and total[0][0] is not None else 0

    # DISTINCT ON (email) + ORDER BY created_at DESC → survey mais recente do
    # comprador. Join só traz compradores (resultado pequeno), sem varrer o ledger.
    rows = conn.run(
        "SELECT DISTINCT ON (lower(s.email)) l.survey_responses, l.has_computer "
        "FROM analytics.sales s "
        "JOIN registros_ml l ON lower(l.email) = lower(s.email) "
        "WHERE s.sale_date >= :ws AND s.sale_date < :we "
        "  AND l.survey_responses IS NOT NULL "
        "ORDER BY lower(s.email), l.created_at DESC",
        ws=ws, we=we,
    )
    recs = []
    for survey, has_computer in rows:
        s = json.loads(survey) if isinstance(survey, str) else (survey or {})
        recs.append(survey_to_canonical(s, has_computer))
    df = pd.DataFrame(recs, columns=PROFILE_FEATURES) if recs else pd.DataFrame(columns=PROFILE_FEATURES)
    return df, n_total, len(df)


def _distribution(df: pd.DataFrame, col: str) -> dict:
    """value_counts normalizado da coluna, pela MESMA régua do drift observado."""
    if col not in df.columns:
        return {'n_responses': 0, 'proportions': {}}
    s = normalize_audience_series(df[col], col)
    s = s[s != '(nulo)']
    n = len(s)
    if n == 0:
        return {'n_responses': 0, 'proportions': {}}
    proportions = (s.value_counts() / n).round(6).to_dict()
    return {'n_responses': int(n), 'proportions': proportions}


def build_buyer_profile(*, as_of: Optional[date] = None, window_days: int = 90,
                        client_id: str = "devclub", conn=None,
                        allow_empty: bool = False) -> dict:
    """Constrói o perfil categórico dos compradores dos últimos `window_days`.

    Args:
        as_of: âncora (default hoje). Janela = [as_of - window_days, as_of].
        window_days: tamanho da janela de compra (default 90).
        client_id: cliente (informativo; a fonte é única por ora).
        conn: conexão injetada (testes/reuso). Se None, abre e fecha a própria.
        allow_empty: se False (default), 0 compradores com survey → ValueError.

    Returns:
        dict {label, window_start, window_end, n_buyers_total, n_buyers_surveyed,
        coverage, categorical_features:{col:{label, n_responses, proportions}}}.
        Mesmo shape de `categorical_features` do snapshot legado → o render trata
        as duas referências igual.
    """
    as_of = as_of or date.today()
    ws = as_of - timedelta(days=window_days)
    we = as_of + timedelta(days=1)  # inclui as vendas de hoje

    own = conn is None
    if own:
        from src.data.analytics_connection import open_analytics_connection
        conn = open_analytics_connection(timeout=180)
    try:
        df, n_total, n_surveyed = _read_buyer_surveys(conn, ws, we)
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass

    if n_surveyed == 0 and not allow_empty:
        raise ValueError(
            f"[buyer_profile] 0 compradores com survey em [{ws}, {we}) — "
            f"referência de perfil NÃO construída (fail-loud)."
        )
    coverage = round(n_surveyed / n_total, 4) if n_total else 0.0
    logger.info(
        "[buyer_profile] %s→%s: %d compradores (por data de compra), %d com survey "
        "no ledger (cobertura %.1f%%)", ws, as_of, n_total, n_surveyed, coverage * 100,
    )

    categorical = {c: {'label': c, **_distribution(df, c)} for c in PROFILE_FEATURES}
    return {
        'label': f'Compradores {window_days}d (janela rolante)',
        'window_start': ws.isoformat(),
        'window_end': as_of.isoformat(),
        'n_buyers_total': n_total,
        'n_buyers_surveyed': n_surveyed,
        'coverage': coverage,
        'categorical_features': categorical,
    }
