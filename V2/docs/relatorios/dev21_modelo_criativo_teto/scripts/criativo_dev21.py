# -*- coding: utf-8 -*-
"""DEV21 - VARIAVEL CRIATIVO: agregado, por tipo de campanha, fatia de verba x conversao,
e lift do D9+D10 DENTRO de cada criativo. Meta (ad_insights) + Google (API)."""
import os,sys,re,ssl,json,math,unicodedata
os.environ.setdefault('LAUNCHES_SOURCE','table')
sys.path.insert(0,'/Users/ramonmoreira/Desktop/bring_data/V2'); os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
from datetime import date, timedelta
import pandas as pd, pg8000.native
from src.validation.model_performance import _open_real_readers,_load_boleto_haircut,_load_meta_gross_up
from src.core.matching import match_leads_to_sales_unified
from src.core.payment_method import forma_pagamento, CARTAO, BOLETO
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
CAP0,CAP1=date(2026,7,21),date(2026,8,3); V0,V1=date(2026,8,10),date(2026,8,16)
REEMB={'santanabessaricardo@gmail.com','feehkrodrigues10@gmail.com','joaopedrodev67@gmail.com'}
ABR28='5d158f0aa6e54b489498470446194a6c'
H=_load_boleto_haircut(); G=_load_meta_gross_up()
GN=json.load(open(S+'google_ads_nomes.json')); GC=json.load(open(S+'google_custo.json'))

# ---------- vendas ----------
lr,sr,spr,cr,cov,closer=_open_real_readers(); sales=sr(CAP0,V1+timedelta(days=1)); spend=spr(CAP0,CAP1+timedelta(days=1)); closer()
v=sales[(sales['sale_date'].dt.date>=V0)&(sales['sale_date'].dt.date<=V1)].copy()
pl=v['produto'].astype(str).str.lower()
v=v[~(pl.str.contains('opera')|pl.str.contains('50k')|pl.str.contains('mba'))]
v=v[~v['email'].astype(str).str.strip().str.lower().isin(REEMB)]
vl=v['produto'].astype(str).str.lower()
COMBO=vl.str.contains('vital')|vl.str.contains('combo')|vl.str.contains('plano dev')|vl.str.contains('club hub')|vl.str.contains('clubhub')
princ=v[~COMBO].copy()

# ---------- leads: MESMA base do painel (Railway Client×UTMTracking, last-touch na janela)
# so que puxando tambem content/term, que o read_cadastros nao projeta.
from src.data.cadastro_records import open_railway_connection
rc=open_railway_connection()
rows=rc.run('SELECT LOWER(TRIM(c.email)), c.phone, u.campaign, LOWER(u.source), u.content, u.term, u."trackedAt" '
  'FROM "Client" c JOIN "UTMTracking" u ON LOWER(TRIM(u."clientEmail"))=LOWER(TRIM(c.email)) '
  'WHERE (u."trackedAt" - INTERVAL \'3 hours\')::date >= :s AND (u."trackedAt" - INTERVAL \'3 hours\')::date <= :e',
  s=CAP0.isoformat(), e=CAP1.isoformat()); rc.close()
latest={}
for email,phone,camp,src,cont,term,tracked in rows:
    p=latest.get(email)
    if p is None or (tracked is not None and (p[0] is None or tracked>=p[0])):
        latest[email]=(tracked,phone,camp,src,cont,term)
L=pd.DataFrame([{'email':e,'telefone':v[1],'data_captura':v[0],'utm_campaign':v[2],
                 'utm_source':v[3],'utm_content':v[4],'utm_term':v[5]} for e,v in latest.items()])
L['data_captura']=pd.to_datetime(L['data_captura'],utc=True,errors='coerce').dt.tz_localize(None)

c=pg8000.native.Connection(user=os.environ['LEDGER_DB_USER'],password=os.environ['LEDGER_DB_PASSWORD'],
  host=os.environ['LEDGER_DB_HOST'],port=int(os.environ.get('LEDGER_DB_PORT',5432)),
  database=os.environ['LEDGER_DB_NAME'],ssl_context=ssl._create_unverified_context(),timeout=900)
