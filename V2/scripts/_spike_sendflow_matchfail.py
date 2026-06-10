"""
SPIKE — ponto 5: match-failure correlaciona com compra?
Se leads com telefone NÃO-canonizável (forçados a entrou=0) convertem diferente
dos canonizáveis, o fillna 0 da feature está enviesado. Read-only, usa o pool.
Roda de V2/ com PYTHONPATH=.
"""
import os
import pandas as pd
for line in open('.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())
from src.core.utils import normalizar_telefone_robusto

def canon(x):
    n = normalizar_telefone_robusto(x, country_code=55)
    if not n: return None
    if len(n) == 11: n = n[:2] + n[3:]
    return n if len(n) == 10 else None

P = pd.read_parquet('outputs/_spike_pool.parquet')
P['_k'] = P['telefone'].map(canon)
P['canon_ok'] = P['_k'].notna()
conv = P['converted'].astype(float)
N = len(P)
print(f"pool: {N} leads | canon válido: {100*P['canon_ok'].mean():.1f}% | canon=None (não-casável): {100*(~P['canon_ok']).mean():.1f}%")

def row(label, mask):
    m = conv[mask]
    print(f"  {label:<34} n={len(m):>6} conv={100*m.mean():.2f}%")

print("\n=== A) GERAL: canonizável vs não-canonizável ===")
row("canon VÁLIDO (casável)", P['canon_ok'])
row("canon=None (NUNCA casa -> 0)", ~P['canon_ok'])
ca = conv[P['canon_ok']].mean(); cn = conv[~P['canon_ok']].mean()
print(f"  razão (None / válido) = {cn/ca:.2f}x" if ca else "")

print("\n=== B) composição da classe entrou=0 ===")
z = P[~P['entrou']]
zc = z['canon_ok']
print(f"  entrou=0: {len(z)} leads | dos quais canon=None: {100*(~zc).mean():.1f}%")
row("entrou=0 & canon VÁLIDO (não-joiner real)", (~P['entrou']) & P['canon_ok'])
row("entrou=0 & canon=None (match-failure)", (~P['entrou']) & (~P['canon_ok']))

print("\n=== C) referência: entrou=1 ===")
row("entrou=1", P['entrou'])

print("\n=== VEREDITO ===")
b_real = conv[(~P['entrou']) & P['canon_ok']].mean()
b_fail = conv[(~P['entrou']) & (~P['canon_ok'])].mean()
print(f"  conv(entrou=0, canon ok)={100*b_real:.2f}%  vs  conv(entrou=0, match-fail)={100*b_fail:.2f}%")
print(f"  divergência = {abs(b_real-b_fail)*100:.2f} p.p.  -> fillna 0 {'ENVIESADO' if b_fail and abs(b_real-b_fail)/max(b_real,1e-9)>0.3 else 'seguro (sem viés relevante)'}")
print("\n=== FIM ===")
