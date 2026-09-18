#!/usr/bin/env python3
"""
Revenue reconciliation: compare real platform data vs validation xlsx for 6 launch periods.
"""

import os
import glob
import pandas as pd
import numpy as np

BASE_DIR = "/Users/ramonmoreira/Desktop/bring_data/V2"

PERIODS = [
    ('LF44',  '02:02 - 08:02', '2026-02-02', '2026-02-08'),
    ('LF45',  '09:02 - 15:02', '2026-02-09', '2026-02-15'),
    ('LF46',  '02:03 - 08:03', '2026-03-02', '2026-03-08'),
    ('LF47',  '09:03 - 15:03', '2026-03-09', '2026-03-15'),
    ('LF47b', '16:03 - 22:03', '2026-03-16', '2026-03-22'),
    ('LF48',  '23:03 - 29:03', '2026-03-23', '2026-03-29'),
]

CACHE_DIR = os.path.join(BASE_DIR, "files/validation/cache")
VALIDATION_DIR = os.path.join(BASE_DIR, "outputs/validation")
EVOLUTION_FILE = os.path.join(BASE_DIR, "outputs/validation/historico/evolucao_ml_devclub_20260402_111415.xlsx")

# --- Load TMB once (all periods combined) ---
tmb_file = os.path.join(BASE_DIR, "data/devclub/contas_a_receber_30032026_0934.xlsx")
tmb_all = pd.read_excel(tmb_file)
tmb_all['Pago em'] = pd.to_datetime(tmb_all['Pago em'])

# --- Load evolution report revenue row ---
# The evolution report uses its own LF numbering by date range.
# Mapping (our label -> evo report column, matched by vendas dates):
#   Our LF44  (02-02 → 02-08) = evo LF43
#   Our LF45  (02-09 → 02-15) = evo LF44
#   Our LF46  (03-02 → 03-08) = evo LF45
#   Our LF47  (03-09 → 03-15) = evo LF46
#   Our LF47b (03-16 → 03-22) = evo LF47
#   Our LF48  (03-23 → 03-29) = evo LF48
evo_df = pd.read_excel(EVOLUTION_FILE, sheet_name='Resumo', header=None)
header_row = evo_df.iloc[3].tolist()    # [Métrica, LF40, LF41, ...]
vendas_inicio = evo_df.iloc[7].tolist() # [Vendas início, date, ...]
vendas_fim    = evo_df.iloc[8].tolist() # [Vendas fim, date, ...]
receita_row   = evo_df.iloc[19].tolist()  # [Receita (R$), ...]

# Build date -> revenue map from evo report
evo_by_date = {}  # (vs, ve) -> revenue
for i in range(1, len(header_row)):
    vs_evo = str(vendas_inicio[i])[:10] if vendas_inicio[i] else None
    ve_evo = str(vendas_fim[i])[:10] if vendas_fim[i] else None
    val = receita_row[i]
    if val and vs_evo and ve_evo:
        if isinstance(val, str):
            val = float(val.replace('R$', '').replace(',', '').strip())
        evo_by_date[(vs_evo, ve_evo)] = float(val)

# Map our periods to evo revenue by date
evo_revenue = {}
for (lf, folder, vs, ve) in PERIODS:
    evo_revenue[lf] = evo_by_date.get((vs, ve))

def fmt_r(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return 'N/A'
    return f"R$ {v:,.0f}"

def fmt_n(n):
    if n is None:
        return 'N/A'
    return str(int(n))

def load_xlsx_detalhes(folder_name, vs, ve):
    """Load the latest xlsx for a period and return its Detalhes tab."""
    folder = os.path.join(VALIDATION_DIR, folder_name)
    pattern = os.path.join(folder, "*.xlsx")
    files = glob.glob(pattern)
    if not files:
        return None
    latest = max(files, key=os.path.getmtime)
    df = pd.read_excel(latest, sheet_name='Detalhes das Conversões', header=None)
    # Row 2 is header, rows 3+ are data
    df.columns = df.iloc[2]
    df = df.iloc[3:].reset_index(drop=True)
    # Parse Valor Venda as numeric
    df['Valor Venda'] = pd.to_numeric(df['Valor Venda'], errors='coerce')
    df['Fonte Venda'] = df['Fonte Venda'].astype(str).str.strip().str.lower()
    return df, latest

def load_guru(vs, ve):
    path = os.path.join(CACHE_DIR, f"guru_{vs}_{ve}_fechamento.parquet")
    if not os.path.exists(path):
        return None, None
    df = pd.read_parquet(path)
    return len(df), df['sale_value'].sum()

def load_hotmart(vs, ve):
    path = os.path.join(CACHE_DIR, f"hotmart_{vs}_{ve}.parquet")
    if not os.path.exists(path):
        return None, None
    df = pd.read_parquet(path)
    return len(df), df['sale_value'].sum()

def load_asaas(vs, ve):
    path = os.path.join(CACHE_DIR, f"asaas_{vs}_{ve}.parquet")
    if not os.path.exists(path):
        return None, None
    df = pd.read_parquet(path)
    return len(df), df['sale_value'].sum()

def load_tmb(vs, ve):
    vs_dt = pd.Timestamp(vs)
    ve_dt = pd.Timestamp(ve)
    mask = (
        (tmb_all['Pago em'] >= vs_dt) &
        (tmb_all['Pago em'] <= ve_dt + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)) &
        (tmb_all['Parcela'] == 0) &
        (tmb_all['Status Pedido'] == 'Efetivado')
    )
    sub = tmb_all[mask]
    return len(sub), sub['Ticket'].sum()

