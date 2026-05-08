"""
rules_vs_rf.py — Quantifica o moat do RF vs baselines "gestor de tráfego".

Pergunta: quanto do valor entregue pelo Champion v4 (RandomForest) pode ser
reproduzido por modelos que um gestor de tráfego competente conseguiria
montar sem pipeline de dados sofisticado?

Baselines em complexidade crescente:
  1. napkin_rules        — top-5 conceitos, pesos inteiros intuitivos
                           (representa: gestor sem acesso à importância do RF)
  2. importance_weighted — top-5 conceitos, pesos proporcionais ao
                           feature_importances_ do Champion v4
                           (representa: gestor com acesso ao output do RF)
  3. shallow_tree        — DecisionTreeClassifier max_depth=3
                           (representa: teto de regras automáticas descobertas)

Referência: champion_v4_rf — RandomForest re-treinado no MESMO split
(hiperparâmetros de configs/clients/devclub.yaml, replica o Champion).

Métricas reportadas (comparáveis às do model_metadata do Champion v4):
  - AUC-ROC, AUC-PR
  - D10 concentração de conversões (%), D10 lift
  - top3/top5 decil concentration
  - Monotonia (% dos pares de decis em ordem crescente de conversão)
  - Unique score values (proxy de calibração — alta granularidade = decis balanceáveis)

Pré-requisito: dataset encoded com coluna __Data__.
  python -m src.train_pipeline --save-encoded --initial-matching email_telefone

Uso:
  python -m src.experiments.rules_vs_rf
  python -m src.experiments.rules_vs_rf --cut-date 2026-03-01 --mlflow-log
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.tree import DecisionTreeClassifier, export_text

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("rules_vs_rf")


# ---------------------------------------------------------------------------
# Config de baselines — derivada da feature_importance do Champion v4
# ---------------------------------------------------------------------------

# Top-5 conceitos do Champion v4 (ver mlruns/1/60637bb9.../feature_registry.json)
# Pesos napkin: inteiros pequenos, intuitivos.
# Pesos importance-weighted: proporcionais ao feature_importances_ (rank × 100).
NAPKIN_WEIGHTS = {
    "Voc_possui_cart_o_de_cr_dito_sim": 3.0,
    "J_estudou_programa_o_Sim": 2.0,
    "Tem_computador_notebook_sim": 2.0,
    "Source_facebook_ads": 1.0,
    "O_que_mais_voc_quer_ver_no_evento_fazer_transicao_de_carreira_e_conseguir_meu_primeiro_emprego_na_area": 1.0,
}

# Importâncias do Champion v4 (fonte: feature_registry.json → top_10_features)
IMPORTANCE_WEIGHTS = {
    "Voc_possui_cart_o_de_cr_dito_sim": 0.1637,
    "Voc_possui_cart_o_de_cr_dito_nao": -0.1516,
    "Tem_computador_notebook_nao": -0.0580,
    "J_estudou_programa_o_Sim": 0.0529,
    "J_estudou_programa_o_N_o": -0.0466,
    "Source_facebook_ads": 0.0236,
    "Tem_computador_notebook_sim": 0.0224,
    "O_que_mais_voc_quer_ver_no_evento_fazer_transicao_de_carreira_e_conseguir_meu_primeiro_emprego_na_area": 0.0195,
}


# ---------------------------------------------------------------------------
# Dataset loading & split
# ---------------------------------------------------------------------------

def load_dataset(path: Path) -> pd.DataFrame:
    """Carrega dataset encoded com __Data__ e target (produzido por train_pipeline --save-encoded)."""
    if not path.exists():
        logger.error(f"Dataset não encontrado: {path}")
        logger.error("Rode primeiro: python -m src.train_pipeline --save-encoded --initial-matching email_telefone")
        sys.exit(1)
    df = pd.read_parquet(path)
    required = {"target", "__Data__"}
    missing = required - set(df.columns)
    if missing:
        logger.error(f"Dataset inválido — colunas ausentes: {missing}. Regere com --save-encoded.")
        sys.exit(1)
    df["__Data__"] = pd.to_datetime(df["__Data__"], errors="coerce")
    df = df.dropna(subset=["__Data__"]).reset_index(drop=True)
    logger.info(f"Dataset: {len(df):,} leads | range: {df['__Data__'].min().date()} → {df['__Data__'].max().date()} | target rate: {df['target'].mean()*100:.3f}%")
    return df


def temporal_leads_split(df: pd.DataFrame, cut_date: str = "2026-03-01") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Replica split_method='temporal_leads' do training_model.py:446-466.
    70% mais antigos para treino, 30% mais recentes para teste.
    Se cut_date informado, usa como âncora; senão, percentil 70% por data."""
    df_sorted = df.sort_values("__Data__").reset_index(drop=True)
    if cut_date:
        mask_train = df_sorted["__Data__"] < pd.Timestamp(cut_date)
    else:
        cut_idx = int(len(df_sorted) * 0.7)
        mask_train = np.arange(len(df_sorted)) < cut_idx
    train, test = df_sorted[mask_train], df_sorted[~mask_train]
    logger.info(f"Split temporal: train {len(train):,} ({train['target'].mean()*100:.3f}%) | test {len(test):,} ({test['target'].mean()*100:.3f}%)")
    return train, test


