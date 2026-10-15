"""Leitores do banco desviam para a base anonimizada quando BASE_ANON_DIR aponta para ela.

Monta uma base mínima em parquet (2 pessoas, 3 respostas, 2 vendas, 1 grau de risco) e confere
que read_pesquisa, read_sales e read_tmb_risk devolvem o contrato de sempre, com o pessoa_id no
lugar do e-mail, sem abrir conexão com o banco.
"""
import json

import pandas as pd
import pytest

from src.data import base_anonimizada
from src.data.leads_reader import read_pesquisa
from src.data.sales_reader import read_sales
from src.data.tmb_risk_reader import read_tmb_risk
from src.core.utils import normalizar_email

A, B = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def base(tmp_path, monkeypatch):
    resp = lambda idade: json.dumps({"Data": "2026-09-01 10:00:00", "Qual a sua idade?": idade})
    pd.DataFrame({
        "pessoa_id": [A, B, A],
        "source": ["leads_treino_prod", "leads_treino_prod", "outra_fonte"],
        "survey_responses": [resp("25 - 34 anos"), resp("18 - 24 anos"), resp("35 - 44 anos")],
        "utm_campaign": ["c1", "c2", "c3"],
        "utm_source": ["facebook-ads", "google-ads", "facebook-ads"],
    }).to_parquet(tmp_path / "leads_anon.parquet")
    pd.DataFrame({
        "pessoa_id": [A, B],
        "gateway": ["guru", "tmb"],
        "sale_value": [997.0, 1200.0],
        "sale_date": pd.to_datetime(["2026-09-10", "2026-10-01"], utc=True),
        "produto": ["DevClub", "DevClub"],
        "status": ["approved", "Efetivado"],
    }).to_parquet(tmp_path / "vendas_anon.parquet")
    pd.DataFrame({"pessoa_id": [B], "risk_grade": ["Alto"]}).to_parquet(tmp_path / "sales_tmb_risk_anon.parquet")
    monkeypatch.setenv(base_anonimizada.VARIAVEL, str(tmp_path))
    monkeypatch.setattr("src.data.leads_reader.open_analytics_connection", lambda *a, **k: pytest.fail("abriu o banco"))
    monkeypatch.setattr("src.data.sales_reader.open_analytics_connection", lambda *a, **k: pytest.fail("abriu o banco"))
    monkeypatch.setattr("src.data.tmb_risk_reader.open_analytics_connection", lambda *a, **k: pytest.fail("abriu o banco"))
    return tmp_path


def test_pesquisa_filtra_a_fonte_e_poe_o_pessoa_id_no_email(base):
    df = read_pesquisa(source="leads_treino_prod", include_utm=True)
    assert len(df) == 2
    assert list(df["E-mail"]) == [A + "@anon.local", B + "@anon.local"]
    assert list(df["Qual a sua idade?"]) == ["25 - 34 anos", "18 - 24 anos"]
    assert list(df["__utm_source__"]) == ["facebook-ads", "google-ads"]
    assert all(normalizar_email(e) for e in df["E-mail"])


def test_vendas_no_contrato_do_sales_reader_e_casam_com_a_pesquisa(base):
    v = read_sales(gateways=["tmb"])
    assert list(v.columns) == ["email", "telefone", "nome", "sale_value", "sale_date", "origem", "status", "product_name"]
    assert list(v["email"]) == [B + "@anon.local"]
    todas = read_sales(start="2026-09-01", end="2026-09-30")
    assert list(todas["email"]) == [A + "@anon.local"]
    assert set(todas["email"]) <= set(read_pesquisa(source="leads_treino_prod")["E-mail"])


def test_grau_de_risco_por_pessoa(base):
    assert read_tmb_risk() == {B + "@anon.local": "Alto"}


def test_as_of_falha_alto(base):
    with pytest.raises(ValueError):
        read_pesquisa(source="leads_treino_prod", as_of="2026-09-01")


def test_sem_a_variavel_le_do_banco(monkeypatch):
    monkeypatch.delenv(base_anonimizada.VARIAVEL, raising=False)
    assert base_anonimizada.diretorio() is None
