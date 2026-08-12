"""Ingere os cadastros do Railway para `analytics.captacoes`, uma linha por INSCRIÇÃO.

POR QUE ESTE SCRIPT EXISTE
==========================
A entrega para o gestor de tráfego passou a ter uma fonte só, a `captacoes` (decisão de
11/08/2026). O caminho é:

    Railway (Client LEFT JOIN UTMTracking)  ->  analytics.captacoes  ->  Supabase deles

Antes disso a `captacoes` era montada por processo AD-HOC a partir das planilhas do Drive.
Procurado em todo o `V2` em 11/08/2026: NENHUM script commitado escrevia nela. É por isso
que ela parou sozinha em 03/08 e ninguém percebeu — e é por isso que o LF64 inteiro estava
com ZERO linhas nela enquanto o lançamento já estava rodando.

DE ONDE VEM CADA COISA, E POR QUE DESTAS TABELAS
================================================
- **`Client`** é a base: uma linha por PESSOA, viva (medido: registro mais novo com 2
  minutos de idade), e é a única do Railway que tem TODO MUNDO — respondente da pesquisa
  ou não. É dela que sai nome, e-mail, telefone e `hasComputer`.
- **`UTMTracking`** é o evento: uma linha por passagem rastreada, com `source`, `medium`,
  `campaign`, `term`, `content` e `url`. É ela que dá o GRÃO de inscrição.

O GRÃO, E O LIMITE HONESTO DELE
===============================
`Client` é 1,00 linha por pessoa: ela NÃO SABE dizer que alguém se inscreveu duas vezes.
Quem sabe é a `UTMTracking`, que tem 1,06 linha por pessoa (7.328 pessoas com 2+ linhas).

Então "uma linha por inscrição" é, na prática:

  - pessoa com N eventos na `UTMTracking`  ->  N linhas, cada uma com a sua data e a sua UTM
  - pessoa com ZERO eventos               ->  1 linha, UTM nula, data do cadastro

É o máximo que o Railway permite hoje. Não é uma escolha de desenho, é o teto da fonte.

A JANELA TEM FOLGA, MAS PEQUENA — E O NÚMERO É MEDIDO
=====================================================
A folga existe porque a linha da `UTMTracking` pode chegar DEPOIS da do `Client`. Sem ela,
o job leria o lead recém-cadastrado sem campanha, gravaria, e nunca voltaria a olhar para
ele: a campanha chegaria e ninguém iria buscar.

Quanto de folga, medido em 11/08/2026 sobre 36.621 cadastros de 30 dias (atraso =
`trackedAt` − `createdAt`):

    chegou antes ou junto ..........   0,2%
    chegou em até 1 HORA ...........  98,3%
    entre 1h e 48h .................   0,0%   <- zero, não "pouco"
    depois de 48h ..................   6 casos em 36.621
    nunca chegou ...................   1,6%

Por isso a folga é de HORAS e não de dias. A primeira versão deste script usava 48 horas,
que era chute meu: erra por um fator de 48 e, numa cadência de 5 minutos, faria 288
rodadas por dia relerem dois dias de Railway cada uma, sem ganhar nada.

CUIDADO AO INTERPRETAR COBERTURA BAIXA COMO ATRASO
==================================================
Medindo por janela, os cadastros dos últimos 7 dias apareciam com só 78,2% de UTM, contra
98,4% nos de 30 dias. É tentador ler isso como defasagem e aumentar a folga. NÃO era.

Por semana, a taxa de cadastro SEM nenhuma linha de UTM ficou entre 0,2% e 1,7% durante
oito semanas seguidas (01/06 a 27/07/2026) e saltou para 8,4% na semana de 03/08 e 5,4% na
de 10/08. É um degrau, não uma curva: falha de cobertura no front, confirmada por quem
cuida dele. Folga nenhuma conserta dado que nunca foi gravado — aumentar a janela só
esconderia o problema atrás de mais leitura.

O `lf` E A SENTINELA
====================
`lf` sai do calendário de lançamento por data de captação. Existe cadastro FORA de
qualquer janela (medido: 04/08 a 06/08 de 2026 cai entre o fim do DEV21 e o início do
LF64). Esse lead entra com `lf = 'SEM_LF'`, e não descartado: a agência pagou por ele.

O QUE ESTE SCRIPT NÃO FAZ (INTENÇÃO REGISTRADA, NÃO ESQUECIDA)
==============================================================
Ele preenche `utm_medium`, `utm_term` e `utm_url` só das linhas que ele mesmo insere, ou
seja, da janela que a entrega usa. As ~503 mil linhas históricas, que vieram das
planilhas, continuam com essas três colunas nulas — as planilhas não as traziam.

Completar o histórico é trabalho separado e combinado para depois (11/08/2026). Quando for
feito, a fonte da `utm_url` antiga já existe e está mapeada: `public.lead_legado`
(fev a mai/2026) e `analytics.url_captura_legado` (jan e fev/2026), as mesmas que a entrega
usa hoje para essa coluna. Para `medium` e `term` a fonte é a `UTMTracking`, que tem 143
mil linhas contra 503 mil da `captacoes`, então a recuperação será PARCIAL por construção.

Uso:
  python scripts/ingest_captacoes_railway.py --check              # só conta, não escreve
  python scripts/ingest_captacoes_railway.py --desde 2026-08-04   # backfill de um ponto
  python scripts/ingest_captacoes_railway.py                      # incremental com folga
"""
from __future__ import annotations