def drop_metadata_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Remove colunas __Data__, __email__, target — deixa só features."""
    meta = [c for c in df.columns if c.startswith("__") or c == "target"]
    return df.drop(columns=meta)


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

def fit_napkin_rules(X_train: pd.DataFrame, y_train: pd.Series) -> Callable[[pd.DataFrame], np.ndarray]:
    """Regras chutadas por gestor de tráfego — não olha y_train."""
    def score(X: pd.DataFrame) -> np.ndarray:
        s = np.zeros(len(X), dtype=float)
        for feat, w in NAPKIN_WEIGHTS.items():
            if feat in X.columns:
                s += w * X[feat].astype(float).values
            else:
                logger.warning(f"  [napkin] feature ausente: {feat}")
        return s
    return score


def fit_importance_weighted(X_train: pd.DataFrame, y_train: pd.Series) -> Callable[[pd.DataFrame], np.ndarray]:
    """Score linear com pesos do feature_importances_ do Champion v4."""
    def score(X: pd.DataFrame) -> np.ndarray:
        s = np.zeros(len(X), dtype=float)
        for feat, w in IMPORTANCE_WEIGHTS.items():
            if feat in X.columns:
                s += w * X[feat].astype(float).values
        return s
    return score


def fit_shallow_tree(X_train: pd.DataFrame, y_train: pd.Series) -> Tuple[Callable[[pd.DataFrame], np.ndarray], str]:
    """DecisionTree max_depth=3 com class_weight balanced — regras automáticas."""
    tree = DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=42)
    tree.fit(X_train, y_train)
    rules_text = export_text(tree, feature_names=list(X_train.columns), max_depth=3)
    def score(X: pd.DataFrame) -> np.ndarray:
        return tree.predict_proba(X)[:, 1]
    return score, rules_text


def fit_conversion_rate_score(X_train: pd.DataFrame, y_train: pd.Series, min_count: int = 100) -> Tuple[Callable[[pd.DataFrame], np.ndarray], Dict[str, float]]:
    """Weight-of-Evidence aditivo — gestor calcula P(buy|feature=1) - base_rate para cada OHE.
    Não depende da feature_importance do RF. Única entrada: tabela lead → comprou/não."""
    base_rate = float(y_train.mean())
    weights: Dict[str, float] = {}
    y_arr = np.asarray(y_train)
    for col in X_train.columns:
        v = X_train[col].values
        # aceitar só features OHE/binárias — ignorar numéricas contínuas que não têm P(buy|=1)
        if not np.isin(np.unique(v[~pd.isna(v)])[:5], [0, 1]).all():
            continue
        mask = v == 1
        n = int(mask.sum())
        if n < min_count:
            continue
        p_buy = float(y_arr[mask].mean())
        weights[col] = p_buy - base_rate  # "lift absoluto" — positivo = melhor que média
    def score(X: pd.DataFrame) -> np.ndarray:
        s = np.zeros(len(X), dtype=float)
        for feat, w in weights.items():
            if feat in X.columns:
                s += w * X[feat].astype(float).values
        return s
    return score, weights


def fit_champion_v4_rf(X_train: pd.DataFrame, y_train: pd.Series) -> Callable[[pd.DataFrame], np.ndarray]:
    """RandomForest com hiperparâmetros do Champion v4 — referência."""
    rf = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_split=2,
        min_samples_leaf=1,
        max_features="sqrt",
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)
    def score(X: pd.DataFrame) -> np.ndarray:
        return rf.predict_proba(X)[:, 1]
    return score


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def eval_model(y_true: np.ndarray, y_score: np.ndarray, name: str) -> Dict[str, float]:
    """Calcula métricas comparáveis ao model_metadata do Champion v4."""
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score, dtype=float)
    # Rank-based — tolera scores com poucos valores únicos (rules)
    rank = pd.Series(y_score).rank(method="average").values
    # Decis por qcut sobre rank → garante 10 bins mesmo com empates massivos
    try:
        decis = pd.qcut(rank, q=10, labels=[f"D{i:02d}" for i in range(1, 11)], duplicates="drop")
    except Exception:
        decis = pd.cut(rank, bins=10, labels=[f"D{i:02d}" for i in range(1, 11)])
    decis = decis.astype(str)
    df = pd.DataFrame({"y": y_true, "decil": decis})
    by_decil = df.groupby("decil", observed=True)["y"].agg(["sum", "count", "mean"]).reset_index()
    by_decil = by_decil.sort_values("decil")
    total_conv = by_decil["sum"].sum()
    base_rate = y_true.mean()
    d10 = by_decil[by_decil["decil"] == "D10"]
    d10_conc = 100.0 * d10["sum"].iloc[0] / total_conv if total_conv > 0 and len(d10) else 0.0
    d10_lift = d10["mean"].iloc[0] / base_rate if base_rate > 0 and len(d10) else 0.0
    top3 = 100.0 * by_decil.tail(3)["sum"].sum() / total_conv if total_conv > 0 else 0.0
    top5 = 100.0 * by_decil.tail(5)["sum"].sum() / total_conv if total_conv > 0 else 0.0
    # Monotonia: % de pares consecutivos (D_i, D_{i+1}) em ordem crescente de conv_rate
    rates = by_decil["mean"].values
    pairs = len(rates) - 1
    monotonic = sum(1 for i in range(pairs) if rates[i] <= rates[i + 1])
    monotonia_pct = 100.0 * monotonic / pairs if pairs else 0.0
    lift_max = (rates.max() / base_rate) if base_rate > 0 else 0.0
    auc = roc_auc_score(y_true, y_score) if len(np.unique(y_true)) > 1 else float("nan")
    auc_pr = average_precision_score(y_true, y_score) if len(np.unique(y_true)) > 1 else float("nan")
    return {
        "model": name,
        "auc": round(auc, 4),
        "auc_pr": round(auc_pr, 4),
        "d10_conc_pct": round(d10_conc, 2),
        "d10_lift": round(d10_lift, 2),
        "top3_conc_pct": round(top3, 2),
        "top5_conc_pct": round(top5, 2),
        "monotonia_pct": round(monotonia_pct, 2),
        "lift_max": round(lift_max, 2),
        "unique_scores": int(len(np.unique(y_score))),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_napkin_from_run(run_id: str, top_n: int = 5) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Deriva NAPKIN_WEIGHTS e IMPORTANCE_WEIGHTS de feature_registry.json do run.
    Napkin = pesos inteiros 5,4,3,2,1 nas top-N features.
    Importance-weighted = importance values diretos."""
    repo_root = Path(__file__).resolve().parents[2]
    fr_path = repo_root / "mlruns" / "1" / run_id / "artifacts" / "feature_registry.json"
    if not fr_path.exists():
        raise FileNotFoundError(f"feature_registry não encontrado para run {run_id}: {fr_path}")
    with open(fr_path) as f:
        fr = json.load(f)
    top = fr.get("feature_importance", {}).get("top_10_features", [])[:top_n]
    napkin = {row["feature_clean"]: float(top_n - i) for i, row in enumerate(top)}  # 5,4,3,2,1
    importance = {row["feature_clean"]: row["importance"] for row in top}
    return napkin, importance


