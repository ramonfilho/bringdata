#!/usr/bin/env python3
"""
backtest_compare_models.py — Backtest comparativo entre 2+ modelos de
lead scoring sobre o mesmo dataset de um lançamento.

Reusa src/validation/backtest_data.load_match_spend_for_lf para a parte de
"carrega leads + vendas + match + spend imputado", garantindo paridade com
validate_ml_performance.py.

Fluxo em três fases:

  FASE A — `--mode prepare-dataset` (rodar 1x na worktree main):
    - Chama src.validation.backtest_data.load_match_spend_for_lf
    - Salva base_dataset.parquet com leads + match + spend

  FASE B — `--mode score` (rodar 1x por worktree/modelo):
    - Lê base_dataset.parquet
    - Carrega model.pkl + decil_thresholds do MLflow run_id
    - Roda preprocess + predict via LeadScoringPipeline
    - Aplica thresholds salvos no MLflow (Opção B — calibração de produção)
    - Salva scored_<label>.parquet

  FASE C — `--mode compare` (rodar 1x na worktree main):
    - Lê scored_<label>.parquet de cada modelo
    - Merge por email
    - Calcula métricas comparativas (lift D10, top-30/50, ROAS)
    - Emite XLSX com múltiplas abas

Exemplo:

    # A — preparar dataset (worktree main)
    python V2/scripts/backtest_compare_models.py --mode prepare-dataset \\
        --lf LF52 --output V2/files/validation/backtest_lf52/base_dataset.parquet

    # B — score com v4 (worktree main)
    python V2/scripts/backtest_compare_models.py --mode score \\
        --label v4 --run-id 60637bb98b94421b9c7579bb4ac1b1ad \\
        --base-dataset V2/files/validation/backtest_lf52/base_dataset.parquet \\
        --output V2/files/validation/backtest_lf52/scored_v4.parquet

    # B' — score com jan30 (rollback worktree)
    cd ../smart_ads_v2_rollback
    python V2/scripts/backtest_compare_models.py --mode score \\
        --label jan30 --run-id d51757f5041c44b7ab1a056fce8c3c35 \\
        --base-dataset ../bring_data_validation_refactor/V2/files/validation/backtest_lf52/base_dataset.parquet \\
        --output ../bring_data_validation_refactor/V2/files/validation/backtest_lf52/scored_jan30.parquet

    # C — comparar (worktree main)
    python V2/scripts/backtest_compare_models.py --mode compare \\
        --labels v4 jan30 \\
        --input-dir V2/files/validation/backtest_lf52/ \\
        --output V2/files/validation/backtest_lf52/backtest.xlsx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # V2/
DECIL_LABELS = [f"D{i:02d}" for i in range(1, 11)]
TOP30_DECILS = ["D08", "D09", "D10"]
TOP50_DECILS = ["D06", "D07", "D08", "D09", "D10"]


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()


# --------------------------------------------------------------------------- #
# Modo PREPARE-DATASET
# --------------------------------------------------------------------------- #

def run_prepare_mode(args) -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.validation.backtest_data import load_match_spend_for_lf

    df = load_match_spend_for_lf(args.lf, output_path=args.output)
    print(f"[prepare] ✅ {len(df)} leads, {df['converted'].sum()} conversões → {args.output}")


# --------------------------------------------------------------------------- #
# Modo SCORE
# --------------------------------------------------------------------------- #

def run_score_mode(args) -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.production_pipeline import LeadScoringPipeline
    from src.model.prediction import LeadScoringPredictor

    base = pd.read_parquet(args.base_dataset)
    print(f"[score] {len(base)} leads do base_dataset, {base['converted'].sum()} conversões")

    # IMPORTANTE: LeadScoringPipeline com use_active_model=True (default) ignora
    # model_path/run_id passados — sempre carrega o active_model.yaml. Para
    # forçar um run_id específico, criar LeadScoringPredictor com mlflow_run_id
    # explícito e passar como predictor_override no pipeline.run().
    predictor = LeadScoringPredictor(mlflow_run_id=args.run_id, use_active_model=False)
    predictor.load_model()
    print(f"[score] predictor carregado para run_id={args.run_id}")

    pipeline = LeadScoringPipeline(model_name=None, model_path=None, client_id="devclub")
    scored = _score_via_pipeline(pipeline, base, predictor_override=predictor)

    thresholds = _load_decil_thresholds(args.run_id, args.mlruns_root)
    scored["decil"] = scored["lead_score"].apply(
        lambda s: _score_to_decil(s, thresholds) if pd.notna(s) else None
    )

    keep = [
        "email", "campaign", "lead_score", "decil",
        "converted", "sale_value", "sale_origin", "match_method",
        "spend_imputado",
    ]
    keep = [c for c in keep if c in scored.columns]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    scored[keep].to_parquet(out, index=False)
    print(f"[score] ✅ {args.label}: {len(scored)} linhas → {out}")
    print(f"[score]   distribuição decis: {scored['decil'].value_counts().to_dict()}")


def _score_via_pipeline(pipeline, base: pd.DataFrame, predictor_override=None) -> pd.DataFrame:
    """preprocess+predict via xlsx temporário, opcionalmente forçando o predictor."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        base.to_excel(tmp_path, index=False)
        scored = pipeline.run(
            filepath=tmp_path,
            with_predictions=True,
            predictor_override=predictor_override,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if "lead_score" not in scored.columns:
        for alt in ("probability", "score", "prediction_proba"):
            if alt in scored.columns:
                scored["lead_score"] = scored[alt]
                break
        else:
            raise RuntimeError(f"Score não encontrado. Cols: {list(scored.columns)[:20]}")

    if "email" not in scored.columns:
        n = min(len(scored), len(base))
        scored = scored.iloc[:n].reset_index(drop=True)
        scored["email"] = base["email"].iloc[:n].values

    # Recolar match data do base (o preprocess pode ter dropado essas cols)
    match_cols = ["converted", "sale_value", "sale_origin", "match_method", "spend_imputado", "campaign"]
    base_lookup = base[["email"] + [c for c in match_cols if c in base.columns]].drop_duplicates("email")
    scored = scored.merge(base_lookup, on="email", how="left", suffixes=("", "_base"))
    for c in match_cols:
        c_base = f"{c}_base"
        if c_base in scored.columns:
            scored[c] = scored[c_base]
            scored = scored.drop(columns=[c_base])
    return scored


def _resolve_artifacts_dir(run_id: str, mlruns_root: Path) -> Path:
    cands = list(mlruns_root.rglob(f"*/{run_id}/artifacts"))
    if not cands:
        raise FileNotFoundError(f"Artifacts não encontrados para {run_id}")
    return cands[0]


def _load_decil_thresholds(run_id: str, mlruns_root: Path) -> List[Tuple[str, float]]:
    cands = list(mlruns_root.rglob(f"*/{run_id}/artifacts/model_metadata.json"))
    if not cands:
        raise FileNotFoundError(f"model_metadata.json não encontrado para {run_id}")
    meta = json.loads(cands[0].read_text())
    raw = meta["decil_thresholds"]["thresholds"]
    items = sorted(raw.items(), key=lambda kv: kv[1]["threshold_min"])
    return [(f"D{int(label.lstrip('D')):02d}", float(info["threshold_min"]))
            for label, info in items]


def _score_to_decil(score: float, thresholds: List[Tuple[str, float]]) -> str:
    decil = thresholds[0][0]
    for label, t_min in thresholds:
        if score >= t_min:
            decil = label
        else:
            break
    return decil


# --------------------------------------------------------------------------- #
# Modo COMPARE
# --------------------------------------------------------------------------- #

def run_compare_mode(args) -> None:
    in_dir = Path(args.input_dir)
    parquets = {
        label: pd.read_parquet(in_dir / f"scored_{label}.parquet")
        for label in args.labels
    }
    for label, df in parquets.items():
        print(f"[compare] {label}: {len(df)} leads, {df['converted'].sum()} conv, "
              f"{df['spend_imputado'].notna().sum()} com spend")

    # Dedup por email — base_dataset pode ter ~100 emails duplicados (ex: lead que
    # respondeu duas pesquisas). Sem dedup, merge inner faz produto cartesiano e
    # explode o n.
    base_label = args.labels[0]
    merged = parquets[base_label][
        ["email", "decil", "converted", "sale_value", "spend_imputado"]
    ].drop_duplicates("email").rename(columns={"decil": f"decil_{base_label}"})
    for label in args.labels[1:]:
        df_l = parquets[label][["email", "decil"]].drop_duplicates("email") \
            .rename(columns={"decil": f"decil_{label}"})
        merged = merged.merge(df_l, on="email", how="inner")
    print(f"[compare] após merge (dedup por email): {len(merged)} leads em comum")

    decile_tables = {label: _decile_table(merged, f"decil_{label}") for label in args.labels}
    summary = _summary_table(merged, args.labels)

    cross = pd.DataFrame()
    if len(args.labels) == 2:
        a, b = args.labels
        cross = pd.crosstab(
            merged[f"decil_{a}"], merged[f"decil_{b}"],
            margins=True, margins_name="Total",
        ).reindex(DECIL_LABELS + ["Total"], fill_value=0) \
         .reindex(columns=DECIL_LABELS + ["Total"], fill_value=0)

    params = pd.DataFrame([
        {"key": "labels", "value": ", ".join(args.labels)},
        {"key": "n_leads_merged", "value": len(merged)},
        {"key": "n_conversions", "value": int(merged["converted"].sum())},
        {"key": "total_revenue", "value": float(merged["sale_value"].sum())},
        {"key": "total_spend",
         "value": float(merged["spend_imputado"].dropna().sum())
                  if "spend_imputado" in merged.columns else 0.0},
        {"key": "ressalva_1",
         "value": "Viés de seleção: leads capturados pelo Meta otimizando para o sinal do baseline."},
        {"key": "ressalva_2",
         "value": "Spend imputado: rateado por campanha (CPL=spend/n_leads) — não é spend observado por lead."},
        {"key": "ressalva_3",
         "value": "ROAS aqui é offline/contrafactual — não é o ROAS produzido por decisão online do Meta."},
    ])

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="summary", index=True)
        for label, tab in decile_tables.items():
            tab.to_excel(writer, sheet_name=f"decile_{label}", index=True)
        if not cross.empty:
            cross.to_excel(writer, sheet_name="cross_tab", index=True)
        params.to_excel(writer, sheet_name="params", index=False)
    print(f"[compare] ✅ XLSX → {out}")


