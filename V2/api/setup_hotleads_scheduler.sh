#!/bin/bash
# =============================================================================
# Scheduler do HotLeads — submissão recorrente de leads pro batch_enrich
# =============================================================================
#
# Cria/atualiza o Cloud Scheduler que chama POST /hotleads/submit-batch no
# serviço 24/7. Cada disparo pega até `batch_limit` leads sem selo da janela e
# submete; o selo volta pela Hotmart no /hotleads/webhook alguns minutos depois.
#
# ⚠️ AUTENTICAÇÃO: o serviço é PÚBLICO (allUsers é obrigatório enquanto os crons
#    não mandam OIDC — ver incidente do apagão de 23/07). Por isso o endpoint tem
#    token próprio, mandado aqui no header X-HotLeads-Token. NÃO trocar por
#    --oauth-service-account-email achando que protege: o endpoint continuaria
#    aberto pra quem souber a URL. O token é a proteção real.
#
# Idempotente: o endpoint só pega quem está com hotleads_status NULL ou
# 'submitted' vencido, então rodar de novo (ou duas vezes juntas) não duplica.
#
# Uso: ./setup_hotleads_scheduler.sh [--schedule "*/15 * * * *"] [--pause] [--run-now]
# =============================================================================
set -e
set -u

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/config.sh"

JOB_NAME="${HOTLEADS_JOB_NAME:-hotleads-submit}"
# A cada 15 min: o lote é de até 1.000 leads e a captação do DevClub em pico faz
# ~1.500/dia, então 15 min mantém a fila sempre curta sem martelar a API.
SCHEDULE="${HOTLEADS_SCHEDULE:-*/15 * * * *}"
SERVICE_URL="${HOTLEADS_PUBLIC_URL:-https://smart-ads-api-gazrm25mda-uc.a.run.app}"

PAUSE=false
RUN_NOW=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --schedule) SCHEDULE="$2"; shift 2 ;;
        --pause)    PAUSE=true; shift ;;
        --run-now)  RUN_NOW=true; shift ;;
        *) echo "argumento desconhecido: $1"; exit 1 ;;
    esac
done

TOKEN="${HOTLEADS_CRON_TOKEN:-$(gcloud secrets versions access latest --secret=hotleads-cron-token --project="$PROJECT_ID" 2>/dev/null)}"
if [ -z "$TOKEN" ]; then
    echo "ERRO: sem HOTLEADS_CRON_TOKEN (nem no ambiente, nem no Secret Manager)."
    echo "      O scheduler seria criado e tomaria 401 em silêncio."
    exit 1
fi

URI="${SERVICE_URL}/hotleads/submit-batch"

if [ "$PAUSE" = true ]; then
    gcloud scheduler jobs pause "$JOB_NAME" --location="$REGION" --quiet
    echo "scheduler pausado: $JOB_NAME"
    exit 0
fi

if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" &>/dev/null; then
    gcloud scheduler jobs update http "$JOB_NAME" \
        --location="$REGION" \
        --schedule="$SCHEDULE" \
        --time-zone="America/Sao_Paulo" \
        --uri="$URI" \
        --http-method=POST \
        --update-headers="X-HotLeads-Token=$TOKEN" \
        --attempt-deadline=600s \
        --quiet
    echo "scheduler atualizado: $JOB_NAME ($SCHEDULE)"
else
    gcloud scheduler jobs create http "$JOB_NAME" \
        --location="$REGION" \
        --schedule="$SCHEDULE" \
        --time-zone="America/Sao_Paulo" \
        --uri="$URI" \
        --http-method=POST \
        --headers="X-HotLeads-Token=$TOKEN" \
        --attempt-deadline=600s \
        --description="HotLeads: submete leads recentes sem selo ao batch_enrich da Hotmart" \
        --quiet
    echo "scheduler criado: $JOB_NAME ($SCHEDULE)"
fi

if [ "$RUN_NOW" = true ]; then
    gcloud scheduler jobs run "$JOB_NAME" --location="$REGION" --quiet
    echo "execução manual disparada"
fi
