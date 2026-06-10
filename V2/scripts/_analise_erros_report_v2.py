"""Análise de erros v2 — rótulos corrigidos (match ao vivo, 989 conversões)."""
import sys
from pathlib import Path
import pandas as pd, numpy as np
from sklearn.metrics import roc_auc_score
pd.set_option("display.width", 200)
OUT = Path("/Users/ramonmoreira/Desktop/bring_data/.claude/worktrees/analise-erros/V2/outputs/analise_erros")
DECILS = [f"D{i:02d}" for i in range(1, 11)]

pool = pd.read_parquet(OUT/"pool.parquet").drop(columns=["converted","sale_value","sale_origin","match_method"], errors="ignore")
pool["Data"] = pd.to_datetime(pool["Data"], errors="coerce")
fresh = pd.read_parquet(OUT/"matched_api_fresh.parquet")[["email","converted"]].drop_duplicates("email")
pool = pool.merge(fresh, on="email", how="left")
pool["converted"] = pool["converted"].fillna(0).astype(int)
print(f"Pool {len(pool):,} | conversões (corrigidas) {pool.converted.sum()} | conv {100*pool.converted.mean():.2f}%")

FEATS = ["Qual a sua idade?","O que você faz atualmente?","Atualmente, qual a sua faixa salarial?",
         "Você possui cartão de crédito?","Tem computador/notebook?","Já estudou programação?",
         "investiu_curso_online","interesse_programacao","Source","Medium"]

def prep(label, win=None):
    sc = pd.read_parquet(OUT/f"scored_{label}.parquet")
    d = pool.merge(sc, on="email", how="inner")
    if win: d = d[d["Data"] >= pd.Timestamp(win)]
    return d

def decile_table(d, label):
    base = d.converted.mean()
    t = d.groupby("decil").agg(n=("converted","size"),conv=("converted","sum"),taxa=("converted","mean")).reindex(DECILS)
    t["lift"]=t["taxa"]/base
    auc = roc_auc_score(d.converted, d.lead_score)
    print(f"\n{'='*64}\n{label} | N={len(d):,} conv={int(d.converted.sum())} base={base*100:.2f}% AUC={auc:.4f}")
    print(t.round({"taxa":4,"lift":2}).to_string())

def profile(d, mask, ref, cols, title, topn=4):
    print(f"\n--- {title} (grupo n={mask.sum()} vs ref n={ref.sum()}) ---")
    g,r=d[mask],d[ref]
    for c in cols:
        if c not in d.columns: continue
        gv=g[c].astype(str).value_counts(normalize=True); rv=r[c].astype(str).value_counts(normalize=True)
        print(f"  [{c}]")
        for k in gv.index[:topn]:
            gp,rp=gv.get(k,0)*100,rv.get(k,0)*100
            print(f"     {str(k)[:46]:<46} grupo={gp:5.1f}% ref={rp:5.1f}% ({gp-rp:+.1f})")

for label,win in [("champion",None),("challenger","2026-04-08")]:
    d=prep(label,win)
    print(f"\n\n{'#'*64}\n# {label.upper()} (rótulos corrigidos)\n{'#'*64}")
    decile_table(d,label)
    top=d.decil.isin(["D09","D10"]); low=d.decil.isin(["D01","D02"]); buy=d.converted==1
    profile(d, top&(d.converted==0), top&buy, FEATS, "FP (D9/D10 não comprou) vs D9/D10 comprou")
    profile(d, low&buy, buy, FEATS, "FN (D1/D2 comprou) vs todos compradores")
