# MLflow — Acesso e Uso

> ⚠️ **A instância Cloud SQL está parada desde 2026-04-26** (`activation-policy=NEVER`) por motivo de custo. Antes de usar MLflow (retreino, exploração ad-hoc), subir a instância — ver `operacoes_gcp_custos.md` para o protocolo de start/stop.

## Infraestrutura

| Componente | Onde |
|---|---|
| Tracking (runs, params, metrics) | Cloud SQL PostgreSQL `104.197.138.129:5432/mlflow` (instância `smart-ads-db`) |
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

## Modelo em produção (27/04/2026)

**Atualmente servido (rollback `00269-jjn`, 100% do tráfego):**
- **Run ID:** `d51757f5` (jan30 ORIGINAL)
- AUC ~0.7311 · Monotonia 88.9% · Treino até 04/11/2025 · Promovido a Champion em 31/03/2026

**Retreinados em 23/04/2026 — Champion v4 ✅ validado out-of-sample em 28/04 e em deploy via canary:**
- **Champion v4:** `60637bb98b94421b9c7579bb4ac1b1ad` — AUC 0.748, monotonia 77.78%, 1.104 positivos, janela até 02/04/2026, OHE default (sem `encoding_overrides`). Em deploy de produção via canary em sessão paralela (28/04).
- **Challenger v4:** `7d08ae0302da420aa99559d4d4f55025` — AUC 0.745, monotonia 66.7%, mesma janela. Em standby até promoção do Champion v4; entra como Challenger no próximo ciclo A/B.

> 🔓 A/B test reaberto em 28/04 após validação OOS do Champion v4 atravessada. Ver `AB_TEST.md` e `PLANO_EXECUCAO.md`.

**Histórico:**
- `2a98e51ca4834697bbc94ec3dd31fcf7` — modelo P1 anterior ao jan30, AUC 0.745, 59 features, treino 04/11/2025–30/01/2026 (referência histórica)

O run ativo também está definido em `configs/active_models/devclub.yaml`.

---

## Experimento

- **Nome:** `devclub_lead_scoring`
- **ID:** `1`
- **Artifact location:** `gs://smart-ads-mlflow/artifacts/`
