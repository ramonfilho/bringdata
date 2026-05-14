# Plano de Refatoração MLOps — Bring Data V2 (Catálogo Técnico + Histórico)

**Data:** 2026-02-23
**Atualizado:** 2026-04-27
**Papel:** (1) **histórico** completo do refactor MLOps (motivação, 153 hardcodes mapeados, decisões arquiteturais, fases já executadas), (2) **catálogo técnico** dos itens DT-X (dívida técnica) e R-X (pré-requisitos do Cliente B).

> **Status canônico e prioridade vivem em `PLANO_EXECUCAO.md`.** Este documento descreve o "como" técnico de cada DT-X / R-X e preserva o histórico do refactor; o "quando" é definido lá. Quando houver conflito sobre prioridade ou status, o PLANO_EXECUCAO vence. Ao concluir um item, atualizar a marcação RESOLVIDO/✅ neste arquivo E mover/remover o item da seção correspondente do PLANO_EXECUCAO.

Referências:
- Roadmap (sequência de execução): `docs/PLANO_EXECUCAO.md`
- Histórico do deploy do refactor: `docs/arquivo/CHECKLIST_DEPLOY_REFACTOR.md`

---

## Glossário rápido (termos do projeto que aparecem ao longo do doc)

Adicionado em 10/05/2026 quando a documentação foi reorganizada pra leitura humana primeiro. Termos universais (encoding, OHE, dtype, fallback, ML jargon clássico) ficam sem explicação. Termos específicos do nosso codebase/config são explicados aqui uma vez:

- **Single Source of Truth** — princípio do refactor: cada transformação de dados existe em UM lugar só (`src/core/`), e treino/produção/monitoramento todos importam dele. Antes do refactor, a mesma transformação era reimplementada 2-3 vezes em arquivos diferentes, com divergências silenciosas entre eles.
- **`src/core/`** — diretório com as funções puras de transformação de dados. Cada função recebe um DataFrame + um `ClientConfig` e devolve o DataFrame transformado. Não tem estado, não tem hardcode de cliente.
- **`ClientConfig`** — dataclass tipado que carrega todos os parâmetros de um cliente do YAML. Tem sub-configs (`encoding`, `feature`, `model`, `business`, `monitoring`, etc.). É o que torna `core/` parametrizável por cliente.
- **`configs/clients/{cliente}.yaml`** — config **estática** do cliente: encoding default, mapeamentos UTM/Medium, schema da pesquisa, hyperparameters do treino, business config. Muda raramente.
- **`configs/active_models/{cliente}.yaml`** — config **dinâmica** do experimento em produção: qual `mlflow_run_id` está ativo, variantes do A/B test, ajustes específicos por variante (encoding, conversion rates). Muda a cada retreino ou A/B novo.
- **`mlflow_run_id`** — identificador único de cada treino no MLflow. É como cada modelo é referenciado em todo o sistema.
- **`feature_registry`** — JSON que o `train_pipeline` salva junto com o modelo no MLflow, listando quais colunas o modelo espera receber e em que ordem. É o que o `apply_encoding` em produção tenta replicar.
- **`--set-active`** — flag do `train_pipeline.py` que marca um modelo recém-treinado como o ativo no `configs/active_models/{cliente}.yaml`. Sem ela, o modelo é treinado e registrado no MLflow mas não vai pra produção.
- **shim de variante (Champion shim)** — entrada no YAML de variantes A/B que existe **só pra hospedar a configuração** (encoding, conversion rates) de um modelo legado, sem fazer roteamento de tráfego próprio. Funciona como "configuração-fantasma": o modelo legado continua sendo usado pra leads que não caem em variante específica, mas a config dele fica acessível pelo mesmo mecanismo do A/B.
- **override (de variante)** — ajuste específico de uma variante A/B em cima da regra base do cliente. Pode ser de encoding, de predictor (modelo) ou de conversion_rates. Quem decide qual override aplicar é o roteador A/B no momento do scoring.
- **OHE (one-hot encoding)** vs **encoding ordinal** — termos universais de ML, mas no nosso contexto: idade e faixa salarial podem ser tratadas como categorias soltas (uma coluna por faixa, OHE) ou em ordem (uma coluna só, com valor 0..N na ordem `< 18 < 18-24 < 25-34 ...`). Modelos diferentes treinaram com formatos diferentes.
- **canary** — uma revisão recém-deployada que recebe % crescente de tráfego (0% → 10% → 50% → 100%) antes de ir a 100%, pra detectar problema com exposição limitada.
- **Identificadores DT-X / R-X / T1-X** — IDs codificados que aparecem no histórico de commits e PRs. Cada item técnico abaixo tem o ID no rodapé (`*Identificador histórico: DT-X.*`); os títulos novos descrevem em linguagem natural o que o item faz. Use os IDs só pra cruzar com commits antigos.

---

> ## ⚠️ AÇÃO URGENTE — PRAZO: 15/04/2026
>
> **Retreino com importance weighting (DevClub)**
>
> A campanha de controle (10–20% do orçamento fora do ML) foi ativada em
> 15/03/2026. A partir desse momento, o dataset começa a acumular dados de
> leads captados por um perfil menos enviesado — o insumo necessário para
> o retreino com pesos.
>
> **Por quê é urgente:** foi confirmado na reunião de 11/03/2026 que o modelo
> sofre feedback loop ativo (D10 chegou a 41% dos leads no LF45, vs 10%
> esperado). O modelo atual foi treinado em dados já enviesados: o Meta
> entregou predominantemente para perfis D10, o que super-representa esse
> grupo no treino e sub-representa D1–D6. Sem correção, o modelo continuará
> otimizando para um público progressivamente mais estreito.
>
> **O que fazer:**
> 1. Após o LF46 encerrar (~2 semanas), coletar os leads da campanha de
>    controle como amostra menos enviesada.
> 2. Retreinar usando importance weighting: atribuir peso maior aos leads
>    provenientes da campanha de controle e peso menor aos leads D10
>    sobre-representados, numa janela deslizante de 90 dias.
> 3. Avaliar se a distribuição de decis voltou a se aproximar da uniforme
>    (alerta: D10 > 40% indica loop ainda ativo).
> 4. Implementar como hook no `retraining_orchestrator.py` para que os
>    pesos sejam calculados automaticamente a cada retreino mensal.
>
> **Critério de conclusão:** modelo retreinado com pesos, D10 estável em
> dois lançamentos consecutivos abaixo do limiar de 40%.
>
> **Status (16/04/2026):** prazo vencido sem execução. Ação incorporada ao `PLANO_EXECUCAO.md` Fase 5 (retreino pós-resultado A/B). Dados da campanha de controle disponíveis desde 15/03/2026.

---

## 1. Contexto e Motivação

O sistema atual foi construído para um único cliente (DevClub). O código funciona, mas contém 5 componentes duplicados entre treino e produção com divergências conhecidas que já causaram quebra em produção. Com um segundo cliente confirmado, qualquer expansão sem refatoração resultará em triplicação de código e divergências incontroláveis.

**Problema central:** não há Single Source of Truth para as transformações de dados. Treino e produção aplicam regras diferentes aos mesmos campos, o monitoramento não garante usar as mesmas funções que produção, e todas as configurações de cliente estão hardcoded no código.

---

## 2. Decisão Arquitetural

**Escolha: Option B — Shared Core Layer**

**Princípio central:** toda transformação de dados vive em `src/core/` como função pura parametrizada por `ClientConfig`. Os pipelines se tornam orquestradores que importam de `core/`, nunca reimplementam transformações.

---

## 3. Nova Estrutura de Diretórios

```
bring_data/V2/
├── src/
│   ├── core/                        # NOVO — Single Source of Truth
│   │   ├── client_config.py         # ClientConfig dataclass + todos os sub-configs
│   │   ├── utils.py                 # Utilitários genéricos: normalizar_telefone, normalizar_email, limpar_texto, remove_columns, detect_problematic_columns, clean_column_names, UnionFind
│   │   ├── ingestion.py             # filter_sheets, remove_duplicates_per_sheet, consolidate_datasets, filter_sales_by_product, aplicar_filtro_status_risco
│   │   ├── column_unification.py    # unify_columns, aplicar_filtro_temporal
│   │   ├── category_unification.py  # unify_categories
│   │   ├── utm.py                   # unify_utm
│   │   ├── medium.py                # unify_medium (consolida 3 arquivos atuais)
│   │   ├── matching.py              # match_leads (consolida 6 arquivos atuais)
│   │   ├── dataset_versioning.py    # criar_dataset_pos_cutoff, aplicar_janela_conversao
│   │   ├── feature_engineering.py   # create_features
│   │   ├── encoding.py              # apply_encoding (versão produção é canônica)
│   │   └── preprocessing.py        # lista de colunas vem do config
│   ├── eda/                         # NOVO — EDA → Config Generator
│   │   └── generate_client_config.py
│   ├── nlp/                         # FUTURO — reservado na arquitetura
│   ├── train_pipeline.py            # Existente — importa de core/
│   ├── production_pipeline.py       # Existente — importa de core/
│   ├── monitoring/                  # Existente — importa de core/
│   ├── retrain/                     # Existente — verificar se está ok
│   └── validation/                  # Existente — usa core/ onde aplicável
└── configs/
    ├── clients/                     # NOVO
    │   ├── devclub.yaml
    │   └── clientb.yaml
    ├── active_models/               # Renomeado de active_model.yaml singular
    │   ├── devclub.yaml
    │   └── clientb.yaml
    └── templates/
        └── client_template.yaml     # Documenta todas as chaves obrigatórias
```

---

## 4. Componentes Novos

### 4.1 ClientConfig (`src/core/client_config.py`)

Dataclass tipado carregado de `configs/clients/{client}.yaml`. Sub-configs organizados por pipeline e fase de implementação:

#### Grupo A — Pipelines ML core (Fases 1–2)

Necessários para treino, produção e monitoramento funcionarem multi-cliente. São implementados inteiramente na Fase 1 (definição) e Fase 2 (migração).

| Sub-config | Pipelines | Responsabilidade |
|---|---|---|
| `InfraConfig` | Todos | GCP project ID, Cloud Run URL, GCS buckets, Guru API base URL — valores de infraestrutura que mudam por cliente/ambiente |
| `IngestionConfig` | Train + Produção | Colunas de detecção TMB, identificadores, bare_campaign_names, prefixos de arquivo, cutoff date |
| `UTMConfig` | Train + Produção + Monitoring | Regras de unificação UTM (case normalization, mapeamentos source/term) **[dev/retreino — adicionar `utm.source_to_channel_mapping`: ex. `{'youtube-bio': 'youtube'}` — sources orgânicas que colapsam em um canal existente, distinto de `source_to_outros`]** |
| `MediumConfig` | Train + Produção + Monitoring | Categorias válidas, descontinuadas, estratégia (binary_top3), mapeamento histórico **[dev/retreino — binary_top3 removido do treino; Medium usa `pd.get_dummies` dinâmico (7 features); estratégia de produção a confirmar antes da migração para `core/`]** |
| `CategoryConfig` | Train + Produção | Colunas categóricas a normalizar e mapeamentos semânticos por coluna |
| `MatchingConfig` | Train + Produção | Estratégia de matching, colunas de identificador, path de validação cruzada |
| `FeatureConfig` | Train + Produção | Colunas críticas, colunas a remover, prefixos de categorização do registry, `nlp_columns: []` (reservado) |
| `EncodingConfig` | Train + Produção | Variáveis ordinais, categorias binary_top3, features a remover pós-encoding, threshold de detecção |
| `ModelConfig` | Train | Hiperparâmetros, nome do experimento MLflow, template do nome do modelo, thresholds de tuning |
| `MonitoringConfig` | Monitoring + Retrain | Nome do modelo, janela de conversão, medium_strategy |
| `CAPIConfig` | API (produção) | Pixel ID Meta, event names (`LeadQualified`, `LeadQualifiedHighQuality`, `Faixa A`), mapeamento decil→valor, país, moeda, multiplicador de eventos |

#### Grupo B — API operacional (Fase 2)

Não bloqueiam a migração do pipeline ML. Podem ser implementados depois que Grupo A estiver estável.

| Sub-config | Pipelines | Responsabilidade |
|---|---|---|
| `APIConfig` | API | CORS origins, column_mapping do formulário DevClub, batch sizes, GENERIC_UTMS, period_days — constantes operacionais do servidor |

#### Grupo C — Validação de campanhas (Fase 3+)

**Não implementar nas Fases 1–2.** O módulo `validation/` continua funcionando com os hardcodes atuais enquanto os pipelines ML são migrados. Só criar `ValidationConfig` quando a validação se tornar prioridade ou quando um segundo cliente precisar rodar validação.

| Sub-config | Pipelines | Responsabilidade |
|---|---|---|
| `ValidationConfig` | validation/ | Guru status/column names, TMB status/column names, fatores de realização TMB, cadência do lançamento (`launch_period`), padrões de campanha (`captacao_campaign_pattern`, `ml_campaign_keywords`), Meta account names, matched adsets/ads, guru API status mapping, guru export schema (82 cols → YAML separado), `fair_comparison.*`, `default_comparison_period`, `monitoring.decile_groups` |

---

Interface: `ClientConfig.from_yaml(path)` + `ClientConfig.validate()` com mensagens acionáveis.

> **`ClientConfig` é um arquivo vivo.** A cada novo cliente, a varredura pode revelar necessidades de parametrização que clientes anteriores não tinham — seja um campo novo em um sub-config existente ou um sub-config inteiro novo. Quando isso acontecer, atualizar o dataclass e o `client_template.yaml`. Todo campo novo deve ter um **valor default**, garantindo que os clientes já existentes continuem funcionando sem alterar seus YAMLs.

### 4.2 Módulo `src/core/`

Funções puras. Assinatura padrão: `transform(df, config: SubConfig, **artifacts) -> df`.

- **`utils.py`** — utilitários genéricos sem hardcodes: `normalizar_telefone_robusto`, `normalizar_email`, `limpar_texto`, `remove_columns(df, columns)`, `detect_problematic_columns(df)`, `clean_column_names(df)`, `UnionFind`
- **`ingestion.py`** — `filter_sheets`, `remove_duplicates_per_sheet`, `consolidate_datasets`, `filter_sales_by_product`, `aplicar_filtro_status_risco` (guarded por `ingestion.has_tmb`)
- **`column_unification.py`** — `unify_columns(df, merge_rules)`, `aplicar_filtro_temporal`
- **`category_unification.py`** — `unify_categories(df, config: CategoryConfig)`
- **`utm.py`** — `unify_utm(df, config: UTMConfig)` — versão canônica com `.lower()` corrigido
- **`medium.py`** — `unify_medium(df, config: MediumConfig)` — elimina os 3 arquivos atuais
- **`matching.py`** — `match_leads(df_leads, df_vendas, config: MatchingConfig)` — consolida os 6 arquivos atuais
- **`dataset_versioning.py`** — `criar_dataset_pos_cutoff`, `aplicar_janela_conversao` — só treino; requer todas as unificações anteriores
- **`feature_engineering.py`** — `create_features(df, config: FeatureConfig)` — guards de colunas unificados
- **`encoding.py`** — `apply_encoding(df, config: EncodingConfig, artifacts)` — versão produção é canônica
- **`preprocessing.py`** — orquestra a sequência canônica de pré-processamento: `remove_duplicates` → `clean_columns` → `remove_campaign_features` → `rename_long_column_names`; chama `utils.remove_columns` com as listas do config; treino e produção chamam `preprocess(df, config)` — sequência idêntica garantida por construção; monitoring chama a mesma função com wrapper de preservação de `decil`/`lead_score` em torno dela. **⚠️ RESTRIÇÃO CRÍTICA DE ORDEM:** remoção de colunas de score (`Pontuação`, `Score`, `Faixa A/B/C/D`, `lead_score`, `decil`) deve acontecer APÓS `criar_dataset_pos_cutoff` no pipeline de treino — essas colunas são o sinal implícito que o detector de cutoff usa para identificar "quando o modelo foi ao ar" (alta missing em lançamentos pré-modelo, baixa missing em lançamentos pós-modelo). Remover antes destrói o sinal e o cutoff regride para datas anteriores, inflando o dataset com dados irrelevantes. Em produção, a remoção pode ocorrer normalmente pois não há detecção de cutoff.

### 4.3 EDA → Config Generator (`src/eda/generate_client_config.py`)

> **Implementado na Fase 4** — após `devclub.yaml` e `clientb.yaml` serem escritos manualmente. Construir antes seria prematuro: o padrão real só fica claro depois de ter passado pelo processo manual duas vezes.

Script que analisa dados brutos do cliente e gera automaticamente a maior parte de `configs/clients/{client}.yaml`.

**Auto-gerado:**
- Lista e tipos de colunas
- Categorias únicas por coluna categórica
- Missing rates e distribuições
- Detecção de colunas email/telefone/identificador
- Taxa de conversão estimada
- Sugestões de unificação de colunas (similaridade de nome ou sobreposição de valores)
- Sugestões de unificação de categorias (`"SIM"` vs `"Sim"` vs `"sim"`)

