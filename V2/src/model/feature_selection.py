"""Seleção de features por importância de PERMUTAÇÃO (etapa final opcional do treino).

Mede a contribuição de cada feature para GENERALIZAR fora do tempo: fita o modelo,
embaralha cada feature num holdout temporal e vê quanto o AUC cai. Remove as que não
ajudam (importância <= threshold). Escolhido num torneio contra RF-nativo/L1/RFE/
informação-mútua (a permutação ganhou em todo K).

Agnóstico ao modelo: trata o estimador como caixa-preta (só precisa de predict_proba
+ holdout). Trocar RandomForest por XGBoost = passar outro `estimator_cls`; a seleção
se recalibra pro modelo novo (o conjunto escolhido é específico do modelo, então
re-roda a seleção pra cada modelo, não reaproveita a lista).

A propagação pro modelo/produção NÃO mora aqui: quem consome o resultado (train_pipeline)
dropa as colunas ANTES do fit, então o feature_registry gravado no MLflow já reflete o
subset e core/encoding.apply_encoding alinha produção — mecanismo que já existe.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

logger = logging.getLogger(__name__)


@dataclass
class SelectionResult:
    """Resultado da seleção. `dropped` vazio + `aborted`/`reason` explicam quando
    nada foi removido (nada abaixo do threshold, guard de mínimo, ou não-regressão)."""
    kept: List[str]
    dropped: List[str]
    importances: Dict[str, float]
    auc_baseline: float
    auc_selected: float
    n_before: int
    n_after: int
    aborted: bool
    reason: str
    method: str
    threshold: float


def params_mlflow(result: Optional['SelectionResult'] = None) -> Dict[str, object]:
    """Parâmetros do run que descrevem a seleção de features.

    Existe porque contagem de features NÃO prova que a seleção rodou. Ao comparar abr28
    (60 features) com jul_24 (53) em 06/08/2026 foi preciso inferir pela contagem, e a
    inferência era ambígua: das 7 de diferença, parte veio da seleção e parte veio de o
    formulário ter trocado de opções entre abril e julho — os dois efeitos se somam.

    `result=None` significa "a seleção não rodou" e é logado como `false`, não omitido:
    parâmetro ausente é indistinguível de run antigo que nem conhecia a flag.
    """
    if result is None:
        return {'use_feature_selection': False}
    p: Dict[str, object] = {
        'use_feature_selection': True,
        'feature_selection_method': result.method,
        'feature_selection_threshold': result.threshold,
        'feature_selection_n_before': result.n_before,
        'feature_selection_n_after': result.n_after,
        'feature_selection_n_dropped': len(result.dropped),
        'feature_selection_auc_before': round(float(result.auc_baseline), 6),
        'feature_selection_auc_after': round(float(result.auc_selected), 6),
        'feature_selection_aborted': result.aborted,
    }
    if not result.dropped:
        p['feature_selection_reason'] = str(result.reason)[:250]
    return p


def _temporal_holdout_mask(dates, train_ratio: float) -> np.ndarray:
    """Máscara booleana posicional (True=treino): ordena por data e pega os primeiros
    train_ratio. Espelha o split temporal_leads do treino — mesmo critério, então o
    holdout aqui bate com o test set do modelo por construção."""
    d = pd.to_datetime(pd.Series(dates).reset_index(drop=True), errors='coerce')
    order = np.argsort(d.values, kind='mergesort')
    n_train = int(len(order) * train_ratio)
    mask = np.zeros(len(order), dtype=bool)
    mask[order[:n_train]] = True
    return mask


def select_features(
    X: pd.DataFrame,
    y,
    dates,
    *,
    train_ratio: float = 0.8,
    estimator_params: Optional[Dict[str, Any]] = None,
    estimator_cls: Type = RandomForestClassifier,
    method: str = 'permutation',
    threshold: float = 0.0,
    min_features: int = 20,
    n_repeats: int = 5,
    non_regression_eps: float = 0.0,
    random_state: int = 42,
) -> SelectionResult:
    """Seleciona features por importância de permutação num holdout temporal.

    Args:
        X: DataFrame de features JÁ ENCODADAS (sem a coluna target).
        y: alvo binário (array/Series posicional a X).
        dates: data por linha (posicional a X) — define o holdout temporal.
        train_ratio: fração de treino no split (igual ao do modelo).
        estimator_params: hiperparâmetros do MESMO modelo que o treino usa.
        estimator_cls: classe do estimador (default RandomForest; XGBClassifier no futuro).
        method: só 'permutation' por ora (falha alto se outro).
        threshold: remove features com importância <= threshold (default 0.0).
        min_features: nunca cai abaixo disso (mantém as melhores) — guard.
        n_repeats: repetições da permutação (estabilidade da importância).
        non_regression_eps: aborta a seleção se AUC_selecionado < AUC_baseline - eps.

    Returns:
        SelectionResult. Em qualquer aborto/guard, `dropped=[]` e `kept` = todas.
    """
    if method != 'permutation':
        raise ValueError(f"[feature_selection] método não suportado: {method!r} (só 'permutation' por ora)")

    cols = list(X.columns)
    assert cols, "[feature_selection] X sem colunas — nada a selecionar"
    Xv = X.fillna(0).to_numpy()
    y = np.asarray(y).astype(int)

    mask = _temporal_holdout_mask(dates, train_ratio)
    Xtr, Xte, ytr, yte = Xv[mask], Xv[~mask], y[mask], y[~mask]
    assert ytr.sum() > 0 and yte.sum() > 0, (
        f"[feature_selection] holdout temporal sem positivos (treino={int(ytr.sum())}, "
        f"test={int(yte.sum())}) — split inválido, não dá pra medir importância"
    )

    params = dict(estimator_params or {})

    # baseline: modelo com TODAS as features (usado pra permutação E pra régua de não-regressão)
    base = estimator_cls(**params)
    base.fit(Xtr, ytr)
    auc_baseline = float(roc_auc_score(yte, base.predict_proba(Xte)[:, 1]))

    pi = permutation_importance(
        base, Xte, yte, scoring='roc_auc', n_repeats=n_repeats,
        random_state=random_state, n_jobs=params.get('n_jobs', -1),
    )
    imp = {c: float(v) for c, v in zip(cols, pi.importances_mean)}
    ranked = sorted(cols, key=lambda c: imp[c], reverse=True)

    to_drop = [c for c in cols if imp[c] <= threshold]

    # guard de mínimo: nunca cortar abaixo de min_features (mantém as de maior importância)
    if len(cols) - len(to_drop) < min_features:
        keep_set = set(ranked[:max(min_features, 0)])
        to_drop = [c for c in cols if c not in keep_set]
        logger.warning("[feature_selection] guard min_features=%d ativado — cortando só até %d features",
                       min_features, len(cols) - len(to_drop))

    if not to_drop:
        logger.info("[feature_selection] nada a remover (todas as %d features > threshold=%.4g)", len(cols), threshold)
        return SelectionResult(cols, [], imp, auc_baseline, auc_baseline, len(cols), len(cols),
                               False, 'nada abaixo do threshold', method, threshold)

    kept = [c for c in cols if c not in set(to_drop)]
    keep_idx = [i for i, c in enumerate(cols) if c in set(kept)]
    sel = estimator_cls(**params)
    sel.fit(Xtr[:, keep_idx], ytr)
    auc_selected = float(roc_auc_score(yte, sel.predict_proba(Xte[:, keep_idx])[:, 1]))

    # trava de NÃO-REGRESSÃO: seleção que piora o AUC nunca sobe — mantém todas.
    if auc_selected < auc_baseline - non_regression_eps:
        logger.warning(
            "[feature_selection] ABORTADO por não-regressão: AUC selecionado %.4f < baseline %.4f - eps %.4g "
            "→ mantendo todas as %d features",
            auc_selected, auc_baseline, non_regression_eps, len(cols),
        )
        return SelectionResult(cols, [], imp, auc_baseline, auc_selected, len(cols), len(cols),
                               True, f'não-regressão ({auc_selected:.4f} < {auc_baseline:.4f})', method, threshold)

    logger.info(
        "[feature_selection] %d → %d features | AUC holdout %.4f → %.4f (Δ%+.4f) | removidas %d",
        len(cols), len(kept), auc_baseline, auc_selected, auc_selected - auc_baseline, len(to_drop),
    )
    return SelectionResult(kept, to_drop, imp, auc_baseline, auc_selected, len(cols), len(kept),
                           False, 'ok', method, threshold)
