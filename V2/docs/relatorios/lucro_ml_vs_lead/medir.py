#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Item 3: lucro ML vs Lead por LF, sobre os contratos da corrida (LF56..DEV21) + LF64.

Pergunta do Ramon: "o lead encareceu, logo o ML nao da mais lucro que o Lead?"
Medicao, nao projecao. Fonte: contratos congelados da maquina canonica
(docs/relatorios/_corrida/<LF>/contrato.json, regua de producao de 27/08;
DEV21 reconstruido em 31/08 com --as-of 2026-08-27) + LF64 (26/08, PROVISORIO).

Comparacao JUSTA: so campanhas FRIAS da Meta (regra #220/221: Lead padrao =
captacao fria; quente tem economia propria e sai da comparacao, listado a parte).
"""
import json
import re
from pathlib import Path

V2 = Path("/Users/ramonmoreira/Desktop/bring_data/V2")
LFS = ["LF56", "LF57", "LF58", "LF59", "LF60", "LF61", "LF62", "LF63", "DEV21"]

_SEP = re.compile(r"[\[\]]+")
_PIPES = re.compile(r"\s*\|[\s|]*")


def temperatura(nome: str) -> str:
    """Mesma normalizacao do ab_arm (colchetes viram pipes) + token de publico."""
    t = _PIPES.sub(" | ", _SEP.sub(" | ", str(nome or "").lower())).strip()
    toks = {p.strip() for p in t.split("|") if p.strip()}
    if "quente" in toks:
        return "quente"
    if "morno" in toks:
        return "morno"
    if "frio" in toks:
        return "frio"
    return "sem_publico_no_nome"


NAO_MODELO = {"Lead Padrão (Meta)", "Google Ads", "Orgânico/Outro", "Não está na base"}


def agrega(rows):
    g = dict(gasto=0.0, leads=0, vendas=0.0, fat=0.0, lucro=0.0, camp=0)
    for x in rows:
        g["gasto"] += x.get("gasto") or 0
        g["leads"] += x.get("leads") or 0
        g["vendas"] += x.get("vendas") or 0
        g["fat"] += x.get("faturamento") or 0
        g["lucro"] += x.get("lucro") or 0
        g["camp"] += 1
    g["cpl"] = g["gasto"] / g["leads"] if g["leads"] else None
    g["roas"] = g["fat"] / g["gasto"] if g["gasto"] else None
    g["lucro_lead"] = g["lucro"] / g["leads"] if g["leads"] else None
    g["conv"] = 100 * g["vendas"] / g["leads"] if g["leads"] else None
    return g


def fmt(v, spec=",.2f"):
    return format(v, spec) if v is not None else "-"


linhas = []
tot = {"ml": [], "lead": [], "quente": []}
for lf in LFS + ["LF64"]:
    p = (V2 / "docs/relatorios/_corrida" / lf / "contrato.json") if lf != "LF64" \
        else V2 / "docs/relatorios/lf64_resultado/contrato.json"
    c = json.loads(p.read_text())
    ca = c["tabelas"]["campanhas"]
    meta_rows = [x for x in ca if x.get("plataforma") == "meta"]
    for x in meta_rows:
        x["_temp"] = temperatura(x["campanha"])
    frio = [x for x in meta_rows if x["_temp"] != "quente"]
    ml = [x for x in frio if x["modelo"] not in NAO_MODELO]
    lead = [x for x in frio if x["modelo"] == "Lead Padrão (Meta)"]
    quente = [x for x in meta_rows if x["_temp"] == "quente"]
    tot["ml"] += ml
    tot["lead"] += lead
    tot["quente"] += quente
    a, b, q = agrega(ml), agrega(lead), agrega(quente)
    linhas.append((lf, c["meta"]["estado"], a, b, q))

W = 132
print("LUCRO ML vs LEAD (so campanhas FRIAS da Meta; quente a parte)".center(W))
print(f"{'LF':6} {'estado':22} | {'CPL ML':>8} {'CPL Lead':>8} | {'ROAS ML':>7} {'ROAS Ld':>7} | "
      f"{'lucro ML':>12} {'lucro Lead':>12} | {'R$/lead ML':>10} {'R$/lead Ld':>10} | {'conv ML':>7} {'conv Ld':>7}")
for lf, est, a, b, q in linhas:
    print(f"{lf:6} {est:22} | {fmt(a['cpl']):>8} {fmt(b['cpl']):>8} | {fmt(a['roas']):>7} {fmt(b['roas']):>7} | "
          f"{fmt(a['lucro'],',.0f'):>12} {fmt(b['lucro'],',.0f'):>12} | {fmt(a['lucro_lead']):>10} {fmt(b['lucro_lead']):>10} | "
          f"{fmt(a['conv']):>7} {fmt(b['conv']):>7}")
    if q["camp"]:
        print(f"{'':6} {'  quente:':22} | {fmt(q['cpl']):>8} {'':>8} | {fmt(q['roas']):>7} {'':>7} | "
              f"{fmt(q['lucro'],',.0f'):>12} {'':>12} | {fmt(q['lucro_lead']):>10} {'':>10} | {fmt(q['conv']):>7}")

print()
A, B, Q = agrega(tot["ml"]), agrega(tot["lead"]), agrega(tot["quente"])
for rot, g in (("ML (Champion+Challenger), frio", A), ("Lead Padrao (Meta), frio", B), ("Quente (todas)", Q)):
    print(f"TOTAL {rot:32} camp={g['camp']:3}  gasto={fmt(g['gasto'],',.0f'):>10}  leads={g['leads']:>7,}  "
          f"CPL={fmt(g['cpl'])}  conv={fmt(g['conv'])}%  ROAS={fmt(g['roas'])}  lucro={fmt(g['lucro'],',.0f'):>10}  R$/lead={fmt(g['lucro_lead'])}")

# placar: em quantos LFs fechados o ML lucrou mais POR LEAD que o Lead?
fech = [(lf, a, b) for lf, est, a, b, _ in linhas
        if a["leads"] and b["leads"] and lf != "LF64"]
ganha = sum(1 for _, a, b in fech if (a["lucro_lead"] or 0) > (b["lucro_lead"] or 0))
print(f"\nplacar R$/lead (LFs fechados com os dois lados): ML ganha em {ganha}/{len(fech)}")
ganha_roas = sum(1 for _, a, b in fech if (a["roas"] or 0) > (b["roas"] or 0))
print(f"placar ROAS: ML ganha em {ganha_roas}/{len(fech)}")
