"""Teto de CPL (Fase 3): valor por venda pela mistura real de gateways (cartão 2k +
boleto 50%) e teto = conversão × valor ÷ roas_alvo (breakeven). Puro (sem banco).

Rodável:  PYTHONPATH=. python tests/test_teto.py
"""
import pandas as pd

from src.monitoring.teto import value_per_sale_from_sales, teto_cpl, CARTAO_VALUE


def test_value_per_sale_mistura_real():
    # 2 cartão (guru/hotmart) + 3 boleto (asaas/tmb/boletex) → pct_cartao 0.4
    sales = pd.DataFrame({"gateway": ["guru", "hotmart", "asaas", "tmb", "boletex"]})
    r = value_per_sale_from_sales(sales)
    assert r["n_sales"] == 5
    assert r["pct_cartao"] == 0.4
    # 0.4×2000 + 0.6×1000 = 1400
    assert r["value_per_sale"] == 1400.0
    assert r["cartao_value"] == 2000.0 and r["boleto_value"] == 1000.0


def test_gateway_desconhecido_ignorado():
    sales = pd.DataFrame({"gateway": ["guru", "asaas", "pix_misterioso", None]})
    r = value_per_sale_from_sales(sales)
    assert r["n_sales"] == 2                 # só guru + asaas contam
    assert r["value_per_sale"] == 1500.0     # 0.5×2000 + 0.5×1000


def test_sem_vendas_vira_none():
    assert value_per_sale_from_sales(pd.DataFrame({"gateway": []}))["value_per_sale"] is None
    assert value_per_sale_from_sales(None)["value_per_sale"] is None


def test_teto_cpl_breakeven():
    # conversão 0.84% · valor R$1.357 · breakeven (roas 1) → teto ≈ R$11.40
    t = teto_cpl(0.0084, 1357.0, roas_alvo=1.0)
    assert round(t, 2) == 11.40
    # roas alvo 8 → teto 8× menor
    assert round(teto_cpl(0.0084, 1357.0, roas_alvo=8.0), 3) == round(11.3988 / 8, 3)
    # ingrediente ausente → None
    assert teto_cpl(None, 1357.0) is None
    assert teto_cpl(0.0084, None) is None


if __name__ == "__main__":
    for fn in (test_value_per_sale_mistura_real, test_gateway_desconhecido_ignorado,
               test_sem_vendas_vira_none, test_teto_cpl_breakeven):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")


# ===========================================================================
# CalculadoraDeTeto — a montagem que saiu dos dois relatórios (passo 1, 14/08/2026)
# ===========================================================================
# Estes testes existem para uma coisa só: provar que tirar a montagem de dentro dos
# relatórios NÃO mudou nenhum número entregue. O que eles comparam é a conta NOVA
# contra a conta ANTIGA reescrita à mão, sobre a referência real de 10/08/2026.

from src.monitoring.teto import (  # noqa: E402
    CalculadoraDeTeto, MOTIVO_OK, MOTIVO_SEM_CONVERSAO, MOTIVO_SEM_REFERENCIA,
    MOTIVO_SEM_VALOR_POR_VENDA, MOTIVO_SEGMENTO_VAZIO,
)

# Referência viva de 10/08/2026: 104.453 leads, 881 compradores, cartão 29,4%.
_DECIS = [(8732, 10), (8891, 27), (9402, 30), (10041, 50), (10284, 53),
          (10748, 76), (11116, 106), (11193, 140), (11645, 149), (12401, 240)]
_REF = {
    'as_of': '2026-08-10',
    'conversion': {
        'economics': {'value_per_sale': 1293.98, 'pct_cartao': 0.294},
        'by_decile': {f'D{i:02d}': {'leads': n, 'conv': k}
                      for i, (n, k) in enumerate(_DECIS, 1)},
        'by_bucket': {'Lead': {'rate': 0.008718526869597896},
                      'Champion': {'rate': 0.014331210191082803}},
    },
}


def _teto_do_jeito_antigo(pct_topo):
    """A conta EXATA que morava em `enrich_campaign_budget` antes do passo 1."""
    by_dec = _REF['conversion']['by_decile']
    vps = _REF['conversion']['economics']['value_per_sale']

    def _rate(keys):
        c = sum((by_dec.get(k) or {}).get('conv', 0) or 0 for k in keys)
        n = sum((by_dec.get(k) or {}).get('leads', 0) or 0 for k in keys)
        return (c / n) if n else None
    conv_hi = _rate(['D09', 'D10'])
    conv_lo = _rate([f'D{i:02d}' for i in range(1, 9)])
    exp_conv = (pct_topo / 100.0) * conv_hi + (1 - pct_topo / 100.0) * conv_lo
    return teto_cpl(exp_conv, vps, roas_alvo=1.0)