summary_rows = []

for (lf, folder, vs, ve) in PERIODS:
    print("=" * 90)
    print(f"  {lf}  |  {folder}  |  {vs} → {ve}")
    print("=" * 90)

    # Load real platform data
    platforms = {}
    platforms['guru']    = load_guru(vs, ve)
    platforms['hotmart'] = load_hotmart(vs, ve)
    platforms['asaas']   = load_asaas(vs, ve)
    platforms['tmb']     = load_tmb(vs, ve)

    # Load xlsx detalhes
    result = load_xlsx_detalhes(folder, vs, ve)
    if result is None:
        print("  [ERROR] No xlsx found for this period")
        continue
    xlsx_df, xlsx_file = result
    xlsx_filename = os.path.basename(xlsx_file)

    print(f"  Xlsx: {xlsx_filename}")
    print()

    # Build per-platform comparison
    print(f"  {'Platform':<10} | {'N real':>7} | {'Rev real':>14} | {'N xlsx':>7} | {'Rev xlsx':>14} | {'Diff':>12} | Status")
    print(f"  {'-'*10}-+-{'-'*7}-+-{'-'*14}-+-{'-'*7}-+-{'-'*14}-+-{'-'*12}-+--------")

    total_real_n = 0
    total_real_rev = 0.0
    total_xlsx_n = 0
    total_xlsx_rev = 0.0

    for plat_name in ['guru', 'hotmart', 'asaas', 'tmb']:
        real_n, real_rev = platforms[plat_name]

        xlsx_sub = xlsx_df[xlsx_df['Fonte Venda'] == plat_name]
        xlsx_n = len(xlsx_sub)
        xlsx_rev = xlsx_sub['Valor Venda'].sum()

        if real_n is None:
            real_n_str = 'N/A'
            real_rev_str = 'N/A'
            diff = None
            diff_str = 'N/A'
            status = '❓ no cache'
        else:
            real_n_str = str(real_n)
            real_rev_str = fmt_r(real_rev)
            diff = real_rev - xlsx_rev
            diff_str = fmt_r(diff)
            if abs(diff) > 1000:
                status = '⚠️  DIFF'
            else:
                status = 'OK'
            total_real_n += real_n
            total_real_rev += real_rev

        total_xlsx_n += xlsx_n
        total_xlsx_rev += xlsx_rev

        print(f"  {plat_name:<10} | {real_n_str:>7} | {real_rev_str:>14} | {xlsx_n:>7} | {fmt_r(xlsx_rev):>14} | {diff_str:>12} | {status}")

    # Total row
    total_diff = total_real_rev - total_xlsx_rev
    total_diff_str = fmt_r(total_diff)
    total_status = '⚠️  DIFF' if abs(total_diff) > 1000 else 'OK'
    print(f"  {'-'*10}-+-{'-'*7}-+-{'-'*14}-+-{'-'*7}-+-{'-'*14}-+-{'-'*12}-+--------")
    print(f"  {'TOTAL':<10} | {total_real_n:>7} | {fmt_r(total_real_rev):>14} | {total_xlsx_n:>7} | {fmt_r(total_xlsx_rev):>14} | {total_diff_str:>12} | {total_status}")
    print()

    summary_rows.append({
        'LF': lf,
        'Total real': total_real_rev,
        'Total xlsx': total_xlsx_rev,
        'Diff': total_diff,
        'Evo report': evo_revenue.get(lf),
    })

# ---- SUMMARY TABLE ----
print()
print("=" * 90)
print("  SUMMARY TABLE")
print("=" * 90)
print(f"  {'LF':<8} | {'Total real':>14} | {'Total xlsx':>14} | {'Diff real/xlsx':>14} | {'Evo report':>14} | {'Diff real/evo':>14}")
print(f"  {'-'*8}-+-{'-'*14}-+-{'-'*14}-+-{'-'*14}-+-{'-'*14}-+-{'-'*14}")

for row in summary_rows:
    lf = row['LF']
    total_real = row['Total real']
    total_xlsx = row['Total xlsx']
    diff_rx = row['Diff']
    evo = row['Evo report']

    diff_re = (total_real - evo) if evo is not None else None
    status_rx = '⚠️' if abs(diff_rx) > 1000 else ''
    status_re = ('⚠️' if diff_re is not None and abs(diff_re) > 1000 else '') if evo else 'N/A'

    diff_rx_str = fmt_r(diff_rx) + (' ' + status_rx if status_rx else '')
    diff_re_str = (fmt_r(diff_re) + (' ' + status_re if status_re else '')) if evo is not None else 'N/A'
    evo_str = fmt_r(evo) if evo is not None else 'N/A'

    print(f"  {lf:<8} | {fmt_r(total_real):>14} | {fmt_r(total_xlsx):>14} | {diff_rx_str:>14} | {evo_str:>14} | {diff_re_str:>14}")

print()
print("Notes:")
print("  - Diff real/xlsx: positive = real has MORE revenue than xlsx (possible: xlsx filtered some records)")
print("  - Diff real/evo:  positive = our reconciliation is HIGHER than evolution report")
print("  - ⚠️  = difference > R$1,000")
print("  - LF47b not present in evolution report (N/A)")
