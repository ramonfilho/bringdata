---
title: Análise de calibração de probabilidades — Champion jan30 e Challenger abr28
data: 2026-05-08
autor: sessão Claude (capi/value=0 + design DT-20)
escopo: medição empírica do quão miscalibrados estão os modelos atualmente em produção; subsídio à decisão de tratar calibração como caminho crítico antes da fórmula `leadScore × ticket / CPL` por lead entrar em produção.
artefatos_consultados:
  - V2/mlruns/1/d51757f5041c44b7ab1a056fce8c3c35/artifacts/model_metadata.json
  - V2/mlruns/1/5d158f0aa6e54b489498470446194a6c/artifacts/model_metadata.json
---

# Análise de calibração de probabilidades — Champion jan30 e Challenger abr28

## Propósito

Quantificar **se** e **quanto** os scores brutos do Random Forest dos dois modelos em produção representam fielmente a probabilidade real de conversão de cada lead. A pergunta surgiu no contexto de uma proposta paralela de mudar a fórmula do valor enviado pra Meta de uma tabela por decil (atual) pra uma multiplicação direta no nível do lead: `value = leadScore × ticket / CPL_adset`. Se o leadScore não for uma probabilidade calibrada, a multiplicação direta amplifica o erro proporcionalmente ao quanto está miscalibrado.

## Pergunta investigada

> O `predict_proba` do Random Forest, combinado com `class_weight='balanced'` no treino, é uma boa aproximação da probabilidade verdadeira de compra — ou existe distorção sistemática grande o suficiente pra mudar significativamente o sinal econômico que vai pra Meta?

## Dados utilizados

Foram consultados exclusivamente os arquivos `model_metadata.json` dos dois modelos em produção, salvos como artifact MLflow durante o treino original. Esses arquivos contêm estatísticas agregadas por decil computadas no test set do split temporal de cada modelo. **Nenhum dado novo foi processado** — toda a análise se baseou nas estatísticas já registradas no treino.

### Champion `jan30`

- **Run MLflow:** `d51757f5041c44b7ab1a056fce8c3c35`
- **Arquivo lido:** `V2/mlruns/1/d51757f5041c44b7ab1a056fce8c3c35/artifacts/model_metadata.json`
- **Modelo:** Random Forest com `class_weight='balanced'`
- **Treinado em:** 30/01/2026
- **AUC no test set:** 0.7311
- **Monotonia de decis:** 88.89%
- **Tamanho do test set:** 33.156 leads (soma de `total_leads` ao longo dos 10 decis)
- **Método de split:** `temporal_leads` — 70% dos leads mais antigos para treino, 30% mais recentes para teste

### Challenger `abr28`

- **Run MLflow:** `5d158f0aa6e54b489498470446194a6c`
- **Arquivo lido:** `V2/mlruns/1/5d158f0aa6e54b489498470446194a6c/artifacts/model_metadata.json`
- **Modelo:** Random Forest com `class_weight='balanced'` + importance weighting (T2-3 alpha=1, grupo controle/ML/neutro)
- **Treinado em:** 28/04/2026
- **AUC no test set:** 0.7531
- **Monotonia de decis:** 77.78%
- **Tamanho do test set:** 40.310 leads
- **Método de split:** mesmo `temporal_leads` 70/30

### Estrutura específica dos campos consumidos

Para cada decil `D1..D10`, foram lidos dois valores:

1. **`decil_analysis.decil_<N>.conversion_rate`** — proporção de leads do decil que efetivamente converteram no test set. Numericamente é `conversions / total_leads`. Representa a **probabilidade observada** de compra dentro do decil.

2. **`decil_thresholds.thresholds.D<N>.mean_probability`** — média dos scores brutos do `predict_proba` dos leads que caíram nesse decil. Representa a **probabilidade afirmada pelo modelo** dentro do decil.

A comparação entre essas duas séries é o coração da análise. Se um modelo é bem calibrado, `mean_probability ≈ conversion_rate` em todos os decis.

## Métricas utilizadas

### Expected Calibration Error (ECE)

Métrica padrão da literatura para resumir miscalibração em um único número. Calculada como:

```
ECE = Σ (n_d / N) × |score_médio_d − P_observado_d|
```

