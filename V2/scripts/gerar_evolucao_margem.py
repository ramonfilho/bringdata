"""
gerar_evolucao_margem.py

Adiciona nova sheet "Margem & Contrafactual" ao arquivo de evolução ML
e gera gráficos de margem, ROAS total e análise contrafactual.

Pergunta central: o sistema ML aumenta a margem de contribuição total
do negócio, ou apenas substitui ROAS das campanhas Controle?
"""

import sys
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, numbers
from openpyxl.utils import get_column_letter
from datetime import datetime

BASE = Path(__file__).parent.parent  # V2/

PERIODOS = [
    ('LF40',  '08:12 - 14:12'),
    ('LF41',  '15:12 - 21:12'),
    ('LF42',  '22:12 - 28:12'),
    ('DEV19', '19:01 - 25:01'),
    ('LF43',  '02:02 - 08:02'),
    ('LF44',  '09:02 - 15:02'),
    ('LF45',  '02:03 - 08:03'),
    ('LF46',  '09:03 - 15:03'),
]

EVOLUCAO_XLSX = BASE / 'outputs' / 'validation' / 'historico' / 'evolucao_ml_devclub_20260310_163649.xlsx'
GRAFICOS_DIR  = BASE / 'outputs' / 'validation' / 'historico' / 'graficos'
GRAFICOS_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1. SELEÇÃO DO RELATÓRIO MAIS RECENTE
# ─────────────────────────────────────────────────────────────────────────────

def get_latest_report(folder: str) -> Path | None:
    path = BASE / 'outputs' / 'validation' / folder
    files = sorted(path.glob('validation_report_*.xlsx'))
    return files[-1] if files else None


# ─────────────────────────────────────────────────────────────────────────────
# 2. PARSING DA SHEET "COMPARAÇÃO ML"
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v, default=0.0):
    if v is None or (isinstance(v, str) and v.strip() in ('—', '-', 'N/A', '')):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_comparacao_ml(xlsx_path: Path) -> dict:
    """
    Extrai métricas da aba 'Comparação ML' (bloco All vs All, não Matched Pairs).
    Suporta formato novo (18/03) e antigo (09/03).
    """
    df = pd.read_excel(xlsx_path, sheet_name='Comparação ML', header=None)

    result = {
        'gasto_ml': None, 'gasto_ctrl': None,
        'receita_ml': None, 'receita_ctrl': None,
        'roas_ml': None, 'roas_ctrl': None,
        'margem_ml': None, 'margem_ctrl': None,
        'formato': None,
    }

    # Detectar formato pelo conteúdo da primeira célula não-nula
    first_label = ''
    for _, row in df.iterrows():
        v = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
        if v:
            first_label = v
            break

    if 'TOTAIS DO LANÇAMENTO' in first_label:
        result['formato'] = 'novo'
        _parse_novo(df, result)
    else:
        result['formato'] = 'antigo'
        _parse_antigo(df, result)

    # Métricas derivadas
    gml  = result['gasto_ml']   or 0
    gctl = result['gasto_ctrl'] or 0
    rml  = result['receita_ml'] or 0
    rctl = result['receita_ctrl'] or 0
    mml  = result['margem_ml']  or 0
    mctl = result['margem_ctrl'] or 0

    result['gasto_total']   = gml + gctl
    result['receita_total'] = rml + rctl
    result['margem_total']  = mml + mctl

    roas_ctrl = result['roas_ctrl']
    if roas_ctrl and roas_ctrl > 0 and result['gasto_total'] > 0:
        result['receita_cf'] = result['gasto_total'] * roas_ctrl
        result['margem_cf']  = result['receita_cf'] - result['gasto_total']
        result['ganho_margem'] = result['margem_total'] - result['margem_cf']
    else:
        result['receita_cf']   = None
        result['margem_cf']    = None
        result['ganho_margem'] = None

    result['pct_budget_ml'] = (gml / result['gasto_total'] * 100) if result['gasto_total'] > 0 else 100.0

    if result['gasto_total'] > 0:
        result['roas_total'] = result['receita_total'] / result['gasto_total']
    else:
        result['roas_total'] = None

    return result


