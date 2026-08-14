"""Preenche `analytics.captacoes.utm_medium` e `utm_term` no HISTÓRICO, da `UTMTracking`.

POR QUE ESTE SCRIPT EXISTE
==========================
Irmão do `completa_url_captacoes.py`, e pela mesma razão: as 503.438 linhas históricas da
`captacoes` vieram das planilhas do Drive, e as planilhas nunca trouxeram `medium` nem
`term`. Medido em 12/08/2026, antes de rodar: `utm_medium` preenchido em 1.866 de 505.826
linhas (0,4%), e todas as 1.866 são da ingestão nova do Railway.

Na tabela da agência isso aparece como `medium` e `term` em 1,8%, contra `source` em 98,6%.
Não é dado que falta no lead: é dado que existe no nosso banco e nunca foi copiado para cá.

A REGRA DE CASAMENTO É (EMAIL, DIA), E ISSO FOI MEDIDO
=====================================================
A `UTMTracking` é o evento de clique; a `captacoes` é a inscrição. Casar só por e-mail
estaria errado: 5.904 pessoas têm evento de UTM em 2+ dias distintos, e uma pessoa que se
inscreveu no LF55 e no LF63 tem duas linhas na `captacoes` que não devem herdar a mesma UTM.

Casar por (email, dia) resolve isso, e a medição diz que o dia é a chave certa. Distância em
dias entre o cadastro no `Client` e o evento de UTM mais próximo, 90 dias, 100.489 pessoas:

    mesmo dia ......... 100.353   (99,86%)
    um dia .................... 1
    dois a sete dias ......... 64
    oito a trinta dias ....... 61
    mais de trinta ........... 10

É o mesmo grão que a entrega usa (`DISTINCT ON (email, data)`), então o backfill e a entrega
concordam por construção em vez de por coincidência.

Divergência dentro do mesmo dia é irrelevante mas precisa de regra determinística: em
142.549 pares (email, dia), só 24 têm mais de um `medium`. A regra é ÚLTIMO EVENTO DO DIA
(`trackedAt DESC`), que é atribuição de último toque: o clique que precede a inscrição é o
que leva o crédito.

A ARMADILHA DE FUSO QUE ESTE SCRIPT TEVE QUE RESOLVER PRIMEIRO
==============================================================
`captured_at` é `timestamptz`, mas nas linhas de planilha ele NÃO é um instante: 494.195 das
503.438 (98,2%) estão em 00:00 UTC exato. É uma DATA guardada como meia-noite, e a data que
a planilha trazia já era a data local brasileira.

Consequência: ler essas linhas com `AT TIME ZONE 'America/Sao_Paulo'` devolve 21h do dia
ANTERIOR, ou seja desloca o dia em −1. Medido por pertinência (o dia lido existe entre as
datas de cadastro da pessoa no `Client`, amostra de 2.998):

    lido como UTC ....... 2.716 de 2.998   (90,6%)
    lido em Brasília .......... 0 de 2.998   (0,0%)

Por isso a junção aqui usa `(captured_at AT TIME ZONE 'UTC')::date` para as linhas de
planilha. Não é preferência de fuso: é que naquelas linhas o valor guardado JÁ É a data
local, e convertê-la é corrompê-la. Nas linhas do Railway, `captured_at` é instante de
verdade e a leitura correta é em Brasília — é por isso que a regra é por PROCEDÊNCIA e não
uma expressão só para a tabela toda.

POR QUE SÓ AS LINHAS DE PLANILHA
================================
Linha que a ingestão do Railway trouxe já aponta para o SEU evento de UTM
(`origem_id = 'utm:<id>'`), então o `medium` dela é de primeira mão. As 21,9% de linhas
`railway` sem `medium` são de 05 a 10/08/2026, quando o front parou de gravar `UTMTracking`
e o evento simplesmente não existe: 326 cadastros sem nenhuma linha de UTM. Preencher essas
com o evento de outra hora do dia trocaria "não temos" por um palpite. Ficam nulas, que é a
informação correta.

QUANTO ISSO RECUPERA
====================
Alcance esperado: cobertura de cadastro pela `UTMTracking` (98,8% em 90 dias) vezes o
preenchimento de `medium` dentro dela (98,6%), ou seja ~97,4%. Na tabela da agência, `medium`
e `term` saem de 1,8% para perto de 97%.

O QUE FAZER DEPOIS DE RODAR, E NÃO É OPCIONAL
=============================================
Rodar este script NÃO faz o dado chegar na agência. Falta uma
`push_supabase_zanelato.py --full`, que apaga e reinsere os 90 dias inteiros (~28 min).

POR QUE ESTE SCRIPT NÃO CARIMBA `ingested_at`, AO CONTRÁRIO DO IRMÃO DELE
========================================================================
A entrega descobre o que mudou olhando `ingested_at`, e a regra que o
`completa_url_captacoes.py` escreveu é "quem altera um valor ENTREGUE carimba a coluna que a
entrega usa como marca". A regra está certa, e a fronteira dela é o TAMANHO da mudança.

O incremental de 10 minutos escreve apagando-e-inserindo por chave, a ~62 linhas/s, dentro de
um job com teto de 600 s. Carimbar ~99 mil linhas de uma vez faria a rodada seguinte tentar
99 mil: ela levaria ~27 minutos, seria morta no meio, faria rollback, e a rodada depois
tentaria exatamente a mesma coisa. Um carimbo que existe para tornar a mudança visível teria
o efeito oposto — travaria o canal por onde as linhas novas chegam.

A regra completa, então, é: mudança PEQUENA carimba e viaja no incremental; mudança em LOTE
não carimba e viaja numa `--full`. A `--full` não olha `ingested_at`, ela relê os 90 dias, e
por isso entrega o backfill inteiro numa transação só. E como ela reescreve `recebido_em` de
todas as linhas, a marca do incremental salta junto e a rodada seguinte volta a ser pequena.

Efeito prático: este script pode rodar com o cron LIGADO. Ele não gera trabalho para o
incremental, então as linhas novas continuam chegando na agência enquanto ele roda.

Uso:
  python scripts/completa_utm_captacoes.py --check   # mede o alcance e não escreve
  python scripts/completa_utm_captacoes.py           # preenche em lotes
"""
from __future__ import annotations

