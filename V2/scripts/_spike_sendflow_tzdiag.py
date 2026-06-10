"""Diagnóstico de fuso/lag: pares casados crus form×entrada. Read-only."""
import os, glob, csv
import pandas as pd
from datetime import datetime
for line in open('.env'):
    line=line.strip()
    if line and not line.startswith('#') and '=' in line:
        k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip())
from src.core.client_config import ClientConfig
from src.core.utils import normalizar_telefone_robusto
from src.validation.data_loader import SalesDataLoader
def canon(x):
    n=normalizar_telefone_robusto(x,55)
    if not n: return None
    if len(n)==11: n=n[:2]+n[3:]
    return n if len(n)==10 else None
cfg=ClientConfig.from_yaml('configs/clients/devclub.yaml')
leads=SalesDataLoader().load_railway_leads('2026-03-01','2026-05-31',cfg)
leads['form_dt']=pd.to_datetime(leads['Data'],errors='coerce')
leads['k']=leads['Telefone'].map(canon)
leads=leads.dropna(subset=['k','form_dt'])
print("form hora-do-dia (top5):", leads['form_dt'].dt.hour.value_counts().head(5).to_dict())

pairs=[]
joinhours=[]
for f in sorted(glob.glob('data/devclub/SendFlow*.csv')):
    join={}; dts=[]
    with open(f,encoding='utf-8-sig',errors='replace') as fh:
        rd=csv.reader(fh,delimiter=';'); h=next(rd,[])
        idx={c.strip().lower():i for i,c in enumerate(h)}; ni,di=idx.get('numero'),idx.get('data')
        for r in rd:
            if ni is None or ni>=len(r) or di is None or di>=len(r): continue
            k=canon(r[ni])
            try: jd=datetime.strptime(r[di].strip().rstrip(';').strip(),'%d/%m/%Y, %H:%M:%S')
            except: continue
            dts.append(jd); joinhours.append(jd.hour)
            if k and (k not in join or jd<join[k]): join[k]=jd
    if not dts: continue
    dmin,dmax=min(dts),max(dts)
    win=leads[(leads['form_dt']>=pd.Timestamp(dmin)-pd.Timedelta(days=2))&(leads['form_dt']<=pd.Timestamp(dmax)+pd.Timedelta(days=2))]
    form=win.groupby('k')['form_dt'].min().to_dict()
    for k,jd in join.items():
        if k in form:
            pairs.append((k, form[k], jd, (jd-form[k].to_pydatetime()).total_seconds()/60.0))
print("join hora-do-dia (top5):", pd.Series(joinhours).value_counts().head(5).to_dict())
d=pd.Series([p[3] for p in pairs])
print(f"\npares={len(d)}")
print("delta_raw (min) percentis:", {q: round(d.quantile(q)) for q in [.05,.1,.25,.5,.75,.9,.95,.99]})
print("\n=== 12 pares crus (form | entrada | delta_min) ===")
for k,fd,jd,dl in pairs[:12]:
    print(f"  {k} | form {fd} | join {jd} | {dl:+.0f} min")
