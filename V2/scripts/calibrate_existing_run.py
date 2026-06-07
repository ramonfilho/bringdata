"""
[DT-20 Fase 2] Calibração pós-hoc de modelos atuais via run filho MLflow local.

Cada modelo já em produção (jan30, abr28) recebe um calibrador isotônico
ajustado sobre o test set ORIGINAL, salvo como artifact `calibrator.pkl` em
um run filho local em `V2/mlruns/1/{parent}-calibrated-isotonic/artifacts/`.

O run filho preserva o `model.pkl` bit-idêntico ao parent — só adiciona o
calibrador e thresholds recomputados em escala calibrada.

Duas fontes de pares (score, target) suportadas:

  1. **CSV salvo no treino** (`--source csv`): quando o train_pipeline original
     foi rodado com `--save-test-predictions`, salva o test set scoreado em
     `V2/files/{timestamp}/test_set_predictions.csv` com colunas
     `probabilidade` e `target_real`. Fonte preferida — usa os 33.152 leads
     do jan30 exatamente como ele os scoreou no dia do treino.

  2. **Matched_dataset filtrado pelo período** (`--source matched`): quando o
     CSV não existe (caso do abr28), filtra `matched_dataset.parquet` pela
     janela do test set do modelo (cut_date+1 a period_end) e roda
     `LeadScoringPipeline` com `predictor_override` do modelo. Aceita
     pequena divergência de volume pela diferença de filtro entre os dois
     momentos.

Uso típico:

    # jan30 — usa CSV salvo no treino (volume idêntico)
    python -m scripts.calibrate_existing_run \\
        --run-id d51757f5041c44b7ab1a056fce8c3c35 \\
        --source csv \\
        --csv-path V2/files/20260130_090227/test_set_predictions.csv

    # abr28 — re-scoreia leads do período via pipeline atual
    python -m scripts.calibrate_existing_run \\
        --run-id 5d158f0aa6e54b489498470446194a6c \\
        --source matched \\
        --matched-dataset V2/outputs/analysis/matched_dataset_2026-05-09.parquet

Output: novo diretório `V2/mlruns/1/{run-id}-calibrated-isotonic/artifacts/`
com `model/`, `feature_registry.json`, `calibrator.pkl` e `model_metadata.json`
(thresholds em escala calibrada + bloco `calibration` com ECE pré/pós).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT.parent))
sys.path.insert(0, str(PROJECT_ROOT))

from src.model.calibration import IsotonicCalibrator, SigmoidCalibrator, NoneCalibrator, make_calibrator

logger = logging.getLogger(__name__)


def ece(scores: np.ndarray, targets: np.ndarray, n_bins: int = 20) -> float:
    """Expected Calibration Error em N bins de score uniforme em quantil."""
    df = pd.DataFrame({"s": scores, "t": targets})
    df["bin"] = pd.qcut(df["s"], n_bins, duplicates="drop")
    g = df.groupby("bin", observed=True).agg(sm=("s", "mean"), tm=("t", "mean"), n=("s", "size"))
    return float((np.abs(g["sm"] - g["tm"]) * g["n"]).sum() / g["n"].sum())


def fit_from_csv(csv_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Lê o CSV `test_set_predictions.csv` salvo pelo train_pipeline."""
    df = pd.read_csv(csv_path)
    if "probabilidade" not in df.columns or "target_real" not in df.columns:
        raise ValueError(
            f"{csv_path} não tem as colunas esperadas (probabilidade, target_real). "
            f"Colunas encontradas: {list(df.columns)[:10]}..."
        )
    print(f"[csv] {len(df)} leads, {int(df['target_real'].sum())} conversões")
    return df["probabilidade"].values, df["target_real"].values