dec={e:(dc if rr==ABR28 else dl) for e,rr,rl,dc,dl in c.run(f"""SELECT lower(trim(email)),champion_run_id,challenger_run_id,
   decil_champion,decil_challenger FROM public.registros_ml
 WHERE ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo')::date BETWEEN '2026-07-21' AND '2026-08-03'
   AND email IS NOT NULL AND (champion_run_id='{ABR28}' OR challenger_run_id='{ABR28}')""")}
c.close()
print(f'leads na base cheia: {len(L):,} · com decil abr_28: {sum(1 for e in L["email"] if e in dec):,}')
L['decil']=L['email'].map(dec)

# ---------- criativo ----------
def nrm(s):
    s=unicodedata.normalize('NFC',str(s or '')).strip()
    return re.sub(r'\s+',' ',s)
def criativo_do(src,content):
    s=str(src or '').lower(); t=nrm(content)
    if not t or t.startswith('{{'): return None
    if 'google' in s:
        g=GN.get(t) or GC.get(t)
        return nrm(g['ad_name']) if g else f'[G] id {t}'
    return t
L['criativo']=[criativo_do(a,b) for a,b in zip(L['utm_source'],L['utm_content'])]
L['familia']=L['criativo'].map(lambda x: (re.search(r'AD\s?0*(\d{2,4})',str(x)).group(0).replace(' ','') if x and re.search(r'AD\s?0*(\d{2,4})',str(x)) else None))

# ---------- categoria da campanha ----------
def norm(s): return unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().upper()
def cat_de(nome,plat):
    N=norm(nome)
    if plat=='google': return 'Google Ads'
    temp='QUENTE' if 'QUENTE' in N else ('FRIO' if 'FRIO' in N else 'S/ROTULO')
    for t in ('JUL24_TOP10','JUL24_TOP30','JUL24_TOP50'):
        if t in N: return f"{t.replace('JUL24_','')} · {temp}"
    if 'HQLB' in N: return f'HQLB · {temp}'
    return f'Lead · {temp}'
sp=spend.copy(); sp['plat']=sp['platform'].astype(str).str.lower().str.strip(); sp['cid']=sp['campaign_id'].astype(str).str.strip()
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

# ---------- conversao ----------
m=match_leads_to_sales_unified(L,princ,mode='validation',use_temporal_validation=True)
cap=pd.to_datetime(m['data_captura'],utc=True,errors='coerce'); sd=pd.to_datetime(m['sale_date'],utc=True,errors='coerce')
dd=(sd-cap).dt.total_seconds()/86400.0
ok=(m['converted'].fillna(False)&sd.notna()&(dd>=0)&(dd<=(V1-CAP0).days+3))
L['conv']=ok.astype(bool).values
fp=m['sale_origin'].apply(lambda o: forma_pagamento(o) if pd.notna(o) else None)
sv=pd.to_numeric(m['sale_value'],errors='coerce').fillna(0)
L['fat']=(sv.where(fp==CARTAO,0)+sv.where(fp==BOLETO,0)*H).where(ok,0).values
print(f'compradores casados: {int(L["conv"].sum())} · faturamento R$ {L["fat"].sum():,.2f}')

# ---------- gasto por criativo x categoria ----------
c=pg8000.native.Connection(user=os.environ['LEDGER_DB_USER'],password=os.environ['LEDGER_DB_PASSWORD'],
  host=os.environ['LEDGER_DB_HOST'],port=int(os.environ.get('LEDGER_DB_PORT',5432)),
  database=os.environ['LEDGER_DB_NAME'],ssl_context=ssl._create_unverified_context(),timeout=600)
ins=c.run("""SELECT ad_name, campaign_id, sum(spend) FROM analytics.ad_insights
 WHERE insight_date BETWEEN '2026-07-21' AND '2026-08-03' GROUP BY 1,2"""); c.close()
gast={}
for nome,camp,g in ins:
    cat=cid2cat.get(str(camp).strip())
    if not cat: continue
    gast[(nrm(nome),cat)]=gast.get((nrm(nome),cat),0.0)+float(g)*G
for aid,d in GC.items():
    if d['custo']<=0: continue
    k=(nrm(d['ad_name']),'Google Ads'); gast[k]=gast.get(k,0.0)+float(d['custo'])
