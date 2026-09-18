"""A janela de deploy: dia útil, 09:00 às 18:00 em São Paulo.

É o que substitui o clique humano nos environments (decisão do Ramon, 17/09/2026): o
gate responde "pode?" pelos números e a janela responde "é hora?". O carrinho aberto
deixou de fechar a janela em 18/09/2026, também por decisão dele.
"""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import janela_de_deploy as j  # noqa: E402

SP = ZoneInfo("America/Sao_Paulo")


def _em(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=SP)


# 2026-09-15 é terça; 18 é sexta; 19 é sábado; 20 é domingo; 21 é segunda.


def test_terca_de_manha_esta_aberta():
    d = j.decidir(_em(2026, 9, 15, 10))
    assert d.aberta and d.motivo == "dentro da janela" and d.proxima is None


def test_terca_a_noite_fecha_e_reabre_quarta_as_nove():
    d = j.decidir(_em(2026, 9, 15, 20, 15))
    assert not d.aberta
    assert "fora do horário (20:15" in d.motivo
    assert d.proxima == _em(2026, 9, 16, 9)


def test_sabado_fecha_e_reabre_segunda():
    d = j.decidir(_em(2026, 9, 19, 10))
    assert not d.aberta and "fim de semana (sábado)" in d.motivo
    assert d.proxima == _em(2026, 9, 21, 9)


def test_carrinho_aberto_nao_fecha_mais_a_janela():
    # 18/09/2026 é sexta, dentro das vendas do LF67 (14 a 20/09): a janela abre mesmo assim.
    d = j.decidir(_em(2026, 9, 18, 11))
    assert d.aberta and d.motivo == "dentro da janela"


def test_a_janela_nao_depende_de_calendario_nem_de_banco():
    fonte = Path(j.__file__).read_text(encoding="utf-8")
    for termo in ("load_launches", "LAUNCHES_SOURCE", "vendas_start", "carrinhos_abertos"):
        assert termo not in fonte, termo


def test_bordas_do_horario():
    assert j.decidir(_em(2026, 9, 15, 9, 0)).aberta
    assert not j.decidir(_em(2026, 9, 15, 18, 0)).aberta
    assert not j.decidir(_em(2026, 9, 15, 8, 59)).aberta


def test_madrugada_de_dia_util_reabre_no_mesmo_dia():
    d = j.decidir(_em(2026, 9, 15, 6))
    assert not d.aberta and d.proxima == _em(2026, 9, 15, 9)
