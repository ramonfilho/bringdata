# Plano de Refatoração MLOps — Smart Ads V2

**Data:** 2026-02-23
**Status:** Ativo — v1.0
**Motivação imediata:** Segundo cliente confirmado, chegada em ~1 semana.
**Branch:** todo o desenvolvimento acontece em branch alternativa — `main` e produção não são afetados até merge explícito e validado.

---

## 1. Contexto e Motivação

O sistema atual foi construído para um único cliente (DevClub). O código funciona, mas contém 5 componentes duplicados entre treino e produção com divergências conhecidas que já causaram quebra em produção. Com um segundo cliente confirmado, qualquer expansão sem refatoração resultará em triplicação de código e divergências incontroláveis.

**Problema central:** não há Single Source of Truth para as transformações de dados. Treino e produção aplicam regras diferentes aos mesmos campos, o monitoramento não garante usar as mesmas funções que produção, e todas as configurações de cliente estão hardcoded no código.

---

## 2. Decisão Arquitetural

**Escolha: Option B — Shared Core Layer**

Rejeitamos Option A (consolidar arquivos com `config: dict`, depois extrair tipagem) porque o segundo cliente chega em ~1 semana — tocar os mesmos arquivos duas vezes é desperdício. Rejeitamos Option C (Pipeline as YAML spec) por overengineering para o volume atual.

**Princípio central:** toda transformação de dados vive em `src/core/` como função pura parametrizada por `ClientConfig`. Os pipelines se tornam orquestradores que importam de `core/`, nunca reimplementam transformações.

---

## 3. Nova Estrutura de Diretórios

