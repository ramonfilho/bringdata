# SMART ADS V2 — ARQUITETURA DO SISTEMA

> **DOCUMENTO CRÍTICO**: Leia no início de TODA sessão de desenvolvimento.
> Última atualização: 2026-03-24

---

## OBJETIVO E LÓGICA DE NEGÓCIO

**Problema:** Anunciantes tomam decisões baseadas em métricas incompletas (compra real leva 7–21 dias), gerando ROAS subótimo e alocação ineficiente de verba.

**Solução:** Sistema de lead scoring ML que identifica, em ~5 minutos após o lead chegar, quais leads têm maior probabilidade de compra — e envia esse sinal de qualidade ao Meta via Conversions API.

**Como funciona:**
1. Lead preenche formulário na landing page (pesquisa com ~10 perguntas)
2. Modelo ML classifica o lead em decis D01–D10 (D10 = maior probabilidade de compra)
3. Sistema envia evento `LeadQualified` ao Meta com **valor proporcional ao decil** (D01→R$3,20 / D10→R$87,39)
4. Meta usa os valores para otimizar anúncios para perfis de maior qualidade

**Por que funciona (moat):**
- Sinal em 5 min vs compra real em 21 dias → Meta otimiza 56x mais rápido
- 100 leads → 30–40 eventos LeadQualified em 1 dia vs 10 eventos Purchase em 21 dias → 63–84x mais aprendizado
- Campanhas novas saem do "modo exploração" em 7 dias vs 35–70 dias

**Resultado validado:** ROAS até 300% maior com o sistema ativo.

**Cliente atual:** DevClub (curso online de programação). Sistema multi-cliente via config — sem alterar código para novos clientes.

---

## ESTRUTURA DE DIRETÓRIOS

```
V2/
├── api/                        # API REST (FastAPI) — produção no Cloud Run
│   ├── app.py                  # Endpoints + A2 (pipeline dict por client_id)
│   ├── database.py             # ORM LeadCAPI + CRUD com has_client_id_column()
│   ├── capi_integration.py     # Envio eventos Meta CAPI
│   ├── railway_mapping.py      # Mapeamento Railway → formato scoring
│   └── deploy_capi.sh          # Script de deploy Cloud Run
├── src/
│   ├── train_pipeline.py       # Pipeline de treino (21 células, importa 100% de core/)
│   ├── production_pipeline.py  # Pipeline de produção (scoring em batch)
│   ├── core/                   # ★ Camada compartilhada — única fonte de verdade
│   │   ├── client_config.py    # ClientConfig dataclass + from_yaml() + validate()
│   │   ├── ingestion.py        # filtro status/risco, filtro produto
│   │   ├── column_unification.py  # unify_survey/sales_columns, filtro_temporal
│   │   ├── category_unification.py  # unify_categories
│   │   ├── utm.py              # unify_utm (canônico — com .lower())
│   │   ├── medium.py           # unify_medium (modo treino / produção via valid_categories)
│   │   ├── dataset_versioning.py  # criar_dataset_pos_cutoff, aplicar_janela_conversao
│   │   ├── matching.py         # match_leads (consolida 6 arquivos antigos)
│   │   ├── feature_engineering.py  # create_features
│   │   ├── encoding.py         # apply_encoding (com clean_column_names + feature registry)
│   │   └── preprocessing.py    # preprocess() — wrapper para produção/monitoramento
│   ├── data_processing/        # Ingestão de arquivos (read_excel, filter_sheets etc.)
│   ├── model/                  # Treino, predição, thresholds de decis
│   ├── monitoring/             # Monitoramento diário (drift, CAPI, operacional)
│   ├── retrain/                # Retreino mensal automatizado
│   └── validation/             # Validação de performance ML vs Meta Ads
├── configs/
│   ├── clients/
│   │   └── devclub.yaml        # Todos os parâmetros do cliente (153 hardcodes extraídos)
│   ├── active_models/
│   │   └── devclub.yaml        # Modelo ativo: run_id, model_path, métricas
│   └── templates/
│       └── client_template.yaml  # Template para onboarding de novos clientes
├── files/{timestamp}/          # Artefatos de cada modelo treinado
├── outputs/                    # Logs timestampados (training/, production/, monitoring/)
└── tests/
    └── fixtures/               # Snapshots de paridade treino × produção
```

**Diretórios deletados no refactor (22/03/2026):**
- `src/matching/` (6 arquivos) → consolidado em `core/matching.py`
- `src/data_processing/medium_*.py` (3 arquivos) → `core/medium.py`
- `src/data_processing/utm_training.py` → `core/utm.py`
- `src/features/feature_engineering_training.py` → `core/feature_engineering.py`
- `src/features/encoding_training.py` → `core/encoding.py`

