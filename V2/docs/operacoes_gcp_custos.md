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

**Atualização (2026-05-06, mesmo dia, pós-investigação):** o usuário confirmou que `LeadQualified` continua sendo usado em produção pelas campanhas Meta. **A desativação foi revertida** algumas horas depois — `send_both_lead_events` voltou a enviar os dois eventos por lead.

Mitigação efetiva do worker timeout que ficou em produção:

- Os 4 blocos `🔍 DEBUG` em `send_lead_qualified_with_value` que faziam `json.dumps(indent=2)` em payload nested **continuam removidos** (~50-100ms CPU/lead economizado).
- O Dockerfile já tinha `--timeout 1200s` (20 min), que é o teto razoável — aumentar mais não resolve.

Próximas opções para reduzir timeout, caso volte a ocorrer:

1. Paralelizar as 2 chamadas Meta API com `asyncio.gather` em vez de chamar sequencialmente.
2. Limitar batch size em `/railway/process-pending` (processar no máximo N leads por poll).
3. Aumentar workers do gunicorn (atualmente `--workers 2`) se a memória do container suportar.

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

---

## Investigação de spike de custo — 2026-05-14

Custo diário do projeto saltou de ~R$ 22-32/dia (baseline de abril) para R$ 90-120/dia entre 09/mai e 13/mai, com pico de R$ 120,51 em 12/mai. Em pace de gasto ~4× o baseline.

### Causa-raiz identificada

O serviço Cloud Run `smart-ads-api` está configurado com `min-instances=1`, `CPU=2`, `memory=2Gi`. Cada revisão que tem uma **tag de tráfego** associada (`--tag=canary-<timestamp>`) mantém **sua própria instância sempre ligada**, mesmo com 0% de tráfego — porque a tag gera URL dedicada (`https://canary-<ts>---smart-ads-api-...run.app`) que precisa estar pronta pra responder.

O script de deploy (`V2/api/deploy_capi.sh`) cria essa tag em todo deploy `--no-traffic` (necessária para que o smoke test, a auditoria de YAML dentro da imagem e o teste de paridade de scoring — coletivamente os "Gates B/C/D" — consigam bater na revisão isoladamente, sem dar tráfego pra ela). Mas o script **nunca removia as tags antigas**, então cada deploy adicionava +1 instância 24×7 ao serviço.

**Auditoria em 14/mai mostrou:** 33 tags `canary-*` ativas no serviço, 32 delas em revisões com 0% de tráfego. Cada tag mantendo ~R$ 4-5/dia (24h × 2 vCPU × 2 GiB always-on) — ~R$ 130/dia desperdiçados no pico.

**Linha do tempo do acúmulo (estimativa por SKU "Services Min Instance CPU/Memory"):**

```
14-30/abr: ~10 revisões tagueadas    → ~R$ 22/dia (baseline)
05/mai:    4 deploys em um dia → 9   → R$  47/dia
06/mai:    +2                  → 11  → R$  60/dia
08/mai:    +10 deploys → 21         → R$  52/dia
09-13/mai: continua acumulando → 32  → R$ 105/dia (média)
12/mai:    pico                      → R$ 120/dia
```

Não houve mudança de tráfego, de imagem ou de config de container. O salto é 100% do acúmulo de tags.

### Remediação aplicada (2026-05-14)

| Ação | Estado | Economia/dia |
|---|---|---|
| Remoção das 32 tags `canary-*` obsoletas via `gcloud run services update-traffic --remove-tags=...` | ✅ | ~R$ 70-80 |
| Bloco de cleanup adicionado ao `V2/api/deploy_capi.sh` (linhas ~505-528 da função `deploy_to_cloud_run`) — antes de cada deploy `--no-traffic`, lista tags `canary-*` em revisões com `percent == 0` e remove. Tags em revisões com tráfego > 0 (produção + canary parcial em andamento) são preservadas | ✅ | preventivo |

**Tag preservada:** `canary-1778618296` → revisão `smart-ads-api-00447-zuc` (100% de tráfego em produção em 14/mai).

**Projeção pós-fix:** ~R$ 25-30/dia, volta ao baseline.

### Comando para auditar tags futuramente

```bash
gcloud run services describe smart-ads-api \
  --project=smart-ads-451319 --region=us-central1 --format=json \
  | python3 -c "
import json, sys
traffic = json.load(sys.stdin).get('status', {}).get('traffic', [])
print(f'Total entries: {len(traffic)}')
for t in traffic:
    tag = t.get('tag', '(no tag)')
    rev = t.get('revisionName', '?')
    pct = t.get('percent', 0)
    flag = '  ←⚠️ always-on sem tráfego' if pct == 0 and tag.startswith('canary-') else ''
    print(f'{tag:<25} {rev:<28} {pct:>3}%{flag}')
"
```

