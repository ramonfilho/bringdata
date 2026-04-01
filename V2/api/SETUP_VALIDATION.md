# 📊 Setup de Validação Semanal - Bring Data ML

Guia completo para configurar o sistema de validação semanal automatizada do modelo ML com notificações no Slack.

> **🏗️ Arquitetura Modular MLOps**
> Este sistema utiliza biblioteca compartilhada (`lib/`) seguindo princípios de engenharia de software:
> - ✅ **DRY:** Código reutilizável, sem duplicação
> - ✅ **Single Source of Truth:** Configurações centralizadas
> - ✅ **Fácil Replicação:** Editar 1 arquivo para novo cliente
> - ✅ **Manutenível:** Bug fix em 1 lugar, afeta todos os scripts

---

## 🎯 O Que Este Sistema Faz

**Validação Semanal Automatizada:**
- 🕒 **Execução:** Toda segunda-feira às 10h UTC (7h Brasília)
- 📊 **Métricas:** AUC, concentração de decis, conversões, ROAS
- 📄 **Relatório:** Excel completo gerado e armazenado no Cloud Storage
- 📱 **Notificação:** Sumário enviado automaticamente para Slack com link do Excel
- ⚠️ **Alertas:** Detecta degradação de performance do modelo

---

## ⚡ Quick Start

### Opção 1: Setup Automático (Recomendado)

```bash
cd api/
./setup_validation.sh --yes
```

> **📚 Pré-requisito:** A biblioteca compartilhada (`lib/`) deve existir.
> Se este é o primeiro setup ou após clonar o repo, os arquivos `lib/common.sh` e `lib/config.sh` são criados automaticamente na estrutura modular.

**O que o script faz:**
1. ✅ Carrega configurações de `lib/config.sh` (single source of truth)
2. ✅ Usa funções de `lib/common.sh` (validações compartilhadas)
3. ✅ Valida Cloud SQL (PostgreSQL) - **CRÍTICO para evitar perda de dados**
4. ✅ Cria bucket Cloud Storage (se não existir)
5. ✅ Cria Cloud Scheduler job (se não existir)
6. ✅ Configura environment variables
7. ✅ Executa deploy.sh automaticamente

### Opção 2: Setup Manual

