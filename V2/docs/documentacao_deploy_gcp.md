# 📋 Documentação Completa - Deploy Smart Ads Lead Scoring API

## 🎯 Visão Geral

API de Lead Scoring em produção no Google Cloud Platform, integrada com Google Sheets via Apps Script para predições automáticas em lote.

---

## 🏗️ Arquitetura

```
Google Sheets (Cliente)
    ↓ (Apps Script)
    ↓ (HTTP POST - JSON)
Cloud Run (API FastAPI)
    ↓ (Pipeline Python)
    ↓ (Modelo RandomForest)
Predições → Google Sheets
```

---

## ☁️ Google Cloud Platform

### Projeto GCP
- **Project ID:** `smart-ads-451319`
- **Project Number:** `12955519745`
- **Região:** `us-central1` (Iowa, EUA)

### Cloud Run
- **Service Name:** `smart-ads-api`
- **URL:** `https://smart-ads-api-12955519745.us-central1.run.app`
- **Revisão Atual:** `smart-ads-api-00007-7mf` (última funcional)
- **Configuração:**
  - CPU: 2 vCPUs
  - Memória: 2 GiB
  - Timeout: 120 segundos
  - Min Instances: 1 (sempre ativa, sem cold start)
  - Max Instances: 100 (auto-scaling)
  - Concurrency: 80 requisições simultâneas por instância

### Container Registry
- **Registry:** `gcr.io/smart-ads-451319`
- **Imagem:** `gcr.io/smart-ads-451319/smart-ads-api:v2`
- **Plataforma:** `linux/amd64` (importante: não ARM64!)
- **Tamanho:** ~247MB

---

## 🔐 Autenticação e Segurança

### Status Atual: PÚBLICO (temporário para testes)
```bash
# API está acessível publicamente
--allow-unauthenticated
```

### Service Accounts Configuradas

#### 1. App Engine Service Account
- **Email:** `smart-ads-451319@appspot.gserviceaccount.com`
- **Roles:**
  - `roles/editor`
  - `roles/aiplatform.admin`
  - `roles/bigquery.jobUser`
  - `roles/run.invoker` ✅ (adicionado para Cloud Run)

#### 2. Compute Engine Default Service Account
- **Email:** `12955519745-compute@developer.gserviceaccount.com`
- **Roles:** Múltiplas (editor, storage.admin, etc.)

### 🔒 Para Produção (próximo passo):

```bash
# Remover acesso público
gcloud run services remove-iam-policy-binding smart-ads-api \
  --region=us-central1 \
  --member="allUsers" \
  --role="roles/run.invoker"

# Manter apenas Service Account
# (já configurado com roles/run.invoker)
```

**OAuth Consent Screen:**
- Tipo: External
- App Name: Smart Ads Lead Scoring
- Scopes configurados:
  - `https://www.googleapis.com/auth/spreadsheets`
  - `https://www.googleapis.com/auth/script.external_request`

---

## 🐳 Docker

### Dockerfile
- **Localização:** `V2/api/Dockerfile`
- **Base Image:** `python:3.10-slim-bullseye`
- **Build Context:** `V2/` (diretório raiz do projeto)

### Estrutura Copiada para Container
```
/app/
├── api/
│   ├── app.py              # FastAPI application
│   ├── requirements.txt
│   └── Dockerfile
├── src/                    # Módulos do pipeline
│   ├── data/
│   ├── features/
│   └── model/
└── arquivos_modelo/        # Modelos treinados (.pkl, .json)
```