**Sinal de alarme:** se aparecer mais de 2-3 tags `canary-*` simultâneas em revisões com `0%`, o cleanup automático do `deploy_capi.sh` falhou — investigar. Em fluxo normal, espera-se no máximo 2 tags ativas: a revisão em produção + a revisão recém-deployada em smoke test.

### Pegadinha do cleanup automático

O cleanup remove tags de **qualquer** revisão com 0% de tráfego, incluindo uma revisão recém-deployada **se ainda estiver em smoke test em outra sessão paralela**. Operador deve garantir, antes de rodar o `deploy_capi.sh`, que não há outra sessão executando smoke test contra uma revisão `--no-traffic` recém-criada. Se houver, esperar promoção (revisão ganha tráfego > 0) ou descarte (revisão deletada) antes do novo deploy.

### Fatores secundários no mesmo período

- **Créditos sumiram após 02/mai (~R$ 15/dia):** havia desconto não-rotulado aplicado só em 01-02/mai (padrão de Sustained Use Discount retroativo do mês anterior). Sem essa linha, o "custo líquido" parecia subir mais que o bruto. Não é regressão — é como o GCP fatura.
- **Cloud SQL `smart-ads-db` reativado em 09/mai (~R$ 1,35/dia):** o que apareceu como "instância Micro nova" no billing é a própria `smart-ads-db` que foi ligada (`activation-policy=ALWAYS`) em sessão anterior — não uma instância separada. Em 14/mai foi devolvida pra `NEVER`. Detalhes da continuação abaixo.

---

## Eliminação de min-instances no Cloud Run — 2026-05-14

Após o fix de tags `canary-*` acumuladas (ver seção acima), a conta de Cloud Run ainda tinha **~R$ 9/dia em min-instance always-on**: a revisão em produção (`min-instances=1`, 2 vCPU, 2 GiB) mantinha uma instância ligada 24h. Cliente confirmou que o serviço **não tem interface humana** — só recebe webhook do front e dispara CAPI pra Meta em janela de minutos. Cold start de 5-15s em request após idle é invisível pro sinal.

### Verificações feitas antes da mudança

| Hipótese a descartar | Resultado |
|---|---|
| Há background task / scheduler dentro do container? | **Não.** `api/app.py:199` só faz `initialize_pipelines()`, `init_database()` e `validate_capi_destinations` no startup. Sem threads persistentes. |
| Polling do Railway depende de instância viva? | **Não.** Cloud Scheduler externo dispara `/railway/process-pending` a cada 5 min — Cloud Run sobe instância sob demanda. |
| `encoding.py` chama MLflow em runtime e quebraria sem Cloud SQL? | **Não.** `core/encoding.py:51-72` está em `try/except` com fallback `experiment_id='1'` e lê `feature_registry.json` do filesystem local da imagem Docker. |
| Min-instance faz algo além de evitar cold start? | **Não.** Confirmado por leitura de código. |

### Ações aplicadas

| Ação | Comando | Estado |
|---|---|---|
| Template do serviço com `min-instances=0` | `gcloud run services update smart-ads-api --min-instances=0 --region=us-central1` | ✅ aplicado em 14/mai ~07h BRT |
| Cloud SQL `smart-ads-db` voltou pra NEVER | `gcloud sql instances patch smart-ads-db --activation-policy=NEVER --project=smart-ads-451319` | ✅ aplicado em 14/mai |
| Tag órfã `canary-1778752864` removida (revisão `00460-vak` criada pelo `update` veio com `minScale=1`; tag a mantinha cobrando) | `gcloud run services update-traffic smart-ads-api --remove-tags=canary-1778752864 --region=us-central1` | ✅ aplicado |

### Pegadinha encontrada — `--min-instances=0` cria revisão nova com annotation persistente

Rodar `gcloud run services update --min-instances=0` removeu a annotation `autoscaling.knative.dev/minScale` do **template do serviço** mas a **revisão nova criada** pelo próprio comando manteve `minScale=1` na sua annotation. Como o comando também associa uma tag canary à revisão nova, a revisão órfã passa a cobrar min-instance até a tag ser removida.

**Fix manual aplicado:** remover a tag da revisão órfã. **Para próxima vez:** preferir `gcloud run services update smart-ads-api --clear-min-instances` (testar) ou aplicar a remoção da annotation diretamente.

### Estado em que efetivamente cai pra `min=0` em produção

O template está com `minScale=unset`, mas a **revisão atualmente em 100% de tráfego** (`smart-ads-api-00447-zuc`) ainda tem `minScale=1` na annotation dela (foi criada com a config antiga). Min-instance dela só desliga quando:

