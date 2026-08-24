# -*- coding: utf-8 -*-
"""A janela do ETL de vendas embutido no relatorio_lancamento: puxa só com
carrinho aberto/imaturo, começando na última venda já ingerida."""
import importlib.util
from datetime import date
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "relatorio_lancamento", _V2 / "scripts" / "relatorio_lancamento.py")
rl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rl)

CAP = (date(2026, 8, 7), date(2026, 8, 17))
VEN = (date(2026, 8, 24), date(2026, 8, 30))


def _j(hoje, sales_max):
    return rl._janela_de_etl(*CAP, *VEN, hoje, sales_max)


def test_captacao_aberta_nao_puxa():
    assert _j(date(2026, 8, 10), None) is None


def test_entre_captacao_e_carrinho_nao_puxa():
    assert _j(date(2026, 8, 20), None) is None


def test_carrinho_aberto_sem_venda_ingerida_comeca_no_inicio_do_carrinho():
    estado, inicio, fim = _j(date(2026, 8, 26), None)
    assert estado == "venda_aberta"
    assert (inicio, fim) == (VEN[0], date(2026, 8, 26))


def test_carrinho_aberto_recomeca_na_ultima_venda_ingerida():
    estado, inicio, fim = _j(date(2026, 8, 28), date(2026, 8, 26))
    assert estado == "venda_aberta"
    assert inicio == date(2026, 8, 26)  # re-lê o dia; upsert idempotente


def test_ultima_venda_anterior_ao_carrinho_nao_encolhe_a_janela():
    _, inicio, _ = _j(date(2026, 8, 25), date(2026, 8, 1))
    assert inicio == VEN[0]


def test_carrinho_fechado_imaturo_ainda_puxa():
    estado, inicio, fim = _j(date(2026, 9, 2), date(2026, 8, 28))
    assert estado == "venda_fechada_imatura"
    assert (inicio, fim) == (date(2026, 8, 28), date(2026, 9, 2))


def test_maduro_nao_puxa():
    # 60 dias após o fim da captação, com ingestão cobrindo o carrinho inteiro
    assert _j(date(2026, 10, 20), date(2026, 8, 30)) is None
