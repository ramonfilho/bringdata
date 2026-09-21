# -*- coding: utf-8 -*-
"""DEV21 - VARIAVEL MODELO: conversao e lift do D9+D10 por campanha, regua por run_id."""
import os,sys,re,ssl,unicodedata,math
os.environ.setdefault('LAUNCHES_SOURCE','table')
sys.path.insert(0,'/Users/ramonmoreira/Desktop/bring_data/V2'); os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
from datetime import date, timedelta
import pandas as pd, pg8000.native
from src.validation.model_performance import _open_real_readers
from src.core.matching import match_leads_to_sales_unified
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
CAP0,CAP1=date(2026,7,21),date(2026,8,3); V0,V1=date(2026,8,10),date(2026,8,16)
REEMB={'santanabessaricardo@gmail.com','feehkrodrigues10@gmail.com','joaopedrodev67@gmail.com'}
ABR28='5d158f0aa6e54b489498470446194a6c'; JUL24='b085b63681bc4d0d90bdbd466106763a'

lr,sr,spr,cr,cov,closer=_open_real_readers(); sales=sr(CAP0,V1+timedelta(days=1)); spend=spr(CAP0,CAP1+timedelta(days=1)); closer()
v=sales[(sales['sale_date'].dt.date>=V0)&(sales['sale_date'].dt.date<=V1)].copy()
pl=v['produto'].astype(str).str.lower()
v=v[~(pl.str.contains('opera')|pl.str.contains('50k')|pl.str.contains('mba'))]
v=v[~v['email'].astype(str).str.strip().str.lower().isin(REEMB)]
vl=v['produto'].astype(str).str.lower()
COMBO=vl.str.contains('vital')|vl.str.contains('combo')|vl.str.contains('plano dev')|vl.str.contains('club hub')|vl.str.contains('clubhub')
princ=v[~COMBO].copy()

c=pg8000.native.Connection(user=os.environ['LEDGER_DB_USER'],password=os.environ['LEDGER_DB_PASSWORD'],
  host=os.environ['LEDGER_DB_HOST'],port=int(os.environ.get('LEDGER_DB_PORT',5432)),
  database=os.environ['LEDGER_DB_NAME'],ssl_context=ssl._create_unverified_context(),timeout=900)
rows=c.run(f"""SELECT lower(trim(email)) email, phone AS telefone,
  ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo') data_captura,
  utm_source, utm_campaign, utm_term, utm_content,
  champion_run_id, challenger_run_id, decil_champion, decil_challenger
 FROM public.registros_ml
 WHERE ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo')::date BETWEEN '2026-07-21' AND '2026-08-03'
   AND email IS NOT NULL""")
c.close()
L=pd.DataFrame(rows,columns=['email','telefone','data_captura','utm_source','utm_campaign','utm_term',
  'utm_content','champion_run_id','challenger_run_id','decil_champion','decil_challenger'])
L=L.drop_duplicates('email',keep='last').reset_index(drop=True)
print(f'leads respondentes DEV21: {len(L):,}')

def decil_do(run):
    d=pd.Series(pd.NA,index=L.index,dtype='Float64')
    d=d.mask(L['champion_run_id']==run, pd.to_numeric(L['decil_champion'],errors='coerce'))
    d=d.mask(L['challenger_run_id']==run, pd.to_numeric(L['decil_challenger'],errors='coerce'))
    return d
L['d_abr28']=decil_do(ABR28); L['d_jul24']=decil_do(JUL24)
print(f"  regua abr_28 cobre {L['d_abr28'].notna().sum():,} leads · jul_24 cobre {L['d_jul24'].notna().sum():,}")

m=match_leads_to_sales_unified(L,princ,mode='validation',use_temporal_validation=True)
cap=pd.to_datetime(m['data_captura'],utc=True,errors='coerce'); sd=pd.to_datetime(m['sale_date'],utc=True,errors='coerce')
dd=(sd-cap).dt.total_seconds()/86400.0
L['conv']=(m['converted'].fillna(False)&sd.notna()&(dd>=0)&(dd<=(V1-CAP0).days+3)).astype(bool).values
print(f'  compradores casados: {int(L["conv"].sum())}')