1. Uma nova revisão (criada via `gcloud run deploy` ou `gcloud run services update`) sobe pra 100% de tráfego, **E**
2. A 00447-zuc perde sua tag canary (o `deploy_capi.sh` faz isso automaticamente no próximo deploy via cleanup).

Próximo deploy normal já resolve. Se quiser forçar agora, basta deployar a mesma imagem com `--clear-min-instances` ou aguardar o ciclo de canary natural.

### Guardrails adicionados aos scripts de treino

Como `Cloud SQL smart-ads-db` agora fica em `NEVER` por padrão (economia ~R$ 40/mês), os scripts de treino e retreino podem falhar com erro críptico de SQLAlchemy se o usuário esquecer de ligar a instância antes. Adicionamos:

- `src/model/training_model.py` (novas funções `assert_mlflow_backend_running()` + `register_mlflow_cleanup_reminder()`) — valida via `gcloud sql instances describe` que estado é `RUNNABLE`. Levanta erro claro com comando de fix se não.
- `src/train_pipeline.py:main()` — chama o assert + registra atexit de lembrete pra desligar.
- `src/retrain/retraining_orchestrator.py:main()` — idem.

**Não automatiza o stop** porque sessões paralelas (múltiplos Claude Code, retreino + investigação simultâneos) podem precisar do Cloud SQL juntas — só lembra no final.

### Projeção pós-mudanças completas

| Item | R$/dia antes | R$/dia depois |
|---|---:|---:|
| Min-instance always-on (1 inst × 2 vCPU × 2 GiB) | 9 | 0 |
| Cloud SQL `smart-ads-db` (ALWAYS) | 1,35 | 0 |
| Cloud SQL `smart-ads-db` (NEVER — IP+storage residual) | — | 0,50 |
| Request-based CPU (carga real) | 3 | 3 |
| Storages, BQ, egress | 0,5 | 0,5 |
| **Total** | **~14** | **~4-5** |

**Atinge o objetivo de R$ 5-10/dia**, com sobra. Em meses com retreino (instância ligada por 1-2 dias), pico de ~R$ 6-8 por aqueles dias.

### Checklist de monitoramento agressivo pós-mudança (próximas 2-3h)

Como **derrubamos min-instance em prod**, validar que o serviço continua respondendo bem:

1. **Latência (Cloud Run Console → Metrics)**
   - p50 de `/predict/batch` antes vs depois — esperado: aumento mínimo (já era ~50-200ms request-based).
   - p95 de `/predict/batch` — **esperado: spike inicial em requests após idle** (cold start 5-15s nos primeiros leads após gap de >15 min). Em janelas de alta carga (lançamento ativo), instância fica quente → spike só na madrugada.
   - URL: `https://console.cloud.google.com/run/detail/us-central1/smart-ads-api/metrics?project=smart-ads-451319`

2. **Taxa de erro (mesma página)**
   - Esperado: zero. Cold start não causa erro, só latência.
   - Se aparecer 5xx, ação: `gcloud run services update smart-ads-api --region=us-central1 --min-instances=1` (volta em 60s).

3. **Logs Cloud Run** — buscar regressões
   ```
   gcloud logging read 'resource.type=cloud_run_revision AND \
     resource.labels.service_name=smart-ads-api AND severity>=ERROR' \
     --limit=20 --format='value(textPayload)' --freshness=2h
   ```
   Atenção a: `STARTUP CHECK ❌ FATAL` (algum check do `validate_capi_destinations`), `OOMKilled`, `worker timeout`.

4. **CAPI enviando**
   - Bater no endpoint de stats internas ou monitoramento Slack.
   - Confirmar volume de eventos `LeadQualified` + `LeadQualifiedHighQuality` por hora bate com o dia anterior.

5. **Métrica de instâncias ativas (Cloud Run Console)**
   - Esperado: 0-3 instâncias ativas em pico (era sempre ≥1).
   - Vale 0 em madrugada quando não há tráfego.

6. **Rollback rápido se algo falhar**
   ```bash
   gcloud run services update smart-ads-api \
     --region=us-central1 --min-instances=1 --project=smart-ads-451319
   ```
   Effetua em ~60s. Não precisa redeployar.

---

## Fix do startup probe — eliminação do churn de container — 2026-05-14

Descoberto durante o monitoramento pós min-instances=0: uma regressão crítica vinha aumentando os SIGABRTs desde 06/mai.

| Dia | SIGABRTs/dia |
|---|---:|
| 06/mai (incidente conhecido) | 460 |
| 12/mai | 644 |
| **13/mai** | **1640** (3.5× o pico antigo) |
| 14/mai (até 09h UTC) | 716 parcial |

