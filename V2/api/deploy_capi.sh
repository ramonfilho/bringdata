#!/bin/bash
# =============================================================================
# Script de Deploy Automatizado - Bring Data Lead Scoring API
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
# IMPORTAR BIBLIOTECAS COMPARTILHADAS
# =============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Importar funções compartilhadas (cores, print_*, validações GCP)
source "$SCRIPT_DIR/lib/common.sh"

# Importar configurações centralizadas (PROJECT_ID, REGION, etc.)
source "$SCRIPT_DIR/lib/config.sh"

# =============================================================================
# VARIÁVEIS DE CONTROLE ESPECÍFICAS DO DEPLOY
# =============================================================================

MODEL_VERSION=""
IMAGE_TAG=""
SKIP_TESTS=false
ALLOW_PUBLIC=true  # Temporário - mudar para false em produção
PREVIOUS_REVISION=""
YES_FLAG=false  # Pula confirmação se true
NO_TRAFFIC=false  # Se true, deploy sem redirecionar tráfego (para teste)
FORCE_DEPLOY=false  # Requer --force-deploy para branches não autorizadas
SKIP_PARITY_AUDIT=${SKIP_PARITY_AUDIT:-false}  # [T1-8] Escape hatch para pular parity audit em branch não-rollback

# =============================================================================
# BRANCHES AUTORIZADAS PARA DEPLOY DE PRODUÇÃO
# =============================================================================
# Apenas commits/branches listados aqui podem ser deployados sem --force-deploy.
# Para deployar qualquer outra branch (incluindo main), use:
#   FORCE_DEPLOY=true ./deploy_capi.sh --force-deploy
# com confirmação explícita adicional.
#
# Branches autorizadas:
#   rollback/edf23e9  — worktree do rollback P1 (edf23e9, jan30, 05/03/2026)
#
# Para adicionar uma branch autorizada, edite AUTHORIZED_BRANCHES abaixo
# E documente o motivo no commit.
# =============================================================================
AUTHORIZED_BRANCHES=("rollback/edf23e9" "HEAD" "detached")

check_authorized_branch() {
    local CURRENT_BRANCH
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    local CURRENT_COMMIT
    CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    # Verificar se é detached HEAD (worktree de rollback) — permitido
    if [ "$CURRENT_BRANCH" = "HEAD" ]; then
        local COMMIT_MSG
        COMMIT_MSG=$(git log -1 --pretty=format:"%s" 2>/dev/null || echo "")
        echo ""
        echo "  ✅  Branch: DETACHED HEAD @ ${CURRENT_COMMIT}"
        echo "      Commit: ${COMMIT_MSG}"
        echo ""
        return 0
    fi

    # Verificar se branch está na lista autorizada
    for authorized in "${AUTHORIZED_BRANCHES[@]}"; do
        if [ "$CURRENT_BRANCH" = "$authorized" ]; then
            echo "  ✅  Branch autorizada: ${CURRENT_BRANCH} @ ${CURRENT_COMMIT}"
            return 0
        fi
    done

    # Branch NÃO autorizada — exige --force-deploy
    echo ""
    echo "  ╔══════════════════════════════════════════════════════════════════╗"
    echo "  ║  🚨  DEPLOY BLOQUEADO — BRANCH NÃO AUTORIZADA                  ║"
    echo "  ╠══════════════════════════════════════════════════════════════════╣"
    echo "  ║  Branch atual : ${CURRENT_BRANCH} @ ${CURRENT_COMMIT}"
    echo "  ║  Produção deve rodar: rollback/edf23e9 (worktree, edf23e9)      ║"
    echo "  ║                                                                  ║"
    echo "  ║  Para deployar esta branch você precisa de autorização           ║"
    echo "  ║  explícita. Execute com a flag abaixo E confirme o prompt:       ║"
    echo "  ║                                                                  ║"
    echo "  ║    FORCE_DEPLOY=true ./deploy_capi.sh --force-deploy            ║"
    echo "  ║                                                                  ║"
    echo "  ║  Documente o motivo antes de prosseguir.                        ║"
    echo "  ╚══════════════════════════════════════════════════════════════════╝"
    echo ""

    if [ "$FORCE_DEPLOY" = "true" ]; then
        echo "  ⚠️  --force-deploy ativado. Você está deployando uma branch NÃO autorizada."
        echo "  Branch : ${CURRENT_BRANCH} @ ${CURRENT_COMMIT}"
        echo ""
        read -r -p "  Digite exatamente 'CONFIRMO DEPLOY DE ${CURRENT_BRANCH}' para continuar: " CONFIRMATION
        if [ "$CONFIRMATION" != "CONFIRMO DEPLOY DE ${CURRENT_BRANCH}" ]; then
            echo "  ❌  Confirmação incorreta. Deploy cancelado."
            exit 1
        fi
        echo ""
        echo "  ⚠️  Deploy autorizado manualmente para ${CURRENT_BRANCH}. Prosseguindo."
        echo ""
        return 0
    fi

    exit 1
}