import argparse
import os
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv                                          # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from src.data.analytics_connection import open_analytics_connection     # noqa: E402

TABELA = "analytics.captacoes"
CLIENTE = "devclub"
SEM_LF = "SEM_LF"
# 2 horas cobre com sobra o atraso REAL da UTMTracking (98,3% chegam em menos de 1h, e
# entre 1h e 48h chegam zero). Ver o cabeçalho: 48h era chute e erra por um fator de 48.
FOLGA_HORAS = 2
LOTE = 500
FUSO = "America/Sao_Paulo"

# Limite do job no Cloud Run, e a fração dele a partir da qual esta rodada RECLAMA.
#
# NÃO existe teto de linhas por rodada, e é decisão medida. Em 11/08/2026, cronometrado
# contra o Railway de verdade:
#
#     1 dia   ->    639 registros em 3,7s
#     8 dias  ->  2.558 registros em 3,0s
#    30 dias  -> 39.684 registros em 6,6s   (+ 0,10s para montar em Python)
#
# Um atraso catastrófico de 30 dias cabe em 7 segundos de um limite de 600. Fatiar em lotes
# com avanço parcial da marca resolveria o caso "volume maior que o job aguenta", mas esse
# caso está 85x longe, e código para um problema que não existe é código que ninguém testa.
#
# O que fica no lugar é o AVISO. Falhar por volume seria silencioso: o job morre no limite,
# a transação é desfeita, a marca não avança e a rodada seguinte tenta o mesmo. A auditoria
# diária pegaria a divergência, mas dias depois. Reclamar ao passar da metade do orçamento
# de tempo dá aviso ANTES de quebrar, que é a diferença entre consertar e descobrir.
TIMEOUT_JOB_S = 600
AVISA_ACIMA_DE = 0.5

# As colunas que este script escreve, na ordem do INSERT. `bought_45d`/`bought_ever` e
# `ad_base`/`ad_name` NÃO entram: são preenchidas por outro processo (casamento com vendas
# e normalização de nome de anúncio) e sobrescrevê-las com nulo apagaria dado bom.
COLUNAS = ["lf", "chave", "origem_id", "email", "phone", "phone8", "nome",
           "captured_at", "utm_source", "utm_medium", "utm_campaign", "utm_content",
           "utm_term", "utm_url", "has_computer", "planilha", "ingested_at"]

PROCEDENCIA = "railway"   # vai na coluna `planilha`, que é a de procedência da linha


def railway(timeout: int = 900):
    """Conexão de leitura no Railway. Só SELECT: este script nunca escreve lá."""
    import pg8000.native
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ.get("RAILWAY_DB_HOST", "shortline.proxy.rlwy.net"),
        port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
        database=os.environ.get("RAILWAY_DB_NAME", "railway"),
        user=os.environ.get("RAILWAY_DB_USER", "postgres"),
        password=os.environ["RAILWAY_DB_PASSWORD"],
        ssl_context=ctx, timeout=timeout,
    )


