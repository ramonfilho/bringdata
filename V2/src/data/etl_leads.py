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

import hashlib
import json
import logging
import math
from typing import Optional

import pandas as pd

from src.data.leads_store import upsert_leads

logger = logging.getLogger(__name__)


def _row_hash(d: dict) -> str:
    """Hash estável do conteúdo da linha — vira event_id sintético pra que NENHUMA
    linha de pesquisa seja dropada por falta de email/telefone (o treino mantém
    esses leads como negativos). Linhas idênticas colapsam (dedup correto)."""
    blob = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


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

    df_pesquisa = df_pesquisa.copy()
    # 'Data' no df do treino é object MISTO (Timestamp + string). Serializar misto
    # vira formato misto no jsonb e o pd.to_datetime downstream coerce a maioria a
    # NaT. Parsear aqui (mesmo dayfirst do pipeline) dá ISO uniforme → reconstrução
    # parseável e data parseada IDÊNTICA (o pipeline parseia 'Data' de qualquer jeito).
    if "Data" in df_pesquisa.columns:
        df_pesquisa["Data"] = pd.to_datetime(
            df_pesquisa["Data"], errors="coerce", dayfirst=True
        )

    out = pd.DataFrame(index=df_pesquisa.index)
    out["email"] = df_pesquisa.apply(lambda r: _first(r, _EMAIL_ALIASES), axis=1)
    out["telefone"] = df_pesquisa.apply(lambda r: _first(r, _PHONE_ALIASES), axis=1)
    out["data_captura"] = df_pesquisa.apply(lambda r: _first(r, _DATA_ALIASES), axis=1)
    out["campaign"] = df_pesquisa.apply(lambda r: _first(r, _CAMPAIGN_ALIASES), axis=1)
    survey = [_row_to_clean_dict(r) for _, r in df_pesquisa.iterrows()]
    out["survey_responses"] = survey
    # event_id = hash do conteúdo → toda linha tem chave (nada dropado por falta de
    # email/telefone) e o dedup (uq_leads_source_event) fica uniforme.
    out["event_id"] = [_row_hash(d) for d in survey]

    res = upsert_leads(out, source=source, client_id=client_id)
    logger.info("[etl_leads] pesquisa→leads (source=%s): %s", source, res)
    return res
