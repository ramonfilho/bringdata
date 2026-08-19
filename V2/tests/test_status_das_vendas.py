"""Trava: todo gateway precisa emitir `status` no dicionário normalizado.

O `analytics.sales.status` é a única forma de distinguir venda aprovada de
reembolsada/estornada depois de gravada, e `sales_store._row_params` lê a chave
'status'. Antes desta trava, 4 dos 5 gateways não a emitiam: o Guru extraía e
descartava, o Asaas mandava como `_asaas_status` (prefixo de debug), o Boletex lia
só para filtrar e a Hotmart nem lia. Resultado: 12.139 linhas com status NULO.
"""
import pandas as pd
import pytest

from src.validation.sales_store import _row_params


def test_row_params_le_a_chave_status():
    """O contrato do store: a chave é 'status', não '_asaas_status' nem outra."""
    row = {"origem": "guru", "email": "a@b.com", "sale_date": "2026-08-10",
           "sale_value": 1997.0, "status": "Aprovada"}
    assert _row_params(row, "devclub")["status"] == "Aprovada"


def test_row_params_nao_le_status_com_prefixo_de_debug():
    """Campo com `_` é debug e NÃO chega ao banco — foi assim que o Asaas se perdeu."""
    row = {"origem": "asaas", "email": "a@b.com", "sale_date": "2026-08-10",
           "sale_value": 219.0, "_asaas_status": "RECEIVED"}
    assert _row_params(row, "devclub")["status"] is None


@pytest.mark.parametrize("metodo", [
    "load_guru_sales_from_api",
    "load_hotmart_sales_from_api",
])
def test_loader_nao_descarta_status(metodo):
    """Nenhum loader pode ter um drop de 'status' no caminho de saída."""
    import inspect
    from src.validation.data_loader import SalesDataLoader
    fonte = inspect.getsource(getattr(SalesDataLoader, metodo))
    assert "drop(columns=['status'])" not in fonte, (
        f"{metodo} descarta a coluna status; ela precisa chegar ao sales_store")


def test_asaas_emite_status():
    from src.validation import asaas_sales_extractor as m
    fonte = open(m.__file__, encoding="utf-8").read()
    assert "'status': payment.get('status')" in fonte


def test_boletex_emite_status():
    from src.validation import boletex_sales_extractor as m
    fonte = open(m.__file__, encoding="utf-8").read()
    assert "'status': status" in fonte


def test_hotmart_emite_status():
    from src.validation import data_loader as m
    fonte = open(m.__file__, encoding="utf-8").read()
    assert "'status':      purchase.get('status')" in fonte
