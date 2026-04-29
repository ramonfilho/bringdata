"""
Gera PDF do briefing de Teste A/B Champion vs Challenger — DEV20.

Saída: V2/propostas_e_apresentacoes/briefing_teste_ab_dev20.pdf
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether, PageBreak, Image,
)
from reportlab.lib.colors import HexColor

import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUTPUT = Path(__file__).parent.parent / "propostas_e_apresentacoes" / "briefing_teste_ab_dev20.pdf"

# Paleta consistente com outros docs Bring Data
C_BLACK      = HexColor('#1a1a1a')
C_DARK_GRAY  = HexColor('#444444')
C_MID_GRAY   = HexColor('#777777')
C_LIGHT_GRAY = HexColor('#f5f5f5')
C_GREEN      = HexColor('#1d8a3e')
C_GREEN_MID  = HexColor('#52a86b')
C_GREEN_LIGHT= HexColor('#e8f5ec')
C_GREEN_PALE = HexColor('#f4fbf6')
C_WHITE      = HexColor('#ffffff')
C_RULE       = HexColor('#e0e0e0')
C_CALLOUT_BG = HexColor('#fff8e1')
C_CALLOUT_BD = HexColor('#f9a825')


def styles():
    base = 'Helvetica'
    bold = 'Helvetica-Bold'
    return {
        'h1': ParagraphStyle('h1', fontName=bold, fontSize=18,
                             textColor=C_BLACK, leading=22, spaceAfter=4),
        'h1_sub': ParagraphStyle('h1_sub', fontName=base, fontSize=10,
                                 textColor=C_MID_GRAY, leading=14, spaceAfter=2),
        'h2': ParagraphStyle('h2', fontName=bold, fontSize=13,
                             textColor=C_BLACK, leading=18, spaceBefore=18, spaceAfter=8),
        'h3': ParagraphStyle('h3', fontName=bold, fontSize=10.5,
                             textColor=C_BLACK, leading=14, spaceBefore=10, spaceAfter=4),
        'body': ParagraphStyle('body', fontName=base, fontSize=9.5,
                               textColor=C_DARK_GRAY, leading=14, spaceAfter=6, alignment=TA_LEFT),
        'body_bold': ParagraphStyle('body_bold', fontName=bold, fontSize=9.5,
                                    textColor=C_DARK_GRAY, leading=14, spaceAfter=6),
        'callout': ParagraphStyle('callout', fontName=base, fontSize=10,
                                  textColor=C_BLACK, leading=15, spaceAfter=10,
                                  leftIndent=10, rightIndent=10),
        'mono': ParagraphStyle('mono', fontName='Courier', fontSize=8.5,
                               textColor=C_DARK_GRAY, leading=11, alignment=TA_LEFT),
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
        'footer': ParagraphStyle('footer', fontName=base, fontSize=7.5,
                                 textColor=C_MID_GRAY, leading=10, alignment=TA_CENTER),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_table(rows, col_widths, header_bg=C_GREEN, highlight_row=None, st=None):
    """Cria Table com estilo padrão (header verde, linhas alternadas, opcionalmente uma linha destacada)."""
    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), header_bg),
        ('TEXTCOLOR',  (0,0), (-1,0), C_WHITE),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ('LINEBELOW',  (0,0), (-1,0), 0.5, C_RULE),
        ('LINEBELOW',  (0,-1), (-1,-1), 0.5, C_RULE),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ])
    # Linhas alternadas
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.add('BACKGROUND', (0,i), (-1,i), C_LIGHT_GRAY)
    # Linha destacada
    if highlight_row is not None:
        style.add('BACKGROUND', (0,highlight_row), (-1,highlight_row), C_GREEN_LIGHT)
    return Table(rows, colWidths=col_widths, style=style, hAlign='LEFT')


def P(text, style):
    return Paragraph(text, style)


def make_flow_diagram() -> bytes:
    """Gera diagrama do fluxo do teste A/B em PNG via matplotlib."""
    fig, ax = plt.subplots(figsize=(9, 6.2), dpi=200)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 9.2)
    ax.set_aspect('equal')
    ax.axis('off')

    def box(x, y, w, h, text, color='#e8f5ec', edge='#1d8a3e', fontsize=10.5):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.08,rounding_size=0.18",
            edgecolor=edge, facecolor=color, linewidth=1.3,
        ))
        ax.text(x + w/2, y + h/2, text, ha='center', va='center',
                fontsize=fontsize, color='#1a1a1a')

    def diamond(cx, cy, w, h, text, color='#fff8e1', edge='#f9a825', fontsize=10.5):
        pts = [[cx, cy + h/2], [cx + w/2, cy], [cx, cy - h/2], [cx - w/2, cy]]
        poly = plt.Polygon(pts, edgecolor=edge, facecolor=color, linewidth=1.3)
        ax.add_patch(poly)
        ax.text(cx, cy, text, ha='center', va='center', fontsize=fontsize, color='#1a1a1a')

    def arrow(x1, y1, x2, y2, label=None, label_offset=(0, 0)):
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle='->', lw=1.4, color='#444'))
        if label:
            mx, my = (x1+x2)/2 + label_offset[0], (y1+y2)/2 + label_offset[1]
            ax.text(mx, my, label, ha='center', va='center',
                    fontsize=10, color='#1d8a3e', fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.25', facecolor='white', edgecolor='none'))

    # Top: form
    box(2.5, 8.1, 5, 0.85, 'Lead chega ao formulário do site DevClub')
    arrow(5, 8.1, 5, 7.55)

    # API
    box(2.5, 6.7, 5, 0.85, 'API recebe lead com UTM')
    arrow(5, 6.7, 5, 6.25)

    # Decision diamond
    diamond(5, 5.6, 3.0, 1.3, 'UTM contém "HQLB"?')

    # Branches from diamond
    arrow(3.5, 5.6, 1.8, 4.4, 'NÃO', label_offset=(-0.1, 0.2))
    arrow(6.5, 5.6, 8.2, 4.4, 'SIM', label_offset=(0.1, 0.2))

    # Models
    box(0.3, 3.5, 3, 0.85, 'Modelo A (Champion)')
    box(6.7, 3.5, 3, 0.85, 'Modelo B (Challenger)')

    # Down arrows
    arrow(1.8, 3.5, 1.8, 2.95)
    arrow(8.2, 3.5, 8.2, 2.95)

    # CAPI events
    box(0.3, 2.05, 3, 0.85, 'Dispara CAPI:\nLeadQualifiedHighQuality',
        color='#f4fbf6', edge='#52a86b', fontsize=9)
    box(6.7, 2.05, 3, 0.85, 'Dispara CAPI:\nevento HQLB',
        color='#f4fbf6', edge='#52a86b')

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=200, bbox_inches='tight',
                facecolor='white', pad_inches=0.1)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ── Construção do documento ───────────────────────────────────────────────────

def build_story(st):
    story = []

    # ── Header ──
    story.append(P("Teste A/B Champion vs Challenger — DEV20", st['h1']))
    story.append(P("28/04/2026 · Lançamento DEV20 (cap 21/04 → 04/05, vendas 11/05 → 17/05)", st['h1_sub']))
    story.append(P(
        "<b>Champion (A) = jan30</b> — modelo em produção desde 30/01/2026 &nbsp;|&nbsp; "
        "<b>Challenger (B) = abr28</b> — candidato treinado em 28/04/2026",
        st['body']))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceBefore=10, spaceAfter=2))

    # ── Sumário executivo ──
    story.append(P("Sumário executivo", st['h2']))
    story.append(P(
        "O Champion A entrega ROAS médio de <b>5,3×</b> ao longo de 7 lançamentos consecutivos (LF45–LF51).",
        st['body']))
    story.append(P(
        "O Challenger B foi treinado com dataset 1,8× maior (201 mil leads vs 110 mil). "
        "Em testes offline sobre 186 vendas reais (LF51, LF52, LF53), <b>B separa compradores de não-compradores cerca de 2,7× melhor</b> que A no decil mais alto.",
        st['body']))
    story.append(P(
        "Antes de promover B a Champion, é necessário validar em produção real. "
        "Propomos teste A/B no DEV20 com <b>R$ 72k (35% do orçamento restante)</b> alocado numa campanha B, "
        "mantendo as campanhas A com os R$ 133k restantes.",
        st['body']))
    story.append(P(
        "Leitura final: <b>22–25/05/2026</b> após carrinho fechar e parcelas TMB efetivarem.",
        st['body']))

    # ── 1. Por que considerar substituir ──
    story.append(P("1. Por que considerar substituir o Champion A", st['h2']))
    story.append(P("O que A entrega hoje", st['h3']))

    rows = [[P('Lançamento', st['th_left']), P('ROAS', st['th']), P('Top‑3 decis (D8+D9+D10) capturam', st['th'])]]
    historico = [
        ('LF45', '7,70×',  '75% das vendas'),
        ('LF46', '5,73×',  '77% das vendas'),
        ('LF47', '5,75×',  '73% das vendas'),
        ('LF48', '3,63×',  '67% das vendas'),
        ('LF49', '5,39×',  '38% (anomalia documentada)'),
        ('LF50', '5,06×',  '69% das vendas'),
        ('LF51', '3,85×',  '61% das vendas'),
    ]
    for lf, roas, top3 in historico:
        rows.append([P(lf, st['td_left']), P(roas, st['td']), P(top3, st['td'])])
    rows.append([P('<b>Média</b>', st['td_bold_left']), P('<b>5,3×</b>', st['td_bold']), P('<b>66% das vendas</b>', st['td_bold'])])
    story.append(make_table(rows, [3.5*cm, 3*cm, 8*cm], highlight_row=len(rows)-1, st=st))
    story.append(Spacer(1, 6))
    story.append(P(
        "Os 30% de leads classificados nos top 3 decis pelo Champion A capturam, em média, 66% das vendas do lançamento.",
        st['body']))

    story.append(P("Por que reavaliar", st['h3']))
    story.append(P(
        "<b>1. Saturação no decil mais alto.</b> A hoje classifica ~33% dos leads como D10 "
        "(esperado pela calibração do treino: 10%).", st['body']))
    story.append(P(
        "<b>2. Treino defasado.</b> A foi treinado com dados até novembro de 2025 — não viu nenhum lançamento de 2026.", st['body']))
    story.append(P(
        "<b>3. Volume de dados disponíveis cresceu.</b> Dataset disponível hoje é quase 2× maior que o usado no treino de A.", st['body']))

    story.append(P("O que B traz de diferente", st['h3']))
    rows = [[P('Característica', st['th_left']), P('Champion A (jan30)', st['th']), P('Challenger B (abr28)', st['th'])]]
    diff = [
        ('Data de treino', '30/01/2026', '28/04/2026'),
        ('Total de leads no dataset', '110.505', '201.547'),
        ('Janela temporal coberta', 'mar/2025 → nov/2025', 'fev/2025 → abr/2026'),
        ('Fontes de venda', 'Guru', 'Guru + Hotmart'),
        ('Fontes de lead', 'Sheets', 'Sheets + Railway'),
        ('Correção de feedback loop', 'Não', 'Sim (importance weighting do grupo controle)'),
    ]
    for c, a, b in diff:
        rows.append([P(c, st['td_left']), P(a, st['td']), P(b, st['td'])])
    story.append(make_table(rows, [6*cm, 5*cm, 5*cm], st=st))

    # ── 2. Performance comparativa ──
    story.append(P("2. Performance comparativa em testes offline", st['h2']))
    story.append(P(
        "Avaliamos os dois modelos nos lançamentos LF51 (parcial), LF52 e LF53 — período em que "
        "<b>nenhum dos dois</b> havia visto os leads no treino. Total: <b>186 vendas reais matched</b>.",
        st['body']))

    story.append(P("Quanto leads dos top decis convertem acima da média do lançamento", st['h3']))
    rows = [[P('Métrica', st['th_left']), P('Challenger B', st['th']), P('Champion A', st['th'])]]
    perf = [
        ('Lead D10 → converte X% acima da média', '<b>+102%</b>', '+40%'),
        ('Lead D9 → converte X% acima da média',  '<b>+41%</b>',  '+18%'),
        ('Lead D9+D10 (top 20%) → converte X% acima da média', '<b>+72%</b>', '+33%'),
    ]
    for m, b, a in perf:
        rows.append([P(m, st['td_left']), P(b, st['td_bold']), P(a, st['td'])])
    story.append(make_table(rows, [9*cm, 3.5*cm, 3.5*cm], st=st))
    story.append(Spacer(1, 6))
    story.append(P(
        "Quando B classifica um lead como D10, esse grupo converte 102% acima da média do lançamento. "
        "Quando A classifica o mesmo, o grupo converte 40% acima.", st['body']))

    story.append(P("ROAS observado offline (top decis)", st['h3']))
    rows = [[P('Métrica', st['th_left']), P('Challenger B', st['th']), P('Champion A', st['th'])]]
    roas_data = [
        ('ROAS dos top 30% leads (top 3 decis)', '2,29×', '1,84×'),
        ('ROAS dos top 50% leads (top 5 decis)', '2,00×', '1,74×'),
        ('ROAS de toda a base (controle)',       '1,50×', '1,50×'),
    ]
    for m, b, a in roas_data:
        rows.append([P(m, st['td_left']), P(b, st['td']), P(a, st['td'])])
    story.append(make_table(rows, [9*cm, 3.5*cm, 3.5*cm], st=st))
    story.append(Spacer(1, 6))
    story.append(P(
        "ROAS de toda a base é igual (mesmo dataset). A diferença aparece quando filtramos por decis altos.",
        st['body']))


    # ── 3. Validação técnica do pipeline ──
    story.append(P("3. Validação técnica do pipeline", st['h2']))
    story.append(P(
        "A produção hoje roda numa versão antiga do código (commit \"rollback\" de 05/03/2026). "
        "Para servir B em produção, precisamos voltar a usar a versão atual do código.",
        st['body']))
    story.append(P(
        "Pegamos 5.000 leads reais e rodamos o Champion A em ambas as versões do código. Resultados:",
        st['body']))
    rows = [[P('Métrica', st['th_left']), P('Resultado', st['th'])]]
    paridade = [
        ('Score idêntico nas duas versões (diferença <0,001)', '<b>96% dos leads</b>'),
        ('Mesmo decil atribuído pelas duas versões',           '<b>98,3% dos leads</b>'),
        ('Mesma decisão "esse lead recebe sinal premium ao Meta?"', '<b>99,8% dos leads</b>'),
    ]
    for m, r in paridade:
        rows.append([P(m, st['td_left']), P(r, st['td'])])
    story.append(make_table(rows, [11*cm, 5*cm], st=st))
    story.append(Spacer(1, 6))
    story.append(P(
        "Em 100 leads, ~98 receberiam exatamente o mesmo decil em ambas as versões. "
        "Os ~2 restantes ficariam deslocados em ±1 decil. Magnitude pequena, sem impacto material no ROAS agregado.",
        st['body']))

    # ── 4. Como o teste vai funcionar ──
    story.append(P("4. Como o teste vai funcionar", st['h2']))
    diagram_png = make_flow_diagram()
    img = Image(io.BytesIO(diagram_png), width=15.5*cm, height=10.7*cm)
    img.hAlign = 'CENTER'
    story.append(img)
    story.append(Spacer(1, 8))
    story.append(P(
        "Cada modelo emite seu próprio evento ao Meta. Cada campanha é configurada para otimizar "
        "pelo seu evento correspondente. Vendas reais são medidas externamente (via plataformas Hotmart/Guru/Asaas) "
        "— a métrica de ROAS por modelo é calculada por nós, não pelo Meta.", st['body']))

    # ── 5. Investimento ──
    story.append(P("5. Investimento necessário", st['h2']))
    story.append(P(
        "Para concluir com segurança que \"B é melhor que A\", precisamos observar um número mínimo de "
        "vendas atribuídas a cada modelo. Com pouco investimento em B, o sinal não consegue ser distinguido "
        "do ruído da amostra pequena.", st['body']))
    rows = [[P('Cenário', st['th_left']), P('% budget B', st['th']), P('R$ B', st['th']), P('Detecta diferença de…', st['th'])]]
    cenarios = [
        ('Mínimo direcional',          '15%', 'R$ 31k',  'apenas >40% (só sinais grandes)', False),
        ('Conservador',                '25%', 'R$ 51k',  '>30%',                            False),
        ('Moderado (recomendado)',     '35%', 'R$ 72k',  '>25%',                            True),
        ('Equilibrado',                '50%', 'R$ 102k', '>18%',                            False),
    ]
    highlight_idx = None
    for i, (c, p, r, d, h) in enumerate(cenarios):
        rows.append([
            P(f'<b>{c}</b>' if h else c, st['td_bold_left'] if h else st['td_left']),
            P(f'<b>{p}</b>' if h else p, st['td_bold'] if h else st['td']),
            P(f'<b>{r}</b>' if h else r, st['td_bold'] if h else st['td']),
            P(f'<b>{d}</b>' if h else d, st['td_bold'] if h else st['td']),
        ])
        if h: highlight_idx = i + 1
    story.append(make_table(rows, [5.5*cm, 2.5*cm, 2.5*cm, 5.5*cm], highlight_row=highlight_idx, st=st))
    story.append(Spacer(1, 6))
    story.append(P(
        "<b>Recomendação: cenário moderado (R$ 72k em B).</b> Detecta diferenças de ROAS ≥25% — "
        "exatamente o range esperado dado os testes offline. A continua com R$ 133k (65% do orçamento) — "
        "ROAS atual protegido.", st['body']))

    story.append(Spacer(1, 18))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE))
    story.append(Spacer(1, 4))
    story.append(P("Documento técnico-explicativo · Bring Data · 28/04/2026", st['footer']))

    return story


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    st = styles()
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="Briefing Teste A/B DEV20",
        author="Bring Data",
    )
    doc.build(build_story(st))
    print(f"PDF gerado: {OUTPUT}")


if __name__ == '__main__':
    main()