Se preferir fazer passo a passo manualmente, veja a seção [Setup Manual](#-setup-manual) abaixo.

---

## 🏗️ Biblioteca Compartilhada (lib/)

Este sistema utiliza **arquitetura modular** seguindo princípios de MLOps:

### `lib/common.sh` - Funções Reutilizáveis

**Funções auxiliares** usadas por todos os scripts:
- `print_header()` - Cabeçalhos formatados
- `print_success()` - Mensagens de sucesso (verde)
- `print_error()` - Mensagens de erro (vermelho)
- `print_warning()` - Avisos (amarelo)
- `print_info()` - Informações (azul)

**Validações GCP** compartilhadas:
- `validate_gcloud()` - Verifica gcloud CLI instalado
- `validate_auth()` - Verifica autenticação GCP
- `validate_project()` - Verifica/configura projeto
- `validate_cloud_sql()` - Valida PostgreSQL **[CRÍTICO]**

### `lib/config.sh` - Single Source of Truth

**Configurações centralizadas** para todos os scripts:
```bash
# GCP
PROJECT_ID="smart-ads-451319"
REGION="us-central1"
SERVICE_NAME="bring-data-api"

# Cloud SQL (PostgreSQL) - CRÍTICO
CLOUD_SQL_INSTANCE="bring-data-db"
DB_NAME="bring_data"
DB_USER="postgres"
DB_PASSWORD="SmartAds2026DB!"

# Validação
BUCKET_NAME="bring-data-validation-reports"
SCHEDULER_JOB="validation-weekly"
SLACK_WEBHOOK_URL="https://hooks.slack.com/..."
```

**Permite override via environment variables:**
```bash
# Valores padrão, mas pode sobrescrever:
export PROJECT_ID="novo-cliente-123"
./setup_validation.sh  # Usa novo-cliente-123
```

### Por Que Esta Arquitetura?

**1. DRY (Don't Repeat Yourself)**
- Antes: Mesma validação Cloud SQL em 2 scripts
- Agora: 1 função `validate_cloud_sql()` em `lib/common.sh`

**2. Manutenibilidade**
- Antes: Bug em validação? Fix em 2 lugares
- Agora: Fix em `lib/common.sh`, afeta todos automaticamente

**3. Replicação Fácil**
- Antes: Editar configs em múltiplos arquivos
- Agora: Editar apenas `lib/config.sh`

**4. Testabilidade**
- Biblioteca pode ser testada isoladamente
- Scripts ficam mais limpos e focados

---

## 🔴 CRÍTICO: Proteção Contra Perda de Dados

### ⚠️ Por que PostgreSQL é Obrigatório?

**Problema:**
- SQLite armazena dados em `/tmp/bring_data_dev.db`
- Cloud Run **destroi** `/tmp/` a cada deploy
- **TODOS os 20,000+ leads CAPI são PERDIDOS**

**Solução Implementada:**
1. `api/database.py`: Bloqueia deploy se PostgreSQL não estiver configurado
2. `api/deploy.sh`: Configura OBRIGATORIAMENTE env vars do PostgreSQL
3. `api/setup_validation.sh`: Valida Cloud SQL ANTES de qualquer setup

### Validação Automática

O script `setup_validation.sh` **BLOQUEIA** o setup se:
- Cloud SQL instance não existir
- Cloud SQL não estiver em estado `RUNNABLE`
- Variáveis de ambiente do PostgreSQL não estiverem configuradas

**Você verá este erro se PostgreSQL não estiver OK:**
```
❌ Cloud SQL instance 'bring-data-db' NÃO ENCONTRADA!

🚨 SETUP BLOQUEADO - POSTGRESQL OBRIGATÓRIO 🚨

Sem Cloud SQL, o deploy usará SQLite e TODOS os leads CAPI serão
PERDIDOS a cada deploy (SQLite fica em /tmp/ que é destruído).
```

---

## 📋 Pré-requisitos

### 1. Cloud SQL (PostgreSQL) - **OBRIGATÓRIO**

**Verificar se existe:**
```bash
gcloud sql instances describe bring-data-db --format="value(state)"
# Esperado: RUNNABLE
```

**Se não existir, criar:**
```bash
# Criar instance
gcloud sql instances create bring-data-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1

# Criar banco de dados
gcloud sql databases create bring_data --instance=bring-data-db

# Configurar senha
gcloud sql users set-password postgres \
  --instance=bring-data-db \
  --password=SmartAds2026DB!
```

### 2. APIs GCP Habilitadas

O script habilita automaticamente, mas você pode verificar:
```bash
gcloud services list --enabled --filter="name:(run|sqladmin|storage|cloudscheduler)"
```

### 3. Autenticação

```bash
gcloud auth login
gcloud config set project smart-ads-451319
```

---

## 🚀 Setup Manual

Se preferir fazer passo a passo sem o script automatizado:

### 1️⃣ Criar Cloud Storage Bucket

```bash
# Criar bucket
gsutil mb -l us-central1 gs://bring-data-validation-reports

# Tornar público (para links compartilháveis no Slack)
gsutil iam ch allUsers:objectViewer gs://bring-data-validation-reports
```

### 2️⃣ Criar Cloud Scheduler Job

```bash
gcloud scheduler jobs create http validation-weekly \
  --location=us-central1 \
  --schedule="0 10 * * MON" \
  --uri="https://bring-data-api-gazrm25mda-uc.a.run.app/validation/weekly" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --description="Validação semanal do modelo ML (toda segunda 10h UTC)"
```

### 3️⃣ Configurar Environment Variables

```bash
gcloud run services update bring-data-api \
  --region=us-central1 \
  --update-env-vars="ENVIRONMENT=production,\
CLOUD_SQL_CONNECTION_NAME=smart-ads-451319:us-central1:bring-data-db,\
DB_NAME=bring_data,\
DB_USER=postgres,\
DB_PASSWORD=SmartAds2026DB!,\
META_DATA_SOURCE=api,\
VALIDATION_REPORTS_BUCKET=bring-data-validation-reports,\
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/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"
```

### 4️⃣ Deploy

```bash
cd api/
./deploy.sh --yes
```

---

## 🔧 Comandos Úteis

### Testar Validação Agora (Sem Esperar Segunda-feira)

```bash
gcloud scheduler jobs run validation-weekly --location=us-central1
```

### Ver Logs da Validação

```bash
# Logs do Cloud Run
gcloud logging tail "resource.type=cloud_run_revision AND resource.labels.service_name=bring-data-api"

# Logs do Scheduler
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=validation-weekly" --limit=20

# Logs de erros
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=bring-data-api AND severity>=ERROR" --limit=20
```

### Pausar/Retomar Validações

```bash
# Pausar (ex: durante manutenção)
gcloud scheduler jobs pause validation-weekly --location=us-central1

# Retomar
gcloud scheduler jobs resume validation-weekly --location=us-central1
```

### Verificar Status

```bash
# Status do scheduler job
gcloud scheduler jobs describe validation-weekly --location=us-central1

# Próxima execução
gcloud scheduler jobs describe validation-weekly --location=us-central1 \
  --format="value(scheduleTime)"

# Listar relatórios gerados
gsutil ls -lh gs://bring-data-validation-reports/validation/
```

### Testar Endpoint Manualmente

```bash
# Testar dependências (rápido)
curl https://bring-data-api-gazrm25mda-uc.a.run.app/validation/test

# Executar validação completa (lento - ~3-5 minutos)
curl -X POST https://bring-data-api-gazrm25mda-uc.a.run.app/validation/weekly
```

---

## 📊 Como Funciona

### Fluxo de Execução

```
┌──────────────────────────────────────────────────────────┐
│ 1. Cloud Scheduler (Segunda 10h UTC)                    │
│    POST /validation/weekly                              │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│ 2. Cloud Run API                                         │
│    ├─ Calcula período (semana anterior)                 │
│    ├─ Executa validate_ml_performance.py                │
│    └─ Timeout: 10 minutos                               │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│ 3. Script de Validação                                   │
│    ├─ Busca leads (Google Sheets)                       │
│    ├─ Busca vendas (Guru API)                           │
│    ├─ Busca relatórios Meta (CSV/API)                   │
│    ├─ Calcula métricas ML                               │
│    └─ Gera Excel: validation_report_*.xlsx              │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│ 4. Upload Cloud Storage                                  │
│    gs://bring-data-validation-reports/validation/...     │
│    URL pública gerada automaticamente                    │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│ 5. Notificação Slack                                     │
│    ├─ Sumário de métricas (AUC, ROAS, conversões)       │
│    ├─ Link para download do Excel                       │
│    └─ Cor: Verde/Amarelo/Vermelho baseado em performance│
└──────────────────────────────────────────────────────────┘
```

### Formato da Notificação Slack

```
📊 Validação Semanal ML - Bring Data

📅 Período Analisado
   Captação: 2025-12-16
   Vendas: 2026-01-19 a 2026-01-25

📈 Métricas de Performance
   🟢 AUC Produção: 0.6309 (Test Set: 0.7487, Δ -0.1178)
   • Top 3 Decis: 60.7% (Test Set: 66.5%)
   • Conversões: 177
   🟢 ROAS: 2.04x
   • Leads Analisados: 8,426

📄 Relatório Completo
   📥 Download Excel
   (link público do Cloud Storage)
```

**Cores:**
- 🟢 **Verde:** AUC delta >= -0.02 AND ROAS >= 2.5
- 🟡 **Amarelo:** AUC delta >= -0.05 OR ROAS >= 1.5
- 🔴 **Vermelho:** AUC delta < -0.05 OR ROAS < 1.5

---

## 🔍 Troubleshooting

### Scheduler não dispara

**Verificar estado:**
```bash
gcloud scheduler jobs describe validation-weekly --location=us-central1 --format="value(state)"
```

**Se estado = PAUSED:**
```bash
gcloud scheduler jobs resume validation-weekly --location=us-central1
```

### Validação timeout

**Problema:** Execução demora mais de 10 minutos

**Solução 1:** Otimizar queries no script de validação
**Solução 2:** Aumentar timeout no deploy.sh (linha 49):
```bash
TIMEOUT="900"  # 15 minutos
```

### Excel não aparece no Slack

**Verificar bucket:**
```bash
gsutil ls -lh gs://bring-data-validation-reports/validation/
```

**Se vazio:** Problema no script de validação ou upload

**Verificar permissões:**
```bash
gsutil iam get gs://bring-data-validation-reports
```

Deve conter: `"members": ["allUsers"]`

### Métricas zeradas no Slack

**Problema:** Regex não está fazendo match com output do script

**Verificar logs:**
```bash
gcloud logging read "resource.type=cloud_run_revision AND textPayload=~'validation'" --limit=50
```

**Ajustar regex em:** `api/app.py` função `_parse_validation_metrics()`

### SQLite sendo usado em produção

**CRÍTICO!** Se ver este warning nos logs:
```
⚠️ Usando SQLite (desenvolvimento) - Configure PostgreSQL para produção!
```

**Solução:**
1. Verificar Cloud SQL:
   ```bash
   gcloud sql instances describe bring-data-db
   ```

2. Re-executar setup:
   ```bash
   ./setup_validation.sh --yes
   ```

3. Deploy:
   ```bash
   ./deploy.sh --yes
   ```

### Erro ao importar lib/common.sh ou lib/config.sh

**Sintoma:**
```
./setup_validation.sh: line 10: lib/common.sh: No such file or directory
```

**Causa:** Arquivos da biblioteca não foram criados ou estão no lugar errado

**Solução:**
```bash
# Verificar estrutura
ls -la api/lib/
# Esperado:
# common.sh
# config.sh

# Se não existir, recriar estrutura modular
# (veja seção "Arquitetura Modular" deste documento)
```

### Configs diferentes entre scripts

**Sintoma:** `setup_validation.sh` usa um PROJECT_ID, mas `deploy.sh` usa outro

**Causa:** Edição manual direta nos scripts ao invés de usar `lib/config.sh`

**Solução:**
```bash
# NUNCA editar configs diretamente em setup_validation.sh ou deploy.sh
# SEMPRE editar em lib/config.sh (single source of truth)

vi lib/config.sh  # ✅ Correto
vi setup_validation.sh  # ❌ Errado
```

---

## 📁 Arquitetura Modular

Este sistema segue princípios de **MLOps** com código modular e reutilizável:

```
api/
├── lib/                          # 📚 Biblioteca compartilhada (DRY)
│   ├── common.sh                 # Funções auxiliares reutilizáveis
│   └── config.sh                 # Configurações centralizadas
│
├── setup_validation.sh           # ⭐ Script de setup (usa lib/)
├── deploy.sh                     # Deploy no Cloud Run (usa lib/)
├── app.py                        # Endpoints /validation/weekly e /validation/test
└── database.py                   # Proteção contra SQLite em produção

src/validation/
├── validate_ml_performance.py    # Script principal de validação
├── slack_notifier.py             # Classe para envio de notificações Slack
└── period_calculator.py          # Cálculo de períodos automático

configs/
├── weekly_validation_config.yaml # Documentação completa do sistema
└── campanhas_atipicas.yaml       # Configuração de campanhas atípicas
```

### 🎯 Vantagens da Arquitetura Modular

**DRY (Don't Repeat Yourself):**
- Funções auxiliares em **1 só lugar** (`lib/common.sh`)
- Configurações em **1 só lugar** (`lib/config.sh`)
- Bug fix ou mudança? Atualiza apenas 1 arquivo

**Fácil Replicação:**
- Novo cliente? Edita apenas `lib/config.sh`
- Não precisa caçar configs em múltiplos arquivos

**Testabilidade:**
- Biblioteca pode ser testada isoladamente
- Scripts menores e mais focados

**Manutenibilidade:**
- Código mais limpo e organizado
- Fácil entender responsabilidades

---

## 🔄 Replicação para Novo Cliente

Com a arquitetura modular, replicar para um novo cliente é **extremamente simples**:

### Opção 1: Via Arquivo de Configuração (Recomendado)

```bash
# 1. Clone o repositório
git clone <repo>
cd api/

# 2. Editar APENAS lib/config.sh (todas as configs em 1 lugar!)
vi lib/config.sh
# Ajustar:
#   - PROJECT_ID="novo-cliente-123"
#   - CLOUD_SQL_INSTANCE="novo-cliente-db"
#   - DB_PASSWORD="SuaSenhaSegura2026!"
#   - BUCKET_NAME="novo-cliente-validation-reports"
#   - SLACK_WEBHOOK_URL="https://hooks.slack.com/..."

# 3. Criar Cloud SQL (se não existir)
gcloud sql instances create novo-cliente-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1

# 4. Executar setup (automaticamente usa lib/config.sh)
./setup_validation.sh --yes

# 5. Testar
gcloud scheduler jobs run validation-weekly --location=us-central1
```

### Opção 2: Via Environment Variables (CI/CD)

```bash
# Útil para CI/CD pipelines
export PROJECT_ID="novo-cliente-123"
export CLOUD_SQL_INSTANCE="novo-cliente-db"
export DB_PASSWORD="SuaSenhaSegura2026!"
export BUCKET_NAME="novo-cliente-validation-reports"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."

# Setup usa automaticamente as env vars
./setup_validation.sh --yes
```

### ✨ Benefícios da Arquitetura Modular

**Antes (código duplicado):**
- ❌ Editar `setup_validation.sh` (linhas 31-58)
- ❌ Editar `deploy.sh` (linhas 34-65)
- ❌ Risco de inconsistência entre arquivos

**Agora (código centralizado):**
- ✅ Editar **APENAS** `lib/config.sh` (1 arquivo!)
- ✅ Todos os scripts usam automaticamente
- ✅ Impossível ficar inconsistente

---

## 📚 Referências

### Google Cloud Platform
- [Cloud Scheduler Documentation](https://cloud.google.com/scheduler/docs)
- [Cloud Run Environment Variables](https://cloud.google.com/run/docs/configuring/environment-variables)
- [Cloud Storage IAM](https://cloud.google.com/storage/docs/access-control/iam)
- [Cloud SQL for PostgreSQL](https://cloud.google.com/sql/docs/postgres)

### Integrações
- [Slack Incoming Webhooks](https://api.slack.com/messaging/webhooks)

### MLOps & Arquitetura
- [Google MLOps Best Practices](https://cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning)
- [Bash Best Practices](https://google.github.io/styleguide/shellguide.html)
- [Infrastructure as Code Principles](https://www.terraform.io/intro)
- [DRY Principle (Don't Repeat Yourself)](https://en.wikipedia.org/wiki/Don%27t_repeat_yourself)

---

## 🆘 Suporte

**Problemas?**
1. Verificar logs: `gcloud logging tail ...` (comandos acima)
2. Testar endpoint: `/validation/test`
3. Verificar `configs/weekly_validation_config.yaml` para troubleshooting completo

**Dúvidas sobre o sistema?**
- Arquitetura: `api/lib/` (biblioteca compartilhada)
- Configurações: `api/lib/config.sh` (single source of truth)
- Validações: `api/lib/common.sh` (funções reutilizáveis)
- Documentação: `configs/weekly_validation_config.yaml` (sistema completo)
- Notificações: `src/validation/slack_notifier.py` (lógica Slack)
