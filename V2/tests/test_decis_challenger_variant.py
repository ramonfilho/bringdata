"""Régua própria do jul_24 na linha Challenger do painel de decis (desvio).

Quando o payload traz `challenger_variant`, a linha Challenger é pontuada na régua
DELE (decil jul_24) e comparada à baseline dele (19,6%), não à régua única abr_28.
Sem `challenger_variant`, mantém o comportamento antigo (abr_28). Puro (sem banco).

Rodável:  PYTHONPATH=. python tests/test_decis_challenger_variant.py
"""
from src.monitoring.digest import _slack_decis_window


def _decil(d9, d10, filler, total):
    d = {f'D{i:02d}': filler for i in range(1, 9)}
    d['D09'], d['D10'] = d9, d10
    return d


def _pct_baseline(d9, d10):
    # pct por decil somando 100; só D09/D10 importam pro teste
    rest = (100.0 - d9 - d10) / 8.0
    p = {f'D{i:02d}': rest for i in range(1, 9)}
    p['D09'], p['D10'] = d9, d10
    return {'pct': p, 'label': 'Top5 régua jul_24', 'n_leads': 49407}


def _info(*, with_variant: bool):
    # bucket Challenger na régua abr_28: 47 em D9-D10 de 322 → 14.6%
    chal_abr = {'distribution': _decil(27, 20, 32, 322), 'total': 322}
    info = {
        'distribution': _decil(40, 40, 115, 1000), 'total': 1000, 'window_label': 'LF64',
        'baseline_challenger': {'pct': {**{f'D{i:02d}': 7.16 for i in range(1, 9)},
                                        'D09': 16.0, 'D10': 12.4}, 'label': 'Top 5 ROAS'},
        'by_source': {'meta': {'distribution': _decil(40, 40, 115, 1000), 'total': 1000},
                      'google': {'distribution': _decil(0, 0, 0, 0), 'total': 0}},
        'by_optgoal': {
            'lead':    {'distribution': _decil(50, 50, 112.5, 1000), 'total': 1000},
            'champion':{'distribution': _decil(80, 60, 107.5, 1000), 'total': 1000},
            'challenger': chal_abr,
        },
    }
    if with_variant:
        # régua jul_24: 34 em D9-D10 de 322 → 10.6%
        info['challenger_variant'] = {
            'run_id': 'b085b636', 'total': 322,
            'distribution': _decil(20, 14, 36, 322),
            'baseline': _pct_baseline(11.2, 8.4),  # 19.6% em D9-D10
        }
    return info


def _text(blocks):
    return "\n".join(b.get('text', {}).get('text', '') for b in blocks if b.get('type') == 'section')


def test_challenger_usa_regua_jul24_quando_variante():
    B = []
    _slack_decis_window({'lead_quality': {'decil_distribution_current_launch': _info(with_variant=True)}},
                        B, 'current_launch')
    txt = _text(B)
    # a linha Challenger compara contra a baseline do jul_24 (19.6%), não abr_28 28.4%
    assert 'jul_24 19.6%' in txt
    # Δ = 10.6 - 19.6 = -9.0
    assert '-9.0' in txt
    # as outras linhas seguem no abr_28
    assert 'abr_28' in txt


def test_challenger_regua_unica_sem_variante():
    B = []
    _slack_decis_window({'lead_quality': {'decil_distribution_current_launch': _info(with_variant=False)}},
                        B, 'current_launch')
    txt = _text(B)
    # sem variante → Challenger fica na régua abr_28 (28.4%), sem menção a jul_24 na ref
    assert 'jul_24 19.6%' not in txt
    assert 'abr_28 28.4%' in txt


if __name__ == "__main__":
    for fn in (test_challenger_usa_regua_jul24_quando_variante,
               test_challenger_regua_unica_sem_variante):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
