# Fonte de Verdade por Lançamento (LF) — DevClub

**Data:** 17/06/2026
**Objetivo:** inventariar, para cada lançamento, **quais dados temos, de qual fonte, com qual metodologia/interpretação e com quais ressalvas** — para então padronizar uma fonte de verdade única e consistente em todos os LFs. Este documento é só de **procedência e consistência**; não contém conclusão de análise de retorno.

> ⚠️ Antes de usar qualquer número deste inventário num estudo, ler a **Seção 4 (problemas de consistência)** — vários dados não são comparáveis entre si sem ajuste.

---

## 1. Os eixos de dado e suas interpretações possíveis

Cada "número de um LF" pode significar coisas diferentes. Os eixos:

| Eixo | Variações que aparecem nos nossos dados |
|---|---|
| **Gasto** | (a) Meta **API** gravado no relatório de validação; (b) **gerenciador** Meta (canônico, puxado manualmente) |
| **Faturamento — base** | (a) **Contratado** = valor cheio da venda (cartão + boleto 12x); (b) **Recebido/à vista** = cartão + 1ª parcela do boleto (boleto÷12) |
| **Faturamento — cobertura** | (a) **Total** do lançamento (dashboard); (b) **Matched/rastreado** (só vendas vinculadas a um lead via email/telefone, ~tracking rate) |
| **Janela de vendas** | (a) **Semana de vendas** (carrinho aberto); (b) **60 dias** de matching (inclui comprador que virou lead em LF anterior) |
| **Leads** | (a) só **Meta**; (b) **all-leads** (todas as fontes); (c) só respondentes de pesquisa (`registros_ml`) |
| **Split por grupo** | Champion / Challenger / Controle — definido pela **tag na `utm_campaign`**, cuja convenção **mudou ao longo do tempo** (ver Seção 3) |

---

## 2. Fontes disponíveis hoje

| Fonte | O que fornece | Confiabilidade |
|---|---|---|
| **Dashboard do cliente** (manual) | Faturamento total por lançamento, separado cartão/boleto | ⭐ Canônico p/ faturamento |
| **Gerenciador Meta** (manual) | Gasto por lançamento (e por campanha, se exportado) | ⭐ Canônico p/ gasto |
| **Arquivos `outputs/validation/*.xlsx`** | Relatórios do pipeline: Performance Geral, Comparação ML, ML Monitoring, Detalhes das Conversões | ⚠️ Varia por data de geração e versão de código |
| **Aba "Detalhes das Conversões"** do relatório | Cada venda: valor (contratado), fonte, meio pgto, **grupo**, campanha | Base do split por grupo |
| **Banco Railway** (`Lead` ∪ `Client`) | Contagem all-leads por janela de captação | ⭐ Canônico p/ nº de leads |
| **Caches `files/validation/cache/*.parquet`** | Vendas (guru/asaas/hotmart/boletex) e leads (capi) por período | Reaproveitáveis (datas variam) |

---

## 3. As convenções de classificação de campanha mudaram ao longo do tempo ⚠️

**Esta é a maior fonte de inconsistência.** O grupo (Champion/Challenger/Controle) é derivado da tag no nome da campanha (`classify_variant`), mas a convenção de tag mudou em pelo menos 3 épocas:

| Época | "ML / Champion" | "Controle" | "Challenger" | Rótulos no relatório |
|---|---|---|---|---|
| **DEV19 e antes** (~jan/2026) | `MACHINE LEARNING` | `SCORE` / `ESCALA SCORE` / `FAIXA A` (otimiza por score, **sem** evento CAPI) | — | **"Eventos ML" / "Controle"** |
| **LF40–LF52** (~dez/25–abr/26) | `MACHINE LEARNING` | `ABERTO ADV+ \| SCORE` | *(a coluna "Challenger" do relatório = o controle SCORE, **não** um modelo A/B)* | "Champion / Challenger" |
| **LF54–LF56** (mai/26+) | `LEADQUALIFIED` | `LEAD` sem tag (Lead puro Meta) | `LEADHQLB` (**modelo A/B real**, abr28) | "Champion / Challenger / Controle" |

