"""ETL de leads/pesquisa → analytics.leads (Fase 3 da consolidação, escrita).

Pesquisa do TREINO: para garantir paridade de feature, a pesquisa é carregada
EXATAMENTE como o `train_pipeline` carrega (os mesmos loaders de `core/`) e cada
linha é gravada com `survey_responses` = a linha INTEIRA como jsonb (snapshot
verbatim). O reader (`leads_reader`) reconstrói o `df_pesquisa` idêntico —
paridade por construção, sem remapear chave de pergunta.

Identidade/data/utm também são extraídas para colunas tipadas (índice/dedup),
mas a fonte da reconstrução é o jsonb verbatim.

Uso prático: `python -m src.train_pipeline --dump-pesquisa-db` (a flag dumpa a
pesquisa já carregada pelo pipeline e encerra — reuso do carregamento exato).
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import pandas as pd

from src.data.leads_store import upsert_leads

logger = logging.getLogger(__name__)


def _jsonsafe(v):
    """Valor pronto pra jsonb: NaN/NaT/None → None; Timestamp → ISO; resto → str/num."""
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass  # não-escalar
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if isinstance(v, float):
        return None if math.isnan(v) else v
    if isinstance(v, (int, bool, str)):
        return v
    return str(v)


def _row_to_clean_dict(row: pd.Series) -> dict:
    """Linha inteira → dict json-safe (snapshot verbatim do df_pesquisa)."""
    return {str(k): _jsonsafe(v) for k, v in row.items()}


# nomes de coluna no df_pesquisa do treino → o que o leads_store espera ler
_EMAIL_ALIASES = ("email", "E-mail", "e-mail", "Email")
_PHONE_ALIASES = ("telefone", "Telefone", "phone")
_DATA_ALIASES = ("data_captura", "Data", "data")
_CAMPAIGN_ALIASES = ("utm_campaign", "Campaign", "campaign")


def _first(row: pd.Series, names):
    for n in names:
        if n in row.index:
            v = row[n]
            try:
                if pd.notna(v):
                    return v
            except (TypeError, ValueError):
                return v
    return None


def pesquisa_to_leads(df_pesquisa: pd.DataFrame, source: str = "train_pesquisa",
                      client_id: str = "devclub") -> dict:
    """Converte o df_pesquisa do treino → shape do leads_store e faz upsert.

    `survey_responses` recebe a linha inteira (snapshot verbatim) pra reconstrução
    lossless. email/telefone/data/campaign extraídos pra colunas tipadas (dedup).
    """
    if df_pesquisa is None or getattr(df_pesquisa, "empty", True):
        logger.warning("[etl_leads] df_pesquisa vazio — nada a gravar")
        return {"attempted": 0, "inserted": 0, "skipped": 0, "filtered": 0}

    out = pd.DataFrame(index=df_pesquisa.index)
    out["email"] = df_pesquisa.apply(lambda r: _first(r, _EMAIL_ALIASES), axis=1)
    out["telefone"] = df_pesquisa.apply(lambda r: _first(r, _PHONE_ALIASES), axis=1)
    out["data_captura"] = df_pesquisa.apply(lambda r: _first(r, _DATA_ALIASES), axis=1)
    out["campaign"] = df_pesquisa.apply(lambda r: _first(r, _CAMPAIGN_ALIASES), axis=1)
    out["survey_responses"] = [_row_to_clean_dict(r) for _, r in df_pesquisa.iterrows()]

    res = upsert_leads(out, source=source, client_id=client_id)
    logger.info("[etl_leads] pesquisa→leads (source=%s): %s", source, res)
    return res