```
smart_ads/V2/
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
| `UTMConfig` | Train + Produção + Monitoring | Regras de unificação UTM (case normalization, mapeamentos source/term) |
| `MediumConfig` | Train + Produção + Monitoring | Categorias válidas, descontinuadas, estratégia (binary_top3), mapeamento histórico |
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
- **`preprocessing.py`** — orquestra a sequência canônica de pré-processamento: `remove_duplicates` → `clean_columns` → `remove_campaign_features` → `rename_long_column_names` → `remove_technical_fields`; chama `utils.remove_columns` com as listas do config; treino e produção chamam `preprocess(df, config)` — sequência idêntica garantida por construção; monitoring chama a mesma função com wrapper de preservação de `decil`/`lead_score` em torno dela

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

Antes de implementar qualquer coisa, mapear todos os valores específicos de cliente que estão hardcoded no código. Sem essa lista completa, não é possível definir os sub-configs do `ClientConfig` corretamente.

**Processo:** percorrer cada arquivo linha a linha junto com o responsável pelo projeto, anotando:
1. Todo valor literal específico de cliente (strings, listas, dicionários, números de negócio) → tabela de hardcodes abaixo
2. Funções duplicadas entre arquivos que deveriam viver em `src/core/` → tabela de funções candidatas ao core abaixo

Não conta como hardcode constantes do algoritmo (ex: `random_state=42`) nem parâmetros já recebidos via argumento de função. Ambas as tabelas são atualizadas no documento ao final de cada arquivo varrido.

**Funções candidatas ao `src/core/` identificadas na varredura:**

| Função | Arquivos (treino) | Arquivos (produção) | Destino sugerido |
|---|---|---|---|
| `normalizar_telefone_robusto` | `matching_email_telefone.py`, `matching_robusto.py`, `matching_training.py`, `feature_engineering_training.py` | `engineering.py:14` | `core/utils.py` |
| `normalizar_email` | `matching_email_only.py`, `matching_email_telefone.py`, `matching_robusto.py`, `matching_training.py`, `matching_email_with_validation.py` | — (confirmar na varredura produção) | `core/utils.py` |
| `limpar_texto` + `normalizar_para_comparacao` | `category_unification.py`, `medium_training.py` (mesma lógica, nomes diferentes) | — (confirmar na varredura produção) | `core/utils.py` (consolidar em uma única função de normalização de texto) |
| mapeamento de colunas API→pipeline | `ingestion.py:584-601` (inline, sem função nomeada) | — (confirmar na varredura produção) | `core/ingestion.py` ou `core/preprocessing.py` |
| `remove_duplicates_per_sheet` | `ingestion.py` | `preprocessing.py` (`remove_duplicates`) | `core/ingestion.py` |
| `filter_sheets` | `ingestion.py` | — (provavelmente só treino — confirmar) | `core/ingestion.py` (condicionado a extrair lógica inline #57-#59 para config) |
| `remove_unnecessary_columns` + `remover_colunas_utm_ausentes` + `remover_features_desnecessarias` | `ingestion.py`, `column_unification_refactored.py`, `feature_removal.py` | `clean_columns` + `remove_technical_fields` + `remove_campaign_features` (`preprocessing.py`) | primitiva genérica `remove_columns(df, columns, errors='ignore')` em `core/utils.py`; as três funções nomeadas colapsam em chamadas parametrizadas a ela dentro de `core/preprocessing.py`, que define a sequência canônica única para treino, produção e monitoring — ordem garantida por construção, eliminando risco de training-serving skew |
| `consolidate_datasets` | `ingestion.py` | — (confirmar na varredura produção) | `core/ingestion.py` (sem condicionantes — completamente parametrizada) |
| `unificar_colunas_pesquisa` + `unificar_colunas_vendas` | `column_unification_refactored.py` | — (confirmar na varredura produção) | `core/column_unification.py` como função única `unify_columns(df, merge_rules)` — padrão genérico, apenas os nomes de colunas (#13–#20) vão para config |
| `aplicar_filtro_temporal` | `column_unification_refactored.py` | — (confirmar na varredura produção) | `core/column_unification.py` (sem condicionantes — lógica puramente genérica) |
| `aplicar_filtro_status_risco` | `column_unification_refactored.py` | — (confirmar na varredura produção) | `core/ingestion.py` (condicionado a extrair #22, #23, #62 para config; só executada se `ingestion.has_tmb: true` — #12) |
| `filtrar_vendas_devclub` | `column_unification_refactored.py` | — (confirmar na varredura produção) | `core/ingestion.py` como `filter_sales_by_product(df, product_keyword)` — sem condicionantes além do #24 já mapeado |
| `unificar_categorias_completo` | `category_unification.py` | `category_unification.py` (mesmo arquivo — já compartilhado entre treino, produção e monitoring; sem divergência) | `core/category_unification.py` como `unify_categories(df, config: CategoryConfig)` — hardcodes #27–#33 vão para config |
| detecção de colunas problemáticas (inline em `remover_features_desnecessarias`) | `feature_removal.py:38-70` | `preprocessing.py:176-181` (inline em `remove_campaign_features`) | `core/utils.py` como `detect_problematic_columns(df) -> List` — detecta colunas com nome vazio, None, NaN ou comprimento ≤ 2; genérica, sem hardcodes |
| `unificar_utm_source_term` | `utm_training.py` | `utm_unification.py` (`unify_utm_columns` + `unify_utm_source` + `unify_utm_term`) — divergência `.lower()` confirmada em `utm_unification.py:36` | `core/utm.py` como `unify_utm(df, config: UTMConfig)` — hardcodes #35, #63 e #67 vão para config |
| `extrair_publico_medium` | `medium_training.py` | `medium_unification.py` (`extract_medium_audience` + `unify_medium_by_actions`) — divergência confirmada: `mapping_dict` difere do treino (#7); `aplicar_unificacao_robusta` presente em ambos com lógicas distintas | `core/medium.py` como `unify_medium(df, config: MediumConfig)` — hardcodes #7, #36 e #37 vão para config |
| `criar_dataset_pos_cutoff` | `dataset_versioning_training.py` | — (provavelmente só treino — confirmar) | `core/dataset_versioning.py` — executado após todas as unificações; hardcodes #38, #39, #40 vão para config |
| `aplicar_janela_conversao` | `conversion_window.py` | — (só treino — produção não aplica) | `core/dataset_versioning.py` — sem condicionantes; hardcode #9 está no chamador e vai para config |
| `fazer_matching_email_only` + `fazer_matching_email_telefone` + `fazer_matching_robusto` + `fazer_matching_variantes` + `fazer_matching_email_with_validation` + `match_leads_to_sales_unified` | `matching_*.py` (6 arquivos) | — (confirmar na varredura produção) | `core/matching.py` como função única `match_leads(df_leads, df_vendas, config: MatchingConfig)` — estratégia controlada por config; hardcodes #41–#46 vão para config |
| `criar_features_derivadas` | `feature_engineering_training.py` | `engineering.py` (`create_derived_features`) — divergência confirmada: produção tem guard `arquivo_origem` (linha 183) para detectar contexto treino vs monitoring; some ao migrar para `core/` com `FeatureConfig` | `core/feature_engineering.py` como `create_features(df, config: FeatureConfig)` — hardcodes #41, #42, #47, #48 vão para config |
| `aplicar_encoding_estrategico` | `encoding_training.py` | `encoding.py` (`apply_categorical_encoding`) — confirmado: versão produção é canônica (tem feature registry, reordenação, `mapeamentos_especificos`); divergência de nomes de colunas ordinais confirmada (ver Seção 3) | `core/encoding.py` como `apply_encoding(df, config: EncodingConfig, artifacts)` — hardcodes #49, #50, #51, #64, #70, #71 vão para config |
| `UnionFind` (classe inline) | `training_model.py:410-428` | — (só treino — confirmar) | `core/utils.py` — algoritmo genérico de componentes conectados; sem hardcodes |
| `clean_column_names` (inline, linhas 179-182) | `training_model.py` | `encoding.py:238-240` (mesma regex aplicada em produção no encoding) | `core/utils.py` como `clean_column_names(df) -> df` — regex genérica `[^A-Za-z0-9_]`→`_`; sem hardcodes |
| `prepare_features` | — (só produção) | `prediction.py:179-229` | `core/utils.py` como `align_features(df, expected_features) -> df` — preenche features ausentes com 0 e reordena; sem hardcodes |

**Hardcodes mapeados — pipeline de treino varrido célula por célula (#1–#66):**

| # | Localização atual | Chave no YAML |
|---|---|---|
| 1 | `training_model.py:598-608` | `model.hyperparameters` |
| 2 | `training_model.py:184-198` | `feature.ordering_rules` |
| 3 | `train_pipeline.py:510-522` + `dataset_versioning_training.py:63-69` | Lista de features críticas a monitorar (duas definições sobrepostas — ver #40) → `feature.critical_columns` |
| 4 | `monitoring/data_quality.py:863` | `monitoring.medium_strategy` |
| 5 | `monitoring/data_quality.py:868` | `monitoring.model_name` |
| 6 | `ingestion.py:78-100` | `ingestion.tmb_detection_columns` |
| 7 | ~~`medium_production_training.py:36-119`~~ + `medium_unification.py:151-218` | **[dev/retreino — PARCIALMENTE RESOLVIDO]** `medium_production_training.py` agora deriva categorias válidas/descontinuadas automaticamente comparando dados atuais com `distribuicoes_esperadas.json` do modelo ativo (thresholds: válida ≥ 2.5%, nova ≥ 5%). Mapeamento de variantes históricas mantido. Ainda hardcoded em `medium_unification.py` (produção) — pendente ao migrar para `core/medium.py`. Ao migrar: `medium.variant_mappings` + `medium.threshold_valid` + `medium.threshold_new` no config. |
| 8 | `api/app.py:44` | `ingestion.bare_campaign_names` |
| 9 | `train_pipeline.py:652` (`janela_dias=20`) | `monitoring.conversion_window_days` |
| 10 | `training_model.py:27` | `model.mlflow_experiment_name` |
| 11 | `train_pipeline.py:248` | `"API Guru"` — nome da fonte de dados secundária | `ingestion.api_source_name` |
| 12 | `train_pipeline.py:263-273` | Lógica de filtro TMB sempre presente — nem todo cliente usa TMB | `ingestion.has_tmb` (bool) |
| 13 | `column_unification_refactored.py:64-67` | Texto literal da pergunta do formulário DevClub: `'Já investiu em algum curso online...'` | `ingestion.column_unification.pesquisa_merges` |
| 14 | `column_unification_refactored.py:80-83` | Texto literal da pergunta do formulário DevClub: `'O que mais te chama atenção na profissão de Programador?'` | `ingestion.column_unification.pesquisa_merges` |
| 15 | `column_unification_refactored.py:97-100` | Texto literal da pergunta do formulário DevClub: `'Atualmente, qual a sua faixa salarial?'` | `ingestion.column_unification.pesquisa_merges` |
| 16 | `column_unification_refactored.py:135-146` | Nomes de colunas de valor das plataformas Guru/TMB: `'Ticket (R$)'`, `'valor produtos'` | `ingestion.column_unification.valor_columns` |
| 17 | `column_unification_refactored.py:155-163` | Nomes de colunas de produto: `'Produto'`, `'Lançamento'`, `'nome produto'` | `ingestion.column_unification.produto_columns` |
| 18 | `column_unification_refactored.py:185-196` | Nomes de colunas de nome: `'Cliente Nome'`, `'nome contato'` | `ingestion.column_unification.nome_columns` |
| 19 | `column_unification_refactored.py:199-210` | Nomes de colunas de email: `'Cliente Email'`, `'email contato'` | `ingestion.column_unification.email_columns` |
| 20 | `column_unification_refactored.py:248-259` | Nomes de colunas de telefone: `'Telefone'`, `'telefone contato'` | `ingestion.column_unification.telefone_columns` |
| 21 | `column_unification_refactored.py:428` | Identificador da plataforma de vendas no nome do arquivo: `'guru'` | `ingestion.sales_platform_identifier` |
| 22 | `column_unification_refactored.py:433` | Status de venda aprovada: `'Aprovada'` | `ingestion.approved_status_value` |
| 23 | `column_unification_refactored.py:444` | Nome da coluna de risco TMB: `'Grau de risco'` | `ingestion.tmb_risk_column` |
| 24 | `column_unification_refactored.py:536`, `ingestion.py:649` | Palavra-chave para filtrar produtos do cliente: `'devclub'` / `'DevClub'` | `ingestion.product_filter_keyword` |
| 25 | `column_unification_refactored.py:312,317` | Nome da coluna de data no dataset de pesquisa: `'Data'` | `ingestion.pesquisa_date_column` |
| 26 | `column_unification_refactored.py:403` | Valor padrão do filtro de risco TMB: `tmb_risk_filter='all'` | `ingestion.tmb_risk_filter_default` (CLI pode sobrescrever) |
| 27 | `category_unification.py:95-116` | Lista de colunas categóricas a normalizar (`COLUNAS_CATEGORICAS`) | `ingestion.categorical_columns_to_normalize` |
| 28 | `category_unification.py:128-133` | Mapeamento semântico de variantes de `interesse_programacao` | `ingestion.category_mappings.interesse_programacao` |
| 29 | `category_unification.py:170-180` | Mapeamento semântico de variantes da pergunta sobre evento | `ingestion.category_mappings.o_que_quer_ver_evento` |
| 30 | `category_unification.py:216-222` | Mapeamento de variantes de faixa salarial | `ingestion.category_mappings.faixa_salarial` |
| 31 | `category_unification.py:241-255` | Mapeamento de variantes de situação profissional | `ingestion.category_mappings.o_que_faz_atualmente` |
| 32 | `category_unification.py:276-283` | Mapeamento de variantes de faixa etária | `ingestion.category_mappings.idade` |
| 33 | `category_unification.py:299-305` | Lista de colunas categóricas adicionais (`outras_colunas`) | `ingestion.other_categorical_columns` |
| 34 | `feature_removal.py:73-76` + `preprocessing.py:145-148` | Colunas a remover do modelo por data leakage: `'Campaign'`, `'Content'` | `feature.columns_to_remove` |
| 35 | `utm_training.py:50-53` + `utm_unification.py:39` | Valores UTM Source do histórico DevClub a agrupar em `'outros'`: `'fb'`, `'manychat'`, `'organico'`, `'youtube-bio'`, etc. (listas diferem entre treino e produção — produção tem 10 itens; unificar em config) | `utm.source_to_outros` |
| 36 | `medium_training.py:59` + `medium_unification.py:45` | Prefixo DevClub nos valores de Medium: `'ADV'` (ex: `ADV\|Aberto` → `Aberto`) | `medium.adv_prefix` |
| 37 | `medium_training.py:163-172` + `medium_unification.py:119-121` | Unificações manuais de case em nomes de públicos: `'ABERTO'`→`'Aberto'`, `'MIX QUENTE'`→`'Mix Quente'` (produção tem subset — só `'ABERTO'`→`'Aberto'`) | `medium.manual_unifications` |
| 38 | `dataset_versioning_training.py:33` | Data de corte do dataset: `'2025-03-01'` (quando features críticas passaram a ser preenchidas) | `ingestion.dataset_cutoff_date` |
| 39 | `dataset_versioning_training.py:55` | Coluna removida pós-cutoff por alto missing: `'Qual o seu nível em programação?'` | `feature.columns_to_remove_post_cutoff` |
| 40 | `dataset_versioning_training.py:63-69` | Lista de features com missing crítico a monitorar — **sobrepõe com #3** (mesma chave, dois locais no código) → unificar em `feature.critical_columns` ao implementar |
| 41 | `matching_*.py:múltiplas linhas` + `engineering.py:170` | Nome da coluna de email na pesquisa: `'E-mail'` | `matching.pesquisa_email_column` |
| 42 | `matching_*.py:múltiplas linhas` + `engineering.py:174` | Nome da coluna de telefone na pesquisa: `'Telefone'` | `matching.pesquisa_phone_column` |
| 43 | `matching_email_telefone.py` + `matching_robusto.py` | Validação de telefone brasileiro: código de país `55`, comprimento 10-11 dígitos | `matching.country_code` + `matching.phone_digits` |
| 44 | `matching_email_with_validation.py:35` | Path do arquivo de validação cruzada: `'../data/devclub/alunos TODOS.xlsx'` | `matching.alunos_todos_path` |
| 45 | `matching_email_with_validation.py:91-103` | Lista de nomes de produtos para validação cruzada (10 produtos DevClub) | `matching.validation_products` |
| 46 | `matching_email_with_validation.py:132` | Coluna de email no arquivo de alunos: `'Qual seu e-mail ?'` | `matching.alunos_email_column` |
| 47 | `feature_engineering_training.py:152-154` + `engineering.py:164` | Nome da coluna de nome no formulário: `'Nome Completo'` | `feature.pesquisa_name_column` |
| 48 | `feature_engineering_training.py:178-184` + `engineering.py:200-206` | Lista de colunas a remover após feature engineering (inclui nomes DevClub + variantes CRM antigo) | `feature.columns_to_drop_after_fe` |
| 49 | `encoding_training.py:46-53` + `encoding.py:108-128` | Categorias canônicas para encoding ordinal de `idade` e `faixa_salarial` — devem estar em sincronia com `mapa_idade` e `mapa_faixa` da Célula 7 (divergência de nomes: treino usa `'idade'` e `'faixa_salarial'`; produção usa `'Qual a sua idade?'` e `'Atualmente, qual a sua faixa salarial?'`) | `encoding.ordinal_variables` |
| 50 | `encoding_training.py:74-76` + `encoding.py:177-179` | 3 categorias Medium para binary_top3: `'Linguagem de programação'`, `'Aberto'`, `'Lookalike 2% Cadastrados - DEV 2.0 + Interesses'` | `medium.binary_top3_categories` |
| 51 | `encoding_training.py:105-106` + `encoding.py:209-210` | Feature removida após encoding: `'telefone_comprimento_8'` | `encoding.features_to_drop_after_encoding` |
| 52 | `training_model.py:675` | Stems de nomes de colunas de pesquisa para categorização no feature registry: `['gênero', 'idade', 'faz', 'faixa', 'cartão', 'estudou', 'faculdade', 'evento']` | `feature.survey_column_stems` |
| 53 | `training_model.py:691,853,987,1008,1036` + `encoding.py:299-300` + `prediction.py:69,73` | Template do nome do modelo com cliente e versão hardcoded: `f"v1_devclub_rf_{split_method}_single"` | `model.model_name_template` |
| 54 | `training_model.py:982` + `prediction.py:52` | Path do arquivo de modelo ativo: `configs/active_model.yaml` (pré-refactor — será `configs/active_models/devclub.yaml`) | resolvido pela estrutura de diretórios da Fase 1 |
| 55 | `training_model.py:77` | Path hardcoded para `api/business_config.py` na função `atualizar_business_config_com_recall` | `model.business_config_path` |
| 56 | `hyperparameter_tuning.py:328,331,344` | Thresholds de decisão para adotar params tunados: `>1.0%` (recomendado), `>0.3%` (marginal/considerar) — regra de negócio embutida no código | `model.tuning_improvement_thresholds` |
| 57 | `ingestion.py:233-236` | Convenção de nomes de arquivo DevClub: `'LF'` (arquivos de leads) e `'LF06'` (exceção — mantém abas Guru/TMB) | `ingestion.lf_file_prefix` + `ingestion.lf_guru_exception_files` |
| 58 | `ingestion.py:241` | Identificador de arquivo de vendas local a excluir: `'guru'` in filename (excluído porque substituído pela API) | `ingestion.local_sales_filename_identifier` |
| 59 | `ingestion.py:256` | Threshold de colunas preenchidas para detectar abas com survey: `> 10` | `ingestion.min_survey_columns` |
| 60 | `ingestion.py:381` | Prefixos de colunas de score a remover por pattern matching: `['score', 'faixa', 'pontuação', 'pontuacao', 'lead_score', 'decil']` | `ingestion.score_column_prefixes` |
| 61 | `column_unification_refactored.py:371` | Colunas UTM do dataset de vendas a remover (alta % ausentes): `['source', 'medium', 'campaign', 'content']` | `ingestion.vendas_utm_columns_to_remove` |
| 62 | `column_unification_refactored.py:446,448` | Valores de grau de risco TMB: `'Baixo'`, `'Médio'` | `ingestion.tmb_risk_values` |
| 63 | `utm_training.py:91-113` + `utm_unification.py:85,91,94,101` | Mapeamentos de Term: `'ig'`→`'instagram'`, `'fb'`→`'facebook'`; padrões `'--'` e `'{'` → `'outros'` | `utm.term_mappings` + `utm.term_outros_patterns` |
| 64 | `encoding_training.py:95` | Threshold de valores únicos para considerar coluna como categórica no one-hot: `<= 20` | `encoding.categorical_detection_max_unique` |
| 65 | `training_model.py:673` | Prefixos de colunas UTM para categorização no feature registry: `['Source_', 'Medium_', 'Term_']` | `feature.utm_feature_prefixes_for_registry` |
| 66 | `training_model.py:677` | Prefixos de features derivadas para categorização no feature registry: `['nome_', 'email_', 'telefone_', 'dia_semana']` | `feature.derived_feature_prefixes_for_registry` |
| 67 | `utm_unification.py:117` | Threshold de comprimento para classificar valor de Term como ID longo: `len > 10` | `utm.term_long_id_threshold` |
| 68 | `preprocessing.py:278-281` | Mapeamento de renomeação de colunas longas: `'Já investiu em algum curso online...'`→`'investiu_curso_online'`, `'O que mais te chama atenção...'`→`'interesse_programacao'` (mesmas strings de #13 e #14 — operação diferente) | `ingestion.column_rename_mapping` |
| 69 | `preprocessing.py:41-62` + `preprocessing.py:236-248` + `configs/devclub.yaml:cleaning.colunas_remover` | Lista de colunas a remover — treino e produção usam a mesma chave; colunas inexistentes ignoradas via `errors='ignore'`; substitui as duas funções estáticas de produção e o `cleaning.colunas_remover` do treino | `ingestion.columns_to_remove` (lista única) |
| 70 | `encoding.py:243-248` | Mapeamentos específicos de correção de nomes de colunas pós-normalização: `'O_que_voc_faz_atualmente_Sou_autonomo'`→`'..._aut_nomo'`, `'Tem_computador_notebook_SIM'`→`'...Sim'`, etc. (4 entradas DevClub) | `encoding.column_name_corrections` |
| 71 | `encoding.py:280` + `prediction.py:124` | ID do experimento MLflow hardcoded no path de artefatos: `"mlruns" / "1" / mlflow_run_id` | `model.mlflow_experiment_id` |
| 72 | `prediction.py:70,74` | Diretório legado de modelos: `"arquivos_modelo"` (fallback quando `active_model.yaml` falha) | `model.legacy_model_dir` |
| 73 | `orchestrator.py:286` | Índice da aba de survey no Google Sheets: `1` (segunda aba) | `monitoring.survey_sheet_tab_index` |
| 74 | `orchestrator.py:313` | Formato de data da aba 2 do Google Sheets DevClub: `'%d/%m/%Y %H:%M:%S'` (formato brasileiro) | `monitoring.sheet_date_format` |
| 75 | `orchestrator.py:318` | Offset de timezone Brasil: `timedelta(hours=-3)` (BRT) | `monitoring.timezone_offset_hours` |
| 76 | `orchestrator.py:371` | Índice da aba principal no Google Sheets: `0` | `monitoring.main_sheet_tab_index` |
| 77 | `orchestrator.py:386` | Valor de decil inválido a filtrar do histórico: `'MODELO 6 ML'` (nome do modelo antigo DevClub que aparecia no campo decil antes do modelo atual) | `monitoring.invalid_decil_values` |
| 78 | `orchestrator.py:398` | Formato de data da aba principal do Google Sheets: `'%Y-%m-%d %H:%M:%S'` (formato de saída do pipeline de produção) | `monitoring.main_sheet_date_format` |
| 79 | `orchestrator.py:422,423` | Decis de alta qualidade monitorados: `'D9'` e `'D10'` — top 20% num modelo de 10 decis; outro cliente pode usar número diferente de decis | `model.top_decils_to_monitor` |
| 80 | `orchestrator.py:676` | Janela de lookback do funil de leads: `hours=12` | `monitoring.funnel_lookback_hours` |
| 81 | `orchestrator.py:683,684` | Formato de exibição de data no sumário: `'%d/%m/%Y %H:%M'` (convenção brasileira) | `monitoring.display_date_format` |
| 82 | `orchestrator.py:752` | Fator de estimativa de eventos CAPI por lead: `1.3` (cada lead gera em média 1.3 eventos no DevClub) | `monitoring.capi_events_per_lead_estimate` |
| 83 | `monitoring/config.py:6-44` | Dict `THRESHOLDS` completo: distribution_drift categorical=0.15, numerical=2.0; missing_rate=0.20; score_distribution=0.10; operational no_leads_hours=6, no_capi_hours=6; capi_quality missing_rate=0.50, rejection_rate=0.10 — todos potencialmente diferentes por cliente | `monitoring.thresholds` (sub-chaves por categoria) |
| 84 | `monitoring/config.py:63-102` | Lista `MISSING_RATE_IGNORE_COLUMNS` — nomes de colunas DevClub específicos a ignorar no check de missing rate: `'Qual estado você mora?'`, `'Pontuação'`, `'Faixa'`, `'tem_computador'`, etc. | `monitoring.missing_rate_ignore_columns` |
| 85 | `monitoring/data_drift_detection.py:16` | URL do Google Sheets de produção DevClub hardcoded: `1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo` | `monitoring.sheets_url` (mesmo campo de #73/#76 — consolidar) |
| 86 | `monitoring/data_drift_detection.py:32-45` | Lista `FEATURES_CATEGORICAS` para análise de drift — nomes de features DevClub: `'genero'`, `'idade'`, `'o_que_faz_atualmente'`, `'faixa_salarial'`, `'tem_cartao_credito'`, etc. | `monitoring.drift_features_to_analyze` |
| 87 | `retraining_orchestrator.py:157-158` | Thresholds de mudança em missing rates no quality gate hook: `THRESHOLD_WARNING = 0.10` (10pp) e `THRESHOLD_CRITICAL = 0.20` (20pp) | `retrain.quality_gate_warning_threshold` + `retrain.quality_gate_critical_threshold` |
| 88 | `retraining_orchestrator.py:383` | Path do arquivo TMB com `'devclub'` hardcoded: `data/devclub/treino/tmb.xlsx` | resolvido por `ingestion.tmb_file_path` (mesmo campo do #6) |
| 89 | `retraining_orchestrator.py:130,289` | Padrão de nome do arquivo de metadata: `'model_metadata*.json'` — hardcoded em dois lugares; glob falha silenciosamente se o padrão não bater | `model.metadata_filename_pattern` |

**`api/business_config.py` — arquivo inteiro é DevClub-specific:**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 90 | `api/business_config.py:10` | Valor médio do produto: `PRODUCT_VALUE = 1649.73` (ponderado Guru + TMB, 149 conversões Dez/2025) | `business.product_value` |
| 91 | `api/business_config.py:29-40` | Taxas de conversão corrigidas por decil: `CONVERSION_RATES = {"D1": 0.001505, ..., "D10": 0.029262}` — calibradas para DevClub | `business.conversion_rates` |
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
| 105 | `api/capi_integration.py:514` | Decis da estratégia high quality: `if decil not in ['D09', 'D10']` — threshold cliente-specific | `capi.high_quality_decils` |
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
| 120 | `api/app.py:3152,3285` | Nome do bucket GCS para relatórios de validação como fallback: `'smart-ads-validation-reports'` | `infra.validation_bucket` |
| 121 | `api/app.py:3217-3220` | ⚠️ TEMPORÁRIO — datas de campanha hardcoded no endpoint `/validation/weekly`: `'2025-12-16'`, `'2026-01-12'` etc. — o próprio código tem TODO | remover — endpoint deve usar `PeriodCalculator` automaticamente |
| 122 | `api/app.py:3447` | Limite de leads por execução no polling Railway: `LIMIT 50` | `api.railway_polling_batch_size` |

**⚠️ Segurança (separado dos hardcodes de config):**
- `api/guru_config.py:13` — token Guru hardcoded diretamente no arquivo (`"user_token": "a0e3cf5b-..."`) — deve ir para env var `GURU_API_TOKEN`
- `api/meta_config.py:12` — access token Meta hardcoded no arquivo — deve ir para env var `META_ACCESS_TOKEN` (a env var já existe mas o token fica no arquivo como fallback comentado)

**Observações de qualidade (não hardcodes — corrigir separadamente):**
- `hyperparameter_tuning.py`: usa `print()` ao longo de todo o corpo em vez de `logger` — inconsistente com o restante do projeto

> **VARREDURA COMPLETA** — Train, produção, monitoring, retrain, api/ e validation/ inteiramente varridos. **153 hardcodes registrados** (+ dezenas de duplicatas documentadas). `validation/` 100% concluído: 15 arquivos varridos, 4 com zero hardcodes próprios (`matching.py`, `ml_monitoring_calculator.py`, `visualization.py`, `sheets_uploader.py`).

**Arquivos a varrer, organizados por pipeline:**

**`train_pipeline.py` e seus módulos — ✅ varrido:**
| Arquivo | Módulo |
|---|---|
| `src/train_pipeline.py` | Pipeline principal |
| `src/data_processing/ingestion.py` | data_processing |
| `src/data_processing/column_unification_refactored.py` | data_processing |
| `src/data_processing/category_unification.py` | data_processing |
| `src/data_processing/feature_removal.py` | data_processing |
| `src/data_processing/utm_training.py` | data_processing |
| `src/data_processing/medium_training.py` | data_processing |
| `src/data_processing/medium_production_training.py` | data_processing |
| `src/data_processing/dataset_versioning_training.py` | data_processing |
| `src/data_processing/conversion_window.py` | data_processing |
| `src/matching/matching_training.py` | matching |
| `src/matching/matching_robusto.py` | matching |
| `src/matching/matching_email_only.py` | matching |
| `src/matching/matching_email_with_validation.py` | matching |
| `src/matching/matching_email_telefone.py` | matching |
| `src/matching/matching_unified.py` | matching |
| `src/features/feature_engineering_training.py` | features |
| `src/features/encoding_training.py` | features |
| `src/model/training_model.py` | model |
| `src/model/hyperparameter_tuning.py` | model |
| `src/monitoring/data_quality.py` | monitoring |

**`production_pipeline.py` e seus módulos — ✅ varrido:**
| Arquivo | Módulo |
|---|---|
| `src/production_pipeline.py` | Pipeline de produção |
| `src/data_processing/preprocessing.py` | data_processing |
| `src/data_processing/utm_unification.py` | data_processing |
| `src/data_processing/medium_unification.py` | data_processing |
| `src/features/engineering.py` | features |
| `src/features/encoding.py` | features |
| `src/model/prediction.py` | model |

**`monitoring/orchestrator.py` e seus módulos — ✅ varrido:**
| Arquivo | Módulo |
|---|---|
| `src/monitoring/orchestrator.py` ✅ | monitoring |
| `src/monitoring/operational_monitor.py` ✅ (zero hardcodes — delega para config.py) | monitoring |
| `src/monitoring/capi_monitor.py` ✅ (zero hardcodes — delega para config.py) | monitoring |
| `src/monitoring/models.py` ✅ (zero hardcodes — estruturas genéricas) | monitoring |
| `src/monitoring/config.py` ✅ (#83, #84) | monitoring |
| `src/monitoring/data_drift_detection.py` ✅ (#85, #86 — script ad-hoc) | monitoring |

**`retrain/retraining_orchestrator.py` e seus módulos — ✅ varrido:**
| Arquivo | Módulo |
|---|---|
| `src/retrain/retraining_orchestrator.py` ✅ (#87, #88, #89) | retrain |
| `src/retrain/data_validation.py` ✅ (zero hardcodes — tudo via `self.config`) | retrain |
| `src/retrain/model_comparison.py` ✅ (zero hardcodes — Sprint 2, NotImplemented) | retrain |

**`validation/` — 🔄 em andamento:**

**`src/validation/validate_ml_performance.py` — ✅ varrido (#123–#127):**
| # | Arquivo | Hardcode | Campo sugerido |
|---|---------|----------|---------------|
| 123 | `validate_ml_performance.py:825` | Path default para dados de vendas: `'V2/data/devclub'` — contém nome do cliente | `validation.default_vendas_path` |
| 124 | `validate_ml_performance.py:902` | URL do Cloud Run como fallback de `INTERNAL_API_URL`: `'https://smart-ads-api-12955519745.us-central1.run.app'` — URL específica do projeto DevClub | `infra.api_url` (env var `INTERNAL_API_URL` já existe; remover fallback hardcoded) |
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
| 135 | `data_loader.py:1110` | URL do Cloud Run como default do `CAPILeadDataLoader`: `"https://smart-ads-api-12955519745.us-central1.run.app"` — duplicata de #124 no contexto de `__init__` | resolves via `infra.api_url` (mesmo que #124) |
| 136 | `data_loader.py:733` | `VALIDATION_REPORTS_BUCKET` fallback: `'smart-ads-validation-reports'` | resolves via `infra.validation_bucket` (mesmo que #120) |
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

| `src/validation/data_loader.py` ✅ | validation |
| `src/validation/campaign_classifier.py` ✅ | validation |
| `src/validation/matching.py` ✅ | validation — zero hardcodes próprios |
| `src/validation/metrics_calculator.py` ✅ | validation |
| `src/validation/report_generator.py` ✅ | validation |
| `src/validation/period_calculator.py` ✅ | validation |
| `src/validation/meta_reports_loader.py` ✅ | validation |
| `src/validation/ml_monitoring_calculator.py` ✅ | validation — zero hardcodes próprios |
| `src/validation/fair_campaign_comparison.py` ✅ | validation |
| `src/validation/sheets_uploader.py` ✅ | validation — zero hardcodes próprios |
| `src/validation/tmb_adjuster.py` ✅ | validation |
| `src/validation/guru_sales_extractor.py` ✅ | validation |
| `src/validation/capi_events_counter.py` ✅ | validation |
| `src/validation/visualization.py` ✅ | validation — zero hardcodes próprios |
| `src/validation/meta_api_client.py` ✅ | validation — hardcodes já cobertos por #104/#140/#141 |
| `src/validation/analyze_tmb_inadimplencia.py` ✅ | validation — hardcodes já cobertos por #90/#132 |
| `src/validation/tmb_adjuster.py` | validation |
| `src/validation/sheets_uploader.py` | validation |
| `src/validation/fair_campaign_comparison.py` | validation |
| `src/validation/ml_monitoring_calculator.py` | validation |
| `src/validation/analyze_tmb_inadimplencia.py` | validation |
| `src/validation/guru_sales_extractor.py` | validation |
| `src/validation/matching.py` | validation |
| `src/validation/meta_reports_loader.py` | validation |
| `src/validation/capi_events_counter.py` | validation |
| `src/validation/visualization.py` | validation |
| `src/validation/meta_api_client.py` | validation |

**`api/` — ✅ varrido (#90–#108 + alertas de segurança):**
| Arquivo | Observação |
|---|---|
| `api/business_config.py` ✅ | (#90–#98) arquivo inteiro é DevClub-specific |
| `api/railway_mapping.py` ✅ | (#99–#100) mapeamentos de formulário DevClub |
| `api/bigquery_sync.py` ✅ | (#101–#102) dataset/tabela DevClub hardcoded |
| `api/capi_integration.py` ✅ | (#103–#106) Pixel ID, event names, decis, país/moeda |
| `api/meta_integration.py` ✅ | (#107–#108) prefixos UTM DevClub, event names |
| `api/economic_metrics.py` ✅ | zero hardcodes próprios — importa tudo de `business_config.py` |
| `api/database.py` ✅ | zero hardcodes — tudo via env vars com defaults genéricos Railway |
| `api/guru_config.py` ✅ | ⚠️ token Guru hardcoded no código — mover para env var `GURU_API_TOKEN` |
| `api/meta_config.py` ✅ | ⚠️ token Meta hardcoded — já usa env var `META_ACCESS_TOKEN` mas token fica no arquivo |
| `api/app.py` ✅ | (#109–#122) padrões de campanha, CORS, column_mapping, batch sizes, URLs |

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
> **Ao migrar para `core/ingestion.py`:** comportamento dual-source controlado por `ingestion.has_tmb` (#12) + `ingestion.tmb_pedidos_detection_columns` (#154). A Célula 15.1 (filtro pós-matching) deve ser preservada como step separado em `train_pipeline.py` — não faz parte da lógica de `core/matching.py`, que não conhece risco TMB.

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
6. **Audit de divergências treino × produção** ⏳ — para cada função compartilhada (UTM, Medium, Categories, FE, Encoding): (1) capturar snapshot real em pickle (`capture_parity_snapshots=True` no `train_pipeline.main()`) na entrada da função durante uma execução do pipeline de treino; (2) injetar o mesmo snapshot nas duas implementações (treino e produção) separadamente e comparar outputs coluna a coluna; (3) documentar cada divergência encontrada; (4) para cada divergência, decidir qual implementação está correta — produção é canônica por padrão, mas cada caso deve ser verificado; (5) registrar a decisão como especificação para a implementação em `core/`. Executar antes de iniciar a Fase 2.

> `configs/templates/client_template.yaml` e `src/eda/generate_client_config.py` são adiados: o template emerge do `devclub.yaml` ao final da Fase 2; o gerador de EDA é construído na Fase 4, depois de dois configs escritos manualmente.

**Critério de saída:** ✅ `src/core/` existe com assinaturas; ✅ `ClientConfig.from_yaml('configs/clients/devclub.yaml').validate()` passa; ⏳ audit de divergências pendente — snapshots capturados, divergências documentadas e decisão registrada para cada função compartilhada.

### Fase 2 — Consolidação (Semana 2–3)

**Ciclo por componente** — para cada item abaixo, o loop é sempre o mesmo:
1. Implementar a função em `src/core/` parametrizada por config
2. Extrair os hardcodes desse componente para `configs/clients/devclub.yaml`
3. Atualizar imports nos pipelines afetados
4. Rodar shadow mode (velha e nova em paralelo, ao menos 1 ciclo de scoring em produção)
5. Validar paridade contra o snapshot da Fase 1
6. Remover implementação antiga

**Componentes em ordem de criticidade:**

1. `core/utm.py` — divergência `.lower()` ativa; hardcodes #35, #63, #67 → `UTMConfig`
   - Atualizar imports: `train_pipeline.py`, `production_pipeline.py`, `monitoring/orchestrator.py`
2. `core/feature_engineering.py` — unifica guards de colunas; hardcodes #41, #42, #47, #48 → `FeatureConfig`
   - Atualizar imports: `train_pipeline.py`, `production_pipeline.py`, `monitoring/orchestrator.py`
3. `core/encoding.py` — versão produção é canônica; hardcodes #49, #50, #51, #64, #70, #71 → `EncodingConfig`
   - Atualizar imports: `train_pipeline.py`, `production_pipeline.py`
4. `core/medium.py` — consolida 3 arquivos; hardcodes #7, #36, #37 → `MediumConfig` (etapa mais trabalhosa)
   - Atualizar imports: `train_pipeline.py`, `production_pipeline.py`, `monitoring/orchestrator.py`
5. `core/preprocessing.py` — sequência canônica única; hardcodes #34, #68, #69 → `FeatureConfig`/`IngestionConfig`
   - Atualizar: `train_pipeline.py`, `production_pipeline.py`, `monitoring/orchestrator.py` (com wrapper de preservação de `decil`/`lead_score`)
6. `core/category_unification.py` — já compartilhado; hardcodes #27–#33 → `CategoryConfig`
   - Atualizar imports: `train_pipeline.py`, `production_pipeline.py`, `monitoring/orchestrator.py`
7. Demais módulos `core/` (ingestion, matching, utils, dataset_versioning, column_unification) — mesmo ciclo
8. `validation/` — atualizar onde há reimplementação paralela

Ao concluir o último componente: `configs/clients/devclub.yaml` está completamente preenchido → gerar `configs/templates/client_template.yaml` a partir dele.

**Critério de saída:** treino e produção importam 100% de `core/`; `configs/clients/devclub.yaml` completamente preenchido; `ClientConfig.from_yaml('configs/clients/devclub.yaml').validate()` passa sem erros.

> **Shadow mode por componente:** a cada módulo migrado para `core/`, rodar a versão antiga e a nova em paralelo sobre os mesmos dados reais por pelo menos 1 ciclo de scoring antes de remover a versão antiga. Divergências detectadas em produção antes do corte, não depois.

> **Como executar o teste de paridade:**
> 1. Usar os snapshots do audit da Fase 1 — um pickle por função compartilhada (ex: `tests/fixtures/snapshot_utm_input.pkl`)
> 2. Para cada função migrada para `core/`, injetar o snapshot na implementação canônica de produção (baseline) e na nova implementação; comparar outputs coluna a coluna
> 3. Qualquer divergência entre a nova `core/` e o baseline é uma regressão a corrigir
>
> ```python
> # Exemplo para UTM — mesmo padrão para cada função compartilhada
> df_snapshot = pd.read_pickle("tests/fixtures/snapshot_utm_input.pkl")
>
> output_baseline = unify_utm_producao(df_snapshot.copy())          # implementação atual de produção
> output_novo     = core.utm.unify_utm(df_snapshot.copy(), config.utm)  # nova core/
>
> for col in output_baseline.columns:
>     diffs = (output_baseline[col] != output_novo[col]).sum()
>     if diffs > 0:
>         print(f"UTM - {col}: {diffs} divergências")
> ```
>
> Rodar **após cada componente consolidado** para confirmar que o comportamento foi preservado.
>
> **Por que o snapshot de treino é o input correto:** treino e produção recebem dados de fontes diferentes (Excel histórico vs API em tempo real) e passam por steps não-compartilhados antes e entre as funções compartilhadas — portanto não é possível comparar os dois pipelines de ponta a ponta. O snapshot serializado na entrada de cada função compartilhada durante uma execução de treino fornece um input idêntico para ambas as implementações, isolando a comparação ao comportamento da função em si. Qualquer divergência encontrada é de lógica de transformação, não de dados upstream. A `preprocessing.py` canônica garante estruturalmente que, em produção, os dados chegam às funções compartilhadas pela mesma sequência de passos — completando a garantia que o parity test não pode dar sozinho.
>
> **Três camadas de validação, cada uma cobrindo um risco distinto:**
>
> | Camada | O que verifica | Dados usados |
> |---|---|---|
> | Parity test (acima) | Implementação idêntica entre treino e nova `core/` | Snapshot real de treino |
> | Shadow mode (acima) | Nova `core/` não quebra com dados reais de produção | Leads reais em produção |
> | Métricas do modelo (`validate_ml_performance.py`) | Performance do modelo preservada após refactor | Dataset histórico |

### Fase 3 — Cliente B (Semana 3–4)

- Escrever `configs/clients/clientb.yaml` manualmente usando `configs/templates/client_template.yaml` como guia (gerado ao final da Fase 2)
- Executar `train_pipeline.main(config=clientb_config)`
- Validar primeiras predições do Cliente B
- Configurar `configs/active_models/clientb.yaml`

**Critério de saída:** pipeline completo roda para Cliente B sem alterar código, apenas config.

### Fase 4 — EDA Generator (após Cliente B estável)

Com dois configs escritos manualmente (`devclub.yaml` e `clientb.yaml`), o padrão está claro o suficiente para automatizá-lo:

- Construir `src/eda/generate_client_config.py`
- Validar rodando sobre o dataset DevClub e comparando output com `devclub.yaml` existente
- Usar para onboarding de clientes seguintes

### Fase 5 — NLP (Futuro, sem data)

- Definir interface final de `src/nlp/`
- Implementar extração de features de texto
- Registrar como step opcional no `FeatureConfig`

---

## 8. O Que NÃO Muda

- Estrutura de orquestração do `train_pipeline.py` (21 células)
- Estrutura de classe do `production_pipeline.py`
- Arquitetura de hooks do retrain orchestrator
- Integração MLflow
- Endpoints da API e banco de dados
- Funções de drift detection em `monitoring/data_quality.py`
- **Algoritmos** de matching (a lógica não muda; os 6 arquivos são consolidados em `core/matching.py` sem alterar o comportamento)
- **Algoritmo** de `category_unification.py` (o código migra para `core/category_unification.py` sem alterar a lógica)
- `model/decil_thresholds.py`

---

## 9. Compatibilidade com Sprint 2–3

`train_pipeline.main()` passa a aceitar `config: ClientConfig`. O retrain orchestrator deve ser atualizado simultaneamente na Fase 2 para passar o config correto. Sprints 2 e 3 (comparação de modelos e deploy automático) podem prosseguir após a conclusão da Fase 2. A Fase 1 não bloqueia nenhum sprint existente — é aditiva.

**Produção DevClub:** cada componente é migrado individualmente com teste de paridade antes de substituição. Sem big-bang replacement. API e banco de dados não são tocados.

---

## 10. Componentes Já Compartilhados (Referência)

| Componente | Usado por |
|---|---|
| `category_unification.py` | Todos os pipelines |
| `monitoring/data_quality.py` | Treino (captura) + monitoramento (check) |
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

## 11. Caminho para MLOps Nível 3

O refactor atual (Fases 1–3) leva o projeto do Nível 1 para o Nível 2. O Nível 3 exige infraestrutura adicional e só faz sentido com 5+ clientes ou quando o retreino manual virar gargalo operacional real.

| O que muda | Hoje | Nível 3 |
|---|---|---|
| Orquestração de pipelines | `train_pipeline.py` manual | Vertex AI Pipelines / Kubeflow |
| Feature engineering | Recalculada a cada treino | Feature Store (Vertex AI) |
| Trigger de retreino | Cloud Scheduler mensal fixo | Event-driven por drift detectado |
| Deploy de modelo | Manual / semi-automático (Sprint 2–3) | CI/CD com shadow deployment e traffic split |
| Versionamento de dados | Arquivos Excel / Sheets | Data versioning (DVC) + data contracts |
| Observabilidade | Logs + Slack | Dashboards de lineage, model cards automáticos |
| Multi-plataforma | Só Meta | Meta + Google + TikTok com mesmo modelo |

**Esforço estimado do estado atual até Nível 3:** 6–9 meses, time de 2–3 engenheiros. O `src/core/` deste refactor é o pré-requisito técnico — sem ele, migrar para Vertex AI Pipelines seria inviável.

---

---

## 12. Backlog (fora do escopo das Fases 1–3)

| Item | Descrição |
|---|---|
| Detecção contínua de training-serving skew | Adicionar ao monitoring orchestrator um check periódico que compara distribuições de features entre os dados que chegam em produção e o snapshot de treino — hoje o skew só é verificado pontualmente na Fase 2. Trigger de retreino quando skew acumulado ultrapassar threshold definido em `MonitoringConfig`. |
| Janela deslizante de treino (90–120 dias) | Em vez de treinar com todos os dados históricos pós-cutoff de missing, usar apenas os últimos N dias (ex: 90 ou 120). Motivação observada empiricamente: modelos com menos registros e mais recentes performaram melhor (AUC 0.751 com ~4 meses vs dados mais antigos) porque o comportamento do lead muda com o tempo — perguntas do formulário mudam, públicos mudam, lançamentos mudam. A janela deslizante descarta dados defasados automaticamente, sem depender de retreino manual para "esquecer" padrões obsoletos. Implementação: parâmetro `training_window_days` em `IngestionConfig`; `dataset_versioning.py` aplica `df[df['Data'] >= (data_max - timedelta(days=training_window_days))]` após o cutoff de missing. Testar 90 vs 120 vs sem janela e comparar AUC + lift + monotonia. |

---

*Documento de referência — atualizar ao final de cada fase com status e desvios encontrados.*
