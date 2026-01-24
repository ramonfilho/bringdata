#!/bin/bash
# =============================================================================
# Script de Deploy Automatizado - Smart Ads Lead Scoring API
# =============================================================================
#
# Descrição: Automatiza todo o processo de deploy da API no Google Cloud Run
# Uso: ./deploy.sh [--env production|staging] [--model-version YYYYMMDD_HHMMSS]
#
# Funcionalidades:
#   1. Validações pré-deploy (Docker, gcloud, arquivos)
#   2. Build da imagem Docker (linux/amd64)
#   3. Deploy no Cloud Run com configurações corretas
#   4. Testes pós-deploy (health check + predição)
#   5. Rollback automático em caso de falha
#   6. Relatório detalhado
#
# ⚠️  CRÍTICO - PROTEÇÃO CONTRA PERDA DE DADOS:
#   Este script configura OBRIGATORIAMENTE as variáveis de ambiente do PostgreSQL.
#   SEM essas variáveis, a API cai no fallback SQLite e TODOS os leads CAPI são
#   PERDIDOS a cada deploy (SQLite fica em /tmp/ que é destruído).
#
#   NUNCA remova as linhas de --update-env-vars e --add-cloudsql-instances!
#
# =============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configurações do GCP
PROJECT_ID="smart-ads-451319"
REGION="us-central1"
SERVICE_NAME="smart-ads-api"
GCR_REGISTRY="gcr.io"

# Configurações do Container
MEMORY="2Gi"
CPU="2"
TIMEOUT="600"  # 10 minutos para validação
MIN_INSTANCES="1"
MAX_INSTANCES="100"
CONCURRENCY="80"

# Diretórios
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MODEL_DIR="$PROJECT_ROOT/files"
CONFIG_FILE="$PROJECT_ROOT/configs/active_model.yaml"
BUSINESS_CONFIG="$SCRIPT_DIR/business_config.py"

# Variáveis de controle
ENVIRONMENT="production"
MODEL_VERSION=""
IMAGE_TAG=""
SKIP_TESTS=false
ALLOW_PUBLIC=true  # Temporário - mudar para false em produção
PREVIOUS_REVISION=""
YES_FLAG=false  # Pula confirmação se true

# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# =============================================================================
# VALIDAÇÕES PRÉ-DEPLOY
# =============================================================================

