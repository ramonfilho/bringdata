"""Trava o envio dos leads para o Supabase da agência.

O que estes testes protegem, em uma frase: que as 11 colunas cheguem na ordem certa,
que a janela seja de 90 dias, que a auditoria QUEBRE quando divergir, e que a carga
incremental nunca invente uma janela quando não sabe de onde partir.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import push_supabase_zanelato as p


def test_as_11_colunas_sao_as_que_o_cliente_pediu():
    """A tabela deles tem 13 colunas; duas são preenchidas por eles (`id`, que é
    identidade automática, e `recebido_em`, que tem default `now()`). Mandar qualquer
    uma das duas quebra a inserção ou sobrescreve o carimbo de recebimento, que é a
    marca d'água da carga incremental."""
    assert p.COLUNAS == ["nome", "email", "telefone", "source", "medium", "campaign",
                         "term", "content", "data", "tem_computador", "utm_url"]
    assert "id" not in p.COLUNAS, (
        '`id` é identidade automática no destino; mandar valor quebra a inserção')
    assert "recebido_em" not in p.COLUNAS, (
        '`recebido_em` é a MARCA D\'ÁGUA da carga incremental (max dele = nossa última '
        'gravação). Sobrescrever isso quebra o incremental de um jeito silencioso')


def _fontes(janela=False):
    """Devolve o SQL de cada braço do UNION, separados.

    Corta em `-- FONTE ` e não em `UNION ALL`: a CTE de URL dentro da entrega curada
    também usa `UNION ALL`, e cortar por ela partiria o braço 1 no meio.
    """
    sel = p._select(janela)
    partes = sel.split("-- FONTE ")
    assert len(partes) == 3, (
        f'esperava 2 fontes (curada + ledger vivo), achei {len(partes) - 1}')
    return partes[1], partes[2]


def _ordem_dos_apelidos(braco):
    """Em que ordem as 11 colunas saem deste braço.

    Olha só a PROJEÇÃO (o pedaço entre o `SELECT` e o `FROM` dele). Sem isso, o braço
    da entrega curada casa com os apelidos de dentro de `sql_fonte`, que é uma query
    inteira aninhada com as mesmas 11 palavras em outra ordem — e o teste reprovaria
    código correto.
    """
    import re
    corte = re.search(r"^\s*FROM\s", braco, re.M)
    assert corte, 'braço sem FROM'
    braco = braco[:corte.start()]
    posicoes = []
    for c in p.COLUNAS:
        # Sai com apelido (`... AS email`) ou com o nome cru (`q.nome,`). O espaçamento
        # entre a expressão e o AS é livre, daí a busca por padrão e não por texto fixo.
        m = re.search(rf"\bAS\s+{c}\b", braco) or re.search(rf"\bq\.{c}\b", braco)
        assert m, f'a coluna {c} não sai deste braço'
        posicoes.append((m.start(), c))
    return [c for _, c in sorted(posicoes)]


def test_a_ordem_do_SELECT_bate_com_a_ordem_das_COLUNAS():
    """A falha que este teste pega é a pior de todas aqui: se a ordem divergir, o
    INSERT continua funcionando (é tudo texto) e a agência recebe campanha na coluna de
    conteúdo. Ninguém vê erro, o painel deles só passa a mentir.

    Checa CADA braço do UNION, não o SELECT de fora, porque é ali que o erro nasce
    (ver o teste do casamento por posição, abaixo).
    """
    for i, braco in enumerate(_fontes(), start=1):
        assert _ordem_dos_apelidos(braco) == p.COLUNAS, (
            f'a fonte {i} emite as colunas em ordem diferente de COLUNAS')


def test_as_duas_FONTES_casam_por_POSICAO_e_por_isso_a_ordem_tem_que_ser_identica():
    """O `UNION ALL` do Postgres casa coluna por POSIÇÃO, não por nome do apelido.

    Se a fonte 2 emitir `telefone` onde a fonte 1 emite `nome`, o SQL continua válido
    (é tudo texto), o SELECT de fora continua chamando a primeira coluna de `nome`, e
    a agência recebe telefone na coluna de nome só nas linhas que vieram do ledger.
    Não há erro em lugar nenhum: metade da tabela fica trocada em silêncio.
    """
    curada, ledger = _fontes()
    assert _ordem_dos_apelidos(curada) == _ordem_dos_apelidos(ledger), (
        'as duas fontes do UNION emitem as colunas em ordens diferentes')


