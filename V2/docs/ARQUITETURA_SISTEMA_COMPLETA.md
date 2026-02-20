# SMART ADS V2 — ARQUITETURA DO SISTEMA

> **DOCUMENTO CRÍTICO**: Leia no início de TODA sessão de desenvolvimento.
> Última atualização: 2026-02-20

---

## OBJETIVO E LÓGICA DE NEGÓCIO

**Problema:** Anunciantes tomam decisões baseadas em métricas incompletas (compra real leva 7–21 dias), gerando ROAS subótimo e alocação ineficiente de verba.

**Solução:** Sistema de lead scoring ML que identifica, em 3 horas após o lead chegar, quais leads têm maior probabilidade de compra — e envia esse sinal de qualidade ao Meta via Conversions API.

**Como funciona:**
1. Lead preenche formulário na landing page (pesquisa com ~10 perguntas)
2. Modelo ML classifica o lead em decis D1–D10 (D10 = maior probabilidade de compra)
3. Sistema envia evento `LeadQualified` ao Meta com **valor proporcional ao decil** (D1→R$7,67 / D10→R$69,10)
4. Meta usa os valores para otimizar anúncios para perfis de maior qualidade

**Por que funciona (moat):**
- Sinal em 3h vs compra real em 21 dias → Meta otimiza 56x mais rápido
- 100 leads → 30–40 eventos LeadQualified em 1 dia vs 10 eventos Purchase em 21 dias → 63–84x mais aprendizado
- Campanhas novas saem do "modo exploração" em 7 dias vs 35–70 dias

**Resultado validado:** ROAS até 300% maior com o sistema ativo.

**Cliente atual:** DevClub (curso online de programação). Arquitetura preparada para escalar para múltiplos clientes.

---

## ESTRUTURA DE DIRETÓRIOS

```
V2/
├── api/                    # API REST (FastAPI) — produção no Cloud Run
├── src/
│   ├── train_pipeline.py   # Pipeline de treino (21 células, replica notebook)
│   ├── production_pipeline.py  # Pipeline de produção (scoring em batch)
│   ├── data_processing/    # Ingestão, limpeza, unificação de dados
│   ├── features/           # Feature engineering e encoding
│   ├── matching/           # Matching leads × vendas
│   ├── model/              # Treino, predição, thresholds de decis
│   ├── monitoring/         # Monitoramento diário (drift, CAPI, operacional)
│   ├── retrain/            # Retreino mensal automatizado
│   └── validation/         # Validação de performance ML vs Meta Ads
├── configs/                # Configurações YAML (active_model, devclub, retreino)
├── files/{timestamp}/      # Artefatos de cada modelo treinado
├── outputs/                # Logs timestampados (training/, production/, monitoring/)
└── tests/                  # Testes unitários
```

---

## PIPELINE DE TREINO (`src/train_pipeline.py`)

Reproduz célula por célula um notebook Jupyter. Entrada: arquivos Excel + Google Sheets (Guru).

| Etapa | O que faz |
|-------|-----------|
| Célula 1–3 | Lê Excel de `data/devclub/treino/` + Sheets API, remove duplicatas e colunas desnecessárias |
| Célula 4 | Separa em `df_pesquisa` (respostas do formulário) e `df_vendas` (vendas Guru + TMB) |
| Células 5–5.4 | Unifica colunas, filtro temporal, remove UTMs com alto missing, filtra status/risco, filtra produtos DevClub |
| Célula 7–8 | Unifica e normaliza categorias de pesquisa, remove features desnecessárias |
| Célula 10–11 | Unifica UTM Source/Term e UTM Medium |
| Célula 13 | Filtro temporal por missing rate (versão do dataset) |
| Célula 15 | **Matching leads × vendas** (email + telefone) → cria target binário (converteu=1) |
| Célula 17 | Janela de conversão de 20 dias (captação 7d + CPL 6d + carrinho 7d) |
| Célula 18 | **Feature engineering** + captura de categorias/distribuições para drift detection |
| Célula 20 | Encoding categórico (estratégia `binary_top3` para Medium) |
| Célula 21 | **Treino RandomForest** + registro MLflow + salva artefatos + atualiza `business_config.py` com taxas de conversão corrigidas pelo recall real |

**Parâmetros principais:**
- `--initial-matching`: método de matching (padrão: `email_telefone`)
- `--split-method`: `temporal_leads` (padrão) / `temporal` / `stratified`
- `--medium-strategy`: `binary_top3` (padrão)
- `--set-active`: atualiza `configs/active_model.yaml` com o novo modelo
- `--tune-hyperparams`: grid search opcional

