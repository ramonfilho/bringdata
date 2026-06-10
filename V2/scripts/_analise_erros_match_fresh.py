import sys
from pathlib import Path
MAIN = "/Users/ramonmoreira/Desktop/bring_data/V2"
sys.path.insert(0, MAIN)
import pandas as pd
pd.set_option("display.width", 200)
from src.validation.matching import match_leads_to_sales, filter_by_period

OUT = Path("/Users/ramonmoreira/Desktop/bring_data/.claude/worktrees/analise-erros/V2/outputs/analise_erros")
SALES_START, SALES_END = "2026-02-24", "2026-05-31"

sales = pd.read_parquet(OUT/"sales_api_fresh.parquet")
oc = "sale_origin" if "sale_origin" in sales.columns else "origem"
sales["sale_date"] = pd.to_datetime(sales["sale_date"], errors="coerce")
print("Bruto por origem (todas as datas):\n", sales[oc].value_counts().to_string())
sales_w = filter_by_period(sales, SALES_START, SALES_END, "sale_date")
print(f"\nApós filtro janela {SALES_START}→{SALES_END}: {len(sales_w)}")
print(sales_w[oc].value_counts().to_string())

pool = pd.read_parquet(OUT/"pool.parquet")
leads = pool[["email","telefone","Data"]].rename(columns={"Data":"data_captura"}).copy()
leads["data_captura"] = pd.to_datetime(leads["data_captura"], errors="coerce")

matched = match_leads_to_sales(leads, sales_w, use_temporal_validation=False)
conv = matched[matched["converted"]==1]
print(f"\n===== MATCH vs pool ({len(pool):,} leads) =====")
print("Conversões casadas:", len(conv), f"(conv rate {100*len(conv)/len(pool):.2f}%)")
moc = "sale_origin" if "sale_origin" in conv.columns else ("origem" if "origem" in conv.columns else None)
if moc: print("Por origem:\n", conv[moc].value_counts().to_string())
if "match_method" in conv.columns: print("Por método:\n", conv["match_method"].value_counts().to_string())
print("\nComparação com análise original (só guru/hotmart/asaas, email-only): asaas=410 guru=132 hotmart=107, total=649")
matched.to_parquet(OUT/"matched_api_fresh.parquet", index=False)
print("[done]")
