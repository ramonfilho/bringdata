"""rolling_reference: conversão realizada da janela madura por decil/canal/balde e
re-ajuste do calibrador. Testa a agregação e a calibração com matched-df sintético
(sem banco): o decil usa TUDO, canal/balde só a fatia com UTM (a ponte sem UTM não
pode virar 'organic' falso), e o calibrador fica monotônico e calibrado.

Rodável:  PYTHONPATH=. python tests/test_rolling_reference.py
"""
import numpy as np
import pandas as pd

from src.monitoring.rolling_reference import (
    conversion_reference, fit_calibrator, MIN_SEGMENT_CONV, MIN_SEGMENT_LEADS,
)

# A fixture abaixo tem 6 leads. O piso de base de produção (MIN_SEGMENT_*) cortaria
# todo segmento dela, então os testes de AGREGAÇÃO desligam o piso de propósito: o que
# eles verificam é o fatiamento (canal/balde só com UTM), não tamanho de amostra.
_SEM_PISO = {"min_segment_conv": 0, "min_segment_leads": 0}

_BMAP = {"tags": [("LEADHQLB", "Challenger"), ("LEADQUALIFIED", "Champion")], "fallback": "Lead"}


def _matched():
    # 4 leads com UTM (2 meta, 2 google) + 2 da ponte SEM UTM (decil 8 e 1).
    return pd.DataFrame({
        "decil_challenger": pd.array([10, 2, 9, 5, 8, 1], dtype="Int64"),
        "score_challenger": [0.80, 0.20, 0.70, 0.40, 0.60, 0.10],
        "utm_source": ["facebook-ads", "facebook-ads", "google-ads", "google-ads", None, None],
        "utm_campaign": ["cap LEADHQLB", "cap x", "cap-go y", "cap-go z", None, None],
        "converted": [True, False, True, False, True, False],
    })


def test_overall_e_por_decil_usam_tudo():
    ref = conversion_reference(_matched(), bucket_map=_BMAP, **_SEM_PISO)
    assert ref["overall"] == {"leads": 6, "conv": 3, "rate": 0.5}
    assert ref["by_decile"]["D10"]["rate"] == 1.0
    assert ref["by_decile"]["D02"]["rate"] == 0.0
    # a ponte (decil 8, sem UTM) CONTA no decil — só fica fora de canal/balde
    assert ref["by_decile"]["D08"]["conv"] == 1


def test_canal_balde_so_com_utm():
    ref = conversion_reference(_matched(), bucket_map=_BMAP, **_SEM_PISO)
    assert ref["channel_bucket_coverage"] == {"leads_com_utm": 4, "leads_total": 6}
    assert set(ref["by_channel"]) == {"meta", "google"}   # sem 'organic' falso da ponte
    assert ref["by_channel"]["meta"]["leads"] == 2 and ref["by_channel"]["google"]["leads"] == 2
    # LEADHQLB → Challenger (1); resto cai no fallback Lead (3)
    assert ref["by_bucket"]["Challenger"]["leads"] == 1
    assert ref["by_bucket"]["Lead"]["leads"] == 3


def test_segmento_de_base_fina_fica_fora_da_referencia():
    """Piso de base: segmento pequeno não publica taxa própria.

    Regressão do teto de CPL de 03/08/2026: a taxa do Champion vinha de 7 vendas em
    438 leads (1,598%) e levava o teto dele a R$20,81, sendo o real ~R$9. Com o piso
    ligado (o default de produção) esse segmento simplesmente não entra, e o painel
    mostra "—" em vez de número inventado.
    """
    ref = conversion_reference(_matched(), bucket_map=_BMAP)   # piso de produção
    assert ref["by_channel"] == {}, ref["by_channel"]
    assert ref["by_bucket"] == {}, ref["by_bucket"]
    # overall e por decil NÃO dependem de segmento, seguem cheios.
    assert ref["overall"]["leads"] == 6
    assert ref["by_decile"]["D10"]["rate"] == 1.0
    # cobertura continua reportada, pra não parecer que não havia UTM
    assert ref["channel_bucket_coverage"] == {"leads_com_utm": 4, "leads_total": 6}