**Artefatos salvos em `files/{timestamp}/`:**
```
modelo_lead_scoring_*.pkl       → RandomForest serializado
features_ordenadas_*.json       → features esperadas (ordem exata)
model_metadata_*.json           → métricas, AUC, lift, decil_analysis
categorias_esperadas.json       → categorias únicas por coluna (drift detection)
distribuicoes_esperadas.json    → proporções do treino (drift detection)
test_set_predictions.csv        → predições do test set (opcional)
```

---

## PIPELINE DE PRODUÇÃO (`src/production_pipeline.py`)

Classe `LeadScoringPipeline` usada pelo endpoint `/predict/batch`. Espelha exatamente o treino.

**Fluxo:**
```
load_data() → 11 passos preprocess → predict()
```

**Passos:**
1. Remove duplicatas
2. Limpa colunas score/faixa
3. Remove features de campanha
4. Unifica UTM Source/Term
5. Unifica UTM Medium
6. Renomeia colunas longas
7. Unifica categorias de pesquisa
8. **Check category drift** (categorias novas não vistas no treino)
8.5. **Check distribution drift** (mudanças nas proporções)
9. Feature engineering
10. Encoding categórico
11. Mantém features UTM

Carrega modelo ativo via `configs/active_model.yaml`.

---

## API REST (`api/app.py`)

**Runtime:** FastAPI + Uvicorn | **Produção:** Cloud Run (`https://smart-ads-api-12955519745.us-central1.run.app`)

| Endpoint | Método | Função |
|----------|--------|--------|
| `/health` | GET | Status do pipeline e modelo |
| `/predict/batch` | POST | Predição batch via JSON (Google Sheets → Apps Script) |
| `/webhook/lead_capture` | POST | Captura lead Página 1 (FBP/FBC/UTMs) → PostgreSQL |
| `/webhook/update_survey` | POST | Atualiza lead Página 2 + scoring ML |
| `/webhook/lead_capture/stats` | GET | Estatísticas de leads |
| `/webhook/lead_capture/recent` | GET | Últimos N leads |
| `/capi/process_daily_batch` | POST | Batch CAPI diário → Meta |
| `/monitoring/run` | POST | Dispara check de monitoramento |

**Fluxo CAPI:**
```
Landing Page (JS) → /webhook/lead_capture → PostgreSQL → CAPI batch → Meta Ads
```

**Fluxo predição:**
```
Google Sheets → Apps Script → /predict/batch → LeadScoringPipeline → scores → Sheets
```

---

## MONITORAMENTO (`src/monitoring/`)

`MonitoringOrchestrator.run_daily_check()` — disparado diariamente via API.

**3 monitors executados:**

| Monitor | Verifica |
|---------|----------|
| `DataQualityMonitor` | Category drift, distribution drift, missing rates nos dados dos Sheets |
| `OperationalMonitor` | Mais de 6h sem leads? Mais de 6h sem CAPI enviado? |
| `CAPIQualityMonitor` | FBP/FBC presentes? Taxa de rejeição Meta > 10%? |

**Thresholds (`monitoring/config.py`):**
- Distribution drift categórico: 15pp
- Distribution drift numérico: 2σ
- Missing rate crítico: 20%
- Score distribution: 10pp por decil

**Sumário crítico (11 pontos):** novas categorias, mudanças nas proporções, dados faltantes, features ausentes, mudança em score/decil, CAPI enviado, FBP/FBC preenchidos, resposta Meta, funil completo, taxa de resposta à pesquisa, qualidade dos leads (score médio + % D9/D10) por período (24h/semana/mês/histórico).

**Output:** Slack + log em `outputs/monitoring/{timestamp}.log`

---

## VALIDAÇÃO DE PERFORMANCE (`src/validation/`)

Script `validate_ml_performance.py` — compara campanhas COM ML vs SEM ML.

- Busca dados via Meta Ads API
- Faz matching leads → vendas (por período)
- Calcula métricas por decil D1–D10 (lift, conversão, ROAS)
- Gera relatório comparativo
- Detecta campanhas atípicas via `configs/campanhas_atipicas.yaml`

---

## RETREINO MENSAL (`src/retrain/`)

`RetreinoMensal` — arquitetura **hook-based** (reutiliza 100% do `train_pipeline.py`, zero duplicação).

**Fluxo:**
```
Cloud Scheduler (mensal) → Cloud Run Job → retraining_orchestrator.py
```

