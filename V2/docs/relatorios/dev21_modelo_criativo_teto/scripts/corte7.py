# -*- coding: utf-8 -*-
"""O corte D7-D10 vs resto resolveria o ponto de atencao do frio no DEV21?
Mesma serie do historico_frio2 (abr_28 em qualquer coluna, papel real), dois cortes
lado a lado: topo>=9 vs D1-D8, e topo>=7 vs D1-D6. E a forma completa da curva do
frio no DEV21, que e quem decide a resposta.
"""
import os, sys, json
os.environ.setdefault('LAUNCHES_SOURCE', 'table')
sys.path.insert(0, '/Users/ramonmoreira/Desktop/bring_data/V2')
os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
import pandas as pd
from src.data.analytics_connection import open_analytics_connection
S = '/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'

L = pd.read_pickle(S + 'abr28_leads.pkl')      # ja tem decil, temp, hqlb
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

print(f"{'LF':<8}{'público':<7}{'leads':>7} | {'lift D9+ vs resto':>18} | {'lift D7+ vs resto':>18} | curva por par de decis")
print('-' * 118)
res = []
for lf, c0, c1, vend in cal:
    g = L[(L['dt'].dt.date >= c0) & (L['dt'].dt.date <= c1)].copy()
    if len(g) < 300:
        continue
    lim = pd.Timestamp(vend) + pd.Timedelta(days=1)
    g['conv'] = [int(any(d0 <= s <= lim for s in (pe.get(e, []) + pt.get(t8(p), []))))
                 for e, p, d0 in zip(g['email'], g['phone'], g['dt'])]
    if g['conv'].sum() < 5:
        continue
    s = g[g['temp'] == 'FRIO']
    if len(s) < 500 or s['conv'].sum() < 5:
        continue

    def lift(corte):
        top = s[s['decil'] >= corte]; rst = s[s['decil'] < corte]
        if not len(top) or not len(rst) or not rst['conv'].sum():
            return None, 0, 0
        return (top['conv'].mean() / rst['conv'].mean()), top['conv'].mean(), rst['conv'].mean()

    l9, t9, r9 = lift(9); l7, t7, r7 = lift(7)
    curva = []
    for a, b in ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10)):
        p = s[s['decil'].isin([a, b])]
        curva.append(f"{p['conv'].mean()*100:.2f}" if len(p) >= 100 else '·')
    print(f"{lf[:7]:<8}{'FRIO':<7}{len(s):>7,} | {l9 or 0:>6.2f}x ({t9*100:.2f}/{r9*100:.2f}) | "
          f"{l7 or 0:>6.2f}x ({t7*100:.2f}/{r7*100:.2f}) | {' '.join(curva)}")
    res.append(dict(lf=lf, l9=l9, l7=l7, curva=curva))
json.dump(res, open(S + 'corte7.json', 'w'), default=float, indent=1)
print("\ncurva = conversao %% por par de decis, D1-D2 ... D9-D10 (so pares com 100+ leads)")
