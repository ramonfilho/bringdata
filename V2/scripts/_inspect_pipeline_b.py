"""Ad-hoc: schema + overlap inspection for Pipeline B (lead_surveys & friends). Read-only."""
import os, pg8000.native

def env(k, d=None):
    for line in open('/Users/ramonmoreira/Desktop/bring_data/V2/.env'):
        line = line.strip()
        if line.startswith(k + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return os.environ.get(k, d)

c = pg8000.native.Connection(
    host=env('RAILWAY_DB_HOST'), port=int(env('RAILWAY_DB_PORT', '11594')),
    database=env('RAILWAY_DB_NAME', 'railway'), user=env('RAILWAY_DB_USER', 'postgres'),
    password=env('RAILWAY_DB_PASSWORD'), ssl_context=True, timeout=40)

print("=== ALL TABLES ===")
rows = c.run("""SELECT table_name FROM information_schema.tables
                WHERE table_schema='public' ORDER BY table_name""")
for r in rows:
    print(" ", r[0])

for tbl in ('lead_surveys', 'UTMTracking', 'utm_tracking', 'integration_logs', 'IntegrationLog'):
    try:
        cols = c.run("""SELECT column_name, data_type FROM information_schema.columns
                        WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position""", t=tbl)
        if not cols:
            continue
        print(f"\n=== SCHEMA {tbl} ===")
        for cn, dt in cols:
            print(f"  {cn:32s} {dt}")
        n = c.run(f'SELECT count(*) FROM "{tbl}"')[0][0]
        print(f"  -> total rows: {n}")
    except Exception as e:
        print(f"  (skip {tbl}: {e})")

# Overlap lead_surveys vs Lead, last 5 days, by gmail-normalized email
print("\n=== OVERLAP lead_surveys.clientEmail vs Lead.email (last 7 days) ===")
try:
    q = """
    WITH ls AS (
      SELECT DISTINCT lower(trim("clientEmail")) AS em
      FROM lead_surveys WHERE "submittedAt" >= now() - interval '7 days'
    ), ld AS (
      SELECT DISTINCT lower(trim(email)) AS em
      FROM "Lead" WHERE "createdAt" >= now() - interval '7 days'
    )
    SELECT
      (SELECT count(*) FROM ls) AS ls_distinct,
      (SELECT count(*) FROM ld) AS lead_distinct,
      (SELECT count(*) FROM ls JOIN ld USING(em)) AS overlap;
    """
    r = c.run(q)[0]
    print(f"  lead_surveys distinct emails (7d): {r[0]}")
    print(f"  Lead distinct emails (7d):         {r[1]}")
    print(f"  overlap (same email both):         {r[2]}")
except Exception as e:
    print("  err:", e)

# How many lead_surveys rows have a matching Lead that ALREADY fired CAPI
print("\n=== lead_surveys -> matching Lead capiSentAt status (last 7 days) ===")
try:
    q = """
    SELECT
      count(*) AS ls_rows,
      count(l.email) AS has_matching_lead,
      count(l."capiSentAt") AS matching_lead_capi_sent
    FROM lead_surveys s
    LEFT JOIN "Lead" l ON lower(trim(l.email)) = lower(trim(s."clientEmail"))
                       AND l."createdAt" >= now() - interval '8 days'
    WHERE s."submittedAt" >= now() - interval '7 days';
    """
    r = c.run(q)[0]
    print(f"  lead_surveys rows (7d):                 {r[0]}")
    print(f"  ...with a matching Lead row:            {r[1]}")
    print(f"  ...whose matching Lead already CAPI'd:  {r[2]}")
except Exception as e:
    print("  err:", e)

c.close()
print("\nDONE")
