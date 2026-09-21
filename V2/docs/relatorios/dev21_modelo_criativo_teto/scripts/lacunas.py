# -*- coding: utf-8 -*-
"""As lacunas do painel DEV21, medidas:
  A) ROAS e lucro por BALDE DE DECIL (os mesmos 5 pares que a producao usa no teto)
  B) os criativos VETERANOS que foram parar na campanha de Lead
  D) mesmo criativo em campanhas diferentes (pareado + qui-quadrado de homogeneidade)
  E) a corrida: CPL barato vs teto so modelo vs teto final
Nada de projecao contrafactual. So medicao.
"""
import json, math
import numpy as np, pandas as pd
from scipy.stats import fisher_exact, chi2_contingency, spearmanr
S = '/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
BALDES = (('D1-D2', (1, 2)), ('D3-D4', (3, 4)), ('D5-D6', (5, 6)),
          ('D7-D8', (7, 8)), ('D9-D10', (9, 10)))
OUT = {}

L = pd.read_pickle(S + 'criativo_leads.pkl')
U = pd.read_pickle(S + 'criativo_unidades.pkl')
T = pd.read_pickle(S + 'teto_v2.pkl')

# ---------------------------------------------------------------- sanidade
print('=' * 100); print('SANIDADE'); print('=' * 100)
print(f"leads {len(L):,} · compradores {int(L['conv'].sum())} · faturamento R$ {L['fat'].sum():,.2f}")
print(f"unidades {len(U)} · gasto total R$ {U['gasto'].sum():,.2f} · comp {int(U['comp'].sum())}")
print(f"decil champion preenchido: {L['decil'].notna().sum():,} · challenger: {L['decil_jul'].notna().sum():,}")

# custo de cada lead = CPL da unidade (criativo x campanha) em que ele caiu.
# Segura o custo constante dentro da unidade e deixa a RECEITA variar: e exatamente
# a pergunta "o decil previu dinheiro?", sem contrafactual nenhum.
cpl = U[U['gasto'] > 0].set_index(['criativo', 'cat'])['cpl'].to_dict()
L['custo'] = [cpl.get((c, k), np.nan) for c, k in zip(L['criativo'], L['cat'])]
pago = L[L['custo'].notna()].copy()
print(f"\nleads PAGOS com custo atribuido: {len(pago):,} de {len(L):,} "
      f"({len(pago)/len(L)*100:.1f}%) · custo somado R$ {pago['custo'].sum():,.2f}")


def baldes(df, col):
    """Tabela de balde de decil: leads, compradores, conversao, faturamento, custo,
    ROAS e lucro. ROAS aqui = faturamento do balde / custo dos leads do balde."""
    d = df[df[col].notna()].copy()
    d['dec'] = pd.to_numeric(d[col], errors='coerce').astype('Int64')
    linhas = []
    for rot, (a, b) in BALDES:
        g = d[d['dec'].isin([a, b])]
        if not len(g):
            continue
        fat, cus = g['fat'].sum(), g['custo'].sum()
        linhas.append(dict(balde=rot, leads=len(g), comp=int(g['conv'].sum()),
                           conv=g['conv'].mean(), fat=fat, custo=cus,
                           roas=fat / cus if cus else np.nan, lucro=fat - cus,
                           cpl=cus / len(g), ticket=fat / g['conv'].sum() if g['conv'].sum() else np.nan))
    t = pd.DataFrame(linhas)
    base = d['conv'].mean()
    t['lift'] = t['conv'] / base
    return t, base


def mostra(t, base, rot):
    print(f"\n--- {rot} (conversao geral {base*100:.3f}%) ---")
    print(f"{'balde':<8}{'leads':>8}{'comp':>6}{'conv%':>8}{'lift':>6}{'CPL':>7}"
          f"{'ticket':>10}{'fatur.':>12}{'custo':>11}{'ROAS':>7}{'lucro':>12}")
    for _, r in t.iterrows():
        print(f"{r['balde']:<8}{r['leads']:>8,}{r['comp']:>6}{r['conv']*100:>8.3f}"
              f"{r['lift']:>6.2f}{r['cpl']:>7.2f}{r['ticket'] if pd.notna(r['ticket']) else 0:>10,.0f}"
              f"{r['fat']:>12,.0f}{r['custo']:>11,.0f}{r['roas']:>7.2f}{r['lucro']:>12,.0f}")


print('\n' + '=' * 100); print('A) ROAS E LUCRO POR BALDE DE DECIL'); print('=' * 100)
A = {}
for rot, col, sub in (('CHAMPION abr_28 · tudo', 'decil', pago),
                      ('CHALLENGER jul_24 · tudo', 'decil_jul', pago),
                      ('CHAMPION · so QUENTE', 'decil', pago[pago['cat'].str.contains('QUENTE')]),
                      ('CHAMPION · so FRIO Meta', 'decil', pago[pago['cat'].str.contains('FRIO')]),
                      ('CHAMPION · so GOOGLE', 'decil', pago[pago['cat'] == 'Google Ads'])):
    t, base = baldes(sub, col)
    mostra(t, base, rot)
    A[rot] = dict(base=base, linhas=t.to_dict('records'))
