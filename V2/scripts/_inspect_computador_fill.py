"""Ad-hoc read-only: computador fill-rate in Lead.pesquisa vs survey-recoverable, multiple windows."""
import os, json, pg8000.native
from collections import Counter

def env(k, d=None):
    for line in open('/Users/ramonmoreira/Desktop/bring_data/V2/.env'):
        line = line.strip()
        if line.startswith(k + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return os.environ.get(k, d)

c = pg8000.native.Connection(
    host=env('RAILWAY_DB_HOST'), port=int(env('RAILWAY_DB_PORT', '11594')),
    database=env('RAILWAY_DB_NAME', 'railway'), user=env('RAILWAY_DB_USER', 'postgres'),
    password=env('RAILWAY_DB_PASSWORD'), ssl_context=True, timeout=90)

for win in ('7 days', '30 days', '90 days'):
    rows = c.run(f"""SELECT pesquisa FROM "Lead"
                     WHERE "createdAt" >= now() - interval '{win}'""")
    total = len(rows)
    pres_key = 0      # key exists
    nonempty = 0      # value present and not '' / None-ish
    vals = Counter()
    for (p,) in rows:
        if p is None:
            vals['<pesquisa NULL>'] += 1
            continue
        try:
            d = p if isinstance(p, dict) else json.loads(p)
        except Exception:
            vals['<unparseable>'] += 1
            continue
        if 'computador' in d:
            pres_key += 1
            v = d.get('computador')
            sv = ('' if v is None else str(v)).strip()
            vals[sv if sv != '' else '<empty str>'] += 1
            if sv != '' and sv.lower() not in ('none', 'null', 'nan'):
                nonempty += 1
        else:
            vals['<key absent>'] += 1
    print(f"\n=== Lead.pesquisa.computador — window {win} ===")
    print(f"  total Lead rows:        {total}")
    if total:
        print(f"  key 'computador' exists: {pres_key} ({pres_key*100.0/total:.1f}%)")
        print(f"  non-empty value:         {nonempty} ({nonempty*100.0/total:.1f}%)")
    print("  value distribution (top):")
    for v, n in vals.most_common(10):
        print(f"    {str(v)[:30]:30s} {n}")

# also leadScore presence when computador empty: does pipeline still score them?
print("\n=== Lead (7d): scored even when computador empty? ===")
r = c.run("""
  SELECT
    count(*) total,
    count(*) FILTER (WHERE coalesce(nullif(trim(pesquisa->>'computador'),''),'X')='X') AS computador_blank,
    count(*) FILTER (WHERE coalesce(nullif(trim(pesquisa->>'computador'),''),'X')='X'
                       AND "leadScore" IS NOT NULL) AS blank_but_scored,
    count(*) FILTER (WHERE coalesce(nullif(trim(pesquisa->>'computador'),''),'X')='X'
                       AND "capiSentAt" IS NOT NULL) AS blank_but_capi_sent
  FROM "Lead" WHERE "createdAt" >= now() - interval '7 days'
""")[0]
print(f"  total={r[0]} | computador_blank={r[1]} | blank_but_scored={r[2]} | blank_but_capi_sent={r[3]}")

c.close()
print("\nDONE")
