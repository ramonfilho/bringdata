"""O run tem que DIZER se passou por seleção de features, em vez de deixar adivinhar.

Motivo real (06/08/2026): abr28 tinha 60 features e jul_24 tinha 53, e a única forma de
saber se a seleção havia rodado era contar. A contagem mentia: das 7 de diferença, parte
veio da seleção e parte veio de o formulário ter trocado de opções entre abril e julho.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.model.feature_selection import SelectionResult, params_mlflow  # noqa: E402
from src.model.training_model import registrar_features_e_modelo_devclub  # noqa: E402


def _resultado(dropped, aborted=False, reason=""):
    return SelectionResult(
        kept=["a", "b"], dropped=list(dropped), importances={"a": 0.1, "b": 0.05},
        auc_baseline=0.7301234567, auc_selected=0.7355, n_before=60,
        n_after=60 - len(dropped), aborted=aborted, reason=reason,
        method="permutation", threshold=0.0,
    )


def test_sem_selecao_loga_false_em_vez_de_omitir():
    """Parâmetro ausente é indistinguível de run antigo — tem que sair `False` explícito."""
    p = params_mlflow(None)
    assert p == {"use_feature_selection": False}


def test_com_selecao_registra_o_que_saiu_e_o_efeito_no_auc():
    p = params_mlflow(_resultado(["x", "y", "z"]))
    assert p["use_feature_selection"] is True
    assert p["feature_selection_n_before"] == 60
    assert p["feature_selection_n_after"] == 57
    assert p["feature_selection_n_dropped"] == 3
    assert p["feature_selection_method"] == "permutation"
    assert p["feature_selection_auc_before"] == 0.730123   # arredondado, não truncado
    assert p["feature_selection_auc_after"] == 0.7355


def test_selecao_que_rodou_e_nao_cortou_nada_e_distinguivel_de_nao_ter_rodado():
    """O caso que mais confunde: contagem igual nos dois, param tem que separar."""
    rodou = params_mlflow(_resultado([], aborted=True, reason="nao_regressao"))
    nao_rodou = params_mlflow(None)
    assert rodou["use_feature_selection"] is True
    assert nao_rodou["use_feature_selection"] is False
    assert rodou["feature_selection_n_dropped"] == 0
    assert rodou["feature_selection_reason"] == "nao_regressao"
    assert "feature_selection_reason" not in nao_rodou


def test_reason_nao_estoura_o_limite_de_param_do_mlflow():
    p = params_mlflow(_resultado([], reason="x" * 900))
    assert len(p["feature_selection_reason"]) == 250


def test_todo_valor_e_serializavel_como_param():
    """log_param aceita escalar; lista/dict viraria string ilegível."""
    for v in params_mlflow(_resultado(["a"])).values():
        assert isinstance(v, (str, int, float, bool)), f"{v!r} não é escalar"


def test_registro_do_modelo_aceita_o_parametro():
    """Contrato entre train_pipeline e training_model — quebra silenciosa se sumir."""
    sig = inspect.signature(registrar_features_e_modelo_devclub)
    assert "feature_selection_params" in sig.parameters
    assert sig.parameters["feature_selection_params"].default is None


def test_train_pipeline_passa_o_parametro_no_registro():
    fonte = (Path(__file__).resolve().parents[1] / "src" / "train_pipeline.py").read_text()
    assert "feature_selection_params=_fs_params" in fonte, (
        "train_pipeline parou de passar os params da seleção — o run volta a sair mudo"
    )
