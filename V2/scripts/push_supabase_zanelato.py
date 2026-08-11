"""Empurra os leads dos últimos 90 dias para o Supabase da agência Zanelato.

POR QUE EMPURRAR, EM VEZ DE ELES LEREM O NOSSO BANCO
====================================================
A entrega original era por leitura: criamos um banco `dash` e demos um usuário só de
SELECT. Funcionava, mas a agência passou dias sem conseguir conectar, e a causa nunca
foi permissão nem bloqueio de IP: era a ferramenta DELES não conseguindo configurar o
TLS contra o Cloud SQL, cujo certificado é de autoridade interna e não fecha cadeia com
raiz pública. Invertendo o sentido, o cliente de conexão passa a ser o NOSSO, que a
gente controla, e o problema deixa de existir em vez de ser contornado.

De quebra, some a credencial de leitura na nossa base. Depois do episódio da senha do
Postgres num repositório público, menos porta é melhor.

Ironia registrada para a próxima vez: o certificado do pooler do Supabase TAMBÉM não
fecha cadeia com raiz pública. A conexão daqui falha com `CERTIFICATE_VERIFY_FAILED` se
o contexto verificar. `sslmode=require`, que foi o que eles pediram, significa
exatamente "criptografa e não verifica" — o mesmo conselho que a gente deu pra eles.

A CADÊNCIA MANDA NO DESENHO
===========================
O job da entrega antiga reconstrói a tabela inteira, e o docstring do `refresh()` no
`provisiona_dash_zanelato` explica por que a carga incremental foi rejeitada em
06/08/2026: era 3x mais lenta e abria risco de falha silenciosa. Aquele raciocínio
valia para um job diário das 07:30 num banco nosso. Aqui a cadência pedida é de 5 em 5
minutos, e reescrever 130 mil linhas a cada 5 minutos não é "mais lento", é impossível:
a tabela ficaria em reconstrução permanente.

O erro de 06/08 foi otimizar a ESCRITA quando o custo estava na LEITURA. Aqui as duas
encolhem: `sql_fonte(janela=True)` só traz o que mudou. Medido em 09/08/2026, nas
últimas 24h: 3.190 linhas mexidas em `analytics.leads` e 440 em `analytics.cadastros`,
de universos de 366 mil e 455 mil. Numa rodada de 5 minutos são dezenas de linhas.

O QUE A TABELA DELES ACEITA (medido em 10/08/2026, não suposto)
===============================================================
`public.leads_inbound` tem 13 colunas: as 11 que a gente preenche, mais `id` (identidade
automática, não mandamos) e `recebido_em` (default `now()`, não mandamos).

A CHAVE PRIMÁRIA É `id`, e NÃO existe restrição de unicidade em (email, data). Isso tem
duas consequências práticas:

  1. `INSERT ... ON CONFLICT` NÃO funciona aqui. Sem índice único, o Postgres não tem
     em que conflitar. O upsert é feito à mão: apaga as chaves do lote, insere o lote.
     É idempotente do mesmo jeito, e é o motivo mais forte para a permissão de DELETE.
  2. Sem o índice, duas rodadas simultâneas duplicariam linha em silêncio. Por isso o
     SELECT daqui já sai deduplicado por (email, data): a defesa não pode depender de
     uma restrição que não existe do outro lado.

Vale pedir a eles um `CREATE UNIQUE INDEX ON public.leads_inbound (email, data)`. É uma
linha, dispensa o apaga-e-insere e fecha a porta da duplicação. Não bloqueia nada.

A MARCA D'ÁGUA VEM DO DESTINO
=============================
`max(recebido_em)` na tabela deles é o horário da NOSSA última gravação, porque a coluna
tem default `now()`. Usar isso como marca, em vez de guardar estado do nosso lado, dá
duas coisas de graça: não preciso criar tabela de controle (e não tenho permissão para
criar nada no schema deles), e se eles truncarem a tabela a marca desaparece junto, o
que faz a próxima rodada perceber em vez de continuar de um ponteiro que não vale mais.

A janela tem FOLGA em vez de ser marca exata. Marca exata perde linha quando os relógios
das duas pontas discordam ou quando uma rodada falha e a seguinte avança o ponteiro.
Com folga, a rodada seguinte reprocessa o mesmo intervalo, e o apaga-e-insere por chave
faz disso um não-evento. Mesma convenção do `leads_unify.py`.

OS QUATRO MODOS
===============
`--full`         Primeira carga e recuperação. Manda os 90 dias inteiros.
`--incremental`  De 5 em 5 minutos. Só o que mudou desde a última gravação.
`--podar`        1x/dia. Apaga o que passou de 90 dias — sem isto a janela deixa de
                 ser de 90 dias e a tabela cresce para sempre.
`--auditar`      1x/dia. Compara origem e destino por mês e FALHA ALTO se divergir.

POR QUE O `--auditar` É OBRIGATÓRIO, E NÃO ENFEITE
==================================================
Porque os outros três modos dependem de eu ter acertado a lista de tudo que faz uma
linha mudar, e o histórico deste projeto diz que essa aposta falha: a URL de captura
passou meses em 35% de cobertura porque UMA fonte tinha sido esquecida na consulta, e
ninguém soube. A auditoria não confia na minha lista: conta as linhas dos dois lados,
por mês, e quebra com a diferença no erro. Total igual pode esconder um mês a menos
compensando outro a mais, por isso é por mês e não só o total.

`--incremental` e `--podar` podem falhar quietos sem tragédia, porque a auditoria os
cobre. A auditoria é a única que não pode falhar quieta.

USO
===
    python -m scripts.push_supabase_zanelato --full
    python -m scripts.push_supabase_zanelato --incremental
    python -m scripts.push_supabase_zanelato --podar
    python -m scripts.push_supabase_zanelato --auditar
"""
from __future__ import annotations

