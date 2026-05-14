# Checklist de Promoção de Modelo (Champion / Challenger)

**Atualizado:** 2026-05-08
**Propósito:** evitar a "pegadinha de promoção" — substituir o `mlflow_run_id` do Champion sem migrar `encoding_overrides`, `conversion_rates` e códigos correlatos quebra produção em segundos. Este doc é o protocolo obrigatório.

> **Nota sobre identificadores codificados (`T1-10`, `DT-12`, `DT-17`, `DT-18`):** este doc cita IDs curtos pra rastreabilidade. O nome verbal e contexto completo de cada um vivem nos catálogos:
> - `T1-10` ("detecção de feature crítica zerada após encoding") — ver [`PLANO_SAFEGUARD.md`](PLANO_SAFEGUARD.md).
> - `DT-12` ("encoding diferente por variante A/B"), `DT-17` ("eliminar duplicação business_config × YAML"), `DT-18` ("normalizar 4 features binárias raw") — ver [`PLANO_REFACTOR_MLOPS.md`](PLANO_REFACTOR_MLOPS.md).

---

## A pegadinha em uma linha

**Promover um modelo NÃO é trocar `mlflow_run_id`.** É promover **modelo + config de encoding + conversion_rates + (eventualmente) eventos Pixel + UTM routing**, tudo no mesmo deploy. Trocar parcial deixa o encoding inconsistente com o feature_registry do modelo novo, e o Champion serve com features zeradas silenciosamente em ~10% de importância.

---

## Por que existe a pegadinha

`configs/active_models/devclub.yaml` define hoje **3 estruturas independentes** que precisam estar sincronizadas:

```yaml
active_model:
  mlflow_run_id: <run_X>          # → carrega o pickle do modelo do MLflow

ab_test:
  variants:
    champion_jan30:                # ← shim do Champion (mesmo run_id do active_model)
      run_id: <run_X>
      encoding_overrides:          # 🔴 lido em produção, força ordinal
        ordinal_variables:
          "Qual a sua idade?": [...]
          "Atualmente, qual a sua faixa salarial?": [...]
      conversion_rates:            # 🔴 lido em produção, sobrescreve business_config
        D01: ... D10: ...
```

Cada um é lido em pontos diferentes do `api/app.py`:
- `active_model.mlflow_run_id` → carregado em boot pelo `LeadScoringPipeline` (1 vez)
- `champion_jan30.encoding_overrides` → lido **a cada lead** que vai pelo path Champion (`api/app.py:937-947`, `:3373-3380`)
- `champion_jan30.conversion_rates` → lido **a cada CAPI event** (`api/app.py:1016, :3516` → vira `conversion_rates_override` em `capi_integration.py:347`)

Resultado: trocar `mlflow_run_id` mas manter o resto = encoding ordinal aplicado a um modelo que espera OHE → features de idade/salário **zeradas** → ~10% de importância perdida sem alerta visível ao usuário (T1-10 dispara warning, mas o lead ainda é processado e enviado ao Meta).

---

## Tipos de promoção

Cada tipo tem checklist próprio. Identifique antes de começar.

### Tipo 1 — Promoção "leve" (mesmo encoding, novo run_id)

Quando o modelo novo foi treinado **com a mesma config de encoding** do Champion atual (ex: ambos OHE puro, ambos ordinal idade+salário, etc.).

**Características:**
- Mesma estrutura de features (mesmo número, mesmos nomes)
- `feature_registry.json` do novo modelo pode diferir só em `feature_importance` e `decil_thresholds`
- `conversion_rates` precisa ser back-calculado mesmo assim (distribuição de probas muda)

**Risco:** baixo — só pegadinha sutil em `conversion_rates`.

### Tipo 2 — Promoção com mudança de encoding

Quando o modelo novo foi treinado **com encoding diferente** (ex: Champion atual usa ordinal idade/salário, novo usa OHE; ou novo remove `--exclude-features`).

**Características:**
- `feature_registry.json` lista features diferentes
- `encoding_overrides` do shim Champion precisa ser **migrado ou removido**
- `conversion_rates` precisa back-calcular

**Risco:** alto — é onde a pegadinha mata.

### Tipo 3 — Promoção com novo evento Pixel ou UTM routing

Quando o modelo novo é uma **arm experimental** (challenger), não substitui o Champion default.

**Características:**
- Modelo novo recebe variant própria com `utm_pattern` ou `url_pattern`
- Pixel evento próprio (ex: `HQLB`, `ReducedLQ`)
- Pixel ID pode ser diferente
- Champion atual **permanece intocado**

**Risco:** baixo — não toca no Champion default; isolado por roteamento.

---

## Checklist Tipo 1 — Promoção leve

```
□ 1. Confirmar que feature_registry.json do novo run lista MESMAS features
     que o Champion atual (mesmo número, mesmos nomes)

□ 2. Back-calcular conversion_rates do novo modelo a partir do
     test_set_predictions OU re-extraindo distribuições do MLflow run

□ 3. Editar configs/active_models/devclub.yaml:
     □ active_model.mlflow_run_id   → novo run_id
     □ active_model.trained_at      → data do novo treino
     □ active_model.performance     → métricas do novo run
     □ champion_<nome>.run_id       → novo run_id
     □ champion_<nome>.conversion_rates → back-calculados

□ 4. Não tocar em encoding_overrides do shim Champion
     (mesmo encoding, mantém)

□ 5. Rodar parity audit local antes do deploy:
     python -m pytest V2/tests/parity_audit.py -v

□ 6. Deploy --no-traffic + smoke test (5 leads reais)

□ 7. Promover gradual: 5% → 10% → 50% → 100%
```

