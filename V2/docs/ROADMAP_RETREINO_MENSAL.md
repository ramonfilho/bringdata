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

## 📦 Componentes a Criar/Modificar

### Novos Arquivos

1. `V2/src/retreino_mensal.py` - Orquestrador principal
2. `V2/configs/retreino_mensal.yaml` - Configurações do job
3. `V2/src/monitoring/validation_rules.py` - Validador estruturado
4. `V2/src/model/model_comparison.py` - Comparação de modelos
5. `V2/infrastructure/cloud_run_job_retreino.yaml` - Deploy GCP
6. `V2/Dockerfile.retreino` - Container para o job

### Modificações

1. `V2/src/monitoring/data_quality.py` - Refatorar para ValidationRule
2. `V2/src/model/training_model.py` - Adicionar retorno de metadata estruturado
3. `V2/configs/active_model.yaml` - Adicionar campo `previous_champion`
4. `V2/src/utils/slack_notifier.py` - Adicionar templates de retreino

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

### Sprint 1 (Semana 1-2): Validação + Infraestrutura

- [ ] Refatorar `data_quality.py` para `ValidationRule` estruturado
- [ ] Criar `validation_rules.py` com regras padrão
- [ ] Criar `retreino_mensal.yaml` (config)
- [ ] Implementar Steps 1-2 em `retreino_mensal.py`
- [ ] Testar validação end-to-end localmente

**Entrega:** Validação de dados funcionando e testada

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

### Phase 1: Validação de Dados

```
[ ] Criar dataclass ValidationRule
[ ] Migrar checks existentes para ValidationRule
[ ] Adicionar regras:
    [ ] Schema validation (colunas obrigatórias)
    [ ] Volume mínimo (>100 leads)
    [ ] Taxa de emails válidos (>80%)
    [ ] Taxa de telefones válidos (>50%)
    [ ] Missing rate por coluna (<30%)
    [ ] Category drift (reusa código existente)
    [ ] Distribution drift (reusa código existente)
[ ] Criar método validate() que retorna dict estruturado
[ ] Adicionar severidade (HIGH/MEDIUM/LOW)
[ ] Testar com dados históricos
```

### Phase 2: Treinamento + Comparação

```
[ ] Criar retreino_mensal.py com estrutura base
[ ] Implementar extract_data() - lê Excel do GCS
[ ] Implementar validate_data() - usa ValidationRule
[ ] Implementar prepare_data() - chama train_pipeline steps
[ ] Implementar train_model() - chama training_model.py
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

## 📚 Referências

- [Arquitetura do Sistema](./ARQUITETURA_SISTEMA_COMPLETA.md)
- [Sistema de Validação ML](./SISTEMA_VALIDACAO_ML.md)
- [Documentação de Deploy GCP](../api/docs/documentacao_deploy_gcp.md)

---

**Última atualização:** 2026-01-26
