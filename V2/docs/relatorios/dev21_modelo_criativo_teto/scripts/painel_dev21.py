# -*- coding: utf-8 -*-
"""Painel DEV21 por CAMPANHA e por TIPO, reusando a maquina canonica do relatorio
(mesmo casamento, mesmo haircut de boleto, mesmo imposto Meta, mesmos produtos de lancamento)."""
import os, sys, re, json, unicodedata
from datetime import date
os.environ.setdefault('LAUNCHES_SOURCE','table')
sys.path.insert(0,'/Users/ramonmoreira/Desktop/bring_data/V2'); os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv
load_dotenv('/Users/ramonmoreira/Desktop/bring_data/V2/.env')
import pandas as pd
from src.core.launches import load_launches
from src.validation.model_performance import (
    _open_real_readers, _load_matched, _bucket_metrics,
    _load_boleto_haircut, _load_meta_gross_up,
)

LF='DEV21'; AS_OF=date.today(); WINDOW=60
HAIRCUT=_load_boleto_haircut(); GROSSUP=_load_meta_gross_up()
print(f'haircut boleto={HAIRCUT} · imposto Meta={GROSSUP} · as_of={AS_OF} · janela={WINDOW}d')

rd = _open_real_readers()
ledger_reader, sales_reader, spend_reader, cadastro_reader, coverage_reader, closer = rd
m = _load_matched(LF, ledger_reader=ledger_reader, sales_reader=sales_reader,
                  spend_reader=spend_reader, cadastro_reader=cadastro_reader,
                  as_of=AS_OF, window_days=WINDOW, launches=load_launches())
neg = m['matched_negocio']; mod = m['matched_modelo']; spend = m['spend_df']
print(f"captacao {m['cap_start']} a {m['cap_end']} · vendas {m['vendas_start']} a {m['vendas_end']}")
print(f'cadastros={len(neg):,} · respondentes={len(mod):,} · linhas de gasto={len(spend):,}')
print('colunas do cadastro:', [c for c in neg.columns][:18])

# ---------- extrair campaign_id dos dois lados ----------
def cid_lead(src, camp, term):
    s=str(src or '').lower()
    if 'google' in s:
        t=str(term or '')
        mm=re.match(r'^(\d{6,})', t)
        return mm.group(1) if mm else None
    c=str(camp or '')
    mm=re.search(r'(\d{10,})\s*$', c)
    return mm.group(1) if mm else None

for df in (neg, mod):
    df['cid']=[cid_lead(a,b,cc) for a,b,cc in zip(
        df.get('utm_source'), df.get('utm_campaign'), df.get('utm_term', pd.Series([None]*len(df))))]

print('\ncobertura de campaign_id nos cadastros:')
print('  com cid:', int(neg['cid'].notna().sum()), ' sem cid:', int(neg['cid'].isna().sum()))

# ---------- gasto por campanha ----------
sp=spend.copy()
sp['plat']=sp['platform'].astype(str).str.strip().str.lower()
sp['gasto']=pd.to_numeric(sp['spend'],errors='coerce').fillna(0.0)*sp['plat'].map(
    lambda p: GROSSUP if p=='meta' else 1.0)
sp['cid']=sp['campaign_id'].astype(str).str.strip()
gasto=sp.groupby(['cid','plat'],dropna=False).agg(
    gasto=('gasto','sum'), nome=('campaign_name','last')).reset_index()

# ---------- classificacao ----------
def norm(s): return unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().upper()
def classifica(nome, plat):
    N=norm(nome)
    if plat=='google':
        ev='HQLQ' if 'HQLQ' in N else 'Conversao Google'
        return 'Google','Frio',ev
    temp = 'Quente' if 'QUENTE' in N else ('Frio' if 'FRIO' in N else 'Sem rotulo')
    if 'JUL24' in N:
        ev = next((t for t in ('JUL24_TOP10','JUL24_TOP30','JUL24_TOP50') if t in N), 'JUL24')
        return 'Challenger (jul_24)', temp, ev
    if 'LEADHQLB' in N or 'HQLB' in N:
        return 'Champion (abr_28)', temp, 'HQLB'
    return 'Lead Padrao (Meta)', temp, 'Lead'

gasto[['tipo','temp','evento']]=gasto.apply(
    lambda r: pd.Series(classifica(r['nome'], r['plat'])), axis=1)
mapa={r['cid']:(r['tipo'],r['temp'],r['evento'],r['nome'],r['plat']) for _,r in gasto.iterrows()}

def metricas(bdf, inv, rot):
    b=_bucket_metrics(bdf, rot, rot, investimento=inv, haircut=HAIRCUT)
    return dict(leads=b.n_leads, cpl=b.cpl, conv=b.conversion_rate, n_vendas=b.n_conversions,
                cart=b.compradores_cartao, bol=b.compradores_boleto,
                fatur=b.faturamento, roas=b.roas, lucro=b.lucro, invest=b.investimento)

linhas=[]
for cid, g in gasto.groupby('cid'):
    inv=float(g['gasto'].sum()); nome=g['nome'].iloc[-1]; plat=g['plat'].iloc[-1]
    tipo,temp,ev = classifica(nome, plat)
    bdf = neg[neg['cid']==cid]
    r=metricas(bdf, inv, nome)
    r.update(cid=cid, nome=nome, plat=plat, tipo=tipo, temp=temp, evento=ev)
    linhas.append(r)
# leads sem campanha paga (organico/mensageria/sem cid)
cids=set(gasto['cid'])
orf = neg[~neg['cid'].isin(cids)]
if len(orf):
    r=metricas(orf, None, 'Organico / sem campanha paga')
    r.update(cid='—', nome='Organico, mensageria e leads sem campanha paga', plat='—',
             tipo='Organico/Outro', temp='—', evento='—')
    linhas.append(r)

df=pd.DataFrame(linhas).sort_values('invest', ascending=False, na_position='last')
df.to_pickle('/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/painel_dev21.pkl')

def fmt(v,d=2,pc=False):
    if v is None or (isinstance(v,float) and pd.isna(v)): return '—'
    if pc: return f'{v*100:.2f}%'
    return f'{v:,.{d}f}'.replace(',','X').replace('.',',').replace('X','.')

print('\n' + '='*168)
print('PAINEL POR CAMPANHA — DEV21')
print(f"{'campanha':<62} {'tipo':<20} {'temp':<7} {'evento':<12} {'gasto':>12} {'leads':>7} {'CPL':>7} {'conv':>7} {'vendas':>6} {'fatur':>13} {'ROAS':>6} {'lucro':>13}")
print('-'*168)
for _,r in df.iterrows():
    print(f"{str(r['nome'])[:62]:<62} {r['tipo']:<20} {r['temp']:<7} {r['evento']:<12} "
          f"{fmt(r['invest']):>12} {r['leads']:>7,} {fmt(r['cpl']):>7} {fmt(r['conv'],pc=True):>7} "
          f"{r['n_vendas']:>6} {fmt(r['fatur']):>13} {fmt(r['roas']):>6} {fmt(r['lucro']):>13}")
closer()