def _sql_railway() -> str:
    """Um registro por INSCRIÇÃO: `Client` como base, `UTMTracking` como evento.

    `LEFT JOIN` e não `JOIN`: com `JOIN`, os 22% de cadastros recentes cuja linha de UTM
    ainda não chegou simplesmente NÃO SERIAM ENTREGUES, e a agência veria menos lead do
    que existe — sem erro em lugar nenhum. O `LEFT JOIN` entrega a pessoa com UTM nula, e
    a rodada seguinte, na folga, completa a UTM.

    `createdAt` é `timestamp WITHOUT time zone` guardando UTC (verificado em 11/08/2026);
    `trackedAt` também. A conversão para Brasília acontece na gravação, não aqui, para
    esta consulta poder ser comparada crua com o Railway.
    """
    return """
      SELECT lower(c.email)                       AS email,
             c.phone,
             nullif(trim(concat_ws(' ', c."firstName", c."lastName")), '') AS nome,
             c."hasComputer"                      AS has_computer,
             c."createdAt"                        AS criado_em,
             u.id                                 AS utm_id,
             u."trackedAt"                        AS rastreado_em,
             u.source, u.medium, u.campaign, u.content, u.term, u.url
        FROM "Client" c
        LEFT JOIN "UTMTracking" u ON lower(u."clientEmail") = lower(c.email)
       WHERE c.email IS NOT NULL AND c.email <> ''
         AND (c."createdAt" >= :desde OR u."trackedAt" >= :desde)
    """


def _tel8(t) -> str | None:
    """Últimos 8 dígitos do telefone — a mesma chave de casamento do resto do projeto."""
    if not t:
        return None
    d = "".join(ch for ch in str(t) if ch.isdigit())
    return d[-8:] if len(d) >= 8 else None


def _calendario(c) -> list:
    """Janelas de captação, da que começa mais TARDE para a mais cedo.

    A ordem importa: três pares de janelas se sobrepõem em 2026, e a convenção do projeto
    (a mesma do relatório de criativo) é que o dia de emenda pertence ao lançamento que
    COMEÇA nele. Varrendo de trás para frente, o primeiro que casa é o certo.
    """
    return c.run("""
        SELECT lf_name, cap_start, cap_end FROM analytics.launch_calendar
         WHERE client_id = :cli ORDER BY cap_start DESC""", cli=CLIENTE)


def _lf_de(dia, cal) -> str:
    for nome, ini, fim in cal:
        if ini <= dia <= fim:
            return nome
    return SEM_LF


