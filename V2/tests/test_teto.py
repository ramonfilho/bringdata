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

# A referência que o leitor REALMENTE SERVE (as_of 03/08, janela até 13/07): 86.141
# leads, 700 compradores, cartão 35,0%.
#
# A fixture anterior era a de 10/08, e estava errada por um motivo que vale registrar:
# aquela linha foi construída com maturação de 60 dias, a política que o projeto
# abandonou em 07/08 por inflar o teto. O leitor ordena por fim de janela, e maturação
# curta termina mais tarde, então quem sai é a de 03/08. Calibrar o teste na linha que
# NÃO é servida é testar um número que ninguém recebe.
_DECIS = [(4922, 5), (5798, 21), (7058, 21), (7814, 39), (8254, 53),
          (9253, 53), (10371, 82), (10289, 111), (10859, 135), (11523, 180)]
_VPS = 1349.61
_REF = {
    'as_of': '2026-08-03',
    'conversion': {
        'economics': {'value_per_sale': _VPS, 'pct_cartao': 0.350},
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

    Antes, tudo abaixo do D9 caía num balde só. Um criativo inteiramente D7-D8 e outro
    inteiramente D1-D2 saíam com o MESMO teto, apesar de a conversão real deles diferir
    várias vezes.

    O LIMIAR AQUI É 3x, E NÃO 5x, por uma correção de 14/08/2026: o 5x vinha da
    referência de 10/08, que não é a servida. Na servida a razão é 3,85x. O limiar é
    deliberadamente FROUXO em relação ao valor medido — ele existe para provar que os
    extremos estão longe o bastante para o balde único ser um erro operacional, não
    para congelar um número que muda a cada reconstrução da referência. O valor exato
    de cada balde é fixado no teste seguinte, que é onde ele deve ser cobrado."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    baixo = calc.por_mistura_de_decis(_so_no_balde(('D01', 'D02')))
    alto = calc.por_mistura_de_decis(_so_no_balde(('D07', 'D08')))
    assert baixo.ok and alto.ok
    assert alto.valor > 3 * baixo.valor
    # e o teto único de antes ficava no meio dos dois, errando os DOIS lados
    teto_antigo = (sum(k for _, k in _DECIS[:8]) / sum(n for n, _ in _DECIS[:8])) * _VPS / 2
    assert baixo.valor < teto_antigo < alto.valor


def test_valores_dos_cinco_baldes_batem_com_a_documentacao():
    """Os R$ publicados em docs/interno/TETO_DE_CPL_DECISOES.md, decisão 1. Se este teste cair,
    ou a conta mudou ou a documentação está mentindo — e as duas exigem ação."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    esperado = {'D1-D2': 1.64, 'D3-D4': 2.72, 'D5-D6': 4.09,
                'D7-D8': 6.30, 'D9-D10': 9.50}
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
    """Dentro do balde, soma compradores e soma leads antes de dividir.

    Média das taxas daria o mesmo peso a um decil de 4.922 leads e a outro de 5.798, e
    o resultado não seria a conversão de ninguém. O caso exercitado é o D1-D2, onde os
    dois decis têm volumes e taxas bem diferentes (5/4.922 contra 21/5.798) — nos
    baldes de cima os volumes são parecidos e as duas contas quase coincidem, o que
    faria o teste passar por coincidência da fixture em vez de por acerto do código."""
    calc = CalculadoraDeTeto.de_referencia_carregada(_REF)
    obtido = calc.por_mistura_de_decis({'D01': 50, 'D02': 50}).conversao
    (n1, k1), (n2, k2) = _DECIS[0], _DECIS[1]
    ponderado = (k1 + k2) / (n1 + n2)
    media_simples = (k1 / n1 + k2 / n2) / 2
    assert abs(obtido - ponderado) < 1e-12          # é o ponderado, exato
    assert obtido != media_simples                  # e NÃO é a média das taxas
    assert abs(ponderado - media_simples) > 1e-4    # e a diferença é operacionalmente real


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
    assert calc.por_mistura_de_decis({'D05': 1}).referencia_as_of == _REF['as_of']
    assert calc.por_balde('Champion').referencia_as_of == _REF['as_of']


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


# ===========================================================================
# PROCEDÊNCIA — de onde saiu este número (14/08/2026)
# ===========================================================================

def test_a_linha_do_teto_se_explica_sozinha():
    """A tabela da referência é reescrita quando o mesmo fim de janela é recalculado
    (`ON CONFLICT DO UPDATE`). Um recibo que só APONTASSE pra ela levaria a um endereço
    cujo conteúdo pode ter mudado depois — e quem investigasse leria números diferentes
    dos que foram usados, sem nada avisando. Por isso os dois números viajam junto."""
    t = CalculadoraDeTeto.de_referencia_carregada(_REF).por_mistura_de_decis({'D09': 1})
    assert t.conversao is not None and t.valor_por_venda is not None
    assert abs(t.valor - t.conversao * t.valor_por_venda / t.roas_alvo) < 1e-9


def test_o_identificador_da_referencia_desempata_o_que_a_data_nao():
    """Em 03/08/2026 duas reconstruções gravaram a mesma data: uma com 86.141 leads (a
    servida, maturação 21) e outra com 107.986 (maturação 60, a política abandonada).
    Um carimbo que apontasse pras duas não seria carimbo."""
    ref = dict(_REF, referencia_id='2026-08-03T19:15')
    t = CalculadoraDeTeto.de_referencia_carregada(ref).por_mistura_de_decis({'D09': 1})
    assert t.referencia_id == '2026-08-03T19:15'
    assert t.referencia_id != t.referencia_as_of      # a data sozinha não bastava


def test_um_carimbo_de_codigo_responde_por_TODO_parametro_de_codigo():
    """K, número de baldes e fórmula do encolhimento não ganham coluna cada um: o
    commit responde por todos, inclusive pelos que ainda não existem. Coluna por
    parâmetro é coluna que alguém esquece de acrescentar no parâmetro seguinte."""
    t = CalculadoraDeTeto.de_referencia_carregada(_REF).por_mistura_de_decis({'D09': 1})
    assert t.codigo is not None and 'origem' in t.codigo
    # 'git' na máquina de desenvolvimento, 'imagem' no contêiner, 'desconhecida' se
    # não houver nenhum dos dois — e ter o buraco NOMEADO vale mais que um None solto.
    assert t.codigo['origem'] in ('git', 'imagem', 'desconhecida')


def test_a_configuracao_vigente_viaja_porque_git_nao_a_ve():
    """Chave de ambiente muda o número e não deixa rastro em commit nenhum. Já custou
    caro: um deploy ligou REFERENCE_SOURCE=rolling de um template sujo, sem ninguém
    pedir. É a única das três procedências sem outra fonte a consultar depois."""
    import os
    from src.monitoring.teto import CHAVES_QUE_MUDAM_O_TETO
    salvo = os.environ.get('REFERENCE_SOURCE')
    os.environ['REFERENCE_SOURCE'] = 'rolling'
    try:
        t = CalculadoraDeTeto.de_referencia_carregada(_REF).por_mistura_de_decis({'D09': 1})
        assert t.configuracao['REFERENCE_SOURCE'] == 'rolling'
        assert set(t.configuracao) == set(CHAVES_QUE_MUDAM_O_TETO)
    finally:
        if salvo is None:
            os.environ.pop('REFERENCE_SOURCE', None)
        else:
            os.environ['REFERENCE_SOURCE'] = salvo


def test_chave_ausente_vira_default_explicito_e_nao_buraco():
    """'(default)' diz 'ninguém definiu'. Célula vazia não diferencia isso de 'não
    conseguimos ler', que é a mesma confusão que o motivo do teto resolve."""
    import os
    salvo = os.environ.pop('LAUNCHES_SOURCE', None)
    try:
        t = CalculadoraDeTeto.de_referencia_carregada(_REF).por_mistura_de_decis({'D09': 1})
        assert t.configuracao['LAUNCHES_SOURCE'] == '(default)'
    finally:
        if salvo is not None:
            os.environ['LAUNCHES_SOURCE'] = salvo


def test_o_carimbo_funciona_sem_git_que_e_o_caso_do_conteiner():
    """O `.dockerignore` exclui `.git/`, então em produção não há repositório a quem
    perguntar. Sem a leitura do carimbo assado no build, `versao_do_codigo` devolveria
    'desconhecida' exatamente onde a procedência faz falta."""
    import os
    from src.core.git_info import versao_do_codigo
    salvo = os.environ.get('APP_COMMIT')
    os.environ['APP_COMMIT'] = 'abc1234def'
    try:
        v = versao_do_codigo()
        # Numa worktree o git existe e VENCE (é a verdade do instante); o que este
        # teste garante é que o carimbo nunca é ignorado quando o git falta.
        assert v['origem'] in ('git', 'imagem')
        if v['origem'] == 'imagem':
            assert v['commit'] == 'abc1234'
    finally:
        if salvo is None:
            os.environ.pop('APP_COMMIT', None)
        else:
            os.environ['APP_COMMIT'] = salvo


# ===========================================================================
# Fator de rastreamento (Decisão 9): a conversão medida sobe pelo fator MEDIDO no
# payload da referência antes de virar teto. Referência antiga (sem a chave) → 1,0.

def _ref_com_fator(fator):
    import copy
    ref = copy.deepcopy(_REF)
    ref['conversion']['tracking'] = {'factor': fator, 'casadas': 500,
                                     'conhecidas': 400, 'sumidas': 100}
    return ref


def test_fator_de_rastreamento_sobe_o_teto_e_fica_carimbado():
    sem = CalculadoraDeTeto.de_referencia_carregada(_REF).por_mistura_de_decis(_so_no_balde(('D09', 'D10')))
    com = CalculadoraDeTeto.de_referencia_carregada(_ref_com_fator(1.2)).por_mistura_de_decis(_so_no_balde(('D09', 'D10')))
    assert sem.fator_rastreamento == 1.0
    assert com.fator_rastreamento == 1.2
    # o invariante vale nos dois: valor = conversao × vps ÷ roas
    for t in (sem, com):
        assert abs(t.valor - t.conversao * t.valor_por_venda / t.roas_alvo) < 1e-9
    # e o teto com fator é exatamente 1,2× o sem fator
    assert abs(com.valor / sem.valor - 1.2) < 1e-9
    assert abs(com.conversao / sem.conversao - 1.2) < 1e-9


def test_referencia_antiga_sem_tracking_se_comporta_como_antes():
    t = CalculadoraDeTeto.de_referencia_carregada(_REF).por_mistura_de_decis(_so_no_balde(('D09', 'D10')))
    assert t.ok and t.fator_rastreamento == 1.0


def test_fator_invalido_degrada_pra_1():
    t = CalculadoraDeTeto.de_referencia_carregada(_ref_com_fator(-3)).por_mistura_de_decis(_so_no_balde(('D09', 'D10')))
    assert t.ok and t.fator_rastreamento == 1.0


# ===========================================================================
# Fórmula da unidade (Decisão 9): conv = cm × (peso × lift + (1 − peso)).

def test_unidade_estreante_fica_com_o_modelo():
    from src.monitoring.teto import conversao_prevista_da_unidade
    assert conversao_prevista_da_unidade(0.01, 0, 0, 0.0) == 0.01


def test_unidade_com_historico_grande_converge_pro_lift():
    from src.monitoring.teto import conversao_prevista_da_unidade
    # criativo 2x acima da época dele, com 40k leads: peso ~0,95
    prev = conversao_prevista_da_unidade(0.01, 40000, 400, 200.0, k=2000)
    assert 0.019 < prev < 0.0198  # perto de cm×2, sem nunca chegar (modelo não sai)


def test_unidade_lift_e_adimensional_o_nivel_vem_do_modelo():
    from src.monitoring.teto import conversao_prevista_da_unidade
    a = conversao_prevista_da_unidade(0.010, 5000, 60, 50.0)
    b = conversao_prevista_da_unidade(0.020, 5000, 60, 50.0)
    assert abs(b / a - 2.0) < 1e-9  # mercado dobra → previsão dobra, lift intacto


def test_unidade_sem_esperados_cai_no_modelo():
    from src.monitoring.teto import conversao_prevista_da_unidade
    assert conversao_prevista_da_unidade(0.01, 500, 3, 0.0) == 0.01
