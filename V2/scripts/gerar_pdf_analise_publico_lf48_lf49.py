"""
Diagnóstico para o cliente DevClub: por que LF48 e LF49 tiveram retorno baixo,
comparando o público desses lançamentos com os seis melhores lançamentos do
histórico recente.

Duas análises encadeadas, linguagem acessível, sem jargão técnico:
  1. Qualidade geral da audiência (pontuação do modelo) — Top 6 vs LF48/LF49
  2. Onde está a diferença: características do público que mais se moveram

Saída: V2/propostas_e_apresentacoes/analise_publico_lf48_lf49_devclub.pdf

Versão maio/2026: pool de referência expandido para Top 6 ROAS atribuível 60d
(LF44, LF45, LF41, LF46, LF43, LF47), validado por análise de paridade entre
três candidatos (Top 5 PDF antigo, Top 4, Top 6). Top 6 vence por: (a) +55% de
amostra estatística, (b) diversidade temporal (jan–mar/26), (c) preserva 78–90%
da magnitude direcional do Top 4.
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, PageBreak,
)
from reportlab.lib.colors import HexColor


OUTPUT = Path(__file__).parent.parent / "propostas_e_apresentacoes" / "analise_publico_lf48_lf49_devclub.pdf"


C_BLACK       = HexColor('#1a1a1a')
C_DARK_GRAY   = HexColor('#444444')
C_MID_GRAY    = HexColor('#777777')
C_LIGHT_GRAY  = HexColor('#f5f5f5')
C_GREEN       = HexColor('#1d8a3e')
C_GREEN_LIGHT = HexColor('#e8f5ec')
C_RED         = HexColor('#b3261e')
C_RED_LIGHT   = HexColor('#fdecea')
C_AMBER_LIGHT = HexColor('#fff4d6')
C_WHITE       = HexColor('#ffffff')
C_RULE        = HexColor('#e0e0e0')
C_CALLOUT_BG     = HexColor('#fff8e1')
C_CALLOUT_BD     = HexColor('#f9a825')
C_INSIGHT_BG     = HexColor('#eef4fb')
C_INSIGHT_BD     = HexColor('#3b6fa3')


def styles():
    base = 'Helvetica'
    bold = 'Helvetica-Bold'
    italic = 'Helvetica-Oblique'
    return {
        'h1': ParagraphStyle('h1', fontName=bold, fontSize=20,
                             textColor=C_BLACK, leading=24, spaceAfter=4),
        'h1_sub': ParagraphStyle('h1_sub', fontName=base, fontSize=11,
                                 textColor=C_MID_GRAY, leading=15, spaceAfter=2),
        'h2': ParagraphStyle('h2', fontName=bold, fontSize=14,
                             textColor=C_BLACK, leading=18, spaceBefore=10, spaceAfter=5),
        'h3': ParagraphStyle('h3', fontName=bold, fontSize=11,
                             textColor=C_DARK_GRAY, leading=15, spaceBefore=6, spaceAfter=3),
        'body': ParagraphStyle('body', fontName=base, fontSize=10.5,
                               textColor=C_DARK_GRAY, leading=15, spaceAfter=6, alignment=TA_LEFT),
        'callout': ParagraphStyle('callout', fontName=base, fontSize=10.5,
                                  textColor=C_BLACK, leading=15, spaceAfter=3,
                                  leftIndent=10, rightIndent=10),
        'callout_label': ParagraphStyle('callout_label', fontName=bold, fontSize=9.5,
                                        textColor=C_DARK_GRAY, leading=12,
                                        spaceAfter=2, leftIndent=10, rightIndent=10),
        'th': ParagraphStyle('th', fontName=bold, fontSize=9.5,
                             textColor=C_WHITE, alignment=TA_CENTER, leading=12),
        'th_left': ParagraphStyle('th_left', fontName=bold, fontSize=9.5,
                                  textColor=C_WHITE, alignment=TA_LEFT, leading=12),
        'td': ParagraphStyle('td', fontName=base, fontSize=9.5,
                             textColor=C_DARK_GRAY, alignment=TA_CENTER, leading=13),
        'td_left': ParagraphStyle('td_left', fontName=base, fontSize=9.5,
                                  textColor=C_DARK_GRAY, alignment=TA_LEFT, leading=13),
        'td_bold': ParagraphStyle('td_bold', fontName=bold, fontSize=9.5,
                                  textColor=C_BLACK, alignment=TA_CENTER, leading=13),
        'td_bold_left': ParagraphStyle('td_bold_left', fontName=bold, fontSize=9.5,
                                       textColor=C_BLACK, alignment=TA_LEFT, leading=13),
        'td_red': ParagraphStyle('td_red', fontName=bold, fontSize=9.5,
                                 textColor=C_RED, alignment=TA_CENTER, leading=13),
        'td_green': ParagraphStyle('td_green', fontName=bold, fontSize=9.5,
                                   textColor=C_GREEN, alignment=TA_CENTER, leading=13),
        'glossary': ParagraphStyle('glossary', fontName=italic, fontSize=9.5,
                                   textColor=C_MID_GRAY, leading=13, spaceAfter=8),
        'footer': ParagraphStyle('footer', fontName=base, fontSize=8,
                                 textColor=C_MID_GRAY, leading=10, alignment=TA_CENTER),
    }


def P(text, style):
    return Paragraph(text, style)


def make_table(rows, col_widths, header_bg=C_GREEN, highlight_rows=None,
               alert_rows=None, warn_rows=None):
    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), header_bg),
        ('TEXTCOLOR',  (0,0), (-1,0), C_WHITE),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ('LINEBELOW',  (0,0), (-1,0), 0.5, C_RULE),
        ('LINEBELOW',  (0,-1), (-1,-1), 0.5, C_RULE),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ])
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.add('BACKGROUND', (0,i), (-1,i), C_LIGHT_GRAY)
    if highlight_rows:
        for r in highlight_rows:
            style.add('BACKGROUND', (0,r), (-1,r), C_GREEN_LIGHT)
    if alert_rows:
        for r in alert_rows:
            style.add('BACKGROUND', (0,r), (-1,r), C_RED_LIGHT)
    if warn_rows:
        for r in warn_rows:
            style.add('BACKGROUND', (0,r), (-1,r), C_AMBER_LIGHT)
    return Table(rows, colWidths=col_widths, style=style, hAlign='LEFT')


def callout(label, body, st, bg=C_CALLOUT_BG, bd=C_CALLOUT_BD):
    inner = []
    if label:
        inner.append(P(f"<b>{label}</b>", st['callout_label']))
    if isinstance(body, list):
        for line in body:
            inner.append(P(line, st['callout']))
    else:
        inner.append(P(body, st['callout']))
    t = Table([[inner]], colWidths=[16.4*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), bg),
        ('LINEBEFORE', (0,0), (0,-1), 3, bd),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 14),
    ]))
    return t


def build_story(st):
    s = []

    # ========== CABEÇALHO ==========
    s.append(P("Por que LF48 e LF49 tiveram retorno baixo", st['h1']))
    s.append(P("Comparação do público com os lançamentos de melhor desempenho · maio/2026",
               st['h1_sub']))
    s.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceBefore=12, spaceAfter=12))

    # ========== INTRODUÇÃO ==========
    s.append(P("Pergunta de partida", st['h2']))
    s.append(P(
        "Dois lançamentos de março/2026 (LF48 e LF49) terminaram com retorno "
        "bem abaixo da média do período: <b>1,28× e 0,81× respectivamente</b>, contra "
        "uma média acima de 2,8× nos seis melhores lançamentos do histórico recente. "
        "A pergunta natural é: <b>foi o público que chegou que era diferente, ou foi outro "
        "fator (criativo, oferta, página de vendas, sazonalidade)?</b>",
        st['body']))
    s.append(P(
        "Para responder, comparamos a audiência desses dois lançamentos com a "
        "audiência dos seis lançamentos de melhor desempenho usando duas análises "
        "encadeadas: a qualidade geral da audiência (pontuação do modelo) e a "
        "decomposição por característica para localizar onde está a diferença.",
        st['body']))

    # ========== TOP 6 REFERÊNCIA ==========
    s.append(P("Lançamentos usados como referência (Top 6)", st['h2']))
    rows = [[
        P('Lançamento', st['th_left']),
        P('Período de captação', st['th']),
        P('Retorno verificado', st['th']),
    ]]
    pool_data = [
        ('LF41',  '02/12/25 — 08/12/25', '3,97×'),
        ('LF45',  '03/02/26 — 23/02/26', '3,25×'),
        ('LF44',  '27/01/26 — 03/02/26', '2,99×'),
        ('LF47',  '03/03/26 — 09/03/26', '2,59×'),
        ('LF46',  '24/02/26 — 02/03/26', '2,43×'),
        ('LF43',  '13/01/26 — 26/01/26', '1,74×'),
    ]
    for lf, cap, roas in pool_data:
        rows.append([P(lf, st['td_bold_left']), P(cap, st['td']),
                     P(roas, st['td_bold'])])
    s.append(make_table(rows, [3.0*cm, 6.5*cm, 6.9*cm]))
    s.append(Spacer(1, 4))
    s.append(P(
        "<i>Retorno verificado = receita efetivamente recebida pelo cliente "
        "(descontados cancelamentos) dividida pelo valor investido em mídia. "
        "Total combinado dos 6 lançamentos: 54.420 leads. Critério de seleção: "
        "ROAS atribuível 60d ≥ 1,5× (matched-only, janela de atribuição de "
        "60 dias) — garantia de que cada lançamento contribuiu com público "
        "convertedor real, não só com volume.</i>",
        st['glossary']))

    s.append(PageBreak())

    # ========== ANÁLISE 1 — Qualidade geral ==========
    s.append(P("1. Qualidade geral da audiência", st['h2']))
    s.append(P(
        "Para cada lead, o sistema atribui uma <b>pontuação de propensão a compra</b> "
        "(de 0 a 1) baseada nas características da pesquisa. Comparamos três métricas:",
        st['body']))
    s.append(P(
        "• <b>Pontuação média</b> — quanto maior, mais qualificada a audiência<br/>"
        "• <b>% nas faixas top</b> — % dos leads nas 10% ou 20% mais qualificadas<br/>"
        "• <b>% nas faixas top 30%</b> — visão um pouco mais ampla",
        st['body']))
    s.append(Spacer(1, 4))

    rows = [[
        P('Lançamento', st['th_left']),
        P('Leads', st['th']),
        P('Pontuação<br/>média', st['th']),
        P('Δ vs<br/>Top 6', st['th']),
        P('% top 10%', st['th']),
        P('% top 20%', st['th']),
        P('Avaliação', st['th_left']),
    ]]
    # Top6 baseline row
    rows.append([P('<b>Top 6 (referência)</b>', st['td_bold_left']),
                 P('61.790', st['td']),
                 P('0,441', st['td_bold']),
                 P('—', st['td']),
                 P('11,8%', st['td_bold']),
                 P('28,4%', st['td_bold']),
                 P('referência', st['td_left'])])
    rows.append([P('LF48', st['td_bold_left']),
                 P('14.827', st['td']),
                 P('0,408', st['td']),
                 P('<b>-7,5%</b>', st['td_red']),
                 P('9,7%', st['td']),
                 P('20,0%', st['td_red']),
                 P('<b>Abaixo</b> do padrão', st['td_left'])])
    rows.append([P('LF49', st['td_bold_left']),
                 P('15.620', st['td']),
                 P('0,381', st['td']),
                 P('<b>-13,8%</b>', st['td_red']),
                 P('7,4%', st['td_red']),
                 P('15,2%', st['td_red']),
                 P('<b>Muito abaixo</b> do padrão', st['td_left'])])
    s.append(make_table(
        rows, [2.7*cm, 1.7*cm, 1.9*cm, 1.5*cm, 1.7*cm, 1.7*cm, 5.2*cm],
        alert_rows=[2, 3]))
    s.append(Spacer(1, 6))

    s.append(callout("O que esse painel mostra",
        "Os dois lançamentos com retorno baixo (LF48 e LF49) também tiveram <b>público "
        "estruturalmente inferior</b> sob a mesma régua, antes de qualquer ação de "
        "campanha. LF49, em particular, ficou quase 14% abaixo da pontuação média do "
        "Top 6 e perdeu 13 pontos percentuais no % de leads top 20%.<br/><br/>"
        "A diferença entre LF48 e LF49 também é relevante: LF49 é praticamente o "
        "dobro de degradado em cada métrica. Não foi a mesma falha de público — "
        "foi uma falha progressivamente maior.",
        st, bg=C_INSIGHT_BG, bd=C_INSIGHT_BD))

    s.append(PageBreak())

    # ========== ANÁLISE 2 — Onde está a diferença ==========
    s.append(P("2. Onde está a diferença: características do público", st['h2']))
    s.append(P(
        "A pontuação resume tudo em um número, mas é útil abrir e ver <b>quais "
        "características do público se moveram</b> em LF48 e LF49 em comparação com o "
        "Top 6. A tabela abaixo mostra o maior desvio observado em cada característica "
        "(em pontos percentuais).",
        st['body']))
    s.append(Spacer(1, 2))

    rows = [[
        P('Característica do público', st['th_left']),
        P('Crítica?', st['th']),
        P('Maior desvio<br/>em LF48', st['th']),
        P('Maior desvio<br/>em LF49', st['th']),
        P('Avaliação', st['th_left']),
    ]]
    drift_data = [
        ('Tem computador',          'Sim',  '9,6 pp',  '17,6 pp', 'crítica em ambos', 'alert', 'alert'),
        ('Já estudou programação',  'Sim',  '8,1 pp',  '12,1 pp', 'crítica em ambos', 'alert', 'alert'),
        ('Tem cartão de crédito',   'Sim',  '7,7 pp',  '11,7 pp', 'crítica em ambos', 'alert', 'alert'),
        ('Gênero',                  'Sim',  '7,6 pp',  '10,6 pp', 'crítica em ambos', 'alert', 'alert'),
        ('Ocupação',                'Sim',  '4,3 pp',  '6,8 pp',  'sub-crítica em LF48, crítica em LF49', 'warn', 'alert'),
        ('Faixa salarial',          'não',  '1,6 pp',  '6,0 pp',  'estável em LF48, sub-crítica em LF49', '', 'warn'),
        ('Faixa de idade',          'não',  '2,3 pp',  '3,3 pp',  'estável', '', ''),
    ]
    for ft, crit, d48, d49, avalia, c48, c49 in drift_data:
        td48 = st['td_red'] if c48 == 'alert' else (st['td'] if c48 == 'warn' else st['td'])
        td49 = st['td_red'] if c49 == 'alert' else (st['td'] if c49 == 'warn' else st['td'])
        if c48 == 'alert': d48 = f"<b>{d48}</b>"
        if c49 == 'alert': d49 = f"<b>{d49}</b>"
        rows.append([P(ft, st['td_bold_left']), P(crit, st['td']),
                     P(d48, td48), P(d49, td49), P(avalia, st['td_left'])])
    s.append(make_table(rows, [4.0*cm, 1.6*cm, 2.6*cm, 2.6*cm, 5.6*cm]))
    s.append(Spacer(1, 4))
    s.append(P(
        "<i>Crítica = característica que tem peso alto na previsão de compra do "
        "modelo. Desvio = diferença em pontos percentuais (pp) entre a proporção "
        "no lançamento e a proporção no Top 6.</i>",
        st['glossary']))
    s.append(Spacer(1, 4))

    s.append(callout("Padrão claro nos dois lançamentos ruins",
        "Tanto em LF48 quanto em LF49, as quatro características mais associadas a "
        "compra real em curso de programação se moveram <b>na mesma direção</b>: menos "
        "computador, menos histórico em programação, menos cartão de crédito, menos "
        "público masculino. Isso indica problema sistêmico de aquisição, não falha "
        "isolada em uma característica.<br/><br/>"
        "LF49 é o caso mais extremo: a proporção de leads <b>com computador</b> caiu "
        "<b>17,6 pontos percentuais</b> em relação ao Top 6 (de 87% para 69%), e a "
        "proporção <b>com cartão de crédito</b> caiu 11,7 pontos. Em curso pago de "
        "programação, esses dois indicadores são quase pré-requisitos.",
        st, bg=C_INSIGHT_BG, bd=C_INSIGHT_BD))

    s.append(PageBreak())

    # ========== CONCLUSÕES ==========
    s.append(P("Conclusões", st['h2']))
    s.append(P(
        "<b>1. O retorno baixo em LF48 e LF49 tem origem no público.</b> A audiência "
        "que chegou nesses dois lançamentos era estruturalmente diferente — menos "
        "público com computador, menos com história em programação, menos com cartão "
        "de crédito, menos masculino. Esses são justamente os indicadores mais ligados "
        "à intenção real de compra em curso de programação.",
        st['body']))
    s.append(P(
        "<b>2. Não é necessário invocar problema de criativo, oferta ou página para "
        "explicar o resultado.</b> O sinal do público já antecipava retorno fraco — "
        "antes mesmo do ciclo de vendas acontecer. Isso não exclui outros fatores, "
        "mas indica que a audiência sozinha já justifica boa parte do desempenho.",
        st['body']))
    s.append(P(
        "<b>3. LF49 é o caso mais grave, com magnitude de degradação cerca do dobro "
        "do LF48 em todas as métricas.</b> Não foi a mesma falha replicada — foi uma "
        "falha que piorou. Investigar o que diferenciou a operação de captação entre "
        "esses dois lançamentos (mudança de criativo, alvo, página, orçamento) é o "
        "próximo passo natural para evitar repetição.",
        st['body']))

    s.append(P("Implicação operacional", st['h2']))
    s.append(P(
        "A partir de 12/05/2026, esse sinal está <b>incorporado ao monitoramento "
        "diário</b> do sistema com a referência atualizada para o Top 6. Todo dia, "
        "durante a captação de um lançamento, publicamos automaticamente a "
        "pontuação média da audiência, o % de leads nas faixas top e a avaliação "
        "(acima / dentro / abaixo do padrão).",
        st['body']))
    s.append(P(
        "Quando o sinal cair para 'abaixo do padrão', um alerta é emitido antes "
        "do ciclo de vendas terminar, permitindo decidir se vale a pena reforçar "
        "criativo, ajustar segmentação ou ampliar o orçamento. <b>É um indicador "
        "antecedente, complementar ao forecast de faturamento que já existe.</b>",
        st['body']))

    s.append(Spacer(1, 14))
    s.append(P(
        "<i>Bring Data · diagnóstico de qualidade preditiva de audiência · maio/2026</i>",
        st['footer']))
    s.append(P(
        '<i>"In God we trust, all the others must bring data." — W. Edwards Deming</i>',
        st['footer']))

    return s


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    st = styles()
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2.2*cm, bottomMargin=2*cm,
    )
    doc.build(build_story(st))
    print(f"✅ PDF gerado: {OUTPUT}")


if __name__ == "__main__":
    main()
