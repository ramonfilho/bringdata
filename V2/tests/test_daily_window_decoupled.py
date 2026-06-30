"""Guarda-corpo: a linha "ontem" (janela) do relatório de criativo é DESACOPLADA
do rótulo de lançamento.

Regressão que motivou (29-30/06/2026): a linha do dia filtrava por `lf=<LF>` além
da data, então quando os leads de um dia se partiram entre dois rótulos de
lançamento (LF60 real + um "LF61" que o resolver inventou), metade ficou invisível
e o relatório mostrou o N do lançamento no lugar do N do dia. "Quantos entraram
ontem" não tem a ver com qual lançamento o sistema acha que está ativo.

Trava: a visão da JANELA roda com pin_lf=False (sem filtro de lf), e o builder do
diário (app._build_top5_window) passa pin_lf=False.
"""
import inspect
import re
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]


def test_funcoes_aceitam_pin_lf():
    """challenger_quality_by_utm e build_top5_comparison expõem o modo janela."""
    from src.data.scores_historicos import challenger_quality_by_utm
    from src.monitoring.utm_quality import build_top5_comparison

    assert 'pin_lf' in inspect.signature(challenger_quality_by_utm).parameters
    assert 'pin_lf' in inspect.signature(build_top5_comparison).parameters


def test_builder_do_diario_passa_pin_lf_false():
    """O builder da janela (ontem) não amarra no lançamento."""
    src = (V2_ROOT / "api" / "app.py").read_text()
    m = re.search(r"def _build_top5_window\(.*?(?=\ndef )", src, re.DOTALL)
    assert m, "_build_top5_window não encontrada em app.py"
    assert "pin_lf=False" in m.group(0), (
        "_build_top5_window deve chamar build_top5_comparison com pin_lf=False "
        "(visão do dia desacoplada do rótulo de lançamento)."
    )


def test_visao_lancamento_continua_amarrada_no_lf():
    """A linha 'Lançamento' (acumulado) continua presa ao lf — é sobre o LF."""
    src = (V2_ROOT / "api" / "app.py").read_text()
    m = re.search(r"def _build_top5_for\(.*?(?=\ndef )", src, re.DOTALL)
    assert m, "_build_top5_for não encontrada em app.py"
    # não pode ter virado pin_lf=False sem querer (manteria o acoplamento correto).
    assert "pin_lf=False" not in m.group(0), (
        "_build_top5_for (visão do lançamento) NÃO deve usar pin_lf=False — a "
        "linha 'Lançamento' é, por definição, presa ao lf."
    )
