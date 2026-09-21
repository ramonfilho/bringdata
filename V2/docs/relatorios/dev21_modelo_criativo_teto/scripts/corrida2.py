# -*- coding: utf-8 -*-
"""A CORRIDA, refeita com corte DERIVADO em vez de arbitrario.

O corte de "CPL barato" da primeira versao era a media do proprio lancamento (R$ 6,50):
circular, porque so existe DEPOIS do lancamento acabar. Aqui as tres regras usam a
MESMA formula, o MESMO valor por venda, o MESMO alvo de ROAS, e diferem so na
informacao que cada uma enxerga:

  teto = conversao_esperada x valor_por_venda x fator / ROAS_alvo

  R0 TETO PLANO   : conversao_esperada = a conversao GERAL da referencia congelada.
                    Nao olha o lead nem o criativo. E "CPL barato" com regua de negocio.
  R1 TETO MODELO  : conversao_esperada = a da MISTURA DE DECIS daquela unidade.
  R2 TETO FINAL   : R1 ajustado pelo historico do criativo. E o que a producao usa.

Sao NINHOS: R0 e o mesmo numero pra todo mundo, R1 personaliza pelo lead, R2 pelo
lead e pelo criativo. Assim a comparacao mede informacao, nao escolha de corte.
"""
import json
import numpy as np, pandas as pd
from scipy.stats import fisher_exact, spearmanr
S = '/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
x = pd.read_pickle(S + 'corrida.pkl')
OUT = json.load(open(S + 'lacunas.json'))
CONV0, VPS, FATOR, ALVO = 0.008126, 1349.61, 1.2105, 2.0     # referencia congelada em 13/07
TETO_PLANO = CONV0 * VPS * FATOR / ALVO
print(f"TETO PLANO derivado da referencia: {CONV0*100:.4f}% x R$ {VPS:,.2f} x {FATOR} / {ALVO} "
      f"= R$ {TETO_PLANO:.2f}")
print(f"   (o corte arbitrario da versao anterior era R$ {x['gasto'].sum()/x['leads'].sum():.2f})")
x['r0'] = x['cpl'] <= TETO_PLANO
x['r1'] = x['cpl'] <= x['teto_so_modelo']
x['r2'] = x['cpl'] <= x['teto']


def julga(col, rot):
    a, b = x[x[col]], x[~x[col]]
    if not len(a) or not len(b):
        print(f"\n  {rot}: um lado vazio"); return None
    f = fisher_exact([[int((a['roas'] >= ALVO).sum()), int((a['roas'] < ALVO).sum())],
                      [int((b['roas'] >= ALVO).sum()), int((b['roas'] < ALVO).sum())]])
    ra = np.average(a['roas'], weights=a['gasto']); rb = np.average(b['roas'], weights=b['gasto'])
    ca = a['comp'].sum() / a['leads'].sum(); cb = b['comp'].sum() / b['leads'].sum()
    lua = ((a['roas'] - 1) * a['gasto']).sum(); lub = ((b['roas'] - 1) * b['gasto']).sum()
    ac = int((a['roas'] >= ALVO).sum() + (b['roas'] < ALVO).sum())
    print(f"\n  {rot}")
    print(f"    APROVA : {len(a):>2}u · R$ {a['gasto'].sum():>9,.0f} · conv {ca*100:.3f}% · "
          f"ROAS {ra:.2f} · lucro R$ {lua:>9,.0f} · R$ {lua/a['gasto'].sum():.2f} de lucro por real")
    print(f"    REPROVA: {len(b):>2}u · R$ {b['gasto'].sum():>9,.0f} · conv {cb*100:.3f}% · "
          f"ROAS {rb:.2f} · lucro R$ {lub:>9,.0f} · R$ {lub/b['gasto'].sum():.2f} de lucro por real")
    print(f"    razao de ROAS {ra/rb:.2f}x · conv aprovada/reprovada {ca/cb:.2f}x · "
          f"Fisher p={f.pvalue:.4f} · acertos {ac}/{len(x)}")
    return dict(rot=rot, na=len(a), nb=len(b), ga=float(a['gasto'].sum()), gb=float(b['gasto'].sum()),
                conva=float(ca), convb=float(cb), razao_conv=float(ca / cb), ra=float(ra), rb=float(rb),
                razao=float(ra / rb), luca=float(lua), lucb=float(lub),
                lpr_a=float(lua / a['gasto'].sum()), lpr_b=float(lub / b['gasto'].sum()),
                fisher=float(f.pvalue), acertos=ac, n=len(x))