OUT['baldes'] = A

# ------------------------------------------------------------------- B) Lead
print('\n' + '=' * 100); print('B) OS CRIATIVOS VETERANOS QUE FORAM PARA A CAMPANHA DE LEAD'); print('=' * 100)
tt = T.sort_values('n_hist', ascending=False)
print(f"{'criativo':<40}{'campanha':<16}{'histor.':>9}{'peso':>6}{'lift':>6}"
      f"{'leads':>7}{'CPL':>6}{'conv%':>7}{'ROAS':>6}")
for _, r in tt.iterrows():
    lf = f"{r['lift_cri']:.2f}" if pd.notna(r['lift_cri']) else '-'
    print(f"{str(r['criativo'])[:38]:<40}{r['cat'][:14]:<16}{r['n_hist']:>9,}{r['peso']*100:>5.0f}%"
          f"{lf:>6}{r['leads']:>7,}{r['cpl']:>6.2f}{r['comp']/r['leads']*100:>7.3f}{r['roas']:>6.2f}")
lead = T[T['cat'].str.startswith('Lead')]
ml = T[~T['cat'].str.startswith('Lead')]
OUT['lead_vs_ml'] = dict(
    lead=dict(n=len(lead), hist_medio=float(lead['n_hist'].mean()), gasto=float(lead['gasto'].sum()),
              leads=int(lead['leads'].sum()), comp=int(lead['comp'].sum()),
              roas=float(np.average(lead['roas'], weights=lead['gasto'])),
              lift_med=float(lead['lift_cri'].median())),
    ml=dict(n=len(ml), hist_medio=float(ml['n_hist'].mean()), gasto=float(ml['gasto'].sum()),
            leads=int(ml['leads'].sum()), comp=int(ml['comp'].sum()),
            roas=float(np.average(ml['roas'], weights=ml['gasto'])),
            lift_med=float(ml['lift_cri'].median())))
print(f"\nLead : {len(lead)} unid · historico medio {lead['n_hist'].mean():,.0f} leads · "
      f"lift mediano {lead['lift_cri'].median():.2f} · ROAS {np.average(lead['roas'],weights=lead['gasto']):.2f}")
print(f"ML   : {len(ml)} unid · historico medio {ml['n_hist'].mean():,.0f} leads · "
      f"lift mediano {ml['lift_cri'].median():.2f} · ROAS {np.average(ml['roas'],weights=ml['gasto']):.2f}")
# a qualidade do lead que cada uma entregou
for rot, m in (('Lead', L['cat'].str.startswith('Lead')), ('ML', ~L['cat'].str.startswith('Lead'))):
    g = L[m & L['decil'].notna()]
    d = pd.to_numeric(g['decil'], errors='coerce')
    print(f"  {rot}: {len(g):,} leads · D1-D2 {(d<=2).mean()*100:.1f}% · D9-D10 {(d>=9).mean()*100:.1f}%")
    OUT['lead_vs_ml'][rot.lower() + '_qualidade'] = dict(
        n=len(g), pct_fundo=float((d <= 2).mean()), pct_topo=float((d >= 9).mean()))

# ------------------------------------------------------ D) mesmo criativo, campanhas
print('\n' + '=' * 100); print('D) MESMO CRIATIVO, CAMPANHAS DIFERENTES'); print('=' * 100)
u = U[(U['gasto'] > 0) & (U['leads'] >= 100)].copy()
for c in ('leads', 'comp', 'conv', 'roas', 'lucro', 'cpl', 'gasto', 'fat'):
    u[c] = pd.to_numeric(u[c], errors='coerce')
D = []
for cr, g in u.groupby('criativo'):
    if len(g) < 2:
        continue
    tab = np.array([[int(r['comp']), int(r['leads'] - r['comp'])] for _, r in g.iterrows()])
    p = chi2_contingency(tab)[1] if tab.sum() > 0 and (tab.sum(0) > 0).all() else np.nan
    best = g.loc[g['conv'].idxmax()]; worst = g.loc[g['conv'].idxmin()]
    print(f"\n{cr[:70]}  ({len(g)} campanhas · homogeneidade p={p:.3f})")
    print(f"   {'campanha':<16}{'leads':>7}{'CPL':>7}{'alunos':>7}{'conv%':>8}{'ROAS':>7}{'lucro':>10}")
    for _, r in g.sort_values('leads', ascending=False).iterrows():
        print(f"   {r['cat'][:14]:<16}{r['leads']:>7,}{r['cpl']:>7.2f}{int(r['comp']):>7}"
              f"{r['conv']*100:>8.3f}{r['roas']:>7.2f}{r['lucro']:>10,.0f}")
    D.append(dict(criativo=cr, n=len(g), p=float(p) if pd.notna(p) else None,
                  amp=float(best['conv'] / worst['conv']) if worst['conv'] > 0 else None,
                  melhor=best['cat'], pior=worst['cat'],
                  linhas=g.sort_values('leads', ascending=False)[
                      ['cat', 'leads', 'cpl', 'comp', 'conv', 'roas', 'lucro']].to_dict('records')))
