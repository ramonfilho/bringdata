"""Fase 2: painel de decis com conversão esperada calibrada vs referência rolante
como COLUNAS extras (ConvEsp% + Δ rolante), mantendo %D9-D10 vs Top5.

Injeta a referência rolante via cache `v['_rolling_ref']` → sem banco. Cobre:
coluna nova presente quando há referência, e painel idêntico ao de hoje quando não há.

Rodável:  PYTHONPATH=. python tests/test_decis_rolling_render.py
"""
from src.monitoring.digest import _slack_decis_window


def _dist(d10, d09, rest):
    d = {f'D{i:02d}': rest for i in range(1, 9)}
    d['D09'] = d09
    d['D10'] = d10
    return d


def _view(rolling_ref):
    dist = _dist(200, 100, 87)          # total 1000
    meta_dist = _dist(120, 60, 53)      # total 600
    ggl_dist = _dist(140, 60, 25)       # total 400
    og_dist = _dist(80, 40, 35)         # total 400 (>= MIN_BUCKET_N)
    info = {
        'distribution': dist, 'total': sum(dist.values()), 'window_label': 'LF64',
        'baseline_challenger': {'label': 'Top 5 ROAS atribuível 60d',
                                'pct': {f'D{i:02d}': 10.0 for i in range(1, 11)}},
        'by_source': {
            'meta': {'distribution': meta_dist, 'total': sum(meta_dist.values())},
            'google': {'distribution': ggl_dist, 'total': sum(ggl_dist.values())},
        },
        'by_optgoal': {
            'lead': {'distribution': og_dist, 'total': sum(og_dist.values())},
            'champion': {'distribution': og_dist, 'total': sum(og_dist.values())},
            'challenger': {'distribution': og_dist, 'total': sum(og_dist.values())},
        },
    }
    return {'lead_quality': {'decil_distribution_current_launch': info}, '_rolling_ref': rolling_ref}


_RR = {'conversion': {
    'overall': {'rate': 0.0084},
    'by_decile': {f'D{i:02d}': {'rate': 0.001 * i} for i in range(1, 11)},
    'by_channel': {'meta': {'rate': 0.008}, 'google': {'rate': 0.011}},
    'by_bucket': {'Lead': {'rate': 0.005}, 'Champion': {'rate': 0.012}, 'Challenger': {'rate': 0.010}},
}}


def _text(blocks):
    return "\n".join(b.get('text', {}).get('text', '') for b in blocks if b.get('type') == 'section')


def test_frozen_igual_a_hoje():
    blocks = []
    _slack_decis_window(_view(None), blocks, 'current_launch')
    txt = _text(blocks)
    assert '%D9-D10' in txt and 'Δ vs ref' in txt   # métrica antiga intacta
    assert 'ConvEsp' not in txt                       # sem coluna nova


def test_rolling_adiciona_convesp():
    blocks = []
    _slack_decis_window(_view(_RR), blocks, 'current_launch')
    txt = _text(blocks)
    assert '%D9-D10' in txt          # métrica antiga PRESERVADA ao lado
    assert 'ConvEsp' in txt          # coluna nova
    assert 'Δ vs ref rolante' in txt
    assert '(rol ' in txt            # conversão realizada da referência inline
    # Total: mix concentrado em D10 (rate alta) → ConvEsp acima do overall 0.84%
    assert 'LF64' in txt


def test_rolling_por_balde_usa_by_bucket():
    # Lead/Champion/Challenger puxam a conversão realizada de by_bucket
    blocks = []
    _slack_decis_window(_view(_RR), blocks, 'current_launch')
    txt = _text(blocks)
    assert 'rol 0.50%' in txt or 'rol 1.20%' in txt or 'rol 1.00%' in txt  # Lead/Champion/Challenger


if __name__ == "__main__":
    for fn in (test_frozen_igual_a_hoje, test_rolling_adiciona_convesp,
               test_rolling_por_balde_usa_by_bucket):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
