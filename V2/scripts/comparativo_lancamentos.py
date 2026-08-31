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
        maduro=(carrinho_fechado and vendas_cobertas),
    )


def main() -> int:
    alvo = sys.argv[1] if len(sys.argv) > 1 else "LF65"
    pasta = _V2 / f"docs/relatorios/{alvo.lower()}_resultado"
    serie = [metricas(lf) for lf in SERIE]
    at = metricas(alvo)
    prev = metricas("LF64") if alvo != "LF64" else None
    top3 = sorted(serie, key=lambda r: -(r["roas"] or 0))[:3]

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
                f"<td>{br(r['pct_gasto_dentro'], 1)}%</td>"
                f"<td>{br(r['roas'])}</td>"
                f"<td class='{'pos' if (r['lucro'] or 0) > 0 else 'neg'}'>{br(r['lucro'], 0, 'R$ ')}</td></tr>")

    media = {k: med(serie, k) for k in
             ("gasto", "cadastros", "cpl", "pct_gasto_dentro", "roas", "lucro")}
    media["cadastros"] = int(media["cadastros"] or 0)
    t3 = {k: med(top3, k) for k in
          ("gasto", "cadastros", "cpl", "pct_gasto_dentro", "roas", "lucro")}
    t3["cadastros"] = int(t3["cadastros"] or 0)

    head = ("<tr><th></th><th>Gasto</th><th>Cadastros</th><th>CPL</th>"
            "<th>% gasto dentro do teto 1,5</th><th>ROAS</th><th>Lucro</th></tr>")
    rows = [linha(f"{alvo} (este)", at, prov)]
    if prev:
        rows.append(linha("LF64 (anterior)", prev, not prev["maduro"]))
    rows.append(linha("Média LF56→DEV21", media))
    rows.append(linha("Top 3 ROAS (" + ", ".join(r["lf"] for r in top3) + ")", t3))
    tab1 = (f"<div class='tw'><table class='tb'><thead>{head}</thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")

    # hipótese da época do mês: semana da 1ª data de captação
    sem_rows = []
    for r in sorted(serie + [at], key=lambda r: r["cap_start"]):
        sem_rows.append(
            f"<tr><td><b>{r['lf']}</b></td><td>{r['cap_start'][8:10]}/{r['cap_start'][5:7]}</td>"
            f"<td>{r['semana']}ª</td><td>{br(r['cpl'])}</td><td>{br(r['roas'])}"
            f"{' <i>(prov.)</i>' if not r['maduro'] else ''}</td></tr>")
    por_sem = {}
    for r in serie:      # só a série fechada entra na média por semana
        por_sem.setdefault(r["semana"], []).append(r)
    med_rows = "".join(
        f"<tr><td><b>{s}ª semana</b></td><td>{len(g)} LF{'s' if len(g) > 1 else ''}</td><td></td>"
        f"<td>{br(med(g, 'cpl'))}</td><td>{br(med(g, 'roas'))}</td></tr>"
        for s, g in sorted(por_sem.items()))
    tab2 = ("<div class='tw'><table class='tb'><thead><tr><th>LF</th><th>Início captação</th>"
            "<th>Semana do mês</th><th>CPL</th><th>ROAS</th></tr></thead>"
            f"<tbody>{''.join(sem_rows)}</tbody></table></div>"
            "<p class='h2sub' style='margin-top:10px'>Média por semana do mês "
            "(só os 9 fechados):</p>"
            "<div class='tw'><table class='tb'><thead><tr><th>Semana</th><th>Base</th><th></th>"
            f"<th>CPL médio</th><th>ROAS médio</th></tr></thead><tbody>{med_rows}</tbody></table></div>")

    aviso = ("<p class='h2sub'>Como ler: 1- <b>Gasto, cadastros, CPL e teto</b> fecham "
             "junto com a captação. Pode comparar sempre. 2- <b>ROAS e lucro</b> só fecham "
             "quando o carrinho fecha e a venda cai no banco. Linha com <i>(provisório)</i> "
             "ainda vai crescer; não tire conclusão dela. 3- O teto aqui é a régua de HOJE "
             "aplicada a todos. A comparação entre eles é justa, mas o número não bate com "
             "o publicado na época de cada um.</p>")
    fonte = ("<p class='h2sub' style='margin-top:10px'>Fonte: o contrato congelado de cada "
             "lançamento (contrato.json): LF56→DEV21 na pasta da corrida (gerados em "
             f"{serie[0]['gerado'][8:10]}/{serie[0]['gerado'][5:7]}), "
             + (f"LF64 em {prev['gerado'][8:10]}/{prev['gerado'][5:7]}, " if prev else "")
             + f"{alvo} em {at['gerado'][8:10]}/{at['gerado'][5:7]}.</p>")
    html = aviso + tab1 + ("<p class='h2sub' style='margin-top:14px'><b>Hipótese da época "
                           "do mês</b> — a semana em que a captação começa:</p>") + tab2 + fonte
    dst = pasta / "comparativo.html"
    dst.write_text(html)
    print(f"comparativo: {dst}  ({dst.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
