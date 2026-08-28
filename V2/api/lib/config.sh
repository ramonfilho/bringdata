#!/bin/bash
# =============================================================================
# Configuração Centralizada - Bring Data Deploy Scripts
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
# min-instances=0: serviço não tem interface humana (só webhook→CAPI, janela
# de minutos), cold start de ~15s é invisível pro sinal. Manter 1 custava
# ~R$ 9/dia de instância always-on sem ganho. Ver docs/operacoes_gcp_custos.md
# seção "Eliminação de min-instances no Cloud Run — 2026-05-14".
MIN_INSTANCES="${MIN_INSTANCES:-0}"
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

# CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-bring-data-db}"
# CLOUD_SQL_CONNECTION="${CLOUD_SQL_CONNECTION:-$PROJECT_ID:$REGION:$CLOUD_SQL_INSTANCE}"
# DB_NAME="${DB_NAME:-bring_data}"
# DB_USER="${DB_USER:-postgres}"
# DB_PASSWORD="${DB_PASSWORD:-<senha: gcloud secrets versions access latest --secret=mlflow-db-password>}"

# =============================================================================
# RAILWAY POSTGRESQL (LEAD SCORING — CAMINHO B)
# =============================================================================

RAILWAY_DB_HOST="${RAILWAY_DB_HOST:-shortline.proxy.rlwy.net}"
RAILWAY_DB_PORT="${RAILWAY_DB_PORT:-11594}"
RAILWAY_DB_NAME="${RAILWAY_DB_NAME:-railway}"
RAILWAY_DB_USER="${RAILWAY_DB_USER:-postgres}"
# Senha NUNCA em texto plano aqui: este repositório é PÚBLICO. Vem do Secret Manager no
# momento do deploy, e env exportada tem precedência (é assim que o desenvolvimento local
# usa o `V2/.env`, que está no `.gitignore`).
#
# ESTA LINHA CARREGOU A SENHA EM TEXTO CLARO DE 2026 ATÉ 12/08/2026, num repositório
# público, e o teste que existe justamente para travar isso não pegou. O buraco era a forma:
# `${VAR:-valor}` é o idioma de "env var com fallback", e o teste tinha um lookahead que
# liberava `${` de propósito, para não acusar leitura de ambiente. O segredo estava DENTRO
# do fallback, do lado de dentro do que o teste ignorava. Corrigido em
# `V2/tests/test_sem_credencial_no_repo.py` no mesmo commit — a trava e o vazamento que ela
# deixou passar consertam juntos, senão a próxima cópia passa igual.
RAILWAY_DB_PASSWORD="${RAILWAY_DB_PASSWORD:-$(gcloud secrets versions access latest --secret=railway-db-password --project="$PROJECT_ID" 2>/dev/null)}"

# =============================================================================
# CLOUD STORAGE (VALIDATION REPORTS)
# =============================================================================

BUCKET_NAME="${BUCKET_NAME:-bring-data-validation-reports}"

# =============================================================================
# CLOUD SCHEDULER (VALIDATION AUTOMATION)
# =============================================================================

SCHEDULER_JOB="${SCHEDULER_JOB:-validation-weekly}"
SCHEDULER_SCHEDULE="${SCHEDULER_SCHEDULE:-0 10 * * MON}"  # Segunda 10h UTC (7h Brasília)
SCHEDULER_DESCRIPTION="${SCHEDULER_DESCRIPTION:-Validação semanal do modelo ML (toda segunda 10h UTC)}"

