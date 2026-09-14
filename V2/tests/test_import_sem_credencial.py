"""Importar módulo de src não pode exigir credencial.

Em 14/09/2026 o primeiro CI do GitHub Actions caiu na COLETA: training_model.py chamava
ensure_tracking_uri() no import, e o runner (sem .env) levantava RuntimeError antes de
rodar um teste sequer. Três arquivos de teste importam esse módulo por funções puras
(reescrever_active_model_yaml, atualizar_business_config_com_recall).

O contrato: a URI do MLflow é resolvida dentro das funções que falam com o servidor.
"""
import importlib
import re
from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parents[1]


def _sem_uri():
    raise RuntimeError("sem MLFLOW_TRACKING_URI (simulado pelo teste)")


def test_importar_training_model_sem_uri_do_mlflow(monkeypatch):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    import src.core.mlflow_setup as ms
    monkeypatch.setattr(ms, "resolve_tracking_uri", _sem_uri)

    import src.model.training_model as tm
    importlib.reload(tm)  # re-executa o corpo do módulo: não pode levantar

    assert callable(tm.reescrever_active_model_yaml)


def test_funcoes_que_falam_com_mlflow_resolvem_a_uri_na_hora():
    src = (_V2 / "src/model/training_model.py").read_text()
    # nada de chamada no nível do módulo
    assert not re.search(r"^(?:_?\w+\s*=\s*)?ensure_tracking_uri\(\)", src, re.M), \
        "ensure_tracking_uri() chamado no import de training_model.py"
    # e cada função que abre um MlflowClient resolve a URI antes
    for chamada in ("client = mlflow.tracking.MlflowClient()",
                    "_mlflow_client = mlflow.tracking.MlflowClient()"):
        i = src.index(chamada)
        antes = src[max(0, i - 200):i]
        assert "ensure_tracking_uri()" in antes, f"sem ensure_tracking_uri() antes de: {chamada}"


def test_ativar_run_sem_uri_falha_com_a_instrucao(monkeypatch, tmp_path):
    """Sem URI, quem chama a função de verdade recebe a mensagem de como configurar."""
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    import src.core.mlflow_setup as ms
    monkeypatch.setattr(ms, "resolve_tracking_uri", _sem_uri)
    import src.model.training_model as tm
    with pytest.raises(RuntimeError, match="MLFLOW_TRACKING_URI"):
        tm.ativar_run_existente("0" * 32)
