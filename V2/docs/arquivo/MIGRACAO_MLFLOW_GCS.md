# Migração MLflow → GCS Backend

**Status:** ✅ Concluído — 17/03/2026 (50 runs migrados para Cloud SQL `104.197.138.129:5432/mlflow`, artifacts em `gs://smart-ads-mlflow/artifacts/`)
**Motivação:** MLflow com `sqlite:///mlflow.db` cria runs em diretórios diferentes dependendo de onde o script é executado. Com múltiplos worktrees e Cloud Run, os runs ficam espalhados e inacessíveis entre ambientes.

---

## Problema atual

```
bring_data/V2/mlruns/1/2a98e51c...   ← modelo ativo (worktree main)
bring_data_refactor/V2/mlruns/1/...  ← runs do refactor (worktree refactor)
bring_data_refactor/mlruns/1/972cf3  ← run criado na raiz (bug de path relativo)
```

Cada vez que `python -m V2.src.train_pipeline` é executado fora de `V2/`, o SQLite e o `mlruns/` são criados no diretório de trabalho atual. Resultado: runs perdidos, comparações inviáveis, modelo ativo inacessível de outro worktree.

## Como o modelo chega ao Cloud Run

**O modelo NÃO é carregado do MLflow em runtime.** O mecanismo é:

1. `api/deploy_capi.sh` define `MODEL_PATH="mlruns/1/${MLFLOW_RUN_ID}/artifacts"` e passa como `--build-arg`
2. `api/Dockerfile` linha 52: `COPY ./${MODEL_PATH}/ ./${MODEL_PATH}/` — **bake nos artefatos na imagem no build**
3. O container rodando no Cloud Run tem o diretório `mlruns/1/{run_id}/artifacts/` localmente
4. `prediction.py` lê de `mlruns/1/{run_id}/artifacts/` — funciona porque o path está dentro do container

**Consequência crítica para a migração:** o container em produção hoje é 100% independente de onde os mlruns/ locais estão, de qual worktree está ativo, e de qualquer mudança no tracking URI. A imagem tem os artefatos embutidos.

---

**Arquivos afetados (leitura/escrita de mlruns):**

| Arquivo | O que faz | Como é afetado |
|---|---|---|
| `src/model/training_model.py:26` | Define `tracking_uri = sqlite:///mlflow.db`, salva runs | **Ponto de mudança principal** |
| `src/train_pipeline.py` | Lê `get_experiment_by_name()` | Precisa do tracking_uri correto |
| `src/model/prediction.py:132` | Carrega modelo via path `mlruns/1/{run_id}/artifacts/` | Path hardcoded → muda para `mlflow.artifacts.download_artifacts()` |
| `src/core/encoding.py:53` | Carrega `feature_registry.json` via path `mlruns/{exp_id}/{run_id}/artifacts/` | Idem |
| `src/features/encoding.py:263` | Carrega feature registry (produção) | Idem |
| `api/deploy_capi.sh` | Copia artefatos locais para a imagem Docker via `--build-arg MODEL_PATH` | Precisa copiar de GCS antes do build (ou mudar estratégia de build) |
| `src/production_pipeline.py` | Passa `mlflow_run_id` para encoding | Sem mudança — só passa o ID |
| `api/app.py` | Passa `mlflow_run_id` para encoding | Sem mudança — só passa o ID |

---

## Solução escolhida: GCS como backend unificado

MLflow 2.x suporta GCS como artifact store **sem precisar de servidor MLflow separado**. O cliente conecta direto ao GCS.

### Por que não Vertex AI Model Registry?

É o serviço nativo GCP para model registry, mas:
- Custo por modelo registrado + API calls (vs. cents de storage no GCS)
- Lock-in alto — requer reescrita completa da integração MLflow
- Overengineering para o volume atual (1 modelo ativo por cliente)

### Por que não PostgreSQL como backend?

- Cloud SQL foi desativado — criaria dependência de nova instância
- A API usa **Railway PostgreSQL** como banco operacional (leads_capi), não Cloud SQL
- GCS é mais simples e suficiente para metadados MLflow (JSON pequenos)

