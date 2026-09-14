"""
Ativar um run não pode apagar o A/B do YAML de produção.

Até 14/09/2026, `--activate-run` abria configs/active_models/devclub.yaml em modo
escrita e gravava um dicionário novo com um único bloco. O `ab_test` inteiro
(variantes, role_history, pixels, eventos secundários e os comentários que explicam
cada decisão) sumia a cada ativação. Ninguém tinha rodado o comando desde que o A/B
existe, então o bug nunca apareceu; o pipeline de promoção por PR passa a rodá-lo, e
por isso a trava vem antes.

O teste usa o YAML REAL de produção como fixture (copiado para um diretório
temporário): é o arquivo que a função vai reescrever de verdade, com os comentários e
a estrutura que importam.
"""
from pathlib import Path

import pytest
import yaml

from src.model.training_model import reescrever_active_model_yaml

_V2 = Path(__file__).resolve().parents[1]
_YAML_REAL = _V2 / "configs" / "active_models" / "devclub.yaml"

_INFO = {"model_name": "v1_devclub_rf_novo", "trained_at": "2026-09-14T00:00:00", "split_type": "temporal_leads"}


def _cauda(texto: str) -> str:
    """Tudo a partir da primeira linha na coluna 0 depois do bloco active_model."""
    linhas = texto.split("\n")
    ini = next(i for i, l in enumerate(linhas) if l.rstrip() == "active_model:")
    fim = next(i for i in range(ini + 1, len(linhas)) if linhas[i] and not linhas[i].startswith((" ", "\t")))
    return "\n".join(linhas[fim:])


@pytest.fixture
def yaml_tmp(tmp_path):
    alvo = tmp_path / "devclub.yaml"
    alvo.write_text(_YAML_REAL.read_text())
    return alvo


def test_troca_o_run_e_mantem_o_ab_test_byte_a_byte(yaml_tmp):
    antes = yaml_tmp.read_text()
    reescrever_active_model_yaml(yaml_tmp, "abc123def456", _INFO)
    depois = yaml_tmp.read_text()

    cfg = yaml.safe_load(depois)
    assert cfg["active_model"]["mlflow_run_id"] == "abc123def456"
    assert cfg["active_model"]["model_name"] == "v1_devclub_rf_novo"
    assert cfg["active_model"]["trained_at"] == "2026-09-14T00:00:00"
    assert cfg["active_model"]["split_method"] == "temporal_leads"

    # O A/B (e tudo que vem depois do bloco) é o mesmo texto, não só o mesmo parse.
    assert _cauda(depois) == _cauda(antes), "o texto depois do bloco active_model mudou"
    assert cfg["ab_test"] == yaml.safe_load(antes)["ab_test"]


def test_performance_sai_e_comentarios_do_bloco_ficam(yaml_tmp):
    antes = yaml_tmp.read_text()
    assert "performance:" in antes, "fixture sem o bloco que este teste remove"
    reescrever_active_model_yaml(yaml_tmp, "abc123def456", _INFO)
    depois = yaml_tmp.read_text()
    assert "performance" not in yaml.safe_load(depois)["active_model"]
    assert "auc:" not in depois.split("ab_test:")[0], "sub-item do performance sobrou"
    # comentário que vive DENTRO do bloco active_model (explica o champion) continua lá
    assert "# Champion = abr28" in depois


def test_e_idempotente(yaml_tmp):
    reescrever_active_model_yaml(yaml_tmp, "abc123def456", _INFO)
    uma = yaml_tmp.read_text()
    reescrever_active_model_yaml(yaml_tmp, "abc123def456", _INFO)
    assert yaml_tmp.read_text() == uma


def test_chave_ausente_e_inserida_sem_quebrar_o_resto(tmp_path):
    alvo = tmp_path / "min.yaml"
    alvo.write_text("active_model:\n  mlflow_run_id: velho\n\nab_test:\n  enabled: false\n")
    reescrever_active_run = reescrever_active_model_yaml
    reescrever_active_run(alvo, "novo", _INFO)
    cfg = yaml.safe_load(alvo.read_text())
    assert cfg["active_model"]["mlflow_run_id"] == "novo"
    assert cfg["active_model"]["model_name"] == "v1_devclub_rf_novo"
    assert cfg["ab_test"] == {"enabled": False}


def test_sem_bloco_active_model_nao_grava_nada(tmp_path):
    alvo = tmp_path / "estranho.yaml"
    alvo.write_text("ab_test:\n  enabled: true\n")
    with pytest.raises(RuntimeError):
        reescrever_active_model_yaml(alvo, "novo", _INFO)
    assert alvo.read_text() == "ab_test:\n  enabled: true\n"