def test_piso_de_producao_exige_dezenas_de_vendas():
    # Trava os valores: taxa de ordem 1% precisa de base, senão o Δ e o teto são ruído.
    assert MIN_SEGMENT_CONV >= 30 and MIN_SEGMENT_LEADS >= 1000


def test_maturacao_default_e_o_ciclo_do_lancamento():
    """21 dias = captação 7d + CPL 6d + carrinho 7d.

    Era 60, e a folga jogava a janela madura inteira para antes do ledger
    (`registros_ml` nasce em 23/05/2026), derrubando a fatia com UTM para 6,6%.
    """
    from src.data.matured_window import DEFAULT_MATURATION_DAYS, matured_bounds
    from datetime import date
    assert DEFAULT_MATURATION_DAYS == 21
    ws, we = matured_bounds(as_of=date(2026, 8, 3))
    assert (ws.date(), we.date()) == (date(2026, 4, 14), date(2026, 7, 13))


def test_vazio_degrada_limpo():
    empty = pd.DataFrame(columns=["decil_challenger", "score_challenger",
                                  "utm_source", "utm_campaign", "converted"])
    ref = conversion_reference(empty, bucket_map=_BMAP)
    assert ref["overall"]["leads"] == 0 and ref["by_decile"] == {}


def test_calibrador_monotono_e_calibrado():
    m = _matched()
    cal = fit_calibrator(m)
    p = cal.transform(np.array([0.1, 0.4, 0.8]))
    assert p[0] <= p[1] <= p[2]  # monotônico: score maior → P(compra) maior
    # propriedade da calibração: média da P calibrada ≈ taxa observada na janela
    allp = cal.transform(m["score_challenger"].to_numpy(dtype=float))
    assert abs(float(allp.mean()) - float(m["converted"].mean())) < 0.15


def _matched_com_datas():
    """Fixture pra janela do CALENDÁRIO: leads com data de captação e de venda.

    Calendário sintético: DEV19 capta 01-07/06 e vende até 10/07 (ciclo de 40d,
    o caso real que motivou a mudança: 15,4% dos compradores dele depois do dia 21).
    """
    launches = {"DEV19": {"cap_start": "2026-06-01", "cap_end": "2026-06-07",
                          "vendas_start": "2026-07-04", "vendas_end": "2026-07-10"}}
    m = pd.DataFrame({
        # a) DEV19, compra no dia 30 da captação: o prazo fixo de 21d jogava fora
        # b) DEV19, compra DEPOIS do vendas_end: pertence ao lançamento seguinte
        # c) fora de calendário, compra no dia 15: piso de 21d segura
        # d) fora de calendário, compra no dia 30: passou do piso
        # e) DEV19, sem compra
        "data_captura": pd.to_datetime(["2026-06-02", "2026-06-05", "2026-05-10",
                                        "2026-05-10", "2026-06-03"]),
        "sale_date": pd.to_datetime(["2026-07-02", "2026-07-15", "2026-05-25",
                                     "2026-06-09", pd.NaT]),
        "converted": [True, True, True, True, False],
    })
    return m, launches


def test_janela_de_compra_vem_do_calendario():
    from datetime import date
    from src.monitoring.rolling_reference import _aplica_janela_do_calendario
    m, launches = _matched_com_datas()
    out = _aplica_janela_do_calendario(m, as_of=date(2026, 8, 1), launches=launches)
    assert len(out) == 5  # todas as janelas já fecharam em 01/08
    conv = out["converted"].tolist()
    assert conv[0] is True or conv[0] == True    # dia 30, dentro do vendas_end  # noqa: E712
    assert not conv[1]                           # depois do vendas_end
    assert conv[2]                               # piso: dia 15 conta
    assert not conv[3]                           # piso: dia 30 não conta
    assert not conv[4]                           # sem venda


