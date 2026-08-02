#!/usr/bin/env bash
# setup_sync_monitoring_cron.sh — cria (idempotente) a rede de segurança do deploy-gate:
# SA + Cloud Run Job (roda sync_monitoring_cron.sh na imagem cloud-sdk) + Cloud Scheduler diário.
# A SA recebe run.developer (alinha serviços; NÃO pode IAM/allUsers) + storage p/ o ledger.
#
# Uso:  bash scripts/setup_sync_monitoring_cron.sh
set -euo pipefail
PROJECT="smart-ads-451319"; REGION="us-central1"
SA="deploy-gate-syncer"; SA_EMAIL="$SA@$PROJECT.iam.gserviceaccount.com"
JOB="deploy-gate-sync-monitoring"; CRON="deploy-gate-sync-monitoring-daily"
GS="gs://smart-ads-mlflow/deploy-gate"
SDK_IMAGE="gcr.io/google.com/cloudsdktool/cloud-sdk:slim"   # traz gcloud + python3 + curl
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "→ 1. service account"
gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SA" --project="$PROJECT" --display-name="deploy-gate monitoring syncer"

echo "→ 2. permissões (run.developer NÃO inclui setIamPolicy → não mexe em allUsers)"
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA_EMAIL" --role="roles/run.developer" --condition=None >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA_EMAIL" --role="roles/storage.objectAdmin" --condition=None >/dev/null

echo "→ 3. sobe o script do cron pro GCS"
gcloud storage cp "$HERE/sync_monitoring_cron.sh" "$GS/sync_monitoring_cron.sh" --project="$PROJECT"

echo "→ 4. Cloud Run Job (cloud-sdk: busca o script no GCS e roda)"
FETCH='gcloud storage cp '"$GS"'/sync_monitoring_cron.sh /tmp/s.sh && bash /tmp/s.sh'
if gcloud run jobs describe "$JOB" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud run jobs update "$JOB" --region="$REGION" --project="$PROJECT" --image="$SDK_IMAGE" \
    --service-account="$SA_EMAIL" --command=bash --args="^@@^-c@@$FETCH" --max-retries=0 --task-timeout=300 >/dev/null
else
  gcloud run jobs create "$JOB" --region="$REGION" --project="$PROJECT" --image="$SDK_IMAGE" \
    --service-account="$SA_EMAIL" --command=bash --args="^@@^-c@@$FETCH" --max-retries=0 --task-timeout=300 >/dev/null
fi

echo "→ 5. Cloud Scheduler (diário 07:30 BRT = 10:30 UTC, dispara o Job)"
URI="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/$JOB:run"
if gcloud scheduler jobs describe "$CRON" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$CRON" --location="$REGION" --project="$PROJECT" \
    --schedule="30 10 * * *" --uri="$URI" --http-method=POST \
    --oauth-service-account-email="$SA_EMAIL" --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" >/dev/null
else
  gcloud scheduler jobs create http "$CRON" --location="$REGION" --project="$PROJECT" \
    --schedule="30 10 * * *" --uri="$URI" --http-method=POST \
    --oauth-service-account-email="$SA_EMAIL" --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" >/dev/null
fi
echo "✅ pronto. Testar agora:  gcloud run jobs execute $JOB --region=$REGION --project=$PROJECT --wait"
echo "   Rollback total:  gcloud scheduler jobs delete $CRON --location=$REGION; gcloud run jobs delete $JOB --region=$REGION"
