"""ad_insights_reader.py: leitura do gasto POR ANÚNCIO de analytics.ad_insights.

Gêmeo do `ad_spend_reader`, um grão abaixo: lá a linha é (plataforma, campanha,
dia); aqui é (anúncio, dia), com o `campaign_id` junto. É o grão que o relatório
de lançamento precisa, porque "o único grão que importa é o anúncio" (Ramon,
15/08) e a unidade julgada por LF é criativo×campanha.

Mesmas convenções do vizinho, de propósito: conexão injetada (DI, o dono fecha),
shape canônico em DataFrame, `spend` numérico já coagido, sem bater na API viva
(quem enche a tabela é `scripts/ingest_ad_insights.py`). Sem try/except: fonte
quebrada é para falhar alto, não para o relatório publicar meio gasto calado.

FONTE É META PURA. `analytics.ad_insights` nasce da API da Meta e não tem uma
linha de Google (o gasto do Google vive em `analytics.ad_spend`, platform
'google', só por campanha). Medido na janela do LF64 (07 a 17/08/2026):
ad_insights R$ 69.187,62 contra ad_spend/meta R$ 69.189,58, razão 1,0000; o
Google, R$ 11.186,79, não aparece aqui.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection
from src.data.criativo_historico import chave_canonica

_COLS = ("ad_id", "ad_name", "campaign_id", "adset_id", "adset_name",
         "insight_date", "spend", "leads", "impressions", "clicks")


def read_ad_insights(start: date, end: date, *, conn=None,
                     client_id: str = "devclub") -> pd.DataFrame:
    """Insights com insight_date em [start, end) (END EXCLUSIVO, igual ao
    `read_ad_spend`). Shape canônico: uma linha por (anúncio, dia).

    O end EXCLUSIVO não é detalhe: as janelas de captação vêm COLADAS (LF64
    termina em 17/08 e o LF65 começa em 18/08), então um dia de erro na borda
    mistura dois lançamentos. Quem tem a data final INCLUSIVA do calendário
    passa `end + 1 dia`, como já faz o `utm_quality` com o gasto por campanha.

    Colunas devolvidas: ad_id, ad_name, campaign_id, adset_id, adset_name,
    insight_date, spend, leads, impressions, clicks. Todas existem na tabela
    (conferido no information_schema em 24/08/2026). Ficam de fora, de caso
    pensado, `client_id` (já é filtro) e `ingested_at` (metadado da carga).
    A mesma escolha do `ad_spend_reader`. NÃO existe coluna de plataforma:
    a tabela é Meta pura (ver docstring do módulo).

    `leads` é a contagem do GERENCIADOR da Meta (action_type 'lead'), não a
    nossa: serve de contraprova do lead casado por UTM, nunca de substituto.
    """
    sql = (
        f"SELECT {', '.join(_COLS)} FROM ad_insights "
        "WHERE client_id = :cid AND insight_date >= :s AND insight_date < :e"
    )
    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        rows = conn.run(sql, cid=client_id, s=start.isoformat(), e=end.isoformat())
    finally:
        if own:
            conn.close()
    if not rows:
        return pd.DataFrame(columns=list(_COLS))
    df = pd.DataFrame(rows, columns=list(_COLS))
    df["spend"] = pd.to_numeric(df["spend"], errors="coerce").fillna(0.0)
    return df


def gasto_por_unidade(insights_df: pd.DataFrame,
                      chave_criativo: Optional[Callable[[object], str]] = None,
                      gross_up: float = 1.0) -> dict:
    """Soma o gasto na UNIDADE do relatório: (campanha, criativo).

    Chave: `(str(campaign_id), chave_do_criativo)`. O campaign_id vira string
    porque ele viaja como texto no banco e como número em quem lê do gerenciador;
    comparar 120..._int com '120..._str' devolve unidade vazia sem erro nenhum.

    Valor: `{"spend": float, "leads_gerenciador": int, "ad_ids": set}`. Os
    `ad_ids` ficam à vista porque cópia é o mesmo anúncio (Ramon, 18/08): o mesmo
    vídeo vive como VÁRIOS ad_ids (AD0139 = 9 ids no Google), e a unidade precisa
    dizer quantos ids ela fundiu.

    `chave_criativo=None` usa `criativo_historico.chave_canonica` (a mesma grafia
    do histórico: sem carimbo `[G] `, NFC, espaço colapsado, casefold). É o que
    faz o gasto e o histórico caírem na MESMA gaveta.

    `gross_up` multiplica SÓ o `spend`, nunca os leads: ele é o imposto sobre a
    mídia da Meta (1,13), e imposto não compra lead. Default 1,0 = gasto cru.
    """
    fn = chave_criativo or chave_canonica
    unidades: dict = {}
    if insights_df is None or getattr(insights_df, "empty", True):
        return unidades
    for r in insights_df.itertuples(index=False):
        chave = (_txt(r.campaign_id), fn(_txt(r.ad_name)))
        u = unidades.get(chave)
        if u is None:
            u = unidades[chave] = {"spend": 0.0, "leads_gerenciador": 0,
                                   "ad_ids": set()}
        u["spend"] += _num(r.spend) * float(gross_up)
        u["leads_gerenciador"] += int(_num(r.leads))
        u["ad_ids"].add(_txt(r.ad_id))
    return unidades


def _txt(v) -> str:
    """Texto tolerante: None e NaN viram string vazia. Sem isto, `str(nan)` grava
    a unidade na gaveta literal 'nan' e ela some do casamento sem erro nenhum."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _num(v) -> float:
    """Numérico tolerante: None/NaN/Decimal/texto viram float, o resto vira 0,0.
    O banco devolve `spend` como Decimal e `leads` pode vir nulo em linha antiga."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if pd.isna(f) else f
