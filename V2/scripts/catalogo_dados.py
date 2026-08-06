#!/usr/bin/env python3
"""Gera o catálogo de dados lendo o PRÓPRIO banco, em vez de alguém escrever à mão.

Por que gerado e não escrito: um catálogo à mão nasce certo e apodrece em silêncio.
Foi assim que o treino passou meses lendo uma planilha morta, e assim que 20 das 25
tabelas do banco ficaram sem documentação nenhuma. O que a máquina consegue descobrir
sozinha (nome, tamanho, janela de datas, última atualização, colunas) ela descobre toda
vez que roda; o que ela não consegue (para que a tabela serve) fica no dicionário
`PARA_QUE_SERVE` abaixo, que é a única parte manual e quase não muda.

A coluna mais importante do relatório é **"última atualização"**: é ela que responde
"esta tabela ainda é alimentada ou parou?" sem ninguém precisar investigar.

Uso:
    python -m scripts.catalogo_dados                    # escreve V2/docs/CATALOGO_DADOS.md
    python -m scripts.catalogo_dados --stdout           # imprime, não escreve
    python -m scripts.catalogo_dados --sem-colunas      # só o resumo, sem listar colunas
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.data.analytics_connection import open_analytics_connection  # noqa: E402

SAIDA = Path(__file__).resolve().parents[1] / "docs" / "CATALOGO_DADOS.md"

# A ÚNICA parte manual. Uma linha por tabela dizendo para que ela serve — o resto o
# script descobre sozinho. Tabela que aparecer no banco e não estiver aqui sai no
# relatório marcada como SEM DESCRIÇÃO, que é o lembrete de vir escrever uma linha.
PARA_QUE_SERVE = {
    "public.registros_ml":
        "O ledger do ML. O consumer do Pub/Sub escreve uma linha por lead no momento em "
        "que o scoreia. É a fonte VIVA de decil, score, variante do A/B, respostas da "
        "pesquisa e status do envio ao Meta.",
    "public.scores_historicos":
        "Score e decil recalculados retroativamente para leads antigos, quando um modelo "
        "novo precisa pontuar quem já tinha passado.",
    "public.lead_legado":
        "Backup da tabela de leads do front antigo do Railway (fev a jun/2026), com a "
        "pesquisa em camelCase. Só histórico.",
    "public.leads_historico":
        "Backup da outra tabela de leads do Railway (nov/2025 a jun/2026), com a pesquisa "
        "em snake_case. Só histórico.",
    "public.lead_surveys_stg":
        "Área de passagem da migração de schema de maio/2026. Morta.",
    "analytics.leads":
        "Universo de treino: os leads que responderam a pesquisa, unificados de todas as "
        "fontes. É daqui que o pipeline de treino lê.",
    "analytics.cadastros":
        "Espinha de TODOS os cadastros, respondentes ou não, uma linha por PESSOA. Serve "
        "para contar volume real de captação e casar compra.",
    "analytics.captacoes":
        "Histórico de captação no grão lead x LANÇAMENTO, com o anúncio que trouxe cada "
        "um e se comprou. Montada das planilhas do Drive. É a base da nota do criativo.",
    "analytics.sales":
        "Vendas de todos os gateways (Guru, TMB, Boletex, Asaas, Hotmart), já unificadas.",
    "analytics.sales_tmb_risk":
        "Grau de risco de inadimplência das vendas por boleto da TMB.",
    "analytics.ad_spend":
        "Gasto por anúncio e por dia, vindo da API da Meta. Denominador do ROAS.",
    "analytics.meta_insights":
        "Métricas brutas de campanha da API da Meta (impressões, cliques, custo).",
    "analytics.launch_calendar":
        "Calendário canônico dos lançamentos: quando cada um capta e quando vende. "
        "Espelha a planilha PC FORMULÁRIOS.",
    "analytics.campaign_labels":
        "Rótulo de cada campanha por qual MODELO a tocou, para o relatório saber a quem "
        "creditar cada lead.",
    "analytics.reference_rolling":
        "Referência rolante dos relatórios: a régua de comparação que substituiu o "
        "recorte congelado Top 5 ROAS.",
    "analytics.transcricoes":
        "Transcrição da fala dos vídeos dos criativos, com duração e contagem de palavras. "
        "Alimenta o palpite para criativo estreante.",
    "analytics.hotleads_seal":
        "Selo do HotLeads da Hotmart por lead: se a pessoa já comprou algo na plataforma.",
    "analytics.validation_runs":
        "Cabeçalho de cada rodada de validação do modelo.",
    "analytics.validation_metrics":
        "Métricas de cada rodada de validação.",
    "analytics.leads_provenance":
        "De qual fonte veio cada lead do universo de treino. Trilha de lineage.",
    "analytics.leads_unified_audit":
        "Auditoria da unificação de leads: o que entrou, o que foi deduplicado.",
}

# Colunas que denunciam quando a tabela foi tocada pela última vez, em ordem de
# preferência. A primeira que existir na tabela vira a resposta de "ainda é alimentada?".
COLS_ATUALIZACAO = ("refreshed_at", "ingested_at", "updated_at_src", "updated_at",
                    "created_at", "scored_at", "capturado_em", "captured_at",
                    "first_seen_at", "sale_date", "day", "data")

# Colunas que definem a janela de DADOS (o período que a tabela cobre), diferente da
# janela de INGESTÃO (quando as linhas entraram). As duas juntas contam a história:
# dados até 03/08 com ingestão só em 03/08 = carga única, ninguém alimenta.
COLS_JANELA = ("captured_at", "capturado_em", "created_at", "sale_date", "first_seen_at",
               "day", "data", "cap_start", "window_end")

LIMITE_LINHAS_EXATO = 2_000_000   # acima disso, usa estimativa do planejador


def _colunas(conn, schema, tabela):
    return conn.run(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position",
        s=schema, t=tabela)


def _primeira_que_existe(nomes, disponiveis):
    for n in nomes:
        if n in disponiveis:
            return n
    return None


def _minmax(conn, schema, tabela, coluna):
    try:
        r = conn.run(f'SELECT min("{coluna}")::date, max("{coluna}")::date '
                     f'FROM "{schema}"."{tabela}"')
        return r[0][0], r[0][1]
    except Exception:
        return None, None


def _fmt(d):
    if d is None:
        return "-"
    return d.isoformat() if isinstance(d, (date, datetime)) else str(d)


def _idade(d, hoje):
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return (hoje - d).days


def coleta(conn):
    tabelas = conn.run(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_type = 'BASE TABLE' "
        "AND table_schema NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY table_schema, table_name")
    hoje = datetime.now(timezone.utc).date()
    out = []
    for schema, tabela in tabelas:
        cols = _colunas(conn, schema, tabela)
        nomes = {c for c, _ in cols}
        try:
            n = conn.run(f'SELECT count(*) FROM "{schema}"."{tabela}"')[0][0]
        except Exception as e:
            n = -1
            print(f"  [aviso] count falhou em {schema}.{tabela}: {type(e).__name__}",
                  file=sys.stderr)
        col_at = _primeira_que_existe(COLS_ATUALIZACAO, nomes)
        col_jan = _primeira_que_existe(COLS_JANELA, nomes)
        ult = _minmax(conn, schema, tabela, col_at)[1] if (col_at and n > 0) else None
        jan = _minmax(conn, schema, tabela, col_jan) if (col_jan and n > 0) else (None, None)
        out.append({
            "nome": f"{schema}.{tabela}", "schema": schema, "linhas": n,
            "colunas": cols, "col_atualizacao": col_at, "ultima": ult,
            "janela_ini": jan[0], "janela_fim": jan[1],
            "idade_dias": _idade(ult, hoje),
        })
        print(f"  lida: {schema}.{tabela} ({n:,} linhas)", file=sys.stderr)
    return out, hoje


def _sinal(t):
    """Semáforo de 'ainda é alimentada?'. É a coluna mais útil do relatório."""
    d = t["idade_dias"]
    if t["linhas"] == 0:
        return "⬜ vazia"
    if d is None:
        return "❔ sem coluna de data"
    if d <= 2:
        return "🟢 viva"
    if d <= 15:
        return f"🟡 {d}d sem escrita"
    return f"🔴 {d}d sem escrita"


def render(tabelas, hoje, sem_colunas=False):
    L = []
    L.append("# Catálogo de dados")
    L.append("")
    L.append(f"**Gerado automaticamente em {hoje.isoformat()}** por "
             "[scripts/catalogo_dados.py](../scripts/catalogo_dados.py). "
             "Não editar à mão: rode o script de novo.")
    L.append("")
    L.append("A única parte escrita por gente é a coluna *Para que serve*, que mora no "
             "dicionário `PARA_QUE_SERVE` dentro do script. Tabela nova aparece aqui "
             "sozinha, marcada como SEM DESCRIÇÃO até alguém escrever a linha dela.")
    L.append("")
    L.append("**Como ler a coluna Estado:** 🟢 escrita nos últimos 2 dias · "
             "🟡 parada há até 15 dias · 🔴 parada há mais de 15 dias · ⬜ vazia. "
             "Parada não quer dizer quebrada: uma tabela de captação fica parada de "
             "propósito entre lançamentos. Quer dizer *confira antes de confiar*.")
    L.append("")

    vivas = [t for t in tabelas if t["idade_dias"] is not None and t["idade_dias"] <= 2]
    paradas = [t for t in tabelas if t["idade_dias"] is not None and t["idade_dias"] > 15]
    L.append(f"**{len(tabelas)} tabelas** · {len(vivas)} escritas nos últimos 2 dias · "
             f"{len(paradas)} paradas há mais de 15 dias.")
    L.append("")

    for schema in sorted({t["schema"] for t in tabelas}):
        doschema = [t for t in tabelas if t["schema"] == schema]
        L.append(f"## Schema `{schema}` ({len(doschema)} tabelas)")
        L.append("")
        L.append("| Tabela | Linhas | Estado | Última escrita | Janela dos dados | Para que serve |")
        L.append("|---|---:|---|---|---|---|")
        for t in sorted(doschema, key=lambda x: -x["linhas"]):
            desc = PARA_QUE_SERVE.get(t["nome"], "**SEM DESCRIÇÃO** (escrever no script)")
            jan = (f"{_fmt(t['janela_ini'])} a {_fmt(t['janela_fim'])}"
                   if t["janela_ini"] else "-")
            linhas = f"{t['linhas']:,}" if t["linhas"] >= 0 else "?"
            L.append(f"| `{t['nome'].split('.')[1]}` | {linhas} | {_sinal(t)} | "
                     f"{_fmt(t['ultima'])} | {jan} | {desc} |")
        L.append("")

    if not sem_colunas:
        L.append("## Colunas de cada tabela")
        L.append("")
        for t in sorted(tabelas, key=lambda x: x["nome"]):
            L.append(f"### `{t['nome']}`")
            L.append("")
            L.append(", ".join(f"`{c}`" for c, _ in t["colunas"]))
            L.append("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stdout", action="store_true", help="imprime em vez de escrever")
    ap.add_argument("--sem-colunas", action="store_true", help="omite a lista de colunas")
    args = ap.parse_args()

    conn = open_analytics_connection(timeout=600)
    try:
        conn.run("SET lock_timeout = '5s'")
        conn.run("SET statement_timeout = '120s'")
        tabelas, hoje = coleta(conn)
    finally:
        conn.close()

    texto = render(tabelas, hoje, sem_colunas=args.sem_colunas)
    if args.stdout:
        print(texto)
        return
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(texto, encoding="utf-8")
    print(f"\n{SAIDA} escrito · {len(tabelas)} tabelas", file=sys.stderr)
    sem_desc = [t["nome"] for t in tabelas if t["nome"] not in PARA_QUE_SERVE]
    if sem_desc:
        print(f"SEM DESCRIÇÃO ({len(sem_desc)}): {', '.join(sem_desc)}", file=sys.stderr)


if __name__ == "__main__":
    main()