# ---- categoria da campanha (mesma logica do painel publicado)
def norm(s): return unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().upper()
def cat_de(nome,plat):
    N=norm(nome)
    if plat=='google': return 'Google Ads'
    temp='QUENTE' if 'QUENTE' in N else ('FRIO' if 'FRIO' in N else 'S/ROTULO')
    for t in ('JUL24_TOP10','JUL24_TOP30','JUL24_TOP50'):
        if t in N: return f"{t.replace('JUL24_','')} · {temp}"
    if 'HQLB' in N: return f'HQLB · {temp}'
    return f'Lead · {temp}'
sp=spend.copy(); sp['plat']=sp['platform'].astype(str).str.lower().str.strip()
sp['cid']=sp['campaign_id'].astype(str).str.strip()
gas=sp[pd.to_numeric(sp['spend'],errors='coerce').fillna(0)>0].groupby('cid').agg(nome=('campaign_name','last'),plat=('plat','last')).reset_index()
cid2cat={r['cid']:cat_de(r['nome'],r['plat']) for _,r in gas.iterrows()}
def cid_de(src,camp,tm):
    s=str(src or '').lower()
    if 'google' in s:
        mm=re.match(r'^(\d{6,})',str(tm or '')); return mm.group(1) if mm else None
    if 'face' in s or s=='fb':
        mm=re.search(r'(\d{10,})\s*$',str(camp or '')); return mm.group(1) if mm else None
    return None
L['cid']=[cid_de(a,b,cc) for a,b,cc in zip(L['utm_source'],L['utm_campaign'],L['utm_term'])]
def catg(r):
    if r['cid'] and r['cid'] in cid2cat: return cid2cat[r['cid']]
    s=str(r['utm_source'] or '').lower()
    if 'google' in s: return 'Google Ads'
    if 'face' in s or s=='fb': return cat_de(str(r['utm_campaign'] or ''),'meta')
    return 'Outro / Orgânico'
L['cat']=L.apply(catg,axis=1)

def rr_ci(a,na,b,nb):
    """IC95 do risco relativo (Katz log). a/na = topo D9+D10, b/nb = resto D1-D8.
    A inferencia e SEMPRE topo-vs-resto (grupos disjuntos); o lift-vs-media e so leitura."""
    if a==0 or b==0 or na==0 or nb==0: return (None,None)
    rr=(a/na)/(b/nb); se=math.sqrt(1/a-1/na+1/b-1/nb)
    return (rr*math.exp(-1.96*se), rr*math.exp(1.96*se))

def mantel_haenszel(estratos):
    """RR agrupado segurando a CAMPANHA fixa + IC95 de Greenland-Robins.
    estratos = [(a,n1,b,n0)] com a/n1 = topo, b/n0 = resto."""
    num=den=0.0; R=Sp=0.0
    for a,n1,b,n0 in estratos:
        N=n1+n0
        if N==0 or n1==0 or n0==0: continue
        num+=a*n0/N; den+=b*n1/N
        Sp+=((n1*n0*(a+b)-a*b*N)/N**2)
    if den==0 or num==0: return (None,None,None)
    rr=num/den; var=Sp/(num*den)
    if var<=0: return (rr,None,None)
    se=math.sqrt(var)
    return (rr, rr*math.exp(-1.96*se), rr*math.exp(1.96*se))

PAGAS=['HQLB · QUENTE','HQLB · FRIO','TOP50 · FRIO','TOP30 · FRIO','TOP10 · FRIO',
       'Lead · FRIO','Lead · QUENTE','Google Ads']
