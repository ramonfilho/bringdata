"""criativo_historico: os CONTRATOS que protegem o desenho.

1. O upsert semanal NUNCA toca prior_conversao/prior_fonte — essas colunas
   pertencem ao módulo do texto; sobrescrever apagaria o palpite toda segunda.
2. Leitura com tabela ausente degrada pra {} (o consumidor cai no modelo puro),
   nunca explode o push.
3. Acumulado vazio FALHA ALTO na gravação: com 26 lançamentos fechados na base,
   vazio = fonte quebrada, não estado válido.

Rodável:  PYTHONPATH=. python -m pytest tests/test_criativo_historico.py -q
"""
import pandas as pd
import pytest

from src.data.criativo_historico import DDL, _UPSERT, grava_historico, le_historico


def test_upsert_nao_toca_o_prior_do_texto():
    assert "prior_conversao" not in _UPSERT
    assert "prior_fonte" not in _UPSERT
    # mas as colunas EXISTEM na tabela (a casa do texto está no DDL)
    assert "prior_conversao" in DDL and "prior_fonte" in DDL


def test_ddl_tem_chave_por_cliente_e_criativo_e_lock_timeout():
    assert "PRIMARY KEY (client_id, criativo)" in DDL
    assert "lock_timeout" in DDL  # regra da casa pra DDL no analytics


class _ConnQueQuebra:
    def run(self, *a, **k):
        raise RuntimeError("relation does not exist")


def test_leitura_sem_tabela_degrada_pra_vazio():
    assert le_historico(_ConnQueQuebra()) == {}


def test_acumulado_vazio_falha_alto_na_gravacao():
    with pytest.raises(AssertionError):
        grava_historico(_ConnQueQuebra(), pd.DataFrame())
