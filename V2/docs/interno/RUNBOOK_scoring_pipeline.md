# Runbook — confiabilidade da pipeline de scoring (smart-ads-api)

Guia operacional pra quando "o relatório não veio" ou "o scoring parou". Nasceu do
apagão de 22-23/07/2026 (ver post-mortem no fim).

## Como o lead vira score (caminho crítico)

```
Lead preenche formulário (browser)
   ├─(a) POST anônimo → /webhook/lead_capture  ─┐
   └─(b) evento publicado no tópico Pub/Sub      ├─→ fila lead-capture-ingest-sub (PULL, retém 7d)
                                                  │
Cron pubsub-process-pending (5/5min) ────────────┘
   → puxa lote (DEFAULT_BATCH) → scoreia (pipeline.run) → CAPI (Meta/Google)
   → grava no ledger registros_ml → ack
```

O relatório diário (06:00 cliente #team-dados, 06:20 seu DM) é outro cron
(`slack-digest-daily` / `-dm`) que lê o ledger e posta no Slack.

## ⛔ INVARIANTE: o serviço `smart-ads-api` é PÚBLICO por design — NUNCA remover `allUsers`

O `/webhook/lead_capture` recebe **POST anônimo de browser** (o formulário do lead
não manda token). Por isso o binding `allUsers → roles/run.invoker` no serviço é
**obrigatório**. Remover derruba a captura de lead E os crons.

- O `deploy_capi.sh` **reafirma** o `allUsers` a cada deploy (self-healing) e NÃO
  instrui mais removê-lo (a antiga instrução "remover antes de produção" foi o
  gatilho do apagão).
- Os 6 crons que batem no serviço autenticam por **token OIDC** (SA
  `scheduler-invoker`) como defense-in-depth: se o `allUsers` sumir por engano, os
  crons sobrevivem (só o webhook quebra) e o alerta dispara. Reproduzir:
  `scripts/setup_scheduler_oidc.sh`.

## Alertas (Cloud Monitoring → email ramonfceo@gmail.com)

Reproduzir/atualizar: `scripts/setup_monitoring_alerts.sh`.

1. **Scoring parado / backlog** — dispara se `num_undelivered_messages` da sub > 200
   por 10min OU a mensagem mais antiga (`oldest_unacked_message_age`) > 30min.
2. **Cron falhou** — dispara em qualquer Cloud Scheduler job com log de erro (403/500).

## Diagnóstico rápido

```bash
# 1. O serviço está público? (allUsers presente?)
gcloud run services get-iam-policy smart-ads-api --region=us-central1 --format="value(bindings.members)" | tr ',' '\n' | grep -i allUsers

# 2. Os crons estão falhando? (status.code 7 = 403)
for j in slack-digest-daily slack-digest-daily-dm pubsub-process-pending railway-polling; do
  gcloud scheduler jobs describe $j --location=us-central1 --format="value(name, lastAttemptTime, status.code)"; done

# 3. Backlog e frescor da fila (REST, pois `gcloud monitoring time-series` não existe nesta versão):
TOKEN=$(gcloud auth print-access-token)
curl -s -G -H "Authorization: Bearer $TOKEN" \
  "https://monitoring.googleapis.com/v3/projects/smart-ads-451319/timeSeries" \
  --data-urlencode 'filter=metric.type="pubsub.googleapis.com/subscription/num_undelivered_messages" AND resource.label.subscription_id="lead-capture-ingest-sub"' \
  --data-urlencode "interval.startTime=$(date -u -v-20M +%Y-%m-%dT%H:%M:%SZ)" \
  --data-urlencode "interval.endTime=$(date -u -v-90S +%Y-%m-%dT%H:%M:%SZ)"
```

## Conserto

- **`allUsers` sumiu** → recolocar: `gcloud run services add-iam-policy-binding smart-ads-api --region=us-central1 --member=allUsers --role=roles/run.invoker` (propaga em ~1-2min).
- **Backlog acumulado** → drenar na mão até esvaziar:
  ```bash
  URL=https://smart-ads-api-gazrm25mda-uc.a.run.app/pubsub/process-pending
  for i in $(seq 1 60); do p=$(curl -s -X POST "$URL" | python3 -c "import sys,json;print(json.load(sys.stdin).get('processed',0))"); echo "$i: $p"; [ "$p" = "0" ] && break; done
  ```
  Confirmar sempre pelo metric depois (pulls vazios podem ser transientes).
- **Relatório do dia não saiu** → reenviar o DM (seguro): `curl -s "https://smart-ads-api-gazrm25mda-uc.a.run.app/monitoring/slack-digest?channel_full=D0A9USV3XEX&hours=24"`. Canal do cliente só com OK explícito.

## Post-mortem 22-23/07/2026

Removi o `allUsers` em 22/07 12:09 UTC como limpeza pós-deploy (seguindo a instrução
do próprio `deploy_capi.sh`). Como os crons eram anônimos, TODOS deram 403 por ~22h:
relatórios não saíram e o `pubsub-process-pending` parou → ~1.060 leads empilhados na
fila (não perdidos, Pub/Sub retém). Conserto: restaurar `allUsers`, drenar a fila.
Endurecimento (este PR): (A) deploy nunca remove allUsers + doc; (B) crons com OIDC;
(C) DEFAULT_BATCH 25→250 (recuperação de horas → ~20min); (D) 2 alertas. Follow-up
aberto: splitar o webhook num serviço público próprio pra o resto poder ser privado.
Detalhe: memória `incidente_allusers_derruba_crons`.
