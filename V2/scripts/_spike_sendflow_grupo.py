"""
SPIKE OFFLINE (scratch, read-only) — feature "entrou no grupo de WhatsApp".
Passo 1: gate de match. Reusa os módulos do pipeline de validação:
  - SalesDataLoader.load_railway_leads   (leads do Railway, tabela Lead)
  - core.utils.normalizar_telefone_robusto  (MESMA chave de telefone do matching)
  - core.client_config.ClientConfig
Único código novo = ler os CSVs "Histórico de atividade" do SendFlow e cruzar.
NÃO toca produção. Roda de V2/ com PYTHONPATH=.
"""
import os, glob, csv, re
import pandas as pd
from datetime import datetime

# --- .env (parse robusto, sem sourcing) ---
for line in open('.env'):
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    os.environ.setdefault(k.strip(), v.strip())

from src.core.client_config import ClientConfig
from src.core.utils import normalizar_telefone_robusto
from src.validation.data_loader import SalesDataLoader

def norm(x):
    return normalizar_telefone_robusto(x, country_code=55)
def last8(x):
    n = norm(x)
    return n[-8:] if n and len(n) >= 8 else None

# --- 1. Leads do Railway (módulo do pipeline) ---
cfg = ClientConfig.from_yaml('configs/clients/devclub.yaml')
leads = SalesDataLoader().load_railway_leads('2026-03-01', '2026-05-31', cfg)
print(f"[leads] {len(leads)} linhas | cols: {list(leads.columns)[:18]}")
if len(leads) == 0:
    print("!! load_railway_leads vazio — tabela Lead sem dados no período (ver schema novo). Parando.")
    raise SystemExit

phcol = 'Telefone' if 'Telefone' in leads.columns else next((c for c in leads.columns if 'tel' in c.lower()), None)
dtcol = 'Data' if 'Data' in leads.columns else next((c for c in leads.columns if c.lower() in ('data','createdat','data_captura','data_processamento')), None)
print(f"[leads] phone_col={phcol!r} date_col={dtcol!r}")
leads['_tn'] = leads[phcol].map(norm)
leads['_t8'] = leads[phcol].map(last8)
leads['_dt'] = pd.to_datetime(leads[dtcol], errors='coerce', dayfirst=False)
print(f"[leads] com telefone normalizado: {leads['_tn'].notna().sum()}  | data válida: {leads['_dt'].notna().sum()}")

# --- 2. Joins SendFlow (código novo) ---
launches = []
for f in sorted(glob.glob('data/devclub/SendFlow*.csv')):
    tn, t8, dates = set(), set(), []
    with open(f, encoding='utf-8-sig', errors='replace') as fh:
        rd = csv.reader(fh, delimiter=';'); hdr = next(rd, [])
        idx = {h.strip().lower(): i for i, h in enumerate(hdr)}
        ni, di = idx.get('numero'), idx.get('data')
        for r in rd:
            if ni is None or ni >= len(r):
                continue
            a, b = norm(r[ni]), last8(r[ni])
            if a: tn.add(a)
            if b: t8.add(b)
            if di is not None and di < len(r):
                try: dates.append(datetime.strptime(r[di].split(',')[0].strip(), '%d/%m/%Y'))
                except: pass
    if dates:
        launches.append({'f': f.split(' - ')[-1], 'tn': tn, 't8': t8,
                         'dmin': min(dates), 'dmax': max(dates)})

g_tn = set().union(*[L['tn'] for L in launches])
g_t8 = set().union(*[L['t8'] for L in launches])
print(f"\n[sendflow] {len(launches)} lançamentos | telefones únicos: norm={len(g_tn)} last8={len(g_t8)}")

# --- 3. Match rate geral (qualquer grupo) ---
base = leads[leads['_tn'].notna()]
mr_norm = base['_tn'].isin(g_tn).mean() * 100
mr_l8   = base['_t8'].isin(g_t8).mean() * 100
print(f"\n=== MATCH RATE GERAL (lead entrou em ALGUM grupo) ===")
print(f"  leads c/ telefone: {len(base)}")
print(f"  match canônico (normalizar_telefone_robusto): {mr_norm:.1f}%")
print(f"  match relaxado (últimos 8 dígitos, ignora 9º): {mr_l8:.1f}%   <- teto")

# --- 4. Por lançamento (alinha lead.data à janela do CSV) ---
print(f"\n=== POR LANÇAMENTO (leads na janela × grupo do mesmo lançamento) ===")
for L in sorted(launches, key=lambda x: x['dmin']):
    win = base[(base['_dt'] >= L['dmin']) & (base['_dt'] <= L['dmax'] + pd.Timedelta(days=1))]
    if len(win) == 0:
        print(f"  {L['dmin'].date()}→{L['dmax'].date()}  leads_janela=0  (sem leads do Lead nessa janela)")
        continue
    m = win['_tn'].isin(L['tn']).mean() * 100
    m8 = win['_t8'].isin(L['t8']).mean() * 100
    print(f"  {L['dmin'].date()}→{L['dmax'].date()}  leads={len(win):>5}  grupo={len(L['tn']):>5}  match={m:.1f}%  (last8={m8:.1f}%)")
print("\n=== FIM Passo 1 ===")
