"""A janela de deploy: dia útil, 09:00 às 18:00 em São Paulo, e nenhum carrinho aberto.

É o que substitui o clique humano nos environments (decisão do Ramon, 17/09/2026): o
gate responde "pode?" pelos números e a janela responde "é hora?".
"""
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import janela_de_deploy as j  # noqa: E402

SP = ZoneInfo("America/Sao_Paulo")


def _em(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=SP)


# 2026-09-15 é terça; 19 é sábado; 20 é domingo; 21 é segunda.
CAL = {"LF66": {"vendas_start": "2026-09-22", "vendas_end": "2026-09-28"},
       "LF40": {"vendas_start": "2025-12-08", "vendas_end": "2025-12-14"},
       "LF-sem-data": {"cap_start": "2026-01-01"},
       "LF-data-ruim": {"vendas_start": "12/09/2026", "vendas_end": "x"}}


def test_terca_de_manha_sem_carrinho_esta_aberta():
    d = j.decidir(_em(2026, 9, 15, 10), CAL)
    assert d.aberta and d.motivo == "dentro da janela" and d.proxima is None


def test_terca_a_noite_fecha_e_reabre_quarta_as_nove():
    d = j.decidir(_em(2026, 9, 15, 20, 15), CAL)
    assert not d.aberta
    assert "fora do horário (20:15" in d.motivo
    assert d.proxima == _em(2026, 9, 16, 9)


def test_sabado_fecha_e_reabre_segunda():
    d = j.decidir(_em(2026, 9, 19, 10), CAL)
    assert not d.aberta and "fim de semana (sábado)" in d.motivo
    assert d.proxima == _em(2026, 9, 21, 9)


def test_carrinho_aberto_fecha_a_janela_ate_o_dia_util_depois_do_fim():
    # 24/09 é quinta, dentro das vendas do LF66 (22 a 28); reabre terça 29/09.
    d = j.decidir(_em(2026, 9, 24, 11), CAL)
    assert not d.aberta and "carrinho aberto: LF66 (2026-09-22 a 2026-09-28)" in d.motivo
    assert d.proxima == _em(2026, 9, 29, 9)


def test_bordas_do_horario():
    assert j.decidir(_em(2026, 9, 15, 9, 0), CAL).aberta
    assert not j.decidir(_em(2026, 9, 15, 18, 0), CAL).aberta
    assert not j.decidir(_em(2026, 9, 15, 8, 59), CAL).aberta


def test_entradas_sem_data_ou_com_data_ruim_sao_ignoradas():
    assert j.carrinhos_abertos(CAL, date(2026, 1, 1)) == []
    assert j.carrinhos_abertos({}, date(2026, 9, 24)) == []


def test_madrugada_de_dia_util_reabre_no_mesmo_dia():
    d = j.decidir(_em(2026, 9, 15, 6), CAL)
    assert not d.aberta and d.proxima == _em(2026, 9, 15, 9)
