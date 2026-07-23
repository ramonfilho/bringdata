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