validate_prerequisites() {
    print_header "1. VALIDAÇÕES PRÉ-DEPLOY"

    # 1.1 Docker
    print_info "Verificando Docker..."
    if ! command -v docker &> /dev/null; then
        print_error "Docker não está instalado"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        print_warning "Docker não está rodando. Iniciando Docker Desktop..."
        open -a Docker

        print_info "Aguardando Docker inicializar (timeout: 120s)..."
        for i in {1..60}; do
            if docker info &> /dev/null 2>&1; then
                print_success "Docker iniciado com sucesso!"
                break
            fi
            echo -n "."
            sleep 2

            if [ $i -eq 60 ]; then
                echo ""
                print_error "Timeout: Docker não inicializou em 120 segundos"
                print_error "Inicie o Docker Desktop manualmente e tente novamente"
                exit 1
            fi
        done
        echo ""
    else
        print_success "Docker está rodando"
    fi

    # 1.2 gcloud CLI
    print_info "Verificando gcloud CLI..."
    if ! command -v gcloud &> /dev/null; then
        print_error "gcloud CLI não está instalado"
        exit 1
    fi
    print_success "gcloud CLI instalado"

    # 1.3 Autenticação GCP
    print_info "Verificando autenticação GCP..."
    CURRENT_ACCOUNT=$(gcloud config get-value account 2>/dev/null)
    if [ -z "$CURRENT_ACCOUNT" ]; then
        print_error "Não autenticado no GCP. Execute: gcloud auth login"
        exit 1
    fi
    print_success "Autenticado como: $CURRENT_ACCOUNT"

    # 1.4 Projeto GCP
    print_info "Verificando projeto GCP..."
    CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
    if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
        print_warning "Projeto atual: $CURRENT_PROJECT. Mudando para: $PROJECT_ID"
        gcloud config set project $PROJECT_ID
    fi
    print_success "Projeto: $PROJECT_ID"

    # 1.5 Dockerfile
    print_info "Verificando Dockerfile..."
    if [ ! -f "$SCRIPT_DIR/Dockerfile" ]; then
        print_error "Dockerfile não encontrado em: $SCRIPT_DIR/Dockerfile"
        exit 1
    fi
    print_success "Dockerfile encontrado"

    # 1.6 active_model.yaml
    print_info "Verificando active_model.yaml..."
    if [ ! -f "$CONFIG_FILE" ]; then
        print_error "active_model.yaml não encontrado em: $CONFIG_FILE"
        exit 1
    fi

    # Extrair model_path do YAML
    MODEL_PATH=$(grep "model_path:" "$CONFIG_FILE" | awk '{print $2}')
    if [ -z "$MODEL_PATH" ]; then
        print_error "model_path não encontrado em active_model.yaml"
        exit 1
    fi

    FULL_MODEL_DIR="$PROJECT_ROOT/$MODEL_PATH"
    if [ ! -d "$FULL_MODEL_DIR" ]; then
        print_error "Diretório do modelo não existe: $FULL_MODEL_DIR"
        exit 1
    fi
    print_success "Modelo ativo: $MODEL_PATH"

    # 1.7 Arquivos do modelo
    print_info "Verificando arquivos do modelo..."
    MODEL_PKL=$(find "$FULL_MODEL_DIR" -name "*.pkl" | head -n 1)
    if [ -z "$MODEL_PKL" ]; then
        print_error "Arquivo .pkl não encontrado em: $FULL_MODEL_DIR"
        exit 1
    fi

    MODEL_METADATA=$(find "$FULL_MODEL_DIR" -name "model_metadata_*.json" | head -n 1)
    if [ -z "$MODEL_METADATA" ]; then
        print_error "model_metadata_*.json não encontrado em: $FULL_MODEL_DIR"
        exit 1
    fi

    FEATURES_JSON=$(find "$FULL_MODEL_DIR" -name "features_ordenadas_*.json" | head -n 1)
    if [ -z "$FEATURES_JSON" ]; then
        print_error "features_ordenadas_*.json não encontrado em: $FULL_MODEL_DIR"
        exit 1
    fi
    print_success "Arquivos do modelo validados"

    # 1.8 business_config.py
    print_info "Verificando business_config.py..."
    if [ ! -f "$BUSINESS_CONFIG" ]; then
        print_error "business_config.py não encontrado em: $BUSINESS_CONFIG"
        exit 1
    fi

    # Verificar se PRODUCT_VALUE está definido
    if ! grep -q "^PRODUCT_VALUE = " "$BUSINESS_CONFIG"; then
        print_error "PRODUCT_VALUE não encontrado em business_config.py"
        exit 1
    fi

    PRODUCT_VALUE=$(grep "^PRODUCT_VALUE = " "$BUSINESS_CONFIG" | awk '{print $3}')
    print_success "PRODUCT_VALUE: R$ $PRODUCT_VALUE"

    # 1.9 Obter revisão atual (para rollback)
    print_info "Obtendo revisão atual do Cloud Run..."
    PREVIOUS_REVISION=$(gcloud run revisions list \
        --service=$SERVICE_NAME \
        --region=$REGION \
        --format="value(metadata.name)" \
        --limit=1 2>/dev/null || echo "")

    if [ -n "$PREVIOUS_REVISION" ]; then
        print_success "Revisão atual: $PREVIOUS_REVISION"
    else
        print_warning "Nenhuma revisão anterior encontrada (primeiro deploy?)"
    fi

    # 1.10 Verificar Cloud SQL (CRÍTICO - evita perda de dados)
    print_info "Verificando Cloud SQL..."
    CLOUD_SQL_STATUS=$(gcloud sql instances describe smart-ads-db \
        --format="value(state)" 2>/dev/null || echo "NOT_FOUND")

    if [ "$CLOUD_SQL_STATUS" = "RUNNABLE" ]; then
        print_success "Cloud SQL está rodando (smart-ads-db)"
    elif [ "$CLOUD_SQL_STATUS" = "NOT_FOUND" ]; then
        print_error "Cloud SQL instance 'smart-ads-db' não encontrada!"
        print_error "Deploy BLOQUEADO - sem Cloud SQL, todos os dados serão perdidos"
        exit 1
    else
        print_warning "Cloud SQL em estado: $CLOUD_SQL_STATUS"
    fi

    echo ""
}

# =============================================================================
# BUILD DA IMAGEM DOCKER
# =============================================================================

build_docker_image() {
    print_header "2. BUILD DA IMAGEM DOCKER"

    # Determinar tag da imagem
    if [ -n "$MODEL_VERSION" ]; then
        IMAGE_TAG="$MODEL_VERSION"
    else
        IMAGE_TAG="v$(date +%Y%m%d_%H%M%S)"
    fi

    IMAGE_FULL="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"
    IMAGE_LATEST="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:latest"

    print_info "Tag da imagem: $IMAGE_TAG"
    print_info "Imagem completa: $IMAGE_FULL"

    # Ler MODEL_PATH do active_model.yaml
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
    print_success "Modelo incluído: $MODEL_PATH"
    echo ""
}

