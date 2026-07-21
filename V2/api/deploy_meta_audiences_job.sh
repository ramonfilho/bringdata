#!/bin/bash
# =============================================================================
# Deploy - Job de Públicos da Meta (Cloud Run Job) — ISOLADO do token do serviço
# =============================================================================
#
# Substitui os 2 Custom Audiences (leads + alunos) do DevClub por email/telefone
# hasheado, lendo das tabelas frescas. Roda:
#   python /app/scripts/meta_audiences_sync.py --audience both --execute --yes-write-to-client-meta
#
# ⚠️ ISOLAMENTO DELIBERADO (auditoria do token, 21/07): este script NÃO chama
#    build_env_vars() de propósito. build_env_vars LÊ o META_ACCESS_TOKEN do
#    serviço de produção (smart-ads-api) pra preservá-lo — não queremos nem ler
#    o token do serviço aqui. Em vez disso, este job recebe o token COM
#    ads_management de um Secret DEDICADO (meta-audiences-token) via --set-secrets,
#    setado SÓ neste job. O serviço smart-ads-api e o CAPI ficam intocados.
#
# Uso: ./deploy_meta_audiences_job.sh [--reuse-image] [--with-scheduler] [--execute-now] [--yes]
# Pré-requisito: o Secret Manager tem 'meta-audiences-token' (o token com ads_management).
# =============================================================================
set -e
set -u

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/config.sh"     # PROJECT_ID/REGION/SERVICE_NAME/GCR_REGISTRY/RAILWAY_DB_* + helpers (só LEITURA)

# --- constantes deste job (self-contained; não polui config.sh compartilhado) ---
JOB_NAME="${META_AUDIENCES_JOB:-meta-audiences-daily}"
JOB_SCHEDULE="${META_AUDIENCES_SCHEDULE:-15 10 * * *}"   # 07:15 BRT (após a ingestão ~06:45)
TOKEN_SECRET="${META_AUDIENCES_TOKEN_SECRET:-meta-audiences-token}"
JOB_MEMORY="${META_AUDIENCES_MEMORY:-2Gi}"
JOB_CPU="${META_AUDIENCES_CPU:-1}"
JOB_TIMEOUT="${META_AUDIENCES_TIMEOUT:-1800}"
JOB_ARGS="/app/scripts/meta_audiences_sync.py,--audience,both,--execute,--yes-write-to-client-meta"

REUSE_IMAGE=false; WITH_SCHEDULER=false; EXECUTE_NOW=false; YES_FLAG=false
IMAGE_TAG=""

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --reuse-image) REUSE_IMAGE=true; shift;;
            --with-scheduler) WITH_SCHEDULER=true; shift;;
            --execute-now) EXECUTE_NOW=true; shift;;
            --yes|-y) YES_FLAG=true; shift;;
            -h|--help) echo "Uso: $0 [--reuse-image] [--with-scheduler] [--execute-now] [--yes]"; exit 0;;
            *) print_error "Argumento desconhecido: $1"; exit 1;;
        esac
    done
}

validate_prerequisites() {
    print_header "1. VALIDAÇÕES"
    validate_gcloud; validate_auth; validate_project "$PROJECT_ID"
    # o Secret com o token precisa existir
    if ! gcloud secrets describe "$TOKEN_SECRET" --project="$PROJECT_ID" &>/dev/null; then
        print_error "Secret '$TOKEN_SECRET' não existe. Crie antes: gcloud secrets create $TOKEN_SECRET --data-file=<arquivo-do-token>"
        exit 1
    fi
    print_success "Secret do token '$TOKEN_SECRET' encontrado"
    if [ "$REUSE_IMAGE" = false ]; then
        validate_docker
        [ -f "$SCRIPT_DIR/Dockerfile" ] || { print_error "Dockerfile não encontrado"; exit 1; }
    fi
    echo ""
}

build_docker_image() {
    print_header "2. IMAGEM DOCKER"
    if [ "$REUSE_IMAGE" = true ]; then
        IMAGE_TAG="latest"
        print_warning "Reusando :latest — confirme que já contém scripts/meta_audiences_sync.py + enabled:true"
        return 0
    fi
    IMAGE_TAG="v$(date +%Y%m%d_%H%M%S)"
    local IMAGE_FULL="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"
    local IMAGE_LATEST="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:latest"
    local MODEL_PATH; MODEL_PATH=$(grep "model_path:" "$CONFIG_FILE" | awk '{print $2}')
    [ -z "$MODEL_PATH" ] && { print_error "model_path não encontrado em $CONFIG_FILE"; exit 1; }
    print_info "Build linux/amd64 (tag $IMAGE_TAG)…"
    cd "$PROJECT_ROOT"
    docker buildx build --platform linux/amd64 --build-arg MODEL_PATH="$MODEL_PATH" \
        -f api/Dockerfile -t "$IMAGE_FULL" -t "$IMAGE_LATEST" --push . \
        || { print_error "Falha no build"; exit 1; }
    print_success "Imagem publicada: $IMAGE_TAG"
    echo ""
}

