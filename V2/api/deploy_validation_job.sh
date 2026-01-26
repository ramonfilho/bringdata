#!/bin/bash
# =============================================================================
# Script de Deploy - Smart Ads ML Validation Job (Cloud Run Job)
# =============================================================================
#
# Descrição: Deploy do Job de Validação Semanal do Modelo ML
# Uso: ./deploy_validation_job.sh [--yes]
#
# ⚠️  IMPORTANTE - DISTINÇÃO:
#   - deploy.sh = Deploy da API em PRODUÇÃO (Cloud Run Service - 24/7 HTTP)
#   - deploy_validation_job.sh = Deploy do JOB de Validação (Cloud Run Job - batch)
#
# O Job roda ISOLADAMENTE da API de produção. Usa a mesma imagem Docker,
# mas executa apenas o script de validação validate_ml_performance.py.
#
# Funcionalidades:
#   1. Validações pré-deploy (Docker, gcloud, Cloud SQL, etc.)
#   2. Build/reuso da imagem Docker (mesma da API)
#   3. Deploy do Cloud Run Job com configurações corretas
#   4. Teste opcional do Job
#
# ⚠️  CRÍTICO - PROTEÇÃO CONTRA PERDA DE DADOS:
#   Este script configura OBRIGATORIAMENTE as variáveis de ambiente do PostgreSQL.
#   O Job de validação PRECISA dessas variáveis para:
#     - Registrar leads processados no banco
#     - Fazer upload de relatórios para Cloud Storage
#     - Enviar notificações para Slack
#
#   NUNCA remova --set-env-vars ou --set-cloudsql-instances!
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

# Importar configurações centralizadas (PROJECT_ID, REGION, etc.)
source "$SCRIPT_DIR/lib/config.sh"

# =============================================================================
# VARIÁVEIS DE CONTROLE ESPECÍFICAS DO JOB
# =============================================================================

JOB_NAME="validation-weekly-job"
IMAGE_TAG=""
YES_FLAG=false
EXECUTE_NOW=false
REUSE_IMAGE=false

# =============================================================================
# VALIDAÇÕES PRÉ-DEPLOY
# =============================================================================

validate_prerequisites() {
    print_header "1. VALIDAÇÕES PRÉ-DEPLOY"

    # 1.1 Docker (para build, se necessário)
    validate_docker

    # 1.2 gcloud CLI
    validate_gcloud

    # 1.3 Autenticação GCP
    validate_auth

    # 1.4 Projeto GCP
    validate_project "$PROJECT_ID"

    # 1.5 Dockerfile
    print_info "Verificando Dockerfile..."
    if [ ! -f "$SCRIPT_DIR/Dockerfile" ]; then
        print_error "Dockerfile não encontrado em: $SCRIPT_DIR/Dockerfile"
        exit 1
    fi
    print_success "Dockerfile encontrado"

    # 1.6 Script de validação
    VALIDATION_SCRIPT="$PROJECT_ROOT/src/validation/validate_ml_performance.py"
    print_info "Verificando script de validação..."
    if [ ! -f "$VALIDATION_SCRIPT" ]; then
        print_error "validate_ml_performance.py não encontrado em: $VALIDATION_SCRIPT"
        exit 1
    fi
    print_success "Script de validação encontrado"

    # 1.7 ⚠️ CRÍTICO: Verificar Cloud SQL
    validate_cloud_sql "$CLOUD_SQL_INSTANCE" "$REGION" "$DB_NAME" "$DB_USER" "$DB_PASSWORD"

    # 1.8 Verificar se já existe uma imagem (para reuso)
    print_info "Verificando imagem Docker existente..."
    EXISTING_IMAGE=$(gcloud container images list-tags "$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME" \
        --limit=1 \
        --format="value(tags)" 2>/dev/null | head -n 1 || echo "")

    if [ -n "$EXISTING_IMAGE" ]; then
        print_success "Imagem existente encontrada: $EXISTING_IMAGE"
        print_info "Você pode reusar essa imagem ou fazer novo build"
    else
        print_warning "Nenhuma imagem existente encontrada - build será necessário"
    fi

    echo ""
}

# =============================================================================
# BUILD DA IMAGEM DOCKER
# =============================================================================

