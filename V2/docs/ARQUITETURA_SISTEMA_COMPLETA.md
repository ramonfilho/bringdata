# MAPEAMENTO COMPLETO DO SISTEMA SMART ADS V2

> **DOCUMENTO CRÍTICO**: Leia este documento no início de TODA sessão de desenvolvimento.
> Última atualização: 2026-02-17

---

## STATUS DA CONEXÃO COM BANCO DE DADOS

### RESOLVIDO (18/11/2025)

A conexão com Cloud SQL PostgreSQL está **FUNCIONANDO** corretamente via Unix socket.

**Solução implementada:**
- `database.py` agora detecta `CLOUD_SQL_CONNECTION_NAME` e usa pg8000 driver
- Conexão via `URL.create()` com `unix_sock` parameter
- Password configurado via `DB_PASSWORD` environment variable

**Variáveis de ambiente necessárias:**
```bash
CLOUD_SQL_CONNECTION_NAME=smart-ads-451319:us-central1:smart-ads-db
DB_NAME=smart_ads
DB_USER=postgres
DB_PASSWORD=SmartAds2026DB!
```

**Nota sobre Landing Page:** A página de captura usa `fetch` com `keepalive: true` (não `sendBeacon`).

---

## Estrutura Geral do Projeto

```
/Users/ramonmoreira/Desktop/smart_ads/V2/
├── api/                          # API REST (FastAPI) - Predições e CAPI
├── src/                          # Código ML - Pipeline de treino e produção
│   ├── data_processing/          # Pré-processamento e engenharia de dados
│   ├── features/                 # Engenharia e encoding de features
│   ├── matching/                 # Matching entre leads e vendas
│   ├── model/                    # Treinamento e predição
│   ├── production_pipeline.py    # Pipeline de produção
│   └── train_pipeline.py         # Pipeline de treino
├── landing_page_capi/            # Frontend - Landing Page + captura de leads CAPI
├── files/                        # Artefatos do modelo
├── configs/                      # Configurações (active_model.yaml, devclub.yaml)
├── arquivos_modelo/              # Modelos salvos (.pkl, .json)
├── mlruns/                       # MLflow experiment tracking
└── tests/                        # Testes unitários
```

---

## PARTE 1: API REST (FastAPI)

### Arquivo: `api/app.py` (1709 linhas)

**Propósito:** API principal que orquestra predições de lead scoring, captura de leads CAPI, análise UTM e integração com Meta Ads.

**Framework:** FastAPI + Uvicorn
**Porta:** 8000 (desenvolvimento) ou Cloud Run (produção)
**URL Base Produção:** `https://smart-ads-api-12955519745.us-central1.run.app`

#### Endpoints Principais

| Endpoint | Método | Propósito |
|----------|--------|-----------|
| `/health` | GET | Verificar pipeline e modelo |
| `/predict/batch` | POST | Predição em batch via JSON |
| `/webhook/lead_capture` | POST | Captura leads Página 1 (com FBP/FBC/UTMs) |
| `/webhook/update_survey` | POST | Atualiza lead com pesquisa Página 2 + scoring ML |
| `/webhook/lead_capture/stats` | GET | Estatísticas de leads capturados |
| `/webhook/lead_capture/recent` | GET | Últimos N leads capturados |
| `/capi/process_daily_batch` | POST | Processa batch diário CAPI |

#### Modelos Pydantic Principais

```python
class LeadCaptureRequest:
    name: str                      # Nome completo
    first_name: Optional[str]      # Primeiro nome (CAPI)
    last_name: Optional[str]       # Sobrenome (CAPI)
    email: str
    phone: Optional[str]
    fbp: Optional[str]             # Facebook Browser ID (_fbp cookie)
    fbc: Optional[str]             # Facebook Click ID (_fbc cookie)
    event_id: str                  # ID único evento (deduplicação)
    user_agent: Optional[str]
    event_source_url: Optional[str]
    utm_source/medium/campaign/term/content: Optional[str]
```

---

### Arquivo: `api/database.py` (201 linhas)

**Propósito:** Gerenciar conexão PostgreSQL e modelo SQLAlchemy para tabela `leads_capi`.

