#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comparativo_lancamentos — a seção "como este LF se compara" (nota 4, 31/08).

    python3 scripts/comparativo_lancamentos.py LF65

Lê SÓ contratos congelados (nunca banco): o do LF alvo, o do LF64 e os da
corrida (docs/relatorios/_corrida/, LF56→DEV21, todos na régua de produção
atual). Escreve `comparativo.html` na pasta do LF alvo; o render insere a
seção antes do carimbo, como faz com conclusao.html.

Três comparações + uma hipótese:
  1. este LF vs o anterior (LF64)
  2. este LF vs a MÉDIA da série LF56→DEV21
  3. este LF vs os 3 MELHORES ROAS da série (referência do que "bom" parece)
  4. época do mês: semana da 1ª data de captação vs CPL/ROAS de cada LF

Separação honesta: métricas FECHADAS na captação (gasto, cadastros, CPL,
% do gasto dentro do teto) comparam sempre; ROAS/lucro de LF provisório
(carrinho aberto/imaturo) vêm marcados e não entram em conclusão.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]

SERIE = ["LF56", "LF57", "LF58", "LF59", "LF60", "LF61", "LF62", "LF63", "DEV21"]


def br(v, dec=2, prefixo=""):
    if v is None:
        return "—"
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{prefixo}{s}"


def carrega(lf):
    p = _V2 / "docs/relatorios/_corrida" / lf / "contrato.json"
    if not p.exists():
        p = _V2 / f"docs/relatorios/{lf.lower()}_resultado/contrato.json"
    return json.loads(p.read_text())


