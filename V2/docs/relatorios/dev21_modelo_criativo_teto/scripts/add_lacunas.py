# -*- coding: utf-8 -*-
"""Emenda no painel as secoes que fecham as lacunas:
   S1 o que a regua valeu em dinheiro (ROAS por balde de decil)   -> antes do bloco criativo
   S2 separar nao e a mesma coisa que dar lucro                    -> antes do bloco criativo
   S3 a campanha de Lead recebeu os melhores criativos             -> antes de "As duas variaveis"
   S4 CPL barato preve lucro?  (a corrida + merito + 2x2)          -> antes de "Como ler"
   S5 a proxima alavanca: a fala do video                          -> antes de "Como ler"
Rodar SEMPRE sobre o painel_dev21.html corrente (ele e a fonte de verdade, nao o gera_final).
"""
import json, math
import pandas as pd
S = '/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/'
J = json.load(open(S + 'lacunas.json'))
SEP = json.load(open(S + 'separacao.json'))


def br(v, d=2):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return '-'
    return f'{v:,.{d}f}'.replace(',', '@').replace('.', ',').replace('@', '.')


def rs(v, d=0):
    """Reais com sinal na frente do cifrao, que e como se le: -R$ 2.331, nao R$ -2.331."""
    return ('-' if v < 0 else '') + 'R$ ' + br(abs(v), d)


def pv(p, lim=0.05):
    if p is None:
        return '-'
    return f'<b class="ok">{br(p*100,1)}%</b>' if p < lim else f'{br(p*100,1)}%'


# ============================================================ S1 ROAS por balde
B = J['baldes']['CHAMPION abr_28 · tudo']['linhas']
lin = []
for r in B:
    cls = 'pos' if r['roas'] >= 2 else ('neg' if r['roas'] < 1 else '')
    lin.append(f"<tr><td><b>{r['balde']}</b></td><td>{br(r['leads'],0)}</td><td>{r['comp']}</td>"
               f"<td>{br(r['conv']*100,3)}%</td><td class=\"sp\">R$ {br(r['cpl'])}</td>"
               f"<td>R$ {br(r['ticket'],0)}</td><td>R$ {br(r['fat'],0)}</td><td>R$ {br(r['custo'],0)}</td>"
               f"<td class=\"{cls}\"><b>{br(r['roas'])}</b></td>"
               f"<td class=\"{'pos' if r['lucro']>0 else 'neg'}\">{rs(r['lucro'])}</td></tr>")
CH = J['baldes']['CHALLENGER jul_24 · tudo']['linhas']
lin2 = []
for r in CH:
    cls = 'pos' if r['roas'] >= 2 else ('neg' if r['roas'] < 1 else '')
    lin2.append(f"<tr><td><b>{r['balde']}</b></td><td>{br(r['leads'],0)}</td><td>{r['comp']}</td>"
                f"<td>{br(r['conv']*100,3)}%</td><td class=\"sp\">R$ {br(r['cpl'])}</td>"
                f"<td class=\"{cls}\"><b>{br(r['roas'])}</b></td>"
                f"<td class=\"{'pos' if r['lucro']>0 else 'neg'}\">{rs(r['lucro'])}</td></tr>")
cpl_min = min(r['cpl'] for r in B); cpl_max = max(r['cpl'] for r in B)
S1 = f'''    {{ title:"O que a régua do modelo valeu em dinheiro",
      sub:"Cada lead foi custeado pelo CPL da unidade em que ele caiu. Isso segura o preço e deixa só a receita variar, que é exatamente a pergunta: a nota do lead previu dinheiro, e não só compra.",
      chart:{{ type:"bars", unit:"", dec:2, color:"accent", data:[
        {",".join(f'{{label:"{r["balde"]}", mean:{r["roas"]:.2f}}}' for r in B)}] }},
      html:`<div class="tw"><table class="tb"><thead><tr><th>Balde</th><th>Leads</th><th>Alunos</th><th>Conv</th>
<th class="sp">CPL pago</th><th>Ticket</th><th>Faturamento</th><th>Custo</th><th>ROAS</th><th>Lucro</th></tr></thead><tbody>
{chr(10).join(lin)}
</tbody></table></div>
<p style="margin-top:14px"><b>O número que prova a tese está na coluna do CPL: ela é plana.</b> Do fundo ao topo da régua o lançamento pagou entre <b>R$ {br(cpl_min)}</b> e <b>R$ {br(cpl_max)}</b> pelo lead, uma variação de {br((cpl_max/cpl_min-1)*100,0)}%. O ROAS foi de <b>{br(B[0]['roas'])}</b> a <b>{br(B[-1]['roas'])}</b>. Como o custo não mexeu, toda a diferença é receita, e quem a ordenou foi o modelo.</p>
<p><b>O fundo da régua destrói dinheiro e o topo paga o lançamento.</b> Os {br(B[0]['leads'],0)} leads do D1-D2 deram prejuízo de R$ {br(-B[0]['lucro'],0)}. Os {br(B[-1]['leads'],0)} do D9-D10 deram <b>R$ {br(B[-1]['lucro'],0)}</b> de lucro.</p>
<p><b>Uma coisa o modelo não faz: prever quanto a pessoa gasta.</b> O ticket é praticamente o mesmo em todos os baldes, de R$ {br(min(r['ticket'] for r in B),0)} a R$ {br(max(r['ticket'] for r in B),0)}. Ele acerta <i>quem</i> compra, não <i>quanto</i> compra. E os dois baldes de cima empataram entre si neste lançamento ({br(B[-2]['conv']*100,3)}% contra {br(B[-1]['conv']*100,3)}%), então aqui a separação foi 40% de cima contra 60% de baixo. Na referência histórica de 86 mil leads o degrau entre eles existe (1,407% contra 0,934%, 1,5x): o empate é deste lançamento, não da régua.</p>
<h4 class="cap">O Challenger jul_24 na mesma conta</h4>
<div class="tw"><table class="tb"><thead><tr><th>Balde</th><th>Leads</th><th>Alunos</th><th>Conv</th>
<th class="sp">CPL pago</th><th>ROAS</th><th>Lucro</th></tr></thead><tbody>
{chr(10).join(lin2)}
</tbody></table></div>
<p style="margin-top:14px">Mesmo desenho, separação mais forte: o D7-D8 do Challenger entrega ROAS <b>{br(CH[-2]['roas'])}</b>, o melhor balde de qualquer uma das duas réguas.</p>` }},
'''

