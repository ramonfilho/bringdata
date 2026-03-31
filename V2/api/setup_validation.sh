#!/bin/bash
# =============================================================================
# Setup de Validação Semanal - Bring Data ML
# =============================================================================
#
# Descrição: Configura infraestrutura completa para validação semanal automática
# Uso: ./setup_validation.sh [--project-id PROJECT] [--yes]
#
# Funcionalidades:
#   1. ✅ Valida Cloud SQL (PostgreSQL) - CRÍTICO para evitar perda de dados
#   2. ✅ Cria Cloud Storage bucket (se não existir)
#   3. ✅ Cria Cloud Scheduler job (se não existir)
#   4. ✅ Configura environment variables no Cloud Run
#   5. ✅ Executa deploy.sh automaticamente (com proteções PostgreSQL)
#
# ⚠️  PROTEÇÃO CONTRA PERDA DE DADOS:
#   Este script EXIGE que Cloud SQL (PostgreSQL) esteja rodando.
#   Se não estiver, o setup é BLOQUEADO para evitar deploy com SQLite.
#   SQLite em /tmp/ perde TODOS os dados de leads CAPI a cada deploy.
#
# =============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# =============================================================================
# IMPORTAR BIBLIOTECAS COMPARTILHADAS
# =============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Importar funções compartilhadas (cores, print_*, validações GCP)
source "$SCRIPT_DIR/lib/common.sh"

# Importar configurações centralizadas (PROJECT_ID, REGION, DB credentials, etc.)
source "$SCRIPT_DIR/lib/config.sh"

# =============================================================================
# VARIÁVEIS DE CONTROLE ESPECÍFICAS DO SETUP
# =============================================================================

YES_FLAG=false
SKIP_DEPLOY=false

# =============================================================================
# VALIDAÇÕES PRÉ-SETUP
# =============================================================================

validate_prerequisites() {
    print_header "1. VALIDAÇÕES PRÉ-SETUP"

    # 1.1 gcloud CLI (da lib/common.sh)
    validate_gcloud

    # 1.2 Autenticação GCP (da lib/common.sh)
    validate_auth

    # 1.3 Projeto GCP (da lib/common.sh)
    validate_project "$PROJECT_ID"

    # 1.4 APIs habilitadas (da lib/common.sh)
    validate_gcp_apis "run.googleapis.com" "sqladmin.googleapis.com" "storage.googleapis.com" "cloudscheduler.googleapis.com"

    # 1.5 ⚠️ CRÍTICO: Validar Cloud SQL PostgreSQL (da lib/common.sh)
    print_header "🔴 VALIDAÇÃO CRÍTICA: POSTGRESQL"
    validate_cloud_sql "$CLOUD_SQL_INSTANCE" "$REGION" "$DB_NAME" "$DB_USER" "$DB_PASSWORD"

    # 1.6 Verificar se Cloud Run service existe (da lib/common.sh)
    check_cloud_run_service "$SERVICE_NAME" "$REGION"

    echo ""
}

# =============================================================================
# CLOUD STORAGE SETUP
# =============================================================================

setup_cloud_storage() {
    print_header "2. CLOUD STORAGE BUCKET"

    # Verificar se bucket existe (usa função da lib/common.sh)
    if bucket_exists "$BUCKET_NAME"; then
        print_success "Bucket já existe: gs://$BUCKET_NAME"

        # Tornar público se necessário (usa função da lib/common.sh)
        make_bucket_public "$BUCKET_NAME"
    else
        print_info "Criando bucket: gs://$BUCKET_NAME"
        gsutil mb -l "$REGION" "gs://$BUCKET_NAME"
        print_success "Bucket criado"

        # Tornar público (usa função da lib/common.sh)
        make_bucket_public "$BUCKET_NAME"
    fi

    # Verificar estrutura de pastas
    print_info "Verificando estrutura de pastas..."
    if gsutil ls "gs://$BUCKET_NAME/validation/" &>/dev/null; then
        print_success "Estrutura de pastas OK"
    else
        print_info "Criando estrutura de pastas..."
        echo "" | gsutil cp - "gs://$BUCKET_NAME/validation/.keep" 2>/dev/null || true
        print_success "Estrutura criada: gs://$BUCKET_NAME/validation/"
    fi

    echo ""
}

# =============================================================================
# CLOUD SCHEDULER SETUP
# =============================================================================