def _parse_novo(df: pd.DataFrame, result: dict):
    """Formato novo (18/03): seção 'COMPARAÇÃO ML vs CONTROLE' com labels em col A."""
    in_comparacao = False
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''

        if 'COMPARAÇÃO ML vs CONTROLE' in label or 'COMPARAÇÃO ML' in label:
            in_comparacao = True
            continue

        # Parar ao chegar na seção de Adsets
        if in_comparacao and ('ADSETS' in label.upper() or 'MATCHED' in label.upper()):
            break

        if not in_comparacao:
            continue

        v1 = _to_float(row.iloc[1])
        v2 = _to_float(row.iloc[2])

        if label == 'Gasto':
            result['gasto_ml'], result['gasto_ctrl'] = v1, v2
        elif label == 'Receita':
            result['receita_ml'], result['receita_ctrl'] = v1, v2
        elif label == 'ROAS':
            result['roas_ml'], result['roas_ctrl'] = v1, v2
        elif label == 'Margem':
            result['margem_ml'], result['margem_ctrl'] = v1, v2


def _parse_antigo(df: pd.DataFrame, result: dict):
    """Formato antigo (09/03): labels descritivos, usa Receita Traqueada e ROAS Traqueado."""
    in_allvsall = True
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
        if 'ADSETS MATCHED' in label.upper() or 'MATCHED PAIRS' in label.upper():
            break
        v1 = _to_float(row.iloc[1])
        v2 = _to_float(row.iloc[2])

        if 'Receita Total (Traqueada)' in label:
            result['receita_ml'], result['receita_ctrl'] = v1, v2
        elif 'Gasto Total' in label and 'Lançamento' not in label:
            result['gasto_ml'], result['gasto_ctrl'] = v1, v2
        elif 'ROAS (Traqueado)' in label:
            result['roas_ml'], result['roas_ctrl'] = v1, v2
        elif 'Margem Contribuição (Traqueada)' in label:
            result['margem_ml'], result['margem_ctrl'] = v1, v2


# ─────────────────────────────────────────────────────────────────────────────
# 3. COLETA DE DADOS
# ─────────────────────────────────────────────────────────────────────────────

data = {}
for name, folder in PERIODOS:
    xlsx = get_latest_report(folder)
    if not xlsx:
        print(f"  {name}: sem relatório em {folder}")
        continue
    try:
        m = parse_comparacao_ml(xlsx)
        m['name'] = name
        m['report'] = xlsx.name
        data[name] = m
        ctrl_str = f"ctrl_ROAS={m['roas_ctrl']:.2f}" if m['roas_ctrl'] else "sem ctrl"
        print(f"  {name}: ML_ROAS={m['roas_ml']:.2f} | {ctrl_str} | total_ROAS={m['roas_total']:.2f if m['roas_total'] else 'N/A'} | margem_total=R${m['margem_total']:,.0f}")
    except Exception as e:
        print(f"  {name}: ERRO — {e}")

LANCAMENTOS = [n for n, _ in PERIODOS if n in data]
df_all = pd.DataFrame([data[n] for n in LANCAMENTOS]).set_index('name')

print(f"\n{len(df_all)} lançamentos carregados.\n")


# ─────────────────────────────────────────────────────────────────────────────
# 4. NOVA SHEET NO EVOLUÇÃO XLSX
# ─────────────────────────────────────────────────────────────────────────────

def brl(v, default='—'):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return default
    return f"R$ {v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

def pct(v, default='—'):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return default
    return f"{v:.1f}%"

def roas_str(v, default='—'):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return default
    return f"{v:.2f}x"