OUT['pareado'] = D

# ----------------------------------------------------------- E) a corrida
print('\n' + '=' * 100); print('E) A CORRIDA: CPL BARATO vs TETO SO MODELO vs TETO FINAL'); print('=' * 100)
x = T.copy()
CPL_LF = x['gasto'].sum() / x['leads'].sum()
x['r_cpl'] = x['cpl'] <= CPL_LF            # "lead barato": abaixo do CPL medio do lancamento
x['r_mod'] = x['cpl'] <= x['teto_so_modelo']
x['r_tet'] = x['cpl'] <= x['teto']
print(f"CPL medio do lancamento (nas 25 unidades): R$ {CPL_LF:.2f}")


def regra(col, rot, alvo=2.0):
    a, b = x[x[col]], x[~x[col]]
    if not len(a) or not len(b):
        print(f"\n  {rot}: um lado vazio ({len(a)}/{len(b)})"); return None
    f = fisher_exact([[int((a['roas'] >= alvo).sum()), int((a['roas'] < alvo).sum())],
                      [int((b['roas'] >= alvo).sum()), int((b['roas'] < alvo).sum())]])
    ra = np.average(a['roas'], weights=a['gasto']); rb = np.average(b['roas'], weights=b['gasto'])
    la = a['comp'].sum() / a['leads'].sum(); lb = b['comp'].sum() / b['leads'].sum()
    luca = (a['roas'] - 1) * a['gasto']; lucb = (b['roas'] - 1) * b['gasto']
    ac = int(((a['roas'] >= alvo)).sum() + ((b['roas'] < alvo)).sum())
    print(f"\n  {rot}")
    print(f"    APROVA: {len(a):>2} unid · R$ {a['gasto'].sum():>9,.0f} · conv {la*100:.3f}% · "
          f"{(a['roas']>=alvo).mean()*100:>3.0f}% batem ROAS 2 · ROAS {ra:.2f} · lucro R$ {luca.sum():>9,.0f}")
    print(f"    REPROVA:{len(b):>2} unid · R$ {b['gasto'].sum():>9,.0f} · conv {lb*100:.3f}% · "
          f"{(b['roas']>=alvo).mean()*100:>3.0f}% batem ROAS 2 · ROAS {rb:.2f} · lucro R$ {lucb.sum():>9,.0f}")
    print(f"    razao {ra/rb:.2f}x · Fisher p={f.pvalue:.4f} · acertos {ac}/{len(x)}")
    return dict(rot=rot, na=len(a), nb=len(b), ga=float(a['gasto'].sum()), gb=float(b['gasto'].sum()),
                conva=float(la), convb=float(lb), ta=float((a['roas'] >= alvo).mean()),
                tb=float((b['roas'] >= alvo).mean()), ra=float(ra), rb=float(rb),
                luca=float(luca.sum()), lucb=float(lucb.sum()), razao=float(ra / rb),
                fisher=float(f.pvalue), acertos=ac, n=len(x))


OUT['corrida'] = [r for r in (
    regra('r_cpl', 'REGRA 1 · CPL barato (abaixo do CPL medio do lancamento)'),
    regra('r_mod', 'REGRA 2 · teto SO MODELO (CPL abaixo do teto que o modelo sozinho daria)'),
    regra('r_tet', 'REGRA 3 · teto FINAL (modelo x criativo) = o que a producao usa hoje')) if r]
rho_c = spearmanr(x['cpl'], x['roas']); rho_f = spearmanr(x['cpl'] / x['teto'], x['roas'])
print(f"\n  correlacao de ordem CPL vs ROAS          : {rho_c.statistic:+.2f} (p={rho_c.pvalue:.3f})")
print(f"  correlacao de ordem (CPL/teto) vs ROAS   : {rho_f.statistic:+.2f} (p={rho_f.pvalue:.3f})")
OUT['spearman'] = dict(cpl=[float(rho_c.statistic), float(rho_c.pvalue)],
                       folga=[float(rho_f.statistic), float(rho_f.pvalue)], cpl_lf=float(CPL_LF))

json.dump(OUT, open(S + 'lacunas.json', 'w'), default=float, indent=1)
x.to_pickle(S + 'corrida.pkl')
print('\nOK -> lacunas.json, corrida.pkl')
