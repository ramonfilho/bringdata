#!/usr/bin/env bash
# bootstrap_identidade_ci.sh: cria, UMA vez, a identidade que o GitHub Actions usa no GCP.
#
# O que faz (idempotente: roda de novo sem estragar o que já existe):
#   1. habilita a API sts (troca de token da federação);
#   2. cria a conta de serviço github-deployer;
#   3. dá a ela só o que o pipeline usa, no menor escopo que o gcloud permite:
#        projeto : run.admin (deploy, tráfego, revisões), logging.viewer (smoke test lê logs),
#                  run.invoker (os gates chamam o serviço fechado)
#        SA de runtime (appspot)          : serviceAccountUser (o deploy sobe serviço que roda como ela)
#        github-deployer e scheduler-invoker : serviceAccountTokenCreator (token de identidade
#                  para chamar o Cloud Run; scripts/gcp_auth.py usa os dois caminhos)
#        bucket gs://smart-ads-mlflow     : objectAdmin (lock e ledger do gate, artefatos do modelo)
#        repositório de imagens gcr.io    : artifactregistry.writer (push da imagem, pull do Gate D)
#        segredos                         : secretAccessor em cada segredo que o deploy lê
#   4. cria o segredo slack-webhook-url com o valor que estava literal em api/lib/config.sh;
#   5. cria o pool e o provider de Workload Identity Federation restritos ao repositório
#      ramonfilho/bringdata e autoriza esse repositório a assumir a github-deployer;
#   6. grava no GitHub as duas variáveis que os workflows leem.
#
# Nenhuma chave JSON é criada: a federação troca o token do job do GitHub por credencial
# de curta duração da conta de serviço. É o caminho que o Google e o GitHub recomendam.
#
# Uso: bash V2/scripts/bootstrap_identidade_ci.sh
# Precisa de: gcloud autenticado como dono do projeto; gh autenticado no repositório.
set -u
P="${PROJECT_ID:-smart-ads-451319}"
PN="$(gcloud projects describe "$P" --format='value(projectNumber)')"
REPO="${GITHUB_REPO:-ramonfilho/bringdata}"
SA="github-deployer@$P.iam.gserviceaccount.com"
RT="$P@appspot.gserviceaccount.com"                       # SA de runtime dos serviços
SCH="scheduler-invoker@$P.iam.gserviceaccount.com"        # SA que os gates personificam
ok(){ echo "ok    $*"; }; falha(){ echo "FALHA $*"; }

echo "== 1. API sts =="
gcloud services enable sts.googleapis.com --project="$P" >/dev/null 2>&1 && ok "sts" || falha "sts"

echo "== 2. conta de serviço =="
if gcloud iam service-accounts describe "$SA" --project="$P" >/dev/null 2>&1; then ok "$SA já existia"
else gcloud iam service-accounts create github-deployer --project="$P" \
       --display-name="GitHub Actions deployer (CI/CD)" >/dev/null 2>&1 && ok "criada $SA" || falha "criar SA"; fi

echo "== 3. papéis no projeto =="
for r in roles/run.admin roles/logging.viewer roles/run.invoker; do
  gcloud projects add-iam-policy-binding "$P" --member="serviceAccount:$SA" --role="$r" \
    --condition=None --quiet >/dev/null 2>&1 && ok "$r" || falha "$r"
done

echo "== 4. agir como a SA de runtime; token de identidade =="
gcloud iam service-accounts add-iam-policy-binding "$RT" --member="serviceAccount:$SA" \
  --role=roles/iam.serviceAccountUser --project="$P" --quiet >/dev/null 2>&1 && ok "serviceAccountUser em ${RT%%@*}" || falha "serviceAccountUser"
for alvo in "$SA" "$SCH"; do
  gcloud iam service-accounts add-iam-policy-binding "$alvo" --member="serviceAccount:$SA" \
    --role=roles/iam.serviceAccountTokenCreator --project="$P" --quiet >/dev/null 2>&1 && ok "tokenCreator em ${alvo%%@*}" || falha "tokenCreator em $alvo"