# =============================================================================
# INGESTÃO AUTOMÁTICA (leads incremental + vendas diário) — Cloud Run Jobs
# =============================================================================
# Dois jobs batch que populam o banco sozinhos (deploy_ingestion_job.sh):
#   leads → leads_unify --incremental (anexa leads novos do ledger ao train_unified)
#   sales → etl_sales --daily (4 gateways de API + alerta se o tmb manual atrasar)
INGESTION_LEADS_JOB="${INGESTION_LEADS_JOB:-ingestion-leads-incremental}"
INGESTION_SALES_JOB="${INGESTION_SALES_JOB:-ingestion-sales-daily}"
# gasto de anúncio (etl_ad_spend --daily): materializa Meta (+Google quando o token
# OAuth voltar) por campanha×dia em analytics.ad_spend. O relatório do DM LÊ dessa
# tabela (leve, sem API viva); este job é quem a enche.
INGESTION_SPEND_JOB="${INGESTION_SPEND_JOB:-ingestion-ad-spend}"
# cadastros (cadastros_ingest --since auto): atualiza analytics.cadastros — a espinha de
# identidade (respondente da pesquisa ou não) — de forma INCREMENTAL: puxa só a Client
# alterada desde a marca d'água e reconcilia is_buyer/is_respondent server-side. Barato
# (< 1 min). A carga CHEIA (--full, ~60 min, reconstrói tudo + backfill dos respondentes
# antigos) NÃO roda no cron: é manual/semanal, pra mudança de schema ou reconciliar
# rebaixamento (estorno). Comando: python -m src.data.cadastros_ingest --full.
INGESTION_CADASTROS_JOB="${INGESTION_CADASTROS_JOB:-ingestion-cadastros-daily}"
# calendário de LFs (launch_calendar --sync-to-table): lê a planilha canônica do
# cliente e materializa as datas de lançamento em analytics.launch_calendar. Vira
# a fonte runtime do resolvedor de LF (LAUNCHES_SOURCE=table) — sem deploy a cada
# novo LF. Roda ANTES do digest/relatórios pra a tabela estar fresca.
INGESTION_LAUNCH_CAL_JOB="${INGESTION_LAUNCH_CAL_JOB:-ingestion-launch-calendar}"
# O job do calendário lê a planilha do cliente via gspread (ADC do runtime SA), então
# PRECISA rodar como a conta que tem acesso de leitura à planilha — a MESMA do serviço
# da API (smart-ads-api roda como appspot; provado que lê a planilha). Os demais jobs
# rodam como a compute default (não leem Sheets). Se a compute default for compartilhada
# na planilha um dia, dá pra apontar pra ela aqui. Vazio = compute default.
INGESTION_LAUNCH_CAL_SA="${INGESTION_LAUNCH_CAL_SA:-smart-ads-451319@appspot.gserviceaccount.com}"
# Schedules em UTC. 08:30 UTC = 05:30 BRT (calendário, antes de tudo), 09:00 UTC = 06:00 BRT (leads),
# 09:30 UTC = 06:30 BRT (vendas, após leads), 09:45 UTC = 06:45 BRT (gasto, antes do relatório
# semanal de segunda 10:00 UTC).
INGESTION_LAUNCH_CAL_SCHEDULE="${INGESTION_LAUNCH_CAL_SCHEDULE:-30 8 * * *}"
INGESTION_LEADS_SCHEDULE="${INGESTION_LEADS_SCHEDULE:-0 9 * * *}"
INGESTION_SALES_SCHEDULE="${INGESTION_SALES_SCHEDULE:-30 9 * * *}"
INGESTION_SPEND_SCHEDULE="${INGESTION_SPEND_SCHEDULE:-45 9 * * *}"
# 10:00 UTC = 07:00 BRT — DEPOIS do job de leads (06:00), pra o is_respondent refletir os
# respondentes que entraram hoje. cadastros não alimenta treino, então horário é folgado.
INGESTION_CADASTROS_SCHEDULE="${INGESTION_CADASTROS_SCHEDULE:-0 10 * * *}"

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
CLIENT_ID="${CLIENT_ID:-devclub}"
CONFIG_FILE="${CONFIG_FILE:-$PROJECT_ROOT/configs/active_models/${CLIENT_ID}.yaml}"
BUSINESS_CONFIG="${BUSINESS_CONFIG:-$SCRIPT_DIR/business_config.py}"
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
    # Fail-loud igual ao do ledger: sem a senha, a API cai no SQLite e o scoring para de
    # ler o banco operacional — em silêncio, porque nada nas rotas devolve erro por isso.
    # A sentinela é impressa e o caller aborta; `exit` aqui morreria só no subshell do
    # `$(build_env_vars)` e o deploy seguiria sem a variável.
    if [ -z "$RAILWAY_DB_PASSWORD" ]; then
        echo "ERROR_RAILWAY_SECRET_UNAVAILABLE"
        return 1
    fi
    ENV_VARS="$ENV_VARS,RAILWAY_DB_PASSWORD=$RAILWAY_DB_PASSWORD"

    # Receiver do Sendhook do SendFlow (feature "entrou no grupo"): o endpoint
    # /webhook/sendflow_group_join valida este header. Só inclui se estiver no ambiente.
    [ -n "${SENDFLOW_SENDTOK:-}" ] && ENV_VARS="$ENV_VARS,SENDFLOW_SENDTOK=$SENDFLOW_SENDTOK"

    # HotLeads (lead scoring da Hotmart → evento LeadScoringHot).
    # Dois tokens porque são duas portas com donos diferentes: o cron (nosso
    # scheduler, manda no header) e o webhook (a HOTMART chama, e como ela não
    # permite header customizado o token vai na query da URL que registramos).
    # Vêm do Secret Manager e são PINADOS aqui pelo mesmo motivo do
    # LEDGER_READ_SOURCE: o deploy usa --update-env-vars (mescla), mas um deploy
    # que não os setasse deixaria os endpoints 401 em silêncio — o cron pararia
    # de submeter e ninguém veria, porque 401 no scheduler não gera alerta.
    # Rollback da feature é hotleads.enabled:false no YAML, não tirar o token.
    HOTLEADS_CRON_TOKEN="${HOTLEADS_CRON_TOKEN:-$(gcloud secrets versions access latest --secret=hotleads-cron-token --project="$PROJECT_ID" 2>/dev/null)}"
    HOTLEADS_WEBHOOK_TOKEN="${HOTLEADS_WEBHOOK_TOKEN:-$(gcloud secrets versions access latest --secret=hotleads-webhook-token --project="$PROJECT_ID" 2>/dev/null)}"
    [ -n "$HOTLEADS_CRON_TOKEN" ] && ENV_VARS="$ENV_VARS,HOTLEADS_CRON_TOKEN=$HOTLEADS_CRON_TOKEN"
    [ -n "$HOTLEADS_WEBHOOK_TOKEN" ] && ENV_VARS="$ENV_VARS,HOTLEADS_WEBHOOK_TOKEN=$HOTLEADS_WEBHOOK_TOKEN"
    # Endereço que mandamos pra Hotmart chamar de volta com o selo. Vai junto de
    # CADA submissão (api/app.py:_hotleads_webhook_url), então corrigir aqui
    # conserta o retorno sem precisar mexer em nada no painel da Hotmart.
    #
    # APONTA PRO smart-ads-webhook, NÃO pro smart-ads-api. O principal foi fechado
    # em 06/08/2026 (perdeu o `allUsers`) e só aceita chamador com identidade
    # Google; a Hotmart é terceiro e não assina token do Google. O default anterior
    # apontava pro principal e ficou apontando depois do fechamento: a Hotmart
    # passou a levar 403 do IAM ANTES de chegar na aplicação, 478 vezes em 30 dias,
    # e o selo parou de voltar por 8 dias (último em 05/08 19:15, primeiro 403 em
    # 06/08 17:30). Nada no nosso lado gritou, porque quem quebrou foi o RETORNO e
    # o alerta do relatório vigia a fila de submissão, que o cron drena normalmente.
    #
    # O smart-ads-webhook é público de propósito e serve APENAS as rotas de webhook
    # (papel `webhook` em api/auth.py, que inclui /hotleads/webhook); todo o resto
    # dá 404. É a portaria: recebe entrega de terceiro sem abrir o prédio inteiro.
    ENV_VARS="$ENV_VARS,HOTLEADS_PUBLIC_URL=${HOTLEADS_PUBLIC_URL:-https://smart-ads-webhook-gazrm25mda-uc.a.run.app}"
    # A credencial Basic da Hotmart (HOTMART_BASIC) NÃO entra aqui: o valor tem
    # ESPAÇO ("Basic xxx") e vai por --update-secrets no deploy_capi.sh, montado
    # do Secret Manager (hotmart-basic). Ela nunca esteve no Cloud Run porque até
    # 30/07 a Hotmart só era chamada em job/local — sem ela o submit do HotLeads
    # devolve "sem token Hotmart" e o cron vira no-op silencioso.

    # Consumer Pub/Sub do sistema novo (PROCESSO_CAPI_LEAD_SURVEYS §5).
    # Sem essa flag a revisão deployada vira no-op no /pubsub/process-pending.
    # Default propagated entre deploys; mude pra "false" aqui em emergência.
    ENV_VARS="$ENV_VARS,PUBSUB_CAPI_ENABLED=true"

    # Alertas críticos: as 9 regras de src/monitoring/critical_alerts.py, avaliadas
    # de carona no polling de 5 min. O CÓDIGO nasce MUDO: os dois pontos que leem a
    # flag (critical_alerts.py:711 e :764) têm default 'true', e em dry-run o
    # despachante só loga "[DRY-RUN] enviaria DM" e não posta nada.
    # A produção está ao vivo desde ~15/08/2026 só porque alguém setou a env na mão
    # no serviço, e o deploy usa --update-env-vars (MESCLA), que preserva o valor sem
    # o script saber que ele existe. Recriar o serviço do zero, ou um deploy com
    # --set-env-vars, devolveria os 9 alertas ao silêncio SEM NINGUÉM VER: alerta que
    # não dispara não tem como avisar que parou. Mesmo motivo do LEDGER_TARGET abaixo:
    # comportamento crítico mora no default daqui, não em env que alguém precisa
    # lembrar. Rollback consciente = exportar CRITICAL_ALERTS_DRY_RUN=true.
    # A entrega ainda depende de SLACK_BOT_TOKEN (secret montado no serviço) e de
    # SLACK_USER_DM; sem os dois, _post_dm devolve 'error' e o alerta morre na porta.
    ENV_VARS="$ENV_VARS,CRITICAL_ALERTS_DRY_RUN=${CRITICAL_ALERTS_DRY_RUN:-false}"

    # Ledger no Cloud SQL nosso (PLANO_LEDGER_CLOUDSQL.md Etapa 4).
    # LEDGER_TARGET: railway | dual (migração) | cloudsql (final — DEFAULT desde 23/06).
    # DEFAULT=cloudsql: a Etapa 4 cortou a escrita no Railway após 7 dias de
    # paridade limpa (16→23/06; acervo event_id 28.573=28.573, 0 só-no-Railway).
    # O consumer grava SÓ no Cloud SQL agora. 'dual' religa o espelho Railway
    # (rollback consciente); 'railway' nunca mais (Cloud SQL é a fonte canônica).
    # Por que o comportamento crítico mora no default daqui e não em env
    # exportada: em 13/06 ~18h UTC um deploy concorrente sem a env reverteu pra
    # railway e o Cloud SQL ficou ~2h sem receber (40 leads só no Railway).
    # Senha NUNCA em texto plano aqui — vem do Secret Manager no momento do
    # deploy (env exportada tem precedência). Falha em obter a senha emite
    # sentinela que o caller (deploy_capi.sh) aborta — exit aqui morreria só
    # no subshell do $(build_env_vars).
    LEDGER_TARGET="${LEDGER_TARGET:-cloudsql}"
    ENV_VARS="$ENV_VARS,LEDGER_TARGET=$LEDGER_TARGET"
    if [ "$LEDGER_TARGET" != "railway" ]; then
        LEDGER_DB_PASSWORD="${LEDGER_DB_PASSWORD:-$(gcloud secrets versions access latest --secret=ledger-db-password --project="$PROJECT_ID" 2>/dev/null)}"
        if [ -z "$LEDGER_DB_PASSWORD" ]; then
            echo "ERROR_LEDGER_SECRET_UNAVAILABLE"
            return 1
        fi
        ENV_VARS="$ENV_VARS,LEDGER_DB_HOST=${LEDGER_DB_HOST:-104.197.138.129}"
        ENV_VARS="$ENV_VARS,LEDGER_DB_PORT=${LEDGER_DB_PORT:-5432}"
        ENV_VARS="$ENV_VARS,LEDGER_DB_NAME=${LEDGER_DB_NAME:-ledger}"
        ENV_VARS="$ENV_VARS,LEDGER_DB_USER=${LEDGER_DB_USER:-ledger_app}"
        ENV_VARS="$ENV_VARS,LEDGER_DB_PASSWORD=$LEDGER_DB_PASSWORD"
    fi

    # Token das rotas internas da API (guarda de api/auth.py). Sem ele, as 15 rotas
    # fechadas devolvem 401 para todo mundo, inclusive para nós. Isso é o fail-safe
    # certo (segredo ausente FECHA a porta), mas seria um jeito bobo de derrubar
    # ferramenta interna, então o deploy aborta em vez de subir sem o token.
    API_INTERNAL_TOKEN="${API_INTERNAL_TOKEN:-$(gcloud secrets versions access latest --secret=api-internal-token --project="$PROJECT_ID" 2>/dev/null)}"
    if [ -z "$API_INTERNAL_TOKEN" ]; then
        echo "ERROR_API_INTERNAL_TOKEN_UNAVAILABLE"
        return 1
    fi
    ENV_VARS="$ENV_VARS,API_INTERNAL_TOKEN=$API_INTERNAL_TOKEN"

    # Fonte de LEITURA do ledger (PLANO_LEDGER_CLOUDSQL.md Etapa 3 — ENCERRADA):
    # railway | cloudsql (DEFAULT). Os leitores (monitoramento, validação) abrem
    # a conexão por open_ledger_read_connection() conforme esta env.
    # A virada da leitura pro Cloud SQL foi pro ar em 16/06 e é o estado fixo
    # final. DEFAULT=cloudsql pelo mesmo motivo do LEDGER_TARGET acima: sem isso,
    # qualquer deploy concorrente que não exporte a env reverte a leitura pro
    # Railway em silêncio (frágil por design enquanto era override por-revisão).
    # Voltar pra 'railway' só em rollback consciente.
    ENV_VARS="$ENV_VARS,LEDGER_READ_SOURCE=${LEDGER_READ_SOURCE:-cloudsql}"

    # Fonte do CALENDÁRIO de LFs do resolvedor (core.launches.load_launches):
    # yaml (configs/launches.yaml estático) | table (analytics.launch_calendar,
    # refresh diário da planilha do cliente pelo job ingestion-launch-calendar).
    # DEFAULT=table desde 24/07/2026 (validado: resolvia a DEV21 que faltava no
    # yaml). Fixo no config.sh pelo mesmo motivo do LEDGER_READ_SOURCE: sem isso,
    # um deploy que não exporte a env reverteria pro yaml estático em silêncio.
    # O código tem fallback automático pro yaml se a tabela vier vazia/indisponível;
    # rollback consciente = LAUNCHES_SOURCE=yaml.
    ENV_VARS="$ENV_VARS,LAUNCHES_SOURCE=${LAUNCHES_SOURCE:-table}"

    # Fonte do decil_challenger dos RELATÓRIOS (refator dual-decil, Fase 3):
    # scores_historicos (legado) | ledger (lê registros_ml direto, onde a Fase 2
    # grava ao vivo e a Fase 4 copiou o histórico). DEFAULT=ledger — o flip da
    # Fase 3. Mesmo motivo dos LEDGER_* acima: default no config.sh pra não
    # depender de env por-revisão. Rollback = voltar tráfego pra revisão anterior
    # (sem o flag → cai em scores_historicos) OU setar =scores_historicos aqui.
    ENV_VARS="$ENV_VARS,LEDGER_DECIL_READ_SOURCE=${LEDGER_DECIL_READ_SOURCE:-ledger}"

    # Canais Slack do relatório de criativo — PINADOS aqui (não confiar no default
    # da app). O deploy usa --update-env-vars (MESCLA), então um override por-revisão
    # (ex.: uma canary de validação apontando o relatório pro DM) VAZARIA pro próximo
    # deploy se o canal de produção não fosse re-setado aqui. Mesmo motivo do
    # LEDGER_READ_SOURCE acima. C09VD6J8A72 = team-trafego (cliente); D0A9USV3XEX = DM
    # do operador (validação). O endpoint escolhe via ?dest=trafego|dm.
    ENV_VARS="$ENV_VARS,UTM_QUALITY_TRAFEGO_CHANNEL=${UTM_QUALITY_TRAFEGO_CHANNEL:-C09VD6J8A72}"
    ENV_VARS="$ENV_VARS,SLACK_VALIDATION_DM_CHANNEL=${SLACK_VALIDATION_DM_CHANNEL:-D0A9USV3XEX}"

    # Teto do alerta de custo do Cloud Run, em reais por dia (uso bruto, antes da
    # camada gratuita). Pinado aqui pelo mesmo motivo dos canais acima: o deploy
    # MESCLA env vars, então um teto de teste setado numa canary vazaria pro
    # próximo deploy se o valor de produção não fosse re-afirmado. R$ 10 fica
    # acima do dia típico (R$ 3 a R$ 5) e abaixo do pico da virada de julho/2026
    # (R$ 12,21). Pra mudar o teto sem deploy: --update-env-vars no serviço.
    ENV_VARS="$ENV_VARS,CLOUD_RUN_COST_ALERT_BRL=${CLOUD_RUN_COST_ALERT_BRL:-10}"

    # Propaga credenciais de API do serviço 24/7 (fonte de verdade) pros jobs:
    # META_ACCESS_TOKEN (Meta Insights, gasto Meta) + GOOGLE_ADS_* OAuth (reporting de
    # gasto do etl_ad_spend, MESMO caminho do funil Google do digest). O
    # `.find(name=...).value` do gcloud retorna VAZIO nessa estrutura aninhada — bug
    # histórico que deixava os jobs SEM o token (o gasto Meta/Google falhava por
    # permissão). Por isso extraímos via JSON+python. O customer_id NÃO vem daqui: o
    # etl_ad_spend lê de ClientConfig.google_ads.customer_id (fonte única do config).
    local CREDS
    CREDS=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format=json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    env = {x['name']: x.get('value', '') for x in d['spec']['template']['spec']['containers'][0].get('env', [])}
except Exception:
    env = {}
keys = ['META_ACCESS_TOKEN', 'GOOGLE_ADS_DEVELOPER_TOKEN', 'GOOGLE_ADS_CLIENT_ID',
        'GOOGLE_ADS_CLIENT_SECRET', 'GOOGLE_ADS_REFRESH_TOKEN', 'GOOGLE_ADS_LOGIN_CUSTOMER_ID']
print(','.join(f'{k}={env[k]}' for k in keys if env.get(k)))
" 2>/dev/null || echo "")
    if [ -n "$CREDS" ]; then
        ENV_VARS="$ENV_VARS,$CREDS"
    fi

    # Token da API da TMB (gateway de vendas TMB no etl_sales). Secret dedicado
    # `tmb-api-token`; só entra se existir (opt-in). Guarda contra job sem o token
    # é o fail-loud do próprio extractor (não esvazia a TMB em silêncio).
    local TMB_TOKEN
    TMB_TOKEN="${TMB_API_TOKEN:-$(gcloud secrets versions access latest --secret=tmb-api-token --project="$PROJECT_ID" 2>/dev/null)}"
    [ -n "$TMB_TOKEN" ] && ENV_VARS="$ENV_VARS,TMB_API_TOKEN=$TMB_TOKEN"

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
