# Alertas críticos — especificação

**Versão:** 2026-05-13
**Status:** spec fechada, pré-implementação

## Propósito

Disparar avisos no Slack **imediatamente** (independente do digest diário das 06h BRT) quando algum sintoma crítico for detectado em produção. Cobre quebras silenciosas que o digest diário só pegaria horas depois.

## Princípios

- **DM pessoal**, nunca canal do cliente.
- **24/7**, sem quiet hours.
- **Zero custo adicional** no GCP — sem novo Cloud Scheduler, sem novo endpoint exclusivo.
- **Janela rolling de 60 minutos** para cada regra.
- **Cooldown de 15 min por regra** para evitar spam.
- **Sem regras automáticas de feature flag** — toda regra está sempre ligada.

## Arquitetura

Hookar dentro do endpoint `/railway/process-pending` que já roda a cada 5 minutos via Cloud Scheduler existente.

```
Cloud Scheduler atual ─5min─►  /railway/process-pending
                                       │
                                       ├── processa leads pendentes (lógica atual)
                                       └── critical_checks.run(ctx)
                                            ├── itera 6 regras
                                            ├── para cada fired: dispatcher.maybe_send(rule)
                                            │     ├── verifica cooldown na tabela Railway
                                            │     └── posta DM via Slack chat.postMessage
                                            └── update last_evaluated_at por regra
```

**Estado em Railway PostgreSQL** (nenhum Redis novo):

```sql
CREATE TABLE critical_alert_state (
  rule_name           text PRIMARY KEY,
  last_fired_at       timestamptz,
  last_resolved_at    timestamptz,
  consecutive_fires   int DEFAULT 0,
  last_message        text
);
```

**Cooldown:** se `now - last_fired_at < 15min`, suprime envio mas incrementa `consecutive_fires`. Quando regra avalia OK por ≥30 min consecutivos, zera `consecutive_fires` e marca `last_resolved_at`.

## Regras

Cada regra avalia a janela das últimas 60 minutos (≠ polling de 5min — a janela é o critério estatístico).

### Regra 1 — Variant com leads roteados mas 0 CAPI enviado

**Dispara quando:** durante A/B test ativo, Champion ou Challenger recebeu ≥ 10 leads roteados nos últimos 60min **e** 0 eventos CAPI enviados.

**Query base:** `Lead.leadScore IS NOT NULL` agrupando por `variant` (derivado via `_iter_active_variants`), comparando contra `capiSentAt IS NOT NULL AND capiStatus NOT IN ('blocked','skipped')`.

**Skip silencioso quando:**
- A/B test não está habilitado no `active_models/devclub.yaml`.
- Nenhum variant teve ≥ 10 leads roteados (sem amostra).

**Mensagem:** `🚨 Variant *{name}* recebeu N leads em 60min mas 0 eventos CAPI enviados. Investigar pipeline de envio.`

---

### Regra 4 — Leads não chegando no banco

**Dispara quando:** 0 leads inseridos em `Lead` nos últimos 60min (corte por `Lead.createdAt`).

**Mensagem:** `🚨 Zero leads novos em 60min — última inserção: {timestamp}. LP/Prisma pode estar travado.`

---

### Regra 5 — Polling com leads mas `capi_success_rate < 95%`

**Dispara quando:** ≥ 10 leads com `capiSentAt IS NOT NULL` nos últimos 60min **e** taxa de `capiStatus = 'success'` < 95%.

**Mensagem:** `🚨 capi_success_rate em 60min = {pct}% (limite 95%). N enviados: {n}, sucesso: {ok}, erro: {err}.`

---

### Regra 6 — FBP/FBC baixo

**Dispara em dois níveis:**
- HIGH: `fbp < 95%` **ou** `fbc < 80%`
- MEDIUM: `fbp < 98%` **ou** `fbc < 88%`

Computado nos últimos 60min via JOIN `Lead × leads_capi ON LOWER(email)`. Mínimo de 50 leads na janela pra evitar variância amostral pequena.

**Mensagem:** `🚨 FBP={pct}% FBC={pct}% em 60min (limite HIGH 95/80, MEDIUM 98/88). N={n}.`

---

### Regra 9 — `/railway/process-pending` falhando

**Dispara quando:** O endpoint retornou HTTP 500 em **≥ 2 pollings consecutivos**.

**Implementação:** cada execução do endpoint grava status (`success`/`error`) numa tabela `polling_status` no Railway. A regra é avaliada lendo essa tabela — se as últimas 2 entradas têm `status='error'`, dispara.

**Mensagem:** `🚨 /railway/process-pending falhou nos últimos {n} pollings (de {timestamp}). Leads pendentes podem estar acumulando.`

**Nota:** se o próprio polling estiver morto e nunca executar, a Regra 4 (zero leads scoreados) acaba pegando o sintoma por outro caminho.

---

### Regra + — Drift de score (duas leituras combinadas)

**Dispara se qualquer uma das condições bater:**

**(A) Score médio das últimas 60min vs baseline rolling 30d:**
- shift > 1σ da distribuição rolling 30d
- mínimo 50 leads com `leadScore IS NOT NULL` na janela

**(B) Distribuição de decis das últimas 60min vs distribuição esperada (rolling 30d):**
- teste KS com `p < 0.01` **OU** delta em D10 ≥ 5 pp
- mínimo 100 leads com `decil IS NOT NULL` na janela

Reusa o `expected_decil_dist` já calculado para o E6 do monitoring (rolling 30d na tabela `Lead`).

**Mensagem:** `🚨 Drift de score em 60min: score médio {x} (esperado {y}, σ={sigma}), D10={pct} (esperado {ref}%). Possível mudança de público ou bug.`

## Schema de saída no Slack

Mensagem por regra é uma postagem única, simples (não Block Kit elaborado):

```
🚨 [CRÍTICO] <regra>
Detectado: <timestamp UTC + BRT>
<descrição>
<números relevantes>
Janela: últimos 60min
```

## O que NÃO é coberto aqui

(Fica só no relatório diário das 06h BRT — não é crítico imediato.)

- Score do dia 2σ abaixo da média rolling 14d (granular por Source)
- `db_leads/clicks` abaixo do percentil 5 rolling 30d
- Algum decil D1–D10 com 0 leads
- Categoria nova aparecendo fora da whitelist do treino
- Smoke test `/smoke/run-variants` retornando fail

## Próximos passos de implementação

1. Criar `src/monitoring/critical_alerts.py` com classe base `CriticalRule` + 6 implementações.
2. Criar `polling_status` e `critical_alert_state` no Railway (migration manual).
3. Hookar `critical_checks.run(ctx)` no fim de `/railway/process-pending`, com try-except — falha de check não pode quebrar o polling.
4. Implementar `SlackDispatcher` com cooldown via `critical_alert_state`.
5. Cadastrar SLACK_USER_DM no Secret Manager (canal alvo).
6. Validar localmente cada regra com fixtures antes de deploy.
