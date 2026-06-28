"""Persiste resultados de validação no schema analytics (Cloud SQL). Fase 1 da
consolidação (docs/CONSOLIDACAO_CLOUDSQL.md).

Sink PARALELO ao .xlsx — o relatório Excel continua sendo a fonte de export.
Aqui gravamos os mesmos números em tabela consultável (`validation_runs` +
`validation_metrics`) pra parar de depender de N planilhas sobrescritas.

APPEND-ONLY: cada execução vira um `run_id` novo (com timestamp), preservando o
histórico de toda validação rodada — inclusive re-runs e fechamento vs
pós-devoluções do mesmo lançamento.

Não calcula nada: recebe as estruturas já computadas pelo pipeline de validação
e só mapeia pro formato longo das tabelas. Toda transformação continua em
src/core/ / src/validation/metrics_calculator.py.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)


# --- coerção segura: numpy/pandas → tipos nativos, NaN → None -------------
def _f(x) -> Optional[float]:
    try:
        if x is None:
            return None
        xf = float(x)
        return None if math.isnan(xf) else xf
    except (TypeError, ValueError):
        return None


def _i(x) -> Optional[int]:
    xf = _f(x)
    return None if xf is None else int(round(xf))


def _s(x) -> Optional[str]:
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    s = str(x).strip()
    return s or None


def _git_sha() -> Optional[str]:
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent), text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


_RUN_SQL = """
INSERT INTO validation_runs
  (run_id, client_id, lf, cap_start, cap_end, sales_start, sales_end,
   model_run_id, report_type, matching_method, tracking_rate, params, git_sha)
VALUES
  (:run_id, :client_id, :lf, CAST(:cap_start AS date), CAST(:cap_end AS date),
   CAST(:sales_start AS date), CAST(:sales_end AS date), :model_run_id,
   :report_type, :matching_method, :tracking_rate, CAST(:params AS jsonb), :git_sha)
"""

_METRIC_SQL = """
INSERT INTO validation_metrics
  (run_id, grain, decile, campaign, comparison_group, leads, conversions,
   conversion_rate, expected_conversion_rate, performance_ratio, revenue,
   spend, cpl, roas, roas_adjusted, extra)
VALUES
  (:run_id, :grain, :decile, :campaign, :comparison_group, :leads, :conversions,
   :conversion_rate, :expected_conversion_rate, :performance_ratio, :revenue,
   :spend, :cpl, :roas, :roas_adjusted, CAST(:extra AS jsonb))
"""

_METRIC_KEYS = (
    "decile", "campaign", "comparison_group", "leads", "conversions",
    "conversion_rate", "expected_conversion_rate", "performance_ratio",
    "revenue", "spend", "cpl", "roas", "roas_adjusted",
)


def _metric_row(run_id, grain, *, extra=None, **fields):
    row = {k: None for k in _METRIC_KEYS}
    row.update(fields)
    row["run_id"] = run_id
    row["grain"] = grain
    row["extra"] = json.dumps(extra, ensure_ascii=False, default=str) if extra else None
    return row


def _decile_rows(run_id, df: Optional[pd.DataFrame]):
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for _, r in df.iterrows():
        out.append(_metric_row(
            run_id, "decile",
            decile=_s(r.get("decile")),
            leads=_i(r.get("leads")),
            conversions=_i(r.get("conversions_total")),
            conversion_rate=_f(r.get("conversion_rate_total")),
            expected_conversion_rate=_f(r.get("expected_conversion_rate")),
            performance_ratio=_f(r.get("performance_ratio_total")),
            revenue=_f(r.get("revenue_total")),
            extra={
                "conversions_guru": _i(r.get("conversions_guru")),
                "conversion_rate_guru": _f(r.get("conversion_rate_guru")),
                "performance_ratio_guru": _f(r.get("performance_ratio_guru")),
                "revenue_guru": _f(r.get("revenue_guru")),
            },
        ))
    return out


def _campaign_rows(run_id, df: Optional[pd.DataFrame]):
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for _, r in df.iterrows():
        out.append(_metric_row(
            run_id, "campaign",
            campaign=_s(r.get("campaign")),
            comparison_group=_s(r.get("comparison_group")),
            leads=_i(r.get("leads")),
            conversions=_i(r.get("conversions")),
            conversion_rate=_f(r.get("conversion_rate")),
            revenue=_f(r.get("total_revenue")),
            spend=_f(r.get("spend")),
            cpl=_f(r.get("cpl")),
            roas=_f(r.get("roas")),
            roas_adjusted=_f(r.get("roas_adjusted")),
            extra={"contribution_margin": _f(r.get("contribution_margin"))},
        ))
    return out


def _overall_row(run_id, matching_stats: dict, ml_comparison):
    ms = matching_stats or {}
    return _metric_row(
        run_id, "overall",
        leads=_i(ms.get("total_leads")),
        conversions=_i(ms.get("total_conversions")),
        conversion_rate=_f(ms.get("conversion_rate")),
        revenue=_f(ms.get("total_revenue")),
        extra={"matching_stats": ms, "ml_comparison": ml_comparison},
    )


def save_validation_run(
    *,
    lf: Optional[str],
    cap_start, cap_end, sales_start, sales_end,
    report_type: Optional[str],
    matching_method: Optional[str],
    matching_stats: dict,
    decile_metrics: Optional[pd.DataFrame],
    campaign_metrics: Optional[pd.DataFrame],
    ml_comparison=None,
    model_run_id: Optional[str] = None,
    params: Optional[dict] = None,
    client_id: str = "devclub",
) -> str:
    """Grava 1 cabeçalho (validation_runs) + N métricas (validation_metrics).

    Retorna o run_id gerado. Append-only — run_id carrega timestamp da execução.
    """
    ms = matching_stats or {}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{_s(lf) or 'NA'}__{_s(sales_start)}_{_s(sales_end)}__{_s(report_type) or 'NA'}__{stamp}"

    rows = (
        _decile_rows(run_id, decile_metrics)
        + _campaign_rows(run_id, campaign_metrics)
        + [_overall_row(run_id, ms, ml_comparison)]
    )

    conn = open_analytics_connection()
    try:
        conn.run(
            _RUN_SQL,
            run_id=run_id, client_id=client_id, lf=_s(lf),
            cap_start=_s(cap_start), cap_end=_s(cap_end),
            sales_start=_s(sales_start), sales_end=_s(sales_end),
            model_run_id=_s(model_run_id), report_type=_s(report_type),
            matching_method=_s(matching_method),
            tracking_rate=_f(ms.get("tracking_rate")),
            params=json.dumps(params or {}, ensure_ascii=False, default=str),
            git_sha=_git_sha(),
        )
        for row in rows:
            conn.run(_METRIC_SQL, **row)
        logger.info(
            "[results_store] run %s salvo: %d métricas (%d decis, %d campanhas)",
            run_id, len(rows),
            sum(1 for r in rows if r["grain"] == "decile"),
            sum(1 for r in rows if r["grain"] == "campaign"),
        )
        return run_id
    finally:
        conn.close()