---

## CAMADA COMPARTILHADA `src/core/`

**Regra crítica:** toda transformação de dados deve ser idêntica em treino, produção e monitoramento. `src/core/` é a implementação única dessa regra.

| Pipeline | Usa `core/` |
|---|---|
| `train_pipeline.py` | ✅ 100% — importa diretamente |
| `production_pipeline.py` | ✅ via `core/preprocessing.py` |
| `monitoring/orchestrator.py` | ✅ via `core/preprocessing.py` |

**Convenção de assinatura:**
```python
def transform(df: pd.DataFrame, config: SubConfig, **artifacts) -> pd.DataFrame:
```
Nunca hardcodes dentro de funções `core/`. Todo valor específico de cliente vem do `ClientConfig`.

---

## CLIENT CONFIG

`ClientConfig` dataclass tipado carregado de `configs/clients/{client_id}.yaml`.

```python
from src.core.client_config import ClientConfig
config = ClientConfig.from_yaml('configs/clients/devclub.yaml')
config.validate()
```

**Sub-configs principais:**
- `ingestion` — termos de filtro de abas, cutoff date, TMB detection columns
- `utm` — mapeamentos Source/Term, lista de UTMs genéricos
- `medium` — frequency_threshold, valid_categories (produção), mapeamentos históricos
- `monitoring` — thresholds de drift, conversion_window_days, missing_rate_ignore_columns
- `model` — mlflow_experiment_name, model_name_template, hyperparâmetros
- `business` — product_value, conversion_rates por decil, thresholds operacionais
- `capi` — pixel_id, event_names, high_quality_decils, currency

**Modelo ativo:** `configs/active_models/{client_id}.yaml` — contém `run_id`, `model_path` e métricas do modelo em produção.

---

## PIPELINE DE TREINO (`src/train_pipeline.py`)

Reproduz célula por célula um notebook Jupyter. Importa 100% de `src/core/`.

| Etapa | O que faz |
|---|---|
| Célula 1 | Lê Excel de `data/devclub/treino/` + Sheets API + vendas Guru |
| Célula 2–3 | Remove abas irrelevantes, duplicatas e colunas desnecessárias |
| Célula 4 | Separa `df_pesquisa` e `df_vendas` (Guru + TMB) |
| Células 5–5.4 | `core/`: unifica colunas, filtro temporal, remove UTMs com alto missing, filtra status/risco, filtra produtos |
| Célula 7–8 | `core/`: unifica categorias, remove features desnecessárias |
| Célula 10–11 | `core/utm.py` e `core/medium.py` |
| Célula 13 | `core/dataset_versioning.py` — cutoff temporal por missing rate |
| Célula 15 | `core/matching.py` — matching leads × vendas → target binário |
| Célula 17 | `core/dataset_versioning.py` — janela de conversão simétrica (20 dias DevClub) |
| Célula 18 | `core/feature_engineering.py` + captura snapshots para drift detection |
| Célula 20 | `core/encoding.py` — ordinal + one-hot + clean_column_names + feature registry |
| Célula 21 | Treino RandomForest + registro MLflow + salva artefatos + atualiza `active_models/devclub.yaml` |

**Parâmetros principais:**
```bash
python -m src.train_pipeline \
  --initial-matching email_telefone \   # padrão
  --split-method temporal_leads \       # padrão
  --tmb-risk-filter all \               # all / none / low / low_medium
  --api-end-date 2026-03-15 \           # limita busca na API Guru (não filtra leads)
  --hyperparams '{"n_estimators": 200, "max_depth": 8, "max_features": "log2", ...}'
  --set-active                          # atualiza configs/active_models/devclub.yaml
  --use-cached-data                     # reutiliza outputs/cache/raw_data_{date}.pkl
```

> **Atenção:** `--api-end-date` controla o range da API Guru, não filtra timestamps dos leads. Para cortar leads por data, usar `--max-date`. O `max_lead_date` real vem de `max(df_vendas['data'])` calculado dinamicamente.

**Artefatos salvos em `files/{timestamp}/`:**
```
modelo_lead_scoring_*.pkl           → RandomForest serializado
features_ordenadas_*.json           → features esperadas (ordem exata)
model_metadata_*.json               → métricas, AUC, lift, decil_analysis
categorias_esperadas.json           → categorias únicas por coluna (drift detection)
distribuicoes_esperadas.json        → proporções do treino (drift detection)
missing_rates_baseline.json         → missing rates de referência (monitoramento)
```

