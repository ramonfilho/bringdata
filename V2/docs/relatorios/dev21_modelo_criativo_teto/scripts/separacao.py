# -*- coding: utf-8 -*-
"""DEV21 - regua de separacao FINAL: lift vs resto, lift vs bottom (D1-D2) e Cochran-Armitage.
Roda sobre modelo (por campanha) e sobre criativo. Salva JSON pro artefato."""
import os,sys,math,json
import pandas as pd
from scipy.stats import norm, chi2
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
M=pd.read_pickle(S+'modelo_dev21.pkl')      # respondentes, decil por run_id
C=pd.read_pickle(S+'criativo_leads.pkl')    # base cheia, criativo + decil abr_28
U=pd.read_pickle(S+'criativo_unidades.pkl')

def katz(a,na,b,nb):
    if a==0 or b==0 or na==0 or nb==0: return (None,None)
    rr=(a/na)/(b/nb); se=math.sqrt(1/a-1/na+1/b-1/nb)
    return (rr*math.exp(-1.96*se), rr*math.exp(1.96*se))

def lift_bottom(a,na,b,nb):
    """D9+D10 contra D1-D2. Se o fundo nao teve comprador, devolve o PISO do lift
    (regra de tres: com 0 em nb leads, a taxa do fundo e no maximo 3/nb a 95%)."""
    if na==0 or nb==0: return (None,None,None,'sem leads no fundo')
    ct=a/na
    if b==0:
        teto_fundo=3.0/nb                       # limite superior 95% da taxa do fundo
        return (ct/teto_fundo, None, None, 'piso')   # o lift real e MAIOR que isso
    rr=ct/(b/nb); lo,hi=katz(a,na,b,nb)
    return (rr,lo,hi,'ok')

def cochran_armitage(dist):
    """Tendencia monotona da conversao ao longo dos 10 decis. dist={decil:(n,x)}.
    Usa a ORDEM dos 10 grupos, nao um corte binario: e o teste com mais poder aqui."""
    ns=[];xs=[];ts=[]
    for d in sorted(dist):
        n,x=dist[d]
        if n>0: ns.append(n); xs.append(x); ts.append(float(d))
    N=sum(ns); X=sum(xs)
    if N==0 or X==0 or X==N or len(ns)<3: return (None,None,None)
    p=X/N
    T=sum(t*(x-n*p) for t,n,x in zip(ts,ns,xs))
    S2=p*(1-p)*(sum(n*t*t for n,t in zip(ns,ts)) - (sum(n*t for n,t in zip(ns,ts))**2)/N)
    if S2<=0: return (None,None,None)
    z=T/math.sqrt(S2)
    return (z, 2*(1-norm.cdf(abs(z))), X)

def linha(g,col,rot):
    d=g[g[col].notna()].copy(); d[col]=pd.to_numeric(d[col],errors='coerce')
    if d.empty: return None
    top=d[d[col]>=9]; res=d[d[col]<9]; bot=d[d[col]<=2]
    a,na=int(top['conv'].sum()),len(top)
    b,nb=int(res['conv'].sum()),len(res)
    c2,nb2=int(bot['conv'].sum()),len(bot)
    lr=(a/na)/(b/nb) if (na and nb and b) else None
    lo,hi=katz(a,na,b,nb)
    lb,blo,bhi,st=lift_bottom(a,na,c2,nb2)
    dist={int(k):(len(v),int(v['conv'].sum())) for k,v in d.groupby(col)}
    z,pv,X=cochran_armitage(dist)
    return dict(rot=rot,leads=len(d),n_top=na,pct_top=(na/len(d)*100 if len(d) else None),
        comp_top=a,conv_top=(a/na*100 if na else None),
        n_resto=nb,comp_resto=b,conv_resto=(b/nb*100 if nb else None),
        n_bot=nb2,pct_bot=(nb2/len(d)*100 if len(d) else None),comp_bot=c2,
        conv_bot=(c2/nb2*100 if nb2 else None),
        lift_resto=lr,lr_lo=lo,lr_hi=hi,
        lift_bottom=lb,lb_status=st,lb_lo=blo,lb_hi=bhi,
        ca_z=z,ca_p=pv,comp_total=int(d['conv'].sum()))