def fit_from_matched_dataset(matched_path: Path, run_id: str, meta: dict) -> tuple[np.ndarray, np.ndarray]:
    """Filtra matched_dataset pela janela do test set e roda predict_proba via pipeline."""
    from src.core.client_config import ABTestConfig
    from src.model.prediction import LeadScoringPredictor
    from src.production_pipeline import LeadScoringPipeline

    df = pd.read_parquet(matched_path)
    df["Data"] = pd.to_datetime(df["Data"])
    cut = pd.Timestamp(meta["training_data"]["temporal_split"]["cut_date"])
    end = pd.Timestamp(meta["training_data"]["temporal_split"]["period_end"])
    test = df[(df["Data"] > cut) & (df["Data"] <= end)].copy()
    print(f"[matched] {len(test)} leads, {int(test['target'].sum())} conversões na janela {cut.date()}..{end.date()}")

    test["converted"] = test["target"]
    csv_path = tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name
    test.drop(columns=["target"]).to_csv(csv_path, index=False)
    try:
        predictor = LeadScoringPredictor(mlflow_run_id=run_id, use_active_model=False)
        predictor.load_model()
        pipeline = LeadScoringPipeline(model_name=None, model_path=None, client_id="devclub")
        ab_cfg = ABTestConfig.from_active_model_yaml(PROJECT_ROOT / "configs/active_models/devclub.yaml")
        encoding_overrides = next((v.encoding_overrides for v in ab_cfg.variants.values() if v.run_id == run_id), None)
        scored = pipeline.run(
            filepath=csv_path,
            with_predictions=True,
            predictor_override=predictor,
            encoding_overrides=encoding_overrides,
            enforce_post_encoding=False,
        )
    finally:
        os.unlink(csv_path)

    if len(scored) != len(test):
        raise RuntimeError(f"Pipeline mudou tamanho: scored={len(scored)} vs test={len(test)}")
    merged = pd.DataFrame({
        "lead_score": scored["lead_score"].reset_index(drop=True).values,
        "target": test["target"].reset_index(drop=True).values,
    }).dropna()
    return merged["lead_score"].values, merged["target"].values


