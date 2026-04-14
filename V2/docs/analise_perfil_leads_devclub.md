# Análise DevClub — Mudança no perfil dos leads de P1 a P3

> Última atualização: 14/04/2026

---

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

O modelo jan30 foi restaurado e o código corrigido. Mas o Meta ainda estava otimizando com o aprendizado das semanas anteriores — e o perfil dos leads reflete isso.

Comparando quem chegava em P1 com quem chega em P3 (61 mil leads, diferenças todas estatisticamente significativas):

| Característica | P1 | P3 | Diferença |
|---|---|---|---|
| Tem computador | 88.5% | 79.5% | **−9.0pp** |
| Tem cartão de crédito | 43.5% | 38.1% | −5.4pp |
| Sem renda | 25.1% | 30.0% | +4.9pp |

A lógica é direta: o produto custa R$2.200 e é um curso de programação. Um lead sem computador e sem cartão está estruturalmente fora do perfil comprador — independentemente de qualquer outra variável.

Além disso, o volume passou a ser dominado pelo segmento genérico de broad targeting, que em P3 performa em 28.9% D10 contra 43.2% que performava em P1 com o mesmo tipo de campanha — reflexo direto da mudança no sinal de otimização.

---

## O que isso significa

O código e o modelo estão corretos. O D10% de ~30% que observamos desde o rollback é o resultado esperado para o perfil de lead que está chegando — o modelo está funcionando.

Para voltar ao patamar de P1, as duas alavancas são:

**Sinal de otimização:** retornar ao LQHQ ou garantir que o Meta volte a aprender a partir de um sinal de topo. O reset de pixel pode acelerar esse processo.

**Mix de criativos:** em P3 existem criativos com boa performance (48–52% D10) mas com volume muito pequeno — a maior parte do orçamento está concentrada no segmento broad que deteriorou. Redistribuir verba para os criativos que já estão entregando pode recuperar parte da qualidade sem depender só do reset.
