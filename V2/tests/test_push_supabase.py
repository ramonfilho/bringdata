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


def _codigo(janela=False):
    """O SQL da entrega SEM as linhas de comentário.

    Existe porque metade dos testes daqui procura ausência ("tal tabela NÃO aparece"), e
    comentário que explica a regra contém as palavras da regra. Um teste que falha por
    causa do próprio comentário que documenta a proibição já aconteceu duas vezes neste
    arquivo.
    """
    sel = p._select(janela)
    return "\n".join(l for l in sel.splitlines() if not l.strip().startswith("--"))


def test_a_entrega_le_UMA_fonte_e_ela_e_a_captacoes():
    """A decisão de 11/08/2026, em uma linha de teste.

    Antes a entrega somava três tabelas (`analytics.leads`, `analytics.cadastros` e o
    ledger `registros_ml`) num UNION com desempate por prioridade. Funcionava e era
    difícil de explicar: a mesma coluna podia vir de três lugares com regras diferentes.

    Agora a fonte é uma só, alimentada pela ingestão do Railway.
    """
    import re
    codigo = _codigo()
    tabelas = set(re.findall(r"FROM\s+([a-z_]+\.[a-z_]+)", codigo))
    assert tabelas == {"analytics.captacoes"}, (
        f"a entrega deveria ler só a captacoes, e lê: {sorted(tabelas)}")


def test_a_entrega_NAO_enriquece_de_outras_fontes():
    """Regra do cliente, não preferência de implementação: se o dado falta no lead, ele
    falta na tabela da agência.

    A versão anterior preenchia `utm_url` do ledger de respondentes, da `lead_legado` e da
    repescagem de backup no MOMENTO de entregar. Remendo na entrega faz a tabela do cliente
    parecer melhor do que o dado é, e esconde o que precisa ser consertado na origem — foi
    exatamente assim que a falha de cobertura do front em 05-06/08/2026 apareceu.

    Completar dado é trabalho de INGESTÃO, dentro da `captacoes`, num lugar só.
    """
    codigo = _codigo()
    for proibida in ("registros_ml", "lead_legado", "url_captura_legado",
                     "analytics.leads", "analytics.cadastros", "launch_calendar",
                     "analytics.sales"):
        assert proibida not in codigo, (
            f'"{proibida}" voltou a ser lida na hora da entrega; enriquecimento é '
            f'trabalho da ingestão, não da entrega')


def test_a_ordem_do_SELECT_bate_com_a_ordem_das_COLUNAS():
    """A falha que este teste pega é a pior de todas aqui: se a ordem divergir, o INSERT
    continua funcionando (é tudo texto) e a agência recebe campanha na coluna de conteúdo.
    Ninguém vê erro, o painel deles só passa a mentir."""
    import re
    codigo = _codigo()
    corpo = codigo[codigo.index("SELECT c.nome"):codigo.index("FROM analytics.captacoes")]
    posicoes = []
    for c in p.COLUNAS:
        m = (re.search(rf"\bAS\s+{c}\b", corpo)
             or re.search(rf"\bc\.{c}\b", corpo))
        assert m, f"a coluna {c} não sai do SELECT"
        posicoes.append((m.start(), c))
    assert [c for _, c in sorted(posicoes)] == p.COLUNAS, (
        f"ordem divergiu de COLUNAS: {[c for _, c in sorted(posicoes)]}")


def test_a_janela_e_de_90_dias_e_na_mesma_regra_de_dia_da_coluna():
    """O combinado com o cliente é 90 dias. E a fronteira tem que usar a MESMA regra de dia
    da coluna `data`: fronteira numa regra e valor em outra faz a linha da borda entrar na
    carga e sair na poda a cada rodada, para sempre, sem erro nenhum aparecendo.

    Atualizado em 12/08/2026: a regra de dia deixou de ser uma expressão fixa e passou a
    depender da procedência (ver `DIA_SQL`), então o que este teste trava é a IGUALDADE
    entre as duas, não o texto de uma delas.
    """
    assert p.DIAS == 90
    assert f"AT TIME ZONE '{p.FUSO}'" in p.CORTE_SQL
    for janela in (False, True):
        sql = p._select(janela)
        assert f"{p.DIA_SQL} >= {p.CORTE_SQL}" in sql, (
            f"sumiu o recorte no modo janela={janela}, ou ele deixou de usar a mesma "
            f"expressão de dia da coluna `data`")