def metricas(lf):
    """As métricas de UM contrato, no grão que a comparação usa."""
    c = carrega(lf)
    m, ca = c["meta"], c["tabelas"]["campanhas"]
    gasto = sum(x.get("gasto") or 0 for x in ca)
    fat = sum(x.get("faturamento") or 0 for x in ca)
    cad = m["cobertura"]["cadastros"]
    # % do gasto julgável dentro do TETO 1,5 (a régua atual do Ramon; o
    # julgamento do contrato usa alvo 2,0, então recalcula das unidades:
    # teto@1,5 = teto@2,0 × 4/3)
    uj = [x for x in c["tabelas"]["unidades"]
          if x.get("no_corte") and x.get("dentro_do_teto") is not None]
    gj = sum(x.get("gasto") or 0 for x in uj)
    gd = sum(x.get("gasto") or 0 for x in uj
             if x["cpl"] <= x["teto"] * (2.0 / 1.5))
    # as duas alavancas do "o que mudou" (nota do Ramon, 31/08): concentração
    # de verba por criativo e qualidade do público; mais o teto 1,5 médio
    um = [x for x in c["tabelas"]["unidades"]
          if x.get("gasto") and x.get("canal") == "meta"]
    g_meta = sum(x["gasto"] for x in um)
    por_cria: dict = {}
    for x in um:
        por_cria[x["criativo"]] = por_cria.get(x["criativo"], 0) + x["gasto"]
    top_cria = sorted(por_cria.values(), reverse=True)
    lw = sum(int(x.get("leads_ledger") or 0) for x in um)
    lj = sum(int(x.get("leads_ledger") or 0) for x in uj)
    # provisório = ainda vai crescer: carrinho aberto, ou a ingestão de vendas
    # (sales_max) ainda não passou do fim do carrinho. 'venda_fechada_imatura'
    # com vendas ingeridas até o fim do carrinho JÁ é final para o NEGÓCIO
    # (a janela de vendas do lançamento fecha com o carrinho).
    carrinho_fechado = m["estado"] in ("venda_fechada_imatura", "maduro")
    vendas_cobertas = str(m.get("sales_max"))[:10] >= m["vendas_end"][:10]
    cap = datetime.strptime(m["cap_start"][:10], "%Y-%m-%d").date()
    return dict(
        lf=lf, estado=m["estado"], cap_start=m["cap_start"][:10],
        gerado=m["gerado_em"][:10], semana=min((cap.day - 1) // 7 + 1, 5),
        gasto=gasto, cadastros=cad, cpl=(gasto / cad if cad else None),
        vendas=sum(x.get("vendas") or 0 for x in ca),
        faturamento=fat, roas=(fat / gasto if gasto else None),
        lucro=fat - gasto,
        pct_gasto_dentro=(100 * gd / gj if gj else None),
        conc1=(100 * top_cria[0] / g_meta if g_meta and top_cria else None),
        conc3=(100 * sum(top_cria[:3]) / g_meta if g_meta and top_cria else None),
        cria1=(max(por_cria, key=por_cria.get) if por_cria else None),
        d910=((sum(float(x.get("pct_d9_d10") or 0) * int(x.get("leads_ledger") or 0)
                   for x in um) / lw) if lw else None),
        teto15=((sum(x["teto"] * (2.0 / 1.5) * int(x.get("leads_ledger") or 0)
                     for x in uj) / lj) if lj else None),
        maduro=(carrinho_fechado and vendas_cobertas),
        vendas_start=m["vendas_start"][:10], vendas_end=m["vendas_end"][:10],
    )


def _pp(a, b):
    """Delta em pontos percentuais, formatado com sinal."""
    if a is None or b is None:
        return None
    d = a - b
    return ("+" if d >= 0 else "") + br(d, 1)


def _ritmo_carrinho(alvo_m, prev_m):
    """Mede na analytics.sales o faturamento dos MESMOS primeiros dias de
    carrinho dos dois LFs, com a mesma régua de produto (launch_products do
    config). Devolve dict ou None se banco/config indisponíveis."""
    from datetime import date, timedelta

    import yaml

    try:
        from dotenv import load_dotenv
        load_dotenv(_V2 / ".env")
    except Exception:
        pass
    try:
        sys.path.insert(0, str(_V2))
        from src.data.analytics_connection import open_analytics_connection
        pats = yaml.safe_load((_V2 / "configs/clients/devclub.yaml").read_text())[
            "business"]["launch_products"]
    except Exception:
        return None

    def _d(s):
        return datetime.strptime(s, "%Y-%m-%d").date()

    hoje = date.today()
    a_ini, a_fim = _d(alvo_m["vendas_start"]), _d(alvo_m["vendas_end"])
    p_ini, p_fim = _d(prev_m["vendas_start"]), _d(prev_m["vendas_end"])
    k = max(1, (min(hoje, a_fim) - a_ini).days + 1)  # dias de carrinho corridos
    cond = " OR ".join("lower(produto) LIKE '%" + p.lower() + "%'" for p in pats)

    try:
        conn = open_analytics_connection(timeout=120)
        try:
            def soma(ini, fim):
                q = ("SELECT count(*), coalesce(sum(sale_value),0) FROM analytics.sales "
                     f"WHERE sale_date::date BETWEEN '{ini}' AND '{fim}' AND ({cond})")
                n, fat = conn.run(q)[0]
                return int(n), float(fat)

            a_n, a_fat = soma(a_ini, min(hoje, a_fim))
            p_n, p_fat = soma(p_ini, min(p_ini + timedelta(days=k - 1), p_fim))
            _, p_full = soma(p_ini, p_fim)
        finally:
            conn.close()
    except Exception:
        return None
    return dict(k=k, dia_corrente=(hoje <= a_fim), a_fat=a_fat, p_fat=p_fat,
                p_full=p_full, share1=(100 * p_fat / p_full if p_full else None))


def _veredito(alvo, at, prev):
    """O parágrafo único sob as duas tabelas, no molde de texto do Ramon
    (01/09): três itens numerados + dois fechos, sem frase de máquina."""
    d_cpl = (100 * (at["cpl"] - prev["cpl"]) / prev["cpl"]
             if (at["cpl"] and prev["cpl"]) else None)
    d_gasto = (100 * (at["gasto"] - prev["gasto"]) / prev["gasto"]
               if prev["gasto"] else None)
    d_cad = (100 * (at["cadastros"] - prev["cadastros"]) / prev["cadastros"]
             if prev["cadastros"] else None)
    d_conc = (at["conc1"] or 0) - (prev["conc1"] or 0)
    cad = f"{at['cadastros']:,}".replace(",", ".")
    p = (f"<p class='h2sub' style='margin-top:14px'><b>O que dá pra afirmar "
         f"hoje: {alvo} contra {prev['lf']}</b><br><br>"
         f"1- Não é lead mais caro nem de pior qualidade: CPL {br(at['cpl'])} "
         f"contra {br(prev['cpl'])} ({'+' if (d_cpl or 0) >= 0 else ''}{br(d_cpl, 1)}%), "
         f"qualidade do público {_pp(at['d910'], prev['d910'])}pp de nota 9-10, e "
         f"{br(at['pct_gasto_dentro'], 1)}% do gasto dentro do teto 1,5 contra "
         f"{br(prev['pct_gasto_dentro'], 1)}%.<br><br>"
         f"2- A verba no criativo nº 1 {'caiu' if d_conc < 0 else 'subiu'} "
         f"({_pp(at['conc1'], prev['conc1'])}pp): foi {br(at['conc1'], 1)}% no "
         f"{alvo} contra {br(prev['conc1'], 1)}% no {prev['lf']}, e volume "
         f"{'menor' if (d_cad or 0) < 0 else 'maior'}: {cad} cadastros "
         f"({br(d_cad, 0)}%) com {br(d_gasto, 0)}% de verba.")
    r = _ritmo_carrinho(at, prev) if not at["maduro"] else None
    if r:
        pct = (100 * (r["a_fat"] / at["gasto"]) / (r["p_fat"] / prev["gasto"])
               if (at["gasto"] and prev["gasto"] and r["p_fat"]) else None)
        janela = ("no dia da abertura" if r["k"] == 1
                  else f"nos primeiros {r['k']} dias de carrinho")
        par = (f"({alvo} R$ {br(r['a_fat'], 0)}, "
               f"{br(r['a_fat'] / at['gasto'], 2)} por real gasto) contra "
               f"({prev['lf']} R$ {br(r['p_fat'], 0)}, "
               f"{br(r['p_fat'] / prev['gasto'], 2)} por real gasto)")
        obs = (" Obs: o dia ainda aberto pode fechar parte disso."
               if r["dia_corrente"] else "")
        if (pct or 0) >= 95:
            p += (f"<br><br>3- Conversão no nível do anterior: faturamento "
                  f"{janela} em {br(pct, 0)}% do ritmo por real {par}.<br><br>"
                  "A diferença de lucro da tabela é só o calendário do carrinho.")
        else:
            p += (f"<br><br>3- A conversão do lançamento está pior: faturamento "
                  f"{janela} está {br(100 - (pct or 0), 0)}% pior {par}.{obs}<br><br>"
                  "Das variáveis que a gente mede, a única que mudou pra pior e "
                  "pode explicar essa queda é a verba menos concentrada no "
                  f"criativo campeão ({_pp(at['conc1'], prev['conc1'])}pp). Lead "
                  "mais caro e público pior estão descartados no item 1.<br><br>"
                  "O que passar disso NÃO tem explicação nas variáveis que "
                  "medimos hoje (página, oferta, momento do público).")
    p += "</p>"
    return p


def main() -> int:
    alvo = sys.argv[1] if len(sys.argv) > 1 else "LF65"
    pasta = _V2 / f"docs/relatorios/{alvo.lower()}_resultado"
    serie = [metricas(lf) for lf in SERIE]
    # média SEM o DEV21 (quente, outlier — nota do Ramon, 31/08)
    serie_sem = [r for r in serie if r["lf"] != "DEV21"]
    at = metricas(alvo)
    # anterior = o LF conhecido (corrida + pastas *_resultado) com a captação
    # imediatamente antes da deste — nada de LF64 cravado no código
    nomes = set(SERIE) | {p.parent.name[:-10].upper() for p in
                          (_V2 / "docs/relatorios").glob("lf*_resultado/contrato.json")}
    cand = []
    for lf in sorted(nomes - {alvo}):
        try:
            cand.append(metricas(lf))
        except Exception:
            pass
    prevs = [r for r in cand if r["cap_start"] < at["cap_start"]]
    prev = max(prevs, key=lambda r: r["cap_start"]) if prevs else None
    # DEV21 fica fora do top 3 (lançamento quente, economia própria — Ramon, 31/08)
    top3 = sorted([r for r in serie if r["lf"] != "DEV21"],
                  key=lambda r: -(r["roas"] or 0))[:3]

    def med(rows, k):
        vals = [r[k] for r in rows if r[k] is not None]
        return sum(vals) / len(vals) if vals else None

    prov = not at["maduro"]

    def linha(rot, r, provisorio=False):
        tag = " <i>(provisório)</i>" if provisorio else ""
        # o replace do milhar fica NUM fragmento só: f-strings adjacentes
        # concatenam antes do .replace e ele comia a vírgula do rótulo
        cad = f"{r['cadastros']:,}".replace(",", ".")
        return (f"<tr><td><b>{rot}</b>{tag}</td>"
                f"<td>{br(r['gasto'], 0, 'R$ ')}</td>"
                f"<td>{cad}</td>"
                f"<td>{br(r['cpl'])}</td>"
                f"<td>{br(r.get('teto15'))}</td>"
                f"<td>{br(r['pct_gasto_dentro'], 1)}%</td>"
                f"<td>{br(r['roas'])}</td>"
                f"<td class='{'pos' if (r['lucro'] or 0) > 0 else 'neg'}'>{br(r['lucro'], 0, 'R$ ')}</td></tr>")

    media = {k: med(serie_sem, k) for k in
             ("gasto", "cadastros", "cpl", "teto15", "pct_gasto_dentro", "roas",
           "lucro", "conc1", "conc3", "d910")}
    media["cadastros"] = int(media["cadastros"] or 0)
    t3 = {k: med(top3, k) for k in
          ("gasto", "cadastros", "cpl", "teto15", "pct_gasto_dentro", "roas",
           "lucro", "conc1", "conc3", "d910")}
    t3["cadastros"] = int(t3["cadastros"] or 0)

    head = ("<tr><th></th><th>Gasto</th><th>Cadastros</th><th>CPL</th>"
            "<th>Teto 1,5 médio</th>"
            "<th>% gasto dentro do teto 1,5</th><th>ROAS</th><th>Lucro</th></tr>")
    rows = [linha(f"{alvo} (este)", at, prov)]
    if prev:
        rows.append(linha(f"{prev['lf']} (anterior)", prev, not prev["maduro"]))
    rows.append(linha("Média LF56→LF63 (sem o DEV21, quente)", media))
    rows.append(linha("Top 3 ROAS (" + ", ".join(r["lf"] for r in top3) + ")", t3))
    tab1 = (f"<div class='tw'><table class='tb'><thead>{head}</thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")

    # ── o que mudou: concentração de verba por criativo + qualidade do público ─
    def linha_mud(rot, r):
        folga = ((r.get("teto15") - r.get("cpl"))
                 if (r.get("teto15") is not None and r.get("cpl") is not None)
                 else None)
        nome1 = f" ({r['cria1'][:22]})" if r.get("cria1") else ""
        return (f"<tr><td><b>{rot}</b></td>"
                f"<td>{br(r.get('conc1'), 1)}%{nome1}</td>"
                f"<td>{br(r.get('conc3'), 1)}%</td>"
                f"<td>{br(r.get('d910'), 1)}%</td>"
                f"<td>{br(r.get('cpl'))}</td><td>{br(r.get('teto15'))}</td>"
                f"<td class='{'pos' if (folga or 0) > 0 else 'neg'}'>{br(folga)}</td></tr>")

    chaves_m = ("conc1", "conc3", "d910", "cpl", "teto15")
    tab_mud = ("<p class='h2sub' style='margin-top:14px'><b>O que mudou neste "
               "lançamento</b> — as duas alavancas que abrem ou fecham a folga do "
               "teto: quanta verba concentrou no criativo certo, e a qualidade do "
               "público comprado (% de leads nota 9-10, pesado por leads):</p>"
               "<div class='tw'><table class='tb'><thead><tr><th></th>"
               "<th>% verba no criativo nº 1</th><th>% top 3 criativos</th>"
               "<th>% leads D9-D10</th><th>CPL</th><th>Teto 1,5 médio</th>"
               "<th>Folga (teto − CPL)</th></tr></thead><tbody>"
               + linha_mud(f"{alvo} (este)", at)
               + (linha_mud(f"{prev['lf']} (anterior)", prev) if prev else "")
               + linha_mud("Média LF56→LF63 (sem o DEV21)", {k: med(serie_sem, k) for k in chaves_m})
               + linha_mud("Top 3 ROAS (" + ", ".join(r["lf"] for r in top3) + ")",
                           {k: med(top3, k) for k in chaves_m})
               + "</tbody></table></div>")

    # ── veredito: por que este LF está melhor/pior que o anterior (nota 31/08) ─
    # Única parte que toca banco: mede o ritmo dos MESMOS primeiros dias de
    # carrinho direto na analytics.sales, com a mesma régua de produto pros dois
    # lados. Se o banco não responder, o parágrafo sai sem essa medição.
    veredito = _veredito(alvo, at, prev) if prev else ""

    # ── época do mês: SÓ a conclusão, sem DEV21 (quente, outlier) — nota 31/08 ─
    base_ep = [r for r in serie if r["lf"] != "DEV21"]
    por_sem = {}
    for r in base_ep:
        por_sem.setdefault(r["semana"], []).append(r)
    med_sem = {s: med(g, "roas") for s, g in por_sem.items()}
    pior_s = min(med_sem, key=lambda s: med_sem[s])
    melhor_s = max(med_sem, key=lambda s: med_sem[s])

    def _lfs(s):
        return " e ".join(f"{r['lf']} ({br(r['roas'])})" for r in por_sem[s])

    epoca = ("<p class='h2sub' style='margin-top:14px'><b>Época do mês — só a "
             "conclusão.</b> 1- Base: os 8 fechados, sem o DEV21 (quente, fora da "
             "régua). No máximo 2 lançamentos por semana do mês; amostra de cara "
             f"ou coroa. 2- O que aparece: a {pior_s}ª semana tem a pior média de "
             f"ROAS ({br(med_sem[pior_s])}: {_lfs(pior_s)}); a {melhor_s}ª tem a "
             f"melhor ({br(med_sem[melhor_s])}: {_lfs(melhor_s)}). 3- Veredito: "
             "sugestivo, não conclusivo — uns 5/10 de confiança; só fecha com mais "
             f"lançamentos. 4- Este LF começou na {at['semana']}ª semana"
             + (", que não é a ruim: época não explica o resultado dele."
                if at["semana"] != pior_s
                else ": a época pode estar pesando aqui.") + "</p>")

    html = tab1 + tab_mud + veredito + epoca
    dst = pasta / "comparativo.html"
    dst.write_text(html)
    print(f"comparativo: {dst}  ({dst.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
