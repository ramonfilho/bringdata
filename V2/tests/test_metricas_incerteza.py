"""src/model/metricas_incerteza.py: intervalos bootstrap, lift do top-10%, Brier e ECE."""
import numpy as np
import pytest
from sklearn.metrics import brier_score_loss, roc_auc_score

from src.model.metricas_incerteza import brier, ece, intervalo_bootstrap, lift_top10, medir_incerteza


def _sintetico(n=6000, taxa=0.02, seed=0):
    rng = np.random.RandomState(seed)
    y = (rng.rand(n) < taxa).astype(int)
    # score correlacionado com y, mas ruidoso: parecido com o problema real (base rate baixa)
    p = np.clip(0.02 + 0.10 * y + rng.normal(0, 0.05, n), 0, 1)
    return y, p


def test_lift_top10_ranqueador_perfeito_e_aleatorio():
    y = np.array([1] * 100 + [0] * 900)
    p_perfeito = np.linspace(1, 0, 1000)      # positivos primeiro
    assert lift_top10(y, p_perfeito) == pytest.approx(10.0)
    rng = np.random.RandomState(1)
    p_aleatorio = rng.rand(1000)
    assert 0.3 < lift_top10(y, p_aleatorio) < 2.5


def test_brier_bate_com_sklearn_e_ece_zero_quando_calibrado():
    y, p = _sintetico()
    assert brier(y, p) == pytest.approx(brier_score_loss(y, p))
    # calibrado por construção: y sorteado com probabilidade p
    rng = np.random.RandomState(3)
    p_cal = rng.rand(200_000)
    y_cal = (rng.rand(200_000) < p_cal).astype(int)
    assert ece(y_cal, p_cal) < 0.01
    # descalibrado: prevê 0,9 para uma taxa real de 0,1
    assert ece(np.array([1] * 10 + [0] * 90), np.full(100, 0.9)) == pytest.approx(0.8)


def test_intervalo_bootstrap_contem_o_ponto_e_e_deterministico():
    y, p = _sintetico()
    auc = roc_auc_score(y, p)
    ic = intervalo_bootstrap(y, p, n_amostras=200, seed=7)
    assert ic["auc_ci95_low"] < auc < ic["auc_ci95_high"]
    assert ic["lift_top10_ci95_low"] < lift_top10(y, p) < ic["lift_top10_ci95_high"]
    assert ic["bootstrap_amostras_validas"] == 200
    assert intervalo_bootstrap(y, p, n_amostras=50, seed=7) == intervalo_bootstrap(y, p, n_amostras=50, seed=7)


def test_medir_incerteza_devolve_so_floats_e_falha_alto_sem_duas_classes():
    y, p = _sintetico()
    m = medir_incerteza(y, p, n_amostras=50)
    assert set(m) >= {"auc_ci95_low", "auc_ci95_high", "lift_top10", "lift_top10_ci95_low",
                      "lift_top10_ci95_high", "brier_test", "ece_test", "n_pos_test"}
    assert all(isinstance(v, float) for v in m.values())
    with pytest.raises(ValueError):
        medir_incerteza(np.zeros(100, dtype=int), p[:100])
