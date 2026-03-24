# Roadmap MLOps — Smart Ads V2

**Contexto em 30 segundos:** o refactor (`refactor/mlops-core`) está completo e validado. O sistema suporta múltiplos clientes via config, sem duplicar código. Este documento é o guia do que fazer a seguir — em ordem, com a condição que desbloqueia cada item.

Documentos relacionados: `CHECKLIST_DEPLOY_REFACTOR.md` (deploy imediato) · `PLANO_REFACTOR_MLOPS.md` (histórico do refactor) · `ARQUITETURA_SISTEMA_COMPLETA.md` (como o sistema funciona)

---

## Stack atual (o que já está em produção)

Cloud Run · Cloud Scheduler · MLflow + Cloud SQL · Cloud Storage · Cloud Logging · PostgreSQL

---

## Backlog — ordem de execução

### Fase imediata — deploy do refactor

- [ ] **1. Capturar golden snapshot do monitoring**
  Rodar `MonitoringOrchestrator.run_daily_check(reference_date=date(2026, 3, 15), dry_run=True)` e salvar output em `docs/monitoring_golden_snapshot.json`. Serve de referência pré-refactor para comparação pós-deploy.
  **→ Fazer antes do merge. Instrução completa: `CHECKLIST_DEPLOY_REFACTOR.md` Etapa 1E.**

- [ ] **2. Abrir e mergear o PR** (`refactor/mlops-core` → `main`)
  **→ Desbloqueado quando:** item 1 concluído.

- [ ] **3. Deploy sem tráfego + validações dos 4 pilares**
  Pilar A (scores idênticos) · Pilar B (monitoring responde) · Pilar C (matching sem regressão) · Pilar D (treino → serve funciona).
  **→ Desbloqueado quando:** PR merged. Instrução completa: `CHECKLIST_DEPLOY_REFACTOR.md` Etapas 3–4.

- [ ] **4. Migrar tráfego para nova revisão**
  **→ Desbloqueado quando:** todos os checks do item 3 passaram.

- [ ] **5. Confirmar job de monitoring no dia seguinte**
  Verificar que o Cloud Scheduler disparou e o relatório chegou no Slack sem alertas inesperados.
  **→ Fazer no dia seguinte ao item 4.**

---

### Fase pós-deploy — antes do Cliente B

- [ ] **6. Atualizar `ARQUITETURA_SISTEMA_COMPLETA.md`**
  Está desatualizado desde fev/2026 — não reflete `src/core/`, `ClientConfig`, multi-cliente.
  **→ Desbloqueado quando:** deploy concluído (item 4).

- [ ] **7. `src/core/validation.py` — schema check pré-treino**
  Adicionar step de validação no início do `train_pipeline.py`: schema esperado, nulos em features obrigatórias, ranges críticos. Sem isso, dado ruim do Cliente B pode corromper o pipeline silenciosamente sem erro explícito.
  **→ Fazer antes do segundo cliente ativo.**

- [ ] **8. Teste A/B champion/challenger em produção**
  Validar o challenger em produção antes de promovê-lo. A métrica final é ROAS no Meta Ads Manager — não AUC.

  **Arquitetura:**
  - O gestor de tráfego cria dois conjuntos de campanhas com UTMs distintas (ex: tag `ML_V1` vs `ML_V2`)
  - O pipeline detecta pelo UTM do lead qual modelo rodar
  - Cada modelo envia um **evento CAPI com nome diferente** (ex: `LeadQualified` vs `LeadQualifiedChallenger`)
  - O Meta atribui compras a cada evento separadamente → ROAS por modelo é visível direto no Ads Manager

  **Config:** bloco `ab_test` em `configs/active_models/{client_id}.yaml`:
  - `variants[champion]`: `run_id`, `utm_pattern`, `capi_event_name`
  - `variants[challenger]`: `run_id`, `utm_pattern`, `capi_event_name`

  **Escopo do teste:** sistema completo — cada variante usa seu próprio modelo **e** seus próprios `CONVERSION_RATES`. Leads cujo UTM não casa com nenhuma variante não são processados pelo pipeline de A/B (ficam fora do teste).

  **Critério de promoção:** ROAS do challenger ≥ champion após 1 lançamento completo com janela de conversão fechada (≥ 27 dias). AUC retrospectivo como critério secundário de sanidade.

  **Challenger imediato:** modelo retreinado com importance weighting (ver bloco urgente no `PLANO_REFACTOR_MLOPS.md` — prazo 15/04/2026).

  **→ Desbloqueado quando:** deploy do refactor concluído (item 4) + challenger treinado.

