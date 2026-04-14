"""
Gera PDF: Mudança no Perfil dos Leads — DevClub (P1 → P2 → P3)

Dados hardcoded a partir da investigação de 13/04/2026.
Não requer acesso ao banco — todos os números vêm das queries já executadas.

Saída: V2/propostas_e_apresentacoes/devclub_perfil_leads_p1_p3.pdf
"""

from pathlib import Path
import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, Image, HRFlowable, KeepTogether,
)
from reportlab.lib.colors import HexColor

# ── Caminhos ───────────────────────────────────────────────────────────────────
OUTPUT = (
    Path(__file__).parent.parent
    / "propostas_e_apresentacoes"
    / "devclub_perfil_leads_p1_p3.pdf"
)

# ── Paleta Bring Data ──────────────────────────────────────────────────────────
C_BLACK       = HexColor('#1a1a1a')
C_DARK_GRAY   = HexColor('#444444')
C_MID_GRAY    = HexColor('#777777')
C_LIGHT_GRAY  = HexColor('#f5f5f5')
C_GREEN       = HexColor('#1d8a3e')
C_GREEN_MID   = HexColor('#52a86b')
C_GREEN_LIGHT = HexColor('#e8f5ec')
C_GREEN_PALE  = HexColor('#f4fbf6')
C_WHITE       = HexColor('#ffffff')
C_RULE        = HexColor('#e0e0e0')
C_CALLOUT_BG  = HexColor('#fff8e1')
C_CALLOUT_BD  = HexColor('#f9a825')
C_RED         = HexColor('#e53935')
C_RED_LIGHT   = HexColor('#fdecea')
C_ORANGE      = HexColor('#f57c00')
C_ORANGE_LIGHT= HexColor('#fff3e0')

# ── Dados (hardcoded da investigação) ─────────────────────────────────────────

# P1 — 03/03 a 09/03 (período estável)
P1_DAILY = [
    ('03/03', 42.2),
    ('04/03', 40.8),
    ('05/03', 42.0),
    ('06/03', 44.0),
    ('07/03', 43.8),
    ('08/03', 41.5),
    ('09/03', 42.5),
]

# Virada — 10/03 a 14/03
VIRADA_DAILY = [
    ('10/03', 41.0),
    ('11/03', 41.5),
    ('12/03', 31.8),
    ('13/03', 30.3),
    ('14/03', 28.1),
]

# P2 — 15/03 a 22/03
P2_DAILY = [
    ('15/03', 19.7),
    ('16/03',  5.4),
    ('17/03',  7.3),
    ('18/03',  6.1),
    ('19/03',  6.2),
    ('20/03',  4.2),
    ('21/03',  3.1),
    ('22/03',  1.8),
]

# P3 — características demográficas comparadas
PROFILE_TABLE = [
    ('Tem computador',    88.5, 79.5, -9.0),
    ('Tem cartão de crédito', 43.5, 38.1, -5.4),
    ('Sem renda declarada', 25.1, 30.0, +4.9),
]


# ── Estilos ────────────────────────────────────────────────────────────────────
def styles():
    base = 'Helvetica'
    bold = 'Helvetica-Bold'
    return {
        'title': ParagraphStyle('title', fontName=bold, fontSize=17,
                                textColor=C_BLACK, leading=22, spaceAfter=2),
        'subtitle': ParagraphStyle('subtitle', fontName=base, fontSize=10,
                                   textColor=C_MID_GRAY, leading=14, spaceAfter=14),
        'section': ParagraphStyle('section', fontName=bold, fontSize=10.5,
                                  textColor=C_BLACK, leading=15, spaceBefore=16, spaceAfter=6),
        'body': ParagraphStyle('body', fontName=base, fontSize=9.5,
                               textColor=C_DARK_GRAY, leading=15, spaceAfter=5),
        'body_bold': ParagraphStyle('body_bold', fontName=bold, fontSize=9.5,
                                    textColor=C_DARK_GRAY, leading=15, spaceAfter=5),
        'callout': ParagraphStyle('callout', fontName=bold, fontSize=11,
                                  textColor=C_BLACK, leading=17, alignment=TA_CENTER),
        'footnote': ParagraphStyle('footnote', fontName=base, fontSize=7.5,
                                   textColor=C_MID_GRAY, leading=11),
        'table_hdr': ParagraphStyle('table_hdr', fontName=bold, fontSize=8.5,
                                    textColor=C_WHITE, alignment=TA_CENTER),
        'table_cell': ParagraphStyle('table_cell', fontName=base, fontSize=8.5,
                                     textColor=C_DARK_GRAY, alignment=TA_CENTER),
        'table_cell_bold': ParagraphStyle('table_cell_bold', fontName=bold, fontSize=8.5,
                                          textColor=C_DARK_GRAY, alignment=TA_CENTER),
        'table_label': ParagraphStyle('table_label', fontName=bold, fontSize=8.5,
                                      textColor=C_DARK_GRAY, alignment=TA_LEFT),
    }