METRICAS = [
    ('RECEITA & ROAS', None),
    ('Receita ML (R$)',          lambda m: brl(m.get('receita_ml'))),
    ('Receita Controle (R$)',    lambda m: brl(m.get('receita_ctrl'))),
    ('Receita Total (R$)',       lambda m: brl(m.get('receita_total'))),
    ('ROAS ML',                  lambda m: roas_str(m.get('roas_ml'))),
    ('ROAS Controle',            lambda m: roas_str(m.get('roas_ctrl'))),
    ('ROAS Total do Lançamento', lambda m: roas_str(m.get('roas_total'))),
    ('MARGEM DE CONTRIBUIÇÃO', None),
    ('Margem ML (R$)',           lambda m: brl(m.get('margem_ml'))),
    ('Margem Controle (R$)',     lambda m: brl(m.get('margem_ctrl'))),
    ('Margem Total (R$)',        lambda m: brl(m.get('margem_total'))),
    ('ANÁLISE CONTRAFACTUAL', None),
    ('Receita CF — e se todo spend fosse a ROAS Ctrl (R$)', lambda m: brl(m.get('receita_cf'), '* sem ctrl')),
    ('Margem CF (R$)',           lambda m: brl(m.get('margem_cf'), '* sem ctrl')),
    ('Ganho de Margem vs CF (R$)', lambda m: brl(m.get('ganho_margem'), '* sem ctrl')),
    ('ALOCAÇÃO DE BUDGET', None),
    ('Gasto ML (R$)',            lambda m: brl(m.get('gasto_ml'))),
    ('Gasto Controle (R$)',      lambda m: brl(m.get('gasto_ctrl'))),
    ('% Budget em ML',           lambda m: pct(m.get('pct_budget_ml'))),
    ('Gasto Total (R$)',         lambda m: brl(m.get('gasto_total'))),
]

wb = load_workbook(EVOLUCAO_XLSX)

# Remover sheet antiga se existir
if 'Margem & Contrafactual' in wb.sheetnames:
    del wb['Margem & Contrafactual']

ws = wb.create_sheet('Margem & Contrafactual')

# Cores
AZUL_HEADER  = PatternFill('solid', fgColor='1E3A5F')
CINZA_BLOCO  = PatternFill('solid', fgColor='D0D7E3')
VERDE_GANHO  = PatternFill('solid', fgColor='C6EFCE')
VERMELHO_CF  = PatternFill('solid', fgColor='FFCCCC')
BRANCO       = PatternFill('solid', fgColor='FFFFFF')
AMARELO_NOTA = PatternFill('solid', fgColor='FFF2CC')

font_header  = Font(bold=True, color='FFFFFF', size=11)
font_bloco   = Font(bold=True, color='1E3A5F', size=10)
font_normal  = Font(size=10)

# Cabeçalho
ws.cell(1, 1, 'MARGEM DE CONTRIBUIÇÃO & ANÁLISE CONTRAFACTUAL — DevClub').font = Font(bold=True, size=13, color='1E3A5F')
ws.cell(2, 1, f'Gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")} | Dados dos relatórios mais recentes de cada período').font = Font(size=9, italic=True, color='666666')
ws.cell(3, 1, '* Contrafactual: e se todo o gasto do lançamento (ML + Controle) fosse alocado ao ROAS Controle?').font = Font(size=9, color='666666')

# Linha de nomes de lançamentos (row 5)
ws.cell(5, 1, 'Métrica').fill = AZUL_HEADER
ws.cell(5, 1).font = font_header
ws.cell(5, 1).alignment = Alignment(horizontal='left')

for col_idx, name in enumerate(LANCAMENTOS, start=2):
    c = ws.cell(5, col_idx, name)
    c.fill = AZUL_HEADER
    c.font = font_header
    c.alignment = Alignment(horizontal='center')

# Dados
row = 6
for metrica_label, fn in METRICAS:
    if fn is None:
        # Bloco header
        c = ws.cell(row, 1, metrica_label)
        c.fill = CINZA_BLOCO
        c.font = font_bloco
        c.alignment = Alignment(horizontal='left')
        for col_idx in range(2, len(LANCAMENTOS) + 2):
            ws.cell(row, col_idx).fill = CINZA_BLOCO
        row += 1
        continue

    ws.cell(row, 1, metrica_label).font = font_normal
    ws.cell(row, 1).alignment = Alignment(horizontal='left')

    for col_idx, name in enumerate(LANCAMENTOS, start=2):
        m = data.get(name, {})
        val = fn(m)
        c = ws.cell(row, col_idx, val)
        c.font = font_normal
        c.alignment = Alignment(horizontal='center')

        # Cor especial para ganho de margem
        if metrica_label == 'Ganho de Margem vs CF (R$)' and val not in ('—', '* sem ctrl'):
            raw = m.get('ganho_margem')
            if raw is not None:
                c.fill = VERDE_GANHO if raw > 0 else VERMELHO_CF
        elif metrica_label == 'Margem Total (R$)':
            raw = m.get('margem_total')
            if raw is not None and raw < 0:
                c.fill = VERMELHO_CF
    row += 1

