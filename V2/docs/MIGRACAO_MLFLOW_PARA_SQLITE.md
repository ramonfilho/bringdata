# Migração do MLflow tracking — Cloud SQL → SQLite + GCS

**Criado:** 2026-05-14
**Status:** 📚 catálogo (especificação técnica). Status de execução vive em `PLANO_EXECUCAO.md`.

---

## Por que migrar

Hoje o tracking server do MLflow usa uma instância Cloud SQL (`smart-ads-db`, PostgreSQL 15, db-f1-micro) como backend de metadados. Custo: ~R$ 50/mês ligada, ~R$ 15/mês parada (IP reservation + storage). Como o uso real é **~1 vez por mês** (retreino + ocasional ativação de run antigo), 95% do tempo a instância está ociosa.

**Alternativa:** SQLite local como tracking store + GCS para artefatos. Custo: ~R$ 0,10/mês (storage GCS). Roda em qualquer máquina sem dependência de infra remota.

**Limitação que mata o uso direto de BigQuery:** MLflow tracking store exige um backend SQL **relacional transacional** (PostgreSQL, MySQL, SQLite, MSSQL). BigQuery é warehouse colunar e não é suportado.

---

## Mapa de dependências do estado atual

Levantado em 2026-05-14 lendo o código.

### Dependem do Cloud SQL ligado

| Arquivo | Categoria | O que faz |
|---|---|---|
| `src/model/training_model.py:27-31` | **Treino — crítico** | `mlflow.set_tracking_uri('postgresql+psycopg2://...104.197.138.129:5432/mlflow')` no nível do módulo |
| `src/model/training_model.py:185-193` | **Ativação — crítico** | `MlflowClient().get_run()` + `download_artifacts()` para ativar um run antigo como modelo de produção |
| `src/model/training_model.py:283-288` | **Treino — crítico** | `mlflow.start_run()` + `mlflow.sklearn.log_model()` registram modelo no servidor |
| `src/experiments/rules_vs_rf.py:420-438` | **Experimentação** | `mlflow.set_experiment()` + `mlflow.start_run()` para logar baseline vs RF |
| `src/validation/data_loader.py:60` | **Validação no retreino** | `mlflow.get_run()` — carrega features esperadas do run de comparação |

### NÃO dependem (têm fallback ou só usam filesystem local)

| Arquivo | Comportamento sem Cloud SQL |
|---|---|
| `src/core/encoding.py:51-72, :126-135` | `try/except` em `mlflow.get_run()`, fallback `experiment_id='1'`; lê `feature_registry.json` de `mlruns/<exp>/<run>/artifacts/` no filesystem local da imagem Docker |
| `src/core/medium.py:128` | Mesmo padrão (tolerante a MLflow offline; lê `distribuicoes_esperadas.json` local) |
| `src/model/prediction.py:145` | Backup: `mlruns/1/{run_id}/artifacts/` no filesystem se MLflow indisponível |
| `src/production_pipeline.py` | Não chama MLflow em nenhum momento — usa apenas `mlruns/` baked-in via Dockerfile |
| `src/monitoring/orchestrator.py` | Não toca MLflow remoto |
| `src/train_pipeline.py:main()` (com guard adicionado em 14/mai) | Fala alto se Cloud SQL não está RUNNABLE — não tenta seguir sem |

### Onde os artefatos REALMENTE vivem em produção

Confirmado pela leitura de `api/Dockerfile:49-52` e `deploy_capi.sh`:

```
api/Dockerfile
    └─> COPY mlruns_build/1/{run_id}/artifacts/* /app/mlruns/1/{run_id}/artifacts/
        ├─ model/model.pkl              (modelo serializado)
        ├─ feature_registry.json        (lista ordenada de features + importâncias)
        ├─ model_metadata.json          (decis, thresholds, taxas)
        └─ distribuicoes_esperadas.json (baselines para drift detection)
```

`deploy_capi.sh` faz `git pull` dos runs ativos (champion + challenger) pra `mlruns_build/` ANTES do build do Docker. Em runtime do Cloud Run, `LeadScoringPredictor` carrega de `/app/mlruns/` direto — zero dependência de MLflow remoto.