**Modelo de referência (produção em 24/03/2026):**
- Run ID: `2a98e51c` | AUC: 0.745 | 59 features | tmb_risk_filter: all
- Treino de confirmação pós-refactor: run `f3e816b6` | AUC: 0.747 | 49.214 leads | 777 positivos

---

## PIPELINE DE PRODUÇÃO (`src/production_pipeline.py`)

Classe `LeadScoringPipeline` usada pelo endpoint `/railway/process-pending`. Compartilha sequência canônica com treino via `core/preprocessing.py`.

```python
pipeline = LeadScoringPipeline(client_id='devclub')
# Carrega ClientConfig + modelo de configs/active_models/devclub.yaml
```

**Passos (via `core/preprocessing.py`):**
1. Remove duplicatas
2. Limpa colunas score/faixa
3. Remove features de campanha
4. `core/utm.py` — unifica UTM Source/Term
5. `core/medium.py` — unifica UTM Medium (modo produção: valid_categories do feature registry)
6. Renomeia colunas longas
7. `core/category_unification.py` — unifica categorias
8. Check category drift
8.5. Check distribution drift
9. `core/feature_engineering.py`
10. `core/encoding.py` — com feature registry do modelo ativo
11. Mantém features UTM

---

## API REST (`api/app.py`)

**Runtime:** FastAPI + Uvicorn | **Produção:** Cloud Run `bring-data-api-00254-dh5`
**URL:** `https://bring-data-api-gazrm25mda-uc.a.run.app`

**Padrão A2 — pipeline dict por client_id:**
```python
pipelines: Dict[str, LeadScoringPipeline]  # indexado por client_id
# Header X-Client-ID: devclub (default)
```

**Endpoints principais:**

| Endpoint | Método | Função |
|---|---|---|
| `/health` | GET | Status do pipeline e modelo |
| `/predict/batch` | POST | Predição batch via JSON (Google Sheets → Apps Script) |
| `/webhook/lead_capture` | POST | Captura lead Página 1 (FBP/FBC/UTMs) → Railway |
| `/webhook/update_survey` | POST | Atualiza lead Página 2 + scoring ML |
| `/railway/process-pending` | POST | ★ Batch scoring + CAPI → Meta (Cloud Scheduler 5/5 min) |
| `/monitoring/daily-check` | GET | Dispara check de monitoramento completo |
| `/webhook/lead_capture/stats` | GET | Estatísticas de leads |
| `/webhook/lead_capture/recent` | GET | Últimos N leads |

**Fluxo principal (produção):**
```
Landing Page (JS) → /webhook/lead_capture → Railway
Cloud Scheduler (5min) → /railway/process-pending → LeadScoringPipeline → CAPI → Meta
```

**Fluxo predição (Sheets):**
```
Google Sheets → Apps Script → /predict/batch → LeadScoringPipeline → scores → Sheets
```

---

## MONITORAMENTO (`src/monitoring/`)

`MonitoringOrchestrator.run_daily_check()` — disparado via Cloud Scheduler + `/monitoring/daily-check`.

Recebe `ClientConfig` e passa para os 3 sub-monitores.

| Monitor | Verifica |
|---|---|
| `DataQualityMonitor` | Category drift, distribution drift, missing rates, features ausentes após encoding |
| `OperationalMonitor` | Mais de 6h sem leads? Mais de 6h sem CAPI enviado? |
| `CAPIQualityMonitor` | FBP/FBC presentes? Taxa de rejeição Meta > 10%? |

**Thresholds (via `MonitoringConfig` em `devclub.yaml`):**
- Distribution drift categórico: 15pp
- Distribution drift numérico: 2σ
- Missing rate crítico: 20%
- Score distribution: 10pp por decil

**Sumário crítico (12 pontos):** novas categorias, proporções, dados faltantes, features ausentes, score/decil, CAPI enviado, FBP/FBC, resposta Meta, funil completo, taxa de resposta, qualidade leads (24h/semana/mês/histórico), Meta Ads CPL/taxa clique→lead.

**Output:** Slack + log em `outputs/monitoring/`

**Golden snapshot:** `docs/monitoring_golden_snapshot.json` — 3.929 leads, 3 alertas. Referência pré-refactor para comparação pós-deploy.

> **Nota DT-7:** alertas `missing_features` para campanhas Lookalike são esperados e documentados. Threshold de Medium calculado sobre dataset histórico completo (pré-cutoff) — campanhas antigas com alta freq histórica mas inativas no lançamento atual aparecem como ausentes. Ver `PLANO_REFACTOR_MLOPS.md` DT-7.

