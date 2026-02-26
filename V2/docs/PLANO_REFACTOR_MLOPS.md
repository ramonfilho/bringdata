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

## 3. Divergências Ativas a Corrigir

| Componente | Arquivo Treino | Arquivo Produção | Divergência |
|---|---|---|---|
| UTM | `utm_training.py` | `utm_unification.py` | Produção aplica `.lower()`, treino não |
| Medium | `medium_training.py` + `medium_production_training.py` | `medium_unification.py` | Função `aplicar_unificacao_robusta` com lógica diferente entre treino e produção; 3 arquivos com listas de mapeamento distintas |
| Feature engineering | `feature_engineering_training.py` | `engineering.py` | Guards de existência de colunas diferentes |
| Encoding | `encoding_training.py` | `encoding.py` | Produção tem feature registry + reordenação; treino não. Adicionalmente: treino usa nomes de colunas normalizados (`'idade'`, `'faixa_salarial'`) no ordinal encoding; produção usa nomes longos do formulário (`'Qual a sua idade?'`, `'Atualmente, qual a sua faixa salarial?'`) |
| Preprocessing | inline em `train_pipeline.py` | `preprocessing.py` | Lista de colunas diferente (YAML vs estática) |
| Limpeza de nomes de colunas | `training_model.py:179-182` (inline antes do fit) | — (confirmar na varredura produção) | Regex `[^A-Za-z0-9_]`→`_` aplicada no treino; momento e forma de aplicação na produção a confirmar |

---

## 4. Nova Estrutura de Diretórios

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

## 5. Componentes Novos

### 5.1 ClientConfig (`src/core/client_config.py`)

Dataclass tipado carregado de `configs/clients/{client}.yaml`. Sub-configs:

| Sub-config | Responsabilidade |
|---|---|
| `IngestionConfig` | Colunas de detecção TMB, identificadores, bare_campaign_names, prefixos de arquivo, cutoff date |
| `UTMConfig` | Regras de unificação UTM (case normalization, mapeamentos source/term) |
| `MediumConfig` | Categorias válidas, descontinuadas, estratégia (binary_top3), mapeamento histórico |
| `CategoryConfig` | Colunas categóricas a normalizar e mapeamentos semânticos por coluna |
| `MatchingConfig` | Estratégia de matching, colunas de identificador, path de validação cruzada |
| `FeatureConfig` | Colunas críticas, colunas a remover, prefixos de categorização do registry, `nlp_columns: []` (reservado) |
| `EncodingConfig` | Variáveis ordinais, categorias binary_top3, features a remover pós-encoding, threshold de detecção |
| `ModelConfig` | Hiperparâmetros, nome do experimento MLflow, template do nome do modelo, thresholds de tuning |
| `MonitoringConfig` | Nome do modelo, janela de conversão, medium_strategy |

Interface: `ClientConfig.from_yaml(path)` + `ClientConfig.validate()` com mensagens acionáveis.

> **`ClientConfig` é um arquivo vivo.** A cada novo cliente, a varredura pode revelar necessidades de parametrização que clientes anteriores não tinham — seja um campo novo em um sub-config existente ou um sub-config inteiro novo. Quando isso acontecer, atualizar o dataclass e o `client_template.yaml`. Todo campo novo deve ter um **valor default**, garantindo que os clientes já existentes continuem funcionando sem alterar seus YAMLs.

### 5.2 Módulo `src/core/`

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

### 5.3 EDA → Config Generator (`src/eda/generate_client_config.py`)

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

### 5.4 NLP Module (`src/nlp/`) — Futuro

Para campos de texto livre em respostas de formulário (sentimento, intenção, nível de maturidade). Fora do escopo do sprint atual. O diretório é criado com README de interface. `FeatureConfig` já prevê o campo `nlp_columns: []`.

---

## 6. Regras de Sincronização por Pipeline

| Pipeline | Regra |
|---|---|
| `train_pipeline.py` | Importa 100% de `core/` para transformações; recebe `config: ClientConfig` |
| `production_pipeline.py` | Importa 100% de `core/`; comportamento idêntico ao treino por construção |
| `monitoring/orchestrator.py` | Chama `core.preprocessing.preprocess(df, config)` com wrapper de preservação de `decil`/`lead_score` em torno dela — mesma sequência canônica de treino e produção, garantindo ausência de training-serving skew |
| `retrain/retraining_orchestrator.py` | Passa `ClientConfig` para `train_pipeline.main()`; hook architecture preservada |
| `validation/` | Usa `core/` para carregamento de dados, busca de vendas e matching |

---

