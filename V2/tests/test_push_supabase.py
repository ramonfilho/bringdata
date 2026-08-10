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


def test_a_ordem_do_SELECT_bate_com_a_ordem_das_COLUNAS():
    """A falha que este teste pega é a pior de todas aqui: se a ordem divergir, o
    INSERT continua funcionando (é tudo texto) e a agência recebe campanha na coluna de
    conteúdo. Ninguém vê erro, o painel deles só passa a mentir."""
    import re
    sel = p._select(False)
    corpo = sel[sel.index("SELECT DISTINCT ON"):sel.index("FROM (")]
    posicoes = []
    for c in p.COLUNAS:
        # Sai com apelido (`... AS email`) ou com o nome cru (`q.nome,`). O espaçamento
        # entre a expressão e o AS é livre, daí a busca por padrão e não por texto fixo.
        m = re.search(rf"\bAS\s+{c}\b", corpo) or re.search(rf"\bq\.{c}\b", corpo)
        assert m, f'a coluna {c} não sai do SELECT'
        posicoes.append((m.start(), c))
    assert [c for _, c in sorted(posicoes)] == p.COLUNAS, (
        f'ordem do SELECT divergiu de COLUNAS: {[c for _, c in sorted(posicoes)]}')


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
        assert f"q.capturado_em::date >= (current_date - {p.DIAS})" in sel, (
            f'sumiu o recorte de {p.DIAS} dias no modo janela={janela}')


def test_o_recorte_e_por_DIA_e_nao_por_instante():
    """Foi este detalhe que produziu o falso positivo de +14 linhas em 10/08/2026.

    A origem filtrava por instante (`now() - interval '90 days'`) e o destino guarda a
    data só como dia. Entre a carga e a auditoria o relógio andou, linhas da fronteira
    saíram de um lado e ficaram no outro, e a auditoria acusou erro onde não havia.
    As três operações (carga, poda, auditoria) têm que usar a MESMA fronteira de dia.
    """
    sel = p._select(False)
    assert "::date >= (current_date" in sel, 'o recorte voltou a ser por instante'
    # Descarta as linhas de comentário INTEIRAS. Remover só o marcador `--` deixaria o
    # texto do comentário no meio do SQL e o teste passaria (ou falharia) pelo motivo
    # errado — foi o que aconteceu na primeira versão deste teste.
    codigo = "\n".join(l for l in sel.splitlines() if not l.strip().startswith("--"))
    assert "now() - interval" not in codigo, (
        'sobrou filtro por instante no SQL de verdade, fora de comentário')


def test_a_data_sai_no_formato_que_a_coluna_deles_espera():
    """A coluna `data` no destino é TEXTO, não data. Deixar o Postgres formatar por
    conta dele faria o formato virar surpresa (e mudar com a configuração do servidor)."""
    assert "to_char(q.capturado_em, 'YYYY-MM-DD')" in p._select(False)


def test_deduplica_por_email_e_data_porque_o_destino_NAO_tem_chave_unica():
    """Medido em 10/08/2026: a chave primária da tabela deles é `id` sequencial, e não
    existe restrição de unicidade em (email, data). Ou seja, linha repetida entra
    calada e a agência conta o mesmo lead duas vezes. A defesa tem que morar aqui
    porque não existe do lado deles."""
    sel = p._select(False)
    assert "DISTINCT ON (lower(q.email), to_char(q.capturado_em, 'YYYY-MM-DD'))" in sel, (
        'sumiu a deduplicação por (email, data)')


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


class _ConnAuditoria:
    """Dublê que responde por TIPO de pergunta, não sempre a mesma coisa.

    A auditoria faz três perguntas diferentes (o corte da janela, a contagem por mês, e
    quantas linhas estão fora da janela esperando poda). Um dublê que devolve a mesma
    lista para todas elas testa outra coisa que não a auditoria.
    """
    def __init__(self, por_mes, a_podar=0):
        self._por_mes, self._a_podar = por_mes, a_podar

    def run(self, sql, **kw):
        # Detecção por padrão ESPECÍFICO: a consulta por mês também menciona
        # `current_date` (o filtro da janela mora dentro dela), então casar só por
        # 'current_date' devolveria a data no lugar da lista de meses.
        if sql.strip().startswith("SELECT (current_date"):
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
