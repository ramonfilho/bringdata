#!/usr/bin/env bash
# Cria ou atualiza o Cloud Run Job `retreino-mensal` (etapa 1 do treino contínuo,
# V2/docs/TREINO_CONTINUO_DESENHO.md). Idempotente.
#
# Uso:  bash scripts/setup_retreino_job.sh <tag da imagem>      # ex.: v20260918_120000
#       bash scripts/setup_retreino_job.sh                      # usa a tag da API viva
# Rodar uma vez:  gcloud run jobs execute retreino-mensal --region us-central1 --wait
#
# A imagem é a etapa `treino` do api/Dockerfile, publicada pelo deploy.yml com a mesma
# tag da API. Credenciais vêm do Secret Manager como variáveis próprias; nenhuma URI
# com senha passa por aqui (src/core/mlflow_setup.py monta a URI de MLFLOW_DB_*).
set -euo pipefail
PROJECT="smart-ads-451319"; REGION="us-central1"; JOB="retreino-mensal"
SA="12955519745-compute@developer.gserviceaccount.com"   # a mesma dos outros jobs; tem os dois segredos
CLOUDSQL_IP="104.197.138.129"                             # smart-ads-db, SSL obrigatório

TAG="${1:-}"
if [ -z "$TAG" ]; then
  API_IMG=$(gcloud run services describe smart-ads-api --region="$REGION" --project="$PROJECT" --format='value(spec.template.spec.containers[0].image)')
  TAG="${API_IMG##*:}"
fi
IMG="gcr.io/$PROJECT/smart-ads-treino:$TAG"
gcloud container images describe "$IMG" --project="$PROJECT" >/dev/null 2>&1 || { echo "imagem não existe: $IMG (o deploy.yml publica uma por deploy)"; exit 1; }

ENVS="LEDGER_DB_HOST=$CLOUDSQL_IP,LEDGER_DB_PORT=5432,LEDGER_DB_NAME=ledger,LEDGER_DB_USER=ledger_app"
ENVS="$ENVS,MLFLOW_DB_HOST=$CLOUDSQL_IP,MLFLOW_DB_PORT=5432,MLFLOW_DB_USER=postgres,MLFLOW_DB_NAME=mlflow"
ENVS="$ENVS,LAUNCHES_SOURCE=table,PYTHONUNBUFFERED=1,TZ=America/Sao_Paulo"
SECRETS="LEDGER_DB_PASSWORD=ledger-db-password:latest,MLFLOW_DB_PASSWORD=mlflow-db-password:latest"
# Forma --flag=valor: o gcloud recusa valor repetido ("db" duas vezes) na lista de --args.
ARGS="--leads-source=db,--sales-source=db,--no-api-data"

COMUM=(--region="$REGION" --project="$PROJECT" --image="$IMG" --service-account="$SA"
       --cpu=4 --memory=8Gi --task-timeout=3600 --max-retries=0 --tasks=1
       --set-env-vars="$ENVS" --set-secrets="$SECRETS" --args="$ARGS")
if gcloud run jobs describe "$JOB" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud run jobs update "$JOB" "${COMUM[@]}" >/dev/null && echo "job $JOB atualizado: $IMG"
else
  gcloud run jobs create "$JOB" "${COMUM[@]}" >/dev/null && echo "job $JOB criado: $IMG"
fi