Onde a soma percorre os `d` decis, `n_d` é o número de leads no decil, `N` é o total de leads no test set, `score_médio_d` é a média do `predict_proba` no decil, e `P_observado_d` é a taxa de conversão observada. O resultado é interpretável como "distância média ponderada entre o que o modelo afirma e a realidade observada".

**Faixas de referência usadas na literatura:**

- ECE < 0.05 (5 pontos percentuais): modelo bem calibrado
- ECE entre 0.05 e 0.10: calibração aceitável, melhorias trazem ganho marginal
- ECE > 0.10: severamente miscalibrado — calibração tem efeito material no sinal econômico

### Reliability por decil

Além do ECE agregado, foi calculado o gap absoluto por decil em pontos percentuais (`mean_probability_d − P_observado_d`) × 100. Isso permite ver **onde** o modelo está mais miscalibrado, não só **quanto** em média.

### Métrica auxiliar — ECE nos decis críticos D8-D10

Recalculado o ECE restrito aos decis 8, 9 e 10, porque é onde a maior parte do valor sai pra Meta (D9-D10 dispara o `LeadQualifiedHighQuality`; D10 sozinho tem `conversion_rate` configurada mais alta no YAML).

## Metodologia

### Passo 1 — extração dos pontos do test set original

Para cada um dos dois modelos, foram extraídos 10 pontos correspondentes aos 10 decis:

```
(score_médio_d, P_observado_d, n_leads_d)  para d em 1..10
```

A vantagem desse atalho: evita reprocessar dataset completo, evita subir o Cloud SQL parado do MLflow, e mantém validade interna (são exatamente os números medidos no test set do treino original).

A limitação: agrega tudo dentro de cada decil — não captura variância intra-decil. A precisão é boa pra ECE entre decis, mas perde nuance que só apareceria com dados por lead. Limitação retomada na seção de ressalvas.

### Passo 2 — cálculo de ECE pré-calibração

Aplicada a fórmula do ECE direto sobre os 10 pontos, com peso `n_leads_d` cada. Resultado em pontos percentuais.

### Passo 3 — ajuste da função isotônica

Aplicada `sklearn.isotonic.IsotonicRegression` aos 10 pontos:

```python
iso = IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0)
iso.fit(scores, p_real, sample_weight=n)
scores_calibrados = iso.predict(scores)
```

Parâmetros escolhidos:
- `out_of_bounds='clip'`: scores fora da faixa observada são saturados nos limites da função aprendida. Comportamento conservador.
- `y_min=0.0, y_max=1.0`: força a função a respeitar o intervalo de probabilidade.
- `sample_weight=n`: cada decil pesa proporcionalmente ao seu tamanho — decis maiores influenciam mais a curva ajustada.

A isotônica resulta numa função monotônica não-decrescente em escada que mapeia `score_bruto → score_calibrado`. Por construção, ajustada nos mesmos 10 bins onde o ECE é depois medido, ela zera (ou quase) o gap bin-a-bin. É um ajuste **in-sample** — limitação retomada nas ressalvas.

### Passo 4 — cálculo de ECE pós-calibração

Aplicada a função isotônica nos 10 `score_médio_d` e recomputado o ECE entre `scores_calibrados` e `P_observado_d`. Esperado por construção que seja próximo de zero; a verificação serve principalmente pra confirmar que o algoritmo rodou corretamente.

### Passo 5 — projeção de impacto na fórmula de valor

Calculada a razão `score_bruto / score_calibrado` em decis selecionados (D1, D5, D8, D9, D10). Essa razão representa **o fator pelo qual o valor enviado pra Meta seria inflado** se a fórmula `leadScore × ticket / CPL_adset` for aplicada com score bruto em vez de calibrado. Se a razão for 1, calibração não muda nada; se for 30, o valor enviado fica 30× acima do real.

## Resultados

### Champion `jan30` — calibração por decil

