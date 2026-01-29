# Roadmap: Pipeline de Retreino Mensal - Smart Ads

## 🎯 Objetivo

Implementar retreino automatizado mensal com validação de dados, comparação champion vs challenger, e deploy condicional.

---

## 🏗️ Arquitetura

```
Cloud Scheduler (mensal)
    ↓
Cloud Run Job: retreino-mensal
    ↓
├─ Validação de Dados (reusa monitoring)
├─ Treinamento (reusa train_pipeline.py)
├─ Comparação Champion vs Challenger
├─ Deploy Condicional (se aprovado)
└─ Relatório + Slack
```

---

## 🔍 Decisão Arquitetural: Hook-Based Validation! (2026-01-28)

**Descobrimos que NÃO precisamos duplicar código!** 🎉

O `train_pipeline.py` (828 linhas) já faz **exatamente** o que o retreino precisa. A solução é adicionar um **validation hook** opcional.

### Evolução do Pensamento:

**FASE 1 (pensávamos):**
- ❌ Código monolítico, precisa refatorar
- ❌ Sprint 1: 2 semanas de refatoração

**FASE 2 (descoberta da modularidade):**
- ✅ Código já modular, só chamar funções
- ✅ Sprint 1.1: 2-4 horas de integração
- ⚠️ Mas ainda duplicaria 600+ linhas de lógica

**FASE 3 (decisão final - hook-based):**
- ✅ Reutiliza 100% do train_pipeline (zero duplicação!)
- ✅ Adiciona hook opcional para injetar validação
- ✅ Sprint 1.1: 30-45 minutos de implementação

### Arquitetura Hook-Based:

```python
# train_pipeline.py (modificação mínima - adicionar parâmetro)
def main(..., validation_hook=None):
    # ... células 1-17: extração + preprocessing ...

    dataset_v1_devclub_fe = criar_features_derivadas(dataset_v1_devclub)

    # === HOOK OPCIONAL PARA VALIDAÇÃO ===
    if validation_hook:
        should_continue = validation_hook(dataset_v1_devclub_fe)
        if not should_continue:
            return {'status': 'ABORTED_BY_VALIDATION'}

    # ... células 18.5-20: baseline capture + encoding + treino ...


# retraining_orchestrator.py (orquestrador mínimo)
def run(self):
    def validation_hook(df):
        validator = RetrainingDataValidator(...)
        result = validator.validate(df)

        if result['has_critical_failures']:
            self.validation_result = result
            return False  # Abortar

        return True  # Continuar

    # Reutiliza train_pipeline completo + injeta validação
    metadata = train_main(..., validation_hook=validation_hook)
```

**Resultado:** Sprint 1.1 simplificado de 2 semanas para 30-45 minutos! 🎉🎉

**Vantagens:**
- ✅ Zero duplicação de código
- ✅ Um único lugar para manter lógica de treino
- ✅ Validação no ponto correto (depois do FE)
- ✅ train_pipeline continua funcional standalone
- ✅ Flexível para futuros hooks

---

## 📦 Componentes a Criar/Modificar

### Arquivos Criados (✅ Sprint 1)

1. ✅ `V2/src/retrain/retraining_orchestrator.py` - Orquestrador principal
2. ✅ `V2/src/retrain/data_validation.py` - Wrapper do DataQualityMonitor + validações específicas
3. ✅ `V2/configs/retreino_mensal.yaml` - Configurações do job
4. ✅ `V2/src/retrain/__init__.py` - Módulo Python
5. ✅ `V2/src/retrain/README.md` - Documentação técnica
6. ✅ `V2/src/retrain/ROADMAP.md` - Planejamento (este arquivo)

### Arquivos Stub (🔄 Sprint 2-3)

1. 🔄 `V2/src/retrain/model_comparison.py` - Comparação champion vs challenger (Sprint 2)
2. 🔄 `V2/src/retrain/deployment.py` - Deploy condicional (Sprint 3)
3. 🔄 `V2/src/retrain/notifications.py` - Notificações Slack (Sprint 3)
4. 🔄 `V2/infrastructure/cloud_run_job_retreino.yaml` - Deploy GCP (Sprint 3)
5. 🔄 `V2/Dockerfile.retreino` - Container para o job (Sprint 3)

