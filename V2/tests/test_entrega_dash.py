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


def test_o_decil_so_e_lido_para_AGREGAR_nunca_por_lead():
    """A regra mudou em 06/08/2026: a consulta PODE ler o decil, mas só dentro das
    CTEs que calculam a qualidade agregada por criativo e por campanha. O que não
    pode é o decil de um lead sair na linha dele.

    Este teste separa as duas coisas, porque a diferença é fácil de perder de vista:
    o mesmo campo que é seguro somado é proibido individual."""
    # A consulta que monta a LINHA DO LEAD não pode nem tocar no decil.
    assert 'decil' not in prov.sql_fonte().lower(), (
        'o decil apareceu na consulta que monta a linha do lead')
    # A que monta o AGREGADO pode, e só dentro de agrupamento com corte mínimo.
    agg = prov.sql_qualidade()
    assert 'decil' in agg.lower() and 'GROUP BY' in agg and 'HAVING' in agg

    # Os demais campos de saída do modelo continuam totalmente fora das duas.
    baixo = (prov.sql_fonte() + agg).lower()
    for termo in ('lead_score', 'score_champion', 'score_challenger',
                  'decile_propensity', 'decile_roas', 'hotleads_hot'):
        assert termo not in baixo, f'a consulta da entrega referencia "{termo}"'


def test_nome_e_email_saem_por_decisao_do_operador():
    """Decisão de 06/08/2026: nome e e-mail SAEM. O time de tráfego já obtém esses
    campos por outras ferramentas, então retê-los aqui atrapalharia o cruzamento deles
    sem reduzir exposição real.

    O teste existe para a decisão ser explícita: se alguém tirar as colunas achando que
    protege, quebra o cruzamento do cliente sem ganho."""
    nomes = {n.lower() for n, _ in prov.colunas_da_tabela()}
    assert 'nome' in nomes and 'email' in nomes


def test_so_sai_o_dado_pessoal_que_foi_PEDIDO():
    """Nome, e-mail e telefone constam do pedido escrito do cliente, inclusive como
    chave de deduplicação ("mesma pessoa que se cadastra 2x conta 1"). Documento,
    endereço e afins não foram pedidos e não saem: ampliar dado pessoal é decisão
    consciente, uma de cada vez."""
    nomes = {n.lower() for n, _ in prov.colunas_da_tabela()}
    for pedido in ('nome', 'email', 'telefone'):
        assert pedido in nomes
    for nao_pedido in ('cpf', 'documento', 'endereco', 'cep', 'data_nascimento'):
        assert nao_pedido not in nomes, (
            f'dado pessoal que ninguém pediu entrou na entrega: {nao_pedido}')


def test_o_lead_id_deixou_de_ser_pseudonimo_e_isso_esta_escrito():
    """Com o e-mail na mesma linha, o hash com sal não protege mais nada e passa a
    valer só como chave estável de junção. Precisa estar escrito, senão alguém depois
    olha o hash e conclui que a tabela é anonimizada."""
    import inspect
    doc = inspect.getdoc(prov) or ''
    assert 'deixa de proteger' in doc, (
        'o módulo não avisa que o hash virou só chave de junção depois que o e-mail '
        'passou a sair na tabela')


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


def test_coluna_de_whatsapp_existe_e_sai_VAZIA():
    """A entrada no grupo de WhatsApp sai NULA em todas as linhas, de propósito.

    O dado existe (112.825 registros) mas a coleta parou em 23/06/2026. Entregar o
    dado congelado faria todo lead captado depois disso aparecer como `false`, ou
    seja "não entrou no grupo", o que é FALSO e levaria a decisão errada sobre canal.
    NULO quer dizer "não sei", que é a verdade.

    A coluna existe mesmo vazia para o dashboard já ser construído contando com ela:
    quando a coleta voltar, o campo se preenche sozinho, sem mexer no painel."""
    nomes = {n for n, _ in prov.colunas_da_tabela()}
    assert 'entrou_no_grupo' in nomes, 'sumiu a coluna de entrada no grupo'
    tipo = dict(prov.colunas_da_tabela())['entrou_no_grupo']
    assert tipo == 'boolean'
    assert 'NULL::boolean AS entrou_no_grupo' in prov.sql_fonte(), (
        'a coluna deixou de sair NULA; conferir se a coleta voltou antes de mudar '
        'isto, senão entrega dado congelado como se fosse atual')


# ── qualidade agregada por criativo: o que substitui a nota individual ───────

