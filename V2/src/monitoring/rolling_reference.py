"""Builder da referência rolante — lado CONVERSÃO/CALIBRAÇÃO.

Transforma a "janela madura rotulada" (`src/data/matured_window.py`) em:
  - conversão REALIZADA por decil / canal (Meta/Google) / balde (Lead/Champion/
    Challenger), a barra móvel que substitui o "Top5 ROAS" congelado;
  - o CALIBRADOR re-ajustado (score→P(compra) real) na mesma janela, pra a métrica
    exibida ser conversão ESPERADA nos leads de hoje.

Uma matched-df, dois usos (a conversão e o calibrador consomem o MESMO casamento).

Reuso (não duplica o join lead↔venda — o incidente fundador da /sw-architect):
  - `build_matched_df` + `read_analytics_sales` (validation): matcher canônico
    email+tel+last6, point-in-time, devolve `converted`.
  - `channel_from_source` / `bucket_from_utm` (campaign_classifier): mesmos
    classificadores do painel de decis (fonte única do split).
  - `make_calibrator` (model.calibration): a Estratégia isotônica que já existe.

Limite conhecido (MVP): a fatia da PONTE (`scores_historicos`, < cutover) não tem
UTM, então canal/balde contam só a fatia do LEDGER (senão os leads sem UTM virariam
'organic' falso). Total e por-decil usam tudo. Isso melhora conforme o ledger
aprofunda e a ponte encolhe.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from src.data.matured_window import build_matured_window, matured_bounds, resolve_ruler_run_id
# NOTE(sw-architect): build_matched_df/read_analytics_sales moram hoje em
# src/validation/model_performance. É reuso (não duplicação); a limpeza de camada
# (mover o join pra src/data e os dois consumirem de lá) fica pra um passo próprio.
from src.validation.model_performance import build_matched_df, read_analytics_sales
from src.monitoring.campaign_classifier import bucket_from_utm, channel_from_source
from src.model.calibration import make_calibrator

logger = logging.getLogger(__name__)


def label_matured(matured_df: pd.DataFrame, sales_df: pd.DataFrame, *,
                  conversion_window_days: int = 60) -> pd.DataFrame:
    """Casa a janela madura com as vendas (matcher canônico) e devolve `matured_df` +
    coluna `converted` (venda dentro de `conversion_window_days` da captação)."""
    return build_matched_df(matured_df, sales_df, window_days=conversion_window_days)


def _conv_by(df: pd.DataFrame, key) -> dict:
    """conversão por grão: {chave: {leads, conv, rate}} a partir da coluna `converted`."""
    out = {}
    g = df.groupby(key)["converted"]
    for k, s in g:
        n = int(s.size)
        c = int(s.sum())
        out[k] = {"leads": n, "conv": c, "rate": (c / n) if n else 0.0}
    return out


def conversion_reference(matched_df: pd.DataFrame, *, bucket_map=None) -> dict:
    """Conversão realizada por decil (tudo), e por canal/balde (só a fatia com UTM).

    by_decile / overall usam a janela inteira (o decil é da régua, vale pra ponte e
    ledger). by_channel / by_bucket usam só linhas COM utm_source (o ledger) — a
    ponte sem UTM não pode virar canal falso.
    """
    if matched_df.empty:
        return {"overall": {"leads": 0, "conv": 0, "rate": 0.0},
                "by_decile": {}, "by_channel": {}, "by_bucket": {},
                "channel_bucket_coverage": {"leads_com_utm": 0, "leads_total": 0}}

    m = matched_df.copy()
    m["converted"] = m["converted"].fillna(False).astype(bool)
    n = len(m)
    c = int(m["converted"].sum())
    overall = {"leads": n, "conv": c, "rate": (c / n) if n else 0.0}

    # por decil (int 1..10 → chave "D01".."D10")
    dec = m.dropna(subset=["decil_challenger"]).copy()
    dec["_dk"] = dec["decil_challenger"].astype(int).map(lambda d: f"D{d:02d}")
    by_decile = _conv_by(dec, "_dk")

    # canal/balde só onde há UTM (fatia do ledger)
    utm = m[m["utm_source"].notna()].copy()
    utm["channel"] = utm["utm_source"].apply(channel_from_source)
    utm["bucket"] = utm["utm_campaign"].apply(lambda x: bucket_from_utm(x, bucket_map))
    by_channel = _conv_by(utm, "channel")
    by_bucket = _conv_by(utm, "bucket")

    logger.info(
        "[rolling_reference] conversão: overall %.3f%% (%d/%d) · canal/balde de %d leads c/ UTM",
        overall["rate"] * 100, c, n, len(utm),
    )
    return {"overall": overall, "by_decile": by_decile, "by_channel": by_channel,
            "by_bucket": by_bucket,
            "channel_bucket_coverage": {"leads_com_utm": len(utm), "leads_total": n}}


def fit_calibrator(matched_df: pd.DataFrame, *, method: str = "isotonic"):
    """Re-ajusta o calibrador (score_challenger → P(compra) real) na janela madura.
    É o passo que mantém a conversão ESPERADA fiel quando o mercado se move."""
    m = matched_df.dropna(subset=["score_challenger"]).copy()
    y_prob = pd.to_numeric(m["score_challenger"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    y_true = m["converted"].fillna(False).astype(int).to_numpy()
    if y_prob.size == 0:
        raise ValueError("[rolling_reference] sem score na janela — não dá pra calibrar.")
    cal = make_calibrator(method).fit(y_prob, y_true)
    logger.info("[rolling_reference] calibrador %s ajustado em %d leads (%d compras)",
                method, y_prob.size, int(y_true.sum()))
    return cal


def sample_calibration_curve(cal, *, n: int = 101) -> dict:
    """Serializa o calibrador como uma curva amostrada score→P num grid [0,1]. O
    leitor reconstrói a conversão ESPERADA de um lead com np.interp — portável, sem
    depender de sklearn na leitura (jsonb na tabela da referência)."""
    import numpy as np
    x = np.linspace(0.0, 1.0, n)
    y = cal.transform(x)
    return {"method": getattr(cal, "method", "unknown"),
            "x": [round(float(v), 4) for v in x.tolist()],
            "y": [round(float(v), 6) for v in y.tolist()]}


def build_conversion_reference(
    *,
    as_of: Optional[date] = None,
    window_days: int = 90,
    maturation_days: int = 60,
    client_id: str = "devclub",
    ruler_run_id: Optional[str] = None,
    bucket_map=None,
    conn=None,
) -> dict:
    """Orquestra: janela madura → casa vendas UMA vez → conversão de referência +
    calibrador. Devolve o dict pronto pra materializar na tabela da referência.
    """
    as_of = as_of or date.today()
    run_id = ruler_run_id or resolve_ruler_run_id(client_id)
    win_start, win_end = matured_bounds(window_days=window_days,
                                        maturation_days=maturation_days, as_of=as_of)

    own = conn is None
    from src.data.analytics_connection import open_analytics_connection
    conn = conn or open_analytics_connection(timeout=180)
    try:
        matured = build_matured_window(
            window_days=window_days, maturation_days=maturation_days, as_of=as_of,
            client_id=client_id, ruler_run_id=run_id, conn=conn,
        )
        # Vendas de [win_start, as_of]: cobre a janela de conversão (até 60d após a
        # captação mais recente da janela, que já passou). end exclusivo → +1 dia.
        sales = read_analytics_sales(conn, win_start.date(), as_of + timedelta(days=1))
    finally:
        if own:
            conn.close()

    matched = label_matured(matured, sales, conversion_window_days=maturation_days)
    conv = conversion_reference(matched, bucket_map=bucket_map)
    # Economia do teto (Fase 3): valor por venda da janela (cartão 2k + boleto 50%,
    # mistura REAL de gateways). Vive dentro do `conversion` jsonb → sem coluna nova.
    from src.monitoring.teto import value_per_sale_from_sales
    conv["economics"] = value_per_sale_from_sales(sales)
    cal = fit_calibrator(matched)
    return {
        "window_start": win_start.date().isoformat(),
        "window_end": win_end.date().isoformat(),
        "as_of": as_of.isoformat(),
        "ruler_run_id": run_id,
        "n_leads": len(matched),
        "conversion": conv,
        "calibrator": cal,
    }
