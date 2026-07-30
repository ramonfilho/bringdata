"""Testes do dono único do nome da fonte unificada de leads + guarda de frescor.

O QUE ESTES TESTES PROTEGEM
---------------------------
O nome do universo de leads de treino (`analytics.leads.source`) estava CRAVADO em dois
arquivos que não se falavam: o escritor da ingestão diária (`src/data/leads_unify.py`) e o
leitor do treino (`src/train_pipeline.py`). Em 21/07/2026 a fonte foi renomeada
`train_unified` -> `leads_treino_prod` e só o leitor migrou. O escritor seguiu enchendo o
nome velho, criando uma fonte PARALELA, e o treino ficou 9 dias congelado em 342.264 leads
— cego pros 12.873 leads novos — sem NADA falhar: a leitura devolvia centenas de milhares
de linhas e o log dizia um número grande e tranquilizador.

Dois testes, um pra cada metade da lição:
  1. o nome tem UM dono e todos herdam dele;
  2. "veio muita linha" não prova fonte viva — só a data do lead mais recente prova.

Rodar: python3 -m pytest V2/tests/test_fonte_treino_dono_unico.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

import pandas as pd
import pytest

_V2 = Path(__file__).resolve().parent.parent
_YAML_VIVO = _V2 / "configs" / "clients" / "devclub.yaml"


def test_um_dono_e_todos_herdam():
    """Escritor, treino e público da Meta leem o MESMO nome, de UMA linha do YAML."""
    from src.core.client_config import ClientConfig
    from src.data.leads_unify import unified_source

    cfg = ClientConfig.from_yaml(_YAML_VIVO)
    dono = cfg.ingestion.leads_unified_source
    assert dono, "ingestion.leads_unified_source não pode ser vazio — é o dono do nome"
    # o bloco de públicos da Meta HERDA (não declara)
    assert cfg.meta_audiences.leads_source == dono
    # o escritor da ingestão diária lê do mesmo lugar
    assert unified_source() == dono


def test_yaml_nao_declara_o_nome_duas_vezes():
    """Guarda contra a regressão exata: o nome voltar a existir em dois lugares do YAML.

    Se alguém precisar MESMO de universos diferentes pra treino e pra público da Meta,
    este teste falha e obriga a decisão a ser consciente em vez de acidental.
    """
    import yaml

    with open(_YAML_VIVO, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    assert "leads_unified_source" in (raw.get("ingestion") or {}), \
        "o dono do nome saiu do bloco ingestion"
    assert (raw.get("meta_audiences") or {}).get("leads_source") is None, \
        ("meta_audiences.leads_source voltou a declarar o nome — foi essa duplicação que "
         "deixou o treino congelado 9 dias. Herde do ingestion.leads_unified_source.")


def test_escritor_cai_no_nome_CORRENTE_se_o_config_sumir():
    """Degradar não pode ressuscitar o bug: sem config, o default é o nome de HOJE."""
    from src.core.client_config import ClientConfig, IngestionConfig
    from src.data.leads_unify import unified_source

    assert unified_source(client_id="cliente_que_nao_existe") == \
        IngestionConfig().leads_unified_source
    assert IngestionConfig().leads_unified_source == \
        ClientConfig.from_yaml(_YAML_VIVO).ingestion.leads_unified_source


def _df(dias_atras):
    return pd.DataFrame({"Data": [pd.Timestamp.now() - pd.Timedelta(days=dias_atras)]})


def test_guarda_de_frescor_deixa_passar_universo_vivo():
    from src.train_pipeline import _assert_universo_fresco

    _assert_universo_fresco(_df(1), fonte="t", max_atraso_dias=7)
    _assert_universo_fresco(_df(7), fonte="t", max_atraso_dias=7)   # no limite, passa


def test_guarda_de_frescor_aborta_universo_congelado():
    """9 dias = exatamente o atraso do incidente. Tem que ABORTAR, não avisar."""
    from src.train_pipeline import _assert_universo_fresco

    with pytest.raises(AssertionError) as e:
        _assert_universo_fresco(_df(9), fonte="leads_treino_prod", max_atraso_dias=7)
    # a mensagem tem que apontar pro conserto, não só reclamar
    assert "leads_unified_source" in str(e.value)


def test_guarda_de_frescor_aborta_sem_data_valida():
    """Muitas linhas + nenhuma data legível também é universo quebrado."""
    from src.train_pipeline import _assert_universo_fresco

    with pytest.raises(AssertionError):
        _assert_universo_fresco(pd.DataFrame({"Data": ["xx", "yy"]}), fonte="t",
                                max_atraso_dias=7)


def test_guarda_nao_derruba_quando_nao_ha_coluna_data():
    """Sem a coluna, a guarda avisa e sai — não pode quebrar quem não tem 'Data'."""
    from src.train_pipeline import _assert_universo_fresco

    _assert_universo_fresco(pd.DataFrame({"outra": [1]}), fonte="t", max_atraso_dias=7)


def test_funcoes_de_ingestao_aceitam_fonte_injetada():
    """As 3 funções públicas recebem `source` — permite testar e migrar sem editar código."""
    import inspect

    from src.data import leads_unify

    for nome in ("build_unified", "build_incremental", "audit_unified"):
        sig = inspect.signature(getattr(leads_unify, nome))
        assert "source" in sig.parameters, f"{nome} não aceita source injetável"
        assert sig.parameters["source"].default is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