**Implementado (Sprint 1.1):**
1. Valida arquivo TMB atualizado
2. Calcula `api_start_date` dinamicamente (dia seguinte à última venda do champion)
3. **Quality Gate Hook** (antes do treino): compara missing rates novos vs baseline → aborta se diferença > 20pp
4. **Validation Hook** (após feature engineering): valida drift de distribuições
5. Treina modelo challenger via `train_pipeline.main()`

**Pendente (Sprint 2–3):**
- Comparação champion vs challenger (AUC, lift, monotonia)
- Decisão de deploy: auto-approve / aprovação manual / rejeitar
- Deploy condicional (atualiza `active_model.yaml`)
- Relatório Excel + notificação Slack

---

## BANCO DE DADOS (`api/database.py`)

**Produção:** PostgreSQL via Cloud SQL (Unix socket + pg8000)
**Local:** SQLite (fallback automático)
**Tabela principal:** `leads_capi`

```
CLOUD_SQL_CONNECTION_NAME=smart-ads-451319:us-central1:smart-ads-db
DB_NAME=smart_ads | DB_USER=postgres | DB_PASSWORD=SmartAds2026DB!
```

**Acesso local:**
```bash
cloud-sql-proxy smart-ads-451319:us-central1:smart-ads-db --port=5432 &
sleep 8  # aguardar autenticação
export DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=smart_ads DB_USER=postgres DB_PASSWORD=SmartAds2026DB!
```

---

## MATCHING DE LEADS × VENDAS

Múltiplos algoritmos em `src/matching/`:

| Método | Descrição |
|--------|-----------|
| `email_only` | Só email |
| `email_telefone` | Email + telefone (**padrão** — +16.5% dados vs só email) |
| `robusto` | Variantes de normalização |
| `validation` | Com validação extra |
| `unified_last6` | Últimos 6 meses unificado |

---

## VARIÁVEIS DE AMBIENTE (PRODUÇÃO)

```bash
CLOUD_SQL_CONNECTION_NAME=smart-ads-451319:us-central1:smart-ads-db
DB_NAME=smart_ads
DB_USER=postgres
DB_PASSWORD=SmartAds2026DB!
META_PIXEL_ID=241752320666130
META_ACCESS_TOKEN=xxx          # expira a cada 60 dias — renovar!
GCP_PROJECT_ID=smart-ads-451319
```

---

## CHECKLIST PRÉ-DEPLOY

```
[ ] configs/active_model.yaml aponta para modelo correto
[ ] Arquivos .pkl e .json existem no path do modelo
[ ] META_ACCESS_TOKEN válido (verificar expiração — 60 dias)
[ ] Testar POST /webhook/lead_capture → verifica no banco
[ ] Testar GET /webhook/lead_capture/stats → count > 0
```

---

## PONTOS CRÍTICOS ATIVOS

| Risco | Impacto | Ação |
|-------|---------|------|
| Meta token expira (60 dias) | CAPI para de funcionar | Renovar token |
| Sincronização treino/produção/monitoramento | Quebra silenciosa em produção | Toda mudança no treino deve ser propagada para os outros pipelines |
| Pipeline de retreino incompleto | Deploy manual necessário | Implementar Sprint 2–3 |
| Dados TMB desatualizados | Retreino com dados errados | Verificar data do arquivo antes do retreino |

---

## COMANDOS ÚTEIS

```bash
# Ver logs do Cloud Run
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api" --limit=50

# Conectar ao Cloud SQL
gcloud sql connect smart-ads-db --user=postgres --database=smart_ads

# Verificar leads no banco
SELECT COUNT(*) FROM leads_capi;
SELECT * FROM leads_capi ORDER BY created_at DESC LIMIT 10;

# Treinar modelo
python -m src.train_pipeline --initial-matching email_telefone --set-active

# Executar retreino mensal
python src/retrain/retraining_orchestrator.py --config configs/retreino_mensal.yaml

# Rodar monitoramento local
bash src/monitoring/run_monitoring_local.sh
```

---

## ROADMAP DE EVOLUÇÃO

**Agora (Fase 1):**
- Retreino mensal completo (Sprint 2–3)
- Refactor de normalização: garantir paridade exata entre treino/produção/monitoramento

**Fase 2 — Profissionalização:**
- Componentes configuráveis e reutilizáveis por cliente
- Onboarding checklist para novos clientes

**Fase 3 — MLOps Completo:**
- Vertex AI Pipelines / Kubeflow
- Feature Store
- CI/CD para modelos
- Google / TikTok Ads além do Meta
