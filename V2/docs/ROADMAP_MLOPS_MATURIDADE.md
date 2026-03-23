# Roadmap de Maturidade MLOps — Smart Ads V2

**Criado:** 2026-03-22
**Framework de referência:** Google MLOps Maturity Levels (0, 1, 2)
**Propósito:** guia de direção de longo prazo. Não é um compromisso de execução imediata — cada item tem uma condição de negócio explícita para quando vale o investimento.

---

## Os três níveis no contexto do Smart Ads

| | Nível 0 | Nível 1 | Nível 2 |
|---|---|---|---|
| **O que define** | Tudo manual | Pipeline automatizado, skew eliminado, CT possível | CI/CD para o código ML em si |
| **Treino** | Notebook manual | Script versionado, pipeline reprodutível | Pipeline versionado, testado e deployado automaticamente |
| **Deploy de modelo** | Manual, esporádico | Semi-automático (script) | Automatizado com quality gate |
| **Monitoring** | Nenhum ou ad-hoc | Ativo com alertas | Drift dispara retreino automaticamente |
| **Retreino** | Quando alguém lembra | Scheduled (mensal) | Event-driven por drift ou volume |
| **Multi-cliente** | Impossível sem duplicar código | Config-driven (ClientConfig) | Config-driven + CI valida para todos os clientes |
| **Quem precisa** | 1 cliente, 1 eng | 1–4 clientes, 1–2 eng | 5+ clientes ou múltiplos eng editando simultaneamente |

---

## Onde o projeto está: fim do Nível 1

O refactor MLOps (branch `refactor/mlops-core`, 2026-03-22) entrega os fundamentos do Nível 1:

### ✅ O que foi resolvido pelo refactor

| Capacidade | Como foi resolvido |
|---|---|
| Training-serving skew eliminado | `src/core/` compartilhado por treino, produção e monitoring |
| Multi-cliente sem duplicar código | `ClientConfig` + `configs/clients/{client_id}.yaml` |
| Monitoring usa mesmas funções que produção | Estruturalmente garantido — mesma `core/` |
| Retreino atualiza config automaticamente | `training_model.py` grava `configs/active_models/{client_id}.yaml` |
| Deploy com rollback em segundos | Cloud Run blue-green via `deploy_capi.sh` |
| MLflow tracking centralizado | Cloud SQL PostgreSQL + `gs://smart-ads-mlflow/artifacts/` |

### ⚠️ O que falta para o Nível 1 estar 100%

**Gap 1 — Validação de dados antes do treino**

Hoje o pipeline de treino começa sem verificar se os dados de entrada têm problemas estruturais. Se o Sheets exportar com uma coluna faltando ou com encoding errado, o treino pode falhar silenciosamente ou produzir um modelo degradado.

*O que fazer:* adicionar um step de validação no início do `train_pipeline.py` — verificar schema esperado, ranges de valores críticos (ex: `decil` entre D01–D10), taxa de nulos em features obrigatórias. Implementável como uma função em `src/core/validation.py`.

*Condição para fazer:* antes do segundo cliente ativo. Com dois clientes, um erro de dados de um cliente não pode derrubar o pipeline do outro.

---

**Gap 2 — Retreino event-driven por drift**

Hoje o retreino é mensal fixo via Cloud Scheduler. O `retraining_orchestrator.py` tem a arquitetura de hooks (Sprint 1.1), mas os Sprints 2 e 3 — quality gate automático antes do deploy e trigger por drift — ainda não foram implementados.

*O que fazer (Sprint 2):* após o treino automático, comparar AUC e monotonia do novo modelo contra o modelo em produção. Só promover se o novo for melhor ou equivalente. Hoje essa comparação é feita manualmente.

*O que fazer (Sprint 3):* o `monitoring/orchestrator.py` já detecta drift de distribuição de features. Conectar esse sinal ao `retraining_orchestrator.py` como trigger — se drift acumulado ultrapassar threshold por N dias consecutivos, disparar retreino.

*Condição para Sprint 2:* qualquer momento — baixa complexidade, a arquitetura de hooks já existe.
*Condição para Sprint 3:* após Cliente B ativo e com volume suficiente de leads para que drift seja detectável (estimativa: 500+ leads/mês por cliente).

---

## Nível 2 — O que significa e quando faz sentido

O Nível 2 (Google) adiciona CI/CD para o **código ML em si** — não apenas para o modelo, mas para o pipeline de treino. Uma mudança em `core/utm.py` dispara automaticamente: build, testes unitários, validação de parity, e só então merge.

**Condição de negócio para o Nível 2:** múltiplos engenheiros editando `src/core/` simultaneamente, ou frequência de mudanças no pipeline ML que torne o processo manual lento demais. Com 1 engenheiro e 2–3 clientes, o custo de setup do CI/CD não se justifica.