# =============================================================================
# DEPLOY NO CLOUD RUN
# =============================================================================

deploy_to_cloud_run() {
    print_header "3. DEPLOY NO CLOUD RUN"

    IMAGE_TO_DEPLOY="$GCR_REGISTRY/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"

    print_info "Imagem: $IMAGE_TO_DEPLOY"
    print_info "Região: $REGION"
    print_info "Memória: $MEMORY"
    print_info "CPU: $CPU"
    print_info "Timeout: ${TIMEOUT}s"
    print_info "Min instances: $MIN_INSTANCES"

    # Deploy
    AUTH_FLAG="--no-allow-unauthenticated"
    if [ "$ALLOW_PUBLIC" = true ]; then
        AUTH_FLAG="--allow-unauthenticated"
    fi

    # Configurar variáveis de ambiente (CRITICAL - NÃO REMOVER!)
    # Sem essas variáveis, a API usa SQLite e PERDE TODOS OS DADOS a cada deploy
    print_info "Configurando variáveis de ambiente..."
    ENV_VARS="ENVIRONMENT=production"
    ENV_VARS="$ENV_VARS,CLOUD_SQL_CONNECTION_NAME=smart-ads-451319:us-central1:smart-ads-db"
    ENV_VARS="$ENV_VARS,DB_NAME=smart_ads"
    ENV_VARS="$ENV_VARS,DB_USER=postgres"
    ENV_VARS="$ENV_VARS,DB_PASSWORD=SmartAds2026DB!"
    ENV_VARS="$ENV_VARS,META_DATA_SOURCE=api"
    ENV_VARS="$ENV_VARS,VALIDATION_REPORTS_BUCKET=smart-ads-validation-reports"

    # Obter META_ACCESS_TOKEN da revisão atual (se existir)
    CURRENT_META_TOKEN=$(gcloud run services describe $SERVICE_NAME \
        --region=$REGION \
        --format="value(spec.template.spec.containers[0].env[?name=='META_ACCESS_TOKEN'].value)" \
        2>/dev/null || echo "")

    if [ -n "$CURRENT_META_TOKEN" ]; then
        ENV_VARS="$ENV_VARS,META_ACCESS_TOKEN=$CURRENT_META_TOKEN"
        print_success "META_ACCESS_TOKEN preservado da revisão anterior"
    else
        print_warning "META_ACCESS_TOKEN não encontrado - configure manualmente se necessário"
    fi

    print_success "Variáveis de ambiente configuradas"

    gcloud run deploy $SERVICE_NAME \
        --image "$IMAGE_TO_DEPLOY" \
        --platform managed \
        --region $REGION \
        --memory $MEMORY \
        --cpu $CPU \
        --timeout $TIMEOUT \
        --min-instances $MIN_INSTANCES \
        --max-instances $MAX_INSTANCES \
        --concurrency $CONCURRENCY \
        --update-env-vars="$ENV_VARS" \
        --add-cloudsql-instances="smart-ads-451319:us-central1:smart-ads-db" \
        $AUTH_FLAG \
        --quiet || {
            print_error "Falha no deploy para Cloud Run"
            exit 1
        }

    print_success "Deploy concluído"

    # Se acesso público temporário
    if [ "$ALLOW_PUBLIC" = true ]; then
        print_warning "Configurando acesso público (TEMPORÁRIO)"
        gcloud run services add-iam-policy-binding $SERVICE_NAME \
            --region=$REGION \
            --member="allUsers" \
            --role="roles/run.invoker" \
            --quiet || {
                print_error "Falha ao configurar acesso público"
            }
        print_warning "⚠️  API está PÚBLICA - remover antes de produção!"
    fi

    # Obter URL do serviço
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
        --region=$REGION \
        --format="value(status.url)")

    print_success "URL: $SERVICE_URL"
    echo ""
}

# =============================================================================
# TESTES PÓS-DEPLOY
# =============================================================================