### Modificações Feitas (✅ Sprint 1)

1. ✅ `V2/src/model/training_model.py` - Retorna model_metadata completo (não resultado_final simplificado)
2. ✅ `V2/src/train_pipeline.py` - Retorna metadata ao final de main()

### Modificações Futuras (🔄 Sprint 2-3)

1. 🔄 `V2/configs/active_model.yaml` - Adicionar campo `previous_champion` (Sprint 3)
2. 🔄 `V2/api/business_config.py` - Update automático com recall (Sprint 3)

### ❌ Não Necessário (descoberta de modularidade)

1. ~~❌ `V2/src/monitoring/validation_rules.py`~~ - Não necessário! DataQualityMonitor já existe e funciona
2. ~~❌ Refatorar `data_quality.py`~~ - Não necessário! Já está bom, só reusamos

---

## ⚙️ Steps do Pipeline

```python
class RetreinoMensal:

    def run(self):
        # STEP 1: Extração
        df_raw = self.extract_data()

        # STEP 2: Validação (reusa monitoring)
        validation_result = self.validate_data(df_raw)
        if validation_result['critical_failures']:
            self.abort_and_notify()
            return

        # STEP 3: Preparação (reusa train_pipeline)
        df_processed = self.prepare_data(df_raw)

        # STEP 4: Treinamento (reusa train_pipeline)
        challenger_model, challenger_meta = self.train_model(df_processed)

        # STEP 5: Comparação
        comparison = self.compare_models(challenger_meta)

        # STEP 6: Decisão
        approved = self.decide_deployment(comparison)

        # STEP 7: Deploy (se aprovado)
        if approved:
            self.deploy_model(challenger_model, challenger_meta)

        # STEP 8: Relatório
        self.generate_report_and_notify(comparison, validation_result)
```

---

## 📅 Cronograma (3 Sprints)

### Sprint 1 (✅ CONCLUÍDO - 2026-01-28)

- [x] ~~Refatorar `data_quality.py`~~ → Não necessário! Reusamos DataQualityMonitor via wrapper
- [x] ~~Criar `validation_rules.py`~~ → Não necessário! Regras já existem em monitoring
- [x] Criar `retreino_mensal.yaml` (config)
- [x] Criar `data_validation.py` (wrapper + validações específicas)
- [x] Implementar estrutura do orquestrador
- [x] Modificar `train_pipeline.py` para retornar metadata
- [x] Documentação (README + ROADMAP)

**Entrega:** ✅ Estrutura básica + validação implementada (wrapper funcional)

**Descoberta importante:** Código já é modular! Economizou ~2 semanas de refatoração.

---

### Sprint 1.1 (Próximo - Estimativa: 30-45 min)

- [ ] Adicionar parâmetro `validation_hook` no `train_pipeline.main()`
- [ ] Chamar hook após feature engineering (célula 18)
- [ ] Modificar orquestrador para injetar validation hook
- [ ] Testar validação end-to-end com dados reais

**Entrega:** Validação funcionando via hook (zero duplicação de código)

---

### Sprint 2 (Semana 3-4): Pipeline Core + Comparação

- [ ] Criar `model_comparison.py` (champion vs challenger)
- [ ] Implementar Steps 3-5 em `retreino_mensal.py`
- [ ] Adicionar lógica de decisão (auto-approve/reject/manual)
- [ ] Criar templates Slack para notificações
- [ ] Testar pipeline completo localmente (sem deploy)

**Entrega:** Pipeline treina e compara modelos localmente

---

### Sprint 3 (Semana 5-6): Deploy + Automação GCP

- [ ] Implementar Step 7 (deploy condicional)
- [ ] Atualizar `active_model.yaml` com versionamento
- [ ] Criar `Dockerfile.retreino`
- [ ] Configurar Cloud Run Job no GCP
- [ ] Configurar Cloud Scheduler (1º dia útil do mês, 10h)
- [ ] Testar job completo no GCP
- [ ] Documentar operação e troubleshooting

