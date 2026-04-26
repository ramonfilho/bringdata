# Operações GCP — Custos e Procedimentos

**Atualizado:** 2026-04-26
**Propósito:** registro do que foi otimizado em custo no GCP, procedimentos para retomar recursos parados e bugs latentes descobertos durante a auditoria.

---

## Otimizações aplicadas em 2026-04-26

Auditoria de custo identificou ~R$ 167/mês de gasto desnecessário. Ações tomadas:

| Ação | Estado | Economia/mês |
|---|---|---|
| Cloud Run `bring-data-api` deletado (sem tráfego, com `min-instances=1`) | ✅ | ~R$ 75 |
| Cloud SQL `smart-ads-db` parado (`activation-policy=NEVER`) | ✅ | ~R$ 75 |
| 6 repos órfãos GCR deletados (`smart-ads-api-final/-fix/-strict`, `smartads-api`, `smartads`, `smart-ads-apiatest`) | ✅ | ~R$ 5 |
| Imagens `bring-data-api` removidas (todas as 56 digests) | ✅ | ~R$ 5 |
| Cleanup policy automática em `gcr.io` (us): keep 30 mais recentes + delete >60d untagged / >90d com tag `v2026*`, protege tags `prod-*` | ✅ | ~R$ 5/mês contínuo |
| Lifecycle `gs://run-sources-*` (delete >30d) e `gs://smart-ads-mlflow` (Coldline >60d, Archive >365d) | ✅ | ~R$ 2 |
| Digest da revisão de produção (`f439d7c…`) tagueada como `prod-current` para sobreviver à cleanup policy | ✅ | — |
| Binding vestigial `cloudsql-instances` removido do `smart-ads-api` (rev. 00276, sem tráfego, fica no template para próximo deploy) | ✅ | — |

**Não tocados intencionalmente:**

- `MIN_INSTANCES=1` mantido no `smart-ads-api` — tráfego é contínuo 24/7 (~37 req/h no vale, ~270 req/h no pico), `minScale=0` causaria cold start visível.
- `MEMORY=2Gi` / `CPU=2` mantidos — log de 2026-04-26 02:45 mostrou `Memory limit exceeded with 2049 MiB used`. Downsize quebra produção.
- `MAX_INSTANCES=100` mantido — guardrail; não afeta cobrança real.
- Cloud Scheduler `railway-polling` (a cada 5 min) — investigar ponto de eficiência junto à janela de leitura da Meta antes de mexer.

---

## Cloud SQL `smart-ads-db` — protocolo para retreino

A instância está parada (`activation-policy=NEVER`) porque MLflow só é necessário durante retreinos (~1×/mês). Storage preservado.

**Por que isso é seguro:** o modelo em produção não consulta MLflow em runtime — os artefatos (`model.pkl`, `feature_registry.json`, etc.) são bakeados na imagem Docker no build (`api/Dockerfile:52`, ver `docs/arquivo/MIGRACAO_MLFLOW_GCS.md`). A API usa Railway PostgreSQL (`leads_capi`), não Cloud SQL.

**Antes de retreinar:**

```bash
# Subir Cloud SQL
gcloud sql instances patch smart-ads-db \
  --activation-policy=ALWAYS \
  --project=smart-ads-451319

# Aguardar state=RUNNABLE (~2-3 min)
gcloud sql instances describe smart-ads-db \
  --project=smart-ads-451319 \
  --format='value(state)'

# Treinar
python -m src.train_pipeline --initial-matching email_telefone --set-active
```

**Depois de retreinar:**

```bash
# Parar Cloud SQL
gcloud sql instances patch smart-ads-db \
  --activation-policy=NEVER \
  --project=smart-ads-451319
```

**Tracking URI:** hardcoded em `src/model/training_model.py:28` apontando para `104.197.138.129:5432/mlflow`. Funciona quando a instância está `ALWAYS`.

---

## Cleanup policy do Artifact Registry

Aplicada em `gcr.io` (location `us`), roda automaticamente todo dia. Regras:

```json
[
  {"name": "keep-prod-current",   "action": "Keep",   "tagState": "TAGGED",   "tagPrefixes": ["prod-"]},
  {"name": "keep-most-recent-30", "action": "Keep",   "mostRecentVersions":   {"keepCount": 30}},
  {"name": "delete-untagged-old", "action": "Delete", "tagState": "UNTAGGED", "olderThan": "60d"},
  {"name": "delete-tagged-old",   "action": "Delete", "tagState": "TAGGED",   "olderThan": "90d", "tagPrefixes": ["v2026"]}
]
```

**Convenção:** sempre que mudar a revisão de produção do `smart-ads-api`, mover a tag `prod-current` para a nova digest:

```bash
gcloud container images add-tag \
  gcr.io/smart-ads-451319/smart-ads-api@sha256:<NOVA_DIGEST> \
  gcr.io/smart-ads-451319/smart-ads-api:prod-current --quiet
```

Caso contrário a digest antiga pode ser purgada pela policy se sair das 30 mais recentes.

---

## Bugs latentes descobertos durante a auditoria

### `/railway/process-pending` — `.str accessor with string values`

`POST /railway/process-pending` retorna HTTP 500 quando o batch tem **1 lead único** e esse lead tem valor não-string (NaN/None) em alguma coluna UTM (`Source` ou `Term`).

```
ERROR - Erro no polling Railway: Can only use .str accessor with string values!
HTTP 500
```

**Frequência:** ~0.3% dos polls (1 a cada ~300 batches; cai principalmente na madrugada quando o volume é baixo).

**Impacto real:** mitigado — o lead é reprocessado no poll seguinte quando o batch volta a ter ≥2 leads ou o valor não-NaN.

**Causa provável:** unificação UTM em `src/core/utm.py` (ou `src/core/column_unification.py`) chama `.str.lower()` numa coluna que pode ter NaN quando há 1 só registro. Pandas levanta o erro.

**Fix sugerido:** `df[col].astype(str).fillna('')` antes do `.str.lower()`, ou pular a unificação quando `len(df) <= 1` e a coluna está nula.

**Rastrear pela query:** `severity=ERROR AND textPayload=~"\.str accessor"` em `smart-ads-api`.

### `/bigquery/stats` retorna 0 rows

O sync para BigQuery aparentemente nunca foi ativado em produção (ou foi descontinuado). Não há erro — só tabela vazia. Se BigQuery não está em uso, considerar deletar dataset/tabela vazios para higiene (não gera custo).

---

## Pendências para discussão futura

1. **Railway-polling 5min**: investigar ponto de eficiência junto à janela de leitura da Meta. Possível folga sem perder sinal.
2. **Migrar MLflow para SQLite + GCS** (option B descartada agora): eliminaria os ~R$ 9/mês remanescentes do storage da instância parada. Refactor pequeno mas precisa testar concorrência no retreino.
3. **Revisões canário órfãs do `smart-ads-api`** (00270, 00271, 00357, 00360, 00274, 00275, 00276): 0% tráfego, podem ser deletadas via `gcloud run revisions delete` para destravar limpeza de imagens antigas.
4. **Fix do bug `.str accessor`** no `/railway/process-pending`.