# ── Gráfico de linha — D10% ao longo do tempo ─────────────────────────────────
def make_d10_chart() -> bytes:
    all_days  = [d for d, _ in P1_DAILY + VIRADA_DAILY + P2_DAILY]
    all_vals  = [v for _, v in P1_DAILY + VIRADA_DAILY + P2_DAILY]
    n_p1      = len(P1_DAILY)
    n_virada  = len(VIRADA_DAILY)

    x = list(range(len(all_days)))

    fig, ax = plt.subplots(figsize=(10.5, 3.6))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    # Regiões de fundo
    ax.axvspan(-0.5, n_p1 - 0.5,
               color='#e8f5ec', alpha=0.55, zorder=0)
    ax.axvspan(n_p1 - 0.5, n_p1 + n_virada - 0.5,
               color='#fff3e0', alpha=0.55, zorder=0)
    ax.axvspan(n_p1 + n_virada - 0.5, len(all_days) - 0.5,
               color='#fdecea', alpha=0.45, zorder=0)

    # Labels de região
    ax.text((n_p1 - 1) / 2, 46.5, 'P1', ha='center', va='center',
            fontsize=8, color='#1d8a3e', fontweight='bold')
    ax.text(n_p1 + (n_virada - 1) / 2, 46.5, 'Virada', ha='center', va='center',
            fontsize=8, color='#f57c00', fontweight='bold')
    ax.text(n_p1 + n_virada + (len(P2_DAILY) - 1) / 2, 46.5, 'P2', ha='center', va='center',
            fontsize=8, color='#e53935', fontweight='bold')

    # Linha principal
    ax.plot(x, all_vals, color='#1a1a1a', linewidth=1.8, zorder=4)

    # Pontos coloridos por período
    colors_per_point = (
        ['#1d8a3e'] * n_p1 +
        ['#f57c00'] * n_virada +
        ['#e53935'] * len(P2_DAILY)
    )
    for xi, yi, ci in zip(x, all_vals, colors_per_point):
        ax.scatter(xi, yi, color=ci, s=36, zorder=5)

    # Rótulo na queda de 12/03
    idx_12 = n_p1 + 2  # terceiro dia da virada
    ax.annotate(
        '12/03 − 10pp em\num único dia',
        xy=(idx_12, P2_DAILY[0][1] + 1.5),
        xytext=(idx_12 + 0.5, 36),
        fontsize=7.5, color='#e53935',
        arrowprops=dict(arrowstyle='->', color='#e53935', lw=0.8),
    )

    ax.set_xticks(x)
    ax.set_xticklabels(all_days, fontsize=8, color='#444444', rotation=45, ha='right')
    ax.set_ylabel('D10 (%)', fontsize=8.5, color='#444444')
    ax.yaxis.set_tick_params(labelsize=8, labelcolor='#777777')
    ax.set_ylim(0, 52)
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.spines['bottom'].set_color('#e0e0e0')
    ax.yaxis.grid(True, color='#eeeeee', linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)

    # Legenda
    legend_handles = [
        mpatches.Patch(color='#1d8a3e', alpha=0.6, label='P1 — estável (42–44%)'),
        mpatches.Patch(color='#f57c00', alpha=0.6, label='Virada — evento LQ ativado'),
        mpatches.Patch(color='#e53935', alpha=0.5, label='P2 — colapso'),
    ]
    ax.legend(handles=legend_handles, loc='lower left', fontsize=7.5, frameon=False)

    plt.tight_layout(pad=0.8)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── Tabela diária (D10% por data) ──────────────────────────────────────────────
