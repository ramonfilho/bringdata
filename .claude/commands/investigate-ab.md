# /investigate-ab — Investigação Técnica do Teste A/B

Você é um engenheiro de MLOps verificando se o teste A/B Champion/Challenger está tecnicamente correto — roteamento, eventos CAPI, janela de dados limpa e poder estatístico.

Referência: `V2/docs/AB_TEST.md` — leia antes de começar para ter o contexto dos eventos, UTMs e janela válida.

---

## Passo 1 — Configuração atual

Leia `V2/configs/active_models/devclub.yaml` e extraia:

- `ab_test.enabled` (true/false)
- Variante Champion: run_id, utm_pattern, capi_event_name, capi_event_name_high_quality
- Variante Challenger: run_id, utm_pattern, capi_event_name, capi_event_name_high_quality
- `encoding_overrides` presentes no Champion? (crítico — DT-12)

Se `enabled: false`, pare aqui — o teste não está ativo.

---

## Passo 2 — Janela de dados válida

A janela limpa atual é:

```
início: 2026-04-01 03:00:00 UTC  (00:00 BRT — encoding_overrides aplicado)
fim:    2026-04-13 22:33:56 UTC  (rollback deployado sem A/B test)
```

Qualquer análise deve usar essa janela. Se houver nova janela após reativação do teste, confirme a data do deploy e atualize os limites.

---

## Passo 3 — Volume por variante

```sql
SELECT
    CASE
        WHEN campaign ILIKE '%ML_MAR%' THEN 'Challenger (mar24)'
        ELSE 'Champion (jan30)'
    END AS variante,
    COUNT(*) AS leads_totais,
    COUNT(CASE WHEN decil IS NOT NULL THEN 1 END) AS leads_scored,
    COUNT(CASE WHEN "capiStatus" = 'success' THEN 1 END) AS capi_success,
    COUNT(CASE WHEN "capiStatus" = 'blocked' THEN 1 END) AS capi_blocked,
    ROUND(COUNT(CASE WHEN decil = 10 THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN decil IS NOT NULL THEN 1 END), 0), 1) AS d10_pct
FROM "Lead"
WHERE "createdAt" >= '2026-04-01 03:00:00'
  AND "createdAt" <  '2026-04-13 22:33:56'
GROUP BY 1;
```

Verifique:
- Challenger com < 10% do volume do Champion → UTM pode estar errado ou campanhas ML_MAR com baixo investimento
- `capi_blocked` > 5% em qualquer variante → o Meta não está recebendo o sinal
- `leads_scored = 0` → pipeline não está rodando para aquela variante

---

## Passo 4 — Roteamento correto (leads ML_MAR indo para o Challenger)

```sql
-- Leads ML_MAR: todos devem ter capiStatus != null e leadScore != null
SELECT
    campaign,
    COUNT(*) AS total,
    COUNT(CASE WHEN "leadScore" IS NOT NULL THEN 1 END) AS com_score,
    COUNT(CASE WHEN "leadScore" IS NULL THEN 1 END) AS sem_score,
    ROUND(AVG("leadScore")::numeric, 4) AS score_medio,
    ROUND(AVG(decil::numeric), 2) AS decil_medio
FROM "Lead"
WHERE "createdAt" >= '2026-04-01 03:00:00'
  AND "createdAt" <  '2026-04-13 22:33:56'
  AND campaign ILIKE '%ML_MAR%'
GROUP BY campaign
ORDER BY total DESC
LIMIT 20;
```

Alerta: se `sem_score > 0` para leads ML_MAR, o roteamento falhou silenciosamente.

---

## Passo 5 — Eventos CAPI enviados por variante

```sql
-- Verificar que ML_MAR recebe LeadQualifiedCha e não LeadQualified
SELECT
    CASE WHEN campaign ILIKE '%ML_MAR%' THEN 'Challenger' ELSE 'Champion' END AS variante,
    -- capiEventName pode estar em campo separado ou inferido pela campaign
    "capiStatus",
    COUNT(*) AS eventos
FROM "Lead"
WHERE "createdAt" >= '2026-04-01 03:00:00'
  AND "createdAt" <  '2026-04-13 22:33:56'
  AND "capiSentAt" IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
```

