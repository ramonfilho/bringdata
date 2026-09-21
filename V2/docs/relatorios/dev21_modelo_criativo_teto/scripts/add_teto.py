# -*- coding: utf-8 -*-
"""Secao do backtest do teto (v2: historico casado direito + lift de plataforma)."""
import math, json
import numpy as np, pandas as pd
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
x=pd.read_pickle(S+'teto_v2.pkl'); R=json.load(open(S+'teto_v2_res.json')); G=x['gasto']
def br(v,d=2):
    if v is None or (isinstance(v,float) and (pd.isna(v) or math.isinf(v))): return '-'
    return f'{v:,.{d}f}'.replace(',','@').replace('.',',').replace('@','.')
def mil(v): return f'{int(v):,}'.replace(',','.')
def curto(n,lim=36):
    n=str(n).replace('-vid-captação','').replace('-Briefing-AnaLaura-COMHEADLINE','')
    n=n.replace('DEV-','').replace('VARIAÇÃO-','').replace('-estão pagando para você aprender',' · pagando p/ aprender')
    return n if len(n)<=lim else n[:lim-1]+'…'
def pv(p): return f'<b class="ok">p={br(p,3)}</b>' if p<0.05 else f'p={br(p,3)}'

res=[]
for rot,k,d in (('Todas as unidades','tudo',x),('Sem o público quente','sem_quente',x[~x['quente']]),
                ('Só o público quente','so_quente',x[x['quente']])):
    r=R.get(k)
    if not r:
        a=d[d['abaixo']]
        res.append(f"<tr><td>{rot}</td><td>{len(a)} / 0</td><td>R$ {br(a['gasto'].sum(),0)}</td>"
          f"<td colspan=6 class=\"z\">as {len(a)} unidades ficaram <b>dentro</b> do teto: não há grupo acima para comparar</td></tr>")
        continue
    res.append(f"<tr><td>{rot}</td><td>{r['na']} / {r['nb']}</td>"
      f"<td>R$ {br(r['ga'],0)} / R$ {br(r['gb'],0)}</td>"
      f"<td class=\"pos\"><b>{br(r['ta']*100,0)}%</b></td><td class=\"neg\">{br(r['tb']*100,0)}%</td>"
      f"<td class=\"pos\"><b>{br(r['ra'])}</b></td><td class=\"neg\">{br(r['rb'])}</td>"
      f"<td><b>{br(r['razao'])}x</b></td><td>{pv(r['fisher'])}<br><span class=\"ic\">Mann-Whitney {br(r['mw'],3)}</span></td></tr>")
t_res='\n'.join(res)

lin=[]
for _,r in x.sort_values('gasto',ascending=False).iterrows():
    dentro=r['abaixo']; acertou=(dentro and r['roas']>=2.0) or ((not dentro) and r['roas']<2.0)
    lift='-' if pd.isna(r['lift_cri']) else br(r['lift_cri'])
    lin.append(f"<tr><td>{curto(r['criativo'])}</td><td>{r['cat']}</td><td>{br(r['gasto'],0)}</td>"
      f"<td>{br(r['cpl'])}</td><td>{mil(r['n_hist'])}</td><td>{br(r['peso']*100,0)}%</td><td>{lift}</td>"
      f"<td class=\"sp\">{br(r['teto_so_modelo'])}</td><td><b>{br(r['teto'])}</b></td>"
      f"<td class=\"{'pos' if dentro else 'neg'}\"><b>{'dentro' if dentro else 'acima'}</b></td>"
      f"<td class=\"{'pos' if r['roas']>=2 else 'neg'}\">{br(r['roas'])}</td><td>{'✓' if acertou else '✗'}</td></tr>")
t_uni='\n'.join(lin)
acertos=sum(1 for _,r in x.iterrows() if (r['abaixo'] and r['roas']>=2) or ((not r['abaixo']) and r['roas']<2))
tm=np.average(x['teto_so_modelo'],weights=G); tf=np.average(x['teto'],weights=G)
pm=np.average(x['peso'],weights=G)*100; mm=np.average(x['mult'],weights=G)
alto=x[x['peso']>=0.5]; lfc=x['lift_cri'].dropna()

