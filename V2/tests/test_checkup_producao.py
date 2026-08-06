"""
Checkup de produção: a régua tem que ser TAXA, não contagem.

Este teste existe por causa de um susto real. Em 06/08/2026, com a captação
pausada, o envio ao Meta caiu de ~2.100 leads/dia para 3, e a primeira leitura foi
"quebrou no deploy de ontem". Não tinha quebrado: dos leads que chegaram, **todos
os de `facebook-ads` foram enviados**, e os de manychat, google-ads e orgânico não
são enviados por regra, porque o CAPI do Meta só recebe lead de origem Meta.

Contagem absoluta confunde pausa com pane, e nos dois sentidos: também esconderia
uma falha real num dia de volume alto. Por isso o checkup mede taxa sobre o
universo elegível, e por isso este arquivo trava esse critério.
"""

import re

import pytest

from scripts import checkup_producao as chk


def test_envio_ao_meta_e_medido_sobre_o_universo_ELEGIVEL():
    """A conta de envio não pode ter o total no denominador."""
    import inspect
    fonte = inspect.getsource(chk.fluxo_do_lead)
    assert 'elegiveis' in fonte, 'sumiu o universo elegível do cálculo'
    assert '100.0 * enviados / elegiveis' in fonte, (
        'a taxa de envio voltou a usar o total no denominador; isso confunde '
        'captação pausada com pipeline quebrado')
    assert '100.0 * enviados / recebidos' not in fonte


def test_o_universo_elegivel_e_so_origem_META():
    """Lead de google-ads, manychat ou orgânico não vai pro CAPI do Meta, e isso é
    regra, não falha. Se entrarem no denominador, a taxa despenca sem motivo."""
    fontes = {f.lower() for f in chk.FONTES_META}
    for deve in ('facebook-ads', 'facebook', 'instagram', 'ig', 'meta'):
        assert deve in fontes
    for nao_deve in ('google-ads', 'manychat', 'organic', 'youtube', 'tiktok',
                     'gruposantigos', 'bio'):
        assert nao_deve not in fontes, (
            f'"{nao_deve}" entrou como elegível ao CAPI do Meta e vai derrubar a taxa')


def test_scoring_exige_100_por_cento():
    """Lead sem score é buraco no fluxo em qualquer volume, então aqui a régua é
    absoluta mesmo: qualquer lead sem score é FALHA."""
    import inspect
    fonte = inspect.getsource(chk.fluxo_do_lead)
    assert 'OK if scoreados == recebidos else FALHA' in fonte


def test_cron_semanal_nao_e_cobrado_com_regua_de_diario():
    """Cobrar um cron semanal com limite de 26h gera alarme falso toda terça."""
    assert chk.PERIODO_ESPERADO_H['model-performance-weekly'] > 24 * 7
    assert chk.PERIODO_ESPERADO_H['refresh-rolling-reference-weekly'] > 24 * 7
    assert chk.PERIODO_ESPERADO_H['railway-polling'] <= 2


def test_checa_que_o_servico_continua_fechado():
    """Regressão de segurança dentro do checkup: já aconteceu do serviço reabrir
    sozinho, quando o deploy readicionou o acesso público pela flag."""
    import inspect
    fonte = inspect.getsource(chk.servico_fechado)
    assert 'build_opener()' in fonte, (
        'o teste de fechamento precisa usar um opener LIMPO; com o handler de '
        'identidade instalado ele testaria autenticado e passaria sempre')
    assert '(401, 403)' in fonte


def test_saida_e_util_em_cron():
    """Sai 1 quando algo falha, para poder ser agendado."""
    import inspect
    fonte = inspect.getsource(chk.main)
    assert 'return 1 if falhas else 0' in fonte
