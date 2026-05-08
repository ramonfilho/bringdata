# BigQuery sinks — observabilidade do Cloud Run

Este doc cobre os datasets do BigQuery em `smart-ads-451319` usados para
observação em produção (custos, logs estruturados, mirror operacional).

Fonte mais usada para investigar comportamento do CAPI e do scoring:
**`cloudrun_logs.run_googleapis_com_stdout`**.

## Datasets

| Dataset | Conteúdo | Quando usar |
|---|---|---|
| `cloudrun_logs` | Sink do Cloud Logging — todos os logs do Cloud Run em tabelas BQ | Auditar comportamento de produção, verificar value/decil/erros por revisão |
| `devclub` | Mirror da tabela `leads_capi` do Railway | Análises ad-hoc sem subir Cloud SQL |
| `billing_export` | Export de custos GCP | Investigar picos de gasto |

## `cloudrun_logs` — tabelas

| Tabela | Conteúdo | Particionada por |
|---|---|---|
| `run_googleapis_com_stdout` | logs `print()` / `logger.info` da API | `DATE(timestamp)` |
| `run_googleapis_com_stderr` | logs de erro do uvicorn/gunicorn | `DATE(timestamp)` |
| `run_googleapis_com_requests` | request logs (método, status, latência) | `DATE(timestamp)` |
| `cloudaudit_googleapis_com_activity` | audit log de mudanças no serviço (deploy, traffic update) | `DATE(timestamp)` |
| `cloudaudit_googleapis_com_system_event` | eventos do sistema | `DATE(timestamp)` |
| `run_googleapis_com_varlog_system` | logs do sistema | `DATE(timestamp)` |

**SEMPRE filtre por `DATE(timestamp) = ...`** — tabelas particionadas. Sem isso a query
varre histórico completo (caro e lento).

### Schema de `run_googleapis_com_stdout`

Campos relevantes:

| Campo | Conteúdo |
|---|---|
| `timestamp` | TIMESTAMP do evento |
| `textPayload` | mensagem do log (string) |
| `severity` | DEFAULT, INFO, WARNING, ERROR, CRITICAL |
| `resource.labels.service_name` | `smart-ads-api` |
| `resource.labels.revision_name` | revisão Cloud Run que emitiu o log (ex: `smart-ads-api-00403-cez`) |
| `resource.labels.location` | `us-central1` |

`stderr` tem o mesmo schema. `requests` tem schema diferente
(http_request, etc.) — ver `bq show --schema` quando precisar.

## Como o sink foi configurado

`gcloud logging sinks list` no projeto deve mostrar um sink
roteando logs do Cloud Run pra esse dataset. Se precisar recriar:

```bash
gcloud logging sinks create cloudrun_to_bq \
  bigquery.googleapis.com/projects/smart-ads-451319/datasets/cloudrun_logs \
  --log-filter='resource.type="cloud_run_revision"' \
  --project=smart-ads-451319
```

Depois conceder ao service account do sink permissão `roles/bigquery.dataEditor`
no dataset.

## Queries de uso comum

### Q1 — Distribuição de `value` enviado ao CAPI por revisão

Use após promover canary pra observar se o cálculo de value bate
com a tabela esperada (`LEAD_VALUE_BY_DECILE_CHAMPION` em `api/business_config.py`).

```sql
SELECT
  resource.labels.revision_name AS revision,
  REGEXP_EXTRACT(textPayload, r'valor proj: R\$ ([0-9]+\.[0-9]+)') AS value,
  REGEXP_EXTRACT(textPayload, r'decil[: =]+(D\d+)') AS decil,
  COUNT(*) AS events
FROM `smart-ads-451319.cloudrun_logs.run_googleapis_com_stdout`
WHERE DATE(timestamp) = CURRENT_DATE()
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
  AND resource.labels.service_name = 'smart-ads-api'
  AND textPayload LIKE '%LeadQualified enviado%'
GROUP BY revision, value, decil
ORDER BY revision, decil
```

### Q2 — ERRORs por revisão

```sql
SELECT
  resource.labels.revision_name AS revision,
  severity,
  COUNT(*) AS n,
  ANY_VALUE(textPayload) AS sample
FROM `smart-ads-451319.cloudrun_logs.run_googleapis_com_stderr`
WHERE DATE(timestamp) = CURRENT_DATE()
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND severity IN ('ERROR', 'CRITICAL')
GROUP BY revision, severity
ORDER BY n DESC
```

### Q3 — Distribuição de decis em produção

Útil para investigar drift de scoring entre revisões.

```sql
SELECT
  resource.labels.revision_name AS revision,
  REGEXP_EXTRACT(textPayload, r'decil=(D\d+)') AS decil,
  COUNT(*) AS n
FROM `smart-ads-451319.cloudrun_logs.run_googleapis_com_stdout`
WHERE DATE(timestamp) BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
  AND resource.labels.service_name = 'smart-ads-api'
  AND REGEXP_CONTAINS(textPayload, r'decil=D\d+')
GROUP BY revision, decil
ORDER BY revision, decil
```

### Q4 — Volume de eventos LeadQualified vs LeadQualifiedHighQuality

```sql
SELECT
  DATE(timestamp) AS dia,
  COUNTIF(textPayload LIKE '%LeadQualified enviado%' AND textPayload NOT LIKE '%HighQuality%') AS lq,
  COUNTIF(textPayload LIKE '%LeadQualifiedHighQuality enviado%') AS lqhq
FROM `smart-ads-451319.cloudrun_logs.run_googleapis_com_stdout`
WHERE DATE(timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND resource.labels.service_name = 'smart-ads-api'
GROUP BY dia
ORDER BY dia
```

## Episódios já investigados via essas queries

- **VAL=0 (06/05/2026):** Q1 mostrou que entre 30/04 e 06/05 todos os
  `LeadQualified` saíam com `value=0`, expondo o bug do
  `conversion_rates` removido do YAML. Ver `docs/registro_erros_ml.md`
  e DT-17 em `docs/PLANO_REFACTOR_MLOPS.md`.

## Limitações

- Sink tem latência de ~1-2 min do log emitido até estar queryable em BQ.
- `textPayload` é string — quando o log tinha emoji ou f-string complexo,
  regex pode falhar. Sempre validar com `LIMIT 5` antes de agregar.
- Tabelas só são particionadas por dia. Para janelas finas, use
  `timestamp >= TIMESTAMP_SUB(...)` em cima do filtro `DATE(timestamp)`.