def test_lead_de_janela_aberta_fica_fora_da_referencia():
    """Lead cujo lançamento ainda vende não pode entrar: a compra dele ainda pode
    acontecer, e gravá-lo agora subestimaria a taxa da referência."""
    from datetime import date
    from src.monitoring.rolling_reference import _aplica_janela_do_calendario
    m, launches = _matched_com_datas()
    # em 05/07 o DEV19 ainda vende (vendas_end 10/07): os 3 leads dele saem;
    # os 2 leads fora de calendário (limite = captação+21d, já passou) ficam.
    out = _aplica_janela_do_calendario(m, as_of=date(2026, 7, 5), launches=launches)
    assert len(out) == 2
    assert out["data_captura"].dt.strftime("%Y-%m-%d").tolist() == ["2026-05-10", "2026-05-10"]


def test_limites_de_compra_bate_com_a_regra_por_lead():
    """A versão vetorizada e a por-lead (`compra_conta_para_o_lead`) são a MESMA
    regra: para cada lead, comprar NO limite conta e um dia depois não conta."""
    from src.data.matured_window import compra_conta_para_o_lead, limites_de_compra
    m, launches = _matched_com_datas()
    lim = limites_de_compra(m["data_captura"], launches)
    for cap, lf, limite in zip(m["data_captura"], lim["lf"], lim["limite"]):
        assert compra_conta_para_o_lead(data_captura=cap, data_compra=limite,
                                        lf_name=lf, launches=launches)
        assert not compra_conta_para_o_lead(data_captura=cap,
                                            data_compra=limite + pd.Timedelta(days=1).to_pytimedelta(),
                                            lf_name=lf, launches=launches)


if __name__ == "__main__":
    for fn in (test_overall_e_por_decil_usam_tudo, test_canal_balde_so_com_utm,
               test_vazio_degrada_limpo, test_calibrador_monotono_e_calibrado,
               test_janela_de_compra_vem_do_calendario,
               test_lead_de_janela_aberta_fica_fora_da_referencia,
               test_limites_de_compra_bate_com_a_regra_por_lead):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")


def test_fator_de_rastreamento_decompoe_e_mede():
    """5 casadas + 4 conhecidas + 1 sumida → fator (5+1)/5 = 1,2. As conhecidas
    (outro funil) nunca entram na correção — é a Decisão 9."""
    from src.monitoring.rolling_reference import fator_de_rastreamento
    leads = pd.DataFrame({"email": [f"lead{i}@x.com" for i in range(5)],
                          "telefone": [None] * 5})
    vendas = pd.DataFrame({
        "email": [f"lead{i}@x.com" for i in range(5)]        # casadas
                 + [f"velho{i}@x.com" for i in range(4)]      # conhecidas
                 + ["fantasma@x.com"],                        # sumida
        "telefone": [None] * 10,
    })
    conhecidos = {f"velho{i}@x.com" for i in range(4)}
    t = fator_de_rastreamento(vendas, leads, conhecidos, set())
    assert t["casadas"] == 5 and t["conhecidas"] == 4 and t["sumidas"] == 1
    assert abs(t["factor"] - 1.2) < 1e-9


def test_fator_sem_venda_casada_nao_inventa_numero():
    from src.monitoring.rolling_reference import fator_de_rastreamento
    leads = pd.DataFrame({"email": ["lead@x.com"], "telefone": [None]})
    vendas = pd.DataFrame({"email": ["outro@x.com"], "telefone": [None]})
    assert fator_de_rastreamento(vendas, leads, set(), set()) is None


def test_fator_deduplica_por_pessoa_e_casa_por_telefone():
    """A mesma pessoa com 2 vendas conta uma vez; venda sem email casa pelo tel-8."""
    from src.monitoring.rolling_reference import fator_de_rastreamento
    leads = pd.DataFrame({"email": ["a@x.com"], "telefone": ["+55 11 91234-5678"]})
    vendas = pd.DataFrame({
        "email": ["a@x.com", "a@x.com", None],
        "telefone": [None, None, "5511912345678"],
    })
    t = fator_de_rastreamento(vendas, leads, set(), set())
    # a@x.com deduplicada; a venda por telefone casa com o mesmo lead
    assert t["casadas"] == 2 and t["sumidas"] == 0 and t["factor"] == 1.0
