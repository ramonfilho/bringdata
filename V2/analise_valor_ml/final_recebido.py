#!/usr/bin/env python3
"""
Resultado final: receita por grupo = CONTRATADO validado (Comparação ML) × ratio
recebido/contratado (do Detalhes, por LF/janela/grupo — robusto à super-atribuição).
Gasto = captação Meta (Comparação). Baseline = controle pooled (só LFs saudáveis).
"""
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd, yaml

BASE = Path("/Users/ramonmoreira/bring_data.worktrees/ab-arm/V2")
OUT = BASE / "analise_valor_ml"
L = yaml.safe_load(open(BASE / "configs/launches.yaml"))
OUTLIERS = ['LF40', 'LF41', 'LF53']
HEALTHY_MIN = 5000

comp = pd.read_csv(OUT / "comparacao_grupos.csv")           # contratado validado
sales = pd.read_parquet(OUT / "sales_tidy.parquet")
sales['dc'] = pd.to_datetime(sales.data_captura)
sales['dv'] = pd.to_datetime(sales.data_venda)

WIN = {"semana": 7, "60d": 60}


def ratio(lf, jan, grupo):
    c = L[lf]
    cs = datetime.fromisoformat(str(c['cap_start'])); ce = datetime.fromisoformat(str(c['cap_end'])) + timedelta(days=1)
    vs = datetime.fromisoformat(str(c['vendas_start']))
    d = sales[(sales.lf == lf) & (sales.grupo == grupo) & (sales.dc >= cs) & (sales.dc < ce)
              & (sales.dv >= vs) & (sales.dv < vs + timedelta(days=WIN[jan]))]
    return d.recebido.sum() / d.contratado.sum() if d.contratado.sum() > 0 else 0.40


comp = comp[~comp.lf.isin(OUTLIERS)].copy()
comp['contratado'] = comp['receita']
comp['recebido'] = [r.receita * ratio(r.lf, r.janela, r.grupo) for r in comp.itertuples()]


def agg(jan, base):
    d = comp[comp.janela == jan]
    ct = d[d.grupo == "Controle"]
    healthy = set(ct[ct.gasto > HEALTHY_MIN].lf)
    cpool = d[(d.grupo == "Controle") & d.lf.isin(healthy)]
    rc = cpool[base].sum() / cpool.gasto.sum()
    ml_all = d[d.grupo.isin(["Champion", "Challenger"])]
    ml_h = ml_all[ml_all.lf.isin(healthy)]
    def block(ml):
        sp, rev = ml.gasto.sum(), ml[base].sum()
        return sp, rev, rev / sp, rev - sp * rc
    sp_p, rev_p, rml_p, dn_p = block(ml_all)
    sp_m, rev_m, rml_m, dn_m = block(ml_h)
    return rc, (rml_m, dn_m, sp_m), (rml_p, dn_p, sp_p), sorted(healthy)


print("FONTE: contratado validado (Comparação ML) ; recebido = × ratio por grupo\n")
for base in ["contratado", "recebido"]:
    print(f"================  BASE = {base.upper()}  ================")
    for jan in ["semana", "60d"]:
        rc, (rml_m, dn_m, sp_m), (rml_p, dn_p, sp_p), h = agg(jan, base)
        print(f"  {jan:7} | controle pooled ROAS={rc:.2f}")
        print(f"          MEDIDO (5 LFs c/ctrl):  ROAS_ML={rml_m:.2f}  +{(rml_m/rc-1)*100:.0f}%  dinheiro novo=R${dn_m:,.0f}")
        print(f"          PORTFÓLIO (14 LFs):     ROAS_ML={rml_p:.2f}  +{(rml_p/rc-1)*100:.0f}%  dinheiro novo=R${dn_p:,.0f}")
    print()
