"""Check T1-10: distinguir "categoria não escolhida" de "pergunta que não veio".

O check T1-10 avisa quando uma feature importante do modelo não está no DataFrame e
vai ser preenchida com 0. A intenção é pegar cegueira do modelo. Mas ele confundia
dois casos muito diferentes, e gritava ERROR nos dois:

  (a) O one-hot cria uma coluna por categoria PRESENTE. Quem respondeu
      "tem computador: sim" gera `..._sim` e não gera `..._nao`. O 0 na ausente é a
      codificação CORRETA, não cegueira. Em batch pequeno isso é estrutural, então
      o log de produção vivia cheio de "modelo fica cego" sem nada errado.

  (b) A coluna de origem não veio no DataFrame, então NENHUMA categoria dela foi
      gerada. Isso é cegueira de verdade e precisa continuar gritando.

Estes testes travam a distinção nos dois sentidos. O de baixar ruído é fácil de
"consertar" silenciando tudo, e é exatamente isso que o teste do caso (b) impede.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd

import src.core.encoding as enc
from src.core.client_config import EncodingConfig


REGISTRY = [
    "Tem_computador_notebook_sim",
    "Tem_computador_notebook_nao",
    "investiu_curso_online_Sim",
    "nome_comprimento",
]

TOP = [
    {"name": "Tem_computador_notebook_nao", "rank": 1, "importance": 0.0834},
    {"name": "investiu_curso_online_Sim", "rank": 2, "importance": 0.0742},
]


def _rodar(df, caplog):
    """Roda o encoding com os dois loaders trocados por stubs — o teste não
    depende de artefato do MLflow no disco."""
    orig_reg, orig_top = enc._load_feature_registry, enc._load_top_features
    enc._load_feature_registry = lambda artifacts: list(REGISTRY)
    enc._load_top_features = lambda artifacts, min_importance=0.01: list(TOP)
    try:
        with caplog.at_level(logging.DEBUG, logger=enc.logger.name):
            out = enc.apply_encoding(df, EncodingConfig(), artifacts={"mlflow_run_id": "x"})
        return out, caplog.records
    finally:
        enc._load_feature_registry, enc._load_top_features = orig_reg, orig_top


def test_clean_column_name_espelha_regra_do_dataframe():
    """Se esta regra divergir do passo 5, o check volta a classificar errado."""
    assert enc._clean_column_name("Tem computador/notebook?") == "Tem_computador_notebook"
    assert enc._clean_column_name("Já estudou programação?") == "J_estudou_programa_o"
    assert enc._clean_column_name("__abc__") == "abc"


def test_categoria_ausente_nao_vira_erro(caplog):
    """(a) A pergunta veio e o lead respondeu 'sim' — `_nao` ausente é o 0 correto."""
    df = pd.DataFrame([{"Tem computador/notebook?": "sim",
                        "investiu_curso_online": "Sim",
                        "nome_comprimento": 11}])
    out, records = _rodar(df, caplog)

    assert "Tem_computador_notebook_nao" in out.columns
    assert out["Tem_computador_notebook_nao"].iloc[0] == 0, "0 é a codificação correta"
    assert out["Tem_computador_notebook_sim"].iloc[0] == 1

    graves = [r for r in records
              if r.levelno >= logging.WARNING and "T1-10" in r.getMessage()]
    assert not graves, f"não devia alertar: {[r.getMessage() for r in graves]}"


def test_pergunta_ausente_continua_gritando(caplog):
    """(b) A coluna de origem não veio: cegueira real, tem que continuar em ERROR.

    É o teste que impede 'resolver' o ruído silenciando o check inteiro.
    """
    df = pd.DataFrame([{"investiu_curso_online": "Sim", "nome_comprimento": 11}])
    out, records = _rodar(df, caplog)

    assert out["Tem_computador_notebook_nao"].iloc[0] == 0

    erros = [r for r in records
             if r.levelno >= logging.ERROR
             and "Tem_computador_notebook_nao" in r.getMessage()]
    assert erros, "feature órfã (rank 1, 8,34%) tinha que gritar ERROR"
    assert "NENHUMA coluna de origem" in erros[0].getMessage()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
