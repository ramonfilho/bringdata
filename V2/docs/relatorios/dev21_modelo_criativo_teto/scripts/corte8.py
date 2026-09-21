# -*- coding: utf-8 -*-
"""Pergunta do Ramon: historicamente, D7-D10 seria melhor que o D8-D10 QUE ENVIAMOS?
(D9-D10 e so referencia de relatorio; o evento pra Meta corta em D8.)

Duas leituras, na serie fria LF56 -> DEV21:
  a) separacao: lift do corte vs o resto (D8+ vs D1-D7, D7+ vs D1-D6)
  b) a MARGINAL, que e quem decide o envio: quanto converte o decil D7 sozinho,
     contra a media do lancamento. Se D7 ~ media, adiciona-lo ao evento so dilui.
"""
import os, sys, json
os.environ.setdefault('LAUNCHES_SOURCE', 'table')
sys.path.insert(0, '/Users/ramonmoreira/Desktop/bring_data/V2')
os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
import pandas as pd, math
from src.data.analytics_connection import open_analytics_connection
S = '/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'

L = pd.read_pickle(S + 'abr28_leads.pkl')
an = open_analytics_connection(timeout=300)
cal = an.run("""SELECT lf_name, cap_start, cap_end, vendas_end FROM launch_calendar
                WHERE client_id='devclub' AND vendas_end IS NOT NULL
                  AND cap_start >= '2026-05-20' ORDER BY cap_start""")
ven = an.run("SELECT lower(trim(email)), phone, sale_date FROM sales WHERE sale_date IS NOT NULL")
an.close()


def t8(t):
    d = ''.join(ch for ch in str(t or '') if ch.isdigit())
    return d[-8:] if len(d) >= 8 else None


v = pd.DataFrame(ven, columns=['email', 'tel', 'sd'])
v['sd'] = pd.to_datetime(v['sd'], errors='coerce').dt.tz_localize(None)
v['t8'] = v['tel'].map(t8)
pe = v.dropna(subset=['email']).groupby('email')['sd'].apply(list).to_dict()
pt = v.dropna(subset=['t8']).groupby('t8')['sd'].apply(list).to_dict()

print(f"{'LF':<8}{'média':>7} | {'D7 sozinho':>11}{'vs média':>9} | {'D8 sozinho':>11}{'vs média':>9} | "
      f"{'lift D8+':>9}{'lift D7+':>9} | {'pureza D8-10':>13}{'pureza D7-10':>13}")
print('-' * 122)
agg = {'l': 0, 'c': 0, 'l7': 0, 'c7': 0, 'l8': 0, 'c8': 0, 'l8p': 0, 'c8p': 0, 'l7p': 0, 'c7p': 0}
for lf, c0, c1, vend in cal:
    g = L[(L['dt'].dt.date >= c0) & (L['dt'].dt.date <= c1)]
    g = g[g['temp'] == 'FRIO'].copy()
    if len(g) < 500:
        continue
    lim = pd.Timestamp(vend) + pd.Timedelta(days=1)
    g['conv'] = [int(any(d0 <= s <= lim for s in (pe.get(e, []) + pt.get(t8(p), []))))
                 for e, p, d0 in zip(g['email'], g['phone'], g['dt'])]
    if g['conv'].sum() < 5:
        continue
    med = g['conv'].mean()
    d7 = g[g['decil'] == 7]; d8 = g[g['decil'] == 8]
    c8 = g[g['decil'] >= 8]; r8 = g[g['decil'] < 8]
    c7 = g[g['decil'] >= 7]; r7 = g[g['decil'] < 7]
    l8 = (c8['conv'].mean() / r8['conv'].mean()) if r8['conv'].sum() else None
    l7 = (c7['conv'].mean() / r7['conv'].mean()) if r7['conv'].sum() else None
    print(f"{lf[:7]:<8}{med*100:>6.2f}% | {d7['conv'].mean()*100:>10.2f}%{d7['conv'].mean()/med:>8.2f}x | "
          f"{d8['conv'].mean()*100:>10.2f}%{d8['conv'].mean()/med:>8.2f}x | "
          f"{l8 or 0:>8.2f}x{l7 or 0:>8.2f}x | "
          f"{c8['conv'].mean()/med:>12.2f}x{c7['conv'].mean()/med:>12.2f}x")
    agg['l'] += len(g); agg['c'] += g['conv'].sum()
    agg['l7'] += len(d7); agg['c7'] += d7['conv'].sum()
    agg['l8'] += len(d8); agg['c8'] += d8['conv'].sum()
    agg['l8p'] += len(c8); agg['c8p'] += c8['conv'].sum()
    agg['l7p'] += len(c7); agg['c7p'] += c7['conv'].sum()

med = agg['c'] / agg['l']
print('-' * 122)
print(f"\nAGREGADO da série fria ({agg['l']:,} leads, {agg['c']} compradores, média {med*100:.3f}%):")
print(f"  decil D7 sozinho : {agg['c7']/agg['l7']*100:.3f}%  = {agg['c7']/agg['l7']/med:.2f}x a média "
      f"({agg['c7']}/{agg['l7']:,})")
print(f"  decil D8 sozinho : {agg['c8']/agg['l8']*100:.3f}%  = {agg['c8']/agg['l8']/med:.2f}x a média "
      f"({agg['c8']}/{agg['l8']:,})")
print(f"  evento D8-D10    : {agg['c8p']/agg['l8p']*100:.3f}% = {agg['c8p']/agg['l8p']/med:.2f}x a média · "
      f"{agg['l8p']/agg['l']*100:.0f}% dos leads")
print(f"  evento D7-D10    : {agg['c7p']/agg['l7p']*100:.3f}% = {agg['c7p']/agg['l7p']/med:.2f}x a média · "
      f"{agg['l7p']/agg['l']*100:.0f}% dos leads")