### Arquitetura proposta

```
Ambiente local / Cloud Run
         │
         ├── Tracking URI: gs://bring-data-mlflow/
         │   └── mlflow/<experiment_id>/<run_id>/
         │       ├── metrics/
         │       ├── params/
         │       └── tags/
         │
         └── Artifact Store: gs://bring-data-mlflow/artifacts/
             └── <run_id>/
                 ├── model/
                 ├── model_metadata.json
                 ├── feature_registry.json
                 ├── categorias_esperadas.json
                 └── distribuicoes_esperadas.json
```

Tudo no mesmo bucket. Acessível de qualquer worktree e do Cloud Run, desde que a service account tenha permissão no bucket.

---

## Plano de execução

### Passo 1 — Criar bucket GCS

```bash
gcloud storage buckets create gs://bring-data-mlflow \
  --project=smart-ads-451319 \
  --location=us-central1 \
  --uniform-bucket-level-access
```

Dar permissão à service account do Cloud Run:

```bash
gcloud storage buckets add-iam-policy-binding gs://bring-data-mlflow \
  --member="serviceAccount:$(gcloud run services describe bring-data-api \
    --region=us-central1 --format='value(spec.template.spec.serviceAccountName)')" \
  --role="roles/storage.admin"
```

### Passo 2 — Migrar runs existentes

Copiar os runs locais (todos os worktrees) para o GCS antes de mudar o código.

```bash
# Worktree main (modelo ativo 2a98e51c)
gsutil -m cp -r /Users/ramonmoreira/Desktop/bring_data/V2/mlruns/ \
  gs://bring-data-mlflow/mlruns/

# Worktree refactor (runs do refactor)
gsutil -m cp -r /Users/ramonmoreira/Desktop/bring_data_refactor/V2/mlruns/ \
  gs://bring-data-mlflow/mlruns/

# Run na raiz do refactor (bug de path)
gsutil -m cp -r /Users/ramonmoreira/Desktop/bring_data_refactor/mlruns/ \
  gs://bring-data-mlflow/mlruns/
```

> **Nota:** Se houver runs com o mesmo `run_id` em múltiplos worktrees (improvável mas possível), o último `cp` vence. Verificar antes.

### Passo 3 — Atualizar `training_model.py`

**Mudança em `src/model/training_model.py` (~linha 26):**

```python
# ANTES
mlflow.set_tracking_uri("sqlite:///mlflow.db")

# DEPOIS
import os
_MLFLOW_TRACKING_URI = os.environ.get(
    "MLFLOW_TRACKING_URI",
    "gs://bring-data-mlflow"   # default remoto
)
mlflow.set_tracking_uri(_MLFLOW_TRACKING_URI)
```

O `MLFLOW_TRACKING_URI` pode ser sobrescrito por env var, o que permite:
- Produção/Cloud Run: usa `gs://bring-data-mlflow` (default ou var explícita)
- Testes locais sem GCS: `MLFLOW_TRACKING_URI=sqlite:///mlflow.db python -m ...`

### Passo 4 — Atualizar leitura de artefatos (prediction.py, encoding.py)

Substituir os paths hardcoded por `mlflow.artifacts.download_artifacts()`:

**`src/model/prediction.py:132` — ANTES:**
```python
mlruns_path = Path(__file__).parent.parent.parent / "mlruns" / "1" / self.mlflow_run_id / "artifacts"
```

**DEPOIS:**
```python
import mlflow
mlruns_path = Path(mlflow.artifacts.download_artifacts(
    run_id=self.mlflow_run_id,
    dst_path=str(Path(tempfile.mkdtemp()) / self.mlflow_run_id)
))
```

> Alternativa mais simples: usar `mlflow.pyfunc.load_model(f"runs:/{run_id}/model")` diretamente.

**`src/core/encoding.py:53` e `src/features/encoding.py:263` — mesma mudança.**

### Passo 5 — Variável de ambiente no Cloud Run

```bash
gcloud run services update bring-data-api \
  --region=us-central1 \
  --set-env-vars MLFLOW_TRACKING_URI=gs://bring-data-mlflow
```