## 7. Varredura e Mapeamento de Hardcodes (Pré-requisito da Fase 1)

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
| 7 | `medium_production_training.py:36-119` + `medium_unification.py:151-218` | Categorias válidas, descontinuadas e mapeamento histórico completo (~50 variantes) → `medium.valid_categories` + `medium.discontinued_categories` + `medium.category_mappings` (listas diferem entre treino e produção — confirmar ao consolidar) |
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
| 49 | `encoding_training.py:46-53` + `encoding.py:108-128` | Categorias canônicas para encoding ordinal de `idade` e `faixa_salarial` — devem estar em sincronia com `mapa_idade` e `mapa_faixa` da Célula 7 (divergência de nomes: treino usa normalizados, produção usa nomes longos — ver Seção 3) | `encoding.ordinal_variables` |
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

**Observações de qualidade (não hardcodes — corrigir separadamente):**
- `hyperparameter_tuning.py`: usa `print()` ao longo de todo o corpo em vez de `logger` — inconsistente com o restante do projeto

> Pipelines de treino e produção varridos — 72 hardcodes registrados. `orchestrator.py` varrido — 82 hardcodes no total. Demais módulos de monitoring e retrain pendentes.

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

**`monitoring/orchestrator.py` e seus módulos — ⏳ em andamento:**
| Arquivo | Módulo |
|---|---|
| `src/monitoring/orchestrator.py` ✅ | monitoring |
| `src/monitoring/operational_monitor.py` | monitoring |
| `src/monitoring/capi_monitor.py` | monitoring |
| `src/monitoring/models.py` | monitoring |
| `src/monitoring/config.py` | monitoring |
| `src/monitoring/data_drift_detection.py` | monitoring |

**`retrain/retraining_orchestrator.py` e seus módulos — ⏳ pendente:**
| Arquivo | Módulo |
|---|---|
| `src/retrain/retraining_orchestrator.py` | retrain |
| `src/retrain/data_validation.py` | retrain |
| `src/retrain/model_comparison.py` | retrain |

**Arquivos presentes nos módulos mas não importados diretamente — também varrer:**
| Arquivo | Observação |
|---|---|
| `src/data_processing/column_unification.py` | Versão antiga (não refatorada) — verificar se ainda é usada |
| `src/data_processing/devclub_filtering_training.py` | Filtros específicos DevClub |
| `src/features/utm_removal.py` | Remoção de UTMs |
| `api/app.py` | Padrões de campanha e URLs hardcoded |

**Critério de conclusão:** todos os arquivos percorridos, tabela acima atualizada com todos os hardcodes encontrados, nenhum valor específico de cliente sem mapeamento para uma chave de config.

---

## 8. Fases de Migração

### Fase 1 — Foundation (Semana 1–2)

1. **Executar varredura completa de hardcodes** (seção 7) e finalizar a tabela de mapeamento
2. **Implementar `ClientConfig`** dataclass com todos os sub-configs identificados na varredura
3. **Criar `configs/templates/client_template.yaml`** documentando todas as chaves do `ClientConfig`
4. **Construir `src/eda/generate_client_config.py`** — o gerador de config a partir de dados brutos
5. **Rodar o EDA no dataset DevClub** e validar que o output cobre todos os campos do template
6. **Criar `configs/clients/devclub.yaml`** combinando o output do EDA com os hardcodes mapeados na varredura
7. **Criar esqueleto de `src/core/`** — arquivos com assinaturas definidas, sem implementação ainda
8. **Criar `src/nlp/`** com README de interface

**Critério de saída:** `ClientConfig.from_yaml('configs/clients/devclub.yaml').validate()` passa sem erros.

### Fase 2 — Consolidação (Semana 2–3)

Em ordem de criticidade de divergência:

1. `core/utm.py` — resolve divergência `.lower()` ativa (mais urgente)
   - Atualizar import em `train_pipeline.py` → `core.utm`
   - Atualizar import em `production_pipeline.py` → `core.utm`
   - Atualizar import em `monitoring/orchestrator.py` → `core.utm`
2. `core/feature_engineering.py` — unifica guards de colunas
   - Atualizar import em `train_pipeline.py` → `core.feature_engineering`
   - Atualizar import em `production_pipeline.py` → `core.feature_engineering`
   - Atualizar import em `monitoring/orchestrator.py` → `core.feature_engineering`
3. `core/encoding.py` — versão produção é canônica, absorve versão treino
   - Atualizar import em `train_pipeline.py` → `core.encoding`
   - Atualizar import em `production_pipeline.py` → `core.encoding`
4. `core/medium.py` — consolida 3 arquivos em 1 parametrizado por config (etapa mais trabalhosa)
   - Atualizar import em `train_pipeline.py` → `core.medium`
   - Atualizar import em `production_pipeline.py` → `core.medium`
   - Atualizar import em `monitoring/orchestrator.py` → `core.medium`