run_post_deploy_tests() {
    print_header "4. TESTES PÓS-DEPLOY"

    if [ "$SKIP_TESTS" = true ]; then
        print_warning "Testes pulados (--skip-tests)"
        return 0
    fi

    # Aguardar serviço ficar pronto
    print_info "Aguardando serviço ficar pronto..."
    sleep 5

    # Obter URL
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
        --region=$REGION \
        --format="value(status.url)")

    # 4.1 Health Check
    print_info "Teste 1/3: Health Check..."
    HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/health" || echo "000")

    if [ "$HEALTH_RESPONSE" != "200" ]; then
        print_error "Health check falhou (HTTP $HEALTH_RESPONSE)"
        return 1
    fi
    print_success "Health check: OK (200)"

    # 4.2 Verificar logs de erro
    print_info "Teste 2/3: Verificando logs de erro..."
    ERROR_COUNT=$(gcloud logging read \
        "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME AND severity>=ERROR AND timestamp>=\"$(date -u -v-5M +%Y-%m-%dT%H:%M:%SZ)\"" \
        --limit=10 \
        --format="value(textPayload)" 2>/dev/null | wc -l | tr -d ' ')

    if [ "$ERROR_COUNT" -gt 0 ]; then
        print_warning "Encontrados $ERROR_COUNT erros nos últimos 5 minutos"
        print_info "Visualize com: gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME AND severity>=ERROR' --limit=10"
    else
        print_success "Nenhum erro encontrado nos logs"
    fi

    # 4.3 Teste de predição
    print_info "Teste 3/3: Teste de predição..."

    # Payload de teste
    TEST_PAYLOAD='{
  "leads": [
    {
      "data": {
        "Data": "2025-09-30T07:00:00.000Z",
        "Nome Completo": "João Silva",
        "E-mail": "joao@example.com",
        "Telefone": 5511999999999,
        "O seu gênero:": "Masculino",
        "Qual a sua idade?": "25 - 34 anos",
        "Atualmente, qual a sua faixa salarial?": "Entre R$2.001 a R$3.000 reais ao mês",
        "Você possui cartão de crédito?": "Sim",
        "Já estudou programação?": "Não",
        "Source": "facebook-ads",
        "Medium": "Linguagem de programação",
        "Term": "instagram",
        "O que você faz atualmente?": "Sou CLT/Funcionário Público",
        "O que mais você quer ver no evento?": "Fazer transição de carreira e conseguir meu primeiro emprego na área",
        "Tem computador/notebook?": "Sim",
        "Você já fez, faz, pretende fazer faculdade?": "Sim",
        "investiu_curso_online": "Não",
        "interesse_programacao": "Todas as alternativas"
      },
      "email": "joao@example.com",
      "row_id": "test_1"
    }
  ]
}'

    PRED_RESPONSE=$(curl -s -X POST "$SERVICE_URL/predict/batch" \
        -H "Content-Type: application/json" \
        -d "$TEST_PAYLOAD" || echo "")

    if [ -z "$PRED_RESPONSE" ]; then
        print_error "Predição falhou: sem resposta"
        return 1
    fi

    # Verificar se resposta contém "predictions"
    if echo "$PRED_RESPONSE" | grep -q '"predictions"'; then
        LEAD_SCORE=$(echo "$PRED_RESPONSE" | grep -o '"lead_score":[0-9.]*' | head -n 1 | cut -d':' -f2)
        DECILE=$(echo "$PRED_RESPONSE" | grep -o '"decile":"[^"]*"' | head -n 1 | cut -d'"' -f4)
        print_success "Predição: score=$LEAD_SCORE, decile=$DECILE"
    else
        print_error "Predição falhou: resposta inválida"
        echo "$PRED_RESPONSE"
        return 1
    fi

    print_success "Todos os testes passaram!"
    echo ""
    return 0
}

# =============================================================================
# ROLLBACK
# =============================================================================

rollback_deploy() {
    print_header "5. ROLLBACK"

    if [ -z "$PREVIOUS_REVISION" ]; then
        print_error "Nenhuma revisão anterior para rollback"
        return 1
    fi

    print_warning "Fazendo rollback para: $PREVIOUS_REVISION"

    gcloud run services update-traffic $SERVICE_NAME \
        --region=$REGION \
        --to-revisions="$PREVIOUS_REVISION=100" \
        --quiet || {
            print_error "Falha no rollback"
            return 1
        }

    print_success "Rollback concluído"
    return 0
}

# =============================================================================
# RELATÓRIO FINAL
# =============================================================================