def make_daily_table(rows_data: list, st: dict,
                     highlight_rows: list = None,
                     highlight_color=None) -> Table:
    """rows_data: list of (data, pct). highlight_rows: 0-indexed row numbers to highlight."""
    header = [
        Paragraph('Data', st['table_hdr']),
        Paragraph('D10 (%)', st['table_hdr']),
    ]
    rows = [header]
    for d, v in rows_data:
        rows.append([
            Paragraph(d, st['table_cell']),
            Paragraph(f'{v:.1f}%', st['table_cell_bold']),
        ])

    style_cmds = [
        ('BACKGROUND',    (0, 0), (-1, 0), C_BLACK),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_LIGHT_GRAY]),
        ('GRID',          (0, 0), (-1, -1), 0.3, C_RULE),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]
    if highlight_rows and highlight_color:
        for ri in highlight_rows:
            style_cmds.append(('BACKGROUND', (0, ri + 1), (-1, ri + 1), highlight_color))

    t = Table(rows, colWidths=[3.5 * cm, 3.0 * cm], repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Tabela de perfil demográfico P1 vs P3 ─────────────────────────────────────
def make_profile_table(st: dict) -> Table:
    header = [
        Paragraph('Característica', st['table_hdr']),
        Paragraph('P1', st['table_hdr']),
        Paragraph('P3', st['table_hdr']),
        Paragraph('Diferença', st['table_hdr']),
    ]
    rows = [header]

    for label, p1_val, p3_val, diff in PROFILE_TABLE:
        sign = '+' if diff > 0 else ''
        diff_color = '#e53935' if diff < 0 else '#e53935'  # queda em capacidade = vermelho
        # Para "sem renda" o aumento é negativo para o negócio — manter vermelho
        rows.append([
            Paragraph(label, st['table_label']),
            Paragraph(f'{p1_val:.1f}%', st['table_cell']),
            Paragraph(f'{p3_val:.1f}%', st['table_cell']),
            Paragraph(
                f'<font color="{diff_color}"><b>{sign}{diff:.1f} pp</b></font>',
                st['table_cell_bold'],
            ),
        ])

    style_cmds = [
        ('BACKGROUND',    (0, 0), (-1, 0), C_BLACK),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_LIGHT_GRAY]),
        ('GRID',          (0, 0), (-1, -1), 0.3, C_RULE),
        ('TOPPADDING',    (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]

    col_widths = [6.5 * cm, 2.8 * cm, 2.8 * cm, 3.5 * cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Caixa de destaque (callout) ────────────────────────────────────────────────
def make_callout(text: str, st: dict,
                 bg=None, border=None) -> Table:
    bg     = bg     or C_CALLOUT_BG
    border = border or C_CALLOUT_BD
    cell = Table(
        [[Paragraph(text, st['callout'])]],
        colWidths=[17.6 * cm],
    )
    cell.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), bg),
        ('LINEABOVE',     (0, 0), (-1,  0), 2, border),
        ('LINEBELOW',     (0,-1), (-1, -1), 2, border),
        ('TOPPADDING',    (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
    ]))
    return cell


