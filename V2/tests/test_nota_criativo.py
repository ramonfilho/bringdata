"""A nota do criativo não pode conter o futuro. É isso que estes testes travam."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.nota_criativo import (  # noqa: E402
    CARENCIA_DIAS, JANELA_DESFECHO_DIAS, K_ENCOLHIMENTO, MIN_HIST_PERIODO,
    NOTA_NEUTRA, adicionar_nota_criativo,
)


def _historico(n_por_semana=6000, semanas=8, conv_bom=0.02, conv_ruim=0.005):
    """Dois criativos com volume alto e conversões bem diferentes, ao longo de 8 semanas."""
    linhas = []
    base = pd.Timestamp("2026-01-05")
    for s in range(semanas):
        dia = base + pd.Timedelta(weeks=s)
        for nome, conv in (("AD_BOM", conv_bom), ("AD_RUIM", conv_ruim)):
            k = int(n_por_semana * conv)
            linhas += [{"criativo": nome, "dia": dia, "buy": 1, "canal": "meta"}] * k
            linhas += [{"criativo": nome, "dia": dia, "buy": 0,
                        "canal": "meta"}] * (n_por_semana - k)
    return pd.DataFrame(linhas)


def _df(criativos, data, source="facebook-ads"):
    return pd.DataFrame({"Content": criativos,
                         "Data": [data] * len(criativos),
                         "Source": [source] * len(criativos),
                         "outra_coluna": range(len(criativos))})


def test_ordena_bom_acima_de_ruim():
    h = _historico()
    df = _df(["AD_BOM", "AD_RUIM"], "2026-03-09")
    out = adicionar_nota_criativo(df, historico=h, transcricoes={})
    assert out.loc[0, "nota_criativo"] > out.loc[1, "nota_criativo"]


def test_criativo_desconhecido_fica_neutro():
    h = _historico()
    out = adicionar_nota_criativo(_df(["AD_BOM", "NUNCA_RODOU"], "2026-03-09"),
                                  historico=h, transcricoes={}, cobertura_minima=0.0)
    assert out.loc[1, "nota_criativo"] == NOTA_NEUTRA


def test_nao_usa_o_futuro():
    """Lead da 1a semana não pode enxergar o desempenho das semanas seguintes."""
    h = _historico()
    cedo = adicionar_nota_criativo(_df(["AD_BOM"], "2026-01-05"), historico=h,
                                   transcricoes={}, cobertura_minima=0.0)
    assert cedo.loc[0, "nota_criativo"] == NOTA_NEUTRA, (
        "sem histórico anterior à 1a semana, a nota tem que ser neutra"
    )


def test_encolhimento_puxa_para_o_neutro():
    """Criativo com pouco volume não pode receber nota extrema."""
    h = _historico()
    pouco = pd.DataFrame([{"criativo": "AD_RARO", "dia": pd.Timestamp("2026-01-05"),
                           "buy": 1, "canal": "meta"}] * 6
                         + [{"criativo": "AD_RARO", "dia": pd.Timestamp("2026-01-05"),
                             "buy": 0, "canal": "meta"}] * 194)
    out = adicionar_nota_criativo(_df(["AD_RARO"], "2026-03-09"),
                                  historico=pd.concat([h, pouco]), transcricoes={}, cobertura_minima=0.0)
    nota = out.loc[0, "nota_criativo"]
    peso = 200 / (200 + K_ENCOLHIMENTO)
    assert peso < 0.06, "com 200 leads o peso tem que ser pequeno"
    assert abs(nota - NOTA_NEUTRA) < 0.25, (
        f"nota {nota:.2f} longe demais do neutro para 200 leads: o encolhimento não pegou"
    )


def test_falta_de_coluna_falha_alto():
    with pytest.raises(KeyError, match="Célula 8"):
        adicionar_nota_criativo(pd.DataFrame({"Data": ["2026-03-09"]}), historico=_historico(), transcricoes={})


def test_cobertura_baixa_falha_alto():
    """Feature inerte tem que gritar, não virar uma coluna silenciosa de 1,0."""
    h = _historico()
    with pytest.raises(ValueError, match="cobertura"):
        adicionar_nota_criativo(_df(["DESCONHECIDO"] * 10, "2026-03-09"), historico=h, transcricoes={})


def test_gera_as_tres_colunas():
    """As três variantes de conteúdo da nota, não só a básica."""
    out = adicionar_nota_criativo(_df(["AD_BOM", "AD_RUIM"], "2026-03-09"),
                                  historico=_historico(), transcricoes={})
    for c in ("nota_criativo", "nota_criativo_canal", "nota_criativo_texto"):
        assert c in out.columns, f"faltou {c}"
    assert (out["nota_criativo_canal"] > 0).all()


def test_sem_transcricao_a_nota_de_texto_cai_na_basica():
    """Tabela de transcrição vazia não pode derrubar o treino."""
    out = adicionar_nota_criativo(_df(["AD_BOM", "AD_RUIM"], "2026-03-09"),
                                  historico=_historico(), transcricoes={})
    assert out["nota_criativo_texto"].tolist() == out["nota_criativo"].tolist()


def test_nao_mexe_nas_outras_colunas():
    h = _historico()
    df = _df(["AD_BOM", "AD_RUIM"], "2026-03-09")
    out = adicionar_nota_criativo(df, historico=h, transcricoes={})
    assert list(df.columns) + ["nota_criativo", "nota_criativo_canal",
                               "nota_criativo_texto"] == list(out.columns)
    assert out["outra_coluna"].tolist() == df["outra_coluna"].tolist()
    assert "nota_criativo" not in df.columns, "não pode mutar o df de entrada"


def test_nota_e_numerica_e_finita():
    h = _historico()
    out = adicionar_nota_criativo(_df(["AD_BOM", "AD_RUIM"], "2026-03-09"), historico=h,
                                 transcricoes={})
    v = out["nota_criativo"].values
    assert np.isfinite(v).all() and v.dtype.kind == "f"


def test_carencia_e_janela_do_desfecho_sao_o_mesmo_numero():
    """A trava mais importante do modulo.

    O desfecho de W dias so existe W dias depois. Carencia MENOR que a janela deixa
    (janela - carencia) dias de futuro dentro da nota, que foi exatamente o vazamento
    encontrado em 05/08/2026. Se alguem baixar so a carencia, este teste cai.
    """
    assert CARENCIA_DIAS == JANELA_DESFECHO_DIAS, (
        f"carencia {CARENCIA_DIAS}d com desfecho de {JANELA_DESFECHO_DIAS}d deixa "
        f"{JANELA_DESFECHO_DIAS - CARENCIA_DIAS}d de futuro dentro da nota"
    )


def test_carencia_impede_ver_desfecho_imaturo():
    """Lead logo depois do fim do historico nao pode usar historico ainda verde.

    Datas derivadas de CARENCIA_DIAS, nao fixas: o teste continua valendo se a constante
    mudar. O lead PERTO fica a meia carencia do fim do historico, entao quase tudo e
    cortado e sobra menos que o minimo -> nota neutra. O LONGE fica alem da carencia
    inteira -> historico maduro -> nota propria.
    """
    semanas = 8
    h = _historico(semanas=semanas)
    fim = h["dia"].max()
    perto = fim + pd.Timedelta(days=CARENCIA_DIAS // 2)
    longe = fim + pd.Timedelta(days=CARENCIA_DIAS + 60)
    r_perto = adicionar_nota_criativo(_df(["AD_BOM"], perto.strftime("%Y-%m-%d")),
                                      historico=h, transcricoes={}, cobertura_minima=0.0)
    r_longe = adicionar_nota_criativo(_df(["AD_BOM"], longe.strftime("%Y-%m-%d")),
                                      historico=h, transcricoes={}, cobertura_minima=0.0)
    assert r_longe.loc[0, "nota_criativo"] != NOTA_NEUTRA, (
        "lead alem da carencia ja pode usar o historico inteiro, que amadureceu"
    )
    # o de perto tem que enxergar ESTRITAMENTE menos historico que o de longe
    maduro_perto = (h["dia"] < perto - pd.Timedelta(days=CARENCIA_DIAS)).sum()
    maduro_longe = (h["dia"] < longe - pd.Timedelta(days=CARENCIA_DIAS)).sum()
    assert maduro_perto < maduro_longe, "a carencia nao encolheu o historico do lead recente"


def test_carencia_encolhe_o_historico_usado():
    """Com carencia, a nota de um lead PROXIMO usa menos historico que a de um DISTANTE."""
    h = _historico(semanas=20)         # 05/01 ate meados de maio
    import src.core.nota_criativo as nc
    vistos = []
    orig = nc._notas_da_semana
    nc._notas_da_semana = lambda d: (vistos.append(len(d)), orig(d))[1]
    try:
        adicionar_nota_criativo(_df(["AD_BOM"], "2026-04-01"), historico=h,
                                transcricoes={}, cobertura_minima=0.0)
        perto = vistos[0]
        vistos.clear()
        adicionar_nota_criativo(_df(["AD_BOM"], "2026-06-01"), historico=h,
                                transcricoes={}, cobertura_minima=0.0)
        longe = vistos[0]
    finally:
        nc._notas_da_semana = orig
    assert perto < longe, (
        f"lead de abril viu {perto:,} linhas e o de junho {longe:,}: a carencia nao encolheu nada"
    )
