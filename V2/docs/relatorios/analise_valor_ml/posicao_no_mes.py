#!/usr/bin/env python3
"""
Posição-no-mês ao nível de LANÇAMENTO (não de venda) — evita o confundidor de
abertura/fechamento de carrinho. Cada LF é classificado por onde cai no mês
(início 1-10 / meio 11-20 / fim 21-31, pelo dia do início das vendas) e comparamos:
  - taxa de conversão (captação: Champion+Challenger+Controle, fonte validada)
  - % boleto (por Fonte)
Janela = semana (vendas próprias do lançamento).
"""
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd, yaml

BASE = Path("/Users/ramonmoreira/bring_data.worktrees/ab-arm/V2")
OUT = BASE / "analise_valor_ml"
L = yaml.safe_load(open(BASE / "configs/launches.yaml"))
OUTLIERS = ['LF40', 'LF41', 'LF51', 'LF53']
BOLETO = {'tmb', 'asaas', 'boletex'}
CARTAO = {'guru', 'hotmart'}

comp = pd.read_csv(OUT / "comparacao_grupos.csv")
sales = pd.read_parquet(OUT / "sales_tidy.parquet")
sales['dv'] = pd.to_datetime(sales.data_venda)


def bucket(day):
    return "início (1-10)" if day <= 10 else ("meio (11-20)" if day <= 20 else "fim (21-31)")


rows = []
for lf in comp.lf.unique():
    c = L[lf]
    vs = datetime.fromisoformat(str(c['vendas_start']))
    # conversão da semana (soma grupos captação)
    cw = comp[(comp.lf == lf) & (comp.janela == "semana")]
    leads, conv = cw.leads.sum(), cw.conv.sum()
    taxa = conv / leads * 100 if leads else float("nan")
    # boleto share da semana (própria venda do LF)
    sw = sales[(sales.lf == lf) & (sales.dv >= vs) & (sales.dv < vs + timedelta(days=7))]
    sw = sw[sw.fonte.isin(BOLETO | CARTAO)]
    bol = sw.fonte.isin(BOLETO).mean() * 100 if len(sw) else float("nan")
    rows.append(dict(lf=lf, dia=vs.day, mes=vs.strftime("%Y-%m"),
                     pos=bucket(vs.day), leads=int(leads), conv=int(conv),
                     taxa_conv=taxa, n_vendas=len(sw), pct_boleto=bol,
                     outlier=lf in OUTLIERS))

df = pd.DataFrame(rows).sort_values("dia")
print("=== POR LANÇAMENTO (semana) ===")
print(df[["lf", "dia", "mes", "pos", "leads", "conv", "taxa_conv", "pct_boleto", "outlier"]]
      .to_string(index=False, float_format=lambda x: f"{x:.2f}"))

ORDER = ["início (1-10)", "meio (11-20)", "fim (21-31)"]
for tag, d in [("COM outliers", df), ("SEM outliers", df[~df.outlier])]:
    print(f"\n=== AGREGADO por posição-no-mês ({tag}) ===")
    g = d.groupby("pos").agg(
        n_lf=("lf", "size"),
        taxa_conv_pooled=("conv", lambda s: s.sum() / d.loc[s.index, "leads"].sum() * 100),
        taxa_conv_media=("taxa_conv", "mean"),
        pct_boleto_media=("pct_boleto", "mean"),
        meses=("mes", lambda s: ",".join(sorted(set(s)))),
    ).reindex(ORDER)
    print(g.to_string(float_format=lambda x: f"{x:.2f}"))
