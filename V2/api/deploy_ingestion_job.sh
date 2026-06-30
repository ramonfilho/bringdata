#!/bin/bash
# =============================================================================
# Script de Deploy - Bring Data | Job de Ingestão Automática (Cloud Run Job)
# =============================================================================
#
# Descrição: Deploy de UM dos Cloud Run Jobs de ingestão automática que populam
#            o banco sozinhos (batch). Espelha o deploy_validation_job.sh, que é
#            parametrizado por --report-type; aqui o parâmetro é --job.
#
# Uso: ./deploy_ingestion_job.sh --job {leads|sales} [--reuse-image] [--execute-now] [--yes]
#
#   --job leads  → ingestion-leads-incremental
#                  python /app/src/data/leads_unify.py --incremental
#                  anexa os leads novos da registros_ml (ledger vivo) ao train_unified.
#   --job sales  → ingestion-sales-daily
#                  python /app/src/validation/etl_sales.py --daily
#                  puxa os 4 gateways de API + alerta no Slack se o tmb (manual) atrasar.
#
# ⚠️  DISTINÇÃO (mesma do validation):
#   - deploy_capi.sh             = API de produção (Cloud Run Service 24/7)
#   - deploy_validation_job.sh   = Job de validação semanal (Cloud Run Job batch)
#   - deploy_ingestion_job.sh    = Jobs de ingestão diária (este; Cloud Run Job batch)
#
# ⚠️  A imagem precisa CONTER o código novo (--incremental / --daily). Por padrão este
#     script faz build; use --reuse-image só se a :latest já tiver esse código.
# O Scheduler (cron) é criado à parte: setup_ingestion_schedulers.sh.
# =============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/config.sh"

# =============================================================================
# VARIÁVEIS DE CONTROLE
# =============================================================================

JOB_KIND=""            # leads | sales (de --job)
JOB_NAME=""            # resolvido de JOB_KIND
JOB_ARGS=""            # script + flags passados ao python
JOB_DESC=""            # descrição em linguagem natural
JOB_TASK_TIMEOUT=""    # timeout específico do job
IMAGE_TAG=""
YES_FLAG=false
EXECUTE_NOW=false
REUSE_IMAGE=false

# Jobs de ingestão são leves (processam poucos milhares de linhas) → menos recurso que validação.
INGESTION_MEMORY="${INGESTION_MEMORY:-2Gi}"
INGESTION_CPU="${INGESTION_CPU:-1}"

# =============================================================================
# RESOLVER JOB A PARTIR DE --job
# =============================================================================

resolve_job() {
    case "$JOB_KIND" in
        leads)
            JOB_NAME="$INGESTION_LEADS_JOB"
            JOB_ARGS="/app/src/data/leads_unify.py,--incremental"
            JOB_DESC="anexa os leads novos do ledger (registros_ml) ao train_unified"
            JOB_TASK_TIMEOUT="1800"
            ;;
        sales)
            JOB_NAME="$INGESTION_SALES_JOB"
            JOB_ARGS="/app/src/validation/etl_sales.py,--daily"
            JOB_DESC="puxa vendas dos 4 gateways de API + alerta se o tmb manual atrasar"
            JOB_TASK_TIMEOUT="900"
            ;;
        *)
            print_error "--job inválido: '$JOB_KIND' (use 'leads' ou 'sales')"
            exit 1
            ;;
    esac
}

# =============================================================================
# VALIDAÇÕES PRÉ-DEPLOY
# =============================================================================

validate_prerequisites() {
    print_header "1. VALIDAÇÕES PRÉ-DEPLOY"

    validate_gcloud
    validate_auth
    validate_project "$PROJECT_ID"

    if [ "$REUSE_IMAGE" = false ]; then
        validate_docker
        if [ ! -f "$SCRIPT_DIR/Dockerfile" ]; then
            print_error "Dockerfile não encontrado em: $SCRIPT_DIR/Dockerfile"
            exit 1
        fi
        print_success "Dockerfile encontrado"
    fi
    echo ""
}

# =============================================================================
# BUILD / REUSO DA IMAGEM (mesma da API/validação)
# =============================================================================

build_docker_image() {
    print_header "2. IMAGEM DOCKER"

    if [ "$REUSE_IMAGE" = true ]; then
        IMAGE_TAG="latest"
        print_warning "Reusando imagem :latest — confirme que ela já tem o código novo (--incremental/--daily)."
        return 0
    fi

    IMAGE_TAG="v$(date +%Y%m%d_%H%M%S)"
    local IMAGE_FULL="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"
    local IMAGE_LATEST="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:latest"

    MODEL_PATH=$(grep "model_path:" "$CONFIG_FILE" | awk '{print $2}')
    [ -z "$MODEL_PATH" ] && { print_error "model_path não encontrado em $CONFIG_FILE"; exit 1; }

    print_info "Build linux/amd64 (tag $IMAGE_TAG)…"
    cd "$PROJECT_ROOT"
    docker buildx build \
        --platform linux/amd64 \
        --build-arg MODEL_PATH="$MODEL_PATH" \
        -f api/Dockerfile \
        -t "$IMAGE_FULL" \
        -t "$IMAGE_LATEST" \
        --push \
        . || { print_error "Falha no build da imagem"; exit 1; }
    print_success "Imagem publicada: $IMAGE_TAG"
    echo ""
}