print(f'gasto mapeado por criativo×campanha: R$ {sum(gast.values()):,.2f} em {len(gast)} unidades')

# ---------- montagem ----------
def bloco(df, chave):
    g=df.groupby(chave,dropna=False)
    t=g.agg(leads=('email','size'),comp=('conv','sum'),fat=('fat','sum')).reset_index()
    return t
def fmt(x,k=2): return '·' if x is None or (isinstance(x,float) and (pd.isna(x) or math.isinf(x))) else f'{x:,.{k}f}'.replace(',','X').replace('.',',').replace('X','.')

pagos=L[L['criativo'].notna()].copy()
pagos['gasto']=[gast.get((k,cc),0.0) for k,cc in zip(pagos['criativo'],pagos['cat'])]
uni=pagos.groupby(['criativo','cat']).agg(leads=('email','size'),comp=('conv','sum'),fat=('fat','sum')).reset_index()
uni['gasto']=[gast.get((k,cc),0.0) for k,cc in zip(uni['criativo'],uni['cat'])]
# unidades com gasto mas zero lead entram tambem
for (k,cc),g in gast.items():
    if not ((uni['criativo']==k)&(uni['cat']==cc)).any():
        uni.loc[len(uni)]=[k,cc,0,0,0.0,g]
uni['conv']=uni['comp']/uni['leads'].replace(0,pd.NA)
uni['roas']=uni['fat']/uni['gasto'].replace(0,pd.NA)
uni['lucro']=uni['fat']-uni['gasto']
uni['cpl']=uni['gasto']/uni['leads'].replace(0,pd.NA)
uni.to_pickle(S+'criativo_unidades.pkl'); L.to_pickle(S+'criativo_leads.pkl')

TOTG=uni['gasto'].sum()
print('\n'+'='*136)
print(f'1) AGREGADO POR CRIATIVO (todas as campanhas somadas) · verba mapeada R$ {fmt(TOTG)}')
ag=uni.groupby('criativo').agg(gasto=('gasto','sum'),leads=('leads','sum'),comp=('comp','sum'),fat=('fat','sum')).reset_index()
ag['pct']=ag['gasto']/TOTG*100; ag['conv']=ag['comp']/ag['leads'].replace(0,pd.NA)
ag['roas']=ag['fat']/ag['gasto'].replace(0,pd.NA); ag['lucro']=ag['fat']-ag['gasto']; ag['cpl']=ag['gasto']/ag['leads'].replace(0,pd.NA)
ag=ag.sort_values('gasto',ascending=False)
print(f"{'Criativo':<52} {'gasto':>12} {'%verba':>7} {'leads':>7} {'CPL':>7} {'comp':>5} {'conv':>7} {'ROAS':>6} {'lucro':>12}")
print('-'*136)
acc=0
for _,r in ag.iterrows():
    if r['gasto']<400 and acc/TOTG>0.95: continue
    acc+=r['gasto']
    print(f"{str(r['criativo'])[:50]:<52} {fmt(r['gasto']):>12} {fmt(r['pct'],1)+'%':>7} {int(r['leads']):>7,} "
          f"{fmt(r['cpl']):>7} {int(r['comp']):>5} {fmt(r['conv']*100 if pd.notna(r['conv']) else None,2)+'%':>7} "
          f"{fmt(r['roas']):>6} {fmt(r['lucro']):>12}")
cauda=ag[ag['gasto']<400]
if len(cauda): print(f"{'CAUDA (' + str(len(cauda)) + ' criativos com <R$400)':<52} {fmt(cauda['gasto'].sum()):>12} "
      f"{fmt(cauda['gasto'].sum()/TOTG*100,1)+'%':>7} {int(cauda['leads'].sum()):>7,} {'·':>7} {int(cauda['comp'].sum()):>5} "
      f"{fmt(cauda['comp'].sum()/max(cauda['leads'].sum(),1)*100,2)+'%':>7} "
      f"{fmt(cauda['fat'].sum()/max(cauda['gasto'].sum(),1)):>6} {fmt(cauda['fat'].sum()-cauda['gasto'].sum()):>12}")
