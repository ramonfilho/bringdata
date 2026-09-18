# Experimento — Moat do modelo RF vs baselines de "gestor de tráfego"

**Data:** 2026-04-24
**Código:** `src/experiments/rules_vs_rf.py`
**Pergunta:** quanto do valor do Champion v4 RF pode ser reproduzido por um gestor de tráfego competente sem acesso ao modelo?

---

## Como rodar

```bash
cd /Users/ramonmoreira/Desktop/bring_data/V2

# 1. Gerar dataset encoded com datas (se não existir ou estiver stale)
python -m src.train_pipeline --save-encoded --use-cached-data --initial-matching email_telefone
# (produz V2/compare_encoded.parquet — pode matar o processo assim que o arquivo aparecer,
#  antes do RF treinar, que é a parte cara)

# 2. Rodar o experimento (~5 min, majoritariamente o RF)
python -m src.experiments.rules_vs_rf --cut-date 2026-03-01 --mlflow-log --out /tmp/rules_vs_rf.csv
```

Split temporal com `--cut-date 2026-03-01` replica o Champion v4. Resultados ficam na experiment MLflow `baselines_vs_champion_v4` e no CSV de saída.

---

## O que está sendo comparado

Quatro baselines em complexidade crescente + referência Champion v4 RF, todos treinados no mesmo split temporal (192.448 leads, 133.795 treino / 58.653 teste, cut_date=2026-03-01):

| Baseline | Representa | Requer acesso ao RF? |
|---|---|---|
| `napkin_rules` | Gestor chutando pesos em top-5 features | Sim (precisa saber o top-5) |
| `importance_weighted` | Gestor com importance values do RF como pesos | Sim |
| `shallow_tree` | DecisionTree `max_depth=3` — regras automáticas | Não |
| `conversion_rate_score` | Gestor calculando `P(buy \| feature=1) - base_rate` por categoria | **Não** |
| `champion_v4_rf` | RandomForest 300 árvores com hiperparâmetros do Champion v4 | — (referência) |

---

## Resultados — corrida 2026-04-24

### Tabela principal (test set temporal)

| Modelo | AUC | AUC-PR | D10 conc% | D10 lift | top3% | top5% | Monotonia | unique_scores |
|---|---|---|---|---|---|---|---|---|
| napkin_rules | 0.6905 | 0.0151 | 29.74 | 2.41 | 62.78 | 89.21 | 71.43 | 10 |
| importance_weighted | 0.6705 | 0.0147 | 29.74 | 2.41 | 47.36 | 80.18 | 66.67 | 33 |
| shallow_tree | 0.6751 | 0.0142 | 0.00* | 0.00* | 83.92 | 98.24 | 40.00 | 8 |
| **conversion_rate_score** | **0.7221** | **0.0188** | 28.63 | 2.86 | 63.00 | 80.18 | 77.78 | 19.123 |
| **champion_v4_rf** | **0.7412** | **0.0252** | **34.58** | **3.46** | 62.56 | 83.04 | 77.78 | 53.750 |

*D10=0 do shallow_tree é artefato de `pd.qcut` com 8 scores distintos — não indica modelo zerado, e sim que a atribuição de decis colapsa com poucos empates.

### Ablação do RF — contribuição de cada camada do pipeline

| Subset de features | n_features | AUC | AUC-PR | D10 lift | Monotonia |
|---|---|---|---|---|---|
| `survey_only` (respostas da pesquisa) | 33 | 0.7426 | 0.0260 | 3.45 | 88.89% |
| `survey_plus_engineered` (+ nome_comprimento, _valido, dia_semana) | 46 | **0.7437** | 0.0256 | **3.52** | **100.00%** |
| `survey_plus_utm` (+ Source/Medium/Term OHE) | 47 | 0.7402 | 0.0262 | 3.49 | 100.00% |
| `all_features` (Champion v4 atual) | 60 | 0.7412 | 0.0252 | 3.46 | 77.78% |

---

## Descobertas

### 1. `conversion_rate_score` (sem RF) chega a 97% da AUC do RF

Um gestor calculando `P(buy | feature=1) - base_rate` por categoria OHE e somando como score aditivo atinge AUC 0.7221 — gap de apenas 2pp para o RF. Em D10 lift (2.86 vs 3.46) captura 83% do valor.