def test_o_recorte_e_por_DIA_e_nao_por_instante():
    """Foi este detalhe que produziu o falso positivo de +14 linhas em 10/08/2026: a origem
    filtrava por instante e o destino guarda só o dia, então entre a carga e a auditoria o
    relógio andava e linhas da fronteira saíam de um lado e ficavam no outro."""
    codigo = _codigo()
    # Os dois ramos da regra de dia terminam em `::date`, então a comparação é entre datas.
    assert codigo.count("::date") >= 2, "o recorte voltou a ser por instante"
    assert "END >=" in codigo, "a comparação de dia perdeu o corte"
    assert "now() - interval" not in codigo, "sobrou filtro por instante no SQL de verdade"


def test_a_data_sai_como_TEXTO_no_formato_que_a_coluna_deles_espera():
    """A coluna `data` no destino é TEXTO, e a agência compara com a planilha dela e com o
    painel da Meta, os dois em horário de Brasília.

    Em 10/08/2026 ela apontou 15 leads do dia 09/08 ausentes; 14 estavam lá datados 10/08,
    e os 14 tinham chegado entre 21:05 e 23:55 de Brasília do dia 09 — desvio sistemático
    de 3 horas. A causa não estava escrita no código: a conexão tem `TimeZone = UTC` e
    `to_char(timestamptz, ...)` renderiza no fuso da SESSÃO. Daí o fuso EXPLÍCITO.

    Em 12/08/2026 descobriu-se que aquele conserto estava certo só para METADE da tabela:
    nas linhas de planilha, `captured_at` já É a data local e converter a corrompia. Qual
    ramo vale para qual procedência é o assunto de
    `test_a_data_entregue_depende_da_PROCEDENCIA_da_linha`; aqui só se trava que a saída é
    texto no formato pedido.
    """
    codigo = _codigo()
    assert "'YYYY-MM-DD')      AS data" in codigo or "'YYYY-MM-DD')" in codigo, (
        "a coluna `data` deixou de sair como texto no formato pedido")
    assert "to_char(" in codigo
    assert p.FUSO == "America/Sao_Paulo"


def test_o_incremental_filtra_por_INGESTED_AT_e_nao_por_captured_at():
    """A diferença entre os dois muda o que a agência recebe.

    `captured_at` é quando o lead entrou; `ingested_at` é quando a NOSSA ingestão escreveu
    aquela linha. Um lead de ontem cuja UTM chegou hoje tem `captured_at` de ontem e
    precisa ser reenviado — filtrando por `captured_at`, ele nunca mais seria olhado e
    ficaria sem campanha na tabela deles para sempre.
    """
    assert "c.ingested_at >= :desde" in p._select(True), (
        "o incremental precisa seguir a marca da INGESTÃO, não a data do lead")
    assert ":desde" not in p._select(False), (
        "a carga cheia não tem `:desde` para casar; o SQL quebraria por parâmetro ausente")


def test_deduplica_por_email_e_data_porque_o_destino_NAO_tem_chave_unica():
    """A chave primária da tabela deles é `id` sequencial, e não existe restrição de
    unicidade em (email, data): linha repetida entra calada e a agência conta o mesmo lead
    duas vezes.

    A `captacoes` já é única em `(lf, chave, origem_id)`, mas o mesmo lead pode estar em
    dois LANÇAMENTOS — e para a agência, que enxerga só (e-mail, data), isso seria duplicata.
    """
    assert "SELECT DISTINCT ON (email, data)" in p._select(False)