import argparse
import os
import ssl
import subprocess
import sys
from datetime import datetime, timedelta
from urllib.parse import unquote, urlparse

# Reaproveita a definição ÚNICA da entrega. Se este script montasse a sua própria
# consulta de leads, ela divergiria da do `provisiona` na primeira coluna nova, e a
# divergência apareceria como dado trocado no painel da agência.
from scripts.provisiona_dash_zanelato import origem_leitura, sql_fonte

TABELA_DESTINO = "public.leads_inbound"
SEGREDO_URL = "dash-zanelato-supabase-url"
PROJETO_GCP = "smart-ads-451319"

DIAS = 90
LOTE = 500
FOLGA_MINUTOS = 15

# Fuso em que a coluna `data` é entregue. NÃO é preferência estética: até 10/08/2026 a
# entrega saía em UTC, e a agência compara essa coluna com a planilha de leads dela e
# com o painel da Meta, os dois em horário de Brasília.
#
# O sintoma foi um "leads faltando" que não existia. Ela apontou 15 leads do dia 09/08
# ausentes da entrega; 14 estavam lá, datados 10/08. Os 14 chegaram entre 00:05 e 02:55
# UTC, ou seja, entre 21:05 e 23:55 de Brasília do dia 09 — todos, sem exceção. Não é
# coincidência de fronteira, é desvio sistemático de 3 horas: TODO lead que entra depois
# das 21h aparecia no dia seguinte para ela.
#
# Por que isso passou batido: a conexão de leitura tem `TimeZone = UTC` (verificado com
# `SHOW TimeZone`), e `to_char(timestamptz, 'YYYY-MM-DD')` renderiza no fuso da SESSÃO.
# Ou seja, o código não dizia UTC em lugar nenhum; o UTC vinha do ambiente. É o tipo de
# erro que não aparece na revisão do SQL, só na conferência contra o dado do cliente.
#
# Consequência prática de errar: o CPL por dia dela fica errado nas duas pontas (leads
# da noite contados no dia seguinte, contra gasto do dia certo), e a diferença é maior
# justamente nos dias de pico, que são os que decidem verba.
FUSO = "America/Sao_Paulo"

# A fronteira da janela de 90 dias, como EXPRESSÃO ÚNICA. A carga, a poda e a auditoria
# avaliam este mesmo texto, cada uma na conexão que já tem na mão.
#
# Tem que ser o mesmo DIA em que a coluna `data` é gravada, e é por isso que sai de
# `now() AT TIME ZONE FUSO` e não de `current_date`: `current_date` numa sessão em UTC dá
# o dia em UTC. Com a `data` em Brasília e a fronteira em UTC, o lead que chegasse entre
# 00h e 03h UTC do dia da fronteira seria gravado com data de um dia ANTES do corte — a
# carga o inseria, a poda o apagava, e isso se repetiria a cada rodada, para sempre.
CORTE_SQL = f"((now() AT TIME ZONE '{FUSO}')::date - {DIAS})"

