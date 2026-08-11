"""Preenche `analytics.captacoes.utm_url` no HISTÓRICO, a partir das fontes que temos.

POR QUE ESTE SCRIPT EXISTE, E POR QUE ELE NÃO É UM ENRIQUECIMENTO NA ENTREGA
===========================================================================
A entrega para a agência lê UMA fonte, a `captacoes`, e não completa nada na hora de
entregar. A regra é do cliente: se o dado falta no lead, ele falta na tabela da agência.
Remendo na entrega faz a tabela parecer melhor do que o dado é e esconde o que precisa ser
consertado na origem.

Mas as 503.438 linhas históricas da `captacoes` vieram das planilhas do Drive, e as
planilhas nunca trouxeram a URL de captura: `utm_url` está em 0,0% nelas. Isso não é
"dado que falta no lead", é dado que existe no nosso banco e nunca foi copiado para cá.

A distinção é a que importa: completar a COLUNA, uma vez, dentro da `captacoes`, deixa o
dado num lugar só, igual para todo consumidor e auditável. Remendar na leitura faria cada
consumidor ter a sua própria versão da verdade.

AS TRÊS FONTES, NESTA ORDEM DE PRIORIDADE
=========================================
1. `public.registros_ml` — o ledger vivo, `utm_url` em 100% (medido: 34.172 linhas em 30
   dias). Só respondente, e só a partir de 23/05/2026.
2. `public.lead_legado` — a tabela `Lead` antiga, morta em ~17/05/2026, com `page_url`
   cheio de FEV a MAI/2026.
3. `analytics.url_captura_legado` — a repescagem do backup de 25/02/2026, montada por
   `scripts/recupera_url_legado.py`. É ela que conserta JANEIRO.

Janeiro parecia perdido e não estava: a URL daquele mês morava em
`leads_capi.event_source_url`, a tabela morreu e hoje a coluna está VAZIA, então quem
consulta a tabela viva conclui que ela nunca teve o dado. No dump de fevereiro ela está
cheia — o dado não se perdeu, deixou de ser copiado adiante quando o schema mudou.

QUANTO ISSO RECUPERA (medido em 11/08/2026, antes de rodar)
==========================================================
    jan/2026 ... 42.765 linhas ... 98,9% casariam
    fev/2026 ... 45.446 ......... 96,3%
    mar/2026 ... 63.732 ......... 86,5%
    abr/2026 ... 49.101 ......... 86,9%
    mai/2026 ... 29.917 ......... 81,2%
    jun/2026 ... 39.148 ......... 82,4%
    jul/2026 ... 46.111 ......... 87,5%

Ou seja, a coluna sai de 0% para entre 81% e 99%. NÃO chega a 100% e não deve: a fonte de
maior cobertura é o ledger, que é só respondente. O que não casar fica nulo, e nulo aqui
quer dizer "não temos", que é a informação correta.

O QUE ELE NÃO TOCA
==================
Só escreve onde `utm_url` está NULO, e só nas linhas vindas das planilhas. Linha que a
ingestão do Railway trouxe já tem a URL da própria origem, e sobrescrever isso seria
trocar dado de primeira mão por dado inferido de outra tabela.

`utm_medium` e `utm_term` NÃO entram aqui. A fonte deles é a `UTMTracking`, que tem 143 mil
linhas contra 503 mil da `captacoes`, então a recuperação seria parcial de um jeito
diferente (por período, não por público) e merece a sua própria medição antes.

Uso:
  python scripts/completa_url_captacoes.py --check   # mede e não escreve
  python scripts/completa_url_captacoes.py           # preenche em lotes
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv                                          # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from src.data.analytics_connection import open_analytics_connection     # noqa: E402

LOTE = 10_000

# A CTE das três fontes, com prioridade por coluna em vez de COALESCE de subconsultas:
# assim a regra fica num lugar só e fonte nova entra sem reescrever nada.
FONTES = """
  url_por_email AS (
    SELECT DISTINCT ON (email) email, url
      FROM (
        SELECT lower(email) AS email, utm_url AS url, 1 AS prio
          FROM public.registros_ml
         WHERE coalesce(utm_url,'') <> '' AND coalesce(email,'') <> ''
        UNION ALL
        SELECT lower(email), page_url, 2
          FROM public.lead_legado
         WHERE coalesce(page_url,'') <> '' AND coalesce(email,'') <> ''
        UNION ALL
        SELECT email, utm_url, 3
          FROM analytics.url_captura_legado
      ) f
     ORDER BY email, prio
  )
