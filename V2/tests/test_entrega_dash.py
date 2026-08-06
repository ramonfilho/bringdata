"""
Entrega de dados para terceiro: o que NUNCA pode sair.

O time da Zanelato (agência de tráfego do DevClub) recebe uma tabela de leads num
banco separado. Score e decil são o núcleo do serviço e não saem, em forma nenhuma,
nem agrupados: trocar 10 decis por 4 letras não protege nada, porque com volume a
ordenação é recuperável, e a ordenação É o método.

Esta suíte trava o esquema da entrega no código. Adicionar coluna vira decisão
consciente com teste falhando junto, em vez de um campo que aparece numa carga e
ninguém nota.
"""

import pytest

from scripts import provisiona_dash_zanelato as prov


PROIBIDO = ('score', 'decil', 'decile', 'propensity', 'hot', 'quente', 'nota',
            'ranking', 'quartil', 'percentil')


def test_nenhuma_coluna_da_entrega_carrega_score_ou_decil():
    for nome, _ in prov.colunas_da_tabela():
        for termo in PROIBIDO:
            assert termo not in nome.lower(), (
                f'coluna "{nome}" cheira a saída do modelo; score e decil não saem')


def test_a_consulta_nao_le_score_nem_decil_da_origem():
    """Não basta a coluna não existir no destino: a consulta não pode nem tocar
    nessas colunas na origem, senão alguém as agrega sem querer."""
    sql = prov.sql_fonte().lower()
    for termo in ('lead_score', 'decil', 'score_champion', 'score_challenger',
                  'decile_propensity', 'decile_roas', 'hotleads_hot'):
        assert termo not in sql, f'a consulta da entrega referencia "{termo}"'


def test_a_entrega_nao_leva_dado_pessoal_direto():
    """Sai sem nome, e-mail e telefone. Eles são gestores de tráfego montando painel
    de criativo, e para isso não precisam saber quem é a pessoa."""
    nomes = {n.lower() for n, _ in prov.colunas_da_tabela()}
    for pii in ('email', 'e_mail', 'telefone', 'phone', 'nome', 'nome_completo', 'cpf'):
        assert pii not in nomes, f'coluna de dado pessoal na entrega: {pii}'


def test_o_identificador_e_hash_COM_SAL():
    """Sem sal, `sha256(email)` é reversível por quem já tem a lista de e-mails, que
    é justamente o caso de uma agência de tráfego: bastaria hashear a base deles e
    cruzar. O sal é o que transforma o `lead_id` em pseudônimo de verdade."""
    sql = prov.sql_fonte()
    assert 'sha256' in sql, 'o identificador deixou de ser hash'
    assert ':sal' in sql, 'o hash perdeu o sal e virou reversível'
    assert 'lower(l.email)' in sql, 'o hash precisa normalizar o e-mail antes'


def test_a_consulta_deduplica_por_lead():
    """Três pares de janelas de lançamento se sobrepõem em 2026 (DEV19 com LF43,
    LF44 com LF45, LF60 com LF61). Sem dedupe o lead do dia de emenda aparece DUAS
    vezes e infla a contagem do painel deles em ~3.100 linhas."""
    sql = prov.sql_fonte()
    assert 'DISTINCT ON (l.event_id)' in sql, 'sumiu o dedupe por lead'
    assert 'cap_start DESC' in sql, (
        'sumiu o critério de desempate: o dia de emenda é do lançamento que COMEÇA nele')


def test_escopo_e_2026():
    sql = prov.sql_fonte()
    assert "'2026-01-01'" in sql and "'2027-01-01'" in sql


def test_o_teste_de_aceitacao_cobre_as_tabelas_sensiveis():
    """A lista do que precisa dar `permission denied` não pode encolher em silêncio."""
    alvos = {t for _, t in prov.PROIBIDAS}
    for obrigatoria in ('public.registros_ml', 'public.scores_historicos',
                        'analytics.leads', 'analytics.cadastros',
                        'analytics.captacoes', 'analytics.sales'):
        assert obrigatoria in alvos, (
            f'{obrigatoria} saiu do teste de aceitação da entrega')


@pytest.mark.parametrize('chave,alias', prov.PESQUISA)
def test_cada_pergunta_da_pesquisa_vira_coluna(chave, alias):
    """O alias é o que a ferramenta de BI deles vê. Precisa existir na tabela e a
    chave precisa ser lida do jsonb."""
    assert alias in {n for n, _ in prov.colunas_da_tabela()}
    assert chave in prov.sql_fonte()