# Larguras
ws.column_dimensions['A'].width = 48
for col_idx in range(2, len(LANCAMENTOS) + 2):
    ws.column_dimensions[get_column_letter(col_idx)].width = 18

# Nota de rodapé
row += 1
ws.cell(row, 1, '* Sem ctrl = LF45 (controle R$306, sem conversões) e LF46 (sem campanhas controle). Contrafactual não calculável.').font = Font(size=8, italic=True, color='888888')

wb.save(EVOLUCAO_XLSX)
print(f"Sheet 'Margem & Contrafactual' salva em: {EVOLUCAO_XLSX.name}\n")


# ─────────────────────────────────────────────────────────────────────────────
# 5. GRÁFICOS
# ─────────────────────────────────────────────────────────────────────────────

plt.rcParams.update({'font.family': 'sans-serif', 'axes.spines.top': False, 'axes.spines.right': False})

AZUL    = '#2563EB'
CINZA   = '#94A3B8'
LARANJA = '#F97316'
VERDE   = '#10B981'
VERM    = '#EF4444'
ROXO    = '#7C3AED'

# Lançamentos com controle válido (para análise contrafactual)
com_ctrl = [n for n in LANCAMENTOS if data[n].get('roas_ctrl') and data[n]['roas_ctrl'] > 0]
# Todos com ROAS ML definido
com_ml   = [n for n in LANCAMENTOS if data[n].get('roas_ml')]

x_all    = np.arange(len(LANCAMENTOS))
x_ctrl   = np.arange(len(com_ctrl))


# ── Gráfico 1: ROAS ML vs Controle vs Total ───────────────────────────────
fig, ax = plt.subplots(figsize=(13, 6))

roas_ml_vals   = [data[n].get('roas_ml')    or np.nan for n in LANCAMENTOS]
roas_ctrl_vals = [data[n].get('roas_ctrl')  or np.nan for n in LANCAMENTOS]
roas_tot_vals  = [data[n].get('roas_total') or np.nan for n in LANCAMENTOS]

ax.plot(x_all, roas_ml_vals,   'o-', color=AZUL,   linewidth=2.2, markersize=8, label='ROAS ML')
ax.plot(x_all, roas_ctrl_vals, 's--',color=CINZA,  linewidth=2.0, markersize=7, label='ROAS Controle')
ax.plot(x_all, roas_tot_vals,  '^-', color=LARANJA,linewidth=2.0, markersize=7, label='ROAS Total Lançamento', alpha=0.85)

for i, (v_ml, v_tot) in enumerate(zip(roas_ml_vals, roas_tot_vals)):
    if not np.isnan(v_ml):
        ax.annotate(f'{v_ml:.2f}x', (i, v_ml), textcoords='offset points', xytext=(0, 10), ha='center', fontsize=8.5, color=AZUL, fontweight='bold')
    if not np.isnan(v_tot):
        ax.annotate(f'{v_tot:.2f}x', (i, v_tot), textcoords='offset points', xytext=(0, -16), ha='center', fontsize=8.5, color=LARANJA)

ax.axhline(1.0, color='red', linestyle=':', linewidth=1, alpha=0.5)
ax.set_xticks(x_all)
ax.set_xticklabels(LANCAMENTOS, fontsize=11)
ax.set_ylabel('ROAS', fontsize=11)
ax.set_title('ROAS por Lançamento: ML vs Controle vs Total do Negócio\n(ROAS Total = toda a receita / todo o gasto do lançamento)', fontsize=13, fontweight='bold', pad=10)
ax.legend(fontsize=10)
ax.grid(axis='y', alpha=0.3)
ax.set_ylim(0, max([v for v in roas_ml_vals if not np.isnan(v)]) * 1.3)