# =============================================================================
# [T1-8] GATE DE PARITY AUDIT
# =============================================================================
# Quando FORCE_DEPLOY=true (deploy de branch não-rollback como main), exige
# que V2/tests/parity_audit.py passe antes de prosseguir. Bloqueia o deploy
# se treino × produção divergirem coluna-a-coluna em encoding ou UTM.
#
# Motivação: antes da unificação edf23e9 → main, a única prova técnica de
# que main não regride produção é o parity audit. Subir main em produção
# sem esse check repete o bug do Medium_Linguagem_programacao (feature
# zerada por semanas sem aviso).
#
# Escape hatch: SKIP_PARITY_AUDIT=true exige confirmação manual digitada.
# =============================================================================

check_parity_audit() {
    # Só roda quando branch não-rollback (FORCE_DEPLOY=true)
    if [ "$FORCE_DEPLOY" != "true" ]; then
        return 0
    fi

    echo ""
    echo "  [T1-8] Verificando parity audit treino × produção..."

    if [ "$SKIP_PARITY_AUDIT" = "true" ]; then
        echo ""
        echo "  ⚠️  SKIP_PARITY_AUDIT=true — você está pulando o gate de paridade."
        echo "      Isso só deve acontecer se os snapshots não estão disponíveis"
        echo "      e você aceitou o risco documentado."
        echo ""
        read -r -p "  Digite exatamente 'PULAR PARITY AUDIT' para continuar: " CONFIRMATION
        if [ "$CONFIRMATION" != "PULAR PARITY AUDIT" ]; then
            echo "  ❌  Confirmação incorreta. Deploy cancelado."
            exit 1
        fi
        echo "  ⚠️  Parity audit pulado manualmente. Prosseguindo sob risco."
        return 0
    fi

    local PROJECT_DIR
    PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

    if ! command -v python3 >/dev/null 2>&1; then
        echo "  ❌  python3 não disponível — não é possível rodar parity audit."
        echo "      Use SKIP_PARITY_AUDIT=true se tiver certeza do que está fazendo."
        exit 1
    fi

    if (cd "$PROJECT_DIR/.." && python3 V2/tests/parity_audit.py --function utm 2>&1 | tail -30 && \
        python3 V2/tests/parity_audit.py --function encoding 2>&1 | tail -30) | tee /tmp/parity_audit_deploy.log; then
        if grep -q "DIVERG" /tmp/parity_audit_deploy.log; then
            echo ""
            echo "  ╔══════════════════════════════════════════════════════════════════╗"
            echo "  ║  🚨  DEPLOY BLOQUEADO — PARITY AUDIT FALHOU                      ║"
            echo "  ╠══════════════════════════════════════════════════════════════════╣"
            echo "  ║  Treino × produção divergem coluna-a-coluna.                     ║"
            echo "  ║  Ver /tmp/parity_audit_deploy.log para detalhes.                 ║"
            echo "  ║                                                                  ║"
            echo "  ║  Corrija a divergência antes de deployar, OU use:                ║"
            echo "  ║    SKIP_PARITY_AUDIT=true ./deploy_capi.sh --force-deploy        ║"
            echo "  ║  (exige confirmação manual digitada)                             ║"
            echo "  ╚══════════════════════════════════════════════════════════════════╝"
            echo ""
            exit 1
        fi
        echo "  ✅  Parity audit OK — treino × produção idênticos"
    else
        echo ""
        echo "  ❌  Erro ao executar parity audit. Ver /tmp/parity_audit_deploy.log"
        exit 1
    fi
}

