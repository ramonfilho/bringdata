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
# CalculadoraDeTeto — cinco baldes de decil e ROAS alvo 2,0 (14/08/2026)
# ===========================================================================
# O teste de paridade que existia aqui (a conta nova batendo com a antiga) foi
# REMOVIDO DE PROPÓSITO: ele provava que o refator anterior não movia número, e este
# passo é justamente o que move. Manter os dois seria pedir que a conta nova fosse
# igual e diferente da antiga ao mesmo tempo. No lugar dele entram testes que fixam o
# comportamento NOVO, incluindo os valores publicados na documentação.

from src.monitoring.teto import (  # noqa: E402
    BALDES_DE_DECIL, CalculadoraDeTeto, ROAS_ALVO_PADRAO,
    MOTIVO_OK, MOTIVO_SEM_CONVERSAO, MOTIVO_SEM_DISTRIBUICAO,
    MOTIVO_SEM_REFERENCIA, MOTIVO_SEM_VALOR_POR_VENDA, MOTIVO_SEGMENTO_VAZIO,
)

# Referência viva de 10/08/2026: 104.453 leads, 881 compradores, cartão 29,4%.
_DECIS = [(8732, 10), (8891, 27), (9402, 30), (10041, 50), (10284, 53),
          (10748, 76), (11116, 106), (11193, 140), (11645, 149), (12401, 240)]
_VPS = 1293.98
_REF = {
    'as_of': '2026-08-10',
    'conversion': {
        'economics': {'value_per_sale': _VPS, 'pct_cartao': 0.294},
        'by_decile': {f'D{i:02d}': {'leads': n, 'conv': k}
                      for i, (n, k) in enumerate(_DECIS, 1)},
        'by_bucket': {'Lead': {'rate': 0.008718526869597896},
                      'Champion': {'rate': 0.014331210191082803}},
    },
}


def _so_no_balde(decis, n=1000):
    """Um segmento inteiramente dentro de um balde."""
    return {d: n // len(decis) for d in decis}


def test_roas_alvo_padrao_e_dois_e_nao_breakeven():
    """Decisão de negócio de 13/08/2026. Breakeven não é meta, é piso de sobrevivência.

    Fixado em teste porque a virada dobra o rigor de TODO teto entregue de uma vez, e
    um retorno silencioso pra 1,0 passaria despercebido no relatório."""
    assert ROAS_ALVO_PADRAO == 2.0


def test_cinco_baldes_distinguem_o_que_dois_baldes_achatavam():
    """O problema que este passo resolve, no caso mais concreto possível.

    Antes, tudo abaixo do D9 caía num balde só e recebia R$ 3,96. Um criativo
    inteiramente D7-D8 e outro inteiramente D1-D2 saíam com o MESMO teto, apesar de a
    conversão real deles diferir 5,2 vezes."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    baixo = calc.por_mistura_de_decis(_so_no_balde(('D01', 'D02')))
    alto = calc.por_mistura_de_decis(_so_no_balde(('D07', 'D08')))
    assert baixo.ok and alto.ok
    assert alto.valor > 5 * baixo.valor          # 5,2x na referência viva
    # e o teto único de antes ficava no meio dos dois, errando os DOIS lados
    teto_antigo = (sum(k for _, k in _DECIS[:8]) / sum(n for n, _ in _DECIS[:8])) * _VPS / 2
    assert baixo.valor < teto_antigo < alto.valor


def test_valores_dos_cinco_baldes_batem_com_a_documentacao():
    """Os R$ publicados em docs/TETO_DE_CPL_DECISOES.md, decisão 1. Se este teste cair,
    ou a conta mudou ou a documentação está mentindo — e as duas exigem ação."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    esperado = {'D1-D2': 1.36, 'D3-D4': 2.66, 'D5-D6': 3.97,
                'D7-D8': 7.13, 'D9-D10': 10.47}
    for nome, decis in BALDES_DE_DECIL:
        t = calc.por_mistura_de_decis(_so_no_balde(decis))
        assert abs(t.valor - esperado[nome]) < 0.01, f"balde {nome}: {t.valor:.2f}"


