# Teste A/B Champion vs Challenger — DEV20

**Data:** 28/04/2026
**Lançamento:** DEV20 (captação 21/04 → 04/05, vendas 11/05 → 17/05)
**Decisão a tomar:** promover ou não o modelo Challenger a Champion principal de produção

- **Champion (A) = jan30** — modelo em produção desde 30/01/2026
- **Challenger (B) = abr28** — candidato treinado em 28/04/2026

---

## Sumário executivo

O Champion A entrega ROAS médio de **5,3×** ao longo de 7 lançamentos consecutivos (LF45–LF51).

O Challenger B foi treinado com dataset 1,8× maior (201 mil leads vs 110 mil). Em testes offline sobre 186 vendas reais (LF51, LF52, LF53), **B separa compradores de não-compradores cerca de 2,7× melhor** que A no decil mais alto.

Antes de promover B a Champion, é necessário validar em produção real. Propomos teste A/B no DEV20 com **R$ 72k (35% do orçamento restante)** alocado numa campanha B, mantendo as campanhas A com os R$ 133k restantes.

Leitura final: **22–25/05/2026** após carrinho fechar e parcelas TMB efetivarem.

---

## 1. Por que considerar substituir o Champion A

### O que A entrega hoje

| Lançamento | ROAS | Top‑3 decis (D8+D9+D10) capturam |
|---|---|---|
| LF45 | 7,70× | 75% das vendas |
| LF46 | 5,73× | 77% das vendas |
| LF47 | 5,75× | 73% das vendas |
| LF48 | 3,63× | 67% das vendas |
| LF49 | 5,39× | 38% (anomalia documentada) |
| LF50 | 5,06× | 69% das vendas |
| LF51 | 3,85× | 61% das vendas |
| **Média** | **5,3×** | **66% das vendas** |

Os 30% de leads classificados nos top 3 decis pelo Champion A capturam, em média, 66% das vendas do lançamento.

### Por que reavaliar

1. **Saturação no decil mais alto.** A hoje classifica ~33% dos leads como D10 (esperado pela calibração do treino: 10%).
2. **Treino defasado.** A foi treinado com dados até novembro de 2025 — não viu nenhum lançamento de 2026.
3. **Volume de dados disponíveis cresceu.** Dataset disponível hoje é quase 2× maior que o usado no treino de A.

### O que B traz de diferente

| Característica | Champion A (jan30) | Challenger B (abr28) |
|---|---|---|
| Data de treino | 30/01/2026 | 28/04/2026 |
| Total de leads no dataset | 110.505 | 201.547 |
| Janela temporal coberta | mar/2025 → nov/2025 | fev/2025 → abr/2026 |
| Fontes de venda | Guru | Guru + Hotmart |
| Fontes de lead | Sheets | Sheets + Railway |
| Correção de feedback loop | Não | Sim (importance weighting do grupo controle) |

---

## 2. Performance comparativa em testes offline

Avaliamos os dois modelos nos lançamentos LF51 (parcial), LF52 e LF53 — período em que **nenhum dos dois** havia visto os leads no treino. Total: **186 vendas reais matched**.

### Quanto leads dos top decis convertem acima da média do lançamento

| | Challenger B | Champion A |
|---|---|---|
| Lead D10 → converte X% acima da média | **+102%** | +40% |
| Lead D9 → converte X% acima da média | **+41%** | +18% |
| Lead D9+D10 (top 20%) → converte X% acima da média | **+72%** | +33% |

Quando B classifica um lead como D10, esse grupo converte 102% acima da média do lançamento. Quando A classifica o mesmo, o grupo converte 40% acima.

### ROAS observado offline (top decis)

| | Challenger B | Champion A |
|---|---|---|
| ROAS dos top 30% leads (top 3 decis) | 2,29× | 1,84× |
| ROAS dos top 50% leads (top 5 decis) | 2,00× | 1,74× |
| ROAS de toda a base (controle) | 1,50× | 1,50× |

ROAS de toda a base é igual (mesmo dataset). A diferença aparece quando filtramos por decis altos.

---

## 3. Validação técnica do pipeline

A produção hoje roda numa versão antiga do código (commit "rollback" de 05/03/2026). Para servir B em produção, precisamos voltar a usar a versão atual do código.

Pegamos 5.000 leads reais e rodamos o Champion A em ambas as versões do código. Resultados:

| Métrica | Resultado |
|---|---|
| Score idêntico nas duas versões (diferença <0,001) | **96% dos leads** |
| Mesmo decil atribuído pelas duas versões | **98,3% dos leads** |
| Mesma decisão "esse lead recebe sinal premium ao Meta?" | **99,8% dos leads** |

Em 100 leads, ~98 receberiam exatamente o mesmo decil em ambas as versões. Os ~2 restantes ficariam deslocados em ±1 decil. Magnitude pequena, sem impacto material no ROAS agregado.

---

## 4. Como o teste vai funcionar

```
[Lead chega ao formulário do site DevClub]
              ↓
[API recebe lead com sua UTM]
              ↓
        UTM contém "HQLB"?
        ↙              ↘
      NÃO              SIM
        ↓                ↓
   Modelo A          Modelo B
   (Champion)        (Challenger)
        ↓                ↓
   Dispara CAPI:     Dispara CAPI:
   LeadQualified     evento HQLB
   HighQuality
```

Cada modelo emite seu próprio evento ao Meta. Cada campanha do gestor é configurada para otimizar pelo seu evento correspondente. Vendas reais são medidas externamente (via plataformas Hotmart/Guru/Asaas) — a métrica de ROAS por modelo é calculada por nós, não pelo Meta.

---

## 5. Investimento necessário

Para concluir com segurança que "B é melhor que A", precisamos observar um número mínimo de vendas atribuídas a cada modelo. Com pouco investimento em B, o sinal não consegue ser distinguido do ruído da amostra pequena.

| Cenário | % budget B | R$ B | Detecta diferença de... |
|---|---|---|---|
| Mínimo direcional | 15% | R$ 31k | apenas >40% (só sinais grandes) |
| Conservador | 25% | R$ 51k | >30% |
| **Moderado (recomendado)** | **35%** | **R$ 72k** | **>25%** |
| Equilibrado | 50% | R$ 102k | >18% |

**Recomendação: cenário moderado (R$ 72k em B).** Detecta diferenças de ROAS ≥25% — exatamente o range esperado dado os testes offline. A continua com R$ 133k (65% do orçamento) — ROAS atual protegido.

---

*Documento técnico-explicativo gerado em 28/04/2026.*
