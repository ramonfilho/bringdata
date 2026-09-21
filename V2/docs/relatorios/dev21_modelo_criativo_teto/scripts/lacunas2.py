# -*- coding: utf-8 -*-
"""Fecha as lacunas que sobraram:
  F) o 2x2 CPL barato x dentro do teto  -> a regra do teto SUBSTITUI ou SOMA ao CPL?
  G) merito por campanha: ROAS = qualidade (conversao) dividido por preco (CPL).
     Decomposicao aritmetica pura, sem contrafactual.
  H) lucro por real de verba em cada regra (o ROAS ja pondera, isto so traduz).
"""
import json
import numpy as np, pandas as pd
from scipy.stats import fisher_exact
S = '/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
x = pd.read_pickle(S + 'corrida.pkl')
L = pd.read_pickle(S + 'criativo_leads.pkl')
U = pd.read_pickle(S + 'criativo_unidades.pkl')
OUT = json.load(open(S + 'lacunas.json'))

# --------------------------------------------------------------- H) lucro por real
print('=' * 100); print('H) LUCRO POR REAL DE VERBA, EM CADA REGRA'); print('=' * 100)
print(f"{'regra':<34}{'aprova R$/R$':>14}{'reprova R$/R$':>15}{'razao':>8}")
H = []
for col, rot in (('r_cpl', 'CPL barato'), ('r_mod', 'teto so modelo'), ('r_tet', 'teto final')):
    a, b = x[x[col]], x[~x[col]]
    la = ((a['roas'] - 1) * a['gasto']).sum() / a['gasto'].sum()
    lb = ((b['roas'] - 1) * b['gasto']).sum() / b['gasto'].sum()
    print(f"{rot:<34}{la:>14.2f}{lb:>15.2f}{la/lb:>8.1f}x")
    H.append(dict(regra=rot, la=float(la), lb=float(lb), razao=float(la / lb)))
OUT['lucro_por_real'] = H

# ------------------------------------------------------------------ F) o 2x2
print('\n' + '=' * 100); print('F) O 2x2: CPL BARATO x DENTRO DO TETO'); print('=' * 100)
q = []
for barato in (True, False):
    for dentro in (True, False):
        g = x[(x['r_cpl'] == barato) & (x['r_tet'] == dentro)]
        if not len(g):
            q.append(dict(barato=barato, dentro=dentro, n=0)); continue
        r = np.average(g['roas'], weights=g['gasto'])
        q.append(dict(barato=barato, dentro=dentro, n=len(g), gasto=float(g['gasto'].sum()),
                      conv=float(g['comp'].sum() / g['leads'].sum()), roas=float(r),
                      lucro=float(((g['roas'] - 1) * g['gasto']).sum()),
                      bate=float((g['roas'] >= 2).mean())))
print(f"{'quadrante':<30}{'unid':>6}{'verba R$':>11}{'conv%':>8}{'ROAS':>7}{'lucro R$':>11}")
for c in q:
    rot = ('CPL barato' if c['barato'] else 'CPL caro') + ' · ' + ('DENTRO do teto' if c['dentro'] else 'acima do teto')
    if not c['n']:
        print(f"{rot:<30}{0:>6}{'-':>11}{'-':>8}{'-':>7}{'-':>11}"); continue
    print(f"{rot:<30}{c['n']:>6}{c['gasto']:>11,.0f}{c['conv']*100:>8.3f}{c['roas']:>7.2f}{c['lucro']:>11,.0f}")
