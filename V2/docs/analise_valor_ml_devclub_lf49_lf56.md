# Valor do ML — DevClub, LF49 a LF56 (continuação do estudo)

**Data:** 17/06/2026
**Período analisado:** LF49 (vendas 30/03) → LF56 (vendas 08–14/06)
**Escopo:** LF49, LF50, LF52, LF54, LF55, LF56
**Excluídos:** LF51 (boleto de R$661k anômalo, pendente de verificação no dashboard) e LF53 (vendas infladas por upsell/segundo produto — outlier declarado no `launches.yaml`)

Este documento estende o `analise_valor_ml_devclub.md` (que cobriu LF40–LF48). A diferença central de método: aqui **o gasto e o faturamento são ancorados nas fontes canônicas do cliente** — gasto do **gerenciador Meta** e faturamento do **dashboard** — e não na receita interna do pipeline de validação, que mostrou divergências por lançamento (ora sub, ora superestima as vendas).

---

## 1. Fontes e as duas bases de receita

| Insumo | Fonte canônica |
|---|---|
| Gasto por lançamento | Gerenciador de anúncios Meta (conta DevClub) |
| Faturamento por lançamento | Dashboard do cliente, separado em Cartão e Boleto |
| Contagem de leads | Tabela "all-leads" do Railway (`Lead` pré-17/05, `Client` pós-17/05) — confere com o dashboard |
| Split por grupo (Champion/Challenger/Controle) | Pipeline de validação (única fonte que separa por grupo) |

O dashboard dá o faturamento em duas leituras, e o estudo reporta **as duas lado a lado**:

- **Contratado** = Cartão + Boleto (valor cheio de todas as vendas). É a base do estudo original (LF40–48) e do material comercial.
- **Recebido (caixa)** = Cartão (à vista) + 1ª parcela do boleto (boleto ÷ 12). É o caixa efetivamente entrado na semana.

> A base recebida foi validada por cruzamento: a receita recebida calculada do dashboard bate com a "Receita Total (Real)" do pipeline em todos os 8 lançamentos (diferença de 0,1–0,3 no ROAS). Isso confirma que o dashboard = base contratada e que o pipeline passou a reportar a base recebida (relatórios regerados em 12/05/2026).

---

## 2. ROAS canônico por lançamento (duas bases)

| LF | Gasto (gerenciador) | Contratado (C+B) | **ROAS contr.** | Recebido (C+B/12) | **ROAS receb.** |
|---|---|---|---|---|---|
| LF49 | R$74.610 | R$394.515 | **5,29** | R$129.992 | 1,74 |
| LF50 | R$54.655 | R$382.515 | **7,00** | R$97.021 | 1,78 |
| LF52 | R$50.606 | R$408.920 | **8,08** | R$109.067 | 2,16 |
| LF54 | R$39.157 | R$126.074 | **3,22** | R$44.189 | 1,13 |
| LF55 | R$31.667 | R$171.620 | **5,42** | R$68.263 | 2,16 |
| LF56 | R$41.830 | R$197.630 | **4,72** | R$100.066 | 2,39 |
| **Total / médio** | **R$292.525** | **R$1.681.274** | **5,75** | **R$548.598** | **1,88** |

---

## 3. Resultado de ML — contrafactual vs baseline 1,91x (base contratada)

Os lançamentos recentes são quase 100% ML, então o contrafactual usa o **baseline histórico de 1,91x** — a mediana do ROAS Controle dos lançamentos limpos do estudo original (LF43=1,52x, LF44=2,30x), na base contratada.

**Contrafactual:** *"se todo o gasto tivesse rendido à eficiência do Controle (ROAS 1,91x), qual seria o faturamento?"*

`Faturamento_CF = Gasto × 1,91` · `Ganho = Faturamento_Contratado − Faturamento_CF`

| LF | Gasto | Faturamento contratado | Faturamento CF (1,91×) | **Ganho** |
|---|---|---|---|---|
| LF49 | R$74.610 | R$394.515 | R$142.505 | **+R$252.010** |
| LF50 | R$54.655 | R$382.515 | R$104.391 | **+R$278.124** |
| LF52 | R$50.606 | R$408.920 | R$96.658 | **+R$312.262** |
| LF54 | R$39.157 | R$126.074 | R$74.789 | **+R$51.285** |
| LF55 | R$31.667 | R$171.620 | R$60.484 | **+R$111.136** |
| LF56 | R$41.830 | R$197.630 | R$79.896 | **+R$117.734** |
| **Total** | **R$292.525** | **R$1.681.274** | **R$558.723** | **+R$1.122.551** |

**Ganho estimado na base contratada: +R$1,12 milhão em 6 lançamentos.**

---

## 4. Ressalva crítica — o ganho é sensível à base

O ROAS médio na **base recebida (caixa) é 1,88x — praticamente igual ao próprio baseline de 1,91x.**