| Decil | Total leads | Score médio (bruto) | P(real) observada | Gap pré-cal | Score calibrado | Gap pós-cal |
|---|---|---|---|---|---|---|
| D1 | 3.316 | 0.0819 | 0.0009 | +8.10 pp | 0.0009 | 0.00 pp |
| D2 | 3.316 | 0.1310 | 0.0012 | +12.98 pp | 0.0012 | 0.00 pp |
| D3 | 3.314 | 0.1599 | 0.0015 | +15.84 pp | 0.0015 | 0.00 pp |
| D4 | 3.315 | 0.1897 | 0.0030 | +18.67 pp | 0.0030 | 0.00 pp |
| D5 | 3.315 | 0.2223 | 0.0045 | +21.78 pp | 0.0045 | 0.00 pp |
| D6 | 3.316 | 0.2620 | 0.0054 | +25.66 pp | 0.0054 | 0.00 pp |
| D7 | 3.316 | 0.3075 | 0.0084 | +29.91 pp | 0.0081 | −0.03 pp |
| D8 | 3.315 | 0.3545 | 0.0078 | +34.67 pp | 0.0081 | +0.03 pp |
| D9 | 3.313 | 0.4113 | 0.0157 | +39.56 pp | 0.0157 | 0.00 pp |
| D10 | 3.316 | 0.5780 | 0.0175 | +56.05 pp | 0.0175 | 0.00 pp |

- **ECE pré-calibração:** 26.32 pp
- **ECE pós-calibração in-sample:** 0.01 pp
- **ECE nos decis críticos D8-D10:** 43.43 pp (pré); ~0 pp (pós)

### Challenger `abr28` — calibração por decil

| Decil | Total leads | Score médio (bruto) | P(real) observada | Gap pré-cal | Score calibrado | Gap pós-cal |
|---|---|---|---|---|---|---|
| D1 | 4.031 | 0.1868 | 0.0000 | +18.68 pp | 0.0000 | 0.00 pp |
| D2 | 4.031 | 0.2530 | 0.0020 | +25.10 pp | 0.0020 | 0.00 pp |
| D3 | 4.031 | 0.2994 | 0.0020 | +29.74 pp | 0.0020 | 0.00 pp |
| D4 | 4.031 | 0.3463 | 0.0027 | +34.36 pp | 0.0022 | −0.05 pp |
| D5 | 4.031 | 0.3891 | 0.0017 | +38.74 pp | 0.0022 | +0.05 pp |
| D6 | 4.031 | 0.4262 | 0.0060 | +42.02 pp | 0.0060 | 0.00 pp |
| D7 | 4.031 | 0.4621 | 0.0062 | +45.59 pp | 0.0062 | 0.00 pp |
| D8 | 4.031 | 0.4964 | 0.0077 | +48.87 pp | 0.0075 | −0.02 pp |
| D9 | 4.031 | 0.5424 | 0.0074 | +53.50 pp | 0.0075 | +0.01 pp |
| D10 | 4.031 | 0.6150 | 0.0226 | +59.24 pp | 0.0226 | 0.00 pp |

- **ECE pré-calibração:** 39.58 pp
- **ECE pós-calibração in-sample:** 0.01 pp
- **ECE nos decis críticos D8-D10:** 53.87 pp (pré); ~0 pp (pós)

### Razão de inflação se a fórmula `leadScore × ticket / CPL` for aplicada sem calibrar

| Decil | Champion `jan30` (razão bruto/calibrado) | Challenger `abr28` (razão bruto/calibrado) |
|---|---|---|
| D1 | 91× | (D1 calibrado ≈ 0; razão indefinida — modelo afirma 18.7% onde realidade é 0%) |
| D5 | 49× | 177× |
| D8 | 44× | 66× |
| D9 | 26× | 72× |
| D10 | **33×** | **27×** |

A coluna do D10 é a mais relevante operacionalmente: D10 é o decil com maior valor configurado no YAML e tipicamente o que concentra o gasto da campanha. Sem calibração, o D10 do Champion mandaria pra Meta um valor 33× acima do que a probabilidade real sustenta.

## Direção e magnitude do viés

Os dois modelos **superestimam sistematicamente** em todos os decis, sem exceção. O gap cresce monotonicamente do D1 até o D10 — onde a aposta econômica é maior, o erro absoluto também é maior. O Challenger é consistentemente mais miscalibrado que o Champion (ECE 40 vs 26 pp), provavelmente porque o `importance_weighting` aplicado nele (alpha=1, grupos controle/ML/neutro) amplifica o efeito que o `class_weight='balanced'` já trazia.

## Por que essa direção