def test_a_janela_e_de_90_dias_nos_dois_modos():
    """O combinado com o cliente é 90 dias. Se a janela crescer sem ninguém mexer no
    combinado, a tabela deles engorda; se encolher, eles perdem histórico sem aviso."""
    assert p.DIAS == 90
    for janela in (False, True):
        sel = p._select(janela)
        # Verifica o FILTRO, não texto solto: a primeira versão deste teste passava
        # porque a expressão antiga (`interval '90 days'`) sobreviveu num COMENTÁRIO do
        # código, mesmo depois do filtro ter mudado. Teste que passa em comentário não
        # trava nada.
        assert f"(q.capturado_em AT TIME ZONE '{p.FUSO}')::date >= {p.CORTE_SQL}" in sel, (
            f'sumiu o recorte de {p.DIAS} dias no modo janela={janela}')


def test_o_recorte_e_por_DIA_e_nao_por_instante():
    """Foi este detalhe que produziu o falso positivo de +14 linhas em 10/08/2026.

    A origem filtrava por instante (`now() - interval '90 days'`) e o destino guarda a
    data só como dia. Entre a carga e a auditoria o relógio andou, linhas da fronteira
    saíram de um lado e ficaram no outro, e a auditoria acusou erro onde não havia.
    As três operações (carga, poda, auditoria) têm que usar a MESMA fronteira de dia.
    """
    sel = p._select(False)
    assert f"::date\n                 >= {p.CORTE_SQL}" in sel or \
           f"::date >= {p.CORTE_SQL}" in sel, 'o recorte voltou a ser por instante'
    # Descarta as linhas de comentário INTEIRAS. Remover só o marcador `--` deixaria o
    # texto do comentário no meio do SQL e o teste passaria (ou falharia) pelo motivo
    # errado — foi o que aconteceu na primeira versão deste teste.
    codigo = "\n".join(l for l in sel.splitlines() if not l.strip().startswith("--"))
    assert "now() - interval" not in codigo, (
        'sobrou filtro por instante no SQL de verdade, fora de comentário')


def test_a_data_sai_no_formato_que_a_coluna_deles_espera():
    """A coluna `data` no destino é TEXTO, não data. Deixar o Postgres formatar por
    conta dele faria o formato virar surpresa (e mudar com a configuração do servidor)."""
    sel = p._select(False)
    assert sel.count("'YYYY-MM-DD'") >= 2, (
        'cada fonte tem que formatar a data explicitamente')


def test_a_data_sai_em_HORARIO_DE_BRASILIA_nas_duas_fontes():
    """Este teste existe por causa de um "leads faltando" que não existia.

    Em 10/08/2026 a agência apontou 15 leads do dia 09/08 ausentes da entrega. 14
    estavam lá, datados 10/08, e todos os 14 tinham chegado entre 00:05 e 02:55 UTC —
    isto é, entre 21:05 e 23:55 de Brasília do dia 09. Desvio sistemático de 3 horas:
    todo lead que entrava depois das 21h aparecia no dia seguinte para ela.

    A causa não estava escrita no código: a conexão de leitura tem `TimeZone = UTC`, e
    `to_char(timestamptz, ...)` renderiza no fuso da SESSÃO. O UTC vinha do ambiente.
    Por isso o teste checa o fuso EXPLÍCITO no SQL — é a única forma de não depender de
    como o servidor está configurado.
    """
    for i, braco in enumerate(_fontes(), start=1):
        assert f"AT TIME ZONE '{p.FUSO}'" in braco, (
            f'a fonte {i} voltou a datar no fuso da sessão; em UTC, o lead da noite '
            f'aparece no dia seguinte para a agência')
    assert p.FUSO == "America/Sao_Paulo"


