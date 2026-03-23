# Checklist de Deploy — Refactor MLOps (branch `refactor/mlops-core`)

**Contexto:** Branch com ~20 commits, 56 arquivos alterados. Nenhuma lógica de negócio foi mudada — apenas caminhos de import e leitura de config via `ClientConfig`. As parity checks (6/6 PASS) e o treino de confirmação (AUC 0.747) confirmam equivalência comportamental. Este checklist é executado **uma vez**, no momento do merge e deploy deste refactor.

---

## Pré-condições para começar

- [ ] Branch `refactor/mlops-core` está sincronizada com `main` (`git log refactor/mlops-core..main` retorna vazio)
- [ ] `configs/active_models/devclub.yaml` existe e contém `mlflow_run_id: 2a98e51c...`
- [ ] `configs/clients/devclub.yaml` existe e passa `ClientConfig.from_yaml(...).validate()`

---

## Etapa 1 — Validações locais (antes do merge)

### 1A — Pilar D: treino → serve (fazer PRIMEIRO — único pilar que o staging não pega)

O objetivo é confirmar que um novo modelo treinado com o refactor pode ser servido imediatamente, sem quebrar o pipeline de produção.

```bash
cd /Users/ramonmoreira/Desktop/smart_ads_refactor/V2

# 1. Treinar com flag --set-active (usa dados reais, atualiza active_models/devclub.yaml)
python -m src.train_pipeline \
  --initial-matching email_telefone \
  --tmb-risk-filter all \
  --api-end-date 2026-03-15 \
  --set-active

# 2. Confirmar que o YAML foi atualizado com o novo run_id
cat configs/active_models/devclub.yaml

# 3. Confirmar que o pipeline de produção carrega o novo modelo sem erro
python -c "
from src.production_pipeline import LeadScoringPipeline
p = LeadScoringPipeline('devclub')
print('model_name:', p.predictor.metadata['model_info']['model_name'])
print('run_id:', p.predictor.mlflow_run_id)
print('features:', len(p.predictor.metadata['model_info'].get('feature_names', [])))
print('OK')
"
```

**Critério de aprovação:**
- `model_name` contém `"devclub"` (vindo de `model.model_name_template`)
- `features` ≥ 50 (registry carregado corretamente)
- Sem `ImportError`, `KeyError` ou `FileNotFoundError`

> **Nota:** após este passo, `configs/active_models/devclub.yaml` aponta para o modelo recém-treinado.
> Se preferir preservar o modelo atual (`2a98e51c`) em produção, restaure o YAML antes de prosseguir:
> `git checkout configs/active_models/devclub.yaml`

---

### 1B — Smoke tests de imports

```bash
cd /Users/ramonmoreira/Desktop/smart_ads_refactor/V2

python -c "
from src.production_pipeline import LeadScoringPipeline
from src.monitoring.orchestrator import MonitoringOrchestrator
from src.retrain.retraining_orchestrator import RetrainingOrchestrator
from api.app import app
from api.capi_integration import send_batch_events
print('Todos os imports OK')
"
```

---

### 1C — Pilar A: parity checks (scores idênticos)

```bash
cd /Users/ramonmoreira/Desktop/smart_ads_refactor/V2
python scripts/validate_orchestration_layer.py
```

**Critério de aprovação:** 6/6 checks PASS (2a–2f).

---

### 1D — Pilar B: smoke do monitoring

```bash
cd /Users/ramonmoreira/Desktop/smart_ads_refactor/V2

python -c "
from src.monitoring.orchestrator import MonitoringOrchestrator
m = MonitoringOrchestrator('devclub')
print('thresholds:', m._client_config.monitoring.thresholds)
print('model_name:', m._client_config.monitoring.model_name)
print('OK — MonitoringOrchestrator instanciado com ClientConfig')
"
```

---

### 1E — Captura do golden snapshot do monitoring (ANTES do merge)

Este é o snapshot de referência. Ele é capturado com o código atual e serve para comparação após o deploy. Se os alertas divergirem, há uma regressão no path de monitoramento.

