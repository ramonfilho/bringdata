"""O bloco "Lançamento anterior" do DM tem que mostrar o lançamento ANTERIOR,
nunca o corrente de novo.

Contexto (auditoria 16/08/2026): desde 24/07 o DM mostrava o MESMO LF64 como
"Lançamento atual" (fim = data da execução) E "Lançamento anterior" (fim =
cap_end do calendário), com contagens diferentes (all-source vs pixel Meta).
Parecia dado corrompido; eram três coisas: o código reusava o rótulo do LF
ATIVO como se fosse o anterior (bug de seleção em api/app.py), o rótulo do
atual não dizia que a janela termina "hoje", e as duas bases de contagem
saíam com o mesmo nome "todas as fontes".

A seleção agora é derivada do calendário: o LF com maior cap_end estritamente
ANTES do cap_start do ativo. Este teste exercita a regra pura com o calendário
real de agosto (LF64 ativo → anterior tem que ser DEV21, nunca LF64/LF65).

Rodável sem pytest: python tests/test_previsao_lf_anterior.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

# Espelho fiel do calendário real (analytics.launch_calendar) na época do bug.
CALENDARIO = {
    'LF62':  {'cap_start': '2026-07-06', 'cap_end': '2026-07-12'},
    'LF63':  {'cap_start': '2026-07-13', 'cap_end': '2026-07-20'},
    'DEV21': {'cap_start': '2026-07-21', 'cap_end': '2026-08-03'},
    'LF64':  {'cap_start': '2026-08-07', 'cap_end': '2026-08-17'},
    'LF65':  {'cap_start': '2026-08-18', 'cap_end': '2026-08-24'},
}


def _lf_anterior(launches: dict, lf_ativo: str):
    """A MESMA regra implementada em api/app.py (bloco lf_anterior): maior
    cap_end estritamente antes do cap_start do ativo; nunca o próprio ativo."""
    cs_ativo = ((launches.get(lf_ativo) or {}).get('cap_start')
                if lf_ativo else None)
    nome = None
    if cs_ativo:
        cands = [(n, c) for n, c in launches.items()
                 if (c or {}).get('cap_end') and (c or {}).get('cap_start')
                 and c['cap_end'] < cs_ativo]
        if cands:
            nome = max(cands, key=lambda kv: kv[1]['cap_end'])[0]
    if nome == lf_ativo:
        nome = None
    return nome


def test_lf64_ativo_anterior_e_dev21():
    """O caso do bug: com LF64 ativo, o anterior é DEV21 — nunca o LF64 de novo."""
    assert _lf_anterior(CALENDARIO, 'LF64') == 'DEV21'


def test_nunca_devolve_o_proprio_ativo():
    for lf in CALENDARIO:
        assert _lf_anterior(CALENDARIO, lf) != lf


def test_lf65_ativo_anterior_e_lf64():
    """Quando o LF65 começar (18/08), o anterior passa a ser o LF64."""
    assert _lf_anterior(CALENDARIO, 'LF65') == 'LF64'


def test_primeiro_lf_do_calendario_nao_tem_anterior():
    assert _lf_anterior(CALENDARIO, 'LF62') is None


def test_ativo_fora_do_calendario_nao_quebra():
    assert _lf_anterior(CALENDARIO, 'LF99') is None
    assert _lf_anterior(CALENDARIO, None) is None
    assert _lf_anterior({}, 'LF64') is None


def test_regra_do_app_e_a_mesma_deste_teste():
    """Trava anti-deriva: o trecho de seleção em api/app.py precisa conter a
    regra 'cap_end < cap_start do ativo' e a guarda contra duplicar o ativo.
    Se alguém reescrever a seleção, este teste aponta o contrato."""
    src = ''.join(p.read_text() for p in [Path(__file__).resolve().parent.parent / 'api' / 'app.py'] + sorted((Path(__file__).resolve().parent.parent / 'api' / 'routers').glob('*.py')))  # app.py + routers
    assert "c['cap_end'] < _cs_ativo" in src
    assert 'nunca duplicar o LF corrente' in src


def test_rotulo_das_bases_distingue_pixel_meta():
    from src.monitoring.digest import _bases_md
    atual = _bases_md(5806, 5104)
    anterior = _bases_md(5492, 5104, base='pixel Meta')
    assert 'todas as fontes' in atual
    assert 'pixel Meta' in anterior
    assert 'todas as fontes' not in anterior


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