def test_o_ledger_declara_que_o_timestamp_dele_esta_em_UTC():
    """`registros_ml.created_at` é `timestamp WITHOUT time zone` guardando UTC, enquanto
    `analytics.leads.capturado_em` é `WITH time zone` (verificado em 10/08/2026). Num
    valor sem fuso, um `AT TIME ZONE` sozinho faz o Postgres assumir o fuso da sessão:
    daria 3 horas de erro, na direção contrária, e só nas linhas vindas do ledger.
    """
    _, ledger = _fontes()
    assert f"AT TIME ZONE 'UTC' AT TIME ZONE '{p.FUSO}'" in ledger, (
        'o braço do ledger precisa declarar UTC antes de converter, porque a coluna '
        'dele não guarda fuso')


def test_a_fronteira_da_janela_esta_no_MESMO_fuso_da_coluna_data():
    """Fronteira num fuso e valor em outro faz a linha da borda entrar na carga e sair
    na poda, a cada rodada, para sempre. Não daria erro nenhum: só uma linha piscando na
    tabela do cliente e uma auditoria contando trabalho pendente que nunca acaba."""
    assert f"AT TIME ZONE '{p.FUSO}'" in p.CORTE_SQL, (
        'a fronteira da janela voltou a ser calculada em outro fuso que não o da '
        'coluna `data`')
    sel = p._select(False)
    codigo = "\n".join(l for l in sel.splitlines() if not l.strip().startswith("--"))
    assert f"(current_date - {p.DIAS})" not in codigo, (
        'sobrou a fronteira antiga em UTC no SQL de verdade')
    assert codigo.count(p.CORTE_SQL) == 2, (
        'as duas fontes têm que usar a MESMA expressão de fronteira')


def test_deduplica_por_email_e_data_porque_o_destino_NAO_tem_chave_unica():
    """Medido em 10/08/2026: a chave primária da tabela deles é `id` sequencial, e não
    existe restrição de unicidade em (email, data). Ou seja, linha repetida entra
    calada e a agência conta o mesmo lead duas vezes. A defesa tem que morar aqui
    porque não existe do lado deles.

    Com duas fontes isso deixou de ser zelo e virou obrigação: o mesmo lead existe nas
    duas quando as tabelas derivadas alcançam o ledger no dia seguinte.
    """
    sel = p._select(False)
    assert "SELECT DISTINCT ON (email, data)" in sel, (
        'sumiu a deduplicação por (email, data)')


def test_a_fonte_CURADA_ganha_do_ledger_no_desempate():
    """Sem esta ordem, a linha JÁ ENTREGUE mudaria de valor sozinha.

    O lead chega pelo ledger hoje e é entregue. Amanhã as tabelas derivadas o alcançam,
    com matching e calendário aplicados. Se o ledger ganhasse o desempate, o painel da
    agência veria o mesmo lead trocar de campanha de um dia para o outro sem nada ter
    acontecido — e a explicação estaria escondida na nossa ordem de UNION.

    `ORDER BY email, data, prio` com prio crescente = ganha o menor = a curada.
    """
    curada, ledger = _fontes()
    assert "1 AS prio" in curada, 'a fonte curada deixou de ser a prioridade 1'
    assert "2 AS prio" in ledger, 'o ledger vivo deixou de ser a prioridade 2'
    sel = p._select(False)
    assert "ORDER BY email, data, prio" in sel, 'sumiu o desempate por prioridade'
    assert "prio DESC" not in sel, (
        'prioridade em ordem decrescente inverte o desempate: o ledger passaria a '
        'sobrescrever a entrega curada')


def test_o_LEDGER_VIVO_esta_na_entrega():
    """A razão de existir desta mudança, em uma linha de teste.

    As tabelas `analytics.leads` e `analytics.cadastros` são reconstruídas uma vez por
    dia (09:00 e 10:00). A agência abre o painel várias vezes ao dia para decidir verba,
    e até 10/08/2026 recebia o lead de hoje só amanhã. Medido naquele dia: 165 leads
    estavam no ledger e ausentes das derivadas; a entrega do dia saía com 33 linhas
    contra 215 na planilha deles, e com o ledger foi para 221.
    """
    _, ledger = _fontes()
    assert "public.registros_ml" in ledger, (
        'o braço do ledger vivo saiu da entrega: a agência volta a ver o lead de hoje '
        'só amanhã')