Isso significa que **o ganho de R$1,12M existe na base contratada, mas quase desaparece na base caixa**: medido pelo dinheiro efetivamente entrado, os lançamentos rodam perto da eficiência-baseline, não muito acima. A diferença entre as duas leituras é o boleto — a base contratada conta o valor cheio de 12 parcelas que em boa parte não serão pagas.

Interpretação honesta:
- **Se o baseline 1,91x é uma referência contratada** (e é — veio de ROAS Controle contratado do LF43/44), então comparar contratado-com-contratado é correto e o ganho de R$1,12M é válido **sob a premissa de que o baseline antigo ainda vale**.
- **Mas o baseline vem de só 2 lançamentos** (LF43/44) e de jan–fev/2026. É a maior fragilidade do número.
- **Na leitura de caixa**, o incremental vs baseline é próximo de zero — esse é o piso conservador.

---

## 5. A/B real — onde voltou a haver Controle

A campanha de Controle (captação Meta **sem nenhuma tag de ML** no nome — otimiza "Lead" genérico, não usa o sinal do modelo) reapareceu nos lançamentos recentes. A distinção é feita pela **tag de optimization-goal embutida na `utm_campaign`**, lida localmente (`campaign_classifier`): `LEADQUALIFIED`/`MACHINE LEARNING` → Champion (modelo de produção); `LEADHQLB`/`HQLB` → Challenger (modelo A/B); sem tag → Controle. Mesma lógica no monitoramento (`bucket_from_utm`) e na validação (`classify_variant`).

Onde há Controle, dá pra medir o incremental direto (base recebida do pipeline — única que separa por grupo):

| LF | ROAS ML (Champion+Challenger) | ROAS Controle | N Controle | Ganho A/B | Leitura |
|---|---|---|---|---|---|
| **LF56** | 1,83 | 0,74 | 14 | **+R$25.055** | **A/B mais limpo: 45% do budget em Controle, ML ganha com folga** |
| LF54 | 0,61 | 0,79 | 10 | −R$8.374 | Inconclusivo (N=10, lançamento fraco, gasto do pipeline não reconcilia com gerenciador) |
| LF55 | — | sem Controle | — | — | Sem A/B no período |

**O único A/B recente com massa razoável (LF56) confirma o ML batendo o Controle de forma clara** (ROAS 1,83 vs 0,74). O LF54 vai na direção contrária mas é estatisticamente inconclusivo e foi um lançamento ruim no geral.

---

## 6. Conclusão

| Leitura | ROAS médio | Resultado de ML |
|---|---|---|
| **Base contratada** vs baseline 1,91x | 5,75x | **+R$1,12M** em 6 lançamentos |
| **Base recebida (caixa)** | 1,88x | ≈ baseline → incremental próximo de zero |
| **A/B real (LF56)** | ML 1,83 vs Ctrl 0,74 | ML vence com folga (+R$25k no período) |

O número defensável depende da base e do baseline:
- O **teto** é +R$1,12M (base contratada, premissa de baseline 1,91x válido).
- O **piso** é ≈ R$0 incremental (base caixa rodando no nível do baseline).
- A **evidência causal mais forte** é o A/B do LF56, que mostra o ML batendo o Controle limpo — mas é um único lançamento.

**Recomendação:** reportar o intervalo, não um número único. A força do caso está menos no valor absoluto (sensível demais à base de receita e ao baseline antigo) e mais no **A/B do LF56**, que é a evidência mais limpa de que o ML supera a otimização sem ML. Para fortalecer, manter o grupo de Controle ativo nos próximos lançamentos e acumular N suficiente para um incremental estatisticamente conclusivo na base de caixa.

---

## 7. Limitações

1. **Baseline antigo:** 1,91x vem de 2 lançamentos (LF43/44, jan–fev/2026); pode não refletir a eficiência de captação atual.
2. **Split por grupo só na base recebida:** o dashboard não separa faturamento por Champion/Challenger/Controle, então o A/B só pode ser medido na base de caixa do pipeline.
3. **Gasto do pipeline ≠ gerenciador em LF54** (API R$59k vs gerenciador R$39k, +51%) — por isso o gasto canônico é o do gerenciador; mas o split por grupo do LF54 herda o gasto do pipeline e fica menos confiável.
4. **LF51 e LF53 fora:** LF51 com boleto anômalo (R$661k) a verificar; LF53 com upsell.
5. **Faturamento contratado superestima caixa:** boleto conta 12 parcelas cheias; realização real é menor.

---

*Insumos: gasto do gerenciador Meta e faturamento do dashboard (cartão/boleto) fornecidos manualmente em 17/06/2026; split por grupo dos relatórios de validação `outputs/validation/`; baseline herdado de `analise_valor_ml_devclub.md`.*