**Tecnologia:** SQLAlchemy ORM
**Banco:** PostgreSQL (produção) ou SQLite (desenvolvimento)

#### Conexão (RESOLVIDO 18/11/2025)

O `database.py` detecta `CLOUD_SQL_CONNECTION_NAME` e conecta via Unix socket com pg8000:

```
postgresql+pg8000://postgres@/smart_ads?unix_sock=/cloudsql/smart-ads-451319:us-central1:smart-ads-db/.s.PGSQL.5432
```

#### Modelo: LeadCAPI

```python
class LeadCAPI(Base):
    __tablename__ = 'leads_capi'

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255))
    first_name = Column(String(255))       # Para CAPI
    last_name = Column(String(255))        # Para CAPI
    phone = Column(String(50))
    fbp = Column(String(255))              # Facebook Browser ID
    fbc = Column(String(255))              # Facebook Click ID
    event_id = Column(String(255), unique=True, index=True)
    user_agent = Column(Text)
    client_ip = Column(String(50))
    event_source_url = Column(Text)
    utm_source/medium/campaign/term/content = Column(String(255))
    created_at = Column(TIMESTAMP)
    updated_at = Column(TIMESTAMP)
```

---

### Arquivo: `api/capi_integration.py` (726 linhas)

**Propósito:** Integração com Meta Conversions API (CAPI) para envio server-side de eventos.

**Tecnologia:** facebook-business SDK
**Pixel ID:** 241752320666130

#### Função Principal: `send_lead_qualified_with_value()`

Envia eventos LeadQualified para Meta com:
- UserData (email, phone, nome - hashados SHA256)
- CustomData (valor por decil)
- event_id (deduplicação)
- fbp/fbc (cookies Facebook)

#### Valores por Decil

```python
CONVERSION_RATES = {
    "D1": 0.003836,   # 0.38% → R$ 7.67
    "D2": 0.004933,   # 0.49% → R$ 9.87
    # ...
    "D10": 0.034551,  # 3.45% → R$ 69.10
}
```

---

### Arquivo: `api/business_config.py` (243 linhas)

**Propósito:** Configurações centralizadas de negócio.

```python
PRODUCT_VALUE = 2000.00  # R$ (LTV)
CONVERSION_RATES = {...}  # Taxas por decil
```

---

## PARTE 2: PIPELINE ML (src/)

### Arquivo: `src/production_pipeline.py` (285 linhas)

**Propósito:** Pipeline de produção que orquestra pré-processamento → features → predição.

#### Classe: LeadScoringPipeline

```python
class LeadScoringPipeline:
    def run(filepath: str) -> pd.DataFrame:
        """
        1. load_data()
        2. preprocess() → 10 passos
        3. predict() → modelo RandomForest
        """
```

#### Passos de Pré-processamento

1. remove_duplicates()
2. clean_columns()
3. remove_campaign_features()
4. unify_utm_columns()
5. unify_medium_columns()
6. remove_technical_fields()
7. rename_long_column_names()
8. create_derived_features()
9. apply_categorical_encoding()
10. handle_missing_values()

---

### Arquivo: `src/model/prediction.py` (231 linhas)

**Propósito:** Carregar modelo RandomForest e realizar predições.

#### Arquivos do Modelo

```
arquivos_modelo/ ou files/{timestamp}/
├── modelo_lead_scoring_*.pkl        # RandomForest serializado
├── features_ordenadas_*.json        # Lista de features esperadas
└── model_metadata_*.json            # Métricas, performance
```

---

## PARTE 3: LANDING PAGE CAPI

### Arquivo: `landing_page_capi/codigo_formulario_completo_com_capi.js`

**Propósito:** Capturar formulário no frontend, enviar para API.

> **NOTA (18/11/2025):** Atualmente a página de captura está usando `fetch` com `keepalive: true`, e NÃO `sendBeacon`. A função sendBeacon está no código mas não está ativa.

#### Fluxo de Captura

```javascript
1. getCookie('_fbp')      → Facebook Browser ID
2. getCookie('_fbc')      → Facebook Click ID
3. generateEventID()      → Deduplicação
4. extractUTM()           → utm_source, etc
5. splitName()            → first_name, last_name
6. sendToCapiAPI()        → POST /webhook/lead_capture (fetch com keepalive)
```

