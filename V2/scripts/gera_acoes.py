#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gera_acoes — o molde com buracos das Ações (decisão do Ramon, 01/09, item C1).

    python3 scripts/gera_acoes.py docs/relatorios/lf65_resultado

O JULGAMENTO continua autoral: vive em `acoes_template.html` na pasta do LF.
Este script só preenche os NÚMEROS, lidos do contrato congelado, pra texto e
tabela nunca divergirem (o buraco que citou 12,09 com a base errada pra Luiza).

Tokens (chaves duplas, casamento por substring casefold em criativo e tipo):
  {{cpl:ad0160:jul_24}}        CPL do criativo no tipo (por CADASTRO, R$)
  {{teto15:ad0160:jul_24}}     teto 1,5 agregado (pesado por cadastros, R$)
  {{folga:ad0160:jul_24}}      teto15 − cpl (R$)
  {{folga_pct:ad0160:jul_24}}  folga ÷ teto15, em %
  {{gasto:...}} {{lucro:...}} {{prejuizo:...}} (= −lucro) {{roas:...}}
  {{camps1k_n}} / {{camps1k_gasto}}  campanhas Meta >R$1k sem venda (nº / R$)
Token que não resolve (ou resolve ambíguo) DERRUBA a emissão com a lista do
que faltou — silêncio é proibido.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def br(v, dec=2):
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def main() -> int:
    pasta = Path(sys.argv[1])
    tpl = pasta / "acoes_template.html"
    if not tpl.exists():
        print(f"sem {tpl.name} — nada a gerar")
        return 0
    c = json.loads((pasta / "contrato.json").read_text())
    ct = c["tabelas"]["criativos_por_tipo"]
    un = c["tabelas"]["unidades"]
    rot = {x["cid"]: x["modelo"] for x in c["tabelas"]["campanhas"]}

    # teto 1,5 agregado por (tipo, criativo), pesado por cadastros
    agg = defaultdict(lambda: [0.0, 0.0])
    for u in un:
        if u.get("teto") is None:
            continue
        mod = "Google Ads" if u["canal"] == "google" else rot.get(u["cid"])
        w = float(u.get("cadastros") or u.get("leads_ledger") or 0)
        if mod and w:
            a = agg[(mod, u["criativo"])]
            a[0] += float(u["teto"]) * w
            a[1] += w

    def _linha(cria, tipo):
        cl, tl = cria.casefold(), tipo.casefold()
        hits = [x for x in ct
                if cl in str(x.get("criativo", "")).casefold()
                and tl in str(x.get("modelo", "")).casefold()]
        if len(hits) != 1:
            raise KeyError(f"{cria}:{tipo} -> {len(hits)} linhas em criativos_por_tipo")
        return hits[0]

    def _teto15(cria, tipo):
        cl, tl = cria.casefold(), tipo.casefold()
        hits = [(sv, sw) for (m, cr), (sv, sw) in agg.items()
                if cl in str(cr).casefold() and tl in str(m).casefold() and sw]
        if len(hits) != 1:
            raise KeyError(f"teto15 {cria}:{tipo} -> {len(hits)} agregados")
        sv, sw = hits[0]
        return sv / sw * (2.0 / 1.5)

    faltas = []

    def token(m):
        campo = m.group(1)
        try:
            if campo == "camps1k_n" or campo == "camps1k_gasto":
                camps = [x for x in c["tabelas"]["campanhas"]
                         if (x.get("gasto") or 0) > 1000 and not (x.get("vendas") or 0)
                         and x.get("plataforma") == "meta"]
                return (str(len(camps)) if campo == "camps1k_n"
                        else br(sum(x["gasto"] for x in camps), 0))
            op, cria, tipo = campo.split(":")
            if op in ("cpl", "gasto", "lucro", "prejuizo", "roas"):
                x = _linha(cria, tipo)
                if op == "cpl":
                    return br(float(x["cpl"]))
                if op == "gasto":
                    return br(float(x["gasto"]), 0)
                if op == "roas":
                    return br(float(x["faturamento"]) / float(x["gasto"]))
                lucro = float(x["lucro"])
                return br(-lucro if op == "prejuizo" else lucro, 0)
            if op == "teto15":
                return br(_teto15(cria, tipo))
            if op == "folga":
                return br(_teto15(cria, tipo) - float(_linha(cria, tipo)["cpl"]))
            if op == "folga_pct":
                t = _teto15(cria, tipo)
                return br(100 * (t - float(_linha(cria, tipo)["cpl"])) / t, 0)
            raise KeyError(f"operação desconhecida: {op}")
        except Exception as e:  # noqa: BLE001 — coletar TUDO que faltou
            faltas.append(f"{{{{{campo}}}}}: {e}")
            return m.group(0)

    html = re.sub(r"\{\{([^{}]+)\}\}", token, tpl.read_text())
    if faltas:
        print("✗ tokens sem resolução — emissão ABORTADA:", file=sys.stderr)
        for f in faltas:
            print("   " + f, file=sys.stderr)
        return 2
    (pasta / "conclusao.html").write_text(html)
    print(f"ações geradas: {pasta / 'conclusao.html'} (molde {tpl.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
