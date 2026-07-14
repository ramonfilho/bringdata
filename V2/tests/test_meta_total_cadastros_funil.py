"""Total de cadastros Meta no funil do digest.

Trava o conserto do "Meta 136": o split por variante conta só quem tem campanha
reconhecida (Lead/Champion/Challenger) e DESCARTA o resto, então o número dele é
um SUBCONJUNTO. Lido sozinho, dava a impressão de que a Meta trouxe um punhado de
leads. A linha "Cadastros" mostra o TOTAL por utm_source (mesma base do Google).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.digest import _slack_unified_funnel  # noqa: E402
from src.monitoring.payload_schema import PAYLOAD_SCHEMA  # noqa: E402


def _view(traffic):
    return {
        "funnel": {"unified_funnel": {"window": {"label": "ontem", "date_brt": "09/07"},
                                      "pipeline": {}}, "data_quality": {}},
        "traffic": traffic,
    }


def _funnel_text(view):
    blocks = []
    _slack_unified_funnel(view, blocks)
    return blocks[0]["text"]["text"]


def test_linha_cadastros_mostra_total_meta_e_nao_so_o_balde_lead():
    """Com 1071 cadastros e só 136 classificados como 'Lead', o funil precisa
    mostrar os 1071 — senão o leitor conclui que a Meta trouxe 136."""
    view = _view({
        "dia_anterior": {
            "spend": 10000, "clicks": 5000,
            "total_cadastros": 1071,
            "por_variante": {"Lead": {"leads": 136, "cpl": 1.5, "conv_lp": 10.0}},
        }
    })
    txt = _funnel_text(view)
    assert "Cadastros" in txt, "a linha de total de cadastros Meta sumiu do funil"
    assert "1,071" in txt, f"total Meta (1071) não apareceu no funil:\n{txt}"
    # o balde por variante segue existindo (é detalhe, não o total)
    assert "136" in txt
    # e o total vem ANTES do balde — senão o olho lê o subconjunto primeiro
    assert txt.index("Cadastros") < txt.index("136")


def test_sem_total_o_funil_nao_quebra():
    """Fail-soft: se a leitura de cadastros falhar, o funil sai como antes."""
    view = _view({
        "dia_anterior": {
            "spend": 10000, "clicks": 5000,
            "por_variante": {"Lead": {"leads": 136, "cpl": 1.5, "conv_lp": 10.0}},
        }
    })
    txt = _funnel_text(view)
    assert "Cadastros" not in txt
    assert "136" in txt


def test_chave_declarada_no_payload_schema():
    """O guard fail-loud derruba o digest (500) se a chave não estiver declarada.
    Gates B/C NÃO pegam isso — só o render ao vivo."""
    assert "traffic_metrics.dia_anterior.total_cadastros" in PAYLOAD_SCHEMA
