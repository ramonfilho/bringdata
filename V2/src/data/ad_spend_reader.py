"""ad_spend_reader.py — leitura do gasto de anúncio de analytics.ad_spend.

Repositório do conceito "gasto de anúncio por campanha por dia" (Meta + Google).
Consumidor recebe a conexão injetada (DI) e não sabe de onde o gasto veio — só
que vem no shape canônico. Espelha src/data/sales_reader.py. O relatório LÊ daqui
(leve, sem API viva); o etl_ad_spend é quem enche a tabela.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection

_COLS = ("platform", "account_id", "campaign_id", "campaign_name",
         "spend_date", "spend", "leads", "impressions", "clicks")


def read_ad_spend(start: date, end: date, *, conn=None,
                  client_id: str = "devclub") -> pd.DataFrame:
    """Gasto com spend_date em [start, end) (end exclusivo). Shape canônico:
    uma linha por (plataforma, campanha, dia). O relatório janela pela captação
    do LF e classifica campaign_name→balde por bucket_from_utm."""
    sql = (
        f"SELECT {', '.join(_COLS)} FROM ad_spend "
        "WHERE client_id = :cid AND spend_date >= :s AND spend_date < :e"
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