def write_child_run(parent_run_id: str, calibrator, scores_cal: np.ndarray,
                    metrics: dict, mlruns_root: Path) -> Path:
    """Cria diretório `V2/mlruns/1/{parent}-calibrated-{method}/artifacts/` e
    popula com cópia do parent + calibrator + thresholds recomputados + metadata."""
    child_dir = mlruns_root / f"{parent_run_id}-calibrated-{calibrator.method}"
    dst = child_dir / "artifacts"
    src = mlruns_root / parent_run_id / "artifacts"
    dst.mkdir(parents=True, exist_ok=True)

    # Copia model + feature_registry + qualquer artifact extra (categorias, distribuicoes)
    shutil.copytree(src / "model", dst / "model", dirs_exist_ok=True)
    for fname in ("feature_registry.json", "categorias_esperadas.json", "distribuicoes_esperadas.json"):
        if (src / fname).exists():
            shutil.copy(src / fname, dst / fname)

    calibrator.save(dst / "calibrator.pkl")

    # Thresholds recomputados em escala calibrada (percentil)
    quantis = np.percentile(scores_cal, [10, 20, 30, 40, 50, 60, 70, 80, 90])
    thresholds: dict[str, dict] = {}
    prev = 0.0
    for i, q in enumerate(list(quantis) + [scores_cal.max() + 1e-9], 1):
        mask = (scores_cal >= prev) & (scores_cal < q) if i < 10 else (scores_cal >= prev)
        n = int(mask.sum())
        thresholds[f"D{i}"] = {
            "threshold_min": float(prev),
            "threshold_max": float(q) if i < 10 else float(scores_cal.max()),
            "count": n,
            "mean_probability": float(scores_cal[mask].mean()) if n else 0.0,
            "std_probability": float(scores_cal[mask].std()) if n else 0.0,
        }
        prev = q

    meta = json.loads((src / "model_metadata.json").read_text())
    meta["decil_thresholds"] = {
        **meta.get("decil_thresholds", {}),
        "method": "percentile_on_calibrated_scores",
        "calculated_at": metrics["fitted_at"],
        "thresholds": thresholds,
        "usage_notes": (
            "Thresholds em escala calibrada (DT-20 Fase 2). "
            "Aplicar IsotonicCalibrator (carregado pelo LeadScoringPredictor) "
            "antes de atribuir_decis_batch — `predict_proba` já devolve calibrado."
        ),
    }
    meta["calibration"] = metrics
    (dst / "model_metadata.json").write_text(json.dumps(meta, indent=2, default=str))

    return child_dir


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True, help="MLflow run_id do modelo a calibrar (parent)")
    ap.add_argument("--method", default="isotonic", choices=["isotonic", "sigmoid"],
                    help="Estratégia de calibração (default: isotonic)")
    ap.add_argument("--source", required=True, choices=["csv", "matched"],
                    help="csv = test_set_predictions.csv salvo no treino; "
                         "matched = filtra matched_dataset pela janela do test set")
    ap.add_argument("--csv-path", help="Caminho do CSV (--source csv)")
    ap.add_argument("--matched-dataset", help="Caminho do matched_dataset.parquet (--source matched)")
    ap.add_argument("--mlruns-root", default=str(PROJECT_ROOT / "mlruns/1"),
                    help="Raiz dos runs MLflow locais (default: V2/mlruns/1)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    mlruns_root = Path(args.mlruns_root)

    # Metadata do parent (pra recuperar janela do test set + reportar contexto)
    meta_path = mlruns_root / args.run_id / "artifacts/model_metadata.json"
    if not meta_path.exists():
        print(f"[ERRO] metadata não encontrada: {meta_path}", file=sys.stderr)
        return 2
    parent_meta = json.loads(meta_path.read_text())

    # Carrega pares (score, target)
    if args.source == "csv":
        if not args.csv_path:
            print("[ERRO] --csv-path obrigatório com --source csv", file=sys.stderr)
            return 2
        scores, targets = fit_from_csv(Path(args.csv_path))
        source_desc = f"CSV: {args.csv_path}"
    else:
        if not args.matched_dataset:
            print("[ERRO] --matched-dataset obrigatório com --source matched", file=sys.stderr)
            return 2
        scores, targets = fit_from_matched_dataset(Path(args.matched_dataset), args.run_id, parent_meta)
        source_desc = f"matched_dataset: {args.matched_dataset}"

    if len(scores) == 0:
        print("[ERRO] zero pares (score, target) obtidos", file=sys.stderr)
        return 2

    # Fitta calibrador
    cal = make_calibrator(args.method)
    cal.fit(scores, targets)
    scores_cal = cal.transform(scores)

    ece_pre_pp = ece(scores, targets) * 100
    ece_post_pp = ece(scores_cal, targets) * 100

    print(f"\nFonte: {source_desc}")
    print(f"Volume: {len(scores)} leads, {int(targets.sum())} conversões")
    print(f"Score bruto:    min={scores.min():.4f}  max={scores.max():.4f}  mean={scores.mean():.4f}")
    print(f"Score calibr.:  min={scores_cal.min():.4f}  max={scores_cal.max():.4f}  mean={scores_cal.mean():.4f}")
    print(f"ECE pré:  {ece_pre_pp:.2f} pp")
    print(f"ECE pós:  {ece_post_pp:.2f} pp (in-sample, mecânico)")
    print(f"Score calibrado médio = taxa real observada: {scores_cal.mean():.4f} = {targets.mean():.4f} → bate" if
          abs(scores_cal.mean() - targets.mean()) < 0.001 else
          f"AVISO: score calibrado médio ({scores_cal.mean():.4f}) ≠ taxa real ({targets.mean():.4f})")

    metrics = {
        "method": cal.method,
        "fitted_at": "2026-06-07",
        "parent_run_id": args.run_id,
        "fit_source": source_desc,
        "n_calibration_leads": int(len(scores)),
        "n_calibration_positives": int(targets.sum()),
        "ece_pre_pp": ece_pre_pp,
        "ece_post_in_sample_pp": ece_post_pp,
    }

    child_dir = write_child_run(args.run_id, cal, scores_cal, metrics, mlruns_root)
    print(f"\nRun filho local: {child_dir}")
    print(f"Para usar em produção, apontar `active_models/devclub.yaml.active_model.mlflow_run_id` "
          f"para `{args.run_id}-calibrated-{cal.method}` após validação out-of-sample (Fase 3).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