---

## BANCO DE DADOS

**Railway (principal — leads em produção):**
```
Host: shortline.proxy.rlwy.net:11594
DB: railway | User: postgres
Tabela: leads_capi
Range atual: 2026-02-26 → presente (~107k leads)
```
> Railway é um banco externo — não há acesso para alterar schema. `database.py` detecta em runtime se colunas opcionais (ex: `client_id`) existem via `has_client_id_column()`.

**Cloud SQL (MLflow tracking):**
```
Instância: smart-ads-451319:us-central1:bring-data-db
DB: mlflow | Acesso direto: 104.197.138.129:5432
MLFLOW_TRACKING_URI=postgresql+psycopg2://postgres:SmartAds2026DB!@104.197.138.129:5432/mlflow
```

**Artifacts MLflow:** `gs://bring-data-mlflow/artifacts/`

**Acesso local via proxy:**
```bash
cloud-sql-proxy smart-ads-451319:us-central1:bring-data-db --port=5432 &
sleep 8
# Conecta ao MLflow DB (não ao bring_data — esse está no Railway)
```

---

## MATCHING DE LEADS × VENDAS

Consolidado em `src/core/matching.py` — função `match_leads(df_pesquisa, df_vendas, config)`.

| Método | Descrição |
|---|---|
| `email_only` | Só email |
| `email_telefone` | Email + telefone (**padrão** — +16.5% dados vs só email) |
| `robusto` | Variantes de normalização |
| `validation` | Com validação extra |

Configurável via `IngestionConfig.matching_method` no `devclub.yaml`.

---

## MLflow

```bash
# Tracking
export MLFLOW_TRACKING_URI=postgresql+psycopg2://postgres:SmartAds2026DB!@104.197.138.129:5432/mlflow

# Ver runs
mlflow ui  # abre em localhost:5000

# Modelo em produção
Run ID: 2a98e51c | Experiment: devclub_lead_scoring
```

---

## VARIÁVEIS DE AMBIENTE (PRODUÇÃO)

```bash
# Railway
RAILWAY_DB_HOST=shortline.proxy.rlwy.net
RAILWAY_DB_PORT=11594
RAILWAY_DB_NAME=railway
RAILWAY_DB_USER=postgres
RAILWAY_DB_PASSWORD=...

# Meta
META_PIXEL_ID=241752320666130
META_ACCESS_TOKEN=...          # ⚠️ expira a cada 60 dias — renovar!

# Guru API
GURU_API_TOKEN=...             # ⚠️ contém '|' — usar python-dotenv, não source

# MLflow
MLFLOW_TRACKING_URI=postgresql+psycopg2://...

# GCP
GCP_PROJECT_ID=smart-ads-451319
```

---

## DEPLOY

```bash
# Deploy (sem alterar tráfego)
bash api/deploy_capi.sh

# Redirecionar tráfego
gcloud run services update-traffic bring-data-api \
  --to-revisions REVISION=100 --region us-central1

# Ver revisões ativas
gcloud run revisions list --service bring-data-api --region us-central1

# Rollback
gcloud run services update-traffic bring-data-api \
  --to-revisions REVISAO_ANTERIOR=100 --region us-central1
```

**Revisão atual:** `bring-data-api-00254-dh5` (24/03/2026)

---

## COMANDOS ÚTEIS

```bash
# Logs Cloud Run (última revisão)
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=bring-data-api" --limit=50

# Treinar modelo (parâmetros baseline)
python -m src.train_pipeline \
  --initial-matching email_telefone \
  --split-method temporal_leads \
  --tmb-risk-filter all \
  --api-end-date 2026-03-15 \
  --hyperparams '{"n_estimators": 200, "max_depth": 8, "max_features": "log2", "min_samples_leaf": 3, "min_samples_split": 2, "class_weight": "balanced"}'

# Monitoramento local
bash src/monitoring/run_monitoring_local.sh

# Monitoramento via API
curl -s "https://bring-data-api-gazrm25mda-uc.a.run.app/monitoring/daily-check?hours=24"

# Retreino mensal
python src/retrain/retraining_orchestrator.py --config configs/retreino_mensal.yaml
```

---

## QUALIDADE DO SINAL CAPI — DECISÕES ARQUITETURAIS

### Roteamento por plataforma (DT-CAPI-01)

**Descoberta em 09/04/2026:** O sistema envia eventos CAPI ao Meta para **todos** os leads que passam pelo webhook e pelo polling Railway, independente do `utm_source` de origem. Isso inclui leads vindos de Google Ads (`source=google-ads`, ~3.800/mês) e tráfego orgânico (YouTube Bio, NULL, ~400/mês).

