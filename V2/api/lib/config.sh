#!/bin/bash
# =============================================================================
# Configuração Centralizada - Smart Ads Deploy Scripts
# =============================================================================
#
# Single Source of Truth para todas as configurações do projeto.
# Permite override via environment variables para máxima flexibilidade.
#
# Uso: source "$(dirname "$0")/lib/config.sh"
#
# Para customizar configurações:
#   export PROJECT_ID="meu-projeto"
#   export REGION="us-east1"
#   ./deploy.sh
#
# =============================================================================

# =============================================================================
# CONFIGURAÇÕES GCP
# =============================================================================

# Projeto e região
PROJECT_ID="${PROJECT_ID:-smart-ads-451319}"
REGION="${REGION:-us-central1}"

# Cloud Run
SERVICE_NAME="${SERVICE_NAME:-smart-ads-api}"
GCR_REGISTRY="${GCR_REGISTRY:-gcr.io}"

# Recursos do Container - SERVICE (CAPI + Monitoramento)
MEMORY="${MEMORY:-2Gi}"  # Suficiente para CAPI + Monitoramento
CPU="${CPU:-2}"
TIMEOUT="${TIMEOUT:-600}"  # 10 minutos (original, necessário para monitoramento)
MIN_INSTANCES="${MIN_INSTANCES:-1}"
MAX_INSTANCES="${MAX_INSTANCES:-100}"
CONCURRENCY="${CONCURRENCY:-80}"

# Recursos do Container - JOB (Validação ML)
JOB_MEMORY="${JOB_MEMORY:-4Gi}"  # Validação processa 30k+ leads + API Meta
JOB_CPU="${JOB_CPU:-2}"
JOB_TIMEOUT="${JOB_TIMEOUT:-1200}"  # 20 minutos para validação completa com API Meta

# Ambiente
ENVIRONMENT="${ENVIRONMENT:-production}"

# =============================================================================
# CLOUD SQL (POSTGRESQL) - Descomissionado em 25/02/2026 (DevClub usa Railway)
# Manter comentado como template para novos clientes que precisem de Cloud SQL
# =============================================================================

# CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-smart-ads-db}"
# CLOUD_SQL_CONNECTION="${CLOUD_SQL_CONNECTION:-$PROJECT_ID:$REGION:$CLOUD_SQL_INSTANCE}"
# DB_NAME="${DB_NAME:-smart_ads}"
# DB_USER="${DB_USER:-postgres}"
# DB_PASSWORD="${DB_PASSWORD:-SmartAds2026DB!}"

# =============================================================================
# RAILWAY POSTGRESQL (LEAD SCORING — CAMINHO B)
# =============================================================================

RAILWAY_DB_HOST="${RAILWAY_DB_HOST:-shortline.proxy.rlwy.net}"
RAILWAY_DB_PORT="${RAILWAY_DB_PORT:-11594}"
RAILWAY_DB_NAME="${RAILWAY_DB_NAME:-railway}"
RAILWAY_DB_USER="${RAILWAY_DB_USER:-postgres}"
RAILWAY_DB_PASSWORD="${RAILWAY_DB_PASSWORD:-THxguXxQPZaSWIzquYRiLlVhJBnPoRGu}"

# =============================================================================
# CLOUD STORAGE (VALIDATION REPORTS)
# =============================================================================

BUCKET_NAME="${BUCKET_NAME:-smart-ads-validation-reports}"

# =============================================================================
# CLOUD SCHEDULER (VALIDATION AUTOMATION)
# =============================================================================

SCHEDULER_JOB="${SCHEDULER_JOB:-validation-weekly}"
SCHEDULER_SCHEDULE="${SCHEDULER_SCHEDULE:-0 10 * * MON}"  # Segunda 10h UTC (7h Brasília)
SCHEDULER_DESCRIPTION="${SCHEDULER_DESCRIPTION:-Validação semanal do modelo ML (toda segunda 10h UTC)}"

# =============================================================================
# SLACK (NOTIFICATIONS)
# =============================================================================

SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-https://hooks.slack.com/services/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}"

# =============================================================================
# META API (DATA SOURCE)
# =============================================================================

# Meta Data Source: 'api' (extração via Meta API) ou 'local' (extração via CSV/Excel local)
META_DATA_SOURCE="${META_DATA_SOURCE:-api}"