---

## PARTE 4: CONFIGURAÇÕES

### `configs/active_model.yaml`

Define qual modelo está em produção:

```yaml
active_model:
  model_name: "v1_devclub_rf_temporal_single"
  model_path: "files/20260130_090227"
```

---

## PARTE 5: FLUXOS PRINCIPAIS

### Fluxo 1: Predição Google Sheets

```
Google Sheets → Apps Script → POST /predict/batch → Pipeline ML → Scores → Sheets
```

### Fluxo 2: Captura CAPI

```
Landing Page (JS) → POST /webhook/lead_capture → PostgreSQL → Batch CAPI → Meta
```

---

## PARTE 6: VARIÁVEIS DE AMBIENTE

### Produção (Cloud Run) - CONFIGURAÇÃO CORRETA

```bash
# Database - VIA UNIX SOCKET (não precisa host/password!)
CLOUD_SQL_CONNECTION_NAME=smart-ads-451319:us-central1:smart-ads-db
DB_NAME=smart_ads
DB_USER=postgres

# Meta CAPI
META_PIXEL_ID=241752320666130
META_ACCESS_TOKEN=xxx

# Google Cloud
GCP_PROJECT_ID=smart-ads-451319
```

### Anotação Cloud Run (já configurada)

```yaml
run.googleapis.com/cloudsql-instances: smart-ads-451319:us-central1:smart-ads-db
```

---

## PARTE 7: CHECKLIST PRÉ-DEPLOY

### ⚠️ ANTES DE QUALQUER DEPLOY, VERIFICAR:

```
[x] Database (RESOLVIDO 18/11/2025)
    [x] database.py suporta CLOUD_SQL_CONNECTION_NAME
    [x] Conexão via pg8000 + Unix socket
    [x] DB_PASSWORD configurado

[ ] Modelo
    [ ] configs/active_model.yaml aponta para modelo correto
    [ ] Arquivos .pkl, .json existem no path

[ ] Meta CAPI
    [ ] META_ACCESS_TOKEN válido (não expirado)
    [ ] Testar evento de teste no Events Manager

[ ] Teste End-to-End
    [ ] POST /webhook/lead_capture → verifica no banco
    [ ] GET /webhook/lead_capture/stats → retorna count > 0
```

---

## PARTE 8: PONTOS CRÍTICOS DE FALHA

| Componente | Risco | Impacto | Solução |
|-----------|-------|---------|---------|
| ~~database.py não conecta ao Cloud SQL~~ | ~~CRÍTICO~~ | ~~Dados perdidos~~ | **RESOLVIDO** - pg8000 + Unix socket |
| Pipeline não carrega | Alto | 503 errors | Validar active_model.yaml |
| Meta token expirado | Alto | CAPI fails | Renovar token (60 dias) |
| FBP/FBC ausentes | Médio | Baixa cobertura | Usar hash como fallback |

---

## HISTÓRICO DE PROBLEMAS

### 18/11/2025 - Dados CAPI perdidos - **RESOLVIDO**

**Sintoma:** Apenas 8 leads no banco após deploy
**Causa:** database.py usando SQLite fallback
**Solução implementada:**
- Adicionado suporte a `CLOUD_SQL_CONNECTION_NAME` em database.py
- Usa pg8000 driver com `URL.create()` e `unix_sock` parameter
- Configurado `DB_PASSWORD=SmartAds2026DB!`
- Migration aplicada para adicionar colunas `first_name` e `last_name`

### 18/11/2025 - Nome/Sobrenome 0% cobertura

**Sintoma:** Quality Score caiu de 7.4 para 7.1
**Causa:** Página "parabéns" sobrescrevia registro com dados incompletos
**Solução:** Priorizar registros com first_name + fallback de extração do campo name

### 18/11/2025 - Gender enum error

**Sintoma:** Erro ao enviar CAPI
**Causa:** Passando string ao invés de Gender enum
**Solução:** Usar Gender.MALE/Gender.FEMALE diretamente

---

## PARTE 9: ACESSO AO DATABASE (Python)

### Como acessar o database programaticamente

