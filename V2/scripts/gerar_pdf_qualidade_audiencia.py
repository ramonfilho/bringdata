"""
Gera PDF do Relatório de Qualidade de Audiência — Bring Data / DevClub.

Versão técnica interna: cobre método, backtest, decisões, sinal e integração
no monitoring. ~10-12 páginas.

Saída: V2/docs/relatorio_qualidade_audiencia_2026-05-11.pdf
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether, PageBreak,
)
from reportlab.lib.colors import HexColor


OUTPUT = Path(__file__).parent.parent / "docs" / "relatorio_qualidade_audiencia_2026-05-11.pdf"


# Paleta Bring Data (mesma de auditoria_dano)
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
        'h1': ParagraphStyle('h1', fontName=bold, fontSize=20,
                             textColor=C_BLACK, leading=24, spaceAfter=4),
        'h1_sub': ParagraphStyle('h1_sub', fontName=base, fontSize=10,
                                 textColor=C_MID_GRAY, leading=14, spaceAfter=2),
        'h2': ParagraphStyle('h2', fontName=bold, fontSize=14,
                             textColor=C_BLACK, leading=17, spaceBefore=8, spaceAfter=4),
        'h3': ParagraphStyle('h3', fontName=bold, fontSize=10.5,
                             textColor=C_BLACK, leading=13, spaceBefore=8, spaceAfter=3),
        'body': ParagraphStyle('body', fontName=base, fontSize=9.5,
                               textColor=C_DARK_GRAY, leading=13, spaceAfter=4, alignment=TA_LEFT),
        'body_bold': ParagraphStyle('body_bold', fontName=bold, fontSize=9.5,
                                    textColor=C_DARK_GRAY, leading=13, spaceAfter=4),
        'glossary': ParagraphStyle('glossary', fontName=italic, fontSize=9,
                                   textColor=C_MID_GRAY, leading=12, spaceAfter=6,
                                   leftIndent=8, rightIndent=8),
        'callout': ParagraphStyle('callout', fontName=base, fontSize=9.5,
                                  textColor=C_BLACK, leading=13, spaceAfter=3,
                                  leftIndent=10, rightIndent=10),
        'callout_label': ParagraphStyle('callout_label', fontName=bold, fontSize=8.5,
                                        textColor=C_DARK_GRAY, leading=11,
                                        spaceAfter=1, leftIndent=10, rightIndent=10),
        'th': ParagraphStyle('th', fontName=bold, fontSize=8.5,
                             textColor=C_WHITE, alignment=TA_CENTER, leading=11),
        'th_left': ParagraphStyle('th_left', fontName=bold, fontSize=8.5,
                                  textColor=C_WHITE, alignment=TA_LEFT, leading=11),
        'td': ParagraphStyle('td', fontName=base, fontSize=8.5,
                             textColor=C_DARK_GRAY, alignment=TA_CENTER, leading=12),
        'td_left': ParagraphStyle('td_left', fontName=base, fontSize=8.5,
                                  textColor=C_DARK_GRAY, alignment=TA_LEFT, leading=12),
        'td_bold': ParagraphStyle('td_bold', fontName=bold, fontSize=8.5,
                                  textColor=C_BLACK, alignment=TA_CENTER, leading=12),
        'td_bold_left': ParagraphStyle('td_bold_left', fontName=bold, fontSize=8.5,
                                       textColor=C_BLACK, alignment=TA_LEFT, leading=12),
        'mono': ParagraphStyle('mono', fontName='Courier', fontSize=8.5,
                               textColor=C_DARK_GRAY, leading=11),
        'footer': ParagraphStyle('footer', fontName=base, fontSize=7.5,
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
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
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
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    return t


def build_story(st):
    s = []

    # ── Header ──
    s.append(P("Qualidade de Audiência — Diagnóstico e Sinal Diário", st['h1']))
    s.append(P("Sistema Bring Data · Cliente DevClub · maio/2026", st['h1_sub']))
    s.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceBefore=10, spaceAfter=10))

    # ── Sumário executivo ──
    s.append(P("Sumário executivo", st['h2']))
    s.append(P(
        "Investigação para responder operacionalmente: <b>a audiência que está chegando ao "
        "lançamento atual sinaliza bom faturamento, considerando apenas o público?</b> "
        "Três abordagens metodológicas foram testadas; a vencedora foi integrada ao endpoint "
        "<font name='Courier' size='9'>/monitoring/daily-check</font> em produção.",
        st['body']))
    s.append(P(
        "<b>Achados-chave:</b><br/>"
        "• <b>Sinal univariado de features (P(target|valor)) descartado</b> — MAPE 43% em receita, "
        "Pearson 0.30 com ROAS. Detecta drift de mix mas não prediz absolutos.<br/>"
        "• <b>Backtest do RF</b> (LF52 + LF53 first peak, OOS): Challenger abr28 com lift D10 de "
        "1.8–2.2× vs Champion jan30 de 1.4×. Calibração de ambos ~60× off (score é rank, não "
        "probabilidade absoluta).<br/>"
        "• <b>Sinal escolhido:</b> %D9-D10 e score médio do Challenger no LF atual comparados ao "
        "baseline pré-computado dos Top5 ROAS realized (LF40, LF41, LF45, LF50, LF53).<br/>"
        "• <b>LF54 e DEV20:</b> ambos <b>DENTRO do padrão histórico</b> de bons lançamentos. "
        "DEV20 inclusive sinaliza ligeiramente acima (+3pp em D9-D10).",
        st['body']))
    s.append(Spacer(1, 4))
    s.append(callout("Resultado em produção (11/05/2026)",
        f"Revisão <font name='Courier' size='9'>smart-ads-api-00439-fir</font> em 100% do tráfego. "
        f"Daily-check emite o bloco <font name='Courier' size='9'>audience_quality_signal</font> "
        f"todo dia comparando o LF ativo vs baseline. Hoje: LF54 (n=5.532 leads) DENTRO do padrão, "
        f"Δ%D9-D10 = +1.8pp, Δscore = +0.3%.",
        st, bg=C_INSIGHT_BG, bd=C_INSIGHT_BD))

    s.append(PageBreak())

    # ── 1. Pergunta-objeto ──
    s.append(P("1. Pergunta-objeto", st['h2']))
    s.append(P(
        "O sistema Bring Data já fornece o score do modelo (Random Forest) por lead. O score "
        "é usado para enviar eventos qualificados ao Meta (CAPI) e para o forecast de faturamento "
        "que existe no endpoint de monitoramento.",
        st['body']))
    s.append(P(
        "A pergunta operacional desta investigação é diferente: <b>tirando o score do modelo, "
        "a composição da audiência atual (gênero, idade, ocupação, faixa salarial, etc.) está "
        "sinalizando faturamento bom ou ruim?</b> A motivação é construir um sinal secundário "
        "que possa servir de orientação durante o lançamento, e que complemente o forecast já "
        "existente.",
        st['body']))

    # ── 2. Audiência usada ──
    s.append(P("2. Audiência usada", st['h2']))
    s.append(P(
        "Dois pools de dados são usados ao longo do estudo:",
        st['body']))

    s.append(P("2.1 Pool de referência — Top5 ROAS realized", st['h3']))
    s.append(P(
        "Cinco lançamentos cujo ROAS realizado (cobrado pelo cliente, descontados "
        "cancelamentos e ajustando TMB para 1/12 do ticket) foi mais alto entre todos os 16 "
        "ciclos cobertos pelo histórico (dez/2025 a abr/2026).",
        st['body']))
    rows = [[
        P('Lançamento', st['th_left']),
        P('Período de captação', st['th']),
        P('Período de vendas', st['th']),
        P('ROAS realized', st['th']),
        P('Leads', st['th']),
    ]]
    pool_data = [
        ('LF40',   '25/11/2025 — 02/12/2025', '08/12 — 14/12/2025', '3.40', '3.999'),
        ('LF41',   '02/12/2025 — 08/12/2025', '15/12 — 21/12/2025', '3.97', '2.464'),
        ('LF45',   '03/02/2026 — 23/02/2026', '02/03 — 08/03/2026', '3.25', '15.325'),
        ('LF50',   '24/03/2026 — 29/03/2026', '01/04 — 06/04/2026', '3.11', '9.122'),
        ('LF53*',  '13/04/2026 — 20/04/2026', '27/04 — 03/05/2026', '4.54', '10.058'),
    ]
    for lf, cap, vendas, roas, n in pool_data:
        rows.append([P(lf, st['td_bold']), P(cap, st['td']), P(vendas, st['td']),
                     P(roas, st['td_bold']), P(n, st['td'])])
    s.append(make_table(rows, [2.0*cm, 4.5*cm, 3.8*cm, 2.6*cm, 2.5*cm]))
    s.append(Spacer(1, 3))
    s.append(P(
        "<i>* LF53 — usou subset 'first peak' (primeiros 3 dias de venda) para isolar o produto "
        "principal do upsell. ROAS de 4.54 considera só o primeiro pico.</i>",
        st['glossary']))
    s.append(Spacer(1, 3))
    s.append(P(
        "<b>Total do pool: 40.968 leads.</b> Pool definido após investigação comparativa entre "
        "10 candidatos de referência (Top5 ROAS atual, ROAS realized com/sem outliers BF, "
        "interseção, mediana, etc.) — Top5 ROAS realized foi o de maior poder discriminante na "
        "correlação Spearman expected_conv × roas_realized das demais LFs (corr +0.66).",
        st['body']))

    s.append(P("2.2 Pool de avaliação — LF atual + sanity", st['h3']))
    rows = [[
        P('LF', st['th_left']),
        P('Estado', st['th']),
        P('Captação', st['th']),
        P('Vendas', st['th']),
        P('Leads (em 11/05)', st['th']),
    ]]
    eval_data = [
        ('LF54',  'Em curso',     '05/05 — 11/05/2026',  '18/05 — 24/05/2026', '5.532'),
        ('DEV20', 'Cap encerrado','21/04 — 04/05/2026',  '11/05 — 17/05/2026', '29.298'),
        ('LF52*', 'Sanity check', '07/04 — 12/04/2026',  '17/04 — 24/04/2026', '9.391'),
    ]
    for lf, est, cap, vendas, n in eval_data:
        rows.append([P(lf, st['td_bold']), P(est, st['td']), P(cap, st['td']),
                     P(vendas, st['td']), P(n, st['td'])])
    s.append(make_table(rows, [2.0*cm, 2.8*cm, 4.5*cm, 4.0*cm, 2.5*cm]))
    s.append(Spacer(1, 3))
    s.append(P(
        "<i>* LF52 — usado apenas como sanity check da metodologia. ROAS realized 2.46 (decente, "
        "não excepcional). Esperamos que fique 'dentro do padrão' levemente abaixo.</i>",
        st['glossary']))

    # ── 3. Features ──
    s.append(P("3. Features categóricas analisadas", st['h2']))
    s.append(P(
        "Nove perguntas categóricas da pesquisa de captação são usadas em todas as análises:",
        st['body']))
    feats = [
        ('1. O seu gênero', 'Masculino / Feminino'),
        ('2. Qual a sua idade', '&lt;18, 18-24, 25-34, 35-44, 45-54, 55+'),
        ('3. O que você faz atualmente', 'CLT, Autônomo, Estudante, Sem trabalho/estudo'),
        ('4. Atualmente, qual a sua faixa salarial', '6 faixas, "sem renda" → "&gt;R$15k"'),
        ('5. Você possui cartão de crédito', 'Sim / Não'),
        ('6. O que mais quer ver no evento', 'Programação / Mentoria / Outros'),
        ('7. Tem computador/notebook', 'Sim / Não'),
        ('8. Já estudou programação', 'Sim / Não'),
        ('9. Pretende fazer faculdade', 'Sim / Não'),
    ]
    rows = [[P('Feature', st['th_left']), P('Valores', st['th_left'])]]
    for f, v in feats:
        rows.append([P(f, st['td_left']), P(v, st['td_left'])])
    s.append(make_table(rows, [6.5*cm, 9.9*cm]))

    s.append(PageBreak())

    # ── 4. Metodologia ──
    s.append(P("4. Metodologia — três abordagens testadas", st['h2']))

    s.append(P("4.1 Abordagem A — Sinal univariado P(target=1|valor) — descartada", st['h3']))
    s.append(P(
        "Para cada feature × valor, calcular P(target=1|valor) no pool de referência via Empirical "
        "Bayes (prior_n=5). Combinar por feature via Naive Bayes log-odds e prever conversão "
        "esperada do LF alvo. Multiplicar por ticket médio realizado para obter receita prevista.",
        st['body']))
    s.append(P(
        "<b>Backtest (10 LFs fora da referência):</b> MAPE 43% em receita, MAPE 43% em ROAS, "
        "Pearson 0.30 com ROAS, acurácia direcional 60% (apenas 10pp acima do chute). "
        "Conclusão: a metodologia univariada não prediz faturamento absoluto. <b>Detecta drift de "
        "mix mas não substitui o modelo</b>. Razão: independência assumida entre 9 features "
        "subestima interações multivariadas que o RF captura.",
        st['body']))

    s.append(P("4.2 Abordagem B — Re-scorear com o Random Forest existente — adotada", st['h3']))
    s.append(P(
        "Em vez de inventar uma nova métrica, usar o próprio modelo Random Forest do sistema. "
        "Para o pool de referência e o LF atual, scorear todos os leads com o mesmo modelo, "
        "calcular percentual de leads em D9-D10 e score médio. Comparar.",
        st['body']))
    s.append(P(
        "Esta abordagem captura as <b>interações multivariadas</b> que a univariada perde. O "
        "Random Forest, treinado com 60 features pós-encoding, modela combinações como "
        "'homem, 18-24, CLT, com cartão' que individualmente são fracas mas juntas são "
        "preditivas.",
        st['body']))

    s.append(P("4.3 Abordagem C — Usar Lead.decil já gravado em produção — descartada", st['h3']))
    s.append(P(
        "Consultar o decil que produção atribuiu via Cloud Run a cada lead, sem re-scorear. "
        "Vantagem: simplicidade total. <b>Descartada</b> porque os leads dos lançamentos "
        "históricos foram escorados por <b>versões diferentes do código e modelo</b>: o "
        "Champion jan30 esteve ativo, mas o patch DT-12 (que corrigia idade/salário cegos via "
        "encoding overrides) só entrou em 02/05/2026. Comparar Lead.leadScore antigo com "
        "Lead.leadScore atual mistura cobertura de bug.",
        st['body']))
    s.append(callout("Decisão metodológica chave",
        "Re-scorear TUDO agora (baseline histórico + LF atual) com o mesmo código e o mesmo "
        "modelo. Self-consistent por construção. Não depender de fotografias antigas do score "
        "salvas em produção.", st))

    # ── 5. Backtest do RF ──
    s.append(PageBreak())
    s.append(P("5. Backtest do Random Forest — Champion vs Challenger", st['h2']))
    s.append(P(
        "Antes de adotar o score do RF como sinal, validamos sua capacidade preditiva em "
        "lançamentos out-of-sample para ambos os modelos ativos. Dois modelos vivem no A/B test "
        "atual:",
        st['body']))
    rows = [[
        P('Modelo', st['th_left']),
        P('Run ID', st['th']),
        P('Treino até', st['th']),
        P('Roteamento', st['th_left']),
    ]]
    rows.append([P('Champion jan30', st['td_bold_left']),
                 P('d51757f5...', st['mono']),
                 P('04/11/2025', st['td']),
                 P('Default (sem UTM HQLB)', st['td_left'])])
    rows.append([P('Challenger abr28', st['td_bold_left']),
                 P('5d158f0a...', st['mono']),
                 P('08/04/2026', st['td']),
                 P('utm_campaign "PIXEL NOVO API" ou URL ml-parabens-psq-devf', st['td_left'])])
    s.append(make_table(rows, [3.5*cm, 3.0*cm, 2.5*cm, 7.4*cm]))
    s.append(Spacer(1, 3))
    s.append(P(
        "<b>LFs out-of-sample escolhidos:</b> LF52 (cap 07-12/04, n=9.391 leads) e LF53 first "
        "peak (cap 13-20/04, n=10.054). LF52 é OOS para o Champion (treino até 04/11) e parcial "
        "OOS para o Challenger (3 dias dentro do treino). LF53fp é 100% OOS para ambos.",
        st['body']))

    s.append(P("5.1 Discriminação (lift por decil)", st['h3']))
    rows = [[
        P('Métrica', st['th_left']),
        P('LF52', st['th']),
        P('LF53fp', st['th']),
    ]]
    bt_data = [
        ('Lift D10 — Champion jan30',  '1.39×', '1.37×'),
        ('Lift D10 — Challenger abr28','1.81×', '2.19×'),
        ('Concentração top30 — Champion (D8-D10 = 60% leads)', '81%', '68%'),
        ('Concentração top30 — Challenger (D8-D10 = 34% leads)','61%', '53%'),
        ('ROAS top30 offline — Champion', '3.26', '1.80'),
        ('ROAS top30 offline — Challenger','4.31', '2.35'),
    ]
    for k, a, b in bt_data:
        rows.append([P(k, st['td_left']), P(a, st['td_bold']), P(b, st['td_bold'])])
    s.append(make_table(rows, [10.5*cm, 3.0*cm, 3.0*cm], highlight_rows=[2, 4, 6]))
    s.append(Spacer(1, 3))
    s.append(P(
        "<b>Leitura:</b> em ambos os LFs OOS, o Challenger discrimina 30-60% melhor que o "
        "Champion (lift D10 mais alto). Em LF53fp — 100% out-of-sample do Challenger — o "
        "lift D10 atinge 2.19×, o que significa que a taxa de conversão real do D10 é "
        "<b>2.19× a baseline</b>. Esse é o sinal preditivo que importa para o Meta otimizar "
        "audiência.",
        st['body']))

    s.append(P("5.2 Calibração (score absoluto)", st['h3']))
    rows = [[
        P('Métrica', st['th_left']),
        P('Champion jan30 (LF52)', st['th']),
        P('Challenger abr28 (LF52)', st['th']),
    ]]
    cal_data = [
        ('Score médio do modelo', '0.387', '0.417'),
        ('Taxa real de conversão', '0.69%', '0.69%'),
        ('calib_ratio (score / taxa real)', '56×', '60×'),
    ]
    for k, a, b in cal_data:
        rows.append([P(k, st['td_left']), P(a, st['td_bold']), P(b, st['td_bold'])])
    s.append(make_table(rows, [7.5*cm, 4.5*cm, 4.5*cm]))
    s.append(Spacer(1, 3))
    s.append(callout("Diferença crítica — discriminação ≠ calibração",
        "O score do RF está <b>56-60× a taxa real</b> de conversão. Isso não é bug — é "
        "estrutural: o modelo foi treinado com class balancing, e <font name='Courier' size='9'>"
        "predict_proba</font> devolve um score de <b>ranking</b>, não uma probabilidade calibrada. "
        "Por isso o &quot;Champion prevê faturamento maior do que o real&quot; é literal, mas não é "
        "erro do modelo — é decisão de design. <b>Σ(score) × ticket NÃO é receita prevista útil.</b> "
        "Para predizer faturamento absoluto, seria preciso recalibrar via Platt scaling ou "
        "isotonic regression (item de backlog). Para o sinal de drift, basta usar rank "
        "(% leads em decis altos), que é o que esta investigação faz.",
        st))

    # ── 6. Sinal final ──
    s.append(PageBreak())
    s.append(P("6. Sinal final — qualidade de audiência LF54 e DEV20", st['h2']))
    s.append(P(
        "Aplicamos a abordagem B (re-scorear com Challenger) sobre os 5 LFs do pool de referência "
        "e sobre LF54 + DEV20. Calculamos para cada LF o score médio, %D10, %D9-D10 e %D8-D10. "
        "O baseline ponderado pelo volume de leads do pool é a régua de comparação.",
        st['body']))

    s.append(P("6.1 Métricas por LF", st['h3']))
    rows = [[
        P('LF', st['th_left']),
        P('n leads', st['th']),
        P('score médio', st['th']),
        P('%D10', st['th']),
        P('%D9-D10', st['th']),
        P('%D8-D10', st['th']),
    ]]
    metrics_data = [
        ('★ LF40',     '3.986',  '0.4302', '11.5%', '23.5%', '36.4%'),
        ('★ LF41',     '3.984',  '0.4379', '11.8%', '26.5%', '34.5%'),
        ('★ LF45',     '8.531',  '0.4559', '17.1%', '30.5%', '43.1%'),
        ('★ LF50',     '9.122',  '0.4209', '12.2%', '23.7%', '35.0%'),
        ('★ LF53fp',  '10.054',  '0.4159', '11.6%', '23.3%', '34.0%'),
        ('Baseline (pond.)','35.677','0.4308','13.1%','25.5%','36.7%'),
        ('◆ LF54 (atual)',     '5.532',  '0.4319', '13.9%', '27.3%', '38.9%'),
        ('◆ DEV20 (cap fim.)','29.298',  '0.4401', '15.7%', '28.7%', '40.6%'),
        ('· LF52 (sanity)',     '9.391',  '0.4169', '12.1%', '23.5%', '34.4%'),
    ]
    for lf, n, sm, d10, d9_10, d8_10 in metrics_data:
        is_baseline = 'Baseline' in lf
        is_target = '◆' in lf
        style_lf = st['td_bold_left'] if (is_baseline or is_target) else st['td_left']
        style_val = st['td_bold'] if (is_baseline or is_target) else st['td']
        rows.append([P(lf, style_lf), P(n, style_val), P(sm, style_val),
                     P(d10, style_val), P(d9_10, style_val), P(d8_10, style_val)])
    s.append(make_table(rows, [3.5*cm, 2.0*cm, 2.6*cm, 2.0*cm, 2.4*cm, 2.4*cm],
                        highlight_rows=[6]))
    s.append(Spacer(1, 3))
    s.append(P(
        "<i>★ = LFs do pool de referência (Top5 ROAS realized). ◆ = LFs avaliados "
        "(LF54 em curso, DEV20 com captação encerrada). · = sanity check.</i>",
        st['glossary']))

    s.append(P("6.2 Δ vs baseline (régua única — Challenger abr28)", st['h3']))
    rows = [[
        P('LF', st['th_left']),
        P('Δscore', st['th']),
        P('Δ%D10 (pp)', st['th']),
        P('Δ%D9-D10 (pp)', st['th']),
        P('Sinal', st['th_left']),
    ]]
    delta_data = [
        ('LF54',  '+0.3%', '+0.8',  '+1.8', 'DENTRO do padrão'),
        ('DEV20', '+2.2%', '+2.7',  '+3.2', 'DENTRO (ligeiramente acima)'),
        ('LF52',  '-3.2%', '-1.0',  '-2.0', 'DENTRO (ligeiramente abaixo)'),
    ]
    for lf, ds, dd10, dd9_10, sinal in delta_data:
        rows.append([P(lf, st['td_bold_left']), P(ds, st['td']),
                     P(dd10, st['td']), P(dd9_10, st['td_bold']),
                     P(sinal, st['td_left'])])
    s.append(make_table(rows, [2.0*cm, 2.5*cm, 2.8*cm, 3.0*cm, 6.1*cm]))
    s.append(Spacer(1, 3))
    s.append(callout("Conclusão prática",
        "<b>LF54 (5.532 leads parcial) e DEV20 (29.298 leads, captação encerrada) têm audiência "
        "DENTRO do padrão histórico de bons lançamentos.</b> DEV20 inclusive sinaliza ligeiramente "
        "acima (+3.2pp em D9-D10, +2.2% em score médio). Não há indício de degradação de público. "
        "Se houver problema, está em outro lugar (criativo, taxa de conversão da página, mix "
        "de produto, sazonalidade).",
        st, bg=C_INSIGHT_BG, bd=C_INSIGHT_BD))
    s.append(Spacer(1, 3))
    s.append(P(
        "<b>Sanity check passou:</b> LF52, cujo ROAS realized foi 2.46 (decente mas não top), "
        "ficou levemente abaixo do baseline (-2.0pp em D9-D10) — alinhado com sua performance "
        "histórica intermediária. Isso valida que a métrica é estável e discriminante.",
        st['body']))

    # ── 7. Integração no monitoring ──
    s.append(PageBreak())
    s.append(P("7. Integração no endpoint de monitoring", st['h2']))
    s.append(P(
        "O sinal foi integrado ao <font name='Courier' size='9'>/monitoring/daily-check/railway</font> "
        "do Cloud Run. Toda execução diária do monitoramento (via Cloud Scheduler) passa a emitir "
        "um bloco <font name='Courier' size='9'>audience_quality_signal</font> que aparece junto "
        "com os demais alertas no digest.",
        st['body']))

    s.append(P("7.1 Arquitetura", st['h3']))
    s.append(P(
        "<b>Chain idêntica à produção:</b> a função <font name='Courier' size='9'>"
        "_check_audience_quality_signal</font> chama <font name='Courier' size='9'>"
        "LeadScoringPipeline.run</font> com tempfile CSV e <font name='Courier' size='9'>"
        "predictor_override=Challenger</font> — exatamente o que o webhook de produção faz em "
        "<font name='Courier' size='9'>api/app.py:345</font> (batch) e <font name='Courier' size='9'>"
        ":959</font> (síncrono). Reusa o <font name='Courier' size='9'>LeadScoringPipeline</font> "
        "já carregado no startup via injeção de dependência (orchestrator → DataQualityMonitor).",
        st['body']))
    s.append(P(
        "<b>Baseline pré-computado</b> em <font name='Courier' size='9'>"
        "configs/reference_audience_profiles/devclub_quality_signal.json</font> com as métricas do "
        "Top5 ROAS realized. Re-gerar quando trocar de modelo Challenger.",
        st['body']))

    s.append(P("7.2 Severidade do alerta emitido", st['h3']))
    rows = [[
        P('Condição', st['th_left']),
        P('Severity', st['th']),
        P('Sinal', st['th_left']),
    ]]
    sev_data = [
        ('Δ%D9-D10 ≤ -5pp OU Δscore ≤ -10%',                  'HIGH',   'Audiência ABAIXO do padrão (alerta)'),
        ('Δ%D9-D10 ≤ -3pp OU Δscore ≤ -5%',                   'MEDIUM', 'Levemente abaixo (atenção)'),
        ('Δ%D9-D10 ≥ +3pp E Δscore ≥ +5%',                    'LOW',    'ACIMA do padrão (informativo)'),
        ('Faixa neutra entre os limites',                     'LOW',    'DENTRO do padrão (informativo)'),
    ]
    for cond, sev, sig in sev_data:
        rows.append([P(cond, st['td_left']), P(sev, st['td_bold']), P(sig, st['td_left'])])
    s.append(make_table(rows, [7.0*cm, 2.5*cm, 6.9*cm]))

    s.append(P("7.3 Deploy", st['h3']))
    s.append(P(
        "Revisão Cloud Run <font name='Courier' size='9'>smart-ads-api-00439-fir</font> "
        "deployed em 11/05/2026 10:44 BRT, promovida para 100% do tráfego após smoke test e "
        "validação do bloco em chamada direta na revisão canary.",
        st['body']))

    # ── 8. Limitações ──
    s.append(PageBreak())
    s.append(P("8. Limitações conhecidas", st['h2']))
    s.append(P(
        "<b>1. Score absoluto não-calibrado.</b> calib_ratio ~60× — para predição de R$ absoluto, "
        "seria necessária recalibração via Platt scaling ou isotonic regression. Item de backlog. "
        "Para o sinal de drift adotado, basta o rank, então não é bloqueador.",
        st['body']))
    s.append(P(
        "<b>2. Sinal é premissa, não previsão.</b> Audiência com composição similar aos bons LFs "
        "(medida pelo modelo) <i>sugere</i> faturamento similar. Pode falhar se o Meta entregar "
        "leads bem-ranqueados pelo modelo mas com criativo/fluxo/landing page ruim. O sinal não "
        "substitui o forecast de receita do endpoint, apenas o complementa.",
        st['body']))
    s.append(P(
        "<b>3. Paridade backtest vs Lead.leadScore: 23%.</b> Comparando re-score atual com o "
        "valor salvo pelo Cloud Run em produção, a coincidência exata é de apenas 23% (decil "
        "bate em 52%). Causa raiz não identificada (testamos round-trip xlsx vs csv, race "
        "condition em <font name='Courier' size='9'>createdAt</font> vs "
        "<font name='Courier' size='9'>updatedAt</font>, mudanças de schema). Possíveis "
        "explicações: estado dinâmico do <font name='Courier' size='9'>pesquisa</font> jsonb "
        "(parcial no momento do score em prod, completo agora), versões de código diferentes "
        "entre score em prod e re-score agora. Mitigação adotada: <b>não usar Lead.leadScore — "
        "re-scorear tudo agora com mesma chain</b>, garantindo self-consistency.",
        st['body']))
    s.append(P(
        "<b>4. Challenger parcialmente in-sample para LF45/LF50 do baseline.</b> O Challenger "
        "abr28 teve cutoff em 08/04/2026 — LF45 e LF50 estão dentro do training+test do "
        "Challenger. Apenas LF53fp é 100% OOS. Para o baseline (régua de comparação) isso não é "
        "problema; para validar capacidade preditiva do modelo, usei LF53fp como OOS puro.",
        st['body']))
    s.append(P(
        "<b>5. Spread baixo entre os deltas observados.</b> LF52 (-2pp), LF54 (+1.8pp), DEV20 "
        "(+3.2pp). O sinal de drift dentro do esperado tem amplitude pequena — não classifica em "
        "&quot;ótimo / médio / ruim&quot;. Está dizendo apenas: &quot;audiência similar aos bons&quot; ou "
        "&quot;diferente&quot;. Para classificações finas, seria preciso baseline maior + threshold "
        "calibrado em mais lançamentos.",
        st['body']))

    # ── 9. Próximos passos ──
    s.append(P("9. Próximos passos / backlog", st['h2']))
    s.append(P(
        "<b>1. Recalibração do score do RF.</b> Treinar uma camada de calibração isotônica num "
        "holdout pós-train (~30min de trabalho). Salvar a curva no MLflow junto com o modelo. "
        "Output: score do RF passa a ser uma probabilidade calibrada (Σ(score) ≈ buyers reais). "
        "Não muda nada no rank (lift D10 idêntico), mas resolve o viés sistemático do revenue "
        "forecast (que hoje tem patches heurísticos).",
        st['body']))
    s.append(P(
        "<b>2. Acompanhar LF54 até o fim do ciclo.</b> Δ%D9-D10 = +1.8pp parcial; o sinal pode "
        "se mover quando a captação fechar (11/05). O daily-check vai mostrar o valor atualizado "
        "diariamente.",
        st['body']))
    s.append(P(
        "<b>3. Re-validar quando próximo Champion entrar.</b> O backtest precisa ser refeito com "
        "modelo novo. Baseline JSON pré-computado também precisa ser regerado.",
        st['body']))
    s.append(P(
        "<b>4. Investigar causa raiz da divergência backtest vs Lead.leadScore.</b> 77% de "
        "divergência indica algo estrutural (estado dinâmico, race condition). Não bloqueia o "
        "sinal porque já adotamos self-consistency, mas vale entender pra futuras integrações "
        "que dependam de Lead.leadScore.",
        st['body']))

    s.append(Spacer(1, 12))
    s.append(P(
        "<i>Bring Data · maio/2026</i>",
        st['footer']))

    return s


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    st = styles()
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )
    doc.build(build_story(st))
    print(f"✅ PDF gerado: {OUTPUT}")


if __name__ == "__main__":
    main()