SEC=f'''    {{ title:"O teste final: o teto funcionou?",
      sub:"O teto é a métrica que junta as duas variáveis numa só nota: qualidade do lead (a mistura de decis do modelo) e qualidade do criativo (o histórico dele). A pergunta é direta: quem pagou abaixo do teto rendeu mais do que quem pagou acima?",
      html:`<div class="tw"><table class="tb"><thead><tr><th>Recorte</th><th>Unidades dentro / acima</th><th>Verba dentro / acima</th>
<th>% bateram ROAS 2</th><th>acima</th><th>ROAS médio</th><th>acima</th><th>Razão</th><th>Chance de ser sorte</th></tr></thead><tbody>
{t_res}
</tbody></table></div>
<p style="margin-top:14px"><b>Sim, funcionou, e nos dois recortes.</b> Quem pagou dentro do teto entregou ROAS <b>{br(R['tudo']['ra'])}</b> contra <b>{br(R['tudo']['rb'])}</b> de quem pagou acima, com <b>{br(R['tudo']['ta']*100,0)}% contra {br(R['tudo']['tb']*100,0)}%</b> de unidades batendo a meta. São 25 unidades cobrindo <b>{br(G.sum()/172838.43*100,1)}% da verba do lançamento</b>.</p>
<p><b>E não é o público quente carregando.</b> Tirando o quente inteiro, a separação continua em <b>{br(R['sem_quente']['razao'])}x</b> e segue significativa. <b>O quente nunca passou do teto</b>: as quatro unidades dele ficaram todas abaixo, o que é o motivo de aquela linha não ter comparação.</p>
<p><b>O que entrou no cálculo, e o que ficou de fora.</b> O mapa de decis, o valor por venda e o fator de rastreamento vêm da referência congelada na janela que termina em <b>13/07</b>, oito dias antes de a captação começar. O histórico de cada criativo foi fechado em <b>20/07</b>. O lift de plataforma do Google está aplicado. Nada do DEV21 entrou no cálculo do próprio DEV21.</p>` }},
    {{ title:"Quanto da nota é modelo e quanto é criativo",
      sub:"A fórmula é conversão do modelo multiplicada pelo ajuste do criativo. O peso do criativo cresce com o passado dele: n dividido por n mais 2.000.",
      html:`<div class="tw"><table class="tb"><thead><tr><th>Ingrediente</th><th>Valor</th><th>Leitura</th></tr></thead><tbody>
<tr><td>Teto médio só com o <b>modelo</b></td><td>R$ {br(tm)}</td><td>é o nível: quem define a ordem de grandeza</td></tr>
<tr><td>Teto médio já com o <b>criativo</b></td><td>R$ {br(tf)}</td><td>o criativo ajustou o nível em <b>{br((mm-1)*100,1)}%</b></td></tr>
<tr><td>Peso do histórico na fórmula</td><td>{br(pm,1)}%</td><td>ponderado por verba, sobre todas as unidades</td></tr>
<tr><td>Unidades com peso de 50% ou mais</td><td>{len(alto)} de {len(x)}</td><td>levaram R$ {br(alto['gasto'].sum(),0)}, {br(alto['gasto'].sum()/G.sum()*100,0)}% da verba</td></tr>
<tr><td>Criativos estreantes de verdade</td><td>{(x['n_hist']==0).sum()} de {len(x)}</td><td>só esses rodam com nota 100% modelo</td></tr>
<tr class="ag"><td>Amplitude do ajuste do criativo</td><td>{br(x['mult'].min())}x a {br(x['mult'].max())}x</td><td>o criativo mexe a nota em até 26% para baixo e 31% para cima</td></tr>
</tbody></table></div>
<p style="margin-top:14px"><b>A divisão de trabalho é clara: o modelo dá o nível, o criativo corrige a margem.</b> Sozinho, o modelo apontaria um teto médio de R$ {br(tm)}; com o criativo, R$ {br(tf)}. O criativo não é passageiro, mas também não é o motorista.</p>
<p><b>E ele puxou o teto para baixo, não para cima.</b> O lift mediano dos criativos que levaram a verba do DEV21 foi de <b>{br(lfc.median())}</b>, e <b>{int((lfc<1).sum())} dos {len(lfc)}</b> ficaram abaixo de 1. Ou seja: a verba foi para criativos com passado abaixo da média, e o teto reconheceu isso apertando o limite. Foi esse aperto que produziu a separação medida acima.</p>` }},
    {{ title:"Unidade a unidade, com o veredito de cada uma",
      sub:"Cada linha é um criativo rodando numa campanha. A coluna do teto aparece duas vezes: como o modelo sozinho diria, e como fica depois do ajuste do criativo.",
      html:`<div class="tw"><table class="tb"><thead><tr><th>Criativo</th><th>Campanha</th><th>Gasto R$</th><th>CPL</th>
<th>Leads de histórico</th><th>Peso</th><th>Lift do criativo</th><th class="sp">Teto só modelo</th><th>Teto final</th><th>Veredito</th><th>ROAS</th><th>Acertou</th></tr></thead><tbody>
{t_uni}
</tbody></table></div>
<p style="margin-top:14px"><b>{acertos} das {len(x)} unidades foram classificadas corretamente.</b> Os dois maiores gastos do lançamento, o AD0150-AD07 no frio e o AD0160-AD08 no quente, ficaram dentro do teto e entregaram 2,03 e 1,97. O AD0140 do Google, que sozinho consumiu R$ 16.790, foi marcado como caro (CPL R$ 9,02 contra teto de R$ 8,35) e devolveu 1,17.</p>` }},
'''
p=S+'painel_dev21.html'; h=open(p,encoding='utf-8').read()
assert '    { title:"Como ler",' in h
h=h.replace('    { title:"Como ler",', SEC+'    { title:"Como ler",',1)
open(p,'w',encoding='utf-8').write(h)
print(f"secoes: {h.count(chr(123)+' title:')} · em dash: {h.count(chr(8212))} · acertos {acertos}/{len(x)}")
