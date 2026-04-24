# /ctx — Contexto Operacional do Projeto Bring Data

Use esta skill como ponto de partida para qualquer trabalho neste repositório: desenvolver features, rodar consultas, executar pipelines, depurar problemas.

---

## O QUE O SISTEMA FAZ (30 segundos)

Lead scoring ML para anunciantes. Fluxo completo:

```
Lead preenche formulário (landing page)
  → POST /v1/predict (API FastAPI, Cloud Run)
      → LeadScoringPipeline (src/production_pipeline.py)
          → src/core/ (transformações idênticas ao treino)
          → modelo RandomForest (MLflow, configs/active_models/devclub.yaml)
      → decil D01–D10 calculado em ~5 min
  → evento LeadQualified enviado ao Meta CAPI com valor proporcional ao decil
  → lead gravado no Railway PostgreSQL (tabela "Lead")
```

**Por que isso importa:** o Meta otimiza baseado nesses valores → 56× mais rápido que esperar compra real.

**Cliente ativo:** DevClub (programação). **Cliente B:** chegando (arquitetura já suporta multi-cliente).

---

## MAPA DO REPOSITÓRIO

```
bring_data/
├── V2/                          ← TRABALHO ACONTECE AQUI
│   ├── api/
│   │   ├── app.py               ← API FastAPI (3.2k linhas) — endpoints, CAPI, webhook
│   │   ├── deploy_capi.sh       ← script de deploy Cloud Run
│   │   └── requirements.txt     ← dependências da API
│   ├── src/
│   │   ├── core/                ← Single Source of Truth de transformações (14 arquivos)
│   │   │   ├── client_config.py ← ClientConfig dataclass + sub-configs
│   │   │   ├── preprocessing.py ← orquestrador sequência canônica
│   │   │   ├── encoding.py      ← encoding ordinal/OHE + feature registry
│   │   │   ├── matching.py      ← match leads × vendas → target binário
│   │   │   └── ...              ← ingestion, utm, medium, feature_engineering, etc.
│   │   ├── train_pipeline.py    ← treino completo (1.1k linhas)
│   │   ├── production_pipeline.py ← scoring em batch
│   │   ├── monitoring/          ← drift, CAPI quality, operational metrics
│   │   ├── retrain/             ← orquestração de retreino mensal
│   │   └── validation/          ← comparação ML vs Meta Ads
│   ├── configs/
│   │   ├── clients/devclub.yaml       ← parâmetros do cliente (termos, colunas, etc.)
│   │   └── active_models/devclub.yaml ← modelo ativo (run_id, thresholds, ab_test)
│   ├── docs/                    ← 30+ documentos (ver índice abaixo)
│   ├── scripts/                 ← 25+ scripts de análise e relatórios
│   └── tests/                   ← parity_audit, unit, integration
├── smart_ads_v2_rollback/       ← worktree edf23e9 (versão em produção)
└── mlflow.db                    ← MLflow local
```

---

## ESTADO ATUAL DO PROJETO (atualizar conforme avança)

| Item | Estado | Detalhe |
|---|---|---|
| Versão em produção | `edf23e9` (05/03/2026) | Rollback executado em 13/04 |
| Branch main | Refactor completo (`src/core/`) | Não deployada ainda |
| Canary ativo | `00270-q2m` a 10% | main; edf23e9 a 90% |
| A/B test | jan30 (Champion) vs mar24 (Challenger) | Janela válida: 01/04–13/04, resultado em 27/04 |
| Próximo marco | Tier 1 Safeguards (7 itens) | Pré-requisito pré-unificação |
| Unificação branches | 28/04–05/05/2026 | Com parity audit antes e depois |

**Bloqueador crítico (T1-1):** encoding ordinal usa nome literal de coluna no treino (`'Qual a sua idade?'`) mas nome curto (`'idade'`) em produção → features zeradas silenciosamente.

Leia `docs/PLANO_EXECUCAO.md` para estado detalhado do roadmap.

---

## AMBIENTE DE DESENVOLVIMENTO

### Setup inicial
```bash
cd /Users/ramonmoreira/Desktop/bring_data/V2
source venv/bin/activate          # venv já configurado
export PYTHONPATH=/Users/ramonmoreira/Desktop/bring_data/V2
```

### Variáveis de ambiente necessárias
```bash
# Produção (Cloud Run tem essas automaticamente)
CLOUDSQL_PASSWORD=...
RAILWAY_DATABASE_URL=...
META_ACCESS_TOKEN=...              # expira ~60 dias — verificar validade
GOOGLE_APPLICATION_CREDENTIALS=... # para Sheets e BigQuery
```

### Cloud SQL Proxy (para queries locais ao PostgreSQL)
```bash
cloud-sql-proxy smart-ads-451319:us-central1:bring-data-db --port=5432 &
# Credenciais: ver docs/acesso_sql.md
```

