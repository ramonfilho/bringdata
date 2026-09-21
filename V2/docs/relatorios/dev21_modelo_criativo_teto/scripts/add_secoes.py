# -*- coding: utf-8 -*-
"""Secoes de MODELO (separacao) e CRIATIVO no painel do DEV21."""
import json,math
import pandas as pd
S='/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
SEP=json.load(open(S+'separacao.json')); CF=json.load(open(S+'criativo_fixo.json'))
U=pd.read_pickle(S+'criativo_unidades.pkl'); PIV=pd.read_pickle(S+'lucro_por_campanha.pkl')

def br(v,d=2):
    if v is None or (isinstance(v,float) and (pd.isna(v) or math.isinf(v))): return '-'
    return f'{v:,.{d}f}'.replace(',','@').replace('.',',').replace('@','.')
def mil(v): return f'{int(v):,}'.replace(',','.')
def curto(n,lim=42):
    n=str(n).replace('-vid-captação','').replace('-Briefing-AnaLaura-COMHEADLINE','')
    n=n.replace('DEV-','').replace('VARIAÇÃO-','').replace('-estão pagando para você aprender',' · pagando p/ aprender')
    return n if len(n)<=lim else n[:lim-1]+'…'
def sorte(p):
    """traduz o p-valor pra linguagem de gente: 1 chance em N de ser sorte"""
    if p is None: return '-'
    if p>=0.05: return f'<span class="ruido">1 em {br(1/p,0)}, pode ser sorte</span>'
    n=1/p
    return f'<b class="ok">1 em {mil(round(n))}</b>' if n<10000 else '<b class="ok">menos de 1 em 10 mil</b>'

CAB=('<thead><tr><th>{0}</th><th>Leads</th><th>% no D1-D2</th><th>Conv do fundo</th>'
  '<th>% no D9-D10</th><th>Alunos no topo</th><th>Conv do topo</th><th>Conv do resto</th>'
  '<th>Lift vs resto</th><th>Lift vs fundo</th><th>Chance de ser sorte</th></tr></thead>')
def linhas(rows,curtar=False):
    out=[]
    for r in rows:
        fraco=r['comp_top']<5
        agreg=r['rot'].startswith(('TODAS','TODOS')) or 'territ' in r['rot']
        lb='-' if r['lift_bottom'] is None else (('&gt;'+br(r['lift_bottom'])+'x') if r['lb_status']=='piso' else br(r['lift_bottom'])+'x')
        lr=('<span class="ruido">poucos alunos</span>' if fraco else
            f"<b>{br(r['lift_resto'])}x</b>"+(f"<br><span class=\"ic\">{br(r['lr_lo'])} a {br(r['lr_hi'])}</span>" if r['lr_lo'] else ''))
        nome=curto(r['rot']) if curtar else r['rot']
        out.append(f"<tr{' class=ag' if agreg else ''}><td>{nome}</td><td>{mil(r['leads'])}</td>"
          f"<td>{br(r['pct_bot'],1)}%</td><td>{br(r['conv_bot'],3)}%</td>"
          f"<td>{br(r['pct_top'],1)}%</td><td><b>{r['comp_top']}</b></td>"
          f"<td>{br(r['conv_top'],3)}%</td><td>{br(r['conv_resto'],3)}%</td>"
          f"<td>{lr}</td><td>{'-' if fraco else lb}</td><td>{sorte(r['ca_p'])}</td></tr>")
    return '\n'.join(out)

# ---------- criativo agregado + lucro por campanha ----------
CAMPS=[c for c in ['HQLB · QUENTE','HQLB · FRIO','Google Ads','TOP50 · FRIO','TOP30 · FRIO','TOP10 · FRIO','Lead · FRIO'] if c in PIV.columns]
ag=U[U['gasto']>0].groupby('criativo').agg(gasto=('gasto','sum'),leads=('leads','sum'),comp=('comp','sum'),fat=('fat','sum'))
TG=ag['gasto'].sum(); ag=ag.loc[PIV.index]
def cel(v):
    if abs(v)<1: return '<td class="z">-</td>'
    return f'<td class="{"pos" if v>0 else "neg"}">{br(v,0)}</td>'
