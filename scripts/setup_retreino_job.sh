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
# Pós-treino (etapas 3 e 4): DM no Slack para o mesmo usuário do monitoring, e a PR do
# modelo pela API do GitHub se o segredo github-pr-token existir (PAT fine-grained do
# repositório, Contents e Pull requests em escrita). Sem ele, o DM traz o comando manual.
SLACK_DM=$(gcloud run services describe smart-ads-monitoring --region="$REGION" --project="$PROJECT" --format=json \
  | python3 -c "import json,sys; e=json.load(sys.stdin)['spec']['template']['spec']['containers'][0].get('env',[]); print(next((x.get('value','') for x in e if x.get('name')=='SLACK_USER_DM'),''))")
[ -n "$SLACK_DM" ] || { echo "SLACK_USER_DM não encontrado no serviço smart-ads-monitoring"; exit 1; }
ENVS="$ENVS,SLACK_USER_DM=$SLACK_DM,GITHUB_REPO=ramonfilho/bringdata"
SECRETS="LEDGER_DB_PASSWORD=ledger-db-password:latest,MLFLOW_DB_PASSWORD=mlflow-db-password:latest,SLACK_BOT_TOKEN=slack-bot-token:latest"
if gcloud secrets describe github-pr-token --project="$PROJECT" >/dev/null 2>&1; then
  SECRETS="$SECRETS,GITHUB_PR_TOKEN=github-pr-token:latest"
else
  echo "aviso: segredo github-pr-token não existe; o job avisa no Slack mas não abre a PR do modelo"
fi
# Forma --flag=valor: o gcloud recusa valor repetido ("db" duas vezes) na lista de --args.
ARGS="--leads-source=db,--sales-source=db,--no-api-data,--pos-treino"

COMUM=(--region="$REGION" --project="$PROJECT" --image="$IMG" --service-account="$SA"
       --cpu=4 --memory=8Gi --task-timeout=3600 --max-retries=0 --tasks=1
       --set-env-vars="$ENVS" --set-secrets="$SECRETS" --args="$ARGS")
if gcloud run jobs describe "$JOB" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud run jobs update "$JOB" "${COMUM[@]}" >/dev/null && echo "job $JOB atualizado: $IMG"
else
  gcloud run jobs create "$JOB" "${COMUM[@]}" >/dev/null && echo "job $JOB criado: $IMG"
fi

# Etapa 5: o cron mensal (dia 1 às 06:00 de São Paulo) executa o job pelo Cloud Scheduler,
# com a mesma conta invocadora dos outros jobs. O gatilho por drift não passa por aqui
# (src/retreino/gatilho.py chama a API do job quando score_drift dispara).
CRON="retreino-mensal-cron"
URI="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/$JOB:run"
SCHED=(--location="$REGION" --project="$PROJECT" --schedule="0 6 1 * *" --time-zone="America/Sao_Paulo"
       --uri="$URI" --http-method=POST --oauth-service-account-email="scheduler-invoker@$PROJECT.iam.gserviceaccount.com")
if gcloud scheduler jobs describe "$CRON" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$CRON" "${SCHED[@]}" >/dev/null && echo "cron $CRON atualizado (dia 1, 06:00)"
else
  gcloud scheduler jobs create http "$CRON" "${SCHED[@]}" >/dev/null && echo "cron $CRON criado (dia 1, 06:00)"
fi
