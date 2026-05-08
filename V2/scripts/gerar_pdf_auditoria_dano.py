"""
Gera PDF da Auditoria de Dano — Bugs do Sistema de ML — DevClub.

Saída: V2/propostas_e_apresentacoes/auditoria_dano_bugs_ml.pdf
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


OUTPUT = Path(__file__).parent.parent / "propostas_e_apresentacoes" / "auditoria_dano_bugs_ml.pdf"


# Paleta consistente com outros docs Bring Data
C_BLACK       = HexColor('#1a1a1a')
C_DARK_GRAY   = HexColor('#444444')
C_MID_GRAY    = HexColor('#777777')
C_LIGHT_GRAY  = HexColor('#f5f5f5')
C_GREEN       = HexColor('#1d8a3e')
C_GREEN_LIGHT = HexColor('#e8f5ec')
C_WHITE       = HexColor('#ffffff')
C_RULE        = HexColor('#e0e0e0')

# Severidade
C_SEV_HIGH       = HexColor('#c0392b')   # vermelho
C_SEV_HIGH_BG    = HexColor('#fde8e6')
C_SEV_MED        = HexColor('#b7791f')   # âmbar escuro
C_SEV_MED_BG     = HexColor('#fdf3d8')
C_SEV_LOW        = HexColor('#1d8a3e')   # verde
C_SEV_LOW_BG     = HexColor('#e8f5ec')

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
        'meta_label': ParagraphStyle('meta_label', fontName=bold, fontSize=9,
                                     textColor=C_DARK_GRAY, leading=12, alignment=TA_LEFT),
        'meta_value': ParagraphStyle('meta_value', fontName=base, fontSize=9,
                                     textColor=C_DARK_GRAY, leading=12, alignment=TA_LEFT),
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
        'sev_badge': ParagraphStyle('sev_badge', fontName=bold, fontSize=9,
                                    textColor=C_WHITE, alignment=TA_CENTER, leading=12),
        'footer': ParagraphStyle('footer', fontName=base, fontSize=7.5,
                                 textColor=C_MID_GRAY, leading=10, alignment=TA_CENTER),
    }


SEV_COLORS = {
    'Alta':  (C_SEV_HIGH, C_SEV_HIGH_BG),
    'Média': (C_SEV_MED,  C_SEV_MED_BG),
    'Baixa': (C_SEV_LOW,  C_SEV_LOW_BG),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def P(text, style):
    return Paragraph(text, style)


def make_table(rows, col_widths, header_bg=C_GREEN, highlight_row=None):
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
    if highlight_row is not None:
        style.add('BACKGROUND', (0,highlight_row), (-1,highlight_row), C_GREEN_LIGHT)
    return Table(rows, colWidths=col_widths, style=style, hAlign='LEFT')


def severity_badge(severity, st):
    """Pequeno badge colorido com a severidade. Retorna Table para uso inline."""
    fg, _ = SEV_COLORS[severity]
    cell = Paragraph(severity.upper(), st['sev_badge'])
    t = Table([[cell]], colWidths=[2.0*cm], rowHeights=[0.5*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), fg),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    return t


def metadata_box(severity, janela, st):
    """Box com Severidade + Janela lado a lado."""
    badge = severity_badge(severity, st)
    rows = [[
        P("<b>Severidade</b>", st['meta_label']),
        badge,
        P("<b>Janela</b>", st['meta_label']),
        P(janela, st['meta_value']),
    ]]
    t = Table(rows, colWidths=[2.5*cm, 2.5*cm, 1.8*cm, 9.7*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_LIGHT_GRAY),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LINEABOVE', (0,0), (-1,0), 0.5, C_RULE),
        ('LINEBELOW', (0,-1), (-1,-1), 0.5, C_RULE),
    ]))
    return t


def callout_box(label, body, st, bg=C_CALLOUT_BG, bd=C_CALLOUT_BD):
    """Caixa destacada com label + corpo."""
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


def section_block(numero, titulo, severidade, janela, blocks, st):
    """
    Renderiza uma seção de erro completa.
    blocks: lista de (label, conteudo). label pode ser None p/ texto solto.
    Seções sem tabelas grandes são embrulhadas em KeepTogether para evitar
    que callouts virem órfãos em páginas quase vazias.
    """
    out = []
    out.append(P(f"Erro {numero} — {titulo}", st['h2']))
    out.append(metadata_box(severidade, janela, st))
    out.append(Spacer(1, 4))
    for label, conteudo in blocks:
        if label == 'CALLOUT_INSIGHT':
            out.append(Spacer(1, 3))
            out.append(callout_box('Insight central', conteudo, st,
                                   bg=C_INSIGHT_BG, bd=C_INSIGHT_BD))
        elif label == 'CALLOUT_DANO':
            out.append(Spacer(1, 3))
            out.append(callout_box(conteudo[0], conteudo[1], st))
        elif label == 'TABLE':
            out.append(conteudo)
            out.append(Spacer(1, 3))
        elif label is None:
            if isinstance(conteudo, list):
                for c in conteudo:
                    out.append(P(c, st['body']))
            else:
                out.append(P(conteudo, st['body']))
        else:
            if isinstance(conteudo, list):
                out.append(P(f"<b>{label}:</b> {conteudo[0]}", st['body']))
                for extra in conteudo[1:]:
                    out.append(P(extra, st['body']))
            else:
                out.append(P(f"<b>{label}:</b> {conteudo}", st['body']))

    # Se não tem tabela grande (decil), embrulha tudo em KeepTogether para
    # evitar que callouts orfãos vão pra páginas quase vazias.
    has_decil_table = any(label == 'TABLE' and conteudo is not None and
                          hasattr(conteudo, '_argW') and len(getattr(conteudo, '_argW', [])) == 4
                          for label, conteudo in blocks)
    if not has_decil_table:
        return [KeepTogether(out)]
    return out


# ── Construção ────────────────────────────────────────────────────────────────

def build_story(st):
    s = []

    # ── Header ──
    s.append(P("Auditoria de Dano", st['h1']))
    s.append(P("Bugs do Sistema de Machine Learning · DevClub · mar–mai/2026", st['h1_sub']))
    s.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceBefore=10, spaceAfter=10))

    s.append(P(
        "Este documento descreve os bugs identificados no sistema de Machine Learning entre março e maio de 2026, "
        "estima o dano de cada um e lista as medidas corretivas implementadas em produção.",
        st['body']))
    s.append(P(
        "<b>Metodologia:</b> backtest contrafactual — para cada bug, o sistema re-pontua os leads do período "
        "com e sem o bug ativo, usando o modelo que estava em produção na janela. A diferença entre os dois "
        "cenários é o efeito direto do bug.",
        st['body']))
    s.append(P(
        "<i>Glossário rápido:</i> uma <b>feature</b> é uma das informações que o modelo usa para decidir o decil "
        "de cada lead — por exemplo, idade, origem do tráfego, faixa salarial. O modelo combina dezenas delas.",
        st['glossary']))

    # ── Sumário de severidade ──
    s.append(P("Sumário", st['h2']))
    s.append(P(
        "Bugs apresentados em ordem cronológica de início, classificados por severidade considerando "
        "volume de leads afetados, duração da janela e impacto financeiro/de otimização atribuível.",
        st['body']))

    # tabela sumário (sem coluna Dano direto)
    rows = [[
        P('Erro', st['th_left']),
        P('Descrição', st['th_left']),
        P('Janela', st['th']),
        P('Severidade', st['th']),
    ]]
    sumario = [
        ('1',   'Modelo aprendia em circuito fechado',                    'histórica',    'Baixa'),
        ('2',   'D9 invisível para a Meta',                               '~2 meses',     'Média'),
        ('3',   'Modelo em produção há 3+ meses sem retreino',            'contínua',     'Média'),
        ('4',   'Evento LQ amplo + valor superestimado',                  '~3 semanas',   'Média'),
        ('5',   'Feature de tráfego zerada (Linguagem de programação)',   '~18 dias',     'Baixa'),
        ('6.1', 'Idade e salário não chegaram ao modelo (pós rollback)',  '~6 dias',      'Alta'),
        ('6.2', 'Idade e salário não chegaram ao modelo (A/B reativado)', '~7 dias',      'Alta'),
        ('7',   'Evento LQ enviado sem valor',                            '~7 dias',      'Média'),
        ('8',   'Lista de origens chegou vazia em produção',              '~2-3 dias',    'Baixa'),
        ('9',   'Campanha A/B em evento ainda não aprovado',              '~2-3 dias',    'Baixa'),
    ]
    for erro, desc, janela, sev in sumario:
        sev_color, _ = SEV_COLORS[sev]
        sev_cell = Paragraph(f"<font color='{sev_color.hexval()}'><b>{sev}</b></font>", st['td'])
        rows.append([
            P(erro, st['td_bold']),
            P(desc, st['td_left']),
            P(janela, st['td']),
            sev_cell,
        ])
    s.append(make_table(rows, [1.4*cm, 9.4*cm, 2.6*cm, 2.6*cm]))
    s.append(Spacer(1, 6))
    s.append(P(
        "<b>Importante:</b> em vários erros o dano direto mensurado é parcial — a degradação do "
        "algoritmo de otimização da Meta (que treina em sinal contaminado e leva tempo para recalibrar) "
        "é um efeito indireto que se soma ao dano direto e não é quantificado nesta auditoria.",
        st['body']))

    s.append(PageBreak())

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 1 — Modelo aprendia em circuito fechado (histórica)
    # ────────────────────────────────────────────────────────────────────────────
    s += section_block(
        "1", "Modelo aprendia em circuito fechado",
        "Baixa", "histórica (até abril/2026)",
        [
            ('O quê',     "sem uma campanha de controle (sem ML) rodando em paralelo, o modelo era "
                          "retreinado em dados já influenciados pelas decisões dele mesmo. Ficava "
                          "difícil separar o efeito real do modelo do perfil dos leads que chegavam."),
            ('Contexto',  "a suspeita foi levantada em mar/2026 durante uma queda de performance e "
                          "motivou a mudança abrupta para o evento LQ amplo (Erro 4). Em abril, "
                          "testes com pesos por grupo mostraram que o impacto real era pequeno — "
                          "variação de performance abaixo de 0,3%. A hipótese que motivou o Erro 4 "
                          "nem havia sido confirmada."),
            ('CALLOUT_INSIGHT',
                "fragilidade reconhecida e já mitigada — campanha de controle agora roda em "
                "paralelo, e o ML mostra ganho consistente sobre ela (lift de 6,88× em D9+D10)."),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 2 — D9 invisível para a Meta
    # ────────────────────────────────────────────────────────────────────────────
    s += section_block(
        "2", "D9 invisível para a Meta",
        "Média", "~mid-jan → 15/mar (~2 meses)",
        [
            ('O quê',     "durante cerca de 2 meses, o evento de \"alta qualidade\" enviado à Meta — "
                          "o sinal principal usado pelo algoritmo para otimizar campanhas — estava "
                          "saindo apenas para leads D10. Os leads D9 (também de alta qualidade) ficaram "
                          "<b>invisíveis</b> nesse sinal."),
            ('Contexto',  "o sistema usava dois formatos diferentes em módulos distintos do código "
                          "(<font name='Courier'>D9</font> em um lado, <font name='Courier'>D09</font> "
                          "em outro). O acréscimo de zero (<font name='Courier'>D09</font> em vez de "
                          "<font name='Courier'>D9</font>) tinha sido solicitado pelo gestor de tráfego "
                          "para facilitar a ordenação manual dos leads quando ainda eram organizados "
                          "em Google Sheets — mas a mudança foi feita só em parte do código, criando "
                          "a divergência. A comparação só casava para D10 (que é igual nos dois formatos) "
                          "e falhava em D9. Múltiplos fixes parciais foram necessários ao longo de "
                          "fev-mar para alinhar todos os módulos — o último deles em 15/mar fechou a janela."),
            ('CALLOUT_INSIGHT',
                "durante ~2 meses, a Meta recebeu o sinal de alta qualidade de <b>apenas metade</b> dos "
                "leads top — só ~10% do volume (apenas D10) em vez dos ~20% esperados (D9 + D10). "
                "O algoritmo otimizou para um perfil mais estreito do que o ideal, perdendo a "
                "oportunidade de aprender com leads D9. Não há medição financeira direta possível, "
                "mas o efeito existiu."),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 3 — Modelo em produção há 3+ meses sem retreino
    # ────────────────────────────────────────────────────────────────────────────
    s += section_block(
        "3", "Modelo em produção há 3+ meses sem retreino",
        "Média", "contínua (treino 30/jan/2026 com dados até 24/set/2025)",
        [
            ('O quê',     "o modelo em produção tem mais de 3 meses de uso e os dados em que ele "
                          "aprendeu terminam em set/2025 — quase 7 meses atrás. O perfil de leads "
                          "e o comportamento de conversão provavelmente mudaram desde então. O "
                          "impacto exato não é mensurável sem um modelo novo em produção pra comparar."),
            ('Contexto',  "várias mudanças de código nos últimos meses tinham como objetivo "
                          "substituir esse modelo por um mais novo. Cada tentativa trouxe efeitos "
                          "colaterais documentados (Erros 6.1, 6.2, 7) que precisaram ser corrigidos "
                          "antes de avançar."),
            ('CALLOUT_INSIGHT',
                "dívida técnica em aberto, não bug pontual. O próximo retreino + deploy controlado "
                "(com as salvaguardas já implementadas — ver Medidas Corretivas) fecha esse risco."),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 4 — LQ amplo + valor superestimado
    # ────────────────────────────────────────────────────────────────────────────
    s += section_block(
        "4", "Evento LQ enviado com cobertura ampla e valor superestimado",
        "Média", "10/mar → início abr (revertido pouco antes do rollback de 13/abr)",
        [
            ('O quê', [
                "dois problemas no evento <b>LeadQualified</b> que o sistema envia ao Meta como sinal "
                "de otimização das campanhas:",
                "<b>1. Cobertura</b> — o evento passou a ser disparado para todos os decis (D1–D10) "
                "com valor proporcional, em vez de só D9–D10 como antes.",
                "<b>2. Valor</b> — o valor financeiro atribuído a cada conversão estava calibrado pelo "
                "<b>total a ser recebido no longo prazo, já descontada a inadimplência projetada</b> "
                "— não pelo valor à vista efetivamente recebido. Isso superestimava o retorno de cada "
                "conversão a curto prazo.",
            ]),
            ('Contexto',  "a decisão foi tomada por se acreditar que enviar um evento \"mais rico\" "
                          "(cobrindo todos os decis com valor proporcional) ajudaria a Meta a otimizar "
                          "melhor as campanhas. Na prática, abriu o sinal para perfis mais amplos e "
                          "inflou o retorno aparente."),
            (None,
                "<b>Resultado (descritivo, sem medição direta):</b> o algoritmo de otimização da Meta "
                "passou a buscar um perfil de lead mais amplo e a \"remunerar\" cada conversão com um "
                "valor inflado. A audiência das campanhas degradou progressivamente. O ROAS dos LFs do "
                "período ficou significativamente abaixo dos LFs limpos (LF44/45), mas o período coincide "
                "com o período de março em que a Meta declarou ter passado por instabilidade no sistema "
                "de anúncios."),
            ('CALLOUT_INSIGHT',
                "a criação do novo pixel pode ter ajudado a reverter esse erro mais rapidamente."),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 5 — Feature de tráfego zerada (Medium_Linguagem)
    # ────────────────────────────────────────────────────────────────────────────
    rows5 = [[P('Métrica', st['th_left']), P('Sem bug', st['th']), P('Com bug', st['th']), P('Δ', st['th'])]]
    rows5.append([P('Leads em D9–D10', st['td_left']), P('14.227', st['td']), P('14.234', st['td']), P('+7', st['td'])])
    rows5.append([P('Conversões em D9–D10', st['td_left']), P('144', st['td']), P('144', st['td']), P('0', st['td'])])
    tab5 = make_table(rows5, [6*cm, 3.3*cm, 3.3*cm, 3.5*cm])

    s += section_block(
        "5", "Feature de tráfego zerada (Linguagem de programação)",
        "Baixa", "26/mar → 13/abr (~18 dias)",
        [
            ('O quê',     "uma feature de origem de tráfego (segmento \"Linguagem de programação\") "
                          "deixou de chegar ao modelo por divergência de nome de coluna entre treino "
                          "e produção. Em produção a feature ficava zerada."),
            ('Contexto',  "durante uma reorganização do código que processa as origens de tráfego, "
                          "uma transformação de texto removeu acentos das categorias. O segmento "
                          "\"Linguagem de programação\" virou \"Linguagem de programacao\" (sem cedilha) "
                          "— mas o modelo, treinado com o nome anterior, não a reconhecia. A feature "
                          "passou a chegar zerada. Foi corrigida em 14/abr."),
            ('TABLE', tab5),
            ('CALLOUT_DANO', ('Dano estimado', '~R$ 0')),
            ('CALLOUT_INSIGHT',
                "a feature pesa ~5% no modelo globalmente, mas na janela analisada a audiência veio "
                "78,9% de campanhas \"aberto\" e apenas 0,1% do segmento \"Linguagem de programação\". "
                "A feature já estava praticamente vazia para essa audiência — o bug existiu, mas não "
                "teve onde causar dano."),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 6.1 — idade/salário pós rollback
    # ────────────────────────────────────────────────────────────────────────────
    rows61 = [[P('Decil sem bug', st['th_left']), P('Total', st['th']), P('Alterados', st['th']), P('% alterado', st['th'])]]
    dados61 = [
        ('D01', '498', '65', '13,1%'),
        ('D02', '491', '153', '31,2%'),
        ('D03', '345', '163', '47,2%'),
        ('D04', '375', '171', '45,6%'),
        ('D05', '562', '219', '39,0%'),
        ('D06', '911', '327', '35,9%'),
        ('D07', '1.003', '361', '36,0%'),
        ('D08', '1.138', '336', '29,5%'),
        ('D09', '1.362', '320', '23,5%'),
        ('D10', '3.891', '260', '6,7%'),
    ]
    for d, t, a, p in dados61:
        rows61.append([P(d, st['td_left']), P(t, st['td']), P(a, st['td']), P(p, st['td'])])
    rows61.append([
        P('<b>Total</b>', st['td_bold_left']),
        P('<b>10.576</b>', st['td_bold']),
        P('<b>2.375</b>', st['td_bold']),
        P('<b>22,5%</b>', st['td_bold']),
    ])
    tab61 = make_table(rows61, [4*cm, 4*cm, 4*cm, 4.4*cm], highlight_row=len(rows61)-1)

    s += section_block(
        "6.1", "Idade e salário não chegaram ao modelo (após rollback do modelo)",
        "Alta", "26/mar → 01/abr (~6 dias)",
        [
            ('O quê',     "o modelo antigo voltou a rodar em 26/mar após um rollback, mas o código "
                          "continuou na versão preparada para o modelo novo. Resultado: durante 6 dias, "
                          "<b>idade</b> e <b>faixa salarial</b> não chegaram ao modelo — ele tomou todas as "
                          "decisões como se esses dois campos fossem desconhecidos. Essas duas variáveis "
                          "representam cerca de <b>8% do peso total</b> das decisões do modelo."),
            ('Contexto',  "em 15/mar foi colocado em produção um modelo novo, treinado em uma pipeline "
                          "nova que esperava idade e salário em formato diferente do antigo. Em 25/mar "
                          "o resultado ficou ruim e foi feito rollback do modelo para o antigo — mas só "
                          "o modelo voltou, o código permaneceu na versão nova. O modelo antigo passou "
                          "então a receber idade e salário em um formato que ele não reconhecia, com "
                          "esses dois campos zerados nas decisões. Foi corrigido em 01/abr."),
            (None, '<b>Backtest — leads alterados por decil de origem:</b>'),
            ('TABLE', tab61),
            ('CALLOUT_DANO', ('Dano direto (referência histórica suavizada)', [
                "Rebaixamentos (perda real): <b>R$ 2.620</b>",
                "Promoções espúrias (falsos positivos): <b>R$ 1.832</b>",
                "<b>Saldo líquido: R$ 788</b>",
                "Movimentação total de valor entre decis: <b>R$ 4.451</b>",
            ])),
            ('CALLOUT_INSIGHT', [
                "o saldo líquido modesto (~R$ 800) <b>não significa ausência de impacto</b>. O bug "
                "embaralhou a ordenação dos leads em vez de empurrá-la em uma direção — rebaixamentos "
                "e promoções se compensaram em valor médio. Mas o efeito real é maior:",
                "<b>1. Poder discriminativo degradado</b> — 22,5% dos leads receberam decil errado, "
                "com taxa de erro acima de 35% nos decis médios (D3–D7).",
                "<b>2. Eventos LeadQualified com decis contaminados</b> — leads de qualidade média "
                "foram para o Meta como D9–D10, e parte dos D9–D10 reais caiu para decis intermediários. "
                "O sinal de otimização da campanha chegou ruidoso.",
                "<b>3. Otimização da campanha perdida</b> — durante a janela, o algoritmo da Meta "
                "treinou em sinal contaminado e perdeu capacidade de encontrar o perfil correto de lead. "
                "Esse efeito acumula no tempo e não é quantificado aqui.",
            ]),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 6.2 — idade/salário A/B reativado
    # ────────────────────────────────────────────────────────────────────────────
    rows62 = [[P('Decil sem bug', st['th_left']), P('Total', st['th']), P('Alterados', st['th']), P('% alterado', st['th'])]]
    dados62 = [
        ('D01', '1.066', '93', '8,7%'),
        ('D02', '718', '209', '29,1%'),
        ('D03', '467', '223', '47,8%'),
        ('D04', '596', '271', '45,5%'),
        ('D05', '946', '433', '45,8%'),
        ('D06', '1.652', '698', '42,3%'),
        ('D07', '1.983', '835', '42,1%'),
        ('D08', '2.034', '674', '33,1%'),
        ('D09', '2.184', '541', '24,8%'),
        ('D10', '5.779', '394', '6,8%'),
    ]
    for d, t, a, p in dados62:
        rows62.append([P(d, st['td_left']), P(t, st['td']), P(a, st['td']), P(p, st['td'])])
    rows62.append([
        P('<b>Total</b>', st['td_bold_left']),
        P('<b>17.425</b>', st['td_bold']),
        P('<b>4.371</b>', st['td_bold']),
        P('<b>25,1%</b>', st['td_bold']),
    ])
    tab62 = make_table(rows62, [4*cm, 4*cm, 4*cm, 4.4*cm], highlight_row=len(rows62)-1)

    s += section_block(
        "6.2", "Idade e salário não chegaram ao modelo (A/B reativado)",
        "Alta", "29/abr → 05/mai (~7 dias)",
        [
            ('O quê',     "quando o teste A/B foi reativado em 29/abr, uma peça de configuração ficou "
                          "faltando para o modelo principal. Resultado: durante 7 dias, <b>idade</b> e "
                          "<b>faixa salarial</b> dos leads não chegaram ao modelo — ele tomou todas as "
                          "decisões como se esses dois campos fossem desconhecidos. Essas duas variáveis "
                          "representam cerca de <b>8% do peso total</b> das decisões do modelo."),
            ('Contexto',  "o erro veio da reativação do teste A/B em 29/abr para comparar o modelo antigo "
                          "(em produção) com um modelo novo. Os dois foram treinados com pipelines "
                          "diferentes e esperavam idade e salário em formatos distintos. Ao religar o A/B, "
                          "o código só aplicou o formato correto para o modelo novo — os leads que caíam "
                          "no modelo antigo (~90% ou + do tráfego) chegaram sem essas duas variáveis. "
                          "A correção equivalente já existia em outro trecho do código, mas não tinha "
                          "sido replicada nesse caminho. Foi corrigida em 05/mai."),
            (None, '<b>Backtest — leads alterados por decil de origem:</b>'),
            ('TABLE', tab62),
            ('CALLOUT_DANO', ('Dano direto (referência histórica suavizada)', [
                "Rebaixamentos (perda real): <b>R$ 4.218</b>",
                "Promoções espúrias (falsos positivos): <b>R$ 4.318</b>",
                "<b>Saldo líquido: ~R$ 0</b>",
                "Movimentação total de valor entre decis: <b>R$ 8.536</b>",
            ])),
            ('CALLOUT_INSIGHT', [
                "o saldo líquido próximo de zero <b>não significa ausência de impacto</b>. O bug embaralhou "
                "a ordenação em vez de empurrá-la em uma direção — rebaixamentos e promoções se "
                "compensaram em valor médio. Mas o efeito real é maior:",
                "<b>1. Poder discriminativo degradado</b> — 25,1% dos leads receberam decil errado, "
                "com taxa de erro acima de 40% nos decis médios (D3–D7).",
                "<b>2. Eventos LeadQualified com decis contaminados</b> — leads de qualidade média "
                "foram para o Meta como D9–D10, e parte dos D9–D10 reais caiu para decis intermediários. "
                "O sinal de otimização da campanha chegou ruidoso.",
                "<b>3. Otimização da campanha perdida</b> — durante a janela, o algoritmo da Meta "
                "treinou em sinal contaminado e perdeu capacidade de encontrar o perfil correto de lead. "
                "Esse efeito acumula no tempo e não é quantificado aqui.",
            ]),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 7 — LQ sem value
    # ────────────────────────────────────────────────────────────────────────────
    s += section_block(
        "7", "Evento LQ enviado sem valor por 7 dias",
        "Média", "29/abr → 06/mai (~7 dias)",
        [
            ('O quê',     "durante 7 dias o evento <b>LeadQualified</b> saiu para a Meta sem o valor "
                          "financeiro associado. As campanhas que estavam otimizando nesse evento "
                          "continuaram gastando, mas sem o sinal econômico que o algoritmo da Meta "
                          "precisa para aprender a buscar leads com maior retorno."),
            ('Contexto',  "o erro veio de uma evolução da arquitetura — o sistema estava sendo migrado "
                          "de uma estrutura com valores escritos diretamente no código para uma versão "
                          "configurável e generalizável, que vai facilitar a manutenção e suportar novos "
                          "modelos do DevClub no futuro. Na reescrita da parte que carrega os valores "
                          "que os leads de cada decil valem, ficou faltando a leitura do arquivo de "
                          "configuração — os valores não chegaram ao evento. O LeadQualified continuou "
                          "sendo enviado, mas com o campo de valor vazio."),
            ('CALLOUT_DANO', ('Gasto no período', [
                "<b>R$ 8.433,19</b> na campanha <i>DEVLF | CAP | FRIO | FASE 04 | ADV | "
                "PIXEL NOVO | MACHINE LEARNING | LQ | PG2 | 2025-04-15</i>",
                "<font name='Courier' size='8'>(id 120242248118610390)</font>",
            ])),
            ('CALLOUT_INSIGHT',
                "o gasto direto no período é o que pode ser atribuído de forma defensável. O efeito "
                "indireto — a Meta tendo gastado 7 dias sem sinal de valor para refinar o perfil dos "
                "leads — não é mensurável diretamente, mas se soma aos demais erros que distorceram o "
                "sinal de otimização nesse mesmo período (Erros 6.2 e 9)."),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 8 — Lista de origens vazia em produção
    # ────────────────────────────────────────────────────────────────────────────
    s += section_block(
        "8", "Lista de origens de tráfego chegou vazia em produção",
        "Baixa", "30/abr → 02/mai (~2-3 dias)",
        [
            ('O quê',     "o sistema mantém uma lista oficial das categorias de origem de tráfego "
                          "(tipos de campanha, lookalikes, criativos) que o modelo conhece — categorias "
                          "com as quais ele foi treinado. Essa lista é gravada em arquivo durante o treino "
                          "e é lida na produção. Por uma divergência de caminho entre onde o sistema "
                          "<b>gravava</b> e onde <b>lia</b> o arquivo, a lista chegou <b>vazia</b> em "
                          "produção. Quando um lead chegava com origem rara ou nova (tag de criativo "
                          "nova, lookalike novo, variante de campanha), o sistema não a reconhecia e "
                          "<b>zerava todas as colunas relacionadas a esse tipo de origem para esses leads</b>."),
            ('Contexto',  "o bug existia no código desde meados de março, mas não impactou produção "
                          "imediatamente — até 30/abr o sistema rodava uma versão anterior do código "
                          "(rollback). Quando a versão atual do código subiu a 100% do tráfego em "
                          "30/abr, o bug se manifestou. Foi detectado e corrigido em 02/mai."),
            ('CALLOUT_INSIGHT',
                "janela curta em produção (~2-3 dias). Natureza similar ao Erro 5 (feature de origem "
                "zerando), mas com features distintas afetadas. Sem medição direta de dano financeiro "
                "pela curta duração, mas se soma à degradação de sinal vivenciada no mesmo período "
                "(sobrepõe Erros 6.2, 7 e 9)."),
        ],
        st,
    )

    s.append(Spacer(1, 6))

    # ────────────────────────────────────────────────────────────────────────────
    # Erro 9 — HQLB cego
    # ────────────────────────────────────────────────────────────────────────────
    s += section_block(
        "9", "Campanha A/B otimizando em evento ainda não aprovado pela Meta",
        "Baixa", "02/mai → 04/mai (~2-3 dias)",
        [
            ('O quê',     "uma campanha A/B foi colocada em produção otimizando num evento HQLB que "
                          "ainda não tinha sido aprovado pela Meta. Durante esses dias a campanha "
                          "gastou dinheiro sem que o evento de otimização estivesse sendo reconhecido "
                          "— a campanha rodou totalmente cega."),
            ('Contexto',  "erro inicial do gestor de tráfego ao subir a campanha antes da aprovação do "
                          "evento, somado à ausência de monitoramento da minha parte que detectasse "
                          "o evento não aprovado em tempo hábil."),
            ('CALLOUT_DANO', ('Gasto no período', [
                "<b>R$ 1.444,89</b> na campanha <i>DEVLF | CAP | FRIO | FASE 04 | ADV | "
                "PIXEL NOVO API | MACHINE LEARNING | LEAD | PG2 | 2025-04-30</i>",
                "<font name='Courier' size='8'>(id 120243354440640390)</font>",
            ])),
            ('CALLOUT_INSIGHT',
                "todo o gasto pode ser atribuído como desperdiçado — sem evento aprovado, a Meta não "
                "recebia nenhum sinal de otimização, então rodou só por entrega bruta. Diferente do "
                "Erro 7 (onde havia evento mas sem valor), aqui não havia evento algum."),
        ],
        st,
    )

    s.append(Spacer(1, 10))

    # ────────────────────────────────────────────────────────────────────────────
    # Medidas corretivas
    # ────────────────────────────────────────────────────────────────────────────
    s.append(P("Medidas corretivas implementadas", st['h2']))
    s.append(P(
        "Todas as medidas abaixo foram implementadas em produção entre 20/abr e 02/mai/2026, "
        "com data de deploy verificável. Atacam diretamente o bug-raiz "
        "<i>\"deploy de modelo com 100% de tráfego sem testes prévios\"</i>.",
        st['body']))

    medidas = [
        ('Deploy agora é controlado e testado', [
            ('Progressão obrigatória de tráfego', '21/abr',
             "toda nova versão começa atendendo 0% dos leads, sobe para 10% (com 1h de monitoramento), "
             "depois 50% (24h de confirmação), e só vai a 100% após critérios cumpridos. Permite rollback instantâneo."),
            ('Teste automático antes de cada deploy', '21/abr',
             "o sistema roda 5 leads de teste reais e bloqueia o deploy se score, decil ou evento não saem corretos."),
            ('Atalho perigoso eliminado', '02/mai',
             "o caminho que permitia deploy direto a 100% foi removido do código. Agora sempre passa "
             "pelo protocolo de progressão."),
        ]),
        ('Detecção de features faltando', [
            ('Verificação antes do envio ao modelo', '23/abr',
             "se uma feature crítica não chegar com o nome ou tipo certo, o sistema falha alto e bloqueia "
             "— em vez de seguir silenciosamente com a feature zerada."),
            ('Verificação após o encoding', '21/abr',
             "se uma feature importante aparecer zerada em mais de 5% dos leads, o sistema gera alerta "
             "e bloqueia. Salvaguarda que faltava nos Erros 5, 6.1, 6.2 e 8."),
            ('Painel de cobertura de features', '23/abr',
             "dashboard com últimas 24h de problemas — quais features tiveram issues e em quantos lotes."),
        ]),
        ('Paridade entre treino e produção', [
            ('Auditoria automática treino↔produção', '21/abr',
             "antes de cada deploy, o sistema pega dados do treino, roda no pipeline de produção, "
             "compara coluna a coluna. Se divergir, bloqueia."),
            ('Verificação do modelo na inicialização', '29/abr',
             "quando o sistema sobe, confere que o modelo carregado é o declarado na configuração "
             "— detecta cenário de versão antiga rodando."),
            ('Reconciliação de identificador do modelo', '29/abr',
             "confirma que o modelo em produção é o mesmo da configuração."),
        ]),
        ('Monitoramento e alertas', [
            ('Alerta para decis sem eventos', '20/abr',
             "se algum decil (D1–D10) não receber evento por 24h, alerta vermelho. Previne situação "
             "como o Erro 2 (D9 invisível por ~2 meses)."),
            ('Eliminação de exceções silenciosas', '28/abr',
             "pontos onde erros eram engolidos sem log foram convertidos em falhas auditáveis."),
            ('Encoding falha alto em divergência de nome', '20/abr',
             "quando uma coluna não casa entre treino e produção, o sistema falha visivelmente em vez "
             "de pular o encoding silenciosamente."),
        ]),
        ('Filtros e correções pontuais', [
            ('Whitelist de origens válidas para o evento Meta', '30/abr',
             "só envia evento ao Pixel para leads com origem rastreável (facebook-ads, instagram)."),
            ('Path correto de categorias de origem', '02/mai',
             "corrigido bug em que a lista de origens válidas chegava vazia em produção (Erro 8)."),
        ]),
    ]
    for grupo_titulo, items in medidas:
        block = []
        block.append(P(grupo_titulo, st['h3']))
        rows = [[P('Medida', st['th_left']), P('Data', st['th']), P('O que faz', st['th_left'])]]
        for nome, data, descricao in items:
            rows.append([
                P(f"<b>{nome}</b>", st['td_bold_left']),
                P(data, st['td']),
                P(descricao, st['td_left']),
            ])
        block.append(make_table(rows, [4.5*cm, 1.5*cm, 10.4*cm]))
        block.append(Spacer(1, 4))
        s.append(KeepTogether(block))

    s.append(P("Itens em andamento", st['h3']))
    s.append(P("• Auditoria automática de paridade durante o treino (próximo retreino).", st['body']))
    s.append(P("• Resolução final de algumas categorias residuais de origem (próximo retreino).", st['body']))

    # ── Footer ──
    s.append(Spacer(1, 16))
    s.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE))
    s.append(Spacer(1, 4))
    s.append(P("Auditoria de Dano · Bring Data · 07/05/2026", st['footer']))

    return s


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    st = styles()
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="Auditoria de Dano — Bugs do Sistema de ML",
        author="Bring Data",
    )
    doc.build(build_story(st))
    print(f"PDF gerado: {OUTPUT}")


if __name__ == '__main__':
    main()