def test_qualidade_sai_AGREGADA_por_criativo_e_campanha():
    """O que orienta decisão de verba é a qualidade do anúncio, não a nota do lead.
    Sai como percentual dos leads daquele criativo nos dois decis mais altos, que é a
    mesma métrica do relatório diário que eles já recebem."""
    # Mora em tabela PRÓPRIA, não colada em cada lead: colar fazia 1.363 linhas
    # serem reescritas por dia em vez de 27, e repetia 58 valores em 250 mil linhas.
    nomes = {n for n, _ in prov.colunas_qualidade()}
    assert {'tipo', 'chave', 'pct_alta_qualidade'} <= nomes
    sql = prov.sql_qualidade()
    assert 'GROUP BY 1, 2 HAVING count(*) >=' in sql, 'o agregado deixou de ser agrupado'
    assert "'criativo'" in sql and "'campanha'" in sql


def test_agregado_tem_corte_MINIMO_de_leads():
    """Sem corte, um criativo com 1 lead publicaria o decil DAQUELE lead, que é
    exatamente o que a regra de não entregar score existe para impedir."""
    assert prov.MIN_LEADS_AGREGADO >= 30, (
        f'corte de {prov.MIN_LEADS_AGREGADO} leads é baixo demais: com poucos leads o '
        f'agregado vira o score individual disfarçado')
    sql = prov.sql_qualidade()
    assert sql.count(f'count(*) >= {prov.MIN_LEADS_AGREGADO}') >= 2, (
        'o corte precisa valer para criativo E campanha')


def test_decil_individual_continua_fora():
    """O agregado entra; a nota por lead não. As duas coisas convivem, e é fácil
    alguém achar que uma libera a outra."""
    nomes = {n.lower() for n, _ in prov.colunas_da_tabela()}
    nomes |= {n.lower() for n, _ in prov.colunas_qualidade()}
    for proibido in ('decil', 'lead_score', 'decil_champion'):
        assert proibido not in nomes


# ── carga incremental ────────────────────────────────────────────────────────

def test_a_chave_da_linha_nao_e_so_o_lead_id():
    """A mesma pessoa cadastrada em dias diferentes vira linhas diferentes: 253.502
    linhas para 234.814 e-mails distintos. Com lead_id sozinho como chave, essas
    18.688 linhas colidiriam e a carga jogaria fora cadastro legítimo."""
    assert prov.CHAVE == ("lead_id", "capturado_em")
    assert "PRIMARY KEY (lead_id, capturado_em)" in prov.ddl_tabela()


def test_refresh_e_INCREMENTAL_e_nao_refaz_a_tabela():
    """Medido: entram ~22 leads novos e ~5 compradores por dia, ou seja 27 linhas em
    253.502. Refazer tudo era reescrever a tabela inteira para mudar 0,01% dela."""
    import inspect
    fonte = inspect.getsource(prov.refresh)
    assert 'ON CONFLICT' in fonte, 'o refresh voltou a ser substituição total'
    # `DO UPDATE SET`, não `DO NOTHING`: com DO NOTHING a linha nova entra mas a
    # existente nunca muda, e a virada do `comprou` (que é o principal motivo de a
    # linha antiga mudar) jamais chegaria ao painel deles.
    assert 'DO UPDATE SET' in fonte, (
        'o upsert virou DO NOTHING: lead que passou a comprar não seria atualizado')
    assert 'DROP TABLE IF EXISTS' in fonte and '_stg' in fonte, 'sumiu a área de estágio'
    for proibido in (f'DROP TABLE IF EXISTS {prov.SCHEMA}.{prov.TABELA}"',
                     'RENAME TO'):
        assert proibido not in fonte, f'o refresh voltou a trocar a tabela: {proibido}'


def test_refresh_remove_o_que_sumiu_da_origem():
    """A origem é reconstruída periodicamente e a deduplicação pode mudar. Sem a
    remoção, linha que deixou de existir ficaria aqui para sempre e o painel contaria
    lead que a gente já não reconhece."""
    import inspect
    fonte = inspect.getsource(prov.refresh)
    assert 'DELETE FROM' in fonte and 'NOT EXISTS' in fonte


def test_refresh_so_conta_como_alterado_o_que_de_fato_mudou():
    """`IS DISTINCT FROM` trata nulo como valor. Com `<>` puro, toda linha com campo
    nulo apareceria como alterada todo dia e o relatório da carga viraria ruído."""
    import inspect
    assert 'IS DISTINCT FROM' in inspect.getsource(prov.refresh)


# ── campos novos que o pedido original citava ────────────────────────────────

@pytest.mark.parametrize('coluna', ['telefone', 'utm_medium', 'url_captura'])
def test_campo_pedido_pelo_cliente_esta_na_entrega(coluna):
    """Os três constavam do pedido escrito e tinham ficado de fora."""
    assert coluna in {n for n, _ in prov.colunas_da_tabela()}