**Detalhe**: as features que o `conversion_rate_score` identifica como mais fortes **não batem** com o top-5 do RF. Taxa de conversão bruta favorece categorias com rate alto e volume baixo (Source_youtube, Source_outros); o RF balanceia separação × volume via bootstrap. Caminhos diferentes, AUC similar.

### 2. Survey unification carrega 99% da AUC do modelo

RF apenas com as 33 features de pesquisa atinge AUC 0.7426 — praticamente idêntico às 60 features (0.7412). A camada de `core/category_unification.py` (normalização de respostas de survey) é a que paga o aluguel do modelo.

### 3. UTM normalization está diluindo o sinal

`survey_plus_utm` (AUC 0.7402) < `survey_only` (AUC 0.7426). As 14 features OHE de UTM adicionam ruído sem contrapartida preditiva no dataset atual. Implicação: **todo o esforço em `core/utm.py` e `core/medium.py` não está melhorando AUC**. UTM pode continuar relevante para atribuição e segmentação downstream, mas não para scoring.

### 4. Feature engineering fecha a monotonia

`survey_plus_engineered` (46 features) tem 100% de monotonia de decis, vs 77.8% do Champion v4 atual (60 features) — ganho relevante para a calibração CAPI. Sugere que **retirar UTM do modelo de scoring pode melhorar monotonia e D10 lift simultaneamente**.

### 5. Unique scores expõem o problema de calibração de regras

- RF: 53.750 scores distintos → decis balanceáveis
- `conversion_rate_score`: 19.123 → decis razoáveis
- Regras (napkin, importance_weighted): 10-33 → decis colapsam, Meta CAPI recebe valor quebrado
- Shallow tree: 8 → decis inviáveis

Mesmo que a AUC das regras seja competitiva, a **calibração de decis** (proporcionalidade valor × qualidade) só é possível com modelo contínuo.

---

## Implicações para o moat do produto

### Decomposição do moat

| Camada | Contribuição ao gap total "gestor vs produto" |
|---|---|
| **Matching multi-source + dedup + janela temporal** (`core/matching.py`) | ~100% — sem target válido, nenhum modelo existe |
| **Survey unification** (`core/category_unification.py`) | 99% da AUC do modelo |
| **Feature engineering** (nome_comprimento, _valido, dia_semana) | +0.001 AUC, +11pp monotonia |
| **UTM normalization** (`core/utm.py`, `core/medium.py`) | −0.0024 AUC (negativo) |
| **Algoritmo RF vs regras** (com target e features idênticos) | ~30% em D10 lift |

### Estimativa consolidada

- **Gap mínimo** (gestor com matching e features idênticos ao produto, só não tem RF): **~30% em D10 lift**
- **Gap real** (gestor em Excel com matching limitado a uma fonte e survey não-normalizado): **~50-60%**
- **Gap projetado** (após implementar features do backlog — User Agent, Similar_leads, LTV, Lead_score_anteriores, Interação página): **~70-80%**, porque essas features são **flywheel-exclusive** — só existem se o sistema já estiver rodando

### Hipótese de melhoria de modelo identificada

Deploy do Champion v4 com feature set `survey_plus_engineered` (46 features, sem UTM) em vez de `all_features` (60). Ganho esperado: +11pp em monotonia de decis, +0.06 em D10 lift, AUC praticamente igual. Requer retreino + parity audit + canary. Fora do escopo deste experimento.

---

## Limitações conhecidas

1. **`shallow_tree` D10=0 é artefato de atribuição**, não do modelo. Com 8 scores distintos, `pd.qcut(q=10)` colapsa bins. Fix futuro: cortar por rank/N em vez de qcut. Não muda a conclusão geral.
2. **`importance_weighted` com pesos negativos introduz inversões** — features OHE com peso negativo (ex: `cartao_credito_nao = -0.15`) confundem a soma quando combinadas com o par positivo. Transpor feature_importance para pesos lineares não é trivial; é resultado informativo, não bug.
3. **Experimento pressupõe target válido**. A qualidade do matching é assumida. Para medir o moat completo seria preciso re-rodar com matching degradado (ex: só email, sem fuzzy, sem cross-source) e observar a degradação da AUC. Sugestão de extensão futura.

---

## Commits

- `87058c9` — `safeguard(T1-1): raise em vez de warning — fail-loud estrito`
- `<este commit>` — `feat(experiments): rules_vs_rf — moat do RF e decomposição do pipeline`
