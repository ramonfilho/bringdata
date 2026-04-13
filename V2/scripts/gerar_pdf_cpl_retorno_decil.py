"""
Gera PDF: Custo e Retorno por Faixa de Intenção — DevClub (DEV19–LF48)

Metodologia:
  Fase 1 — Dados reais (matched):
    - "Detalhes das Conversões" de cada xlsx → email + Valor Venda real por comprador
    - Sheets/Railway → email → decil atribuído pelo modelo
    - Cruzamento por email: comprador real → decil → faturamento real
    - Custo por tier: gasto_ml × (leads_tier_scored / total_scored)

  Fase 2 — Extrapolação para total:
    - scale = vendas_total / total_matched_buyers
    - buyers_tier_total  = buyers_matched_tier × scale
    - revenue_tier_total = revenue_matched_tier × scale
    - Assume distribuição e ticket médio dos matched representam os não-matched

  Sem estimativas de TC. Dados reais + extrapolação proporcional.

Saída: V2/propostas_e_apresentacoes/devclub_cpl_retorno_decil.pdf
"""

from pathlib import Path
import io
import sys
import yaml
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, Image, HRFlowable,
)
from reportlab.lib.colors import HexColor

sys.path.insert(0, str(Path(__file__).parent))
from ml_evolution_report import (
    load_sheets_data, load_railway,
    parse_xlsx_report, find_xlsx_for_period,
)

# ── Caminhos ──────────────────────────────────────────────────────────────────
OUTPUT        = (Path(__file__).parent.parent
                 / "propostas_e_apresentacoes"
                 / "devclub_cpl_retorno_decil.pdf")
BASE          = Path(__file__).parent.parent
LAUNCHES_YAML = BASE / "configs/launches.yaml"
INCLUDE       = ['DEV19', 'LF43', 'LF44', 'LF45', 'LF46', 'LF47', 'LF48']

# Faixas canônicas
TIER_D15  = [f'D{i}' for i in range(1, 6)]
TIER_D69  = [f'D{i}' for i in range(6, 10)]
TIER_D10  = ['D10']
ALL_DECIS = [f'D{i}' for i in range(1, 11)]

TIER_DEFS = [
    ('D10',   'Alta intenção',  'D10',   TIER_D10),
    ('D6–D9', 'Média intenção', 'D6_D9', TIER_D69),
    ('D1–D5', 'Baixa intenção', 'D1_D5', TIER_D15),
]

# Agrupamento mensal por vendas_start (derivado de launches.yaml)
MONTHS = [
    ('Janeiro/26',   ['DEV19']),
    ('Fevereiro/26', ['LF43', 'LF44']),
    ('Março/26',     ['LF45', 'LF46', 'LF47', 'LF48']),
]

TICKET_CONTRATADO = 2_200.0   # valor nominal do contrato
GURU_TICKET       = 1_997.0   # ticket médio Guru (cartão)
GURU_REALIZACAO   = 0.87      # fator de realização Guru
PCT_CARTAO        = 0.469     # proporção histórica pagamentos cartão
N_PARCELAS        = 12
PARCELA_TMB       = TICKET_CONTRATADO / N_PARCELAS  # ≈ 183.33


def _fat_recebido(buyers: float) -> float:
    """Faturamento recebido ≈ entrada imediata (cartão Guru + 1ª parcela TMB)."""
    v_guru = buyers * PCT_CARTAO
    v_tmb  = buyers * (1 - PCT_CARTAO)
    return v_guru * GURU_TICKET * GURU_REALIZACAO + v_tmb * PARCELA_TMB


def _fat_contratado(buyers: float) -> float:
    """Faturamento contratado = valor integral do contrato (todas as parcelas)."""
    return buyers * TICKET_CONTRATADO

# ── Cores (paleta Bring Data) ─────────────────────────────────────────────────
C_BLACK       = HexColor('#1a1a1a')
C_DARK_GRAY   = HexColor('#444444')
C_MID_GRAY    = HexColor('#777777')
C_LIGHT_GRAY  = HexColor('#f5f5f5')
C_GREEN       = HexColor('#1d8a3e')
C_GREEN_MID   = HexColor('#52a86b')
C_GREEN_LIGHT = HexColor('#e8f5ec')
C_WHITE       = HexColor('#ffffff')
C_RULE        = HexColor('#e0e0e0')
C_CALLOUT_BG  = HexColor('#fff8e1')
C_CALLOUT_BD  = HexColor('#f9a825')


# ── Normalização de decil ─────────────────────────────────────────────────────
def _norm(v):
    if pd.isna(v):
        return None
    s = str(v).strip().upper()
    if s.startswith('D') and s[1:].isdigit():
        return f'D{int(s[1:])}'
    if s.isdigit():
        return f'D{int(s)}'
    return None


