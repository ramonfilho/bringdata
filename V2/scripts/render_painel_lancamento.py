#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_painel_lancamento — contrato.json → painel HTML (as telas do relatório).

    python3 scripts/render_painel_lancamento.py docs/relatorios/lf64_resultado

Lê SOMENTE o contrato congelado (nunca banco): republicar o painel é re-rodar
este script; preencher as vendas é re-rodar o relatorio_lancamento e DEPOIS
este script — o mesmo par de comandos para qualquer lançamento.

A base visual é o template da skill painel-dados (já com os 4 consertos de
runtime e o CSS de tabela do relatório executivo). Este script troca só o SPEC.
Célula sem medida imprime "—" (aguardando), nunca 0.
"""
import json
import re
import sys
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
TEMPLATE = _V2 / ".claude" / "skills" / "painel-dados" / "template.html"


def br(v, dec=2, prefixo=""):
    """Número no formato pt-BR; None/ausente vira o traço de 'aguardando'."""
    if v is None:
        return "—"
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{prefixo}{s}"


def pct(v, dec=1):
    return "—" if v is None else f"{v:.{dec}f}%".replace(".", ",")


def _tab(headers, rows, aggr=None):
    """Tabela no CSS .tb do relatório executivo (scroll horizontal próprio)."""
    th = "".join(f"<th>{h}</th>" for h in headers)
    def _tr(cells, cls=""):
        tds = "".join(
            f"<td class='{c[1]}'>{c[0]}</td>" if isinstance(c, tuple) else f"<td>{c}</td>"
            for c in cells)
        return f"<tr class='{cls}'>{tds}</tr>"
    body = "".join(_tr(r) for r in rows)
    ag = _tr(aggr, "ag") if aggr else ""
    return (f"<div class='tw'><table class='tb'><thead><tr>{th}</tr></thead>"
            f"<tbody>{body}{ag}</tbody></table></div>")


def main() -> int:
    pasta = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/relatorios/lf64_resultado")
    c = json.loads((pasta / "contrato.json").read_text())
    m, cob, j = c["meta"], c["meta"]["cobertura"], c["julgamento"]
    ca, u, ct = (c["tabelas"]["campanhas"], c["tabelas"]["unidades"],
                 c["tabelas"]["criativos_por_tipo"])
    lf = c["lf"]
    tem_venda = bool(m["tem_venda"])
    provisorio = ("" if m["estado"] == "maduro"
                  else " · <b>PROVISÓRIO</b>" if tem_venda else "")

    tot_gasto = sum(x["gasto"] or 0 for x in ca)
    tot_cad = cob["cadastros"]
    cpl_geral = tot_gasto / tot_cad if tot_cad else None

    # ── agregado por modelo (a base da tela 1) ───────────────────────────────
    mods = {}
    for x in ca:
        d = mods.setdefault(x["modelo"], dict(g=0.0, l=0, n=0, v=None, f=None, lu=None))
        d["g"] += x["gasto"] or 0
        d["l"] += x["leads"] or 0
        d["n"] += 1
        if tem_venda:
            for k, kk in (("v", "vendas"), ("f", "faturamento"), ("lu", "lucro")):
                if x.get(kk) is not None:
                    d[k] = (d[k] or 0) + x[kk]
    ordem = sorted(mods.items(), key=lambda kv: -kv[1]["g"])

    linhas_mod = []
    for nome, d in ordem:
        cpl = d["g"] / d["l"] if d["l"] else None
        roas = (d["f"] / d["g"]) if (d["f"] is not None and d["g"]) else None
        linhas_mod.append([f"<b>{nome}</b>", d["n"], br(d["g"], 2, "R$ "), f"{d['l']:,}".replace(",", "."),
                           br(cpl, 2, "R$ "), br(d["v"], 0), br(d["f"], 2, "R$ "),
                           br(roas, 2),
                           (br(d["lu"], 2, "R$ "), "pos" if (d["lu"] or 0) > 0 else "neg") if d["lu"] is not None else "—"])
    linhas_mod.append(["<b>TOTAL</b>", sum(d["n"] for _, d in ordem), br(tot_gasto, 2, "R$ "),
                       f"{sum(d['l'] for _, d in ordem):,}".replace(",", "."), br(cpl_geral, 2, "R$ "),
                       "—" if not tem_venda else br(sum(d["v"] or 0 for _, d in ordem), 0), "—", "—", "—"])
    tab_modelo = _tab(["Tipo de campanha", "Camp.", "Gasto", "Cadastros", "CPL",
                       "Vendas", "Faturamento", "ROAS", "Lucro"],
                      linhas_mod[:-1], linhas_mod[-1])

    # ── tela 2: campanha a campanha (top por gasto) ──────────────────────────
    top_camp = sorted([x for x in ca if x.get("gasto")], key=lambda x: -x["gasto"])[:15]
    linhas_c = []
    for x in top_camp:
        linhas_c.append([x["campanha"][:46], x["modelo"], br(x["gasto"], 2, "R$ "),
                         f"{x['leads']:,}".replace(",", "."), br(x["cpl"], 2, "R$ "),
                         br(x.get("vendas"), 0), br(x.get("faturamento"), 2, "R$ "),
                         br(x.get("roas"), 2), br(x.get("lucro"), 2, "R$ ")])
    tab_camp = _tab(["Campanha", "Tipo", "Gasto", "Cadastros", "CPL", "Vendas",
                     "Faturamento", "ROAS", "Lucro"], linhas_c)

    # ── tela 3: criativos por tipo (verba + qualidade) ───────────────────────
    by_mod = {}
    for x in ct:
        if x.get("gasto"):
            by_mod.setdefault(x["modelo"], []).append(x)
    blocos = []
    for nome, _ in ordem:
        xs = sorted(by_mod.get(nome, []), key=lambda x: -x["gasto"])[:5]
        if not xs:
            continue
        rows = [[x["criativo"][:40], br(x["gasto"], 2, "R$ "),
                 f"{int(x['leads_ledger']):,}".replace(",", "."), br(x["cpl"], 2, "R$ "),
                 pct(x.get("pct_d9_d10")),
                 br(x.get("lift_criativo"), 2) if x.get("lift_criativo") else "<span class='ic'>estreante</span>",
                 br(x.get("conversao") and 100 * x["conversao"], 2) + ("%" if x.get("conversao") is not None else "")]
                for x in xs]
        blocos.append(f"<h4 class='bl'>{nome}<span>top 5 por verba</span></h4>"
                      + _tab(["Criativo", "Gasto", "Leads", "CPL", "% notas 9-10",
                              "Nota histórica (lift)", "Conversão"], rows))
    tela3 = "".join(blocos)

    # ── tela 4: teto (dentro vs acima) ───────────────────────────────────────
    modo = "MEDIDO" if tem_venda else "PREVISÃO — o julgamento fecha quando as vendas caírem"
    rows_j = []
    for rot, lado in (("Respeitaram o teto", "dentro"), ("Estouraram o teto", "acima")):
        b = j[lado]
        rows_j.append([f"<b>{rot}</b>", b["n"], br(b["gasto"], 2, "R$ "),
                       f"{b['leads']:,}".replace(",", "."), br(b.get("vendas"), 0),
                       br(b.get("roas_ponderado"), 2), br(b.get("lucro"), 2, "R$ "),
                       br(b.get("bateu_meta"), 0), br(b.get("lucro_acima_1000"), 0),
                       br(b.get("roas_positivo"), 0)])
    tab_teto = _tab(["", "Unidades", "Gasto", "Leads", "Vendas", "ROAS",
                     "Lucro", "Bateu a meta*", "Lucro > R$ 1.000", "Deu lucro"], rows_j)

    # ── telas 5 e 6: menor CPL e ranking ─────────────────────────────────────
    um = [x for x in u if x.get("cpl") is not None and (x.get("leads_ledger") or 0) >= 100]
    menor_cpl = sorted(um, key=lambda x: x["cpl"])[:10]
    rows5 = [[x["criativo"][:38], x["campanha"][:30], br(x["cpl"], 2, "R$ "),
              br(x["teto"], 2, "R$ "),
              (br(x["folga"], 2, "R$ "), "pos" if (x["folga"] or 0) >= 0 else "neg"),
              f"{x['leads_ledger']:,}".replace(",", "."), pct(x.get("pct_d9_d10"))]
             for x in menor_cpl]
    tab_cpl = _tab(["Criativo", "Campanha", "CPL", "Teto", "Folga", "Leads",
                    "% notas 9-10"], rows5)

    chave_rank = "lucro" if tem_venda else "folga"
    rank = sorted([x for x in um if x.get(chave_rank) is not None],
                  key=lambda x: -(x[chave_rank]))[:12]
    # Coluna "Folga" REMOVIDA temporariamente do ranking (pedido do Ramon,
    # 24/08/2026); a ordenação provisória sem venda continua sendo por folga.
    rows6 = [[x["criativo"][:38], x["campanha"][:30], br(x.get("gasto"), 2, "R$ "),
              br(x.get("cpl"), 2, "R$ "),
              br(x.get("faturamento"), 2, "R$ "),
              (br(x.get("lucro"), 2, "R$ "), "pos" if (x.get("lucro") or 0) > 0 else "neg")
              if x.get("lucro") is not None else "—"]
             for x in rank]
    tab_rank = _tab(["Criativo", "Campanha", "Gasto", "CPL", "Faturamento", "Lucro"], rows6)

    # ── SPEC ─────────────────────────────────────────────────────────────────
    aguardando = ("" if tem_venda else
                  "<p><i>Carrinho aberto em " + m["vendas_start"][8:10] + "/" + m["vendas_start"][5:7]
                  + ". As colunas de vendas, faturamento, ROAS e lucro preenchem sozinhas "
                  "na próxima rodada deste mesmo relatório, quando as vendas caírem — traço (—) "
                  "significa \"ainda não medido\", nunca zero.</i></p>")
    spec = {
        "eyebrow": f"DevClub · Lançamento {lf} · captação {m['cap_start'][8:10]}/{m['cap_start'][5:7]}"
                   f" a {m['cap_end'][8:10]}/{m['cap_end'][5:7]} · carrinho {m['vendas_start'][8:10]}/"
                   f"{m['vendas_start'][5:7]} a {m['vendas_end'][8:10]}/{m['vendas_end'][5:7]}",
        "title": f"Painel do {lf}",
        "subtitle": f"O mesmo relatório do DEV21, agora por máquina: um comando gera, o mesmo comando "
                    f"atualiza. Estado: <b>{m['estado'].replace('_', ' ')}</b>{provisorio}.",
        "source": f"Contrato congelado em {m['gerado_em'][:16]} · referência {m['referencia_id']} · "
                  f"régua {m['ruler_run_id'][:8]} (abr_28) · {br(100 * (cob['pct_gasto_casado'] or 0), 1)}% "
                  f"do gasto Meta casado por anúncio",
        "tiles": [
            {"color": "c1", "label": "Investimento total", "value": br(tot_gasto, 0, "R$ "),
             "note": f"Meta com imposto (×{br(m['meta_gross_up'], 2)}) + Google."},
            {"color": "accent", "label": "Cadastros", "value": f"{tot_cad:,}".replace(",", "."),
             "note": f"CPL geral {br(cpl_geral, 2, 'R$ ')} por cadastro."},
            {"color": "c2", "label": "Vendas",
             "value": (br(sum(x.get('vendas') or 0 for x in ca), 0) if tem_venda else "aguardando"),
             "note": ("Somatório das campanhas casadas." if tem_venda
                      else "Carrinho abriu hoje; preenche na próxima rodada.")},
        ],
        "sections": [
            {"title": "1 · Onde o dinheiro foi — por tipo de campanha",
             "sub": "Tipo = o MODELO que escolhe o público da campanha (identidade estável, "
                    "mesmo com os nomes novos da equipe de tráfego).",
             "html": tab_modelo + aguardando},
            {"title": "2 · Campanha a campanha (top 15 por gasto)",
             "sub": "As mesmas colunas do debriefing: gasto, cadastros, CPL, vendas, ROAS e lucro.",
             "html": tab_camp},
            {"title": "3 · Criativos: quem levou a verba em cada tipo de campanha",
             "sub": "O mesmo criativo muda de qualidade conforme o público que a campanha compra — "
                    "\"% notas 9-10\" é a fração de leads no topo da régua do modelo.",
             "html": tela3},
            {"title": f"4 · Teto de CPL — {modo}",
             "sub": "Unidade = criativo×campanha com ≥100 leads e ≥R$ 300 de gasto. "
                    "*Meta = ROAS 2,0 com tolerância de 2% (um 1,97 conta).",
             "html": tab_teto},
            {"title": "5 · Os criativos de menor custo por lead",
             "sub": "Barato não é sinônimo de dentro do teto: a folga compara o CPL com o teto "
                    "DAQUELA unidade (folga negativa = pagando acima do que a qualidade sustenta).",
             "html": tab_cpl},
            {"title": ("6 · Ranking por lucro" if tem_venda else
                       "6 · Ranking — por folga, enquanto não há lucro para ordenar"),
             "sub": ("Do maior para o menor lucro." if tem_venda else
                     "Sem venda ingerida a coluna de lucro fica vazia; a ordem provisória é a folga "
                     "(quem mais respeita o teto). A rodada com vendas reordena por lucro."),
             "html": tab_rank},
            {"title": "7 · Régua e cobertura (o carimbo desta rodada)",
             "html": ("<ul>"
                      f"<li><b>Âncora do teto:</b> a referência que a produção serve hoje "
                      f"({m['referencia_id']}), fator de rastreamento {br(m['fator_rastreamento'], 4)} "
                      f"({m['fator_procedencia']}), crédito do não-respondente {br(m['credito_nao_respondente'], 4)}. "
                      f"O payload inteiro está congelado no contrato — o número não muda se a tabela viva for reescrita.</li>"
                      f"<li><b>Histórico de criativo point-in-time:</b> só lançamentos fechados antes de "
                      f"{m['historico_corte'][8:10]}/{m['historico_corte'][5:7]} ({m['historico_criativos']} criativos) — "
                      f"o lançamento anterior não contamina o teto deste.</li>"
                      f"<li><b>Cobertura:</b> {br(100 * (cob['pct_gasto_casado'] or 0), 1)}% do gasto Meta casado por anúncio; "
                      f"{cob['leads_sem_criativo']} cadastros sem criativo e {cob['leads_criativo_macro']} com macro quebrada "
                      f"ficam em baldes nomeados; {cob['ids_nao_resolvidos']} ids sem nome.</li>"
                      f"<li><b>Boleto</b> conta {br(100 * m['boleto_haircut'], 0)}% no faturamento; gasto Meta com imposto "
                      f"×{br(m['meta_gross_up'], 2)}; devolvidos: {m['devolvidos_n']} (debriefing ainda não existe).</li>"
                      "<li><b>Comparabilidade:</b> os números do teto desta rodada usam a régua de produção de hoje "
                      "(crédito medido) e <b>não</b> são comparáveis ao 1,73x publicado do DEV21, que foi certificado "
                      "com crédito 1,00.</li>"
                      "</ul>")},
        ],
        "footer": f"Gerado do contrato.json por render_painel_lancamento.py · {m['gerado_em'][:16]} · "
                  "traço (—) = ainda não medido",
    }

    tpl = TEMPLATE.read_text()
    ini = tpl.index("const SPEC = {")
    fim = tpl.index("/* ==== runtime")
    html = tpl[:ini] + "const SPEC = " + json.dumps(spec, ensure_ascii=False, indent=1) + ";\n\n" + tpl[fim:]
    html = re.sub(r"<title>.*?</title>", f"<title>Painel do {lf}</title>", html)
    dst = pasta / f"painel_{lf.lower()}.html"
    dst.write_text(html)
    print(f"painel: {dst}  ({dst.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