**Requer input humano** (marcado como `null` no YAML gerado):
- Janela de conversão (conhecimento de negócio)
- Produto-alvo (se cliente vende múltiplos)
- Validação das colunas identificadoras detectadas
- Colunas a excluir do treino

### 4.4 NLP Module (`src/nlp/`) — Futuro

Para campos de texto livre em respostas de formulário (sentimento, intenção, nível de maturidade). Fora do escopo do sprint atual. O diretório é criado com README de interface. `FeatureConfig` já prevê o campo `nlp_columns: []`.

---

## 5. Regras de Sincronização por Pipeline

| Pipeline | Regra |
|---|---|
| `train_pipeline.py` | Importa 100% de `core/` para transformações; recebe `config: ClientConfig` |
| `production_pipeline.py` | Importa 100% de `core/`; comportamento idêntico ao treino por construção |
| `monitoring/orchestrator.py` | Chama `core.preprocessing.preprocess(df, config)` com wrapper de preservação de `decil`/`lead_score` em torno dela — mesma sequência canônica de treino e produção, garantindo ausência de training-serving skew |
| `retrain/retraining_orchestrator.py` | Passa `ClientConfig` para `train_pipeline.main()`; hook architecture preservada |
| `validation/` | Usa `core/` para carregamento de dados, busca de vendas e matching |

---

## 6. Varredura e Mapeamento de Hardcodes (Pré-requisito da Fase 1)

Varredura concluída — 153 hardcodes mapeados. Hardcodes #1–#89 (treino, produção, monitoring, retrain) extraídos para `configs/clients/devclub.yaml` — campos do YAML referenciam os números (#N) para rastreabilidade. Abaixo apenas os hardcodes pendentes para a Fase 3 (`api/` e `validation/`).

**`api/business_config.py` — arquivo inteiro é DevClub-specific:**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 90 | `api/business_config.py:10` | Valor médio do produto: `PRODUCT_VALUE = 1563.75` (ponderado Guru + TMB, atualizado 15/03/2026 — análise de inadimplência TMB com 5.608 pedidos: Guru R$1.973,95 × 42.3% + TMB R$1.262,86 × 57.7%) | `business.product_value` |
| 91 | `api/business_config.py:24-35` | Taxas de conversão por decil: `CONVERSION_RATES = {"D01": 0.002048, ..., "D10": 0.055973}` — calibradas para DevClub, modelo 2a98e51c (209 conv, 100% monotonia). **⚠️ Formato canônico dos decis é `"D01"`–`"D10"` (com zero à esquerda) — o modelo atual emite esse formato. Modelos antigos emitiam `"D1"`–`"D9"` (sem zero). O formato do dict DEVE casar com o output do modelo ativo; ao migrar para `CAPIConfig`, documentar o formato como obrigatório e validar no `ClientConfig.validate()`.** | `business.conversion_rates` |
| 92 | `api/business_config.py:50` | Threshold de gasto sem leads: `SPEND_THRESHOLD_ZERO_LEADS = 100.0` | `business.spend_threshold_zero_leads` |
| 93 | `api/business_config.py:54` | Mínimo de leads para dados suficientes: `MINIMUM_LEADS_THRESHOLD = 3` | `business.minimum_leads_threshold` |
| 94 | `api/business_config.py:62-67` | Thresholds de cor da coluna Ação (Google Sheets): `COLOR_THRESHOLDS = {"green_min": 30, "yellow_min": 1}` | `business.color_thresholds` |
| 95 | `api/business_config.py:76` | ROAS mínimo de segurança: `MIN_ROAS_SAFETY = 2.5` | `business.min_roas_safety` |
| 96 | `api/business_config.py:81` | Cap de variação máxima de budget: `CAP_VARIATION_MAX = 100.0` | `business.cap_variation_max` |
| 97 | `api/business_config.py:113-114` | Parâmetros da sigmoid de confiança: `CONFIDENCE_SIGMOID_L50 = 15.0` (ponto médio) e `CONFIDENCE_SIGMOID_K = 0.15` (inclinação) | `business.confidence_sigmoid_l50` + `business.confidence_sigmoid_k` |
| 98 | `api/business_config.py:131` | ROAS alvo para confiança máxima: `ROAS_TARGET = 8.0` | `business.roas_target` |

