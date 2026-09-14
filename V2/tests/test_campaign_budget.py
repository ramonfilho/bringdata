"""Fase 3b: gatilho de orçamento por breakeven nas campanhas (utm_quality).

CPL (gasto ÷ leads, de ad_spend) vs teto (conversão esperada da campanha × valor).
Campanha barata p/ a qualidade dela → 'aumentar'; cara → 'reduzir'. Frozen → no-op.
Puro: fakes de read_rolling_reference e read_ad_spend (sem banco).

Rodável:  PYTHONPATH=. python tests/test_campaign_budget.py
"""
import os
from datetime import date

import pandas as pd

import src.data.reference_reader as rr
import src.data.ad_spend_reader as ads
from src.monitoring.utm_quality import enrich_campaign_budget

# Referência: D9-D10 convertem 2,5% ; D1-D8 convertem 0,5% ; venda vale R$1.320.
_REF = {'conversion': {
    'by_decile': {
        'D09': {'conv': 20, 'leads': 1000}, 'D10': {'conv': 30, 'leads': 1000},
        **{f'D{i:02d}': {'conv': 5, 'leads': 1000} for i in range(1, 9)},
    },
    'economics': {'value_per_sale': 1320.0},
}}


def _fake_spend(s, e, client_id='devclub'):
    return pd.DataFrame([
        {'platform': 'meta', 'account_id': 'x', 'campaign_id': '1', 'campaign_name': 'CAMP A',
         'spend_date': s, 'spend': 1000.0, 'leads': 100, 'impressions': 0, 'clicks': 0},
        {'platform': 'meta', 'account_id': 'x', 'campaign_id': '2', 'campaign_name': 'camp b',
         'spend_date': s, 'spend': 1000.0, 'leads': 100, 'impressions': 0, 'clicks': 0},
    ])


def _run(rows):
    _o1, _o2 = rr.read_rolling_reference, ads.read_ad_spend
    rr.read_rolling_reference = lambda cid: _REF
    ads.read_ad_spend = _fake_spend
    os.environ['REFERENCE_SOURCE'] = 'rolling'
    try:
        return enrich_campaign_budget(rows, win_start=date(2026, 7, 21), win_end=date(2026, 7, 29))
    finally:
        rr.read_rolling_reference, ads.read_ad_spend = _o1, _o2
        os.environ.pop('REFERENCE_SOURCE', None)


def test_sinal_por_meta_de_roas():
    # A linha carrega a DISTRIBUIÇÃO de decis da campanha, não só a fatia no topo:
    # é ela que distingue uma campanha D7-D8 de uma D1-D2 (ver monitoring/teto.py).
    rows = [
        {'utm': 'CAMP A', 'decis': {'D09': 40, 'D10': 40, 'D01': 10, 'D02': 10}},
        {'utm': 'Camp B', 'decis': {'D09': 5, 'D10': 5, 'D01': 45, 'D02': 45}},
    ]
    _run(rows)
    # CAMP A: cpl=10 ; exp=(80×0,025 + 20×0,005)/100=0,021 ; teto=0,021×1320/2=13,86
    assert rows[0]['cpl'] == 10.0 and rows[0]['budget_signal'] == 'aumentar'
    assert abs(rows[0]['teto_cpl'] - 13.86) < 0.05
    # Camp B: exp=(10×0,025 + 90×0,005)/100=0,007 ; teto=0,007×1320/2=4,62 → reduzir
    assert rows[1]['budget_signal'] == 'reduzir'
    assert abs(rows[1]['teto_cpl'] - 4.62) < 0.05
    # ROAS alvo 2,0 (não mais breakeven): o teto entregue é METADE do de antes.
    assert rows[0]['teto_roas_alvo'] == 2.0
    # A LINHA SE EXPLICA SOZINHA: além do valor, os dois números que o produziram e a
    # procedência. É deliberado — a tabela da referência é reescrita quando o mesmo fim
    # de janela é recalculado, então recibo que só aponta pra ela leva a um endereço
    # cujo conteúdo pode ter mudado.
    assert abs(rows[0]['teto_conversao'] - 0.021) < 1e-9
    assert rows[0]['teto_valor_por_venda'] == 1320.0
    assert rows[0]['teto_motivo'] == 'ok'
    # e a configuração vigente, que é o único registro possível: chave de ambiente
    # muda o número e não aparece em commit nenhum.
    assert 'REFERENCE_SOURCE' in rows[0]['teto_config']