**Diagnóstico inicial estava errado.** Não era worker timeout em batches grandes do `/railway/process-pending` (p99=8.4s, max=10.5s — longe dos 1200s do gunicorn). Os `Uncaught signal: 6` na verdade eram **Cloud Run derrubando containers inteiros** durante o startup. Em 09:23 UTC do dia 14/mai vimos 29 `Handling signal: term` num único minuto — sinal de container churn massivo.

### Causa-raiz real

Startup probe do Cloud Run estava com tolerância zero:

```yaml
startupProbe:
  failureThreshold: 1       # uma única falha derruba o container
  periodSeconds: 240
  timeoutSeconds: 240
  tcpSocket: { port: 8080 }
```

Trio que causava o churn:

1. **A/B test dobrou o tempo de startup.** `LeadScoringPipeline.__init__` (`production_pipeline.py:107`) agora carrega 2 modelos (champion + challenger), ~10-15s.
2. **Probe TCP é fraco.** Verifica só se algo está escutando na porta, não se a API está pronta. Master do gunicorn faz bind cedo, antes do modelo carregar — probe inicial passa, mas requests reais que chegam antes do modelo carregar travam.
3. **`failureThreshold: 1` derruba na primeira falha.** Em alta carga (madrugada brasileira do lançamento ativo), Cloud Run escala. Cada container passa pela janela frágil de 10-15s. Probe falha em alguns → container morre → spawna outro → cluster de SIGABRT.

### Histórico do probe

Revisões antigas (00100–00400) **não tinham startup probe configurado** — usavam default mais tolerante. Algum deploy entre 00400 e 00447 introduziu essa config, provavelmente junto com a ativação do A/B test, mas com tolerância inadequada pro novo tempo de startup. Não encontramos commit explícito.

### Fix aplicado

```bash
gcloud run services update smart-ads-api \
  --region=us-central1 --project=smart-ads-451319 \
  --startup-probe=tcpSocket.port=8080,failureThreshold=3,periodSeconds=240,timeoutSeconds=240
```

Apenas `failureThreshold` mudou: **1 → 3**. Criou revisão `smart-ads-api-00326-v9x` com a **mesma imagem** que estava em prod (`sha256:a13148...`) — único delta é a tolerância do probe. Promovida pra 100% via `update-traffic`.

### Validação imediata pós-promoção (14/mai ~09:33 UTC)

- Cold start: 19.4s (esperado pelo carregamento dos 2 modelos).
- Warm requests sequenciais: 240ms consistente.
- SIGABRT nos 5min pós-promoção: **0**.
- Container subiu limpo em 42s, probe tolerou.

### Próximo passo se persistir (não aplicado hoje)

Se a contagem de SIGABRT/dia não cair como esperado, aplicar fix robusto:

1. **Corrigir `/health` pra retornar HTTP 503 quando `pipelines` está vazio** (`api/app.py:245-258` — hoje sempre retorna 200, então não serve como probe HTTP útil). Mudança de 2 linhas.
2. **Trocar startup probe pra HTTP em `/health`**:
   ```bash
   gcloud run services update smart-ads-api --region=us-central1 \
     --startup-probe=httpGet.path=/health,httpGet.port=8080,failureThreshold=3,periodSeconds=10,timeoutSeconds=5
   ```

Exige deploy pelos Gates por causa da mudança de código.

### Plano de monitoramento — confirmar fix na madrugada 14→15/mai

Janela crítica é 00h-06h BRT (03h-09h UTC) quando o lançamento gera o pico de leads. Checagens recomendadas em 15/mai ~07h BRT:

```bash
# Contagem total de SIGABRT últimas 24h — esperado: <100 (era 1640 em 13/mai)
gcloud logging read 'resource.type=cloud_run_revision AND \
  resource.labels.service_name=smart-ads-api AND "Uncaught signal: 6"' \
  --project=smart-ads-451319 --freshness=24h --limit=3000 --format='value(timestamp)' | wc -l

# Distribuição por hora UTC — esperado: zero ou poucos em 03h-09h
gcloud logging read 'resource.type=cloud_run_revision AND \
  resource.labels.service_name=smart-ads-api AND "Uncaught signal: 6"' \
  --project=smart-ads-451319 --freshness=24h --limit=3000 --format='value(timestamp)' \
  | awk -F'T' '{print substr($2,1,2)}' | sort | uniq -c
```

**Critério de sucesso:**
- SIGABRT/dia cai de ~1640 → <100 (idealmente <30).
- Nenhum cluster de 29 SIGTERMs num minuto se repete.

**Se não cair:** aplicar fix robusto (corrigir `/health` + probe HTTP).