# ── Cruzamento comprador × decil com Valor Venda real ─────────────────────────
def compute_decil_revenue(xlsx_path: Path,
                          sheets_df: pd.DataFrame,
                          cap_start: str, cap_end: str,
                          rail_df: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada decil retorna: leads | buyers_matched | revenue_matched | ticket_medio

    - Lê 'Detalhes das Conversões': email + Valor Venda por comprador
    - Cruza email → decil via Sheets/Railway do período de captação
    - Compradores sem decil ficam em 'SEM_DECIL'
    """
    if not xlsx_path or not xlsx_path.exists():
        return pd.DataFrame()

    xl = pd.ExcelFile(xlsx_path)
    if 'Detalhes das Conversões' not in xl.sheet_names:
        return pd.DataFrame()

    det = xl.parse('Detalhes das Conversões', header=None)

    # Localizar linha de header
    header_idx = None
    for i, row in det.iterrows():
        if any('mail' in str(v).lower() for v in row.values):
            header_idx = i
            break
    if header_idx is None:
        return pd.DataFrame()

    det.columns = det.iloc[header_idx].values
    det = det.iloc[header_idx + 1:].reset_index(drop=True)

    email_col = next((c for c in det.columns if 'mail' in str(c).lower()), None)
    valor_col = next((c for c in det.columns if 'valor' in str(c).lower()), None)
    if email_col is None:
        return pd.DataFrame()

    # Mapa email → valor (deduplica por email, soma se houver múltiplos registros)
    buyers: dict[str, float] = {}
    for _, row in det.iterrows():
        raw = row.get(email_col)
        if pd.isna(raw):
            continue
        email = str(raw).lower().strip()
        if not email or email == 'nan':
            continue
        valor = 0.0
        if valor_col and pd.notna(row.get(valor_col)):
            try:
                valor = float(row[valor_col])
            except (ValueError, TypeError):
                pass
        buyers[email] = buyers.get(email, 0.0) + valor

    buyer_emails = set(buyers.keys())

    # Leads com decil no período de captação (Sheets + Railway)
    start = pd.Timestamp(cap_start)
    end   = pd.Timestamp(cap_end) + pd.Timedelta(days=1)

    frames = []
    if not sheets_df.empty:
        mask = (sheets_df['data'] >= start) & (sheets_df['data'] < end)
        sub  = sheets_df[mask][['email', 'decil']].copy()
        sub['dn'] = sub['decil'].apply(_norm)
        has_d     = sub['dn'].notna()
        with_d    = sub[has_d].drop_duplicates('email', keep='last')
        without_d = sub[~has_d & ~sub['email'].isin(with_d['email'])]\
                       .drop_duplicates('email', keep='last')
        frames.append(pd.concat([with_d, without_d])[['email', 'dn']])

    if not rail_df.empty:
        mask = (rail_df['created_at'] >= start) & (rail_df['created_at'] < end)
        sub  = rail_df[mask][['email', 'decil']].copy()
        sub['dn'] = sub['decil'].apply(_norm)
        if frames:
            sub = sub[~sub['email'].isin(frames[0]['email'])]
        frames.append(sub[['email', 'dn']])

    if not frames:
        return pd.DataFrame()

    leads_df = pd.concat(frames, ignore_index=True)\
                 .drop_duplicates('email', keep='last')
    scored   = leads_df[leads_df['dn'].notna()].copy()
    if scored.empty:
        return pd.DataFrame()

    scored['bought']  = scored['email'].isin(buyer_emails)
    scored['revenue'] = scored['email'].map(buyers).fillna(0.0)

    rows = []
    for d in ALL_DECIS:
        sub = scored[scored['dn'] == d]
        n   = len(sub)
        b   = int(sub['bought'].sum())
        rev = float(sub['revenue'].sum())
        ticket_m = rev / b if b > 0 else 0.0
        rows.append({'decil': d, 'leads': n,
                     'buyers_matched': b, 'revenue_matched': rev,
                     'ticket_medio': ticket_m})

    return pd.DataFrame(rows)


# ── Carregamento por lançamento ────────────────────────────────────────────────
def load_data():
    with open(LAUNCHES_YAML) as f:
        launches = yaml.safe_load(f)

    print("Carregando dados (Sheets + Railway)...")
    sheets_df = load_sheets_data()
    rail_df   = load_railway()

    print("\nCarregando métricas por lançamento...")
    data = {}
    for name in INCLUDE:
        lc = launches.get(name)
        if not lc:
            continue
        xlsx = find_xlsx_for_period(lc['vendas_start'], lc['vendas_end'])
        if xlsx is None or not xlsx.exists():
            print(f"  {name}: xlsx não encontrado"); continue

        fin         = parse_xlsx_report(xlsx)
        gasto       = fin.get('gasto_ml')
        leads_ml    = fin.get('leads_ml')
        vendas_total = fin.get('vendas_total')
        if not gasto or not leads_ml:
            print(f"  {name}: dados financeiros ausentes"); continue

        rev_df = compute_decil_revenue(
            xlsx, sheets_df, lc['cap_start'], lc['cap_end'], rail_df
        )

        total_scored   = int(rev_df['leads'].sum())          if not rev_df.empty else 0
        total_matched  = int(rev_df['buyers_matched'].sum()) if not rev_df.empty else 0
        rev_matched    = float(rev_df['revenue_matched'].sum()) if not rev_df.empty else 0.0

        # Taxa de cobertura do matching (matched / vendas_total)
        match_rate = total_matched / vendas_total if vendas_total and total_matched else 0.0

        data[name] = {
            'gasto':         gasto,
            'leads_ml':      leads_ml,
            'vendas_total':  vendas_total,
            'rev_df':        rev_df,
            'total_scored':  total_scored,
            'total_matched': total_matched,
            'rev_matched':   rev_matched,
            'match_rate':    match_rate,
        }

        print(f"  {name}: gasto=R${gasto:,.0f} | leads={leads_ml:,} | "
              f"vendas={vendas_total} | matched={total_matched} "
              f"({match_rate*100:.0f}%) | fat_matched=R${rev_matched:,.0f}")

    return data


# ── Métricas por tier (por lançamento) ────────────────────────────────────────
def tier_stats(rec: dict, tier_decis: list) -> dict | None:
    """
    Retorna métricas reais + extrapoladas para uma faixa em um lançamento.
    """
    rev_df = rec['rev_df']
    if rev_df is None or rev_df.empty:
        return None

    sub = rev_df[rev_df['decil'].isin(tier_decis)]
    if sub.empty:
        return None

    total_scored  = rec['total_scored']
    leads_tier    = int(sub['leads'].sum())
    buyers_m      = int(sub['buyers_matched'].sum())
    revenue_m     = float(sub['revenue_matched'].sum())
    ticket_m      = revenue_m / buyers_m if buyers_m > 0 else 0.0

    # Custo proporcional ao volume de leads scored
    pct_leads     = leads_tier / total_scored if total_scored > 0 else 0.0
    custo         = rec['gasto'] * pct_leads

    # Extrapolação: scale_factor = vendas_total / total_matched
    vendas_total  = rec['vendas_total'] or 0
    total_matched = rec['total_matched']
    scale         = vendas_total / total_matched if total_matched > 0 else 1.0

    buyers_total  = buyers_m * scale
    fat_rec   = _fat_recebido(buyers_total)
    fat_cont  = _fat_contratado(buyers_total)

    roi_rec  = fat_rec  / custo if custo > 0 else None
    roi_cont = fat_cont / custo if custo > 0 else None

    # Custo por lead e retorno por lead (recebido) da faixa
    leads_ml_tier  = rec['leads_ml'] * pct_leads   # leads totais estimados na faixa
    custo_por_lead = custo / leads_ml_tier if leads_ml_tier > 0 else None
    ret_por_lead   = fat_rec / leads_ml_tier if leads_ml_tier > 0 else None

    return {
        'leads_tier':     leads_tier,
        'pct_leads':      pct_leads * 100,
        'buyers_m':       buyers_m,
        'revenue_m':      revenue_m,
        'ticket_m':       ticket_m,
        'custo':          custo,
        'scale':          scale,
        'buyers_total':   buyers_total,
        'fat_rec':        fat_rec,
        'fat_cont':       fat_cont,
        'roi_rec':        roi_rec,
        'roi_cont':       roi_cont,
        'custo_por_lead': custo_por_lead,
        'ret_por_lead':   ret_por_lead,
    }


def pool_tier_stats(data: dict, tier_decis: list) -> dict:
    """Agrega todas as launches para uma faixa."""
    agg = dict(leads_tier=0, buyers_m=0, revenue_m=0.0, custo=0.0,
               buyers_total=0.0, fat_rec=0.0, fat_cont=0.0,
               vendas_soma=0, matched_soma=0)

    for rec in data.values():
        s = tier_stats(rec, tier_decis)
        if not s:
            continue
        agg['leads_tier']   += s['leads_tier']
        agg['buyers_m']     += s['buyers_m']
        agg['revenue_m']    += s['revenue_m']
        agg['custo']        += s['custo']
        agg['buyers_total'] += s['buyers_total']
        agg['fat_rec']      += s['fat_rec']
        agg['fat_cont']     += s['fat_cont']
        agg['vendas_soma']  += rec['vendas_total'] or 0
        agg['matched_soma'] += rec['total_matched'] or 0

    ticket_m = agg['revenue_m'] / agg['buyers_m'] if agg['buyers_m'] > 0 else 0.0
    roi_rec  = agg['fat_rec']  / agg['custo'] if agg['custo'] > 0 else None
    roi_cont = agg['fat_cont'] / agg['custo'] if agg['custo'] > 0 else None
    return {**agg, 'ticket_m': ticket_m, 'roi_rec': roi_rec, 'roi_cont': roi_cont}


def pool_tier_stats_subset(data: dict, launch_names: list, tier_decis: list) -> dict:
    """Agrega subconjunto de lançamentos para uma faixa."""
    subset = {k: v for k, v in data.items() if k in launch_names}
    return pool_tier_stats(subset, tier_decis)


# ── Gráfico: Custo vs Faturamento por faixa (pool) ───────────────────────────
def make_main_chart(data: dict) -> bytes:
    labels      = ['D1–D5', 'D6–D9', 'D10']
    tier_groups = [TIER_D15, TIER_D69, TIER_D10]

    custos, fat_rec, fat_cont = [], [], []
    for tdecis in tier_groups:
        p = pool_tier_stats(data, tdecis)
        custos.append(p['custo']      / 1_000)
        fat_rec.append(p['fat_rec']   / 1_000)
        fat_cont.append(p['fat_cont'] / 1_000)

    x = np.arange(len(labels))
    w = 0.26

    fig, ax = plt.subplots(figsize=(10.5, 4.4))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    ax.bar(x - w,   custos,   w, color='#cccccc', label='Custo alocado',        zorder=3)
    ax.bar(x,       fat_rec,  w, color='#52a86b', label='Fat. Recebido',         zorder=3)
    bf = ax.bar(x + w, fat_cont, w, color='#1d8a3e', label='Fat. Contratado',   zorder=3)

    # ROI contratado anotado acima de cada grupo
    for i, (c, fr, fc) in enumerate(zip(custos, fat_rec, fat_cont)):
        roi_c = fc / c if c > 0 else 0
        roi_r = fr / c if c > 0 else 0
        ax.text(x[i] + w, fc + max(fat_cont) * 0.015,
                f'{roi_c:.1f}×', ha='center', va='bottom',
                fontsize=8, fontweight='bold', color='#1a1a1a')
        ax.text(x[i], fr + max(fat_cont) * 0.015,
                f'{roi_r:.1f}×', ha='center', va='bottom',
                fontsize=7.5, color='#52a86b')

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, color='#1a1a1a', fontweight='bold')
    ax.set_ylabel('R$ mil', fontsize=8.5, color='#444444')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'R${v:,.0f}k'))
    ax.yaxis.set_tick_params(labelsize=8, labelcolor='#777777')
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.spines['bottom'].set_color('#e0e0e0')
    ax.yaxis.grid(True, color='#eeeeee', linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc='upper left', fontsize=9, frameon=False)

    plt.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── Gráfico: ROI por faixa × lançamento ──────────────────────────────────────
def make_roi_by_launch(data: dict) -> bytes:
    launches = [n for n in INCLUDE if n in data]
    x = np.arange(len(launches))
    w = 0.26

    def rois(tier_decis):
        out = []
        for n in launches:
            s = tier_stats(data[n], tier_decis)
            out.append(s['roi_rec'] if s and s['roi_rec'] else 0)
        return out

    r15 = rois(TIER_D15)
    r69 = rois(TIER_D69)
    r10 = rois(TIER_D10)

    fig, ax = plt.subplots(figsize=(10.5, 3.6))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    ax.bar(x - w, r15, w, color='#cccccc', label='D1–D5', zorder=3)
    ax.bar(x,     r69, w, color='#52a86b', label='D6–D9', zorder=3)
    b10 = ax.bar(x + w, r10, w, color='#1d8a3e', label='D10', zorder=3)

    for bar, v in zip(b10, r10):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
                    f'{v:.1f}×', ha='center', va='bottom',
                    fontsize=7.5, fontweight='bold', color='#1a1a1a')

    ax.axhline(1.0, color='#e53935', linewidth=0.8, linestyle='--', zorder=2, alpha=0.7)
    ax.text(len(launches) - 0.35, 1.06, 'break-even', fontsize=7,
            color='#e53935', alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(launches, fontsize=9, color='#444444')
    ax.set_ylabel('ROI (Faturamento / Custo)', fontsize=8.5, color='#444444')
    ax.yaxis.set_tick_params(labelsize=8, labelcolor='#777777')
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.spines['bottom'].set_color('#e0e0e0')
    ax.yaxis.grid(True, color='#eeeeee', linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc='upper right', fontsize=8, frameon=False)

    plt.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── Gráfico: ROI por faixa × mês ─────────────────────────────────────────────
def make_monthly_chart(data: dict) -> bytes:
    month_labels = [m[0] for m in MONTHS]
    x = np.arange(len(month_labels))
    w = 0.26

    def rois(tier_decis):
        out = []
        for _, lnames in MONTHS:
            p = pool_tier_stats_subset(data, lnames, tier_decis)
            out.append(p['roi_rec'] or 0)
        return out

    r15 = rois(TIER_D15)
    r69 = rois(TIER_D69)
    r10 = rois(TIER_D10)

    fig, ax = plt.subplots(figsize=(10.5, 3.6))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    ax.bar(x - w, r15, w, color='#cccccc', label='D1–D5', zorder=3)
    ax.bar(x,     r69, w, color='#52a86b', label='D6–D9', zorder=3)
    b10 = ax.bar(x + w, r10, w, color='#1d8a3e', label='D10', zorder=3)

    for bar, v in zip(b10, r10):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
                    f'{v:.1f}×', ha='center', va='bottom',
                    fontsize=8, fontweight='bold', color='#1a1a1a')

    ax.axhline(1.0, color='#e53935', linewidth=0.8, linestyle='--', zorder=2, alpha=0.7)
    ax.text(len(month_labels) - 0.35, 1.06, 'break-even',
            fontsize=7, color='#e53935', alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(month_labels, fontsize=10, color='#444444', fontweight='bold')
    ax.set_ylabel('ROI Recebido (Fat. / Custo)', fontsize=8.5, color='#444444')
    ax.yaxis.set_tick_params(labelsize=8, labelcolor='#777777')
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.spines['bottom'].set_color('#e0e0e0')
    ax.yaxis.grid(True, color='#eeeeee', linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc='upper right', fontsize=8, frameon=False)

    plt.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── Tabela mensal (mês × faixa) ───────────────────────────────────────────────
def make_monthly_table(data: dict, st: dict) -> Table:
    header = [
        Paragraph('Mês',                  st['th']),
        Paragraph('Faixa',                st['th']),
        Paragraph('Custo\nalocado',       st['th']),
        Paragraph('Comprad.\n(extrap.)',  st['th']),
        Paragraph('Fat.\nRecebido',       st['th']),
        Paragraph('ROI\nRec.',            st['th']),
        Paragraph('Fat.\nContratado',     st['th']),
        Paragraph('ROI\nCont.',           st['th']),
    ]

    rows       = [header]
    style_cmds = _tbl_style_base()
    month_bgs  = [C_WHITE, C_LIGHT_GRAY, HexColor('#edf7f1')]

    row_i = 1
    for (month_name, launch_names), bg in zip(MONTHS, month_bgs):
        avail = [n for n in launch_names if n in data]
        if not avail:
            continue

        tier_order = [
            ('D10',   'Alta intenção',  TIER_D10),
            ('D6–D9', 'Média intenção', TIER_D69),
            ('D1–D5', 'Baixa intenção', TIER_D15),
        ]

        first_row = row_i
        tot = {'custo': 0.0, 'buyers_total': 0.0, 'fat_rec': 0.0, 'fat_cont': 0.0}

        for tier_label, tier_desc, tier_decis in tier_order:
            p = pool_tier_stats_subset(data, avail, tier_decis)
            tot['custo']        += p['custo']
            tot['buyers_total'] += p['buyers_total']
            tot['fat_rec']      += p['fat_rec']
            tot['fat_cont']     += p['fat_cont']

            rc = '#1d8a3e' if (p['roi_rec']  or 0) >= 2 else '#e53935'
            cc = '#1d8a3e' if (p['roi_cont'] or 0) >= 2 else '#e53935'
            rows.append([
                '',  # preenchido abaixo via SPAN
                Paragraph(
                    f'<b>{tier_label}</b><br/>'
                    f'<font size="7" color="#777777">{tier_desc}</font>',
                    st['td_l'],
                ),
                Paragraph(_brl(p['custo']),           st['td']),
                Paragraph(f'{p["buyers_total"]:.0f}',  st['td']),
                Paragraph(_brl(p['fat_rec']),           st['td']),
                _roi_p(p['roi_rec'],  st, bold=True, color=rc),
                Paragraph(_brl(p['fat_cont']),          st['td']),
                _roi_p(p['roi_cont'], st, bold=True, color=cc),
            ])
            style_cmds.append(('BACKGROUND', (1, row_i), (-1, row_i), bg))
            row_i += 1

        # Linha total do mês
        roi_rec_t  = tot['fat_rec']  / tot['custo'] if tot['custo'] > 0 else None
        roi_cont_t = tot['fat_cont'] / tot['custo'] if tot['custo'] > 0 else None
        launches_str = ', '.join(avail)
        rows.append([
            '',
            Paragraph(
                f'<b>Total</b><br/>'
                f'<font size="6.5" color="#777777">{launches_str}</font>',
                st['td_l'],
            ),
            Paragraph(f'<b>{_brl(tot["custo"])}</b>',       st['td']),
            Paragraph(f'<b>{tot["buyers_total"]:.0f}</b>',   st['td']),
            Paragraph(f'<b>{_brl(tot["fat_rec"])}</b>',      st['td']),
            _roi_p(roi_rec_t,  st, bold=True),
            Paragraph(f'<b>{_brl(tot["fat_cont"])}</b>',     st['td']),
            _roi_p(roi_cont_t, st, bold=True),
        ])
        style_cmds += [
            ('BACKGROUND', (1, row_i), (-1, row_i), HexColor('#e8f5ec')),
            ('LINEABOVE',  (0, row_i), (-1, row_i), 0.6, C_GREEN),
        ]
        row_i += 1

        # Merge da coluna Mês para todo o bloco do mês
        style_cmds.append(('SPAN',       (0, first_row), (0, row_i - 1)))
        style_cmds.append(('VALIGN',     (0, first_row), (0, row_i - 1), 'MIDDLE'))
        style_cmds.append(('BACKGROUND', (0, first_row), (0, row_i - 1), bg))
        style_cmds.append(('LINEBELOW',  (0, row_i - 1), (-1, row_i - 1), 1.0, C_RULE))
        # Texto do mês na primeira célula do bloco
        rows[first_row][0] = Paragraph(f'<b>{month_name}</b>', st['td_l'])

    col_widths = [2.4*cm, 2.6*cm, 2.4*cm, 2.2*cm, 2.4*cm, 1.8*cm, 2.6*cm, 1.8*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Estilos ReportLab ─────────────────────────────────────────────────────────
def styles():
    base, bold = 'Helvetica', 'Helvetica-Bold'
    return {
        'title':    ParagraphStyle('title',   fontName=bold, fontSize=17,
                                   textColor=C_BLACK, leading=22, spaceAfter=2),
        'subtitle': ParagraphStyle('sub',     fontName=base, fontSize=10,
                                   textColor=C_MID_GRAY, leading=14, spaceAfter=14),
        'section':  ParagraphStyle('section', fontName=bold, fontSize=10.5,
                                   textColor=C_BLACK, leading=15,
                                   spaceBefore=16, spaceAfter=6),
        'body':     ParagraphStyle('body',    fontName=base, fontSize=9.5,
                                   textColor=C_DARK_GRAY, leading=15, spaceAfter=5),
        'callout':  ParagraphStyle('callout', fontName=bold, fontSize=11,
                                   textColor=C_BLACK, leading=17,
                                   alignment=TA_CENTER),
        'footnote': ParagraphStyle('fn',      fontName=base, fontSize=7.5,
                                   textColor=C_MID_GRAY, leading=11),
        'th':       ParagraphStyle('th',      fontName=bold, fontSize=8.5,
                                   textColor=C_WHITE,     alignment=TA_CENTER),
        'td':       ParagraphStyle('td',      fontName=base, fontSize=8.5,
                                   textColor=C_DARK_GRAY, alignment=TA_CENTER),
        'td_l':     ParagraphStyle('td_l',    fontName=bold, fontSize=8.5,
                                   textColor=C_DARK_GRAY, alignment=TA_LEFT),
        'td_r':     ParagraphStyle('td_r',    fontName=base, fontSize=8.5,
                                   textColor=C_DARK_GRAY, alignment=TA_RIGHT),
    }


def _brl(v):
    if v is None: return '—'
    return f'R$ {v:,.0f}'.replace(',', '.')

def _pct(v):
    if v is None: return '—'
    return f'{v:.1f}%'

def _roi_p(v, st, bold=False, color=None):
    if not v: return Paragraph('—', st['td'])
    txt = f'{v:.1f}×'
    if bold:  txt = f'<b>{txt}</b>'
    if color: txt = f'<font color="{color}">{txt}</font>'
    return Paragraph(txt, st['td'])

def _tbl_style_base():
    return [
        ('BACKGROUND',    (0, 0), (-1, 0), C_BLACK),
        ('GRID',          (0, 0), (-1,-1), 0.3, C_RULE),
        ('TOPPADDING',    (0, 0), (-1,-1), 7),
        ('BOTTOMPADDING', (0, 0), (-1,-1), 7),
        ('LEFTPADDING',   (0, 0), (-1,-1), 9),
        ('RIGHTPADDING',  (0, 0), (-1,-1), 9),
        ('VALIGN',        (0, 0), (-1,-1), 'MIDDLE'),
    ]


# ── Tabela resumo pooled ───────────────────────────────────────────────────────
def make_summary_table(data: dict, st: dict) -> Table:
    header = [
        Paragraph('Faixa',               st['th']),
        Paragraph('Custo\nalocado',      st['th']),
        Paragraph('Comprad.\n(extrap.)', st['th']),
        Paragraph('Fat.\nRecebido',      st['th']),
        Paragraph('ROI\nRecebido',       st['th']),
        Paragraph('Fat.\nContratado',    st['th']),
        Paragraph('ROI\nContratado',     st['th']),
    ]

    bgs = [C_GREEN_LIGHT, HexColor('#edf7f1'), C_LIGHT_GRAY]
    rows       = [header]
    style_cmds = _tbl_style_base()

    tot = {'custo': 0, 'buyers_total': 0, 'fat_rec': 0, 'fat_cont': 0}

    for i, ((label, desc, _, tdecis), bg) in enumerate(zip(TIER_DEFS, bgs), start=1):
        p = pool_tier_stats(data, tdecis)
        tot['custo']        += p['custo']
        tot['buyers_total'] += p['buyers_total']
        tot['fat_rec']      += p['fat_rec']
        tot['fat_cont']     += p['fat_cont']

        roi_rec_color  = '#1d8a3e' if (p['roi_rec']  or 0) >= 2 else '#e53935'
        roi_cont_color = '#1d8a3e' if (p['roi_cont'] or 0) >= 2 else '#e53935'
        lbl = Paragraph(
            f'<b>{label}</b><br/><font size="7.5" color="#777777">{desc}</font>',
            st['td_l'],
        )
        rows.append([
            lbl,
            Paragraph(_brl(p['custo']),          st['td']),
            Paragraph(f'{p["buyers_total"]:.0f}', st['td']),
            Paragraph(_brl(p['fat_rec']),          st['td']),
            _roi_p(p['roi_rec'],  st, bold=True, color=roi_rec_color),
            Paragraph(_brl(p['fat_cont']),         st['td']),
            _roi_p(p['roi_cont'], st, bold=True, color=roi_cont_color),
        ])
        style_cmds.append(('BACKGROUND', (0, i), (-1, i), bg))

    # Total
    roi_rec_t  = tot['fat_rec']  / tot['custo'] if tot['custo'] > 0 else None
    roi_cont_t = tot['fat_cont'] / tot['custo'] if tot['custo'] > 0 else None
    last = len(rows)
    rows.append([
        Paragraph('<b>TOTAL</b>', st['td_l']),
        Paragraph(f'<b>{_brl(tot["custo"])}</b>',      st['td']),
        Paragraph(f'<b>{tot["buyers_total"]:.0f}</b>',  st['td']),
        Paragraph(f'<b>{_brl(tot["fat_rec"])}</b>',     st['td']),
        _roi_p(roi_rec_t,  st, bold=True),
        Paragraph(f'<b>{_brl(tot["fat_cont"])}</b>',    st['td']),
        _roi_p(roi_cont_t, st, bold=True),
    ])
    style_cmds += [
        ('BACKGROUND', (0, last), (-1, last), HexColor('#e8f5ec')),
        ('LINEABOVE',  (0, last), (-1, last), 0.8, C_GREEN),
    ]

    t = Table(rows, colWidths=[2.8*cm, 2.4*cm, 2.2*cm, 2.6*cm, 2.2*cm, 2.8*cm, 2.2*cm],
              repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Tabela cobertura de matching por lançamento ───────────────────────────────
def make_coverage_table(data: dict, st: dict) -> Table:
    launches = [n for n in INCLUDE if n in data]

    header = [
        Paragraph('Lançamento',   st['th']),
        Paragraph('Vendas\ntotal',st['th']),
        Paragraph('Matched\n(com decil)',st['th']),
        Paragraph('Cobertura',    st['th']),
        Paragraph('Fat. matched', st['th']),
        Paragraph('Scale\nfactor',st['th']),
        Paragraph('Fat.\nextrap.',st['th']),
    ]

    rows       = [header]
    style_cmds = _tbl_style_base()
    style_cmds.append(('ROWBACKGROUNDS', (0, 1), (-1,-1), [C_WHITE, C_LIGHT_GRAY]))

    for i, name in enumerate(launches, start=1):
        rec  = data[name]
        vt   = rec['vendas_total'] or 0
        tm   = rec['total_matched']
        rm   = rec['rev_matched']
        cov  = rec['match_rate'] * 100
        scale = vt / tm if tm > 0 else 0
        fat_ext = rm * scale if tm > 0 else 0

        cov_color = '#1d8a3e' if cov >= 50 else ('#f9a825' if cov >= 20 else '#e53935')
        rows.append([
            Paragraph(f'<b>{name}</b>', st['td_l']),
            Paragraph(str(vt),           st['td']),
            Paragraph(str(tm),           st['td']),
            Paragraph(f'<font color="{cov_color}"><b>{cov:.0f}%</b></font>', st['td']),
            Paragraph(_brl(rm),          st['td']),
            Paragraph(f'{scale:.2f}×',   st['td']),
            Paragraph(_brl(fat_ext),     st['td']),
        ])

    t = Table(rows, colWidths=[2.6*cm, 2.2*cm, 2.6*cm, 2.4*cm, 3.0*cm, 2.2*cm, 3.0*cm],
              repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Tabela por lançamento (D10 vs D1-D5) ──────────────────────────────────────
def make_launch_table(data: dict, st: dict) -> Table:
    launches = [n for n in INCLUDE if n in data]

    # Colunas: Lançamento | [D1-D5: custo/lead, ret/lead, custo total, fat total, ROI]
    #                     | [D6-D9: custo/lead, ret/lead] | [D10: custo/lead, ret/lead, fat cont, ROI]
    header = [
        Paragraph('Lançamento',          st['th']),
        Paragraph('D1–D5\nCusto/Lead',   st['th']),
        Paragraph('D1–D5\nRet./Lead',    st['th']),
        Paragraph('D6–D9\nCusto/Lead',   st['th']),
        Paragraph('D6–D9\nRet./Lead',    st['th']),
        Paragraph('D10\nCusto/Lead',     st['th']),
        Paragraph('D10\nRet./Lead',      st['th']),
        Paragraph('D10\nFat. Cont.',     st['th']),
        Paragraph('D10\nROI',            st['th']),
    ]

    rows       = [header]
    style_cmds = _tbl_style_base()
    style_cmds.append(('ROWBACKGROUNDS', (0, 1), (-1,-1), [C_WHITE, C_LIGHT_GRAY]))

    for i, name in enumerate(launches, start=1):
        rec = data[name]
        s15 = tier_stats(rec, TIER_D15)
        s69 = tier_stats(rec, TIER_D69)
        s10 = tier_stats(rec, TIER_D10)

        roi10_color = '#1d8a3e' if s10 and (s10['roi_cont'] or 0) >= 2 else '#e53935'

        def _cpl(s):
            return Paragraph(_brl(s['custo_por_lead']) if s and s['custo_por_lead'] else '—', st['td'])
        def _rpl(s):
            return Paragraph(_brl(s['ret_por_lead']) if s and s['ret_por_lead'] else '—', st['td'])

        rows.append([
            Paragraph(f'<b>{name}</b>', st['td_l']),
            _cpl(s15), _rpl(s15),
            _cpl(s69), _rpl(s69),
            _cpl(s10), _rpl(s10),
            Paragraph(_brl(s10['fat_cont']) if s10 else '—', st['td']),
            _roi_p(s10['roi_cont'] if s10 else None, st, bold=True, color=roi10_color),
        ])
        style_cmds.append(('BACKGROUND', (5, i), (8, i), C_GREEN_LIGHT))

    col_widths = [2.0*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.4*cm, 1.8*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Callout ────────────────────────────────────────────────────────────────────
def make_callout(text: str, st: dict) -> Table:
    cell = Table([[Paragraph(text, st['callout'])]], colWidths=[17.6*cm])
    cell.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1,-1), C_CALLOUT_BG),
        ('LINEABOVE',     (0, 0), (-1, 0), 2, C_CALLOUT_BD),
        ('LINEBELOW',     (0,-1), (-1,-1), 2, C_CALLOUT_BD),
        ('TOPPADDING',    (0, 0), (-1,-1), 11),
        ('BOTTOMPADDING', (0, 0), (-1,-1), 11),
        ('LEFTPADDING',   (0, 0), (-1,-1), 14),
        ('RIGHTPADDING',  (0, 0), (-1,-1), 14),
    ]))
    return cell


# ── Montagem do PDF ────────────────────────────────────────────────────────────
def build_pdf(data: dict):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=2.0*cm, rightMargin=2.0*cm,
        topMargin=1.8*cm,  bottomMargin=1.8*cm,
    )
    st   = styles()
    elms = []

    # Callout numbers
    p_d10 = pool_tier_stats(data, TIER_D10)
    p_d15 = pool_tier_stats(data, TIER_D15)
    roi_d10 = p_d10['roi_rec']
    roi_d15 = p_d15['roi_rec']
    lift = f'{roi_d10/roi_d15:.1f}×' if roi_d10 and roi_d15 and roi_d15 > 0 else '?'

    # Cobertura média
    all_match_rates = [r['match_rate'] for r in data.values() if r['total_matched'] > 0]
    avg_coverage = np.mean(all_match_rates) * 100 if all_match_rates else 0

    # ── Cabeçalho ──────────────────────────────────────────────────────────────
    elms.append(Paragraph('Custo e Retorno por Faixa de Intenção', st['title']))
    elms.append(Paragraph(
        'DevClub &nbsp;·&nbsp; 7 lançamentos &nbsp;·&nbsp; '
        'jan/2026–mar/2026 &nbsp;·&nbsp; Ticket real por comprador (Guru, Asaas, TMB, Hotmart)',
        st['subtitle'],
    ))
    elms.append(HRFlowable(width='100%', thickness=1, color=C_RULE, spaceAfter=14))

    # ── Callout ────────────────────────────────────────────────────────────────
    elms.append(make_callout(
        f'D10 gera {lift} mais retorno por real investido que D1–D5  '
        f'(ROI recebido {roi_d10:.1f}× vs {roi_d15:.1f}×)',
        st,
    ))
    elms.append(Spacer(1, 16))

    # ── Resumo pooled ──────────────────────────────────────────────────────────
    elms.append(Paragraph('Custo e retorno por faixa — pool de 7 lançamentos', st['section']))
    elms.append(Paragraph(
        'Custo alocado = gasto ML × (leads_faixa / total_leads_scored). '
        '<b>Fat. Recebido</b> = compradores extrap. × (46,9% × R$1.997 × 0,87 + 53,1% × R$183) ≈ R$912/comprador '
        f'(entrada imediata: cartão Guru + 1ª parcela TMB). Cobertura média de matching: {avg_coverage:.0f}%. '
        '<b>Fat. Contratado</b> = compradores extrap. × R$2.200 (valor integral de todas as parcelas).',
        st['body'],
    ))
    elms.append(Spacer(1, 6))
    elms.append(make_summary_table(data, st))
    elms.append(Spacer(1, 5))
    elms.append(Paragraph(
        'Compradores matched: email do comprador (Guru/Asaas) encontrado no banco de leads com decil atribuído. '
        'Extrap.: matched × (vendas_total / matched) por lançamento. '
        'Ticket médio calculado sobre os matched (valor real da transação).',
        st['footnote'],
    ))
    elms.append(Spacer(1, 16))

    # ── Gráfico principal ──────────────────────────────────────────────────────
    elms.append(Paragraph('Custo × faturamento por faixa (pool)', st['section']))
    elms.append(Paragraph(
        'Comparação direta entre investimento alocado e faturamento gerado por faixa.',
        st['body'],
    ))
    elms.append(Spacer(1, 4))
    elms.append(Image(io.BytesIO(make_main_chart(data)), width=17.0*cm, height=6.5*cm))
    elms.append(Spacer(1, 16))

    # ── Gráfico ROI por lançamento ────────────────────────────────────────────
    elms.append(Paragraph('ROI por faixa · consistência entre lançamentos', st['section']))
    elms.append(Paragraph(
        'ROI = Faturamento (extrap.) / Custo alocado por lançamento.',
        st['body'],
    ))
    elms.append(Spacer(1, 4))
    elms.append(Image(io.BytesIO(make_roi_by_launch(data)), width=17.0*cm, height=5.5*cm))
    elms.append(Spacer(1, 16))

    # ── Tabela por lançamento ──────────────────────────────────────────────────
    elms.append(Paragraph('D10 vs D1–D5 por lançamento', st['section']))
    elms.append(Spacer(1, 4))
    elms.append(make_launch_table(data, st))
    elms.append(Spacer(1, 20))

    # ── Visão mensal ───────────────────────────────────────────────────────────
    elms.append(Paragraph('Custo e retorno por faixa — visão mensal', st['section']))
    elms.append(Paragraph(
        'Agrupamento por mês de vendas (jan/26: DEV19 · fev/26: LF43+LF44 · '
        'mar/26: LF45–LF48). Permite avaliar consistência do padrão entre meses.',
        st['body'],
    ))
    elms.append(Spacer(1, 4))
    elms.append(Image(io.BytesIO(make_monthly_chart(data)), width=17.0*cm, height=5.5*cm))
    elms.append(Spacer(1, 8))
    elms.append(make_monthly_table(data, st))
    elms.append(Spacer(1, 16))

    # ── Cobertura de matching ──────────────────────────────────────────────────
    elms.append(Paragraph('Cobertura do matching por lançamento', st['section']))
    elms.append(Paragraph(
        'Mostra quantos compradores tiveram email cruzado com o decil do modelo. '
        'A extrapolação assume que matched e não-matched têm a mesma distribuição por faixa.',
        st['body'],
    ))
    elms.append(Spacer(1, 4))
    elms.append(make_coverage_table(data, st))

    elms.append(Spacer(1, 14))
    elms.append(HRFlowable(width='100%', thickness=0.5, color=C_RULE, spaceAfter=8))

    # ── Nota metodológica ──────────────────────────────────────────────────────
    elms.append(Paragraph(
        '<b>Nota metodológica.</b> '
        'Fonte de compradores: aba "Detalhes das Conversões" (Guru, Asaas, TMB e Hotmart) — '
        'usada para identificar proporção de compradores por faixa via e-mail. '
        'Faturamento calculado com fórmulas históricas: Recebido ≈ R$912/comprador '
        '(46,9% cartão Guru × R$1.997 × 0,87 + 53,1% TMB × R$183); '
        'Contratado = R$2.200/comprador. '
        'Decil por lead: Google Sheets de captação + Railway PostgreSQL '
        '(configs/launches.yaml). Cruzamento por e-mail. '
        'Extrapolação: scale = vendas_total / matched por lançamento, por faixa. '
        'LF44: sem dados de score no período de captação — excluído da análise por faixa.',
        st['footnote'],
    ))

    doc.build(elms)
    print(f'\nPDF gerado: {OUTPUT}')


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    data = load_data()
    if not data:
        print("Sem dados suficientes.")
        raise SystemExit(1)
    build_pdf(data)