def _decile_table(df: pd.DataFrame, decil_col: str) -> pd.DataFrame:
    g = df.groupby(decil_col).agg(
        leads=("email", "count"),
        conversions=("converted", "sum"),
        revenue=("sale_value", "sum"),
        spend=("spend_imputado", lambda x: x.dropna().sum()),
    )
    g["conv_pct"] = g["conversions"] / g["leads"]
    g["roas"] = np.where(g["spend"] > 0, g["revenue"] / g["spend"], np.nan)
    overall = df["converted"].sum() / len(df) if len(df) > 0 else 0
    g["lift"] = g["conv_pct"] / overall if overall > 0 else np.nan
    g["leads_pct"] = g["leads"] / g["leads"].sum() if g["leads"].sum() > 0 else np.nan
    return g.reindex(DECIL_LABELS, fill_value=0).round(4)


def _summary_table(merged: pd.DataFrame, labels: List[str]) -> pd.DataFrame:
    rows: Dict[str, Dict] = {}
    total_leads = len(merged)
    total_conv = int(merged["converted"].sum())
    total_revenue = float(merged["sale_value"].sum())
    total_spend = (float(merged["spend_imputado"].dropna().sum())
                   if "spend_imputado" in merged.columns else 0.0)
    baseline_conv = total_conv / total_leads if total_leads else 0

    def safe_div(num, den):
        return (num / den) if den and den > 0 else np.nan

    for label in labels:
        col = f"decil_{label}"
        d10 = merged[merged[col] == "D10"]
        top30 = merged[merged[col].isin(TOP30_DECILS)]
        top50 = merged[merged[col].isin(TOP50_DECILS)]

        rows[label] = {
            "leads_total": total_leads,
            "conv_total": total_conv,
            "conv_pct_global": round(baseline_conv, 4),
            "leads_d10": len(d10),
            "leads_d10_pct": round(len(d10) / total_leads, 4) if total_leads else np.nan,
            "conv_d10": int(d10["converted"].sum()),
            "conv_pct_d10": round(safe_div(d10["converted"].sum(), len(d10)), 4),
            "lift_d10": round(safe_div(safe_div(d10["converted"].sum(), len(d10)), baseline_conv), 4),
            "leads_top30_pct": round(len(top30) / total_leads, 4) if total_leads else np.nan,
            "conv_concentracao_top30": round(safe_div(top30["converted"].sum(), total_conv), 4),
            "roas_top30": round(safe_div(top30["sale_value"].sum(),
                                          top30["spend_imputado"].dropna().sum()), 4),
            "leads_top50_pct": round(len(top50) / total_leads, 4) if total_leads else np.nan,
            "conv_concentracao_top50": round(safe_div(top50["converted"].sum(), total_conv), 4),
            "roas_top50": round(safe_div(top50["sale_value"].sum(),
                                          top50["spend_imputado"].dropna().sum()), 4),
            "roas_global": round(safe_div(total_revenue, total_spend), 4),
        }
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--mode", choices=["prepare-dataset", "score", "compare"], required=True)
    ap.add_argument("--lf", type=str, help="LF (ex: LF52) — modo prepare-dataset")
    ap.add_argument("--label", type=str, help="Label do modelo — modo score")
    ap.add_argument("--run-id", type=str, help="MLflow run_id — modo score")
    ap.add_argument("--base-dataset", type=Path, help="base_dataset.parquet — modo score")
    ap.add_argument("--mlruns-root", type=Path, default=PROJECT_ROOT / "mlruns")
    ap.add_argument("--labels", nargs="+", help="Labels a comparar — modo compare")
    ap.add_argument("--input-dir", type=Path, help="Dir com scored_<label>.parquet — modo compare")
    ap.add_argument("--output", type=Path, help="Caminho do output (parquet ou xlsx)")

    args = ap.parse_args()

    def require(*names):
        missing = [n for n in names if getattr(args, n.replace("-", "_")) is None]
        if missing:
            ap.error(f"--{' --'.join(missing)} obrigatório(s) no modo {args.mode}")

    if args.mode == "prepare-dataset":
        require("lf", "output")
        run_prepare_mode(args)
    elif args.mode == "score":
        require("label", "run-id", "base-dataset", "output")
        run_score_mode(args)
    else:
        require("labels", "input-dir", "output")
        run_compare_mode(args)


if __name__ == "__main__":
    main()
