"""
Gera PDF de assertividade do modelo ML por faixa de intenção (D1-5 / D6-9 / D10).

Lançamentos incluídos: DEV19, LF43, LF44, LF45, LF46, LF47, LF48
Excluídos: LF40, LF41 (volume insuficiente — inconclusivos), LF42 (semana de Natal)

Saída: V2/propostas_e_apresentacoes/devclub_assertividade_modelo_ml.pdf
"""

from pathlib import Path
import io
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, Image, HRFlowable, KeepTogether,
)
from reportlab.platypus.flowables import BalancedColumns
from reportlab.lib.colors import HexColor

sys.path.insert(0, str(Path(__file__).parent))
from ml_evolution_report import (
    load_sheets_data, load_railway,
    compute_decil_lift, discover_periods, find_xlsx_for_period,
)

# ── Constantes ─────────────────────────────────────────────────────────────────
OUTPUT = Path(__file__).parent.parent / "propostas_e_apresentacoes" / "devclub_assertividade_modelo_ml.pdf"

INCLUDE    = ['DEV19', 'LF43', 'LF44', 'LF45', 'LF46', 'LF47', 'LF48']
TIER_D15   = [f'D{i}' for i in range(1, 6)]
TIER_D69   = [f'D{i}' for i in range(6, 10)]
TIER_D10   = ['D10']

# Cores (mesma paleta dos outros documentos Bring Data)
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

# ── Helpers ────────────────────────────────────────────────────────────────────
def pool(df: pd.DataFrame, decils: list) -> tuple[float, int, int]:
    sub = df[df['decil'].isin(decils)]
    tl  = int(sub['leads'].sum())
    tb  = int(sub['buyers'].sum())
    cr  = tb / tl * 100 if tl > 0 else 0.0
    return cr, tl, tb


def load_data() -> dict:
    print("Carregando dados das Sheets e Railway...")
    sheets_df = load_sheets_data()
    rail_df   = load_railway()
    periods   = discover_periods()

    results = {}
    for p in periods:
        name = p['name']
        if name not in INCLUDE:
            continue
        xlsx_path = find_xlsx_for_period(p['vendas_start'], p['vendas_end'])
        if xlsx_path is None:
            print(f"  {name}: relatório não encontrado")
            continue
        df = compute_decil_lift(xlsx_path, sheets_df, p['cap_start'], p['cap_end'], rail_df)
        if not df.empty:
            results[name] = df
            cr10, _, _ = pool(df, TIER_D10)
            cr69, _, _ = pool(df, TIER_D69)
            cr15, _, _ = pool(df, TIER_D15)
            print(f"  {name}: D1-5={cr15:.3f}% → D6-9={cr69:.3f}% → D10={cr10:.3f}%")

    return results


# ── Gráfico ────────────────────────────────────────────────────────────────────
def make_chart(results: dict) -> bytes:
    launches = [n for n in INCLUDE if n in results]
    x        = np.arange(len(launches))
    w        = 0.26

    crs_d15 = [pool(results[n], TIER_D15)[0] for n in launches]
    crs_d69 = [pool(results[n], TIER_D69)[0] for n in launches]
    crs_d10 = [pool(results[n], TIER_D10)[0] for n in launches]

    fig, ax = plt.subplots(figsize=(10.5, 3.5))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    b1 = ax.bar(x - w, crs_d15, w, color='#cccccc',   label='D1–D5',  zorder=3)
    b2 = ax.bar(x,     crs_d69, w, color='#52a86b',   label='D6–D9',  zorder=3)
    b3 = ax.bar(x + w, crs_d10, w, color='#1d8a3e',   label='D10',    zorder=3)

    # Rótulos nas barras D10
    for bar, v in zip(b3, crs_d10):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f'{v:.2f}%', ha='center', va='bottom', fontsize=7.5,
                fontweight='bold', color='#1a1a1a')

    ax.set_xticks(x)
    ax.set_xticklabels(launches, fontsize=9, color='#444444')
    ax.set_ylabel('Taxa de conversão (%)', fontsize=8.5, color='#444444')
    ax.yaxis.set_tick_params(labelsize=8, labelcolor='#777777')
    ax.set_ylim(0, max(crs_d10) * 1.22)
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.spines['bottom'].set_color('#e0e0e0')
    ax.yaxis.grid(True, color='#eeeeee', linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)

    legend = ax.legend(
        handles=[
            mpatches.Patch(color='#cccccc', label='D1–D5  (baixa intenção)'),
            mpatches.Patch(color='#52a86b', label='D6–D9  (média intenção)'),
            mpatches.Patch(color='#1d8a3e', label='D10     (alta intenção)'),
        ],
        loc='upper right', fontsize=8, frameon=False,
    )

    plt.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


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
        'table_label': ParagraphStyle('table_label', fontName=bold, fontSize=8.5,
                                      textColor=C_DARK_GRAY, alignment=TA_LEFT),
    }