## Checklist Tipo 2 — Promoção com mudança de encoding

```
□ 1. Mapear features adicionadas e removidas:
     diff <(jq -r '.model_input_features.ordered_list[]' OLD/feature_registry.json) \
          <(jq -r '.model_input_features.ordered_list[]' NEW/feature_registry.json)

□ 2. Para CADA encoding_override do shim Champion atual:
     □ A feature ainda existe no novo registry com mesma forma?
       → manter override
     □ A feature mudou de ordinal para OHE no novo modelo?
       → REMOVER do encoding_overrides
     □ A feature foi removida (--exclude-features)?
       → REMOVER do encoding_overrides

□ 3. Back-calcular conversion_rates do novo modelo

□ 4. Editar configs/active_models/devclub.yaml em ÚNICO commit:
     □ active_model.mlflow_run_id   → novo
     □ active_model.trained_at, performance
     □ champion_<nome>.run_id       → novo
     □ champion_<nome>.encoding_overrides → ajustado conforme passo 2
     □ champion_<nome>.conversion_rates   → back-calculados

□ 5. Validar localmente que o pipeline gera as features esperadas:
     python -m src.production_pipeline --client devclub --batch <amostra>
     # Verificar logs T1-10: nenhuma "feature CRÍTICA ausente"

□ 6. Rodar parity audit treino × produção:
     python -m pytest V2/tests/parity_audit.py -v

□ 7. Smoke test em 5 leads reais ANTES de deployar com tráfego

□ 8. Deploy --no-traffic + canary 5% × 24h + verificar:
     □ /monitoring/feature-report : batches_with_issues == 0
     □ Logs Cloud Run : zero T1-10 ERROR
     □ Distribuição de decis em produção bate com test set do MLflow

□ 9. Promover gradual: 5% → 10% → 50% → 100% com validação a cada passo
```

## Checklist Tipo 3 — Nova arm experimental (challenger)

```
□ 1. Treinar modelo com encoding novo
     (use --exclude-features se reduzir features)

□ 2. Definir mecanismo de roteamento ÚNICO:
     □ utm_pattern (ex: utm_term: "REDUCED")
     □ url_pattern (ex: ml-parabens-psq-reduced)
     □ Confirmar que NENHUM lead atual atende esse pattern
       (senão você está roubando tráfego do Champion)

□ 3. Criar evento novo no Meta Pixel:
     □ Nome único (ex: "ReducedLQ", "ReducedHQ")
     □ Test event antes de salvar
     □ Anotar Pixel ID se for diferente do Champion

□ 4. Back-calcular conversion_rates da nova variante

□ 5. Adicionar variante em configs/active_models/devclub.yaml:
     ab_test:
       variants:
         <nova_variante>:
           run_id: <run_id_novo>
           utm_pattern: { ... }
           url_pattern: ...
           pixel_id_override: ...        # se aplicável
           capi_event_name: ReducedLQ
           capi_event_name_high_quality: ReducedHQ
           conversion_rates: { ... }
           encoding_overrides:           # se modelo precisar de override
             ordinal_variables: { ... }

□ 6. NÃO tocar no champion_<nome> shim — Champion permanece intocado

□ 7. Deploy + smoke test isolado da arm:
     curl com utm_term="REDUCED" → confirmar que vai pra arm nova
     curl sem o utm → confirmar que vai pro Champion

□ 8. Rodar lançamento completo, comparar métricas no /investigate-ab

□ 9. SE ganho confirmado: promover via Tipo 2 (substitui Champion default)
```

---

## Sinais de que algo deu errado pós-deploy

Verificar nas primeiras 24h:

| Sinal | O que checar | Provável causa |
|---|---|---|
| Logs com `[T1-10] Feature CRÍTICA ausente` | Cloud Run | encoding_overrides desatualizado vs novo modelo |
| `batches_with_issues > 0` em /monitoring/feature-report | endpoint | feature do registry não está sendo gerada |
| Distribuição de decis em produção 0% em D9-D10 | Cloud SQL | conversion_rates apontando pra valores zerados |
| ROAS cai 30%+ no primeiro lançamento | Validação | Bug silencioso de encoding (features zeradas) |
| Meta CAPI rejeitando eventos | Meta Events Manager | Pixel ID diferente sem registro do evento |

---

## Referência cruzada

- `configs/active_models/devclub.yaml` — config canônica
- `api/app.py:920-947, :3373-3380` — A/B routing + encoding_overrides lookup
- `api/app.py:1016, :3516` — conversion_rates_override propagação
- `capi_integration.py:347` — onde conversion_rates_override é aplicado
- `core/encoding.py:175-203` — merge de EncodingConfig + override
- `core/encoding.py:321-355` — alinhamento ao feature_registry
- `docs/PLANO_REFACTOR_MLOPS.md` DT-12 — histórico do encoding_overrides
- `docs/PLANO_REFACTOR_MLOPS.md` DT-17 — solução arquitetural definitiva (em aberto)

---

## Lições registradas

| Data | Incidente | Correção registrada em |
|---|---|---|
| 2026-05-02 | jan30 servindo leads sem encoding_overrides para path Champion (ab_v=None) | `core/encoding.py` + `api/app.py` (commits 9fe2745, 795770f) |
| 2026-05-08 | Canary 00403-cez VAL=0 parcial — comentário desatualizado afirmava "conversion_rates NUNCA são lidos" | `active_models/devclub.yaml` Patch B + comentário corrigido |
