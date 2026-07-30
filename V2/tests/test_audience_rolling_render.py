"""Fase 1c: render das 2 tabelas reancoradas no DM (Drift A/B + por fonte, janela de
lançamento) com a referência rolante (Compr%) como coluna. Puro (sem banco).

Cobre: gate REFERENCE_SOURCE, coluna Compr% só quando há rolling_reference_pct,
frozen (default) → DM no-op e renderers sem a coluna extra.

Rodável:  PYTHONPATH=. python tests/test_audience_rolling_render.py
"""
import os

from src.monitoring.digest import (
    _slack_audience_rolling_dm, _slack_alert_audience_by_variant,
    _slack_alert_audience_by_source, _ref_cols_header, _ref_cols_cell,
)


def _variant_alert(window, *, rolling=True):
    return {
        'type': 'audience_profile_drift_by_variant',
        'details': {
            'window': window, 'window_label': 'LF64',
            'lead_n': 500, 'champion_n': 500, 'challenger_n': 500,
            'google_n': 100, 'outros_n': 10,
            'top_list': [{
                'feature_label': 'Gênero', 'category': 'Masculino',
                'reference_pct': 81.7,
                'rolling_reference_pct': 90.1 if rolling else None,
                'lead_pct': 88.0, 'lead_delta_pp': 6.3, 'lead_quality': 'neutro',
                'champion_pct': 89.0, 'champion_delta_pp': 7.3, 'champion_quality': 'ruim',
                'challenger_pct': 90.0, 'challenger_delta_pp': 8.3, 'challenger_quality': 'ruim',
                'direction': 'negative', 'winner': 'champion',
            }],
        },
    }


def _source_alert(window, *, rolling=True):
    return {
        'type': 'audience_profile_drift_by_source',
        'details': {
            'window': window, 'meta_n': 400, 'google_n': 120,
            'top_list': [{
                'feature_label': 'Gênero', 'category': 'Masculino',
                'reference_pct': 81.7,
                'rolling_reference_pct': 90.1 if rolling else None,
                'meta_pct': 88.0, 'meta_delta_pp': 6.3, 'meta_quality': 'ruim',
                'google_pct': 70.0, 'google_delta_pp': -11.7, 'google_quality': 'bom',
            }],
        },
    }


def _text(blocks):
    return "\n".join(b.get('text', {}).get('text', '') for b in blocks if b.get('type') == 'section')


def test_dm_noop_quando_frozen():
    os.environ.pop('REFERENCE_SOURCE', None)  # default = frozen
    blocks = []
    view = {'alerts': [_variant_alert('current_launch'), _source_alert('current_launch')]}
    _slack_audience_rolling_dm(view, blocks)
    assert blocks == []  # frozen → DM não mostra drift de público (comportamento atual)


def test_dm_rolling_mostra_2_tabelas_lancamento():
    os.environ['REFERENCE_SOURCE'] = 'rolling'
    try:
        blocks = []
        view = {'alerts': [
            _variant_alert('previous_day'),      # ontem NÃO entra
            _variant_alert('current_launch'),    # lançamento entra
            _source_alert('current_launch'),
        ]}
        _slack_audience_rolling_dm(view, blocks)
        txt = _text(blocks)
        assert 'Drift por A/B' in txt and 'Drift por Fonte' in txt
        assert 'Compr%' in txt          # coluna da referência rolante
        assert '90.1%' in txt           # valor do comprador rolante
        assert 'Lançamento Atual' in txt
        # ontem foi filtrado: só janela de lançamento
        assert 'Ontem' not in txt
    finally:
        os.environ.pop('REFERENCE_SOURCE', None)


def test_renderer_sem_rolling_nao_tem_coluna():
    # item sem rolling_reference_pct → has_rolling False → sem Compr%
    blocks = []
    _slack_alert_audience_by_variant(_variant_alert('current_launch', rolling=False), blocks)
    txt = _text(blocks)
    assert 'Compr%' not in txt and 'Top%' in txt


def test_ref_cols_helpers():
    assert _ref_cols_header(False).strip() == 'Top%'
    assert 'Compr%' in _ref_cols_header(True)
    assert _ref_cols_cell(81.7, None, False).strip() == '81.7%'
    cell = _ref_cols_cell(81.7, 90.1, True)
    assert '81.7%' in cell and '90.1%' in cell
    assert _ref_cols_cell(81.7, None, True).endswith('—')  # rolling ausente → —


if __name__ == "__main__":
    for fn in (test_dm_noop_quando_frozen, test_dm_rolling_mostra_2_tabelas_lancamento,
               test_renderer_sem_rolling_nao_tem_coluna, test_ref_cols_helpers):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