def test_o_email_sai_em_MINUSCULO():
    """O dedupe é por (email, data) em texto. Sem normalizar, `Joao@x.com` e `joao@x.com`
    seriam duas chaves e a mesma pessoa entraria duas vezes. E isso NÃO é hipotético: a
    chave primária do `Client` no Railway preserva o caso, e medido em 11/08/2026 são
    136.622 linhas lá para 136.484 e-mails distintos em minúsculo."""
    assert "lower(c.email)" in _codigo()


def test_a_entrega_NAO_leva_score_nem_decil():
    """Score e decil por lead são proibidos nesta entrega. A `captacoes` guarda
    `lead_score` e `decil` como colunas, então um `SELECT c.*` ou um copiar-colar de outra
    query bastaria para vazar."""
    codigo = _codigo()
    for proibida in ("lead_score", "decil", "score_champion", "score_challenger",
                     "decile_propensity", "decile_roas", "hotleads_hot", "c.*"):
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
            # Responde por TIPO de pergunta. Um dublê que devolve a mesma coisa para tudo
            # fazia a trava de concorrência "negar" o lock e este teste passava a exercitar
            # o caminho errado — dizia `ja_rodando` quando o assunto era destino vazio.
            if "advisory_lock" in sql:
                return [[True]]
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


def test_a_entrega_NAO_depende_mais_da_consulta_da_outra_entrega():
    """O acoplamento que este teste trava é o INVERSO do que ele travava antes.

    Até 11/08/2026 este script importava `sql_fonte` da entrega do banco `dash` (27
    colunas) e projetava 11 delas. A razão era boa — uma definição, duas entregas, sem
    divergir. O preço era arrastar o trabalho inteiro da outra: a consulta calculava e
    jogava fora `lead_id` (um hash sha256), `lf`, `comprou` e 8 das 9 perguntas da
    pesquisa, e o job exigia o segredo `dash-lead-id-salt` só para descartar o resultado.

    Com a `captacoes` como fonte única, as duas entregas ficaram independentes. Este teste
    existe para que ninguém religue esse acoplamento sem perceber.
    """
    import re
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "push_supabase_zanelato.py").read_text()
    # Olha CÓDIGO, não prosa: o cabeçalho do módulo explica de propósito o que a entrega
    # deixou de fazer, e um teste que casa com a explicação da proibição falha por causa da
    # própria documentação. Aconteceu três vezes neste arquivo.
    codigo = "\n".join(l for l in fonte.splitlines()
                       if not l.strip().startswith("#"))
    assert not re.search(r"import .*\bsql_fonte\b", codigo), (
        "a entrega voltou a IMPORTAR a consulta da entrega do `dash`")
    assert not re.search(r"\bsql_fonte\s*\(", codigo), (
        "a entrega voltou a CHAMAR a consulta da entrega do `dash`")
    assert not re.search(r"\bsal\s*\(\s*\)", codigo), (
        "voltou a usar o sal do `lead_id`, que esta entrega não entrega")


def test_o_incremental_SAI_quando_outra_rodada_esta_em_curso():
    """Cron de 5 minutos com rodada que leva 6 não espera a anterior: o Cloud Run dispara as
    duas. Duas rodadas gravando as mesmas chaves ao mesmo tempo é travamento ou trabalho
    duplicado, e num cron que roda 288 vezes por dia isso deixa de ser hipótese.

    A trava é `pg_try_advisory_lock` no banco DELES porque é o único ponto que as duas
    rodadas concorrentes têm em comum. E é lock de SESSÃO: morre junto com a conexão, então
    job morto no meio não deixa cadeado órfão para alguém destravar na mão.
    """
    tentou_gravar = []

    class _Ocupado:
        def run(self, sql, **kw):
            if "advisory_lock" in sql:
                return [[False]]              # outra rodada já tem a trava
            tentou_gravar.append(sql)
            return [[None]]
        def close(self):
            pass

    orig = p.destino
    p.destino = lambda porta=None: _Ocupado()
    try:
        r = p.incremental()
    finally:
        p.destino = orig
    assert r.get("erro") == "ja_rodando"
    assert not tentou_gravar, (
        f"saiu pela trava mas ainda tocou o banco: {tentou_gravar}")


