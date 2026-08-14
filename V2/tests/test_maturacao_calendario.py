"""A maturação sai do número fixo e vem do calendário de lançamentos (14/08/2026).

Maturidade deixou de ser "passaram 21 dias" e virou "o carrinho do MEU lançamento já
fechou". O 21 continua existindo como PISO, para o lead que caiu fora de qualquer
janela de captação.

O que motivou: medido no calendário canônico, 6 dos 28 lançamentos fecham as vendas
depois do dia 21 do lead do dia 1. No LF45 (captação de 21 dias, vendas fechando 33
dias depois do primeiro lead) a janela fixa descartava 55,6% dos compradores DO PRÓPRIO
lançamento.
"""
from datetime import date

from src.data.matured_window import (
    MATURACAO_MAXIMA_DIAS, MATURACAO_MINIMA_DIAS,
    compra_conta_para_o_lead, lead_esta_maduro, maturacao_do_lancamento,
    maturacao_por_lancamento,
)

# Dois lançamentos REAIS do calendário, um padrão e um grande.
_LF46 = {'cap_start': '2026-02-24', 'cap_end': '2026-03-02', 'vendas_end': '2026-03-15'}
_LF45 = {'cap_start': '2026-02-03', 'cap_end': '2026-02-23', 'vendas_end': '2026-03-08'}
_CAL = {'LF46': _LF46, 'LF45': _LF45}


def test_lancamento_padrao_cabe_no_piso_e_o_grande_nao():
    """O 21 fixo funcionava para o formato padrão. É no grande que ele quebra."""
    assert maturacao_do_lancamento(_LF46) == 19 or maturacao_do_lancamento(_LF46) == MATURACAO_MINIMA_DIAS
    assert maturacao_do_lancamento(_LF45) == 33      # captação de 21 dias
    assert maturacao_do_lancamento(_LF45) > MATURACAO_MINIMA_DIAS


def test_sem_calendario_cai_no_PISO_e_nao_em_zero():
    """Lead fora de qualquer lançamento não pode virar 'maduro na hora'."""
    assert maturacao_do_lancamento(None) == MATURACAO_MINIMA_DIAS
    assert maturacao_do_lancamento({}) == MATURACAO_MINIMA_DIAS
    assert maturacao_do_lancamento({'cap_start': '2026-02-03'}) == MATURACAO_MINIMA_DIAS


def test_data_absurda_na_planilha_bate_no_TETO_em_vez_de_passar():
    """A planilha é editada à mão. Ano errado empurraria a janela madura meses para
    trás sem ninguém notar — é o tipo de erro que tem que bater num limite."""
    assert maturacao_do_lancamento(
        {'cap_start': '2026-02-03', 'vendas_end': '2027-03-08'}) == MATURACAO_MAXIMA_DIAS


def test_maturidade_e_o_carrinho_ter_fechado_nao_o_calendario_ter_virado():
    """O caso que o número fixo errava: lead do LF45 captado no dia 1.

    Passados 25 dias ele JÁ estaria maduro pela regra antiga (25 > 21), mas o carrinho
    do lançamento dele só fecha no dia 33. Contá-lo antes disso é contar um lead que
    ainda pode comprar como se ele já tivesse decidido não comprar."""
    captura = date(2026, 2, 3)
    assert not lead_esta_maduro(lf_name='LF45', data_captura=captura,
                                as_of=date(2026, 2, 28), launches=_CAL)   # dia 25
    assert lead_esta_maduro(lf_name='LF45', data_captura=captura,
                            as_of=date(2026, 3, 9), launches=_CAL)        # carrinho fechou


def test_lead_sem_lancamento_conhecido_usa_o_piso():
    captura = date(2026, 2, 3)
    assert not lead_esta_maduro(lf_name=None, data_captura=captura,
                                as_of=date(2026, 2, 20), launches=_CAL)
    assert lead_esta_maduro(lf_name=None, data_captura=captura,
                            as_of=date(2026, 3, 1), launches=_CAL)


def test_compra_conta_ate_o_fim_das_vendas_DAQUELE_lancamento():
    """Depois do carrinho fechar, o lead só volta a receber oferta no lançamento
    seguinte — outro evento, outra promessa. Creditar aquela venda ao criativo que o
    captou seria dar crédito pelo trabalho de outro."""
    captura = date(2026, 2, 3)
    ok = dict(data_captura=captura, lf_name='LF45', launches=_CAL)
    assert compra_conta_para_o_lead(data_compra=date(2026, 3, 7), **ok)    # véspera
    assert compra_conta_para_o_lead(data_compra=date(2026, 3, 8), **ok)    # último dia
    assert not compra_conta_para_o_lead(data_compra=date(2026, 3, 9), **ok)  # já é outro


def test_o_ganho_concreto_do_LF45():
    """A janela fixa cortava do dia 22 ao 33 do próprio lançamento. Este teste fixa
    exatamente esse intervalo, que é onde estavam 55,6% dos compradores dele."""
    captura = date(2026, 2, 3)
    for dia_da_compra in (date(2026, 2, 26), date(2026, 3, 1), date(2026, 3, 8)):
        assert (dia_da_compra - captura).days > MATURACAO_MINIMA_DIAS   # a antiga cortava
        assert compra_conta_para_o_lead(data_captura=captura, data_compra=dia_da_compra,
                                        lf_name='LF45', launches=_CAL)  # a nova conta


def test_compra_antes_da_captacao_nunca_conta():
    assert not compra_conta_para_o_lead(data_captura=date(2026, 2, 3),
                                        data_compra=date(2026, 2, 1),
                                        lf_name='LF45', launches=_CAL)


def test_a_nota_do_criativo_consome_a_MESMA_fonte():
    """Havia um 21 escrito à mão na nota e outro na fonte única. Coincidiam por sorte,
    e quando a fonte única foi de 60 para 21 em 07/08 só um dos dois se mexeu."""
    from src.core import nota_criativo
    assert nota_criativo.JANELA_DESFECHO_DIAS is MATURACAO_MINIMA_DIAS
    assert nota_criativo.CARENCIA_DIAS == nota_criativo.JANELA_DESFECHO_DIAS


def test_mapa_do_calendario_inteiro():
    m = maturacao_por_lancamento(_CAL)
    assert m['LF45'] == 33 and m['LF46'] == maturacao_do_lancamento(_LF46)
