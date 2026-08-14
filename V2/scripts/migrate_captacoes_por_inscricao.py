"""Prepara `analytics.captacoes` para virar a fonte ÚNICA da entrega da agência.

CONTEXTO
========
A entrega para o gestor de tráfego lia TRÊS tabelas (`analytics.leads`,
`analytics.cadastros` e o ledger `public.registros_ml`). A decisão de 11/08/2026 foi
outra: uma tabela só de leads alimenta a entrega, e é a `captacoes`. O caminho passa a ser

    Railway (Client LEFT JOIN UTMTracking)  ->  analytics.captacoes  ->  Supabase deles

O QUE ESTA MIGRAÇÃO FAZ, E POR QUE CADA PEDAÇO
==============================================
1. **3 colunas novas**: `utm_medium`, `utm_term`, `utm_url`. A entrega manda 11 colunas e a
   `captacoes` não tinha essas três — sem elas a agência PERDERIA campo que já recebe hoje.
   O dado vem da `UTMTracking` do Railway, que tem os três.

2. **`origem_id` + índice único novo**: é o que muda o GRÃO de "uma linha por pessoa por
   lançamento" para "uma linha por INSCRIÇÃO".

   A chave hoje é `(lf, chave)`, com `chave` = e-mail. Isso IMPEDE a mesma pessoa de
   aparecer duas vezes no mesmo lançamento, que é exatamente o que a agência precisa ver.

   `origem_id` é o discriminador, e ele é `NOT NULL` de propósito. Em Postgres, dois NULL
   NÃO conflitam num índice único: se o discriminador fosse nulável, cada rodada da
   ingestão inseriria as MESMAS linhas de novo, para sempre, sem erro nenhum. O valor é
   `'utm:<id>'` para a linha que vem de um evento da `UTMTracking`, `'client:<email>'` para
   quem não tem nenhum evento, e `'planilha:<nome>'` para as 503 mil linhas históricas.

3. **`SEM_LF` como sentinela**: `lf` é `NOT NULL` e faz parte da chave, então não pode
   ficar nulo. Existe cadastro FORA de qualquer janela de captação (medido: 04/08 a 06/08
   de 2026 cai entre o fim do DEV21 e o começo do LF64), e esse lead precisa entrar de
   qualquer forma — a agência paga por ele. Sentinela explícita é melhor que inventar um
   lançamento ou descartar o lead em silêncio.

O QUE ELA NÃO FAZ
=================
Não toca em nenhuma linha existente além de preencher `origem_id` a partir de `planilha`,
e não muda valor de nenhuma coluna. As 503.438 linhas continuam sendo únicas em
`(lf, chave)`, então o índice novo, mais frouxo, aceita todas sem conflito.

Uso:
  python scripts/migrate_captacoes_por_inscricao.py --check      # só mostra o estado
  python scripts/migrate_captacoes_por_inscricao.py              # aplica
  python scripts/migrate_captacoes_por_inscricao.py --rollback   # desfaz
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv                                          # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from src.data.analytics_connection import open_analytics_connection     # noqa: E402

TABELA = "analytics.captacoes"

# (coluna, tipo). As três primeiras são o que a entrega precisa e não existia.
COLS = [
    ("utm_medium", "text"),
    ("utm_term",   "text"),
    ("utm_url",    "text"),
    # Discriminador da inscrição. NOT NULL é aplicado num passo separado, depois do
    # backfill, porque a coluna nasce nula nas 503 mil linhas que já existem.
    ("origem_id",  "text"),
]

IDX_ANTIGO = "captacoes_pkey"                 # UNIQUE (lf, chave)
IDX_NOVO = "captacoes_inscricao_uk"           # UNIQUE (lf, chave, origem_id)

# Sentinela para quem se cadastrou fora de qualquer janela de captação.
SEM_LF = "SEM_LF"


def _colunas(c) -> dict:
    return {r[0]: r[1] for r in c.run(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='analytics' AND table_name='captacoes'")}


def _indices(c) -> dict:
    return {r[0]: r[1] for r in c.run(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE schemaname='analytics' AND tablename='captacoes'")}


def checar(c) -> None:
    cols, idx = _colunas(c), _indices(c)
    print(f"### {TABELA}")
    for nome, tipo in COLS:
        print(f"  {nome:14s} {'EXISTE (' + cols[nome] + ')' if nome in cols else 'falta'}")
    print("\n### índices")
    for nome, ddl in sorted(idx.items()):
        print(f"  {nome}: {ddl[ddl.index('('):]}")
    print(f"\n  chave por inscrição ({IDX_NOVO}): "
          f"{'EXISTE' if IDX_NOVO in idx else 'falta'}")
    n = c.run(f"SELECT count(*) FROM {TABELA}")[0][0]
    if "origem_id" in cols:
        preenchido = c.run(
            f"SELECT count(origem_id) FROM {TABELA}")[0][0]
        print(f"\n  {n:,} linhas · origem_id preenchido em {preenchido:,} "
              f"({100.0 * preenchido / max(n, 1):.1f}%)")
    else:
        print(f"\n  {n:,} linhas")


def _guarda_de_lock(c) -> None:
    """Não deixa o DDL entrar na fila de espera de um lock e travar leitura nova.

    Isto existe por causa de 30/07/2026: uma query órfã de 31,5 horas segurava lock na
    `registros_ml`, o `ALTER` entrou na fila, e um `ALTER` na fila BLOQUEIA toda leitura
    que chega depois dele. O banco parou por causa de uma migração de uma coluna.

    Com `lock_timeout`, o pior caso é a migração falhar rápido dizendo o porquê, em vez de
    derrubar quem está lendo.
    """
    c.run("SET lock_timeout = '15s'")
    presos = c.run("""
        SELECT pid, to_char(now() - query_start, 'HH24:MI:SS'),
               left(regexp_replace(query, '\\s+', ' ', 'g'), 70)
          FROM pg_stat_activity
         WHERE state <> 'idle' AND pid <> pg_backend_pid()
           AND query ILIKE '%captacoes%'""")
    if presos:
        print("  ATENÇÃO: há query ativa tocando a captacoes agora:")
        for p in presos:
            print(f"    pid={p[0]} há {p[1]}: {p[2]}")
        print("  O lock_timeout de 15s vai fazer esta migração falhar em vez de "
              "bloquear leitura. Se falhar, espere essas queries e rode de novo.")


LOTE_BACKFILL = 25_000


def aplicar(c) -> None:
    """Três fases, e a separação NÃO é estética.

    A primeira versão fazia tudo numa transação só, com o `UPDATE` de 503.438 linhas
    dentro. Resultado, em 11/08/2026: o socket estourou 15 minutos no meio do UPDATE, e
    nem o ROLLBACK conseguiu ser enviado. A tabela não sofreu nada (a transação era
    atômica e o servidor desfez ao ver a conexão morrer), mas a migração simplesmente não
    tinha como terminar.

    O problema não era o timeout, era o desenho: meio milhão de linhas reescritas dentro
    de uma transação de DDL segura lock por todo o tempo do UPDATE. As três fases abaixo
    fazem cada pedaço com o lock que ele merece e pelo tempo que ele merece.
    """
    _guarda_de_lock(c)

    # FASE 1 — metadados. `ADD COLUMN` de coluna nulável não reescreve linha nenhuma em
    # Postgres moderno: é instantâneo, mesmo em meio milhão de linhas.
    cols = _colunas(c)
    for nome, tipo in COLS:
        if nome in cols:
            print(f"  fase 1 · {nome}: já existe, pulando")
            continue
        c.run(f"ALTER TABLE {TABELA} ADD COLUMN IF NOT EXISTS {nome} {tipo}")
        print(f"  fase 1 · {nome}: criada ({tipo})")

    # FASE 2 — backfill EM LOTES, cada um com o seu commit. Fora de transação longa: se
    # cair no meio, o que já foi preenchido fica, e rodar de novo continua de onde parou
    # (o `WHERE origem_id IS NULL` é o próprio ponteiro). `planilha` é a procedência que a
    # tabela já registrava; quando é nula, o e-mail serve, porque as linhas antigas são
    # únicas em (lf, chave) e portanto não colidem entre si.
    falta = c.run(f"SELECT count(*) FROM {TABELA} WHERE origem_id IS NULL")[0][0]
    print(f"  fase 2 · {falta:,} linhas para preencher, em lotes de {LOTE_BACKFILL:,}")
    feitas = 0
    while True:
        n = c.run(f"""
            UPDATE {TABELA} SET origem_id = 'planilha:' || coalesce(planilha, chave)
             WHERE ctid IN (SELECT ctid FROM {TABELA}
                             WHERE origem_id IS NULL LIMIT {LOTE_BACKFILL})""")
        restam = c.run(f"SELECT count(*) FROM {TABELA} WHERE origem_id IS NULL")[0][0]
        feitas = falta - restam
        print(f"    {feitas:,}/{falta:,} ({100.0 * feitas / max(falta, 1):.0f}%)",
              flush=True)
        if restam == 0:
            break
        if feitas == 0:
            raise RuntimeError(
                "o lote não avançou nada — abortando para não girar em falso")

    # FASE 3 — o DDL que muda o grão. Curto de propósito.
    #
    # O índice único é criado CONCURRENTLY e FORA de transação: em 503 mil linhas, um
    # `CREATE UNIQUE INDEX` comum segura lock de escrita durante a construção inteira, e
    # esta tabela é lida pela nota do criativo e pelo sync de públicos da Meta.
    # "Existe" NÃO basta: um índice CONCURRENTLY que falhou no meio FICA na tabela, com
    # nome e tudo, mas marcado como inválido — e índice inválido NÃO garante unicidade.
    #
    # A primeira versão desta checagem só olhava validade no caminho em que CRIAVA o
    # índice. Como a fase 3 dropa a chave antiga logo depois, um índice inválido deixaria
    # a tabela SEM NENHUMA proteção de unicidade, e a migração ainda imprimiria "OK".
    # Foi exatamente o cenário que se armou em 11/08/2026, quando o build falhou por
    # lock timeout e a rodada seguinte disse "já existe" e seguiu.
    invalido = c.run("""
        SELECT c.relname FROM pg_class c
          JOIN pg_index i ON i.indexrelid = c.oid
          JOIN pg_class t ON t.oid = i.indrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'analytics' AND c.relname = :n
           AND (NOT i.indisvalid OR NOT i.indisready)""", n=IDX_NOVO)
    if invalido:
        print(f"  fase 3 · {IDX_NOVO} existe mas está INVÁLIDO (build anterior falhou): "
              f"dropando para recriar — índice inválido não garante unicidade")
        c.run(f"DROP INDEX IF EXISTS analytics.{IDX_NOVO}")

    idx = _indices(c)
    if IDX_NOVO in idx and not invalido:
        print(f"  fase 3 · {IDX_NOVO}: já existe e está válido")
    else:
        # `lock_timeout` SOLTO só aqui, e é o oposto de descuido. O guard de 15s existe
        # para o DDL EXCLUSIVO (`SET NOT NULL`, `DROP CONSTRAINT`), que bloqueia leitura
        # se entrar na fila. O `CONCURRENTLY` não bloqueia ninguém: ele ESPERA as
        # transações abertas terminarem. Com timeout curto, quem morre é a migração —
        # medido em 11/08/2026, ela falhou com `55P03 canceling statement due to lock
        # timeout` depois de o backfill inteiro já ter passado.
        c.run("SET lock_timeout = 0")
        try:
            c.run(f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {IDX_NOVO} "
                  f"ON {TABELA} (lf, chave, origem_id)")
        finally:
            c.run("SET lock_timeout = '15s'")
        print(f"  fase 3 · {IDX_NOVO}: criado UNIQUE (lf, chave, origem_id)")

    # Agora sim, transação curta: exigir valor e soltar a chave antiga. O índice novo já
    # está de pé, então a tabela nunca fica sem proteção de unicidade.
    c.run("BEGIN")
    try:
        c.run(f"ALTER TABLE {TABELA} ALTER COLUMN origem_id SET NOT NULL")
        print("  fase 3 · origem_id: NOT NULL aplicado")
        if IDX_ANTIGO in _indices(c):
            c.run(f"ALTER TABLE {TABELA} DROP CONSTRAINT {IDX_ANTIGO}")
            print(f"  fase 3 · {IDX_ANTIGO}: removida (era ela que proibia recadastro)")
        c.run("COMMIT")
    except Exception:
        c.run("ROLLBACK")
        raise
    print("\nOK: aplicado.")


def desfazer(c) -> None:
    _guarda_de_lock(c)
    c.run("BEGIN")
    try:
        idx = _indices(c)
        # Volta a chave antiga ANTES de soltar a nova, mesmo motivo da ida. Se sobrou
        # recadastro na tabela, este passo FALHA — e falhar é o certo: a alternativa
        # seria escolher sozinho qual linha do cliente apagar.
        if IDX_ANTIGO not in idx:
            c.run(f"ALTER TABLE {TABELA} ADD CONSTRAINT {IDX_ANTIGO} PRIMARY KEY (lf, chave)")
            print(f"  {IDX_ANTIGO}: recriada")
        if IDX_NOVO in idx:
            c.run(f"DROP INDEX IF EXISTS analytics.{IDX_NOVO}")
            print(f"  {IDX_NOVO}: removido")
        for nome, _ in COLS:
            c.run(f"ALTER TABLE {TABELA} DROP COLUMN IF EXISTS {nome}")
            print(f"  {nome}: removida")
        c.run("COMMIT")
        print("\nOK: desfeito.")
    except Exception:
        c.run("ROLLBACK")
        print("\nFALHOU. Se a queixa foi de chave duplicada, é porque JÁ existe recadastro "
              "gravado: a chave antiga não cabe mais nos dados. Decidir o que fazer com "
              "essas linhas é decisão de gente, não de script.", file=sys.stderr)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="só mostra o estado")
    ap.add_argument("--rollback", action="store_true", help="desfaz")
    a = ap.parse_args()
    # 3600s e não 900: o backfill é em lotes, mas o `SET NOT NULL` e o build do índice
    # varrem meio milhão de linhas cada um, e 900s foi exatamente o que estourou antes.
    c = open_analytics_connection(timeout=3600)
    try:
        if a.check:
            checar(c)
        elif a.rollback:
            desfazer(c)
        else:
            aplicar(c)
            print()
            checar(c)
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