# ================================================ S2 separar nao e dar lucro
mer = {r['cat']: r for r in J['merito']['linhas']}
sep = {r['rot']: r for r in SEP['abr28']}
ordem = ['HQLB · QUENTE', 'HQLB · FRIO', 'Google Ads', 'TOP30 · FRIO', 'TOP50 · FRIO',
         'TOP10 · FRIO', 'Lead · FRIO']
lin = []
for c in ordem:
    m = mer.get(c); s = sep.get(c)
    if not m:
        continue
    lf = br(s['lift_resto']) + 'x' if s and s.get('lift_resto') else '<span class="z">ruído</span>'
    p = pv(s['ca_p']) if s and s.get('ca_p') is not None else '-'
    sepa = ('<b class="ok">sim</b>' if (s and s.get('ca_p') is not None and s['ca_p'] < 0.05)
            else '<b class="neg">não</b>' if s and s.get('ca_p') is not None else '-')
    lin.append(f"<tr><td>{c}</td><td>{lf}</td><td>{p}</td><td>{sepa}</td>"
               f"<td class=\"sp\">{br(m['conv']*100,3)}%</td>"
               f"<td class=\"{'pos' if m['roas']>=1 else 'neg'}\"><b>{br(m['roas'])}</b></td>"
               f"<td class=\"{'pos' if m['lucro']>0 else 'neg'}\">{rs(m['lucro'])}</td></tr>")
hf = mer['HQLB · FRIO']; lf_ = mer['Lead · FRIO']

# -- a serie historica do abr_28 no frio (historico_frio2.py; papel real pela verba na
#    Meta desde 22/06, nao pelo carimbo champion_run_id que so vale a partir de 25/07)
HF = json.load(open(S + 'historico_frio2.json'))
hl = [r for r in HF['linhas'] if r['temp'] == 'FRIO']
hl.sort(key=lambda r: r['cap'])
hlin = []
for r in hl:
    pp = 'principal' if r['depois'] else 'sombra'
    dest = ' class="ag"' if r['lf'] == 'DEV21' else ''
    hlin.append(f"<tr{dest}><td><b>{r['lf']}</b></td><td>{pp}</td><td>{br(r['leads'],0)}</td>"
                f"<td>{r['comp']}</td><td>{br(r['ct']*100,3)}%</td><td>{br(r['cr']*100,3)}%</td>"
                f"<td class=\"{'pos' if r['lift']>=1.5 else ''}\"><b>{br(r['lift'])}x</b></td>"
                f"<td>{br(r['pct_fundo']*100,1)}%</td></tr>")
FT = HF['FRIO · TODOS os lançamentos']; FH = HF['FRIO-HQLB · TODOS os lançamentos']
HIST = f'''<h4 class="cap">O histórico: o abr_28 no público frio, lançamento a lançamento</h4>
<p style="margin-bottom:12px">Antes de decidir qualquer coisa, a pergunta certa: a falha do DEV21 é o padrão dele ou a exceção? A nota do abr_28 está gravada em todo lead desde 25/05, primeiro rodando <b>em sombra</b> (pontuava tudo, sem comandar a verba) e, a partir de <b>22/06</b>, como o modelo principal da conta, quando passou a levar o orçamento e o objetivo de otimização na Meta.</p>
<div class="tw"><table class="tb"><thead><tr><th>Lançamento</th><th>Papel</th><th>Leads frios</th><th>Alunos</th><th>Conv topo</th><th>Conv resto</th><th>Lift</th><th>%D1-D2</th></tr></thead><tbody>
{chr(10).join(hlin)}
</tbody></table></div>
<p style="margin-top:14px"><b>O DEV21 é o pior ponto da série, não o padrão.</b> No público frio o abr_28 ficou acima de 1 em <b>{FT['acima']} de {FT['n_lf']} lançamentos</b>, com lift agrupado de <b>{br(FT['rr'])}x</b> (intervalo de {br(FT['lo'])} a {br(FT['hi'])}, segurando o lançamento fixo) em {br(FT['leads'],0)} leads. Restringindo só às campanhas HQLB frias, {br(FH['rr'])}x em {FH['n_lf']} lançamentos. <b>Desativar no frio agora seria reagir ao pior ponto de uma série que aponta para o outro lado.</b></p>
<p><b>O que a série pede é vigilância, não desligamento.</b> Os dois lançamentos mais recentes são os dois mais fracos ({br(hl[-2]['lift'])}x no LF63 e {br(hl[-1]['lift'])}x no DEV21). Dois pontos não fazem tendência, mas fazem um alerta: se o próximo lançamento frio vier abaixo de 1, aí sim a conversa de desligar ou retreinar se abre, com três pontos na mão. E repare na coluna %D1-D2 caindo de 19,8% para 9,5% ao longo da série: o público frio entregue foi ficando mais limpo, que é exatamente a compressão que dificulta o ranking descrita acima.</p>
<p><b>Três ressalvas que acompanham este ponto de atenção.</b> Primeira: o ponto fraco do DEV21 pode ser em boa parte <b>tamanho de amostra</b>. Com 81 compradores frios, o lift de 1,12x carrega um intervalo que vai de 0,69 a 1,83, e o 1,87x da série fica na beira de fora: o dado é compatível quase por inteiro com a escada de sempre mais azar de amostra. Segunda: mesmo onde o ranking falha, <b>separar não é dar lucro</b>, e o frio deste lançamento devolveu R$ 17.654 com ROAS 1,29. Terceira: se o terceiro ponto fraco vier, a <b>solução já está desenhada, e não é retreinar do jeito simples</b>. Retreinar o mesmo formulário com dado mais fresco já foi testado: o jul_24 ganha no quente (1,50x contra 1,29x) mas <b>empatou no frio deste lançamento</b> (1,26x contra 1,23x nos mesmos leads). Se a causa é a compressão descrita acima, o formulário saturou, e a saída é colocar no score <b>o que o formulário não vê</b>. O arsenal, já medido e em coleta: <b>entrar no grupo de WhatsApp</b> (separa ~3x dentro do mesmo decil; coleta no ar desde 10/06); a <b>nota do criativo por plataforma, com a fala do vídeo, dentro do score</b> (a única variante testada cujo ganho não toca o zero; no teste dos quatro braços, 92 compradores contra 67 na mesma fatia de tráfego); o <b>texto no teto</b> (a fala do vídeo como palpite inicial do criativo estreante na nota que ajusta o teto); e o <b>selo de comprador Hotmart</b> (~2x segurando a nota fixa, medido em 323 mil leads; a fusão com o modelo ainda não foi testada, de propósito, porque só o selo capturado ANTES da venda vale, e essa coleta roda desde 30/07). Mais duas possibilidades ainda sem dado: a <b>página de captura</b> e o <b>campo de texto aberto da pesquisa</b>. O A/B champion contra challenger deixa qualquer troca sem risco: o desafiante roda ao lado do titular até provar.</p>'''