Se o banco não tiver campo de event_name, valide via logs do Cloud Run:

```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=smart-ads-api AND textPayload:LeadQualifiedCha" \
  --limit=20 --format="value(textPayload)"
```

Esperado:
- Champion → `LeadQualified` / `LeadQualifiedHighQuality`
- Challenger → `LeadQualifiedCha` / `LeadQualifiedChaHighQuality`

Se Challenger estiver enviando `LeadQualified`, o roteamento de eventos CAPI está errado — os dados do teste são inválidos.

---

## Passo 6 — Distribuição de decis por variante

```sql
SELECT
    CASE WHEN campaign ILIKE '%ML_MAR%' THEN 'Challenger' ELSE 'Champion' END AS variante,
    decil,
    COUNT(*) AS leads,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (
        PARTITION BY CASE WHEN campaign ILIKE '%ML_MAR%' THEN 'Challenger' ELSE 'Champion' END
    ), 1) AS pct
FROM "Lead"
WHERE "createdAt" >= '2026-04-01 03:00:00'
  AND "createdAt" <  '2026-04-13 22:33:56'
  AND decil IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
```

Procure por:
- Champion com D10% muito diferente do Challenger → modelos com calibração diferente (esperado, mas documentar)
- Qualquer variante com D10% < 5% → modelo pode estar produzindo scores comprimidos

---

## Passo 7 — Contaminação pelo período de rollback

Verifique se há leads ML_MAR que foram processados durante o rollback (sem A/B test) e receberam o evento errado:

```sql
SELECT
    DATE_TRUNC('hour', "createdAt") AS hora,
    COUNT(*) AS leads_ml_mar,
    COUNT(CASE WHEN "leadScore" IS NOT NULL THEN 1 END) AS com_score
FROM "Lead"
WHERE campaign ILIKE '%ML_MAR%'
  AND "createdAt" >= '2026-04-13 20:00:00'  -- 2h em torno do rollback
  AND "createdAt" <= '2026-04-14 06:00:00'
GROUP BY 1
ORDER BY 1;
```

Leads ML_MAR com score entre 22:33 UTC (13/04) e a reativação do A/B test estão contaminados — precisam ser excluídos da análise.

---

## Passo 8 — Poder estatístico (vale a pena continuar?)

Com os volumes do Passo 3, calcule:

```python
from scipy import stats
import numpy as np

n_champion = <leads_champion>
n_challenger = <leads_challenger>

# Taxa de conversão histórica do Champion (D10 é ~1.75%, mas para todos os leads usar baseline)
p_champion = 0.0066  # baseline do modelo jan30

# Para detectar melhoria de 20% no Challenger com 80% de poder:
effect_size = 0.20
p_challenger_detectavel = p_champion * (1 + effect_size)

from statsmodels.stats.power import NormalIndPower
analysis = NormalIndPower()
n_needed = analysis.solve_power(
    effect_size=abs(p_challenger_detectavel - p_champion) / np.sqrt(p_champion * (1 - p_champion)),
    power=0.80,
    alpha=0.05
)
print(f"Leads necessários por grupo: {n_needed:.0f}")
print(f"Champion atual: {n_champion} ({'OK' if n_champion >= n_needed else 'INSUFICIENTE'})")
print(f"Challenger atual: {n_challenger} ({'OK' if n_challenger >= n_needed else 'INSUFICIENTE'})")
```

---

## Passo 9 — Síntese técnica

Produza uma tabela de status:

| Verificação | Status | Detalhe |
|---|---|---|
| A/B test habilitado | ✓/✗ | |
| encoding_overrides no Champion | ✓/✗ | |
| Roteamento ML_MAR → Challenger | ✓/✗ | |
| Eventos CAPI corretos por variante | ✓/✗ | |
| Volume Challenger ≥ 15% do Champion | ✓/✗ | |
| Janela limpa identificada | ✓/✗ | início → fim |
| Contaminação por rollback | sim/não | leads afetados |
| Poder estatístico suficiente | ✓/✗ | leads necessários vs atuais |

**Conclusão**: o teste está tecnicamente válido para análise? Se não, quais são os bloqueadores e o que precisa ser corrigido antes de tirar qualquer conclusão.