def test_o_ledger_tambem_respeita_os_90_dias():
    """Se o braço novo não tivesse o recorte, a carga cheia mandaria o ledger inteiro
    (2 anos) e a tabela da agência estouraria o combinado de 90 dias por baixo."""
    _, ledger = _fontes()
    assert p.CORTE_SQL in ledger and "r.created_at AT TIME ZONE" in ledger, (
        f'sumiu o recorte de {p.DIAS} dias no braço do ledger')


def test_no_incremental_o_ledger_le_APENAS_a_janela():
    """Sem este filtro o incremental continuaria correto e ficaria caro: leria os 90
    dias do ledger a cada rodada. Numa cadência de minutos, cada rodada custaria como
    uma carga cheia, e o custo apareceria como lentidão, não como erro."""
    _, ledger_janela = _fontes(janela=True)
    _, ledger_cheia = _fontes(janela=False)
    assert "r.created_at >= :desde" in ledger_janela, (
        'o incremental está lendo o ledger inteiro em vez da janela')
    assert "r.created_at >= :desde" not in ledger_cheia, (
        'a carga cheia não tem `:desde` para casar; o SQL quebraria por parâmetro '
        'ausente')


def test_os_dois_bracos_normalizam_o_email_em_MINUSCULO():
    """O dedupe é por (email, data) em texto. Se um braço mandasse `Joao@x.com` e o
    outro `joao@x.com`, seriam duas chaves diferentes: a mesma pessoa entraria duas
    vezes e o dedupe passaria batido."""
    for i, braco in enumerate(_fontes(), start=1):
        assert "lower(" in braco and "email" in braco, (
            f'a fonte {i} não normaliza o e-mail em minúsculo')
    _, ledger = _fontes()
    assert "lower(r.email)" in ledger, 'o ledger não normaliza o e-mail'


def test_o_ledger_NAO_vaza_score_nem_decil():
    """É proibido entregar score ou decil por lead, e este é o ponto do código onde
    vazar sem querer é mais fácil: `registros_ml` guarda `lead_score`, `decil_champion`
    e `decil_challenger` na coluna vizinha das que a entrega usa. Um `SELECT r.*` ou um
    copiar-colar de outra query já bastaria.

    Descarta comentários antes de olhar: a primeira versão deste teste falhou por
    causa do próprio comentário que EXPLICA a proibição.
    """
    sel = p._select(False)
    codigo = "\n".join(l for l in sel.splitlines() if not l.strip().startswith("--"))
    for proibida in ("lead_score", "decil", "score_champion", "score_challenger",
                     "decile_propensity", "decile_roas", "hotleads_hot", "r.*"):
        assert proibida not in codigo, (
            f'"{proibida}" apareceu no SQL da entrega: score por lead é proibido')


def test_o_ssl_nao_verifica_e_isso_e_deliberado():
    """`sslmode=require`, que foi o que eles pediram, significa criptografar SEM
    verificar. Não é desleixo: o pooler do Supabase apresenta cadeia que não fecha com
    raiz pública, e verificar falha com CERTIFICATE_VERIFY_FAILED (medido)."""
    import ssl as _ssl
    ctx = p._ctx()
    assert ctx.verify_mode == _ssl.CERT_NONE and ctx.check_hostname is False


def test_a_credencial_NAO_esta_no_codigo():
    """Este repositório é PÚBLICO e uma senha de Postgres já vazou nele (fechado em
    05/08/2026). A credencial do Supabase vem do Secret Manager, e este teste existe
    para que uma colagem 'só pra testar rápido' não passe da revisão."""
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "push_supabase_zanelato.py").read_text()
    assert "pooler.supabase.com" not in fonte, 'host do cliente hardcoded no código'
    assert "postgresql://" not in fonte, 'string de conexão hardcoded no código'
    assert p.SEGREDO_URL == "dash-zanelato-supabase-url"


