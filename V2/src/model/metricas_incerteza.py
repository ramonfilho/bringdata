"""Incerteza e calibração das métricas do test set.

Por que existe: o changelog compara AUCs a 0,001 de distância sem nenhum intervalo, e o
score bruto do RandomForest (class_weight=balanced) vira valor monetário por decil sem uma
medida de calibração ao lado. Com ~500 positivos no test set, uma diferença de 0,002 de
AUC cabe dentro do ruído; o intervalo diz se cabe ou não.

O que sai (tudo medido no test set, com a probabilidade crua do modelo):
- auc_ci95_low / auc_ci95_high: intervalo bootstrap (percentil, n reamostragens com
  reposição) do AUC.
- lift_top10, lift_top10_ci95_low / high: conversão dos 10% de maior score dividida
  pela conversão geral, e o intervalo dela.
- brier_test: erro quadrático médio da probabilidade (0 = perfeito; prever a taxa base
  para todos dá taxa_base * (1 - taxa_base)).
- ece_test: erro de calibração esperado em 10 caixas de score: média, pesada por
  caixa, de |taxa observada - probabilidade média prevista|. 0 = calibrado.

Nunca derruba o treino: quem chama trata exceção e segue sem estas métricas.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score


def lift_top10(y: np.ndarray, p: np.ndarray) -> float:
    """Conversão dos 10% de maior score sobre a conversão geral (1,0 = igual à média)."""
    y = np.asarray(y, dtype=float); p = np.asarray(p, dtype=float)
    n_top = max(1, int(round(len(y) * 0.10)))
    topo = np.argsort(-p, kind="mergesort")[:n_top]
    base = y.mean()
    return float(y[topo].mean() / base) if base > 0 else float("nan")


def brier(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, dtype=float); p = np.asarray(p, dtype=float)
    return float(np.mean((p - y) ** 2))


def ece(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error em caixas de largura igual no [0, 1]."""
    y = np.asarray(y, dtype=float); p = np.asarray(p, dtype=float)
    bordas = np.linspace(0.0, 1.0, n_bins + 1)
    caixa = np.clip(np.digitize(p, bordas[1:-1], right=True), 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = caixa == b
        if m.any():
            total += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(total)


def intervalo_bootstrap(y, p, n_amostras: int = 500, seed: int = 42, alpha: float = 0.05) -> dict:
    """Intervalo percentil (1 - alpha) de AUC e de lift_top10 por reamostragem com
    reposição do test set. Reamostras sem positivo ou sem negativo são descartadas
    (AUC indefinido); o retorno diz quantas valeram."""
    y = np.asarray(y, dtype=int); p = np.asarray(p, dtype=float)
    rng = np.random.RandomState(seed)
    n = len(y)
    aucs, lifts = [], []
    for _ in range(n_amostras):
        idx = rng.randint(0, n, n)
        yb, pb = y[idx], p[idx]
        if yb.sum() == 0 or yb.sum() == n:
            continue
        aucs.append(roc_auc_score(yb, pb))
        lifts.append(lift_top10(yb, pb))
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    return {
        "auc_ci95_low": float(np.percentile(aucs, lo)),
        "auc_ci95_high": float(np.percentile(aucs, hi)),
        "lift_top10_ci95_low": float(np.percentile(lifts, lo)),
        "lift_top10_ci95_high": float(np.percentile(lifts, hi)),
        "bootstrap_amostras_validas": float(len(aucs)),
    }


def medir_incerteza(y, p, n_amostras: int = 500, seed: int = 42) -> dict:
    """Tudo junto, pronto para mlflow.log_metric (só floats)."""
    y = np.asarray(y, dtype=int); p = np.asarray(p, dtype=float)
    if y.sum() == 0 or y.sum() == len(y):
        raise ValueError("test set sem as duas classes; AUC e lift indefinidos")
    saida = {
        "lift_top10": lift_top10(y, p),
        "brier_test": brier(y, p),
        "ece_test": ece(y, p),
        "n_pos_test": float(int(y.sum())),
    }
    saida.update(intervalo_bootstrap(y, p, n_amostras=n_amostras, seed=seed))
    return saida
