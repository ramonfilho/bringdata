"""
Versão cliente DevClub do Relatório de Qualidade de Audiência.

Linguagem leve, sem jargão técnico. Foco em resultado prático e tabelas
acessíveis. ~4-6 páginas.

Saída: V2/propostas_e_apresentacoes/qualidade_audiencia_lf54_dev20.pdf
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable,
)
from reportlab.lib.colors import HexColor


OUTPUT = Path(__file__).parent.parent / "propostas_e_apresentacoes" / "qualidade_audiencia_lf54_dev20.pdf"


C_BLACK       = HexColor('#1a1a1a')
C_DARK_GRAY   = HexColor('#444444')
C_MID_GRAY    = HexColor('#777777')
C_LIGHT_GRAY  = HexColor('#f5f5f5')
C_GREEN       = HexColor('#1d8a3e')
C_GREEN_LIGHT = HexColor('#e8f5ec')
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
        'h1': ParagraphStyle('h1', fontName=bold, fontSize=22,
                             textColor=C_BLACK, leading=26, spaceAfter=4),
        'h1_sub': ParagraphStyle('h1_sub', fontName=base, fontSize=11,
                                 textColor=C_MID_GRAY, leading=15, spaceAfter=2),
        'h2': ParagraphStyle('h2', fontName=bold, fontSize=15,
                             textColor=C_BLACK, leading=19, spaceBefore=10, spaceAfter=5),
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
        'glossary': ParagraphStyle('glossary', fontName=italic, fontSize=9.5,
                                   textColor=C_MID_GRAY, leading=13, spaceAfter=8),
        'footer': ParagraphStyle('footer', fontName=base, fontSize=8,
                                 textColor=C_MID_GRAY, leading=10, alignment=TA_CENTER),
    }


def P(text, style):
    return Paragraph(text, style)


def make_table(rows, col_widths, header_bg=C_GREEN, highlight_rows=None):
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

    s.append(P("Qualidade da Audiência", st['h1']))
    s.append(P("Diagnóstico LF54 e DEV20 · maio/2026", st['h1_sub']))
    s.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceBefore=12, spaceAfter=12))

    # ── O que foi avaliado ──
    s.append(P("O que foi avaliado", st['h2']))
    s.append(P(
        "Investigamos uma pergunta prática: <b>o público que está chegando nas pesquisas do "
        "lançamento atual indica que o faturamento vai ser bom — considerando apenas as "
        "características desse público?</b>",
        st['body']))
    s.append(P(
        "A motivação é ter um indicador adicional, independente do modelo, que ajude a "
        "decidir se vale a pena dobrar a aposta em criativo, ajustar a campanha ou esperar "
        "o ciclo fechar. O sinal complementa o forecast de faturamento que já existe.",
        st['body']))

    # ── Como medimos ──
    s.append(P("Como medimos", st['h2']))
    s.append(P(
        "Comparamos a audiência do lançamento atual com a audiência dos 5 lançamentos de "
        "melhor desempenho financeiro entre os últimos 16. Para cada lead, calculamos qual a "
        "chance de ele virar comprador. Depois agregamos por lançamento e comparamos:",
        st['body']))
    s.append(P(
        "• <b>Quanto % dos leads estão nas faixas mais qualificadas</b> (D10 = top 10%, "
        "D9-D10 = top 20%)<br/>"
        "• <b>Pontuação média</b> dos leads no lançamento<br/>"
        "• Confrontamos com a média histórica dos lançamentos de melhor performance",
        st['body']))

    s.append(P("Lançamentos usados como referência (Top 5)", st['h2']))
    rows = [[
        P('Lançamento', st['th_left']),
        P('Período de captação', st['th']),
        P('Período de vendas', st['th']),
        P('Retorno verificado', st['th']),
    ]]
    pool_data = [
        ('LF40',  '25/11/25 — 02/12/25', '08/12 — 14/12/25', '3,40×'),
        ('LF41',  '02/12/25 — 08/12/25', '15/12 — 21/12/25', '3,97×'),
        ('LF45',  '03/02/26 — 23/02/26', '02/03 — 08/03/26', '3,25×'),
        ('LF50',  '24/03/26 — 29/03/26', '01/04 — 06/04/26', '3,11×'),
        ('LF53',  '13/04/26 — 20/04/26', '27/04 — 03/05/26', '4,54×'),
    ]
    for lf, cap, vendas, roas in pool_data:
        rows.append([P(lf, st['td_bold_left']), P(cap, st['td']),
                     P(vendas, st['td']), P(roas, st['td_bold'])])
    s.append(make_table(rows, [3.0*cm, 4.5*cm, 4.2*cm, 4.7*cm]))
    s.append(Spacer(1, 4))
    s.append(P(
        "<i>Retorno verificado = receita efetivamente recebida pelo cliente (descontados "
        "cancelamentos) dividida pelo valor investido em mídia no período. Total combinado "
        "dos 5 lançamentos: 40.968 leads.</i>",
        st['glossary']))

    # ── Resultado ──
    s.append(P("Resultado do lançamento atual e do próximo", st['h2']))
    rows = [[
        P('Lançamento', st['th_left']),
        P('Estado', st['th']),
        P('Leads avaliados', st['th']),
        P('% leads nas faixas top', st['th']),
        P('Avaliação', st['th_left']),
    ]]
    rows.append([P('LF54', st['td_bold_left']),
                 P('Em curso', st['td']),
                 P('5.532', st['td']),
                 P('+1,8 pontos<br/>vs Top 5', st['td_bold']),
                 P('Dentro do padrão dos melhores', st['td_left'])])
    rows.append([P('DEV20', st['td_bold_left']),
                 P('Captação encerrada', st['td']),
                 P('29.298', st['td']),
                 P('+3,2 pontos<br/>vs Top 5', st['td_bold']),
                 P('Ligeiramente acima do padrão', st['td_left'])])
    s.append(make_table(rows, [2.2*cm, 3.0*cm, 2.8*cm, 3.6*cm, 4.8*cm], highlight_rows=[1, 2]))
    s.append(Spacer(1, 6))

    s.append(callout("Conclusão prática",
        "<b>A audiência dos dois lançamentos atuais (LF54 e DEV20) tem qualidade equivalente "
        "aos cinco lançamentos de melhor desempenho do histórico recente.</b> O DEV20, com "
        "captação já encerrada, mostra inclusive uma audiência ligeiramente mais qualificada do "
        "que a média dos lançamentos top.<br/><br/>"
        "Operacionalmente: <b>não há sinal de degradação de público</b>. Se houver problema com "
        "o resultado final, ele não vem da audiência — pode estar em outros fatores como criativo, "
        "página de vendas, mix de produto ou sazonalidade.",
        st, bg=C_INSIGHT_BG, bd=C_INSIGHT_BD))

    # ── Validação ──
    s.append(P("Como sabemos que a medida funciona", st['h2']))
    s.append(P(
        "Aplicamos a mesma régua ao LF52, um lançamento já encerrado com retorno medido em 2,46× "
        "(desempenho intermediário, não top). A medida ficou <b>levemente abaixo do padrão</b> "
        "dos melhores (-2 pontos), alinhada com sua performance real. Isso valida que a régua "
        "discrimina lançamentos top de lançamentos medianos.",
        st['body']))
    s.append(P(
        "<b>O que a régua faz:</b> compara o perfil do público (gênero, idade, ocupação, "
        "faixa salarial, intenção de compra, etc.) processado pelo modelo de Machine Learning. "
        "O modelo combina dezenas de características para estimar a chance de cada lead virar "
        "comprador.",
        st['body']))
    s.append(P(
        "<b>O que a régua não faz:</b> não prevê faturamento absoluto em reais. Ela compara "
        "o perfil atual com perfis históricos de lançamentos vencedores. Se os perfis batem, "
        "a expectativa é que a conversão também bata — desde que o restante da operação "
        "(criativo, página, oferta) esteja igual ao período de referência.",
        st['body']))

    # ── Acompanhamento ──
    s.append(P("Acompanhamento diário", st['h2']))
    s.append(P(
        "Esse sinal foi integrado ao painel de monitoramento diário do sistema (a partir de "
        "11/05/2026). Todo dia, durante o ciclo de captação de um lançamento ativo, o sistema "
        "publica automaticamente:",
        st['body']))
    s.append(P(
        "• Número de leads acumulados até o momento<br/>"
        "• % dos leads nas faixas top (D9-D10)<br/>"
        "• Pontuação média comparada com o padrão dos melhores<br/>"
        "• Avaliação final: <b>acima / dentro / abaixo</b> do padrão",
        st['body']))
    s.append(P(
        "Quando o sinal cair para &quot;abaixo do padrão&quot;, o sistema emite alerta de severidade "
        "média ou alta, permitindo intervenção rápida durante o ciclo de captação.",
        st['body']))

    s.append(Spacer(1, 16))
    s.append(P(
        "<i>Bring Data · sistema de qualidade preditiva de audiência · maio/2026</i>",
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