S2 = f'''    {{ title:"Separar não é a mesma coisa que dar lucro",
      sub:"As duas leituras lado a lado. À esquerda, se o modelo ordenou os leads daquela campanha. À direita, se aquela campanha devolveu dinheiro. Elas não andam juntas, e é isso que decide o que fazer.",
      html:`<div class="tw"><table class="tb"><thead><tr><th>Campanha</th><th>Lift do topo</th><th>Chance de ser sorte</th><th>Separou?</th>
<th class="sp">Conversão</th><th>ROAS</th><th>Lucro</th></tr></thead><tbody>
{chr(10).join(lin)}
</tbody></table></div>
<p style="margin-top:14px"><b>O caso que interessa é o HQLB frio.</b> Ali o modelo <b>não</b> separou (lift {br(sep['HQLB · FRIO']['lift_resto'])}x, {br(sep['HQLB · FRIO']['ca_p']*100,1)}% de chance de ser sorte), e mesmo assim a campanha devolveu <b>R$ {br(hf['lucro'],0)}</b> de lucro com ROAS {br(hf['roas'])}. Ordenar leads e gerar lucro são coisas diferentes.</p>
<p class="ic"><b>Como ler a coluna do lift junto com a da sorte.</b> Um lift grande acompanhado de uma chance de sorte grande, como o 3,60x do TOP50 com 9,1%, não quer dizer que o modelo funcionou ali: quer dizer que a campanha é pequena demais para saber. Com 9 alunos no total, trocar um único comprador de balde vira o número. A coluna \"Separou?\" só diz sim quando o resultado sobrevive a esse teste.</p>
<p><b>A explicação é que o modelo faz dois trabalhos, e só um deles é o ranking.</b> O primeiro trabalho acontece <b>antes de o lead existir</b>: o evento que o modelo dispara para a Meta a cada lead bom vira o alvo de otimização da campanha, e a Meta sai caçando gente parecida com quem já pontuou alto. É assim que o sinal <b>constrói o público</b>. O segundo trabalho é <b>ordenar os leads</b> depois que eles chegam. São medições em momentos diferentes, e é por isso que uma pode falhar com a outra funcionando.</p>
<p><b>E há um motivo mecânico para o ranking parecer fraco justamente onde o público é bom.</b> Quando o primeiro trabalho funciona, ele corta o fundo da régua antes de o lead entrar: o HQLB frio recebeu só {br(hf['fundo']*100,1)}% de leads no D1-D2, contra {br(lf_['fundo']*100,1)}% do Lead frio. Sobra um público comprimido no meio e no topo, e ordenar gente parecida entre si é muito mais difícil do que separar bom de ruim. É o mesmo efeito de comparar aprovados de um vestibular: entre quem já passou, a nota da prova quase não prevê o desempenho no curso, porque a seleção já jogou fora a variação que a nota enxergava. A prova de que o público veio melhor está na conversão: <b>{br(hf['conv']*100,3)}%</b> no HQLB frio contra <b>{br(lf_['conv']*100,3)}%</b> do Lead frio, {br(hf['conv']/lf_['conv'])} vezes mais.</p>
{HIST}` }},
'''

# ================================== S3 os melhores criativos foram para o Lead
lv = J['lead_vs_ml']
S3 = f'''    {{ title:"A campanha de Lead recebeu os melhores criativos e ainda assim perdeu dinheiro",
      sub:"Aqui \\"histórico do criativo\\" quer dizer quantos leads aquele anúncio já tinha acumulado nos 26 lançamentos anteriores, o currículo dele. Não tem relação com o volume que ele trouxe no DEV21.",
      html:`<div class="tw"><table class="tb"><thead><tr><th>&nbsp;</th><th>Campanha de <b>Lead</b></th><th>Campanhas de <b>modelo</b></th></tr></thead><tbody>
<tr><td>Currículo do criativo (leads acumulados antes do DEV21)</td><td class="pos"><b>38.101</b></td><td>808</td></tr>
<tr><td>Nota histórica desse currículo</td><td class="pos"><b>1,05</b>, na média</td><td>0,61, abaixo da média</td></tr>
<tr><td>CPL pago</td><td class="pos"><b>R$ 4,62</b>, o mais barato do lançamento</td><td>R$ 6,07 a R$ 9,08</td></tr>
<tr><td>Leads entregues no fundo da régua (D1-D2)</td><td class="neg"><b>{br(lv['lead_qualidade']['pct_fundo']*100,1)}%</b></td><td>{br(lv['ml_qualidade']['pct_fundo']*100,1)}%</td></tr>
<tr><td>Leads entregues no topo (D9-D10)</td><td class="neg">{br(lv['lead_qualidade']['pct_topo']*100,1)}%</td><td class="pos"><b>{br(lv['ml_qualidade']['pct_topo']*100,1)}%</b></td></tr>
<tr class="ag"><td>Resultado</td><td class="neg"><b>ROAS 0,89 · prejuízo de R$ 813</b></td><td class="pos"><b>ROAS 1,90</b></td></tr>
</tbody></table></div>
<p style="margin-top:14px"><b>Os três anúncios que rodaram na campanha de Lead são os de maior currículo do lançamento inteiro</b>, com 42.180, 38.101 e 28.634 leads de passado. A qualidade desse passado, medida pela nota histórica (quanto o anúncio converte contra a média dos lançamentos em que rodou, onde 1,00 é a média), foi de <b>1,06</b> ponderada pelo gasto: um baralho na média, não acima dela. Já as campanhas de modelo rodaram um baralho claramente pior: nota ponderada de <b>0,64</b>.</p>
<p><b>É por isso que o argumento fecha nas duas direções.</b> A campanha de Lead perdeu dinheiro com criativos na média e com o lead mais barato do lançamento: preço a favor, criativo neutro, e ainda assim ROAS 0,89. As campanhas de modelo entregaram ROAS 1,90 carregando criativos <b>65% piores</b> que os do Lead pela nota histórica. A vitória delas não veio do criativo, e a derrota do Lead não veio nem do criativo nem do preço. O que sobrou de diferente é <b>para quem a Meta entregou os anúncios</b>.</p>
<p><b>Uma ressalva honesta:</b> nenhum dos três criativos do Lead rodou em qualquer outra campanha, então não dá para parear o mesmo anúncio entre a campanha de Lead e as de modelo. Mas o desequilíbrio pende para o lado do Lead, ou seja, contra a conclusão, o que só a deixa mais segura.</p>` }},
'''