### Passo 6 — Adicionar mlflow a api/requirements.txt

```
mlflow==2.14.3
google-cloud-storage>=2.14.0  # já está, confirmar versão
```

---

## Impacto em produção

### O que NÃO muda

- Endpoints da API (`/predict/batch`, `/webhook/*`, etc.)
- Banco de dados Railway (leads_capi) — sem relação com MLflow
- `configs/active_model.yaml` — continua apontando para `mlflow_run_id`
- Lógica de scoring/predição — só o carregamento do modelo muda
- CAPI integration, monitoramento operacional

### O que muda

| Componente | Antes | Depois | Risco |
|---|---|---|---|
| `training_model.py` | Salva em `sqlite:///mlflow.db` local | Salva em `gs://bring-data-mlflow` | **Zero produção** — só treino local |
| `prediction.py` | Lê de `mlruns/1/{run_id}/` dentro do container | `mlflow.artifacts.download_artifacts()` | Apenas em novos deploys |
| `core/encoding.py` | Lê de `mlruns/` dentro do container | Idem | Apenas em novos deploys |
| `features/encoding.py` | Idem | Idem | Apenas em novos deploys |
| `deploy_capi.sh` | Copia mlruns/ local → Docker image | Baixa artefatos do GCS antes do build | Apenas em novos deploys |
| Container em produção hoje | Artefatos embutidos na imagem (imutável) | Não muda — imagem não é recriada | **Zero** |

### Garantia de produção

**O container em produção hoje não será afetado por NADA nas fases 1–4.** A imagem Docker é imutável — tem os artefatos de `mlruns/1/2a98e51c.../artifacts/` embutidos desde o `docker build`. Nenhuma mudança de tracking URI, de worktree, ou de mlruns/ local atinge o que está rodando.

Quando um novo modelo for deployado (fase 5), o `deploy_capi.sh` precisará baixar os artefatos do GCS antes do `docker build`. Até lá, o deploy continua igual ao atual.

---

## Sequência de migração segura

```
FASE 1 — Zero impacto em produção (container atual inalterado)
──────────────────────────────────────────────────────────────
1. Criar bucket GCS                          → infra apenas
2. Migrar runs existentes para GCS           → cópia, sem deletar local
3. Atualizar training_model.py               → só treino local muda
4. Validar: treinar novo modelo, confirmar   → zero impacto em produção
   que run aparece no GCS e é acessível        O container atual continua
   de ambos os worktrees                       rodando com artefatos embutidos

FASE 2 — Próximo deploy (novo modelo)
──────────────────────────────────────────────────────────────
5. Atualizar prediction.py + encoding.py     → muda apenas no próximo build
   Atualizar deploy_capi.sh para baixar        docker build → novo container
   artefatos do GCS antes do docker build    → Rollback: reverter para
                                               deploy_capi.sh antigo

FASE 3 — Limpeza
──────────────────────────────────────────────────────────────
6. Remover mlruns/ locais                    → após 1+ deploy validado com GCS
```

---

## Dependências de pacotes

```
# Para usar GCS como MLflow backend:
mlflow>=2.14.3
google-cloud-storage>=2.14.0

# Autenticação (já configurada via Application Default Credentials)
# gcloud auth application-default login  ← local
# Service account com roles/storage.admin ← Cloud Run
```

---

## Verificação pós-migração

```bash
# 1. Confirmar que o run está no GCS
gsutil ls gs://bring-data-mlflow/1/2a98e51ca4834697bbc94ec3dd31fcf7/

# 2. Confirmar que o treino salva no GCS
MLFLOW_TRACKING_URI=gs://bring-data-mlflow \
  python -m V2.src.train_pipeline --no-api-data --use-cached-data

# 3. Confirmar que o novo run aparece de ambos os worktrees
# (rodar de bring_data/ e de bring_data_refactor/ e ver o mesmo run)

# 4. Confirmar que a API ainda pontua corretamente após deploy
curl -X POST https://bring-data-api-12955519745.us-central1.run.app/predict/batch \
  -H "Content-Type: application/json" \
  -d '{"leads": [...]}'
```