gr=[]
for k,r in ag.iterrows():
    conv=r['comp']/r['leads'] if r['leads'] else None; roas=r['fat']/r['gasto']; luc=r['fat']-r['gasto']
    gr.append(f"<tr><td>{curto(k)}</td><td>{br(r['gasto'],0)}</td><td>{br(r['gasto']/TG*100,1)}%</td>"
      f"<td>{mil(r['leads'])}</td><td>{br(r['gasto']/r['leads']) if r['leads'] else '-'}</td><td>{int(r['comp'])}</td>"
      f"<td>{br(conv*100,2) if conv is not None else '-'}%</td>"
      f"<td class=\"{'pos' if roas>=1 else 'neg'}\">{br(roas)}</td>"
      f"<td class=\"{'pos' if luc>0 else 'neg'}\"><b>{br(luc,0)}</b></td>"
      +''.join(cel(float(PIV.loc[k,c])) for c in CAMPS)+"</tr>")
cd=U[(U['gasto']>0)&(~U['criativo'].isin(PIV.index))].groupby('criativo').agg(
    gasto=('gasto','sum'),leads=('leads','sum'),comp=('comp','sum'),fat=('fat','sum'))
gr.append(f"<tr class=ag><td>Cauda: {len(cd)} criativos abaixo de R$ 400</td><td>{br(cd['gasto'].sum(),0)}</td>"
  f"<td>{br(cd['gasto'].sum()/TG*100,1)}%</td><td>{mil(cd['leads'].sum())}</td><td>-</td><td>{int(cd['comp'].sum())}</td>"
  f"<td>{br(cd['comp'].sum()/max(cd['leads'].sum(),1)*100,2)}%</td><td>{br(cd['fat'].sum()/max(cd['gasto'].sum(),1))}</td>"
  f"<td><b>{br(cd['fat'].sum()-cd['gasto'].sum(),0)}</b></td>"+'<td class="z">-</td>'*len(CAMPS)+"</tr>")
CAB_CRI=('<thead><tr><th>Criativo</th><th>Gasto R$</th><th>% verba</th><th>Leads</th><th>CPL</th><th>Alunos</th>'
  '<th>Conv</th><th>ROAS</th><th>Lucro total R$</th>'+''.join(f'<th class="sp">{c.replace(" · ","<br>")}</th>' for c in CAMPS)+'</tr></thead>')
tab_ag_cri='\n'.join(gr)

# ---------- criativo dentro de cada campanha ----------
blocos=[]
for cat in ['HQLB · QUENTE','HQLB · FRIO','Google Ads','TOP50 · FRIO','TOP30 · FRIO','Lead · FRIO']:
    g=U[(U['cat']==cat)&(U['gasto']>0)].sort_values('gasto',ascending=False)
    if g.empty: continue
    GT=g['gasto'].sum(); LT=g['leads'].sum(); CT=g['comp'].sum(); ls=[]
    for _,r in g.iterrows():
        if r['gasto']<GT*0.02 and r['comp']==0: continue
        conv=r['comp']/r['leads'] if r['leads'] else None; roas=r['fat']/r['gasto'] if r['gasto'] else None
        ls.append(f"<tr><td>{curto(r['criativo'])}</td><td>{br(r['gasto']/GT*100,1)}%</td><td>{mil(r['leads'])}</td>"
          f"<td>{br(r['gasto']/r['leads']) if r['leads'] else '-'}</td><td>{int(r['comp'])}</td>"
          f"<td>{br(conv*100,2) if conv is not None else '-'}%</td>"
          f"<td class=\"{'pos' if roas and roas>=1 else 'neg'}\">{br(roas)}</td>"
          f"<td class=\"{'pos' if r['lucro']>0 else 'neg'}\">{br(r['lucro'],0)}</td></tr>")
    blocos.append(f"<h4 class=\"bl\">{cat} <span>R$ {br(GT,0)} de verba · {mil(LT)} leads · {int(CT)} alunos · "
      f"conversão da campanha {br(CT/LT*100,3) if LT else '-'}%</span></h4><div class=\"tw\"><table class=\"tb\">"
      f"<thead><tr><th>Criativo</th><th>% da verba</th><th>Leads</th><th>CPL</th><th>Alunos</th><th>Conv</th>"
      f"<th>ROAS</th><th>Lucro R$</th></tr></thead><tbody>"+'\n'.join(ls)+"</tbody></table></div>")
tab_por_camp='\n'.join(blocos)

HET=[('HQLB · QUENTE',0.79,1.17,1.49,0.760),('HQLB · FRIO',0.37,0.76,2.05,0.656),
     ('Google Ads',0.48,1.41,2.95,0.093),('TOP50 · FRIO',0.35,0.88,2.55,0.881),('Lead · FRIO',0.18,0.33,1.80,0.627)]
