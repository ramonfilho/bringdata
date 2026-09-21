# -*- coding: utf-8 -*-
"""Resolve os ad_id do Google do DEV21 em nome, pela mesma GAQL do resolvedor diario.
SO LE da API do Google; NAO escreve no banco (a gravacao no criativo_id_map e passo a parte)."""
import os,sys,ssl,json,time
sys.path.insert(0,'/Users/ramonmoreira/Desktop/bring_data/V2'); os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
import pg8000.native, requests as rq
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
c=pg8000.native.Connection(user=os.environ['LEDGER_DB_USER'],password=os.environ['LEDGER_DB_PASSWORD'],
  host=os.environ['LEDGER_DB_HOST'],port=int(os.environ.get('LEDGER_DB_PORT',5432)),
  database=os.environ['LEDGER_DB_NAME'],ssl_context=ssl._create_unverified_context(),timeout=600)
W="((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo')::date BETWEEN '2026-07-21' AND '2026-08-03'"
ids=[str(r[0]) for r in c.run(f"""SELECT DISTINCT trim(utm_content) FROM public.registros_ml
 WHERE {W} AND lower(coalesce(utm_source,'')) LIKE '%google%' AND trim(coalesce(utm_content,'')) ~ '^[0-9]{{6,}}$'""")]
ja={str(r[0]):r[1] for r in c.run("SELECT ad_id,ad_name FROM analytics.criativo_id_map WHERE ad_name IS NOT NULL")}
c.close()
falta=[i for i in ids if i not in ja]
print(f'ad_id google distintos no DEV21: {len(ids)} · ja no mapa: {len(ids)-len(falta)} · a resolver: {len(falta)}')

cid=os.getenv('GOOGLE_ADS_CUSTOMER_ID','').replace('-',''); dev=os.getenv('GOOGLE_ADS_DEVELOPER_TOKEN')
tok=rq.post('https://oauth2.googleapis.com/token',data={
  'client_id':os.getenv('GOOGLE_ADS_CLIENT_ID'),'client_secret':os.getenv('GOOGLE_ADS_CLIENT_SECRET'),
  'refresh_token':os.getenv('GOOGLE_ADS_REFRESH_TOKEN'),'grant_type':'refresh_token'},timeout=30).json().get('access_token')
print('token OK' if tok else 'TOKEN FALHOU')
if not tok: sys.exit(1)
H={'Authorization':f'Bearer {tok}','developer-token':dev,
   'login-customer-id':os.getenv('GOOGLE_ADS_LOGIN_CUSTOMER_ID',cid).replace('-','')}
out={}
LOTE=120
for k in range(0,len(falta),LOTE):
    bloco=falta[k:k+LOTE]
    q=("SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group.name, campaign.name, campaign.id "
       f"FROM ad_group_ad WHERE ad_group_ad.ad.id IN ({','.join(bloco)})")
    r=rq.post(f'https://googleads.googleapis.com/v22/customers/{cid}/googleAds:searchStream',
              headers=H,json={'query':q},timeout=90)
    if r.status_code!=200:
        print(f'  lote {k//LOTE}: HTTP {r.status_code} {str(r.text)[:200]}'); continue
    n=0
    for bl in r.json():
        for row in bl.get('results',[]):
            ad=row.get('adGroupAd',{}).get('ad',{})
            nome=ad.get('name') or row.get('adGroup',{}).get('name')
            if ad.get('id') and nome:
                out[str(ad['id'])]={'ad_name':f'[G] {" ".join(str(nome).split())}',
                                    'campaign_name':' '.join(str(row.get('campaign',{}).get('name') or '').split()),
                                    'campaign_id':str(row.get('campaign',{}).get('id') or '')}
                n+=1
    print(f'  lote {k//LOTE}: {n} resolvidos'); time.sleep(1)
print(f'\nRESOLVIDOS {len(out)} de {len(falta)}')
json.dump(out,open(S+'google_ads_nomes.json','w'),ensure_ascii=False,indent=1)
for i,(k,v) in enumerate(sorted(out.items())[:15]): print(f'  {k:<16} {v["ad_name"][:52]:<54} camp={v["campaign_name"][:40]}')
