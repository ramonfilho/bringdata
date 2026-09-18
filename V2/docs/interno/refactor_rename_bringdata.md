# Rename: smart_ads → bring_data

## Status
- Fase 1 (código): **concluída**
- Fase 2 (infra GCP): pendente

---

## Substituições realizadas (Fase 1)

| De | Para | Escopo |
|----|------|--------|
| `smart_ads` | `bring_data` | todos os arquivos `.py`, `.yaml`, `.sh`, `.md`, `.js`, `.html`, `.json`, `.toml`, `.env` |
| `smart-ads` | `bring-data` | idem — **exceto** `smart-ads-451319` (GCP Project ID, imutável) |
| `SmartAds` | `BringData` | idem |
| `Smart Ads` | `Bring Data` | idem |

---

## Riscos e decisões

### GCP Project ID `smart-ads-451319` — INTOCÁVEL
IDs de projeto GCP são **imutáveis**. Mantido como está em todo o código.
Para migrar de vez: criar novo projeto GCP `bring-data-XXXXX`, migrar recursos e atualizar essa string.

### Cloud Run URL com hash gerado — Fase 2
O nome do serviço foi atualizado para `bring-data-api` no código, mas a URL antiga
`smart-ads-api-12955519745.us-central1.run.app` continuará funcionando até o redeploy.
Após redeploy, o GCP gera um novo hash — a URL muda e **19 arquivos** precisam ser atualizados.

Arquivos afetados:
- `api/apps-script-code.js`
- `api/landing_page/codigo_formulario_completo_com_capi.js`
- `api/landing_page/index.html`
- `src/validation/generate_taxa_resposta_csv.py`
- `src/validation/send_purchase_events.py`
- `src/validation/data_loader.py`
- `configs/campanhas_atipicas.yaml`
- `configs/weekly_validation_config.yaml`
- `docs/interno/instrucoes_dev_frontend_capi.md`
- `docs/CHECKLIST_DEPLOY_REFACTOR.md`
- `CLAUDE.md`
- (+ arquivos em `docs/arquivo/`)

### MLflow bucket `gs://smart-ads-mlflow` → `gs://bring-data-mlflow`
`training_model.py:285` agora referencia o novo nome. Migrar artifacts antes de treinar:

```bash
gsutil mb gs://bring-data-mlflow
gsutil -m cp -r gs://smart-ads-mlflow/* gs://bring-data-mlflow/
```

### Senha do `postgres` hardcoded: RESOLVIDA em 05/08/2026

Era dívida técnica conhecida: a senha do usuário `postgres` do Cloud SQL estava escrita
em texto claro no código (na época em `src/model/training_model.py:28`, depois em
`src/core/mlflow_setup.py:18`) e em 10 outros arquivos versionados, num repositório
**público**. Como a instância aceitava conexão de qualquer IP, a credencial dava acesso de
**dono** a `analytics.leads` (366 mil leads com e-mail, telefone e nome) e a
`analytics.sales`.

Fechado em 05/08/2026: senha rotacionada, guardada no Secret Manager
(`mlflow-db-password`) e lida do `V2/.env` (gitignored). A URI de tracking do MLflow não
tem mais default embutido: falta de configuração levanta exceção com a instrução de
correção, em vez de cair calada num MLflow local vazio. Um teste de regressão
(`V2/tests/test_sem_credencial_no_repo.py`) varre os arquivos versionados e falha se
qualquer credencial literal voltar.

### Paths absolutos locais
`configs/devclub.yaml` e `docs/arquivo/mlflow_tracking/0/meta.yaml` foram atualizados para `/Users/ramonmoreira/Desktop/bring_data/`.
Para que funcionem, renomear o diretório localmente:

```bash
mv /Users/ramonmoreira/Desktop/smart_ads /Users/ramonmoreira/Desktop/bring_data
```

---

## Checklist Fase 2 (infra)

- [ ] Renomear diretório local: `smart_ads` → `bring_data`
- [ ] Redeploy Cloud Run com `SERVICE_NAME=bring-data-api`
- [ ] Capturar nova URL gerada pelo GCP e atualizar os 19 arquivos
- [ ] Atualizar Cloud Scheduler com nova URL do endpoint `/validation/weekly`
- [ ] Migrar bucket `gs://smart-ads-mlflow` → `gs://bring-data-mlflow`
- [ ] Criar bucket `gs://bring-data-validation-reports` (migrar de `gs://smart-ads-validation-reports`)
- [ ] Criar bucket `gs://bring-data-ml-artifacts` (migrar de `gs://smart-ads-ml-artifacts`)
- [ ] Renomear instância Cloud SQL `smart-ads-db` → `bring-data-db`
- [ ] Testar Google Sheets (Apps Script) com nova URL
- [ ] Testar landing page (webhook CAPI) com nova URL