- [ ] **9. Sprint 2 `retraining_orchestrator.py` — quality gate automático**
  Após treino, comparar AUC e monotonia do novo modelo contra o modelo em produção. Só promover se melhor ou equivalente. Hoje essa comparação é feita manualmente. A arquitetura de hooks já existe (Sprint 1.1 implementado).
  **→ Desbloqueado quando:** item 8 validado em pelo menos um ciclo completo (a análise do A/B alimenta os thresholds do quality gate automático).**

---

### Fase Cliente B

- [ ] **10. Dados do Cliente B chegam**
  Formulário XLS + export de vendas + cadência do lançamento.
  **→ Depende do cliente.**

- [ ] **11. DT-2 — testes unitários `src/core/`**
  `pytest tests/core/ --client devclub --client clientb` para `utm.py`, `medium.py`, `encoding.py`. Devem ser parametrizados com dois `ClientConfig` reais — escrever com um só entrega metade do valor.
  **→ Desbloqueado quando:** dados do Cliente B disponíveis (item 10).

- [ ] **12. Onboarding Cliente B** — Fase 3b
  1. Escrever `configs/clients/clientb.yaml` usando `configs/templates/client_template.yaml`
  2. Executar `train_pipeline.py` — confirmar que nome do modelo e experimento MLflow contêm "clientb"
  3. Configurar `configs/active_models/clientb.yaml`
  4. Validar predições de produção
  **→ Desbloqueado quando:** itens 7, 10 e 11 concluídos. Instrução: `PLANO_REFACTOR_MLOPS.md` Fase 3b.**

- [ ] **13. EDA Generator** — `src/eda/generate_client_config.py`
  Gera `clientX.yaml` automaticamente a partir dos dados brutos do cliente. Com dois configs escritos manualmente, o padrão está claro o suficiente para automatizar.
  **→ Desbloqueado quando:** Cliente B estável (item 12 completo).**

---

### Fase 2–4 clientes

- [ ] **14. GitHub Actions CI — testes automáticos a cada push em `src/core/`**
  Push → lint → `pytest tests/core/ --client devclub --client clientb` → parity check → merge liberado.
  **→ Desbloqueado quando:** DT-2 concluído (item 11) + 2 clientes ativos.**

- [ ] **15. Sprint 3 `retraining_orchestrator.py` — trigger de retreino por drift**
  `monitoring/orchestrator.py` já detecta drift. Conectar ao `retraining_orchestrator.py`: se drift acumulado ultrapassar threshold por N dias consecutivos, disparar retreino automaticamente.
  **→ Desbloqueado quando:** 500+ leads/mês por cliente (volume mínimo para drift ser estatisticamente detectável).**

- [ ] **16. Looker Studio — dashboard de performance**
  Visualização de ROAS, CPL, distribuição de decis e taxa de conversão por cliente e lançamento.
  **→ Qualquer momento após Cliente B ativo. Baixo esforço, alto valor de apresentação.**

- [ ] **17. Vertex AI Model Registry**
  Substituir `configs/active_models/*.yaml` manual por registro centralizado com promoção policy-based.
  **→ Desbloqueado quando:** 3+ clientes ativos.**

---

### Fase 5+ clientes / escala B2B

Estes componentes só fazem sentido quando a infraestrutura atual virar gargalo real.

- [ ] **18. Stack GCP completo**

  | Componente | Substitui | Condição real |
  |---|---|---|
  | Pub/Sub + Apache Beam + Dataflow | Webhook síncrono no Cloud Run | 10k+ leads/dia ou múltiplas fontes simultâneas |
  | BigQuery Feature Store | Features computadas a cada treino em `src/core/` | Features caras de computar ou compartilhadas entre múltiplos modelos |
  | Kubeflow / Vertex AI Pipelines | `train_pipeline.py` manual | Múltiplos engenheiros editando o pipeline ou treino > diário |
  | Vertex AI Endpoints | Cloud Run para serving | Cloud Run mais caro que Vertex AI na escala atingida, ou A/B testing de modelos necessário |
  | Vertex AI Model Monitoring | `monitoring/orchestrator.py` customizado | 5+ clientes — o monitor customizado não escala mais |

  > MLflow permanece mesmo no stack completo — é portável e trackeia experimentos de forma que o Vertex AI não replica. Não substituir.