**O que o Nível 2 exige no contexto do Smart Ads:**

| Capacidade | Implementação concreta | Pré-requisito |
|---|---|---|
| Testes unitários para `src/core/` | `pytest tests/core/ --client devclub --client clientb` (DT-2) | Dados de Cliente B disponíveis |
| CI pipeline | GitHub Actions: push → lint → testes → parity check | DT-2 concluído |
| Quality gate automatizado de modelo | Sprint 2 do `retraining_orchestrator.py` | Pode fazer antes |
| Versionamento formal de modelos | Vertex AI Model Registry substituindo `active_models/*.yaml` | 3+ clientes |
| CD de modelo | Deploy automatizado após quality gate | Vertex AI Model Registry em uso |

---

## Stack GCP completo — quando cada peça entra

A visão de stack abaixo é o estado-alvo de longo prazo. Cada componente tem uma condição concreta que justifica o investimento.

### Já em uso ✅

| Componente | Papel atual | Status |
|---|---|---|
| **Cloud Run** | Serving da API (predição, webhooks, CAPI) | Produção, estável |
| **Cloud Scheduler** | Trigger mensal do monitoring e retreino | Produção |
| **MLflow + Cloud SQL** | Experiment tracking, artifact storage | Produção desde 17/03/2026 |
| **Cloud Storage** | Artifacts do MLflow (`gs://smart-ads-mlflow/`) | Produção |
| **Cloud Logging** | Logs da API em produção | Produção |

---

### Nível 1 completo (próximos 1–2 meses)

| Componente | Papel | Condição para adotar |
|---|---|---|
| **`src/core/validation.py`** (novo) | Schema check pré-treino | Antes do segundo cliente ativo |
| **`retraining_orchestrator.py` Sprint 2** | Quality gate automático pós-treino | Qualquer momento |
| **`retraining_orchestrator.py` Sprint 3** | Trigger de retreino por drift | 500+ leads/mês por cliente |

---

### Nível 2 (2–5 clientes, 1–2 anos)

| Componente | Papel | Substitui | Condição para adotar |
|---|---|---|---|
| **GitHub Actions (CI)** | Testa `src/core/` automaticamente a cada push | Validação manual | DT-2 + 2 clientes ativos |
| **Vertex AI Model Registry** | Versionamento e promoção formal de modelos | `configs/active_models/*.yaml` manual | 3+ clientes |
| **Artifact Registry (Docker)** | Versionar imagens do Cloud Run formalmente | Tagging informal atual | CI pipeline ativo |
| **Looker Studio** | Dashboard de performance por cliente e lançamento | Relatórios gerados pelo script de validação | Qualquer momento — baixo esforço |

---

### Nível 3 / Stack GCP completo (5+ clientes ou escala B2B)

Estes componentes fazem sentido quando o volume de dados ou de clientes tornar a infraestrutura atual um gargalo real — não antes.

| Componente | Papel | Substitui | Condição real para adotar |
|---|---|---|---|
| **Pub/Sub + Apache Beam + Dataflow** | Ingestão e processamento de leads em streaming | Webhook síncrono no Cloud Run | Volume de leads onde o webhook síncrono vira gargalo (estimativa: 10k+ leads/dia), ou múltiplas fontes de dados simultâneas |
| **BigQuery como Feature Store** | Features pré-computadas e versionadas, compartilhadas entre treino e serving | Features computadas a cada treino via `src/core/` | Quando features forem caras de computar ou compartilhadas entre múltiplos modelos |
| **Kubeflow / Vertex AI Pipelines** | Orquestração do pipeline de treino com dependências explícitas | `train_pipeline.py` manual | Quando `train_pipeline.py` tiver múltiplos engenheiros editando ou frequência de treino > diária |
| **Vertex AI Endpoints** | Serving gerenciado com A/B testing e traffic splitting nativos | Cloud Run | Quando Cloud Run custar mais que Vertex AI na escala atingida, ou quando A/B testing de modelos for necessário |
| **Vertex AI Model Monitoring** | Drift detection gerenciado e integrado ao Vertex AI | `monitoring/orchestrator.py` customizado | Quando o monitoring customizado não escalar (estimativa: 5+ clientes com modelos distintos) |
| **CI/CD para modelos (Nível 2 Google)** | Push no pipeline ML → build → testes → deploy automático | Deploy manual via `deploy_capi.sh` | Múltiplos engenheiros editando simultaneamente |

> **Nota sobre Vertex AI Model Monitoring vs monitoring customizado:** o monitor customizado atual é mais barato e mais flexível para o negócio de lançamentos (ciclos de 20–30 dias, métricas de ROAS e CPL que nenhum serviço gerenciado conhece). Migrar para Vertex AI Model Monitoring só faz sentido quando o monitoring customizado não escalar mais em complexidade de manutenção.