# As 11 colunas da tabela deles, na ordem em que o SELECT abaixo as produz. `id` e
# `recebido_em` ficam de fora: o primeiro é identidade automática, o segundo tem
# default `now()` — medido em 10/08/2026, não suposto.
COLUNAS = ["nome", "email", "telefone", "source", "medium", "campaign", "term",
           "content", "data", "tem_computador", "utm_url"]


def _ctx() -> ssl.SSLContext:
    """`sslmode=require`: criptografa e NÃO verifica o certificado.

    Não é desleixo, é o que o destino aceita: o pooler do Supabase apresenta cadeia que
    não fecha com raiz pública, e verificar falha com `CERTIFICATE_VERIFY_FAILED`. Foi
    exatamente o que eles pediram na credencial que mandaram.
    """
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def destino(porta: int | None = None):
    """Conexão com o Supabase da agência.

    A URL vem do Secret Manager, NUNCA de arquivo no repositório: este repo é público,
    e uma senha de Postgres já vazou nele uma vez (fechado em 05/08/2026). Se alguém
    for tentado a colar a string aqui para "testar rápido", é este comentário que ele
    tem que ler primeiro.

    Porta 6543 é o pooler em modo transação, indicado por eles para o sync contínuo;
    5432 é conexão direta, indicada para carga grande. As duas foram testadas e
    funcionam com o nosso cliente.
    """
    url = os.environ.get("SUPABASE_ZANELATO_URL") or subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         f"--secret={SEGREDO_URL}", f"--project={PROJETO_GCP}"],
        capture_output=True, text=True, timeout=120).stdout.strip()
    if not url:
        raise RuntimeError(f"sem credencial: exporte SUPABASE_ZANELATO_URL ou "
                           f"dê acesso ao segredo {SEGREDO_URL}")
    u = urlparse(url)
    import pg8000.native
    return pg8000.native.Connection(
        host=u.hostname, port=porta or u.port or 5432,
        database=(u.path or "/").lstrip("/") or "postgres",
        user=unquote(u.username or ""), password=unquote(u.password or ""),
        ssl_context=_ctx(), timeout=600)


