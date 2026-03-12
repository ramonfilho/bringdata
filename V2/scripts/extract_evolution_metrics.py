"""
Extract enhanced ML evolution metrics:
- AUC, CPA, D concentrations from validation xlsx reports
- Lead count, survey responses from each report's sheets
- CAPI events sent + D10% from Cloud SQL backup + Railway
"""

import os
import sys
import re
import gzip
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# Auto-load .env
_env_file = Path(__file__).parent.parent / '.env'
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

REPORTS = [
    {
        'name': 'DEV19',
        'xlsx': 'V2/outputs/validation/19:01 - 25:01/validation_report_FECHAMENTO_2026-01-19_to_2026-01-25_20260309_142121.xlsx',
        'cap_start': '2026-12-16',  # NOTE: 2025-12-16
        'cap_end':   '2026-01-14',
        'vendas_start': '2026-01-19',
        'vendas_end':   '2026-01-25',
        'source': 'cloudsql',
    },
    {
        'name': 'LF43',
        'xlsx': 'V2/outputs/validation/02:02 - 08:02/validation_report_FECHAMENTO_2026-02-02_to_2026-02-08_20260309_135755.xlsx',
        'cap_start': '2026-01-13',
        'cap_end':   '2026-01-26',
        'vendas_start': '2026-02-02',
        'vendas_end':   '2026-02-08',
        'source': 'cloudsql',
    },
    {
        'name': 'LF44',
        'xlsx': 'V2/outputs/validation/09:02 - 15:02/validation_report_FECHAMENTO_2026-02-09_to_2026-02-15_20260309_134446.xlsx',
        'cap_start': '2026-01-27',
        'cap_end':   '2026-02-03',
        'vendas_start': '2026-02-09',
        'vendas_end':   '2026-02-15',
        'source': 'cloudsql',
    },
    {
        'name': 'LF45',
        'xlsx': 'V2/outputs/validation/02:03 - 08:03/validation_report_FECHAMENTO_2026-03-02_to_2026-03-08_20260309_133352.xlsx',
        'cap_start': '2026-02-03',
        'cap_end':   '2026-02-23',
        'vendas_start': '2026-03-02',
        'vendas_end':   '2026-03-08',
        'source': 'mixed',  # cloudsql until 2026-02-17, railway from 2026-02-18
    },
]

BASE = Path('/Users/ramonmoreira/Desktop/smart_ads')
CLOUDSQL_PATH = BASE / 'V2/data/backups/cloud-sql-final-export-20260225.sql'

# ─────────────────────────────────────────────────────────────────────────────
# 1. PARSE CLOUD SQL BACKUP
# ─────────────────────────────────────────────────────────────────────────────
print("Parsing Cloud SQL backup...")

# Column indices in the COPY data (0-based after splitting by tab)
# Based on confirmed column order from summary:
# 0=id,1=email,2=name,3=phone,4=fbp,5=fbc,6=event_id,7=user_agent,
# 8=client_ip,9=event_source_url,10=utm_source,11=utm_medium,12=utm_campaign,
# 13=utm_term,14=utm_content,15=tem_comp,16=created_at,17=updated_at,
# 18=first_name,19=last_name,20=capi_sent_at,21=capi_response_status,...
# 36=lead_score,37=decil,38=scored_at

COL_EMAIL = 1
COL_CREATED_AT = 16
COL_CAPI_SENT_AT = 20
COL_CAPI_STATUS = 21
COL_LEAD_SCORE = 36
COL_DECIL = 37

cloudsql_records = []
in_copy = False

