# Plano de Refatoração MLOps — Smart Ads V2

**Data:** 2026-02-23
**Status:** Ativo — v1.0
**Motivação imediata:** Segundo cliente confirmado, chegada em ~1 semana.

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
| Medium | `medium_training.py` + `medium_production_training.py` | `medium_unification.py` | 3 arquivos com listas hardcoded |
| Feature engineering | `feature_engineering_training.py` | `engineering.py` | Guards de existência de colunas diferentes |
| Encoding | `encoding_training.py` | `encoding.py` | Produção tem feature registry + reordenação; treino não |
| Preprocessing | inline em `train_pipeline.py` | `preprocessing.py` | Lista de colunas diferente (YAML vs estática) |

---

## 4. Nova Estrutura de Diretórios

```
smart_ads/V2/
├── src/
│   ├── core/                        # NOVO — Single Source of Truth
│   │   ├── client_config.py         # ClientConfig dataclass
│   │   ├── utm.py
│   │   ├── medium.py
│   │   ├── feature_engineering.py
│   │   ├── encoding.py
│   │   └── preprocessing.py
│   ├── eda/                         # NOVO — EDA → Config Generator
│   │   └── generate_client_config.py
│   ├── nlp/                         # FUTURO — reservado na arquitetura
│   ├── train_pipeline.py            # Existente — importa de core/
│   ├── production_pipeline.py       # Existente — importa de core/
│   ├── monitoring/                  # Existente — importa de core/
│   ├── retrain/                     # Existente — sem mudança estrutural
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
| `UTMConfig` | Regras de unificação UTM (case normalization, mapeamentos) |
| `MediumConfig` | Categorias válidas, descontinuadas, estratégia (binary_top3 etc.) |
| `FeatureConfig` | Colunas críticas, flags de criação, `nlp_columns: []` (reservado) |
| `EncodingConfig` | Feature registry, ordem de colunas para o modelo |
| `ModelConfig` | Hiperparâmetros, nome do experimento MLflow |
| `MonitoringConfig` | Nome do modelo, janela de conversão, medium_strategy |
| `IngestionConfig` | Colunas de detecção TMB, identificadores, bare_campaign_names |

Interface: `ClientConfig.from_yaml(path)` + `ClientConfig.validate()` com mensagens acionáveis.

### 5.2 Módulo `src/core/`

Funções puras. Assinatura padrão: `transform(df, config: SubConfig, **artifacts) -> df`.

- **`utm.py`** — `unify_utm(df, config: UTMConfig)` — versão canônica com `.lower()` controlado por config
- **`medium.py`** — `unify_medium(df, config: MediumConfig)` — elimina os 3 arquivos atuais
- **`feature_engineering.py`** — `create_features(df, config: FeatureConfig)` — guards de colunas unificados
- **`encoding.py`** — `encode(df, config: EncodingConfig, artifacts)` — versão produção é canônica
- **`preprocessing.py`** — lista de colunas vem do config, não estática

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
| `monitoring/orchestrator.py` | Usa as mesmas funções `core/` que produção — proibido reimplementar localmente |
| `retrain/retraining_orchestrator.py` | Passa `ClientConfig` para `train_pipeline.main()`; hook architecture preservada |
| `validation/` | Usa `core/` para carregamento de dados, busca de vendas e matching |

---

## 7. Hardcodes a Mover para Config

<!-- TODO: Fazer varredura completa em train_pipeline.py e production_pipeline.py (e demais arquivos de src/) para confirmar que esta lista está completa. A análise identificou os casos mais críticos, mas podem existir outros valores hardcoded de cliente espalhados no código. -->

| # | Localização atual | Chave no YAML |
|---|---|---|
| 1 | `training_model.py:598-608` | `model.hyperparameters` |
| 2 | `training_model.py:184-198` | `feature.ordering_rules` |
| 3 | `train_pipeline.py:510-522` | `feature.critical_columns` |
| 4 | `monitoring/data_quality.py:863` | `monitoring.medium_strategy` |
| 5 | `monitoring/data_quality.py:868` | `monitoring.model_name` |
| 6 | `ingestion.py:78-100` | `ingestion.tmb_detection_columns` |
| 7 | `medium_production_training.py:36-57` | `medium.valid_categories` + `medium.discontinued_categories` |
| 8 | `api/app.py:44` | `ingestion.bare_campaign_names` |
| 9 | `conversion_window.py` | `monitoring.conversion_window_days` |
| 10 | `training_model.py:27` | `model.mlflow_experiment_name` |

---

## 8. Fases de Migração

### Fase 1 — Foundation (Semana 1–2)

- Implementar `ClientConfig` dataclass com todos os sub-configs
- Criar `configs/templates/client_template.yaml` documentando todas as chaves
- Rodar EDA no dataset DevClub e validar que o gerador produz config correta
- Criar `configs/clients/devclub.yaml` a partir dos hardcodes atuais
- Criar esqueleto de `src/core/` (arquivos com assinaturas definidas)
- Criar diretório `src/nlp/` com README de interface

**Critério de saída:** `ClientConfig.from_yaml('configs/clients/devclub.yaml').validate()` passa sem erros.

### Fase 2 — Consolidação (Semana 2–3)

Em ordem de criticidade de divergência:

1. `core/utm.py` — resolve divergência `.lower()` ativa (mais urgente)
2. `core/feature_engineering.py` — unifica guards de colunas
3. `core/encoding.py` — versão produção é canônica, absorve versão treino
4. `core/medium.py` — consolida 3 arquivos em 1 parametrizado por config (etapa mais trabalhosa)
5. `core/preprocessing.py` — lista de colunas vem do config
6. Atualizar `train_pipeline.py` para importar 100% de `core/`
7. Atualizar `production_pipeline.py` para importar 100% de `core/`
8. Atualizar `monitoring/orchestrator.py` para usar funções `core/` (mesmas de produção)
9. Atualizar `validation/` para usar `core/` onde há reimplementação paralela

**Critério de saída:** treino e produção aplicam exatamente as mesmas transformações, verificável por teste de paridade em amostra DevClub.

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
- `category_unification.py` — já é shared, mantém como está
- Funções de drift detection em `monitoring/data_quality.py`
- Algoritmos de matching
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

*Documento de referência — atualizar ao final de cada fase com status e desvios encontrados.*