### Build e Deploy
```bash
# Build (importante: --platform linux/amd64 para Cloud Run)
docker buildx build \
  --platform linux/amd64 \
  -f api/Dockerfile \
  -t gcr.io/smart-ads-451319/smart-ads-api:v2 \
  --push \
  .

# Deploy
gcloud run deploy smart-ads-api \
  --image gcr.io/smart-ads-451319/smart-ads-api:v2 \
  --platform managed \
  --region us-central1 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 120 \
  --min-instances 1 \
  --no-allow-unauthenticated

# Configurar acesso (temporário - remover em produção)
gcloud run services add-iam-policy-binding smart-ads-api \
  --region=us-central1 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

### Dependências Principais (requirements.txt)
```
fastapi==0.104.1
uvicorn[standard]==0.24.0
pandas==2.0.3
numpy==1.26.4              # IMPORTANTE: 1.26.4 (não 1.24.3)
scikit-learn==1.3.0
joblib==1.3.2
pydantic==2.4.2
gunicorn==21.2.0
```

---

## 🔌 API Endpoints

### 1. Health Check
```
GET /health
```
**Response:**
```json
{
  "status": "healthy",
  "pipeline_status": "healthy",
  "model_loaded": true,
  "timestamp": "2025-09-30T12:00:00.000000",
  "version": "2.0.0"
}
```

### 2. Batch Predictions
```
POST /predict/batch
Content-Type: application/json
```

**Request Body:**
```json
{
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
        "Term": "instagram"
        // ... outros campos
      },
      "email": "joao@example.com",  // Deve ser string (validação Pydantic)
      "row_id": "2"
    }
  ]
}
```

**Limites:**
- **Máximo:** 500 leads por requisição
- **Timeout:** 120 segundos

**Response:**
```json
{
  "predictions": [
    {
      "row_id": "2",
      "lead_score": 0.7523,
      "decile": "D8"
    }
  ],
  "total_leads": 1,
  "processing_time_seconds": 0.45,
  "model_version": "v1_devclub_rf_temporal_single"
}
```

---

## 📱 Google Sheets Integration

### Apps Script
- **Localização:** `V2/api/apps-script-code.js`
- **Função Principal:** `getPredictions()`
- **Processamento em Lotes:** 500 leads por vez
- **Execução Automática:** Configurável (a cada X horas)

### Fluxo de Dados

1. **Apps Script lê Google Sheets**
   - Linha 1: Cabeçalhos
   - Linhas 2+: Dados dos leads

2. **Divide em lotes de 500**
   - API aceita máximo 500 leads/requisição

3. **Envia para API**
   - Dados crus (sem conversão, exceto email → string)

4. **API Processa:**
   - Remove duplicatas (usando todas as colunas)
   - Aplica pipeline de transformação
   - Gera predições

5. **Escreve de volta no Sheets:**
   - Coluna `lead_score`: Probabilidade (0-1)
   - Coluna `decile`: Decil (D1-D10)

### Dados Enviados
- **Formato:** JSON bruto do Google Sheets
- **Conversões:** Apenas `email` é convertido para string (validação Pydantic)
- **Valores vazios:** Enviados como estão (pipeline trata)

---

## 🧬 Pipeline de Processamento

### Etapas (em ordem):

1. **Remove Duplicatas** (`preprocessing.py`)
   - Usa todas as colunas
   - Mantém primeira ocorrência
   - ⚠️ Pode reduzir muito o número de registros (ex: 3896 → 2026)

2. **Limpa Colunas** (`preprocessing.py`)
   - Remove colunas de score/faixa antigas
   - Remove colunas `Unnamed:`

3. **Remove Features de Campanha** (`preprocessing.py`)
   - Remove `Campaign`, `Content`

4. **Unifica UTM** (`utm_unification.py`)
   - Padroniza `Source`, `Term`, `Medium`

5. **Remove Campos Técnicos** (`preprocessing.py`)
   - Remove `Remote IP`, `User Agent`, etc.

6. **Renomeia Colunas Longas** (`preprocessing.py`)
   - Simplifica nomes muito longos

7. **Feature Engineering** (`engineering.py`)
   - Cria features temporais (`dia_semana`)
   - Valida nome, email, telefone
   - Remove colunas originais após criar features

8. **Encoding Categórico** (`encoding.py`)
   - **Ordinal:** idade, faixa salarial, dia_semana
   - **One-Hot:** demais categóricas
   - **Tratamento de NaN:**
     - Valores não mapeados → NaN
     - NaN preenchidos com 0
     - Logging detalhado de valores problemáticos

9. **Predição** (`prediction.py`)
   - Alinha features com modelo treinado
   - Features ausentes preenchidas com 0
   - Retorna DataFrame **processado** (sem duplicatas)

---

## 🐛 Problemas Resolvidos (Histórico)

### 1. ❌ Numpy Module Not Found
**Erro:** `No module named 'numpy._core'`
**Causa:** Modelo treinado com numpy 1.26.4, container com 1.24.3
**Solução:** Atualizar `requirements.txt` para `numpy==1.26.4`

### 2. ❌ Pydantic Validation Error (422)
**Erro:** `Input should be a valid string` no campo `email`
**Causa:** Google Sheets envia telefones como números no campo email
**Solução:** Apps Script converte `email` para string antes de enviar

### 3. ❌ Input X contains NaN
**Erro:** RandomForest não aceita NaN
**Causa:** Valores não mapeados no encoding ordinal viravam NaN
**Solução:** Adicionar `fillna(0)` após encoding com logging detalhado

### 4. ❌ Length Mismatch (500 vs 264)
**Erro:** `Length of values (264) does not match length of index (500)`
**Causa:** Remoção de duplicatas + tentativa de usar DataFrame original
**Solução:** Sempre usar DataFrame processado (sem duplicatas) para predições

### 5. ⚠️ Duplicatas em Produção
**Descoberta:** 48% dos registros eram duplicatas (1870 de 3896)
**Decisão:** Aceitar - pipeline remove corretamente, retorna apenas únicos
**Impacto:** API retorna menos predições que leads enviados (esperado)

---

## 📊 Performance

### Resultados Reais (Teste com 3896 leads):

- **Leads Enviados:** 3896
- **Lotes Processados:** 8 (7x500 + 1x396)
- **Duplicatas Removidas:** 1870 (48%)
- **Predições Retornadas:** 2026
- **Tempo Total:** 9.03 segundos
- **Score Range:** 0.018 - 0.750

### Breakdown por Lote:
- **Lote 1:** 6.47s (cold start + carregamento modelo)
- **Lote 2:** 1.34s
- **Lotes 3-8:** ~0.20s cada (otimizado)

### Custo Estimado:
- **Min Instances = 1:** ~$50-70/mês (sempre ativa)
- **Min Instances = 0:** ~$5-20/mês (cold starts frequentes)

---

## 🔍 Logs e Debugging

### Ver Logs no Cloud Run:
```bash
# Logs gerais
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api" --limit=50