### MLflow
```bash
# Remoto (canônico — tracking prod, backend Cloud SQL Postgres)
export MLFLOW_TRACKING_URI="postgresql+psycopg2://postgres:SmartAds2026DB!@104.197.138.129:5432/mlflow"
# Artifacts: gs://smart-ads-mlflow/artifacts/
# Não há UI web ativa — use SDK Python (mlflow.tracking.MlflowClient) ou CLI.
# Detalhes em docs/MLFLOW.md.

# Local (apenas sandbox — mlflow.db SQLite + mlruns/ locais)
mlflow ui --backend-store-uri sqlite:///mlflow.db   # http://localhost:5000
```

---

## QUERIES FREQUENTES (Railway PostgreSQL)

```bash
# Conectar
psql $RAILWAY_DATABASE_URL
```

### Distribuição de decis por semana
```sql
SELECT
    DATE_TRUNC('week', "createdAt") AS semana,
    decil,
    COUNT(*) AS leads,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY DATE_TRUNC('week', "createdAt")), 1) AS pct
FROM "Lead"
WHERE "createdAt" >= NOW() - INTERVAL '90 days'
  AND decil IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
```

### Status CAPI por semana
```sql
SELECT
    DATE_TRUNC('week', "capiSentAt") AS semana,
    "capiStatus",
    COUNT(*) AS eventos
FROM "Lead"
WHERE "capiSentAt" >= NOW() - INTERVAL '90 days'
GROUP BY 1, 2
ORDER BY 1, 2;
```

### Leads de um lançamento com score e decil
```sql
SELECT
    id, "createdAt", "leadScore", decil, "capiStatus",
    campaign, "utmSource", "utmMedium"
FROM "Lead"
WHERE "createdAt" BETWEEN '2026-03-01' AND '2026-03-20'
ORDER BY "leadScore" DESC
LIMIT 50;
```

### Volume por campanha (A/B test)
```sql
SELECT
    campaign,
    COUNT(*) AS leads,
    ROUND(AVG("leadScore"), 3) AS score_medio,
    COUNT(CASE WHEN decil >= 9 THEN 1 END) AS d9_d10
FROM "Lead"
WHERE "createdAt" >= '2026-04-01'
GROUP BY campaign
ORDER BY leads DESC;
```

---

## COMO RODAR PIPELINES

### Treino de modelo
```bash
cd /Users/ramonmoreira/Desktop/bring_data/V2
python -m src.train_pipeline \
    --client devclub \
    --split-method temporal \
    --tmb-risk-filter \
    --initial-matching

# Flags disponíveis:
#   --initial-matching     primeiro treino (sem modelo anterior)
#   --split-method         temporal | random
#   --tmb-risk-filter      filtrar inadimplentes antes do match
#   --hyperparams          path para JSON com hiperparâmetros
```

### Scoring em produção (batch local)
```python
import sys; sys.path.insert(0, '/Users/ramonmoreira/Desktop/bring_data/V2')
from src.production_pipeline import LeadScoringPipeline

pipeline = LeadScoringPipeline(client_id='devclub')
results = pipeline.score_batch(leads_df)  # DataFrame com colunas do formulário
# results: ['lead_id', 'lead_score', 'decil']
```

### Monitoramento manual
```bash
python -m src.monitoring.orchestrator --client devclub --date 2026-04-19
```

### Parity audit (OBRIGATÓRIO antes de qualquer merge)
```bash
python -m pytest V2/tests/parity_audit.py -v
# Testa: Medium, UTM, encoding — treino vs produção
```

### Validação ML vs Meta Ads
```bash
python -m src.validation.validate_ml_performance --client devclub --lancamento LF52
```

---

## COMO DESENVOLVER NOVAS FEATURES

### Regra de ouro
**Toda transformação de dados deve estar em `src/core/`.** Nunca reimplementar fora de lá.

### Adicionar feature ao pipeline

1. **Criar/editar arquivo em `src/core/`** seguindo a assinatura canônica:
```python
def transform(df: pd.DataFrame, config: SubConfig, **artifacts) -> pd.DataFrame:
    # config vem de ClientConfig; não use globals nem hardcodes
    ...
    return df
```

2. **Registrar na `ClientConfig`** (`src/core/client_config.py`):
```python
@dataclass
class NovaSubConfig:
    algum_parametro: str = "default_value"  # SEMPRE tem default

@dataclass
class ClientConfig:
    ...
    nova_config: NovaSubConfig = field(default_factory=NovaSubConfig)
```

3. **Adicionar ao template** `configs/templates/client_template.yaml`

4. **Atualizar `configs/clients/devclub.yaml`** com os valores reais

5. **Chamar em `preprocessing.py`** na sequência canônica (com ordem correta — encoding vem depois de feature engineering)

6. **Rodar parity audit:**
```bash
python -m pytest V2/tests/parity_audit.py -v
```

### Adicionar novo endpoint à API
- Editar `api/app.py`
- Padrão: `@app.post("/v1/nova-rota")` com `client_id` como parâmetro
- Usar `pipelines[client_id]` para acessar o pipeline do cliente