print('\n' + '=' * 104); print('A CORRIDA (25 unidades, alvo ROAS 2, mesma formula, informacao diferente)')
print('=' * 104)
R = [r for r in (julga('r0', 'R0 · TETO PLANO (nao olha o lead) = "CPL barato" com regua de negocio'),
                 julga('r1', 'R1 · TETO COM O MODELO (olha a mistura de decis da unidade)'),
                 julga('r2', 'R2 · TETO FINAL, modelo x criativo (o que a producao usa hoje)')) if r]
OUT['corrida2'] = R; OUT['teto_plano'] = float(TETO_PLANO)

# ---- quanto as regras DISCORDAM: e o que limita o que da pra concluir sobre o criativo
print('\n' + '=' * 104); print('O QUE R1 E R2 DISCORDAM (o limite do que este lancamento consegue decidir)')
print('=' * 104)
d = x[x['r1'] != x['r2']]
print(f"  R1 e R2 dao o MESMO veredito em {len(x)-len(d)} das {len(x)} unidades. Discordam em {len(d)}:")
for _, r in d.iterrows():
    print(f"    {str(r['criativo'])[:40]:<42}{r['cat'][:13]:<15}CPL {r['cpl']:>5.2f} · "
          f"teto modelo {r['teto_so_modelo']:>5.2f} · teto final {r['teto']:>5.2f} · "
          f"ROAS {r['roas']:.2f} · quem acertou: {'R2' if (r['r2']==(r['roas']>=ALVO)) else 'R1'}")
OUT['discordancia_r1_r2'] = dict(iguais=int(len(x) - len(d)), n=len(x),
                                 linhas=d[['criativo', 'cat', 'cpl', 'teto_so_modelo', 'teto',
                                           'roas', 'r1', 'r2']].to_dict('records'))

# ---- sem corte nenhum: correlacao de ordem
print('\n' + '=' * 104); print('SEM CORTE NENHUM: correlacao de ordem contra o ROAS observado')
print('=' * 104)
sp = {}
for col, rot in (('cpl', 'CPL puro (quanto mais barato, melhor?)'),
                 ('folga0', 'CPL / teto plano'),
                 ('folga1', 'CPL / teto do modelo'),
                 ('folga2', 'CPL / teto final')):
    if col == 'cpl':
        s = x['cpl']
    else:
        s = x['cpl'] / {'folga0': TETO_PLANO, 'folga1': x['teto_so_modelo'], 'folga2': x['teto']}[col]
    r = spearmanr(s, x['roas'])
    marca = ' <-- passa' if r.pvalue < 0.05 else ''
    print(f"  {rot:<42} rho {r.statistic:+.2f} · p={r.pvalue:.4f}{marca}")
    sp[col] = [float(r.statistic), float(r.pvalue)]
OUT['spearman2'] = sp
print("\n  (rho negativo = quanto MENOR a razao, MAIOR o ROAS, que e a direcao esperada.")
print("   'CPL puro' e 'CPL / teto plano' sao a MESMA ordem: dividir todo mundo pelo mesmo")
print("   numero nao reordena ninguem. Por isso o rho e identico: e o mesmo teste.)")
json.dump(OUT, open(S + 'lacunas.json', 'w'), default=float, indent=1)
x.to_pickle(S + 'corrida.pkl')
print('\nOK -> lacunas.json atualizado')
