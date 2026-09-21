# -*- coding: utf-8 -*-
"""RECONTAGEM: o abr_28 no publico frio, lancamento a lancamento.

CORRECAO da primeira versao (o Ramon apontou, e e a 2a vez que uma sessao erra nisso):
filtrar por `champion_run_id` era ERRADO. Essa coluna so passou a refletir o papel real
depois de um fix de codigo em 25/07/2026. Na pratica o abr_28 virou o modelo principal
por volta de 22 a 29/06, e o que definia o papel era OUTRA coisa: qual modelo estava
levando mais orcamento na Meta, com o objetivo de otimizacao maior.

Entao o decil do abr_28 e lido de ONDE ELE ESTIVER: `decil_champion` quando ele e o
champion_run_id, `decil_challenger` quando ele e o challenger_run_id. Isso abre a
cobertura de 27 mil para 93 mil leads, a partir de 25/05/2026.
"""
import os, sys, ssl, math, json, unicodedata
os.environ.setdefault('LAUNCHES_SOURCE', 'table')
sys.path.insert(0, '/Users/ramonmoreira/Desktop/bring_data/V2')
os.chdir('/Users/ramonmoreira/Desktop/bring_data/V2')
from dotenv import load_dotenv; load_dotenv('.env')
import pandas as pd, numpy as np, pg8000.native
from src.data.analytics_connection import open_analytics_connection
S = '/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
ABR28 = '5d158f0aa6e54b489498470446194a6c'
VIRADA = pd.Timestamp('2026-06-22')     # quando ele assumiu de fato, pela verba na Meta

an = open_analytics_connection(timeout=900)
cal = an.run("""SELECT lf_name, cap_start, cap_end, vendas_end FROM launch_calendar
                WHERE client_id='devclub' AND vendas_end IS NOT NULL
                  AND cap_start >= '2026-05-20' ORDER BY cap_start""")
ven = an.run("SELECT lower(trim(email)), phone, sale_date, sale_value FROM sales WHERE sale_date IS NOT NULL")
an.close()

c = pg8000.native.Connection(user=os.environ['LEDGER_DB_USER'], password=os.environ['LEDGER_DB_PASSWORD'],
                             host=os.environ['LEDGER_DB_HOST'], port=int(os.environ.get('LEDGER_DB_PORT', 5432)),
                             database=os.environ['LEDGER_DB_NAME'],
                             ssl_context=ssl._create_unverified_context(), timeout=900)
rows = c.run(f"""SELECT lower(trim(email)) email, phone,
   ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo') dt,
   utm_source, utm_campaign,
   CASE WHEN champion_run_id  = '{ABR28}' THEN decil_champion
        WHEN challenger_run_id = '{ABR28}' THEN decil_challenger END decil,
   CASE WHEN champion_run_id  = '{ABR28}' THEN 'champion' ELSE 'challenger' END papel
 FROM public.registros_ml
 WHERE (champion_run_id = '{ABR28}'  AND decil_champion   IS NOT NULL)
    OR (challenger_run_id = '{ABR28}' AND decil_challenger IS NOT NULL)""")
c.close()
L = pd.DataFrame(rows, columns=['email', 'phone', 'dt', 'utm_source', 'utm_campaign', 'decil', 'papel'])
L['dt'] = pd.to_datetime(L['dt'], errors='coerce'); L = L.dropna(subset=['dt'])
L['decil'] = pd.to_numeric(L['decil'], errors='coerce')
L = L.dropna(subset=['decil'])
print(f"leads com decil do abr_28 (qualquer coluna): {len(L):,} · "
      f"{L['dt'].min():%d/%m/%Y} a {L['dt'].max():%d/%m/%Y}")


def t8(t):
    d = ''.join(ch for ch in str(t or '') if ch.isdigit())
    return d[-8:] if len(d) >= 8 else None


v = pd.DataFrame(ven, columns=['email', 'tel', 'sd', 'val'])
v['sd'] = pd.to_datetime(v['sd'], errors='coerce').dt.tz_localize(None)
v['val'] = pd.to_numeric(v['val'], errors='coerce').fillna(0.0)
v['t8'] = v['tel'].map(t8); v['par'] = list(zip(v['sd'], v['val']))
pe = v.dropna(subset=['email']).groupby('email')['par'].apply(list).to_dict()
pt = v.dropna(subset=['t8']).groupby('t8')['par'].apply(list).to_dict()


def temp(nome, src):
    if 'google' in str(src or '').lower():
        return 'Google'
    N = unicodedata.normalize('NFKD', str(nome or '')).encode('ascii', 'ignore').decode().upper()
    if 'QUENTE' in N:
        return 'QUENTE'
    if 'FRIO' in N or 'ABERTO' in N:
        return 'FRIO'
    return 'S/ROTULO'


L['temp'] = [temp(a, b) for a, b in zip(L['utm_campaign'], L['utm_source'])]
L['hqlb'] = L['utm_campaign'].astype(str).str.upper().str.contains('HQLB')

