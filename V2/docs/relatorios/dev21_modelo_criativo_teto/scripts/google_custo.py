# -*- coding: utf-8 -*-
"""Custo por ANUNCIO no Google na janela do DEV21. So LE da API, nao escreve no banco."""
import os,sys,json
sys.path.insert(0,'/Users/ramonmoreira/Desktop/bring_data/V2'); os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
import requests as rq
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
cid=os.getenv('GOOGLE_ADS_CUSTOMER_ID','').replace('-',''); dev=os.getenv('GOOGLE_ADS_DEVELOPER_TOKEN')
tok=rq.post('https://oauth2.googleapis.com/token',data={
  'client_id':os.getenv('GOOGLE_ADS_CLIENT_ID'),'client_secret':os.getenv('GOOGLE_ADS_CLIENT_SECRET'),
  'refresh_token':os.getenv('GOOGLE_ADS_REFRESH_TOKEN'),'grant_type':'refresh_token'},timeout=30).json().get('access_token')
if not tok: print('TOKEN FALHOU'); sys.exit(1)
H={'Authorization':f'Bearer {tok}','developer-token':dev,
   'login-customer-id':os.getenv('GOOGLE_ADS_LOGIN_CUSTOMER_ID',cid).replace('-','')}
q=("SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group.name, campaign.name, campaign.id, "
   "metrics.cost_micros, metrics.impressions, metrics.clicks "
   "FROM ad_group_ad WHERE segments.date BETWEEN '2026-07-21' AND '2026-08-03'")
r=rq.post(f'https://googleads.googleapis.com/v22/customers/{cid}/googleAds:searchStream',
          headers=H,json={'query':q},timeout=180)
print('HTTP',r.status_code)
if r.status_code!=200: print(str(r.text)[:500]); sys.exit(1)
out={}
for bl in r.json():
    for row in bl.get('results',[]):
        ad=row.get('adGroupAd',{}).get('ad',{}); m=row.get('metrics',{})
        i=str(ad.get('id') or '')
        if not i: continue
        nome=ad.get('name') or row.get('adGroup',{}).get('name') or ''
        d=out.setdefault(i,{'ad_name':f'[G] {" ".join(str(nome).split())}',
            'campaign_name':' '.join(str(row.get('campaign',{}).get('name') or '').split()),
            'campaign_id':str(row.get('campaign',{}).get('id') or ''),'custo':0.0,'impr':0,'cliques':0})
        d['custo']+=float(m.get('costMicros') or 0)/1e6
        d['impr']+=int(m.get('impressions') or 0); d['cliques']+=int(m.get('clicks') or 0)
tot=sum(v['custo'] for v in out.values())
print(f'anuncios com custo: {sum(1 for v in out.values() if v["custo"]>0)} de {len(out)} · total R$ {tot:,.2f}')
print('(ad_spend do banco marca R$ 32.171,97 no google na mesma janela)')
json.dump(out,open(S+'google_custo.json','w'),ensure_ascii=False,indent=1)
for i,(k,v) in enumerate(sorted(out.items(),key=lambda x:-x[1]['custo'])[:15]):
    print(f'  R$ {v["custo"]:>9,.2f} {k:<15} {v["ad_name"][:50]:<52} {v["campaign_name"][:38]}')