**`api/railway_mapping.py` — mapeamentos de formulário DevClub-specific:**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 99 | `api/railway_mapping.py:87-183` | Cinco dicionários de mapeamento de respostas do formulário Railway → formato do modelo: `MAPA_FAIXA_SALARIAL`, `MAPA_OCUPACAO`, `MAPA_IDADE`, `MAPA_INTERESSE_EVENTO`, `MAPA_ATRACAO_PROFISSAO` — todos com textos literais das perguntas DevClub | `api.railway_field_mappings` (um sub-dict por mapa) |
| 100 | `api/railway_mapping.py:219-275` | Nomes das colunas Sheets hardcoded na função `railway_lead_to_sheets_row`: `'O seu gênero:'`, `'Qual a sua idade?'`, `'O que você faz atualmente?'`, `'Atualmente, qual a sua faixa salarial?'` etc. — textos exatos das perguntas do formulário DevClub | `api.sheets_column_names` (mesmos que #13-#15, extender cobertura) |

**`api/bigquery_sync.py`:**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 101 | `api/bigquery_sync.py:15` | GCP Project ID como fallback: `os.getenv('GCP_PROJECT_ID', 'smart-ads-451319')` — projeto DevClub exposto | `infra.gcp_project_id` (env var já existe; remover fallback hardcoded) |
| 102 | `api/bigquery_sync.py:16-17` | Dataset e tabela BigQuery DevClub: `DATASET_ID = 'devclub'`, `TABLE_ID = 'leads_capi'` | `infra.bigquery_dataset_id` + `infra.bigquery_table_id` |

**`api/capi_integration.py`:**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 103 | `api/capi_integration.py:26` | Pixel ID como fallback hardcoded: `os.getenv('META_PIXEL_ID', '241752320666130')` — Pixel de produção DevClub exposto | `capi.pixel_id` (env var já existe; remover fallback hardcoded) |
| 104 | `api/capi_integration.py:366,591` | Nomes dos eventos CAPI: `'LeadQualified'` e `'LeadQualifiedHighQuality'` — convenção de nomenclatura DevClub usada em múltiplos lugares | `capi.event_name_with_value` + `capi.event_name_high_quality` |
| 105 | `api/capi_integration.py:514` | Decis da estratégia high quality: `if decil not in ['D09', 'D10']` — threshold cliente-specific. **Formato `"D09"`/`"D10"` (com zero) é o canônico — deve ser consistente com `CONVERSION_RATES` (#91) e com o output do modelo ativo.** | `capi.high_quality_decils` |
| 106 | `api/capi_integration.py:298,534,793` | País e moeda hardcoded: `country = 'br'`, `currency='BRL'` | `capi.country_code` + `capi.currency` |

**`api/meta_integration.py`:**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 107 | `api/meta_integration.py:570-578` | Prefixos de nomenclatura UTM DevClub na função `extract_adset_name_from_campaign_utm`: `'FASE '` e `'PG'` — estrutura de campanha específica DevClub (`DEVLF \| CAP \| FRIO \| FASE 01 \| ... \| PG2`) | `api.utm_campaign_structure.fase_prefix` + `api.utm_campaign_structure.page_prefix` |
| 108 | `api/meta_integration.py:409` | Nomes dos eventos CAPI na detecção de adsets: `['LeadQualified', 'LeadQualifiedHighQuality']` | resolvido por `capi.event_name_with_value` + `capi.event_name_high_quality` (mesmo que #104) |

**`api/app.py` — ✅ varrido (#109–#122):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 109 | `api/app.py:45-46` | UTM filter lists: `BARE_MEDIUM_NAMES = ['dgen', 'paid']`, `GENERIC_TERMS = ['fb', 'ig', 'instagram', 'facebook']` (complementa #8 que já mapeia `BARE_CAMPAIGN_NAMES`) | `api.bare_medium_names` + `api.generic_utm_terms` |
| 110 | `api/app.py:49-52` | `GOOGLE_SHEETS_URL` com fallback hardcoded para planilha DevClub: `os.getenv('GOOGLE_SHEETS_URL', 'https://docs.google.com/spreadsheets/d/1VYti8jX...')` | resolvido por `monitoring.sheets_url` (mesmo que #85) |
| 111 | `api/app.py:112-119` | CORS `allow_origins` com `'https://lp.devclub.com.br'` hardcoded — domínio do cliente | `api.cors_origins` |
| 112 | `api/app.py:216` | Nome do arquivo de mapeamento de features: `'feature_name_mapping_v1_devclub_rf_temporal_single.json'` — contém nome do cliente e versão do modelo | resolvido por `model.model_name_template` (mesmo que #53) — filename gerado a partir do template |
| 113 | `api/app.py:643-664,841-864` | Dict `column_mapping` com textos exatos das perguntas DevClub: `'genero': 'O seu gênero:'`, `'idade': 'Qual a sua idade?'` etc. — aparece em dois endpoints (`webhook_lead_capture` e `webhook_update_survey`) | resolvido por `api.sheets_column_names` (mesmo que #100) |
| 114 | `api/app.py:1619` | Tamanho do batch para processamento em lote: `BATCH_SIZE = 500` | `api.batch_processing_size` |
| 115 | `api/app.py:1790-1793` | Número default de dias para período 'Total' na análise UTM: `period_days = 30` | `api.default_analysis_period_days` |
| 116 | `api/app.py:1837,1866` | Nomes das fontes UTM principais: `'facebook-ads'` e `'google-ads'` — usados em filtragem de leads por source | `api.utm_main_sources` |
| 117 | `api/app.py:1892` | Lista de termos genéricos para excluir da análise de Term: `['fb', 'ig', 'instagram', 'facebook']` | resolvido por `api.generic_utm_terms` (mesmo que #109) |
| 118 | `api/app.py:2171` | Set de UTMs genéricos para excluir de análise de Medium: `GENERIC_UTMS = {'paid', 'dgen', 'facebook', 'instagram', 'meta', 'fb', 'ig', 'cpc'}` | `api.generic_utms_set` |
| 119 | `api/app.py:2897` | Fator multiplicador de eventos CAPI por lead: `1.3` — duplicata de `orchestrator.py:752` (#82) | resolvido por `monitoring.capi_events_per_lead_estimate` (mesmo que #82) |
| 120 | `api/app.py:3152,3285` | Nome do bucket GCS para relatórios de validação como fallback: `'bring-data-validation-reports'` | `infra.validation_bucket` |
| 121 | `api/app.py:3217-3220` | ⚠️ TEMPORÁRIO — datas de campanha hardcoded no endpoint `/validation/weekly`: `'2025-12-16'`, `'2026-01-12'` etc. — o próprio código tem TODO | remover — endpoint deve usar `PeriodCalculator` automaticamente |
| 122 | `api/app.py:3447` | Limite de leads por execução no polling Railway: `LIMIT 50` | `api.railway_polling_batch_size` |

**⚠️ Segurança (separado dos hardcodes de config):**
- `api/guru_config.py:13` — token Guru hardcoded diretamente no arquivo (`"user_token": "a0e3cf5b-..."`) — deve ir para env var `GURU_API_TOKEN`
- `api/meta_config.py:12` — access token Meta hardcoded no arquivo — deve ir para env var `META_ACCESS_TOKEN` (a env var já existe mas o token fica no arquivo como fallback comentado)

**Observações de qualidade (não hardcodes — corrigir separadamente):**
- `hyperparameter_tuning.py`: usa `print()` ao longo de todo o corpo em vez de `logger` — inconsistente com o restante do projeto

> **VARREDURA COMPLETA** — Train, produção, monitoring, retrain, api/ e validation/ inteiramente varridos. **153 hardcodes registrados** (+ dezenas de duplicatas documentadas). `validation/` 100% concluído: 15 arquivos varridos, 4 com zero hardcodes próprios (`matching.py`, `ml_monitoring_calculator.py`, `visualization.py`, `sheets_uploader.py`).

**`validation/` — hardcodes pendentes para Fase 3+:**

**`src/validation/validate_ml_performance.py` — ✅ varrido (#123–#127):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 123 | `validate_ml_performance.py:825` | Path default para dados de vendas: `'V2/data/devclub'` — contém nome do cliente | `validation.default_vendas_path` |
| 124 | `validate_ml_performance.py:902` | URL do Cloud Run como fallback de `INTERNAL_API_URL`: `'https://bring-data-api-12955519745.us-central1.run.app'` — URL específica do projeto DevClub | `infra.api_url` (env var `INTERNAL_API_URL` já existe; remover fallback hardcoded) |
| 125 | `validate_ml_performance.py:1933-1944` | Keywords de nomes de campanha DevClub na função `format_campaign_name`: `'MACHINE LEARNING'`, `'ESCALA SCORE'`, `'FAIXA A'`, `'FAIXA B'`, `'FAIXA C'` — estrutura de nomenclatura específica DevClub | `validation.campaign_type_keywords` |
| 126 | `validate_ml_performance.py:1951-1952` | Tipo e temperatura de campanha DevClub: `'CAP'`, `'RET'` (tipo) e `'FRIO'`, `'MORNO'` (temperatura) — convenção de nomenclatura DevClub | `validation.campaign_type_labels` + `validation.campaign_temp_labels` |
| 127 | `validate_ml_performance.py:633` | Taxa de tracking default: `0.5` (50%) — estimativa de cobertura de conversões para DevClub | `validation.default_tracking_rate` |

Duplicatas encontradas (resolução via campo já mapeado):
- `validate_ml_performance.py:1070`: `'Pedido'`, `'Parcela'`, `'Grau de risco'` → já coberto por #6 (`ingestion.tmb_detection_columns`)
- `validate_ml_performance.py:1616`: `model_metadata_v1_devclub_rf_temporal_leads_single.json` → já coberto por #53 (`model.model_name_template`)
- `validate_ml_performance.py:1408`: `source != 'facebook-ads'` → já coberto por #116 (`api.utm_main_sources`)
- `validate_ml_performance.py:1066,1120-1129`: `'guru'` e `'tmb'` como identificadores de fonte → resolução via `validation.sales_source_names` (grupo dos #6/#57)

| Arquivo | Módulo |
|---|---|
| `src/validation/validate_ml_performance.py` ✅ | validation |

**`src/validation/data_loader.py` — ✅ varrido (#128–#137):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 128 | `data_loader.py:67` | URL de backup do Google Sheets hardcoded: `BACKUP_SHEETS_URL = 'https://docs.google.com/spreadsheets/d/1OqNYA5z...'` (complementa #85/#110 que já cobrem a URL principal) | `monitoring.backup_sheets_url` |
| 129 | `data_loader.py:85` | Colunas obrigatórias do formulário DevClub: `required_columns = ['Data', 'E-mail', 'Campaign']` | resolves via `api.sheets_column_names` (mesmo que #100) |
| 130 | `data_loader.py:626,632,936,942` | Status de venda Guru: `'Aprovada'` e `'Cancelada'` — valores DevClub/Guru | `validation.guru_status_values` |
| 131 | `data_loader.py:641-675` | Colunas do export Guru: `'email contato'`, `'nome contato'`, `'telefone contato'`, `'valor venda'`, `'data aprovacao'`, `'data pedido'`, `'utm_campaign'` — estrutura do export Guru para DevClub | `validation.guru_column_names` |
| 132 | `data_loader.py:817,821,823` | Status TMB: `'Status Pedido'`/`'Status'` (coluna) e `'Efetivado'`/`'Cancelado'` (valores) | `validation.tmb_status_column` + `validation.tmb_status_values` |
| 133 | `data_loader.py:828-876` | Colunas TMB: `'Pedido'`, `'Cliente Email'`, `'Cliente E-mail'`, `'Cliente Nome'`, `'Cliente Telefone'`, `'Ticket (R$)'`, `'Data Efetivado'`, `'Criado Em'`, `'Grau de risco'` — estrutura do arquivo TMB DevClub | `validation.tmb_column_names` |
| 134 | `data_loader.py:700,1003` | Priority map para deduplicação de vendas Guru: `{'Aprovada': 1, 'Cancelada': 2}` — depende dos status values (#130) | resolves via `validation.guru_status_values` (mesmo que #130) |
| 135 | `data_loader.py:1110` | URL do Cloud Run como default do `CAPILeadDataLoader`: `"https://bring-data-api-12955519745.us-central1.run.app"` — duplicata de #124 no contexto de `__init__` | resolves via `infra.api_url` (mesmo que #124) |
| 136 | `data_loader.py:733` | `VALIDATION_REPORTS_BUCKET` fallback: `'bring-data-validation-reports'` | resolves via `infra.validation_bucket` (mesmo que #120) |
| 137 | `data_loader.py:734` | Path do blob TMB no GCS: `f'vendas/tmb_{report_type}.xlsx'` — convenção de nomenclatura do projeto | `validation.tmb_gcs_blob_prefix` |

**`src/validation/campaign_classifier.py` — ✅ varrido (#138–#139):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 138 | `campaign_classifier.py:7,103,115` | Padrão de identificação de campanha captação DevClub: `'DEVLF \| CAP \| FRIO'` / `'devlf \| cap \| frio'` — `DEVLF` = DevClub Lançamento; toda a lógica de `is_captacao_campaign()` depende deste padrão de nomenclatura | `validation.captacao_campaign_pattern` |
| 139 | `campaign_classifier.py:155` | Padrões de campanha COM_ML: `'machine learning'` e `'\| ml \|'` — identifica campanhas que usaram scoring ML pelo nome da campanha DevClub | `validation.ml_campaign_keywords` |

**Duplicatas observadas (já cobertas):**
- `campaign_classifier.py:361`: `'LeadQualified'` e `'LeadQualifiedHighQuality'` → resolves via `capi.event_name_with_value` + `capi.event_name_high_quality` (mesmo que #104)
- Labels internos `'COM_ML'`, `'SEM_ML'`, `'EXCLUIR'`, `'COM_CAPI'`, `'SEM_CAPI'` — vocabulário arquitetural genérico, não DevClub-specific

**`src/validation/metrics_calculator.py` — ✅ varrido (#140):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 140 | `metrics_calculator.py:125,216,247,568` | Evento CAPI `'Faixa A'` — terceiro evento Meta personalizado para DevClub (além de `'LeadQualified'` e `'LeadQualifiedHighQuality'` do #104), usado em `CUSTOM_EVENTS` e como coluna de contagem em `campaign_stats` | extends `capi.event_names` (mesmo grupo que #104) |

**Duplicatas observadas (já cobertas):**
- `metrics_calculator.py:23`: `from api.business_config import CONVERSION_RATES, PRODUCT_VALUE` → resolves via `ClientConfig` (mesmo que #90–#98)
- `metrics_calculator.py:122–126`: `'LeadQualified'`, `'LeadQualifiedHighQuality'` em `CUSTOM_EVENTS` → resolves via #104
- `metrics_calculator.py:1153`: `'OFFSITE_CONVERSIONS'` → constante da Meta API, não DevClub-specific

**Observação — artefato de debug a remover:**
- `metrics_calculator.py:177,585`: Campaign ID hardcoded `'120234062599950...'` — ajuste manual para uma campanha específica que teve bug de tracking. Não deve virar ClientConfig — deve ser removido na limpeza de código.

**`src/validation/report_generator.py` — ✅ varrido (#141–#142):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 141 | `report_generator.py:522,2175` | Mapeamento de Meta account IDs para nomes amigáveis: `{'act_188005769808959': 'Ads - Rodolfo Mori', 'act_786790755803474': 'Ads - Gestor de IA'}` — hardcoded em 2 lugares; IDs são das contas Meta do DevClub | `validation.meta_account_names` (dict account_id → display_name) |
| 142 | `report_generator.py:2782,2793` | Agrupamentos de decis hardcoded: `'Top 3 Decis (D8, D9, D10)'` e `'Top 5 Decis (D6-D10)'` — define quais faixas de decil são consideradas "top" para o monitoramento | `validation.monitoring.decile_groups` |

**Duplicatas / UI text observados (não registrar como config keys independentes):**
- `report_generator.py:368,515,727,1987,2108,2162,2703`: Títulos de abas em português (ex: `'PERFORMANCE GERAL - VALIDAÇÃO DE PERFORMANCE ML'`) — são UI labels que variam por cliente; devem ser agrupados em `validation.report_labels` ou tratados como template strings, não como hardcodes de lógica.
- `report_generator.py:730-741,1335`: Headers de colunas de tabela em português — mesma categoria: labels de exibição.

**`src/validation/period_calculator.py` — ✅ varrido (#143):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 143 | `period_calculator.py:50-52` | Duração dos períodos do lançamento DevClub: `LEAD_CAPTURE_DAYS = 7`, `CPL_ANALYSIS_DAYS = 6`, `SALES_PERIOD_DAYS = 7` — e início obrigatório às terças-feiras (`TUESDAY = 1`). Refletem a cadência semanal do lançamento DevClub. Outro cliente pode ter cadência totalmente diferente (ex: 30 dias contínuos sem CPL week). | `validation.launch_period.capture_days`, `validation.launch_period.cpl_days`, `validation.launch_period.sales_days`, `validation.launch_period.start_weekday` |

**`src/validation/meta_reports_loader.py` — ✅ varrido (#144):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 144 | `meta_reports_loader.py:1103,1135` | Datas do período de comparação hardcoded: `start_date='2025-11-18'`, `end_date='2025-12-01'` — presentes em dois métodos (`load_adsets_for_comparison` e `load_ads_for_comparison`). São datas fixas de um lançamento específico DevClub. | `validation.default_comparison_period.start` + `validation.default_comparison_period.end` |

**Duplicatas observadas (já cobertas):**
- `meta_reports_loader.py:370-372,486-488`: Meta account IDs `'188005769808959'`/`'786790755803474'` → resolves via `validation.meta_account_names` (mesmo que #141, 3ª ocorrência)
- `meta_reports_loader.py:977`: Campaign ID `'120234062599950'` → mesmo artefato de debug já anotado em metrics_calculator.py, a remover na limpeza de código

**`src/validation/ml_monitoring_calculator.py` — ✅ varrido:** Zero hardcodes próprios. Totalmente genérico — calcula AUC, concentração de conversões, lift usando apenas colunas normalizadas.

**`src/validation/fair_campaign_comparison.py` — ✅ varrido (#145–#148):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 145 | `fair_campaign_comparison.py:162-167` | Lista de adsets para comparação "justa": `['ABERTO \| AD0022', 'ABERTO \| AD0027', 'ADV \| Linguagem de programação', 'ADV \| Lookalike 1%...', 'ADV \| Lookalike 2%...']` — nomes de conjuntos de anúncios específicos do DevClub (padrão `ABERTO \| AD00XX`, referências a "DEV 2.0") | `validation.fair_comparison.matched_adsets` |
| 146 | `fair_campaign_comparison.py:173-175` | Lista de creative codes para comparação: `['AD0013', 'AD0014', 'AD0017', 'AD0018', 'AD0022', 'AD0027', 'AD0033']` — códigos internos de criativos DevClub | `validation.fair_comparison.matched_ads` |
| 147 | `fair_campaign_comparison.py:394,642` | Paths de arquivos de análise: `Path("files/validation/meta_reports/adsets_analysis/faixa")` e `Path("files/validation/meta_reports/adsets_analysis/eventos_ml")` — convenções de nomenclatura de diretório DevClub | `validation.fair_comparison.faixa_reports_path` + `validation.fair_comparison.eventos_ml_reports_path` |
| 148 | `fair_campaign_comparison.py:701-704,432,461` | Nomes de colunas do export CSV da Meta Ads: `'Nome da campanha'`, `'Identificação da campanha'`, `'Valor usado (BRL)'`, `'Nome do conjunto de anúncios'` — padrão da exportação Meta em português; podem variar por locale/configuração da conta | `validation.meta_export_column_names` |

**Duplicatas observadas (já cobertas):**
- `fair_campaign_comparison.py:100`: `'machine learning'` como keyword → resolves via #139
- `fair_campaign_comparison.py:106`: `'LeadQualified'`, `'LeadQualifiedHighQuality'` → resolves via #104
- `fair_campaign_comparison.py:2534-2543`: Meta account IDs → resolves via #141
- `fair_campaign_comparison.py:2550,2622`: `product_value = 2000.0` → resolves via #90 (PRODUCT_VALUE)

**`src/validation/sheets_uploader.py` — ✅ varrido:** Zero hardcodes próprios. Código genérico de upload Google Sheets via Drive API.

**`src/validation/tmb_adjuster.py` — ✅ varrido (#149):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 149 | `tmb_adjuster.py:15,19` | Fatores de realização TMB: `FATOR_TMB_REALISTA = 0.5605` (56.05% — baseado em 442 pedidos históricos) e `FATOR_TMB_CONSERVADOR = 0.6817` (68.17% — baseado em ticket médio R$1.500). `FATOR_TMB_MEDIO` é derivado dos dois. Refletem inadimplência histórica específica DevClub/TMB. | `validation.tmb_realization_factor_realistic` + `validation.tmb_realization_factor_conservative` |

**Duplicatas observadas (já cobertas):**
- `tmb_adjuster.py:51,155`: valores `'tmb'` / `'guru'` como sale_origin → resolves via #128–#137

**`src/validation/guru_sales_extractor.py` — ✅ varrido (#150–#152):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 150 | `guru_sales_extractor.py:14-15` | URLs base da API Guru: `"https://digitalmanager.guru/api/v2"` e endpoint `"/transactions"`. Específico da plataforma de pagamentos usada pelo DevClub. | `infra.guru_api_base_url` + `infra.guru_api_transactions_endpoint` |
| 151 | `guru_sales_extractor.py:336-344` | Mapeamento de status da API Guru para português: `{'approved': 'Aprovada', 'canceled': 'Cancelada', 'expired': 'Expirada', 'refunded': 'Reembolsada', 'chargeback': 'Reclamada', 'waiting_payment': 'Ag. Pagamento', 'scheduled': 'Agendada'}` — complementa #130 (status values) com o mapeamento API→display | `validation.guru_api_status_mapping` |
| 152 | `guru_sales_extractor.py:170-268` | Schema do export manual/API da Guru: ~82 colunas hardcoded em português (ex: `'id transação'`, `'nome marketplace'`, etc.) — estrutura completa do export Guru para DevClub | `validation.guru_export_schema` (→ YAML separado por volume) |

**`src/validation/capi_events_counter.py` — ✅ varrido (#153):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 153 | `capi_events_counter.py:66` | GCP Project ID hardcoded como default: `project_id = 'smart-ads-451319'` — identificador único do projeto GCP DevClub, essencial para queries Cloud Logging | `infra.gcp_project_id` |

**Duplicatas observadas (já cobertas):**
- `capi_events_counter.py:95`: `'LeadQualified enviado:'`, `'LeadQualifiedHighQuality enviado:'`, `'Faixa A enviado:'` em filtro de logs → resolves via #104 + #140

**`src/validation/visualization.py` — ✅ varrido:** Zero hardcodes próprios. Gera visualizações usando dados passados como parâmetros.

**`src/validation/meta_api_client.py` — ✅ varrido:** Hardcodes já cobertos: account ID `'act_188005769808959'` → #141; `'Faixa A'`/`'LeadQualified'`/`'LeadQualifiedHighQuality'` → #104/#140; `'CAP'` em filtro de nome de campanha → resolve via #138 (`captacao_campaign_pattern`).

**`src/validation/analyze_tmb_inadimplencia.py` — ✅ varrido:** Hardcodes já cobertos: `'Efetivado'`/`'Cancelado'` → #132; `product_value = 2200.40` → #90. Artefato `3497.53` (preço de cenário) não vai para ClientConfig — é cálculo pontual a remover.


**Hardcodes introduzidos pela branch `dev/tmb-dual-source` (2026-03-03) — TMB dual-source:**
| # | Localização atual | Hardcode | Campo sugerido |
|---|---|---|---|
| 154 | `ingestion.py` (novo bloco `is_tmb_pedidos`) | Colunas de detecção do arquivo TMB "pedidos" (relatório de alunos com telefone): `'ID do Pedido'`, `'E-mail do Cliente'`, `'Telefone do Cliente'` — complementa #6 (que documenta apenas o arquivo de parcelas `is_tmb_parcelas`) | `ingestion.tmb_pedidos_detection_columns` |
| 155 | `ingestion.py` (novo bloco `is_tmb_pedidos`) | Mapa de renomeação de colunas do arquivo TMB "pedidos" para formato canônico: `'ID do Pedido'→'Pedido'`, `'E-mail do Cliente'→'Cliente Email'`, `'Telefone do Cliente'→'Telefone'`, `'Nome do Produto'→'nome produto'`, `'Ticket do pedido'→'Ticket (R$)'` | `ingestion.tmb_pedidos_column_mapping` |
| 156 | `ingestion.py` (`is_tmb_pedidos` filter) | Critério de filtro do arquivo de pedidos TMB: `Situação != 'Cancelado'` (Vigente + Quitado = manter) — difere do arquivo de parcelas que usa `Status Pedido == 'Aprovada'` (#22) | `ingestion.tmb_pedidos_active_status_exclude` |

> **Comportamento novo em `consolidate_datasets`:** quando ambos os tipos TMB estão presentes, a função constrói um `tmb_risk_lookup` — dict `{email_normalizado → Grau de risco}` — a partir do arquivo de parcelas, e usa o arquivo de **pedidos** como `df_vendas` (tem email + telefone). O lookup é retornado como terceiro valor e aplicado **pós-matching** na Célula 15.1 do `train_pipeline.py`, demovendo para `target=0` os leads com risco fora do filtro configurado. O lookup é por **email** (não por `'Pedido'`) porque a coluna `'Pedido'` é removida na Célula 3 (`colunas_remover`) antes de `consolidate_datasets` ser chamada. O arquivo de parcelas é descartado após o lookup.
>
> **`filter_sheets`:** dados carregados via API (filename contém `'[API]'`) bypassam a heurística de contagem de colunas (`> 10`) para não serem filtrados indevidamente.
>
> **Ao migrar para `core/ingestion.py`:** comportamento dual-source controlado por `ingestion.has_tmb` (#12) + `ingestion.tmb_pedidos_detection_columns` (#154). **[dev/retreino — Célula 15.1 (filtro TMB pós-matching) REMOVIDA; `aplicar_filtro_status_risco` agora é chamada na Célula 5.3, pré-matching, sobre o df de vendas antes do join. A Célula 15.1 não existe mais como step separado em `train_pipeline.py`. `core/matching.py` continua sem conhecer risco TMB — a filtragem ocorre antes, em `core/ingestion.py` ou no step de column_unification.]**

**Arquivos confirmados como código morto — deletar no refactor:**
| Arquivo | Observação |
|---|---|
| `src/data_processing/column_unification.py` | ❌ CÓDIGO MORTO — o próprio docstring confirma que foi movido para `column_unification_refactored.py`; zero callers. Deletar. |
| `src/data_processing/devclub_filtering_training.py` | ❌ CÓDIGO MORTO — só importado por `tests/quantify_leakage.py`; pipeline principal usa filtragem DevClub dentro de `column_unification_refactored.py`. Deletar. |
| `src/features/utm_removal.py` | ❌ CÓDIGO MORTO — zero importers em todo o projeto; `train_pipeline.py` faz remoção de UTM inline. Deletar. |

**Critério de conclusão:** todos os arquivos percorridos, tabela acima atualizada com todos os hardcodes encontrados, nenhum valor específico de cliente sem mapeamento para uma chave de config.

---

## 7. Fases de Migração

### Fase 1 — Foundation (em andamento)

1. ~~**Executar varredura completa de hardcodes** (seção 6) e finalizar a tabela de mapeamento~~ ✅ — 153 hardcodes mapeados; sub-configs atualizados na seção 4.1
2. ~~**Criar estrutura base do `ClientConfig`**~~ ✅ — `src/core/client_config.py` com 13 sub-configs tipados; `from_yaml()` + `validate()` funcionais (commit c0d38ca)
3. ~~**Criar `configs/clients/devclub.yaml`**~~ ✅ — esqueleto com todas as chaves; cada campo referencia o número do hardcode; valores `null` preenchidos na Fase 2
4. ~~**Criar esqueleto de `src/core/`**~~ ✅ — 11 módulos com assinaturas e `NotImplementedError` (commit c0d38ca)
5. ~~**Criar `src/nlp/`** com README de interface~~ ✅
6. ~~**Audit de divergências treino × produção**~~ ✅ — executado em 2026-03-08 com `python -m V2.src.train_pipeline --capture-parity-snapshots --no-api-data`; comparação via `V2/tests/parity_audit.py`. Snapshots em `V2/tests/fixtures/`. Divergências encontradas e decisão canônica registrada abaixo.

**Resultado do audit — divergências e decisão canônica:**

| Função | Divergência | Impacto | Canônico | Ação em `core/` |
|---|---|---|---|---|
| UTM | `'utm_source'` não está em `source_to_outros` da produção | 1 lead (0.0%) | Treino | Incluir `'utm_source'` na lista `utm.source_to_outros` |
| Medium | `'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação'` → produção classifica como `'Outros'`, treino mantém como categoria válida | 44 leads (0.04%) | Treino | `core/medium.py` deve reconhecer esta variante como categoria válida |
| Feature Engineering | Produção cria `email_valido`, `nome_valido`, `telefone_valido` — removidas do treino em `dev/retreino` | 3 colunas a mais na produção | Treino | `core/feature_engineering.py` não deve criar essas 3 features; atualizar `engineering.py` de produção antes do merge |
| Feature Engineering | `telefone_comprimento`: produção retém valores inteiros 4 e 10, treino agrupa em `'outros'` | 1.835 leads (1.8%) | Treino | `core/feature_engineering.py` aplica grouping via `feature.telefone_comprimento_outros_values` (#157) |
| Encoding | Treino mantém nomes de colunas com caracteres especiais (`'Qual a sua idade?_18 24 anos'`); produção normaliza para snake_case via `clean_column_names()` (`'Qual_a_sua_idade'`) | Estrutural — 59 cols treino vs 50 produção | **Produção** | `core/encoding.py` aplica `clean_column_names()` após get_dummies — mesmo comportamento da produção |
| Encoding | Medium: treino gera one-hot dinâmico com nomes completos; produção usa nomes normalizados (binary_top3 foi removido do treino em `dev/retreino`) | Estrutural | **Produção** (nomes normalizados) | `core/encoding.py` normaliza nomes de colunas Medium junto com as demais |

> `configs/templates/client_template.yaml` e `src/eda/generate_client_config.py` são adiados: o template emerge do `devclub.yaml` ao final da Fase 2; o gerador de EDA é construído na Fase 4, depois de dois configs escritos manualmente.

**Critério de saída:** ✅ `src/core/` existe com assinaturas; ✅ `ClientConfig.from_yaml('configs/clients/devclub.yaml').validate()` passa; ✅ audit de divergências concluído — snapshots capturados, divergências documentadas e decisão canônica registrada para cada função compartilhada. **Fase 1 concluída.**

### Fase 2 — Consolidação (em andamento)

**Ciclo por componente** — para cada item abaixo, o loop é sempre o mesmo:
1. Implementar a função em `src/core/` parametrizada por config
2. Extrair os hardcodes desse componente para `configs/clients/devclub.yaml`
3. Atualizar imports nos pipelines afetados
4. Rodar shadow mode (velha e nova em paralelo, ao menos 1 ciclo de scoring em produção)
5. Validar paridade contra o snapshot da Fase 1 (ver §12)
6. **Validar integridade do pipeline de treino** — rodar treino completo com os mesmos argumentos do modelo de referência e confirmar que o AUC não regride além da margem de tolerância (ver critério abaixo)
7. Remover implementação antiga

**Protocolo obrigatório por componente** — ver §12 para instruções completas de `validate_parity_snapshots.py`.

> ⚠️ **CRITÉRIO DE APROVAÇÃO — DUAS CAMADAS OBRIGATÓRIAS:**
>
> **Camada 1:** `validate_parity_snapshots.py --validate` — 6 checkpoints bit-a-bit idênticos antes e depois da migração.
>
> **Camada 2:** `train_pipeline.py --initial-matching email_telefone --tmb-risk-filter all --api-end-date 2026-03-15 --hyperparams '{"n_estimators": 200, "max_features": "log2", "min_samples_leaf": 3, "min_samples_split": 2, "max_depth": 8}'` — AUC dentro de ±0.5% de 0.745 (referência `2a98e51c`). Usar `--tmb-risk-filter all`.
>
> Ambas obrigatórias — nenhuma substitui a outra.

**Componentes em ordem de criticidade:**

1. ~~`core/utm.py`~~ ✅ **ATIVO em `train_pipeline.py`** (18/03/2026)
   - Substitui `unificar_utm_source_term` + `verificar_consistencia_utm` de `utm_training.py`
   - Validado: `validate_parity_snapshots.py --validate` — todos 6 snapshots ✅
   - Hardcodes #35, #63, #67 → `configs/clients/devclub.yaml`

2. ~~`core/feature_engineering.py`~~ ✅ **ATIVO em `train_pipeline.py`** (18/03/2026)
   - Substitui `criar_features_derivadas` de `features/feature_engineering_training.py`
   - Validado: todos 6 snapshots ✅ — `fe_input` row count preservado (49.214)
   - Hardcodes #47, #48 → `configs/clients/devclub.yaml`
   - `production_pipeline.py`: migração pendente (item 3a-1 da Fase 3); `monitoring/orchestrator.py`: já usa `core/` ✅

3. ~~`core/medium.py`~~ ✅ **ATIVO em `train_pipeline.py`** (18/03/2026)
   - Substitui `extrair_publico_medium` + `unificar_medium_para_producao` (dois arquivos)
   - `valid_categories: null` = modo treino (frequency threshold 2.5%)
   - Validado: todos 6 snapshots ✅ — distribuição Medium preservada
   - Hardcodes #7, #36, #37 → `configs/clients/devclub.yaml`
   - `production_pipeline.py`: migração pendente (item 3a-1 da Fase 3); `monitoring/orchestrator.py`: já usa `core/` ✅

4. ~~`core/encoding.py`~~ ✅ **ATIVO em `train_pipeline.py` + `production_pipeline.py`** (18/03/2026)
   - Substitui `aplicar_encoding_estrategico` (encoding_training.py) e `apply_categorical_encoding` (features/encoding.py)
   - Confirmado: modelos já treinados desde ~15/03 já tinham nomes normalizados no feature
     registry — retreino não necessário. `core/encoding.py` produz 59 features idênticas ao
     modelo de produção 2a98e51c (match programático confirmado).
   - `column_name_corrections` em devclub.yaml limpo (era patch transitório, obsoleto)
   - Hardcodes #49, #50, #51, #64, #70, #71 → `configs/clients/devclub.yaml`

5. `core/preprocessing.py` (Célula 8) — **DECISÃO: NÃO MIGRAR CÉLULA 8**
   - `feature_removal.py` permanece em Célula 8. Motivo: remove `Campaign`/`Content` mas
     **preserva colunas de score** (`Pontuação`, `Score`, `Faixa A/B/C/D`) até a Célula 13.
     `core/preprocessing.py` → `preprocess()` remove score columns — isso destrói o sinal
     de cutoff do detector de feature missing (ver §12 — incidente Componente 5).
   - `feature_removal.py` é lógica exclusiva do treino (timing constraint). Não é lógica
     compartilhada → não pertence a `core/`.
   - `core/preprocessing.py` → `preprocess()` é para produção e monitoramento (onde não
     há detecção de cutoff). `preprocess_for_monitoring()` já ativo em `monitoring/orchestrator.py`.

6. ~~`core/category_unification.py`~~ ✅ **ATIVO em `train_pipeline.py`** (19/03/2026)
   - Já era compartilhado entre treino/produção/monitoring; hardcodes #27–#33 → `CategoryConfig`
   - Validado: `validate_parity_snapshots.py --validate` — todos 6 snapshots ✅
   - Camada 2: AUC 0.747 (run `ffc20588`, 19/03/2026) ✅ — dentro de ±0.5% do baseline 0.745
   - `production_pipeline.py`: migração pendente (item 3a-1 da Fase 3); `monitoring/orchestrator.py`: já usa `core/` ✅

7. ~~`core/column_unification.py`~~ ✅ **ATIVO em `train_pipeline.py`** (19/03/2026)
   - Substitui `unificar_colunas_pesquisa` + `unificar_colunas_vendas` + `aplicar_filtro_temporal` de `column_unification_refactored.py`
   - Validado: todos 6 snapshots ✅
   - Camada 2: AUC 0.747 (run `ffc20588`, 19/03/2026) ✅
   - Hardcodes #13–#22 → `configs/clients/devclub.yaml`

8. ~~`core/matching.py`~~ ✅ **ATIVO em `train_pipeline.py`** (19/03/2026)
   - Consolida 6 arquivos `src/matching/` em função única `match_leads()`
   - Validado: todos 6 snapshots ✅ — `fe_input` row count e `target` distribution preservados
   - Camada 2: AUC 0.747 (run `ffc20588`, 19/03/2026) ✅
   - Hardcodes #41–#46 → `configs/clients/devclub.yaml`

9. ~~`core/dataset_versioning.py`~~ ✅ **ATIVO em `train_pipeline.py`** (19/03/2026)
   - Substitui `criar_dataset_pos_cutoff` + `aplicar_janela_conversao`
   - Janela de conversão simétrica implementada (remove TODOS os leads após `date_limite`)
   - Validado: todos 6 snapshots ✅
   - Camada 2: AUC 0.747 (run `ffc20588`, 19/03/2026) ✅
   - Hardcodes #38, #39, #40 → `configs/clients/devclub.yaml`

10. ~~`core/ingestion.py`~~ ✅ **ATIVO em `train_pipeline.py`** (19/03/2026)
    - Substitui `filter_sheets`, `remove_duplicates_per_sheet`, `consolidate_datasets`, `filter_sales_by_product`, `aplicar_filtro_status_risco`
    - Validado: todos 6 snapshots ✅
    - Camada 2: AUC 0.747 (run `ffc20588`, 19/03/2026) ✅
    - Hardcodes #6, #8, #11, #12, #22–#25 → `configs/clients/devclub.yaml`

11. `validation/` — atualizar onde há reimplementação paralela

~~12. `configs/clients/devclub.yaml` completamente preenchido~~ ✅ **VALIDADO** (19/03/2026)
    - Todos os hardcodes #6–#89 populados com valores reais do código-fonte
    - Campos null restantes são intencionais:
      - `dataset_cutoff_date: null` — MANTER NULL: o valor "2025-03-01" do hardcode original era um
        mínimo na lógica antiga; em `core/dataset_versioning.py` valor não-null substitui a
        auto-detecção completamente → 168k rows vs 49k esperados. Detectado e corrigido na validação.
      - `infra.*`, `capi.*` — env vars (nunca hardcodar)
      - `monitoring.*` (maioria), `api.*` — componentes não migrados para core/
      - `feature.ordering_rules` — lógica de código (reordenação por sufixo numérico)
    - Escopo da validação: campos lidos pelo train_pipeline confirmados pelas duas camadas.
      Campos de `model.*`, `retrain.*` preenchidos por inspeção (valores extraídos do código-fonte);
      cobertura de execução virá quando esses componentes forem conectados ao ClientConfig.
    - Camada 1: `validate_parity_snapshots.py --validate` — 6/6 ✅
    - Camada 2: AUC 0.747 (run `a36989d6`, 19/03/2026) ✅ — dentro de ±0.5% de 0.745

~~13. `configs/active_model.yaml` → `configs/active_models/devclub.yaml`~~ ✅ **VALIDADO** (19/03/2026)
    - Arquivo renomeado e movido
    - 6 referências funcionais atualizadas: prediction.py, training_model.py, data_validation.py,
      data_loader.py, medium_production_training.py, run_monitoring_local.sh
    - Todos com `# TODO multi-client: derivar client_id do ClientConfig`
    - Incluído na validação de duas camadas do item 12 ✅

~~14. `configs/templates/client_template.yaml` gerado~~ ✅ (19/03/2026)
    - Template funcional com REQUIRED/OPTIONAL/ENV VAR para cada campo
    - Derivado do devclub.yaml completo — sem valores DevClub-específicos
    - Cobre todos os 13 sub-configs

~~15. `monitoring/orchestrator.py` migrado para `core/`~~ ✅ **JÁ ESTAVA COMPLETO** (verificado 19/03/2026)
    - `ClientConfig` injetado via `__init__`, fallback para `configs/clients/devclub.yaml`
    - Sequência canônica: `core.utm` → `core.medium` → `core.category_unification` → `core.preprocessing.preprocess_for_monitoring` → `core.feature_engineering`
    - Nenhum import de componentes antigos (`data_processing/`, `matching/`) — migração estava completa antes desta sessão

**Critério de saída Fase 2 — o que foi resolvido:** ✅ **CAMADA DE TRANSFORMAÇÃO DE DADOS CONCLUÍDA** (19/03/2026)
- `core/` com 11 módulos; treino, produção e monitoramento aplicam a mesma sequência canônica ✅
- `configs/clients/devclub.yaml` completamente preenchido e validado (Camada 1 + Camada 2) ✅
- `configs/templates/client_template.yaml` gerado ✅
- `monitoring/orchestrator.py` usando sequência canônica idêntica aos demais pipelines ✅

**O que a Fase 2 NÃO resolveu (e bloqueia o critério da Fase 3):**

A Fase 2 focou na camada de transformação de dados — e a resolveu completamente. Mas o critério de saída da Fase 3 ("sem alterar código, apenas config") requer também que as camadas de orquestração e API leiam do ClientConfig. Elas ainda não leem:

| Camada | Status | Impacto para Cliente B |
|---|---|---|
| **Orquestração de treino** | `training_model.py` — nome do modelo, experimento MLflow, path `active_models/` hardcoded "devclub" (#10, #53, #54, #55, #72, #89) | Modelo de Client B seria nomeado `v1_devclub_rf_...` e registrado no experimento "devclub_lead_scoring" |
| **Orquestração de produção** | `prediction.py` — carrega `active_models/devclub.yaml` (#54; TODO multi-client colocado mas não resolvido) | Client B serviria predições com modelo DevClub |
| **Retrain** | `retraining_orchestrator.py` — path TMB, thresholds quality gate, padrão metadata (#87–#89) | Retreino de Client B procuraria arquivos TMB DevClub |
| **Monitoring config** | `monitoring/config.py` — THRESHOLDS e MISSING_RATE_IGNORE_COLUMNS hardcoded (#83, #84) | Client B seria monitorado com thresholds e lista de colunas do DevClub |
| **API** | `app.py`, `capi_integration.py`, `business_config.py`, `railway_mapping.py` (#90–#122) | CAPI enviaria para Pixel DevClub; CORS rejeitaria domínio Client B; taxas de conversão erradas |

**Pendente — validação do monitoramento (golden snapshot):**

O protocolo de duas camadas foi aplicado ao `train_pipeline.py`. O `monitoring/orchestrator.py` ainda não tem validação equivalente. A forma concreta de fechar esta lacuna é o **golden snapshot**:

- **O que é:** rodar `MonitoringOrchestrator.run_daily_check(reference_date=date(2026, 3, 15), dry_run=True)` com data fixa e salvar o output (contagem e tipos de alertas) em `docs/monitoring_golden_snapshot.json`.
- **Quando capturar:** **antes do merge do PR** — com o código atual, para ter a referência pré-refactor.
- **Quando comparar:** imediatamente após o deploy, ainda sem tráfego (Etapa 4D do `CHECKLIST_DEPLOY_REFACTOR.md`). Qualquer divergência na contagem ou tipo de alertas indica regressão no path de monitoramento.
- **Uso contínuo:** sempre que houver mudança em `core/preprocessing.py` ou `core/feature_engineering.py`, rodar novamente e comparar com o golden. Se divergir, investigar antes de deployar.

**Condição para bloquear:** (a) qualquer mudança em `core/preprocessing.py` ou `core/feature_engineering.py` que afete o path de monitoramento; (b) onboarding de Cliente B com monitoramento ativo — nesse momento o golden deve existir para devclub e será criado um novo para clientb.

**⚠️ Segurança — não deveria esperar uma fase de refatoração:**
- `api/guru_config.py` — Guru API token hardcoded no arquivo (flag #guru_config)
- `api/meta_config.py` — Meta access token no arquivo, mesmo que env var exista
Ação: mover para env vars `GURU_API_TOKEN` e `META_ACCESS_TOKEN`, remover fallback hardcoded do arquivo.

---

### Checklist pós-retreino (antes de subir para produção)

Quando o próximo retreino for executado com os componentes `core/` já migrados, os seguintes passos devem ser feitos **antes** de atualizar `production_pipeline.py`:

1. **Verificar feature registry do novo modelo** — confirmar que os nomes das features estão em snake_case normalizado (sem `ã`, `ç`, `?`). Isso confirma que `core/encoding.py` foi usado no treino.

2. **Atualizar imports em `production_pipeline.py`:**
   - `from .features.engineering import ...` → `from .core.feature_engineering import create_features`
   - `from .features.encoding import apply_categorical_encoding` → `from .core.encoding import apply_encoding`
   - (e demais componentes já migrados no momento)

3. **Limpar `encoding.column_name_corrections` em `devclub.yaml`** — esvaziar o dict `{}`. As correções existem apenas para o modelo atual (treinado com nomes históricos); o novo modelo não precisa delas.

4. **Remover aliases curtos de `encoding.ordinal_variables`** — após `category_unification` migrado, as chaves `"idade"` e `"faixa_salarial"` podem ser removidas; manter apenas as formas longas.

5. **Rodar parity audit completo** (`python V2/tests/parity_audit.py --function all`) contra dados reais de produção antes de liberar o deploy.

6. **Confirmar que `nome_valido`, `email_valido`, `telefone_valido` NÃO aparecem** no feature registry do novo modelo — essas features foram removidas no `dev/retreino` e `core/feature_engineering.py` não as cria.

| Camada | O que verifica |
> |---|---|
> | Parity snapshots | Implementação idêntica, isolada por checkpoint |
> | Treino completo (Camada 2) | Pipeline ponta a ponta com dados reais, AUC preservado |
> | Shadow mode (produção) | Nova `core/` não quebra com dados em tempo real — mínimo 1 ciclo antes de remover implementação antiga |

---

## Modelo de referência (baseline vigente)

Run `2a98e51c` — AUC 0.7450, monotonia 100%, tmb_risk_filter=all, 59 features, cutoff 2025-11-04, 48.812 registros. Usado como baseline para validação das Fases 1–2. Ver `memory/project_active_model.md` para metadados completos.

> Modelos A e B (07/03/2026) foram referência intermediária durante a migração de `core/encoding.py`. Supersedidos pelo run `a36989d6` (19/03/2026, AUC 0.747) após conclusão da Fase 2. Não são mais referência ativa.

---

### Fase 3 — Multi-cliente end-to-end

O critério real desta fase é: **pipeline completo (treino → produção → monitoramento → retreino) roda para Cliente B sem alterar código, apenas adicionando `configs/clients/clientb.yaml`**. Para chegar lá, a fase tem três sub-fases obrigatórias nesta ordem.

#### 3a — Conectar camada de orquestração ao ClientConfig ✅ CONCLUÍDO (20/03/2026)

*Nenhum destes itens requer mudança em `core/`. São conexões de leitura de config em componentes que já existem.*

1. ~~**`training_model.py`**~~ ✅ — `model.mlflow_experiment_name` e `model.model_name_template` lidos do ClientConfig; MLflow experiment setup movido do módulo para dentro da função; `active_models/{client_id}.yaml` dinâmico. Hardcodes #10, #53, #71 resolvidos.
2. ~~**`prediction.py`**~~ ✅ — `client_id` derivado do ClientConfig para `active_models/{client_id}.yaml`; `legacy_model_dir` do `ModelConfig`. TODO multi-client removidos.
3. ~~**`monitoring/config.py`**~~ ✅ — `DataQualityMonitor`, `OperationalMonitor` e `CAPIQualityMonitor` resolvem thresholds no `__init__` a partir de `MonitoringConfig.thresholds` e `MonitoringConfig.missing_rate_ignore_columns`; fallback para constantes de `config.py`. Hardcodes #83, #84 resolvidos.
4. ~~**`retraining_orchestrator.py`**~~ ✅ — carrega `ClientConfig` no `__init__`; TMB path derivado de `client_id`; quality gate thresholds de `MonitoringConfig.thresholds`; `get_active_model_path()` aceita `client_id`. Hardcodes #87–#89 resolvidos.
5. ~~**Código morto confirmado**~~ — `column_unification.py`, `devclub_filtering_training.py`, `utm_removal.py` não existem no repositório (já deletados anteriormente).

**Adicionalmente resolvidos na 3a:**
- `train_pipeline.py` — comparação pós-treino lê `model.mlflow_experiment_name` do ClientConfig
- `monitoring/data_quality.py` — `_check_missing_features` e `_check_extra_features` usam `core.encoding` (não mais `features.encoding` antigo) e `LeadScoringPredictor` via `client_id`
- `monitoring/orchestrator.py` — passa `client_config` para todos os 3 sub-monitores

**Validação da camada de orquestração — ✅ COMPLETA (20/03/2026):**
- **Camada 1 (smoke tests):** imports + instanciação com ClientConfig devclub — zero erros ✅
- **Camada 2 (parity checks 2a–2f):** 6/6 PASS via `scripts/validate_orchestration_layer.py` ✅
  - 2e: `_thresholds is THRESHOLDS` para DataQualityMonitor, OperationalMonitor, CAPIQualityMonitor ✅
  - 2f: `experiment_name='devclub_lead_scoring'`, `model_name='v1_devclub_rf_temporal_single'` ✅
  - 2d: `get_active_model_path() == get_active_model_path('devclub') = 'files/20251111_212345'` ✅
  - 2a: `mlflow_run_id='2a98e51c...'`; 59 features idênticas com/sem client_config ✅
  - 2b: predições idênticas em 10 amostras sintéticas (diferença < 1e-10) ✅
  - 2c: 5.422 leads reais do Sheets → 7 alertas `missing_rate_high` idênticos com/sem client_config ✅
- **Treino de confirmação** run `f3e816b6` (`--api-end-date 2026-03-15`): AUC 0.747, 49.214 registros, 777 positivos — idêntico ao baseline Fase 2 (±0.5% do modelo em produção 0.745) ✅

#### Pré-condições obrigatórias antes de iniciar 3b/3c

> Estas tarefas devem ser concluídas **antes** do onboarding de Cliente B. São independentes dos dados do cliente e devem ser feitas durante o período de espera pelo material.

~~**P1 — Credenciais hardcoded → env vars**~~ ✅ — `guru_config.py` e `meta_config.py` leem 100% de env vars; sem fallback hardcoded.

~~**P2 — Patch `production_pipeline.py` linha 103**~~ ✅ — `_config_path` usa `{client_id}` dinamicamente; `client_id='devclub'` é apenas o default do parâmetro Python, não hardcode no path.

#### 3b — Onboarding Cliente B

> **Execução:** ver `ROADMAP_MLOPS_MATURIDADE.md` item 11 — é a fonte de verdade para o que fazer. O contexto abaixo é histórico.

> **Atenção ao preencher o template:**
> - `monitoring.conversion_window_days`: não copiar 20 do DevClub. Calcular como `captacao_days + cpl_days + vendas_days` do ciclo real de Cliente B.
> - `business.conversion_rates`: o formato das chaves **deve ser** `"D01"`, `"D02"` ... `"D10"` (zero à esquerda). O valor enviado ao Meta é calculado em runtime como `product_value × conversion_rates[decil]` — sem zero à esquerda, o lookup retorna 0.0 silenciosamente.
> - `mlflow_experiment_id`: campo DEPRECATED — experiment_id é derivado em runtime via `mlflow.get_run()`. Não precisa preencher.

#### 3c — API multi-cliente ✅ CONCLUÍDA (22/03/2026)

~~10. **`api/capi_integration.py`**~~ ✅ — Pixel ID, event names, high_quality_decils (#103–#106) lidos de `CAPIConfig`.
~~11. **`api/app.py`**~~ ✅ — CORS origins, column_mapping, batch sizes, UTM filters (#109–#116) lidos do ClientConfig. `analyze_utms_with_costs` removido (código morto).
~~12. **`api/business_config.py`**~~ ✅ — `decil_to_value` pré-computado em `CAPIConfig`; write-back do treino atualiza também o YAML.
~~13. **`api/railway_mapping.py`**~~ ✅ — mapeamentos de formulário (#99–#100) lidos do ClientConfig.

~~14. **`api/capi_integration.py`**~~ ✅ RESOLVIDO (22/03/2026) — DT-5: cálculo em runtime.
~~15. **`api/app.py:255`**~~ ✅ RESOLVIDO (22/03/2026) — derivado de `metadata.model_info.model_name`.
~~16. **`src/validation/metrics_calculator.py`**~~ ✅ RESOLVIDO (22/03/2026) — `DecileMetricsCalculator` aceita `conversion_rates` como parâmetro.
~~17. **`api/deploy_capi.sh`**~~ ✅ RESOLVIDO (22/03/2026) — DT-6: lê de `configs/clients/{CLIENT_ID}.yaml`.
~~18. **Merge com main**~~ ✅ — main já incorporado em merge anterior (`d57db08`); zero commits pendentes.

~~**19. Deploy do refactor para produção**~~ ✅ CONCLUÍDO (26/03/2026)

`CHECKLIST_DEPLOY_REFACTOR.md` executado. A/B test ativo: jan30 (Champion, `d51757f5`) vs mar24 (Challenger, `a859c68b`), roteamento por `utm_campaign`. Golden snapshot do monitoring: não capturado antes do deploy (lacuna — cobrir na próxima mudança estrutural em `core/`). Commit de configuração: `73e371b`.

*Critério de saída Fase 3:* pipeline completo roda para Cliente B sem alterar código. Modelo nomeado, registrado, servido e monitorado com identidade "clientb".

#### Limpeza de código morto

| Arquivo | Status | Substituído por |
|---|---|---|
| `src/data_processing/medium_training.py` | ✅ Deletado (22/03/2026) | `core/medium.py` |
| `src/data_processing/medium_unification.py` | ✅ Deletado (22/03/2026) | `core/medium.py` |
| `src/data_processing/medium_production_training.py` | ✅ Deletado (22/03/2026) | `core/medium.py` |
| `src/data_processing/utm_training.py` | ✅ Deletado (22/03/2026) | `core/utm.py` |
| `src/features/feature_engineering_training.py` | ✅ Deletado (22/03/2026) | `core/feature_engineering.py` |
| `src/features/encoding_training.py` | ✅ Deletado (22/03/2026) | `core/encoding.py` |
| `src/matching/` (6 arquivos) | ✅ Deletado (22/03/2026) | `core/matching.py` |

---

### Divergências residuais — Auditoria 30/03/2026

Auditoria sistemática após o deploy revelou que o critério "Fase 2 concluída" garantiu que `core/` está correto, mas não que todos os pipelines usam os mesmos contratos com `core/`. As divergências abaixo não estão na camada `core/` — estão nas pontas (train, produção, monitoramento) que chamam `core/` de forma inconsistente.

**Estado geral:** `core/` está correto. Os pipelines chegam lá mas com contratos diferentes. O resultado é que o sistema funciona para DevClub (o modelo compensa silenciosamente), mas quebra para Cliente B ou após retreino com alteração de features.

#### Pré-condições obrigatórias antes de Fase 3b (ordem de execução)

| # | Divergência | Criticidade | Arquivo | Ação |
|---|---|---|---|---|
| **R1** | **REVISTO 2026-04-21:** `production_pipeline.py` cria `nome_valido`, `email_valido`, `telefone_valido`. A descrição original dizia "remover pois o modelo nunca viu" — isso era errado. O Champion (jan30, ATIVO) tem 6 features dependentes dessas (`nome_valido_True/False`, `email_valido_True/False`, `telefone_valido_True/False`) no seu feature registry. Remover cegaria o Champion em ~11% do input. A ação correta é PORTAR a criação dessas features para `src/core/feature_engineering.py` na unificação Fase 3 do `PLANO_EXECUCAO.md`. Só depois de retreinar o Champion sem essas features, pode-se removê-las. | **ALTO** | `src/core/feature_engineering.py`, `src/production_pipeline.py` | Portar criação das 3 features para `core/feature_engineering.py`. Depois de retreinar Champion sem elas (se desejado), remover do production_pipeline. → DT-8 |
| **R2** | `PESOS_COMPRADOR` e `DEFAULT_HYPERPARAMS` hardcoded em `train_pipeline.py` — valores já existem em `devclub.yaml` (`model.buyer_weights`, `model.hyperparameters`), mas o treino reimplementa inline. Para Cliente B, o treino usará pesos do DevClub sem nenhum erro. | **MÉDIO** | `src/train_pipeline.py:~763,~788` | Substituir por `client_config.model.buyer_weights` e `client_config.model.hyperparameters`. Rodar Camada 2 (AUC ±0.5%) para confirmar. → DT-10 |
| ~~**R3**~~ | ~~Encoding ordinal — verificar se `'idade'`/`'faixa_salarial'` ainda existem como chaves em `devclub.yaml > encoding.ordinal_variables`.~~ ✅ **RESOLVIDO 2026-04-21** — Confirmado via inspeção: config atual (`configs/clients/devclub.yaml`) usa apenas os nomes longos `"Qual a sua idade?"` e `"Atualmente, qual a sua faixa salarial?"`. Não há mais aliases curtos. | — | — | Fechado |
| **R4** | `medium.unify_medium` tem condicional em `train_pipeline.py` (`if 'Medium' in df.columns: ...`) que não existe em produção — produção sempre chama a função. Se Medium desaparecer do formulário no futuro, produção quebrará enquanto treino continuaria silenciosamente. | **BAIXO** | `src/train_pipeline.py:~619`, `src/production_pipeline.py` | Alinhar comportamento: produção deve ter o mesmo guard ou `core/medium.py` deve absorver o caso de coluna ausente. |
| **R5** | Imports de `core/` em `monitoring/orchestrator.py` estão dentro do método `run_daily_check()` em vez do topo do módulo. Funcional, inconsistente. | **BAIXO** | `src/monitoring/orchestrator.py` | Mover imports para o topo. → DT-11 |

> **R1 (revisto) é pré-requisito da unificação Fase 3** — sem portar essas features para main, Champion perde sinal quando servido pela pipeline refatorada. R2 bloqueia o critério multi-cliente. R3 está resolvido. R4 e R5 são limpeza antes de escalar.

#### O que foi resolvido na auditoria (30/03/2026)

- ~~**`monitoring/data_quality.py` sem `artifacts`**~~ ✅ — `_check_missing_features` e `_check_extra_features` agora criam o `LeadScoringPredictor` antes do encoding, extraem `mlflow_run_id` e passam como `artifacts` para `apply_encoding`. Step 7 (feature registry alignment) executa em monitoramento — mesmo contrato que produção. Eliminado falso-positivo de 12 features faltantes. Commit `d519ee6`. → DT resolvido sem número formal.

---

### Fase 4 — EDA Generator (após Cliente B estável)

> **Execução:** ver `ROADMAP_MLOPS_MATURIDADE.md` item 12 — é a fonte de verdade para o que fazer. O contexto abaixo é histórico.

Com dois configs escritos manualmente (`devclub.yaml` e `clientb.yaml`), o padrão está claro o suficiente para automatizá-lo:

- Construir `src/eda/generate_client_config.py`
- Validar rodando sobre o dataset DevClub e comparando output com `devclub.yaml` existente
- Usar para onboarding de clientes seguintes

### Fase 5 — NLP (Futuro, sem data)

- Definir interface final de `src/nlp/`
- Implementar extração de features de texto
- Registrar como step opcional no `FeatureConfig`

---

---

## 10. Componentes Compartilhados (Referência)

> Esta seção documentava o estado pré-refactor. Após a Fase 2, todos os componentes de transformação de dados migraram para `core/`. A lista abaixo mantém apenas o que não é `core/` e permanece compartilhado.

| Componente | Usado por |
|---|---|
| `monitoring/data_quality.py` | Treino (captura de snapshots) + monitoramento (check diário) |
| `model/decil_thresholds.py` | Produção + monitoramento |
| Hook architecture (retrain) | Retrain orchestrator |

**Arquivos em `validation/` já prontos para multi-cliente** (zero hardcodes próprios, confirmado na varredura):

| Arquivo | Situação |
|---|---|
| `validation/matching.py` | Usa apenas colunas normalizadas (`email`, `telefone`, `data_captura`) — sem lógica DevClub-specific |
| `validation/ml_monitoring_calculator.py` | Calcula AUC, lift e concentração de conversões — totalmente genérico |
| `validation/visualization.py` | Gera gráficos recebendo DataFrames como parâmetros — sem hardcodes |
| `validation/sheets_uploader.py` | Upload genérico via Drive API — sem hardcodes |

---

## 11. Dívida Técnica Conhecida

Itens identificados na revisão de 20/03/2026 que **não bloqueiam** Fase 3b/3c mas devem ser endereçados antes de escalar para 3+ clientes.

### ~~DT-1 — `mlflow_experiment_id: "1"` é frágil~~ ✅ RESOLVIDO (22/03/2026)

`core/encoding.py`, `core/medium.py`, `src/model/prediction.py` e `src/validation/data_loader.py` agora derivam o experiment_id em runtime via `mlflow.get_run(run_id).info.experiment_id`, com fallback para o valor do YAML apenas em caso de falha. `mlflow_experiment_id` no YAML e dataclass marcado como DEPRECATED.

### Ausência de testes unitários em `src/core/`

Toda validação atual é integration test (pipeline de treino ponta a ponta, ~10–20 minutos). Não há testes unitários isolados para `core/utm.py`, `core/medium.py`, `core/encoding.py`. Com dois clientes, qualquer mudança em `core/` requererá validação para ambos — sem testes unitários, isso é um pipeline completo por cliente.

**Fix:** escrever testes parametrizados por `ClientConfig` para as funções de `core/` com maior superfície de mudança (`utm.py`, `medium.py`, `encoding.py`). Padrão: `pytest tests/core/test_utm.py --client devclub --client clientb`. Investimento estimado: 1–2 sessões. Retorno: detecção de regressão em segundos, não horas.

**Condição para fazer:** após dados do Cliente B chegarem. Motivo: o principal valor dos testes é serem parametrizados por dois `ClientConfig` reais — escrever com um só cliente entrega metade do valor e provavelmente exige reescrita quando o segundo chegar. Não bloqueia o PR nem o deploy.

**Condição para não adiar mais:** antes de qualquer mudança em `core/utm.py`, `core/medium.py` ou `core/encoding.py` com dois clientes ativos.

*Identificador histórico: DT-2.*

### ~~DT-3 — `preprocessing.py` em `core/` não documenta a exceção de score columns~~ ✅ RESOLVIDO (22/03/2026)

Comentário adicionado ao docstring de `preprocess()` em `core/preprocessing.py` explicando o timing constraint: no treino, score columns são removidas em `feature_removal.py` (Célula 8) para preservar o sinal do detector de cutoff temporal; `preprocess()` aqui é só para produção e monitoring.

### ~~DT-5 — `capi.decil_to_value` fica obsoleto após retreino~~ ✅ RESOLVIDO (22/03/2026)

A implementação atual (Fase 3c, item 12) pré-computa `decil_to_value = PRODUCT_VALUE × CONVERSION_RATES[decil]` e grava no YAML. O write-back pós-treino em `training_model.py` atualiza `business.conversion_rates` no YAML mas **não recalcula `capi.decil_to_value`**. Após um retreino, os valores enviados ao Meta ficam congelados nos valores antigos sem nenhum erro.

Adicionalmente: o write-back usa `f"D{i}"` (produz `D1`, `D2`...) em vez de `f"D{i:02d}"` (`D01`, `D02`...), divergindo do formato canônico declarado no #91.

**Fix (Opção B — aprovada 22/03/2026):** reverter o pré-cômputo. `capi_integration.py` volta a calcular em runtime:
```python
taxa = client_config.business.conversion_rates.get(decil, 0.0)
valor_projetado = client_config.business.product_value * taxa
```
Elimina `capi.decil_to_value` do YAML e do dataclass. Corrigir também `f"D{i}"` → `f"D{i:02d}"` no write-back. Sem estado duplicado; sempre em sincronia com o modelo ativo.

### ~~DT-6 — `api/deploy_capi.sh` lê `PRODUCT_VALUE` de `business_config.py` via `grep`~~ ✅ RESOLVIDO (22/03/2026)

`lib/config.sh` agora define `CLIENT_ID=devclub` e `CLIENT_CONFIG_FILE`. O script lê `business.product_value` de `configs/clients/{CLIENT_ID}.yaml` via `python3 + yaml` em vez de grep em `business_config.py`.

### ~~DT-4 — `client_template.yaml` incompleto~~ ✅ RESOLVIDO (22/03/2026)

Campos adicionados ao template, ao dataclass e ao `devclub.yaml`:
- Seção `business:` completa (product_value, conversion_rates, spend_threshold, color_thresholds, min_roas_safety, cap_variation_max, confidence_sigmoid, roas_target)
- `ingestion.tmb_pedidos_detection_columns`, `tmb_pedidos_column_mapping`, `tmb_pedidos_active_status_exclude` (#154–#156)

### Threshold do whitelist de Medium calculado sobre a janela errada

O threshold de 2.5% que define categorias válidas de UTM Medium em `core/medium.py` (modo treino) é computado sobre o dataset completo **antes** do corte temporal da Célula 13. Isso faz com que campanhas com alta frequência histórica mas que desapareceram antes do final do training set passem no critério e entrem no feature registry — causando alertas de "features faltantes" no monitoramento de lançamentos futuros onde essas campanhas não rodam.

**Evidência (lançamento março/2026 — investigado em 23/03/2026):**

| Feature no registry | Última ocorrência | Posição no split |
|---|---|---|
| `Medium_Lookalike_1_Cadastrados_DEV_2_0_Interesse_Ci_ncia_da_Computa_o` | 2026-01-20 | Training set only |
| `Medium_Lookalike_2_Alunos_Interesse_Linguagem_de_Programa_o` | 2026-01-14 | Training set only |
| `Medium_Lookalike_2_Cadastrados_DEV_2_0_Interesses` | 2026-02-04 (1 lead) | Training + test (1 ocorrência) |

Todas as três campanhas Lookalike representam >5% do dataset histórico completo (32k, 13k e 43k leads respectivamente), o que as manteve acima do threshold de 2.5%. Nenhuma delas aparece no banco Railway (lançamento atual), confirmando que estão genuinamente inativas.

**Fix:** calcular o threshold de frequência sobre os dados pós-cutoff (janela efetiva de treino), ou exigir presença mínima no test set para que uma categoria entre no feature registry. Arquivo a modificar: `src/core/medium.py` — função `unify_medium`, passo 5a (modo treino).

**Prioridade:** baixa — não impacta predições (modelo preenche com 0); apenas gera alertas corretos no monitoramento. Endereçar antes de escalar para 3+ clientes.

*Identificador histórico: DT-7.*

### DT-8 — Features fantasmas em `production_pipeline.py` ✅ RESOLVIDO

> **Status (2026-04-29):** RESOLVIDO. `production_pipeline.py` não tem mais criação inline das features `nome_valido`/`email_valido`/`telefone_valido` — toda a lógica está em `core/feature_engineering.py` atrás da flag `create_valido_features` (config-driven). Verificação `grep -nE "nome_valido|email_valido|telefone_valido" src/production_pipeline.py` retorna vazio. A migração aconteceu durante o porte #2 da Fase 3 da unificação (23/04/2026).

**Histórico do problema:** `production_pipeline.py` criava as 3 features inline; `core/feature_engineering.py` não criava. Quando o Champion jan30 (que tem essas features no registry) era servido, funcionava por acaso porque a versão inline replicava a lógica histórica. Mas era código duplicado fora do core canônico.

**Como foi resolvido:** o porte #2 (23/04/2026) migrou a criação para `core/feature_engineering.py` com flag opcional, e o bloco em produção sumiu junto. DevClub usa `create_valido_features=true` no YAML; clientes futuros que não precisam das features deixam o default `false`.

### DT-9 — Encoding ordinal: verificar consistência de nomes de coluna ✅ RESOLVIDO

> **Status (2026-04-29):** RESOLVIDO. `encoding.ordinal_variables` no `devclub.yaml` contém apenas `dia_semana`. Os aliases transitórios `'idade'` e `'faixa_salarial'` foram removidos durante a Opção A da unificação Fase 3 (23/04/2026), quando idade e faixa salarial migraram de ordinal para OHE como default do cliente.

**Histórico do problema:** o YAML tinha `'idade'` e `'faixa_salarial'` como chaves ordinais com nomes curtos, mas o df chegava ao `apply_encoding` com o nome longo (`'Qual a sua idade?'`, `'Atualmente, qual a sua faixa salarial?'`) — encoding ordinal era silenciosamente pulado. A Opção A resolveu o problema na raiz: idade/salário deixaram de ser ordinais por default; modelos antigos que ainda esperam ordinal recebem essa configuração via `encoding_overrides` na variante A/B (DT-12).

### DT-10 — Hardcodes de modelo em `train_pipeline.py` ✅ RESOLVIDO

> **Status (2026-04-29):** RESOLVIDO. Os fallbacks hardcoded de `PESOS_COMPRADOR` e `DEFAULT_HYPERPARAMS` em `train_pipeline.py` foram removidos. O treino agora lê **obrigatoriamente** de `client_config.model.buyer_weights` e `client_config.model.hyperparameters`. Se qualquer um dos dois estiver ausente no YAML, levanta `ValueError [R2/DT-10]` antes do fit, apontando o caminho exato a preencher. Cliente B esquecer = aborta loud (não treina com pesos DevClub silenciosamente).

**Histórico do problema:** havia fallback inline no train_pipeline com valores específicos do DevClub (`{'guru': 1.0, 'tmb_baixo': 0.84, ...}` e os hyperparams). Como o fallback só ativava quando o YAML não tinha o campo, treino do DevClub funcionava porque o YAML tem tudo preenchido, mas qualquer cliente B novo sem esses campos cairia silenciosamente nos valores DevClub. A solução foi tornar o YAML obrigatório.

### DT-11 — Imports dinâmicos em `monitoring/orchestrator.py` ✅ RESOLVIDO

> **Status (2026-04-29):** RESOLVIDO. Verificação confirma que os imports de `core/` em `monitoring/orchestrator.py` já estão no topo do arquivo (linhas 22-27): `client_config`, `utm`, `medium`, `category_unification`, `preprocessing`, `feature_engineering`. `grep -nE "^[[:space:]]+(from|import)[[:space:]].*core" src/monitoring/orchestrator.py` retorna vazio.

**Histórico do problema:** os imports estavam dentro de `run_daily_check()` em alguma versão anterior, fazendo com que erros de import só aparecessem ao rodar o monitor. Em algum commit do refactor (provavelmente parte da consolidação `src/core/`) foram movidos para o topo. Imports lazy que persistem dentro de funções são de bibliotecas pesadas (`gspread`, `google.auth`) ou com risco de ciclo (`api.database`) — escolhas intencionais, não cobertas por este item.

---

### DT-12 — Encoding por variante A/B (`encoding_overrides`) — ✅ RESOLVIDO

> **Status (2026-04-27):** RESOLVIDO em 01/04/2026 com `encoding_overrides` aplicado a `guru_jan30` em `configs/active_models/devclub.yaml`. Em 21/04/2026 a Opção A (remover idade/salário de `ordinal_variables` no `devclub.yaml`) foi aplicada e jan30 manteve o override ordinal como exceção explícita. **Atenção pós-retreino v4 (23/04):** o Champion v4 (`60637bb98b94421b9c7579bb4ac1b1ad`) foi treinado com OHE default (sem override). Quando v4 for promovido, o `encoding_overrides` do `guru_jan30` no YAML deve ser **removido** — manter quebraria o scoring do v4. Ação registrada em `PLANO_EXECUCAO.md` Fase 3 "Pendente antes do deploy".

**Problema (histórico):** `ClientConfig.encoding` é config de cliente — global para todos os modelos. Com o A/B test Champion jan30 × Challenger mar24, os dois modelos têm expectativas opostas para idade e faixa salarial: jan30 foi treinado com ordinal (coluna única `Qual_a_sua_idade = 0..5`), mar24 com OHE (`Qual_a_sua_idade_18_24_anos` etc.). A produção usa OHE → jan30 recebe `Qual_a_sua_idade = 0` para todos os leads → skew de treino/produção silencioso nos dois features mais preditivos de renda.

**Raiz histórica:** `encoding_training.py` usava nomes curtos (`'idade'`) que não existiam no DataFrame → ordinal falhava silenciosamente → OHE acidental no treino. O fix de 15/03 (`9b86d37`) alinhou produção ao OHE do modelo ativo na época; jan30 foi promovido a Champion depois sem reverter. Mar24 foi treinado após o fix, com OHE correto.

**Solução config-driven (princípio de reprodutibilidade):**

1. `ABTestVariantConfig` recebe campo `encoding_overrides: Optional[EncodingConfig] = None`
2. `merge_encoding(base, override)` em `core/encoding.py` — copia base e aplica campos não-None do override; `ordinal_variables` é merged (union, override vence conflitos)
3. `production_pipeline.preprocess(encoding_overrides=None)` aplica `merge_encoding` antes de chamar `apply_encoding`
4. `production_pipeline.run(encoding_overrides=None)` repassa para `preprocess`
5. `api/app.py` passa `ab_variant.encoding_overrides` ao chamar `pipeline.run()` por grupo A/B
6. `active_models/devclub.yaml` → variante `guru_jan30` recebe `encoding_overrides.ordinal_variables` com os mapeamentos de idade e salário

**Impacto:** mar24 sem `encoding_overrides` → comportamento idêntico ao atual (OHE). Jan30 com overrides → ordinal correto. Funciona para Cliente B sem nenhum código extra — se o cliente não tiver A/B ou não precisar de override, o campo simplesmente fica `None`.

**Arquivos:** `src/core/client_config.py`, `src/core/encoding.py`, `src/production_pipeline.py`, `api/app.py`, `configs/active_models/devclub.yaml`

**Prioridade:** alta — A/B test atual está com jan30 em desvantagem estrutural.

---

#### Complemento — 2026-04-21 (descoberto durante preparação da Fase 3)

A implementação original do DT-12 assumiu que o **default** do cliente era OHE. Na verdade, `configs/clients/devclub.yaml` manteve idade/salário em `ordinal_variables` como default, então:

- **Jan30 com override ordinal:** funciona (override confirma o default)
- **Mar24 sem override:** herda o default ordinal → **perde 11 features OHE esperadas pelo feature_registry** (6 de idade + 5 de salário). Situação inversa do que DT-12 descreve.

Evidência: `mlruns/1/a859c68b1cb94c3b93767a3131eda89a/artifacts/feature_registry.json` tem `Qual_a_sua_idade_18_24_anos`, `Atualmente_qual_a_sua_faixa_salarial_entre_r1000_a_r2000_reais_ao_mes` etc. — ou seja, mar24 foi treinado com OHE.

**Ação (Opção A):** na Fase 3 da unificação, remover idade/salário de `ordinal_variables` do `clients/devclub.yaml`. Jan30 mantém override ordinal (passa a ser a exceção explícita ao default). Mar24 herda OHE (como foi treinado). Ver `PLANO_EXECUCAO.md` → Fase 3 → "Decisão arquitetural — Opção A".

### Brecha de dígitos curtos no fallback de UTM Term (deixa códigos numéricos passarem como categoria nova)

`src/core/utm.py:118` — a condição de fallback `if not valor.isdigit() or len(valor) > threshold` foi escrita para mandar IDs longos para `'outros'` enquanto preservaria códigos numéricos curtos conhecidos. Na prática, nenhuma categoria numérica existe na whitelist DevClub (`Term: instagram / facebook / outros`), e a exceção apenas cria uma brecha: qualquer string 100% numérica com até 10 dígitos permanece como valor raw em vez de virar `'outros'`.

**Evidência (investigado em 22/04/2026; reconfirmado em 23/04/2026 com novo termo):**

| `utm_term` raw | Leads 24h (22/04) | Leads 24h (23/04) | Destino atual | Destino correto |
|---|---|---|---|---|
| `0405` | 669 | 131 | permanece `'0405'` | `'outros'` |
| `2104` | — | 232 | permanece `'2104'` | `'outros'` |
| `{{site_source_name}}` | 40 | 29 | `'outros'` (pattern `{`) | — ok |
| `120240527343300390` | 4 | 5 | `'outros'` (18 dígitos > threshold) | — ok |

O padrão se confirmou em 23/04: o volume em `0405` caiu mas surgiu `2104` (232 leads) — o bug continua deixando passar qualquer novo código numérico de até 10 dígitos que o gestor de tráfego resolver usar. Total de leads afetados permanece na mesma ordem de magnitude (363 em 23/04 vs 669 em 22/04).

**Impacto:** os 669 leads/24h com `term='0405'` saem do encoding com `Term_facebook = Term_instagram = Term_outros = 0` — combinação nunca vista no treino, onde todo lead tinha exatamente um dos três = 1. A feature `Term_0405` é criada e descartada pelo modelo; o lead fica sem sinal de Term (grupo pesa 3,59% da importância). Efeito desprezível por lead, mas 16% do volume diário.

**Fix (uma linha):** substituir o bloco da regra remainder por um teste simples de presença na whitelist:

```python
# Antes (src/core/utm.py:112-119)
valores_conhecidos = set(direct_mappings.values()) | {'outros'}
outros_mask = df['Term'].notna() & ~df['Term'].isin(valores_conhecidos)
valores_restantes = df.loc[outros_mask, 'Term'].unique()
for valor in valores_restantes:
    if isinstance(valor, str):
        if not valor.isdigit() or len(valor) > threshold:
            df.loc[df['Term'] == valor, 'Term'] = 'outros'

# Depois
valores_conhecidos = set(direct_mappings.values()) | {'outros'}
df.loc[df['Term'].notna() & ~df['Term'].isin(valores_conhecidos), 'Term'] = 'outros'
```

O parâmetro `config.term_long_id_threshold` pode ser marcado DEPRECATED no YAML e no dataclass. Validar em paridade com treino: rodar pipeline de treino pós-fix — a distribuição de Term no dataset não deve mudar (no treino histórico não existem valores numéricos curtos não-mapeados, pelo que `_load_valid_categories` mostra só instagram/facebook/outros).

**Prioridade:** alta — bug ativo degradando 16% dos leads diários, fix trivial. Fechar antes de qualquer retreino (DT-13 precede "Gatilho de retreino por drift de públicos" no `PLANO_EXECUCAO.md`).

**Referência cruzada:** `Erros_cometidos.md` item 11 (mesma lição, ocorrência anterior em UTM Source — 20/02–26/02/2026); `PLANO_EXECUCAO.md` "Gatilho de retreino por drift de públicos".

*Identificador histórico: DT-13.*

---

### Nomenclatura `clients/{cliente}.yaml` vs `active_models/{cliente}.yaml` confunde

**Sintoma:** existem dois arquivos com o mesmo nome (`devclub.yaml`) em diretórios distintos: `configs/clients/devclub.yaml` e `configs/active_models/devclub.yaml`. A nomenclatura não comunica o papel de cada um, e a duplicação do nome força quem trabalha no projeto a memorizar o significado por convenção.

**Papéis reais (descobertos só após leitura de código):**
- `configs/clients/devclub.yaml` — config **estática** do cliente: encoding default, mapeamentos UTM/Medium, schema da pesquisa, hyperparameters do treino, business config. Muda raramente.
- `configs/active_models/devclub.yaml` — config **dinâmica** do experimento: qual `mlflow_run_id` está em produção, variantes do A/B test, `encoding_overrides` por modelo. Muda a cada retreino/A/B.

**Confusão registrada (sessão 02/05/2026):** o usuário relatou explicitamente que a nomenclatura "não deixa claro para que serve cada arquivo e por que precisamos de um active_model em um YAML separado". Sinalizou também que reorganizar é arriscado pelo número de funções que dependem dos paths atuais.

**Impacto:** custo cognitivo recorrente em qualquer sessão envolvendo encoding, A/B test ou roteamento de modelo. Onboarding de Cliente B vai herdar o mesmo padrão e replicar a confusão.

**Soluções possíveis (não decidir aqui — discutir com usuário):**
1. **Renomear** preservando a separação: `configs/<cliente>/static.yaml` + `configs/<cliente>/experiment.yaml`. Comunica o papel pelo nome do arquivo.
2. **Unificar em um arquivo só** com seções claras: `configs/<cliente>.yaml` com top-level `static:` e `experiment:`. Reduz arquivos mas obriga lock contention em mudanças simultâneas (ex: alguém atualizando run_id ativo enquanto outro mexe em encoding default).
3. **Manter estrutura, melhorar nomes:** `configs/clients_static/<cliente>.yaml` + `configs/active_models/<cliente>.yaml`. Mudança mínima, comunica que clients_static é estático.

**Custo do fix:** médio. Os paths estão referenciados em `production_pipeline.py:127-132`, `app.py:2642-2650, 2882-2891`, `train_pipeline.py`, `monitoring/orchestrator.py`, scripts de deploy. Renomear exige grep + replace consistente + smoke test completo. Sem urgência — registrar e voltar quando houver outra razão para tocar nesses paths (ex: onboarding Cliente B).

**Prioridade:** baixa (não quebra nada). Reabrir quando houver janela para refactor de paths.

*Identificador histórico: DT-14.*

---

### Variante A/B exige campos obrigatórios que o caminho do Champion nunca usa

**Sintoma:** [`ABTestVariantConfig`](../src/core/client_config.py#L342-L352) declara `capi_event_name`, `capi_event_name_high_quality` e `conversion_rates` como obrigatórios no dataclass + parser ([client_config.py:382-388](../src/core/client_config.py#L382-L388)). Mas em produção esses campos só são consumidos quando `ab_v` (variante matcheada por `match_variant`) é truthy ([app.py:3458-3464](../api/app.py#L3458-L3464)). Pro path Champion (variante não matcheia, `ab_v=None`), event_name e conversion_rates vêm de `client_config.capi.*` em `clients/devclub.yaml`, e o pixel vem de `client_config.capi.pixel_id`.

**Cheiro de design:** uma entrada tipo "shim" — variante existindo só pra hospedar `encoding_overrides` do Champion (caso DT-12 + workaround do bug do jan30 descoberto em 02/05/2026) — é forçada a preencher event_name, event_name_hq, conversion_rates como **lixo de parser**. O leitor do YAML acha que esses valores vão ser usados; eles não vão. Documentação fica enganosa, manutenção fica frágil (alguém pode "corrigir" um valor desses achando que é bug e na verdade nunca foi lido).

**Confusão registrada (sessão 02/05/2026):** o usuário sinalizou explicitamente: "documenta essa puta confusão de nomes de eventos sendo lidos como tendo o override etc. Dá para simplificar muito isso."

**Soluções possíveis (não decidir aqui):**
1. **Tornar campos `Optional` no dataclass** + ajustar parser pra aceitar ausência + adaptar callers que assumem presença. Solução mínima.
2. **Separar em dois dataclasses:** `RoutingVariantConfig` (variante real, com event_name/conversion_rates obrigatórios) vs `EncodingShimVariantConfig` (só `run_id` + `encoding_overrides`). YAML schema ganha 2 entradas em `ab_test`: `variants:` (routing) e `encoding_shims:` (só encoding).
3. **Mover `encoding_overrides` pra fora de `variants`:** novo bloco top-level no `active_models/<cliente>.yaml` indexado por `run_id`. Variantes só descrevem roteamento; encoding por modelo é uma tabela à parte. Mais limpo conceitualmente, mas requer mudar todos os callers de `variant.encoding_overrides`.

**Custo do fix:** baixo a médio dependendo da opção. Opção 1 (tornar opcional) ~30min + smoke. Opção 3 (refactor estrutural) ~2h.

**Prioridade:** baixa, mas com alavancagem alta no esclarecimento. Bom candidato pra agrupar com DT-14 num único refactor de configs.

*Identificador histórico: DT-15.*

---

### Aposentar o mecanismo de "encoding override" treinando próximo Champion já com OHE nativo

**Contexto:** DT-12 introduziu `encoding_overrides` para resolver a divergência de encoding (ordinal vs OHE) entre Champion jan30 (treinado pré-Opção A com ordinal) e modelos novos (treinados com OHE default). DT-14 e DT-15 documentam débitos colaterais desse mecanismo: nomenclatura de configs que confunde, campos obrigatórios não-utilizáveis no shim do Champion, código duplicado em monitoring que precisa replicar a lógica de merge_encoding (resolvido em 05/05/2026 mas reforça o cheiro de design, e em 06/05/2026 transformado em loop per-variant via helper `_iter_active_variants` que itera Champion + Challenger emitindo alertas com `variant_name`).

**Estratégia mais simples que todas as anteriores:** matar o mecanismo por convergência. Se o único modelo em produção que precisa de override (jan30 hoje) for substituído por **qualquer modelo treinado com o pipeline atual** (OHE nativo, default desde Opção A em 21/04/2026), `encoding_overrides` não tem mais usuário e pode ser removido sem refactor estrutural.

**Pré-requisito:** ter o **próximo Champion** treinado com pipeline atual ativo. **Não precisa ser "jan30 retreinado" especificamente.** Sinalização do usuário (sessão 05/05/2026): "o run do modelo retreinado jan30 com o novo pipeline, além de ter se perdido, utilizou dados muito diferentes do Challenger atual; eu realmente criaria um novo modelo, o que redundaria no Champion e tornaria esse ponto atual irrelevante." Ou seja: o jan30 retreinado está perdido + usaria dados antigos demais → o caminho real é **um novo modelo conceitualmente**, treinado com dados recentes, que vire o novo Champion.

**Quando o override volta a ser potencialmente necessário?** Só se algum dia houver A/B entre dois modelos com **encodings divergentes** (ex: novo Challenger com hash encoding rodando contra Champion OHE). Hoje, qualquer modelo treinado pelo pipeline atual sai com OHE nativo → o A/B Champion vs novo Challenger nunca exige override. O usuário confirmou (05/05/2026): "o ponto só se tornaria relevante quando formos testar A/B entre o Challenger atual e um novo Challenger também retreinado na arquitetura atual — invalidando a necessidade do override de encodings."

**Sequência de execução (assumindo novo Champion válido):**

| Passo | Ação | Esforço |
|---|---|---|
| 1 | Validar metadados do novo Champion: AUC/lift/monotonia aceitáveis; feature_registry com `Qual_a_sua_idade_18_24_anos` etc (OHE-expandido); **idade/salário NÃO em colunas ordinais únicas** (sinal inequívoco de pipeline atual) | 5 min |
| 2 | `configs/active_models/devclub.yaml`: trocar `active_model.mlflow_run_id` pro novo run_id; **remover entrada `champion_jan30`** dos `ab_test.variants` | 2 min |
| 3 | Deploy canary + smoke (gate E3) + promoção 100% | 15 min |
| 4 | Verificar nos logs Cloud Run: T1-10 deixa de citar `Qual_a_sua_idade` (ordinal) e passa a citar `Qual_a_sua_idade_*_anos` quando aplicável (esperado pra batches pequenos sem cobertura de todas categorias) | 5 min |
| 5 | (Code cleanup, opcional) Marcar `ABTestVariantConfig.encoding_overrides` como `# DEPRECATED — manter campo por backward-compat enquanto algum YAML legado ainda usa; remover quando confirmar que nenhum YAML em produção tem essa chave` | 2 min |
| 6 | (Refactor futuro, opcional) Após N semanas sem uso, remover totalmente: campo do dataclass, parser em `from_active_model_yaml`, função `merge_encoding`, parâmetro `encoding_overrides` em `production_pipeline.run/preprocess`, lookup do champion variant em `app.py:937-943` e `:3373-3380`, e os blocos em `monitoring/data_quality.py:_iter_active_variants, _check_missing_features, _check_extra_features e _check_critical_features_coverage (T1-10 surface)` | 30-60 min |

**Total mínimo (passos 1-4):** ~30 min ponta a ponta. Resolve **simultaneamente**:
- DT-12 (encoding por variante) — vira histórico, sem usuário ativo
- DT-15 (campos obrigatórios não-utilizáveis) — não precisa mais do shim, parser fica honesto
- Bug atual do jan30 cego em idade/salário (já foi mitigado com champion_jan30 shim em 02/05/2026, mas é definitivamente apagado aqui)
- Bug do monitoring assimétrico (resolvido em 05/05/2026 mas torna-se irrelevante quando override some)

**Não resolve diretamente:**
- DT-14 (nomenclatura `clients/` vs `active_models/` confunde) — a separação dos dois arquivos continua, e o motivo da separação ainda existe (config estática vs dinâmica). Esse é refactor independente.

**Trade-off:**
- ✅ **Pra simplicidade:** caminho mais limpo. Encoding default (OHE) atende todos os modelos novos. `merge_encoding` vira código órfão e some no passo 6.
- ⚠️ **Pra flexibilidade futura:** se algum dia houver modelo treinado com encoding diferente (target encoding, hash encoding pra cliente B), o mecanismo seria útil. Mas dá pra ressuscitar quando a necessidade aparecer — não precisa manter código preventivamente.

**Sinalização do usuário (sessão 05/05/2026):** "Se decidimos optar por uma arquitetura única que serve apenas modelos com o modelo atual de código, ou seja, OHE para todas as features, toda essa questão desaparece, e encoding overrides vira legado. O quão fácil ou difícil seria fazer com que Encoding Override vire legado?"

**Recomendação:** matar por convergência assim que o run_id do jan30 retreinado for confirmado. Bloqueio único: validar o retreino.

**Prioridade:** alta — a soma de DT-12+DT-14+DT-15+bug monitoring é mais cara que esse passo único de deprecation.

*Identificador histórico: DT-16.*

---

### Eliminar duplicação entre `api/business_config.py` e o YAML do cliente — treino escreve no MLflow, promoção copia pro YAML

**Contexto:** o sistema tem hoje **três** lugares onde dados de negócio são definidos, com responsabilidades sobrepostas:

| Local | Conteúdo | Quem lê |
|---|---|---|
| `configs/clients/devclub.yaml:business` | `product_value`, `ticket_contracted`, `conversion_rates` (Fix A 06/05) etc. | Pipeline pós-refactor (`src/core/`, `api/capi_integration.py` via `BusinessConfig`) |
| `BusinessConfig` em `src/core/client_config.py` | dataclass com defaults — `product_value: float = 1563.75` ⚠️ | Forma tipada do YAML acima |
| `api/business_config.py` | `PRODUCT_VALUE`, `CONVERSION_RATES`, `LEAD_VALUE_BY_DECILE_CHAMPION/CHALLENGER` hardcoded | (1) `src/model/training_model.py:atualizar_business_config_com_recall` escreve aqui após cada treino; (2) revisão `edf23e9` (rollback) lia daqui via import direto até 29/04 |

**O bug que esse débito causou (já mitigado com Fix A em 06/05):** entre 30/04 e 06/05, produção (revisão `main`) usava o YAML como fonte de verdade mas `conversion_rates` tinha sido removido em 06/04 (commit `d40970a`) sem ninguém atualizar o código de runtime. Resultado: 7 dias com 100% dos `LeadQualified` enviados com `value=0`. Detalhes em `docs/operacoes_gcp_custos.md` seção "Investigação de spike de custo — 2026-05-06" e em `PLANO_EXECUCAO.md` "Sequelas 02/05" item VAL=0.

**Fix A aplicado em 06/05/2026:** `conversion_rates` recolocado no YAML, com rates back-calculadas a partir de `LEAD_VALUE_BY_DECILE_CHAMPION` (rate = lead_value / product_value). Próximo deploy aplica em produção. **Esse fix tampa o buraco mas não unifica nada** — `business_config.py` continua como fonte secundária, não-lida em produção.

**DT-17 = fix arquitetural definitivo.** Objetivo: deletar `api/business_config.py` por convergência. YAML vira a única fonte de verdade. Mas com uma restrição importante explicitada pelo usuário em 06/05/2026:

> "O fix C não pode ser o treino atualizando direto o YAML do cliente, a não ser que a gente queira colocar em produção. A atualização tem que ser no momento em que a gente aponta o container para usar o ID do MLflow com o modelo atualizado."

Ou seja: **treino ≠ deploy.** O YAML do cliente é configuração de produção; alterar no momento do treino exporia rates de um modelo ainda não promovido. A sequência correta:

```
[treino] → escreve rates como artifact dentro do MLflow run (gs://smart-ads-mlflow/artifacts/{run_id}/business_rates.yaml)
[--set-active] → lê o artifact do run que está sendo promovido
              → copia rates para configs/clients/{client_id}.yaml (ou para configs/active_models/{client_id}.yaml — decidir no design)
[deploy] → roda normalmente, lê do YAML
```

**Sequência de execução (assumindo arquitetura definida + próximo Champion treinado):**

| Fase | Ação | Esforço | Bloqueio |
|---|---|---|---|
| 1 | Adicionar campo `lead_values_by_decile: Optional[Dict[str, float]]` em `BusinessConfig` (dataclass) e em `ABTestVariantConfig`. Modificar `capi_integration.py:347` para preferir esse campo quando setado: `value = lead_values_by_decile[decil]` direto, sem multiplicação por product_value | ~30 min | Nenhum — fix sai compatível com Fix A. Dois caminhos coexistem: `lead_values_by_decile` (novo) e `product_value × conversion_rates` (legado) | 
| 2 | Remover defaults DevClub-específicos do dataclass (`product_value: float = 1563.75` → `0.0`); adicionar validação em `validate()` que levanta erro se cliente esquecer campo obrigatório | ~10 min | Nenhum |
| 3 | Modificar `training_model.py:atualizar_business_config_com_recall` para **escrever um YAML artifact dentro do MLflow run** (`mlflow.log_artifact("business_rates.yaml")`) em vez de mexer em `api/business_config.py`. Manter escrita em `api/business_config.py` em paralelo (deprecation gradual) | ~20 min | Nenhum |
| 4 | Modificar fluxo de promoção (`train_pipeline.py --set-active` ou novo comando dedicado): no momento de apontar `configs/active_models/{client_id}.yaml` pro novo `run_id`, baixar `business_rates.yaml` do MLflow run e copiar `lead_values_by_decile` para o YAML autoritativo | ~30 min | Decidir destino: `clients/{client_id}.yaml` (estático, polui git) ou `active_models/{client_id}.yaml` (dinâmico, já é convencionado para "estado mutável de produção"). Sugestão: `active_models` |
| 5 | Próximo retreino real: validar fluxo ponta a ponta — modelo treinado → rates aparecem no MLflow → `--set-active` copia → deploy lê → valor correto sai pra Meta | depende do retreino | Aguarda próximo Champion |
| 6 | Após N semanas com fluxo novo funcionando: deletar `api/business_config.py:CONVERSION_RATES`, `LEAD_VALUE_BY_DECILE_*` e `PRODUCT_VALUE`. Manter outros campos do arquivo (thresholds operacionais, color_thresholds etc.) ou migrar todos para YAML também (escopo maior) | ~10 min | Confirmar que ninguém mais lê `business_config.py` (grep) |

**Total fases 1-3 (preparatórias, sem retreino):** ~1h.
**Total fases 4-6 (executar com próximo retreino):** ~1h adicional + tempo natural do retreino.

**Resolve simultaneamente:**

- Bug latente "value=0" (Fix A já mitiga, DT-17 elimina a possibilidade de regressão futura)
- Defaults DevClub-específicos no dataclass (impede contaminação silenciosa em multi-cliente)
- Duplicação `business_config.py` × YAML (uma fonte só)
- Frame ambíguo "rate × product_value vs lead_value direto" (usa lead_value direto, sem ginástica matemática)

**Não resolve:**

- Outros campos hardcoded em `business_config.py` (color_thresholds, MIN_ROAS_SAFETY, etc.) — esses ficam para uma rodada futura, sem urgência. Cada um deles tem path próprio: ou migra pra YAML (se específico do cliente) ou pode virar default sensato no código (se realmente genérico).

**Sinalização do usuário (06/05/2026):** "não vejo sentido em usar dados do cliente hardcoded no dataclass" — afirmação correta. Os defaults atuais (`product_value: float = 1563.75`) violam o princípio multi-cliente do refactor.

**Etapa 0 — atacável imediatamente (sem retreino, ~30min):**

A duplicação fonte do bug VAL=0 é o fato de **`CONVERSION_RATES` e `LEAD_VALUE_BY_DECILE_*` estarem hardcoded em `api/business_config.py`** simultaneamente com cópias no YAML. Hoje, em runtime, a variante A/B sobrescreve com valores do YAML (`active_models/{cliente}.yaml`), mas os hardcoded permanecem como armadilha — qualquer drift entre os dois lugares passa silencioso até o Gate D pegar (e Gate D não roda em todos os fluxos).

Atacar agora:
1. Marcar `CONVERSION_RATES`, `LEAD_VALUE_BY_DECILE_CHAMPION` e `LEAD_VALUE_BY_DECILE_CHALLENGER` em `business_config.py` como `DEPRECATED` via comentário + `warnings.warn` no import — sem deletar ainda (transição segura).
2. Adicionar leitura desses valores **a partir do YAML do cliente** (`configs/clients/devclub.yaml:business.conversion_rates` já existe pós-Fix A).
3. Atualizar `training_model.py:atualizar_business_config_com_recall` para escrever no YAML em vez de no `business_config.py`.
4. Após próximo retreino estável: deletar os hardcoded.

Fechamento desta etapa: **uma única fonte de verdade** (YAML) para `conversion_rates` em runtime. Gate D continua como salvaguarda. Próximas etapas (1-6 abaixo) ficam pra quando o próximo Champion sair.

**Sequência completa (fases 1-6) permanece como abaixo, executável junto do próximo retreino.**

**Atualização de status (2026-05-11):** etapa 0 é o próximo passo imediato (decidido com o usuário). Foi reclassificada de "NÃO é o próximo passo imediato" para "atacar agora" porque (a) Fix A mitigou mas não unificou, (b) usuário priorizou direção arquitetural bundle-imutável (Sessão 3.2 da discussão), (c) etapa 0 é independente de retreino.

**Prioridade:** ALTA agora (etapa 0); fases 1-6 ficam ALTA para quando próximo Champion sair.

*Identificador histórico: DT-17.*

---

### Normalizar 4 features binárias raw (`genero`, `estudouProgramacao`, `faculdade`, `investiuCurso`) — bloqueia A/B com Challenger novo

**Contexto:** quatro features categóricas vindas da pesquisa do front chegam ao modelo **sem normalização** (sem `.lower()`, sem `unidecode`, sem `.strip()`):

| Coluna pós-`data_loader` | Valores canônicos atuais |
|---|---|
| `genero` | `'Masculino'`, `'Feminino'` |
| `estudou_programacao` | `'Sim'`, `'Não'` |
| `fez_faculdade` | `'Sim'`, `'Não'` |
| `investiu_curso_online` | `'Sim'`, `'Não'` |

A exclusão é **deliberada** e está documentada com comentário longo em [src/data_processing/category_unification.py:91-115](../src/data_processing/category_unification.py#L91-L115). Razão: o Champion atual (`jan30`, run `d51757f5041c44b7ab1a056fce8c3c35`) foi treinado com os valores ORIGINAIS — `pd.get_dummies()` gera nomes de coluna sufixados pelo valor cru (`'Não' → '_N_o'`). Se a normalização passar a rodar em produção, `'Não' → '_N_o'` vira `'nao' → '_nao'` (sufixo inexistente no `feature_registry`) e o modelo recebe **as 4 features zeradas pra 100% dos leads** — silencioso, sem erro.

**Por que vira bug se o front mudar:** hoje protegidos porque o payload é estável (`'Sim'`/`'Não'` exatos). Se o front mandar `'sim'` minúsculo, `'SIM'` caps ou whitespace extra, o OHE gera coluna inédita e o sinal cai a zero do mesmo jeito. Mesma classe dos Clusters 1, 3, 4, 5 do Erro 2 do `registro_erros_ml.md`. Dependência implícita inadmissível em sistema multi-modelo/multi-cliente.

**Fix obrigatório (vetor 2 da V.2 do registro_erros_ml.md):** aplicar `.strip().lower()` (ou equivalente) nas 4 features **em treino e produção juntos**. Remover a exclusão explícita em `category_unification.py:95-116` e incluir as 4 colunas no `COLUNAS_CATEGORICAS` que recebe `limpar_texto`.

**🚨 Bloqueio crítico — fix isolado QUEBRA produção:**

| Cenário | Champion (jan30) `feature_registry` | Produção (encoding) | Resultado |
|---|---|---|---|
| Hoje | OHE com sufixos `_Sim`/`_Não`/`_Masculino`/`_Feminino` | Strings raw | ✅ Funciona |
| Fix só em produção | OHE com sufixos originais | Strings normalizadas (`_sim`/`_nao`) | ❌ **QUEBRA** — 100% das 4 features zeradas |
| Fix só em treino | (jan30 não muda — já está em produção) | Strings raw | ✅ Funciona, mas próximos modelos divergem do legado |
| Fix em treino + produção + retreino do Champion | OHE com sufixos normalizados | Strings normalizadas | ✅ Funciona e robusto a casing variation futura |

**Conclusão dura:** **DT-18 não pode ser implementado isolado em produção enquanto `jan30` estiver como Champion.** Tem que ir junto com retreino do Champion. Sem isso, produção roda com 100% dos leads cegos pra essas 4 features (8% do peso somado, similar ao dano do Cluster 4/5 do Erro 2 — que custou ~R$4-8k de movimentação total entre decis em janelas de 6-7 dias).

**Pré-requisitos para implementar:**
1. Implementar normalização em `core/category_unification.py` (remover bloco de exclusão linhas 91-116 + adicionar as 4 colunas a `COLUNAS_CATEGORICAS`).
2. Confirmar que treino (`train_pipeline.py`) e produção (`production_pipeline.py`) usam o mesmo código via `core/` — regra já existente, só validar que não há replicação fora.
3. Treinar **próximo Champion** com o código novo. **NÃO promover sem retreino.**
4. Validar no `categorias_esperadas.json` do novo run: as 4 features com valores normalizados (`'sim'`, `'nao'`, `'masculino'`, `'feminino'`).
5. Promover via canary normal (gates A→B→C→D→E).

**Dependência com DT-16:** DT-16 (matar `encoding_overrides`) já requer um novo Champion treinado com pipeline atual. **DT-18 deve entrar no MESMO retreino do DT-16** — qualquer modelo que vire o próximo Champion já sai com o fix. Faz UM retreino só, não dois.

**A/B com Challenger é condicional:** se um A/B for ligado com Champion legado (jan30, sem fix) + Challenger novo (com fix), o caminho do Challenger funciona mas o do Champion roda exposto à variação de casing. O A/B fica enviesado pelos leads que caem no Champion. **Retreinar o Champion é pré-condição para qualquer A/B em que o Challenger use código com normalização.**

**Mitigação de risco enquanto o fix não entra:** vetor 3 da V.2 implementado em 08/05/2026 — `actionable_alerts` no `/monitoring/daily-check` destaca HIGH+MEDIUM. Se o front mandar valor inesperado, `check_category_drift` dispara `new_categories` e aparece no topo do response. Isso não é fail-safe (continua silencioso pra produção até o próximo daily-check), mas dá detecção em até 24h.

**Cross-refs:**
- `V2/docs/registro_erros_ml.md` § V.2
- `V2/src/data_processing/category_unification.py:91-115` (comentário longo no código)
- `V2/docs/CHECKLIST_ONBOARDING_NEW_CLIENT.md` § 3 (treinar modelo)
- `V2/docs/PLANO_EXECUCAO.md` (item de pré-requisito do próximo retreino)

**Prioridade:** **alta** — bloqueia A/B com Challenger novo. Risco operacional atual baixo (front estável), mas a primeira variação de casing quebra silenciosamente.

*Identificador histórico: DT-18.*

### Unificação de Source/Term ignora a whitelist da variante A/B em execução

**Contexto (descoberto em 2026-05-11, Cenário 1.2 do `AUDITORIA_QUEBRA_PRODUCAO.md`):** a unificação de Medium em [src/core/medium.py:99-169](../src/core/medium.py#L99-L169) **já é variant-aware** — carrega a whitelist canônica de `distribuicoes_esperadas.json` do `mlflow_run_id` da variante em execução (resolvido em `production_pipeline.py:279` como `predictor_override or self.predictor`). A unificação de Source/Term em [src/core/utm.py](../src/core/utm.py), em contraste, **só usa o YAML global do cliente** (`config.source_canonical_values` e `term_mappings`). Sem variant info, sem artifacts.

**Por que vira bug:** o YAML hoje aceita `tiktok` e `youtube` como Source canônico, porque a Challenger `abr28` (`5d158f0aa6e54b489498470446194a6c`) tem `Source_tiktok` e `Source_youtube` no `feature_registry`. Mas o Champion `jan30` (`d51757f5041c44b7ab1a056fce8c3c35`) só tem `Source_facebook_ads`, `Source_google_ads`, `Source_outros`. Resultado:

| Lead `Source=tiktok` | Path Champion (default, sem utm_campaign matching) | Path Challenger (`utm_campaign='PIXEL NOVO API'`) |
|---|---|---|
| Resultado | `Source_*` todas zeradas (3 colunas = 0) | `Source_tiktok = 1` ✅ |
| Volume últimos 30d | 1.93% (2186 leads) atinge o path Champion | poucos leads tiktok têm utm_campaign='PIXEL NOVO API' |

Mesma classe do Cluster 3, 4 e 5 do Erro 2 — feature OHE silenciosamente zerada por um lead com categoria não vista pela variante.

**Solução proposta:** espelhar a arquitetura de `core/medium.py` em `core/utm.py`:

1. `unify_utm(df, config, artifacts=None)` — adicionar parâmetro `artifacts` opcional.
2. `_unify_source` — antes de aplicar `config.source_canonical_values`, tentar carregar `distribuicoes_esperadas['categorical']['Source'].keys()` do `mlflow_run_id` dos `artifacts`. Mesmo padrão de `_load_valid_categories` em `core/medium.py:99-169` (com fallback fail-loud).
3. `_unify_term` — análogo para Term.
4. `production_pipeline.py:268` — mover chamada de `unify_utm` para depois da construção do `_artifacts` (linha 279), passar `_artifacts`.
5. `train_pipeline.py` — chamar `unify_utm` sem `artifacts` (mantém comportamento atual de descobrir whitelist a partir dos dados do treino).

**Pré-requisitos obrigatórios (não pular):**

A. **Auditoria de paridade variant-aware para UTM** — estender `audit_utm` em `V2/tests/parity_audit.py` para rodar por variante, igual `audit_encoding_ab_variants` já faz. Sem isso, refactor entra sem cobertura.

B. **Snapshot por variante para UTM** — criar `V2/tests/capture_utm_snapshots_ab.py` análogo ao `capture_encoding_snapshots_ab.py`. Captura input snapshot diferenciado por variante.

C. **Validador pós-encoding cross-coluna** — regra "as 3-5 colunas `Source_*` de uma variante não podem estar TODAS simultaneamente zeradas para o mesmo lead". Roda no smoke test (`scripts/smoke_test_revision.py`) e em runtime via `feature_validator.py`. Detecta exatamente o cenário "categoria nova passou pela unificação sem mapear na whitelist da variante".

D. **Teste unitário em `tests/test_unify_utm.py`** — input com `Source=tiktok`, executa via Champion e via Challenger, assert resultado correto em cada variante.

**Gates de deploy que cobrem o refactor:**
- Gate A (parity audit) **com cobertura variant-aware adicionada via Pré-req A**.
- Gate B (smoke test variantes) cobre execução por variante.
- Gate C (equivalência de decil): leads `tiktok` antes do refactor (decil X com Source zerado) vs após (decil Y com Source válido). Mudança esperada — passar `--expect-score-change` se >0 leads divergirem por causa do refactor.

**Estimativa de tempo:** ~3h totais (1.5h refactor + 1.5h pré-requisitos A-D).

**Impacto prático imediato:** ~1.93% dos leads do path Champion (≈70 leads/dia, ≈2100 leads/30d em volume atual) deixam de ter encoding Source zerado. Crescente se o gestor escalar TikTok.

**Cross-refs:**
- `V2/docs/AUDITORIA_QUEBRA_PRODUCAO.md` Cenário 1.2 (achado original).
- `V2/src/core/medium.py:99-169` (referência arquitetural — já é variant-aware).
- `V2/src/core/utm.py:52-103` (`_unify_source` — alvo do refactor).
- `V2/src/production_pipeline.py:268, 296` (assimetria atual: medium recebe artifacts, utm não).
- `V2/configs/clients/devclub.yaml:148-185` (YAML utm que hoje guarda whitelist da união de variantes).

**Prioridade:** média — volume atual baixo (1.93%), mas precondição clara e classe de bug com precedente histórico (Clusters 3, 4, 5 do Erro 2). Refactor desbloqueia adicionar qualquer Source/Term novo via Challenger sem dependência de retreino do Champion.

*Identificador histórico: DT-19.*

---

## 12. Caminho para Nível 2 e além

Ver **`docs/ROADMAP_MLOPS_MATURIDADE.md`** para o guia completo.

Resumo: o refactor (Fases 1–3) entrega o Nível 1 sólido (Google MLOps Level 1 — pipeline automatizado, skew eliminado, multi-cliente por config). Os próximos passos imediatos são os dois gaps do Nível 1 ainda abertos:

1. **Validação de dados pré-treino** (`src/core/validation.py`) — antes do segundo cliente
2. **Quality gate automático pós-treino** (Sprint 2 do `retraining_orchestrator.py`) — qualquer momento

O Nível 2 (CI/CD para código ML) e o stack GCP completo (Pub/Sub, Dataflow, Vertex AI, BigQuery Feature Store) têm condições de negócio explícitas documentadas no roadmap — não são compromissos imediatos.

---

---

## 12. Lições Aprendidas

### Regra: implementar exatamente o que a função original faz — nada mais

**Regra obrigatória para toda migração de componente:**

1. Antes de implementar, listar explicitamente o que a função original remove/transforma (verificar no código, não na memória)
2. Implementar exatamente isso — nem mais, nem menos
3. Rodar o pipeline de treino completo e comparar: dataset size, cutoff date, AUC e monotonia com o modelo de referência (`2a98e51c`: 48.812 registros, cutoff 2025-11-04, AUC 0.745, monotonia 100%)
4. Só após paridade confirmada, expandir com transformações adicionais (se necessário)

**Sinal de alarme:** se o número de registros pós-cutoff mudar entre o run de referência e o run de validação, há regressão — não prosseguir.

---

### Protocolo obrigatório: `validate_parity_snapshots.py`

Para tornar o passo 3 acima objetivo e automático, existe o script `V2/scripts/validate_parity_snapshots.py`. Ele captura snapshots do DataFrame em 6 checkpoints do pipeline e compara row count, conjunto de colunas e distribuições de categorias contra um golden baseline.

**Fluxo obrigatório:**

```bash
# ANTES de tocar qualquer código:
python scripts/validate_parity_snapshots.py --generate-golden [ARGS]
# APÓS implementar:
python scripts/validate_parity_snapshots.py --validate [ARGS]  # mesmos ARGS — obrigatório
# ❌ CRÍTICO → não commitar | ✅ OK → pode commitar
```

> ⚠️ `--generate-golden` e `--validate` devem usar **exatamente os mesmos argumentos**. Argumentos diferentes invalidam a comparação. Regenerar o golden quando os argumentos de referência mudarem.

**Checkpoints monitorados:**

| Snapshot | O que verifica | Crítico? |
|---|---|---|
| `snapshot_utm_input` | Saída da Célula 8 — remoção de features (entrada do UTM) | Sim |
| `snapshot_utm_output` | Saída UTM unification — distribuição de Source/Term | Sim |
| `snapshot_medium_output` | Saída Medium unification — distribuição de Medium | Sim |
| `snapshot_fe_input` | **Entrada do Feature Engineering** — row count = tamanho do dataset pós-cutoff | **Sim** |
| `snapshot_fe_output` | Saída Feature Engineering | Não (aviso) |
| `snapshot_encoding_output` | Saída Encoding — feature count e nomes finais do modelo | Sim |

**`snapshot_fe_input` é o mais crítico:** uma variação de row count > 0.5% neste ponto indica que o cutoff de Feature Missing foi alterado — comportamento idêntico ao que ocorreu no incidente do Componente 5.

**Parâmetros de tolerância:**

```python
ROW_TOLERANCE  = 0.005   # 0.5% — diferença de row count aceitável
DIST_TOLERANCE = 0.02    # 2pp  — diferença de distribuição categórica aceitável
```

**Referência do golden baseline:** run `2a98e51c` — 48.812 registros, cutoff 2025-11-04, AUC 0.745, monotonia 100%. Gerado com `python -m V2.src.train_pipeline --capture-parity-snapshots --no-api-data --initial-matching email_telefone`. O `--validate` deve usar **os mesmos argumentos** — qualquer divergência de argumentos invalida a comparação.

---

## 13. Backlog (fora do escopo das Fases 1–3)

| Item | Descrição |
|---|---|
| Detecção contínua de training-serving skew | Adicionar ao monitoring orchestrator um check periódico que compara distribuições de features entre os dados que chegam em produção e o snapshot de treino — hoje o skew só é verificado pontualmente na Fase 2. Trigger de retreino quando skew acumulado ultrapassar threshold definido em `MonitoringConfig`. |
| Janela deslizante de treino (90–120 dias) | Em vez de treinar com todos os dados históricos pós-cutoff de missing, usar apenas os últimos N dias (ex: 90 ou 120). Motivação observada empiricamente: modelos com menos registros e mais recentes performaram melhor (AUC 0.751 com ~4 meses vs dados mais antigos) porque o comportamento do lead muda com o tempo — perguntas do formulário mudam, públicos mudam, lançamentos mudam. A janela deslizante descarta dados defasados automaticamente, sem depender de retreino manual para "esquecer" padrões obsoletos. Implementação: parâmetro `training_window_days` em `IngestionConfig`; `dataset_versioning.py` aplica `df[df['Data'] >= (data_max - timedelta(days=training_window_days))]` após o cutoff de missing. Testar 90 vs 120 vs sem janela e comparar AUC + lift + monotonia. |

---

*Documento de referência — atualizar ao final de cada fase com status e desvios encontrados.*