def test_montagem_nova_bate_com_a_antiga_em_toda_faixa():
    """O refator não pode mover NENHUM número. Se este teste cair, ele moveu."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    for pct in (0.0, 7.3, 25.0, 30.0, 50.0, 66.6, 100.0):
        assert calc.por_fatia_no_topo(pct).valor == _teto_do_jeito_antigo(pct), (
            f"o teto da fatia {pct}% mudou com o refator"
        )


def test_balde_bate_com_a_conta_antiga_do_resumo_diario():
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    for balde, taxa in _REF['conversion']['by_bucket'].items():
        assert calc.por_balde(balde).valor == teto_cpl(
            taxa['rate'], _REF['conversion']['economics']['value_per_sale'], roas_alvo=1.0)


def test_conversao_agrega_por_VOLUME_e_nao_por_media_das_taxas():
    """Somar compradores e somar leads antes de dividir, não tirar média das taxas.

    Média das taxas daria o mesmo peso a um decil de 8.732 leads e a outro de 12.401,
    e o resultado não seria a conversão de ninguém. Com esta referência a diferença é
    visível: ponderado dá 0,612% no D1-D8, e a média simples das 8 taxas dá 0,582%.
    """
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    ponderado = calc.por_fatia_no_topo(0.0).conversao
    media_simples = sum(k / n for n, k in _DECIS[:8]) / 8
    assert abs(ponderado - 0.006119) < 1e-5
    assert abs(ponderado - media_simples) > 1e-4        # os dois NÃO coincidem


def test_carimbo_da_referencia_viaja_junto():
    """Sem o carimbo, 'por que o teto era X naquele dia' fica sem resposta depois que
    a referência é reconstruída na segunda seguinte."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    assert calc.por_fatia_no_topo(30.0).referencia_as_of == '2026-08-10'
    assert calc.por_balde('Champion').referencia_as_of == '2026-08-10'


def test_cada_ingrediente_que_falta_tem_MOTIVO_proprio():
    """O achado que motivou o dataclass: 'não há teto' e 'não deu para calcular'
    eram indistinguíveis na tela do gestor. Cada falta agora se nomeia."""
    sem_ref = CalculadoraDeTeto.de_referencia_carregada(None)
    assert sem_ref.por_fatia_no_topo(30.0).motivo == MOTIVO_SEM_REFERENCIA
    assert not sem_ref.utilizavel

    sem_economia = CalculadoraDeTeto.de_referencia_carregada(
        {'as_of': 'x', 'conversion': {'by_decile': _REF['conversion']['by_decile']}})
    assert sem_economia.por_fatia_no_topo(30.0).motivo == MOTIVO_SEM_VALOR_POR_VENDA
    assert not sem_economia.utilizavel

    sem_decis = CalculadoraDeTeto.de_referencia_carregada(
        {'as_of': 'x', 'conversion': {'economics': {'value_per_sale': 1000.0}}})
    assert sem_decis.utilizavel                     # a BASE está de pé...
    assert sem_decis.por_fatia_no_topo(30.0).motivo == MOTIVO_SEM_CONVERSAO   # ...o segmento não

    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    assert calc.por_fatia_no_topo(None).motivo == MOTIVO_SEGMENTO_VAZIO
    assert calc.por_fatia_no_topo(30.0).motivo == MOTIVO_OK


def test_roas_alvo_e_parametro_da_calculadora_inteira():
    """O passo 2 sobe o alvo para 2,0 mudando UM valor, não N chamadas espalhadas."""
    breakeven = CalculadoraDeTeto.de_referencia_carregada(_REF)
    dobro = CalculadoraDeTeto.de_referencia_carregada(_REF, roas_alvo=2.0)
    a, b = breakeven.por_fatia_no_topo(30.0), dobro.por_fatia_no_topo(30.0)
    assert abs(a.valor / 2 - b.valor) < 1e-9
    assert b.roas_alvo == 2.0        # o alvo viaja no resultado, para o render explicar
