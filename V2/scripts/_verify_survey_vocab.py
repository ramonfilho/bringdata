"""Ad-hoc READ-ONLY: does lead_surveys, after the EXISTING normalization, yield only
categories the Lead pipeline already produces in prod? Flags silent-degradation risk."""
import os, sys, json, pg8000.native
from collections import Counter

sys.path.insert(0, '/Users/ramonmoreira/Desktop/bring_data/V2')
from api.railway_mapping import (
    _limpar_texto, _normalizar,
    MAPA_FAIXA_SALARIAL, MAPA_OCUPACAO, MAPA_IDADE,
    MAPA_INTERESSE_EVENTO, MAPA_ATRACAO_PROFISSAO,
)

def env(k, d=None):
    for line in open('/Users/ramonmoreira/Desktop/bring_data/V2/.env'):
        line = line.strip()
        if line.startswith(k + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return os.environ.get(k, d)

c = pg8000.native.Connection(
    host=env('RAILWAY_DB_HOST'), port=int(env('RAILWAY_DB_PORT', '11594')),
    database=env('RAILWAY_DB_NAME', 'railway'), user=env('RAILWAY_DB_USER', 'postgres'),
    password=env('RAILWAY_DB_PASSWORD'), ssl_context=True, timeout=60)

# field -> (lead_surveys column, map or None, normalized?, Lead.pesquisa key)
FIELDS = [
    ('idade',              'idade',              MAPA_IDADE,            True,  'idade'),
    ('ocupacao',           'ocupacao',           MAPA_OCUPACAO,         True,  'ocupacao'),
    ('faixaSalarial',      'faixaSalarial',      MAPA_FAIXA_SALARIAL,   True,  'faixaSalarial'),
    ('interesseEvento',    'interesseEvento',    MAPA_INTERESSE_EVENTO, True,  'interesseEvento'),
    ('atracaoProfissao',   'atracaoProfissao',   MAPA_ATRACAO_PROFISSAO,True,  'atracaoProfissao'),
    ('cartaoCredito',      'cartaoCredito',      None,                  True,  'cartaoCredito'),
    ('genero',             'genero',             None,                  False, 'genero'),
    ('estudouProgramacao', 'estudouProgramacao', None,                  False, 'estudouProgramacao'),
    ('faculdade',          'faculdade',          None,                  False, 'faculdade'),
    ('investiuCurso',      'investiuCurso',      None,                  False, 'investiuCurso'),
]

# Build the set of normalized categories the Lead pipeline produces in prod (last 30d)
print("Lendo Lead.pesquisa (30d) para baseline de categorias de produção...")
lead_rows = c.run("""SELECT pesquisa FROM "Lead"
                     WHERE pesquisa IS NOT NULL AND "createdAt" >= now() - interval '30 days'""")
lead_norm = {f[0]: Counter() for f in FIELDS}
for (p,) in lead_rows:
    try:
        d = p if isinstance(p, dict) else json.loads(p)
    except Exception:
        continue
    for fname, _col, mapa, is_norm, lkey in FIELDS:
        raw = d.get(lkey)
        if is_norm:
            out = _normalizar(raw, mapa)
        else:
            out = (str(raw).strip() or None) if raw is not None else None
        if out is not None:
            lead_norm[fname][out] += 1

# Now distinct lead_surveys values per field, normalized the SAME way
print("Lendo lead_surveys (todas as linhas)...\n")
for fname, col, mapa, is_norm, lkey in FIELDS:
    rows = c.run(f'SELECT "{col}", count(*) FROM lead_surveys GROUP BY 1 ORDER BY 2 DESC')
    print(f"================ {fname}  (normalizado={is_norm}, tem_mapa={mapa is not None}) ================")
    prod_cats = set(lead_norm[fname].keys())
    risky = []
    for raw, n in rows:
        if is_norm:
            out = _normalizar(raw, mapa)
            cleaned = _limpar_texto(raw)
            in_map = (mapa is not None) and (cleaned in mapa)
        else:
            out = (str(raw).strip() or None) if raw is not None else None
            cleaned = None
            in_map = None
        status = 'OK'
        if out is None:
            status = 'NULL'
        elif out not in prod_cats:
            status = '*** NÃO EXISTE NO LEAD (risco) ***'
            risky.append((raw, out, n))
        flag_map = '' if in_map is None else (' [via mapa]' if in_map else ' [PASSTHROUGH cru]')
        print(f"  raw={str(raw)[:42]:42s} n={n:<4} -> '{out}'{flag_map}  {status}")
    if risky:
        print(f"  >>> {fname}: {len(risky)} valor(es) que produzem categoria inexistente no funil Lead:")
        for raw, out, n in risky:
            print(f"      '{raw}'  ->  '{out}'  ({n} linhas)")
    print(f"  (categorias que o Lead produz p/ {fname}: {sorted(prod_cats)})\n")

c.close()
print("DONE")
