# -*- coding: utf-8 -*-
"""DEV21 criativo, partes 2-4: por tipo de campanha, fatia de verba x conversao, lift D9+D10 dentro do criativo."""
import os,sys,math,re
import pandas as pd
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
uni=pd.read_pickle(S+'criativo_unidades.pkl'); L=pd.read_pickle(S+'criativo_leads.pkl')
def br(x,k=2):
    if x is None or (isinstance(x,float) and (pd.isna(x) or math.isinf(x))) or pd.isna(x): return '·'
    return f'{x:,.{k}f}'.replace(',','X').replace('.',',').replace('X','.')
def rr_ci(a,na,b,nb):
    if a==0 or b==0 or na==0 or nb==0: return (None,None)
    rr=(a/na)/(b/nb); se=math.sqrt(1/a-1/na+1/b-1/nb)
    return (rr*math.exp(-1.96*se), rr*math.exp(1.96*se))

# ---- separa criativo PAGO de conteudo sem verba (organico/mensageria)
uni['pago']=uni['gasto']>0
pagas=uni[uni['pago']].copy()
sem=uni[~uni['pago']]
print('='*128)
print('0) FRONTEIRA DO QUE E "CRIATIVO"')
print(f"   com verba:  {len(pagas):>4} unidades criativo×campanha · R$ {br(pagas['gasto'].sum()):>12} · "
      f"{int(pagas['leads'].sum()):>6,} leads · {int(pagas['comp'].sum()):>3} compradores")
print(f"   sem verba:  {len(sem):>4} unidades (conteudo de trafego organico/mensageria, NAO e criativo pago) · "
      f"{int(sem['leads'].sum()):>6,} leads · {int(sem['comp'].sum()):>3} compradores")
print('   (as tabelas abaixo usam SO o que tem verba; sem isso o ROAS da cauda vira infinito)')

ORD=['HQLB · QUENTE','HQLB · FRIO','Google Ads','TOP50 · FRIO','TOP30 · FRIO','TOP10 · FRIO','Lead · FRIO','Lead · QUENTE']
# ---- 2 e 3) criativo DENTRO de cada tipo de campanha
print('\n'+'='*128)
print('2+3) CADA CRIATIVO DENTRO DE CADA TIPO DE CAMPANHA  ·  fatia de verba contra a conversao que ela comprou')
for cat in ORD:
    g=pagas[pagas['cat']==cat].sort_values('gasto',ascending=False)
    if g.empty: continue
    GT=g['gasto'].sum(); LT=g['leads'].sum(); CT=g['comp'].sum()
    base=CT/LT if LT else 0
    print(f"\n▸ {cat}   ·  verba R$ {br(GT)}  ·  {int(LT):,} leads  ·  {int(CT)} compradores  ·  conversao da campanha {br(base*100,3)}%")
    print(f"   {'Criativo':<50} {'gasto':>11} {'%verba':>7} {'leads':>7} {'%leads':>7} {'CPL':>6} {'comp':>5} {'conv':>7} {'ROAS':>6} {'lucro':>11}")
    print('   '+'-'*122)
    for _,r in g.iterrows():
        if r['gasto']<GT*0.005 and r['comp']==0: continue
        conv=r['comp']/r['leads'] if r['leads'] else None
        print(f"   {str(r['criativo'])[:48]:<50} {br(r['gasto']):>11} {br(r['gasto']/GT*100,1)+'%':>7} {int(r['leads']):>7,} "
              f"{br(r['leads']/LT*100,1)+'%':>7} {br(r['gasto']/r['leads']) if r['leads'] else '·':>6} {int(r['comp']):>5} "
              f"{br(conv*100,2)+'%' if conv is not None else '·':>7} {br(r['fat']/r['gasto']) if r['gasto'] else '·':>6} {br(r['lucro']):>11}")
    # heterogeneidade MEDIDA entre criativos da mesma campanha (qui-quadrado de homogeneidade)
    gg=g[g['leads']>=200]
    if len(gg)>=2:
        p=gg['comp'].sum()/gg['leads'].sum()
        chi=sum(((r['comp']-r['leads']*p)**2)/(r['leads']*p*(1-p)) for _,r in gg.iterrows())
        gl=len(gg)-1
        from scipy.stats import chi2 as _chi2
        p_val=float(_chi2.sf(chi,gl))
        lo=gg.loc[gg['comp'].div(gg['leads']).idxmin()]; hi=gg.loc[gg['comp'].div(gg['leads']).idxmax()]
        print(f"   → entre os {len(gg)} criativos com 200+ leads: pior {br(lo['comp']/lo['leads']*100,2)}%  "
              f"melhor {br(hi['comp']/hi['leads']*100,2)}%  ·  amplitude {br((hi['comp']/hi['leads'])/(lo['comp']/lo['leads']),2)}x  "
              f"·  qui-quadrado={br(chi,1)} (gl={gl}, p≈{br(p_val,3)})")