lin = []
for lf, c0, c1, vend in cal:
    g = L[(L['dt'].dt.date >= c0) & (L['dt'].dt.date <= c1)].copy()
    if len(g) < 300:
        continue
    lim = pd.Timestamp(vend) + pd.Timedelta(days=1)
    par = [[p for p in (pe.get(e, []) + pt.get(t8(ph), [])) if d0 <= p[0] <= lim]
           for e, ph, d0 in zip(g['email'], g['phone'], g['dt'])]
    g['conv'] = [int(bool(p)) for p in par]
    if g['conv'].sum() < 5:
        continue
    recortes = [('QUENTE', g[g['temp'] == 'QUENTE']), ('FRIO', g[g['temp'] == 'FRIO']),
                ('FRIO-HQLB', g[(g['temp'] == 'FRIO') & g['hqlb']])]
    for tp, s in recortes:
        if len(s) < 200:
            continue
        top = s[s['decil'] >= 9]; res = s[s['decil'] < 9]
        a, na = int(top['conv'].sum()), len(top); b, nb = int(res['conv'].sum()), len(res)
        if na < 50 or nb < 50 or (a + b) < 5:
            continue
        lin.append(dict(lf=lf, cap=str(c0), temp=tp, leads=len(s), comp=a + b, a=a, na=na, b=b, nb=nb,
                        ct=a / na, cr=b / nb, lift=(a / na) / (b / nb) if b else None,
                        depois=pd.Timestamp(c0) >= VIRADA,
                        pct_fundo=float((s['decil'] <= 2).mean())))
H = pd.DataFrame(lin)


def mh(e):
    num = den = Sp = 0.0
    for a, n1, b, n0 in e:
        N = n1 + n0
        if not N or not n1 or not n0:
            continue
        num += a * n0 / N; den += b * n1 / N
        Sp += (n1 * n0 * (a + b) - a * b * N) / N ** 2
    if not den or not num:
        return None, None, None
    rr = num / den; var = Sp / (num * den)
    if var <= 0:
        return rr, None, None
    se = math.sqrt(var)
    return rr, rr * math.exp(-1.96 * se), rr * math.exp(1.96 * se)


print('\n' + '=' * 108)
print('O abr_28 POR LANCAMENTO  (topo D9-D10 contra o resto D1-D8, dentro da mesma temperatura)')
print(f'virada de papel usada: {VIRADA:%d/%m/%Y}, quando ele passou a levar a verba na Meta')
print('=' * 108)
print(f"{'lançamento':<13}{'início':<12}{'papel':<10}{'público':<9}{'leads':>8}{'alunos':>7}"
      f"{'conv topo':>11}{'conv resto':>12}{'lift':>8}{'%D1-D2':>8}")
for tp in ('QUENTE', 'FRIO', 'FRIO-HQLB'):
    for _, r in H[H['temp'] == tp].sort_values('cap').iterrows():
        pp = 'principal' if r['depois'] else 'sombra'
        lf = f"{r['lift']:.2f}x" if r['lift'] else '-'
        print(f"{r['lf'][:11]:<13}{r['cap']:<12}{pp:<10}{tp:<9}{r['leads']:>8,}{r['comp']:>7}"
              f"{r['ct']*100:>10.3f}%{r['cr']*100:>11.3f}%{lf:>8}{r['pct_fundo']*100:>7.1f}%")
    print('-' * 108)

OUT = {'linhas': H.to_dict('records'), 'virada': str(VIRADA.date())}
print()
for tp in ('QUENTE', 'FRIO', 'FRIO-HQLB'):
    for rot, sub in ((f'{tp} · TODOS os lançamentos', H[H['temp'] == tp]),
                     (f'{tp} · só depois da virada', H[(H['temp'] == tp) & H['depois']])):
        if len(sub) < 1:
            continue
        rr, lo, hi = mh([(r['a'], r['na'], r['b'], r['nb']) for _, r in sub.iterrows()])
        if rr is None:
            continue
        ok = 'SEPARA' if (lo and lo > 1) else 'não passa'
        print(f"  {rot:<36} {len(sub)} LFs · {sub['leads'].sum():>6,} leads · "
              f"lift agrupado {rr:.2f}x · IC95 {lo:.2f} a {hi:.2f} · {ok} · "
              f"acima de 1 em {int((sub['lift']>1).sum())}/{len(sub)}")
        OUT[rot] = dict(n_lf=len(sub), leads=int(sub['leads'].sum()), rr=float(rr),
                        lo=float(lo), hi=float(hi), acima=int((sub['lift'] > 1).sum()))
json.dump(OUT, open(S + 'historico_frio2.json', 'w'), default=float, indent=1)
H.to_pickle(S + 'historico_frio2.pkl'); L.to_pickle(S + 'abr28_leads.pkl')
print('\nOK -> historico_frio2.json')
