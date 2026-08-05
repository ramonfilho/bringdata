"""A nota do criativo não pode conter o futuro. É isso que estes testes travam."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.nota_criativo import (  # noqa: E402
    K_ENCOLHIMENTO, NOTA_NEUTRA, adicionar_nota_criativo,
)


def _historico(n_por_semana=6000, semanas=8, conv_bom=0.02, conv_ruim=0.005):
    """Dois criativos com volume alto e conversões bem diferentes, ao longo de 8 semanas."""
    linhas = []
    base = pd.Timestamp("2026-01-05")
    for s in range(semanas):
        dia = base + pd.Timedelta(weeks=s)
        for nome, conv in (("AD_BOM", conv_bom), ("AD_RUIM", conv_ruim)):
            k = int(n_por_semana * conv)
            linhas += [{"criativo": nome, "dia": dia, "buy": 1}] * k
            linhas += [{"criativo": nome, "dia": dia, "buy": 0}] * (n_por_semana - k)
    return pd.DataFrame(linhas)


def _df(criativos, data):
    return pd.DataFrame({"Content": criativos,
                         "Data": [data] * len(criativos),
                         "outra_coluna": range(len(criativos))})


def test_ordena_bom_acima_de_ruim():
    h = _historico()
    df = _df(["AD_BOM", "AD_RUIM"], "2026-03-09")
    out = adicionar_nota_criativo(df, historico=h)
    assert out.loc[0, "nota_criativo"] > out.loc[1, "nota_criativo"]


def test_criativo_desconhecido_fica_neutro():
    h = _historico()
    out = adicionar_nota_criativo(_df(["AD_BOM", "NUNCA_RODOU"], "2026-03-09"),
                                  historico=h, cobertura_minima=0.0)
    assert out.loc[1, "nota_criativo"] == NOTA_NEUTRA


def test_nao_usa_o_futuro():
    """Lead da 1a semana não pode enxergar o desempenho das semanas seguintes."""
    h = _historico()
    cedo = adicionar_nota_criativo(_df(["AD_BOM"], "2026-01-05"), historico=h,
                                   cobertura_minima=0.0)
    assert cedo.loc[0, "nota_criativo"] == NOTA_NEUTRA, (
        "sem histórico anterior à 1a semana, a nota tem que ser neutra"
    )


def test_encolhimento_puxa_para_o_neutro():
    """Criativo com pouco volume não pode receber nota extrema."""
    h = _historico()
    pouco = pd.DataFrame([{"criativo": "AD_RARO", "dia": pd.Timestamp("2026-01-05"),
                           "buy": 1}] * 6
                         + [{"criativo": "AD_RARO", "dia": pd.Timestamp("2026-01-05"),
                             "buy": 0}] * 194)
    out = adicionar_nota_criativo(_df(["AD_RARO"], "2026-03-09"),
                                  historico=pd.concat([h, pouco]), cobertura_minima=0.0)
    nota = out.loc[0, "nota_criativo"]
    peso = 200 / (200 + K_ENCOLHIMENTO)
    assert peso < 0.06, "com 200 leads o peso tem que ser pequeno"
    assert abs(nota - NOTA_NEUTRA) < 0.25, (
        f"nota {nota:.2f} longe demais do neutro para 200 leads: o encolhimento não pegou"
    )


def test_falta_de_coluna_falha_alto():
    with pytest.raises(KeyError, match="Célula 8"):
        adicionar_nota_criativo(pd.DataFrame({"Data": ["2026-03-09"]}), historico=_historico())


def test_cobertura_baixa_falha_alto():
    """Feature inerte tem que gritar, não virar uma coluna silenciosa de 1,0."""
    h = _historico()
    with pytest.raises(ValueError, match="cobertura"):
        adicionar_nota_criativo(_df(["DESCONHECIDO"] * 10, "2026-03-09"), historico=h)


def test_nao_mexe_nas_outras_colunas():
    h = _historico()
    df = _df(["AD_BOM", "AD_RUIM"], "2026-03-09")
    out = adicionar_nota_criativo(df, historico=h)
    assert list(df.columns) + ["nota_criativo"] == list(out.columns)
    assert out["outra_coluna"].tolist() == df["outra_coluna"].tolist()
    assert "nota_criativo" not in df.columns, "não pode mutar o df de entrada"


def test_nota_e_numerica_e_finita():
    h = _historico()
    out = adicionar_nota_criativo(_df(["AD_BOM", "AD_RUIM"], "2026-03-09"), historico=h)
    v = out["nota_criativo"].values
    assert np.isfinite(v).all() and v.dtype.kind == "f"