build_docker_image() {
    print_header "2. BUILD DA IMAGEM DOCKER"

    # Se usuário escolheu reusar imagem
    if [ "$REUSE_IMAGE" = true ]; then
        IMAGE_TAG="latest"
        print_info "Reusando imagem existente: $IMAGE_TAG"
        return 0
    fi

    # Determinar tag da imagem
    IMAGE_TAG="v$(date +%Y%m%d_%H%M%S)"
    IMAGE_FULL="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"
    IMAGE_LATEST="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:latest"

    print_info "Tag da imagem: $IMAGE_TAG"
    print_info "Imagem completa: $IMAGE_FULL"

    # Ler MODEL_PATH do active_model.yaml (necessário para API, mas incluído no Job também)
    MODEL_PATH=$(grep "model_path:" "$CONFIG_FILE" | awk '{print $2}')
    if [ -z "$MODEL_PATH" ]; then
        print_error "model_path não encontrado em active_model.yaml"
        exit 1
    fi
    print_info "Modelo ativo: $MODEL_PATH"

    # Build para linux/amd64 (Cloud Run requer)
    print_info "Iniciando build (linux/amd64)..."
    cd "$PROJECT_ROOT"

    docker buildx build \
        --platform linux/amd64 \
        --build-arg MODEL_PATH="$MODEL_PATH" \
        -f api/Dockerfile \
        -t "$IMAGE_FULL" \
        -t "$IMAGE_LATEST" \
        --push \
        . || {
            print_error "Falha no build da imagem Docker"
            exit 1
        }

    print_success "Imagem construída e enviada para GCR"
    print_success "Tag: $IMAGE_TAG"
    echo ""
}

# =============================================================================
# DEPLOY NO CLOUD RUN JOB
# =============================================================================

deploy_validation_job() {
    print_header "3. DEPLOY DO CLOUD RUN JOB"

    IMAGE_TO_DEPLOY="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"

    print_info "Job: $JOB_NAME"
    print_info "Imagem: $IMAGE_TO_DEPLOY"
    print_info "Região: $REGION"
    print_info "Memória: $JOB_MEMORY"
    print_info "CPU: $JOB_CPU"
    print_info "Timeout: ${JOB_TIMEOUT}s"

    # ⚠️ CRÍTICO: Configurar variáveis de ambiente (NÃO REMOVER!)
    # O Job precisa dessas variáveis para acessar banco, storage, Slack, etc.
    print_info "Configurando variáveis de ambiente..."
    ENV_VARS=$(build_env_vars)
    print_success "Variáveis de ambiente configuradas (via lib/config.sh)"

    # Deploy do Job
    # IMPORTANTE: Cloud Run Jobs usam --set-env-vars (não --update-env-vars)
    # Configurado para Campanha Atípica 1 (Dez/2025 - Jan/2026)
    gcloud run jobs deploy $JOB_NAME \
        --image "$IMAGE_TO_DEPLOY" \
        --region $REGION \
        --memory $JOB_MEMORY \
        --cpu $JOB_CPU \
        --task-timeout $JOB_TIMEOUT \
        --max-retries 0 \
        --set-env-vars="$ENV_VARS" \
        --set-cloudsql-instances="$CLOUD_SQL_CONNECTION" \
        --command python \
        --args /app/src/validation/validate_ml_performance.py,--start-date,2025-12-16,--end-date,2026-01-12,--sales-start-date,2026-01-19,--sales-end-date,2026-01-25 \
        --quiet || {
            print_error "Falha no deploy do Cloud Run Job"
            exit 1
        }

    print_success "Deploy do Job concluído"

    print_info "O Job está configurado para executar:"
    print_info "  python /app/src/validation/validate_ml_performance.py \\"
    print_info "    --start-date 2025-12-16 --end-date 2026-01-12 \\"
    print_info "    --sales-start-date 2026-01-19 --sales-end-date 2026-01-25"
    print_info ""
    print_info "Campanha Atípica 1: Dez/2025 - Jan/2026 (28 dias captação, fim de ano)"
    echo ""
}

# =============================================================================
# TESTE DO JOB
# =============================================================================