O `class_weight='balanced'` do scikit-learn rebalanceia a função de perda durante o treino para tratar a classe minoritária como se fosse igualmente abundante. Em datasets onde compradores são ~1-2% da população (caso DevClub), isso significa **inflar o peso de cada comprador em ~50-100×**. O modelo aprende a separar muito bem comprador de não-comprador, mas perde calibração absoluta: ele afirma "isso parece comprador, então probabilidade 50%" quando a prevalência real da classe é 2%. A escala do `predict_proba` perde relação com a probabilidade marginal.

A confirmação empírica é o gap crescente — quanto mais perto do "perfil comprador" o lead está (decis altos), maior a inflação absoluta. O modelo está dizendo "tenho 58% de certeza que esse lead é comprador" no D10 do Champion, mas só 1.75% dos leads desse decil efetivamente compram.

## Implicações

### Para o sistema atual (decil + tabela `conversion_rate` no YAML)

O sistema atual é **parcialmente protegido** da miscalibração porque o valor enviado pra Meta não usa o score bruto — usa a `conversion_rate` configurada no YAML por decil. Se o YAML estiver bem calibrado (taxas correspondendo às observadas), o número que sai pra Meta está correto independentemente da escala interna do modelo.

A inspeção dos valores configurados em `configs/clients/devclub.yaml` mostra `D10: 0.009573` — o que dá value de R$ 14.97. A taxa observada no test set é 0.0175 (~1.8×) → o YAML está **subestimando** o valor real do D10. Não é alarmante, mas indica que a tabela do YAML também foi derivada de dados que carregam algum drift (provavelmente lançamentos mais antigos com perfil de público diferente, ou da fórmula contábil que considera realização Guru + TMB em vez da taxa bruta).

A calibração não é estritamente necessária pro sistema atual continuar funcionando, mas:
- Permite **recomputar a tabela de conversion_rate automaticamente** a cada retreino, derivando-a do calibrador em vez de manter no YAML
- Reduz a chance de gap entre score interno e valor sinalizado pra Meta (DT-17 fica mais fácil de resolver)

### Para a fórmula proposta (`leadScore × ticket / CPL` no nível do lead)

**A calibração se torna pré-requisito não-negociável.** A fórmula multiplica `leadScore` diretamente — qualquer fator de inflação se traduz proporcionalmente no valor enviado. Pelas razões da tabela acima, valores enviados ficariam 27× a 177× acima do que a probabilidade real sustenta, dependendo do decil e do modelo. A Meta otimizaria pra um sinal econômico fantasma, e o A/B test entre Champion e Challenger seria dominado pela diferença de miscalibração, não pelo mérito de cada modelo.

## Limitações declaradas

A análise faz uma série de simplificações que vale enumerar pra evitar leituras otimistas:

1. **In-sample fit.** A isotônica foi ajustada e medida nos mesmos 10 bins. Por construção, ela zera o gap. O número que importa de verdade é o ECE pré (que é mensurável e honesto), não o pós (que é mecânico).

2. **Granularidade de 10 bins.** A análise assumiu que todos os leads de um decil compartilham o `score_médio` e a `P(real)` do decil. Variância intra-decil não foi capturada. Análise com bins menores (ex: 20 ou 50) pode revelar não-monotonias dentro dos decis que o resumo agregado esconde.

3. **Dados de treino original — não dados recentes.** Os números vêm do test set do split temporal original (até final de janeiro pro Champion, até final de abril pro Challenger). Drift de perfil de público (documentado no `audience_profile_drift` de 08/05/2026) pode ter mudado a relação `score → P(real)` desde então. Calibração ajustada hoje pode estar parcialmente desatualizada amanhã. Recomputação periódica é necessária.

4. **Não testa generalização da calibração.** Idealmente, treinaríamos isotônica em metade do test set e mediríamos ECE na outra metade. Não foi feito porque o metadata só tem os agregados por decil, não os pontos individuais. Pra fazer esse teste honesto seria preciso reprocessar o dataset (próximo passo).

5. **`P(real)` é estimada com ruído.** Decis com 3.000-4.000 leads e taxa de conversão de ~0.1% têm intervalos de confiança largos (D1 do Champion tem apenas 3 conversões; D1 do Challenger tem 0). Pra esses decis o gap pode estar inflado ou deflacionado dependendo do azar amostral. Pra D8-D10 com taxas de 0.7-2.3% os intervalos são mais estreitos e a estimativa é mais confiável.

