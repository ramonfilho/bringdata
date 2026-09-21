# -*- coding: utf-8 -*-
"""BACKTEST DO TETO no DEV21 - v2, com dois consertos no casamento do historico:
  1) chave NORMALIZADA (NFC + minuscula + espacos colapsados). O ledger grava
     "captação" em NFC e a captacoes em NFD; comparar cru fazia o criativo que tem
     23.179 leads de passado parecer estreante com 331.
  2) prefixo "[G] " do resolvedor do Google removido antes de casar: o video e o
     MESMO que ja rodou na Meta, e o merito relativo do criativo atravessa a plataforma
     (quem cuida do canal e o lift de plataforma, que agora entra tambem).
Decompoe a nota: quanto veio do MODELO (mistura de decis) e quanto do CRIATIVO.
"""
import os,sys,re,unicodedata,json,math
sys.path.insert(0,'/Users/ramonmoreira/Desktop/bring_data/V2'); os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import fisher_exact, mannwhitneyu
from src.data.analytics_connection import open_analytics_connection
from src.monitoring.teto import CalculadoraDeTeto, conversao_prevista_da_unidade, K_HISTORICO_CRIATIVO
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
CAP0='2026-07-21'; MIN_LEADS,MIN_GASTO=100,300.0; LIFT_GOOGLE=1.31

def chave(s):
    """Chave canonica de criativo: tira o prefixo do resolvedor, normaliza Unicode,
    colapsa espaco e baixa a caixa. E o conserto do bug."""
    s=re.sub(r'^\[g\]\s*','',str(s or '').strip(),flags=re.I)
    return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s)).casefold()

an=open_analytics_connection(timeout=900)
conv,as_of=an.run("SELECT conversion,as_of FROM reference_rolling WHERE client_id='devclub' AND window_end='2026-07-13'")[0]
eco=conv.get('economics') or {}
conv=dict(conv); conv['tracking']={'factor':float(eco.get('late_purchase_uplift') or 1.0)}
calc=CalculadoraDeTeto({'conversion':conv,'as_of':str(as_of)})
VPS=float(eco['value_per_sale']); FATOR=float(conv['tracking']['factor'])
cal={r[0]:r[1:] for r in an.run(f"""SELECT lf_name,cap_start,cap_end,vendas_start,vendas_end FROM launch_calendar
 WHERE client_id='devclub' AND vendas_end IS NOT NULL AND cap_end < '{CAP0}'""")}
cap=an.run("SELECT lf,utm_content,lower(trim(email)),phone,captured_at FROM captacoes "
           "WHERE lf IS NOT NULL AND utm_content IS NOT NULL AND email IS NOT NULL")
ven=an.run("SELECT lower(trim(email)),phone,sale_date FROM sales WHERE sale_date IS NOT NULL")
an.close()
def t8(t):
    d=''.join(c for c in str(t or '') if c.isdigit()); return d[-8:] if len(d)>=8 else None
v=pd.DataFrame(ven,columns=['email','tel','dt']); v['dt']=pd.to_datetime(v['dt'],errors='coerce').dt.tz_localize(None)
v['t8']=v['tel'].map(t8)
pe=v.dropna(subset=['email']).groupby('email')['dt'].apply(list).to_dict()
pt=v.dropna(subset=['t8']).groupby('t8')['dt'].apply(list).to_dict()
d=pd.DataFrame(cap,columns=['lf','criativo','email','tel','cap_dt'])
d=d[d['lf'].isin(cal)].drop_duplicates(['lf','criativo','email'])
d['k']=d['criativo'].map(chave)
d['cap_dt']=pd.to_datetime(d['cap_dt'],errors='coerce').dt.tz_localize(None); d=d.dropna(subset=['cap_dt'])
lim={lf:pd.Timestamp(c[3])+pd.Timedelta(days=1) for lf,c in cal.items()}
d['buy']=[int(any(c0<=s<=lim[lf] for s in (pe.get(e,[])+pt.get(t8(t),[]))))
          for lf,e,t,c0 in zip(d['lf'],d['email'],d['tel'],d['cap_dt'])]
hist=defaultdict(lambda:[0,0,0.0])
for lf,g in d.groupby('lf'):
    conv_lf=g['buy'].mean()
    for k,sx in g.groupby('k'):
        hist[k][0]+=len(sx); hist[k][1]+=int(sx['buy'].sum()); hist[k][2]+=len(sx)*conv_lf
print(f"HISTORICO ate 20/07: {len(cal)} lancamentos · {len(d):,} leads · {int(d['buy'].sum()):,} compradores · {len(hist):,} criativos")

U=pd.read_pickle(S+'criativo_unidades.pkl'); L=pd.read_pickle(S+'criativo_leads.pkl'); L=L[L['criativo'].notna()]
dist={}
for (cr,ct),g in L.groupby(['criativo','cat']):
    dd=pd.to_numeric(g['decil'],errors='coerce').dropna().astype(int)
    dist[(cr,ct)]={f'D{int(x):02d}':int(n) for x,n in dd.value_counts().items()}
