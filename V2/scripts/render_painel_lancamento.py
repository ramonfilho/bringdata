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
ROTULO_GOOGLE = "Google Ads"   # mesmo literal de lancamento_unidades (o contrato ja vem rotulado)


def br(v, dec=2, prefixo=""):
    """Número no formato pt-BR; None/ausente vira o traço de 'aguardando'."""
    if v is None:
        return "—"
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{prefixo}{s}"


def pct(v, dec=1):
    return "—" if v is None else f"{v:.{dec}f}%".replace(".", ",")


def _cor(v, dec=2, prefixo="R$ "):
    """Célula de dinheiro COLORIDA: verde positivo, vermelho negativo, traço ausente."""
    if v is None:
        return "—"
    return (br(v, dec, prefixo), "pos" if v > 0 else "neg")


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
        conv = (d["v"] / d["l"]) if (d["v"] is not None and d["l"]) else None
        linhas_mod.append([f"<b>{nome}</b>", d["n"], br(d["g"], 2, "R$ "), f"{d['l']:,}".replace(",", "."),
                           br(cpl, 2, "R$ "), br(d["v"], 0),
                           pct(100 * conv, 2) if conv is not None else "—",
                           br(d["f"], 2, "R$ "),
                           br(roas, 2),
                           (br(d["lu"], 2, "R$ "), "pos" if (d["lu"] or 0) > 0 else "neg") if d["lu"] is not None else "—"])
    tot_l = sum(d["l"] for _, d in ordem)
    tot_v = sum(d["v"] or 0 for _, d in ordem) if tem_venda else None
    tot_f = sum(d["f"] or 0 for _, d in ordem) if tem_venda else None
    linhas_mod.append(["<b>TOTAL</b>", sum(d["n"] for _, d in ordem), br(tot_gasto, 2, "R$ "),
                       f"{tot_l:,}".replace(",", "."), br(cpl_geral, 2, "R$ "),
                       br(tot_v, 0) if tem_venda else "—",
                       pct(100 * tot_v / tot_l, 2) if (tem_venda and tot_l) else "—",
                       br(tot_f, 2, "R$ ") if tem_venda else "—", "—", "—"])
    tab_modelo = _tab(["Tipo de campanha", "Camp.", "Gasto", "Cadastros", "CPL",
                       "Vendas", "Conversão", "Faturamento", "ROAS", "Lucro"],
                      linhas_mod[:-1], linhas_mod[-1])

    # ── tela 2: campanha a campanha (top por gasto) ──────────────────────────
    top_camp = sorted([x for x in ca if x.get("gasto")], key=lambda x: -x["gasto"])[:15]
    linhas_c = []
    for x in top_camp:
        linhas_c.append([x["campanha"][:46], x["modelo"], br(x["gasto"], 2, "R$ "),
                         f"{x['leads']:,}".replace(",", "."), br(x["cpl"], 2, "R$ "),
                         br(x.get("vendas"), 0), br(x.get("faturamento"), 2, "R$ "),
                         br(x.get("roas"), 2), _cor(x.get("lucro"))])
    tab_camp = _tab(["Campanha", "Tipo", "Gasto", "Cadastros", "CPL", "Vendas",
                     "Faturamento", "ROAS", "Lucro"], linhas_c)

    # ── tela 3: criativos por tipo (verba + qualidade + efeito na conversão) ─
    # Efeito do criativo = quanto o HISTÓRICO dele multiplica a conversão prevista
    # da unidade: peso×lift + (1−peso). Agregado por (tipo, criativo) e por tipo,
    # ponderado pelos leads — responde "quanto os criativos influenciaram a % de
    # conversão da campanha" no lado PREVISTO (o realizado é a coluna Conversão).
    rot_cid = dict(zip((x["cid"] for x in ca), (x["modelo"] for x in ca)))

    def _tipo(x):
        return ROTULO_GOOGLE if x["canal"] == "google" else (rot_cid.get(x["cid"]) or "—")

    efeito_cria, efeito_tipo, teto_cria = {}, {}, {}
    for x in u:
        mod = ROTULO_GOOGLE if x["canal"] == "google" else rot_cid.get(x["cid"])
        if mod is None:
            continue
        peso = x.get("peso_historico") or 0.0
        lift = x.get("lift_criativo")
        mult = (peso * lift + (1 - peso)) if lift is not None else 1.0
        n = int(x.get("leads_ledger") or 0)
        if x.get("teto") is not None and n:
            t = teto_cria.setdefault((mod, x["criativo"]), [0.0, 0])
            t[0] += x["teto"] * n
            t[1] += n
        for chave, d in ((("c", mod, x["criativo"]), efeito_cria),
                         (("t", mod), efeito_tipo)):
            s = d.setdefault(chave, [0.0, 0])
            s[0] += mult * n
            s[1] += n
    def _efeito(d, *k):
        s = d.get(k)
        return (s[0] / s[1] - 1.0) if s and s[1] else None

    # (tela 3 fundida na 7 em 24/08: teto e efeito viram colunas da agregada)

    # ── tela 4: teto (dentro vs acima) ───────────────────────────────────────
    modo = "MEDIDO" if tem_venda else "PREVISÃO — o julgamento fecha quando as vendas caírem"
    rows_j = []
    for rot, lado in (("Respeitaram o teto", "dentro"), ("Estouraram o teto", "acima")):
        b = j[lado]
        rows_j.append([f"<b>{rot}</b>", b["n"], br(b["gasto"], 2, "R$ "),
                       f"{b['leads']:,}".replace(",", "."), br(b.get("vendas"), 0),
                       br(b.get("roas_ponderado"), 2), _cor(b.get("lucro")),
                       br(b.get("bateu_meta"), 0), br(b.get("lucro_acima_1000"), 0),
                       br(b.get("roas_positivo"), 0)])
    tab_teto = _tab(["", "Unidades", "Gasto", "Leads", "Vendas", "ROAS",
                     "Lucro", "Bateu a meta*", "Lucro > R$ 1.000", "Deu lucro"], rows_j)
    # A régua alternativa pedida (meta 1,5): o teto publicado usa alvo 2,0, então
    # meta 1,5 equivale a teto ×(2,0/1,5). Mesmas unidades julgáveis.
    uj = [x for x in u if x.get("no_corte") and x.get("dentro_do_teto") is not None]
    d15 = [x for x in uj if x["cpl"] <= x["teto"] * (2.0 / 1.5)]
    a15 = [x for x in uj if not (x["cpl"] <= x["teto"] * (2.0 / 1.5))]

    def _lado15(xs, rot):
        gasto = sum(x.get("gasto") or 0 for x in xs)
        leads = sum(int(x.get("leads_ledger") or 0) for x in xs)
        if tem_venda and xs:
            fat = sum(x.get("faturamento") or 0 for x in xs)
            vendas = sum(x.get("vendas") or 0 for x in xs)
            lucro = sum(x.get("lucro") or 0 for x in xs)
            roas = fat / gasto if gasto else None
            bateu = sum(1 for x in xs if (x.get("roas") or 0) >= 1.5 * (1 - j["tolerancia_meta"]))
            l1000 = sum(1 for x in xs if (x.get("lucro") or 0) > 1000)
            pos = sum(1 for x in xs if (x.get("lucro") or 0) > 0)
        else:
            vendas = roas = lucro = bateu = l1000 = pos = None
        return [f"<b>{rot}</b>", len(xs), br(gasto, 2, "R$ "),
                f"{leads:,}".replace(",", "."), br(vendas, 0), br(roas, 2),
                _cor(lucro), br(bateu, 0), br(l1000, 0), br(pos, 0)]

    tab_teto15 = _tab(["", "Unidades", "Gasto", "Leads", "Vendas", "ROAS",
                       "Lucro", "Bateu a meta†", "Lucro > R$ 1.000", "Deu lucro"],
                      [_lado15(d15, "Respeitaram o teto"), _lado15(a15, "Estouraram o teto")])
    tab_teto += ("<p class='h2sub' style='margin-top:14px'>A mesma leitura com meta de ROAS "
                 "<b>1,5</b> (o teto cresce ×1,33; †bateu a meta = ROAS ≥ 1,5 com a mesma "
                 "tolerância de 2%):</p>" + tab_teto15
                 + f"<p class='h2sub' style='margin-top:10px'>Mesmo com a régua mais folgada, "
                 f"só <b>{len(d15)}</b> de {len(uj)} unidades couberam. O que aperta é o custo "
                 "por lead: o cadastro do LF64 saiu <b>39% mais caro</b> que o do DEV21 "
                 "(R$ 8,77 contra R$ 6,33), e essa alta pode ter vindo da troca de pixel "
                 "(as campanhas recomeçaram o aprendizado no pixel novo) ou de outra causa "
                 "ainda não isolada.</p>")

    # ── telas 5 e 6: menor CPL e ranking ─────────────────────────────────────
    um = [x for x in u if x.get("cpl") is not None and (x.get("leads_ledger") or 0) >= 100]
    # (tela 5 'menor CPL' removida em 24/08: a lição dela vive na conclusão)

    chave_rank = "lucro" if tem_venda else "folga"
    rank = sorted([x for x in um if x.get(chave_rank) is not None],
                  key=lambda x: -(x[chave_rank]))[:12]
    # Coluna "Folga" REMOVIDA temporariamente do ranking (pedido do Ramon,
    # 24/08/2026); a ordenação provisória sem venda continua sendo por folga.
    rows6 = [[x["criativo"][:38], _tipo(x), br(x.get("gasto"), 2, "R$ "),
              br(x.get("cpl"), 2, "R$ "),
              br(x.get("faturamento"), 2, "R$ "),
              (br(x.get("lucro"), 2, "R$ "), "pos" if (x.get("lucro") or 0) > 0 else "neg")
              if x.get("lucro") is not None else "—"]
             for x in rank]
    tab_rank = _tab(["Criativo", "Tipo", "Gasto", "CPL", "Faturamento", "Lucro"], rows6)

    # ── tela 7: criativo AGREGADO por tipo (todas as campanhas do tipo somadas) ──
    # No HTML só entra gasto > R$ 300 (mesmo piso do corte do teto); a lista
    # COMPLETA sai em XLSX ao lado do painel, na mesma rodada.
    chave7 = "lucro" if tem_venda else "gasto"
    ct_ord = sorted([x for x in ct if x.get("gasto")],
                    key=lambda x: -(x.get(chave7) or 0))
    def _roas7(x):
        return (x["faturamento"] / x["gasto"]) if (x.get("faturamento") is not None
                                                   and x.get("gasto")) else None
    def _fx7(x):
        tc = teto_cria.get((x["modelo"], x["criativo"]))
        ef = _efeito(efeito_cria, "c", x["modelo"], x["criativo"])
        cel_ef = ("—" if ef is None else
                  (f"{'+' if ef >= 0 else ''}{br(100 * ef, 1)}%", "pos" if ef >= 0 else "neg"))
        return (br(tc[0] / tc[1], 2, "R$ ") if tc and tc[1] else "—"), cel_ef
    rows7 = []
    for x in ct_ord:
        if (x.get("gasto") or 0) <= 300:
            continue
        cel_teto, cel_ef = _fx7(x)
        rows7.append([x["criativo"][:38], x["modelo"], br(x.get("gasto"), 2, "R$ "),
                      br(x.get("cpl"), 2, "R$ "), cel_teto, cel_ef,
                      br(x.get("faturamento"), 2, "R$ "), br(_roas7(x), 2), _cor(x.get("lucro"))])
    tab_cria_tipo = _tab(["Criativo", "Tipo", "Gasto", "CPL", "Teto", "Efeito na conversão",
                          "Faturamento", "ROAS", "Lucro"], rows7)

    import pandas as pd
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    xlsx = pasta / f"criativos_por_tipo_{lf.lower()}.xlsx"
    df7 = pd.DataFrame([{
        "Criativo": x["criativo"], "Tipo": x["modelo"], "Unidades": x.get("unidades"),
        "Leads": x.get("leads_ledger"), "Cadastros": x.get("cadastros"),
        "Gasto": x.get("gasto"), "CPL": x.get("cpl"), "Vendas": x.get("vendas"),
        "Faturamento": x.get("faturamento"), "ROAS": _roas7(x), "Lucro": x.get("lucro"),
        "Conversão %": (100 * x["conversao"]) if x.get("conversao") is not None else None,
        "% notas 9-10": x.get("pct_d9_d10"),
    } for x in ct_ord])
    # Formatação no padrão do painel: dinheiro em R$ com 2 casas, ROAS 2 casas,
    # percentuais com o símbolo, inteiros sem casa; cabeçalho em negrito e congelado.
    _FMT = {"Gasto": 'R$ #,##0.00', "CPL": 'R$ #,##0.00', "Faturamento": 'R$ #,##0.00',
            "Lucro": 'R$ #,##0.00', "ROAS": '0.00', "Conversão %": '0.00"%"',
            "% notas 9-10": '0.0"%"', "Leads": '#,##0', "Cadastros": '#,##0',
            "Unidades": '0', "Vendas": '0'}
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        df7.to_excel(xw, index=False, sheet_name="criativos_por_tipo")
        ws = xw.sheets["criativos_por_tipo"]
        for i, col in enumerate(df7.columns, 1):
            letra = get_column_letter(i)
            ws.column_dimensions[letra].width = (44 if col == "Criativo" else
                                                 24 if col == "Tipo" else
                                                 max(len(col) + 3, 12))
            f = _FMT.get(col)
            if f:
                for cell in ws[letra][1:]:
                    cell.number_format = f
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
    print(f"xlsx:   {xlsx}  ({len(ct_ord)} linhas, completo, formatado)")

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
            {"title": f"4 · Teto de CPL — {modo}",
             "sub": "Unidade = criativo×campanha com ≥100 leads e ≥R$ 300 de gasto. "
                    "*Meta = ROAS 2,0 com tolerância de 2% (um 1,97 conta).",
             "html": tab_teto},
            {"title": ("6 · Ranking por lucro" if tem_venda else
                       "6 · Ranking — por folga, enquanto não há lucro para ordenar"),
             "sub": ("Do maior para o menor lucro." if tem_venda else
                     "Sem venda ingerida a coluna de lucro fica vazia; a ordem provisória é a folga "
                     "(quem mais respeita o teto). A rodada com vendas reordena por lucro."),
             "html": tab_rank},
            {"title": "7 · Criativo agregado por tipo de campanha",
             "sub": "Cada linha soma TODAS as campanhas de um tipo em que o criativo rodou. "
                    "Teto = o CPL máximo que a unidade sustenta na meta de ROAS 2,0 (condensa a "
                    "qualidade do público e a nota histórica do criativo); Efeito na conversão = "
                    "quanto o histórico do criativo puxou a conversão prevista. Só gasto acima de "
                    "R$ 300; a lista completa sai em XLSX junto do painel, na mesma rodada.",
             "html": tab_cria_tipo},
            {"title": "8 · Régua e cobertura (o carimbo desta rodada)",
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

    # Conclusão do lançamento: análise autoral deste LF vive em conclusao.html na
    # pasta do relatório (não no script, que é genérico); entra ANTES do carimbo.
    conclusao = pasta / "conclusao.html"
    if conclusao.exists():
        carimbo = next(i for i, x in enumerate(spec["sections"])
                       if "carimbo" in x["title"])
        spec["sections"].insert(carimbo, {"title": "Conclusão — o que fazer no próximo lançamento",
                                          "html": conclusao.read_text()})
    for i, x in enumerate(spec["sections"], 1):   # renumera 1..N (sempre)
        x["title"] = re.sub(r"^\d+ · ", "", x["title"])
        x["title"] = f"{i} · {x['title']}"

    # Notas do lançamento: fatos pontuais deste LF vivem em notas.html na pasta
    # do relatório (não no script, que é genérico); se existir, vira a seção final.
    notas = pasta / "notas.html"
    if notas.exists():
        spec["sections"].append({"title": f"{len(spec['sections']) + 1} · Notas do lançamento",
                                 "html": notas.read_text()})

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