def _monta(linhas, cal, agora) -> list:
    """Traduz o resultado do Railway para as colunas da `captacoes`.

    A data da linha é a do EVENTO quando ele existe (`trackedAt`), e a do cadastro quando
    não existe. Usar sempre a do cadastro colapsaria as duas inscrições da mesma pessoa no
    mesmo dia, que é justamente o que o grão novo existe para não fazer.
    """
    # Dedupe pela CHAVE, dentro do próprio lote, ANTES de tocar no banco.
    #
    # Não é zelo: o Postgres RECUSA um `INSERT ... ON CONFLICT DO UPDATE` que traga a mesma
    # chave duas vezes no mesmo comando (21000, "cannot affect row a second time"). E a
    # colisão acontece de verdade — a chave primária do `Client` é `email` com o CASO
    # preservado, então `Joao@x.com` e `joao@x.com` são duas linhas lá e viram a MESMA
    # chave aqui, porque a ingestão normaliza para minúsculo. Medido em 11/08/2026:
    # 136.622 linhas no `Client` para 136.484 e-mails distintos em minúsculo.
    #
    # Guardar num dicionário pela chave resolve, e o `colapsadas` sai no log: dedupe que
    # acontece calado é o tipo de coisa que esconde crescimento de duplicata na origem.
    vistas: dict = {}
    for (email, phone, nome, has_pc, criado, utm_id, rastreado,
         src, med, camp, cont, term, url) in linhas:
        # Minúsculo AQUI, e não só no SQL. A consulta já faz `lower(c.email)`, mas a
        # invariante da CHAVE tem que morar junto com quem monta a chave: se alguém mexer
        # na consulta, a colisão por caixa volta e o Postgres recusa o lote inteiro com
        # 21000. Defesa em dois lugares custa uma linha.
        email = (email or "").strip().lower() or None
        if email is None:
            continue
        quando = rastreado or criado
        # NUNCA datar o lead ANTES de ele existir como cadastro. Medido em 11/08/2026 no
        # backfill: 28 de 1.935 linhas saíram datadas de março a julho porque a pessoa
        # tinha um evento de rastreio ANTIGO (visitou a página em março) e se cadastrou
        # agora. Datar pelo evento fazia esse lead aparecer como lead de março na contagem
        # diária da agência, quando ele virou lead em agosto.
        #
        # Não é o mesmo que ignorar o evento: quando o rastreio vem DEPOIS do cadastro (o
        # caso normal, 98,3% em menos de 1h), a data do evento é a que vale — é ela que
        # distingue a segunda inscrição da primeira.
        if quando is not None and criado is not None and quando < criado:
            quando = criado
        if quando is None:
            continue                       # sem data não há lançamento nem coluna `data`
        # O Railway guarda UTC em coluna sem fuso. Declarar antes de converter, senão o
        # Postgres assume o fuso da sessão e a data erra em 3 horas — o mesmo erro que já
        # jogou lead da noite para o dia seguinte na entrega da agência.
        quando = quando.replace(tzinfo=timezone.utc)
        dia_brt = (quando - timedelta(hours=3)).date()
        lf = _lf_de(dia_brt, cal)
        origem = f"utm:{utm_id}" if utm_id is not None else f"client:{email}"
        chave = (lf, email, origem)
        linha = [
            lf,
            email,                                        # `chave` é o e-mail
            origem,
            email, phone, _tel8(phone), nome,
            quando,
            (src or "").strip().lower() or None,
            (med or "").strip() or None,
            (camp or "").strip() or None,
            (cont or "").strip() or None,
            (term or "").strip() or None,
            (url or "").strip() or None,
            (has_pc or "").strip() or None,
            PROCEDENCIA,
            agora,
        ]
        # Empate resolvido pela linha MAIS COMPLETA, não pela última que chegou. Entre duas
        # variantes de caso do mesmo e-mail, ficar com a que tem UTM e telefone preenchidos
        # é melhor que ficar com a que veio por último por acidente de ordenação.
        anterior = vistas.get(chave)
        if anterior is None or _preenchidos(linha) > _preenchidos(anterior):
            vistas[chave] = linha
    return list(vistas.values())


def _preenchidos(linha) -> int:
    """Quantos campos da linha têm valor. Critério de desempate entre linhas iguais."""
    return sum(1 for v in linha if v not in (None, ""))


def _grava(c, linhas) -> tuple:
    """Upsert por `(lf, chave, origem_id)`, que é a chave da inscrição.

    `ON CONFLICT DO UPDATE` e não apaga-e-insere: aqui EXISTE índice único (foi a migração
    `migrate_captacoes_por_inscricao.py` que o criou), então o Postgres resolve sozinho.

    O `UPDATE` não toca em `bought_45d`, `bought_ever`, `ad_base` nem `ad_name`: essas são
    de outro processo, e sobrescrevê-las com nulo em cada rodada apagaria dado bom de
    forma invisível.
    """
    if not linhas:
        return 0, 0
    antes = c.run(f"SELECT count(*) FROM {TABELA}")[0][0]
    cols = ",".join(COLUNAS)
    atualiza = ",".join(
        f"{k}=EXCLUDED.{k}" for k in COLUNAS
        if k not in ("lf", "chave", "origem_id"))
    for i in range(0, len(linhas), LOTE):
        pedaco = linhas[i:i + LOTE]
        vals, par = [], {}
        for j, linha in enumerate(pedaco):
            marcas = []
            for k, v in enumerate(linha):
                par[f"p{j}_{k}"] = v
                marcas.append(f":p{j}_{k}")
            vals.append("(" + ",".join(marcas) + ")")
        c.run(f"INSERT INTO {TABELA} ({cols}) VALUES " + ",".join(vals) +
              f" ON CONFLICT (lf, chave, origem_id) DO UPDATE SET {atualiza}", **par)
    depois = c.run(f"SELECT count(*) FROM {TABELA}")[0][0]
    return len(linhas), depois - antes