def load_run_meta(run_id: str) -> Dict:
    """Carrega hyperparams + cut_date do model_metadata.json local."""
    repo_root = Path(__file__).resolve().parents[2]
    mm_path = repo_root / "mlruns" / "1" / run_id / "artifacts" / "model_metadata.json"
    if not mm_path.exists():
        return {}
    with open(mm_path) as f:
        return json.load(f)


def main():
    import json as _json
    p = argparse.ArgumentParser(description="Rules vs RF — moat do modelo de lead scoring.")
    p.add_argument("--dataset", default=None, help="Path para parquet encoded (default: V2/compare_encoded.parquet)")
    p.add_argument("--cut-date", default=None, help="Data de corte temporal (default: usa cut_date do --reference-run, ou 2026-03-01)")
    p.add_argument("--reference-run", default=None, help="MLflow run_id de referência. Se informado, deriva NAPKIN/IMPORTANCE weights, hyperparams e cut_date dele. Default: usa pesos hardcoded do Champion v4.")
    p.add_argument("--mlflow-log", action="store_true", help="Loga métricas na experiment baselines_vs_champion_v4 do MLflow remoto")
    p.add_argument("--out", default=None, help="CSV de saída (default: stdout)")
    args = p.parse_args()

    # Permite parametrizar referência via --reference-run
    global NAPKIN_WEIGHTS, IMPORTANCE_WEIGHTS
    ref_label = "champion_v4_hardcoded"
    cut_date = args.cut_date or "2026-03-01"
    if args.reference_run:
        NAPKIN_WEIGHTS, IMPORTANCE_WEIGHTS = load_napkin_from_run(args.reference_run)
        meta = load_run_meta(args.reference_run)
        if not args.cut_date:
            cd = meta.get("training_data", {}).get("temporal_split", {}).get("cut_date")
            if cd:
                cut_date = cd
        ref_label = f"run_{args.reference_run[:8]}"
        logger.info(f"Reference: {args.reference_run} (cut_date={cut_date})")
        logger.info(f"  NAPKIN top-{len(NAPKIN_WEIGHTS)}: {list(NAPKIN_WEIGHTS.keys())}")

    repo_root = Path(__file__).resolve().parents[2]
    dataset_path = Path(args.dataset) if args.dataset else repo_root / "compare_encoded.parquet"

    df = load_dataset(dataset_path)
    train, test = temporal_leads_split(df, cut_date=cut_date)
    X_train, y_train = drop_metadata_cols(train), train["target"].values
    X_test, y_test = drop_metadata_cols(test), test["target"].values

    # Fail-loud: se os nomes de feature dos baselines não batem com o parquet,
    # o resultado dos baselines será spurious (AUC = 0.5). Abortar com mensagem clara.
    expected = set(NAPKIN_WEIGHTS) | set(IMPORTANCE_WEIGHTS)
    present = expected & set(X_train.columns)
    if len(present) < len(expected) // 2:
        logger.error("")
        logger.error(f"[PARIDADE] Dataset tem nomes de coluna incompatíveis com os baselines.")
        logger.error(f"  Esperado (exemplo): {sorted(expected)[:3]}")
        logger.error(f"  Encontrado (exemplo): {[c for c in X_train.columns if 'estudou' in c.lower() or 'cart' in c.lower() or 'comput' in c.lower()][:5]}")
        logger.error(f"  Matches: {len(present)}/{len(expected)} features")
        logger.error(f"  Ação: regere o dataset com `python -m src.train_pipeline --save-encoded --initial-matching email_telefone`")
        logger.error(f"  (o pipeline atual sanitiza nomes via clean_column_names em core/encoding.py)")
        sys.exit(2)

    logger.info("")
    logger.info(f"Treinando {len(X_train.columns)} features × {len(X_train)} leads...")
    logger.info("")

    models: List[Tuple[str, Callable]] = []

    logger.info("[1/4] napkin_rules (regras chutadas por gestor)...")
    models.append(("napkin_rules", fit_napkin_rules(X_train, y_train)))

    logger.info("[2/4] importance_weighted (regras com pesos do RF)...")
    models.append(("importance_weighted", fit_importance_weighted(X_train, y_train)))

    logger.info("[3/5] shallow_tree (DecisionTree max_depth=3)...")
    tree_score, tree_rules = fit_shallow_tree(X_train, y_train)
    models.append(("shallow_tree", tree_score))

    logger.info("[4/5] conversion_rate_score (taxa de conversão por categoria, sem RF)...")
    cr_score, cr_weights = fit_conversion_rate_score(X_train, pd.Series(y_train))
    models.append(("conversion_rate_score", cr_score))

    logger.info(f"[5/5] reference_rf ({ref_label}) — RandomForest 300 árvores...")
    models.append((f"reference_rf_{ref_label}", fit_champion_v4_rf(X_train, y_train)))

    rows = [eval_model(y_test, scorer(X_test), name) for name, scorer in models]
    df_out = pd.DataFrame(rows)

    logger.info("")
    logger.info("=" * 100)
    logger.info("RESULTADOS — baselines vs Champion v4 (test set temporal)")
    logger.info("=" * 100)
    print(df_out.to_string(index=False))
    logger.info("")
    logger.info(f"Top-10 pesos descobertos pelo conversion_rate_score (sem acesso ao RF):")
    cr_top = sorted(cr_weights.items(), key=lambda x: -abs(x[1]))[:10]
    for feat, w in cr_top:
        logger.info(f"  {w:+.4f}  {feat}")
    logger.info("")

    # -----------------------------------------------------------------------
    # Ablation: quanto do RF vem de features pipeline-pesadas
    # -----------------------------------------------------------------------
    logger.info("=" * 100)
    logger.info("ABLAÇÃO — quanto do RF depende do pipeline de dados")
    logger.info("=" * 100)
    feature_groups = {
        "survey_only": [c for c in X_train.columns if any(c.startswith(p) for p in [
            "Voc_possui", "Tem_computador", "J_estudou_programa",
            "Qual_a_sua_idade", "Atualmente_qual_a_sua_faixa",
            "O_que_voc_faz_atualmente", "O_que_mais_voc_quer",
            "Voc_j_fez_faz", "O_seu_g_nero",
        ])],
        "survey_plus_engineered": None,  # survey + nome_comprimento/dia_semana/_valido/_tem_sobrenome/telefone_comprimento
        "survey_plus_utm": None,         # survey + UTM
        "all_features": list(X_train.columns),
    }
    eng_prefixes = ("nome_", "telefone_", "email_", "dia_semana")
    utm_prefixes = ("Source_", "Medium_", "Term_")
    feature_groups["survey_plus_engineered"] = (
        feature_groups["survey_only"] +
        [c for c in X_train.columns if c.startswith(eng_prefixes) or c == "dia_semana"]
    )
    feature_groups["survey_plus_utm"] = (
        feature_groups["survey_only"] +
        [c for c in X_train.columns if c.startswith(utm_prefixes)]
    )
    abl_rows = []
    for group_name, cols in feature_groups.items():
        cols = [c for c in cols if c in X_train.columns]
        rf = RandomForestClassifier(
            n_estimators=300, max_depth=8, max_features="sqrt",
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
        rf.fit(X_train[cols], y_train)
        y_score = rf.predict_proba(X_test[cols])[:, 1]
        m = eval_model(y_test, y_score, f"rf_{group_name}")
        m["n_features"] = len(cols)
        abl_rows.append(m)
    abl_df = pd.DataFrame(abl_rows)[["model", "n_features", "auc", "auc_pr", "d10_conc_pct", "d10_lift", "monotonia_pct"]]
    print(abl_df.to_string(index=False))
    logger.info("")
    logger.info("Regras descobertas pelo shallow_tree:")
    logger.info(tree_rules)

    if args.out:
        df_out.to_csv(args.out, index=False)
        logger.info(f"\nResultados salvos em {args.out}")

    if args.mlflow_log:
        os.environ.setdefault(
            "MLFLOW_TRACKING_URI",
            "postgresql+psycopg2://postgres:SmartAds2026DB!@104.197.138.129:5432/mlflow",
        )
        import mlflow
        mlflow.set_experiment(f"baselines_vs_{ref_label}")
        for row in rows:
            with mlflow.start_run(run_name=row["model"]):
                mlflow.log_param("cut_date", cut_date)
                mlflow.log_param("reference_run", args.reference_run or "champion_v4_hardcoded")
                mlflow.log_param("n_train", len(X_train))
                mlflow.log_param("n_test", len(X_test))
                mlflow.log_param("n_features", X_train.shape[1])
                for k, v in row.items():
                    if k == "model":
                        continue
                    mlflow.log_metric(k, v)
        logger.info(f"Logado em MLflow experiment 'baselines_vs_champion_v4' ({len(rows)} runs).")


if __name__ == "__main__":
    main()