# ---- 4) lift do D9+D10 DENTRO de cada criativo
print('\n'+'='*128)
print('4) LIFT DO D9+D10 DENTRO DE CADA CRIATIVO (regua abr_28)  ·  o criativo fica FIXO, so o modelo varia')
d=L[L['decil'].notna()&L['criativo'].notna()].copy()
d['decil']=pd.to_numeric(d['decil'],errors='coerce')
paga_nomes=set(pagas['criativo'])
d=d[d['criativo'].isin(paga_nomes)]
print(f"{'Criativo':<50} {'leads':>7} {'D9+D10':>7} {'%topo':>6} {'conv topo':>10} {'comp':>5} {'conv resto':>11} "
      f"{'lift vs média':>14} {'lift vs resto':>14} {'IC95':>16}")
print('-'*128)
est=[]
for cri,g in d.groupby('criativo'):
    top=g[g['decil']>=9]; res=g[g['decil']<9]
    a,na=int(top['conv'].sum()),len(top); b,nb=int(res['conv'].sum()),len(res)
    if len(g)<300: continue
    est.append((a,na,b,nb))
    if a<5:
        print(f"{str(cri)[:48]:<50} {len(g):>7,} {na:>7,} {br(na/len(g)*100,1)+'%':>6} {'·':>10} {a:>5} {'·':>11} "
              f"{'·':>14} {'·':>14} {'RUÍDO':>16}"); continue
    ct=a/na; crest=b/nb if nb else 0; cc=g['conv'].mean(); lo,hi=rr_ci(a,na,b,nb)
    print(f"{str(cri)[:48]:<50} {len(g):>7,} {na:>7,} {br(na/len(g)*100,1)+'%':>6} {br(ct*100,3)+'%':>10} {a:>5} "
          f"{br(crest*100,3)+'%':>11} {br(ct/cc)+'x':>14} {br(ct/crest)+'x':>14} "
          f"{(br(lo)+' a '+br(hi)) if lo else '·':>16}")
def mh(estr):
    num=den=Sp=0.0
    for a,n1,b,n0 in estr:
        N=n1+n0
        if N==0 or n1==0 or n0==0: continue
        num+=a*n0/N; den+=b*n1/N; Sp+=((n1*n0*(a+b)-a*b*N)/N**2)
    if not den or not num: return (None,None,None)
    rr=num/den; var=Sp/(num*den)
    se=math.sqrt(var) if var>0 else None
    return (rr, rr*math.exp(-1.96*se) if se else None, rr*math.exp(1.96*se) if se else None)
rr,lo,hi=mh(est)
print('-'*128)
print(f"{'ESTRATIFICADO POR CRIATIVO (MH)':<50} {'':>7} {'':>7} {'':>6} {'':>10} {'':>5} {'':>11} {'':>14} "
      f"{br(rr)+'x':>14} {(br(lo)+' a '+br(hi)) if lo else '·':>16}")
print('  = o modelo separa MESMO segurando o criativo fixo? Este e o numero que responde.')