# ============================================ S4 CPL barato preve lucro?
C = {r['rot'][:2]: r for r in J['corrida2']}
nomes = {'R0': 'CPL barato (teto plano, não olha o lead)',
         'R1': 'Teto com o modelo', 'R2': 'Teto final: modelo x criativo'}
lin = []
for k in ('R0', 'R1', 'R2'):
    r = C[k]
    dest = ' class="ag"' if k == 'R2' else ''
    lin.append(f"<tr{dest}><td><b>{nomes[k]}</b></td><td>{r['na']} / {r['nb']}</td>"
               f"<td class=\"sp\">{br(r['conva']*100,3)}%</td><td>{br(r['convb']*100,3)}%</td>"
               f"<td><b>{br(r['razao_conv'])}x</b></td>"
               f"<td>{br(r['ra'])} / {br(r['rb'])}</td><td><b>{br(r['razao'])}x</b></td>"
               f"<td>R$ {br(r['lpr_a'])} / R$ {br(r['lpr_b'])}</td><td>{pv(r['fisher'])}</td></tr>")
q = {(x['barato'], x['dentro']): x for x in J['quadrantes'] if x['n']}
sp2 = J['spearman2']
mlin = []
for c in ordem:
    m = mer.get(c)
    if not m:
        continue
    mlin.append(f"<tr><td>{c}</td><td>{br(m['roas'])}</td><td>{br(m['roas']/J['merito']['roas0'])}</td>"
                f"<td class=\"{'pos' if m['f_qual']>=1 else 'neg'}\"><b>{br(m['f_qual'])}</b></td>"
                f"<td class=\"{'pos' if m['f_prec']>=1 else 'neg'}\"><b>{br(m['f_prec'])}</b></td>"
                f"<td class=\"{'pos' if m['lucro']>0 else 'neg'}\">{rs(m['lucro'])}</td></tr>")
