#!/usr/bin/env bash
# Codifica a autenticação OIDC dos crons que batem no smart-ads-api (frente B do
# endurecimento pós-apagão 22-23/07/2026). Idempotente: pode rodar de novo.
#
# NÃO deixa o serviço privado (o /webhook/lead_capture precisa de anônimo — ver
# docs/RUNBOOK_scoring_pipeline.md). É defense-in-depth: se o allUsers sumir por
# engano, os crons sobrevivem via token; só o webhook quebraria.
set -euo pipefail

PROJECT="smart-ads-451319"
PROJNUM="12955519745"
REGION="us-central1"
SERVICE="smart-ads-api"
SA="scheduler-invoker@${PROJECT}.iam.gserviceaccount.com"
AUD="https://smart-ads-api-gazrm25mda-uc.a.run.app"
# Só os crons que chamam o smart-ads-api por HTTP. Os de ingestão chamam a API
# run.googleapis.com (:run) e já autenticam por OAuth — fora deste script.
JOBS="slack-digest-daily slack-digest-daily-dm utm-quality-daily-trafego utm-quality-daily-trafego-tarde railway-polling cpl-refresh-daily pubsub-process-pending"

echo "== 1. SA dedicada (cria se não existir) =="
gcloud iam service-accounts describe "$SA" --project="$PROJECT" >/dev/null 2>&1 \
  || gcloud iam service-accounts create scheduler-invoker \
       --display-name="Cloud Scheduler -> smart-ads-api (OIDC)" --project="$PROJECT"

echo "== 2. SA pode invocar o serviço =="
gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" \
  --member="serviceAccount:${SA}" --role="roles/run.invoker" --quiet

echo "== 3. agente do Scheduler pode mintar token da SA =="
gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$PROJECT" \
  --member="serviceAccount:service-${PROJNUM}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator" --quiet

echo "== 4. seta OIDC (SA + audience) em cada cron =="
for j in $JOBS; do
  gcloud scheduler jobs update http "$j" --location="$REGION" \
    --oidc-service-account-email="$SA" --oidc-token-audience="$AUD" --quiet
  echo "  ok: $j"
done
echo "== pronto. Verificar: cada job deve retornar 2xx mesmo se o allUsers for removido. =="