def _select(janela: bool) -> str:
    """Traduz a entrega de 27 colunas para as 11 que eles pediram.

    `DISTINCT ON (email, data)` não é zelo: a tabela deles não tem restrição de
    unicidade, então uma linha repetida entraria calada e a agência contaria o mesmo
    lead duas vezes. A defesa mora aqui porque não pode morar lá.

    `data` sai como texto no formato que eles pediram (YYYY-MM-DD) porque a coluna é
    `text`, não `date`. Mandar um objeto de data deixaria o Postgres formatar do jeito
    dele, e o formato viraria surpresa.

    `data` sai em HORÁRIO DE BRASÍLIA, e isso é o oposto do que fazíamos até
    10/08/2026. Ver `FUSO` para o porquê e para a medição.
    """
    # No modo janela, o ledger também é recortado pelo que chegou desde `:desde`. Sem
    # isto o incremental leria os 90 dias do ledger a cada rodada, e a rodada de 5
    # minutos passaria a custar como uma carga cheia.
    filtro_ledger = "AND r.created_at >= :desde" if janela else ""
    return f"""
      SELECT DISTINCT ON (email, data)
             nome, email, telefone, source, medium, campaign, term, content,
             data, tem_computador, utm_url
        FROM (
          -- FONTE 1: a entrega curada. Passa por matching, calendário de lançamento e
          -- dedupe, e é a MESMA definição usada na entrega do nosso banco. Mas lê
          -- `analytics.leads` e `analytics.cadastros`, que são reconstruídas UMA VEZ
          -- POR DIA (09:00 e 10:00). Por isso ela sozinha nunca tem o lead de hoje.
          SELECT q.nome,
                 lower(q.email)                        AS email,
                 q.telefone,
                 q.utm_source                          AS source,
                 q.utm_medium                          AS medium,
                 q.utm_campaign                        AS campaign,
                 q.utm_term                            AS term,
                 q.utm_content                         AS content,
                 to_char(q.capturado_em AT TIME ZONE '{FUSO}', 'YYYY-MM-DD') AS data,
                 q.tem_computador,
                 q.url_captura                         AS utm_url,
                 1 AS prio
            FROM ({sql_fonte(janela=janela, magro=True)}) q
           -- Corte por DIA, e não por instante. A primeira versão usava
           -- `capturado_em >= now() - interval '90 days'`, que é um instante, enquanto
           -- a coluna `data` do destino guarda só o dia. Medido em 10/08/2026: entre a
           -- carga (13:59) e a auditoria o relógio andou, 14 linhas do dia 12/05
           -- saíram da janela da ORIGEM continuando no DESTINO, e a auditoria acusou
           -- divergência de +14 onde não havia erro. Auditoria que dá falso positivo
           -- todo dia ensina a ignorar auditoria. As três operações (carga, poda e
           -- auditoria) usam a MESMA fronteira de dia, e no MESMO fuso da coluna.
           WHERE (q.capturado_em AT TIME ZONE '{FUSO}')::date >= {CORTE_SQL}
             AND nullif(q.email, '') IS NOT NULL

          UNION ALL

          -- FONTE 2: o LEDGER VIVO. Recebe o lead em minutos, via a fila do Pub/Sub.
          --
          -- Ela existe porque a fonte 1 não serve ao caso de uso. A agência abre o
          -- painel várias vezes por dia para decidir verba, e até 10/08/2026 a entrega
          -- só tinha o lead do dia seguinte. Pior: eu tinha respondido a um pedido de
          -- atualização de 5 em 5 minutos dizendo que não fazia sentido "porque a
          -- origem só muda uma vez por dia" — o que era defender a limitação em vez de
          -- removê-la. Medido no dia em que isto foi escrito: o ledger tinha 165 leads
          -- que as tabelas derivadas ainda não tinham.
          --
          -- Cobertura medida no ledger nos 7 dias anteriores: nome 100%, telefone
          -- 99,2%, source 100%, tem_computador 100%, url 100%, e as UTM de medium,
          -- campanha, termo e conteúdo entre 88% e 93%. Ou seja, a linha que vem daqui
          -- não é pior que a da fonte 1 em nada que a agência use.
          --
          -- `prio = 2`: quando o mesmo lead existe nas duas, a fonte 1 ganha. Assim a
          -- linha que já foi entregue não muda de valor quando o lead aparece nas
          -- derivadas no dia seguinte — só linhas NOVAS vêm daqui.
          --
          -- NÃO seleciona `lead_score`, `decil`, `score_champion`, `decil_challenger`
          -- nem nada derivado: score por lead é proibido nesta entrega, e este é o
          -- ponto do código onde seria mais fácil vazar sem querer, porque a tabela
          -- tem todas essas colunas ao lado das que a gente usa.
          SELECT nullif(trim(concat_ws(' ', r.first_name, r.last_name)), '') AS nome,
                 lower(r.email)                        AS email,
                 nullif(r.phone, '')                   AS telefone,
                 lower(nullif(r.utm_source, ''))       AS source,
                 nullif(r.utm_medium, '')              AS medium,
                 nullif(r.utm_campaign, '')            AS campaign,
                 nullif(r.utm_term, '')                AS term,
                 nullif(r.utm_content, '')             AS content,
                 -- Dois `AT TIME ZONE` em sequência, e os dois são necessários. Esta
                 -- coluna é `timestamp WITHOUT time zone` guardando UTC (a de
                 -- `analytics.leads` é `WITH time zone`; verificado, não suposto). O
                 -- primeiro diz ao Postgres em que fuso o número está — sem ele, ele
                 -- assume o fuso da sessão e a conversão erra. O segundo converte para
                 -- Brasília. Um só, aqui, daria 3 horas de erro na direção contrária.
                 to_char(r.created_at AT TIME ZONE 'UTC' AT TIME ZONE '{FUSO}',
                         'YYYY-MM-DD')                 AS data,
                 nullif(r.has_computer, '')            AS tem_computador,
                 nullif(r.utm_url, '')                 AS utm_url,
                 2 AS prio
            FROM public.registros_ml r
           WHERE (r.created_at AT TIME ZONE 'UTC' AT TIME ZONE '{FUSO}')::date
                 >= {CORTE_SQL}
             AND nullif(r.email, '') IS NOT NULL
             {filtro_ledger}
        ) u
       ORDER BY email, data, prio
    """


