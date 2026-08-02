#!/usr/bin/env bash
# sync_monitoring_cron.sh — rede de segurança do deploy-gate. Roda no Cloud Run Job
# (imagem cloud-sdk) 1x/dia. Se o monitoring estiver numa imagem DIFERENTE do scorer
# (drift, ex.: alguém deployou o scorer por fora do gate), alinha o monitoring à
# imagem VIVA do scorer com segurança: cria revisão -> roteia -> verifica Ready ->
# rollback se não subir. Se estiverem iguais, não faz nada.
#
# NUNCA mexe em IAM/allUsers (a SA só tem run.developer). Idempotente. Sem drift = no-op.
set -uo pipefail
PROJECT="${PROJECT:-smart-ads-451319}"; REGION="${REGION:-us-central1}"
API="${API_SVC:-smart-ads-api}"; MON="${MON_SVC:-smart-ads-monitoring}"
GS="${GS_BASE:-gs://smart-ads-mlflow/deploy-gate}"

live_rev(){ gcloud run services describe "$1" --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null \
  | python3 -c "import json,sys
try:
 d=json.load(sys.stdin)
 print(next((t['revisionName'] for t in d['status']['traffic'] if t.get('percent')==100),''))
except Exception: pass"; }
rev_img(){ gcloud run revisions describe "$1" --region="$REGION" --project="$PROJECT" --format='value(spec.containers[0].image)' 2>/dev/null; }
rev_sha(){ gcloud run revisions describe "$1" --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null \
  | python3 -c "import json,sys
try:
 d=json.load(sys.stdin); e={x['name']:x.get('value') for x in d['spec']['containers'][0].get('env',[]) if 'value' in x}
 print(e.get('DEPLOY_GIT_SHA','unknown'))
except Exception: print('unknown')"; }
alert(){ [ -n "${SLACK_WEBHOOK:-}" ] && curl -sS -m 10 -X POST -H 'Content-type: application/json' -d "{\"text\":\"$1\"}" "$SLACK_WEBHOOK" >/dev/null 2>&1 || true; }
ledger(){ local ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"ts":"%s","host":"cron","action":"sync","service":"%s","from_sha":"%s","to_sha":"%s","result":"%s","reason":"%s"}\n' \
    "$ts" "$MON" "$1" "$2" "$3" "$4" | gcloud storage cp - "$GS/events/${ts//:/-}_${MON}_sync.json" --project="$PROJECT" >/dev/null 2>&1 || true; }

ar=$(live_rev "$API"); ai=$(rev_img "$ar"); as=$(rev_sha "$ar")
mr=$(live_rev "$MON"); mi=$(rev_img "$mr")
echo "[deploy-gate-cron] scorer=$as ($ai)  monitoring=$(rev_sha "$mr") ($mi)"
[ -z "$ai" ] && { echo "não obtive a imagem do scorer — abortando sem tocar."; exit 0; }
if [ "$ai" = "$mi" ]; then echo "sem drift — nada a fazer."; exit 0; fi

echo "DRIFT: monitoring != scorer. Alinhando $MON a $as…"
newrev=$(gcloud run services update "$MON" --region="$REGION" --project="$PROJECT" --image="$ai" --update-env-vars="DEPLOY_GIT_SHA=$as" --format='value(status.latestCreatedRevisionName)' 2>/dev/null)
[ -n "$newrev" ] || { echo "falha ao criar revisão."; ledger "$mi" "$as" fail create; alert "deploy-gate cron: falhei ao criar revisão do monitoring pra $as."; exit 1; }
gcloud run services update-traffic "$MON" --region="$REGION" --project="$PROJECT" --to-revisions="$newrev=100" >/dev/null 2>&1 \
  || { echo "falha ao rotear."; ledger "$mi" "$as" fail route; alert "deploy-gate cron: falhei ao rotear o monitoring pra $newrev."; exit 1; }
sleep 5; ready=$(gcloud run revisions describe "$newrev" --region="$REGION" --project="$PROJECT" --format='value(status.conditions[0].status)' 2>/dev/null)
if [ "$ready" != "True" ]; then
  echo "revisão nova não ficou Ready ($ready) — ROLLBACK pra $mr."
  gcloud run services update-traffic "$MON" --region="$REGION" --project="$PROJECT" --to-revisions="$mr=100" >/dev/null 2>&1
  ledger "$mi" "$as" fail rollback-not-ready; alert "deploy-gate cron: revisão nova do monitoring não subiu, revertido pra $mr. Verifique."; exit 1
fi
echo "OK: $MON alinhado a $as ($newrev)."
ledger "$mi" "$as" ok cron-align
alert "deploy-gate cron: monitoring estava atrás e foi realinhado ao scorer ($as). Alguém deployou por fora do gate?"