**Consequências:**
1. **"Challenger" significa coisas diferentes**: no LF44 = controle SCORE; no LF56 = modelo A/B. Não somar/comparar entre épocas sem traduzir.
2. **O "Controle" trocou de natureza**: de campanha `SCORE` (DEV19/LF40-48) para `LEAD` sem tag (LF54+).
3. **O classificador atual só reconhece a convenção moderna** (`LEADQUALIFIED`/`LEADHQLB`/`MACHINE LEARNING`). Tags antigas (`LQ`, `ML_MAR`, `LQC`, `HLQC`) **caem em "Controle" por engano** — ex.: no LF54, campanhas de ML de março/2025 (`ML_MAR`, `LQ`) foram classificadas como Controle, inflando o "controle".
4. **A janela de 60 dias mistura épocas**: um lançamento recente recebe compradores cujos leads vieram de campanhas antigas (convenção antiga) → classificação errada importada para dentro do lançamento novo.

---

## 4. Problemas de consistência identificados

1. **Duas bases de receita no mesmo arquivo**: o detalhe guarda **contratado**; o headline "Receita Total (Real)" guarda **recebido**. A extração ingênua mistura.
2. **Receita do pipeline ≠ dashboard, em duas direções**:
   - LF50/52 (e prováveis LF51/53): pipeline **subestima** — relatórios de **12/05 estão desatualizados** (vendas/boletos que entraram depois não foram capturados) e/ou excluem `Mentoria`/upsell.
   - LF54/55: pipeline **superestima** — janela 60d puxa comprador de outro lançamento (tracking real do negócio, mas não é a venda "daquela semana").
3. **Gasto API ≠ gerenciador em LF54** (API R$59k vs gerenciador R$39k, +51%). Nos demais bate (±0–10%).
4. **Heterogeneidade de data de geração**: DEV19 = 24/03 (esquema antigo "Eventos ML/Controle"); LF40–52 = 12/05; LF56 = 10/06; LF54/55 = 17/06. Versões de código diferentes → estruturas e classificações diferentes.
5. **Split por grupo só é confiável onde a tag é moderna e limpa** (LF56). Nos antigos é mistura de convenções (ver Seção 3).
6. **Vendas "NA"** (campanha vazia): parcela das vendas não tem campanha atribuída (ex.: LF44 22 vendas, DEV19 73) — nem ML nem controle.

---

## 5. Inventário por LF

Legenda fonte: **D** = dashboard (manual, canônico) · **G** = gerenciador Meta (manual, canônico) · **V** = arquivo `outputs/validation` · **DB** = query Railway (`Lead`∪`Client`) · **E** = estudo original `analise_valor_ml_devclub.md`.