def test_casa_por_campaign_id_quando_nome_diverge():
    """O caso real que estava zerando o breakeven: o `utm_campaign` do lead traz o
    id grudado no fim e o nome do Meta tem uma tag extra do A/B, então NENHUM nome
    casa — mas o `campaign_id` casa. Também confere a folga (teto − CPL)."""
    def _fake_spend_id(s, e, client_id='devclub'):
        return pd.DataFrame([
            {'platform': 'meta', 'account_id': 'x', 'campaign_id': '120245448615560390',
             'campaign_name': 'DEVLF | CAP | FRIO | FASE 04 | ... | 2026-06-18 | jul24_top30',
             'spend_date': s, 'spend': 1000.0, 'leads': 100, 'impressions': 0, 'clicks': 0},
        ])
    _o1, _o2 = rr.read_rolling_reference, ads.read_ad_spend
    rr.read_rolling_reference = lambda cid: _REF
    ads.read_ad_spend = _fake_spend_id
    os.environ['REFERENCE_SOURCE'] = 'rolling'
    try:
        rows = [{'utm': 'DEVLF | CAP | FRIO | FASE 04 | ... | 2026-06-18|120245448615560390',
                 'decis': {'D09': 40, 'D10': 40, 'D01': 10, 'D02': 10}}]
        enrich_campaign_budget(rows, win_start=date(2026, 7, 21), win_end=date(2026, 7, 29))
    finally:
        rr.read_rolling_reference, ads.read_ad_spend = _o1, _o2
        os.environ.pop('REFERENCE_SOURCE', None)
    # casou por id (nome não bateria): cpl=10 ; teto=13,86 ; folga=3,86 ; aumentar
    assert rows[0]['cpl'] == 10.0 and rows[0]['budget_signal'] == 'aumentar'
    assert abs(rows[0]['teto_cpl'] - 13.86) < 0.05
    assert abs(rows[0]['folga'] - 3.86) < 0.05


def test_folga_negativa_e_render():
    """Folga negativa quando o CPL passa do teto, e ela aparece no sufixo do render."""
    from src.monitoring.utm_quality import _budget_suffix
    e = {'cpl': 30.0, 'teto_cpl': 15.0, 'folga': -15.0}
    suf = _budget_suffix(e)
    assert 'folga -R$ 15,00' in suf and 'CPL R$ 30,00' in suf and 'teto R$ 15,00' in suf
    # folga positiva
    assert 'folga +R$ 5,00' in _budget_suffix({'cpl': 10.0, 'teto_cpl': 15.0, 'folga': 5.0})


def test_frozen_noop():
    os.environ.pop('REFERENCE_SOURCE', None)   # frozen
    rows = [{'utm': 'CAMP A', 'decis': {'D09': 80, 'D01': 20}}]
    out = enrich_campaign_budget(rows, win_start=date(2026, 7, 21), win_end=date(2026, 7, 29))
    assert 'budget_signal' not in out[0] and 'cpl' not in out[0]


def test_breakeven_e_o_definidor_no_render():
    """O breakeven FLIPA o critério de qualidade: campanha de %D9-D10 alto mas CPL
    acima do teto vai pra 📉 Reduzir; %D9-D10 baixo mas CPL barato vai pra 📈 Aumentar."""
    from src.monitoring.utm_quality import _render_twoline_top5
    top5 = {'bar_pct': 20.0, 'levels': {'creative': {'rows': []}, 'campaign': {'rows': [
        # qualidade ALTA (40% > 20%) mas cara (CPL 30 > teto 15) → reduzir
        {'utm': 'CAMP A', 'pct_d9_d10': 40.0, 'n': 200, 'cpl': 30.0, 'teto_cpl': 15.0, 'budget_signal': 'reduzir'},
        # qualidade BAIXA (10% < 20%) mas barata (CPL 5 < teto 12) → aumentar
        {'utm': 'CAMP B', 'pct_d9_d10': 10.0, 'n': 200, 'cpl': 5.0, 'teto_cpl': 12.0, 'budget_signal': 'aumentar'},
    ]}}}
    blocks = _render_twoline_top5(top5, top5, win_label='ontem', lf_label='LF',
                                  lf_state='ativo', n_win=200, nlf=200)
    secs = [b['text']['text'] for b in blocks if b.get('type') == 'section']
    aumentar = next(s for s in secs if 'Aumentar orçamento' in s)
    reduzir = next(s for s in secs if 'Reduzir orçamento' in s)
    assert 'R$ 5,00' in aumentar and 'teto R$ 12,00' in aumentar    # CAMP B, apesar de qualidade baixa
    assert 'R$ 30,00' in reduzir and 'teto R$ 15,00' in reduzir     # CAMP A, apesar de qualidade alta


if __name__ == "__main__":
    for fn in (test_casa_por_campaign_id_quando_nome_diverge,
               test_folga_negativa_e_render, test_frozen_noop,
               test_breakeven_e_o_definidor_no_render):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
