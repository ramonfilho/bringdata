# -*- coding: utf-8 -*-
"""Complementos pedidos: decil do jul_24 na base cheia (p/ criativo fixo nos DOIS modelos)
e a matriz lucro do criativo POR campanha."""
import os,sys,ssl,json,math
sys.path.insert(0,'/Users/ramonmoreira/Desktop/bring_data/V2'); os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
import pandas as pd, pg8000.native
from scipy.stats import norm
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
ABR='5d158f0aa6e54b489498470446194a6c'; JUL='b085b63681bc4d0d90bdbd466106763a'
C=pd.read_pickle(S+'criativo_leads.pkl'); U=pd.read_pickle(S+'criativo_unidades.pkl')
c=pg8000.native.Connection(user=os.environ['LEDGER_DB_USER'],password=os.environ['LEDGER_DB_PASSWORD'],
  host=os.environ['LEDGER_DB_HOST'],port=int(os.environ.get('LEDGER_DB_PORT',5432)),
  database=os.environ['LEDGER_DB_NAME'],ssl_context=ssl._create_unverified_context(),timeout=900)
dj={e:(dc if rr==JUL else dl) for e,rr,rl,dc,dl in c.run(f"""SELECT lower(trim(email)),champion_run_id,
   challenger_run_id,decil_champion,decil_challenger FROM public.registros_ml
 WHERE ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo')::date BETWEEN '2026-07-21' AND '2026-08-03'
   AND email IS NOT NULL AND (champion_run_id='{JUL}' OR challenger_run_id='{JUL}')""")}
c.close()
C['decil_jul']=C['email'].map(dj)
C.to_pickle(S+'criativo_leads.pkl')
print(f"cobertura na base cheia · abr_28 {C['decil'].notna().sum():,} · jul_24 {C['decil_jul'].notna().sum():,}")

def katz(a,na,b,nb):
    if a==0 or b==0 or na==0 or nb==0: return (None,None)
    rr=(a/na)/(b/nb); se=math.sqrt(1/a-1/na+1/b-1/nb)
    return (rr*math.exp(-1.96*se), rr*math.exp(1.96*se))
def ca(dist):
    ns=[];xs=[];ts=[]
    for d in sorted(dist):
        n,x=dist[d]
        if n>0: ns.append(n);xs.append(x);ts.append(float(d))
    N=sum(ns);X=sum(xs)
    if N==0 or X==0 or X==N or len(ns)<3: return (None,None)
    p=X/N; T=sum(t*(x-n*p) for t,n,x in zip(ts,ns,xs))
    S2=p*(1-p)*(sum(n*t*t for n,t in zip(ns,ts))-(sum(n*t for n,t in zip(ns,ts))**2)/N)
    if S2<=0: return (None,None)
    z=T/math.sqrt(S2); return (z,2*(1-norm.cdf(abs(z))))
def linha(d,col,rot):
    d=d[d[col].notna()].copy(); d[col]=pd.to_numeric(d[col],errors='coerce')
    if d.empty: return None
    top=d[d[col]>=9]; res=d[d[col]<9]; bot=d[d[col]<=2]
    a,na=int(top['conv'].sum()),len(top); b,nb=int(res['conv'].sum()),len(res)
    c2,nb2=int(bot['conv'].sum()),len(bot)
    lo,hi=katz(a,na,b,nb)
    if nb2==0: lb,st=None,'sem fundo'
    elif c2==0: lb,st=(a/na)/(3.0/nb2),'piso'
    else: lb,st=(a/na)/(c2/nb2),'ok'
    z,pv=ca({int(k):(len(v),int(v['conv'].sum())) for k,v in d.groupby(col)})
    return dict(rot=rot,leads=len(d),n_top=na,pct_top=na/len(d)*100,comp_top=a,
      conv_top=(a/na*100 if na else None),n_bot=nb2,pct_bot=nb2/len(d)*100,comp_bot=c2,
      conv_bot=(c2/nb2*100 if nb2 else None),conv_resto=(b/nb*100 if nb else None),
      lift_resto=((a/na)/(b/nb) if na and nb and b else None),lr_lo=lo,lr_hi=hi,
      lift_bottom=lb,lb_status=st,ca_z=z,ca_p=pv,comp_total=int(d['conv'].sum()))

pag=set(U[U['gasto']>0]['criativo'])
out={}
for col,tag in (('decil','abr28'),('decil_jul','jul24')):
    CC=C[C['criativo'].isin(pag)&C[col].notna()]
    gr=CC.groupby('criativo').size().sort_values(ascending=False)
    L=[linha(CC[CC['criativo']==k],col,k) for k in gr[gr>=300].index]+[linha(CC,col,'TODOS (agregado)')]
    out[tag]=[x for x in L if x]
    ag=out[tag][-1]
    print(f"{tag}: criativo fixo -> lift vs resto {ag['lift_resto']:.2f}x  bottom {ag['lift_bottom']:.2f}x  "
          f"CA z={ag['ca_z']:.2f} p={ag['ca_p']:.5f}  ({ag['comp_total']} compradores)")
json.dump(out,open(S+'criativo_fixo.json','w'),ensure_ascii=False,indent=1,default=float)

# matriz lucro do criativo por campanha
piv=U[U['gasto']>0].pivot_table(index='criativo',columns='cat',values='lucro',aggfunc='sum').fillna(0.0)
gs=U[U['gasto']>0].groupby('criativo')['gasto'].sum()
piv=piv.loc[gs[gs>=400].sort_values(ascending=False).index]
piv.to_pickle(S+'lucro_por_campanha.pkl')
print('\nmatriz lucro criativo x campanha:',piv.shape)
print(piv.round(0).to_string())