### Adicionar novo campo ao CAPI
- Verificar `send_batch_events()` em `api/app.py`
- Event name padrão: `LeadQualified` (D1–D8), `LeadQualifiedHighQuality` (D9–D10)
- Challengers: `LeadQualifiedCha`, `LeadQualifiedChaHighQuality`
- **Nunca mudar event name sem grupo de controle**

---

## DEPLOY

### Deploy completo (protocolo obrigatório)
```bash
cd /Users/ramonmoreira/Desktop/bring_data/V2/api

# 1. Build sem tráfego
./deploy_capi.sh --no-traffic

# 2. Smoke test (5 leads)
curl -X POST https://smart-ads-api-URL/v1/predict/single \
    -H "Content-Type: application/json" \
    -d '{"client_id": "devclub", "lead": {...}}'

# 3. Canary gradual: 5% → 10% → 1 lançamento → 100%
gcloud run services update-traffic smart-ads-api \
    --region us-central1 \
    --to-revisions NOVA=10,ANTERIOR=90
```

### Ver logs em produção
```bash
gcloud logging read \
    "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api" \
    --project smart-ads-451319 \
    --limit=50 \
    --format="value(textPayload)"
```

### Listar revisões ativas
```bash
gcloud run revisions list \
    --service smart-ads-api \
    --region us-central1 \
    --project smart-ads-451319
```

---

## ÍNDICE DE DOCUMENTAÇÃO

| Pergunta | Documento |
|---|---|
| O que implementar agora? | `docs/PLANO_EXECUCAO.md` ← **leitura diária** |
| Mapa de todos os docs | `docs/INDICE_DOCUMENTACAO.md` |
| Arquitetura completa | `docs/ARQUITETURA_SISTEMA_COMPLETA.md` |
| Refactor `src/core/` (motivação, fases) | `docs/PLANO_REFACTOR_MLOPS.md` |
| Safeguards pendentes (T1–T3) | `docs/PLANO_SAFEGUARD.md` |
| A/B test (config, janela, critério) | `docs/AB_TEST.md` |
| Investigação de erros passados | `docs/Erros_cometidos.md` ← antes de infra |
| Roadmap de maturidade MLOps | `docs/ROADMAP_MLOPS_MATURIDADE.md` |
| Como conectar ao banco local | `docs/acesso_sql.md` |
| Como acessar Google Sheets | `docs/acesso_sheets.md` |
| ROAS DevClub (histórico) | `docs/analise_valor_ml_devclub.md` |
| Decisão do rollback (13/04) | `docs/ROLLBACK_DECISION.md` |

---

## SKILLS DISPONÍVEIS

### ML / Infra
| Skill | Quando usar |
|---|---|
| `/ctx` | Esta skill — contexto geral, onboarding, desenvolvimento |
| `/mlops-architect` | Contexto arquitetural profundo + checklists de segurança |
| `/investigate` | Por que um lançamento foi ruim? D10% anormal? |
| `/investigate-ab` | A/B test está funcionando? Roteamento correto? |
| `/safeguard` | Auditoria completa de integridade pré-deploy/merge |
| `/plan-integrator` | Ler toda a documentação e reconciliar estado atual |

### Comercial
| Skill | Quando usar |
|---|---|
| `/comercial` | Contexto das propostas em circulação (decks, case, preços) |
| `/prospect` | Pesquisar contatos de uma empresa-alvo com protocolo de confiança (tier ranking, multi-source) |
| `/copy` | Redigir ou revisar mensagens iniciais de outreach (email, LinkedIn, WhatsApp) |
| `/pptx` | Ler ou editar texto dos decks em `V2/propostas_e_apresentacoes/` |
| `/sheets` | Leitura/edição do CSV-fonte (`V2/comercial/contatos.csv`) e sync com Google Sheets |

---

## CONVENÇÕES DO PROJETO

- **Multi-cliente:** tudo parametrizado via `ClientConfig`; nunca hardcode de cliente
- **Timezone:** sempre `datetime.now(timezone.utc)` — nunca `datetime.now()` sem UTC
- **Encoding:** nome da chave YAML deve ser idêntico ao nome real da coluna no DataFrame
- **Parity:** qualquer mudança em `src/core/` → rodar `tests/parity_audit.py`
- **Deploy:** sempre `--no-traffic` primeiro; canary antes de 100%
- **CAPI valores:** `ticket_real × taxa_conversão_decil` — nunca ticket médio nem hardcoded
- **Decis:** formato `D01–D10` (zero à esquerda) em todo o código e YAMLs
- **Fail-loud:** todo transform novo em `src/core/` deve ter assert explícito que falha alto se output for zero/null inesperado — falha silenciosa é pior que exceção

---

## CHECKLIST RÁPIDO ANTES DE QUALQUER MUDANÇA

- [ ] A mudança está em `src/core/` (não duplicada em treino/produção/monitoramento separadamente)?
- [ ] Novos campos em `ClientConfig` têm `default`?
- [ ] `parity_audit.py` passa antes e depois?
- [ ] Deploy usa `--no-traffic` + canary?
- [ ] O rollback está identificado (qual revisão Cloud Run reverter)?
