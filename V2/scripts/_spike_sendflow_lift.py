"""
SPIKE OFFLINE — LIFT + REDUNDÂNCIA da feature "entrou no grupo de WhatsApp".
Reusa entrypoint canônico do pipeline de validação (read-only):
  - validation.backtest_data.load_match_spend_for_lf  -> leads + `converted`
  - core.utils.normalizar_telefone_robusto / normalizar_email
Decil de produção: lido direto de "Lead".decil por email (rico em mar–mai).
Novo = join SendFlow + métricas. Roda de V2/ com PYTHONPATH=.
"""
import os, glob, csv
import pandas as pd
from datetime import datetime

for line in open('.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())

import yaml, pg8000.native as pg
from src.core.utils import normalizar_telefone_robusto, normalizar_email
from src.validation.backtest_data import load_match_spend_for_lf

def canon(x):
    n = normalizar_telefone_robusto(x, country_code=55)
    if not n: return None
    if len(n) == 11: n = n[:2] + n[3:]
    return n if len(n) == 10 else None

def conn():
    return pg.Connection(host=os.environ.get('RAILWAY_DB_HOST','shortline.proxy.rlwy.net'),
                         port=int(os.environ.get('RAILWAY_DB_PORT','11594')),
                         database=os.environ.get('RAILWAY_DB_NAME','railway'),
                         user=os.environ.get('RAILWAY_DB_USER','postgres'),
                         password=os.environ['RAILWAY_DB_PASSWORD'])

# grupos SendFlow
csvs = []
for f in sorted(glob.glob('data/devclub/SendFlow*.csv')):
    ks, dates = set(), []
    with open(f, encoding='utf-8-sig', errors='replace') as fh:
        rd = csv.reader(fh, delimiter=';'); h = next(rd, [])
        idx = {c.strip().lower(): i for i, c in enumerate(h)}; ni, di = idx.get('numero'), idx.get('data')
        for r in rd:
            if ni is not None and ni < len(r):
                k = canon(r[ni])
                if k: ks.add(k)
                if di is not None and di < len(r):
                    try: dates.append(datetime.strptime(r[di].split(',')[0].strip(), '%d/%m/%Y'))
                    except: pass
    if dates: csvs.append({'ks': ks, 'dmin': min(dates), 'dmax': max(dates)})
launches = yaml.safe_load(open('configs/launches.yaml'))
def grupo(lf):
    cs = pd.to_datetime(launches[lf]['cap_start']); ce = pd.to_datetime(launches[lf]['cap_end'])
    best, bov = set(), -1
    for c in csvs:
        ov = (min(ce, c['dmax']) - max(cs, c['dmin'])).days
        if ov > bov: bov, best = ov, c['ks']
    return best

TARGET = ['LF48','LF49','LF50','LF51','LF53','DEV20','LF54','LF55']
POOL = 'outputs/_spike_pool.parquet'
if os.path.exists(POOL):
    P = pd.read_parquet(POOL); print(f"[pool] cache: {len(P)} linhas")
else:
    parts = []
    cn = conn()
    for lf in TARGET:
        try: df = load_match_spend_for_lf(lf, include_production_decil=False)
        except Exception as e: print(f"  {lf}: ERRO {e}"); continue
        if df is None or len(df) == 0: continue
        g = grupo(lf)
        df = df.copy()
        df['_k'] = df['telefone'].map(canon)
        df['entrou'] = df['_k'].isin(g)
        df['_lf'] = lf
        # decil de produção direto da Lead, por email, na janela do LF
        cs, ce = launches[lf]['cap_start'], launches[lf]['cap_end']
        ce1 = (pd.to_datetime(ce) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        rows = cn.run('SELECT email, decil FROM "Lead" WHERE "createdAt">=:s AND "createdAt"<:e AND decil IS NOT NULL', s=cs, e=ce1)
        dmap = {}
        for em, dc in rows:
            ne = normalizar_email(em)
            if ne and ne not in dmap: dmap[ne] = dc
        df['_email_n'] = df['email'].map(normalizar_email)
        df['decil_prod'] = df['_email_n'].map(dmap)
        print(f"  {lf}: leads={len(df)} entrou%={100*df['entrou'].mean():.0f} decil_cov={100*df['decil_prod'].notna().mean():.0f}%")
        parts.append(df[['_lf','email','telefone','converted','entrou','decil_prod']])
    P = pd.concat(parts, ignore_index=True)
    os.makedirs('outputs', exist_ok=True); P.to_parquet(POOL, index=False)
    print(f"[pool] salvo {POOL}: {len(P)} linhas")

conv = P['converted'].astype(float); e = P['entrou']
t1, t0 = 100*conv[e].mean(), 100*conv[~e].mean()
print(f"\n=== AGREGADO ===  ENTROU {t1:.2f}% (n={int(e.sum())}) | NÃO {t0:.2f}% (n={int((~e).sum())}) | LIFT {t1/t0:.2f}x")

P['decil_prod'] = pd.to_numeric(P['decil_prod'], errors='coerce')
print(f"cobertura decil no pool: {100*P['decil_prod'].notna().mean():.0f}%")
print("\n=== DENTRO DE CADA DECIL (redundância) ===")
print("decil | n_entrou conv% | n_não conv% | lift")
Pd = P[P['decil_prod'].notna()]
for d in sorted(Pd['decil_prod'].unique()):
    s = Pd[Pd['decil_prod'] == d]; se = s[s['entrou']]; sn = s[~s['entrou']]
    if len(se) < 20 or len(sn) < 20: continue
    te, tn = 100*se['converted'].astype(float).mean(), 100*sn['converted'].astype(float).mean()
    lift = (te/tn) if tn else float('nan')
    print(f"  D{int(d):<2} | {len(se):>5} {te:.2f}% | {len(sn):>5} {tn:.2f}% | {lift:.2f}x")
print("\n=== FIM ===")
