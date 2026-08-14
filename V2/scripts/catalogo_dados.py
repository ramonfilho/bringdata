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

# A OUTRA parte manual. Existe porque a tabela de cima descreve UMA tabela por vez, e a
# dúvida que mais custa tempo não é "o que é esta tabela", é "então esta e aquela são a
# mesma coisa?". Sem um lugar para a RELAÇÃO, o leitor precisa deduzir de duas linhas
# distantes — e em 10/08/2026 essa dedução saiu errada em conversa, com `analytics.leads`
# e `analytics.cadastros` trocadas de papel por quem conhece o projeto.
RELACOES = """## Relações entre tabelas

A tabela acima descreve cada tabela isolada. Esta seção diz como elas se cruzam, que é a
parte que a listagem não consegue mostrar.

### Os três lugares onde um lead pode estar (e por que não é redundância)

```
      o lead responde a pesquisa
                 │
                 ▼
   public.registros_ml ......... LEDGER VIVO. Uma linha por RESPOSTA.
   (23/05/2026 em diante)        Chega em minutos, pela fila do Pub/Sub.
                 │
                 │  prio 1 de cinco fontes (leads_unify.py)
                 ▼
   analytics.leads ............. UNIVERSO DE TREINO. Só respondente.
   (histórico completo)          Uma linha por (e-mail, dia). Refeita 09:00.
                 │
                 │  define a marca is_respondent
                 ▼
   analytics.cadastros ......... ESPINHA. Respondente E não-respondente.
   (histórico completo)          Uma linha por PESSOA. Refeita 10:00.
```

**`registros_ml` e `analytics.leads` cobrem a mesma gente de 23/05/2026 para cá.** Não é
duplicação por descuido: o ledger é a fonte CRUA e VIVA, e `analytics.leads` é a
consolidação tratada que o INGERE como prioridade 1. Antes de 23/05 o ledger não existia,
e naquele período `analytics.leads` é a única que tem o dado — ele vem das outras quatro
fontes (`lead_legado`, `lead_surveys`, planilhas do Sheets e arquivos `.xlsx`).

Consequência prática, e é a que morde: **quem quer o lead de HOJE não pode ler as duas
derivadas**, porque as duas são reconstruídas de madrugada. Tem que ler o ledger.

### Os dois erros de leitura mais fáceis de cometer

1. **"`analytics.leads` tem todos os leads."** Não. Ela tem os que RESPONDERAM a pesquisa.
   Quem se cadastrou e não respondeu (23% da base em 2026) só existe em
   `analytics.cadastros`.
2. **"`analytics.cadastros` é a base de treino."** Não. O treino lê `analytics.leads`. A
   marca `is_respondent` de `cadastros` é derivada de estar em `analytics.leads`, então
   inverter os dois papéis inverte a direção da dependência.

### Onde cada uma é consumida

| Consumidor | Lê | Por quê |
|---|---|---|
| Pipeline de treino | `analytics.leads` | é o universo de treino |
| Entrega para a agência de tráfego | **`analytics.captacoes`, só ela** | fonte única desde 11/08/2026; antes somava as três |
| Nota do criativo | `analytics.captacoes` | histórico de captação com desfecho |
| Contagem de volume real de captação | `analytics.cadastros` | é a única com quem não respondeu |
| Relatórios de decil e score | `public.registros_ml` | é onde score e decil moram |

### A QUARTA tabela de lead: `analytics.captacoes`

Ela não entra no desenho acima porque não vem daquela cadeia. As três de cima nascem da
PESQUISA; a `captacoes` nasce do CADASTRO, direto do Railway (`Client` LEFT JOIN
`UTMTracking`), por `scripts/ingest_captacoes_railway.py`.

```
   Railway: Client (todo mundo)  +  UTMTracking (a campanha)
                 │
                 ▼
   analytics.captacoes ......... uma linha por INSCRIÇÃO.
   (chave lf+email+origem_id)    Chega em minutos. É a fonte da entrega
                                 para a agência e da nota do criativo.
```

O grão dela é o único que permite a MESMA pessoa aparecer duas vezes no mesmo lançamento —
as outras três colapsam por pessoa ou por (pessoa, dia). Foi essa a razão da mudança de
chave em 11/08/2026: a agência precisa ver o recadastro.

Cuidado ao contar gente nela: 505 mil linhas NÃO são 505 mil pessoas. Quem for contar
público tem que deduplicar por e-mail — `read_captacoes_audience` já faz, e `nota_criativo`
deduplica por (pessoa, criativo, dia) porque a nota é uma taxa.
"""

