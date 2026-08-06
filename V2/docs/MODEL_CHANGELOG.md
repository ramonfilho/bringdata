# Changelog de Modelos — lineage de treino

Lineage humano de cada modelo treinado e considerado (candidato, deployado ou rejeitado).
Amarra as 3 camadas de versionamento: **código** (Git/PR), **dados** (fonte + contagens +
fingerprint) e **modelo** (run MLflow + métricas). Uma entrada por modelo, mais recente no topo.

- Deploy seguro (trocar o `mlflow_run_id` de produção) segue o [`PROMOCAO_MODELO_CHECKLIST.md`](PROMOCAO_MODELO_CHECKLIST.md).
- O `run_id` é a chave no MLflow (backend Postgres `104.197.138.129:5432/mlflow`).

## Template de entrada

```
## <data> — <nome curto> — <CANDIDATO | DEPLOYADO | REJEITADO>

- **run_id:** <mlflow_run_id>   ·  **código:** <git SHA / PR>   ·  **modelo anterior:** <run_id / nome>
- **Dados:** fonte de leads + vendas, contagens, data de corte (as-of), fingerprint.
- **Config:** hiperparâmetros + flags que mudaram vs o anterior.
- **Métricas (test set temporal):** AUC / lift / top-3 decis / monotonia / D10%.
- **Δ vs anterior:** o que melhorou/piorou e por quê.
- **Mudanças de código desde o modelo anterior (só o que toca modelo/dados):** lista de PRs.
- **Decisão:** candidato / deploy (canário) / rejeitado + motivo.
```

---

## 2026-07-27 — peaceful-hawk-814 — CANDIDATO

- **run_id:** `76841105b1cf41b58d962eaf076d05ec`  ·  **código:** `f3174e5` ⚠️árvore suja  ·  **modelo anterior:** `b085b63681bc4d0d90bdbd466106763a`
- **Dados:** matched **100014** leads, **283** compradores (0.28% positivos), fingerprint `a7ed2821922a4f9a`. Split `temporal_leads`, corte 2026-03-31, período 2026-02-04..2026-04-12 (treino 80011 / teste 20003).
- **Config:** n_estimators=300, max_depth=8, min_samples_split=2, min_samples_leaf=1, max_features=sqrt, class_weight=balanced, random_state=42. buyer_weights=True, tmb_risk_filter=all, matching=email_telefone, features=41.
- **Métricas (test):** AUC **0.7168** · lift **2.44** · top-3 **64.44%** · top-5 82.22% · monotonia 66.67% · baseline 0.22%.
- **Δ vs anterior:** _(preencher: comparação exige rodar o modelo anterior no mesmo test set)_
- **Mudanças de código desde o anterior (rascunho automático, curar):**
  - aa47ce8 feat(relatório criativo): mostra o ID da campanha na Meta no rótulo
  - f1c5454 feat(relatório criativo): agrupa por AÇÃO (aumentar/reduzir orçamento) em vez de lista única
  - ee2010d feat(capi): jul_24 dispara 5 eventos de qualidade (top10/top30/top50 + 70-90/50-70)
  - bcd3111 feat(ab): promove abr28 a champion + jul_24 challenger (eventos top30/top10)
  - 3873026 feat(capi): segundo evento de qualidade por variante (capi_secondary_hq_events)
- **Decisão:** CANDIDATO — registrado no MLflow, não ativado, produção intacta. Promover exige o [`PROMOCAO_MODELO_CHECKLIST.md`](PROMOCAO_MODELO_CHECKLIST.md) + deploy com canário.

---

## 2026-07-25 — secretive-owl-433 — CANDIDATO

