# Ingestão automática — leads e vendas se populam sozinhos

Antes desta frente, as duas tabelas que alimentam o treino eram populadas **só na mão**:
o `train_unified` (leads) com `leads_unify --write` e o `analytics.sales` (vendas) com
`etl_sales --start --end`. Esta frente põe os dois pra rodar sozinhos, diariamente, como
Cloud Run Jobs agendados — seguindo o mesmo padrão do job de validação semanal.

---

## 1. O que roda sozinho

| Job (Cloud Run) | Comando | O que faz | Cron |
|---|---|---|---|
| `ingestion-leads-incremental` | `leads_unify --incremental` | anexa ao `train_unified` só os leads novos da `registros_ml` (ledger vivo), janela móvel de 7 dias, upsert por `event_id` (idempotente). Histórico congelado nunca é tocado. | 06:00 BRT |
| `ingestion-sales-daily` | `etl_sales --daily` | puxa as vendas dos 4 gateways de **API** (guru/hotmart/asaas/boletex) numa janela móvel de 14 dias (idempotente via `ON CONFLICT`), reporta cobertura por gateway e **alerta no Slack se o tmb atrasar** > 7 dias. | 06:30 BRT |

Os dois são **idempotentes**: re-rodar a mesma janela não duplica nada.

### Por que incremental (e não rebuild diário)

Das 5 fontes do `train_unified`, **4 são históricas e congeladas** (a `Lead` antiga,
o `lead_surveys`, as planilhas Google Sheets e os exports xlsx — nenhuma muda mais).
Só **uma é viva: a `registros_ml`**, onde a produção grava cada lead ao scorear. Então o
diário só precisa puxar o pedaço vivo. O rebuild completo das 5 fontes (`leads_unify --write`)
continua existindo para reconstruir o histórico do zero quando necessário.

### O tmb continua manual (de propósito)

O tmb é **54% das vendas** mas só vem por **arquivo Excel** (não tem API). Então o job diário
puxa só os 4 gateways de API; o tmb continua sendo subido na mão no fechamento de cada lançamento
(`etl_sales --gateways tmb --tmb-paths <xlsx>`), e o job diário **alerta no Slack** se a última
venda tmb ficar velha — pra essa fonte não sumir em silêncio do dado de treino.

---

## 2. Como colocar no ar (ordem)

> Pré-requisito: a imagem Docker precisa conter o código novo (`--incremental` / `--daily`).
> Por isso o deploy faz **build** por padrão (não use `--reuse-image` na primeira vez).

```bash
cd V2

# 1) Deploy dos 2 Cloud Run Jobs (faz build da imagem na primeira vez)
bash api/deploy_ingestion_job.sh --job leads
bash api/deploy_ingestion_job.sh --job sales --reuse-image   # reusa a imagem do passo anterior

# 2) Agendar os 2 crons (idempotente: cria ou atualiza)
bash api/setup_ingestion_schedulers.sh

# 3) (opcional) testar um job agora
gcloud run jobs execute ingestion-leads-incremental --region us-central1
```

### ⚠️ Credenciais dos gateways no job de vendas

O `ingestion-sales-daily` precisa das credenciais de API dos gateways
(guru/hotmart/asaas/boletex) no ambiente do job. Elas entram pelas mesmas variáveis que o
job de validação já usa (`build_env_vars` em `api/lib/config.sh` + Secret Manager). Se algum
gateway falhar por falta de credencial, o job **não derruba** os outros (cada gateway é
isolado em `try/except`) — mas a cobertura daquele gateway fica velha. Confira o log da
primeira execução por gateway.

---

## 3. Monitorar

```bash
# logs da última execução
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=ingestion-leads-incremental' --limit 50

# estado dos crons
gcloud scheduler jobs list --location us-central1 | grep ingestion
```

A cobertura de vendas por gateway sai no próprio log do job (`sales_coverage`): contagem +
data da última venda + dias parado por gateway. O alerta de tmb vai pro Slack via
`ValidationSlackNotifier`.

---

## 4. Reverter

- Pausar um cron:  `gcloud scheduler jobs pause <nome>-cron --location us-central1`
- Apagar um job:   `gcloud run jobs delete <nome> --region us-central1`
- Os dados já gravados ficam (idempotentes, rotulados por fonte); nada a desfazer no banco.