# ── Tabelas diárias lado a lado ────────────────────────────────────────────────
def make_three_tables_side_by_side(st: dict) -> Table:
    """P1 | Virada | P2 dispostos em 3 colunas."""

    def inner_table(rows_data, title_text, title_bg, highlight_idx=None, hl_color=None):
        # Título da sub-tabela
        title_row = [
            Paragraph(title_text, ParagraphStyle(
                'col_title', fontName='Helvetica-Bold', fontSize=8.5,
                textColor=C_WHITE, alignment=TA_CENTER,
            ))
        ]
        data_rows = [title_row]
        # Sub-header
        data_rows.append([Paragraph('<b>Data &nbsp; D10%</b>', ParagraphStyle(
            'sub_hdr', fontName='Helvetica-Bold', fontSize=7.5,
            textColor=C_MID_GRAY, alignment=TA_CENTER,
        ))])
        for i, (d, v) in enumerate(rows_data):
            data_rows.append([Paragraph(
                f'{d}  &nbsp; <b>{v:.1f}%</b>',
                ParagraphStyle('cell_inner', fontName='Helvetica', fontSize=8.5,
                               textColor=C_DARK_GRAY, alignment=TA_CENTER),
            )])

        cmds = [
            ('BACKGROUND',    (0, 0), (-1, 0), title_bg),
            ('ROWBACKGROUNDS', (0, 2), (-1, -1), [C_WHITE, C_LIGHT_GRAY]),
            ('BACKGROUND',    (0, 1), (-1, 1), HexColor('#eeeeee')),
            ('GRID',          (0, 0), (-1, -1), 0.3, C_RULE),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ]
        if highlight_idx is not None and hl_color is not None:
            # +2 because title + subheader rows come first
            cmds.append(('BACKGROUND', (0, highlight_idx + 2), (-1, highlight_idx + 2), hl_color))

        t = Table(data_rows, colWidths=[5.4 * cm])
        t.setStyle(TableStyle(cmds))
        return t

    t_p1     = inner_table(P1_DAILY,     'P1 — estável',   C_GREEN)
    t_virada = inner_table(VIRADA_DAILY, 'Virada (10–14/03)', C_ORANGE,
                           highlight_idx=2, hl_color=C_ORANGE_LIGHT)
    t_p2     = inner_table(P2_DAILY,     'P2 — colapso',   C_RED)

    outer = Table(
        [[t_p1, t_virada, t_p2]],
        colWidths=[5.7 * cm, 5.7 * cm, 5.7 * cm],
        hAlign='LEFT',
    )
    outer.setStyle(TableStyle([
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    return outer


# ── Tabela de criativos P1 vs P3 ──────────────────────────────────────────────
# Dados: Railway query sobre decil por criativo, ≥80 leads, por período
CREATIVES_P1 = [
    # (ad_code, leads, vol_pct, d10_pct)
    ('AD0150', 16222, 55.4, 42.3),
    ('AD0156',  3585, 12.3, 48.0),
    ('AD0160',  3001, 10.3, 47.0),
    ('AD0141',  2349,  8.0, 39.8),
    ('AD0027',  1956,  6.7, 12.8),
    ('AD0170',   154,  0.5, 55.8),
    ('AD0172',   110,  0.4, 51.8),
    ('AD0157',   173,  0.6, 48.6),
]
CREATIVES_P3 = [
    ('AD0141',  6213, 22.7, 18.7),
    ('AD0150',  8664, 31.7, 34.7),
    ('AD0160',  4343, 15.9, 27.7),
    ('AD0156',  2192,  8.0, 40.2),
    ('AD0138',  1401,  5.1, 43.7),
    ('AD0027',  1561,  5.7, 19.7),
    ('AD0151',   379,  1.4, 52.8),
    ('AD0152',   451,  1.6, 47.0),
]


def make_creatives_table(st: dict) -> Table:
    # Construir lookup P3 por ad_code
    p3_map = {r[0]: r for r in CREATIVES_P3}

    header = [
        Paragraph('Criativo', st['table_hdr']),
        Paragraph('Vol% P1', st['table_hdr']),
        Paragraph('D10% P1', st['table_hdr']),
        Paragraph('Vol% P3', st['table_hdr']),
        Paragraph('D10% P3', st['table_hdr']),
        Paragraph('Δ D10', st['table_hdr']),
    ]
    rows = [header]
    style_cmds = [
        ('BACKGROUND',    (0, 0), (-1, 0), C_BLACK),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_LIGHT_GRAY]),
        ('GRID',          (0, 0), (-1, -1), 0.3, C_RULE),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]

    # Ordenar: criativos em P1 primeiro (por vol%), depois exclusivos de P3
    shown = set()
    sorted_rows = sorted(CREATIVES_P1, key=lambda x: -x[1])

    # Adicionar criativos exclusivos de P3 não presentes em P1
    p1_codes = {r[0] for r in CREATIVES_P1}
    for r in sorted(CREATIVES_P3, key=lambda x: -x[1]):
        if r[0] not in p1_codes:
            sorted_rows.append(('*' + r[0], 0, 0.0, 0.0))  # marcador para P3-only

    for i, (code, leads_p1, vol_p1, d10_p1) in enumerate(sorted_rows, start=1):
        p3_only = code.startswith('*')
        clean_code = code.lstrip('*')
        p3 = p3_map.get(clean_code)
        vol_p3  = p3[2] if p3 else None
        d10_p3  = p3[3] if p3 else None

        if p3_only:
            # Criativo só em P3
            vol_p1_str  = Paragraph('—', st['table_cell'])
            d10_p1_str  = Paragraph('—', st['table_cell'])
            vol_p3_str  = Paragraph(f'{vol_p3:.1f}%', st['table_cell'])
            d10_p3_str  = Paragraph(f'<b>{d10_p3:.1f}%</b>', st['table_cell_bold'])
            delta_str   = Paragraph('novo', st['table_cell'])
            bg = C_GREEN_PALE
        elif p3 is None:
            # Só em P1 — saiu do mix
            vol_p1_str  = Paragraph(f'{vol_p1:.1f}%', st['table_cell'])
            d10_p1_str  = Paragraph(f'{d10_p1:.1f}%', st['table_cell'])
            vol_p3_str  = Paragraph('—', st['table_cell'])
            d10_p3_str  = Paragraph('—', st['table_cell'])
            delta_str   = Paragraph('saiu', st['table_cell'])
            bg = HexColor('#fafafa')
        else:
            delta = d10_p3 - d10_p1
            sign  = '+' if delta >= 0 else ''
            color = '#1d8a3e' if delta >= 0 else '#e53935'
            vol_p1_str  = Paragraph(f'{vol_p1:.1f}%', st['table_cell'])
            d10_p1_str  = Paragraph(f'{d10_p1:.1f}%', st['table_cell'])
            vol_p3_str  = Paragraph(f'{vol_p3:.1f}%', st['table_cell'])
            d10_p3_str  = Paragraph(f'<b>{d10_p3:.1f}%</b>', st['table_cell_bold'])
            delta_str   = Paragraph(
                f'<font color="{color}"><b>{sign}{delta:.1f}pp</b></font>',
                st['table_cell_bold'],
            )
            bg = C_RED_LIGHT if delta <= -10 else (C_ORANGE_LIGHT if delta < 0 else C_GREEN_PALE)

        rows.append([Paragraph(f'<b>{clean_code}</b>', st['table_label']),
                     vol_p1_str, d10_p1_str, vol_p3_str, d10_p3_str, delta_str])
        style_cmds.append(('BACKGROUND', (0, i), (-1, i), bg))

    col_widths = [2.8*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.2*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Montagem do PDF ────────────────────────────────────────────────────────────
def build_pdf():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm,
        topMargin=1.8 * cm,  bottomMargin=1.8 * cm,
    )

    st   = styles()
    elms = []

    # ── Cabeçalho ──────────────────────────────────────────────────────────────
    elms.append(Paragraph('Mudança no Perfil dos Leads', st['title']))
    elms.append(Paragraph(
        'DevClub &nbsp;·&nbsp; P1 → P2 → P3 &nbsp;·&nbsp; '
        'fev/2026 – abr/2026 &nbsp;·&nbsp; 61 mil leads analisados',
        st['subtitle'],
    ))
    elms.append(HRFlowable(width='100%', thickness=1, color=C_RULE, spaceAfter=14))

    # ── Gráfico de linha ───────────────────────────────────────────────────────
    elms.append(Paragraph('D10% ao longo do tempo', st['section']))
    elms.append(Paragraph(
        'Proporção diária de leads classificados no decil 10 (maior propensão de compra) '
        'durante as três fases. A queda de 12/03 ocorreu sem nenhuma alteração de código ou modelo.',
        st['body'],
    ))
    elms.append(Spacer(1, 6))
    chart_bytes = make_d10_chart()
    chart_img   = Image(io.BytesIO(chart_bytes), width=17.0 * cm, height=5.8 * cm)
    elms.append(chart_img)
    elms.append(Spacer(1, 12))

    # ── A lógica por trás da mudança ───────────────────────────────────────────
    elms.append(Paragraph('A lógica por trás da mudança', st['section']))
    elms.append(Paragraph(
        'O evento LQHQ (<i>LeadQualifiedHighQuality</i>) enviava sinal ao Meta apenas para leads '
        'D9–D10 — os de maior propensão. A estratégia funcionava bem para atrair leads '
        'qualificados, mas trazia um risco estrutural: o Meta aprende a partir dos eventos '
        'que recebe. Com LQHQ exclusivo, o algoritmo passava a entregar para um público '
        'progressivamente mais estreito — e o modelo, retreinado nesses dados, '
        'potencialmente reforçaria essa concentração.',
        st['body'],
    ))
    elms.append(Paragraph(
        'A migração para LQ (<i>LeadQualified</i>) com valor proporcional por decil buscava '
        'corrigir isso: em vez de um sinal binário (qualificado / não qualificado), o Meta '
        'receberia um sinal econômico contínuo — "este lead vale R$\u202f87, este vale R$\u202f32, '
        'este vale R$\u202f3" — permitindo otimizar ROAS diretamente em vez de apenas filtrar '
        'por intenção declarada.',
        st['body'],
    ))
    elms.append(Paragraph(
        'O efeito colateral foi que, ao receber sinal de todos os decis, o Meta reconfigurou '
        'sua busca para um público mais amplo, priorizando volume em detrimento do perfil.',
        st['body'],
    ))
    elms.append(Spacer(1, 10))

    # ── Tabelas diárias ────────────────────────────────────────────────────────
    elms.append(Paragraph('Evolução diária por período', st['section']))
    elms.append(Spacer(1, 4))
    elms.append(make_three_tables_side_by_side(st))
    elms.append(Spacer(1, 6))
    elms.append(Paragraph(
        'P1: 18/02–09/03 &nbsp;·&nbsp; Virada: 10–14/03 &nbsp;·&nbsp; '
        'P2: 15–25/03 &nbsp;·&nbsp; P3: 26/03 em diante',
        st['footnote'],
    ))
    elms.append(Spacer(1, 14))

    # ── Callout — causa raiz ───────────────────────────────────────────────────
    elms.append(make_callout(
        'A mudança de evento foi tecnicamente fundamentada — mas o Meta interpretou o sinal '
        'mais amplo como uma instrução para buscar um público mais diverso, '
        'e o D10% refletiu isso imediatamente.',
        st,
    ))
    elms.append(Spacer(1, 14))

    # ── Perfil demográfico P1 vs P3 ────────────────────────────────────────────
    elms.append(HRFlowable(width='100%', thickness=0.5, color=C_RULE, spaceAfter=12))
    elms.append(Paragraph('Perfil demográfico: P1 vs P3', st['section']))
    elms.append(Paragraph(
        'Comparando os leads que chegaram em P1 com os de P3 — 61 mil leads, '
        'todas as diferenças estatisticamente significativas:',
        st['body'],
    ))
    elms.append(Spacer(1, 6))
    elms.append(make_profile_table(st))
    elms.append(Spacer(1, 8))
    elms.append(Spacer(1, 14))

    # ── O que isso significa ───────────────────────────────────────────────────
    elms.append(HRFlowable(width='100%', thickness=0.5, color=C_RULE, spaceAfter=12))
    elms.append(Paragraph('O que isso significa', st['section']))

    elms.append(Paragraph(
        '<b>Código e modelo.</b> '
        'O rollback corrigiu um bug de encoding que afetava a feature '
        '<i>Medium_Linguagem_programacao</i> — a 5ª variável mais importante do modelo '
        '(5,31% de peso). O bug zerrava silenciosamente essa coluna para todos os leads, '
        'reduzindo a precisão do modelo especificamente nos segmentos de campanha de '
        'linguagem de programação. O impacto foi localizado: os 94,69% restantes do peso '
        'do modelo operavam normalmente. Após a correção, o D10% estabilizou em ~30% — '
        'confirmando que o problema principal não é técnico, mas de audiência.',
        st['body'],
    ))

    elms.append(Paragraph(
        '<b>Sinal de otimização.</b> '
        'Para voltar ao patamar de P1, o Meta precisa reaprender a buscar o perfil correto. '
        'O sinal que está sendo enviado agora é idêntico ao de P1 — o modelo correto, '
        'pontuando corretamente. Com isso, podemos esperar que o Meta vá convergindo '
        'gradualmente, buscando cada vez mais leads com o perfil de P1 e elevando o D10% '
        'ao longo do tempo.',
        st['body'],
    ))

    elms.append(Paragraph(
        'O reset de pixel pode ser um fator determinante nesse processo, '
        'limpando o aprendizado contaminado do período anterior e acelerando a convergência.',
        st['body'],
    ))

    elms.append(Spacer(1, 14))

    # ── Mix de criativos P1 vs P3 ──────────────────────────────────────────────
    elms.append(HRFlowable(width='100%', thickness=0.5, color=C_RULE, spaceAfter=12))
    elms.append(Paragraph('Mix de criativos: P1 vs P3', st['section']))
    elms.append(Paragraph(
        'A análise por criativo revela um padrão consistente com a degradação de audiência. '
        'Os mesmos criativos que performavam bem em P1 apresentam queda expressiva de D10% '
        'em P3 — não porque os criativos mudaram, mas porque o Meta passou a entregá-los '
        'para um público diferente.',
        st['body'],
    ))
    elms.append(Spacer(1, 6))
    elms.append(make_creatives_table(st))
    elms.append(Spacer(1, 8))
    elms.append(Paragraph(
        'Os dois movimentos mais relevantes: AD0141 triplicou sua participação de volume '
        '(8% → 23%) enquanto o D10% colapsou de 40% para 19%; AD0160 manteve volume alto '
        'mas viu o D10% cair de 47% para 28%. Os criativos de nicho que lideravam em P1 '
        '(AD0170, AD0172, AD0157 — todos acima de 48% D10) saíram completamente do mix ativo.',
        st['body'],
    ))
    elms.append(Paragraph(
        'Em P3 surgem dois criativos com performance alta — AD0151 (53% D10) e AD0152 '
        '(47% D10) — mas com menos de 2% de volume cada. Concentrar verba nesses criativos '
        'combinado com o reset do pixel são a melhor alavanca disponível: o reset limpa o '
        'aprendizado contaminado e os criativos corretos entregam o sinal certo desde o '
        'primeiro dia do novo ciclo.',
        st['body'],
    ))

    elms.append(Spacer(1, 14))

    # ── Callout final ──────────────────────────────────────────────────────────
    elms.append(make_callout(
        'O código e o modelo estão corretos. O D10% de ~30% observado é o resultado esperado '
        'para o perfil de lead atual — o modelo está funcionando.',
        st,
        bg=C_GREEN_LIGHT,
        border=C_GREEN,
    ))

    elms.append(Spacer(1, 16))
    elms.append(HRFlowable(width='100%', thickness=0.5, color=C_RULE, spaceAfter=8))

    # ── Nota metodológica ──────────────────────────────────────────────────────
    elms.append(Paragraph(
        '<b>Fonte dos dados.</b> '
        'Railway PostgreSQL — tabela <i>Lead</i>, campo <i>decil</i>. '
        'Análise de 61 mil leads cobrindo P1 (18/02–09/03) e P3 (26/03–13/04/2026). '
        'Diferenças demográficas verificadas com teste qui-quadrado (p &lt; 0,001 em todos os campos). '
        'D10% diário calculado sobre leads pontuados no dia, excluindo dias com menos de 100 leads.',
        st['footnote'],
    ))

    doc.build(elms)
    print(f'\nPDF gerado: {OUTPUT}')


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    build_pdf()
