#!/usr/bin/env bash
# Codifica os alertas de confiabilidade da pipeline de scoring (frente D do
# endurecimento pós-apagão 22-23/07/2026). Idempotente por displayName.
#
# `gcloud monitoring time-series` NÃO existe nesta versão do gcloud → usamos a API
# REST via curl. `gcloud monitoring policies`/`channels` variam por componente, então
# criamos tudo por REST tb. Ver docs/interno/RUNBOOK_scoring_pipeline.md.
set -euo pipefail

PROJECT="smart-ads-451319"
EMAIL="ramonfceo@gmail.com"
SUB="lead-capture-ingest-sub"
TOKEN="$(gcloud auth print-access-token)"
API="https://monitoring.googleapis.com/v3/projects/${PROJECT}"

echo "== 1. canal de notificação (email) — reusa se já existir =="
CH=$(curl -s -H "Authorization: Bearer $TOKEN" "${API}/notificationChannels" \
  | python3 -c "import sys,json;print(next((c['name'] for c in json.load(sys.stdin).get('notificationChannels',[]) if c.get('labels',{}).get('email_address')=='${EMAIL}'),''))")
if [ -z "$CH" ]; then
  CH=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    "${API}/notificationChannels" -d "{\"type\":\"email\",\"displayName\":\"Ramon — alertas ML serving\",\"labels\":{\"email_address\":\"${EMAIL}\"},\"enabled\":true}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['name'])")
fi
echo "  canal: $CH"

create_policy () { # $1=displayName  $2=json-conditions
  local exists
  exists=$(curl -s -H "Authorization: Bearer $TOKEN" "${API}/alertPolicies" \
    | python3 -c "import sys,json;print(next((p['name'] for p in json.load(sys.stdin).get('alertPolicies',[]) if p.get('displayName')=='''$1'''),''))")
  if [ -n "$exists" ]; then echo "  já existe: $1"; return; fi
  curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    "${API}/alertPolicies" -d "{\"displayName\":\"$1\",\"combiner\":\"OR\",\"conditions\":$2,\"notificationChannels\":[\"$CH\"],\"enabled\":true}" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print('  criada:', d.get('name', d))"
}

echo "== 2. alerta: scoring parado / backlog =="
create_policy "ML serving — scoring parado / backlog (lead-capture-ingest-sub)" '[
  {"displayName":"Backlog > 200 msgs por 10min","conditionThreshold":{
    "filter":"metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\" AND resource.type=\"pubsub_subscription\" AND resource.label.\"subscription_id\"=\"'"$SUB"'\"",
    "comparison":"COMPARISON_GT","thresholdValue":200,"duration":"600s",
    "aggregations":[{"alignmentPeriod":"300s","perSeriesAligner":"ALIGN_MEAN"}],"trigger":{"count":1}}},
  {"displayName":"Msg mais antiga > 30min sem processar","conditionThreshold":{
    "filter":"metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\" AND resource.type=\"pubsub_subscription\" AND resource.label.\"subscription_id\"=\"'"$SUB"'\"",
    "comparison":"COMPARISON_GT","thresholdValue":1800,"duration":"300s",
    "aggregations":[{"alignmentPeriod":"300s","perSeriesAligner":"ALIGN_MAX"}],"trigger":{"count":1}}}]'

echo "== 3. métrica + alerta: qualquer cron falhando =="
gcloud logging metrics describe scheduler_job_failures --project="$PROJECT" >/dev/null 2>&1 \
  || gcloud logging metrics create scheduler_job_failures --project="$PROJECT" \
       --description="Falhas de qualquer Cloud Scheduler job (403/500/timeout)." \
       --log-filter='resource.type="cloud_scheduler_job" AND severity>=ERROR'
create_policy "Cron falhou — qualquer job do Scheduler (403/500)" '[
  {"displayName":"1+ falha de cron em 5min","conditionThreshold":{
    "filter":"metric.type=\"logging.googleapis.com/user/scheduler_job_failures\" AND resource.type=\"cloud_scheduler_job\"",
    "comparison":"COMPARISON_GT","thresholdValue":0,"duration":"0s",
    "aggregations":[{"alignmentPeriod":"300s","perSeriesAligner":"ALIGN_SUM","crossSeriesReducer":"REDUCE_SUM"}],"trigger":{"count":1}}}]'
echo "== pronto =="