# =============================================================================
# GURU API (DATA SOURCE)
# =============================================================================

# Guru Data Source: 'api' (extração via Guru API) ou 'local' (arquivos CSV locais)
GURU_DATA_SOURCE="${GURU_DATA_SOURCE:-api}"

# =============================================================================
# DIRETÓRIOS DO PROJETO
# =============================================================================

# Nota: Estes são calculados dinamicamente, mas podem ser overridden
SCRIPT_DIR="${SCRIPT_DIR:-$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )}"
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$SCRIPT_DIR")}"
MODEL_DIR="${MODEL_DIR:-$PROJECT_ROOT/files}"
CONFIG_FILE="${CONFIG_FILE:-$PROJECT_ROOT/configs/active_model.yaml}"
BUSINESS_CONFIG="${BUSINESS_CONFIG:-$SCRIPT_DIR/business_config.py}"
CLIENT_ID="${CLIENT_ID:-devclub}"
CLIENT_CONFIG_FILE="${CLIENT_CONFIG_FILE:-$PROJECT_ROOT/configs/clients/${CLIENT_ID}.yaml}"

# =============================================================================
# ENVIRONMENT VARIABLES PARA CLOUD RUN
# =============================================================================

# Monta string de environment variables para Cloud Run
# Preserva META_ACCESS_TOKEN se já estiver configurado
build_env_vars() {
    local ENV_VARS="ENVIRONMENT=$ENVIRONMENT"
    ENV_VARS="$ENV_VARS,META_DATA_SOURCE=$META_DATA_SOURCE"
    ENV_VARS="$ENV_VARS,GURU_DATA_SOURCE=$GURU_DATA_SOURCE"
    ENV_VARS="$ENV_VARS,VALIDATION_REPORTS_BUCKET=$BUCKET_NAME"
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
    ENV_VARS="$ENV_VARS,TZ=America/Sao_Paulo"
    ENV_VARS="$ENV_VARS,RAILWAY_DB_HOST=$RAILWAY_DB_HOST"
    ENV_VARS="$ENV_VARS,RAILWAY_DB_PORT=$RAILWAY_DB_PORT"
    ENV_VARS="$ENV_VARS,RAILWAY_DB_NAME=$RAILWAY_DB_NAME"
    ENV_VARS="$ENV_VARS,RAILWAY_DB_USER=$RAILWAY_DB_USER"
    ENV_VARS="$ENV_VARS,RAILWAY_DB_PASSWORD=$RAILWAY_DB_PASSWORD"

    # Preserva META_ACCESS_TOKEN existente
    local CURRENT_META_TOKEN=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --format="value(spec.template.spec.containers[0].env.find(name=META_ACCESS_TOKEN).value)" 2>/dev/null || echo "")

    if [ -n "$CURRENT_META_TOKEN" ]; then
        ENV_VARS="$ENV_VARS,META_ACCESS_TOKEN=$CURRENT_META_TOKEN"
    fi

    echo "$ENV_VARS"
}

# =============================================================================
# VALIDAÇÃO DE CONFIGURAÇÃO
# =============================================================================

# Valida que configurações críticas estão definidas
validate_config() {
    local ERRORS=0

    if [ -z "$PROJECT_ID" ]; then
        echo "ERROR: PROJECT_ID não está definido" >&2
        ERRORS=$((ERRORS + 1))
    fi

    if [ -z "$REGION" ]; then
        echo "ERROR: REGION não está definido" >&2
        ERRORS=$((ERRORS + 1))
    fi

    if [ -z "$SERVICE_NAME" ]; then
        echo "ERROR: SERVICE_NAME não está definido" >&2
        ERRORS=$((ERRORS + 1))
    fi

    # Cloud SQL descomissionado em 25/02/2026 — descomentar para novos clientes com Cloud SQL
    # if [ -z "$CLOUD_SQL_INSTANCE" ]; then
    #     echo "ERROR: CLOUD_SQL_INSTANCE não está definido" >&2
    #     ERRORS=$((ERRORS + 1))
    # fi
    # if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ]; then
    #     echo "ERROR: Credenciais do banco de dados não estão completas" >&2
    #     ERRORS=$((ERRORS + 1))
    # fi

    if [ $ERRORS -gt 0 ]; then
        return 1
    fi

    return 0
}

# =============================================================================
# FIM
# =============================================================================