import argparse
import os
import ssl
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv                                          # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import pg8000.native                                                    # noqa: E402

from src.data.analytics_connection import open_analytics_connection     # noqa: E402

MAPA = "analytics._mapa_utm_tmp"
LOTE_CARGA = 2_000       # linhas por INSERT no mapa (2.000 x 4 colunas = 8.000 parâmetros)
LOTE_UPDATE = 10_000     # linhas por UPDATE na captacoes

# `trackedAt` e `createdAt` no Railway são `timestamp without time zone` guardando UTC, então
# precisam do AT TIME ZONE DUPLO: o primeiro diz "isto é UTC", o segundo converte. Um só
# erraria em 3 horas, na direção oposta, e silenciosamente.
BRT_RAILWAY = "AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo'"

# Na `captacoes`, ao contrário, o dia das linhas de PLANILHA é o valor lido como UTC — ver a
# seção de fuso no topo. Expressão diferente para tabela diferente, de propósito.
DIA_PLANILHA = "(c.captured_at AT TIME ZONE 'UTC')::date"

# Só as linhas de planilha. As do Railway têm o medium do próprio evento delas.
SO_PLANILHA = "c.origem_id LIKE 'planilha:%'"


def _railway():
    """Conexão de leitura no Railway. Só SELECT: este script nunca escreve lá."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
        database=os.environ.get("RAILWAY_DB_NAME", "railway"),
        user=os.environ.get("RAILWAY_DB_USER", "postgres"),
        password=os.environ["RAILWAY_DB_PASSWORD"],
        ssl_context=ctx,
        timeout=900,
    )
    conn.run("SET statement_timeout = '840s'")
    return conn


def _puxa_mapa() -> list:
    """Um registro por (email, dia) com o ÚLTIMO evento de UTM daquele dia.

    A escolha do último toque acontece aqui, no `DISTINCT ON` com `trackedAt DESC`, e não do
    lado do UPDATE: assim o mapa já chega com uma linha por chave e a junção do lote fica
    barata e sem ambiguidade.
    """
    rw = _railway()
    try:
        return rw.run(f"""
            SELECT DISTINCT ON (lower("clientEmail"), ("trackedAt" {BRT_RAILWAY})::date)
                   lower("clientEmail")                        AS email,
                   ("trackedAt" {BRT_RAILWAY})::date            AS dia,
                   nullif(medium, '')                           AS medium,
                   nullif(term, '')                             AS term
              FROM "UTMTracking"
             WHERE nullif("clientEmail", '') IS NOT NULL
               AND (nullif(medium, '') IS NOT NULL OR nullif(term, '') IS NOT NULL)
             ORDER BY lower("clientEmail"),
                      ("trackedAt" {BRT_RAILWAY})::date,
                      "trackedAt" DESC, id DESC""")
    finally:
        rw.close()


def _carrega_mapa(c, linhas: list) -> int:
    """Materializa o mapa numa tabela do nosso banco, com índice.

    Materializar em vez de mandar o mapa dentro de cada lote é a lição do backfill de URL: o
    custo fixo tem que ser pago UMA vez. Aqui é mais forte ainda, porque a origem é OUTRO
    banco — não existe junção possível entre Railway e Cloud SQL sem trazer o dado para cá.
    """
    c.run("SET lock_timeout = '30s'")
    c.run(f"DROP TABLE IF EXISTS {MAPA}")
    c.run(f"CREATE TABLE {MAPA} (email text, dia date, medium text, term text)")
    for i in range(0, len(linhas), LOTE_CARGA):
        pedaco = linhas[i:i + LOTE_CARGA]
        vals, par = [], {}
        for j, linha in enumerate(pedaco):
            marcas = []
            for k, v in enumerate(linha):
                par[f"p{j}_{k}"] = v
                marcas.append(f":p{j}_{k}")
            vals.append("(" + ",".join(marcas) + ")")
        c.run(f"INSERT INTO {MAPA} (email, dia, medium, term) VALUES " + ",".join(vals),
              **par)
        print(f"    mapa: {min(i + LOTE_CARGA, len(linhas)):,} de {len(linhas):,}",
              flush=True)
    c.run(f"CREATE UNIQUE INDEX ON {MAPA} (email, dia)")
    return c.run(f"SELECT count(*) FROM {MAPA}")[0][0]


# A condição de alvo aparece nos dois lugares (medir e preencher) e é a MESMA de propósito:
# medir uma população e escrever em outra é como se descobre, depois, que o relatório e o
# efeito nunca falaram da mesma coisa.
#
# E ela tem um segundo papel, que é fazer o laço TERMINAR. A condição ingênua
# ("medium é nulo OU term é nulo") não converge: uma linha cujo mapa tem `medium` mas não
# `term` continua satisfazendo "term é nulo" depois do UPDATE, seria escolhida de novo, e o
# laço rodaria para sempre gravando zero. Exigir que o mapa TENHA o valor que falta faz cada
# volta reduzir de verdade o conjunto restante.
ALVO = f"""
    FROM analytics.captacoes c
    JOIN {MAPA} m ON m.email = lower(c.email) AND m.dia = {DIA_PLANILHA}
   WHERE {SO_PLANILHA}
     AND ( (nullif(c.utm_medium, '') IS NULL AND m.medium IS NOT NULL)
        OR (nullif(c.utm_term,   '') IS NULL AND m.term   IS NOT NULL) )