def test_o_incremental_nao_inventa_janela_quando_o_destino_esta_vazio():
    """Se a tabela do cliente estiver vazia (primeira vez, ou alguém truncou), não há
    marca d'água. Assumir 'manda as últimas 24h' aqui deixaria o destino
    permanentemente incompleto e em SILÊNCIO — o pior modo de falhar numa entrega para
    terceiro. O certo é recusar e pedir a carga cheia."""
    class _DestinoVazio:
        def run(self, sql, **kw):
            return [[None]]          # max(recebido_em) de tabela vazia
        def close(self):
            pass
    orig = p.destino
    p.destino = lambda porta=None: _DestinoVazio()
    try:
        r = p.incremental()
    finally:
        p.destino = orig
    assert r.get("erro") == "destino_vazio", (
        'o incremental deveria RECUSAR rodar sem marca, não adivinhar uma janela')


def _captura_dm(monkeypatch=None):
    """Substitui o poster do Slack por um que só guarda o que seria enviado."""
    enviados = []

    def _poster(canal, blocos, texto):
        enviados.append({"canal": canal, "blocos": blocos, "texto": texto})
        return {"ok": True}
    return enviados, _poster


def test_a_auditoria_AVISA_no_DM_quando_diverge():
    """Até 10/08/2026 a auditoria detectava, quebrava, e o erro morria no log do Cloud
    Run. Verificado naquele dia: das 3 políticas de alerta do projeto, NENHUMA cobre
    este job (a de `Cron falhou` pega o Scheduler não conseguir disparar, não o job
    falhar por dentro). A defesa mais importante da entrega era invisível.
    """
    enviados, poster = _captura_dm()
    orig = p._avisa_no_dm
    p._avisa_no_dm = lambda linhas, resumo, **kw: poster("D_TESTE", linhas, resumo)
    o_l, o_d = _com_dubles([["2026-08", 100]], [["2026-08", 90]])
    try:
        with pytest.raises(SystemExit):
            p.auditar()
    finally:
        p.origem_leitura, p.destino = o_l, o_d
        p._avisa_no_dm = orig
    assert enviados, 'a auditoria divergiu e NÃO avisou ninguém'
    assert "auditoria não bateu" in enviados[0]["texto"], (
        'a mensagem tem que dizer o que aconteceu, não só alertar')
    assert "--full" in enviados[0]["texto"], (
        'a mensagem tem que dizer o que FAZER; alerta sem ação vira ruído')


def test_o_DM_sai_ANTES_do_erro_que_mata_o_processo():
    """A ordem aqui é o bug inteiro. `raise SystemExit` encerra o processo: se o aviso
    fosse depois, ele nunca sairia, e o conserto teria a aparência de estar funcionando
    (código presente, teste de conteúdo passando) sem nunca entregar uma mensagem."""
    ordem = []
    orig = p._avisa_no_dm
    p._avisa_no_dm = lambda linhas, resumo, **kw: ordem.append("dm")
    o_l, o_d = _com_dubles([["2026-08", 100]], [["2026-08", 90]])
    try:
        with pytest.raises(SystemExit):
            p.auditar()
        ordem.append("exit")
    finally:
        p.origem_leitura, p.destino = o_l, o_d
        p._avisa_no_dm = orig
    assert ordem == ["dm", "exit"], f'ordem errada: {ordem}'


def test_a_auditoria_avisa_tambem_quando_BATE():
    """Sem a linha de sucesso, silêncio quer dizer duas coisas ao mesmo tempo: nada
    divergiu, ou o job não rodou. São exatamente as duas que precisam ser distinguidas,
    e a segunda é a que já mordeu este projeto antes."""
    enviados, poster = _captura_dm()
    orig = p._avisa_no_dm
    p._avisa_no_dm = lambda linhas, resumo, **kw: poster("D_TESTE", linhas, resumo)
    iguais = [["2026-07", 100], ["2026-08", 50]]
    o_l, o_d = _com_dubles(list(iguais), list(iguais))
    try:
        r = p.auditar()
    finally:
        p.origem_leitura, p.destino = o_l, o_d
        p._avisa_no_dm = orig
    assert r["linhas"] == 150
    assert enviados, 'auditoria limpa não avisou nada: silêncio ambíguo de novo'
    assert "150" in enviados[0]["texto"], 'a mensagem de sucesso tem que trazer o número'