rows=[]
for _,r in U[U['gasto']>0].iterrows():
    if r['leads']<MIN_LEADS or r['gasto']<MIN_GASTO: continue
    dd=dist.get((r['criativo'],r['cat'])) or {}
    if sum(dd.values())<30: continue
    base=calc.por_mistura_de_decis(dd)
    if not base.ok: continue
    conv_mod=base.conversao/base.fator_rastreamento
    google = r['cat']=='Google Ads'
    if google: conv_mod*=LIFT_GOOGLE
    nh,kh,E=hist.get(chave(r['criativo']),(0,0,0.0))
    cv=conversao_prevista_da_unidade(conv_mod,nh,kh,E,k=K_HISTORICO_CRIATIVO)
    peso=nh/(nh+K_HISTORICO_CRIATIVO) if nh>0 else 0.0
    lift=(kh/E) if E>0 else None
    mult=(cv/conv_mod) if conv_mod else 1.0          # o quanto o CRIATIVO mexeu a nota
    rows.append(dict(criativo=r['criativo'],cat=r['cat'],google=google,leads=int(r['leads']),
        gasto=float(r['gasto']),cpl=float(r['gasto'])/int(r['leads']),comp=int(r['comp']),
        n_hist=nh,peso=peso,lift_cri=lift,mult=mult,conv_mod=conv_mod,conv_final=cv,
        teto_so_modelo=conv_mod*VPS*FATOR/2.0, teto=cv*VPS*FATOR/2.0,
        roas=int(r['comp'])*VPS*FATOR/float(r['gasto'])))
x=pd.DataFrame(rows); x['abaixo']=x['cpl']<=x['teto']; x['quente']=x['cat'].str.contains('QUENTE')
x.to_pickle(S+'teto_v2.pkl')
G=x['gasto']
print(f"\nUNIDADES: {len(x)} · R$ {G.sum():,.2f} ({G.sum()/172838.43*100:.1f}% do lançamento)")
print(f"  ANTES do conserto: 9 de 25 estreantes · peso médio 14,8%")
print(f"  DEPOIS:            {(x['n_hist']==0).sum()} de {len(x)} estreantes · "
      f"peso médio {np.average(x['peso'],weights=G)*100:.1f}% (ponderado por verba)")
print(f"\n== DECOMPOSIÇÃO DA NOTA (ponderada por verba) ==")
print(f"  teto médio só com o MODELO : R$ {np.average(x['teto_so_modelo'],weights=G):.2f}")
print(f"  teto médio COM o criativo  : R$ {np.average(x['teto'],weights=G):.2f}")
print(f"  o criativo mexeu a nota em {(np.average(x['mult'],weights=G)-1)*100:+.1f}% em média · "
      f"amplitude {x['mult'].min():.2f}x a {x['mult'].max():.2f}x")
def julga(df,rot,alvo=2.0):
    a,b=df[df['abaixo']],df[~df['abaixo']]
    if len(a)==0 or len(b)==0:
        print(f"\n  {rot}: {len(a)} dentro / {len(b)} acima — um lado vazio, sem comparação"); return None
    ta,tb=(a['roas']>=alvo).mean(),(b['roas']>=alvo).mean()
    ra=np.average(a['roas'],weights=a['gasto']); rb=np.average(b['roas'],weights=b['gasto'])
    ft=fisher_exact([[int((a['roas']>=alvo).sum()),int((a['roas']<alvo).sum())],
                     [int((b['roas']>=alvo).sum()),int((b['roas']<alvo).sum())]])
    mw=mannwhitneyu(a['roas'],b['roas'],alternative='greater')
    print(f"\n  {rot}")
    print(f"    DENTRO: {len(a):>2} unid · R$ {a['gasto'].sum():>9,.0f} · {100*ta:>3.0f}% batem ROAS 2 · ROAS {ra:.2f}")
    print(f"    ACIMA : {len(b):>2} unid · R$ {b['gasto'].sum():>9,.0f} · {100*tb:>3.0f}% batem ROAS 2 · ROAS {rb:.2f}")
    print(f"    razão {ra/rb:.2f}x · Fisher p={ft.pvalue:.3f} · Mann-Whitney p={mw.pvalue:.3f}")
    return dict(na=len(a),nb=len(b),ga=a['gasto'].sum(),gb=b['gasto'].sum(),ta=ta,tb=tb,ra=ra,rb=rb,
                razao=ra/rb,fisher=ft.pvalue,mw=mw.pvalue)
print('\n'+'='*104); print('BACKTEST v2 · histórico casado direito + lift de plataforma no Google'); print('='*104)
R={'tudo':julga(x,'TUDO'),'sem_quente':julga(x[~x['quente']],'SEM O PÚBLICO QUENTE'),
   'so_quente':julga(x[x['quente']],'SÓ O PÚBLICO QUENTE')}
json.dump(R,open(S+'teto_v2_res.json','w'),default=float,indent=1)
print('\n'+'='*118); print('UNIDADE A UNIDADE'); print('='*118)
print(f"{'Criativo':<38} {'Campanha':<15} {'gasto':>9} {'CPL':>6} {'histórico':>10} {'peso':>6} {'lift':>6} "
      f"{'teto modelo':>12} {'teto final':>11} {'':^8} {'ROAS':>6}")
for _,r in x.sort_values('gasto',ascending=False).iterrows():
    _lf = f"{r['lift_cri']:.2f}" if r['lift_cri'] else '-'
    print(f"{str(r['criativo'])[:36]:<38} {r['cat'][:14]:<15} {r['gasto']:>9,.0f} {r['cpl']:>6.2f} "
          f"{r['n_hist']:>10,} {r['peso']*100:>5.0f}% {_lf:>6} "
          f"{r['teto_so_modelo']:>12.2f} {r['teto']:>11.2f} {('DENTRO' if r['abaixo'] else 'acima'):^8} {r['roas']:>6.2f}")
