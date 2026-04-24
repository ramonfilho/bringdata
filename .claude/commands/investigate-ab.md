# /investigate-ab — Investigação de equivalência de decis entre revisões Cloud Run

Você é um engenheiro de MLOps verificando se um **canary deploy** está entregando um sinal de scoring equivalente (ou melhor) que a revisão anterior. Hoje não temos Champion/Challenger por UTM — temos **duas revisões Cloud Run convivendo** (rollback vs main unificada) e queremos saber se a nova não está degradando o sinal.

Referência: `V2/docs/AB_TEST.md` seção "Estratégia de deploy — 50/50 em vez de 100%" e `V2/docs/PLANO_EXECUCAO.md` Fase 3.

**Premissa:** `ab_test.enabled` está `false`. Cada revisão scora 100% dos seus leads com um modelo único. O split é gerenciado pelo Cloud Run, não por UTM.

---

## Passo 1 — Identificar as revisões em tráfego

```bash
gcloud run services describe smart-ads-api --region us-central1 \
  --format="value(status.traffic[].revisionName,status.traffic[].percent,status.traffic[].tag)"
```

Esperado: 2 revisões com tráfego > 0% (ex.: 90/10 ou 50/50). Revisões com tag `staging` ou `canary-*` com 0% não entram.

Anote:
- `REV_BASELINE` = revisão com maior tráfego (referência conhecida)
- `REV_CANARY` = revisão com menor tráfego (a validar)
- Confirmar `active_model.mlflow_run_id` de cada: ler `configs/active_models/devclub.yaml` na branch/commit deployado em cada revisão.

Se só houver 1 revisão com tráfego, não há canary para validar — parar.

---

## Passo 2 — Distribuição de decis por revisão (últimas 24h)

Para cada revisão, contar decis a partir dos logs CAPI:

```bash
for REV in $REV_BASELINE $REV_CANARY; do
  echo "=== $REV ==="
  gcloud logging read "resource.type=cloud_run_revision \
    AND resource.labels.service_name=smart-ads-api \
    AND resource.labels.revision_name=$REV \
    AND textPayload:\"LeadQualified enviado\"" \
    --limit=2000 --freshness=24h --format="value(textPayload)" \
    | grep -oE "decil: D[0-9]+" | sort | uniq -c | sort -rn
done
```

**Atenção ao formato dos decis:**
- Modelos antigos (pré-refactor): `D1, D2, ..., D9, D10`
- Modelos novos (pós-refactor): `D01, D02, ..., D09, D10`

Um canary com formato diferente do baseline é **esperado** (o refactor normalizou para `D01`–`D10`). Mas a lógica de downstream (`decil_to_value`, `high_quality_decils`) precisa aceitar o formato emitido. Se não aceitar, o CAPI envia `value=0` ou filtra erradamente — investigar `api/business_config.py` e `api/capi_integration.py` se suspeitar.

---

## Passo 3 — Comparar distribuição

Normalize as contagens em percentuais e compare lado a lado. Exemplo:

| Decil | Baseline (n=N_b) | Canary (n=N_c) | Δ pp | Diagnóstico |
|---|---|---|---|---|
| D10 | X% | Y% | ±Z pp | |
| D09 | | | | |
| ... | | | | |
| D01 | | | | |

Critérios de atenção:
- **D10% > 25%** em qualquer revisão → colapso de D10 (esperado ~10%; drift conhecido no jan30 original).
- **D10% < 5%** → scores comprimidos; modelo pode não estar discriminando.
- **|Δ pp| > 10 em qualquer decil** → diferença estrutural entre modelos — esperada se o canary foi retreinado, mas precisa ser justificada.
- **Distribuição do canary mais uniforme que baseline** → possivelmente *bom sinal* (correção do drift). Ainda assim, comparar contra expectativa de 10% por decil no dataset de treino.

---

## Passo 4 — Volume proporcional ao split

Confirmar que o número de eventos CAPI por revisão é coerente com o split declarado. Com 10/90, espera-se ~11× mais eventos no baseline. Variação grande (ex.: 50×) pode indicar:
- Um dos endpoints não está rodando numa revisão (ex.: Cloud Scheduler só bate num host fixo)
- Canary ainda aquecendo (cold start) — refazer em algumas horas
- Erro de roteamento na camada Cloud Run

```bash
for REV in $REV_BASELINE $REV_CANARY; do
  N=$(gcloud logging read "resource.type=cloud_run_revision \
    AND resource.labels.service_name=smart-ads-api \
    AND resource.labels.revision_name=$REV \
    AND textPayload:\"LeadQualified enviado\"" \
    --limit=2000 --freshness=24h --format="value(textPayload)" | wc -l)
  echo "$REV: $N eventos"
done
```

---

## Passo 5 — Erros 5xx e simetria

```bash
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=smart-ads-api \
  AND httpRequest.status>=500" \
  --limit=100 --freshness=24h \
  --format="value(timestamp,resource.labels.revision_name,httpRequest.status,httpRequest.requestUrl)"
```

Comparar taxa de 5xx entre as revisões. Erros **simétricos** (mesma URL, ambas as revisões) geralmente são upstream (Railway DB timeout, Cloud SQL indisponível). Erros **assimétricos** (só no canary) são regressão do novo código — investigar stack trace.

---

## Passo 6 — Síntese

| Verificação | Status | Detalhe |
|---|---|---|
| Duas revisões com tráfego identificadas | ✓/✗ | baseline / canary / split |
| Formato de decil consistente com downstream | ✓/✗ | D1–D10 ou D01–D10 |
| D10% dentro do intervalo saudável (5–25%) | ✓/✗ | baseline X%, canary Y% |
| Distribuição comparável ou canary ≥ saudável | ✓/✗ | resumo dos Δ |
| Volume proporcional ao split | ✓/✗ | N_base / N_canary |
| 5xx simétricos (upstream, não regressão) | ✓/✗ | lista de URLs |

**Conclusão:** o canary pode progredir para próxima fatia de tráfego? Se não, qual é o bloqueador e o que observar antes de reavaliar?