- **run_id:** `b085b63681bc4d0d90bdbd466106763a`  ·  **código:** `135b219` ⚠️árvore suja  ·  **modelo anterior:** `1f0f0a71061648368fc29cb58ab0cbd0`
- **Dados:** matched **316280** leads, **4043** compradores (1.28% positivos), fingerprint `2c3e423ca07bf12f`. Split `temporal_leads`, corte 2026-04-29, período 2025-01-03..2026-07-01 (treino 253024 / teste 63256).
- **Config:** n_estimators=300, max_depth=8, min_samples_split=2, min_samples_leaf=1, max_features=sqrt, class_weight=balanced, random_state=42. buyer_weights=True, tmb_risk_filter=all, matching=email_telefone, features=53.
- **Métricas (test):** AUC **0.7297** · lift **3.32** · top-3 **63.82%** · top-5 79.92% · monotonia 88.89% · baseline 0.83%.
- **Δ vs anterior:** _(preencher: comparação exige rodar o modelo anterior no mesmo test set)_
- **Mudanças de código desde o anterior (rascunho automático, curar):**
  - 0eaee9f docs(indice): lista RUNBOOK_scoring_pipeline, ROLLBACK_DECISION e MODEL_CHANGELOG
  - 96fa6d6 fix(deploy): isola gate de progressão na revisão canary + fonte única de URL Cloud Run
  - edb8198 feat(relatório criativo): tokens relativos hoje/ontem na janela (envio das 14h)
  - d0c5289 chore(scheduler): 2º envio diário do relatório de criativo (14h BRT) na lista OIDC
  - 7de65d9 fix(launches): 3º bypass do digest (revenue_forecast) + LAUNCHES_SOURCE durável no config.sh
  - cbddbbf fix(launches): job do calendário roda como a SA que lê a planilha (evita 403)
  - f15c484 feat(launches): fonte runtime de LF via analytics.launch_calendar (refresh diário da planilha)
  - d3c2bc4 feat(relatório criativo): daily-trafego aceita start_date/end_date (janela fundida) (#93)
  - c4c5a46 feat(lineage): model card automatico + carimbo de commit no treino
  - 784dea4 feat(lineage): dataset_fingerprint no MLflow + MODEL_CHANGELOG.md
- **Decisão:** CANDIDATO — registrado no MLflow, não ativado, produção intacta. Promover exige o [`PROMOCAO_MODELO_CHECKLIST.md`](PROMOCAO_MODELO_CHECKLIST.md) + deploy com canário.

---

## 2026-07-23 — RF + feature selection (permutação) — CANDIDATO

- **run_id:** `1f0f0a71061648368fc29cb58ab0cbd0`  ·  **código:** `9175264` (PR #90)  ·  **modelo anterior (produção):** Challenger `abr28` = `5d158f0aa6e54b489498470446194a6c` (treinado 28/04/2026)
- **Dados:**
  - Leads: `analytics.leads` source **`leads_treino_prod`** (universo consolidado congelado, **342.264** linhas). `leads_source=db`.
  - Vendas: `analytics.sales`, gateways **guru+tmb**, **10.864** vendas (as-of 23/07/2026). `sales_source=db`.
  - Dataset matcheado (pós-matching + janela de conversão): **316.280** leads, **4.043** compradores (target=1), 0,83% de positivos no test.
  - **Fingerprint (grosso, até o auto-log entrar):** leads=342.264 · vendas=10.864 · matched=316.280 · pos=4.043 · SHA de código `9175264`. (Hash de conteúdo exato passa a ser auto-logado no run a partir da frente "dataset fingerprint" — ver Pendências.)
- **Config:** RandomForest `n_estimators=300, max_depth=8, max_features=sqrt, class_weight=balanced, random_state=42`. `train_ratio=0.8`. `buyer_weights` ON (desconto de risco TMB: guru 1.0 / tmb_baixo 0.84 / medio 0.67 / alto 0.49 / sem 0.42). Peso de controle **OFF**. **Feature selection ON** (permutação, threshold 0, min_features 20) → **70 → 53 features** (cortou 17).
- **Métricas (test temporal, 63.256 leads):** AUC **0,7290** · lift **3,22** · top-3 decis **63,07%** · top-5 **79,55%** · monotonia 88,9%.
- **Δ vs baseline de MESMA config sem feature selection (mesma data):** AUC 0,7184 → **0,7290 (+0,011)** · top-3 60,23% → **63,07% (+2,8pp)**. O ganho é da feature selection isolada (única mudança).
- **Mudanças de código desde o abr28 que tocam modelo/dados de treino:**
  - **Serving dos dados de treino:** TMB entra no `analytics.sales` via API REST (PR #79/#80, live #82); consolidação Cloud SQL + **universo único `leads_treino_prod`** (substitui Sheets/Railway); ingestão automática de vendas+leads; **fix do nome da fonte** `train_unified` → `leads_treino_prod` (PR #90) que tira a dependência de monkeypatch; treino passa a ler leads e vendas do banco (`leads_source=db`, `sales_source=db`, todos os gateways disponíveis).
  - **Sinal / rótulos:** grupo de controle curado em `analytics.campaign_labels` ligado ao peso de controle (PR #85); peso direcional de controle `control_boost` (PR #86, off por default).
  - **Features:** seleção por importância de permutação como etapa final opt-in (PR #89).
- **Decisão:** **CANDIDATO** (registrado no MLflow, **não ativado**, produção intacta). Não é comparável 1:1 com o abr28 (test set, features e janela de dados diferentes). Promover exige o [`PROMOCAO_MODELO_CHECKLIST.md`](PROMOCAO_MODELO_CHECKLIST.md) + deploy com canário (sem tráfego → 5% → 10% → 1 lançamento → 100%, monitorando D10% e CAPI).

---

## Referência — Challenger `abr28` (produção atual)

- **run_id:** `5d158f0aa6e54b489498470446194a6c`  ·  treinado **28/04/2026**.
- Treinado com Guru + TMB (log 28/04: 3.280 Guru + 7.270 TMB); TMB descontada via `buyer_weights`; usou `control_group_weights=True`.
- É o modelo que scoreia as campanhas `LEADHQLB` no A/B (o Champion `jan30` = `d51757f5041c44b7ab1a056fce8c3c35` scoreia o resto). Ponteiro de produção em `configs/active_models/devclub.yaml`.
- Entradas anteriores a este changelog não foram backfilladas (o changelog começa em 23/07/2026); o histórico detalhado desses modelos vive no MLflow e nos docs de erro/auditoria.