def _le(janela: bool, desde: datetime | None = None) -> list:
    origem = origem_leitura(timeout=1800)
    try:
        # Sem `sal`: no modo magro a consulta não calcula o hash `lead_id`, então não
        # há parâmetro para preencher. É o que tira do job a dependência do segredo
        # `dash-lead-id-salt`, que ele pedia só para descartar o resultado.
        params = {}
        if janela:
            params["desde"] = desde
        return origem.run(_select(janela), **params)
    finally:
        origem.close()


def _grava(dst, linhas: list, *, apagar_chaves: bool) -> int:
    """Apaga as chaves do lote e insere o lote. Upsert na mão.

    Por que na mão: a tabela deles não tem índice único em (email, data), então
    `ON CONFLICT` não tem em que conflitar. Apagar-e-inserir escopado às chaves do
    lote dá o mesmo resultado e é idempotente — é o que permite usar janela com folga
    sem medo de duplicar.

    LIMITE QUE IMPORTA NA HORA DE SUBIR MUDANÇA: o escopo do DELETE é (email, data). Se a
    `data` de um lead MUDAR de valor entre duas versões deste código, o incremental apaga
    a chave NOVA e insere, e a linha com a data ANTIGA fica órfã ao lado — o lead aparece
    duas vezes para a agência. Aconteceria com o conserto de fuso de 10/08/2026, que
    mudou a data de ~12% das linhas. Por isso: toda mudança que altere o VALOR de `data`
    exige uma `--full` logo depois do deploy, não é opcional.
    """
    if not linhas:
        return 0
    total = 0
    for i in range(0, len(linhas), LOTE):
        pedaco = linhas[i:i + LOTE]
        if apagar_chaves:
            # Remove só as (email, data) que estão neste lote. Nada além delas.
            cond, par = [], {}
            for j, linha in enumerate(pedaco):
                par[f"e{j}"], par[f"d{j}"] = linha[1], linha[8]
                cond.append(f"(email = :e{j} AND data = :d{j})")
            dst.run(f"DELETE FROM {TABELA_DESTINO} WHERE " + " OR ".join(cond), **par)
        vals, par = [], {}
        for j, linha in enumerate(pedaco):
            marcas = []
            for k, v in enumerate(linha):
                nome = f"p{j}_{k}"
                par[nome] = v
                marcas.append(f":{nome}")
            vals.append("(" + ",".join(marcas) + ")")
        dst.run(f"INSERT INTO {TABELA_DESTINO} ({','.join(COLUNAS)}) VALUES "
                + ",".join(vals), **par)
        total += len(pedaco)
    return total


def full() -> dict:
    """Carga cheia dos 90 dias. Primeira vez e recuperação."""
    linhas = _le(janela=False)
    print(f"  {len(linhas):,} linhas nos últimos {DIAS} dias")
    dst = destino(porta=5432)          # direta: eles indicaram esta para carga grande
    try:
        dst.run("BEGIN")
        antes = dst.run(f"SELECT count(*) FROM {TABELA_DESTINO}")[0][0]
        dst.run(f"DELETE FROM {TABELA_DESTINO}")
        n = _grava(dst, linhas, apagar_chaves=False)
        dst.run("COMMIT")
        print(f"  destino: {antes:,} -> {n:,} linhas")
        return {"modo": "full", "antes": antes, "depois": n}
    finally:
        dst.close()


def incremental(minutos: int = FOLGA_MINUTOS) -> dict:
    """Só o que mudou desde a nossa última gravação. Roda de 5 em 5 minutos."""
    dst = destino(porta=6543)          # pooler: eles indicaram esta para sync contínuo
    try:
        marca = dst.run(f"SELECT max(recebido_em) FROM {TABELA_DESTINO}")[0][0]
        if marca is None:
            # Tabela vazia: pode ser primeira execução ou alguém truncou. Em nenhum dos
            # dois casos o incremental deve adivinhar uma janela — isso deixaria o
            # destino permanentemente incompleto, em silêncio.
            print("destino vazio (primeira vez ou truncado): rode --full",
                  file=sys.stderr)
            return {"modo": "incremental", "erro": "destino_vazio"}
        desde = marca - timedelta(minutes=minutos)
        print(f"janela: desde {desde.isoformat()} "
              f"(última gravação {marca.isoformat()}, folga {minutos} min)")
        linhas = _le(janela=True, desde=desde)
        print(f"  {len(linhas):,} linhas mudaram")
        dst.run("BEGIN")
        n = _grava(dst, linhas, apagar_chaves=True)
        dst.run("COMMIT")
        print(f"  {n:,} gravadas")
        return {"modo": "incremental", "linhas": n}
    finally:
        dst.close()