cc = q[(False, True)]
S4 = f'''    {{ title:"CPL barato prevê lucro?",
      sub:"Três regras de decisão sobre as mesmas 25 unidades de verba, com a mesma fórmula, o mesmo valor por venda e o mesmo alvo de ROAS 2. A única diferença entre elas é quanta informação cada uma enxerga.",
      html:`<p style="margin-bottom:14px">Para a comparação ser justa, o corte de \\"CPL barato\\" não pode ser um número escolhido a dedo. Ele é a <b>mesma conta do teto</b>, só que usando a conversão média do negócio em vez da nota do lead: <b>R$ {br(J['teto_plano'])}</b> para todo mundo, igual. É literalmente o teto de quem não olha o lead nem o criativo.</p>
<div class="tw"><table class="tb"><thead><tr><th>Regra</th><th>Aprova / reprova</th><th class="sp">Conv aprovada</th><th>Conv reprovada</th><th>Razão</th>
<th>ROAS aprov. / repr.</th><th>Razão</th><th>Lucro por real</th><th>Chance de ser sorte</th></tr></thead><tbody>
{chr(10).join(lin)}
</tbody></table></div>
<p style="margin-top:14px"><b>O veredito é em lucro, e ele é este: das 25 unidades, a régua do teto guarda no grupo aprovado {br(C['R2']['luca']/(C['R2']['luca']+C['R2']['lucb'])*100,0)}% do lucro do lançamento; a régua do CPL guarda {br(C['R0']['luca']/(C['R0']['luca']+C['R0']['lucb'])*100,0)}%.</b> Régua de decisão se julga pelo que ela manda cortar: o grupo que a regra do CPL reprova gerou <b>R$ {br(C['R0']['lucb'],0)}</b> de lucro (ROAS {br(C['R0']['rb'])}, dinheiro bom que seria cortado), enquanto o grupo que o teto reprova gerou R$ {br(C['R2']['lucb'],0)} (ROAS {br(C['R2']['rb'])}, perto do peso morto).</p>
<p><b>E sim, às vezes o lead barato que converte menos compensa. O teto é exatamente a conta de quando compensa.</b> A prova são as duas unidades mais baratas do lançamento, lado a lado, as duas na campanha de Lead: pela régua do CPL, as duas melhores compras do DEV21. O <b>AD0027</b> (CPL R$ 3,74) convertia 32% abaixo da média mas custava 45% menos: o desconto cobre o déficit, e o teto aprovou (valia até R$ 4,87). Devolveu <b>ROAS 2,26</b>. O <b>AD0150-V0</b> (CPL R$ 3,58) convertia 76% abaixo da média e custava só 47% menos: o desconto não cobre, e o teto reprovou (valia até R$ 2,94). Devolveu <b>0,84</b>. O CPL não distingue os dois; o teto distinguiu os dois <b>antes do resultado</b>.</p>
<p><b>"Ficar abaixo do teto" e "custo por qualificação" são a mesma régua dita de dois jeitos.</b> O teto da unidade é a conversão esperada dela (modelo x criativo) vezes o valor da venda, dividido pelo ROAS alvo. Pagar abaixo do teto é o mesmo que exigir que o <b>custo por venda esperada</b> fique abaixo de R$ 817, que é metade dos R$ 1.634 que a venda vale com o fator de rastreamento. CPL barato exige preço baixo em absoluto; o teto exige preço baixo <b>em relação ao que aquele lead vale</b>.</p>
<p><b>Por que a régua do CPL erra: ela não enxerga qualidade.</b> Ela aprova leads que convertem {br(C['R0']['conva']*100,3)}% e reprova leads que convertem {br(C['R0']['convb']*100,3)}%, a mesma coisa. As regras de teto aprovam leads que convertem <b>{br((C['R2']['razao_conv']-1)*100,0)}% mais</b> que os que reprovam. O ganho de ROAS que a regra do CPL ainda assim mostra é em parte aritmético, porque o CPL é o denominador do próprio ROAS, e o número acima mostra o que sobra dele: um corte que joga fora R$ {br(C['R0']['lucb'],0)} de lucro para se proteger de pouco.</p>
<p><b>Sem corte nenhum a conclusão é a mesma.</b> Ordenando as 25 unidades pelo CPL puro, a concordância com o ROAS é de {br(sp2['cpl'][0])} numa régua de menos um a mais um, com {br(sp2['cpl'][1]*100,1)}% de chance de ser acaso: <b>não passa</b>. Ordenando pela folga contra o teto do modelo, a concordância vai para <b>{br(sp2['folga1'][0])}</b> com {br(sp2['folga1'][1]*100,2)}% de chance de acaso. Dividir todo mundo pelo mesmo teto plano dá exatamente a mesma ordem do CPL puro, o que é a prova de que os dois são a mesma regra.</p>
<h4 class="cap">Por que a campanha rendeu o que rendeu: qualidade dividida por preço</h4>
<p style="margin-bottom:12px">O ROAS de uma campanha contra o do lançamento se abre em exatamente dois fatores que se multiplicam: a conversão dela sobre a geral (<b>qualidade</b>) e o CPL geral sobre o dela (<b>preço</b>). Referência do lançamento: conversão {br(J['merito']['conv0']*100,3)}%, CPL R$ {br(J['merito']['cpl0'])}.</p>
<div class="tw"><table class="tb"><thead><tr><th>Campanha</th><th>ROAS</th><th>vs referência</th><th>Qualidade</th><th>Preço</th><th>Lucro</th></tr></thead><tbody>
{chr(10).join(mlin)}
</tbody></table></div>
<p style="margin-top:14px"><b>A última linha responde a pergunta do título sozinha.</b> A campanha de Lead teve o <b>melhor preço do lançamento</b>, {br((mer['Lead · FRIO']['f_prec']-1)*100,0)}% abaixo da média, e mesmo assim perdeu dinheiro, porque a qualidade foi {br(mer['Lead · FRIO']['f_qual'])}. O Google é o espelho: a segunda melhor qualidade do lançamento ({br(mer['Google Ads']['f_qual'])}), estragada por um preço {br((1-mer['Google Ads']['f_prec'])*100,0)}% pior que a média.</p>
<h4 class="cap">O quadrante que decide a troca de métrica</h4>
<div class="tw"><table class="tb"><thead><tr><th>Quadrante</th><th>Unidades</th><th>Verba</th><th>Conversão</th><th>ROAS</th><th>Lucro</th></tr></thead><tbody>
<tr><td>CPL barato · dentro do teto</td><td>{q[(True,True)]['n']}</td><td>R$ {br(q[(True,True)]['gasto'],0)}</td><td>{br(q[(True,True)]['conv']*100,3)}%</td><td class="pos">{br(q[(True,True)]['roas'])}</td><td>{rs(q[(True,True)]['lucro'])}</td></tr>
<tr><td>CPL barato · acima do teto</td><td>{q[(True,False)]['n']}</td><td>R$ {br(q[(True,False)]['gasto'],0)}</td><td>{br(q[(True,False)]['conv']*100,3)}%</td><td>{br(q[(True,False)]['roas'])}</td><td>{rs(q[(True,False)]['lucro'])}</td></tr>
<tr class="ag"><td><b>CPL caro · dentro do teto</b></td><td><b>{cc['n']}</b></td><td><b>R$ {br(cc['gasto'],0)}</b></td><td><b>{br(cc['conv']*100,3)}%</b></td><td class="pos"><b>{br(cc['roas'])}</b></td><td class="pos"><b>R$ {br(cc['lucro'],0)}</b></td></tr>
<tr><td>CPL caro · acima do teto</td><td>{q[(False,False)]['n']}</td><td>R$ {br(q[(False,False)]['gasto'],0)}</td><td class="neg">{br(q[(False,False)]['conv']*100,3)}%</td><td class="neg">{br(q[(False,False)]['roas'])}</td><td>{rs(q[(False,False)]['lucro'])}</td></tr>
</tbody></table></div>
<p style="margin-top:14px"><b>A linha destacada é o motivo de trocar de métrica.</b> São {cc['n']} unidades com CPL acima da média, que qualquer régua de CPL teria marcado como caras, e que entregaram ROAS <b>{br(cc['roas'])}</b> e <b>R$ {br(cc['lucro'],0)}</b> de lucro. Elas eram caras porque o lead valia o preço. Dentro do grupo de CPL caro o teto separa {br(J['teto_dentro_do_cpl'][1]['razao'])}x, com {br(J['teto_dentro_do_cpl'][1]['p']*100,1)}% de chance de ser sorte.</p>
<p><b>Sobre o pedaço do criativo, uma ressalva de tamanho de amostra.</b> As regras 2 e 3 dão o <b>mesmo veredito em {J['discordancia_r1_r2']['iguais']} das {J['discordancia_r1_r2']['n']} unidades</b> e discordam em {J['discordancia_r1_r2']['n']-J['discordancia_r1_r2']['iguais']}. Com quatro unidades de diferença nenhum teste decide se o ajuste do criativo melhora ou não a previsão. Este lançamento <b>não tem tamanho para responder isso</b>, e por isso ele não confirma nem contradiz os testes do projeto que mediram o criativo lead a lead, em 26 lançamentos, onde ele ganha com folga.</p>` }},
'''

