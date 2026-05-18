"""Ad-hoc read-only: does Pipeline B already fire CAPI? UTM join feasibility? Contact fields?"""
import os, json, pg8000.native

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

print("=== integration_logs: distinct integration / eventType / status (7d) ===")
for r in c.run("""SELECT integration, "eventType", status, count(*)
                  FROM integration_logs WHERE "createdAt" >= now() - interval '7 days'
                  GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 40"""):
    print(f"  {str(r[0]):20s} {str(r[1]):28s} {str(r[2]):12s} {r[3]}")

print("\n=== integration_logs sample requestPayload (most recent CAPI-ish) ===")
rows = c.run("""SELECT integration, "eventType", "requestPayload"
                FROM integration_logs
                WHERE "createdAt" >= now() - interval '7 days'
                ORDER BY "createdAt" DESC LIMIT 5""")
for integ, et, rp in rows:
    s = json.dumps(rp)[:900] if rp is not None else None
    print(f"\n  [{integ} / {et}]\n  {s}")

print("\n=== integration_logs: rows that look like Meta/CAPI (7d) ===")
for r in c.run("""SELECT count(*) FROM integration_logs
                  WHERE "createdAt" >= now() - interval '7 days'
                  AND (lower(integration) LIKE '%meta%' OR lower(integration) LIKE '%face%'
                       OR lower(integration) LIKE '%capi%' OR lower("eventType") LIKE '%lead%')"""):
    print("  count:", r[0])

print("\n=== UTMTracking cardinality per email (7d) ===")
for r in c.run("""SELECT count(*) total, count(DISTINCT "clientEmail") distinct_emails,
                          round(count(*)::numeric / NULLIF(count(DISTINCT "clientEmail"),0),2) rows_per_email
                   FROM "UTMTracking" WHERE "trackedAt" >= now() - interval '7 days'"""):
    print(f"  rows={r[0]} distinct_emails={r[1]} rows_per_email={r[2]}")

print("\n=== UTMTracking source distribution (7d) ===")
for r in c.run("""SELECT lower(trim(source)), count(*) FROM "UTMTracking"
                  WHERE "trackedAt" >= now() - interval '7 days'
                  GROUP BY 1 ORDER BY 2 DESC LIMIT 12"""):
    print(f"  {str(r[0]):24s} {r[1]}")

print("\n=== lead_surveys: do we have a UTMTracking match? (7d) ===")
for r in c.run("""
  SELECT count(*) ls_rows,
         count(u.em) ls_with_utm
  FROM (SELECT lower(trim("clientEmail")) em, "submittedAt" FROM lead_surveys
        WHERE "submittedAt" >= now() - interval '7 days') s
  LEFT JOIN (SELECT DISTINCT lower(trim("clientEmail")) em FROM "UTMTracking"
             WHERE "trackedAt" >= now() - interval '14 days') u ON u.em = s.em"""):
    print(f"  lead_surveys rows (7d): {r[0]}  | with a UTMTracking email match: {r[1]}")

print("\n=== lead_surveys sample (eventId, ip present?) ===")
for r in c.run("""SELECT id, "clientEmail", "eventId", ip, "interesseEvento", "submittedAt"
                  FROM lead_surveys ORDER BY "submittedAt" DESC LIMIT 5"""):
    print(f"  id={r[0][:14]} email={str(r[1])[:28]:28s} eventId={str(r[2])[:18]:18s} ip={str(r[3]):16s} interesse={str(r[4])[:18]}")

print("\n=== Lead: is 'computador' inside pesquisa always present? sample distinct keys ===")
rows = c.run("""SELECT pesquisa FROM "Lead" WHERE pesquisa IS NOT NULL
                AND "createdAt" >= now() - interval '2 days' LIMIT 3""")
for (p,) in rows:
    try:
        d = p if isinstance(p, dict) else json.loads(p)
        print("  keys:", sorted(d.keys()))
    except Exception as e:
        print("  parse err:", e)

c.close()
print("\nDONE")
