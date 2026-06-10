"""Puxa Guru/Hotmart/Asaas via API + TMB local, compara totais e conversões casadas
contra o pool de leads da análise de erros."""
import sys
from pathlib import Path
MAIN = "/Users/ramonmoreira/Desktop/bring_data/V2"
sys.path.insert(0, MAIN)
import os, pandas as pd
from dotenv import load_dotenv
load_dotenv(f"{MAIN}/.env")
pd.set_option("display.width", 200)

from src.validation.data_loader import SalesDataLoader
from src.validation.matching import match_leads_to_sales
from api.business_config import PRODUCT_VALUE

SALES_START, SALES_END = "2026-02-20", "2026-06-08"
CAP_START, CAP_END = "2026-02-20", "2026-05-10"
TMB_FILE = f"{MAIN}/data/devclub/contas_a_receber_08062026_1538.xlsx"
OUT = Path("/Users/ramonmoreira/Desktop/bring_data/.claude/worktrees/analise-erros/V2/outputs/analise_erros")

L = SalesDataLoader()
print(">>> GURU"); guru = L.load_guru_sales_from_api(SALES_START, SALES_END, save_excel=False)
print(">>> HOTMART")
try: hot = L.load_hotmart_sales_from_api(SALES_START, SALES_END)
except Exception as e: print("HOTMART FALHOU", e); hot = None
print(">>> ASAAS")
try:
    asa = L.load_asaas_sales(SALES_START, SALES_END, product_value=PRODUCT_VALUE,
                             customer_created_from="2020-01-01")
except Exception as e: print("ASAAS FALHOU", e); asa = None
print(">>> TMB local")
tmb = L.load_tmb_sales(tmb_paths=[TMB_FILE], report_type="fechamento")

def desc(df, name):
    if df is None or len(df) == 0: print(f"{name}: 0"); return
    v = pd.to_numeric(df.get("sale_value"), errors="coerce")
    tel = df["telefone"].notna().sum() if "telefone" in df.columns else 0
    print(f"{name}: n={len(df)} | tel_preenchido={tel} ({100*tel/len(df):.0f}%) | "
          f"valor med={v.median():.2f} min={v.min():.2f} max={v.max():.2f}")
print("\n===== TOTAIS BRUTOS (janela", SALES_START, "→", SALES_END, ") =====")
for d, n in [(guru,"guru"),(hot,"hotmart"),(asa,"asaas"),(tmb,"tmb")]: desc(d, n)

sales = L.combine_sales(guru_df=guru, hotmart_df=hot, asaas_df=asa, tmb_df=tmb, tmb_paths=[])
oc = "sale_origin" if "sale_origin" in sales.columns else "origem"
print("\nTotal combinado:", len(sales), "| por origem:\n", sales[oc].value_counts().to_string())
sales.to_parquet(OUT/"sales_api_fresh.parquet", index=False)

print("\n===== MATCH contra o pool de leads =====")
pool = pd.read_parquet(OUT/"pool.parquet")
leads = pool[["email","telefone","Data"]].copy()
matched = match_leads_to_sales(leads, sales, use_temporal_validation=False)
conv = matched[matched["converted"]==1] if "converted" in matched.columns else matched[matched.get("sale_value").notna()]
print("Conversões casadas:", len(conv))
moc = "sale_origin" if "sale_origin" in conv.columns else ("origem" if "origem" in conv.columns else oc)
if moc in conv.columns:
    print("Por origem:\n", conv[moc].value_counts().to_string())
if "match_method" in conv.columns:
    print("Por método:\n", conv["match_method"].value_counts().to_string())
matched.to_parquet(OUT/"matched_api_fresh.parquet", index=False)
print("\n[done]")
