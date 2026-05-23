"""Base compartilhada dos geradores de PDF Bring Data.

Paleta, estilos, helpers de tabela/callout/rodapé e a função de build.
Qualquer `gerar_pdf_*.py` novo deve importar daqui em vez de recopiar.

──────────────────────────────────────────────────────────────────────────
PADRÃO DE ESPAÇAMENTO (regra do projeto — não recriar o bug do gap enorme)
──────────────────────────────────────────────────────────────────────────
- NÃO usar `PageBreak` gratuito antes de seção/título. Quebra forçada antes
  de cabeçalho deixa o resto da página em branco e gera o "espaçamento
  gigante" entre páginas. O fluxo é contínuo.
- Espaçamento entre blocos vem de `spaceBefore`/`spaceAfter` dos estilos
  (já calibrados aqui), não de `Spacer` grande nem de `PageBreak`.
- `PageBreak` só quando estritamente necessário e justificado (ex.: capa
  separada deliberada). Para evitar que uma tabela quebre feia entre
  páginas, usar `KeepTogether`, nunca `PageBreak` antes dela.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
    Preformatted,
)
from reportlab.lib.colors import HexColor

# Paleta consistente com os demais docs Bring Data
C_BLACK      = HexColor('#1a1a1a')
C_DARK_GRAY  = HexColor('#444444')
C_MID_GRAY   = HexColor('#777777')
C_LIGHT_GRAY = HexColor('#f5f5f5')
C_GREEN      = HexColor('#1d8a3e')
C_CALLOUT_BG = HexColor('#eef4fb')
C_CALLOUT_BD = HexColor('#c9d9ec')
C_WHITE      = HexColor('#ffffff')
C_RULE       = HexColor('#e0e0e0')

CONTENT_WIDTH = 17 * cm  # A4 (21cm) menos margens de 2cm de cada lado


def styles():
    base, bold, ital = 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'
    return {
        'h1':   ParagraphStyle('h1', fontName=bold, fontSize=18, textColor=C_BLACK,
                               leading=22, spaceBefore=6, spaceAfter=4),
        'h2':   ParagraphStyle('h2', fontName=bold, fontSize=13, textColor=C_BLACK,
                               leading=16, spaceBefore=12, spaceAfter=4),
        'h3':   ParagraphStyle('h3', fontName=bold, fontSize=10.5, textColor=C_BLACK,
                               leading=13, spaceBefore=8, spaceAfter=3),
        'body': ParagraphStyle('body', fontName=base, fontSize=9.5, textColor=C_DARK_GRAY,
                               leading=14, spaceAfter=5, alignment=TA_LEFT),
        'li':   ParagraphStyle('li', fontName=base, fontSize=9.5, textColor=C_DARK_GRAY,
                               leading=14, spaceAfter=3, leftIndent=14, bulletIndent=4),
        'callout': ParagraphStyle('callout', fontName=base, fontSize=9, textColor=C_BLACK,
                                  leading=13, spaceAfter=3, leftIndent=10, rightIndent=10),
        'th':   ParagraphStyle('th', fontName=bold, fontSize=8, textColor=C_WHITE,
                               alignment=TA_LEFT, leading=10),
        'td':   ParagraphStyle('td', fontName=base, fontSize=8, textColor=C_DARK_GRAY,
                               alignment=TA_LEFT, leading=11),
        'code': ParagraphStyle('code', fontName='Courier', fontSize=7, textColor=C_BLACK,
                               leading=9),
        'footer': ParagraphStyle('footer', fontName=base, fontSize=7.5, textColor=C_MID_GRAY,
                                 leading=10),
    }


def P(text, style):
    return Paragraph(text, style)


def make_table(header_cells, body_rows, col_widths):
    data = [header_cells] + body_rows
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), C_GREEN),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, C_RULE),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, C_RULE),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ])
    for i in range(2, len(data), 2):
        style.add('BACKGROUND', (0, i), (-1, i), C_LIGHT_GRAY)
    return Table(data, colWidths=col_widths, style=style, hAlign='LEFT', repeatRows=1)


def col_widths(ncols, total=CONTENT_WIDTH):
    """Primeira coluna mais larga (rótulo); resto divide o restante."""
    if ncols == 1:
        return [total]
    w0 = total * (0.30 if ncols >= 4 else 0.34)
    return [w0] + [(total - w0) / (ncols - 1)] * (ncols - 1)


def callout(html, st, width=CONTENT_WIDTH):
    box = Table([[Paragraph(html, st['callout'])]], colWidths=[width])
    box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_CALLOUT_BG),
        ('BOX', (0, 0), (-1, -1), 0.5, C_CALLOUT_BD),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return [box, Spacer(1, 4)]


def code_block(raw, st, width=CONTENT_WIDTH):
    """Bloco de código monoespaçado, fundo cinza, preservando espaços.

    Preformatted renderiza o texto literalmente (não decodifica entidades
    XML), então NÃO escapar — escapar produziria '&amp;'/'&lt;' visíveis.
    """
    box = Table([[Preformatted(raw, st['code'])]], colWidths=[width])
    box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_LIGHT_GRAY),
        ('BOX', (0, 0), (-1, -1), 0.5, C_RULE),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return [box, Spacer(1, 6)]


def rule():
    return HRFlowable(width="100%", thickness=0.5, color=C_RULE,
                      spaceBefore=8, spaceAfter=8)


def make_footer(label):
    """Rodapé com numeração. Use em onFirstPage/onLaterPages."""
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(C_MID_GRAY)
        canvas.drawCentredString(A4[0] / 2, 1.1 * cm, f"{label} · pág {doc.page}")
        canvas.restoreState()
    return _footer


def build_pdf(output_path, story, *, title, footer_label):
    """Constrói o PDF com margens/rodapé padrão. NÃO injeta PageBreak."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title=title,
    )
    ftr = make_footer(footer_label)
    doc.build(story, onFirstPage=ftr, onLaterPages=ftr)