**Por que isso é um problema:** O Meta usa o sinal `LeadQualified` para aprender quais perfis de usuário tendem a comprar e direcionar novos anúncios. Incluir leads que o Meta nunca gerou faz o algoritmo aprender padrões que ele não consegue usar para targeting — dilui o sinal sem nenhum benefício para a otimização das campanhas Meta.

**Correção parcial aplicada (09/04/2026):** `utm_source_allowlist` em `CAPIConfig` — o backend só envia CAPI se `utm_source` estiver na lista configurada. Para DevClub: `["facebook-ads", "instagram"]`. Leads de outras origens recebem `capiStatus = 'skipped'`.

**Decisão arquitetural de longo prazo:** Um modelo único de scoring serve todas as plataformas — o perfil de comprador não muda por canal. O que muda é o dispatch de eventos: cada plataforma tem sua própria integração configurada com a lista de `utm_source` que alimenta. Ao adicionar Google Ads como canal otimizável, basta adicionar uma `GoogleAdsConfig` com `utm_source: ["google-ads"]` — o pipeline de treino e scoring não muda.

```
Lead scored (modelo único)
        ↓
utm_source == 'facebook-ads' / 'instagram'  →  Meta CAPI (LeadQualified)
utm_source == 'google-ads'                  →  Google Ads API (futuro)
utm_source == orgânico / outro              →  nenhum envio
```

**Esta refatoração deve acontecer quando:** o segundo canal pago (Google Ads ou outro) for ativado como objetivo de otimização. Não antes — o `utm_source_allowlist` mitiga o problema até lá.

---

### Contaminação histórica LEAD|LQ (DT-CAPI-02)

**Descoberta em 09/04/2026:** Campanhas com `LEAD | LQ` no `utm_campaign` tinham seus adsets Meta otimizando para o evento padrão `lead` (genérico). O backend enviava `LeadQualified` (ML CAPI) para os mesmos leads, gerando dois eventos distintos para a mesma pessoa no mesmo pixel. Representava ~13% do volume total de leads.

**Impacto:** O Meta aprendeu com sinal contaminado por aproximadamente 2 meses antes da correção. Os ~7.500 eventos já enviados não podem ser removidos retroativamente.

**Correção aplicada (09/04/2026):** `utm_blocklist: ["LEAD | LQ"]` em `CAPIConfig` no `devclub.yaml`. Leads dessas campanhas recebem `capiStatus = 'blocked'` e não geram evento CAPI.

---

## PONTOS CRÍTICOS ATIVOS

| Risco | Impacto | Ação |
|---|---|---|
| Meta token expira (60 dias) | CAPI para de funcionar | Renovar `META_ACCESS_TOKEN` |
| Guru token com `\|` no valor | Pipeline não lê token se usar `source .env` | Sempre usar `python-dotenv` — já implementado em todos os entry points |
| Pipeline de retreino incompleto (Sprint 2–3) | Deploy manual necessário | Implementar quality gate automático + deploy condicional |
| Dados TMB desatualizados | Retreino com dados errados | Verificar data do arquivo antes do retreino |
| Threshold Medium calculado pré-cutoff (DT-7) | Alertas falsos de features ausentes | Baixa prioridade — endereçar antes de 3+ clientes |
| Leads não-Meta recebendo CAPI (DT-CAPI-01) | Sinal Meta contaminado com Google/orgânico | `utm_source_allowlist` aplicado — refatorar dispatch ao ativar 2º canal pago |
| Contaminação histórica LEAD\|LQ (DT-CAPI-02) | ~7.500 eventos poluídos já enviados | Bloqueio aplicado — monitorar recuperação do sinal Meta |

---

## ROADMAP ATUAL

Ver `ROADMAP_MLOPS_MATURIDADE.md` para backlog completo com dependências.

**Fases 1–3 concluídas (22-24/03/2026):**
- `src/core/` com 11 módulos — skew treino/produção eliminado estruturalmente
- `ClientConfig` parametriza todos os pipelines
- API multi-cliente (A2 pattern)
- Deploy do refactor validado e em produção

**Próximos itens ativos:**
- **Item 6:** Atualizar `ARQUITETURA_SISTEMA_COMPLETA.md` ✅ (este documento)
- **Item 7:** `src/core/validation.py` — schema check pré-treino (antes do Cliente B)
- **Item 8:** Teste A/B champion/challenger em produção
- **Itens 10–12:** Onboarding Cliente B (aguardando dados)