with open(CLOUDSQL_PATH, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        if line.startswith('COPY public.leads_capi'):
            in_copy = True
            continue
        if in_copy:
            if line.strip() == '\\.' or line.startswith('--') or not line.strip():
                in_copy = False
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 38:
                continue
            email = parts[COL_EMAIL]
            created_at = parts[COL_CREATED_AT]
            capi_sent_at = parts[COL_CAPI_SENT_AT]
            capi_status = parts[COL_CAPI_STATUS]
            lead_score = parts[COL_LEAD_SCORE]
            decil = parts[COL_DECIL]

            cloudsql_records.append({
                'email': email,
                'created_at': created_at[:10] if created_at and created_at != '\\N' else None,
                'capi_sent_at': capi_sent_at[:10] if capi_sent_at and capi_sent_at != '\\N' else None,
                'capi_status': capi_status if capi_status != '\\N' else None,
                'lead_score': lead_score if lead_score != '\\N' else None,
                'decil': decil if decil != '\\N' else None,
            })

cloudsql_df = pd.DataFrame(cloudsql_records)
cloudsql_df['created_at'] = pd.to_datetime(cloudsql_df['created_at'], errors='coerce')
print(f"  Cloud SQL: {len(cloudsql_df):,} records, date range: {cloudsql_df['created_at'].min()} → {cloudsql_df['created_at'].max()}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUERY RAILWAY
# ─────────────────────────────────────────────────────────────────────────────
railway_df = pd.DataFrame()
try:
    import pg8000.native
    conn = pg8000.native.Connection(
        host=os.environ.get('RAILWAY_DB_HOST', 'shortline.proxy.rlwy.net'),
        port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
        database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
        user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
        password=os.environ['RAILWAY_DB_PASSWORD'],
        ssl_context=True,
    )
    rows = conn.run("""
        SELECT email, "createdAt", "capiSentAt", "capiResponseStatus", "leadScore", decil
        FROM "Lead"
        WHERE "createdAt" >= '2026-02-03'
        ORDER BY "createdAt"
    """)
    railway_df = pd.DataFrame(rows, columns=['email', 'created_at', 'capi_sent_at', 'capi_status', 'lead_score', 'decil'])
    railway_df['created_at'] = pd.to_datetime(railway_df['created_at'], utc=True).dt.tz_convert(None)
    print(f"  Railway: {len(railway_df):,} records, date range: {railway_df['created_at'].min()} → {railway_df['created_at'].max()}")
    conn.close()
except Exception as e:
    print(f"  Railway connection failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. COMPUTE METRICS PER LANÇAMENTO
# ─────────────────────────────────────────────────────────────────────────────

def get_capi_stats(cap_start, cap_end, source):
    """Get CAPI events sent + D10% for a captação period."""
    start = pd.Timestamp(cap_start)
    end = pd.Timestamp(cap_end)

    # Merge cloudsql and railway as needed
    frames = []

    # Cloud SQL covers up to Feb 25
    mask = (cloudsql_df['created_at'] >= start) & (cloudsql_df['created_at'] <= end)
    frames.append(cloudsql_df[mask].copy())

    # Railway from Feb 18 onward
    if source in ('railway', 'mixed') and not railway_df.empty:
        mask_r = (railway_df['created_at'] >= start) & (railway_df['created_at'] <= end)
        frames.append(railway_df[mask_r].copy())

    if not frames or all(f.empty for f in frames):
        return {'capi_sent': 0, 'd10_pct': 0, 'total_leads': 0, 'scored_leads': 0}

    df = pd.concat(frames, ignore_index=True)
    # Dedup by email — keep last (most recent record)
    df = df.drop_duplicates(subset=['email'], keep='last')

    total = len(df)
    sent = df['capi_sent_at'].notna().sum()

    scored = df[df['decil'].notna() & (df['decil'] != '')]
    n_scored = len(scored)
    d10 = (scored['decil'] == 'D10').sum() if n_scored > 0 else 0
    d10_pct = d10 / n_scored * 100 if n_scored > 0 else 0

    return {
        'total_leads_db': total,
        'capi_sent': int(sent),
        'scored_leads': n_scored,
        'd10_count': int(d10),
        'd10_pct': round(d10_pct, 1),
    }

# ─────────────────────────────────────────────────────────────────────────────
# 4. EXTRACT METRICS FROM VALIDATION XLSX
# ─────────────────────────────────────────────────────────────────────────────

def extract_xlsx_metrics(xlsx_path):
    """Extract key metrics from validation report xlsx."""
    path = BASE / xlsx_path
    if not path.exists():
        print(f"  NOT FOUND: {path}")
        return {}

    xl = pd.ExcelFile(path)
    print(f"  Sheets in {path.name}: {xl.sheet_names}")

    metrics = {}

    # Try to get summary/overview sheet
    for sheet_name in xl.sheet_names:
        sn = sheet_name.lower()
        if 'resumo' in sn or 'summary' in sn or 'overview' in sn:
            df = xl.parse(sheet_name, header=None)
            print(f"\n  --- {sheet_name} ---")
            print(df.to_string())
            break

    # Try ML performance sheet
    for sheet_name in xl.sheet_names:
        sn = sheet_name.lower()
        if 'ml' in sn or 'performance' in sn or 'decil' in sn:
            df = xl.parse(sheet_name)
            print(f"\n  --- {sheet_name} ---")
            print(df.head(20).to_string())
            metrics['ml_sheet'] = df
            break

    return metrics

print("\n" + "="*60)
print("EXTRACTING XLSX METRICS")
print("="*60)

all_data = []

for r in REPORTS:
    print(f"\n{'='*50}")
    print(f"  {r['name']}: {r['cap_start']} → {r['cap_end']}")

    capi_stats = get_capi_stats(r['cap_start'], r['cap_end'], r['source'])
    print(f"  CAPI stats: {capi_stats}")

    xlsx_metrics = extract_xlsx_metrics(r['xlsx'])

    all_data.append({
        'lancamento': r['name'],
        'cap_start': r['cap_start'],
        'cap_end': r['cap_end'],
        'vendas_start': r['vendas_start'],
        'vendas_end': r['vendas_end'],
        **capi_stats,
    })

print("\n\nSUMMARY TABLE:")
summary_df = pd.DataFrame(all_data)
print(summary_df.to_string())
