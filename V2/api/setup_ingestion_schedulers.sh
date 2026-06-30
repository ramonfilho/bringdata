#!/bin/bash
# =============================================================================
# Setup dos Cloud Schedulers da INGESTÃO AUTOMÁTICA (leads + vendas)
# =============================================================================
#
# Cria/atualiza os 2 crons que disparam os Cloud Run Jobs de ingestão (deployados
# por deploy_ingestion_job.sh). Espelha o setup_validation.sh; a diferença é o alvo:
# aqui o Scheduler chama o Cloud Run Job direto (run.googleapis.com :run) com uma
# Service Account que tem roles/run.invoker — não passa pela API de produção.
#
# Idempotente: se o scheduler já existe, atualiza; senão, cria.
#
# Uso: ./setup_ingestion_schedulers.sh [--sa <email>] [--yes]
#   --sa   Service Account que o Scheduler usa p/ invocar (default: compute SA do projeto)
# =============================================================================

set -e
set -u

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/config.sh"

SCHEDULER_SA="${SCHEDULER_SA:-}"
YES_FLAG=false

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --sa) SCHEDULER_SA="${2:-}"; shift 2;;
            --yes|-y) YES_FLAG=true; shift;;
            -h|--help) echo "Uso: $0 [--sa <email>] [--yes]"; exit 0;;
            *) print_error "Argumento desconhecido: $1"; exit 1;;
        esac
    done
}

# =============================================================================
# VALIDAÇÕES
# =============================================================================

validate_prerequisites() {
    print_header "1. VALIDAÇÕES"
    validate_gcloud
    validate_auth
    validate_project "$PROJECT_ID"
    validate_gcp_apis "run.googleapis.com" "cloudscheduler.googleapis.com"

    # SA default = compute SA do projeto (precisa roles/run.invoker nos jobs)
    if [ -z "$SCHEDULER_SA" ]; then
        local proj_num
        proj_num=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
        SCHEDULER_SA="${proj_num}-compute@developer.gserviceaccount.com"
    fi
    print_info "Service Account do Scheduler: $SCHEDULER_SA"
    echo ""
}

# =============================================================================
# UPSERT DE UM SCHEDULER (Scheduler → Cloud Run Job :run)
# =============================================================================

run_job_uri() {
    # endpoint da API admin do Cloud Run que dispara uma execução do job
    echo "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/$1:run"
}

upsert_scheduler() {
    local name="$1" cron="$2" job="$3" desc="$4"
    local uri; uri="$(run_job_uri "$job")"

    # garantir que a SA pode invocar o job
    gcloud run jobs add-iam-policy-binding "$job" \
        --region="$REGION" \
        --member="serviceAccount:$SCHEDULER_SA" \
        --role="roles/run.invoker" \
        --quiet >/dev/null
    print_info "  run.invoker garantido p/ $SCHEDULER_SA em $job"

    if gcloud scheduler jobs describe "$name" --location="$REGION" &>/dev/null; then
        gcloud scheduler jobs update http "$name" \
            --location="$REGION" \
            --schedule="$cron" \
            --time-zone="Etc/UTC" \
            --uri="$uri" \
            --http-method=POST \
            --oauth-service-account-email="$SCHEDULER_SA" \
            --quiet
        print_success "  scheduler atualizado: $name ($cron UTC)"
    else
        gcloud scheduler jobs create http "$name" \
            --location="$REGION" \
            --schedule="$cron" \
            --time-zone="Etc/UTC" \
            --uri="$uri" \
            --http-method=POST \
            --oauth-service-account-email="$SCHEDULER_SA" \
            --description="$desc" \
            --quiet
        print_success "  scheduler criado: $name ($cron UTC)"
    fi
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    parse_arguments "$@"

    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║   Bring Data - Setup dos Schedulers de Ingestão Automática      ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    print_info "Projeto: $PROJECT_ID | Região: $REGION"
    print_info "Leads:   $INGESTION_LEADS_JOB   ($INGESTION_LEADS_SCHEDULE UTC)"
    print_info "Vendas:  $INGESTION_SALES_JOB   ($INGESTION_SALES_SCHEDULE UTC)"
    echo ""

    validate_prerequisites

    if [ "$YES_FLAG" = false ]; then
        read -p "Criar/atualizar os 2 schedulers? (y/n) " -n 1 -r; echo ""
        [[ $REPLY =~ ^[Yy]$ ]] || { print_warning "Cancelado"; exit 0; }
    fi

    print_header "2. CLOUD SCHEDULERS"
    upsert_scheduler "${INGESTION_LEADS_JOB}-cron" "$INGESTION_LEADS_SCHEDULE" \
        "$INGESTION_LEADS_JOB" "Ingestão diária: anexa leads novos do ledger ao train_unified"
    upsert_scheduler "${INGESTION_SALES_JOB}-cron" "$INGESTION_SALES_SCHEDULE" \
        "$INGESTION_SALES_JOB" "Ingestão diária: vendas dos 4 gateways API + alerta tmb stale"

    print_header "PRONTO"
    echo "Schedulers (região $REGION):"
    echo "  ${INGESTION_LEADS_JOB}-cron   $INGESTION_LEADS_SCHEDULE UTC (06:00 BRT)"
    echo "  ${INGESTION_SALES_JOB}-cron   $INGESTION_SALES_SCHEDULE UTC (06:30 BRT)"
    echo ""
    echo "Disparar um agora (teste):"
    echo "  gcloud scheduler jobs run ${INGESTION_LEADS_JOB}-cron --location $REGION"
    echo ""
    print_success "Concluído! 🎉"
}

main "$@"
