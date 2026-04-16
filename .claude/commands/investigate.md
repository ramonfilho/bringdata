# /investigate — Investigação de Desempenho de Modelo

Você é um analista de ML investigando por que os resultados de um lançamento foram ruins ou inesperados. Seu objetivo é mapear causas possíveis com evidências numéricas, não apenas teóricas.

## Contexto do sistema

- Modelo ativo: configurado em `V2/configs/active_models/devclub.yaml`
- Artefatos: `V2/files/{timestamp}/model_metadata_*.json`
- Banco de dados: Railway PostgreSQL (tabela `Lead`, colunas camelCase: `leadScore`, `decil`, `capiStatus`, `capiSentAt`, `campaign`, `createdAt`)
- CAPI events: `capiStatus` = success/skipped/blocked/null

## Passo 1 — Identificar o modelo em uso e seu período de dados

Leia `V2/configs/active_models/devclub.yaml` e o `model_metadata_*.json` correspondente.

Extraia e apresente:
- Nome do modelo e run ID
- Período do dataset: `temporal_split.period_start` → `period_end`
- Data de corte treino/test: `cut_date`
- Total de registros de treino e test
- AUC e lift máximo
- Thresholds D9 e D10 (min/max)

> Isso estabelece até quando o modelo "viu" o mundo antes de ser deployado.

## Passo 2 — Distribuição de decis em produção (por lançamento)

Rode a query abaixo no banco Railway. Substitua o período conforme o lançamento sendo investigado (padrão: últimos 90 dias):

```sql
SELECT
    DATE_TRUNC('week', "createdAt") AS semana,
    decil,
    COUNT(*) AS leads,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY DATE_TRUNC('week', "createdAt")), 1) AS pct
FROM "Lead"
WHERE "createdAt" >= NOW() - INTERVAL '90 days'
  AND decil IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
```

Procure por:
- D10% variando significativamente entre semanas
- Colapso de decis altos (D9/D10 somem)
- Inflação de decis baixos

## Passo 3 — Verificar features críticas chegando zeradas

Rode inline com Python para checar se as features mais importantes estão chegando com valores esperados. Pegue uma amostra de leads recentes do Railway e passe pelo pipeline de produção:

```python
import sys; sys.path.insert(0, 'V2')
from src.production_pipeline import LeadScoringPipeline
import json

p = LeadScoringPipeline()

# Pegar amostra do banco (últimos 100 leads com pesquisa respondida)
# Cole aqui alguns payloads reais do campo `pesquisa` da tabela Lead
# e verifique se Medium_Linguagem_programacao, idade e faixa salarial chegam corretos

sample = p.predictor.feature_registry  # features que o modelo espera
print("Features esperadas:", len(sample))
```

Procure por:
- `Medium_Linguagem_programacao` sempre 0 → bug de encoding OHE/binary_top3
- Colunas de idade/salário todas 0 → bug de ordinal encoding
- Features ausentes no registry de produção vs treino

## Passo 4 — Status do sinal CAPI ao longo do tempo

```sql
SELECT
    DATE_TRUNC('week', "capiSentAt") AS semana,
    "capiStatus",
    COUNT(*) AS eventos
FROM "Lead"
WHERE "capiSentAt" >= NOW() - INTERVAL '90 days'
GROUP BY 1, 2
ORDER BY 1, 2;
```

Procure por:
- Semanas com `capiStatus = blocked` ou `null` em volume alto → sinal não chegou ao Meta
- Queda brusca em `success` → deploy com bug silencioso

## Passo 5 — Comparar conversão por decil vs histórico

Verifique se as taxas de conversão observadas em produção ainda batem com as taxas registradas no `model_metadata`:

```sql
-- Requer matching com tabela de vendas (ajustar nome conforme cliente)
SELECT
    decil,
    COUNT(*) AS leads,
    SUM(CASE WHEN comprou THEN 1 ELSE 0 END) AS conversoes,
    ROUND(AVG(CASE WHEN comprou THEN 1.0 ELSE 0 END) * 100, 2) AS taxa_pct
FROM "Lead"
WHERE "createdAt" BETWEEN '<inicio_captacao>' AND '<fim_captacao>'
GROUP BY decil
ORDER BY decil;
```

Compare com as `conversion_rates` do `devclub.yaml`. Desvio > 30% em D9/D10 é sinal de alerta.

## Passo 6 — Checar se o período do lançamento está dentro ou fora da janela de dados do modelo

Compare:
- `period_end` do modelo (último dado que ele viu)
- Data de captação do lançamento sendo investigado

Se a captação está > 3 meses após `period_end`, drift de audiência é hipótese forte.

Calcule também: quantos lançamentos aconteceram entre `period_end` e hoje? O modelo nunca viu nenhum deles.

## Passo 7 — Síntese: mapeamento de causas

Ao final, produza uma tabela com as hipóteses encontradas:

| Hipótese | Evidência encontrada | Confirmada? | Corrigível? |
|---|---|---|---|
| Bug de encoding em produção | | | |
| Sinal CAPI mal calibrado (LQ vs LQHQ) | | | |
| Drift de audiência (modelo desatualizado) | | | |
| Volume insuficiente de D9/D10 | | | |
| Feature drift (perguntas mudaram) | | | |

E uma conclusão em linguagem de negócio — no formato do exemplo abaixo — adequada para compartilhar com o gestor de tráfego.

---

## Argumentos para o gestor (template de saída)

> **O que está acontecendo:** [1 parágrafo]
> **Causa identificada:** [lista de causas confirmadas]
> **O que já foi corrigido:** [ações tomadas]
> **O que ainda está em curso:** [prazo estimado]
> **Por que retreinar pode ser necessário:** [dados de período_end + drift evidence]