**Conclusão crítica:** produção (Cloud Run) é **totalmente independente** do Cloud SQL. Quem precisa é só treino/ativação.

---

## Plano de migração em fases

### Fase 1 — Trocar tracking_uri (1 dia)

- Substituir `postgresql+psycopg2://...` por `sqlite:///<path>` em `src/model/training_model.py:27-30`.
- Path do SQLite: `V2/mlflow_tracking.db` (versionar via Git? Ou só `.gitignore` e push manual pra GCS?). **Decisão pendente.**
- Variável de ambiente `MLFLOW_TRACKING_URI` continua sobrescrevendo (já existe).
- Testar `python -m src.train_pipeline --initial-matching email_telefone --save-files` localmente.

### Fase 2 — Mover artefatos pra GCS (2 dias)

- Hoje os artefatos vão pra `mlflow-artifacts:/` (gerenciado pelo MLflow servidor) ou `gs://bring-data-mlflow/artifacts` (configurado mas não usado operacionalmente).
- Configurar `mlflow.create_experiment(name='devclub_lead_scoring', artifact_location='gs://bring-data-mlflow/devclub_v2/')`.
- Service account do treinador precisa de `Storage Object Admin` no bucket.
- Testar `mlflow.sklearn.log_model()` → confirmar que sobe pra GCS.

### Fase 3 — Adaptar `deploy_capi.sh` (1 dia)

- Hoje o script copia de `mlruns_build/` local pro contexto Docker.
- Mudança: baixar artefatos do GCS antes do build.
  ```bash
  gsutil -m cp -r "gs://bring-data-mlflow/devclub_v2/${RUN_ID}/artifacts" \
    "mlruns_build/1/${RUN_ID}/"
  ```
- Cache no `mlruns_build/` (gitignored) pra evitar re-download em deploys consecutivos.

### Fase 4 — Backup e migração de runs históricos (1 dia)

- Antes de deletar a Cloud SQL `smart-ads-db`, exportar todos os runs históricos pra SQLite local + GCS:
  ```python
  # script ad-hoc — listar runs e re-logar no SQLite local
  ```
- Validar que `mlflow ui --backend-store-uri sqlite:///mlflow_tracking.db` mostra histórico completo.

### Fase 5 — Decomissionamento (1 dia)

- Atualizar `assert_mlflow_backend_running()` em `training_model.py` pra validar SQLite + GCS em vez de Cloud SQL.
- Atualizar `register_mlflow_cleanup_reminder()` (remover o lembrete — não há mais o que parar).
- Atualizar `operacoes_gcp_custos.md` removendo o protocolo Cloud SQL.
- `gcloud sql instances delete smart-ads-db --project=smart-ads-451319` após confirmar 30 dias sem regressão.

**Esforço total:** 5-6 dias de trabalho focado. Economia recorrente: ~R$ 15/mês + zero risco de "esqueci de desligar".

---

## Pré-condições antes de iniciar

- [ ] Próximo retreino concluído com sucesso no fluxo atual (estado base validado).
- [ ] Bucket `gs://bring-data-mlflow` existe e tem permissão correta (verificar com `gsutil ls`).
- [ ] Decisão sobre versionamento do SQLite (Git LFS vs GCS-only).

---

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Perda de histórico de runs durante a migração | Fase 4 (export + validação) antes da Fase 5 (delete instance) |
| Performance do SQLite com muitos runs concorrentes | Para o uso atual (1 retreino/mês, single-user), SQLite é adequado. Se virar problema, considerar PostgreSQL em GCS-mounted Cloud Run Job (mais complexo) |
| `mlflow ui` local ficar lento com SQLite grande | Vacuum + indexes periódicos. O DB do MLflow é pequeno (poucos MB mesmo com 100+ runs) |
| Permissão GCS no Cloud Build / CI | Service account configurada com `Storage Object Admin` no bucket específico |
| Outros membros do time não conseguirem ver runs | SQLite local é single-user. Solução: subir SQLite pra GCS após cada retreino e gravar instrução de "puxar antes de inspecionar" no doc |

---

## Status atual (14/mai/2026)

Não iniciado. Próximo passo: incluir no `PLANO_EXECUCAO.md` quando houver janela (atualmente bloqueado por trabalho na frente de monitoramento "Outros" e LF55).