def marca_dagua(c) -> datetime:
    """De quando retomar: a última captação que ESTE script gravou, menos a folga.

    Sai do DESTINO e não de estado nosso, pelo mesmo motivo da entrega do Supabase: se
    alguém apagar as linhas, a marca desaparece junto e a rodada seguinte percebe, em vez
    de continuar de um ponteiro que não vale mais.
    """
    r = c.run(f"SELECT max(captured_at) FROM {TABELA} WHERE planilha = :p",
              p=PROCEDENCIA)
    return r[0][0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--desde", help="data (AAAA-MM-DD) para backfill explícito")
    ap.add_argument("--folga-horas", type=int, default=FOLGA_HORAS,
                    help=f"quanto reprocessar para trás (default {FOLGA_HORAS}h)")
    ap.add_argument("--check", action="store_true", help="conta e não escreve")
    a = ap.parse_args()

    inicio = time.monotonic()
    c = open_analytics_connection(timeout=1800)
    try:
        if a.desde:
            desde = datetime.fromisoformat(a.desde).replace(tzinfo=timezone.utc)
            print(f"backfill explícito desde {a.desde}")
        else:
            marca = marca_dagua(c)
            if marca is None:
                print("nenhuma linha vinda do Railway ainda: rode com --desde para a "
                      "primeira carga (ex.: --desde 2026-08-04)", file=sys.stderr)
                return 1
            desde = marca - timedelta(hours=a.folga_horas)
            print(f"incremental desde {desde.isoformat()} "
                  f"(última captação {marca.isoformat()}, folga {a.folga_horas}h)")

        cal = _calendario(c)
        print(f"  calendário: {len(cal)} janelas de captação")

        rw = railway()
        try:
            linhas = rw.run(_sql_railway(), desde=desde.replace(tzinfo=None))
        finally:
            rw.close()
        print(f"  Railway devolveu {len(linhas):,} registros")

        agora = datetime.now(timezone.utc)
        montadas = _monta(linhas, cal, agora)
        print(f"  {len(montadas):,} linhas montadas")
        # O dedupe interno do lote sai no log de propósito. Ele existe por causa de
        # variante de CAIXA no e-mail do `Client` (a PK de lá preserva o caso), e se esse
        # número começar a crescer é sinal de que a origem está duplicando pessoa — coisa
        # que a gente quer VER, não absorver em silêncio.
        colapsadas = len(linhas) - len(montadas)
        if colapsadas:
            print(f"  {colapsadas:,} colapsadas por chave repetida dentro do lote "
                  f"(variante de caixa no e-mail, ou registro sem data)")
        sem_lf = sum(1 for x in montadas if x[0] == SEM_LF)
        if sem_lf:
            print(f"  {sem_lf:,} fora de qualquer janela de captação -> lf={SEM_LF}")
        com_utm = sum(1 for x in montadas if x[2].startswith("utm:"))
        print(f"  {com_utm:,} de evento da UTMTracking, "
              f"{len(montadas) - com_utm:,} só do cadastro")

        if a.check:
            print("\n--check: nada gravado.")
            return 0

        c.run("BEGIN")
        try:
            n, delta = _grava(c, montadas)
            c.run("COMMIT")
        except Exception:
            c.run("ROLLBACK")
            raise
        print(f"\n  {n:,} linhas gravadas · {delta:+,} de saldo na tabela")

        # O aviso. Ver `TIMEOUT_JOB_S`: sem ele, estourar o limite é falha silenciosa.
        gasto = time.monotonic() - inicio
        fracao = gasto / TIMEOUT_JOB_S
        print(f"  rodada levou {gasto:.1f}s de um limite de {TIMEOUT_JOB_S}s "
              f"({fracao*100:.0f}% do orçamento)")
        if fracao > AVISA_ACIMA_DE:
            print(f"AVISO: esta rodada usou {fracao*100:.0f}% do tempo do job para "
                  f"{len(montadas):,} linhas. Perto do limite, a rodada é MORTA no meio, a "
                  f"transação é desfeita e a marca não avança — a seguinte tentaria o mesmo "
                  f"volume e falharia igual. Se isto repetir, é hora de fatiar em lotes com "
                  f"avanço parcial da marca.", file=sys.stderr)
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
