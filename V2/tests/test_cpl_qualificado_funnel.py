"""CPL qualificado (gasto ÷ leads D9-D10) no funil do DM (_slack_unified_funnel).

Confere que o valor sai por variante (Meta e Google) e por canal (Meta),
reusando a contagem D9-D10 do payload de decis, e que degrada pra "—" sem
o payload de decis (nunca quebra o funil)."""
from src.monitoring.digest import _slack_unified_funnel


def _decil(**d9d10):
    base = {f'D{i:02d}': 0 for i in range(1, 11)}
    base.update(d9d10)
    return base


def _view(with_decis=True):
    v = {
        'funnel': {'unified_funnel': {'window': {'label': 'ontem', 'date_brt': '18/07'},
                                      'pipeline': {}}, 'data_quality': {}},
        'traffic': {
            'dia_anterior': {
                'spend': 6000.0, 'clicks': 1000, 'total_cadastros': 900,
                'por_variante': {
                    'Lead':     {'leads': 300, 'cpl': 20.0, 'conv_lp': 5.0},
                    'Champion': {'leads': 200, 'cpl': 25.0, 'conv_lp': 6.0},
                },
            },
            'por_variante_lf': {},
        },
        'google_funnel': {
            'total_spend': 1000, 'total_clicks': 100,
            'por_variante': {'Lead': {'leads': 50, 'cpl': 10.0, 'conv_lp': 4.0}},
            'por_variante_lf': {},
        },
    }
    if with_decis:
        v['lead_quality'] = {'decil_distribution_previous_day': {
            'by_source': {
                'meta':   {'distribution': _decil(D09=60, D10=40), 'total': 500},
                'google': {'distribution': _decil(D09=5, D10=5), 'total': 50},
            },
            'by_optgoal': {
                'lead':       {'distribution': _decil(D09=30, D10=20)},   # 50 D9-D10
                'champion':   {'distribution': _decil(D09=25, D10=15)},   # 40 D9-D10
                'challenger': {'distribution': _decil()},
            },
        }}
    return v


def _text(v):
    B = []
    _slack_unified_funnel(v, B)
    return "\n".join(b.get('text', {}).get('text', '') for b in B)


def test_meta_canal_cpl_qualificado():
    # gasto COM imposto = 20×300 + 25×200 = 11000 ÷ (60+40 D9-D10 Meta) = R$ 110,00
    assert "CPL qualif.    R$ 110,00" in _text(_view())


def test_meta_variante_cpl_qualificado():
    t = _text(_view())
    # Lead: 20 × 300 / 50 = 120,00 ; Champion: 25 × 200 / 40 = 125,00
    assert "CPLq R$ 120,00" in t
    assert "CPLq R$ 125,00" in t


def test_google_variante_usa_by_source_google():
    # Google Lead: 10 × 50 / (5+5) = R$ 50,00
    assert "CPLq R$ 50,00" in _text(_view())


def test_fail_soft_sem_decis_nao_quebra():
    t = _text(_view(with_decis=False))
    assert "CPLq R$ —" in t          # variantes mostram traço
    assert "CPL qualif." not in t    # sem linha de canal Meta (sem D9-D10)


if __name__ == "__main__":
    fns = [x for k, x in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn(); print(f"  [OK ] {fn.__name__}"); ok += 1
        except AssertionError as e:
            print(f"  [FALHOU] {fn.__name__}: {e!r}")
    print(f"\n{ok}/{len(fns)} passaram")
    raise SystemExit(0 if ok == len(fns) else 1)