**Entrega:** Pipeline automatizado em produção

---

## 📋 Checklist de Implementação

### Phase 1: Validação de Dados (✅ Concluído - Sprint 1)

```
[x] ~~Criar dataclass ValidationRule~~ → Não necessário (reusamos DataQualityMonitor)
[x] ~~Migrar checks existentes~~ → Não necessário (já existe em monitoring)
[x] Criar RetrainingDataValidator (wrapper)
[x] Adicionar validações específicas de retreino:
    [x] Volume mínimo (>1000 registros)
    [x] Taxa de conversão esperada (0.5%-5%)
    [x] Período mínimo de dados (30 dias)
[x] Reusar validações do monitoramento via wrapper:
    [x] Category drift (via DataQualityMonitor)
    [x] Distribution drift (via DataQualityMonitor)
    [x] Missing rate (via DataQualityMonitor)
    [x] Score distribution (via DataQualityMonitor)
[x] Criar método validate() que retorna dict estruturado
[x] Severidade já implementada (HIGH/MEDIUM/LOW via monitor)
[ ] Testar com dados históricos reais (Sprint 1.1)
```

**Status:** ✅ Implementado mas não testado com dados reais (precisa Sprint 1.1)

### Phase 1.1: Integração Hook-Based (🔄 Próximo - 30-45min)

```
[ ] Modificar train_pipeline.py:
    [ ] Adicionar parâmetro opcional validation_hook na assinatura de main()
    [ ] Chamar hook após feature engineering (linha ~697)
    [ ] Retornar status ABORTED_BY_VALIDATION se hook retornar False
[ ] Modificar retraining_orchestrator.py:
    [ ] Implementar validation_hook() que chama RetrainingDataValidator
    [ ] Passar hook ao chamar train_main()
    [ ] Capturar resultado de validação e decidir se prossegue
[ ] Testar com dados históricos reais
```

**Estimativa:** 30-45 minutos (modificação mínima, zero duplicação!)

### Phase 2: Comparação Champion vs Challenger (🔄 Sprint 2)

```
[x] Criar retraining_orchestrator.py com estrutura base
[x] Implementar validate_data() - wrapper do DataQualityMonitor
[ ] Implementar _load_champion_metadata() - lê active_model.yaml
[ ] Criar model_comparison.py:
    [ ] Função compare_metrics(champion, challenger)
    [ ] Regras de decisão:
        • AUC delta > +2%: AUTO_APPROVE
        • AUC delta +0.5% a +2%: HUMAN_APPROVAL
        • AUC delta -0.5% a +0.5%: KEEP_CHAMPION
        • AUC delta < -0.5%: REJECT
    [ ] Incluir: Lift D1, Monotonia, Recall
[ ] Implementar decide_deployment():
    [ ] Auto-approve se regras permitirem
    [ ] Enviar Slack para aprovação manual (se necessário)
    [ ] Timeout 48h (default: REJECT)
[ ] Testar com modelos históricos
```

### Phase 3: Deploy + Notificações

```
[ ] Implementar deploy_model():
    [ ] Salvar modelo no GCS
    [ ] Atualizar active_model.yaml:
        • Adicionar campo previous_champion
        • Atualizar model_path
        • Adicionar timestamp e metadata
    [ ] Atualizar business_config.py (recall correction)
    [ ] Registrar no MLflow (se disponível)
[ ] Criar slack_notifier.py:
    [ ] Template: início de retreino
    [ ] Template: validação falhou (abortar)
    [ ] Template: comparação de modelos
    [ ] Template: aprovação necessária (botões)
    [ ] Template: deploy concluído
    [ ] Template: retreino finalizado
[ ] Implementar generate_report():
    [ ] Reusar formato do validation Excel
    [ ] Adicionar aba "Comparação Champion/Challenger"
    [ ] Upload para GCS
[ ] Testar fluxo completo localmente
```

### Phase 4: Infraestrutura GCP

