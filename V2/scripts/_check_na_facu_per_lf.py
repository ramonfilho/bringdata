"""Investigação rápida: onde os NAs de 'faculdade' caem por LF (vetorizado)."""
import pandas as pd
import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
launches = yaml.safe_load((REPO / 'configs' / 'launches.yaml').read_text())
df = pd.read_parquet(REPO / 'outputs' / 'analysis' / 'matched_dataset_2026-05-09.parquet')

df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
df['_d'] = df['Data'].dt.normalize()

# Atribuir LF vetorizado
df['_lf'] = pd.NA
for name, cfg in launches.items():
    cs = pd.to_datetime(cfg.get('cap_start'))
    ce = pd.to_datetime(cfg.get('cap_end'))
    if pd.isna(cs) or pd.isna(ce):
        continue
    mask = (df['_d'] >= cs) & (df['_d'] <= ce)
    df.loc[mask, '_lf'] = name

col = 'Você já fez/faz/pretende fazer faculdade?'
df['_m'] = df[col].isna() | (df[col].astype(str).str.lower().isin(['none', 'nan', '<na>', '']))

# Por LF da referência
ref = ['LF40', 'LF41', 'LF45', 'LF50', 'LF53']
print('=== Missing rate "faculdade" por LF da REFERÊNCIA ===')
for lf in ref:
    sub = df[df['_lf'] == lf]
    if not len(sub):
        continue
    nm = int(sub['_m'].sum())
    pct = nm / len(sub) * 100
    if nm:
        p = sub.loc[sub['_m'], 'target'].mean() * 100
        print(f'  {lf}: n={len(sub):>6,}  NA={nm:>5}  ({pct:>5.1f}%)  P(buy|NA)={p:>5.2f}%')
    else:
        print(f'  {lf}: n={len(sub):>6,}  NA=0')

# Quem mais carrega NA?
print('\n=== TODOS os LFs com pelo menos 1 NA ===')
g = df.groupby('_lf').agg(n=('Data', 'count'), n_na=('_m', 'sum'))
g['pct'] = (g['n_na'] / g['n'] * 100).round(2)
print(g[g['n_na'] > 0].sort_values('n_na', ascending=False).to_string())

# Ver o blip de fev/2026 distribuído por LF
print('\n=== fev/2026: NAs distribuídos por LF ===')
f = df[df['Data'].dt.to_period('M').astype(str) == '2026-02'].copy()
g_feb = f.groupby('_lf', dropna=False).agg(n=('Data', 'count'), n_na=('_m', 'sum'))
g_feb['pct'] = (g_feb['n_na'] / g_feb['n'] * 100).round(2)
print(g_feb.to_string())

# Distribuição diária de NAs em LF45
print('\n=== NAs por dia DENTRO de LF45 (cap 03-23/02/2026) ===')
lf45 = df[df['_lf'] == 'LF45'].copy()
lf45_byday = lf45.groupby(lf45['Data'].dt.date).agg(
    n=('Data', 'count'), n_na=('_m', 'sum')
)
lf45_byday['pct'] = (lf45_byday['n_na'] / lf45_byday['n'] * 100).round(1)
print(lf45_byday.to_string())
