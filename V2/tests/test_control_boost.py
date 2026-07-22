"""Teste da ênfase direcional no grupo CONTROLE (control_boost) do peso de treino.

control_boost multiplica SÓ o peso do grupo CONTROLE, por cima do balanceamento;
ML e NEUTRO ficam intactos. É o anti-feedback-loop de verdade (peso maior nos
leads que nenhum modelo tocou), distinto do balanceamento por frequência (alpha).

Rodar: python3 V2/tests/test_control_boost.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

import pandas as pd

from src.train_pipeline import _compute_control_weights

# label_map por assinatura de tag (como vem de analytics.campaign_labels)
_LM = {"aberto": "Controle", "leadhqlb": "Challenger",
       "machine learning": "Champion", "dev20": "Excluir"}
_DF = pd.DataFrame({"__campaign_for_weights__": [
    "DEVLF|CAP|FRIO|ABERTO", "DEVLF|CAP|FRIO|ABERTO", "DEVLF|CAP|FRIO|ABERTO",   # Controle x3
    "DEVLF|CAP|FRIO|LEADHQLB|1", "DEVLF|CAP|FRIO|MACHINE LEARNING",              # ML x2
    "DEV20",                                                                     # NEUTRO x1
]})


def _w(boost):
    return _compute_control_weights(_DF, alpha=1.0, campaign_col="__campaign_for_weights__",
                                    label_map=_LM, control_boost=boost)


def test_boost_multiplica_so_controle():
    w1, w2 = _w(1.0), _w(2.0)
    # controle (linhas 0-2) dobra; ML (3-4) e NEUTRO (5) intactos
    assert abs(w2.iloc[0] / w1.iloc[0] - 2.0) < 1e-9
    assert abs(w1.iloc[3] - w2.iloc[3]) < 1e-9      # ML igual
    assert abs(w1.iloc[5] - 1.0) < 1e-9 and abs(w2.iloc[5] - 1.0) < 1e-9  # neutro=1


def test_boost_1_e_no_op():
    # boost=1.0 → idêntico a não passar boost (só balanceamento)
    w_none = _compute_control_weights(_DF, alpha=1.0, campaign_col="__campaign_for_weights__", label_map=_LM)
    w_one = _w(1.0)
    assert (w_none.round(9) == w_one.round(9)).all()


def test_boost_invalido_cai_pra_1():
    # boost <= 0 é inválido → clamp pra 1.0 (não zera nem inverte o peso)
    w_bad, w_one = _w(0.0), _w(1.0)
    assert (w_bad.round(9) == w_one.round(9)).all()


if __name__ == "__main__":
    test_boost_multiplica_so_controle()
    test_boost_1_e_no_op()
    test_boost_invalido_cai_pra_1()
    print("OK — control_boost: direcional no controle, boost=1 no-op, boost<=0 clamp")
