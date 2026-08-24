#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auditoria de decisões do LF64: para cada unidade (campanha×criativo), o DIA em
que o sinal de estouro ficou claro e o gasto incorrido DEPOIS dele, com o retorno
MEDIDO desse gasto (leads captados após o sinal e as vendas que eles casaram).
Régua do sinal: CPL acumulado > teto×1,33 (corte 1,5) com ≥R$ 1.000 e ≥30 leads
acumulados. O teto usado é o CONGELADO no contrato (proxy declarado: a nota do
criativo era conhecida no dia 1 e a mistura de decis estabiliza cedo).
Sem projeção de venda: só verba pós-sinal e o que ela devolveu, medidos."""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_V2 = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_V2))
os.chdir(_V2)
os.environ.setdefault("LAUNCHES_SOURCE", "table")
from dotenv import load_dotenv
load_dotenv(_V2 / ".env")

import pandas as pd
from src.core.launches import load_launches
from src.data.ad_insights_reader import gasto_por_unidade, read_ad_insights
from src.data.ad_spend_reader import read_ad_spend
from src.data.analytics_connection import open_analytics_connection
from src.data.cadastro_records import open_railway_connection, read_cadastros
from src.data.criativo_historico import mapa_de_nomes
from src.data.ledger_connection import open_ledger_read_connection
from src.validation.lancamento_unidades import BRT, prepara_leads
from src.validation.model_performance import (_load_matched, _load_meta_gross_up,
                                              read_analytics_sales, read_ledger_leads)

LF = "LF64"
c = json.loads((_V2 / "docs/relatorios/lf64_resultado/contrato.json").read_text())
teto_unid = {(x["cid"], x["criativo"]): x["teto"] for x in c["tabelas"]["unidades"]
             if x.get("teto") is not None}

launches = load_launches()
cfg = launches[LF]
cap_start = datetime.strptime(str(cfg["cap_start"])[:10], "%Y-%m-%d").date()
cap_end = datetime.strptime(str(cfg["cap_end"])[:10], "%Y-%m-%d").date()

an = open_analytics_connection(timeout=900)
lg = open_ledger_read_connection()
rc = open_railway_connection()
try:
    mapa = mapa_de_nomes(an, client_id="devclub")
    m = _load_matched(
        LF,
        ledger_reader=lambda cs, ce: read_ledger_leads(lg, cs, ce),
        sales_reader=lambda s, e: read_analytics_sales(an, s, e),
        spend_reader=lambda s, e: read_ad_spend(s, e, conn=an),
        cadastro_reader=lambda cs, ce: read_cadastros(rc, cs, ce, utms_extras=True),
        as_of=datetime.now(BRT).date(), window_days=60, launches=launches)
    insights = read_ad_insights(cap_start, cap_end + timedelta(days=1), conn=an)
finally:
    pass

neg = prepara_leads(m["matched_negocio"], mapa)
gross_up = _load_meta_gross_up()

# gasto acumulado por unidade e por dia (reusa o mapeador anúncio→unidade da máquina)
dias = sorted(insights["insight_date"].unique())
gasto_dia = {}   # (unit, dia) -> spend do dia
for d in dias:
    gpu = gasto_por_unidade(insights[insights["insight_date"] == d], gross_up=gross_up)
    for k, v in gpu.items():
        gasto_dia[(k, d)] = v["spend"]

# cadastros e vendas casadas por unidade e por dia de CAPTURA (data em BRT)
neg = neg.copy()
neg["dia"] = pd.to_datetime(neg["data_captura"], utc=True).dt.tz_convert("America/Sao_Paulo").dt.date
neg["unit"] = list(zip(neg["cid"].astype(str), neg["criativo"]))

FATOR15 = 2.0 / 1.5
PISOS = [(300, 15), (500, 20), (1000, 30)]   # sensibilidade: o teto existe com pouco gasto
units = sorted({k for (k, _) in gasto_dia} & {(str(a), b) for a, b in teto_unid})
saida = {}
for GMIN, LMIN in PISOS:
    res = []
    for unit in units:
        teto = teto_unid.get((unit[0], unit[1]))
        if not teto:
            continue
        sub = neg[neg["unit"] == unit]
        ga = la = 0.0
        dstar, volta = None, False
        serie = []
        for d in dias:
            ga += gasto_dia.get((unit, d), 0.0)
            la += int((sub["dia"] == d).sum())
            cpl = ga / la if la else None
            dentro = (cpl is not None and cpl <= teto * FATOR15)
            serie.append((d, ga, la, cpl, dentro))
            if dstar is None and ga >= GMIN and la >= LMIN and cpl is not None and not dentro:
                dstar = d
            elif dstar is not None and dentro:
                volta = True
        if dstar is None:
            continue
        g_star = next(g for (d, g, *_ ) in serie if d == dstar)
        g_total = serie[-1][1]
        apos = sub[sub["dia"] > dstar]
        vend = apos[apos["converted"].fillna(False)]
        res.append(dict(cid=unit[0], criativo=unit[1], teto=round(teto, 2), dstar=str(dstar),
                        gasto_no_sinal=round(g_star), gasto_apos=round(g_total - g_star),
                        leads_apos=int(len(apos)), vendas_apos=int(len(vend)),
                        fat_apos=round(float(vend["sale_value"].sum())), voltou=volta))
    res.sort(key=lambda r: -r["gasto_apos"])
    ev = [r for r in res if not r["voltou"]]
    fa = [r for r in res if r["voltou"]]
    saida[f"{GMIN}"] = res
    print(f"\n== piso R$ {GMIN} + {LMIN} leads ==")
    print(f"  alarmes {len(res)} (falsos, voltaram: {len(fa)})  "
          f"verba pós-sinal dos que nunca voltaram: R$ {sum(r['gasto_apos'] for r in ev):,.0f}  "
          f"→ devolveu {sum(r['vendas_apos'] for r in ev)} vendas R$ {sum(r['fat_apos'] for r in ev):,.0f}  "
          f"| falsos alarmes: pós-sinal R$ {sum(r['gasto_apos'] for r in fa):,.0f} "
          f"→ {sum(r['vendas_apos'] for r in fa)} vendas R$ {sum(r['fat_apos'] for r in fa):,.0f}")
    if GMIN == 300:
        for r in res[:14]:
            print(f"    {r['criativo'][:30]:30s} teto {r['teto']:>6.2f}  sinal {r['dstar']} "
                  f"c/ R$ {r['gasto_no_sinal']:>5,}  APÓS: R$ {r['gasto_apos']:>6,} · "
                  f"{r['leads_apos']:>3} leads · {r['vendas_apos']} vendas R$ {r['fat_apos']:,}"
                  + ("  (voltou)" if r["voltou"] else ""))
json.dump(saida, open(_V2 / "docs/relatorios/lf64_resultado/auditoria_decisoes.json", "w"))
print("\nsalvo em docs/relatorios/lf64_resultado/auditoria_decisoes.json")