```
[ ] Criar Dockerfile.retreino:
    [ ] Base: python:3.10-slim
    [ ] Install deps: requirements.txt
    [ ] Copiar código V2/
    [ ] CMD: python src/retreino_mensal.py
[ ] Build e push para GCR:
    docker build -f Dockerfile.retreino -t gcr.io/PROJECT/retreino-mensal .
    docker push gcr.io/PROJECT/retreino-mensal
[ ] Criar Cloud Run Job:
    [ ] Nome: retreino-mensal
    [ ] Região: us-central1
    [ ] Memory: 8GB
    [ ] CPU: 4
    [ ] Timeout: 3600s (1h)
    [ ] Service Account: com permissões GCS + Secret Manager
[ ] Configurar Cloud Scheduler:
    [ ] Nome: trigger-retreino-mensal
    [ ] Schedule: "0 10 1 * *" (dia 1, 10h)
    [ ] Target: Cloud Run Job
    [ ] Timezone: America/Sao_Paulo
[ ] Testar execução manual:
    gcloud run jobs execute retreino-mensal --region us-central1
[ ] Validar logs e outputs no GCS
```

### Phase 5: Monitoramento & Docs

```
[ ] Adicionar métricas de observabilidade:
    [ ] Duração do retreino
    [ ] Taxa de sucesso/falha
    [ ] Alertas no Cloud Monitoring
[ ] Criar documentação:
    [ ] README: Como funciona o retreino
    [ ] Troubleshooting: Erros comuns
    [ ] Runbook: Como aprovar/rejeitar modelo manualmente
    [ ] Como fazer rollback de modelo
[ ] Criar dashboard (opcional):
    [ ] Looker/Data Studio com métricas de retreino
    [ ] Histórico de AUC ao longo do tempo
    [ ] Taxa de aprovação de modelos
```

---

## 🔧 Configurações Principais

### retreino_mensal.yaml

```yaml
# Dados
training_data_dir: "gs://smart-ads/data/devclub/treino/"
min_records: 100

# Validação
validation:
  email_valid_threshold: 0.8
  phone_valid_threshold: 0.5
  missing_rate_threshold: 0.3
  critical_drift_threshold: 0.15

# Treinamento
training:
  initial_matching: "email_telefone"
  split_method: "temporal_leads"
  hyperparameters:
    n_estimators: 300
    max_depth: 8
    class_weight: "balanced"

# Comparação
comparison:
  auto_approve_threshold: 0.02  # +2% AUC
  manual_approval_threshold: 0.005  # +0.5% AUC
  min_monotonia: 0.80  # 80%

# Deploy
deployment:
  gcs_bucket: "smart-ads-ml-artifacts"
  models_path: "models/"
  active_config_path: "configs/active_model.yaml"

# Notificações
notifications:
  slack_webhook: "${SLACK_WEBHOOK_URL}"  # Secret Manager
  alert_channel: "#ml-alerts"

# MLflow
mlflow:
  tracking_uri: "sqlite:///mlflow.db"  # Ou PostgreSQL remoto
  experiment_name: "devclub_lead_scoring"
```

---

## 📊 Decisão de Deploy (Lógica)

```python
def decide_deployment(comparison: dict) -> bool:
    """
    Regras de decisão baseadas em métricas

    Returns:
        True se modelo deve ser deployado
        False se deve manter champion
    """
    auc_delta_pct = comparison['auc_delta_pct']
    monotonia = comparison['monotonia_challenger']

    # Pré-requisito: monotonia >= 80%
    if monotonia < 80:
        return False

    # AUTO_APPROVE: melhoria significativa
    if auc_delta_pct >= 2.0:
        return True

    # HUMAN_APPROVAL: melhoria moderada
    if 0.5 <= auc_delta_pct < 2.0:
        return request_slack_approval(comparison, timeout_hours=48)

    # KEEP_CHAMPION: performance similar ou pior
    return False
```

---

## 🚀 Como Executar

### Local (desenvolvimento)

```bash
python V2/src/retreino_mensal.py --config configs/retreino_mensal.yaml
```

### GCP (produção)

