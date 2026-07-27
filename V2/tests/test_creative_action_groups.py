"""Relatório de criativo agrupado por AÇÃO (decisão do usuário, 27/07/2026):
em vez de lista única/extremos, mostra TODAS as campanhas acima do alvo (aumentar
orçamento) e abaixo (reduzir), omitindo as dentro do alvo (só conta). Roda:
  python3 -m pytest V2/tests/test_creative_action_groups.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.monitoring.utm_quality import _guarded_status, _render_twoline_top5

BAR = 28.4


def _row(utm, pct, status, n=200, avg=6.0):
    return {'utm': utm, 'pct_d9_d10': pct, 'status': status, 'n': n, 'avg_decil': avg}


# ───────────────────────── classificador ────────────────────────────────────
def test_guarded_status_basico():
    assert _guarded_status(_row('a', 40, 'acima'), None, BAR) == 'acima'
    assert _guarded_status(_row('b', 8, 'abaixo'), None, BAR) == 'abaixo'
    assert _guarded_status(_row('c', 28, 'neutro'), None, BAR) == 'neutro'
    assert _guarded_status(None, None, BAR) == 'neutro'


def test_guarded_status_recencia_rebaixa_abaixo_para_neutro():
    # 1.4pp abaixo (27 vs 28.4) E melhorou ontem (33 > 27) → vira neutro
    st = _guarded_status(_row('c', 27.0, 'abaixo'), {'pct_d9_d10': 33.0}, BAR)
    assert st == 'neutro'
    # muito abaixo (8pp) mesmo melhorando → segue abaixo
    st2 = _guarded_status(_row('c', 20.0, 'abaixo'), {'pct_d9_d10': 21.0}, BAR)
    assert st2 == 'abaixo'


# ───────────────────────── agrupamento no render ────────────────────────────
def _blob(blocks):
    out = []
    for b in blocks:
        if b.get('type') == 'section':
            out.append(b['text']['text'])
        elif b.get('type') == 'context':
            out += [el.get('text', '') for el in b.get('elements', [])]
    return "\n".join(out)


def _make_top5(campaign_rows):
    return {'bar_pct': BAR, 'levels': {'creative': {'rows': []}, 'campaign': {'rows': campaign_rows}}}


def test_render_agrupa_por_acao_e_omite_neutro():
    lf_rows = [
        _row('camp_a', 40.0, 'acima'),                 # aumentar
        _row('camp_e', 33.0, 'acima'),                 # aumentar
        _row('camp_b', 8.0, 'abaixo', n=300),          # reduzir (bem abaixo)
        _row('camp_c', 27.0, 'abaixo'),                # guarda de recência → neutro (omite)
        _row('camp_d', 28.0, 'neutro'),                # neutro (omite)
    ]
    win_rows = [{'utm': 'camp_c', 'pct_d9_d10': 33.0, 'status': 'neutro', 'n': 50}]
    blocks = _render_twoline_top5(
        _make_top5(win_rows), _make_top5(lf_rows),
        win_label='ontem', lf_label='DEV21', lf_state='em captação', n_win=100, nlf=1000)
    blob = _blob(blocks)

    # dois grupos de campanha, rotulados por ação
    assert 'Aumentar orçamento' in blob
    assert 'Reduzir orçamento' in blob
    # acionáveis certas aparecem
    assert 'camp_a' in blob and 'camp_e' in blob   # aumentar
    assert 'camp_b' in blob                          # reduzir
    # as dentro do alvo (guardada + neutra) NÃO aparecem como linha
    assert 'camp_d' not in blob
    # camp_c foi rebaixada a neutro pela recência → não vai pra "reduzir"
    reduzir_idx = blob.find('Reduzir orçamento')
    assert 'camp_c' not in blob[reduzir_idx:]
    # conta as 2 dentro do alvo
    assert '2 campanhas dentro do alvo' in blob


def test_render_todas_no_alvo_sem_acao():
    lf_rows = [_row('camp_x', 28.0, 'neutro'), _row('camp_y', 29.0, 'neutro')]
    blocks = _render_twoline_top5(
        _make_top5([]), _make_top5(lf_rows),
        win_label='ontem', lf_label='DEV21', lf_state='em captação', n_win=100, nlf=1000)
    blob = _blob(blocks)
    assert 'todas dentro do alvo' in blob
    assert 'Aumentar orçamento' not in blob and 'Reduzir orçamento' not in blob


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
