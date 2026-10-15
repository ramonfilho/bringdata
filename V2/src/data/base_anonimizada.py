"""Leitura da base anonimizada em parquet no lugar do banco, para treinar sem o Cloud SQL.

Liga quando a variável BASE_ANON_DIR aponta para a pasta da base (a que o desligamento de outubro
de 2026 gerou, com leads_anon.parquet, vendas_anon.parquet e sales_tmb_risk_anon.parquet). Os
leitores do banco (read_pesquisa, read_sales, read_tmb_risk) desviam para cá, então o treino roda
com `--leads-source db --sales-source db` sem mudar nada no pipeline.

A base não tem e-mail. O `pessoa_id` (o mesmo código para a mesma pessoa nas três tabelas) entra no
lugar dele, com um domínio falso para passar pela validação de e-mail do matching
(`<pessoa_id>@anon.local`). O casamento lead-venda por e-mail continua funcionando. O casamento por
telefone some, porque a base não tem telefone.

Ver V2/docs/desligamento_2026-10/README.md, seção 6.
"""
import json
import logging
import os
from typing import Optional, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

VARIAVEL = "BASE_ANON_DIR"
DOMINIO = "@anon.local"


def diretorio() -> Optional[str]:
    """Pasta da base anonimizada, ou None quando o treino deve ler do banco."""
    d = os.environ.get(VARIAVEL)
    if not d:
        return None
    if not os.path.isdir(d):
        raise FileNotFoundError(f"{VARIAVEL}={d} não é uma pasta")
    return d


def _email(pessoa_id: pd.Series) -> pd.Series:
    return pessoa_id.where(pessoa_id.isna(), pessoa_id.astype(str) + DOMINIO)


def _sem_as_of(as_of: Optional[str]) -> None:
    if as_of:
        raise ValueError("a base anonimizada é uma foto de 14/10/2026 e não tem leitura por data (as_of)")


def read_pesquisa_anon(source: str, include_utm: bool = False, as_of: Optional[str] = None) -> pd.DataFrame:
    """Mesmo contrato de leads_reader.read_pesquisa: uma linha por resposta, colunas do JSON."""
    _sem_as_of(as_of)
    cols = ["pessoa_id", "source", "survey_responses"] + (["utm_campaign", "utm_source"] if include_utm else [])
    t = pd.read_parquet(os.path.join(diretorio(), "leads_anon.parquet"), columns=cols)
    t = t[(t["source"] == source) & t["survey_responses"].notna()].reset_index(drop=True)
    if t.empty:
        logger.warning("[base_anonimizada] 0 linhas de pesquisa (source=%s)", source)
        return pd.DataFrame()
    df = pd.DataFrame([json.loads(v) for v in t["survey_responses"]])
    df["E-mail"] = _email(t["pessoa_id"]).values
    if include_utm:
        df["__utm_campaign__"] = t["utm_campaign"].values
        df["__utm_source__"] = t["utm_source"].values
    logger.info("[base_anonimizada] %d linhas de pesquisa (source=%s, %d colunas)", len(df), source, len(df.columns))
    return df


def read_sales_anon(start: Optional[str] = None, end: Optional[str] = None,
                    gateways: Optional[Sequence[str]] = None, as_of: Optional[str] = None) -> pd.DataFrame:
    """Mesmo contrato de sales_reader.read_sales: email, telefone, nome, sale_value, sale_date,
    origem, status, product_name."""
    _sem_as_of(as_of)
    v = pd.read_parquet(os.path.join(diretorio(), "vendas_anon.parquet"))
    v["sale_date"] = pd.to_datetime(v["sale_date"], errors="coerce", utc=True).dt.tz_localize(None)
    if start:
        v = v[v["sale_date"] >= pd.Timestamp(start)]
    if end:
        v = v[v["sale_date"] < pd.Timestamp(end) + pd.Timedelta(days=1)]
    if gateways:
        v = v[v["gateway"].isin(list(gateways))]
    df = pd.DataFrame({
        "email": _email(v["pessoa_id"]).values,
        "telefone": None,
        "nome": None,
        "sale_value": v["sale_value"].values,
        "sale_date": v["sale_date"].values,
        "origem": v["gateway"].values,
        "status": v["status"].values,
        "product_name": v["produto"].values,
    })
    logger.info("[base_anonimizada] %d vendas (gateways=%s)", len(df), gateways or "todos")
    return df


def read_tmb_risk_anon() -> dict:
    """Mesmo contrato de tmb_risk_reader.read_tmb_risk: {email_norm: grau de risco}."""
    r = pd.read_parquet(os.path.join(diretorio(), "sales_tmb_risk_anon.parquet"))
    r = r.dropna(subset=["pessoa_id", "risk_grade"])
    lookup = dict(zip(_email(r["pessoa_id"]), r["risk_grade"]))
    logger.info("[base_anonimizada] %d pessoas com grau de risco TMB", len(lookup))
    return lookup