| LF | Relatório V (data) | Leads (DB) | Gasto canônico (G) | Faturamento (D) | Split grupo no V | Época da tag | Ressalvas |
|---|---|---|---|---|---|---|---|
| LF40 | 12/05 | — | ❌ falta | ❌ falta | 4 / 7 / 0 | LF40-52 (SCORE=ctrl) | Outlier declarado (gasto baixo). E: ganho +R$1,3k (matched) |
| LF41 | 12/05 | — | ❌ | ❌ | 16 / 27 / 0 | idem | Outlier declarado. E: +R$3,1k |
| LF42 | 12/05 | — | ❌ | ❌ | 14 / 14 / 0 | idem | E: +R$19,4k (A/B) |
| DEV19 | **24/03** (esquema antigo) | — | ❌ | ❌ | "Eventos ML" 141 / "Controle" 197 | **DEV19 (SCORE/FAIXA A=ctrl)** | Rótulos diferentes; escala atípica. E: +R$146,6k |
| LF43 | 12/05 | — | ❌ | ❌ | 54 / 32 / 0 | LF40-52 | **Clean** no estudo. E: +R$90k |
| LF44 | 12/05 | — | ❌ | ❌ | 94 / 11 / 0 (+22 NA) | LF40-52 | **Clean**. "Challenger"(11)=ctrl SCORE. E: +R$119k |
| LF45 | 12/05 | — | ❌ | ❌ | 196 / 0 / 0 | LF40-52 | ML-only, baseline. E: +R$224k |
| LF46 | 12/05 | — | ❌ | ❌ | 72 / 0 / 0 | idem | ML-only. E: +R$35,5k |
| LF47 | 12/05 | — | ❌ | ❌ | 89 / 0 / 0 | idem | ML-only. E: +R$63k |
| LF48 | 12/05 | — | ❌ | ❌ | 66 / 3 / 0 | LF40-52 | ctrl insuficiente. E: +R$90,7k |
| LF49 | 12/05 | 16.685 | R$74.610 | C 105.944 + B 288.571 | 53 / 8 / 0 | LEGADA/mix | Detalhe(394.733) **bate** com D(394.515) |
| LF50 | 12/05 | 10.614 | R$54.655 | C 71.067 + B 311.448 | 37 / 4 / 0 | LEGADA/mix | Pipeline(239.836) **<** D(382.515): relatório 12/05 desatualizado |
| LF51 | 12/05 | 15.317 | R$64.093 | C 122.891 + B 661.169 | 57 / 9 / 0 | LEGADA/mix | **EXCLUÍDO** — boleto anômalo (R$661k), verificar no dashboard |
| LF52 | 12/05 | 9.332 | R$50.606 | C 81.808 + B 327.112 | 45 / 7 / 0 | LEGADA/mix | Pipeline(243.192) < D(408.920): desatualizado/upsell |
| LF53 | 12/05 (múltiplos arquivos) | 9.926 | R$57.000 | C 154.409 + B 516.020 | — | LEGADA/mix | **EXCLUÍDO** — upsell/2º produto |
| LF54 | **17/06** (atual) | 6.567 | **R$39.157** (G) / R$59.251 (API ⚠️) | C 36.745 + B 89.329 | 60 / 13 / 13 | LEGADA/mix | "Controle"(13) **contaminado** por ML antigo (`ML_MAR`,`LQ`); 60d superestima |
| LF55 | **17/06** (atual) | 4.586 | R$31.667 | C 58.867 + B 112.753 | 72 / 0 / 8 | LEGADA/mix | Sem controle real; 60d superestima |
| LF56 | **10/06** (atual) | 7.448 | R$41.830 | C 91.197 + B 106.433 | 28 / 6 / 14 | **MODERNA (limpa)** | Detalhe(196.642) **bate** com D(197.630); A/B confiável |

> "Split grupo" = contagem de vendas Champion / Challenger / Controle na aba Detalhes. "Época da tag" indica qual convenção de nome de campanha predomina — e portanto se a classificação é confiável.

---

## 6. Recomendação — fonte de verdade única por eixo

| Eixo | Fonte de verdade proposta | Pendência p/ ficar consistente |
|---|---|---|
| **Gasto por lançamento** | **Gerenciador Meta** (G) | Puxar LF40–48 (datas em `PC FORMULÁRIOS`); confirmar por que API furou no LF54 |
| **Gasto por grupo** | Gerenciador, separado pela **tag da campanha** | Exige classificador que cubra TODAS as épocas (Seção 3); hoje só cobre a moderna |
| **Faturamento por lançamento** | **Dashboard** (D), duas bases (contratado / recebido) | Puxar LF40–48; **definir se inclui upsell/2º produto** |
| **Faturamento por grupo** | Proporção do **matched do pipeline** aplicada ao total do dashboard | Só confiável onde a tag é limpa (LF56) |
| **Nº de leads** | **Railway `Lead`∪`Client`** (DB), all-leads, janela de captação | Rodar LF40–48 também |
| **Janela de vendas** | Decidir **um** padrão (semana de vendas **ou** 60d) e aplicar a todos | Hoje os relatórios usam 60d; o dashboard é da semana |
| **Split por grupo** | Reclassificar com **mapa de convenções por época**, OU restringir A/B aos LFs com tag moderna (LF56+) | Construir o mapa de tags antigas → grupo |

---

## 7. Próximos passos para padronizar (sem análise ainda)

1. **Definir a janela de vendas canônica** (semana vs 60d) — decisão de negócio.
2. **Definir se faturamento inclui upsell** — confere o gap LF50/52 vs dashboard.
3. **Puxar LF40–48 canônico** (gasto G + faturamento D + leads DB) para fechar a linha do tempo na mesma fonte.
4. **Construir o mapa de convenções de tag por época** para reclassificar grupo de forma consistente (ou aceitar split só de LF56+).
5. Só então refazer a análise de retorno sobre a base unificada.

---

*Procedência levantada em 17/06/2026 a partir de: arquivos `outputs/validation/`, queries diretas ao Railway, números do gerenciador/dashboard fornecidos manualmente, e o estudo `analise_valor_ml_devclub.md`.*
