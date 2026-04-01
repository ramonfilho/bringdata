#!/bin/bash
# =============================================================================
# Biblioteca Compartilhada - Bring Data Deploy Scripts
# =============================================================================
#
# Funções e validações compartilhadas entre deploy.sh e setup_validation.sh
# para evitar duplicação de código e garantir consistência.
#
# Uso: source "$(dirname "$0")/lib/common.sh"
#
# =============================================================================

# =============================================================================
# CORES PARA OUTPUT
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# FUNÇÕES DE PRINT
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
# VALIDAÇÕES GCP
# =============================================================================

# Valida se gcloud CLI está instalado
validate_gcloud() {
    print_info "Verificando gcloud CLI..."
    if ! command -v gcloud &> /dev/null; then
        print_error "gcloud CLI não está instalado"
        print_error "Instale: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi
    print_success "gcloud CLI instalado"
}

# Valida autenticação GCP
validate_auth() {
    print_info "Verificando autenticação GCP..."
    local CURRENT_ACCOUNT=$(gcloud config get-value account 2>/dev/null)
    if [ -z "$CURRENT_ACCOUNT" ]; then
        print_error "Não autenticado no GCP. Execute: gcloud auth login"
        exit 1
    fi
    print_success "Autenticado como: $CURRENT_ACCOUNT"
}

# Valida e configura projeto GCP
# Parâmetros: $1 = PROJECT_ID esperado
validate_project() {
    local PROJECT_ID="$1"

    if [ -z "$PROJECT_ID" ]; then
        print_error "PROJECT_ID não fornecido para validate_project()"
        exit 1
    fi

    print_info "Verificando projeto GCP..."
    local CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
    if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
        print_warning "Projeto atual: $CURRENT_PROJECT. Mudando para: $PROJECT_ID"
        gcloud config set project "$PROJECT_ID"
    fi
    print_success "Projeto: $PROJECT_ID"
}

# ⚠️  CRÍTICO: Valida que Cloud SQL (PostgreSQL) está rodando
# Parâmetros: $1 = CLOUD_SQL_INSTANCE, $2 = REGION, $3 = DB_NAME, $4 = DB_USER, $5 = DB_PASSWORD
validate_cloud_sql() {
    local CLOUD_SQL_INSTANCE="$1"
    local REGION="$2"
    local DB_NAME="$3"
    local DB_USER="$4"
    local DB_PASSWORD="$5"

    if [ -z "$CLOUD_SQL_INSTANCE" ]; then
        print_error "CLOUD_SQL_INSTANCE não fornecido para validate_cloud_sql()"
        exit 1
    fi

    print_info "Verificando Cloud SQL instance..."

    local CLOUD_SQL_STATUS=$(gcloud sql instances describe "$CLOUD_SQL_INSTANCE" \
        --format="value(state)" 2>/dev/null || echo "NOT_FOUND")

    if [ "$CLOUD_SQL_STATUS" = "RUNNABLE" ]; then
        print_success "Cloud SQL está RODANDO (instance: $CLOUD_SQL_INSTANCE)"
        return 0
    elif [ "$CLOUD_SQL_STATUS" = "NOT_FOUND" ]; then
        print_error "Cloud SQL instance '$CLOUD_SQL_INSTANCE' NÃO ENCONTRADA!"
        print_error ""
        print_error "🚨 BLOQUEADO - POSTGRESQL OBRIGATÓRIO 🚨"
        print_error ""
        print_error "Sem Cloud SQL, o deploy usará SQLite e TODOS os leads CAPI serão"
        print_error "PERDIDOS a cada deploy (SQLite fica em /tmp/ que é destruído)."
        print_error ""
        print_error "SOLUÇÃO:"
        print_error "1. Crie a instance Cloud SQL:"
        print_error "   gcloud sql instances create $CLOUD_SQL_INSTANCE \\"
        print_error "     --database-version=POSTGRES_15 \\"
        print_error "     --tier=db-f1-micro \\"
        print_error "     --region=$REGION"
        print_error ""
        print_error "2. Configure o banco de dados:"
        print_error "   gcloud sql databases create $DB_NAME --instance=$CLOUD_SQL_INSTANCE"
        print_error "   gcloud sql users set-password $DB_USER --instance=$CLOUD_SQL_INSTANCE --password=$DB_PASSWORD"
        print_error ""
        exit 1
    else
        print_error "Cloud SQL em estado inválido: $CLOUD_SQL_STATUS"
        print_error "Aguarde a instance ficar RUNNABLE antes de continuar"
        exit 1
    fi
}