# Env SÓ com o que o job precisa (Cloud SQL + Railway + TZ). SEM build_env_vars,
# SEM META_ACCESS_TOKEN aqui (vem do Secret via --set-secrets, ver deploy).
build_job_env() {
    local ledger_pw
    ledger_pw=$(gcloud secrets versions access latest --secret=ledger-db-password --project="$PROJECT_ID" 2>/dev/null)
    [ -z "$ledger_pw" ] && { echo "ERROR_LEDGER_SECRET"; return 1; }
    local E="TZ=America/Sao_Paulo"
    E="$E,LEDGER_DB_HOST=${LEDGER_DB_HOST:-104.197.138.129}"
    E="$E,LEDGER_DB_PORT=${LEDGER_DB_PORT:-5432}"
    E="$E,LEDGER_DB_NAME=${LEDGER_DB_NAME:-ledger}"
    E="$E,LEDGER_DB_USER=${LEDGER_DB_USER:-ledger_app}"
    E="$E,LEDGER_DB_PASSWORD=$ledger_pw"
    E="$E,RAILWAY_DB_HOST=$RAILWAY_DB_HOST,RAILWAY_DB_PORT=$RAILWAY_DB_PORT"
    E="$E,RAILWAY_DB_NAME=$RAILWAY_DB_NAME,RAILWAY_DB_USER=$RAILWAY_DB_USER,RAILWAY_DB_PASSWORD=$RAILWAY_DB_PASSWORD"
    [ -n "${SLACK_WEBHOOK_URL:-}" ] && E="$E,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
    echo "$E"
}

deploy_job() {
    print_header "3. DEPLOY DO CLOUD RUN JOB"
    local IMAGE="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"
    local ENV; ENV=$(build_job_env) || { print_error "senha do ledger indisponível"; exit 1; }
    [ "$ENV" = "ERROR_LEDGER_SECRET" ] && { print_error "senha do ledger indisponível"; exit 1; }
    print_info "Job: $JOB_NAME | Imagem: $IMAGE | Mem: $JOB_MEMORY | Timeout: ${JOB_TIMEOUT}s"
    print_info "Token: do Secret '$TOKEN_SECRET' (NÃO do serviço) via --set-secrets"
    gcloud run jobs deploy "$JOB_NAME" \
        --image "$IMAGE" --region "$REGION" \
        --memory "$JOB_MEMORY" --cpu "$JOB_CPU" --task-timeout "$JOB_TIMEOUT" --max-retries 1 \
        --set-env-vars="$ENV" \
        --set-secrets="META_ACCESS_TOKEN=${TOKEN_SECRET}:latest" \
        --command python --args="$JOB_ARGS" --quiet \
        || { print_error "Falha no deploy do job"; exit 1; }
    print_success "Job deployado: $JOB_NAME"
    echo ""
}

setup_scheduler() {
    [ "$WITH_SCHEDULER" = false ] && return 0
    print_header "4. SCHEDULER (cron)"
    local proj_num; proj_num=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
    local SA="${proj_num}-compute@developer.gserviceaccount.com"
    local NAME="${JOB_NAME}-cron"
    local URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"
    # a SA do runtime do job precisa ler o secret do token
    gcloud secrets add-iam-policy-binding "$TOKEN_SECRET" --project="$PROJECT_ID" \
        --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --quiet >/dev/null || true
    # e o scheduler precisa invocar o job
    gcloud run jobs add-iam-policy-binding "$JOB_NAME" --region="$REGION" \
        --member="serviceAccount:$SA" --role="roles/run.invoker" --quiet >/dev/null
    if gcloud scheduler jobs describe "$NAME" --location="$REGION" &>/dev/null; then
        gcloud scheduler jobs update http "$NAME" --location="$REGION" \
            --schedule="$JOB_SCHEDULE" --time-zone="Etc/UTC" --uri="$URI" \
            --http-method=POST --oauth-service-account-email="$SA" --quiet
        print_success "Scheduler atualizado: $NAME ($JOB_SCHEDULE UTC = 07:15 BRT)"
    else
        gcloud scheduler jobs create http "$NAME" --location="$REGION" \
            --schedule="$JOB_SCHEDULE" --time-zone="Etc/UTC" --uri="$URI" \
            --http-method=POST --oauth-service-account-email="$SA" \
            --description="Diário 07:15 BRT: substitui os 2 públicos da Meta (leads+alunos) por hash" --quiet
        print_success "Scheduler criado: $NAME ($JOB_SCHEDULE UTC = 07:15 BRT)"
    fi
    echo ""
}

test_run() {
    [ "$EXECUTE_NOW" = false ] && { print_warning "Teste pulado (use --execute-now)."; return 0; }
    print_header "5. EXECUÇÃO DE TESTE"
    print_warning "Isto ESCREVE nos públicos do cliente (dados reais)."
    gcloud run jobs execute "$JOB_NAME" --region "$REGION" --quiet
    print_info "Logs: gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --limit 50 --freshness=1h"
    echo ""
}

main() {
    parse_arguments "$@"
    echo "╔═══ Deploy Job Públicos Meta (isolado do token do serviço) ═══╗"
    print_info "Projeto: $PROJECT_ID | Região: $REGION | Job: $JOB_NAME"
    validate_prerequisites
    if [ "$YES_FLAG" = false ]; then
        read -p "Prosseguir com build+deploy do job? (y/n) " -n 1 -r; echo ""
        [[ $REPLY =~ ^[Yy]$ ]] || { print_warning "Cancelado"; exit 0; }
    fi
    build_docker_image
    deploy_job
    setup_scheduler
    test_run
    print_header "PRONTO"
    echo "Job: $JOB_NAME  (token do Secret $TOKEN_SECRET; serviço smart-ads-api INTOCADO)"
    echo "Rodar manual: gcloud run jobs execute $JOB_NAME --region $REGION"
    [ "$WITH_SCHEDULER" = true ] && echo "Cron: ${JOB_NAME}-cron  ($JOB_SCHEDULE UTC = 07:15 BRT)"
}
main "$@"