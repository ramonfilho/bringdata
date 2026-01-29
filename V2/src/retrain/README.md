# Retreino Automatizado - Módulo Técnico

Pipeline de retreino mensal com validação, comparação e deploy condicional.

> 📋 **Planning/Roadmap**: Ver [ROADMAP.md](./ROADMAP.md)

## 🚀 Uso Rápido

### Local
```bash
python src/retrain/retraining_orchestrator.py --config configs/retreino_mensal.yaml
```

### Produção
```bash
gcloud run jobs execute retreino-mensal --region us-central1
```

## 📁 Arquivos

| Arquivo | Status | Descrição |
|---------|--------|-----------|
| `retraining_orchestrator.py` | ✅ Sprint 1 | Orquestrador principal |
| `data_validation.py` | ✅ Sprint 1 | Validação de qualidade/drift |
| `model_comparison.py` | 🔄 Sprint 2 | Comparação champion vs challenger |
| `deployment.py` | 🔄 Sprint 3 | Deploy condicional |
| `notifications.py` | 🔄 Sprint 3 | Notificações Slack |

## 🔧 Configuração

Criar `configs/retreino_mensal.yaml`:

```yaml
training:
  initial_matching: "email_telefone"
  split_method: "temporal_leads"

comparison:
  auto_approve_threshold: 0.02   # +2% AUC → AUTO
  manual_approval_threshold: 0.005  # +0.5% AUC → MANUAL
  min_monotonia: 0.80
```

## 🎯 APIs dos Componentes

### retraining_orchestrator.py (✅ Implementado)

```python
from src.retrain.retraining_orchestrator import RetreinoMensal

orquestrador = RetreinoMensal('configs/retreino_mensal.yaml')
resultado = orquestrador.run()  # Executa pipeline completo

# Retorna:
# {
#     'status': 'SUCCESS_MVP',
#     'execution_id': '20260128_102030',
#     'challenger_metadata': {...},
#     'notes': 'MVP: Apenas treinamento implementado'
# }
```

### data_validation.py (Sprint 1)

```python
from src.retrain.data_validation import DataValidator

validator = DataValidator(config)
result = validator.validate(df)

# Retorna:
# {
#     'passed': True,
#     'has_critical_failures': False,
#     'validations': [...]
# }
```

### model_comparison.py (Sprint 2)

```python
from src.retrain.model_comparison import ModelComparator

comparator = ModelComparator(config)
comparison = comparator.compare(champion_metadata, challenger_metadata)
decision = comparator.decide_deployment(comparison)

# decision: 'AUTO_APPROVE' | 'HUMAN_APPROVAL' | 'KEEP_CHAMPION' | 'REJECT'
```

## 📊 Arquitetura Hook-Based (Decisão Final!)

**Descobrimos que NÃO precisamos duplicar código!** 🎉

O `train_pipeline.py` (828 linhas) já faz **exatamente** o que o retreino precisa. A solução é adicionar um **validation hook** opcional que permite injetar validação sem duplicar código.

### Abordagem Hook-Based (Opção 3)

```python
# train_pipeline.py (modificação mínima)
def main(..., validation_hook=None):
    # ... células 1-17: extração + preprocessing ...

    dataset_v1_devclub_fe = criar_features_derivadas(dataset_v1_devclub)

    # === HOOK OPCIONAL PARA VALIDAÇÃO ===
    if validation_hook:
        should_continue = validation_hook(dataset_v1_devclub_fe)
        if not should_continue:
            return {'status': 'ABORTED_BY_VALIDATION'}

    # ... células 18.5-20: baseline capture + encoding + treino ...
```

```python
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

## 📊 Fluxo de Dados (Sprint 1.1 - Arquitetura Final)

```
train_pipeline.py (REUTILIZADO 100%)
    ├─ Células 1-7: Extração
    ├─ Células 8-17: Preprocessing
    ├─ Célula 18: Feature Engineering
    │
    ├─ 🔧 VALIDATION HOOK (novo!)
    │   └─ Chamado pelo train_pipeline se fornecido
    │       ├─ Orquestrador injeta validação aqui
    │       ├─ RetrainingDataValidator.validate()
    │       └─ Retorna True (continuar) ou False (abortar)
    │
    ├─ Célula 18.5: Baseline capture (monitoramento)
    ├─ Célula 20: Encoding
    └─ Treino + Registro MLflow

Orquestrador (MÍNIMO - apenas coordenação)
    ├─ STEP 1-4: train_main(..., validation_hook=hook)
    ├─ STEP 5: Comparação (Sprint 2)
    ├─ STEP 6: Decisão (Sprint 2)
    └─ STEP 7: Deploy (Sprint 3)
```

**Vantagens desta arquitetura:**
- ✅ **Zero duplicação de código** (reutiliza 100% do train_pipeline.py)
- ✅ Validação acontece no ponto correto (depois do FE, antes do encoding)
- ✅ Mantém train_pipeline funcional standalone (hook é opcional)
- ✅ Orquestrador fica mínimo (~50 linhas vs 400+)
- ✅ Flexível para futuros hooks (ex: custom preprocessing)
- ✅ Um único lugar para manter o código de treino

## 🔗 Integração com Pipeline de Treino

### Abordagem Sprint 1.1 (Hook-Based - FINAL):

```python
# Orquestrador injeta validation hook no train_pipeline
def run(self):
    # Criar hook de validação
    def validation_hook(dataset_fe):
        """Chamado pelo train_pipeline após feature engineering."""
        validator = RetrainingDataValidator(
            model_path=get_active_model_path(),
            config=self.config['validation']
        )

        result = validator.validate(dataset_fe)

        if result['has_critical_failures']:
            self.validation_result = result
            return False  # Abortar treino

        self.validation_result = result
        return True  # Continuar treino

    # Chamar train_pipeline com hook
    metadata = train_main(
        initial_matching=self.config['training']['initial_matching'],
        save_files=True,
        split_method=self.config['training']['split_method'],
        tune_hyperparams=False,
        set_active=False,
        validation_hook=validation_hook  # ← INJETA VALIDAÇÃO
    )

    if metadata.get('status') == 'ABORTED_BY_VALIDATION':
        return {
            'status': 'ABORTED',
            'reason': 'Data validation failed',
            'validation_result': self.validation_result
        }

    return metadata
```

**Metadados retornados incluem:**
- `model_info`: nome, tipo, trained_at
- `performance_metrics`: AUC, lift, monotonia
- `decil_analysis`: métricas por decil
- `recall_metrics`: recall real, fator correção
- `output_dir`: path do modelo salvo
- `mlflow_run_id`: ID do MLflow run

---

**Status Atual**: Sprint 1 Parcial - Treinamento + Validação implementados

**Próximo Passo**: Sprint 1.1 - Adicionar validation hook no train_pipeline.py (30-45 min)
- Adicionar parâmetro `validation_hook` opcional no `train_pipeline.main()`
- Hook é chamado após feature engineering (célula 18)
- Modificar orquestrador para injetar hook de validação
- Zero duplicação de código! Reutiliza 100% do train_pipeline existente

**Planning Completo**: [ROADMAP.md](./ROADMAP.md)