# Nota para pontos ausentes
ax.annotate('sem ctrl', (LANCAMENTOS.index('LF45'), roas_ctrl_vals[LANCAMENTOS.index('LF45')]),
            textcoords='offset points', xytext=(0, 12), ha='center', fontsize=7.5, color='#888')
ax.annotate('sem ctrl', (LANCAMENTOS.index('LF46'), 0.3),
            ha='center', fontsize=7.5, color='#888')

plt.tight_layout()
plt.savefig(GRAFICOS_DIR / '01_roas_ml_controle_total.png', dpi=180, bbox_inches='tight')
plt.close()


# ── Gráfico 2: Margem Real vs Contrafactual ────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 6))
W = 0.35

margem_real_cf = [data[n]['margem_total'] / 1000 for n in com_ctrl]
margem_cf_vals = [data[n]['margem_cf']    / 1000 for n in com_ctrl]

b1 = ax.bar(x_ctrl - W/2, margem_real_cf, W, label='Margem Real (ML + Ctrl)', color=AZUL,  alpha=0.88)
b2 = ax.bar(x_ctrl + W/2, margem_cf_vals, W, label='Margem Contrafactual (sem ML)', color=CINZA, alpha=0.80)

for bar, v in zip(b1, margem_real_cf):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + (1 if v >= 0 else -8),
            f'R${v:.0f}k', ha='center', va='bottom', fontsize=8.5, color=AZUL, fontweight='bold')
for bar, v in zip(b2, margem_cf_vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + (1 if v >= 0 else -8),
            f'R${v:.0f}k', ha='center', va='bottom', fontsize=8.5, color='#555')

ax.axhline(0, color='black', linewidth=0.8)
ax.set_xticks(x_ctrl)
ax.set_xticklabels(com_ctrl, fontsize=11)
ax.set_ylabel('Margem de Contribuição (R$ mil)', fontsize=11)
ax.set_title('Margem Real vs Contrafactual\n"e se todo o gasto do lançamento fosse ao ROAS Controle?"', fontsize=13, fontweight='bold', pad=10)
ax.legend(fontsize=10)
ax.grid(axis='y', alpha=0.3)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'R${v:.0f}k'))

plt.tight_layout()
plt.savefig(GRAFICOS_DIR / '02_margem_real_vs_contrafactual.png', dpi=180, bbox_inches='tight')
plt.close()


# ── Gráfico 3: Ganho de Margem absoluto ────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5.5))

ganhos = [data[n]['ganho_margem'] / 1000 for n in com_ctrl]
cores  = [VERDE if g > 0 else VERM for g in ganhos]

bars = ax.bar(x_ctrl, ganhos, 0.55, color=cores, alpha=0.88)
for bar, v in zip(bars, ganhos):
    va  = 'bottom' if v >= 0 else 'top'
    off = 1 if v >= 0 else -1
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + off,
            f'R${v:+.0f}k', ha='center', va=va, fontsize=9.5, fontweight='bold',
            color=bar.get_facecolor())

total_ganho = sum(ganhos)
ax.axhline(0, color='black', linewidth=0.8)
ax.set_xticks(x_ctrl)
ax.set_xticklabels(com_ctrl, fontsize=11)
ax.set_ylabel('Ganho de Margem (R$ mil)', fontsize=11)
ax.set_title(f'Ganho de Margem atribuído ao ML vs Contrafactual\nAcumulado (LF40–LF44): R${total_ganho:+.0f}k', fontsize=13, fontweight='bold', pad=10)
ax.grid(axis='y', alpha=0.3)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'R${v:+.0f}k'))

plt.tight_layout()
plt.savefig(GRAFICOS_DIR / '03_ganho_margem_vs_contrafactual.png', dpi=180, bbox_inches='tight')
plt.close()


# ── Gráfico 4: Budget ML% + ROAS Total ────────────────────────────────────
fig, ax1 = plt.subplots(figsize=(13, 6))
ax2 = ax1.twinx()

