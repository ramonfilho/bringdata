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

OS DOIS CORTES: ACUMULADO E TRÊS DIAS
=====================================
A nota acumulada do lançamento responde "este criativo prestou?". Ela é a certa para decidir
se um criativo entra no próximo lançamento, e é ruim para decidir hoje: depois de alguns dias
ela para de se mexer, porque cada dia novo é uma fração pequena do total. Um criativo pode
virar de ruim para bom e a nota acumulada leva uma semana para reconhecer.

O corte de TRÊS DIAS existe para isso. Três e não um: um dia de criativo raramente alcança
os 100 leads do piso, então o corte diário publicaria pouca linha ou nenhuma. Três dias é a
menor janela que ainda passa do piso e ainda se move.

Eles convivem na MESMA tabela sem pedir nada à agência, porque a chave única de lá é
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
    tipo                 'criativo' / 'campanha'              = acumulado do lançamento
                         'criativo_3dias' / 'campanha_3dias'  = últimos 3 dias
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

# Tamanho do corte curto, em dias. Três é o menor que ainda passa do piso de N=100 com o
# volume que um criativo faz por dia neste cliente (60 a 100 leads/dia nos que rodam de
# verdade). Baixar para 1 esvaziaria o corte; subir para 7 o deixaria tão inerte quanto o
# acumulado, que é justamente o problema que ele resolve.
DIAS_CORTE = 3

# Sufixo que separa os dois cortes na coluna `tipo` da tabela deles. Vazio = acumulado do
# lançamento. Mudar estes valores é mudar o CONTRATO com o painel da agência.
CORTE_ACUMULADO = ""
CORTE_CURTO = f"_{DIAS_CORTE}dias"
# Corte HOJE (aprovado 16/08): a visão mais fresca possível que ainda é honesta —
# só publica quem cruzou o piso de N no PRÓPRIO dia; em dia fraco a lista vem curta.
CORTE_HOJE = "_hoje"

# `atualizado_em` fica de fora: tem default `now()` no lado deles, e é o carimbo de quando
# ELES receberam. Mandar valor sobrescreveria a informação deles com a nossa.
COLUNAS = ["tipo", "chave", "leads", "pct_top20", "referencia_pct", "delta_vs_referencia",
           "teto_cpl", "teto_roas_alvo", "teto_referencia"]

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


def _um_corte(conn, lf, run_id, ini, fim, sufixo: str, mapa_nome: dict) -> tuple:
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
        # `pin_lf=False` no corte curto: a janela de 3 dias conta quem entrou NELA, sem
        # amarrar no lançamento. No acumulado o default (amarrado) é o certo, porque ali a
        # pergunta é sobre o lançamento inteiro. É a mesma distinção que o relatório faz
        # entre a visão do dia e a visão do LF.
        **({"pin_lf": False} if sufixo else {}),
    )
    if not comp:
        return [], {"vazio": True, "sufixo": sufixo, "ini": ini, "fim": fim}

    # Teto por chave (Decisão 9): calculado pela MESMA janela do corte, pelo módulo
    # de produção (teto_por_chave), e só traduzido aqui. Linha sem teto leva o
    # motivo no carimbo em vez de célula muda.
    from src.monitoring.teto_por_chave import tetos_completos, carimbo
    tetos, unidades_t = tetos_completos(
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
    for u in unidades_t:
        if u["n"] < min_n_u:
            continue
        t = u["teto"]
        cr = u["criativo"]
        if cr.isdigit() and len(cr) >= 10 and cr in mapa_nome:
            cr = mapa_nome[cr]
        linhas.append([
            "criativo_campanha" + sufixo,
            f"{cr} @ {u['campanha']}",
            int(u["n"]),
            round(u["pct"], 1),
            barra,
            round(u["pct"] - (barra or 0), 1),
            (f"{t.valor:.2f}" if t.ok else None),
            (t.roas_alvo if t.ok else None),
            carimbo(t),
        ])

    return linhas, {"sufixo": sufixo, "ini": ini, "fim": fim, "barra": barra,
                    "min_n": comp.get("min_n"), "escondidas": escondidas,
                    "linhas": len(linhas)}


def coletar(conn) -> tuple:
    """Devolve (linhas, resumos) com os DOIS cortes: acumulado do LF e últimos N dias."""
    lf, ini, fim = _janela_do_lancamento(conn)
    if not lf:
        raise SystemExit("sem lançamento no calendário: nada a publicar")
    run_id = _champion_run_id(conn)
    if not run_id:
        raise SystemExit("sem champion_run_id no ledger: a régua não existe")

    mapa_nome = _mapa_de_nomes(conn)
    linhas, resumos = [], []
    l, r = _um_corte(conn, lf, run_id, ini, fim, CORTE_ACUMULADO, mapa_nome)
    if not l:
        # O acumulado vazio é falha de verdade: significa que a comparação não achou lead
        # nenhum no lançamento. Morrer aqui é melhor que publicar só o corte curto e a
        # agência concluir que o lançamento inteiro sumiu.
        raise SystemExit(f"a comparação voltou vazia para {lf}: nada a publicar")
    linhas += l
    resumos.append(r)

    # O corte curto é GRAMPEADO no início do lançamento. Sem isso, nos primeiros dias ele
    # varreria dias do lançamento ANTERIOR e compararia criativo que rodou em outro contexto
    # — o mesmo motivo pelo qual a janela do acumulado sai do calendário e não de `now() - N`.
    hoje = fim if fim < _hoje_brt() else _hoje_brt()
    curto_ini = max(ini, hoje - timedelta(days=DIAS_CORTE - 1))
    l, r = _um_corte(conn, lf, run_id, curto_ini, hoje, CORTE_CURTO, mapa_nome)
    linhas += l
    resumos.append(r)
    # corte HOJE: mesmo piso de N, janela = O DIA REAL de Brasília, SEM o grampo do
    # calendário. Os outros cortes se ancoram no lançamento; este existe pra gerir
    # o que roda AGORA — entre lançamentos (cap_end ontem, planilha ainda sem o
    # próximo), "hoje" rotulando ontem enganaria o gestor (pego em 16/08: 117 leads
    # do dia invisíveis porque o corte olhava 15/08).
    hoje_real = _hoje_brt()
    l, r = _um_corte(conn, lf, run_id, hoje_real, hoje_real, CORTE_HOJE, mapa_nome)
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
    linhas = list(vistos.values())
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
        podadas = (_poda_sufixo(dst, linhas, CORTE_CURTO)
                   + _poda_sufixo(dst, linhas, CORTE_HOJE))
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
    chaves = [x[1] for x in linhas if str(x[0]).endswith(sufixo)]
    tipos = [t + sufixo for t in list(TIPO.values()) + ["criativo_campanha"]]
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
        rotulo = ("acumulado do lançamento" if not corte["sufixo"]
                  else ("hoje" if corte["sufixo"] == CORTE_HOJE
                        else f"últimos {DIAS_CORTE} dias"))
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
    print(f"\nOK: {len(linhas)} publicadas · {total} linhas na tabela deles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
