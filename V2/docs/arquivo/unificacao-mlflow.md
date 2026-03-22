# Plano de Unificação MLflow

## 📋 **Fase 1 Completa - Unificação Total**

### **1. Feature Registry** ✅
```json
{
  ...
  "model_input_features": {
    "ordered_list": ["feat1", "feat2", ...],
    "count": 52
  }
}
```

### **2. Categorias e Distribuições** ✅ SEMPRE no MLflow
```python
# Adicionar após linha 1050 (sempre, não só quando save_files=true)
mlflow.log_dict(categorias_treino, "categorias_esperadas.json")
mlflow.log_dict(distribuicoes_treino, "distribuicoes_esperadas.json")
```

### **3. Novo Parâmetro** --save-test-predictions
```python
# Substituir save_files por save_test_predictions
def registrar_features_e_modelo_devclub(
    ...
    save_test_predictions: bool = False,  # NOVO
    set_active: bool = False,
    ...
):
```

### **4. Simplificar Lógica de Salvamento Local**

**ANTES** (com --save-files):
```
files/20260213_091500/
├── feature_registry.json           ❌ DUPLICADO (MLflow já tem)
├── model_metadata.json              ❌ DUPLICADO (MLflow já tem)
├── modelo.pkl                       ❌ DUPLICADO (MLflow já tem)
├── features_ordenadas.json          ⚠️  MANTER (compatibilidade)
├── categorias_esperadas.json        ❌ DUPLICADO (agora no MLflow)
├── distribuicoes_esperadas.json     ❌ DUPLICADO (agora no MLflow)
└── test_set_predictions.csv         ✅ ÚNICO
```

**DEPOIS** (com --save-test-predictions):
```
files/20260213_091500/
├── feature_registry.json            ✅ Cópia do MLflow (para set_active)
├── features_ordenadas.json          ✅ MANTER (compatibilidade)
└── test_set_predictions.csv         ✅ Apenas se --save-test-predictions
```

### **5. Lógica de --set-active**

**ANTES:**
```python
if save_files and set_active:
    # Atualizar configs/active_model.yaml
    # Apontar para files/timestamp/
```

**DEPOIS:**
```python
if set_active:
    # Criar diretório se não existe
    # Baixar feature_registry do MLflow
    # Copiar features_ordenadas (compatibilidade)
    # Atualizar configs/active_model.yaml
```

---

## 🎯 **Resumo das Mudanças:**

| Item | Antes | Depois |
|------|-------|--------|
| **feature_registry** | Categorizado | + lista ordenada |
| **categorias/distribuições** | Só com --save-files | SEMPRE no MLflow |
| **modelo.pkl** | MLflow + files/ | SÓ MLflow |
| **test_predictions.csv** | Com --save-files | --save-test-predictions |
| **features_ordenadas** | Com --save-files | SEMPRE (compatibilidade) |
| **--save-files** | ✅ Existe | ⚠️ Deprecado |
| **--set-active** | Requer --save-files | Independente |

---

## 📝 **Mudanças no train_pipeline.py:**

```python
# ANTES
parser.add_argument('--save-files', action='store_true',
    help='Salvar arquivos locais')
parser.add_argument('--set-active', action='store_true',
    help='Atualizar modelo ativo (requer --save-files)')

# DEPOIS
parser.add_argument('--save-test-predictions', action='store_true',
    help='Salvar predições do test set em files/')
parser.add_argument('--set-active', action='store_true',
    help='Atualizar modelo ativo (baixa do MLflow se necessário)')
```

---

## ⚠️ **Backward Compatibility:**

Para não quebrar scripts existentes, podemos manter `--save-files` como alias:
```python
# Deprecation warning
if args.save_files:
    logger.warning("--save-files está deprecado, use --save-test-predictions")
    args.save_test_predictions = True
```

---

## 🔄 **Plano de Migração Sem Quebrar**

### **Fase 1: Unificação no Treino** (Hoje)

**O que fazer:**
1. Adicionar lista ao `feature_registry.json`:
```json
{
  "model_input_features": {
    "ordered_list": ["feat1", "feat2", ...],
    "count": 52
  }
}
```

2. **CONTINUAR** salvando `features_ordenadas.json` (backward compatibility)
3. MLflow sempre loga ambos

**Resultado:** Modelos novos têm ambos, produção continua funcionando

---

### **Fase 2: Migração Gradual do Prediction.py** (Semana que vem)

**Modificar `prediction.py`** para tentar feature_registry primeiro:

```python
def load_model(self):
    # ... carregar modelo ...

    # NOVO: Tentar feature_registry primeiro
    registry_file = self.model_path / f"feature_registry_{self.model_name}.json"
    features_file = self.model_path / f"features_ordenadas_{self.model_name}.json"

    # Prioridade 1: feature_registry (novo formato)
    if registry_file.exists():
        logger.info(f"Carregando features de: {registry_file}")
        with open(registry_file, 'r') as f:
            registry = json.load(f)
            self.feature_names = registry['model_input_features']['ordered_list']
            logger.info("Features carregadas do feature_registry")

    # Fallback: features_ordenadas (formato antigo)
    elif features_file.exists():
        logger.info(f"Carregando features de: {features_file} (fallback)")
        with open(features_file, 'r') as f:
            features_data = json.load(f)
            if 'expected_dtypes' in features_data:
                self.feature_names = list(features_data['expected_dtypes'].keys())
            elif 'feature_names' in features_data:
                self.feature_names = features_data['feature_names']

    else:
        raise FileNotFoundError("Nenhum arquivo de features encontrado!")
```

**Resultado:**
- ✅ Modelos novos usam `feature_registry`
- ✅ Modelos antigos continuam funcionando com `features_ordenadas`
- ✅ Zero downtime

---

### **Fase 3: Limpeza** (Após validar em produção - 1-2 semanas)

1. Remover código que salva `features_ordenadas.json` no treino
2. Remover fallback do `prediction.py`
3. Deletar arquivos antigos

---

## ✅ **Vantagens desta Abordagem:**

- 🟢 **Zero risco** - backward compatible
- 🟢 **Rollback fácil** - basta usar modelo antigo
- 🟢 **Testável** - pode validar gradualmente
- 🟢 **Sem pressa** - cada fase pode levar o tempo necessário