O sistema já possui infraestrutura completa para acessar o Cloud SQL PostgreSQL via Python.

#### Método: Usar SessionLocal() do api/database.py

**Arquivo exemplo:** `api/bigquery_sync.py`

```python
from api.database import SessionLocal, LeadCAPI
from datetime import datetime

# Criar sessão
db = SessionLocal()
try:
    # Exemplo 1: Buscar leads por período
    start_date = datetime(2025, 11, 11)
    end_date = datetime(2025, 11, 17)

    leads = db.query(LeadCAPI).filter(
        LeadCAPI.created_at >= start_date,
        LeadCAPI.created_at <= end_date
    ).all()

    # Exemplo 2: Buscar leads por email
    emails = ['email1@example.com', 'email2@example.com']
    leads = db.query(LeadCAPI).filter(
        LeadCAPI.email.in_(emails)
    ).all()

    # Exemplo 3: Buscar campaign_id de emails específicos
    results = db.query(LeadCAPI.email, LeadCAPI.utm_campaign).filter(
        LeadCAPI.email.in_(emails)
    ).all()

    for email, utm_campaign in results:
        # Extrair campaign_id do utm_campaign
        match = re.search(r'\d{18,}', utm_campaign)
        if match:
            campaign_id = match.group(0)
            print(f"{email}: {campaign_id}")

finally:
    db.close()
```

#### Como funciona a conexão

O `database.py` detecta automaticamente o ambiente:

1. **Cloud Run (produção):**
   - Usa `CLOUD_SQL_CONNECTION_NAME` environment variable
   - Conecta via Unix socket: `/cloudsql/smart-ads-451319:us-central1:smart-ads-db/.s.PGSQL.5432`
   - Driver: `postgresql+pg8000`
   - Password: `SmartAds2025!` (via `DB_PASSWORD` env var)

2. **Local (desenvolvimento):**
   - Se não tiver env vars configuradas, usa SQLite fallback
   - Para acessar Cloud SQL localmente, configure Cloud SQL Proxy OU use gcloud auth

#### Funções CRUD disponíveis (api/database.py)

```python
from api.database import (
    get_lead_by_email,
    get_leads_by_emails,
    get_recent_leads,
    count_leads,
    create_lead_capi
)

db = SessionLocal()
try:
    # Buscar lead por email
    lead = get_lead_by_email(db, "email@example.com")

    # Buscar múltiplos leads
    leads = get_leads_by_emails(db, ["email1@example.com", "email2@example.com"])

    # Contar total de leads
    total = count_leads(db)

finally:
    db.close()
```

#### ⚠️ IMPORTANTE: Ambiente Local

Para acessar o database localmente, você precisa:

**Opção 1: Cloud SQL Auth Proxy** (recomendado)
```bash
# Executar proxy (v2 já instalado via homebrew)
cloud-sql-proxy smart-ads-451319:us-central1:smart-ads-db --port=5432 &
sleep 8  # ⚠️ aguardar 8 segundos para autenticar antes de conectar

# Configurar env vars
export DB_HOST=127.0.0.1
export DB_PORT=5432
export DB_NAME=smart_ads
export DB_USER=postgres
export DB_PASSWORD=SmartAds2026DB!
```
> Ver detalhes completos em `docs/acesso_sql.md`

**Opção 2: gcloud auth**
```bash
# Autenticar com gcloud
gcloud auth application-default login

# O SessionLocal() usará suas credenciais automaticamente
```

**Opção 3: Usar dados da produção via CSV**
- Exportar dados de leads para CSV
- Usar CSV localmente (mais simples para desenvolvimento)

---

## COMANDOS ÚTEIS

### Ver status do serviço
```bash
gcloud run services describe smart-ads-api --region=us-central1
```

### Ver logs
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api" --limit=50
```

### Conectar ao Cloud SQL (local)
```bash
gcloud sql connect smart-ads-db --user=postgres --database=smart_ads
```

### Verificar leads no banco
```sql
SELECT COUNT(*) FROM leads_capi;
SELECT * FROM leads_capi ORDER BY created_at DESC LIMIT 10;
```

---

**Este documento deve ser consultado no início de TODA sessão de desenvolvimento para evitar erros críticos em produção.**