# A ÚNICA parte manual. Uma linha por tabela dizendo para que ela serve — o resto o
# script descobre sozinho. Tabela que aparecer no banco e não estiver aqui sai no
# relatório marcada como SEM DESCRIÇÃO, que é o lembrete de vir escrever uma linha.
PARA_QUE_SERVE = {
    "public.registros_ml":
        "O ledger do ML. O consumer do Pub/Sub escreve uma linha por lead no momento em "
        "que o scoreia. É a fonte VIVA de decil, score, variante do A/B, respostas da "
        "pesquisa e status do envio ao Meta. **É a prioridade 1 de `analytics.leads`** — "
        "as duas cobrem a mesma gente de 23/05/2026 pra cá; ver Relações entre tabelas.",
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
        "Universo de treino: os leads que responderam a pesquisa, unificados de CINCO "
        "fontes por `leads_unify.py` (a prioridade 1 é `registros_ml`). É daqui que o "
        "pipeline de treino lê. Uma linha por (e-mail, dia). **Não é a tabela de todos os "
        "leads** — quem não respondeu não está aqui, está em `analytics.cadastros`.",
    "analytics.cadastros":
        "Espinha de TODOS os cadastros, respondentes ou não, uma linha por PESSOA. Serve "
        "para contar volume real de captação e casar compra. **Não é base de treino**: a "
        "marca `is_respondent` dela é calculada perguntando se a pessoa está em "
        "`analytics.leads`.",
    "analytics.url_captura_legado":
        "Repescagem da URL de captura de JANEIRO e fevereiro/2026, montada em 09/08/2026 "
        "por `scripts/recupera_url_legado.py` a partir do dump do Cloud SQL de 25/02. "
        "Estática de propósito: é histórico recuperado, não fonte viva. Existe porque a "
        "URL daquele período morava em `leads_capi.event_source_url`, que hoje está vazia "
        "— o dado não se perdeu, deixou de ser copiado adiante numa migração de schema. "
        "Levou janeiro de 0,9% para 98,6% de cobertura na entrega da agência.",
    "analytics.decis_backfill_jul24":
        "Foto pontual (21/07/2026) do decil do MESMO lead pelos dois modelos, jul24 e "
        "abr28, lado a lado — 418 linhas. Serviu para comparar os dois na mesma régua; "
        "não é alimentada por nada, é registro de uma análise.",
    "analytics.captacoes":
        "Histórico de captação, uma linha por INSCRIÇÃO (chave `lf, chave, origem_id`). É a "
        "FONTE ÚNICA da entrega de leads para a agência de tráfego e a base da nota do "
        "criativo. Alimentada por `ingest_captacoes_railway.py` a partir do Railway "
        "(`Client` LEFT JOIN `UTMTracking`) a cada 5 min; as ~503 mil linhas antigas vieram "
        "das planilhas do Drive (coluna `planilha` guarda a procedência). Até 11/08/2026 "
        "não tinha escritor nenhum no repositório — por isso parou sozinha em 03/08 e o "
        "LF64 ficou com ZERO linhas com o lançamento rodando.",
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
    L.append("As partes escritas por gente são duas, as duas dentro do script: a coluna "
             "*Para que serve* (dicionário `PARA_QUE_SERVE`) e a seção *Relações entre "
             "tabelas* (constante `RELACOES`). Tabela nova aparece aqui sozinha, marcada "
             "como SEM DESCRIÇÃO até alguém escrever a linha dela.")
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

    # Vem ANTES da lista de colunas de propósito: quem abre o catálogo com dúvida de
    # "estas duas são a mesma coisa?" desiste antes de rolar 200 linhas de nomes de coluna.
    L.append(RELACOES)

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