def test_o_aviso_do_DM_NUNCA_derruba_a_auditoria():
    """Slack fora do ar não pode virar falha de entrega. A auditoria continua sendo a
    fonte da verdade; o DM é só o mensageiro."""
    def _explode(canal, blocos, texto):
        raise RuntimeError("slack fora do ar")
    r = p._avisa_no_dm(["x"], "y", poster=_explode, canal="D_TESTE")
    assert r["ok"] is False and "slack fora do ar" in r["erro"]


def test_o_DM_da_auditoria_nao_leva_score_nem_decil():
    """A mensagem é contagem por mês. Se algum dia alguém colar detalhe de lead aqui,
    isso sai do nosso ambiente para o Slack, que é o caminho mais fácil de vazar o que
    é proibido entregar."""
    import re
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "push_supabase_zanelato.py").read_text()
    corpo = fonte[fonte.index("def _avisa_no_dm"):fonte.index("def main(")]
    codigo = "\n".join(l for l in corpo.splitlines()
                       if not l.strip().startswith("#"))
    for proibida in ("lead_score", "decil", "score_champion", "hotleads_hot", "email"):
        assert not re.search(rf"\b{proibida}\b", codigo), (
            f'"{proibida}" apareceu no caminho do DM da auditoria')


def test_a_poda_apaga_pela_MESMA_fronteira_que_a_carga_usa():
    """A poda é a única operação que APAGA dado do cliente, e a fronteira dela mudou de
    lugar: era calculada em Python, em UTC, e virou SQL no fuso de Brasília.

    Se a fronteira ficasse em UTC com a coluna `data` em Brasília, a linha da borda
    entraria na carga e sairia na poda a cada rodada, para sempre. Nada quebraria: só
    uma linha piscando na tabela do cliente.
    """
    vistos = []

    class _Destino:
        def run(self, sql, **kw):
            vistos.append((sql, kw))
            if "::text" in sql and "count(" not in sql:
                return [["2026-05-12"]]
            if sql.strip().startswith("SELECT count("):
                return [[100]]
            return []
        def close(self):
            pass

    orig = p.destino
    p.destino = lambda porta=None: _Destino()
    try:
        p.podar()
    finally:
        p.destino = orig
    pergunta = [s for s, _ in vistos if "::text" in s and "count(" not in s]
    assert pergunta, 'a poda não perguntou a fronteira ao banco'
    assert p.CORTE_SQL in pergunta[0], (
        'a poda calcula a fronteira de um jeito diferente da carga')
    apaga = [(s, k) for s, k in vistos if s.strip().startswith("DELETE")]
    assert apaga and apaga[0][1].get("lim") == "2026-05-12", (
        'a poda tem que apagar usando a fronteira que ELA perguntou, não outra')


class _ConnAuditoria:
    """Dublê que responde por TIPO de pergunta, não sempre a mesma coisa.

    A auditoria faz três perguntas diferentes (o corte da janela, a contagem por mês, e
    quantas linhas estão fora da janela esperando poda). Um dublê que devolve a mesma
    lista para todas elas testa outra coisa que não a auditoria.
    """
    def __init__(self, por_mes, a_podar=0):
        self._por_mes, self._a_podar = por_mes, a_podar

    def run(self, sql, **kw):
        # Detecção por FORMA, não por texto literal. A primeira versão casava
        # `startswith("SELECT (current_date")`; quando a fronteira mudou de fuso e virou
        # `SELECT ((now() AT TIME ZONE ...))::text`, o dublê parou de reconhecê-la e
        # devolveu a lista de meses no lugar da data. Os testes continuaram passando —
        # por sorte, porque o valor errado só era repassado como parâmetro. Dublê que
        # deixa de casar em silêncio é pior que dublê que quebra.
        if "::text" in sql and "count(" not in sql:
            return [["2026-05-12"]]
        if "data <" in sql:
            return [[self._a_podar]]
        return self._por_mes

    def close(self):
        pass


