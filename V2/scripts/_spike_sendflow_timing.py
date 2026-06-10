"""
SPIKE — timing: lag entre preenchimento do formulário (Railway Lead.createdAt)
e entrada no grupo (SendFlow Histórico de atividade). Define a janela ideal
de delay pra usar a feature em produção. Read-only. Roda de V2/ com PYTHONPATH=.
"""
import os, glob, csv
import pandas as pd
from datetime import datetime

for line in open('.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())

from src.core.client_config import ClientConfig
from src.core.utils import normalizar_telefone_robusto
from src.validation.data_loader import SalesDataLoader

def canon(x):
    n = normalizar_telefone_robusto(x, country_code=55)
    if not n: return None
    if len(n) == 11: n = n[:2] + n[3:]
    return n if len(n) == 10 else None

cfg = ClientConfig.from_yaml('configs/clients/devclub.yaml')
leads = SalesDataLoader().load_railway_leads('2026-03-01', '2026-05-31', cfg)
leads['form_dt'] = pd.to_datetime(leads['Data'], errors='coerce')
leads['k'] = leads['Telefone'].map(canon)
leads = leads.dropna(subset=['k', 'form_dt'])
print(f"[leads] {len(leads)} com chave+data")

deltas = []  # minutos (join - form), por par casado dentro da janela do lançamento
for f in sorted(glob.glob('data/devclub/SendFlow*.csv')):
    join = {}  # canon -> earliest join dt
    dts = []
    with open(f, encoding='utf-8-sig', errors='replace') as fh:
        rd = csv.reader(fh, delimiter=';'); h = next(rd, [])
        idx = {c.strip().lower(): i for i, c in enumerate(h)}; ni, di = idx.get('numero'), idx.get('data')
        for r in rd:
            if ni is None or ni >= len(r) or di is None or di >= len(r): continue
            k = canon(r[ni])
            try: jd = datetime.strptime(r[di].strip().rstrip(';').strip(), '%d/%m/%Y, %H:%M:%S')
            except: continue
            dts.append(jd)
            if k and (k not in join or jd < join[k]): join[k] = jd
    if not dts: continue
    dmin, dmax = min(dts), max(dts)
    win = leads[(leads['form_dt'] >= pd.Timestamp(dmin) - pd.Timedelta(days=2)) &
                (leads['form_dt'] <= pd.Timestamp(dmax) + pd.Timedelta(days=2))]
    form = win.groupby('k')['form_dt'].min().to_dict()
    for k, jd in join.items():
        if k in form:
            deltas.append((jd - form[k].to_pydatetime()).total_seconds() / 60.0)

s = pd.Series(deltas)
print(f"\n[pares casados] {len(s)}")

# --- alinhar fuso: escolhe shift (min) que maximiza % em [0,120min] ---
cands = [-240,-180,-120,-60,0,60,120,180,240]
best, frac = 0, -1
for sh in cands:
    f2 = (((s + sh) >= 0) & ((s + sh) <= 120)).mean()
    if f2 > frac: frac, best = f2, sh
print(f"[fuso] shift escolhido: {best:+d} min  (% em [0,2h] = {frac*100:.0f}%)")
d = s + best

print(f"\n=== DISTRIBUIÇÃO de (entrada_grupo - formulário), após ajuste de fuso ===")
print(f"  joined ANTES do form (delta<0): {100*(d<0).mean():.1f}%")
for lab, lo, hi in [('≤5min',0,5),('≤15min',0,15),('≤30min',0,30),('≤1h',0,60),
                    ('≤2h',0,120),('≤3h',0,180),('≤6h',0,360),('≤12h',0,720),('≤24h',0,1440)]:
    print(f"  entrou em {lab:>6} após o form (cumulativo): {100*((d>=0)&(d<=hi)).mean():.1f}%")
print(f"  >24h: {100*(d>1440).mean():.1f}%")
for q in [.25,.5,.75,.9]:
    v=d[d>=0].quantile(q)
    print(f"  p{int(q*100)} (entre os que entraram após o form): {v:.0f} min")
print("\n=== FIM ===")
