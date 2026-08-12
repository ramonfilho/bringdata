"""Empurra a nota por CRIATIVO e por CAMPANHA para `public.scores_inbound` no Supabase deles.

ESTADO EM 12/08/2026: ESCRITO, NÃO LIGADO. Nenhum cron chama este script, então ele é
inerte em produção. Falta:

  1. Decidir o PISO de N. A conta: a diferença real entre criativos é ~11pp (desvio-padrão
     de 13,3pp medido em 21 criativos com N>=200, descontado o ruído de amostra desses
     mesmos 200). Dois erros-padrão dão 18,2pp em N=30, 14,1pp em N=50 e 10,0pp em N=100.
     Abaixo de 100, o ruído é maior que a diferença entre criativos e a coluna de delta
     vira decorativa. Recomendação: 100 (o default da função).
  2. `LEDGER_DECIL_READ_SOURCE=ledger` no ambiente onde ele rodar. Sem isso a função cai no
     ramo legado que lê a `scores_historicos`, aposentada em 08/07/2026 — e devolve VAZIO
     para qualquer lançamento depois do LF61. A produção já tem a variável; um ambiente
     local sem ela reproduz um falso "não tem dado".
  3. Criar o cron. A `scores_inbound` não tem alimentação nenhuma hoje.

O QUE ESTE SCRIPT É, E O QUE ELE NÃO É
======================================
Ele é um TRADUTOR, não um cálculo. A nota vem de
`src.monitoring.utm_quality.build_top5_comparison`, a mesma função que monta o relatório de
criativo que já vai para o Slack todos os dias.

Isso não é economia de código, é a garantia que importa: **a agência vê o mesmo número que
você vê no relatório.** Se este script recalculasse a nota por conta própria, as duas contas
divergiriam na primeira mudança de régua, e ninguém saberia qual está certa — o histórico
deste projeto tem exatamente esse erro, com escritor e leitor divergindo por 9 dias porque
cada um tinha a sua cópia do nome de uma fonte.

AS 7 COLUNAS QUE ELES CRIARAM, E DE ONDE CADA UMA SAI
=====================================================
    tipo                 'criativo' ou 'campanha'  (o `level` da função)
    chave                nome do anúncio / da campanha
    leads                N de leads que entraram na conta
    pct_top20            % dos leads do criativo que caíram no topo (D9-D10)
    referencia_pct       a barra TOP5 ROAS — a régua de comparação
    delta_vs_referencia  pct_top20 − referencia_pct, em pontos percentuais
    atualizado_em        default `now()` no lado deles; não mandamos

O QUE NÃO VAI, E É REGRA INEGOCIÁVEL
====================================
Score e decil POR LEAD são proibidos nesta entrega. O que sai daqui é AGREGADO por criativo
e por campanha, com piso de N — que é justamente o que a função já aplica (`min_n`). Sem o
piso, um criativo com 1 lead publicaria o decil daquele lead com outro nome.

MÍNIMO DE LEADS
===============
O piso vem do `min_n` da função e não é enfeite estatístico: abaixo dele o "agregado" vira o
score individual disfarçado. A função já separa em `rows` (mostrados) e `hidden_below_min_n`,
e este script manda só os primeiros — e REPORTA quantos ficaram de fora, porque corte
silencioso lido como "só existem estes criativos" é pior que corte nenhum.

Uso:
  python scripts/push_scores_zanelato.py --check   # calcula e mostra, não escreve
  python scripts/push_scores_zanelato.py           # calcula e escreve
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv                                          # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from scripts.push_supabase_zanelato import destino                      # noqa: E402

TABELA_DESTINO = "public.scores_inbound"
CLIENTE = "devclub"

# `atualizado_em` fica de fora: tem default `now()` no lado deles, e é o carimbo de quando
# ELES receberam. Mandar valor sobrescreveria a informação deles com a nossa.
COLUNAS = ["tipo", "chave", "leads", "pct_top20", "referencia_pct", "delta_vs_referencia"]

# Tradução do nível interno para a palavra que a agência lê na coluna `tipo`. Explícita, e
# não `level[:8]` ou coisa parecida: o valor vai para a tabela do cliente e é o que ele
# filtra, então mudança aqui é mudança de contrato.
TIPO = {"creative": "criativo", "campaign": "campanha"}


def _janela_do_lancamento(conn):
    """A janela do lançamento ATUAL, pelo calendário canônico.

    Sai do calendário e não de `now() - N dias` porque a nota é por lançamento: misturar
    dois lançamentos na mesma conta compara criativo que rodou em contextos diferentes.
    """
    r = conn.run("""
        SELECT lf_name, cap_start, cap_end FROM analytics.launch_calendar
         WHERE client_id = :cli
           AND (now() AT TIME ZONE 'America/Sao_Paulo')::date
               BETWEEN cap_start AND cap_end
         ORDER BY cap_start DESC LIMIT 1""", cli=CLIENTE)
    if r:
        return r[0][0], r[0][1], r[0][2]
    # Fora de janela de captação (acontece: 04 a 06/08/2026 caiu entre dois lançamentos).
    # Cai no último que terminou, em vez de devolver nada — nota velha é melhor que nota
    # nenhuma, desde que quem lê saiba qual lançamento é, e o `lf_name` diz.
    r = conn.run("""
        SELECT lf_name, cap_start, cap_end FROM analytics.launch_calendar
         WHERE client_id = :cli AND cap_end < (now() AT TIME ZONE 'America/Sao_Paulo')::date
         ORDER BY cap_end DESC LIMIT 1""", cli=CLIENTE)
    return (r[0][0], r[0][1], r[0][2]) if r else (None, None, None)


def _champion_run_id(conn) -> str | None:
    """A régua é o CHAMPION, o modelo que pega todo o tráfego.

    Mesma escolha do relatório de criativo (ver `_build_top5_for` em `api/app.py`): o
    baseline fixo foi gerado no champion, então comparar contra outro modelo compararia
    contra uma régua que não é a dele.
    """
    r = conn.run("""
        SELECT champion_run_id FROM public.registros_ml
         WHERE champion_run_id IS NOT NULL
         ORDER BY created_at DESC LIMIT 1""")
    return r[0][0] if r else None


def coletar(conn) -> tuple:
    """Devolve (linhas, resumo). Reusa a função do relatório: NÃO recalcula nada."""
    from src.monitoring.utm_quality import build_top5_comparison

    lf, ini, fim = _janela_do_lancamento(conn)
    if not lf:
        raise SystemExit("sem lançamento no calendário: nada a publicar")
    run_id = _champion_run_id(conn)
    if not run_id:
        raise SystemExit("sem champion_run_id no ledger: a régua não existe")

    # A janela do calendário vem em DATA de Brasília, e `registros_ml.created_at` guarda UTC.
    # Montar a fronteira como data pura fazia `07/08 00:00` virar 06/08 21:00 de Brasília, e
    # três horas da noite do dia ANTERIOR entravam na conta do lançamento.
    #
    # É o mesmo erro de fuso que jogou lead da noite para o dia seguinte na entrega da
    # agência: nada no código dizia UTC, o UTC vinha do ambiente. Somar 3h converte a
    # meia-noite de Brasília para o instante UTC correspondente; o fim ganha +1 dia porque a
    # janela do calendário é inclusiva no último dia e a comparação é exclusiva.
    #
    # Medido em 12/08/2026: com ou sem o conserto o resultado do LF64 é o mesmo (as 3 horas
    # não tinham lead suficiente para mover nada). Fica certo por construção, não por sorte.
    ini_utc = datetime.combine(ini, datetime.min.time()) + timedelta(hours=3)
    fim_utc = datetime.combine(fim, datetime.min.time()) + timedelta(hours=3, days=1)
    comp = build_top5_comparison(
        lf_name=lf,
        challenger_run_id=run_id,          # nome herdado: o valor é o CHAMPION
        win_start=ini_utc,
        win_end=fim_utc,
        client_id=CLIENTE,
        conn=conn,
    )
    if not comp:
        raise SystemExit(f"a comparação voltou vazia para {lf}: nada a publicar")

    barra = comp["bar_pct"]
    linhas, escondidas = [], 0
    for nivel, dados in comp["levels"].items():
        escondidas += dados.get("hidden_below_min_n", 0) or 0
        for r in dados["rows"]:
            linhas.append([
                TIPO[nivel],
                r.get("utm") or r.get("key") or "sem_utm",
                int(r.get("n") or 0),
                r.get("pct_d9_d10"),
                barra,
                r.get("delta_pp"),
            ])
    resumo = {"lf": lf, "barra": barra, "min_n": comp.get("min_n"),
              "escondidas": escondidas, "linhas": len(linhas)}
    return linhas, resumo


def gravar(linhas) -> int:
    """Upsert por `(tipo, chave)`, que é a chave única que eles criaram.

    `ON CONFLICT DO UPDATE` funciona aqui — ao contrário da `leads_inbound`, esta tabela TEM
    índice único, então o Postgres resolve sozinho e não preciso do apaga-e-insere.

    `atualizado_em = now()` no UPDATE de propósito: sem isso, uma linha que já existia
    manteria o carimbo antigo e a agência não teria como saber se a nota é de hoje ou de
    três dias atrás.
    """
    if not linhas:
        return 0
    dst = destino(porta=5432)
    try:
        cols = ",".join(COLUNAS)
        atualiza = ",".join(f"{k}=EXCLUDED.{k}" for k in COLUNAS
                            if k not in ("tipo", "chave"))
        vals, par = [], {}
        for j, linha in enumerate(linhas):
            marcas = []
            for k, v in enumerate(linha):
                par[f"p{j}_{k}"] = v
                marcas.append(f":p{j}_{k}")
            vals.append("(" + ",".join(marcas) + ")")
        dst.run("BEGIN")
        dst.run(f"INSERT INTO {TABELA_DESTINO} ({cols}) VALUES " + ",".join(vals) +
                f" ON CONFLICT (tipo, chave) DO UPDATE SET {atualiza}, "
                f"atualizado_em = now()", **par)
        dst.run("COMMIT")
        n = dst.run(f"SELECT count(*) FROM {TABELA_DESTINO}")[0][0]
        return n
    finally:
        dst.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="calcula e mostra, não escreve")
    a = ap.parse_args()

    from src.data.analytics_connection import open_analytics_connection
    conn = open_analytics_connection(timeout=1800)
    try:
        linhas, resumo = coletar(conn)
    finally:
        conn.close()

    print(f"lançamento {resumo['lf']} · barra de referência {resumo['barra']}% · "
          f"N mínimo {resumo['min_n']}")
    # O corte sai no log SEMPRE. Corte silencioso lido como "só existem estes criativos" é
    # pior que corte nenhum — é a mesma razão de a auditoria reportar a poda pendente à parte.
    if resumo["escondidas"]:
        print(f"  {resumo['escondidas']} abaixo do N mínimo, NÃO publicados "
              f"(agregado com pouco lead é score individual disfarçado)")
    print(f"  {resumo['linhas']} linhas para publicar")
    por_tipo = {}
    for x in linhas:
        por_tipo[x[0]] = por_tipo.get(x[0], 0) + 1
    for t, n in sorted(por_tipo.items()):
        print(f"    {t}: {n}")
    for x in sorted(linhas, key=lambda r: -(r[5] or -99))[:5]:
        print(f"    {x[0]:9s} {str(x[1])[:38]:40s} n={x[2]:>5} "
              f"top20={x[3]}% ref={x[4]}% delta={x[5]:+}pp")

    if a.check:
        print("\n--check: nada gravado.")
        return 0
    total = gravar(linhas)
    print(f"\nOK: {len(linhas)} publicadas · {total} linhas na tabela deles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