def test_mistura_pondera_pelo_volume_do_SEGMENTO():
    """Meio a meio entre o balde de baixo e o de cima cai no meio dos dois tetos."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    so_baixo = calc.por_mistura_de_decis({'D01': 100, 'D02': 100}).valor
    so_alto = calc.por_mistura_de_decis({'D09': 100, 'D10': 100}).valor
    meio = calc.por_mistura_de_decis({'D01': 50, 'D02': 50, 'D09': 50, 'D10': 50}).valor
    assert so_baixo < meio < so_alto
    assert abs(meio - (so_baixo + so_alto) / 2) < 0.01


def test_conversao_agrega_por_VOLUME_e_nao_por_media_das_taxas():
    """Somar compradores e somar leads antes de dividir, não tirar média das taxas.

    Média das taxas daria o mesmo peso a um decil de 8.732 leads e a outro de 12.401,
    e o resultado não seria a conversão de ninguém."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    d9d10 = calc.por_mistura_de_decis({'D09': 500, 'D10': 500}).conversao
    ponderado = (149 + 240) / (11645 + 12401)
    media_simples = (149 / 11645 + 240 / 12401) / 2
    assert abs(d9d10 - ponderado) < 1e-9
    assert abs(d9d10 - media_simples) > 1e-4         # os dois NÃO coincidem


def test_balde_sem_taxa_na_referencia_SAI_da_conta_em_vez_de_contar_zero():
    """Excluir é neutro; contar como conversão zero rebaixaria o teto sistematicamente
    toda vez que a referência tivesse um buraco — e teto rebaixado manda cortar verba
    de campanha saudável."""
    ref_furada = {'as_of': 'x', 'conversion': {
        'economics': {'value_per_sale': _VPS},
        'by_decile': {'D09': {'leads': 11645, 'conv': 149},
                      'D10': {'leads': 12401, 'conv': 240}},   # D01-D08 ausentes
    }}
    calc = CalculadoraDeTeto.de_referencia_carregada(ref_furada)
    so_topo = calc.por_mistura_de_decis({'D09': 500, 'D10': 500}).valor
    com_buraco = calc.por_mistura_de_decis({'D01': 9000, 'D09': 500, 'D10': 500}).valor
    assert com_buraco == so_topo      # os 9.000 sem taxa não puxaram o teto pra baixo


def test_balde_de_variante_usa_a_taxa_medida_e_o_roas_vigente():
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    for balde, taxa in _REF['conversion']['by_bucket'].items():
        assert calc.por_balde(balde).valor == teto_cpl(
            taxa['rate'], _VPS, roas_alvo=ROAS_ALVO_PADRAO)


def test_carimbo_da_referencia_viaja_junto():
    """Sem o carimbo, 'por que o teto era X naquele dia' fica sem resposta depois que a
    referência é reconstruída na segunda seguinte."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    assert calc.por_mistura_de_decis({'D05': 1}).referencia_as_of == '2026-08-10'
    assert calc.por_balde('Champion').referencia_as_of == '2026-08-10'


def test_cada_ingrediente_que_falta_tem_MOTIVO_proprio():
    """O achado que motivou o dataclass: 'não há teto' e 'não deu para calcular' eram
    indistinguíveis na tela do gestor. Cada falta agora se nomeia."""
    sem_ref = CalculadoraDeTeto.de_referencia_carregada(None)
    assert sem_ref.por_mistura_de_decis({'D05': 1}).motivo == MOTIVO_SEM_REFERENCIA
    assert not sem_ref.utilizavel

    sem_economia = CalculadoraDeTeto.de_referencia_carregada(
        {'as_of': 'x', 'conversion': {'by_decile': _REF['conversion']['by_decile']}})
    assert sem_economia.por_mistura_de_decis({'D05': 1}).motivo == MOTIVO_SEM_VALOR_POR_VENDA

    sem_decis = CalculadoraDeTeto.de_referencia_carregada(
        {'as_of': 'x', 'conversion': {'economics': {'value_per_sale': 1000.0}}})
    assert sem_decis.utilizavel                       # a BASE está de pé...
    assert sem_decis.por_mistura_de_decis({'D05': 1}).motivo == MOTIVO_SEM_CONVERSAO

    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    # distribuição AUSENTE (leitor no caminho legado) é diferente de segmento VAZIO
    assert calc.por_mistura_de_decis(None).motivo == MOTIVO_SEM_DISTRIBUICAO
    assert calc.por_mistura_de_decis({}).motivo == MOTIVO_SEGMENTO_VAZIO
    assert calc.por_mistura_de_decis({'D05': 0}).motivo == MOTIVO_SEGMENTO_VAZIO
    assert calc.por_mistura_de_decis({'D05': 1}).motivo == MOTIVO_OK


def test_roas_alvo_e_parametro_da_calculadora_inteira():
    """Mudar a meta de retorno é mudar UM valor, não N chamadas espalhadas."""
    dois = CalculadoraDeTeto.de_referencia_carregada(_REF)
    quatro = CalculadoraDeTeto.de_referencia_carregada(_REF, roas_alvo=4.0)
    a, b = dois.por_mistura_de_decis({'D09': 1}), quatro.por_mistura_de_decis({'D09': 1})
    assert abs(a.valor / 2 - b.valor) < 1e-9
    assert b.roas_alvo == 4.0        # o alvo viaja no resultado, pro render explicar
