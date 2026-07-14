"""
model_performance.py — Vértebra 1 do relatório de performance de modelo.

Computa as métricas de RANQUEAMENTO do(s) modelo(s) em operação, por LF, lendo
o ledger (`registros_ml`) × `analytics.sales` — sem rescore, sem Meta API, sem
geração de xlsx. O decil já está fotografado no ledger no momento do scoring de
produção; aqui só cruzamos com vendas por email/telefone pra obter o desfecho.

Responsabilidade ÚNICA: dado um LF, devolver um objeto com as métricas por braço.
NÃO persiste (Etapa 2) nem emite Slack (Etapa 3) — isso fica na composição.

Métricas empíricas (decil de produção do ledger × vendas casadas) — lift vs o
baseline OBSERVADO de cada braço, concentração top3/top5. NÃO usa metadata de
treino nem mlruns (o usuário avalia bom/ruim olhando o resultado).

Reuso (fonte única, não recria):
  - matching:            core.matching.match_leads_to_sales_unified (email+tel+last6)
  - janelas de LF:       core.launches.load_launches
  - atribuição de braço: coluna `variant` do ledger (verdade de produção)

Injeção de dependência: `compute_lf_performance` recebe leitores (callables) e o
registro de modelos — não abre conexão. A composição (CLI/job) injeta os leitores
reais. Assim o cálculo é testável sem banco.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from src.core.launches import load_launches
from src.core.matching import match_leads_to_sales_unified

logger = logging.getLogger(__name__)

# Data em que o ledger `registros_ml` passou a ser populado (consumer Pub/Sub).
# LFs cuja captação termina antes disso não têm dado no ledger.
LEDGER_START = date(2026, 5, 23)

_DEFAULT_ACTIVE_MODELS = (
    Path(__file__).resolve().parents[2] / "configs" / "active_models" / "devclub.yaml"
)


# ───────────────────────── contrato de saída (DTO) ──────────────────────────
@dataclass(frozen=True)
class ArmPerformance:
    """Performance de ranqueamento de UM modelo num LF."""
    arm: str                     # 'champion' | 'challenger' (role do config)
    variant: Optional[str]       # valor cru do ledger ('challenger_abr28' | None)
    display_name: str            # rótulo humano do active_models (ex.: 'Champion (abr_28)')
    model_run_id: str
    n_leads: int
    n_conversions: int
    conversion_rate: float       # n_conversions / n_leads (fração)
    revenue: float               # soma de sale_value (bruto) das vendas casadas neste braço
    mean_score: float            # qualidade de entrada (não depende de desfecho)
    lift: pd.DataFrame                 # decil de PRODUÇÃO; lift vs baseline OBSERVADO do braço
    concentration: dict                # top-3 / top-5 decis (produção, empírico)


@dataclass(frozen=True)
class LFModelPerformance:
    """Resultado de um LF: metadados de maturidade + 1 ArmPerformance por modelo."""
    lf: str
    cap_start: date
    cap_end: date
    vendas_start: Optional[date]
    vendas_end: Optional[date]
    as_of_date: date
    window_days: int
    days_since_cap_end: int
    maturity: str                # 'mature' | 'provisional'
    ledger_covered: bool         # False quando a janela precede o ledger
    n_leads_total: int
    arms: tuple                   # tuple[ArmPerformance, ...]
    n_lfs: int = 0                # 0 = LF único; >0 = bloco AGREGADO (pool de N LFs)


# ───────────────────────── registro de modelos ──────────────────────────────
@dataclass(frozen=True)
class _ModelInfo:
    arm: str
    variant_key: Optional[str]
    run_id: str
    display_name: str


class ModelRegistry:
    """Mapeia o `variant` do ledger → modelo (run_id + rótulo humano).

    `variant='challenger_abr28'` → Challenger. `variant` nulo → braço default
    (Champion = active_model). Lê só de configs/active_models/devclub.yaml — NÃO
    precisa de mlruns/model_metadata: as métricas são empíricas (decil de produção
    × vendas casadas), então nenhum artefato de treino é necessário.
    """

    def __init__(self, active_models_path: Optional[Path] = None):
        import yaml

        cfg_path = Path(active_models_path or _DEFAULT_ACTIVE_MODELS)
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}

        active = cfg.get("active_model", {})
        self._active_run = str(active.get("mlflow_run_id", "")).strip()
        variants = (cfg.get("ab_test", {}) or {}).get("variants", {}) or {}

        # display_name do Champion vem do variant cujo run_id == active_model.
        champ_display = "Champion (ativo)"
        for key, v in variants.items():
            if str(v.get("run_id", "")).strip() == self._active_run:
                champ_display = v.get("display_name", champ_display)
                break
        self._champion = _ModelInfo(
            arm="champion", variant_key=None, run_id=self._active_run,
            display_name=champ_display,
        )

        # demais variants (challenger etc.), chaveados pelo valor cru do ledger.
        self._by_variant: dict[str, _ModelInfo] = {}
        for key, v in variants.items():
            run_id = str(v.get("run_id", "")).strip()
            if not run_id or run_id == self._active_run:
                continue  # o que aponta pro active é o Champion (já tratado)
            self._by_variant[key] = _ModelInfo(
                arm=str(v.get("role", "challenger")),
                variant_key=key,
                run_id=run_id,
                display_name=v.get("display_name", key),
            )

    def for_variant(self, variant: Optional[str]) -> Optional[_ModelInfo]:
        """Modelo que scoreou um lead com esse `variant`. None=Champion default.

        Retorna None se o variant for desconhecido (não é o default nem um variant
        cadastrado) — o chamador decide pular com aviso (fail-loud sem derrubar).
        """
        v = (str(variant).strip() if variant is not None else "")
        if not v or v.lower() in ("none", "nan"):
            return self._champion
        return self._by_variant.get(v)


# ───────────────────────── leitores (data access) ───────────────────────────
# Projeções enxutas; ficam aqui na Etapa 1. Fase 2 do estrangulamento move pra
# repositórios em src/data/. O chamador injeta a conexão (dono de fechá-la).
_LEDGER_COLS = ("email", "phone", "created_at", "decil", "lead_score", "variant", "utm_campaign")
_SALES_COLS = ("email", "phone", "sale_value", "sale_value_realizado", "sale_date", "gateway")


def read_ledger_leads(ledger_conn, cap_start: date, cap_end: date) -> pd.DataFrame:
    """Leads scoreados no ledger com captação na janela [cap_start, cap_end]."""
    sql = (
        f"SELECT {', '.join(_LEDGER_COLS)} FROM registros_ml "
        "WHERE created_at >= :s AND created_at < (CAST(:e AS date) + INTERVAL '1 day') "
        "AND lead_score IS NOT NULL"
    )
    rows = ledger_conn.run(sql, s=cap_start.isoformat(), e=cap_end.isoformat())
    df = pd.DataFrame(rows, columns=list(_LEDGER_COLS))
    df = df.rename(columns={"phone": "telefone", "created_at": "data_captura"})
    # tz-naive UTC: o matcher compara data_captura × sale_date direto; precisam
    # do mesmo tz (ledger e sales chegam com awareness diferente do pg8000).
    df["data_captura"] = pd.to_datetime(df["data_captura"], utc=True, errors="coerce").dt.tz_localize(None)
    return df


def read_analytics_sales(analytics_conn, start: date, end: date) -> pd.DataFrame:
    """Vendas de `analytics.sales` com sale_date em [start, end)."""
    sql = (
        f"SELECT {', '.join(_SALES_COLS)} FROM sales "
        "WHERE sale_date >= :s AND sale_date < :e"
    )
    rows = analytics_conn.run(sql, s=start.isoformat(), e=end.isoformat())
    df = pd.DataFrame(rows, columns=list(_SALES_COLS))
    df = df.rename(columns={"phone": "telefone", "gateway": "origem"})
    if not df.empty:
        df["sale_date"] = pd.to_datetime(df["sale_date"], utc=True, errors="coerce").dt.tz_localize(None)
        df = df.sort_values("sale_date").reset_index(drop=True)  # earliest-first p/ o matcher
    return df


def read_sales_coverage(analytics_conn) -> dict:
    """Até quando `analytics.sales` tem vendas — geral e por gateway. Base do guard de
    defasagem: se a observação de um LF passa dessa data, o número está subcontado."""
    rows = analytics_conn.run("SELECT gateway, max(sale_date) FROM sales GROUP BY gateway")
    by_gw = {}
    for r in rows:
        d = pd.to_datetime(r[1], errors="coerce")
        by_gw[r[0]] = (d.date() if pd.notna(d) else None)
    dates = [d for d in by_gw.values() if d]
    return {"overall": max(dates) if dates else None, "by_gateway": by_gw}


# ───────────────────────── construção do matched_df ─────────────────────────
def build_matched_df(leads_df: pd.DataFrame, sales_df: pd.DataFrame, *, window_days: int) -> pd.DataFrame:
    """Marca cada lead como convertido se casa uma venda dentro de `window_days`
    da captação. Reusa o matcher canônico (email+tel+last6, temporal) e impõe o
    teto da janela por lead. Devolve leads_df + colunas `converted` e `decile`.
    """
    if leads_df.empty:
        return leads_df.assign(converted=pd.Series(dtype=bool), decile=pd.Series(dtype=object))

    if sales_df.empty:
        matched = leads_df.copy()
        matched["converted"] = False
        matched["sale_date"] = pd.NaT
    else:
        matched = match_leads_to_sales_unified(
            leads_df, sales_df, mode="validation", use_temporal_validation=True,
        )
        # Teto da janela por lead: venda dentro de [captura, captura + window_days].
        cap = pd.to_datetime(matched["data_captura"], utc=True, errors="coerce")
        sd = pd.to_datetime(matched["sale_date"], utc=True, errors="coerce")
        delta_days = (sd - cap).dt.total_seconds() / 86400.0
        within = matched["converted"].fillna(False) & sd.notna() & (delta_days >= 0) & (delta_days <= window_days)
        matched["converted"] = within.astype(bool)

    matched["decile"] = matched["decil"].apply(
        lambda d: f"D{int(d)}" if pd.notna(d) else None
    )
    return matched


# ───────────────────────── cálculo por LF ───────────────────────────────────
def _coerce_date(s) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def _cart_closed(cfg: dict, as_of: date) -> bool:
    """LF cujo carrinho JÁ FECHOU até `as_of` (ciclo de vendas completo). Antes disso
    as vendas são parciais/ruído — o relatório padrão só inclui LF fechado."""
    ve = _coerce_date(cfg.get("vendas_end"))
    return ve is not None and ve <= as_of


_LIFT_COLS = ["decile", "leads", "conversions", "conversion_rate", "baseline_rate", "lift"]


def _lift_by_decile(arm_df: pd.DataFrame) -> pd.DataFrame:
    """Lift por decil de PRODUÇÃO vs baseline OBSERVADO do próprio braço (empírico,
    sem metadata de treino). Mesmas colunas que o display/persist consomem:
    decile, leads, conversions, conversion_rate (%), baseline_rate (%), lift."""
    df = arm_df[arm_df["decile"].notna()]
    if df.empty:
        return pd.DataFrame(columns=_LIFT_COLS)
    conv = df["converted"].fillna(False).astype(bool)
    g = df.assign(_c=conv).groupby("decile")["_c"].agg(["count", "sum"]).reset_index()
    g.columns = ["decile", "leads", "conversions"]
    g["conversion_rate"] = g["conversions"] / g["leads"] * 100
    total_leads, total_conv = int(g["leads"].sum()), int(g["conversions"].sum())
    baseline = (total_conv / total_leads * 100) if total_leads else 0.0
    g["baseline_rate"] = baseline
    g["lift"] = (g["conversion_rate"] / baseline) if baseline else 0.0
    g["_n"] = g["decile"].str.extract(r"(\d+)").astype(int)
    return g.sort_values("_n").drop(columns="_n").reset_index(drop=True)


def _concentration(arm_df: pd.DataFrame) -> dict:
    """% dos compradores nos top decis de produção (empírico): top3 = D8–D10,
    top5 = D6–D10."""
    conv = arm_df[arm_df["converted"].fillna(False).astype(bool)].groupby("decile").size()
    total = int(conv.sum())
    if total == 0:
        return {"top3_production": 0.0, "top5_production": 0.0}
    top3 = sum(int(conv.get(d, 0)) for d in ("D8", "D9", "D10"))
    top5 = sum(int(conv.get(d, 0)) for d in ("D6", "D7", "D8", "D9", "D10"))
    return {"top3_production": top3 / total * 100, "top5_production": top5 / total * 100}


def _arm_metrics(arm_df: pd.DataFrame, info: _ModelInfo) -> ArmPerformance:
    n = len(arm_df)
    conv_mask = arm_df["converted"].fillna(False).astype(bool)
    conv = int(conv_mask.sum())
    scores = pd.to_numeric(arm_df["lead_score"], errors="coerce")
    # receita = soma do valor bruto das vendas casadas (só onde converteu na janela;
    # o matcher preenche sale_value mesmo em match fora da janela, então mascaramos).
    sv = pd.to_numeric(
        arm_df.get("sale_value", pd.Series(0.0, index=arm_df.index)), errors="coerce"
    ).fillna(0.0)
    revenue = float(sv.where(conv_mask, 0.0).sum())
    return ArmPerformance(
        arm=info.arm,
        variant=info.variant_key,
        display_name=info.display_name,
        model_run_id=info.run_id,
        n_leads=n,
        n_conversions=conv,
        conversion_rate=(conv / n) if n else 0.0,
        revenue=revenue,
        mean_score=float(scores.mean()) if n else float("nan"),
        lift=_lift_by_decile(arm_df),
        concentration=_concentration(arm_df),
    )


def _load_matched(
    lf: str, *, ledger_reader, sales_reader, as_of: date, window_days: int, launches: dict
) -> dict:
    """Lê o ledger + vendas de UM LF e devolve o matched_df + metadados de janela.
    Peça reusada por `compute_lf_performance` (1 LF) e `compute_aggregate_performance`
    (pool de LFs) — mesma leitura, mesma régua de casamento."""
    cfg = launches.get(lf)
    if not cfg:
        raise KeyError(f"LF {lf!r} não encontrado em launches.yaml")

    cap_start = _coerce_date(cfg.get("cap_start"))
    cap_end = _coerce_date(cfg.get("cap_end"))
    vendas_start = _coerce_date(cfg.get("vendas_start"))
    vendas_end = _coerce_date(cfg.get("vendas_end"))
    days_since = (as_of - cap_end).days if cap_end else -1
    maturity = "mature" if days_since >= window_days else "provisional"
    ledger_covered = bool(cap_end and cap_end >= LEDGER_START)

    leads_df = ledger_reader(cap_start, cap_end)
    # vendas: da captação até captura + janela (cobre o teto de qualquer lead do LF)
    sales_end = min(as_of, (cap_end + timedelta(days=window_days))) if cap_end else as_of
    sales_df = sales_reader(cap_start, sales_end + timedelta(days=1))
    matched = build_matched_df(leads_df, sales_df, window_days=window_days)

    return {
        "matched": matched, "cap_start": cap_start, "cap_end": cap_end,
        "vendas_start": vendas_start, "vendas_end": vendas_end,
        "days_since": days_since, "maturity": maturity, "ledger_covered": ledger_covered,
    }


def _arms_from_matched(matched: pd.DataFrame, registry: ModelRegistry, label: str) -> tuple:
    """Agrupa o matched_df por `variant`, resolve o modelo e computa as métricas por
    braço. Champion primeiro. `label` só entra no log de variant desconhecido."""
    arms: list[ArmPerformance] = []
    if not matched.empty:
        for variant, grp in matched.groupby(matched["variant"], dropna=False):
            info = registry.for_variant(variant if pd.notna(variant) else None)
            if info is None:
                logger.warning("[model_performance] %s: variant %r desconhecido — pulado (%d leads)",
                               label, variant, len(grp))
                continue
            arms.append(_arm_metrics(grp.copy(), info))
    arms.sort(key=lambda a: (a.arm != "champion", a.arm))
    return tuple(arms)


def compute_lf_performance(
    lf: str,
    *,
    ledger_reader: Callable[[date, date], pd.DataFrame],
    sales_reader: Callable[[date, date], pd.DataFrame],
    registry: ModelRegistry,
    as_of_date: Optional[date] = None,
    window_days: int = 60,
    launches: Optional[dict] = None,
) -> LFModelPerformance:
    """Computa a performance de ranqueamento de cada modelo em operação no `lf`.

    `ledger_reader(cap_start, cap_end)` e `sales_reader(start, end)` são injetados
    (devolvem DataFrames). `as_of_date` default = hoje (carimbo de maturação).
    """
    launches = launches if launches is not None else load_launches()
    as_of = as_of_date or datetime.utcnow().date()
    m = _load_matched(lf, ledger_reader=ledger_reader, sales_reader=sales_reader,
                      as_of=as_of, window_days=window_days, launches=launches)

    return LFModelPerformance(
        lf=lf, cap_start=m["cap_start"], cap_end=m["cap_end"],
        vendas_start=m["vendas_start"], vendas_end=m["vendas_end"],
        as_of_date=as_of, window_days=window_days,
        days_since_cap_end=m["days_since"], maturity=m["maturity"],
        ledger_covered=m["ledger_covered"], n_leads_total=len(m["matched"]),
        arms=_arms_from_matched(m["matched"], registry, lf),
    )


def compute_range_performance(
    start: date, end: date,
    *,
    ledger_reader: Callable[[date, date], pd.DataFrame],
    sales_reader: Callable[[date, date], pd.DataFrame],
    registry: ModelRegistry,
    as_of_date: Optional[date] = None,
    window_days: int = 60,
) -> LFModelPerformance:
    """AGREGADO por intervalo de CAPTAÇÃO [start, end], ignorando fronteiras de LF —
    pool de todos os leads do ledger capturados na janela, casados com vendas, por
    modelo. Dá controle total de maturação: `end` mais recuado = mais dias observados
    por lead (a observação sempre termina no `as_of`/hoje). O flag MADURO/PROVISÓRIO
    reflete os dias observados do lead mais recente do intervalo."""
    as_of = as_of_date or datetime.utcnow().date()
    leads_df = ledger_reader(start, end)
    sales_end = min(as_of, end + timedelta(days=window_days))
    sales_df = sales_reader(start, sales_end + timedelta(days=1))
    matched = build_matched_df(leads_df, sales_df, window_days=window_days)
    days_since = (as_of - end).days
    label = f"AGREGADO captações {start:%d/%m}–{end:%d/%m}"
    return LFModelPerformance(
        lf=label, cap_start=start, cap_end=end, vendas_start=None, vendas_end=None,
        as_of_date=as_of, window_days=window_days, days_since_cap_end=days_since,
        maturity="mature" if days_since >= window_days else "provisional",
        ledger_covered=(end >= LEDGER_START), n_leads_total=len(matched),
        arms=_arms_from_matched(matched, registry, label),
    )


def compute_aggregate_performance(
    lfs: list,
    *,
    ledger_reader: Callable[[date, date], pd.DataFrame],
    sales_reader: Callable[[date, date], pd.DataFrame],
    registry: ModelRegistry,
    as_of_date: Optional[date] = None,
    window_days: int = 60,
    launches: Optional[dict] = None,
) -> LFModelPerformance:
    """AGREGADO: junta os leads de TODOS os `lfs` num pool e computa as métricas de
    ranqueamento por modelo UMA vez sobre o pool. É a resposta pro n baixo por LF —
    curva de ranqueamento/lift/conc./receita do modelo em TODA a operação, não a soma
    de blocos no olho. O decil de cada lead é o de produção (já fotografado), então
    empilhar LFs é legítimo. Maduro só se todos os LFs usados já passaram dos 60d."""
    launches = launches if launches is not None else load_launches()
    as_of = as_of_date or datetime.utcnow().date()

    parts, used, cap_starts, cap_ends = [], [], [], []
    covered_all = True
    for lf in lfs:
        m = _load_matched(lf, ledger_reader=ledger_reader, sales_reader=sales_reader,
                          as_of=as_of, window_days=window_days, launches=launches)
        if not m["ledger_covered"]:
            covered_all = False
        mt = m["matched"]
        if mt.empty:
            continue
        mt = mt.copy()
        mt["_lf"] = lf
        parts.append(mt)
        used.append(lf)
        if m["cap_start"]:
            cap_starts.append(m["cap_start"])
        if m["cap_end"]:
            cap_ends.append(m["cap_end"])

    pooled = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    cap_start = min(cap_starts) if cap_starts else None
    cap_end = max(cap_ends) if cap_ends else None
    days_since = (as_of - cap_end).days if cap_end else -1
    all_mature = bool(cap_end and days_since >= window_days and covered_all)
    label = f"AGREGADO {used[0]}–{used[-1]}" if used else "AGREGADO (vazio)"

    return LFModelPerformance(
        lf=label, cap_start=cap_start, cap_end=cap_end,
        vendas_start=None, vendas_end=None, as_of_date=as_of, window_days=window_days,
        days_since_cap_end=days_since, maturity="mature" if all_mature else "provisional",
        ledger_covered=covered_all, n_leads_total=len(pooled),
        arms=_arms_from_matched(pooled, registry, label), n_lfs=len(used),
    )


# ───────────────────────── persistência (Etapa 2) ───────────────────────────
def persist_lf_performance(result: LFModelPerformance, *, conn=None, client_id: str = "devclub") -> str:
    """Grava 1 cabeçalho + métricas por braço em `analytics.validation_*`
    (mesmas tabelas/contrato do results_store), com `report_type='model_performance'`.

    Idempotente por (LF, as_of): re-rodar o mesmo dia SUBSTITUI a medição; cada
    `as_of` novo é uma linha nova (série de maturação preservada). Braço vai em
    `comparison_group`; concentração/mean_score no `extra` (jsonb); decil de PRODUÇÃO
    (do lift) vira as linhas grain='decile'.
    """
    import json

    from src.data.analytics_connection import open_analytics_connection
    from src.validation.results_store import _RUN_SQL, _METRIC_SQL, _metric_row, _f, _i, _git_sha

    run_id = f"{result.lf}__model_performance__{result.as_of_date.isoformat()}"
    params = {
        "as_of": result.as_of_date.isoformat(),
        "window_days": result.window_days,
        "maturity": result.maturity,
        "days_since_cap_end": result.days_since_cap_end,
        "ledger_covered": result.ledger_covered,
    }

    rows = []
    for arm in result.arms:
        rows.append(_metric_row(
            run_id, "overall", comparison_group=arm.arm,
            leads=_i(arm.n_leads), conversions=_i(arm.n_conversions),
            conversion_rate=_f(arm.conversion_rate),
            extra={
                "display_name": arm.display_name, "model_run_id": arm.model_run_id,
                "variant": arm.variant, "mean_score": _f(arm.mean_score),
                "revenue": _f(arm.revenue),
                "top3_production": _f(arm.concentration.get("top3_production")),
                "top5_production": _f(arm.concentration.get("top5_production")),
                "maturity": result.maturity,
            },
        ))
        if arm.lift is not None and not arm.lift.empty:
            for r in arm.lift.itertuples():
                rows.append(_metric_row(
                    run_id, "decile", comparison_group=arm.arm, decile=str(r.decile),
                    leads=_i(r.leads), conversions=_i(r.conversions),
                    conversion_rate=_f(r.conversion_rate),
                    extra={"lift": _f(r.lift), "baseline_rate": _f(getattr(r, "baseline_rate", None))},
                ))

    own = conn is None
    conn = conn or open_analytics_connection()
    try:
        conn.run("BEGIN")
        conn.run("DELETE FROM validation_runs WHERE run_id = :rid", rid=run_id)  # CASCADE limpa métricas
        conn.run(
            _RUN_SQL, run_id=run_id, client_id=client_id, lf=result.lf,
            cap_start=result.cap_start.isoformat() if result.cap_start else None,
            cap_end=result.cap_end.isoformat() if result.cap_end else None,
            sales_start=result.vendas_start.isoformat() if result.vendas_start else None,
            sales_end=result.vendas_end.isoformat() if result.vendas_end else None,
            model_run_id=None, report_type="model_performance",
            matching_method="email_phone_60d", tracking_rate=None,
            params=json.dumps(params, ensure_ascii=False), git_sha=_git_sha(),
        )
        for row in rows:
            conn.run(_METRIC_SQL, **row)
        conn.run("COMMIT")
        logger.info("[model_performance] persistido %s (%d métricas, %d braços)",
                    run_id, len(rows), len(result.arms))
        return run_id
    except Exception:
        conn.run("ROLLBACK")
        raise
    finally:
        if own:
            conn.close()


# ───────────────────────── composição / CLI ─────────────────────────────────
def _open_real_readers():
    """Ponto de composição: abre as conexões reais e devolve (readers, closer)."""
    from src.data.ledger_connection import open_ledger_read_connection
    from src.data.analytics_connection import open_analytics_connection

    lc = open_ledger_read_connection()
    ac = open_analytics_connection()

    def ledger_reader(cs, ce):
        return read_ledger_leads(lc, cs, ce)

    def sales_reader(s, e):
        return read_analytics_sales(ac, s, e)

    def coverage_reader():
        return read_sales_coverage(ac)

    def closer():
        lc.close()
        ac.close()

    return ledger_reader, sales_reader, coverage_reader, closer


def _print_result(res: LFModelPerformance, sales_max: Optional[date] = None) -> None:
    if res.n_lfs:
        flag = f"POOL de {res.n_lfs} LFs" + ("" if res.maturity == "mature" else " · inclui LFs imaturos")
    else:
        flag = "MADURO" if res.maturity == "mature" else f"PROVISÓRIO (faltam {res.window_days - res.days_since_cap_end}d p/ 60d)"
    cov = "" if res.ledger_covered else "  [SEM COBERTURA DO LEDGER]"
    gap = _obs_gap_days(res, sales_max)
    stale = f"  ⚠ VENDAS INCOMPLETAS (banco só até {sales_max:%d/%m}, faltam {gap}d de observação)" if gap else ""
    print(f"\n{'='*72}\n{res.lf}  cap {res.cap_start}→{res.cap_end}  | {flag}{cov}{stale}")
    print(f"  leads no ledger: {res.n_leads_total}  | as_of={res.as_of_date}")
    if not res.arms:
        print("  (sem braços com dados)")
        return
    for a in res.arms:
        print(f"\n  ▸ {a.display_name}  [{a.arm} · {a.variant or 'default'} · {a.model_run_id[:8]}]")
        print(f"      leads={a.n_leads}  conversões={a.n_conversions}  "
              f"conv={a.conversion_rate*100:.2f}%  receita=R$ {_brl(a.revenue)}  score_médio={a.mean_score:.4f}")
        print(f"      concentração compradores no topo: top3={a.concentration.get('top3_production'):.0f}% "
              f"top5={a.concentration.get('top5_production'):.0f}%")
        if not a.lift.empty:
            tail = a.lift.tail(3)[["decile", "leads", "conversions", "lift"]]
            print("      lift (D8-D10): " + "  ".join(
                f"{r.decile}:{r.lift:.2f}(n={int(r.leads)})" for r in tail.itertuples()))


# ───────────────────────── Slack DM (Etapa 3) ───────────────────────────────
_LOW_N_CONV = 30  # abaixo disso, métrica de desfecho é ruído — sinaliza


def _lift_at(arm: ArmPerformance, decile: str) -> Optional[float]:
    if arm.lift is None or arm.lift.empty:
        return None
    sel = arm.lift.loc[arm.lift["decile"] == decile, "lift"]
    return float(sel.iloc[0]) if len(sel) else None


_DECILES = [f"D{i}" for i in range(1, 11)]


def _brl(v: float) -> str:
    """Reais no padrão BR: 14.320,21 (milhar com ponto, decimal com vírgula)."""
    return f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _obs_gap_days(res: LFModelPerformance, sales_max: Optional[date]) -> int:
    """Dias da janela de observação do LF que a tabela de vendas NÃO cobre. >0 = o
    número está subcontado (o carrinho/observação passa da última venda no banco)."""
    if sales_max is None or res.cap_end is None:
        return 0
    obs_end = min(res.as_of_date, res.cap_end + timedelta(days=res.window_days))
    return max(0, (obs_end - sales_max).days)


def _short_label(arm: ArmPerformance) -> str:
    """Rótulo curto p/ a tira de decil: a era entre parênteses (jan_30/abr_28)."""
    import re as _re
    m = _re.search(r"\(([^)]+)\)", arm.display_name)
    return m.group(1) if m else arm.arm


def _conv_strip(arm: ArmPerformance) -> str:
    """conv% por decil D1→D10 (do lift df); '·' onde o decil não tem lead."""
    if arm.lift is None or arm.lift.empty:
        return "—"
    m = {r.decile: r.conversion_rate for r in arm.lift.itertuples()}
    return " ".join(f"{m[d]:4.1f}" if d in m else "   ·" for d in _DECILES)


def _fmt_lf_block(res: LFModelPerformance, sales_max: Optional[date] = None) -> str:
    if res.n_lfs:
        flag = f"pool de {res.n_lfs} LFs" + ("" if res.maturity == "mature" else " · inclui LFs imaturos")
    else:
        flag = ("MADURO" if res.maturity == "mature"
                else f"PROVISÓRIO (faltam {res.window_days - res.days_since_cap_end}d p/ 60d)")
    head = f"*{res.lf}*  cap {res.cap_start:%d/%m}–{res.cap_end:%d/%m}  ·  {flag}"
    if not res.arms:
        return head + "\n_(sem braços com dados no ledger)_"
    rows = [f"{'modelo':<18}{'leads':>7}{'vds':>5}{'conv%':>7}{'receita R$':>14}{'top3':>6}{'liftD10':>8}"]
    strips = ["", "conv% por decil (D1→D10):"]
    low = []
    for a in res.arms:
        top3 = a.concentration.get("top3_production")
        top3_s = f"{top3:.0f}%" if isinstance(top3, (int, float)) else "–"
        d10 = _lift_at(a, "D10")
        rows.append(
            f"{a.display_name[:17]:<18}{a.n_leads:>7}{a.n_conversions:>5}"
            f"{a.conversion_rate * 100:>6.2f}%{_brl(a.revenue):>14}{top3_s:>6}"
            f"{(f'{d10:.2f}' if d10 is not None else '–'):>8}"
        )
        strips.append(f"  {_short_label(a):<7} {_conv_strip(a)}")
        if a.n_conversions < _LOW_N_CONV:
            low.append(f"{a.arm} {a.n_conversions} vendas")
    block = head + "\n```\n" + "\n".join(rows + strips) + "\n```"
    gap = _obs_gap_days(res, sales_max)
    if gap:
        block += (f"\n⚠ *vendas incompletas*: banco só até {sales_max:%d/%m} "
                  f"(faltam {gap}d de observação) — números subcontados")
    if low:
        block += f"\n⚠ amostra baixa (ranqueamento = ruído): {', '.join(low)}"
    return block


def _coverage_note(coverage: Optional[dict]) -> str:
    if not coverage or not coverage.get("overall"):
        return ""
    overall = coverage["overall"]
    tmb = coverage.get("by_gateway", {}).get("tmb")
    tmb_s = f" · TMB (boleto) só até {tmb:%d/%m}" if tmb and tmb < overall else ""
    return f"\n_vendas no banco até {overall:%d/%m}{tmb_s}_"


def format_slack(results: list, as_of: date, window_days: int, coverage: Optional[dict] = None) -> str:
    sales_max = coverage.get("overall") if coverage else None
    head = (f"*Performance de ranqueamento dos modelos por LF*\n"
            f"_as_of {as_of:%d/%m/%Y} · janela {window_days}d · top3 = % dos compradores nos decis 8–10 · vendas casadas no ledger_\n"
            f"_receita = valor bruto das vendas casadas (R$) · ROAS = receita÷gasto (gasto ainda fora do banco, ver meta_insights)_"
            f"{_coverage_note(coverage)}")
    return head + "\n\n" + "\n\n".join(_fmt_lf_block(r, sales_max) for r in results)


def post_slack_dm(text: str, *, dry_run: bool = False) -> str:
    """Posta no DM do usuário (SLACK_USER_DM via chat.postMessage). Sem creds ou
    dry_run → só imprime o preview. Mesmo endpoint do critical_alerts (sem a
    máquina de cooldown, que é de alerta)."""
    import json as _json
    import os as _os
    import urllib.request

    chan, token = _os.environ.get("SLACK_USER_DM"), _os.environ.get("SLACK_BOT_TOKEN")
    if dry_run or not (chan and token):
        if not (chan and token):
            logger.warning("[model_performance] SLACK_USER_DM/SLACK_BOT_TOKEN ausente — preview")
        print("\n----- DM Slack (preview) -----\n" + text + "\n------------------------------")
        return "dry_run"
    body = _json.dumps({"channel": chan, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = _json.load(r)
    if not resp.get("ok"):
        logger.error("[model_performance] Slack rejeitou: %s", resp)
        return "error"
    return "sent"


def main():
    import argparse

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    # carrega .env da raiz V2 (creds de DB) se houver
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Performance de ranqueamento do(s) modelo(s) por LF")
    ap.add_argument("--lf",
                    help="LF (ex.: LF56) ou lista separada por vírgula, ou 'challenger' p/ o padrão "
                         "(LFs do ledger com carrinho já fechado). Opcional se usar --start-date/--end-date")
    ap.add_argument("--start-date", help="agregado por CAPTAÇÃO: início YYYY-MM-DD (ignora fronteiras de LF)")
    ap.add_argument("--end-date", help="agregado por CAPTAÇÃO: fim YYYY-MM-DD (você controla a maturação)")
    ap.add_argument("--as-of", help="data de referência YYYY-MM-DD = fim da observação (default: hoje)")
    ap.add_argument("--window-days", type=int, default=60)
    ap.add_argument("--include-open-cart", action="store_true",
                    help="no modo 'challenger', inclui também LFs com carrinho aberto/não aberto")
    ap.add_argument("--aggregate", action="store_true",
                    help="adiciona um bloco AGREGADO (pool de todos os LFs pedidos) por modelo")
    ap.add_argument("--aggregate-only", action="store_true",
                    help="emite SÓ o bloco agregado, sem os blocos por LF")
    ap.add_argument("--persist", action="store_true",
                    help="grava as métricas em analytics.validation_* (report_type=model_performance)")
    ap.add_argument("--slack", action="store_true", help="manda um DM com todos os LFs no Slack")
    ap.add_argument("--slack-dry-run", action="store_true", help="mostra o preview do DM, sem postar")
    args = ap.parse_args()

    if not args.lf and not (args.start_date and args.end_date):
        ap.error("informe --lf, ou --start-date e --end-date (agregado por intervalo)")

    launches = load_launches()
    as_of = _coerce_date(args.as_of) if args.as_of else None
    as_of_eff = as_of or datetime.utcnow().date()

    lfs: list = []
    if args.lf and args.lf.lower() == "challenger":
        # padrão semanal: LFs do ledger com carrinho JÁ FECHADO (ciclo completo).
        covered = [k for k, v in launches.items()
                   if (_coerce_date(v.get("cap_end")) or date.min) >= LEDGER_START]
        covered.sort(key=lambda k: _coerce_date(launches[k].get("cap_end")) or date.min)
        if args.include_open_cart:
            lfs = covered
        else:
            lfs = [k for k in covered if _cart_closed(launches[k], as_of_eff)]
            skipped = [k for k in covered if k not in lfs]
            if skipped:
                print(f"[model_performance] fora do padrão (carrinho não fechou): {', '.join(skipped)}")
    elif args.lf:
        lfs = [x.strip() for x in args.lf.split(",") if x.strip()]

    registry = ModelRegistry()
    ledger_reader, sales_reader, coverage_reader, closer = _open_real_readers()
    coverage = coverage_reader()
    sales_max = coverage.get("overall")
    results = []
    try:
        if lfs and not args.aggregate_only:
            for lf in lfs:
                res = compute_lf_performance(
                    lf, ledger_reader=ledger_reader, sales_reader=sales_reader,
                    registry=registry, as_of_date=as_of, window_days=args.window_days,
                    launches=launches,
                )
                results.append(res)
                _print_result(res, sales_max)
                if args.persist:
                    print(f"      → persistido: {persist_lf_performance(res)}")
        if lfs and (args.aggregate or args.aggregate_only) and len(lfs) > 1:
            agg = compute_aggregate_performance(
                lfs, ledger_reader=ledger_reader, sales_reader=sales_reader,
                registry=registry, as_of_date=as_of, window_days=args.window_days,
                launches=launches,
            )
            results.append(agg)
            _print_result(agg, sales_max)
            if args.persist:
                print(f"      → persistido: {persist_lf_performance(agg)}")
        if args.start_date and args.end_date:
            rng = compute_range_performance(
                _coerce_date(args.start_date), _coerce_date(args.end_date),
                ledger_reader=ledger_reader, sales_reader=sales_reader,
                registry=registry, as_of_date=as_of, window_days=args.window_days,
            )
            results.append(rng)
            _print_result(rng, sales_max)
            if args.persist:
                print(f"      → persistido: {persist_lf_performance(rng)}")
    finally:
        closer()

    if (args.slack or args.slack_dry_run) and results:
        text = format_slack(results, results[0].as_of_date, args.window_days, coverage)
        print(f"\n[slack] {post_slack_dm(text, dry_run=args.slack_dry_run)}")


if __name__ == "__main__":
    main()