def br(x,k=2):
    if x is None or (isinstance(x,float) and (pd.isna(x) or math.isinf(x))): return '·'
    return f'{x:,.{k}f}'.replace(',','X').replace('.',',').replace('X','.')
def mostra(L,titulo):
    print('\n'+'='*142); print(titulo)
    print(f"{'':<22} {'leads':>7} {'%D1-D2':>7} {'conv fundo':>11} {'%D9-D10':>8} {'conv topo':>10} {'conv resto':>11} "
          f"{'lift vs resto':>14} {'IC95':>15} {'lift vs bottom':>15} {'Cochran-Armitage':>19}")
    print('-'*142)
    for r in L:
        if r is None: continue
        ruido = r['comp_top']<5
        lb = ('·' if r['lift_bottom'] is None else
              (f">{br(r['lift_bottom'])}x" if r['lb_status']=='piso' else f"{br(r['lift_bottom'])}x"))
        ca = ('·' if r['ca_p'] is None else f"z={br(r['ca_z'])} p={br(r['ca_p'],4)}"+('  ✓' if r['ca_p']<0.05 else ''))
        print(f"{r['rot'][:21]:<22} {r['leads']:>7,} {br(r['pct_bot'],1)+'%':>7} "
              f"{(br(r['conv_bot'],3)+'%') if r['n_bot'] else '·':>11} {br(r['pct_top'],1)+'%':>8} "
              f"{(br(r['conv_top'],3)+'%') if not ruido else '·':>10} {br(r['conv_resto'],3)+'%':>11} "
              f"{(br(r['lift_resto'])+'x') if (r['lift_resto'] and not ruido) else ('RUÍDO' if ruido else '·'):>14} "
              f"{(br(r['lr_lo'])+'-'+br(r['lr_hi'])) if r['lr_lo'] and not ruido else '·':>15} "
              f"{lb if not ruido else '·':>15} {ca:>19}")

ABR='d_abr28'; JUL='d_jul24'
ORD=['HQLB · QUENTE','HQLB · FRIO','Google Ads','TOP50 · FRIO','TOP30 · FRIO','TOP10 · FRIO','Lead · FRIO','Outro / Orgânico']
out={}
L=[linha(M[M['cat']==c],ABR,c) for c in ORD]+[linha(M,ABR,'TODAS (agregado)')]
mostra(L,'MODELO abr_28 · separacao por campanha'); out['abr28']=[x for x in L if x]
HQ=M[M['cat'].isin(['HQLB · QUENTE','HQLB · FRIO'])]
L2=[linha(HQ,ABR,'HQLB (território)')]
mostra(L2,'MODELO abr_28 · só o território dele'); out['abr28_terr']=[x for x in L2 if x]
TOPS=M[M['cat'].isin(['TOP50 · FRIO','TOP30 · FRIO','TOP10 · FRIO'])]
L3=[linha(M[M['cat']==c],JUL,c) for c in ['HQLB · QUENTE','Google Ads']]+[
   linha(TOPS,JUL,'TOP10/30/50 (território)'),linha(M,JUL,'TODAS (agregado)')]
mostra(L3,'MODELO jul_24 · separacao'); out['jul24']=[x for x in L3 if x]

pag=set(U[U['gasto']>0]['criativo'])
CC=C[C['criativo'].isin(pag)&C['decil'].notna()].copy()
gr=CC.groupby('criativo').size().sort_values(ascending=False)
L4=[linha(CC[CC['criativo']==k],'decil',k[:21]) for k in gr[gr>=300].index]+[linha(CC,'decil','TODOS (agregado)')]
mostra(L4,'MODELO abr_28 DENTRO de cada criativo (criativo fixo, so o modelo varia)')
out['por_criativo']=[x for x in L4 if x]
json.dump(out,open(S+'separacao.json','w'),ensure_ascii=False,indent=1,default=float)
print('\n(lift vs bottom = D9+D10 contra D1-D2 · ">Nx" = o fundo nao teve comprador, entao N e o PISO do lift)')
print('(Cochran-Armitage usa os 10 decis em ordem; ✓ = p<0,05)')