# ================================================== S5 a proxima alavanca
S5 = '''    { title:"As próximas alavancas já medidas",
      sub:"Nada nesta seção é resultado do DEV21: são os dois sinais já validados em base própria que ainda não entraram em produção. O primeiro responde 'se o criativo importa, dá para saber antes de gastar?'. O segundo é um comportamento do lead que o modelo comprovadamente não enxerga.",
      html:`<div class="tw"><table class="tb"><thead><tr><th>Sinal</th><th>O que é</th><th>Separação topo/base</th><th>Concordância</th><th>Chance de ser sorte</th></tr></thead><tbody>
<tr><td><b>Fala do vídeo</b></td><td>a transcrição do que é dito no anúncio</td><td><b>1,95x</b></td><td>+0,40</td><td class="ok"><b>0,31%</b></td></tr>
<tr><td><b>Ritmo de fala</b></td><td>palavras divididas pela duração</td><td><b>1,94x</b></td><td>+0,42</td><td class="ok"><b>~0%</b></td></tr>
<tr class="ag"><td><b>Os dois juntos</b></td><td>a média das duas ordens</td><td class="pos"><b>2,70x</b></td><td><b>+0,55</b></td><td class="ok"><b>0,00%</b></td></tr>
</tbody></table></div>
<p style="margin-top:14px">Base: 65 vídeos distintos, 4.126 compradores. A concordância está numa régua de menos um a mais um, onde zero é fila embaralhada e um é a mesma fila.</p>
<p><b>O ritmo em caixa, que é o achado mais barato do projeto:</b> o terço de vídeos mais lentos fala 3,28 palavras por segundo e converte <b>0,69%</b>. O terço mais rápido fala 3,98 e converte <b>1,12%</b>. Um número só, sem nenhum processamento de linguagem, e vale quase o mesmo que a análise completa do texto.</p>
<p><b>E os dois não são a mesma coisa medida duas vezes.</b> A concordância entre eles é de apenas +0,10, com 44% de chance de ser acaso, ou seja, medem coisas diferentes. É por isso que juntá-los sobe para 2,70x em vez de empatar.</p>
<p><b>Três ressalvas que precisam viajar junto com esses números.</b> Primeira: o gancho, ou seja, só as primeiras palavras do vídeo, foi <b>testado e não é melhor</b> que o vídeo inteiro. Segunda: a duração inclui silêncio e trilha, então \\"ritmo\\" pode estar medindo quanto do vídeo é fala, e não velocidade de fala. Terceira, a mais importante: o papel disto é dar um <b>palpite inicial para criativo estreante</b>, quando ainda não há histórico próprio. Onde o anúncio já tem passado, o histórico manda e o texto empata com ele.</p>
<p><b>E uma pergunta aberta que esses números sugerem.</b> Até aqui a fala do vídeo foi medida contra uma coisa só: a conversão do anúncio. Mas se o texto prevê o que o anúncio rende, ele pode prever também <b>quem</b> o anúncio atrai: a mistura de decis, as respostas do formulário, o perfil do lead. Ainda não medimos isso. Se a resposta for sim, o texto vira alavanca dupla: escolhe o vídeo antes de gastar e antecipa a qualidade do público que ele vai trazer.</p>
<h4 class="cap">A segunda alavanca: entrar no grupo de WhatsApp</h4>
<div class="tw"><table class="tb"><thead><tr><th>Medida</th><th>Valor</th><th>Leitura</th></tr></thead><tbody>
<tr><td>Conversão de quem <b>entrou</b> no grupo</td><td><b>0,69%</b></td><td rowspan="2">separação de <b>3,2x</b>, medida em 8 lançamentos, ~100 mil leads</td></tr>
<tr><td>Conversão de quem <b>não entrou</b></td><td class="neg">0,22%</td></tr>
<tr class="ag"><td>O teste que importa: dentro do <b>mesmo decil</b></td><td><b>~3x em todos</b></td><td>no D10: 1,03% contra 0,34%. O sinal sobrevive a segurar a nota do modelo fixa</td></tr>
<tr><td>Quantos respondentes entram no grupo</td><td>~65%</td><td>sinal frequente, não raridade</td></tr>
</tbody></table></div>
<p style="margin-top:14px"><b>A linha destacada é o motivo de isto estar aqui.</b> Um sinal novo só vale alguma coisa se disser algo que o modelo ainda não sabe. Segurando o decil fixo, quem entrou no grupo converte cerca de <b>3 vezes</b> quem não entrou, em <b>todos</b> os decis. Ou seja: é informação que o formulário não carrega e o modelo não captura. É comportamento, não declaração.</p>
<p><b>Onde isso está hoje.</b> A coleta está no ar desde <b>10/06</b>, gravando cada entrada de grupo em tabela própria, porque a ferramenta do cliente apaga o histórico em 90 dias: sem a coleta, cada lançamento não capturado sumiria para sempre. O que falta é honesto: o ganho <b>dentro do modelo</b> ainda não foi provado, porque o teste disponível tinha só 44 conversões na fatia de avaliação, pouco para decidir. A feature entra em avaliação no próximo retreino, quando houver lançamentos cobertos o bastante.</p>
<h4 class="cap">A terceira, ainda teórica: a página de captura</h4>
<p><b>Esta não tem dado nenhum, e entra como proposta.</b> O raciocínio é o do texto do anúncio, um passo adiante no funil: entre o clique e o formulário existe a página, e o que ela diz pode mexer tanto em <b>quantos</b> leads entram quanto em <b>quem</b> entra. Hoje a página está fora de tudo o que medimos. Se o estudo valer a pena, começa como o do vídeo começou: versões registradas, leads casados por origem, conversão por versão.</p>` },
'''
# ATENCAO: S5 e string CRUA, nao f-string. Aqui `}}` NAO colapsa pra `}` como nas outras,
# e foi exatamente isso que quebrou o painel inteiro (SyntaxError e tela em branco).

