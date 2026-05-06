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

---

## Investigação de spike de custo — 2026-05-06

Usuário recebeu alertas de budget consecutivos (90% à 00:23 BRT, 100% às 06:11 BRT do mesmo dia). Cumulativo do mês cruzou R$ 150 ainda no dia 6 — em pace de gasto ~3× o esperado.

### Causa-raiz identificada

Worker timeout do gunicorn em batches grandes do `/railway/process-pending`, alimentando ciclo de respawn que queima CPU continuamente.

**Sequência:**

1. `send_batch_events` chamava `send_both_lead_events` para cada lead, que enfileirava **2× chamadas síncronas para Meta CAPI API** (LeadQualified-com-valor + LeadQualifiedHighQuality), ~1-2s cada.
2. Cada lead também emitia ~50-80 linhas de log debug (`🔍 DEBUG JSON EXATO enviado para Meta API`, `🔍 DEBUG Resposta da Meta API`, etc.) com `json.dumps(indent=2)` em payload nested — adicionava ~50-100ms de CPU por lead.
3. Em batches grandes (lançamento ativo, ~3000 leads/dia), o tempo total ultrapassava `--timeout 1200s` do gunicorn (que já é 20 min) — worker era morto com SIGABRT.
4. Master gunicorn spawnava worker novo, que recarregava o modelo na RAM (5-10s) e retomava o batch. Os requests reprocessavam parcialmente.
5. Em janela de 1h pós-meianoite de 06/05: 25+ workers mortos, CPU em alta sustentada.

**Frequência observada (SIGABRT/dia):**

```
01/05: 134
02/05: 288
03/05: 380
04/05: 426
05/05: 460  ← pico, véspera do alerta
06/05: 312
```

Crescimento exponencial casava com aumento de tráfego do lançamento + acúmulo de DEBUG verboso.

**Diagnóstico do que NÃO era a causa:**

- Tráfego: 5–12k requests/dia, estável.
- Volume de logs Cloud Logging: ~10 MB/dia (free tier de 50 GB/mês cobre).
- Cloud SQL: confirmado parado (não foi reativado).
- `bring-data-api`: ainda deletado.
- Múltiplas instâncias Cloud Run em paralelo: máximo 1 por hora.

### Mitigações aplicadas (2026-05-06)

| Ação | Onde | Impacto esperado |
|---|---|---|
| Desativar evento `LeadQualified` (com valor) — manter apenas `LeadQualifiedHighQuality` | `api/capi_integration.py` `send_both_lead_events` | Cada lead passa de 2 chamadas Meta API → 1 (e zero para D1-D8 dado que HQ filtra D9-D10). Reduz tempo de processing por lead em ~50%. |
| Remover 4 blocos `🔍 DEBUG` em `send_lead_qualified_with_value` (com `json.dumps` em payload nested) | `api/capi_integration.py` linhas 375-380, 404-422, 446-458, 986 (pré-edição) | Corta ~50-100ms por lead + ~50 linhas de log por lead |
| Habilitar billing export para BigQuery | dataset `smart-ads-451319.billing_export` (criado, falta switch no Console) | Daqui em diante: query precisa por SKU/dia em `gcp_billing_export_v1_*` |

**Não aplicado intencionalmente:**

- **Aumentar gunicorn `--timeout`**: já está em `1200s` (20 min) no `Dockerfile:89`. Aumentar mais não resolveria — o problema não era timeout curto, mas batches que demoravam >20 min.
- **Congelar deploys**: não viável — desenvolvimento ativo precisa de deploys. Investigação seguiu pelas duas mitigações de código acima.

### Trade-offs do drop do `LeadQualified`-com-valor

- ✅ Cessa a sangria de CPU/timeout no worker.
- ⚠️ **Meta perde sinal de valor** (ROAS optimization). Campanhas que otimizam por value não terão dados.
- ⚠️ **D1-D8 (80% dos leads) deixa de mandar evento Meta**: `LeadQualifiedHighQuality` filtra internamente para D9-D10. Em runtime, 80% das chamadas Meta API param.

Decisão do usuário (2026-05-06): aceitar trade-off "por enquanto", pois campanhas ativas no Business Manager estão otimizando por `LeadQualifiedHighQuality`. Reativação do evento com-valor requer descomentar bloco em `send_both_lead_events` (marcado em comentário no código).

### Procedimento para configurar billing export (passo manual)

Dataset `billing_export` em `us` já criado em `smart-ads-451319`. Falta switch no Console:

1. Acesse: `https://console.cloud.google.com/billing/<BILLING_ACCOUNT>/export`
2. **Standard usage cost** → EDIT SETTINGS → projeto `smart-ads-451319`, dataset `billing_export` → Save
3. (Opcional) **Detailed usage cost** → mesmo dataset → Save (granularidade por SKU)

Após ~24h aparecem tabelas `gcp_billing_export_v1_*` e `gcp_billing_export_resource_v1_*`. Próxima investigação consegue isolar custo por SKU, projeto e dia.

### Budget alerts já configurados

Budget existente: **R$ 150 Alerta de orçamento mensal**. Thresholds:

```
50%  (R$ 75)
90%  (R$ 135)  ← disparou 06/05 00:23 BRT
100% (R$ 150)  ← disparou 06/05 06:11 BRT
150% (R$ 225)  ← previne ultrapassagem maior
```

50% também está ativo — mas se o usuário não recebeu, provavelmente foi cruzado em silêncio em algum dia anterior do mês.