# =============================================================================
# VALIDAÇÕES PRÉ-DEPLOY
# =============================================================================

validate_prerequisites() {
    print_header "1. VALIDAÇÕES PRÉ-DEPLOY"

    # 1.0 Verificar branch autorizada (bloqueio de segurança)
    print_info "Verificando branch autorizada para deploy..."
    check_authorized_branch

    # 1.0b [T1-8] Parity audit treino × produção (só em FORCE_DEPLOY=true)
    check_parity_audit

    # 1.1 Docker (específico do deploy)
    validate_docker

    # 1.2 gcloud CLI (da lib/common.sh)
    validate_gcloud

    # 1.3 Autenticação GCP (da lib/common.sh)
    validate_auth

    # 1.4 Projeto GCP (da lib/common.sh)
    validate_project "$PROJECT_ID"

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

    # Detectar modo: mlflow_run_id (novo) ou model_path (legado)
    MLFLOW_RUN_ID=$(grep "mlflow_run_id:" "$CONFIG_FILE" | awk '{print $2}')
    MODEL_PATH=$(grep "model_path:" "$CONFIG_FILE" | awk '{print $2}')

    if [ -n "$MLFLOW_RUN_ID" ]; then
        # Modo MLflow: artifacts do run ficam em mlruns/1/{run_id}/artifacts
        # O Dockerfile reutiliza ARG MODEL_PATH — sem mudanças no Dockerfile
        MODEL_PATH="mlruns/1/${MLFLOW_RUN_ID}/artifacts"
        FULL_MODEL_DIR="$PROJECT_ROOT/$MODEL_PATH"

        if [ ! -d "$FULL_MODEL_DIR" ]; then
            print_error "MLflow artifacts não encontrados: $FULL_MODEL_DIR"
            exit 1
        fi

        # 1.7 Arquivos do modelo (modo MLflow)
        print_info "Verificando arquivos do modelo (modo MLflow)..."
        if [ ! -f "$FULL_MODEL_DIR/model/model.pkl" ]; then
            print_error "model.pkl não encontrado em: $FULL_MODEL_DIR/model/"
            exit 1
        fi
        if [ ! -f "$FULL_MODEL_DIR/model_metadata.json" ]; then
            print_error "model_metadata.json não encontrado em: $FULL_MODEL_DIR"
            exit 1
        fi
        if [ ! -f "$FULL_MODEL_DIR/feature_registry.json" ]; then
            print_error "feature_registry.json não encontrado em: $FULL_MODEL_DIR"
            exit 1
        fi
        print_success "Modo MLflow — run: $MLFLOW_RUN_ID"

    elif [ -n "$MODEL_PATH" ]; then
        # Modo local (legado): files/{timestamp}
        FULL_MODEL_DIR="$PROJECT_ROOT/$MODEL_PATH"

        if [ ! -d "$FULL_MODEL_DIR" ]; then
            print_error "Diretório do modelo não existe: $FULL_MODEL_DIR"
            exit 1
        fi

        # 1.7 Arquivos do modelo (modo local)
        print_info "Verificando arquivos do modelo (modo local)..."
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
        print_success "Modo local — modelo: $MODEL_PATH"

    else
        print_error "active_model.yaml não contém mlflow_run_id nem model_path"
        exit 1
    fi

    # 1.8 configs/clients/{CLIENT_ID}.yaml (produto e taxas de conversão)
    print_info "Verificando configs/clients/${CLIENT_ID}.yaml..."
    if [ ! -f "$CLIENT_CONFIG_FILE" ]; then
        print_error "ClientConfig não encontrado em: $CLIENT_CONFIG_FILE"
        exit 1
    fi

    PRODUCT_VALUE=$(python3 -c "
import yaml, sys
with open('$CLIENT_CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
v = cfg.get('business', {}).get('product_value')
if v is None:
    sys.exit(1)
print(v)
" 2>/dev/null) || { print_error "business.product_value não encontrado em $CLIENT_CONFIG_FILE"; exit 1; }
    print_success "PRODUCT_VALUE (${CLIENT_ID}): R$ $PRODUCT_VALUE"

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

    # Cloud SQL descomissionado em 25/02/2026 — descomentar para novos clientes com Cloud SQL
    # validate_cloud_sql "$CLOUD_SQL_INSTANCE" "$REGION" "$DB_NAME" "$DB_USER" "$DB_PASSWORD"

    echo ""
}

# =============================================================================
# STAGING DE ARTIFACTS PARA O DOCKER BUILD
# =============================================================================
#
# Monta mlruns_build/1/ com apenas os runs necessários:
#   - champion (active_model.mlflow_run_id)
#   - variantes A/B (ab_test.variants.*.run_id) quando ab_test.enabled = true
#
# O Dockerfile faz COPY ./mlruns_build/ ./mlruns/ — imagem enxuta, A/B pronto.
# O diretório é removido após o build (cleanup em build_docker_image).
# =============================================================================

stage_model_artifacts() {
    print_header "1.5 STAGING DE ARTIFACTS"

    STAGE_DIR="$PROJECT_ROOT/mlruns_build"
    STAGE_EXPERIMENT="$STAGE_DIR/1"

    # Limpar staging anterior se existir
    rm -rf "$STAGE_DIR"
    mkdir -p "$STAGE_EXPERIMENT"

    # --- Champion ---
    CHAMPION_SRC="$PROJECT_ROOT/mlruns/1/${MLFLOW_RUN_ID}/artifacts"
    if [ ! -d "$CHAMPION_SRC" ]; then
        print_error "Artifacts do champion não encontrados: $CHAMPION_SRC"
        exit 1
    fi
    cp -r "$PROJECT_ROOT/mlruns/1/${MLFLOW_RUN_ID}" "$STAGE_EXPERIMENT/"
    print_success "Champion staged: $MLFLOW_RUN_ID"

    # --- Variantes A/B (apenas se enabled: true) ---
    AB_ENABLED=$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
ab = cfg.get('ab_test', {})
print('true' if ab.get('enabled') else 'false')
" 2>/dev/null)

    if [ "$AB_ENABLED" = "true" ]; then
        VARIANT_RUN_IDS=$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
variants = cfg.get('ab_test', {}).get('variants', {})
for name, v in variants.items():
    print(v.get('run_id', ''))
" 2>/dev/null)

        for VARIANT_RUN_ID in $VARIANT_RUN_IDS; do
            [ -z "$VARIANT_RUN_ID" ] && continue
            VARIANT_SRC="$PROJECT_ROOT/mlruns/1/${VARIANT_RUN_ID}/artifacts"
            if [ ! -d "$VARIANT_SRC" ]; then
                print_error "Artifacts da variante não encontrados: $VARIANT_SRC"
                print_error "Rode: python -c \"import mlflow; mlflow.artifacts.download_artifacts(run_id='${VARIANT_RUN_ID}', dst_path='mlruns/1/${VARIANT_RUN_ID}/artifacts')\""
                exit 1
            fi
            cp -r "$PROJECT_ROOT/mlruns/1/${VARIANT_RUN_ID}" "$STAGE_EXPERIMENT/"
            print_success "Variante A/B staged: $VARIANT_RUN_ID"
        done
    else
        print_info "A/B test desabilitado — apenas champion no build"
    fi

    # MODEL_PATH aponta para o staging (relativo à raiz do projeto)
    MODEL_PATH="mlruns_build"
    print_success "Staging pronto: $STAGE_DIR"
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

    # MODEL_PATH já definido por validate_prerequisites (suporta modo local e MLflow)
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
            rm -rf "$PROJECT_ROOT/mlruns_build"
            exit 1
        }

    # Limpar staging (não precisa mais após o build)
    rm -rf "$PROJECT_ROOT/mlruns_build"

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

    # ⚠️ CRÍTICO: Configurar variáveis de ambiente (NÃO REMOVER!)
    # Sem essas variáveis, a API usa SQLite e PERDE TODOS OS DADOS a cada deploy
    print_info "Configurando variáveis de ambiente..."
    ENV_VARS=$(build_env_vars)
    print_success "Variáveis de ambiente configuradas (via lib/config.sh)"

    TRAFFIC_FLAG=""
    CANARY_TAG=""
    if [ "$NO_TRAFFIC" = true ]; then
        TRAFFIC_FLAG="--no-traffic"
        # [T1-8/T1-10] Tag garante URL direta para smoke test pós-deploy
        CANARY_TAG="canary-$(date +%s)"
        TRAFFIC_FLAG="$TRAFFIC_FLAG --tag=$CANARY_TAG"
        print_warning "Modo --no-traffic: nova revisão NÃO receberá tráfego (tag: $CANARY_TAG)"
    fi

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
        $AUTH_FLAG \
        $TRAFFIC_FLAG \
        --quiet || {
            print_error "Falha no deploy para Cloud Run"
            exit 1
        }

    # Obter a nova revisão (necessário para tráfego e para --no-traffic informar URL)
    NEW_REVISION=$(gcloud run revisions list \
        --service=$SERVICE_NAME \
        --region=$REGION \
        --format="value(metadata.name)" \
        --limit=1)

    if [ "$NO_TRAFFIC" = true ]; then
        # Modo teste: mostrar URL da revisão para teste direto
        REVISION_URL=$(gcloud run revisions describe "$NEW_REVISION" \
            --region=$REGION \
            --format="value(status.url)" 2>/dev/null || echo "")
        print_warning "Revisão criada sem tráfego: $NEW_REVISION"
        if [ -n "$REVISION_URL" ]; then
            print_info "URL para teste direto: $REVISION_URL"
        fi

        # [T1-10 Gate B] Smoke test automático pós-deploy
        SMOKE_SCRIPT="$SCRIPT_DIR/../scripts/smoke_test_revision.py"
        if [ -f "$SMOKE_SCRIPT" ]; then
            print_info "[T1-10 Gate B] Rodando smoke test contra revisão $NEW_REVISION..."
            if python3 "$SMOKE_SCRIPT" "$NEW_REVISION" --region "$REGION" --project "$PROJECT_ID"; then
                print_success "[T1-10 Gate B] Smoke test passou — revisão saudável"
            else
                print_error "[T1-10 Gate B] Smoke test FALHOU — features críticas ausentes no encoding"
                print_warning "Revisão permanece em 0% de tráfego. NÃO progredir tráfego até resolver."
                print_info "Para descartar: gcloud run revisions delete $NEW_REVISION --region=$REGION"
                exit 1
            fi
        else
            print_warning "Smoke test script não encontrado em $SMOKE_SCRIPT — pulado"
        fi

        # [T3-1] Progressão de canary recomendada — não pular etapas.
        # Critérios objetivos de avanço entre etapas estão em PLANO_SAFEGUARD.md "Protocolo
        # de progressão de tráfego [T1-9]". Resumo dos comandos:
        echo
        print_info "==================== Progressão de canary (T3-1) ===================="
        print_info "Etapa 0 → 10% (canary inicial, observar 24h):"
        print_info "  gcloud run services update-traffic $SERVICE_NAME --region=$REGION \\"
        print_info "    --to-revisions=$NEW_REVISION=10,${PREVIOUS_REVISION:-PREVIOUS_REVISION}=90"
        print_info ""
        print_info "Etapa 10% → 50% (após 24h sem alerta HIGH novo + paridade observada):"
        print_info "  gcloud run services update-traffic $SERVICE_NAME --region=$REGION \\"
        print_info "    --to-revisions=$NEW_REVISION=50,${PREVIOUS_REVISION:-PREVIOUS_REVISION}=50"
        print_info ""
        print_info "Etapa 50% → 100% (após 48h sem alerta HIGH + golden snapshot estável):"
        print_info "  gcloud run services update-traffic $SERVICE_NAME --region=$REGION \\"
        print_info "    --to-revisions=$NEW_REVISION=100"
        print_info ""
        print_info "Rollback rápido (~10s): voltar 100% para $PREVIOUS_REVISION."
        print_info "Re-rodar smoke (Gate A) antes de qualquer avanço: python3 $SMOKE_SCRIPT $NEW_REVISION"
        print_info "Descartar revisão: gcloud run revisions delete $NEW_REVISION --region=$REGION"
        print_info "====================================================================="
    else
        # Garantir que 100% do tráfego vai para a nova revisão.
        # Necessário quando o serviço está em modo de tráfego manual
        # (ocorre após usar update-traffic manualmente).
        print_info "Direcionando 100% do tráfego para: $NEW_REVISION"
        gcloud run services update-traffic $SERVICE_NAME \
            --region=$REGION \
            --to-revisions="$NEW_REVISION=100" \
            --quiet || {
                print_warning "Falha ao redirecionar tráfego (pode já estar correto)"
            }
    fi

    print_success "Deploy concluído"

    # Tag git para rastrear qual commit originou cada revision do Cloud Run
    DEPLOY_TAG="deploy/$(date +%Y-%m-%d)-${NEW_REVISION##*-api-}"
    git tag "$DEPLOY_TAG" 2>/dev/null && print_info "Git tag criada: $DEPLOY_TAG" || print_warning "Git tag não criada (repo sujo ou tag já existe)"

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
    AUC=$(grep "auc:" "$CONFIG_FILE" | awk '{print $2}')
    MONOTONIA=$(grep "monotonia_percentage:" "$CONFIG_FILE" | awk '{print $2}')
    # MODEL_PATH já definido por validate_prerequisites (local ou mlruns/...)

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
    echo "  --no-traffic           Deploy sem redirecionar tráfego (para testar nova revisão)"
    echo "  --yes, -y              Pular confirmação (não perguntar)"
    echo "  --force-deploy         Autorizar deploy de branch NÃO listada em AUTHORIZED_BRANCHES"
    echo "                         Exige confirmação manual digitada. Só use com FORCE_DEPLOY=true."
    echo "  -h, --help             Mostrar esta mensagem"
    echo ""
    echo "Exemplos:"
    echo "  $0"
    echo "  $0 --yes"
    echo "  $0 --no-traffic --yes   # Testa novo modelo sem afetar produção"
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
            --no-traffic)
                NO_TRAFFIC=true
                shift
                ;;
            --yes|-y)
                YES_FLAG=true
                shift
                ;;
            --force-deploy)
                FORCE_DEPLOY=true
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
    echo "║       Bring Data Lead Scoring API - Deploy Automatizado        ║"
    echo "║                                                                ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    # Confirmação
    print_info "Ambiente: $ENVIRONMENT"
    print_info "Projeto GCP: $PROJECT_ID"
    print_info "Região: $REGION"
    print_info "Serviço: $SERVICE_NAME"
    echo ""

    print_success "Confirmação automática (--yes)"

    # Executar pipeline de deploy
    validate_prerequisites
    stage_model_artifacts
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