"""


def medir(c) -> None:
    print("### por mês: linhas SEM url e quantas casariam")
    for r in c.run(f"""
        WITH {FONTES}
        SELECT to_char(cap.captured_at, 'YYYY-MM') m, count(*) n,
               count(u.url) casaria
          FROM analytics.captacoes cap
          LEFT JOIN url_por_email u ON u.email = lower(cap.email)
         WHERE cap.utm_url IS NULL AND cap.captured_at >= '2026-01-01'
         GROUP BY 1 ORDER BY 1"""):
        pct = 100.0 * r[2] / max(r[1], 1)
        print(f"    {r[0]}  sem url={r[1]:>7,}  casaria={r[2]:>7,} ({pct:.1f}%)")


MAPA = "analytics._mapa_url_tmp"


def preencher(c) -> None:
    """Materializa o mapa UMA vez, depois preenche em lotes contra ele.

    POR QUE MATERIALIZAR, E NÃO SÓ FATIAR
    =====================================
    A primeira versão montava a CTE das três fontes DENTRO de cada lote. O custo caro
    (varrer `registros_ml`, `lead_legado` e `url_captura_legado`) era pago de novo a cada
    volta, e não encolhia conforme os lotes avançavam. Resultado, medido em 11/08/2026: o
    primeiro lote de 20.000 passou e o segundo estourou o socket.

    É a mesma armadilha que o teto por rodada resolve num job: fatiar só ajuda se cada
    fatia for MAIS BARATA que a anterior, ou pelo menos barata em termos absolutos. Fatiar
    um trabalho cujo custo fixo já não cabe no tempo disponível não conserta nada — só
    divide o mesmo estouro em mais tentativas.

    Aqui o custo fixo é pago UMA vez, numa tabela com índice, e cada lote passa a ser uma
    junção por e-mail: barata e constante.
    """
    c.run("SET lock_timeout = '30s'")
    print(f"montando o mapa de URLs em {MAPA} (uma vez)...", flush=True)
    c.run(f"DROP TABLE IF EXISTS {MAPA}")
    c.run(f"""CREATE TABLE {MAPA} AS
              WITH {FONTES} SELECT email, url FROM url_por_email""")
    c.run(f"CREATE UNIQUE INDEX ON {MAPA} (email)")
    n_mapa = c.run(f"SELECT count(*) FROM {MAPA}")[0][0]
    print(f"  {n_mapa:,} e-mails com URL conhecida", flush=True)

    falta = c.run("SELECT count(*) FROM analytics.captacoes WHERE utm_url IS NULL")[0][0]
    print(f"\n{falta:,} linhas sem url. Lotes de {LOTE:,}.", flush=True)
    total = 0
    while True:
        # `run()` devolve as LINHAS de um SELECT; num UPDATE devolve None. Ler o retorno
        # como contagem fazia o laço achar que nada mudou e parar na primeira volta — e o
        # script terminava imprimindo "OK: 0 URLs preenchidas", que é falha se anunciando
        # como sucesso. A contagem de verdade está em `row_count`.
        #
        # E o UPDATE carimba `ingested_at` junto. Sem isso, a mudança fica INVISÍVEL para a
        # entrega: ela descobre o que mudou olhando essa coluna, então uma linha com a URL
        # nova e a marca velha "não mudou" na visão dela. A URL certa ficaria no nosso banco
        # convivendo com a antiga no do cliente, indefinidamente, até alguém rodar uma carga
        # cheia na mão.
        #
        # REGRA GERAL para qualquer script futuro: quem altera um valor ENTREGUE carimba a
        # coluna que a entrega usa como marca. É irmão de dois erros que este projeto já
        # teve — a auditoria que detectava e morria no log, e o índice que existia e não
        # valia: peça certa, sem o elo que a torna visível.
        c.run(f"""
            WITH alvo AS (
              SELECT cap.ctid, m.url
                FROM analytics.captacoes cap
                JOIN {MAPA} m ON m.email = lower(cap.email)
               WHERE cap.utm_url IS NULL
               LIMIT {LOTE}
            )
            UPDATE analytics.captacoes c
               SET utm_url = alvo.url,
                   ingested_at = now()
              FROM alvo WHERE c.ctid = alvo.ctid""")
        feitas = int(c.row_count or 0)
        total += feitas
        print(f"    +{feitas:,} (total {total:,})", flush=True)
        if feitas == 0:
            break
    # A tabela auxiliar sai no fim. Deixá-la viraria uma tabela órfã no schema que o
    # catálogo listaria como SEM DESCRIÇÃO e alguém acharia que é dado.
    c.run(f"DROP TABLE IF EXISTS {MAPA}")
    print(f"\nOK: {total:,} URLs preenchidas. Tabela auxiliar removida.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="mede e não escreve")
    a = ap.parse_args()
    c = open_analytics_connection(timeout=3600)
    try:
        medir(c)
        if a.check:
            print("\n--check: nada gravado.")
            return 0
        print()
        preencher(c)
        print()
        r = c.run("""SELECT count(*), count(utm_url),
                     round(100.0*count(utm_url)/count(*),1)
                     FROM analytics.captacoes""")
        print(f"### depois: {r[0][1]:,} de {r[0][0]:,} linhas com url ({r[0][2]}%)")
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