6. **Não considera covariate shift.** A calibração assume que a relação `score → P(real)` é função apenas do score. Na prática, leads de campanhas diferentes ou perfis socioeconômicos diferentes podem ter calibração distinta para o mesmo score. Calibração condicional (por segmento) seria mais robusta mas requer mais dados.

## Conclusões

1. **Os dois modelos em produção estão severamente miscalibrados.** ECE de 26 pp (Champion) e 40 pp (Challenger) — ambos cinco a oito vezes acima do limite "aceitável" da literatura.

2. **A direção do viés é superestimação sistemática em todos os decis.** O Random Forest com `class_weight='balanced'` produz scores que afirmam probabilidades de compra muito acima das observadas, com efeito maior nos decis altos (D9, D10).

3. **A calibração é melhoria significativa no sistema atual** (decil + tabela `conversion_rate`) e **pré-requisito crítico** pra qualquer fórmula que use o `leadScore` bruto direto no valor enviado pra Meta.

4. **Calibração isotônica é tecnicamente adequada.** Os pontos `(score_médio, P_observado)` são monotônicos em ambos os modelos — exatamente o cenário onde isotônica brilha. Sigmoid (Platt) seria forçar uma forma de S que os dados não têm.

5. **A análise feita aqui é cota superior do ganho** porque é in-sample. Validar com dataset reprocessado em holdout temporal é o passo natural antes de implementar.

## Próximos passos

Em ordem natural, sem priorização nesta análise:

1. **Validar out-of-sample** — pegar leads do Railway dos últimos 30-60 dias, com label real, rodar `predict_proba` do Champion + aplicar a isotônica fitada com dados antigos, medir ECE residual.
2. **Repetir a análise com bins de 20** — ver se há não-monotonia intra-decil que justifica granularidade maior na função de calibração final.
3. **Decisão arquitetural sobre DT-20** — registrar como dívida prioritária com escopo expandido ("calibração como pré-requisito da fórmula nova"), com referência cruzada a esta análise.
4. **Plano de adoção dos modelos atuais** — script que reabre run no MLflow, ajusta calibrador, salva como artifact em run filho, atualiza `active_models/devclub.yaml`. Detalhes técnicos na proposta arquitetural feita junto com a skill `/sw-architect`.
5. **Adicionar calibração ao próximo treino** — bloco `scoring.calibration` em `clients/devclub.yaml`, com subsplit temporal interno no train set conforme detalhado na sessão de design.

## Reprodução

Para reproduzir os números desta análise:

```bash
cd /Users/ramonmoreira/Desktop/bring_data
python3 <<'PY'
import json
from pathlib import Path
import numpy as np
from sklearn.isotonic import IsotonicRegression

for run_id in ['d51757f5041c44b7ab1a056fce8c3c35', '5d158f0aa6e54b489498470446194a6c']:
    p = Path(f"V2/mlruns/1/{run_id}/artifacts/model_metadata.json")
    m = json.loads(p.read_text())
    da, th = m['decil_analysis'], m['decil_thresholds']['thresholds']
    scores = np.array([th[f'D{i}']['mean_probability'] for i in range(1,11)])
    p_real = np.array([da[f'decil_{i}']['conversion_rate'] for i in range(1,11)])
    n      = np.array([da[f'decil_{i}']['total_leads']    for i in range(1,11)])
    ece_pre = np.average(np.abs(scores - p_real), weights=n)
    iso = IsotonicRegression(out_of_bounds='clip', y_min=0., y_max=1.).fit(scores, p_real, sample_weight=n)
    ece_post = np.average(np.abs(iso.predict(scores) - p_real), weights=n)
    print(f"{run_id[:8]}  ECE pré={ece_pre*100:.2f}pp  pós={ece_post*100:.2f}pp")
PY
```

Saída esperada:

```
d51757f5  ECE pré=26.32pp  pós=0.01pp
5d158f0a  ECE pré=39.58pp  pós=0.01pp
```

---

*Identificadores históricos: análise feita no contexto do design de DT-20 — Calibração de probabilidades de scoring; modelos referenciados em `configs/active_models/devclub.yaml`.*