setup_cloud_scheduler() {
    print_header "3. CLOUD SCHEDULER JOB"

    # Obter URL do Cloud Run service (usa função da lib/common.sh)
    SERVICE_URL=$(get_cloud_run_url "$SERVICE_NAME" "$REGION")

    if [ -z "$SERVICE_URL" ]; then
        print_warning "Cloud Run service ainda não deployado"
        print_warning "URL será: https://$SERVICE_NAME-<hash>.$REGION.run.app/validation/weekly"
        print_warning "Job do scheduler será criado mas pode falhar até primeiro deploy"
        SERVICE_URL="https://$SERVICE_NAME-placeholder.$REGION.run.app"
    else
        print_success "Cloud Run URL: $SERVICE_URL"
    fi

    ENDPOINT_URL="$SERVICE_URL/validation/weekly"

    # Verificar se job existe
    if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location="$REGION" &>/dev/null; then
        print_success "Scheduler job já existe: $SCHEDULER_JOB"

        # Verificar configuração atual
        CURRENT_SCHEDULE=$(gcloud scheduler jobs describe "$SCHEDULER_JOB" \
            --location="$REGION" \
            --format="value(schedule)")
        CURRENT_URI=$(gcloud scheduler jobs describe "$SCHEDULER_JOB" \
            --location="$REGION" \
            --format="value(httpTarget.uri)")
        CURRENT_STATE=$(gcloud scheduler jobs describe "$SCHEDULER_JOB" \
            --location="$REGION" \
            --format="value(state)")

        print_info "Schedule atual: $CURRENT_SCHEDULE"
        print_info "Endpoint atual: $CURRENT_URI"
        print_info "Estado: $CURRENT_STATE"

        # Verificar se precisa atualizar
        if [ "$CURRENT_URI" != "$ENDPOINT_URL" ]; then
            print_warning "Endpoint desatualizado. Atualizando..."
            gcloud scheduler jobs update http "$SCHEDULER_JOB" \
                --location="$REGION" \
                --uri="$ENDPOINT_URL" \
                --quiet
            print_success "Endpoint atualizado"
        fi

        # Verificar se está habilitado
        if [ "$CURRENT_STATE" != "ENABLED" ]; then
            print_warning "Job está pausado. Habilitando..."
            gcloud scheduler jobs resume "$SCHEDULER_JOB" --location="$REGION" --quiet
            print_success "Job habilitado"
        fi
    else
        print_info "Criando scheduler job: $SCHEDULER_JOB"
        gcloud scheduler jobs create http "$SCHEDULER_JOB" \
            --location="$REGION" \
            --schedule="$SCHEDULER_SCHEDULE" \
            --uri="$ENDPOINT_URL" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --description="$SCHEDULER_DESCRIPTION" \
            --quiet

        print_success "Scheduler job criado"
        print_success "Agendamento: Toda segunda-feira às 10h UTC (7h Brasília)"
    fi

    # Mostrar próxima execução
    NEXT_RUN=$(gcloud scheduler jobs describe "$SCHEDULER_JOB" \
        --location="$REGION" \
        --format="value(scheduleTime)" 2>/dev/null || echo "N/A")

    if [ "$NEXT_RUN" != "N/A" ]; then
        print_info "Próxima execução: $NEXT_RUN"
    fi

    echo ""
}

# =============================================================================
# ENVIRONMENT VARIABLES
# =============================================================================

configure_env_vars() {
    print_header "4. ENVIRONMENT VARIABLES"

    # Verificar se service existe
    if ! gcloud run services describe "$SERVICE_NAME" --region="$REGION" &>/dev/null; then
        print_warning "Cloud Run service ainda não existe"
        print_warning "Env vars serão configuradas no primeiro deploy via deploy.sh"
        echo ""
        return
    fi

    print_info "Configurando variáveis de ambiente no Cloud Run..."

    # ⚠️ CRÍTICO: Usar função centralizada de lib/config.sh
    ENV_VARS=$(build_env_vars)

    # Atualizar env vars
    gcloud run services update "$SERVICE_NAME" \
        --region="$REGION" \
        --update-env-vars="$ENV_VARS" \
        --quiet

    print_success "Environment variables configuradas"
    print_success "PostgreSQL: ✅ $CLOUD_SQL_CONNECTION"
    print_success "Bucket: ✅ $BUCKET_NAME"
    print_success "Slack: ✅ Configurado"

    echo ""
}

# =============================================================================
# DEPLOY
# =============================================================================

run_deploy() {
    print_header "5. DEPLOY NO CLOUD RUN"

    if [ "$SKIP_DEPLOY" = true ]; then
        print_warning "Deploy pulado (--skip-deploy)"
        print_info "Execute manualmente: ./deploy.sh --yes"
        echo ""
        return
    fi

    print_info "Executando deploy.sh..."
    echo ""

    # Garantir que deploy.sh existe e é executável
    DEPLOY_SCRIPT="$(dirname "$0")/deploy.sh"
    if [ ! -f "$DEPLOY_SCRIPT" ]; then
        print_error "deploy.sh não encontrado em: $DEPLOY_SCRIPT"
        exit 1
    fi

    if [ ! -x "$DEPLOY_SCRIPT" ]; then
        chmod +x "$DEPLOY_SCRIPT"
    fi

    # Executar deploy (com flag --yes se setup foi rodado com --yes)
    if [ "$YES_FLAG" = true ]; then
        "$DEPLOY_SCRIPT" --yes
    else
        "$DEPLOY_SCRIPT"
    fi

    echo ""
}

