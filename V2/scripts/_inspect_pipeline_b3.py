"""Ad-hoc read-only: can we recover computador + fbp/fbc + phone/name for survey leads
from integration_logs JSON within our own Railway DB? Measure coverage."""
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
    password=env('RAILWAY_DB_PASSWORD'), ssl_context=True, timeout=60)

# Distinct integration/eventType to know exact keys
print("=== integration_logs distinct integration/eventType (30d) ===")
for r in c.run("""SELECT integration,"eventType",count(*) FROM integration_logs
                  WHERE "createdAt" >= now() - interval '30 days'
                  GROUP BY 1,2 ORDER BY 3 DESC"""):
    print(f"  {str(r[0]):18s} {str(r[1]):26s} {r[2]}")

# Inspect one n8n_onboarding payload keys + one meta_capi user_data keys
print("\n=== sample n8n_onboarding payload keys ===")
for (rp,) in c.run("""SELECT "requestPayload" FROM integration_logs
                       WHERE integration='n8n_onboarding' AND "requestPayload" IS NOT NULL
                       ORDER BY "createdAt" DESC LIMIT 2"""):
    d = rp if isinstance(rp, dict) else json.loads(rp)
    print("  keys:", sorted(d.keys()), "| tem_computador=", d.get('tem_computador'),
          "| telefone=", str(d.get('telefone'))[:18], "| nome=", str(d.get('nome'))[:24])

print("\n=== sample meta_capi user_data keys ===")
for (rp,) in c.run("""SELECT "requestPayload" FROM integration_logs
                       WHERE integration='meta_capi' AND "requestPayload" IS NOT NULL
                       ORDER BY "createdAt" DESC LIMIT 2"""):
    d = rp if isinstance(rp, dict) else json.loads(rp)
    try:
        ud = d['data'][0]['user_data']
        print("  user_data keys:", sorted(ud.keys()),
              "| fbp?", bool(ud.get('fbp')), "| fbc?", bool(ud.get('fbc')),
              "| ip?", bool(ud.get('client_ip_address')), "| ua?", bool(ud.get('client_user_agent')))
    except Exception as e:
        print("  parse err:", e, "| top keys:", sorted(d.keys()))

# Coverage: for survey leads (7d), join by email to integration_logs and see what we can recover
print("\n=== COVERAGE: lead_surveys (7d) recoverable fields via email JOIN integration_logs ===")
q = """
WITH s AS (
  SELECT id, lower(trim("clientEmail")) em, "submittedAt"
  FROM lead_surveys WHERE "submittedAt" >= now() - interval '7 days'
),
mc AS (  -- meta_capi rows w/ fbp & fbc in cleartext
  SELECT DISTINCT lower(trim("clientEmail")) em
  FROM integration_logs
  WHERE integration='meta_capi'
    AND "requestPayload" #>> '{data,0,user_data,fbp}' IS NOT NULL
    AND "requestPayload" #>> '{data,0,user_data,fbp}' <> ''
    AND "requestPayload" #>> '{data,0,user_data,fbc}' IS NOT NULL
    AND "requestPayload" #>> '{data,0,user_data,fbc}' <> ''
    AND "createdAt" >= now() - interval '14 days'
),
n8 AS (  -- n8n_onboarding w/ tem_computador + telefone
  SELECT DISTINCT lower(trim("clientEmail")) em
  FROM integration_logs
  WHERE integration='n8n_onboarding'
    AND "requestPayload" ->> 'tem_computador' IS NOT NULL
    AND "requestPayload" ->> 'tem_computador' <> ''
    AND "createdAt" >= now() - interval '14 days'
),
n8p AS (  -- n8n_onboarding w/ telefone
  SELECT DISTINCT lower(trim("clientEmail")) em
  FROM integration_logs
  WHERE integration='n8n_onboarding'
    AND "requestPayload" ->> 'telefone' IS NOT NULL
    AND "requestPayload" ->> 'telefone' <> ''
    AND "createdAt" >= now() - interval '14 days'
)
SELECT
  (SELECT count(*) FROM s)                              AS survey_rows_7d,
  (SELECT count(DISTINCT em) FROM s)                    AS survey_distinct_email,
  (SELECT count(*) FROM s WHERE em IN (SELECT em FROM mc))  AS has_fbp_fbc,
  (SELECT count(*) FROM s WHERE em IN (SELECT em FROM n8))  AS has_computador,
  (SELECT count(*) FROM s WHERE em IN (SELECT em FROM n8p)) AS has_phone,
  (SELECT count(*) FROM s WHERE em IN (SELECT em FROM mc)
                              AND em IN (SELECT em FROM n8)) AS has_fbp_fbc_AND_computador;
"""
r = c.run(q)[0]
labels = ['survey_rows_7d','survey_distinct_email','has_fbp_fbc','has_computador',
          'has_phone','has_fbp_fbc_AND_computador']
tot = r[0]
for lab, val in zip(labels, r):
    pct = f"  ({val*100.0/tot:.0f}%)" if (tot and lab not in ('survey_rows_7d','survey_distinct_email')) else ""
    print(f"  {lab:30s} {val}{pct}")

# also: is computador also reachable from activecampaign field 144? quick check
print("\n=== activecampaign field 144 (computador) presence (sample) ===")
for (rp,) in c.run("""SELECT "requestPayload" FROM integration_logs
                       WHERE integration='activecampaign' AND "requestPayload" IS NOT NULL
                       ORDER BY "createdAt" DESC LIMIT 1"""):
    d = rp if isinstance(rp, dict) else json.loads(rp)
    try:
        fvs = d['contact']['contact']['fieldValues']
        f144 = [x.get('value') for x in fvs if str(x.get('field')) == '144']
        print("  field144:", f144)
    except Exception as e:
        print("  parse err:", e)

c.close()
print("\nDONE")
