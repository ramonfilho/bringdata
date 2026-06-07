"""
Calibração de probabilidades de scoring (DT-20).

O `predict_proba` do Random Forest treinado com `class_weight='balanced'` produz
scores brutos que não são probabilidades reais de conversão — o reweighting da
classe minoritária empurra todos os scores pra perto do meio, gerando viés
sistemático de superestimação (ECE de 26-40 pp medido nos modelos atuais em
2026-05-08, ver `docs/analise_calibracao_jan30_abr28.md`).

Este módulo implementa o padrão Estratégia (Strategy): cada método de calibração
(none, isotonic, sigmoid) é uma classe que segue a mesma interface. O Predictor
recebe uma instância via injeção e aplica internamente sem perguntar qual é.

`NoneCalibrator` não é fallback — é estratégia legítima ("este modelo não foi
calibrado"). Modelos antigos sem `calibrator.pkl` carregam `NoneCalibrator` no
load e seguem matematicamente idênticos ao comportamento pré-DT-20.

Detalhes arquiteturais completos: `docs/PLANO_REFACTOR_MLOPS.md` § DT-20.
"""

from __future__ import annotations

import json
import logging
import pickle
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


logger = logging.getLogger(__name__)


METHOD_NONE = "none"
METHOD_ISOTONIC = "isotonic"
METHOD_SIGMOID = "sigmoid"

VALID_METHODS = (METHOD_NONE, METHOD_ISOTONIC, METHOD_SIGMOID)


class Calibrator(ABC):
    """Interface comum para todas as estratégias de calibração."""

    method: str  # subclasse define

    @abstractmethod
    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> "Calibrator":
        """
        Ajusta o calibrador.

        Args:
            y_prob: scores brutos do modelo (saída de `predict_proba(X)[:,1]`)
            y_true: labels reais binárias (0/1)

        Returns:
            self, para encadear chamadas
        """
        ...

    @abstractmethod
    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        """
        Aplica a calibração nos scores brutos.

        Args:
            y_prob: scores brutos do modelo

        Returns:
            scores calibrados, mesma shape que `y_prob`, valores em [0, 1]
        """
        ...

    def save(self, path: str | Path) -> None:
        """Serializa o calibrador via pickle. Inclui `method` para identificação."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)
        logger.info(f"Calibrador {self.method} salvo em {path}")


class NoneCalibrator(Calibrator):
    """
    Calibrador identidade.

    Usado em duas situações:
    1. Compatibilidade com modelos pré-DT-20 que não têm `calibrator.pkl` artifact.
    2. Configurações em que o operador decide não calibrar (`method: none` no YAML).
    """

    method = METHOD_NONE

    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> "NoneCalibrator":
        # Não há nada para aprender. fit é no-op.
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        # Identidade matemática — array é retornado intocado.
        return np.asarray(y_prob)


class IsotonicCalibrator(Calibrator):
    """
    Calibração via regressão isotônica (não-paramétrica, monotônica).

    Default recomendado para Random Forest. Aprende uma função em escada que só
    tem a restrição de ser não-decrescente — ajusta-se a qualquer forma de
    miscalibração (incluindo a "compressão pro meio" que o `class_weight='balanced'`
    produz). Funciona bem com volume ≥ 1.000 amostras; com os ~50k leads/treino
    do DevClub está com folga.
    """

    method = METHOD_ISOTONIC

    def __init__(self):
        self._iso: Optional[IsotonicRegression] = None

    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> "IsotonicCalibrator":
        y_prob = np.asarray(y_prob, dtype=float)
        y_true = np.asarray(y_true, dtype=float)
        if y_prob.shape != y_true.shape:
            raise ValueError(f"shapes incompatíveis: y_prob={y_prob.shape}, y_true={y_true.shape}")
        if y_prob.size == 0:
            raise ValueError("não é possível ajustar isotônica em array vazio")
        self._iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self._iso.fit(y_prob, y_true)
        logger.info(f"IsotonicCalibrator ajustado em {y_prob.size} pontos")
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if self._iso is None:
            raise RuntimeError("IsotonicCalibrator.transform chamado antes de fit")
        return self._iso.predict(np.asarray(y_prob, dtype=float))


class SigmoidCalibrator(Calibrator):
    """
    Calibração via sigmoide (Platt scaling).

    Ajusta `P(y=1 | score) = 1 / (1 + exp(A · score + B))` por máxima verossimilhança.
    Funciona bem quando a miscalibração tem forma logística e em datasets pequenos
    (~100-1.000 amostras). Para os modelos do DevClub, isotonic é tipicamente
    melhor — sigmoid fica disponível por completude e como alternativa configurável.
    """

    method = METHOD_SIGMOID

    def __init__(self):
        self._lr: Optional[LogisticRegression] = None

    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> "SigmoidCalibrator":
        y_prob = np.asarray(y_prob, dtype=float).reshape(-1, 1)
        y_true = np.asarray(y_true, dtype=int).ravel()
        if y_prob.shape[0] != y_true.shape[0]:
            raise ValueError(f"shapes incompatíveis: y_prob={y_prob.shape}, y_true={y_true.shape}")
        if y_prob.size == 0:
            raise ValueError("não é possível ajustar sigmoid em array vazio")
        # LogisticRegression de 1 feature reproduz Platt scaling: aprende A e B em
        # P(y=1) = sigmoid(A·score + B). Sem regularização forte para não distorcer.
        self._lr = LogisticRegression(C=1e6, solver="lbfgs")
        self._lr.fit(y_prob, y_true)
        logger.info(f"SigmoidCalibrator ajustado em {y_prob.shape[0]} pontos")
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if self._lr is None:
            raise RuntimeError("SigmoidCalibrator.transform chamado antes de fit")
        y_prob = np.asarray(y_prob, dtype=float).reshape(-1, 1)
        return self._lr.predict_proba(y_prob)[:, 1]


def make_calibrator(method: str) -> Calibrator:
    """
    Factory — devolve instância nova da estratégia escolhida.

    Args:
        method: um dos valores em `VALID_METHODS`. Case-insensitive.

    Returns:
        Calibrador não-ajustado pronto para `fit`.
    """
    method_lc = (method or METHOD_NONE).strip().lower()
    if method_lc == METHOD_NONE:
        return NoneCalibrator()
    if method_lc == METHOD_ISOTONIC:
        return IsotonicCalibrator()
    if method_lc == METHOD_SIGMOID:
        return SigmoidCalibrator()
    raise ValueError(
        f"método de calibração desconhecido: {method!r}. "
        f"Válidos: {VALID_METHODS}"
    )


def load_calibrator(path: str | Path) -> Calibrator:
    """
    Carrega calibrador salvo via pickle.

    Args:
        path: caminho para o `calibrator.pkl` (artifact MLflow).

    Returns:
        Instância já ajustada da subclasse correta.
    """
    path = Path(path)
    with open(path, "rb") as f:
        obj = pickle.load(f)
    if not isinstance(obj, Calibrator):
        raise TypeError(
            f"arquivo em {path} não contém um Calibrator (carregou {type(obj).__name__})"
        )
    logger.info(f"Calibrador {obj.method} carregado de {path}")
    return obj