def tabela(col,rot,universo):
    d=L[L[col].notna()].copy()
    if universo is not None: d=d[d['cat'].isin(universo)]
    if d.empty: return
    base_lanc=d['conv'].mean()
    print('\n'+'='*140); print(f'{rot}')
    print(f'média do lançamento nesta régua: {base_lanc*100:.3f}%  ·  n={len(d):,}  ·  compradores={int(d["conv"].sum())}')
    print(f"{'Campanha':<20} {'leads':>7} {'D9+D10':>7} {'%topo':>6} {'conv topo':>10} {'comp':>5} "
          f"{'conv resto':>11} {'conv média':>11} {'lift vs média':>14} {'lift vs resto':>14} {'IC95 vs resto':>16} {'leitura':>8}")
    print('-'*140)
    f=lambda x,k=2: '·' if x is None else f'{x:.{k}f}'
    estr=[]
    for cat,g in d.groupby('cat'):
        top=g[g[col]>=9]; res=g[g[col]<9]
        a,na=int(top['conv'].sum()),len(top); b,nb=int(res['conv'].sum()),len(res)
        ct=a/na if na else 0; crest=b/nb if nb else 0; cc=g['conv'].mean()
        if cat in PAGAS or universo is not None: estr.append((a,na,b,nb))
        if a<5:
            print(f"{cat:<20} {len(g):>7,} {na:>7,} {na/len(g)*100:>5.1f}% {'·':>10} {a:>5} "
                  f"{'·':>11} {cc*100:>10.3f}% {'·':>14} {'·':>14} {'·':>16} {'RUÍDO':>8}"); continue
        lo,hi=rr_ci(a,na,b,nb)
        print(f"{cat:<20} {len(g):>7,} {na:>7,} {na/len(g)*100:>5.1f}% {ct*100:>9.3f}% {a:>5} "
              f"{crest*100:>10.3f}% {cc*100:>10.3f}% {f(ct/cc)+'x':>14} {f(ct/crest)+'x':>14} "
              f"{(f(lo)+' a '+f(hi)) if lo else '·':>16} {'ok':>8}")
    print('-'*140)
    top=d[d[col]>=9]; res=d[d[col]<9]
    a,na=int(top['conv'].sum()),len(top); b,nb=int(res['conv'].sum()),len(res)
    ct=a/na; crest=b/nb; lo,hi=rr_ci(a,na,b,nb)
    print(f"{'SOMA CRUA':<20} {len(d):>7,} {na:>7,} {na/len(d)*100:>5.1f}% {ct*100:>9.3f}% {a:>5} "
          f"{crest*100:>10.3f}% {base_lanc*100:>10.3f}% {f(ct/base_lanc)+'x':>14} {f(ct/crest)+'x':>14} "
          f"{(f(lo)+' a '+f(hi)) if lo else '·':>16} {'infla':>8}")
    rr,lo,hi=mantel_haenszel(estr)
    print(f"{'ESTRATIFICADO (MH)':<20} {'':>7} {'':>7} {'':>6} {'':>10} {'':>5} {'':>11} {'':>11} "
          f"{'':>14} {f(rr)+'x':>14} {(f(lo)+' a '+f(hi)) if lo else '·':>16} {'honesto':>8}")
    print('  lift vs média = topo D9+D10 contra a média da PRÓPRIA campanha (o número que você pediu)')
    print('  lift vs resto = topo D9+D10 contra D1-D8 da mesma campanha (grupos disjuntos: é o que o IC95 mede)')
    print('  SOMA CRUA soma as campanhas e INFLA (o orgânico converte 3,3% e cai 63% no topo)')
    print('  ESTRATIFICADO (MH) segura a campanha fixa: é o veredito sobre o MODELO, sem o efeito de mistura')

HQLB=['HQLB · QUENTE','HQLB · FRIO']; TOPS=['TOP50 · FRIO','TOP30 · FRIO','TOP10 · FRIO']
tabela('d_abr28','MODELO abr_28  ·  TODAS as campanhas  (ele rodou o dinheiro do HQLB o DEV21 inteiro)',None)
tabela('d_abr28','MODELO abr_28  ·  só o território dele (campanhas HQLB)',HQLB)
tabela('d_jul24','MODELO jul_24 (Challenger)  ·  só o território dele (campanhas TOP10/30/50)',TOPS)
tabela('d_jul24','MODELO jul_24  ·  todas as campanhas onde ele tem decil gravado',None)
L.to_pickle(S+'modelo_dev21.pkl'); print('\nsalvo em modelo_dev21.pkl')