OUT['quadrantes'] = q
# o teste que importa: DENTRO do mesmo nivel de CPL, o teto ainda separa?
for barato, rot in ((True, 'so entre os de CPL BARATO'), (False, 'so entre os de CPL CARO')):
    g = x[x['r_cpl'] == barato]
    a, b = g[g['r_tet']], g[~g['r_tet']]
    if len(a) and len(b):
        f = fisher_exact([[int((a['roas'] >= 2).sum()), int((a['roas'] < 2).sum())],
                          [int((b['roas'] >= 2).sum()), int((b['roas'] < 2).sum())]])
        ra = np.average(a['roas'], weights=a['gasto']); rb = np.average(b['roas'], weights=b['gasto'])
        print(f"\n  {rot}: dentro ROAS {ra:.2f} ({len(a)}u) vs acima {rb:.2f} ({len(b)}u) "
              f"· razao {ra/rb:.2f}x · Fisher p={f.pvalue:.3f}")
        OUT.setdefault('teto_dentro_do_cpl', []).append(
            dict(rot=rot, na=len(a), nb=len(b), ra=float(ra), rb=float(rb),
                 razao=float(ra / rb), p=float(f.pvalue)))
    else:
        print(f"\n  {rot}: um lado vazio ({len(a)}/{len(b)}), sem comparacao")

# --------------------------------------------------------- G) merito por campanha
print('\n' + '=' * 100); print('G) MERITO POR CAMPANHA: qualidade vs preco'); print('=' * 100)
u = U[U['gasto'] > 0].copy()
for c in ('leads', 'comp', 'fat', 'gasto'):
    u[c] = pd.to_numeric(u[c], errors='coerce')
camp = u.groupby('cat').agg(leads=('leads', 'sum'), comp=('comp', 'sum'),
                            fat=('fat', 'sum'), gasto=('gasto', 'sum')).reset_index()
camp = camp[camp['leads'] >= 100]
camp['conv'] = camp['comp'] / camp['leads']; camp['cpl'] = camp['gasto'] / camp['leads']
camp['roas'] = camp['fat'] / camp['gasto']; camp['lucro'] = camp['fat'] - camp['gasto']
CONV0 = camp['comp'].sum() / camp['leads'].sum(); CPL0 = camp['gasto'].sum() / camp['leads'].sum()
ROAS0 = camp['fat'].sum() / camp['gasto'].sum()
camp['f_qual'] = camp['conv'] / CONV0          # quanto do ROAS veio da QUALIDADE do lead
camp['f_prec'] = CPL0 / camp['cpl']            # quanto veio do PRECO pago
# mistura de decis entregue (o que o modelo colocou na campanha)
dq = {}
for cat, g in L[L['decil'].notna()].groupby('cat'):
    d = pd.to_numeric(g['decil'], errors='coerce')
    dq[cat] = (float((d >= 9).mean()), float((d <= 2).mean()), len(g))
camp['topo'] = camp['cat'].map(lambda c: dq.get(c, (np.nan,))[0])
camp['fundo'] = camp['cat'].map(lambda c: dq.get(c, (np.nan, np.nan))[1])
camp = camp.sort_values('lucro', ascending=False)
print(f"referencia do lancamento: conversao {CONV0*100:.3f}% · CPL R$ {CPL0:.2f} · ROAS {ROAS0:.2f}\n")
print(f"{'campanha':<16}{'ROAS':>6}{'vs ref':>8}{'  =  '}{'qualidade':>10}{'  x  '}{'preco':>7}"
      f"{'   |':>4}{'%D9-D10':>9}{'%D1-D2':>8}{'lucro R$':>11}")
for _, r in camp.iterrows():
    print(f"{r['cat'][:14]:<16}{r['roas']:>6.2f}{r['roas']/ROAS0:>8.2f}{'  =  '}"
          f"{r['f_qual']:>10.2f}{'  x  '}{r['f_prec']:>7.2f}{'   |':>4}"
          f"{(r['topo']*100 if pd.notna(r['topo']) else 0):>9.1f}"
          f"{(r['fundo']*100 if pd.notna(r['fundo']) else 0):>8.1f}{r['lucro']:>11,.0f}")
OUT['merito'] = dict(conv0=float(CONV0), cpl0=float(CPL0), roas0=float(ROAS0),
                     linhas=camp.to_dict('records'))
json.dump(OUT, open(S + 'lacunas.json', 'w'), default=float, indent=1)
print('\nOK -> lacunas.json atualizado')
