"""Trava a ingestão Railway -> `analytics.captacoes`.

Cada teste aqui existe por causa de um erro que ACONTECEU em 11/08/2026, no ensaio em
seco ou na primeira gravação. Nenhum é hipotético, e nenhum aparecia nos totais: as
contagens estavam certas nas três vezes, e só a distribuição por dia, a comparação com a
origem ou o erro do Postgres denunciaram.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import ingest_captacoes_railway as ing


# Calendário de mentira, com duas janelas e um VÃO entre elas — o vão é o ponto.
CAL = [
    ("LF64", datetime(2026, 8, 7).date(), datetime(2026, 8, 17).date()),
    ("DEV21", datetime(2026, 7, 21).date(), datetime(2026, 8, 3).date()),
]
AGORA = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


_PADRAO = object()   # distingue "não passei" de "passei None de propósito"


def _reg(email="a@x.com", phone="11987654321", nome="Ana Silva", has_pc="SIM",
         criado=_PADRAO, utm_id=1, rastreado=None, src="facebook-ads", med="cpc",
         camp="camp1", cont="ad1", term="t1", url="https://x.com/cap-meta-lf64/"):
    """Um registro no formato que a consulta do Railway devolve.

    `criado=_PADRAO` em vez de `criado=None`: com None como default não havia como testar
    o caso "registro SEM data nenhuma", porque o helper trocava o None pela data padrão e
    o teste passava por engano.
    """
    return (email, phone, nome, has_pc,
            datetime(2026, 8, 10, 15, 0) if criado is _PADRAO else criado,
            utm_id,
            rastreado,
            src, med, camp, cont, term, url)


def test_o_lf_sai_do_calendario_por_data_de_captacao():
    linhas = ing._monta([_reg(criado=datetime(2026, 8, 10, 15, 0))], CAL, AGORA)
    assert linhas[0][0] == "LF64"


def test_quem_cai_no_VAO_entre_lancamentos_entra_com_sentinela_e_NAO_e_descartado():
    """04 a 06/08/2026 cai entre o fim do DEV21 e o início do LF64. Esse lead precisa
    entrar: a agência pagou por ele. Descartar em silêncio seria pior que a sentinela.

    Medido no backfill: 377 leads nesses três dias.
    """
    linhas = ing._monta([_reg(criado=datetime(2026, 8, 5, 15, 0))], CAL, AGORA)
    assert len(linhas) == 1, "o lead do vão foi DESCARTADO"
    assert linhas[0][0] == ing.SEM_LF


def test_NUNCA_data_o_lead_antes_de_ele_existir_como_cadastro():
    """O bug que o ensaio em seco pegou: 28 de 1.935 linhas saíram datadas de março a
    julho porque a pessoa tinha um evento de rastreio ANTIGO (visitou a página em março) e
    se cadastrou agora. Datando pelo evento, ela aparecia como lead de março na contagem
    diária da agência.

    Este erro NÃO aparecia nos totais — só na distribuição por dia.
    """
    linhas = ing._monta([_reg(criado=datetime(2026, 8, 10, 15, 0),
                              rastreado=datetime(2026, 3, 20, 10, 0))], CAL, AGORA)
    assert linhas[0][7].date() == datetime(2026, 8, 10).date(), (
        "datou o lead pelo rastreio antigo, antes de ele existir como cadastro")
    assert linhas[0][0] == "LF64", "e por consequência caiu no lançamento errado"


def test_quando_o_rastreio_vem_DEPOIS_a_data_do_evento_e_que_vale():
    """A outra metade da regra, e ela não é simétrica.

    O caso normal é o rastreio chegar depois do cadastro (medido: 98,3% em menos de 1
    hora). Nesse caso a data do EVENTO é a que vale, porque é ela que distingue a segunda
    inscrição da primeira. Se a regra fosse "sempre a data do cadastro", o grão por
    inscrição perderia o sentido: todas as inscrições da mesma pessoa colapsariam num dia.
    """
    linhas = ing._monta([_reg(criado=datetime(2026, 8, 7, 23, 0),
                              rastreado=datetime(2026, 8, 8, 1, 0))], CAL, AGORA)
    assert linhas[0][7].date() == datetime(2026, 8, 8).date()


def test_o_fuso_e_declarado_como_UTC_antes_de_converter():
    """O Railway guarda UTC em coluna SEM fuso. Sem declarar, o Postgres (e o Python)
    assumem outro fuso e a data erra em 3 horas — o mesmo erro que já jogou o lead da
    noite para o dia seguinte na entrega da agência.

    Cadastro às 01:00 UTC do dia 08 é 22:00 de Brasília do dia 07, então o lead é do dia 07
    e pertence ao LF64, que começa em 07.
    """
    linhas = ing._monta([_reg(criado=datetime(2026, 8, 8, 1, 0))], CAL, AGORA)
    assert linhas[0][7].tzinfo is not None, "a data saiu sem fuso declarado"
    assert linhas[0][0] == "LF64"
    # 01:00 UTC menos 3 = 22:00 do dia anterior: o dia BRT é 07, não 08.
    assert (linhas[0][7] - timedelta(hours=3)).date() == datetime(2026, 8, 7).date()


def test_pessoa_com_DOIS_eventos_vira_DUAS_linhas():
    """É o requisito: o lead aparece quantas vezes se inscrever. `Client` é uma linha por
    pessoa e não sabe dizer isso; quem sabe é a `UTMTracking`, e cada evento dela tem id
    próprio, que vira o discriminador."""
    linhas = ing._monta([
        _reg(utm_id=10, rastreado=datetime(2026, 8, 10, 15, 0)),
        _reg(utm_id=11, rastreado=datetime(2026, 8, 11, 9, 0)),
    ], CAL, AGORA)
    assert len(linhas) == 2
    assert {x[2] for x in linhas} == {"utm:10", "utm:11"}


def test_pessoa_SEM_evento_de_utm_ainda_entra():
    """`LEFT JOIN` e não `JOIN`: com JOIN, o cadastro cuja linha de UTM ainda não chegou
    (ou nunca vai chegar) simplesmente NÃO seria entregue, e a agência veria menos lead do
    que existe, sem erro em lugar nenhum. Medido em 11/08/2026: 327 de 1.933 linhas do
    backfill vieram só do cadastro."""
    linhas = ing._monta([_reg(utm_id=None, src=None, med=None, camp=None,
                              cont=None, term=None, url=None)], CAL, AGORA)
    assert len(linhas) == 1
    assert linhas[0][2] == "client:a@x.com", "o discriminador do lead sem evento mudou"
    assert linhas[0][8] is None, "UTM vazia deveria virar NULL, não string vazia"


def test_o_discriminador_NUNCA_e_nulo():
    """Em Postgres, dois NULL NÃO conflitam num índice único. Se o discriminador fosse
    nulável, a ingestão reinseriria as mesmas linhas a cada rodada, para sempre, sem erro
    nenhum aparecendo."""
    for r in (_reg(utm_id=None), _reg(utm_id=7)):
        linhas = ing._monta([r], CAL, AGORA)
        assert linhas[0][2], "origem_id saiu vazio"


def test_deduplica_a_chave_repetida_DENTRO_do_lote():
    """O Postgres RECUSA um `INSERT ... ON CONFLICT DO UPDATE` que traga a mesma chave duas
    vezes no mesmo comando (21000, "cannot affect row a second time"). E a colisão acontece
    de verdade: a chave primária do `Client` é `email` com o CASO preservado, então
    `Joao@x.com` e `joao@x.com` são duas linhas lá e viram a mesma chave aqui.

    Medido em 11/08/2026: 136.622 linhas no `Client` para 136.484 e-mails em minúsculo.
    """
    linhas = ing._monta([
        _reg(email="Joao@X.com", utm_id=None, phone=None, nome=None),
        _reg(email="joao@x.com", utm_id=None, phone="11999998888", nome="João"),
    ], CAL, AGORA)
    assert len(linhas) == 1, "a chave repetida no lote não foi colapsada"
    # Empate resolvido pela linha MAIS COMPLETA, não pela última: ficar com a última seria
    # decidir por acidente de ordenação da consulta.
    assert linhas[0][6] == "João", "o desempate não escolheu a linha mais completa"


def test_registro_sem_data_nenhuma_e_descartado():
    """Sem data não há lançamento nem coluna `data` na entrega. Inventar uma data seria
    pior que não entregar a linha."""
    assert ing._monta([_reg(criado=None, utm_id=None, rastreado=None)], CAL, AGORA) == []


def test_a_folga_da_janela_e_de_HORAS_e_nao_de_dias():
    """Medido em 11/08/2026 sobre 36.621 cadastros de 30 dias: 98,3% das UTMs chegam em
    menos de 1 hora e entre 1h e 48h chegam ZERO. A primeira versão usava 48 horas, que
    era chute e errava por um fator de 48 — numa cadência de 5 minutos, isso faria 288
    rodadas por dia relerem dois dias de Railway cada uma, sem ganhar nada."""
    assert ing.FOLGA_HORAS <= 6, (
        f"folga de {ing.FOLGA_HORAS}h: o atraso real da UTMTracking é menor que 1h")


def test_a_ingestao_NAO_escreve_no_railway():
    """A conexão com o Railway é de leitura por contrato. O front é dono daquele banco, e
    escrever lá seria mexer no sistema de outra equipe pela porta de trás."""
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "ingest_captacoes_railway.py").read_text()
    codigo = "\n".join(l for l in fonte.splitlines()
                       if not l.strip().startswith("#"))
    depois_do_railway = codigo[codigo.index("def railway("):]
    for escrita in ("INSERT INTO \"", "UPDATE \"", "DELETE FROM \"", "ALTER TABLE \""):
        assert escrita not in depois_do_railway, f"a ingestão escreve no Railway: {escrita}"


def test_a_ingestao_nao_sobrescreve_colunas_de_outro_processo():
    """`bought_45d`, `bought_ever`, `ad_base` e `ad_name` são preenchidas por outro
    processo (casamento com vendas e normalização de nome de anúncio). Se entrassem no
    upsert, cada rodada as sobrescreveria com NULL e apagaria dado bom de forma invisível.
    """
    for col in ("bought_45d", "bought_ever", "ad_base", "ad_name"):
        assert col not in ing.COLUNAS, (
            f"{col} entrou no upsert da ingestão e seria zerada a cada rodada")


def test_o_upsert_casa_com_a_chave_da_migracao():
    """O `ON CONFLICT` precisa nomear exatamente as colunas do índice único criado por
    `migrate_captacoes_por_inscricao.py`. Se divergirem, o Postgres reclama que não há
    restrição correspondente e a ingestão para de gravar."""
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "ingest_captacoes_railway.py").read_text()
    assert "ON CONFLICT (lf, chave, origem_id)" in fonte


def test_a_marca_dagua_sai_do_DESTINO_e_e_escopada_na_procedencia():
    """Sai do destino para que, se alguém apagar as linhas, a marca desapareça junto e a
    rodada seguinte perceba — em vez de continuar de um ponteiro que não vale mais.

    E escopada em `planilha='railway'`: sem isso, a marca pegaria a captação mais nova das
    503 mil linhas vindas das planilhas e a ingestão nunca voltaria atrás o suficiente.
    """
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "ingest_captacoes_railway.py").read_text()
    assert "SELECT max(captured_at)" in fonte
    assert "WHERE planilha = :p" in fonte
    assert ing.PROCEDENCIA == "railway"


def test_o_telefone_vira_os_8_ultimos_digitos_para_casar_venda():
    """`phone8` é a chave de casamento com venda usada no resto do projeto. Formato
    diferente aqui quebraria o cruzamento sem quebrar nada visível."""
    assert ing._tel8("+55 (11) 98765-4321") == "87654321"
    assert ing._tel8("1234") is None, "número curto deveria virar None, não lixo"
    assert ing._tel8(None) is None


def test_NAO_existe_teto_de_linhas_por_rodada_e_isso_e_medido():
    """Fatiar em lotes com avanço parcial da marca resolveria o caso "volume maior que o
    job aguenta". Esse caso está 85x longe.

    Cronometrado contra o Railway em 11/08/2026: 1 dia = 639 registros em 3,7s; 8 dias =
    2.558 em 3,0s; 30 dias = 39.684 em 6,6s, mais 0,10s para montar em Python. Um atraso
    catastrófico de 30 dias cabe em 7 segundos de um limite de 600.

    Código para um problema que não existe é código que ninguém testa. Este teste existe
    para que a decisão fique explícita: se um dia o AVISO começar a disparar, é aí que o
    teto entra — não antes.
    """
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "ingest_captacoes_railway.py").read_text()
    assert "TIMEOUT_JOB_S" in fonte and "AVISA_ACIMA_DE" in fonte, (
        "sem teto E sem aviso: estourar o limite voltaria a ser falha silenciosa")


def test_o_aviso_dispara_ANTES_do_limite_e_nao_depois():
    """Avisar quando já estourou não serve para nada: o job já morreu. O aviso tem que sair
    com folga suficiente para alguém agir — daí a fração, e não um valor absoluto."""
    assert 0 < ing.AVISA_ACIMA_DE < 1, "a fração tem que ser um pedaço do orçamento"
    assert ing.AVISA_ACIMA_DE <= 0.7, (
        "avisar com menos de 30% de folga deixa pouco espaço para reagir")
    assert ing.TIMEOUT_JOB_S == 600, (
        "o limite tem que casar com o `timeoutSeconds` do job no Cloud Run; se mudar lá, "
        "muda aqui, senão o aviso mede contra um orçamento que não existe")


def test_quem_altera_valor_entregue_carimba_a_marca_da_entrega():
    """REGRA GERAL, e ela nasceu de um furo real.

    A entrega descobre o que mudou olhando `ingested_at`. O script que preenche a `utm_url`
    do histórico alterava só a coluna da URL — então, do ponto de vista da entrega, aquelas
    linhas "não mudaram", e a URL certa ficaria no nosso banco convivendo com a antiga no do
    cliente, indefinidamente, até alguém rodar uma carga cheia na mão.

    Vale para qualquer script futuro que mexa em coluna entregue: carimbar a marca ou a
    mudança não propaga. É irmão da auditoria que morria no log e do índice que existia e não
    valia — peça certa, sem o elo que a torna visível.
    """
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "completa_url_captacoes.py").read_text()
    codigo = "\n".join(l for l in fonte.splitlines()
                       if not l.strip().startswith("#") and "--" not in l)
    assert "ingested_at = now()" in codigo, (
        "o preenchimento da URL não carimba `ingested_at`: a entrega nunca veria a mudança")


def test_a_gravacao_confirma_LOTE_POR_LOTE_e_em_ordem_de_data():
    """As duas coisas juntas, e uma sem a outra é pior que nenhuma.

    COMMIT POR LOTE: com transação única para a rodada inteira, uma rodada morta no limite
    do job é DESFEITA — nada escrito, marca não avança, a seguinte tenta o mesmo volume e
    morre igual. Trava para sempre, e piora, porque o acúmulo cresce. Com commit por lote, a
    rodada morta mantém o que escreveu.

    ORDEM DE DATA CRESCENTE: a marca d'água é `max(captured_at)` do que está gravado. Em
    ordem arbitrária, um lote com um lead de HOJE faria a marca saltar para hoje e os leads
    mais antigos ainda não escritos ficariam atrás dela, perdidos em silêncio — trocaria
    uma rodada que não avança por perda de lead, que é pior.
    """
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "ingest_captacoes_railway.py").read_text()
    codigo = "\n".join(l for l in fonte.splitlines()
                       if not l.strip().startswith("#"))
    corpo = codigo[codigo.index("def _grava("):codigo.index("def marca_dagua(")]
    assert 'c.run("BEGIN")' in corpo and 'c.run("COMMIT")' in corpo, (
        "a gravação deixou de confirmar por lote")
    assert "sorted(linhas, key=lambda x: x[7])" in corpo, (
        "os lotes deixaram de ir em ordem de data; a marca d'água pode saltar e deixar "
        "lead antigo atrás dela")
    # E a transação externa NÃO pode voltar: ela anularia o commit por lote.
    main = codigo[codigo.index("def main("):]
    assert 'c.run("BEGIN")' not in main, (
        "voltou uma transação envolvendo a rodada inteira — anula o commit por lote")


def test_o_aviso_de_teto_vai_para_o_DM_e_nao_so_para_o_stderr():
    """Aviso que só existe no log é o mesmo defeito que a auditoria da entrega tinha.

    Até 10/08/2026 a auditoria DETECTAVA a divergência e morria no log do Cloud Run. As 3
    políticas de alerta do projeto não cobrem este caso: a de `Cron falhou` dispara quando o
    Scheduler não consegue DISPARAR o job, não quando o job roda e avisa por dentro. O aviso
    de teto da ingestão nasceu com o mesmo defeito, e este teste é o que impede a regressão.
    """
    fonte = (Path(__file__).resolve().parents[1] / "scripts" /
             "ingest_captacoes_railway.py").read_text()
    assert "from scripts.aviso_dm import avisa_no_dm" in fonte, (
        "a ingestão não importa o avisador do DM")
    codigo = "\n".join(l for l in fonte.splitlines()
                       if not l.strip().startswith("#"))
    trecho = codigo[codigo.index("if fracao > AVISA_ACIMA_DE:"):]
    assert "avisa_no_dm(" in trecho, (
        "o aviso de teto voltou a ficar só no stderr")


def test_o_avisador_do_DM_nunca_levanta_excecao():
    """Contrato do módulo: aviso que derruba o job que ele vigia é pior que aviso nenhum.

    Transformaria um problema pequeno ("a rodada está lenta") num grande ("a ingestão
    parou"). Por isso toda falha volta como dicionário e nada propaga.
    """
    import sys
    raiz = Path(__file__).resolve().parents[1]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from scripts.aviso_dm import avisa_no_dm

    def explode(*_a, **_k):
        raise RuntimeError("slack fora do ar")

    r = avisa_no_dm(["x"], "y", poster=explode, canal="D_TESTE")
    assert r["ok"] is False and "slack fora do ar" in r["erro"]


def test_o_avisador_manda_o_resumo_e_o_bloco_de_linhas():
    """O resumo vira texto do Slack e as linhas viram bloco de código, nessa ordem."""
    import sys
    raiz = Path(__file__).resolve().parents[1]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from scripts.aviso_dm import avisa_no_dm

    capturado = {}

    def poster(canal, blocos, resumo):
        capturado.update(canal=canal, blocos=blocos, resumo=resumo)
        return {"ok": True}

    avisa_no_dm(["linha A", "linha B"], "resumo aqui", poster=poster, canal="D_TESTE")
    assert capturado["canal"] == "D_TESTE"
    assert capturado["resumo"] == "resumo aqui"
    assert "resumo aqui" in capturado["blocos"][0]["text"]["text"]
    assert "linha A\nlinha B" in capturado["blocos"][1]["text"]["text"]

    # Sem linhas, manda só o resumo — não um bloco de código vazio.
    capturado.clear()
    avisa_no_dm(None, "só o resumo", poster=poster, canal="D_TESTE")
    assert len(capturado["blocos"]) == 1
