"""Empurra a nota por CRIATIVO e por CAMPANHA para `public.scores_inbound` no Supabase deles.

ESTADO: NO AR desde 12/08/2026. Job `push-scores-zanelato`, cron de hora em hora no minuto
22 (fora dos minutos 0,10,20,... da ingestão e dos 5,15,25,... da entrega de leads).

  - PISO DE N = 100, o default de `build_top5_comparison`. A conta: a diferença real entre
    criativos é ~11pp (desvio-padrão de 13,3pp medido em 21 criativos com N>=200, descontado
    o ruído de amostra desses mesmos 200). Dois erros-padrão dão 18,2pp em N=30, 14,1pp em
    N=50 e 10,0pp em N=100. Abaixo de 100 o ruído é maior que a diferença entre criativos e a
    coluna de delta vira decorativa. O relatório interno usa o mesmo 100 desde 12/08/2026.
  - `LEDGER_DECIL_READ_SOURCE=ledger` é OBRIGATÓRIO no ambiente onde ele roda. Sem isso a
    função cai no ramo legado que lê a `scores_historicos`, aposentada em 08/07/2026 — e
    devolve VAZIO para qualquer lançamento depois do LF61. O job já tem a variável; um
    ambiente local sem ela reproduz um falso "não tem dado".

A ESCADA DE JANELAS ROLANTES (Ramon, 19/08/2026)
================================================
São QUATRO janelas, e NENHUMA delas é ancorada no calendário de lançamento:

    histórico (90 dias) → 7 dias → 3 dias → hoje

Todas terminam no dia de hoje e contam para trás. É a escada de recência que o gestor usa
para decidir CPL: o histórico dá o teto estável do anúncio, o de hoje dá o mais fresco, e os
do meio ficam entre os dois. Quanto mais curta a janela, mais rápido ela reage e menos
linhas passam do piso de N.

POR QUE NENHUMA É ANCORADA NO LANÇAMENTO
----------------------------------------
Até 19/08/2026 o corte curto era GRAMPEADO no início do lançamento (`max(cap_start, hoje-2)`)
e o acumulado era a janela do lançamento inteiro. Na virada do LF64 para o LF65 (17→18/08)
isso colapsou a janela de 3 dias para 1 dia e o painel foi de 7 criativos para 1, embora 17
anúncios tivessem atravessado a virada rodando sem nenhuma mudança neles. A nota não se
perdeu: a janela é que foi cortada na data.

O grampo saiu. O "zerar só quem começou do zero" passa a valer sem regra nenhuma: anúncio
que estreou não tem lead nos dias anteriores, não cruza o piso de 100 e simplesmente não
aparece até merecer — enquanto quem continuou rodando mantém a linha inteira. E o tipo sem
sufixo (o antigo acumulado do lançamento) passa a publicar a MESMA conta do histórico, para
não quebrar quem já lê `tipo='criativo'` no painel deles.

POR QUE 90 DIAS NO HISTÓRICO
----------------------------
Não é escolha de calendário: é o alcance da RÉGUA. A distribuição de decis só conta lead
scoreado pelo champion ATUAL, e ele começou a scorear em 25/05/2026 (medido em 19/08). Por
isso 90 dias e 180 dias devolvem exatamente o mesmo conjunto — 90 é todo o histórico que a
régua enxerga, e é a mesma janela em que a referência rolante mede conversão por decil,
valor por venda e fator de rastreamento.

Todas convivem na MESMA tabela sem pedir nada à agência, porque a chave única de lá é
`(tipo, chave)` e `tipo` é uma coluna de texto livre, sem CHECK e sem enum (verificado em
12/08/2026). Então `('criativo', 'DEV-AD0160')` e `('criativo_3dias', 'DEV-AD0160')` são duas
linhas distintas que não colidem.

ATENÇÃO DE QUEM LÊ DO LADO DELES: o painel TEM que filtrar por `tipo`. Sem filtro, o mesmo
criativo aparece duas vezes com números diferentes e parece erro nosso.

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
    tipo                 'criativo' / 'campanha'                    = histórico (90 dias)
                         'criativo_historico' / 'campanha_...'      = o MESMO, nome explícito
                         'criativo_7dias' / 'campanha_7dias'        = últimos 7 dias
                         'criativo_3dias' / 'campanha_3dias'        = últimos 3 dias
                         'criativo_hoje'                            = o dia de hoje
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
# O padrão do carimbo `[G] ` vive num lugar só (ver a função lá): quem põe é o
# resolvedor da ingestão, quem tira é a chave canônica do histórico, e quem
# pergunta é a moeda do gerenciador aqui embaixo.
from src.data.criativo_historico import (                               # noqa: E402
    chave_canonica, tem_carimbo_google,
)

TABELA_DESTINO = "public.scores_inbound"
CLIENTE = "devclub"

# OS DEGRAUS DA ESCADA, em dias contados para trás a partir de HOJE.
# 3 é o menor que ainda passa do piso de N=100 com o volume que um criativo faz por dia
# neste cliente (60 a 100 leads/dia nos que rodam de verdade); 7 é a semana, que reage mais
# devagar e sustenta mais linhas; 90 é o alcance da régua (ver docstring).
DIAS_HISTORICO = 90
DIAS_MEDIO = 7
DIAS_CORTE = 3

# Sufixo que separa os cortes na coluna `tipo` da tabela deles. Vazio = o tipo antigo, que
# desde 19/08 publica a MESMA conta do histórico (era o acumulado do lançamento).
# Mudar estes valores é mudar o CONTRATO com o painel da agência.
CORTE_ACUMULADO = ""
CORTE_HISTORICO = "_historico"
CORTE_MEDIO = f"_{DIAS_MEDIO}dias"
CORTE_CURTO = f"_{DIAS_CORTE}dias"
# Corte HOJE (aprovado 16/08): a visão mais fresca possível que ainda é honesta —
# só publica quem cruzou o piso de N no PRÓPRIO dia; em dia fraco a lista vem curta.
CORTE_HOJE = "_hoje"

# Todos os sufixos que este script é dono de escrever — e, portanto, de PODAR. Lista única:
# um corte novo que entre aqui já nasce com faxina, e foi esquecer disso que deixou linha do
# LF64 congelada no painel depois da virada.
TODOS_OS_CORTES = [CORTE_ACUMULADO, CORTE_HISTORICO, CORTE_MEDIO, CORTE_CURTO, CORTE_HOJE]

# Como cada corte se chama no log (o painel deles lê o `tipo`, não isto).
ROTULO = {CORTE_HISTORICO: f"histórico ({DIAS_HISTORICO} dias)",
          CORTE_MEDIO: f"últimos {DIAS_MEDIO} dias",
          CORTE_CURTO: f"últimos {DIAS_CORTE} dias",
          CORTE_HOJE: "hoje"}

# `atualizado_em` fica de fora: tem default `now()` no lado deles, e é o carimbo de quando
# ELES receberam. Mandar valor sobrescreveria a informação deles com a nossa.
COLUNAS = ["tipo", "chave", "leads", "pct_top20", "referencia_pct", "delta_vs_referencia",
           "teto_cpl", "teto_roas_alvo", "teto_referencia"]

# Segundo teto, com meta de ROAS mais frouxa (pedido do Ramon, 23/08): a meta só
# entra na fórmula como divisor, então o teto a 1,5 é o MESMO teto publicado
# (já na moeda da linha) reescalado por alvo/1,5 — nada é recalculado, e a moeda
# do gerenciador atravessa intacta porque a razão dela não depende da meta.
ROAS_ALVO_SECUNDARIO = 1.5
COLUNA_SECUNDARIA = "teto_cpl_roas15"

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


def _fronteira_utc(dia, fim_do_dia: bool = False):
    """Converte uma DATA de Brasília no instante UTC correspondente.

    A janela do calendário vem em data de Brasília, e `registros_ml.created_at` guarda UTC.
    Montar a fronteira como data pura fazia `07/08 00:00` virar 06/08 21:00 de Brasília, e
    três horas da noite do dia ANTERIOR entravam na conta do lançamento.

    É o mesmo erro de fuso que jogou lead da noite para o dia seguinte na entrega da agência:
    nada no código dizia UTC, o UTC vinha do ambiente. Somar 3h converte a meia-noite de
    Brasília no instante UTC; `fim_do_dia` soma um dia porque a janela do calendário é
    inclusiva no último dia e a comparação de tempo é exclusiva.
    """
    base = datetime.combine(dia, datetime.min.time()) + timedelta(hours=3)
    return base + timedelta(days=1) if fim_do_dia else base


def _mapa_de_nomes(conn) -> dict:
    """ad_id -> nome do anúncio, da criativo_id_map. Existe porque a macro de nome
    falha em alguns anúncios e o utm chega como o ID numérico cru. Publicar número
    numa linha e nome na outra é falha de consistência que corrói a confiança na
    métrica (Ramon, 16/08) — então a CHAVE publicada é sempre o nome quando o mapa
    o conhece; o ID fica só como fallback de anúncio ainda não mapeado."""
    try:
        return {str(r[0]): " ".join(str(r[1]).split())
                for r in conn.run("SELECT ad_id, ad_name FROM analytics.criativo_id_map "
                                  "WHERE ad_name IS NOT NULL")}
    except Exception:
        return {}


# Dia (date) -> linhas cruas da Meta, dentro de UMA rodada. Ver o uso, abaixo.
_CACHE_DIA_VIVO: dict = {}


def _leads_do_gerenciador(conn, ini, fim) -> dict:
    """Leads que o GERENCIADOR da Meta conta na janela, agregados nos grãos das
    linhas publicadas. Cópia (mesmo nome, outro ad_id) SOMA — cópia é o mesmo
    anúncio (Ramon, 18/08). Chaves normalizadas em minúsculas/espaço único.

    Devolve {"fino": {(cid, nome, conjunto): n}, "cn": {(cid, nome): n},
             "campanha": {cid: n}, "nome": {nome: n}}."""
    def _n(x):
        return " ".join(str(x or "").split()).lower()
    out = {"fino": {}, "cn": {}, "campanha": {}, "nome": {}, "cobertura": 1.0}

    def _soma(cid, nome, conj, ld):
        out["fino"][(cid, nome, conj)] = out["fino"].get((cid, nome, conj), 0) + ld
        out["cn"][(cid, nome)] = out["cn"].get((cid, nome), 0) + ld
        out["campanha"][cid] = out["campanha"].get(cid, 0) + ld
        out["nome"][nome] = out["nome"].get(nome, 0) + ld

    try:
        rows = conn.run(
            "SELECT campaign_id, ad_name, coalesce(adset_name, ''), sum(leads) "
            "FROM ad_insights WHERE insight_date >= :i AND insight_date <= :f "
            "AND leads > 0 AND campaign_id IS NOT NULL GROUP BY 1, 2, 3",
            i=ini.isoformat(), f=fim.isoformat())
        max_db = conn.run("SELECT max(insight_date) FROM ad_insights "
                          "WHERE insight_date <= :f", f=fim.isoformat())[0][0]
    except Exception as e:
        print(f"  moeda do gerenciador INDISPONÍVEL nesta rodada ({e}); "
              f"linhas saem na moeda real, com selo dizendo isso")
        out["cobertura"] = 0.0
        return out
    for cid, nome, conj, ld in rows:
        _soma(str(cid), _n(nome), _n(conj), int(ld))

    # A ingestão do gerenciador fecha D-1; a janela dos cortes inclui HOJE.
    # Sem esta puxada AO VIVO, a razão dos cortes hoje/3 dias sairia enviesada
    # pra CIMA (leads reais do dia sem o par do gerenciador) — furo apontado
    # pelo Ramon em 18/08. No máximo 3 dias por rodada (1 chamada/dia).
    # Dia FUTURO não é dia descoberto: a janela do acumulado vai até o fim do
    # lançamento no calendário (ex.: 24/08 num dia 18/08), e contar o futuro
    # como buraco zerava a cobertura do acumulado (pego no --check de 18/08).
    fim_real = min(fim, _hoje_brt())
    faltam = []
    d = ini
    while d <= fim_real:
        if max_db is None or d > max_db:
            faltam.append(d)
        d += timedelta(days=1)
    if faltam:
        token = os.getenv("META_ACCESS_TOKEN")
        vivos = 0
        if token and len(faltam) <= 3:
            try:
                from api.meta_integration import MetaAdsIntegration
                from scripts.ingest_ad_insights import puxa_dia
                meta = MetaAdsIntegration(access_token=token)
                conta = os.getenv("META_ACCOUNT_ID", "act_188005769808959")
                for d in faltam:
                    # CACHE por dia: as quatro janelas da escada terminam todas em hoje,
                    # então sem isto o mesmo dia seria pedido quatro vezes à API da Meta
                    # na mesma rodada — mesma resposta, quatro vezes o custo de cota.
                    if d not in _CACHE_DIA_VIVO:
                        _CACHE_DIA_VIVO[d] = list(puxa_dia(meta, conta, d))
                    for x in _CACHE_DIA_VIVO[d]:
                        if x["ld"] and x["camp"]:
                            _soma(str(x["camp"]), _n(x["nome"]),
                                  _n(x.get("cjn")), int(x["ld"]))
                    vivos += 1
            except Exception as e:
                print(f"  puxada ao vivo do gerenciador falhou ({e})")
        dias_janela = (fim_real - ini).days + 1
        out["cobertura"] = (dias_janela - len(faltam) + vivos) / dias_janela
        if vivos:
            print(f"  gerenciador: {vivos} dia(s) puxado(s) ao vivo "
                  f"(banco fecha D-1); cobertura {out['cobertura']:.0%}")
    return out


def _cadastros_da_janela(conn, ini, fim, mapa_nome: dict) -> dict:
    """Cadastros TOTAIS (respondente ou não) da janela, nos mesmos grãos e com
    as MESMAS chaves das cestas do gerenciador — o par da conta dos leads
    valorados da Decisão 12. Fonte: analytics.captacoes (a espinha de captação;
    registros_ml só tem quem respondeu, e o ponto aqui é justamente contar quem
    não respondeu). O id da campanha sai do sufixo `nome|id` da utm_campaign da
    Meta — linha sem esse formato (Google/devlf) fica fora, e o Google nem
    chega aqui (sai em moeda_real antes).

    PESSOAS, não inscrições: `count(DISTINCT email)`. A captacoes tem uma linha
    por INSCRIÇÃO (a mesma pessoa reinscrita em dois lançamentos da janela de 90
    dias vira duas linhas), enquanto o lado dos respondentes é deduplicado por
    email e o próprio crédito foi medido sobre pessoas únicas. Contar linha
    contra pessoa transformaria cada duplicata num "não-respondente" fantasma
    creditado, inflando o teto.

    E a chave sai TRADUZIDA pelo mesmo mapa de nomes da publicação, canonizada
    igual ao histórico: a linha publicada usa o NOME do anúncio quando a macro
    falhou e a UTM chegou como ID numérico, então indexar aqui pelo utm_content
    cru faria o lookup falhar em silêncio — e o silêncio dá teto diferente para
    anúncios equivalentes, indistinguível no selo. Mesma armadilha de grafia
    (NFC/NFD) do histórico do criativo (PR #237)."""
    def _k(x):
        """Chave canônica do nome, na MESMA régua do casamento do histórico."""
        return chave_canonica(x)
    out = {"fino": {}, "cn": {}, "campanha": {}, "nome": {}}
    try:
        rows = conn.run(
            "SELECT coalesce(utm_campaign,''), utm_content, "
            "       coalesce(utm_medium,''), count(DISTINCT lower(trim(email))) "
            "FROM analytics.captacoes "
            "WHERE captured_at >= :a AND captured_at < :b "
            "  AND utm_content IS NOT NULL AND utm_content <> '' "
            "  AND email IS NOT NULL AND email <> '' "
            "GROUP BY 1, 2, 3",
            a=_fronteira_utc(ini), b=_fronteira_utc(fim, fim_do_dia=True))
    except Exception as e:
        print(f"  cadastros da janela indisponíveis ({e}); "
              f"moeda segue sem o crédito do não-respondente")
        return out
    for camp, nome, conj, n in rows:
        camp = str(camp)
        if "|" not in camp:
            continue
        cid = camp.split("|")[-1].strip()
        nome = str(nome).strip()
        # ID numérico → nome publicado, igual à linha (senão a chave não casa).
        if nome.isdigit() and len(nome) >= 10 and nome in mapa_nome:
            nome = mapa_nome[nome]
        nome, conj, n = _k(nome), _k(conj), int(n)
        out["fino"][(cid, nome, conj)] = out["fino"].get((cid, nome, conj), 0) + n
        out["cn"][(cid, nome)] = out["cn"].get((cid, nome), 0) + n
        out["campanha"][cid] = out["campanha"].get(cid, 0) + n
        out["nome"][nome] = out["nome"].get(nome, 0) + n
    return out


def _credito_da_referencia(conn):
    """O crédito do não-respondente MEDIDO pelo refresh semanal
    (conversion.survey_coverage do payload da referência). Inválido/ausente →
    None, e a moeda cai no comportamento antigo."""
    try:
        from src.data.reference_reader import read_rolling_reference
        ref = read_rolling_reference(CLIENTE, conn=conn) or {}
        sc = (ref.get("conversion") or {}).get("survey_coverage") or {}
        if sc.get("valido") and sc.get("credito"):
            return float(sc["credito"])
    except Exception as e:
        print(f"  crédito do não-respondente indisponível ({e})")
    return None


# Faixa em que a razão por linha é confiável; fora dela (ou sem casamento) a
# linha usa a razão AGREGADA do corte. Medido em 18/08 sobre agosto inteiro:
# mediana 0,82, p10-p90 0,65-0,90, agregado 0,778 — o gerenciador conta ~20-25%
# mais leads que o nosso banco, e publicar teto real contra CPL do gerenciador
# faria o gestor pagar ~22% acima achando que está dentro.
RAZAO_FAIXA = (0.5, 1.5)


def _moeda_do_gerenciador(linhas, ger, cad=None, credito=None) -> list:
    """Converte o teto de cada linha Meta pra moeda do GERENCIADOR.

    teto_ger = teto_real × (leads VALORADOS ÷ leads_gerenciador) da PRÓPRIA janela.
    A decisão do gestor não muda (o gasto é o mesmo e a razão cancela dos dois
    lados); só a régua passa a falar a língua do CPL que ele vê na tela.
    Linha sem casamento no gerenciador (Google, anúncio sem insight) fica na
    moeda real com selo `moeda_real`.

    LEADS VALORADOS (Decisão 12, 20/08): a razão antiga era respondentes÷ger, o
    que descontava do teto DUAS coisas coladas — a inflação real do gerenciador
    (~7%) e a taxa de resposta da pesquisa (~85%) — tratando o cadastro que não
    respondeu como se valesse zero. Ele compra: ~33-45% da taxa do respondente
    (medido em 343k cadastros). Então o numerador vira
    `respondentes + credito × (cadastros − respondentes)`, com o `credito`
    MEDIDO toda semana pelo refresh na janela madura (conversion.survey_coverage
    do payload). Sem crédito válido ou sem contagem de cadastros da linha, cai
    no comportamento antigo — conservador, nunca inventa valor."""
    def _n(x):
        return " ".join(str(x or "").split()).lower()

    def _canon(cesta, k):
        """A chave da cesta de CADASTROS, que é canonizada (NFC, sem carimbo,
        caixa baixa) — a do gerenciador só normaliza espaço/caixa. Sem esta
        tradução o lookup falharia em silêncio por diferença de grafia, e
        silêncio aqui dá teto diferente para anúncios equivalentes."""
        if cesta == "nome":
            return chave_canonica(k)
        if cesta == "cn":
            return (k[0], chave_canonica(k[1]))
        if cesta == "fino":
            return (k[0], chave_canonica(k[1]), chave_canonica(k[2]))
        return k

    def _valorados(x, cesta, k) -> float:
        """O numerador da razão da linha: respondentes + crédito dos cadastros
        que não responderam. Clampa em `resp` quando a contagem de cadastros
        vem menor que a de respondentes (janela/UTM desalinhados): crédito
        negativo seria punir a linha por defeito de contagem nossa."""
        resp = int(x[2] or 0)
        if not credito or not cad:
            return float(resp)
        cad_n = cad.get(cesta, {}).get(_canon(cesta, k))
        if not cad_n or cad_n <= resp:
            return float(resp)
        return resp + credito * (cad_n - resp)

    def _alvo(tipo, chave):
        # ANÚNCIO DO GOOGLE NÃO TEM MOEDA DE GERENCIADOR DA META. É a primeira
        # coisa checada, antes de qualquer parsing: o gerenciador da Meta não conta
        # lead do Google, então não existe razão a aplicar e a linha fica na moeda
        # real. Sem esta guarda a linha do Google passava por linha da Meta, porque
        # o critério era "tem `|` na campanha" (a marca do formato `nome|id` de lá)
        # e as campanhas do Google se chamam `DEVLF | CAP | Dgen | Cold | ...`:
        # 18 das 35 têm barra vertical no nome. Não achava par no gerenciador, caía
        # na razão AGREGADA da Meta e publicava 37 linhas a 0,77 do valor devido —
        # o teto do Google 23% mais apertado do que a régua manda, apagando um terço
        # do lift de plataforma. Ficou escondido enquanto a campanha do Google
        # chegava como 'devlf' (sem pipe); apareceu em 19/08, quando o mapa passou a
        # ter a campanha real de cada colocação.
        if tem_carimbo_google(chave):
            return (None, None)
        # Tira o sufixo do corte para achar o GRÃO da linha. Percorre a lista única de
        # cortes: um sufixo novo esquecido aqui faria a linha não casar com cesta
        # nenhuma e sair na moeda real, em silêncio.
        base = tipo
        for s in TODOS_OS_CORTES:
            if s and base.endswith(s):
                base = base[:-len(s)]
                break
        partes = [p.strip() for p in str(chave).split(" @ ")]
        if base == "campanha" and "|" in str(chave):
            return ("campanha", str(chave).split("|")[-1].strip())
        if base == "criativo":
            return ("nome", _n(chave))
        if base == "criativo_campanha" and len(partes) == 2 and "|" in partes[1]:
            return ("cn", (partes[1].split("|")[-1].strip(), _n(partes[0])))
        if base == "criativo_conjunto_campanha" and len(partes) == 3                 and "|" in partes[2]:
            return ("fino", (partes[2].split("|")[-1].strip(), _n(partes[0]),
                             _n(partes[1])))
        return (None, None)

    # Janela mal coberta pelo gerenciador (API do dia falhou e o banco só tem
    # D-1): converter enviesaria pra cima. Tudo sai na moeda real, com selo.
    if ger.get("cobertura", 1.0) < 0.8:
        print(f"  cobertura do gerenciador {ger.get('cobertura', 0):.0%} < 80%: "
              f"corte sai na moeda real")
        return [x if x[6] is None else x[:8] + [f"{x[8]}·moeda_real"]
                for x in linhas]

    # razão agregada do corte: o fallback de linha sem razão própria confiável.
    tr = tg = 0
    for x in linhas:
        cesta, k = _alvo(x[0], x[1])
        if cesta == "cn" and ger["cn"].get(k):
            tr += _valorados(x, cesta, k)
            tg += ger["cn"][k]
    r_agg = (tr / tg) if tg else None

    out = []
    for x in linhas:
        if x[6] is None:                     # linha já sem teto: só repassa
            out.append(x)
            continue
        cesta, k = _alvo(x[0], x[1])
        if cesta is None:
            # Linha que não é da Meta (Google, campanha sem |id): a moeda do
            # gerenciador DELA não é a nossa razão — fica na moeda real, dito
            # no selo. Aplicar a razão agregada aqui foi o bug pego no teste
            # de 18/08 (a linha [G] @ devlf saiu convertida por engano).
            out.append(x[:8] + [f"{x[8]}·moeda_real"])
            continue
        n_ger = ger[cesta].get(k)
        razao = (_valorados(x, cesta, k) / n_ger) if n_ger else None
        selo = "ger"
        if razao is None or not (RAZAO_FAIXA[0] <= razao <= RAZAO_FAIXA[1]):
            razao, selo = r_agg, "ger_agg"
        if razao is None:
            out.append(x[:8] + [f"{x[8]}·moeda_real"])
            continue
        teto_ger = float(x[6]) * razao
        out.append(x[:6] + [f"{teto_ger:.2f}", x[7],
                            f"{x[8]}·{selo}{razao:.2f}"])
    return out


def _com_teto_secundario(linhas) -> list:
    """Acrescenta a 10ª posição da linha: o teto na meta secundária (ROAS 1,5).

    Derivado do teto FINAL da linha (pós-moeda): teto ∝ 1/alvo, logo
    teto@1,5 = teto_publicado × alvo/1,5. Linha sem teto leva None, nunca 0."""
    out = []
    for x in linhas:
        if x[6] is None or x[7] is None:
            out.append(list(x) + [None])
            continue
        out.append(list(x) +
                   [f"{float(x[6]) * float(x[7]) / ROAS_ALVO_SECUNDARIO:.2f}"])
    return out


def _mapa_campanha_google(conn) -> dict:
    """ad_id google -> nome da CAMPANHA real no Google Ads (criativo_id_map).

    Existe porque no Google a campanha NÃO viaja na UTM (tudo chega 'devlf');
    o ID do anúncio é o único portador de "em qual campanha este vídeo roda".
    Traduzir ID->nome e fundir jogava fora exatamente essa informação — o
    gestor precisa de cada colocação separada pra otimizar (Ramon, 18/08)."""
    try:
        return {str(r[0]): " ".join(str(r[1]).split())
                for r in conn.run("SELECT ad_id, campaign_name "
                                  "FROM analytics.criativo_id_map "
                                  "WHERE campaign_name IS NOT NULL")}
    except Exception:
        return {}


def _um_corte(conn, lf, run_id, ini, fim, sufixo: str, mapa_nome: dict,
              credito=None) -> tuple:
    """Roda a comparação numa janela e devolve (linhas, resumo). NÃO recalcula nada.

    O `sufixo` entra na coluna `tipo` e é o que faz os dois cortes conviverem na tabela
    deles sem colidir na chave única `(tipo, chave)`.
    """
    from src.monitoring.utm_quality import build_top5_comparison

    comp = build_top5_comparison(
        lf_name=lf,
        challenger_run_id=run_id,          # nome herdado: o valor é o CHAMPION
        win_start=_fronteira_utc(ini),
        win_end=_fronteira_utc(fim, fim_do_dia=True),
        client_id=CLIENTE,
        conn=conn,
        # `pin_lf=False` em TODOS os cortes desde 19/08: cada janela conta quem entrou
        # NELA, sem amarrar no rótulo de lançamento. Era o default só do corte curto,
        # enquanto o acumulado era a visão do LF; com a escada rolante não há mais visão
        # de LF neste painel (a nota por lançamento vive no relatório interno).
        pin_lf=False,
    )
    if not comp:
        return [], {"vazio": True, "sufixo": sufixo, "ini": ini, "fim": fim}

    # Teto por chave (Decisão 9): calculado pela MESMA janela do corte, pelo módulo
    # de produção (teto_por_chave), e só traduzido aqui. Linha sem teto leva o
    # motivo no carimbo em vez de célula muda.
    from src.monitoring.teto_por_chave import tetos_completos, carimbo
    tetos, unidades_t, conjuntos_t = tetos_completos(
        conn, conn, run_id=run_id,
        win_start=_fronteira_utc(ini), win_end=_fronteira_utc(fim, fim_do_dia=True))

    barra = comp["bar_pct"]
    linhas, escondidas = [], 0
    for nivel, dados in comp["levels"].items():
        escondidas += dados.get("hidden_below_min_n", 0) or 0
        for r in dados["rows"]:
            chave = str(r.get("utm") or r.get("key") or "sem_utm").strip()
            t = tetos.get((nivel, chave))   # o teto casa pela chave ORIGINAL do utm
            if (nivel == "creative" and chave.isdigit() and len(chave) >= 10
                    and chave in mapa_nome):
                chave = mapa_nome[chave]    # publica o NOME; o ID morre na entrega
            linhas.append([
                TIPO[nivel] + sufixo,
                chave,
                int(r.get("n") or 0),
                r.get("pct_d9_d10"),
                barra,
                r.get("delta_pp"),
                (f"{t.valor:.2f}" if t is not None and t.ok else None),
                (t.roas_alvo if t is not None and t.ok else None),
                (carimbo(t) if t is not None else "sem_teto:sem_distribuicao_de_decis"),
            ])
    # O GRÃO DO PRODUTO: criativo DENTRO de cada campanha (o mesmo anúncio pode
    # ter um teto numa campanha e outro na outra). tipo criativo_campanha[sufixo],
    # chave "criativo @ campanha", mesmo piso de N das demais linhas.
    min_n_u = comp.get("min_n") or 100
    mapa_camp_g = _mapa_campanha_google(conn)
    for u in unidades_t:
        if u["n"] < min_n_u:
            continue
        t = u["teto"]
        cr = u["criativo"]
        camp_rotulo = u["campanha"]
        if cr.isdigit() and len(cr) >= 10:
            # Colocação do GOOGLE: a campanha real vem do mapa (a UTM só diz
            # 'devlf'). Cada ID vira a própria linha "vídeo @ campanha-real";
            # dois IDs do mesmo vídeo NA MESMA campanha ainda se fundem (aí
            # sim é cópia da mesma colocação). O histórico/lift continua
            # somado por vídeo — força de venda é do criativo, otimização é
            # da colocação.
            if cr in mapa_camp_g:
                camp_rotulo = mapa_camp_g[cr]
            if cr in mapa_nome:
                cr = mapa_nome[cr]
        linhas.append([
            "criativo_campanha" + sufixo,
            f"{cr} @ {camp_rotulo}",
            int(u["n"]),
            round(u["pct"], 1),
            barra,
            round(u["pct"] - (barra or 0), 1),
            (f"{t.valor:.2f}" if t.ok else None),
            (t.roas_alvo if t.ok else None),
            carimbo(t),
        ])

    # O grão do PÚBLICO (18/08): o mesmo anúncio na mesma campanha rodando em
    # DOIS conjuntos são dois públicos — fundir os números esconde qual deles
    # sustenta o teto. Só publica o split quando há 2+ conjuntos NOMEADOS do
    # mesmo anúncio na campanha (com 1 só, a linha criativo_campanha já é o
    # número exato e a duplicata seria ruído). Mesmo piso de N.
    grupos = {}
    for u in conjuntos_t:
        grupos.setdefault((u["campanha"], u["criativo"]), []).append(u)
    for (camp0, cria0), lst in grupos.items():
        nomeados = [u for u in lst if u["conjunto"]]
        if len(nomeados) < 2:
            continue
        for u in nomeados:
            if u["n"] < min_n_u:
                continue
            t = u["teto"]
            cr = u["criativo"]
            if cr.isdigit() and len(cr) >= 10 and cr in mapa_nome:
                cr = mapa_nome[cr]
            linhas.append([
                "criativo_conjunto_campanha" + sufixo,
                f"{cr} @ {u['conjunto']} @ {u['campanha']}",
                int(u["n"]),
                round(u["pct"], 1),
                barra,
                round(u["pct"] - (barra or 0), 1),
                (f"{t.valor:.2f}" if t.ok else None),
                (t.roas_alvo if t.ok else None),
                carimbo(t),
            ])

    # A MOEDA DO GERENCIADOR entra por último, sobre as linhas prontas do corte:
    # o teto continua CALCULADO por lead real (a régua honesta); aqui ele só é
    # traduzido pra unidade que o gestor compara na tela dele — com o cadastro
    # sem pesquisa valendo o crédito medido, não zero (Decisão 12).
    linhas = _moeda_do_gerenciador(linhas, _leads_do_gerenciador(conn, ini, fim),
                                   cad=_cadastros_da_janela(conn, ini, fim, mapa_nome),
                                   credito=credito)

    return linhas, {"sufixo": sufixo, "ini": ini, "fim": fim, "barra": barra,
                    "min_n": comp.get("min_n"), "escondidas": escondidas,
                    "linhas": len(linhas)}


def coletar(conn) -> tuple:
    """Devolve (linhas, resumos) com a ESCADA de janelas rolantes: histórico (90d),
    7 dias, 3 dias e hoje. Nenhuma delas é cortada pela virada de lançamento."""
    # O lançamento entra só como RÓTULO (`lf_name` no log e na comparação, que roda com
    # `pin_lf=False`): desde 19/08 nenhuma janela sai do calendário.
    lf, _cap_ini, _cap_fim = _janela_do_lancamento(conn)
    if not lf:
        raise SystemExit("sem lançamento no calendário: nada a publicar")
    run_id = _champion_run_id(conn)
    if not run_id:
        raise SystemExit("sem champion_run_id no ledger: a régua não existe")

    mapa_nome = _mapa_de_nomes(conn)
    # O crédito do não-respondente vem do payload da referência (medido toda
    # segunda pelo refresh, Decisão 12) e vale para TODOS os cortes da rodada.
    credito = _credito_da_referencia(conn)
    if credito:
        print(f"  crédito do não-respondente: {credito:.2f} "
              f"(cadastro sem pesquisa vale isso de um respondente)")
    hoje = _hoje_brt()
    linhas, resumos = [], []

    # HISTÓRICO — a janela mais larga, e a que sustenta o teto estável do anúncio.
    hist_ini = hoje - timedelta(days=DIAS_HISTORICO - 1)
    l, r = _um_corte(conn, lf, run_id, hist_ini, hoje, CORTE_HISTORICO, mapa_nome,
                     credito=credito)
    if not l:
        # Histórico vazio tem DUAS causas possíveis, e elas pedem reações opostas.
        # Vazio legítimo é o estado real quando nenhum anúncio chegou ao piso (era o
        # caso na estreia de lançamento, quando esta janela ainda era a do LF: 110
        # leads no dia inteiro em 18/08/2026) — morrer ali congelava o painel com o
        # "hoje" de ONTEM. Já um vazio com a janela CHEIA de leads é a comparação
        # quebrada, e aí publicar nada e morrer continua certo: a poda apagaria o
        # painel por causa de um bug nosso.
        # O critério que separa os dois é o próprio piso de publicação, aplicado no
        # grão em que ele vale: POR ANÚNCIO. (110 leads na janela repartidos em dez
        # anúncios ainda é vazio legítimo; um único anúncio com 100+ e comparação
        # vazia é bug.)
        maior = conn.run(
            "SELECT coalesce(max(n), 0) FROM ("
            "  SELECT count(*) AS n FROM public.registros_ml "
            "  WHERE created_at >= :a AND created_at < :b "
            "  GROUP BY utm_content) t",
            a=_fronteira_utc(hist_ini), b=_fronteira_utc(hoje, fim_do_dia=True))[0][0]
        if maior >= 100:
            raise SystemExit(f"a comparação voltou vazia no histórico, mas há anúncio "
                             f"com {maior} leads na janela: falha real, nada a publicar")
        print(f"  histórico vazio e LEGÍTIMO: o maior anúncio da janela tem "
              f"{maior} leads (piso 100). Os cortes curtos seguem e a poda tira do "
              f"painel o que sobrou da rodada anterior.")
    linhas += l
    resumos.append(r)

    # O tipo SEM SUFIXO ('criativo', 'campanha', ...) é o mesmo cálculo do histórico,
    # só reetiquetado. Reetiquetar e não recalcular é o ponto: se as duas contas
    # rodassem separadas, um dia divergiriam e ninguém saberia qual está certa — o
    # mesmo erro de escritor×leitor que já custou 9 dias de sinal neste projeto.
    # Ele existe para não quebrar quem já lê `tipo='criativo'` no painel deles; o nome
    # explícito é o `_historico`, e o dia em que a agência migrar, este some.
    linhas += [[x[0][:-len(CORTE_HISTORICO)] + CORTE_ACUMULADO] + list(x[1:]) for x in l]

    # SETE e TRÊS DIAS — rolantes, sem grampo de calendário (ver docstring).
    for dias, sufixo in ((DIAS_MEDIO, CORTE_MEDIO), (DIAS_CORTE, CORTE_CURTO)):
        l, r = _um_corte(conn, lf, run_id, hoje - timedelta(days=dias - 1), hoje,
                         sufixo, mapa_nome, credito=credito)
        linhas += l
        resumos.append(r)

    # corte HOJE: mesmo piso de N, janela = O DIA REAL de Brasília. Existe pra gerir o
    # que roda AGORA: entre lançamentos (cap_end ontem, planilha ainda sem o próximo,
    # como em 04 a 06/08/2026), "hoje" rotulando o último dia de captação enganaria o
    # gestor. (A justificativa original citava "117 leads invisíveis"; era artefato de
    # um query de debug que agrupava campanha truncada. O cenário entre lançamentos
    # acima é o motivo real e suficiente.)
    l, r = _um_corte(conn, lf, run_id, hoje, hoje, CORTE_HOJE, mapa_nome,
                     credito=credito)
    # Corte curto vazio NÃO é erro: acontece de verdade quando nenhum criativo alcançou o
    # piso de N nos últimos dias. O que não pode é passar em silêncio, então vai para o
    # resumo e sai no log.
    linhas += l
    resumos.append(r)
    # FUSÃO PONDERADA por (tipo, chave): dois anúncios com o mesmo nome após a
    # tradução (ex.: o mesmo vídeo em dois grupos do Google) viram UMA linha que
    # SOMA leads e pondera as métricas — antes ficava a de maior n e o resto sumia.
    def _funde(a, b):
        n1, n2 = int(a[2] or 0), int(b[2] or 0)
        tot = (n1 + n2) or 1
        def pond(x, y, casas=1):
            if x is None and y is None:
                return None
            if x is None or y is None:
                return y if x is None else x
            return round((float(x) * n1 + float(y) * n2) / tot, casas)
        teto = pond(a[6], b[6], 2)
        return [a[0], a[1], n1 + n2, pond(a[3], b[3]),
                a[4] if a[4] is not None else b[4], pond(a[5], b[5]),
                (f"{teto:.2f}" if teto is not None else None),
                a[7] if a[7] is not None else b[7],
                a[8] if (a[8] and not str(a[8]).startswith("sem_teto")) else b[8]]
    vistos = {}
    for x in linhas:
        k = (x[0], x[1])
        vistos[k] = _funde(vistos[k], x) if k in vistos else x
    # O teto secundário é o ÚLTIMO passo, depois da fusão: a fusão reconstrói a
    # linha em 9 posições, então derivar antes perderia a 10ª nos homônimos.
    linhas = _com_teto_secundario(list(vistos.values()))
    return linhas, {"lf": lf, "cortes": resumos}


def _hoje_brt():
    """Hoje em Brasília. Sai daqui e não de `date.today()` para não depender do fuso da
    máquina onde o job roda — o container do Cloud Run roda em UTC."""
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def gravar(linhas) -> int:
    """Upsert por `(tipo, chave)`, que é a chave única que eles criaram.

    `ON CONFLICT DO UPDATE` funciona aqui — ao contrário da `leads_inbound`, esta tabela TEM
    índice único, então o Postgres resolve sozinho e não preciso do apaga-e-insere.

    `atualizado_em = now()` no UPDATE de propósito: sem isso, uma linha que já existia
    manteria o carimbo antigo e a agência não teria como saber se a nota é de hoje ou de
    três dias atrás.
    """
    if not linhas:
        # Rodada sem linha nenhuma (estreia de lançamento, madrugada fraca): a poda
        # ainda PRECISA rodar, senão o painel segura os cortes curtos de ontem como
        # se fossem de agora — que é exatamente o que a poda existe pra impedir.
        # (E o `return 0` antigo nem chegava vivo no chamador, que desempacota um par.)
        dst = destino(porta=5432)
        try:
            dst.run("BEGIN")
            podadas = sum(_poda_sufixo(dst, [], s) for s in TODOS_OS_CORTES)
            dst.run("COMMIT")
            n = dst.run(f"SELECT count(*) FROM {TABELA_DESTINO}")[0][0]
            return n, podadas
        finally:
            dst.close()
    dst = destino(porta=5432)
    try:
        # A coluna secundária é contrato NOVO com a agência (Decisão 6: coluna é
        # combinada, não empurrada — e o ALTER é deles, somos só INSERT). Enquanto
        # ela não existir lá, publicamos o contrato antigo e avisamos; quando o
        # ALTER deles entrar, a rodada seguinte já a preenche sozinha.
        tem_secundaria = bool(dst.run(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name='scores_inbound' AND column_name=:c",
            c=COLUNA_SECUNDARIA))
        colunas = COLUNAS + [COLUNA_SECUNDARIA] if tem_secundaria else COLUNAS
        if not tem_secundaria:
            linhas = [x[:len(COLUNAS)] for x in linhas]
            print(f"  coluna {COLUNA_SECUNDARIA} ainda não existe no destino: "
                  f"publicando sem ela (pedir o ALTER à agência)")
        cols = ",".join(colunas)
        atualiza = ",".join(f"{k}=EXCLUDED.{k}" for k in colunas
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
        # ACUMULADO entra na faxina (Ramon, 18/08): linha de lançamento
        # anterior que não é republicada ficava congelada posando de atual
        # (as 3 linhas [G] do LF64 depois da virada). Preço aceito: manhã de
        # estreia mostra painel honesto e quase vazio, como os cortes curtos.
        podadas = sum(_poda_sufixo(dst, linhas, s) for s in TODOS_OS_CORTES)
        # Chave numérica publicada em rodada anterior vira lixo assim que a versão
        # nomeada existe: apaga toda linha de criativo cuja chave é só dígitos —
        # quem continua sem nome no mapa é re-upsertada nesta mesma rodada, então
        # só a órfã (traduzida agora) morre de fato.
        chaves_atuais = {x[1] for x in linhas}
        dst.run("DELETE FROM " + TABELA_DESTINO +
                " WHERE tipo LIKE 'criativo%' AND chave ~ '^[0-9]{10,}$'"
                " AND NOT (chave = ANY(:atuais))", atuais=list(chaves_atuais))
        dst.run("COMMIT")
        n = dst.run(f"SELECT count(*) FROM {TABELA_DESTINO}")[0][0]
        return n, podadas
    finally:
        dst.close()


def _poda_sufixo(dst, linhas, sufixo) -> int:
    """Apaga as linhas do corte curto que NÃO estão nesta rodada.

    POR QUE PODAR SÓ O CORTE CURTO
    ==============================
    O upsert por `(tipo, chave)` atualiza o que existe e insere o que é novo, mas nunca
    remove. Para o acumulado do lançamento isso é o certo: um criativo que parou de rodar
    continua tendo um total válido, e apagá-lo esconderia o histórico do lançamento.

    Para o corte de 3 dias é o oposto. Um criativo que saiu do ar há uma semana ficaria com
    a nota dos últimos 3 dias em que ele rodou, congelada, ao lado dos criativos vivos — e a
    agência leria isso como "este criativo está entregando isto AGORA". É a mesma classe de
    erro do índice que existia e não valia: a peça está lá, o significado dela não.

    O `atualizado_em` não resolve sozinho, porque exigiria que quem lê compare carimbos e
    descarte linha velha. Defesa que depende do leitor lembrar não é defesa.
    """
    tipos = [t + sufixo for t in list(TIPO.values())
             + ["criativo_campanha", "criativo_conjunto_campanha"]]
    # Chave por tipo EXATO: com sufixo vazio (acumulado), o endswith antigo
    # casava TODAS as linhas e a chave de um corte curto protegia linha velha
    # do acumulado com o mesmo nome.
    chaves = [x[1] for x in linhas if str(x[0]) in tipos]
    par = {f"t{i}": v for i, v in enumerate(tipos)}
    cond_tipo = "tipo IN (" + ",".join(f":t{i}" for i in range(len(tipos))) + ")"
    if not chaves:
        # Nenhuma linha no corte curto nesta rodada (nenhum criativo alcançou o piso). Então
        # TODAS as linhas antigas do corte curto estão obsoletas e saem. Publicar nada e
        # deixar as antigas no lugar seria a pior das saídas: dado velho passando por atual.
        dst.run(f"DELETE FROM {TABELA_DESTINO} WHERE {cond_tipo}", **par)
        return int(dst.row_count or 0)
    for i, v in enumerate(chaves):
        par[f"k{i}"] = v
    cond_chave = "chave NOT IN (" + ",".join(f":k{i}" for i in range(len(chaves))) + ")"
    dst.run(f"DELETE FROM {TABELA_DESTINO} WHERE {cond_tipo} AND {cond_chave}", **par)
    return int(dst.row_count or 0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="calcula e mostra, não escreve")
    ap.add_argument("--dump-parity", action="store_true",
                    help="imprime CADA linha calculada (tipo;chave;teto) e não escreve — "
                         "é o lado de cá do portão de paridade local×nuvem")
    a = ap.parse_args()

    from src.data.analytics_connection import open_analytics_connection

    conn = open_analytics_connection(timeout=1800)
    try:
        linhas, resumo = coletar(conn)
    finally:
        conn.close()

    print(f"lançamento {resumo['lf']}")
    for corte in resumo["cortes"]:
        rotulo = ROTULO.get(corte["sufixo"], corte["sufixo"])
        if corte.get("vazio"):
            print(f"  {rotulo} ({corte['ini']} a {corte['fim']}): VAZIO, "
                  f"nenhum criativo alcançou o piso de N")
            continue
        print(f"  {rotulo} ({corte['ini']} a {corte['fim']}): "
              f"{corte['linhas']} linhas · barra {corte['barra']}% · "
              f"N mínimo {corte['min_n']}")
        # O corte sai no log SEMPRE. Corte silencioso lido como "só existem estes criativos"
        # é pior que corte nenhum — mesma razão de a auditoria reportar a poda à parte.
        if corte["escondidas"]:
            print(f"    {corte['escondidas']} abaixo do N mínimo, NÃO publicados "
                  f"(agregado com pouco lead é score individual disfarçado)")

    por_tipo = {}
    for x in linhas:
        por_tipo[x[0]] = por_tipo.get(x[0], 0) + 1
    print(f"  {len(linhas)} linhas para publicar")
    for t, n in sorted(por_tipo.items()):
        print(f"    {t}: {n}")
    for x in sorted(linhas, key=lambda r: -(r[5] or -99))[:6]:
        print(f"    {x[0]:16s} {str(x[1])[:34]:36s} n={x[2]:>5} "
              f"top20={x[3]}% ref={x[4]}% delta={x[5]:+}pp "
              f"teto={'R$'+x[6] if x[6] else x[8]}")

    if a.dump_parity:
        print("PARITY-BEGIN")
        for x in sorted(linhas, key=lambda r: (r[0], str(r[1]))):
            print(f"P|{x[0]}|{x[1]}|{x[6] or ''}|{x[7] or ''}|{x[8] or ''}")
        print("PARITY-END")
        return 0
    if a.check:
        print("\n--check: nada gravado.")
        return 0
    total, podadas = gravar(linhas)
    if podadas:
        print(f"\n  {podadas} linha(s) do corte de {DIAS_CORTE} dias podadas "
              f"(criativo que saiu da janela: nota velha passando por atual)")

    # CORAÇÃO da rodada: a vigia do painel mede a idade DISTO, não do conteúdo.
    # Rodada sem linha nenhuma é legítima (estreia, madrugada) e não pode
    # parecer robô morto; robô morto é coração parado (>2h sem bater).
    conn2 = open_analytics_connection(timeout=60)
    try:
        conn2.run("CREATE TABLE IF NOT EXISTS job_heartbeats ("
                  "job text PRIMARY KEY, ultima_ok timestamptz NOT NULL, "
                  "detalhe text)")
        conn2.run("INSERT INTO job_heartbeats (job, ultima_ok, detalhe) "
                  "VALUES ('push-scores-zanelato', now(), :d) "
                  "ON CONFLICT (job) DO UPDATE SET ultima_ok=now(), "
                  "detalhe=EXCLUDED.detalhe",
                  d=f"{len(linhas)} linhas · {total} na tabela")
    finally:
        conn2.close()
    print(f"\nOK: {len(linhas)} publicadas · {total} linhas na tabela deles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