done

echo "== 5. bucket do gate e dos artefatos =="
gcloud storage buckets add-iam-policy-binding gs://smart-ads-mlflow --member="serviceAccount:$SA" \
  --role=roles/storage.objectAdmin >/dev/null 2>&1 && ok "objectAdmin em gs://smart-ads-mlflow" || falha "bucket"

echo "== 6. repositório de imagens =="
LOC="$(gcloud artifacts repositories list --project="$P" --format=json 2>/dev/null \
  | python3 -c "import json,sys; print([r['name'].split('/locations/')[1].split('/')[0] for r in json.load(sys.stdin) if r['name'].endswith('/gcr.io')][0])")"
gcloud artifacts repositories add-iam-policy-binding gcr.io --location="$LOC" --project="$P" \
  --member="serviceAccount:$SA" --role=roles/artifactregistry.writer >/dev/null 2>&1 && ok "artifactregistry.writer em gcr.io ($LOC)" || falha "artifact registry"

echo "== 7. segredos =="
CONFIG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/api/lib/config.sh"
if gcloud secrets describe slack-webhook-url --project="$P" >/dev/null 2>&1; then ok "slack-webhook-url já existia"
else
  URL="$(grep -oE 'https://hooks\.slack\.com/services/[A-Za-z0-9/]+' "$CONFIG" | head -1)"
  if [ -z "$URL" ]; then URL="${SLACK_WEBHOOK_URL:-}"; fi
  [ -n "$URL" ] && printf '%s' "$URL" | gcloud secrets create slack-webhook-url --project="$P" --data-file=- \
      --replication-policy=automatic >/dev/null 2>&1 && ok "slack-webhook-url criado" || falha "slack-webhook-url (exporte SLACK_WEBHOOK_URL e rode de novo)"
fi
for s in railway-db-password ledger-db-password api-internal-token hotmart-basic slack-webhook-url mlflow-db-password; do
  gcloud secrets add-iam-policy-binding "$s" --project="$P" --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null 2>&1 && ok "accessor em $s" || falha "accessor em $s"
done

echo "== 8. federação de identidade (GitHub -> GCP), só o repositório $REPO =="
if gcloud iam workload-identity-pools describe github --location=global --project="$P" >/dev/null 2>&1; then ok "pool github já existia"
else gcloud iam workload-identity-pools create github --location=global --project="$P" \
       --display-name="GitHub Actions" >/dev/null 2>&1 && ok "pool github" || falha "pool"; fi
if gcloud iam workload-identity-pools providers describe github --location=global \
     --workload-identity-pool=github --project="$P" >/dev/null 2>&1; then ok "provider github já existia"
else gcloud iam workload-identity-pools providers create-oidc github --location=global \
       --workload-identity-pool=github --project="$P" --display-name="GitHub OIDC" \
       --issuer-uri="https://token.actions.githubusercontent.com" \
       --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
       --attribute-condition="assertion.repository == '$REPO'" >/dev/null 2>&1 && ok "provider github" || falha "provider"; fi
gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$P" \
  --member="principalSet://iam.googleapis.com/projects/$PN/locations/global/workloadIdentityPools/github/attribute.repository/$REPO" \
  --role=roles/iam.workloadIdentityUser --quiet >/dev/null 2>&1 && ok "$REPO pode assumir ${SA%%@*}" || falha "workloadIdentityUser"

echo "== 9. variáveis no GitHub =="
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$REPO" \
  --body "projects/$PN/locations/global/workloadIdentityPools/github/providers/github" >/dev/null 2>&1 && ok "GCP_WORKLOAD_IDENTITY_PROVIDER" || falha "variável provider"
gh variable set GCP_DEPLOYER_SA --repo "$REPO" --body "$SA" >/dev/null 2>&1 && ok "GCP_DEPLOYER_SA" || falha "variável SA"

echo "== papéis da $SA no projeto =="
gcloud projects get-iam-policy "$P" --flatten="bindings[].members" --filter="bindings.members:$SA" \
  --format="value(bindings.role)" | tr '\n' ' '; echo
