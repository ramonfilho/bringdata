# MLflow — Acesso e Uso

## Infraestrutura

| Componente | Onde |
|---|---|
| Tracking (runs, params, metrics) | Cloud SQL PostgreSQL `104.197.138.129:5432/mlflow` |
| Artifacts (model.pkl, feature_registry.json, etc.) | `gs://smart-ads-mlflow/artifacts/` |

---

## Conectar ao MLflow

```python
import mlflow

mlflow.set_tracking_uri(
    "postgresql+psycopg2://postgres:SmartAds2026DB!@104.197.138.129:5432/mlflow"
)
```

Ou via variável de ambiente (preferido):

```bash
export MLFLOW_TRACKING_URI="postgresql+psycopg2://postgres:SmartAds2026DB!@104.197.138.129:5432/mlflow"
```

---

## Ver runs pelo Python

```python
import mlflow

mlflow.set_tracking_uri("postgresql+psycopg2://postgres:SmartAds2026DB!@104.197.138.129:5432/mlflow")
client = mlflow.tracking.MlflowClient()

# Listar todos os runs do experimento
runs = client.search_runs(experiment_ids=["1"], order_by=["metrics.auc DESC"])
for r in runs:
    print(r.info.run_id, r.data.metrics.get("auc"), r.data.params.get("period_end"))
```

---

## Ver dados de um run específico

```python
run = client.get_run("2a98e51ca4834697bbc94ec3dd31fcf7")

print(run.info.run_id)
print(run.data.params)   # hiperparâmetros e configurações
print(run.data.metrics)  # auc, monotonia, lift, etc.
```

---

## Baixar artefatos de um run

```python
# Baixa todos os artefatos para um diretório local
local_dir = mlflow.artifacts.download_artifacts(
    run_id="2a98e51ca4834697bbc94ec3dd31fcf7",
    dst_path="/tmp/model"
)
# Artefatos disponíveis em local_dir:
# - model/model.pkl
# - feature_registry.json
# - categorias_esperadas.json
# - distribuicoes_esperadas.json
# - model_metadata.json
```

Ou direto pelo gsutil:

```bash
gsutil -m cp -r gs://smart-ads-mlflow/artifacts/{run_id}/artifacts/ ./modelo/
```

---

## Modelo em produção

**Run ID:** `2a98e51ca4834697bbc94ec3dd31fcf7`

```python
run = client.get_run("2a98e51ca4834697bbc94ec3dd31fcf7")
# AUC: 0.745 | Monotonia: 100% | 59 features | tmb_risk_filter: none
# Treino: 04/11/2025–30/01/2026 | Teste: 30/01/2026–22/02/2026
```

O run ativo também está definido em `configs/active_model.yaml`.

---

## Experimento

- **Nome:** `devclub_lead_scoring`
- **ID:** `1`
- **Artifact location:** `gs://smart-ads-mlflow/artifacts/`