# ==================== S45 o score composto (beat 4, "a aplicar") ====================
# Numeros REGISTRADOS no projeto (projeto_score_criativo, 05/08): os quatro bracos na
# MESMA populacao e mesma metrica. String CRUA: chave simples, nao dobrada.
S45 = '''    { title:"O próximo passo do score, já validado: a nota do criativo dentro dele",
      sub:"Hoje o criativo só ajusta o teto de CPL. O passo seguinte, já medido em base própria e ainda não aplicado, é a nota histórica do criativo multiplicar o próprio score que vai para a Meta.",
      html:`<p style="margin-bottom:12px">O teste: 63.544 leads pontuados pelo abr_28 entre 25/05 e 03/08, 314 compradores, 30 criativos. A nota de cada criativo foi recalculada semana a semana usando só o passado dele, nada do futuro. Quatro versões do score, mesma população, mesma régua:</p>
<div class="tw"><table class="tb"><thead><tr><th>Versão do score</th><th>Acerto de ordenação (AUC)</th><th>Lift do D10</th><th>Compradores no top 10%</th></tr></thead><tbody>
<tr><td>Só a nota do criativo</td><td>0,612</td><td>1,43x</td><td>41</td></tr>
<tr><td>Só o modelo (abr_28), o que roda hoje</td><td>0,640</td><td>1,69x</td><td>67</td></tr>
<tr class="ag"><td><b>Modelo x nota do criativo</b></td><td><b>0,677</b></td><td><b>2,42x</b></td><td><b>76</b></td></tr>
<tr><td>Modelo x nota x fala do vídeo</td><td>0,681</td><td class="pos"><b>2,93x</b></td><td class="pos"><b>92</b></td></tr>
</tbody></table></div>
<p style="margin-top:14px"><b>A régua da tabela:</b> o acerto de ordenação é a chance de o score pôr um comprador acima de um não-comprador num par sorteado (0,5 = moeda, 1,0 = perfeito). O lift do D10 é quanto o decil de cima converte contra a média. E a última coluna é a mais concreta: na mesma fatia de 10% do tráfego, o score composto encontra <b>76 compradores onde o modelo sozinho encontra 67</b>; com a fala do vídeo, <b>92</b>.</p>
<p><b>O ganho não é sorte de uma amostra.</b> Reamostrando por criativo inteiro 400 vezes (o jeito honesto, porque lead do mesmo criativo não é observação independente), o composto ganha do modelo sozinho em <b>100% das reamostras</b>. Numa segunda base, com a nota separada por canal, o ganho se repete com intervalo que não toca o zero.</p>
<p><b>Status: validado offline, não aplicado.</b> O destino desenhado é entrar como <b>desafiante</b> do score que vai para a Meta, com backtest walk-forward antes de encostar em produção. É o item "a aplicar" da troca de métrica: o teto já usa o criativo na régua de preço; isto o coloca na régua de público.</p>` },
'''

# ==================== SMET metodologia e reproducao (fecha o relatorio) ====================
# String CRUA: chave simples. Documento completo no repo:
#   V2/docs/relatorios/dev21_modelo_criativo_teto/METODOLOGIA.md (+ scripts/ + snapshot)
SMET = '''    { title:"Metodologia e reprodução",
      sub:"De onde veio cada número. O documento completo, com os scripts copiados e as fórmulas, vive no repositório em V2/docs/relatorios/dev21_modelo_criativo_teto/ (METODOLOGIA.md).",
      html:`<div class="tw"><table class="tb"><thead><tr><th>Bloco</th><th>Fonte de dados</th><th>Universo</th><th>Script</th></tr></thead><tbody>
<tr><td>Negócio por campanha (1-6)</td><td>Railway Client x UTMTracking + analytics.sales + ad_spend</td><td>27.317 cadastros, last-touch por email</td><td>painel_dev21.py</td></tr>
<tr><td>Separação do modelo (7-9, 16)</td><td>registros_ml (decil dos 2 modelos) + sales</td><td>24.158 respondentes; abr_28 cobre 24.047, jul_24 16.509</td><td>modelo_dev21.py + separacao.py</td></tr>
<tr><td>Dinheiro por decil (10)</td><td>as mesmas bases, custo = CPL da unidade criativo x campanha</td><td>25.562 leads pagos (93,6%)</td><td>lacunas.py</td></tr>
<tr><td>Série histórica fria (11)</td><td>registros_ml com o decil do abr_28 lido das DUAS colunas + launch_calendar</td><td>60.712 leads frios, LF56 a DEV21</td><td>historico_frio2.py</td></tr>
<tr><td>Criativo (12-15)</td><td>utm_content + ad_insights (Meta, por anúncio) + Google Ads API</td><td>276 unidades criativo x campanha</td><td>criativo_dev21.py e irmãos</td></tr>
<tr><td>Backtest do teto (17-19)</td><td>reference_rolling congelada em 13/07 + captacoes até 20/07</td><td>25 unidades (100+ leads, R$ 300+), 92,9% da verba</td><td>teto_v2.py</td></tr>
<tr><td>Corrida CPL vs teto (20)</td><td>derivada do backtest; teto plano = mesma fórmula com a conversão geral</td><td>as mesmas 25 unidades</td><td>corrida2.py + lacunas2.py</td></tr>
<tr><td>Score composto e alavancas (21-22)</td><td>registros da memória do projeto (não recalculados aqui)</td><td>63.544 leads (composto); 65 vídeos (texto); ~100 mil (grupo)</td><td>sessões de 05/08 e 09/06</td></tr>
</tbody></table></div>
<p style="margin-top:14px"><b>A régua de negócio, idêntica ao debriefing do cliente:</b> só produto principal (sem Operação 50k e sem MBA), três devoluções removidas, combos à parte, boleto a 50% no faturamento, gasto da Meta com 13% de imposto e Google sem. Captação 21/07 a 03/08, vendas 10 a 16/08, casamento lead-venda por email, telefone e últimos 6 dígitos.</p>
<p><b>As três regras de honestidade que valem para o relatório inteiro.</b> Primeira: nada do DEV21 entra no cálculo que julga o DEV21 (a referência do teto congela em 13/07 e o histórico de criativo fecha em 20/07). Segunda: o decil histórico do abr_28 é lido de onde ele estiver gravado, porque o carimbo de papel no banco só vale a partir de 25/07, e o papel real veio da verba na Meta desde 22/06. Terceira: criativo casa por grafia canônica (acento, caixa, espaço e carimbo do Google unificados), correção que entrou em produção no PR #237.</p>
<p><b>Para reproduzir ou atualizar:</b> os 18 scripts estão copiados em <b>V2/docs/relatorios/dev21_modelo_criativo_teto/scripts/</b>, com a ordem de execução, as dependências entre eles e as armadilhas conhecidas documentadas no METODOLOGIA.md ao lado. A única edição necessária é apontar a constante S de cada script para um diretório de trabalho novo. O snapshot desta página está congelado na mesma pasta.</p>` },
'''