def podar() -> dict:
    """Apaga o que saiu da janela de 90 dias.

    Sem esta passada a tabela cresce para sempre e a "janela de 90 dias" combinada com
    o cliente deixa de ser verdade. É o outro motivo da permissão de DELETE.
    """
    # Mesma fronteira de dia da carga e da auditoria: a expressão de `CORTE_SQL`, avaliada
    # na conexão que esta função já tem na mão. Antes era calculada aqui em Python, em
    # UTC; virou SQL quando a coluna `data` passou a sair em horário de Brasília, porque
    # fronteira num fuso e valor em outro apaga a linha da borda a cada rodada.
    dst = destino(porta=5432)
    try:
        limite = str(dst.run(f"SELECT ({CORTE_SQL})::text")[0][0])
        antes = dst.run(f"SELECT count(*) FROM {TABELA_DESTINO}")[0][0]
        dst.run("BEGIN")
        dst.run(f"DELETE FROM {TABELA_DESTINO} WHERE data < :lim", lim=limite)
        dst.run("COMMIT")
        depois = dst.run(f"SELECT count(*) FROM {TABELA_DESTINO}")[0][0]
        print(f"poda em data < {limite}: {antes:,} -> {depois:,} ({antes - depois:,} removidas)")
        return {"modo": "podar", "removidas": antes - depois}
    finally:
        dst.close()


def _avisa_no_dm(linhas_texto: list, resumo: str, poster=None, canal: str = "") -> dict:
    """Manda o resultado da auditoria para o DM. NUNCA levanta exceção.

    POR QUE ISTO EXISTE: até 10/08/2026 a auditoria detectava a divergência, saía com
    erro, e o erro morria no log do Cloud Run. Ninguém olha log por hábito. Verificado
    no dia: das 3 políticas de alerta do projeto, nenhuma cobre este job — a de
    `Cron falhou` dispara quando o Scheduler não consegue DISPARAR o job (403/500), não
    quando o job roda e falha por dentro. Ou seja, a defesa mais importante da entrega
    era invisível, e uma defesa que ninguém vê não é defesa.

    MANDA TAMBÉM QUANDO ESTÁ TUDO CERTO, em uma linha. Não é enfeite: sem a mensagem de
    "bateu", silêncio significa duas coisas ao mesmo tempo (nada divergiu, ou o job não
    rodou), e são justamente essas duas que precisam ser distinguidas. Uma linha por dia
    resolve a ambiguidade. Se virar ruído, o que se corta é a linha do sucesso, não a
    do erro.

    `poster` e `canal` são injetáveis para o teste rodar sem Slack.
    """
    if poster is None:
        try:
            from src.monitoring.slack_client import post_blocks as poster
        except Exception as e:                            # sem o pacote, segue a vida
            return {"ok": False, "erro": f"import: {e}"}
    # Mesma cadeia de resolução do resto do projeto (`cost_alert`, `app.py`), incluindo o
    # mesmo último recurso fixo. O ID do DM não é segredo, e deixá-lo aqui evita o pior
    # caso: variável esquecida no job faz o aviso virar um no-op silencioso, que é
    # exatamente o defeito que esta função existe para consertar.
    canal = canal or os.getenv("SLACK_USER_DM") or os.getenv(
        "SLACK_VALIDATION_DM_CHANNEL") or "D0A9USV3XEX"
    blocos = [{"type": "section",
               "text": {"type": "mrkdwn", "text": resumo}}]
    if linhas_texto:
        blocos.append({"type": "section",
                       "text": {"type": "mrkdwn",
                                "text": "```\n" + "\n".join(linhas_texto) + "\n```"}})
    try:
        return poster(canal, blocos, resumo)
    except Exception as e:                                # contrato: nunca derruba
        return {"ok": False, "erro": str(e)}