# Valida que APIs GCP necessárias estão habilitadas
# Parâmetros: $@ = lista de APIs (ex: "run.googleapis.com" "sqladmin.googleapis.com")
validate_gcp_apis() {
    local APIS=("$@")

    if [ ${#APIS[@]} -eq 0 ]; then
        print_warning "Nenhuma API fornecida para validate_gcp_apis()"
        return 0
    fi

    print_info "Verificando APIs necessárias..."

    for api in "${APIS[@]}"; do
        if gcloud services list --enabled --filter="name:$api" --format="value(name)" 2>/dev/null | grep -q "$api"; then
            print_success "$api habilitada"
        else
            print_warning "$api não habilitada. Habilitando..."
            gcloud services enable "$api" --quiet
            print_success "$api habilitada"
        fi
    done
}

# =============================================================================
# VALIDAÇÕES DOCKER (apenas para deploy.sh)
# =============================================================================

# Valida que Docker está instalado e rodando
validate_docker() {
    print_info "Verificando Docker..."

    if ! command -v docker &> /dev/null; then
        print_error "Docker não está instalado"
        print_error "Instale: https://www.docker.com/products/docker-desktop"
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
}

# =============================================================================
# VALIDAÇÕES CLOUD RUN
# =============================================================================

# Verifica se Cloud Run service existe
# Parâmetros: $1 = SERVICE_NAME, $2 = REGION
check_cloud_run_service() {
    local SERVICE_NAME="$1"
    local REGION="$2"

    if [ -z "$SERVICE_NAME" ] || [ -z "$REGION" ]; then
        print_error "SERVICE_NAME e REGION são obrigatórios para check_cloud_run_service()"
        exit 1
    fi

    print_info "Verificando Cloud Run service..."
    if gcloud run services describe "$SERVICE_NAME" --region="$REGION" &>/dev/null; then
        print_success "Cloud Run service '$SERVICE_NAME' existe"
        return 0
    else
        print_warning "Cloud Run service '$SERVICE_NAME' não existe"
        print_warning "Será criado no primeiro deploy"
        return 1
    fi
}

# Obtém URL do Cloud Run service
# Parâmetros: $1 = SERVICE_NAME, $2 = REGION
get_cloud_run_url() {
    local SERVICE_NAME="$1"
    local REGION="$2"

    if [ -z "$SERVICE_NAME" ] || [ -z "$REGION" ]; then
        print_error "SERVICE_NAME e REGION são obrigatórios para get_cloud_run_url()"
        exit 1
    fi

    gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --format="value(status.url)" 2>/dev/null || echo ""
}

# =============================================================================
# VALIDAÇÕES CLOUD STORAGE
# =============================================================================

# Verifica se bucket existe
# Parâmetros: $1 = BUCKET_NAME
bucket_exists() {
    local BUCKET_NAME="$1"

    if [ -z "$BUCKET_NAME" ]; then
        print_error "BUCKET_NAME é obrigatório para bucket_exists()"
        exit 1
    fi

    gsutil ls "gs://$BUCKET_NAME" &>/dev/null
}

# Torna bucket público (para links compartilháveis)
# Parâmetros: $1 = BUCKET_NAME
make_bucket_public() {
    local BUCKET_NAME="$1"

    if [ -z "$BUCKET_NAME" ]; then
        print_error "BUCKET_NAME é obrigatório para make_bucket_public()"
        exit 1
    fi

    local IAM_POLICY=$(gsutil iam get "gs://$BUCKET_NAME" 2>/dev/null || echo "")
    if echo "$IAM_POLICY" | grep -q "allUsers"; then
        print_success "Bucket está público (links compartilháveis)"
    else
        print_warning "Bucket não está público. Tornando público..."
        gsutil iam ch allUsers:objectViewer "gs://$BUCKET_NAME"
        print_success "Bucket agora está público"
    fi
}

# =============================================================================
# FIM
# =============================================================================
