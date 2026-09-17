"""Testes do módulo de seleção de features por importância de permutação.

Dataset sintético: 8 features informativas (sinal forte) + 6 de ruído. Contrato
que o módulo DEVE garantir: (1) nunca cortar uma informativa; (2) cortar ruído;
(3) não regredir o AUC; (4) guard de mínimo e trava de não-regressão funcionam;
(5) agnóstico ao estimador.

Rodar: python3 V2/tests/test_feature_selection.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from src.model.feature_selection import select_features, SelectionResult

RS = np.random.RandomState(0)
N = 4000
N_INFO, N_NOISE = 8, 6
info = [f"info_{i}" for i in range(N_INFO)]
noise = [f"noise_{i}" for i in range(N_NOISE)]
Xi = RS.randn(N, N_INFO)
Xn = RS.randn(N, N_NOISE)                       # ruído: não entra no y
w = RS.choice([-1.0, 1.0], N_INFO) * (1.0 + np.abs(RS.randn(N_INFO)))  # sinal forte (|w|>=1)
p = 1 / (1 + np.exp(-(Xi @ w)))
y = (RS.rand(N) < p).astype(int)
X = pd.DataFrame(np.hstack([Xi, Xn]), columns=info + noise)
dates = np.arange(N)                            # ordem temporal determinística
HP = dict(n_estimators=150, max_depth=6, random_state=42, n_jobs=-1, class_weight='balanced')

# Tolerância da trava de não-regressão no contrato 1-3. Com eps 0 o teste dependia da
# máquina: mesmo sklearn 1.6.1 / numpy 1.26.4, no Linux x86_64 do CI o AUC selecionado
# deu 0,9326 contra 0,9351 de baseline (ruído de floresta, 0,0025) e a seleção abortava.
# Cortar uma informativa (|w| >= 1) derruba o AUC bem mais que 0,005.
EPS_PLATAFORMA = 0.005


def test_nunca_corta_informativa_e_corta_ruido():
    r = select_features(X, y, dates, estimator_params=HP, n_repeats=8, min_features=1, threshold=0.0,
                        non_regression_eps=EPS_PLATAFORMA)
    assert isinstance(r, SelectionResult) and not r.aborted, r.reason
    # CONTRATO 1: nenhuma informativa cortada
    assert set(r.dropped).issubset(set(noise)), f"cortou informativa: {set(r.dropped) & set(info)}"
    # CONTRATO 2: cortou pelo menos parte do ruído
    assert len(r.dropped) >= 1, "não cortou nenhum ruído"
    # CONTRATO 3: não regrediu (além do ruído de plataforma)
    assert r.auc_selected >= r.auc_baseline - EPS_PLATAFORMA


def test_guard_min_features_nao_corta_abaixo():
    # min_features = total → não pode cortar nada (mantém todas)
    r = select_features(X, y, dates, estimator_params=HP, n_repeats=3, min_features=len(X.columns), threshold=0.0)
    assert r.dropped == [] and r.n_after == len(X.columns)


def test_guard_isolado_da_trava(  ):
    # threshold gigante marcaria tudo; guard segura em min_features=5.
    # non_regression_eps grande desliga a trava pra isolar o comportamento do guard.
    r = select_features(X, y, dates, estimator_params=HP, n_repeats=3, min_features=5,
                        threshold=1.0, non_regression_eps=1.0)
    assert r.n_after == 5 and len(r.dropped) == len(X.columns) - 5


def test_trava_nao_regressao_aborta():
    # forço regressão: mantenho só 1 feature (min_features=1, threshold gigante) com a
    # trava ligada (eps=0) → cair pra 1 feature deve piorar o AUC → aborta e mantém todas.
    r = select_features(X, y, dates, estimator_params=HP, n_repeats=3, min_features=1,
                        threshold=10.0, non_regression_eps=0.0)
    assert r.aborted and r.dropped == [] and r.n_after == len(X.columns)


def test_metodo_invalido_falha_alto():
    try:
        select_features(X, y, dates, estimator_params=HP, method='chi2')
        assert False, "deveria ter levantado ValueError"
    except ValueError:
        pass


def test_agnostico_ao_modelo():
    # mesmo procedimento com regressão logística — não quebra e respeita o contrato 1
    r = select_features(X, y, dates, estimator_cls=LogisticRegression,
                        estimator_params=dict(max_iter=300, class_weight='balanced'),
                        n_repeats=3, min_features=1, threshold=0.0)
    assert isinstance(r, SelectionResult)
    assert r.aborted or set(r.dropped).issubset(set(noise))


if __name__ == "__main__":
    test_nunca_corta_informativa_e_corta_ruido()
    test_guard_min_features_nao_corta_abaixo()
    test_guard_isolado_da_trava()
    test_trava_nao_regressao_aborta()
    test_metodo_invalido_falha_alto()
    test_agnostico_ao_modelo()
    print("OK — testes de feature selection passaram")


def test_mascara_treino_temporal_pega_os_primeiros_por_data():
    from src.model.feature_selection import mascara_treino_temporal
    datas = np.array(['2026-03-01', '2026-01-01', '2026-02-01', '2026-04-01', '2026-05-01'], dtype='datetime64[D]')
    m = mascara_treino_temporal(datas, 0.6)
    # 3 de 5 (60%): as 3 datas mais antigas, independente da ordem das linhas
    assert m.tolist() == [True, True, True, False, False]


def test_train_pipeline_seleciona_features_so_na_parte_de_treino():
    """Trava anti-deriva: a chamada de select_features no train_pipeline tem que
    receber só a parte de treino (mascara_treino_temporal), nunca o universo inteiro.
    Se voltar ao universo inteiro, o holdout da seleção vira o test set do modelo."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / 'src' / 'train_pipeline.py').read_text()
    i = src.index('_fs_result = select_features(')
    chamada = src[i:i + 500]
    assert '_fs_treino = mascara_treino_temporal(_fs_datas, train_ratio)' in src
    assert '.iloc[_fs_treino]' in chamada
    assert 'dates=_fs_datas[_fs_treino]' in chamada
