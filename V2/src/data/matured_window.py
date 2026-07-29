"""Janela madura rotulada de leads na régua única do Challenger (abr_28).

É a base da referência rolante do lado da CONVERSÃO/CALIBRAÇÃO: leads captados há
tempo suficiente (>= `maturation_days`) pra já terem passado pelo ciclo de venda,
com score+decil na régua. Nunca inclui lead fresco — a conversão dele é PREVISTA
pelo calibrador, não medida aqui.

(O perfil de característica do COMPRADOR é outra população, ancorada em data de
COMPRA, não de captação — sai de um builder separado, não desta janela.)

Fonte (fonte única por trecho, sem repetir o caso Sheets morto):
  - `registros_ml` (ledger VIVO, >= cutover 23/05/2026) — fonte sustentável: tem
    score+decil na régua e UTM/telefone nativos. Conforme o ledger aprofunda, a
    janela madura desliza pra dentro dele e a ponte abaixo some sozinha (~out/2026).
  - `scores_historicos` (congelada, < cutover) — PONTE transitória: tem score+decil
    da régua no passado. NÃO guarda UTM/telefone, então a fatia da ponte entra só na
    conversão TOTAL; canal/balde da referência cobre a fatia do LEDGER e melhora
    conforme o ledger aprofunda (recuperar UTM da ponte via analytics.leads teve
    plano ruim >180s — fica pra otimização se a cobertura canal/balde apertar).

Não faz o casamento com vendas aqui (isso é `build_matched_df`, reusado a jusante) —
devolve só os LEADS da janela, no shape canônico, deduplicados por email.

Reversível: read-only, não escreve nada.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

# Cutover do ledger: primeira linha de `registros_ml` (verificado 29/07/2026:
# min(created_at) = 2026-05-23). Abaixo disso a régua vem da `scores_historicos`.
LEDGER_CUTOVER = "2026-05-23"

# Shape canônico devolvido (1 linha por email, dedup preferindo o ledger).
CANONICAL_COLS = [
    "email", "telefone", "data_captura", "score_challenger", "decil_challenger",
    "utm_source", "utm_campaign", "utm_content", "source",
]


def resolve_ruler_run_id(client_id: str = "devclub",
                         config_root: Optional[Path] = None) -> Optional[str]:
    """run_id da régua única (o `active_model` = abr_28). A referência tem que nascer
    na régua ATIVA; se o modelo mudar, muda aqui e a referência se recalcula na régua
    nova (é o que resolve a auto-supressão por run_id do relatório de criativo)."""
    root = config_root or Path(__file__).resolve().parents[2]
    p = root / "configs" / "active_models" / f"{client_id}.yaml"
    try:
        cfg = yaml.safe_load(p.read_text()) or {}
        return (cfg.get("active_model") or {}).get("mlflow_run_id")
    except Exception as e:
        logger.warning("[matured_window] run_id da régua indisponível (%s): %s", p, e)
        return None


def matured_bounds(*, window_days: int = 90, maturation_days: int = 60,
                   as_of: Optional[date] = None) -> tuple[datetime, datetime]:
    """Fronteiras da janela madura em captação: [as_of - maturation - window,
    as_of - maturation). O fim recua `maturation_days` do hoje pra garantir que todo
    lead da janela já teve chance de comprar."""
    as_of = as_of or date.today()
    win_end = datetime(as_of.year, as_of.month, as_of.day) - timedelta(days=maturation_days)
    win_start = win_end - timedelta(days=window_days)
    return win_start, win_end


def build_matured_window(
    *,
    window_days: int = 90,
    maturation_days: int = 60,
    as_of: Optional[date] = None,
    client_id: str = "devclub",
    ruler_run_id: Optional[str] = None,
    conn=None,
    allow_empty: bool = False,
) -> pd.DataFrame:
    """Leads da janela madura na régua do Challenger, costurando ledger + ponte.

    Args:
        window_days: largura da janela de captação (default 90d).
        maturation_days: quanto o fim recua do hoje pra garantir maturação (default 60d).
        as_of: "hoje" (default date.today()); injetável pra teste/backfill.
        ruler_run_id: run_id da régua; None → resolve o `active_model` (abr_28).
        conn: conexão Cloud SQL injetada; None → abre e fecha (timeout 180s).
        allow_empty: se False (default), janela vazia FALHA ALTO (uma janela madura de
            90d nunca deve vir vazia em produção — vazio = fonte quebrada).

    Returns:
        DataFrame com `CANONICAL_COLS`, 1 linha por email (dedup preferindo o ledger).
    """
    run_id = ruler_run_id or resolve_ruler_run_id(client_id)
    if not run_id:
        raise ValueError("[matured_window] sem run_id da régua — não dá pra isolar a régua única.")

    win_start, win_end = matured_bounds(window_days=window_days,
                                        maturation_days=maturation_days, as_of=as_of)
    params = {
        "run_id": run_id,
        "cut": LEDGER_CUTOVER,
        "ws": win_start.strftime("%Y-%m-%d %H:%M:%S"),
        "we": win_end.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # DUAS queries simples (plano previsível) em vez de uma costura pesada. Colunas na
    # ordem exata de CANONICAL_COLS nas duas — o concat depois é direto.
    ledger_sql = (
        "SELECT lower(email) AS email, phone AS telefone, created_at AS data_captura, "
        "       score_challenger, decil_challenger, "
        "       utm_source, utm_campaign, utm_content, 'ledger' AS source "
        "FROM public.registros_ml "
        "WHERE created_at >= :cut AND created_at >= :ws AND created_at < :we "
        "  AND challenger_run_id = :run_id "
        "  AND decil_challenger IS NOT NULL AND score_challenger IS NOT NULL "
        "  AND email IS NOT NULL AND email <> ''"
    )
    bridge_sql = (
        "SELECT lower(email) AS email, NULL AS telefone, data_captura, "
        "       score_challenger, (substring(decil_challenger from 2))::int AS decil_challenger, "
        "       NULL AS utm_source, NULL AS utm_campaign, NULL AS utm_content, 'bridge' AS source "
        "FROM public.scores_historicos "
        "WHERE data_captura >= :ws AND data_captura < :cut "
        "  AND challenger_run_id = :run_id "
        "  AND decil_challenger ~ '^D[0-9]+$' AND score_challenger IS NOT NULL "
        "  AND email IS NOT NULL AND email <> ''"
    )

    own = conn is None
    conn = conn or open_analytics_connection(timeout=180)
    try:
        led_rows = conn.run(ledger_sql, **params)
        brg_rows = conn.run(bridge_sql, **params)
    finally:
        if own:
            conn.close()

    df = pd.concat(
        [pd.DataFrame(led_rows, columns=CANONICAL_COLS),
         pd.DataFrame(brg_rows, columns=CANONICAL_COLS)],
        ignore_index=True,
    )
    n_led_raw = len(led_rows)
    n_brg_raw = len(brg_rows)

    if not df.empty:
        # tz-naive UTC: o matcher (build_matched_df) compara data_captura × sale_date
        # direto e exige o mesmo tz.
        df["data_captura"] = pd.to_datetime(df["data_captura"], utc=True, errors="coerce").dt.tz_localize(None)
        df["score_challenger"] = pd.to_numeric(df["score_challenger"], errors="coerce")
        df["decil_challenger"] = pd.to_numeric(df["decil_challenger"], errors="coerce").astype("Int64")
        # Dedup por email preferindo o ledger (produção > snapshot), depois mais recente.
        df["_prio"] = (df["source"] == "ledger").astype(int)
        df = (df.sort_values(["email", "_prio", "data_captura"], ascending=[True, False, False])
                .drop_duplicates("email", keep="first")
                .drop(columns="_prio")
                .reset_index(drop=True))

    logger.info(
        "[matured_window] %s→%s (régua %s): %d leads (ledger %d + ponte %d, %d após dedup)",
        win_start.date(), win_end.date(), run_id[:8], len(df), n_led_raw, n_brg_raw, len(df),
    )

    # Fail-loud: janela madura de produção NÃO vem vazia. Vazio = régua errada,
    # cutover errado, ou fonte quebrada — não um estado legítimo silencioso.
    if df.empty and not allow_empty:
        raise ValueError(
            f"[matured_window] janela {win_start.date()}→{win_end.date()} veio VAZIA "
            f"(régua {run_id}). Fonte quebrada ou run_id/cutover errado — não silenciar."
        )
    return df