print_final_report() {
    print_header "RELATÓRIO FINAL"

    # Informações básicas
    echo -e "${GREEN}✅ Deploy concluído com sucesso!${NC}\n"

    # Detalhes do modelo
    MODEL_NAME=$(grep "model_name:" "$CONFIG_FILE" | awk '{print $2}')
    MODEL_PATH=$(grep "model_path:" "$CONFIG_FILE" | awk '{print $2}')
    AUC=$(grep "auc:" "$CONFIG_FILE" | awk '{print $2}')
    MONOTONIA=$(grep "monotonia_percentage:" "$CONFIG_FILE" | awk '{print $2}')

    echo -e "${BLUE}📊 Modelo:${NC}"
    echo "   Nome: $MODEL_NAME"
    echo "   Path: $MODEL_PATH"
    echo "   AUC: $AUC"
    echo "   Monotonia: $MONOTONIA%"
    echo ""

    # Detalhes do deploy
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
        --region=$REGION \
        --format="value(status.url)")

    CURRENT_REVISION=$(gcloud run revisions list \
        --service=$SERVICE_NAME \
        --region=$REGION \
        --format="value(metadata.name)" \
        --limit=1)

    echo -e "${BLUE}🚀 Deploy:${NC}"
    echo "   Imagem: $IMAGE_TAG"
    echo "   Revisão: $CURRENT_REVISION"
    echo "   URL: $SERVICE_URL"
    echo ""

    if [ -n "$PREVIOUS_REVISION" ]; then
        echo -e "${BLUE}↩️  Rollback (se necessário):${NC}"
        echo "   Revisão anterior: $PREVIOUS_REVISION"
        echo "   Comando: gcloud run services update-traffic $SERVICE_NAME --region=$REGION --to-revisions=$PREVIOUS_REVISION=100"
        echo ""
    fi

    # Comandos úteis
    echo -e "${BLUE}🔧 Comandos Úteis:${NC}"
    echo "   Ver logs:"
    echo "   gcloud logging tail \"resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME\""
    echo ""
    echo "   Ver logs de erro:"
    echo "   gcloud logging read \"resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME AND severity>=ERROR\" --limit=20"
    echo ""
    echo "   Ver revisões:"
    echo "   gcloud run revisions list --service=$SERVICE_NAME --region=$REGION"
    echo ""
    echo "   Status do serviço:"
    echo "   gcloud run services describe $SERVICE_NAME --region=$REGION"
    echo ""

    # Avisos
    if [ "$ALLOW_PUBLIC" = true ]; then
        echo -e "${YELLOW}⚠️  AVISOS:${NC}"
        echo "   - API está PÚBLICA (temporário)"
        echo "   - Remover antes de produção:"
        echo "     gcloud run services remove-iam-policy-binding $SERVICE_NAME \\"
        echo "       --region=$REGION \\"
        echo "       --member=\"allUsers\" \\"
        echo "       --role=\"roles/run.invoker\""
        echo ""
    fi
}

# =============================================================================
# PARSE DE ARGUMENTOS
# =============================================================================

usage() {
    echo "Uso: $0 [OPTIONS]"
    echo ""
    echo "Opções:"
    echo "  --env ENV              Ambiente (production|staging) [default: production]"
    echo "  --model-version VER    Versão do modelo (ex: 20260109_110657) [default: timestamp]"
    echo "  --skip-tests           Pular testes pós-deploy"
    echo "  --no-public            Deploy sem acesso público (requer Service Account)"
    echo "  --yes, -y              Pular confirmação (não perguntar)"
    echo "  -h, --help             Mostrar esta mensagem"
    echo ""
    echo "Exemplos:"
    echo "  $0"
    echo "  $0 --yes"
    echo "  $0 --env production --model-version 20260109_110657"
    echo "  $0 --skip-tests --no-public --yes"
    exit 1
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --env)
                ENVIRONMENT="$2"
                shift 2
                ;;
            --model-version)
                MODEL_VERSION="$2"
                shift 2
                ;;
            --skip-tests)
                SKIP_TESTS=true
                shift
                ;;
            --no-public)
                ALLOW_PUBLIC=false
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
    echo "║       Smart Ads Lead Scoring API - Deploy Automatizado        ║"
    echo "║                                                                ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    # Confirmação
    print_info "Ambiente: $ENVIRONMENT"
    print_info "Projeto GCP: $PROJECT_ID"
    print_info "Região: $REGION"
    print_info "Serviço: $SERVICE_NAME"
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
    deploy_to_cloud_run

    # Testes pós-deploy
    if ! run_post_deploy_tests; then
        print_error "Testes pós-deploy falharam"
        read -p "Fazer rollback? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rollback_deploy
        fi
        exit 1
    fi

    # Relatório final
    print_final_report

    print_success "Deploy concluído com sucesso! 🎉"
}

# Executar
main "$@"