```bash
# Manual
gcloud run jobs execute retreino-mensal --region us-central1

# Automático (Cloud Scheduler)
# Roda automaticamente dia 1 de cada mês às 10h
```

---

## 📈 Métricas de Sucesso

- [ ] Pipeline executa sem erros em <1h
- [ ] Validação detecta drift antes de treinar
- [ ] Comparação de modelos funciona corretamente
- [ ] Notificações Slack chegam em <5min
- [ ] Deploy atualiza `active_model.yaml` corretamente
- [ ] Relatório Excel é gerado e salvo no GCS
- [ ] Rollback manual é possível em <10min

---

## 🔄 Melhorias Futuras (Backlog)

- [ ] Canary deployment (10% traffic → 100%)
- [ ] A/B testing framework
- [ ] Monitoramento de drift em produção (online)
- [ ] MLflow remoto (PostgreSQL no Cloud SQL)
- [ ] Vertex AI Model Registry integration
- [ ] Hyperparameter tuning automático (Optuna)
- [ ] Multi-model serving (segmentação)
- [ ] Online learning (atualização incremental)

---

## ⏱️ Estimativa de Esforço

| Sprint | Tarefas | Complexidade | Tempo |
|--------|---------|--------------|-------|
| Sprint 1 | Validação + Config | Baixa | 2 semanas |
| Sprint 2 | Pipeline + Comparação | Média | 2 semanas |
| Sprint 3 | Deploy + GCP | Média-Alta | 2 semanas |
| **TOTAL** | - | - | **6 semanas** |

**Nota:** 1 pessoa full-time ou 2 pessoas part-time (50%)

---

## ✅ Próximos Passos

1. Criar branch `feature/retreino-mensal`
2. Criar estrutura de pastas/arquivos vazios
3. Começar pelo Sprint 1 (validação)
4. Fazer checkpoint após cada sprint

### Dúvidas? Riscos?

- Aprovação manual via Slack (pode precisar ajustes)
- Integração com GCS (testar permissões)
- Timeout de 1h suficiente? (depende do volume de dados)

---

## 🎯 Objetivo Final

Retreino automatizado, seguro, e com supervisão humana quando necessário.

---

## 📊 Status Atual (2026-01-28)

### ✅ Concluído (Sprint 1):
- Estrutura de pastas e módulos
- Orquestrador básico (`retraining_orchestrator.py`)
- Validação de dados (`data_validation.py` - wrapper do DataQualityMonitor)
- Configuração completa (`configs/retreino_mensal.yaml`)
- Documentação técnica (README + ROADMAP)
- Modificações em `train_pipeline.py` e `training_model.py` para retornar metadata

### 🔄 Em Andamento (Sprint 1.1 - Próximo):
- Adicionar validation hook no train_pipeline.py
- Modificar orquestrador para injetar hook
- Teste end-to-end com dados reais

**Estimativa Sprint 1.1:** 30-45 minutos (graças à arquitetura hook-based!)

### 🔜 Planejado:
- Sprint 2: Comparação champion vs challenger (2 semanas)
- Sprint 3: Deploy condicional + Cloud Run Job (2 semanas)

### 💡 Decisão Arquitetural (2026-01-28):

**Arquitetura Hook-Based!** Reutiliza 100% do train_pipeline sem duplicação.

Adicionar um `validation_hook` opcional permite injetar validação no ponto correto sem duplicar 828 linhas de código.

**Impacto:** Sprint 1.1 reduzido de ~2 semanas para ~30-45 minutos! 🎉🎉

**Vantagens:**
- Zero duplicação de código
- Um único lugar para manter lógica de treino
- train_pipeline continua funcional standalone
- Flexível para futuros hooks (custom preprocessing, etc.)

---

## 📚 Referências

- [README Técnico](./README.md) - Documentação de uso e APIs
- [Documentação do Sistema de Validação](../validation/DOCUMENTATION.md)
- [Monitoramento de Dados](../monitoring/ARCHITECTURE.md)

---

**Última atualização:** 2026-01-28 (Sprint 1 concluído + descoberta de modularidade)
