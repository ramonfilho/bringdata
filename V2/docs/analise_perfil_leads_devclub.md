# Análise DevClub — Mudança no perfil dos leads de P1 a P3

> Última atualização: 14/04/2026

---
3 Períodos (P1, P2 e P3)

## P1 — 18/02 a 09/03

As campanhas entregavam um perfil consistente de lead com capacidade de compra. O modelo classificava em torno de **41–44% dos leads como D10** ao longo de todo o período, com estabilidade diária:

| Data | D10% |
|---|---|
| 03/03 | 42.2% |
| 04/03 | 40.8% |
| 05/03 | 42.0% |
| 06/03 | 44.0% |
| 07/03 | 43.8% |
| 08/03 | 41.5% |
| 09/03 | 42.5% |

---

## A virada — 10 a 14/03

Em 12/03 o D10 caiu 10 pontos percentuais em um único dia, sem nenhuma mudança de código ou modelo. O que aconteceu foi uma mudança no evento de otimização das campanhas: de **LQHQ** (enviado apenas para leads de topo, D9–D10) para **LQ** (enviado para todos os decis com valor proporcional).

O Meta interpreta os eventos que recebe como exemplos do perfil que deve buscar. Com LQHQ, o algoritmo estava calibrado para buscar leads de alta propensão. Com LQ, passou a receber sinal de todos os decis — e naturalmente foi otimizando para um público mais amplo.

| Data | D10% |
|---|---|
| 10/03 | 41.0% |
| 11/03 | 41.5% |
| **12/03** | **31.8%** ← queda |
| 13/03 | 30.3% |
| 14/03 | 28.1% |

---

## P2 — 15 a 25/03

Sobre a queda de audiência, veio uma mudança de modelo que agravou o problema. O D10 colapsou para menos de 10%:

| Data | D10% |
|---|---|
| **15/03** | **19.7%** ← mudança de modelo |
| 16/03 | 5.4% |
| 17/03 | 7.3% |
| 18/03 | 6.1% |
| 19/03 | 6.2% |
| 20/03 | 4.2% |
| 21/03 | 3.1% |
| 22/03 | 1.8% |

---

## P3 — 26/03 em diante

O modelo jan30 foi restaurado. Mas o Meta ainda estava otimizando com o aprendizado das semanas anteriores — e o perfil dos leads reflete isso.

Comparando quem chegava em P1 com quem chega em P3 (61 mil leads, diferenças todas estatisticamente significativas):

| Característica | P1 | P3 | Diferença |
|---|---|---|---|
| Tem computador | 88.5% | 79.5% | **−9.0pp** |
| Tem cartão de crédito | 43.5% | 38.1% | −5.4pp |
| Sem renda | 25.1% | 30.0% | +4.9pp |

---

## O que isso significa

O código e o modelo estão corretos. O D10% de ~30% que observamos desde o rollback é o resultado esperado para o perfil de lead que está chegando — o modelo está funcionando.

Para voltar ao patamar de P1, as duas alavancas são:

**Código e modelo:** o rollback corrigiu um bug de encoding que afetava a feature `Medium_Linguagem_programacao` — a 5ª variável mais importante do modelo (5,31% de peso). O bug zerrava silenciosamente essa coluna para todos os leads, reduzindo a precisão do modelo especificamente nos segmentos de campanha de linguagem de programação. O impacto foi localizado: os 94,69% restantes do peso do modelo operavam normalmente. Após a correção, o D10% estabilizou em ~30% — confirmando que o problema principal não é técnico, mas de audiência.

**Sinal de otimização:** para voltar ao patamar de P1, o Meta precisa reaprender a buscar o perfil correto. O sinal que está sendo enviado agora é idêntico ao de P1 — o modelo correto, pontuando corretamente. Com isso, podemos esperar que o Meta vá convergindo gradualmente, buscando cada vez mais leads com o perfil de P1 e elevando o D10% ao longo do tempo.

O reset de pixel pode ser um fator determinante nesse processo, limpando o aprendizado contaminado do período anterior e acelerando a convergência.

**Mix de criativos:** a análise por criativo revela um padrão consistente com a degradação de audiência. Os mesmos criativos que performavam bem em P1 apresentam queda expressiva de D10% em P3 — não porque os criativos mudaram, mas porque o Meta passou a entregá-los para um público diferente.

| Criativo | Vol% P1 | D10% P1 | Vol% P3 | D10% P3 | Δ D10 |
|---|---|---|---|---|---|
| AD0150 | 55,4% | 42,3% | 31,7% | 34,7% | −7,6pp |
| AD0156 | 12,3% | 48,0% | 8,0% | 40,2% | −7,8pp |
| AD0160 | 10,3% | 47,0% | 15,9% | 27,7% | **−19,3pp** |
| AD0141 | 8,0% | 39,8% | **22,7%** | **18,7%** | **−21,1pp** |
| AD0027 | 6,7% | 12,8% | 5,7% | 19,7% | +6,9pp |
| AD0170 | 0,5% | 55,8% | — | — | saiu |
| AD0172 | 0,4% | 51,8% | — | — | saiu |
| AD0157 | 0,6% | 48,6% | — | — | saiu |
| AD0151 | — | — | 1,4% | 52,8% | novo |
| AD0152 | — | — | 1,6% | 47,0% | novo |
| AD0138 | — | — | 5,1% | 43,7% | novo |

Os dois movimentos mais relevantes: AD0141 triplicou sua participação de volume (8% → 23%) enquanto o D10% colapsou de 40% para 19%; AD0160 manteve volume alto mas viu o D10% cair de 47% para 28%. Os criativos de nicho que lideravam em P1 (AD0170, AD0172, AD0157 — todos acima de 48% D10) saíram completamente do mix ativo.

Em P3 surgem dois criativos com performance alta — AD0151 (53% D10) e AD0152 (47% D10) — mas com menos de 2% de volume cada. Concentrar verba nesses criativos combinado com o reset do pixel são a melhor alavanca disponível: o reset limpa o aprendizado contaminado e os criativos corretos entregam o sinal certo desde o primeiro dia do novo ciclo.