gasto_ml_k   = [data[n]['gasto_ml']    / 1000 for n in LANCAMENTOS]
gasto_ctrl_k = [data[n]['gasto_ctrl']  / 1000 if data[n]['gasto_ctrl'] else 0 for n in LANCAMENTOS]
roas_tot     = [data[n]['roas_total']  or np.nan for n in LANCAMENTOS]

b1 = ax1.bar(x_all, gasto_ml_k,   0.55, label='Gasto ML', color=AZUL, alpha=0.88)
b2 = ax1.bar(x_all, gasto_ctrl_k, 0.55, bottom=gasto_ml_k, label='Gasto Controle', color=CINZA, alpha=0.80)

ax2.plot(x_all, roas_tot, 'D--', color=LARANJA, linewidth=2.2, markersize=8, label='ROAS Total', zorder=5)
for i, v in enumerate(roas_tot):
    if not np.isnan(v):
        ax2.annotate(f'{v:.2f}x', (i, v), textcoords='offset points', xytext=(0, 10),
                     ha='center', fontsize=8.5, color=LARANJA, fontweight='bold')

ax1.set_xticks(x_all)
ax1.set_xticklabels(LANCAMENTOS, fontsize=11)
ax1.set_ylabel('Gasto (R$ mil)', fontsize=11)
ax2.set_ylabel('ROAS Total', fontsize=11, color=LARANJA)
ax2.tick_params(axis='y', labelcolor=LARANJA)
ax2.set_ylim(0, max([v for v in roas_tot if not np.isnan(v)]) * 1.5)

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=10, loc='upper left')
ax1.set_title('Alocação de Budget (ML vs Controle) e ROAS Total do Lançamento', fontsize=13, fontweight='bold', pad=10)
ax1.grid(axis='y', alpha=0.3)
ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'R${v:.0f}k'))

plt.tight_layout()
plt.savefig(GRAFICOS_DIR / '04_budget_ml_vs_roas_total.png', dpi=180, bbox_inches='tight')
plt.close()


# ── Gráfico 5: Margem Total empilhada ML + Controle ───────────────────────
fig, ax = plt.subplots(figsize=(13, 6))

margem_ml_k   = [max(data[n]['margem_ml']   or 0, 0) / 1000 for n in LANCAMENTOS]
margem_ctrl_k = [max(data[n]['margem_ctrl'] or 0, 0) / 1000 for n in LANCAMENTOS]
margem_neg_k  = [min(data[n]['margem_total'] or 0, 0) / 1000 for n in LANCAMENTOS]  # partes negativas

ax.bar(x_all, margem_ml_k,   0.55, label='Margem ML', color=AZUL, alpha=0.90)
ax.bar(x_all, margem_ctrl_k, 0.55, bottom=margem_ml_k, label='Margem Controle', color=CINZA, alpha=0.80)
ax.bar(x_all, margem_neg_k,  0.55, color=VERM, alpha=0.70, label='Margem negativa')

# Total no topo
for i, n in enumerate(LANCAMENTOS):
    tot = (data[n]['margem_total'] or 0) / 1000
    ax.text(i, max(tot, 0) + 1, f'R${tot:.0f}k',
            ha='center', va='bottom', fontsize=8.5, fontweight='bold', color='#333')

ax.axhline(0, color='black', linewidth=0.8)
ax.set_xticks(x_all)
ax.set_xticklabels(LANCAMENTOS, fontsize=11)
ax.set_ylabel('Margem de Contribuição (R$ mil)', fontsize=11)
ax.set_title('Evolução da Margem Total do Negócio por Lançamento\n(ML + Controle, rastreada)', fontsize=13, fontweight='bold', pad=10)
ax.legend(fontsize=10)
ax.grid(axis='y', alpha=0.3)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'R${v:.0f}k'))

plt.tight_layout()
plt.savefig(GRAFICOS_DIR / '05_margem_total_evolucao.png', dpi=180, bbox_inches='tight')
plt.close()


print("Gráficos gerados:")
for f in sorted(GRAFICOS_DIR.glob('0*.png')):
    print(f"  {f.name}")

print("\nConcluído.")
