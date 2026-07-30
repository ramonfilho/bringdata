"""Teto de CPL breakeven no funil do DM (Fase 3a-ii): a linha por variante e a de
canal ganham ' 🟢/🔴 teto R$Y' ao lado do CPLq, da referência rolante. Frozen (sem
ref) → só o CPLq (funil de hoje). Puro (sem banco: `_rolling_ref` pré-semeado em v).

Rodável:  PYTHONPATH=. python tests/test_funnel_teto.py
"""
from src.monitoring.digest import _slack_unified_funnel


def _base_v(rolling_ref):
    return {
        'funnel': {'unified_funnel': {'pipeline': {}}, 'data_quality': {}},
        'traffic': {
            'dia_anterior': {
                'spend': 1000, 'clicks': 500, 'total_cadastros': 300,
                'por_variante': {
                    'Lead':     {'leads': 100, 'cpl': 5.0,  'conv_lp': 10.0},
                    'Champion': {'leads': 200, 'cpl': 8.0,  'conv_lp': 12.0},
                },
            },
            'por_variante_lf': {},
        },
        'lead_quality': {'decil_distribution_previous_day': {
            'by_optgoal': {'lead':     {'distribution': {'D09': 5, 'D10': 5}},    # 10 D9-D10
                           'champion': {'distribution': {'D09': 10, 'D10': 10}}}, # 20
            'by_source':  {'meta':   {'distribution': {'D09': 15, 'D10': 15}},    # 30
                           'google': {'distribution': {'D09': 0, 'D10': 0}}},
        }},
        '_rolling_ref': rolling_ref,   # pré-semeado → _rolling_ref_for_render não bate no banco
    }


_ROLLING = {'conversion': {
    'by_bucket':  {'Lead': {'rate': 0.011}, 'Champion': {'rate': 0.0194}},
    'by_channel': {'meta': {'rate': 0.0112}},
    'economics':  {'value_per_sale': 1320.0},
}}


def _text(blocks):
    return "\n".join(b.get('text', {}).get('text', '') for b in blocks
                     if b.get('type') == 'section')


def test_teto_aparece_com_rolling():
    B = []
    _slack_unified_funnel(_base_v(_ROLLING), B)
    txt = _text(B)
    # Teto fica no CPL (todos os leads), não no CPLq. Lead: CPL R$5 ≤ teto
    # 0.011×1320=R$14,52 → 🟢 (lucra). CPLq segue plano.
    assert 'CPL R$ 5,00 🟢 teto R$ 14,52' in txt
    assert 'CPLq R$ 50,00' in txt
    # Champion: CPL R$8 ≤ teto 0.0194×1320=R$25,61 → 🟢
    assert '🟢 teto R$ 25,6' in txt
    # a linha "CPL qualif." do canal NÃO ganha teto (denominador D9-D10)
    assert 'D9-D10)  🟢' not in txt and 'D9-D10)  🔴' not in txt


def test_frozen_sem_teto():
    B = []
    _slack_unified_funnel(_base_v(None), B)   # sem referência → funil de hoje
    txt = _text(B)
    assert 'teto' not in txt
    assert 'CPLq R$ 50,00' in txt   # CPLq segue normal


if __name__ == "__main__":
    for fn in (test_teto_aparece_com_rolling, test_frozen_sem_teto):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