```bash
cd /Users/ramonmoreira/Desktop/smart_ads_refactor/V2

# Subir proxy do banco
cloud-sql-proxy smart-ads-451319:us-central1:smart-ads-db --port=5432 &
sleep 8
export DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=smart_ads DB_USER=postgres DB_PASSWORD=SmartAds2026DB!

# Capturar snapshot — dry-run com data fixa para reprodutibilidade
python -c "
import json
from datetime import date
from src.monitoring.orchestrator import MonitoringOrchestrator

m = MonitoringOrchestrator('devclub')
result = m.run_daily_check(
    reference_date=date(2026, 3, 15),  # data fixa — não mudar
    dry_run=True
)

snapshot = {
    'reference_date': '2026-03-15',
    'alerts': result.get('alerts', []),
    'alert_count': len(result.get('alerts', [])),
    'missing_rate_alerts': [a for a in result.get('alerts', []) if 'missing' in a.get('type', '')],
    'drift_alerts': [a for a in result.get('alerts', []) if 'drift' in a.get('type', '')],
}

with open('docs/monitoring_golden_snapshot.json', 'w') as f:
    json.dump(snapshot, f, indent=2, default=str)

print(f'Snapshot capturado: {snapshot[\"alert_count\"]} alertas')
print(json.dumps(snapshot, indent=2, default=str))
"
```

**O arquivo `docs/monitoring_golden_snapshot.json` deve ser commitado junto com o PR.**

---

## Etapa 2 — Merge do PR

```bash
# Criar PR no GitHub
gh pr create \
  --title "refactor: MLOps core layer — multi-cliente sem hardcodes" \
  --base main \
  --head refactor/mlops-core \
  --body "Ver V2/docs/PLANO_REFACTOR_MLOPS.md para descrição completa. Parity checks 6/6 PASS. AUC 0.747 (baseline ±0.5%)."

# Após aprovação — merge
gh pr merge --squash  # ou --merge, conforme preferência do repo
```

---

## Etapa 3 — Deploy sem tráfego

```bash
cd /Users/ramonmoreira/Desktop/smart_ads_refactor/V2/api

# Deploy da nova revisão — zero tráfego
./deploy_capi.sh --no-traffic

# Anotar a URL da nova revisão (impressa pelo script)
# Ex: https://smart-ads-api-00043-abc123-uc.a.run.app
NEW_REVISION_URL="<url-impressa-pelo-script>"
```

---

## Etapa 4 — Validações na revisão nova (sem tráfego)

### 4A — Health check

```bash
curl -s "$NEW_REVISION_URL/health" | python3 -m json.tool
```

**Critério:** `status: "healthy"`, sem erros de import ou config.

---

### 4B — Pilar A: predição idêntica à revisão atual

```bash
# Salvar resposta da revisão ATUAL (produção)
curl -s -X POST "https://smart-ads-api-12955519745.us-central1.run.app/predict/single" \
  -H "Content-Type: application/json" \
  -H "X-Client-ID: devclub" \
  -d '{"email": "teste@checklist.com", "telefone": "11999990000", "fonte": "checklist"}' \
  > /tmp/pred_atual.json

# Salvar resposta da revisão NOVA
curl -s -X POST "$NEW_REVISION_URL/predict/single" \
  -H "Content-Type: application/json" \
  -H "X-Client-ID: devclub" \
  -d '{"email": "teste@checklist.com", "telefone": "11999990000", "fonte": "checklist"}' \
  > /tmp/pred_nova.json

# Comparar decil e score
python3 -c "
import json
atual = json.load(open('/tmp/pred_atual.json'))
nova = json.load(open('/tmp/pred_nova.json'))
print('Decil atual:', atual.get('decil'))
print('Decil nova: ', nova.get('decil'))
print('Score atual:', atual.get('score'))
print('Score nova: ', nova.get('score'))
ok = atual.get('decil') == nova.get('decil')
print('PASS' if ok else 'FAIL — decis divergem')
"
```

**Critério:** decil idêntico entre as duas revisões.

---

### 4C — Pilar B: endpoint de monitoring responde

```bash
curl -s "$NEW_REVISION_URL/monitoring/status" \
  -H "X-Client-ID: devclub" | python3 -m json.tool
```

**Critério:** resposta não-vazia, sem stack trace.

---

### 4D — Pilar B: comparação com golden snapshot

