#!/usr/bin/env python3
"""
Análise semana-do-mês: pooled de TODAS as vendas (deduplicadas entre janelas 60d
sobrepostas), bucketizadas pela semana-do-mês do dia da venda.
  - volume de vendas por semana-do-mês (normalizado por nº de dias)
  - proporção cartão/boleto por semana-do-mês (via FONTE, 100% preenchida)
"""
from pathlib import Path
import openpyxl, pandas as pd, yaml

BASE = Path("/Users/ramonmoreira/bring_data.worktrees/ab-arm/V2")
V = BASE / "outputs/validation"
L = yaml.safe_load(open(BASE / "configs/launches.yaml"))
LFS = ['LF40','LF41','LF42','LF43','LF44','LF45','LF46','LF47','LF48','LF49',
       'LF50','LF51','LF52','LF53','LF54','LF55','LF56','DEV19']
BOLETO = {'tmb', 'asaas', 'boletex'}
CARTAO = {'guru', 'hotmart'}


def newest(lf):
    cs = [(p.stat().st_mtime, p) for p in V.glob(f"*/{lf} - *.xlsx")]
    cs += [(p.stat().st_mtime, p) for p in V.glob(f"{lf} - *.xlsx")]
    return max(cs)[1] if cs else None


rows = []
for lf in LFS:
    p = newest(lf)
    if not p:
        continue
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ws = wb["Detalhes das Conversões"]
    for r in ws.iter_rows(min_row=4, values_only=True):
        if not r or r[9] is None:
            continue
        rows.append(dict(email=str(r[1]).strip().lower() if r[1] else "",
                         dv=str(r[9])[:10], contratado=float(r[10] or 0),
                         recebido=float(r[11] or 0), fonte=str(r[12]).strip().lower() if r[12] else ""))
    wb.close()

df = pd.DataFrame(rows)
print(f"linhas brutas (com sobreposição): {len(df):,}")
df = df.drop_duplicates(subset=["email", "dv", "contratado", "fonte"])
df = df[df.email != ""]
print(f"vendas únicas (dedup email+data+valor+fonte): {len(df):,}")

df["dv"] = pd.to_datetime(df.dv)
df["dia"] = df.dv.dt.day
df["wom"] = ((df.dia - 1) // 7 + 1).clip(upper=5)   # semana-do-mês 1..5
df["mes"] = df.dv.dt.to_period("M")
df["tipo"] = df.fonte.map(lambda f: "boleto" if f in BOLETO else ("cartão" if f in CARTAO else "?"))

# período coberto
print(f"período: {df.dv.min().date()} a {df.dv.max().date()}\n")

# nº de dias por semana-do-mês ao longo do período (pra normalizar)
alldays = pd.date_range(df.dv.min().normalize(), df.dv.max().normalize())
diasdf = pd.DataFrame({"d": alldays})
diasdf["wom"] = ((diasdf.d.dt.day - 1) // 7 + 1).clip(upper=5)
dias_por_wom = diasdf.groupby("wom").size()

print("=== 1) VOLUME por semana-do-mês ===")
g = df.groupby("wom").agg(vendas=("dv", "size"), receita=("contratado", "sum"))
g["dias_no_periodo"] = dias_por_wom
g["vendas_por_dia"] = (g.vendas / g.dias_no_periodo).round(1)
g["idx_vs_media"] = (g.vendas_por_dia / g.vendas_por_dia[:4].mean() * 100).round(0)  # base = semanas 1-4
print(g.to_string())

print("\n=== 2) CARTÃO vs BOLETO por semana-do-mês ===")
ct = df[df.tipo != "?"].groupby(["wom", "tipo"]).size().unstack(fill_value=0)
ct["total"] = ct.sum(axis=1)
ct["%_boleto"] = (ct["boleto"] / ct.total * 100).round(1)
ct["%_cartão"] = (ct["cartão"] / ct.total * 100).round(1)
print(ct.to_string())

print("\n=== robustez: %_boleto por semana-do-mês em cada mês ===")
pm = df[df.tipo != "?"].pivot_table(index="mes", columns="wom",
                                    values="tipo", aggfunc=lambda x: (x == "boleto").mean() * 100)
print(pm.round(0).to_string())
