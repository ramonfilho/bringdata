# MLflow — Acesso e Uso

> **A instância Cloud SQL `smart-ads-db` está LIGADA** (`activation-policy=ALWAYS`, conferido em 17/09/2026): o gate de modelo do CI lê o run nela em toda PR que troca o YAML, e o retreino grava nela. Desligar quebra os dois. (O aviso antigo, de 26/04/2026, dizia que ela ficava parada por custo: Antes de usar MLflow (retreino, exploração ad-hoc), subir a instância — ver `operacoes_gcp_custos.md` para o protocolo de start/stop.

## Infraestrutura

| Componente | Onde |
|---|---|
| Tracking (runs, params, metrics) | Cloud SQL PostgreSQL `<IP da instância smart-ads-db>:5432/mlflow` (instância `smart-ads-db`; o IP sai de `gcloud sql instances describe smart-ads-db --format='value(ipAddresses[0].ipAddress)'`) |
| Artifacts (model.pkl, feature_registry.json, etc.) | `gs://smart-ads-mlflow/artifacts/` |

---

## Conectar ao MLflow

A URI **não fica no código**. Ela mora no `V2/.env` (que é gitignored) e é lida por
`src/core/mlflow_setup.py`, que é a fonte única:

```python
from src.core.mlflow_setup import ensure_tracking_uri
ensure_tracking_uri()   # aponta o MLflow pro backend e devolve a URI usada
```

Se a env var não estiver configurada, isso levanta exceção com a instrução de correção,
em vez de cair calado num MLflow local vazio. Para configurar (uma vez por máquina):

```bash
SENHA=$(gcloud secrets versions access latest --secret=mlflow-db-password --project=smart-ads-451319)
echo "MLFLOW_TRACKING_URI=postgresql+psycopg2://postgres:$SENHA@<IP da instância smart-ads-db>:5432/mlflow?sslmode=require" >> V2/.env
```

> **Por que não pode voltar pro código:** até 05/08/2026 a senha do usuário `postgres`
> estava escrita em texto claro em 11 arquivos versionados deste repositório, que é
> **público**. Como a instância aceita conexão de qualquer IP, a credencial dava acesso de
> dono a `analytics.leads` (366 mil leads com e-mail, telefone e nome) e a
> `analytics.sales`. A senha foi rotacionada e o teste
> `V2/tests/test_sem_credencial_no_repo.py` falha se qualquer credencial literal voltar.

---

## Ver runs pelo Python

```python
import mlflow

from src.core.mlflow_setup import ensure_tracking_uri
ensure_tracking_uri()
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