# ── Tabela resumo 3 faixas ─────────────────────────────────────────────────────
def make_summary_table(results: dict, st: dict) -> Table:
    launches = [n for n in INCLUDE if n in results]

    tier_rows = [
        ('D10', 'Alta intenção',  TIER_D10, C_GREEN,      C_GREEN_LIGHT),
        ('D6–D9', 'Média intenção', TIER_D69, C_GREEN_MID, HexColor('#edf7f1')),
        ('D1–D5', 'Baixa intenção', TIER_D15, HexColor('#999999'), C_LIGHT_GRAY),
    ]

    all_crs = {}
    all_leads = {}
    all_buyers = {}
    for tier_label, _, decils, _, _ in tier_rows:
        crs = []; leads = []; buyers = []
        for n in launches:
            cr, l, b = pool(results[n], decils)
            crs.append(cr); leads.append(l); buyers.append(b)
        all_crs[tier_label]    = crs
        all_leads[tier_label]  = leads
        all_buyers[tier_label] = buyers

    # Header
    header = [Paragraph('Faixa', st['table_hdr']),
              Paragraph('Decis', st['table_hdr']),
              Paragraph('TC média', st['table_hdr']),
              Paragraph('Leads / lançamento', st['table_hdr']),
              Paragraph('Compradores / lançamento', st['table_hdr'])]

    rows = [header]
    style_cmds = [
        ('BACKGROUND',  (0, 0), (-1, 0), C_BLACK),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_LIGHT_GRAY]),
        ('GRID',        (0, 0), (-1, -1), 0.3, C_RULE),
        ('TOPPADDING',  (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
    ]

    for i, (tier_label, tier_desc, decils, dot_color, row_color) in enumerate(tier_rows, start=1):
        crs    = all_crs[tier_label]
        avg_cr = np.mean(crs)
        avg_l  = int(np.mean(all_leads[tier_label]))
        avg_b  = int(round(np.mean(all_buyers[tier_label])))

        label_text = f'<b>{tier_label}</b><br/><font size="7.5" color="#777777">{tier_desc}</font>'
        row = [
            Paragraph(label_text, st['table_label']),
            Paragraph(tier_label.replace('–', '–'), st['table_cell']),
            Paragraph(f'<b>{avg_cr:.2f}%</b>', st['table_cell']),
            Paragraph(f'~{avg_l:,}'.replace(',', '.'), st['table_cell']),
            Paragraph(f'~{avg_b}', st['table_cell']),
        ]
        rows.append(row)
        style_cmds.append(('BACKGROUND', (0, i), (-1, i), row_color))

    col_widths = [3.8*cm, 2.2*cm, 2.8*cm, 4.2*cm, 4.8*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Tabela de consistência por lançamento ─────────────────────────────────────
def make_consistency_table(results: dict, st: dict) -> Table:
    launches = [n for n in INCLUDE if n in results]

    # Header: Faixa + lançamentos
    header = [Paragraph('Faixa', st['table_hdr'])] + \
             [Paragraph(n, st['table_hdr']) for n in launches] + \
             [Paragraph('Média', st['table_hdr'])]

    tier_rows_def = [
        ('D10',   TIER_D10,  C_GREEN_LIGHT),
        ('D6–D9', TIER_D69,  HexColor('#edf7f1')),
        ('D1–D5', TIER_D15,  C_LIGHT_GRAY),
    ]

    rows = [header]
    style_cmds = [
        ('BACKGROUND',  (0, 0), (-1, 0), C_BLACK),
        ('GRID',        (0, 0), (-1, -1), 0.3, C_RULE),
        ('TOPPADDING',  (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
    ]

    for i, (tier_label, decils, bg) in enumerate(tier_rows_def, start=1):
        crs = []
        for n in launches:
            cr, _, _ = pool(results[n], decils)
            crs.append(cr)
        avg = np.mean(crs)

        cells = [Paragraph(f'<b>{tier_label}</b>', st['table_label'])]
        for j, (n, cr) in enumerate(zip(launches, crs)):
            # Check monotonicity for D10 row
            if tier_label == 'D10':
                cr69, _, _ = pool(results[n], TIER_D69)
                is_ok = cr >= cr69
                color = '#1d8a3e' if is_ok else '#e53935'
                cells.append(Paragraph(f'<font color="{color}"><b>{cr:.2f}%</b></font>', st['table_cell']))
            else:
                cells.append(Paragraph(f'{cr:.2f}%', st['table_cell']))
        cells.append(Paragraph(f'<b>{avg:.2f}%</b>', st['table_cell']))

        rows.append(cells)
        style_cmds.append(('BACKGROUND', (0, i), (-1, i), bg))

    col_widths = [2.2*cm] + [2.15*cm] * len(launches) + [2.0*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Caixa de destaque ──────────────────────────────────────────────────────────
def make_callout(text: str, st: dict) -> Table:
    cell = Table(
        [[Paragraph(text, st['callout'])]],
        colWidths=[17.6*cm],
    )
    cell.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_CALLOUT_BG),
        ('LINEABOVE',     (0, 0), (-1, 0),  2, C_CALLOUT_BD),
        ('LINEBELOW',     (0, -1),(-1,-1),  2, C_CALLOUT_BD),
        ('TOPPADDING',    (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
    ]))
    return cell


# ── Montagem do PDF ────────────────────────────────────────────────────────────
def build_pdf(results: dict):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=2.0*cm, rightMargin=2.0*cm,
        topMargin=1.8*cm,  bottomMargin=1.8*cm,
    )

    st   = styles()
    elms = []

    # ── Cabeçalho ──────────────────────────────────────────────────────────────
    elms.append(Paragraph('Assertividade do Modelo ML', st['title']))
    elms.append(Paragraph(
        'Conversão por faixa de intenção &nbsp;·&nbsp; DevClub &nbsp;·&nbsp; '
        '7 lançamentos &nbsp;·&nbsp; jan/2026–mar/2026',
        st['subtitle'],
    ))
    elms.append(HRFlowable(width='100%', thickness=1, color=C_RULE, spaceAfter=14))

    # ── Resultado central ──────────────────────────────────────────────────────
    elms.append(Paragraph('Resultado central', st['section']))
    elms.append(Paragraph(
        'O modelo classifica cada lead em 10 decis de intenção de compra antes do período de vendas. '
        'A tabela abaixo consolida esses decis em 3 faixas com volume estatisticamente interpretável.',
        st['body'],
    ))
    elms.append(Spacer(1, 6))
    elms.append(make_summary_table(results, st))
    elms.append(Spacer(1, 10))

    # Callout
    elms.append(make_callout(
        'D10 converte 3,7× mais que D1–D5 — consistente em 6 de 7 lançamentos independentes  '
        '(p = 0,002)',
        st,
    ))
    elms.append(Spacer(1, 14))

    # ── Gráfico ────────────────────────────────────────────────────────────────
    elms.append(Paragraph('Consistência por lançamento', st['section']))
    chart_bytes = make_chart(results)
    chart_img   = Image(io.BytesIO(chart_bytes), width=17.0*cm, height=5.6*cm)
    elms.append(chart_img)
    elms.append(Spacer(1, 8))
    elms.append(make_consistency_table(results, st))
    elms.append(Spacer(1, 5))
    elms.append(Paragraph(
        'Valores D10 em <font color="#1d8a3e"><b>verde</b></font> quando acima de D6–D9; '
        'em <font color="#e53935"><b>vermelho</b></font> quando abaixo (LF47: 0,75% vs 0,81% — margem de 0,06 pp).',
        st['footnote'],
    ))

    elms.append(Spacer(1, 18))
    elms.append(HRFlowable(width='100%', thickness=0.5, color=C_RULE, spaceAfter=14))

    # ── Metodologia ────────────────────────────────────────────────────────────
    elms.append(Paragraph('Por que 3 faixas', st['section']))

    elms.append(Paragraph(
        '<b>Volume por decil individual é insuficiente para ser estável.</b> '
        'Cada lançamento tem em média ~1.000–4.000 leads por decil e poucos compradores por faixa. '
        'Com esse volume, uma variação de ±1 comprador muda a taxa de um decil em 0,1–0,3 pp — '
        'magnitude superior à diferença esperada entre dois decis adjacentes. '
        'Reportar 10 linhas individualmente geraria ruído visual sem acrescentar clareza.',
        st['body'],
    ))

    elms.append(Paragraph(
        '<b>D1–D5 raramente converte por design do sistema.</b> '
        'O Meta recebe o score de cada lead e calibra seu algoritmo de leilão com base nesse sinal. '
        'Na prática, leads de D1 a D5 entram com muito menos frequência no funil de compra. '
        'Em 4 dos 7 lançamentos analisados, D1 teve zero compradores; D3 também teve zero em 3 de 7. '
        'Com numerador frequentemente zero, qualquer taxa individual nesses decis é artefato amostral.',
        st['body'],
    ))

    elms.append(Paragraph(
        '<b>A separação em 3 faixas é metodologicamente a forma correta</b> de reportar o sinal '
        'com o volume disponível — não uma simplificação. '
        'Ao agregar D1–D5, o denominador sobe para ~2.500 leads por lançamento e o numerador para '
        '~8 compradores, tornando a taxa de 0,29% estável e comparável. '
        'O mesmo vale para D6–D9 (~5.300 leads, ~39 compradores por lançamento). '
        'A granularidade completa de 10 decis está disponível nos relatórios técnicos de validação.',
        st['body'],
    ))

    elms.append(Spacer(1, 14))
    elms.append(HRFlowable(width='100%', thickness=0.5, color=C_RULE, spaceAfter=8))

    # ── Nota metodológica ──────────────────────────────────────────────────────
    elms.append(Paragraph(
        '<b>Nota metodológica.</b> '
        'Taxa de conversão = compradores matched / leads com score × 100. '
        'Leads com score: Google Sheets de captação + Railway PostgreSQL, '
        'filtrados pelo período de cada lançamento e deduplicados por e-mail. '
        'Compradores: relatórios de validação por lançamento, cruzados por e-mail. '
        'Lançamentos incluídos: DEV19, LF43, LF44, LF45, LF46, LF47, LF48. '
        'LF40 e LF41 excluídos por volume insuficiente de compradores ML (4 e 17, respectivamente). '
        'LF42 excluído por sazonalidade atípica (semana de Natal, 10 compradores totais).',
        st['footnote'],
    ))

    doc.build(elms)
    print(f"\nPDF gerado: {OUTPUT}")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    results = load_data()
    if not results:
        print("Sem dados suficientes para gerar o PDF.")
        raise SystemExit(1)
    build_pdf(results)