def test_a_folga_do_incremental_e_pouco_maior_que_a_cadencia():
    """A folga cobre a sobreposição entre rodadas. Era 15 minutos, o que numa cadência de 5
    fazia cada linha ser reenviada ~3 vezes — não quebra nada (a gravação é idempotente), só
    é desperdício. Muito menor que a cadência, porém, deixa buraco entre rodadas."""
    assert 5 < p.FOLGA_MINUTOS <= 10, (
        f"folga de {p.FOLGA_MINUTOS} min não casa com uma cadência de 5 minutos")


def test_a_data_entregue_depende_da_PROCEDENCIA_da_linha():
    """Converter uma data local para outro fuso não a corrige, corrompe.

    Em `analytics.captacoes`, `captured_at` significa duas coisas diferentes conforme a
    origem da linha, e tratar as duas igual erra numa delas:

      - procedência `railway`: é INSTANTE (vem do `trackedAt` do evento de UTM). Converter
        para Brasília é o certo.
      - procedência `planilha`: NÃO é instante. 494.195 de 503.438 linhas (98,2%) estão em
        00:00:00 UTC exato, porque é uma DATA guardada como meia-noite, e a data que a
        planilha do Drive trazia já era a data local brasileira. `AT TIME ZONE
        'America/Sao_Paulo'` devolve 21h do dia ANTERIOR e o dia anda −1.

    Medido em 12/08/2026 contra o `Client` do Railway (fonte de FORA, de propósito), 2.998
    linhas de planilha na janela: lido como UTC acerta 90,6%, lido em Brasília acerta 0,0%.
    Contra o calendário de lançamentos, a leitura UTC bate `min(data)` com `cap_start` em 8
    de 10 LFs; a leitura em Brasília dá −1 dia em 8 de 10.

    Este teste existe porque o defeito é INVISÍVEL para a auditoria: ela compara a nossa
    contagem por mês com a deles, e as duas usam a mesma expressão. Deslocamento uniforme
    casa perfeitamente. Só uma fonte de fora, ou este teste, pega.
    """
    import scripts.push_supabase_zanelato as p

    for janela in (False, True):
        sql = p._select(janela)
        assert "origem_id LIKE 'planilha:" in sql, (
            "a expressão de dia deixou de separar por procedência — as linhas de planilha "
            "voltam a ser entregues com a data 1 dia adiantada")
        assert "AT TIME ZONE 'UTC'" in sql, (
            "sumiu a leitura UTC, que é a correta para as linhas de planilha")
        assert "AT TIME ZONE 'America/Sao_Paulo'" in sql, (
            "sumiu a conversão para Brasília, que é a correta para as linhas do Railway")


def test_o_corte_de_90_dias_usa_a_MESMA_expressao_de_dia_que_a_coluna_data():
    """Fronteira num critério e valor em outro faz a linha da borda oscilar para sempre.

    A carga insere quem passa do corte e a poda apaga quem tem `data` antes dele. Se os dois
    calcularem o dia de formas diferentes, a linha da borda entra na carga e sai na poda a
    cada rodada, indefinidamente, e nenhuma das duas dá erro. Por isso `DIA_SQL` aparece nos
    dois lugares do SELECT em vez de haver uma segunda cópia escrita à mão.
    """
    import scripts.push_supabase_zanelato as p

    sql = p._select(False)
    # A expressão de dia é a mesma string nos dois usos: a projeção da coluna e o WHERE.
    corpo = p.DIA_SQL.strip()
    assert sql.count(corpo) == 2, (
        f"`DIA_SQL` aparece {sql.count(corpo)}x no SELECT; tem que aparecer 2x (a coluna "
        f"`data` e o corte de 90 dias). Cópia escrita à mão em um dos dois é o que faz a "
        f"linha da borda oscilar entre carga e poda")
