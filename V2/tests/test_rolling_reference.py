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


if __name__ == "__main__":
    for fn in (test_overall_e_por_decil_usam_tudo, test_canal_balde_so_com_utm,
               test_vazio_degrada_limpo, test_calibrador_monotono_e_calibrado):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