# Logs de erro
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api AND textPayload:ERROR" --limit=50

# Logs de NaN/duplicatas
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api AND textPayload:NaN" --limit=50

# Logs específicos por timestamp
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api AND timestamp>=\"2025-09-30T12:00:00Z\"" --limit=100
```

### Verificar Revisões:
```bash
gcloud run revisions list --service=smart-ads-api --region=us-central1
```

### Verificar Imagens:
```bash
# Listar imagens
gcloud container images list --repository=gcr.io/smart-ads-451319

# Ver tags de uma imagem
gcloud container images list-tags gcr.io/smart-ads-451319/smart-ads-api
```

---

## 🚀 Deploy Rápido (Script Completo)

```bash
#!/bin/bash
# deploy.sh - Deploy completo da API

PROJECT_ID="smart-ads-451319"
IMAGE_NAME="smart-ads-api"
VERSION="v2"
REGION="us-central1"

echo "🔨 Building Docker image for linux/amd64..."
cd /Users/ramonmoreira/Desktop/smart_ads/V2
docker buildx build \
  --platform linux/amd64 \
  -f api/Dockerfile \
  -t gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION \
  --push \
  .

echo "🚀 Deploying to Cloud Run..."
gcloud run deploy $IMAGE_NAME \
  --image gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION \
  --platform managed \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 120 \
  --min-instances 1 \
  --no-allow-unauthenticated

echo "🔓 Configurando acesso público (TEMPORÁRIO)..."
gcloud run services add-iam-policy-binding $IMAGE_NAME \
  --region=$REGION \
  --member="allUsers" \
  --role="roles/run.invoker"

echo "✅ Deploy completo!"
echo "URL: https://smart-ads-api-12955519745.us-central1.run.app"
```

---

## 📝 Notas Importantes

### ⚠️ Para Produção:

1. **Remover Acesso Público:**
   - Remover `--member="allUsers"`
   - Implementar autenticação via Service Account no Apps Script

2. **Configurar Alertas:**
   ```bash
   # Criar alerta de custo
   gcloud alpha billing budgets create \
     --billing-account=BILLING_ACCOUNT_ID \
     --display-name="Smart Ads API Budget" \
     --budget-amount=100USD
   ```

3. **Rate Limiting:**
   - Adicionar middleware FastAPI para limitar requisições/hora
   - Exemplo: 1000 requisições/hora por IP

4. **Monitoramento:**
   - Cloud Monitoring (métricas automáticas)
   - Logging detalhado já implementado
   - Alertas em caso de erro 500

### 🔄 Para Múltiplos Clientes:

**Opção A:** Uma Service Account por cliente
```bash
# Criar nova Service Account
gcloud iam service-accounts create client-name-sa

# Dar permissão específica
gcloud run services add-iam-policy-binding smart-ads-api \
  --region=us-central1 \
  --member="serviceAccount:client-name-sa@smart-ads-451319.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

**Opção B:** Uma Service Account para todos (atual)
- Mais simples
- Menos controle granular
- Adequado para MVP

---

## 📞 Contatos e Recursos

### Arquivos Importantes:
- **Dockerfile:** `V2/api/Dockerfile`
- **API:** `V2/api/app.py`
- **Pipeline:** `V2/src/pipeline.py`
- **Apps Script:** `V2/api/apps-script-code.js`
- **Instruções Apps Script:** `V2/api/INSTRUCOES_APPS_SCRIPT.md`

### Documentação Externa:
- [Cloud Run Docs](https://cloud.google.com/run/docs)
- [FastAPI Docs](https://fastapi.tiangolo.com)
- [Apps Script OAuth2](https://developers.google.com/apps-script/guides/services/authorization)

### Comandos Úteis:
```bash
# Ver status do serviço
gcloud run services describe smart-ads-api --region=us-central1

# Ver logs em tempo real
gcloud logging tail "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api"

# Rollback para revisão anterior
gcloud run services update-traffic smart-ads-api --region=us-central1 --to-revisions=smart-ads-api-00006-hmc=100
```

---

**Última Atualização:** 2025-09-30
**Status:** ✅ Produção - Funcionando
**Versão da API:** v2.0.0
**Revisão Cloud Run:** smart-ads-api-00007-7mf