# =============================================================================
# RELATÓRIO FINAL
# =============================================================================

print_final_report() {
    print_header "✅ SETUP CONCLUÍDO"

    echo -e "${GREEN}Sistema de validação semanal configurado com sucesso!${NC}\n"

    echo -e "${BLUE}📊 Infraestrutura Criada:${NC}"
    echo "   ✅ Cloud SQL: $CLOUD_SQL_INSTANCE (PostgreSQL)"
    echo "   ✅ Cloud Storage: gs://$BUCKET_NAME"
    echo "   ✅ Cloud Scheduler: $SCHEDULER_JOB"
    echo "   ✅ Cloud Run: $SERVICE_NAME (env vars configuradas)"
    echo ""

    echo -e "${BLUE}⏰ Agendamento:${NC}"
    echo "   Execução: Toda segunda-feira às 10h UTC (7h Brasília)"
    echo "   Endpoint: POST /validation/weekly"
    echo ""

    NEXT_RUN=$(gcloud scheduler jobs describe "$SCHEDULER_JOB" \
        --location="$REGION" \
        --format="value(scheduleTime)" 2>/dev/null || echo "N/A")

    if [ "$NEXT_RUN" != "N/A" ]; then
        echo -e "${BLUE}📅 Próxima Execução:${NC}"
        echo "   $NEXT_RUN"
        echo ""
    fi

    echo -e "${BLUE}📱 Notificações:${NC}"
    echo "   Slack webhook configurado"
    echo "   Sumário de métricas + link do Excel"
    echo ""

    echo -e "${BLUE}🔧 Comandos Úteis:${NC}"
    echo "   Testar agora:"
    echo "   gcloud scheduler jobs run $SCHEDULER_JOB --location=$REGION"
    echo ""
    echo "   Ver logs:"
    echo "   gcloud logging tail \"resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME\""
    echo ""
    echo "   Pausar validações:"
    echo "   gcloud scheduler jobs pause $SCHEDULER_JOB --location=$REGION"
    echo ""
    echo "   Retomar validações:"
    echo "   gcloud scheduler jobs resume $SCHEDULER_JOB --location=$REGION"
    echo ""

    echo -e "${GREEN}🎉 Setup completo! Sistema pronto para validações automáticas.${NC}"
}

# =============================================================================
# PARSE DE ARGUMENTOS
# =============================================================================

usage() {
    echo "Uso: $0 [OPTIONS]"
    echo ""
    echo "Opções:"
    echo "  --project-id ID        ID do projeto GCP [default: smart-ads-451319]"
    echo "  --skip-deploy          Não executar deploy.sh automaticamente"
    echo "  --yes, -y              Pular confirmação"
    echo "  -h, --help             Mostrar esta mensagem"
    echo ""
    echo "Exemplos:"
    echo "  $0                     # Setup interativo"
    echo "  $0 --yes               # Setup automático"
    echo "  $0 --skip-deploy       # Só cria infra, sem deploy"
    exit 1
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --project-id)
                PROJECT_ID="$2"
                shift 2
                ;;
            --skip-deploy)
                SKIP_DEPLOY=true
                shift
                ;;
            --yes|-y)
                YES_FLAG=true
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                print_error "Argumento desconhecido: $1"
                usage
                ;;
        esac
    done
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    # Parse argumentos
    parse_arguments "$@"

    # Banner
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                                                                ║"
    echo "║      Bring Data - Setup de Validação Semanal Automatizada      ║"
    echo "║                                                                ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    # Resumo
    print_info "Projeto GCP: $PROJECT_ID"
    print_info "Região: $REGION"
    print_info "Cloud SQL: $CLOUD_SQL_INSTANCE (PostgreSQL)"
    print_info "Bucket: $BUCKET_NAME"
    print_info "Scheduler: $SCHEDULER_JOB"
    echo ""

    # Confirmação
    if [ "$YES_FLAG" = false ]; then
        read -p "Continuar com o setup? (y/n) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_warning "Setup cancelado pelo usuário"
            exit 0
        fi
    else
        print_success "Confirmação pulada (--yes)"
    fi

    # Executar setup
    validate_prerequisites
    setup_cloud_storage
    setup_cloud_scheduler
    configure_env_vars
    run_deploy

    # Relatório final
    print_final_report
}

# Executar
main "$@"
