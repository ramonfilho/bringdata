"""Rótulo de campanha no relatório de criativo agora carrega o ID da campanha na
Meta (decisão do usuário, 27/07/2026): o gestor precisa do número pra achar a
campanha no gerenciador. O ID é a corrida de dígitos que fecha a UTM e vai SEMPRE
no fim do rótulo (o nome é o campo variável; alinhar números pelo fim exige isso).
Roda: python3 -m pytest V2/tests/test_campaign_id_label.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.monitoring.utm_quality import _short_campaign_name, _render_twoline_top5


def test_id_anexado_com_tag():
    # com tag legível (LEADHQLB) o ID vem depois, no fim
    out = _short_campaign_name(
        'DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-18 | LEADHQLB|120246616507840390')
    assert out == 'FRIO · 2026-06-18 · LEADHQLB · ID 120246616507840390'


def test_id_anexado_sem_tag():
    # sem tag de braço, o ID completo entra no lugar do antigo #6dígitos
    out = _short_campaign_name(
        'DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-25|120244621534140390')
    assert out == 'FRIO · 2026-05-25 · ID 120244621534140390'


def test_id_completo_nao_truncado():
    out = _short_campaign_name('DEVLF | CAP | FRIO | LEADHQLB|120248218324420390')
    assert '120248218324420390' in out          # ID inteiro, não os últimos 6
    assert '#' not in out                        # sem o antigo formato #140390


def test_campanha_sem_nome_mostra_id_inteiro():
    assert _short_campaign_name('120246616507840390') == 'campanha sem nome (ID 120246616507840390)'


def test_curtas_e_macro_sem_id():
    assert _short_campaign_name('devlf') == 'devlf'            # sem ID → nada a anexar
    assert _short_campaign_name('{{campaign.name}}|{{campaign.id}}') == 'macro não resolvido'
    assert _short_campaign_name('') == 'sem_utm'


def test_id_aparece_no_render_agrupado():
    # o ID tem que sobreviver até o texto final do Slack (render agrupado por ação)
    utm = 'DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-18 | LEADHQLB|120246616507840390'
    lf_rows = [{'utm': utm, 'pct_d9_d10': 40.0, 'status': 'acima', 'n': 300, 'avg_decil': 8.0}]
    top5 = {'bar_pct': 28.4, 'levels': {'creative': {'rows': []}, 'campaign': {'rows': lf_rows}}}
    blocks = _render_twoline_top5(
        top5, top5, win_label='ontem', lf_label='DEV21', lf_state='em captação',
        n_win=100, nlf=1000)
    blob = "\n".join(
        b['text']['text'] for b in blocks if b.get('type') == 'section')
    assert 'ID 120246616507840390' in blob


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