```bash
# Subir proxy local se ainda não estiver ativo
cloud-sql-proxy smart-ads-451319:us-central1:smart-ads-db --port=5432 &
sleep 8
export DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=smart_ads DB_USER=postgres DB_PASSWORD=SmartAds2026DB!

python -c "
import json
from datetime import date
from src.monitoring.orchestrator import MonitoringOrchestrator

# Rodar com a mesma data fixa usada no golden
m = MonitoringOrchestrator('devclub')
result = m.run_daily_check(reference_date=date(2026, 3, 15), dry_run=True)

golden = json.load(open('docs/monitoring_golden_snapshot.json'))
atual_count = len(result.get('alerts', []))
golden_count = golden['alert_count']

print(f'Alertas golden:  {golden_count}')
print(f'Alertas atual:   {atual_count}')

if atual_count == golden_count:
    print('PASS — contagem idêntica ao golden')
else:
    print('FAIL — divergência de alertas. Investigar antes de migrar tráfego.')
    golden_types = sorted([a.get('type') for a in golden['alerts']])
    atual_types  = sorted([a.get('type') for a in result.get('alerts', [])])
    print('Golden types:', golden_types)
    print('Atual types: ', atual_types)
"
```

**Critério:** contagem e tipos de alertas idênticos ao golden snapshot.

---

## Etapa 5 — Migrar tráfego

Somente após todos os checks da Etapa 4 passarem:

```bash
gcloud run services update-traffic smart-ads-api \
  --to-latest \
  --region=us-central1
```

---

## Etapa 6 — Validações pós-deploy (primeiras 24h)

### 6A — Pilar A: distribuição de decis normal

Verificar no banco que os decis dos leads processados nas primeiras horas seguem a distribuição histórica.

```bash
# Via Cloud SQL Proxy ativo
python3 -c "
import psycopg2, os
conn = psycopg2.connect(host=os.environ['DB_HOST'], port=os.environ['DB_PORT'],
                        dbname=os.environ['DB_NAME'], user=os.environ['DB_USER'],
                        password=os.environ['DB_PASSWORD'])
cur = conn.cursor()
cur.execute('''
    SELECT decil, COUNT(*) as n
    FROM leads_capi
    WHERE created_at > NOW() - INTERVAL '3 hours'
      AND client_id = 'devclub'
    GROUP BY decil ORDER BY decil
''')
rows = cur.fetchall()
print('Distribuição de decis (últimas 3h):')
for r in rows: print(f'  {r[0]}: {r[1]} leads')
conn.close()
"
```

**Critério:** D10 entre 20–60% (histórico normal). Qualquer decil com 0 leads após volume razoável indica problema de scoring.

---

### 6B — Pilar B: monitoramento diário executou

No dia seguinte ao deploy, verificar que o Cloud Scheduler disparou o job e o relatório chegou no Slack.

- [ ] Job `monitoring-daily` executou sem erro no Cloud Scheduler
- [ ] Relatório de monitoramento apareceu no canal Slack configurado
- [ ] Sem alertas inesperados sobre features ausentes ou thresholds

---

### 6C — Pilar C: script de validação gera relatório

Na próxima execução do `validate_ml_performance.py` (próximo lançamento), comparar a taxa de matching com o relatório anterior do mesmo lançamento.

**Critério:** taxa de matching por email ≥ baseline histórico (sem regressão no `core/matching.py`).

---

## Rollback

Se qualquer check falhar após migração de tráfego:

```bash
# Listar revisões disponíveis
gcloud run revisions list --service=smart-ads-api --region=us-central1

# Rollback para revisão anterior (substituir REVISION_NAME)
gcloud run services update-traffic smart-ads-api \
  --to-revisions=REVISION_NAME=100 \
  --region=us-central1
```

O rollback leva ~30 segundos. O cliente não percebe.

---

## Status do checklist

| Etapa | Status | Data |
|---|---|---|
| 1A — Treino → serve local | ⏳ | |
| 1B — Smoke tests imports | ⏳ | |
| 1C — Parity checks 6/6 | ⏳ | |
| 1D — Smoke monitoring | ⏳ | |
| 1E — Golden snapshot capturado | ⏳ | |
| 2 — PR merged | ⏳ | |
| 3 — Deploy sem tráfego | ⏳ | |
| 4A — Health check OK | ⏳ | |
| 4B — Predição idêntica | ⏳ | |
| 4C — Monitoring endpoint OK | ⏳ | |
| 4D — Golden snapshot PASS | ⏳ | |
| 5 — Tráfego migrado | ⏳ | |
| 6A — Decis normais (3h) | ⏳ | |
| 6B — Job diário executou | ⏳ | |
| 6C — Relatório validação OK | ⏳ | |