def auditar() -> dict:
    """Compara origem e destino por mês. Avisa no DM e sai com erro se divergir.

    É esta defesa que torna a carga incremental aceitável numa entrega para terceiro.
    As outras dependem de eu ter listado certo todas as origens de mudança; esta não
    depende de nada meu, só conta as duas pontas.
    """
    origem = origem_leitura(timeout=1800)
    try:
        # A MESMA fronteira de dia usada pela carga e pela poda, calculada de um lado só
        # e aplicada nos dois. Calcular duas vezes, uma em cada ponta, foi o que gerou o
        # falso positivo de +14 em 10/08/2026.
        corte = str(origem.run(f"SELECT ({CORTE_SQL})::text")[0][0])
        esperado = {str(r[0]): int(r[1]) for r in origem.run(
            f"SELECT substr(data,1,7), count(*) FROM ({_select(False)}) s GROUP BY 1")}
    finally:
        origem.close()
    dst = destino(porta=5432)
    try:
        obtido = {str(r[0]): int(r[1]) for r in dst.run(
            f"SELECT substr(data,1,7), count(*) FROM {TABELA_DESTINO} "
            f"WHERE data >= :c GROUP BY 1", c=corte)}
        # Linhas que já saíram da janela e ainda não foram podadas. NÃO é divergência:
        # é trabalho pendente da poda diária, e some sozinho. Reportado à parte de
        # propósito, porque misturar as duas coisas é o que faz uma auditoria virar
        # ruído e ser ignorada.
        a_podar = dst.run(f"SELECT count(*) FROM {TABELA_DESTINO} WHERE data < :c",
                          c=corte)[0][0]
    finally:
        dst.close()

    print(f"corte da janela: data >= {corte} ({DIAS} dias)")
    print(f"{'mês':<9} {'origem':>9} {'destino':>9} {'dif':>8}")
    tabela, ruins = [f"{'mês':<9} {'origem':>9} {'destino':>9} {'dif':>8}"], []
    for m in sorted(set(esperado) | set(obtido)):
        e, o = esperado.get(m, 0), obtido.get(m, 0)
        linha = f"{m:<9} {e:>9,} {o:>9,} {o - e:>+8,}"
        print(linha)
        tabela.append(linha)
        if o != e:
            ruins.append((m, e, o))
    if a_podar:
        print(f"\n(fora da janela, aguardando poda: {a_podar:,} linhas — não é divergência)")
        tabela.append(f"fora da janela, aguardando poda: {a_podar:,} (não é divergência)")

    if ruins:
        det = "; ".join(f"{m}: origem {e:,} destino {o:,} ({o - e:+,})" for m, e, o in ruins)
        # DM ANTES do SystemExit. Invertido, o `raise` mataria o processo e o aviso nunca
        # sairia — que é exatamente o defeito que esta mudança conserta.
        _avisa_no_dm(
            tabela,
            f":rotating_light: *Entrega Zanelato: a auditoria não bateu.*\n"
            f"{len(ruins)} mês(es) divergindo. A tabela deles está diferente do que a "
            f"nossa consulta produz, e o incremental não conserta isso sozinho.\n"
            f"*O que fazer:* rodar a carga cheia (`--full`) e auditar de novo.")
        raise SystemExit(f"AUDITORIA FALHOU — {len(ruins)} mês(es) divergindo: {det}")

    total = sum(esperado.values())
    print(f"\nOK: {total:,} linhas, todos os meses batem")
    _avisa_no_dm(
        [],
        f":white_check_mark: Entrega Zanelato conferida: *{total:,} leads*, "
        f"todos os {len(esperado)} meses batem."
        + (f" ({a_podar:,} linhas aguardando a poda.)" if a_podar else ""))
    return {"modo": "auditar", "linhas": total, "a_podar": a_podar}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true", help="carga cheia dos 90 dias")
    g.add_argument("--incremental", action="store_true", help="só o que mudou (cada 5 min)")
    g.add_argument("--podar", action="store_true", help="apaga o que passou de 90 dias (1x/dia)")
    g.add_argument("--auditar", action="store_true", help="compara origem x destino e falha se divergir")
    ap.add_argument("--minutos", type=int, default=FOLGA_MINUTOS,
                    help=f"folga da janela em minutos (default {FOLGA_MINUTOS})")
    a = ap.parse_args()

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, raiz)
    # `load_dotenv` e não `source .env`: o `source` mutila credencial com espaço ou
    # barra vertical no valor, e já quebrou neste projeto.
    from dotenv import load_dotenv
    load_dotenv(os.path.join(raiz, ".env"))

    if a.full:
        full()
    elif a.incremental:
        incremental(minutos=a.minutos)
    elif a.podar:
        podar()
    else:
        auditar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