"""


def medir(c) -> None:
    print("### alcance por mês: linhas de planilha sem medium, e quantas o mapa alcança")
    for r in c.run(f"""
        SELECT to_char(c.captured_at AT TIME ZONE 'UTC', 'YYYY-MM') mes,
               count(*) n,
               count(*) FILTER (WHERE m.email IS NOT NULL
                                  AND (m.medium IS NOT NULL OR m.term IS NOT NULL)) alcanca
          FROM analytics.captacoes c
          LEFT JOIN {MAPA} m ON m.email = lower(c.email) AND m.dia = {DIA_PLANILHA}
         WHERE {SO_PLANILHA} AND nullif(c.utm_medium, '') IS NULL
         GROUP BY 1 ORDER BY 1"""):
        pct = 100.0 * r[2] / max(r[1], 1)
        print(f"    {r[0]}  sem medium={r[1]:>7,}  alcança={r[2]:>7,} ({pct:5.1f}%)")

    # A janela de 90 dias é a única que a agência vê. Reportada à parte porque é o número
    # que responde "o que muda para o cliente", diferente de "o que muda na nossa tabela".
    r = c.run(f"""
        SELECT count(*), count(*) FILTER (WHERE m.email IS NOT NULL
                                           AND (m.medium IS NOT NULL OR m.term IS NOT NULL))
          FROM analytics.captacoes c
          LEFT JOIN {MAPA} m ON m.email = lower(c.email) AND m.dia = {DIA_PLANILHA}
         WHERE {SO_PLANILHA} AND nullif(c.utm_medium, '') IS NULL
           AND c.captured_at >= (now() - interval '90 days')""")[0]
    pct = 100.0 * r[1] / max(r[0], 1)
    print(f"\n    JANELA DE ENTREGA (90d): {r[0]:,} sem medium, "
          f"{r[1]:,} alcançáveis ({pct:.1f}%)")


def preencher(c) -> None:
    falta = c.run(f"SELECT count(*) {ALVO}")[0][0]
    print(f"\n{falta:,} linhas a preencher. Lotes de {LOTE_UPDATE:,}.", flush=True)
    total = 0
    while True:
        # `coalesce(nullif(...))` e não atribuição direta: preencher NUNCA sobrescreve valor
        # que já existe. É o que garante que rodar de novo é inofensivo, e o que impede
        # trocar dado de primeira mão por dado inferido caso o filtro de procedência mude.
        #
        # SEM `ingested_at = now()`, de propósito e ao contrário do backfill de URL. Carimbar
        # 99 mil linhas faria a rodada seguinte do incremental tentar escrever 99 mil e ser
        # morta pelo teto do job, em laço. Ver a seção sobre isso no topo do arquivo: quem
        # entrega este backfill é a `--full`, não o incremental.
        c.run(f"""
            WITH alvo AS (
              SELECT c.ctid AS id, m.medium AS medium, m.term AS term
              {ALVO}
               LIMIT {LOTE_UPDATE}
            )
            UPDATE analytics.captacoes c
               SET utm_medium = coalesce(nullif(c.utm_medium, ''), alvo.medium),
                   utm_term   = coalesce(nullif(c.utm_term,   ''), alvo.term)
              FROM alvo WHERE c.ctid = alvo.id""")
        # `run()` devolve as LINHAS de um SELECT e None num UPDATE. Ler o retorno como
        # contagem faria o laço parar na primeira volta e o script terminar dizendo
        # "OK: 0 preenchidas", que é falha se anunciando como sucesso.
        feitas = int(c.row_count or 0)
        total += feitas
        print(f"    +{feitas:,} (total {total:,})", flush=True)
        if feitas == 0:
            break
    print(f"\nOK: {total:,} linhas com medium/term preenchidos.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="mede o alcance e não escreve")
    a = ap.parse_args()

    c = open_analytics_connection(timeout=3600)
    try:
        print("puxando o mapa da UTMTracking (um registro por email+dia)...", flush=True)
        linhas = _puxa_mapa()
        print(f"  {len(linhas):,} pares (email, dia) com medium ou term", flush=True)
        n_mapa = _carrega_mapa(c, linhas)
        print(f"  mapa materializado em {MAPA}: {n_mapa:,} linhas\n", flush=True)

        medir(c)
        if a.check:
            # A tabela auxiliar sai mesmo no --check: tabela órfã no schema é o tipo de
            # coisa que o catálogo lista como SEM DESCRIÇÃO e alguém confunde com dado.
            c.run(f"DROP TABLE IF EXISTS {MAPA}")
            print("\n--check: nada gravado. Tabela auxiliar removida.")
            return 0

        preencher(c)
        c.run(f"DROP TABLE IF EXISTS {MAPA}")

        r = c.run("""SELECT count(*), count(nullif(utm_medium,'')),
                            count(nullif(utm_term,''))
                       FROM analytics.captacoes
                      WHERE captured_at >= (now() - interval '90 days')""")[0]
        print(f"\n### depois, na janela de entrega: {r[0]:,} linhas · "
              f"medium {100.0 * r[1] / max(r[0], 1):.1f}% · "
              f"term {100.0 * r[2] / max(r[0], 1):.1f}%")
        print("\nPRÓXIMO PASSO OBRIGATÓRIO: pausar o cron do incremental, rodar "
              "`push_supabase_zanelato.py --full`, retomar o cron. Ver o topo deste arquivo.")
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