test_job_execution() {
    print_header "4. TESTE DO JOB (OPCIONAL)"

    if [ "$EXECUTE_NOW" = false ]; then
        print_warning "Teste pulado. Use --execute-now para testar imediatamente"
        return 0
    fi

    print_info "Executando Job de teste..."
    print_warning "Isso irá processar DADOS REAIS de validação!"
    print_warning "A execução pode levar 6-10 minutos"

    # Executar Job e capturar execution name
    EXECUTION_NAME=$(gcloud run jobs execute $JOB_NAME \
        --region $REGION \
        --format="value(metadata.name)" 2>&1 | tail -n 1)

    if [ -z "$EXECUTION_NAME" ]; then
        print_error "Falha ao iniciar execução do Job"
        return 1
    fi

    print_success "Job iniciado: $EXECUTION_NAME"
    print_info "Acompanhe os logs com:"
    print_info "  gcloud logging tail \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --format=json"

    echo ""
    print_info "Verificar status:"
    print_info "  gcloud run jobs executions describe $EXECUTION_NAME --region $REGION"
    echo ""
}

# =============================================================================
# RELATÓRIO FINAL
# =============================================================================

print_final_report() {
    print_header "RELATÓRIO FINAL"

    echo -e "${GREEN}✅ Deploy do Job de Validação concluído com sucesso!${NC}\n"

    echo -e "${BLUE}📊 Job:${NC}"
    echo "   Nome: $JOB_NAME"
    echo "   Imagem: $IMAGE_TAG"
    echo "   Região: $REGION"
    echo ""

    echo -e "${BLUE}🔧 Comandos Úteis:${NC}"
    echo ""
    echo "   Executar Job manualmente:"
    echo "   gcloud run jobs execute $JOB_NAME --region $REGION"
    echo ""
    echo "   Ver logs da última execução:"
    echo "   gcloud logging tail \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --format=json"
    echo ""
    echo "   Ver execuções do Job:"
    echo "   gcloud run jobs executions list --job=$JOB_NAME --region=$REGION"
    echo ""
    echo "   Deletar Job (se necessário):"
    echo "   gcloud run jobs delete $JOB_NAME --region=$REGION"
    echo ""

    echo -e "${BLUE}📅 Próximos Passos:${NC}"
    echo "   1. Configurar Cloud Scheduler para disparar o Job semanalmente"
    echo "   2. Usar este comando no Scheduler:"
    echo "      gcloud run jobs execute $JOB_NAME --region $REGION"
    echo ""
}

# =============================================================================
# PARSE DE ARGUMENTOS
# =============================================================================

usage() {
    echo "Uso: $0 [OPTIONS]"
    echo ""
    echo "Opções:"
    echo "  --reuse-image          Reusar imagem Docker existente (não fazer novo build)"
    echo "  --execute-now          Executar Job imediatamente após deploy (teste)"
    echo "  --yes, -y              Pular confirmação"
    echo "  -h, --help             Mostrar esta mensagem"
    echo ""
    echo "Exemplos:"
    echo "  $0                     # Build nova imagem e deploy"
    echo "  $0 --yes               # Deploy sem confirmação"
    echo "  $0 --reuse-image       # Reusar imagem existente"
    echo "  $0 --execute-now       # Deploy e testar imediatamente"
    echo "  $0 --reuse-image --yes --execute-now  # Reuso + teste"
    exit 1
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --reuse-image)
                REUSE_IMAGE=true
                shift
                ;;
            --execute-now)
                EXECUTE_NOW=true
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
    echo "║    Smart Ads - Deploy do Job de Validação ML (Cloud Run)      ║"
    echo "║                                                                ║"
    echo "║    ⚠️  IMPORTANTE: Este é o JOB de validação, NÃO a API      ║"
    echo "║    A API de produção usa: deploy.sh                           ║"
    echo "║                                                                ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    # Confirmação
    print_info "Job: $JOB_NAME"
    print_info "Projeto GCP: $PROJECT_ID"
    print_info "Região: $REGION"

    if [ "$REUSE_IMAGE" = true ]; then
        print_info "Modo: Reusar imagem existente"
    else
        print_info "Modo: Build nova imagem Docker"
    fi

    if [ "$EXECUTE_NOW" = true ]; then
        print_warning "Teste: Job será EXECUTADO após deploy (dados reais!)"
    fi
    echo ""

    if [ "$YES_FLAG" = false ]; then
        read -p "Continuar com o deploy? (y/n) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_warning "Deploy cancelado pelo usuário"
            exit 0
        fi
    else
        print_success "Confirmação pulada (--yes)"
    fi

    # Executar pipeline de deploy
    validate_prerequisites
    build_docker_image
    deploy_validation_job
    test_job_execution

    # Relatório final
    print_final_report

    print_success "Deploy do Job concluído com sucesso! 🎉"
}

# Executar
main "$@"