def _het(c,a,b,r,p):
    return (f"<tr><td>{c}</td><td>{br(a,2)}%</td><td>{br(b,2)}%</td><td>{br(r,2)}x</td>"
            f"<td>{sorte(p)}</td><td>{'diferença real' if p<0.05 else 'dentro do ruído'}</td></tr>")
t_het='\n'.join(_het(*x) for x in HET)

SEC=f'''    {{ title:"O modelo separou quem compra?",
      sub:"Régua do Champion abr_28. Três leituras da mesma coisa: o topo contra o resto, o topo contra o fundo, e se a conversão sobe de forma consistente ao longo dos dez decis.",
      html:`<div class="tw"><table class="tb">{CAB.format('Campanha')}<tbody>
{linhas(SEP['abr28'])}
</tbody></table></div>
<p style="margin-top:14px"><b>A coluna "% no D1-D2" mede se a campanha fez o trabalho dela.</b> O quente do Champion joga só <b>2,8%</b> dos leads no fundo da régua e o frio <b>6,3%</b>, contra <b>26,7%</b> do Lead Padrão. As campanhas de modelo trazem de quatro a dez vezes menos lead desqualificado.</p>
<p><b>Onde aparece "poucos alunos", a venda existiu, mas não no topo.</b> No TOP50, dos 8 alunos, 4 caíram em D9-D10 (metade dos alunos em 22% dos leads). No TOP30, dos 9 alunos só 1 chegou ao topo: 5 pararam em D4-D6. Com esse punhado, qualquer taxa calculada seria ruído, então a coluna fica vazia mas o número de alunos aparece ao lado.</p>` }},
    {{ title:"O Champion dentro das campanhas que ele mesmo comanda",
      sub:"O que chamamos de território: as campanhas com a etiqueta LEADHQLB, cujo público a Meta monta a partir do evento que o abr_28 dispara. Ele pontua todo lead que entra, mas só nessas campanhas a nota dele decide quem o anúncio persegue.",
      html:`<div class="tw"><table class="tb">{CAB.format('Recorte')}<tbody>
{linhas(SEP['abr28_terr'])}
</tbody></table></div>
<p style="margin-top:14px"><b>No território dele, o modelo separa</b> (chance de ser sorte de 1 em 54). O resultado está concentrado: separa no quente e no Google, e <b>no frio do HQLB não separa</b>. É o único ponto do lançamento onde a nota não ordenou nada.</p>` }},
    {{ title:"O Challenger jul_24 na mesma régua",
      sub:"O território dele são as campanhas TOP10, TOP30 e TOP50. Ele entrou em 25/07 e cobre 69% da captação, por isso os leads da primeira semana não têm nota dele.",
      html:`<div class="tw"><table class="tb">{CAB.format('Recorte')}<tbody>
{linhas(SEP['jul24'])}
</tbody></table></div>
<p style="margin-top:14px"><b>Nos mesmos 8.438 leads do quente, o jul_24 separa mais que o abr_28</b>: 1,50x contra 1,29x. No território próprio, mesmo com só 6 alunos no topo, a separação aparece: <b>2,66x</b>, e o topo rende <b>7,47x</b> o fundo.</p>` }},
    {{ title:"Criativo: quem levou a verba, quem devolveu, e de onde veio o lucro",
      sub:"Todas as campanhas somadas. As colunas da direita abrem o lucro total de cada criativo pela campanha em que ele rodou. Verba por anúncio: Meta pela ad_insights, Google puxado por ID na API.",
      html:`<div class="tw"><table class="tb">{CAB_CRI}<tbody>
{tab_ag_cri}
</tbody></table></div>
<p style="margin-top:14px"><b>Três criativos da Meta levaram 65,8% de toda a verba.</b> O AD0150-AD07 sozinho gerou R$ 50.952 de lucro, e as colunas da direita mostram de onde: R$ 24.130 no quente, R$ 19.508 no frio, R$ 5.881 no TOP30. Ele é o único que ganhou dinheiro em todas as campanhas onde rodou.</p>
<p><b>O AD0160-AD08 é o oposto: concentrado.</b> Dos R$ 18.043 de lucro dele, R$ 15.548 vieram só do quente; no frio ele empatou e nas TOP perdeu. E o AD0140 do Google consumiu R$ 16.790, quase 10% do lançamento, para voltar empatado.</p>` }},
    {{ title:"Cada criativo dentro de cada campanha",
      sub:"A fatia da verba que cada um recebeu naquela campanha, contra a conversão que ela comprou.",
      html:`{tab_por_camp}
<p style="margin-top:14px"><b>O caso mais claro é o Google.</b> O AD0140 ficou com 52,2% da verba e devolveu ROAS 0,99, enquanto o AD0150 "com música" ficou com 24,9% e devolveu 2,37. No HQLB frio, o AD0160-AD11 e o AD0370 queimaram R$ 2.939 juntos com retorno abaixo de 0,70.</p>` }},
    {{ title:"O criativo mexeu a conversão?",
      sub:"Comparação entre os criativos da mesma campanha, contando só os que tiveram 200 leads ou mais.",
      html:`<div class="tw"><table class="tb"><thead><tr><th>Campanha</th><th>Pior criativo</th><th>Melhor criativo</th><th>Amplitude</th><th>Chance de ser sorte</th><th>Leitura</th></tr></thead><tbody>
{t_het}
</tbody></table></div>
<p style="margin-top:14px"><b>Dentro da mesma campanha, este lançamento não distingue criativo por conversão.</b> No HQLB quente o intervalo do melhor contra o pior vai de 0,53x a 6,24x: cabe tudo ali dentro. Só o Google chega perto.</p>
<p><b>Isso não desmente a alavanca de 2,1x do criativo</b>, que vem de 534 unidades em 26 lançamentos. Diz outra coisa: <b>um lançamento sozinho não tem tamanho para medir criativo por conversão</b>, e é por isso que a fórmula do teto pesa o histórico de cada criativo. A leitura do DEV21 sobre criativo é de <b>alocação de verba e custo por lead</b>, não de conversão.</p>` }},
    {{ title:"As duas variáveis juntas",
      sub:"O mesmo teste de separação, agora com o criativo mantido fixo: só leads que vieram do mesmo anúncio são comparados entre si. Se o lift sobreviver aqui, ele não é criativo disfarçado.",
      html:`<h4 class="bl">Champion abr_28 <span>cobre 24.047 leads da base cheia</span></h4>
<div class="tw"><table class="tb">{CAB.format('Criativo')}<tbody>
{linhas(CF['abr28'],curtar=True)}
</tbody></table></div>
<h4 class="bl" style="margin-top:22px">Challenger jul_24 <span>cobre 16.509 leads (entrou em 25/07)</span></h4>
<div class="tw"><table class="tb">{CAB.format('Criativo')}<tbody>
{linhas(CF['jul24'],curtar=True)}
</tbody></table></div>
<p style="margin-top:14px"><b>Os dois modelos sobrevivem ao teste, e com quase o mesmo número.</b> Champion 1,35x e Challenger 1,37x, ambos com chance de ser sorte abaixo de 1 em 4 mil. Segurando a campanha fixa em vez do criativo, o Champion dava 1,27x.</p>
<p><b>Isso elimina a explicação alternativa.</b> A separação que o modelo mostra não é efeito do criativo nem da campanha, porque sobrevive a fixar os dois, por caminhos independentes.</p>` }},
'''
p=S+'painel_dev21.html'; h=open(p,encoding='utf-8').read()
assert '    { title:"Como ler",' in h
h=h.replace('    { title:"Como ler",', SEC+'    { title:"Como ler",',1)
extra='''<style>
h4.bl{margin:20px 0 4px;font-size:14px;font-weight:700;letter-spacing:.01em}
h4.bl span{font-weight:400;font-size:12px;color:var(--muted,#777);margin-left:8px}
.tb b.ok{color:#1a7f52} .tb .ic{font-size:10.5px;color:var(--muted,#888);white-space:nowrap}
.tb .ruido{color:var(--muted,#999);font-style:italic;font-size:11.5px}
.tb th.sp{font-size:9.5px;border-left:1px solid rgba(128,128,128,.28)}
.tb td.z{color:var(--muted,#bbb);text-align:center}
@media (prefers-color-scheme:dark){.tb b.ok{color:#5cc192}.tb td.z{color:#555}}
</style>'''
h=h.replace('</style>','</style>\n'+extra,1)
open(p,'w',encoding='utf-8').write(h)
print(f"secoes: {h.count(chr(123)+' title:')} · em dash: {h.count(chr(8212))} · bytes {len(h):,}")