def _com_dubles(origem_por_mes, destino_por_mes, a_podar=0):
    """Troca as duas conexões e devolve o que restaurar."""
    o_leitura, o_destino = p.origem_leitura, p.destino
    p.origem_leitura = lambda **kw: _ConnAuditoria(origem_por_mes)
    p.destino = lambda porta=None: _ConnAuditoria(destino_por_mes, a_podar)
    return o_leitura, o_destino


def test_a_auditoria_nao_acusa_o_que_so_espera_poda():
    """Divergência e 'fora da janela aguardando poda' são coisas DIFERENTES.

    Medido em 10/08/2026: a primeira versão comparava uma janela móvel por instante
    contra uma tabela acumulada por dia, e acusava +14 linhas de maio onde não havia
    erro nenhum. O problema não é o falso positivo em si: é que uma auditoria que
    acusa todo dia ensina a ignorar auditoria, e aí ela falha justamente quando importa.
    """
    iguais = [["2026-07", 100], ["2026-08", 50]]
    o_l, o_d = _com_dubles(list(iguais), list(iguais), a_podar=14)
    try:
        r = p.auditar()
        assert r["a_podar"] == 14, 'a poda pendente tem que ser reportada…'
        assert r["linhas"] == 150, '…e NÃO contada como divergência'
    finally:
        p.origem_leitura, p.destino = o_l, o_d


def test_a_auditoria_QUEBRA_quando_diverge():
    """Esta é a defesa que torna a carga incremental aceitável numa entrega para
    terceiro: as outras dependem de eu ter listado certo todas as origens de mudança, e
    o histórico deste projeto mostra que essa aposta falha (a URL de captura ficou
    meses em 35% porque uma fonte foi esquecida, e ninguém soube).

    Se a auditoria apenas IMPRIMISSE a diferença, o cron registraria sucesso e a
    divergência viveria para sempre. Ela tem que sair com erro.
    """
    o_leitura, o_destino = _com_dubles([["2026-07", 100], ["2026-08", 50]],
                                       [["2026-07", 100], ["2026-08", 49]])
    try:
        with pytest.raises(SystemExit) as e:
            p.auditar()
        assert "AUDITORIA FALHOU" in str(e.value)
        assert "2026-08" in str(e.value), 'o erro tem que dizer QUAL mês divergiu'
    finally:
        p.origem_leitura, p.destino = o_leitura, o_destino


def test_a_auditoria_passa_quando_bate():
    iguais = [["2026-07", 100], ["2026-08", 50]]
    o_leitura, o_destino = _com_dubles(list(iguais), list(iguais))
    try:
        r = p.auditar()
        assert r["linhas"] == 150
    finally:
        p.origem_leitura, p.destino = o_leitura, o_destino


def test_a_auditoria_compara_por_MES_e_nao_so_o_total():
    """Total igual pode esconder um mês a menos compensando outro a mais. Foi por isso
    que a comparação é por mês."""
    # mesmo TOTAL (150), meses trocados
    o_leitura, o_destino = _com_dubles([["2026-07", 100], ["2026-08", 50]],
                                       [["2026-07", 50], ["2026-08", 100]])
    try:
        with pytest.raises(SystemExit):
            p.auditar()
    finally:
        p.origem_leitura, p.destino = o_leitura, o_destino


def test_reaproveita_a_definicao_UNICA_da_entrega():
    """Se este script montasse a sua própria consulta de leads, ela divergiria da do
    `provisiona` na primeira coluna nova, e a divergência apareceria como dado trocado
    no painel da agência. Uma definição, um filtro opcional."""
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "push_supabase_zanelato.py").read_text()
    assert "from scripts.provisiona_dash_zanelato import" in fonte
    assert "sql_fonte(janela=janela)" in fonte, (
        'o script deixou de reusar a consulta canônica da entrega')