> **Nota sobre MLflow:** permanece relevante mesmo no stack completo — é portável, já está funcionando e trackeia experimentos de forma que o Vertex AI não replica completamente. Não há razão para substituir.

---

## Backlog ordenado por prioridade

Lista única com todos os próximos passos em ordem. Cada item tem a condição que o desbloqueia ou o torna necessário.

| # | Item | Condição | Onde está documentado |
|---|---|---|---|
| 1 | **Capturar golden snapshot do monitoring** (Etapa 1E) | Fazer antes do merge — referência pré-refactor | `CHECKLIST_DEPLOY_REFACTOR.md` Etapa 1E |
| 2 | **Abrir e mergear o PR** (`refactor/mlops-core` → `main`) | Golden snapshot capturado | `CHECKLIST_DEPLOY_REFACTOR.md` Etapa 2 |
| 3 | **Deploy sem tráfego + validações** (Pilares A, B, C, D) | PR merged | `CHECKLIST_DEPLOY_REFACTOR.md` Etapas 3–4 |
| 4 | **Migrar tráfego para nova revisão** | Todas as validações da Etapa 4 passaram | `CHECKLIST_DEPLOY_REFACTOR.md` Etapa 5 |
| 5 | **Confirmar job de monitoring diário** | Dia seguinte ao deploy | `CHECKLIST_DEPLOY_REFACTOR.md` Etapa 6B |
| 6 | **Atualizar `ARQUITETURA_SISTEMA_COMPLETA.md`** | Deploy concluído — doc está desatualizado desde fev/2026 | `INDICE_DOCUMENTACAO.md` |
| 7 | **`src/core/validation.py`** — schema check pré-treino | Antes do segundo cliente ativo. Sem isso, dado ruim do Cliente B pode corromper o pipeline silenciosamente | `ROADMAP_MLOPS_MATURIDADE.md` Gap 1 |
| 8 | **Sprint 2 `retraining_orchestrator.py`** — quality gate automático pós-treino | Qualquer momento — baixa complexidade, arquitetura de hooks já existe | `ROADMAP_MLOPS_MATURIDADE.md` Gap 2 |
| 9 | **Dados do Cliente B chegam** | Depende do cliente | — |
| 10 | **DT-2 — testes unitários `src/core/`** | Dados do Cliente B disponíveis — testes devem ser parametrizados com dois `ClientConfig` reais | `PLANO_REFACTOR_MLOPS.md` DT-2 |
| 11 | **Fase 3b — Onboarding Cliente B** (YAML + treino + validação) | Dados do Cliente B + itens 7 e 10 concluídos | `PLANO_REFACTOR_MLOPS.md` Fase 3b |
| 12 | **Fase 4 — EDA Generator** (`src/eda/generate_client_config.py`) | Cliente B estável — padrão claro o suficiente para automatizar | `PLANO_REFACTOR_MLOPS.md` Fase 4 |
| 13 | **GitHub Actions CI** — testes automáticos a cada push em `src/core/` | DT-2 concluído + 2 clientes ativos | `ROADMAP_MLOPS_MATURIDADE.md` Nível 2 |
| 14 | **Sprint 3 `retraining_orchestrator.py`** — trigger de retreino por drift | 500+ leads/mês por cliente (volume mínimo para drift ser detectável) | `ROADMAP_MLOPS_MATURIDADE.md` Gap 2 Sprint 3 |
| 15 | **Looker Studio dashboard** | Qualquer momento após Cliente B ativo — baixo esforço, alto valor de apresentação | `ROADMAP_MLOPS_MATURIDADE.md` Nível 2 |
| 16 | **Vertex AI Model Registry** | 3+ clientes — substituir `configs/active_models/*.yaml` manual | `ROADMAP_MLOPS_MATURIDADE.md` Nível 2 |
| 17 | **Stack GCP completo** (Pub/Sub, Dataflow, Kubeflow, Feature Store, Vertex AI Endpoints) | 5+ clientes ou escala B2B | `ROADMAP_MLOPS_MATURIDADE.md` Nível 3 |

---

## Relação com outros documentos

- **`PLANO_REFACTOR_MLOPS.md`** — detalha o que foi feito para chegar ao Nível 1. Leia para entender decisões passadas.
- **`adsmarter_02_execução.md`** — visão de negócio que motivou o roadmap técnico.
- **`ARQUITETURA_SISTEMA_COMPLETA.md`** — arquitetura atual do sistema (atualizar após deploy do refactor).
- **`CHECKLIST_DEPLOY_REFACTOR.md`** — runbook para o deploy imediato do refactor.