# ------------------------------------------------------------------ montagem
p = S + 'painel_dev21.html'
h = open(p, encoding='utf-8').read()
ancoras = [('    { title:"Criativo: quem levou a verba', S1 + S2),
           ('    { title:"As duas variáveis juntas', S3),
           ('    { title:"Como ler",', S4 + S45 + S5 + SMET)]
for anc, bloco in ancoras:
    assert anc in h, f'ancora nao encontrada: {anc}'
    assert bloco.split('title:"')[1][:20] not in h, 'secao ja inserida, rode sobre o painel limpo'
    h = h.replace(anc, bloco + anc, 1)

# -- beat 6: "Como ler" vira tambem o bloco unico de limitacoes consolidadas
LIMIT = '''<h4 class="cap">As limitações, consolidadas</h4>
<div class="tw"><table class="tb"><thead><tr><th>#</th><th>Limitação</th><th>Onde pesa</th></tr></thead><tbody>
<tr><td>1</td><td><b>37 alunos sem origem identificada</b> (o debriefing do gestor deixa 80). É o teto do que dá para atribuir com email + telefone.</td><td>Todas as contas por campanha</td></tr>
<tr><td>2</td><td>A base de cadastros <b>não guarda o campo da campanha do Google</b>, então parte do Google entra pelo agregado, não por campanha individual.</td><td>Seções de campanha e de criativo</td></tr>
<tr><td>3</td><td>O modelo prevê <b>quem</b> compra, não <b>quanto</b>: o ticket é plano do fundo ao topo da régua.</td><td>"O que a régua valeu em dinheiro"</td></tr>
<tr><td>4</td><td><b>Neste lançamento</b> o topo andou em platô: D7-D8 (1,003%) empatou com D9-D10 (0,980%), nas duas réguas. Na referência histórica que o teto usa (86 mil leads) o degrau existe: D9-D10 converte <b>1,407%</b> contra 0,934% do D7-D8, um degrau de 1,5x. O platô é deste lançamento, não da régua.</td><td>"O que a régua valeu em dinheiro"</td></tr>
<tr><td>5</td><td>No <b>HQLB frio deste lançamento o ranking não separou</b> (1,12x). É o pior ponto de uma série que fecha positiva em 9 de 9; pede vigilância, não conclusão.</td><td>"Separar não é a mesma coisa que dar lucro"</td></tr>
<tr><td>6</td><td>Dentro de um lançamento só, <b>criativo não se distingue por conversão</b> (melhor contra pior cabe entre 0,53x e 6,24x). A prova do criativo vem dos 26 lançamentos.</td><td>"O criativo mexeu a conversão?"</td></tr>
<tr><td>7</td><td>O backtest do teto tem <b>25 unidades</b>: dá para provar que o teto separa, não dá para decidir se o ajuste do criativo melhora a previsão aqui (21 de 25 vereditos iguais).</td><td>"O teste final" e "CPL barato prevê lucro?"</td></tr>
<tr><td>8</td><td>Cobertura das réguas: o abr_28 pontua <b>24.047</b> dos 27.317 leads; o jul_24, 16.509 (entrou em 25/07). O resto fica fora das contas por decil.</td><td>Seções do modelo</td></tr>
<tr><td>9</td><td>Vendas contadas na janela de <b>10 a 16/08</b> (com 3 dias de casamento). Compra tardia depois disso não está aqui.</td><td>Faturamento, ROAS e lucro</td></tr>
<tr><td>10</td><td>As alavancas novas (fala do vídeo, ritmo, grupo de WhatsApp, score composto) estão <b>validadas offline e nenhuma em produção</b>; o ganho do grupo dentro do modelo ainda não tem poder estatístico (44 conversões).</td><td>"As próximas alavancas" e "O próximo passo do score"</td></tr>
</tbody></table></div>'''
velho = '{ title:"Como ler",'
assert velho in h
h = h.replace(velho, '{ title:"Como ler, e as limitações consolidadas",', 1)
h = h.replace('      sub:"",',
              '      sub:"A régua de negócio que o painel inteiro segue, e a lista única do que limita cada leitura.",', 1)
alvo_fim = 'individual.</p>` }'
assert alvo_fim in h, 'fim da secao Como ler mudou'
h = h.replace(alvo_fim, 'individual.</p>\n' + LIMIT + '` }', 1)
assert '\u2014' not in h, 'em dash detectado no HTML'

# GATE: nada e gravado sem o JS parsear. Uma chave sobrando ja deixou o painel em BRANCO
# (S5 e string crua e o `}}` dela nao colapsava). Erro de sintaxe nao aparece na leitura.
import re as _re, subprocess as _sp, tempfile as _tf, os as _os
_js = _re.findall(r'<script[^>]*>(.*?)</script>', h, _re.S)
assert len(_js) == 1, f'esperava 1 bloco <script>, achei {len(_js)}'
with _tf.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as _f:
    _f.write(_js[0]); _tmp = _f.name
_r = _sp.run(['node', '--check', _tmp], capture_output=True, text=True)
_os.unlink(_tmp)
if _r.returncode:
    raise SystemExit('JS INVALIDO, nada gravado:\n' + _r.stderr[:1200])
print('gate: JS parseia OK')
open(p, 'w', encoding='utf-8').write(h)
print(f"secoes agora: {h.count(chr(123)+' title:')} · tabelas: {h.count('<table')} · "
      f"graficos: {h.count('chart:')} · em dash: {h.count(chr(8212))}")