5. `core/preprocessing.py` — define sequência canônica única: `remove_duplicates` → `clean_columns` → `remove_campaign_features` → `rename_long_column_names` → `remove_technical_fields`; listas de colunas vêm do config; chama `core/utils.remove_columns` internamente
   - Atualizar `train_pipeline.py` → chamar `core.preprocessing.preprocess(df, config)`
   - Atualizar `production_pipeline.py` → chamar `core.preprocessing.preprocess(df, config)`
   - Atualizar `monitoring/orchestrator.py` → chamar `core.preprocessing.preprocess(df, config)` com wrapper de preservação de `decil`/`lead_score`
6. `core/category_unification.py` — já compartilhado; migrar para `core/` formaliza o contrato
   - Atualizar import em `train_pipeline.py` → `core.category_unification`
   - Atualizar import em `production_pipeline.py` → `core.category_unification`
   - Atualizar import em `monitoring/orchestrator.py` → `core.category_unification`
7. Atualizar `train_pipeline.py` para importar 100% de `core/`
8. Atualizar `production_pipeline.py` para importar 100% de `core/`
9. Atualizar `monitoring/orchestrator.py` para importar 100% de `core/` (itens 1–6 acima cobrem os módulos de transformação; verificar se restam outros)
10. Atualizar `validation/` para usar `core/` onde há reimplementação paralela

**Critério de saída:** treino e produção aplicam exatamente as mesmas transformações, verificável por teste de paridade em amostra DevClub.

> **Shadow mode por componente:** a cada módulo migrado para `core/`, rodar a versão antiga e a nova em paralelo sobre os mesmos dados reais por pelo menos 1 ciclo de scoring antes de remover a versão antiga. Divergências detectadas em produção antes do corte, não depois.

> **Como executar o teste de paridade:**
> 1. Separar um snapshot fixo de ~500 leads reais do DevClub (salvar em `tests/fixtures/paridade_sample.csv`)
> 2. Rodar a amostra pelos dois pipelines até o ponto pós-encoding (antes do modelo)
> 3. Comparar os DataFrames coluna por coluna — qualquer diferença é uma divergência
>
> ```python
> df_train = train_pipeline.preprocess(amostra)
> df_prod  = production_pipeline.preprocess(amostra)
>
> assert df_train.shape == df_prod.shape
> for col in df_train.columns:
>     diffs = (df_train[col] != df_prod[col]).sum()
>     if diffs > 0:
>         print(f"{col}: {diffs} divergências")
> ```
>
> Rodar **antes** de iniciar a Fase 2 (estabelece baseline e revela divergências não mapeadas) e **após cada componente consolidado** (confirma que o comportamento foi preservado).

### Fase 3 — Cliente B (Semana 3–4)

- Rodar EDA no dataset do Cliente B
- Gerar e revisar `configs/clients/clientb.yaml`
- Executar `train_pipeline.main(config=clientb_config)`
- Validar primeiras predições do Cliente B
- Configurar `configs/active_models/clientb.yaml`

**Critério de saída:** pipeline completo roda para Cliente B sem alterar código, apenas config.

### Fase 4 — NLP (Futuro, sem data)

- Definir interface final de `src/nlp/`
- Implementar extração de features de texto
- Registrar como step opcional no `FeatureConfig`

---

## 9. O Que NÃO Muda

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

## 10. Compatibilidade com Sprint 2–3

`train_pipeline.main()` passa a aceitar `config: ClientConfig`. O retrain orchestrator deve ser atualizado simultaneamente na Fase 2 para passar o config correto. Sprints 2 e 3 (comparação de modelos e deploy automático) podem prosseguir após a conclusão da Fase 2. A Fase 1 não bloqueia nenhum sprint existente — é aditiva.

**Produção DevClub:** cada componente é migrado individualmente com teste de paridade antes de substituição. Sem big-bang replacement. API e banco de dados não são tocados.

---

## 11. Componentes Já Compartilhados (Referência)

| Componente | Usado por |
|---|---|
| `category_unification.py` | Todos os pipelines |
| `monitoring/data_quality.py` | Treino (captura) + monitoramento (check) |
| `model/decil_thresholds.py` | Produção + monitoramento |
| Hook architecture (retrain) | Retrain orchestrator |

---

## 12. Caminho para MLOps Nível 3

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

## 13. Backlog (fora do escopo das Fases 1–3)

| Item | Descrição |
|---|---|
| Detecção contínua de training-serving skew | Adicionar ao monitoring orchestrator um check periódico que compara distribuições de features entre os dados que chegam em produção e o snapshot de treino — hoje o skew só é verificado pontualmente na Fase 2. Trigger de retreino quando skew acumulado ultrapassar threshold definido em `MonitoringConfig`. |

---

*Documento de referência — atualizar ao final de cada fase com status e desvios encontrados.*