# =============================================================================
# DEPLOY DO CLOUD RUN JOB
# =============================================================================

deploy_ingestion_job() {
    print_header "3. DEPLOY DO CLOUD RUN JOB"

    local IMAGE_TO_DEPLOY="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"
    print_info "Job: $JOB_NAME  ($JOB_DESC)"
    print_info "Imagem: $IMAGE_TO_DEPLOY"
    print_info "Região: $REGION | Memória: $INGESTION_MEMORY | CPU: $INGESTION_CPU | Timeout: ${JOB_TASK_TIMEOUT}s"

    # ⚠️ CRÍTICO: variáveis de ambiente (DB do ledger via Secret Manager, Slack, etc.) — NÃO remover.
    local ENV_VARS
    ENV_VARS=$(build_env_vars) || { print_error "build_env_vars falhou (segredo do ledger indisponível?)"; exit 1; }
    if [ "$ENV_VARS" = "ERROR_LEDGER_SECRET_UNAVAILABLE" ]; then
        print_error "Não consegui obter a senha do ledger no Secret Manager. Abortando."
        exit 1
    fi

    # Sem --set-cloudsql-instances: o ledger é acessado por IP público + SSL (LEDGER_DB_*),
    # igual ao leads_unify._open / analytics_connection. Cloud Run Jobs usam --set-env-vars.
    gcloud run jobs deploy "$JOB_NAME" \
        --image "$IMAGE_TO_DEPLOY" \
        --region "$REGION" \
        --memory "$INGESTION_MEMORY" \
        --cpu "$INGESTION_CPU" \
        --task-timeout "$JOB_TASK_TIMEOUT" \
        --max-retries 1 \
        --set-env-vars="$ENV_VARS" \
        --command python \
        --args="$JOB_ARGS" \
        --quiet || { print_error "Falha no deploy do Cloud Run Job"; exit 1; }

    print_success "Deploy concluído: $JOB_NAME"
    echo ""
}

# =============================================================================
# TESTE OPCIONAL
# =============================================================================

test_job_execution() {
    print_header "4. TESTE (OPCIONAL)"
    if [ "$EXECUTE_NOW" = false ]; then
        print_warning "Teste pulado. Use --execute-now para rodar agora."
        return 0
    fi
    print_info "Executando $JOB_NAME (dados reais!)…"
    gcloud run jobs execute "$JOB_NAME" --region "$REGION" --quiet || {
        print_error "Falha ao iniciar execução"; return 1; }
    print_success "Execução iniciada"
    print_info "Logs: gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --limit 50"
    echo ""
}

# =============================================================================
# RELATÓRIO FINAL
# =============================================================================

print_final_report() {
    print_header "RELATÓRIO FINAL"
    echo -e "${GREEN}✅ Job de ingestão deployado:${NC} $JOB_NAME"
    echo "   $JOB_DESC"
    echo "   Imagem: $IMAGE_TAG | Região: $REGION"
    echo ""
    echo -e "${BLUE}Executar manualmente:${NC}"
    echo "   gcloud run jobs execute $JOB_NAME --region $REGION"
    echo ""
    echo -e "${BLUE}Próximo passo — agendar (cron):${NC}"
    echo "   bash api/setup_ingestion_schedulers.sh"
    echo ""
}

# =============================================================================
# PARSE DE ARGUMENTOS
# =============================================================================

usage() {
    echo "Uso: $0 --job {leads|sales} [OPTIONS]"
    echo ""
    echo "  --job leads|sales      Qual job de ingestão deployar (obrigatório)"
    echo "  --reuse-image          Reusar imagem :latest (não fazer build)"
    echo "  --execute-now          Executar o job logo após o deploy (teste)"
    echo "  --yes, -y              Pular confirmação"
    echo "  -h, --help             Esta mensagem"
    exit 1
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --job) JOB_KIND="${2:-}"; shift 2;;
            --reuse-image) REUSE_IMAGE=true; shift;;
            --execute-now) EXECUTE_NOW=true; shift;;
            --yes|-y) YES_FLAG=true; shift;;
            -h|--help) usage;;
            *) print_error "Argumento desconhecido: $1"; usage;;
        esac
    done
    [ -z "$JOB_KIND" ] && { print_error "--job é obrigatório (leads|sales)"; usage; }
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    parse_arguments "$@"
    resolve_job

    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║   Bring Data - Deploy de Job de Ingestão Automática (Cloud Run) ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    print_info "Job: $JOB_NAME — $JOB_DESC"
    print_info "Projeto: $PROJECT_ID | Região: $REGION"
    [ "$REUSE_IMAGE" = true ] && print_info "Modo: reusar :latest" || print_info "Modo: build nova imagem"
    [ "$EXECUTE_NOW" = true ] && print_warning "Job será EXECUTADO após o deploy (dados reais!)"
    echo ""

    if [ "$YES_FLAG" = false ]; then
        read -p "Continuar com o deploy? (y/n) " -n 1 -r; echo ""
        [[ $REPLY =~ ^[Yy]$ ]] || { print_warning "Deploy cancelado"; exit 0; }
    fi

    validate_prerequisites
    build_docker_image
    deploy_ingestion_job
    test_job_execution
    print_final_report
    print_success "Concluído! 🎉"
}

main "$@"
