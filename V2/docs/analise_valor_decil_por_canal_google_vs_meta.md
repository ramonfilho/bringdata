# Valor por decil é diferente entre Google e Meta? — análise registrada (não aplicada)

**Status:** análise exploratória registrada em 2026-06-13. **NÃO aplicada em produção** — hoje o evento com `value` não é enviado nem pra Meta, e não vai pro Google tão cedo. Este doc guarda o método e os números calibrados pra quando a decisão de enviar valor pro Google for retomada.

**Pergunta de origem:** ao começar a mandar eventos de ML pro Google Ads, o lead que converte vindo do Google é diferente o suficiente do que converte na Meta a ponto de um sinal único (uma tabela de valor só) ser inadequado?

**Modelo analisado:** o Challenger — modelo que hoje pontua as campanhas marcadas `LEADHQLB` e que naturalmente faria as predições do Google (run MLflow `5d158f0aa6e54b489498470446194a6c`, "abr28"). Janela de treino/teste 08/02/2025→08/04/2026, 202k leads, 2.424 compradores (Meta+Google), corte temporal 15/03/2026.

---

## Resumo executivo

| Eixo | Veredito |
|---|---|
| **Ranqueamento** — o modelo ordena bem o lead do Google? | ✅ **Sim, transfere.** Mesma discriminação da Meta, convertedor do Google cai em decil até mais alto. |
| **Perfil** — o convertedor do Google é diferente? | ⚠️ **Sim, mas o modelo absorve.** Mais jovem / estudante / sem renda. |
| **Valor — componente de conversão** | ✅ **Indistinguível da Meta** em todas as bandas, inclusive D10 (lift≈1, CI cobre 1.0). |
| **Valor — componente de ticket** | ❓ **Não verificado.** Único ponto realmente em aberto. Exige pull de vendas. |

**Decisão hoje:** nenhuma mudança necessária (o valor nem é enviado). Quando for enviar valor pro Google: rodar o componente de ticket antes de assumir que a tabela da Meta transfere.

---

## 1. Ranqueamento transfere (decisivo)

Discriminação dentro de cada canal, **período de teste out-of-time** (>15/03/2026):

| Métrica (convertedores) | META (facebook_ads) | GOOGLE |
|---|---|---|
| AUC | 0.765 [0.734–0.796] | 0.770 [0.638–0.881] |
| Decil médio do convertedor | 7.9 | 8.8 |
| Captura no top-3 decis (D8-10) | 63% | 82% |
| Curva de lift D1→D10 | monotônica → 3.0x | idêntica → 2.8x |

O modelo já tem a feature `Source_google_ads` + idade/ocupação/renda, então **já absorve a diferença de canal**. Um sinal único não mis-rankeia o Google. (CI largo do Google = n pequeno: 17 convertedores out-of-time, 196 no pool total — não prova superioridade, mas não há sinal de degradação.)

## 2. Perfil do convertedor é diferente (real, mas absorvido)

Maiores deltas de perfil, convertedor Google vs Meta (n: Meta=2.228, Google=196):

- Idade 18-24: **36% Google vs 17% Meta** (+19pp); <18 anos: 12% vs 2,5% (+10pp) → mais jovem
- "Sou apenas estudante": 24% vs 11% (+13pp); "não tenho renda": 28% vs 16% (+12pp)
- "Transição de carreira / 1º emprego": 39% vs 51% (-12pp) → menos adulto-em-transição
- Tem computador: 83% vs 73% (+10pp)

*(Os deltas gigantes de Medium/Term — `dgen`, `Term_outros` — são só tagueamento de UTM do canal, não perfil de pessoa.)*

## 3. Valor por decil — componente de conversão (calibrado)

**Método:** para cada (canal × decil), taxa de conversão com shrinkage k=10, valor implícito = taxa × `PRODUCT_VALUE` (R$1.563,75), isotônico crescente (mesma sequência shrinkage→isotonic do `training_model.py`). Comparação por banda grossa (D1-5/D6-9/D10, igual ao `conversion_rate_benchmark` existente) com bootstrap CI, porque o Google é esparso.

**Valor implícito por decil (taxa × PV, shrunk+isotônico) — escala comparativa, não à-vista:**

| | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---|--|--|--|--|--|--|--|--|--|--|
| META | 0.0 | 2.2 | 3.1 | 7.6 | 8.2 | 14.8 | 18.5 | 25.1 | 28.8 | **57.2** |
| GOOGLE | 0.4 | 0.4 | 1.9 | 7.1 | 9.1 | 9.1 | 15.0 | 19.9 | 28.2 | **56.5** |

No topo (D9/D10), onde o orçamento concentra, as curvas batem quase exato.

**Lift Google/Meta por banda (taxa de conversão), com CI 95%:**

| Banda | Meta | Google | Lift | CI 95% | n_conv Google |
|---|---|---|---|---|---|
| D1-D5 | 0.32% | 0.35% | 1.09 | [0.59, 1.70] | 16 |
| D6-D9 | 1.40% | 1.19% | 0.85 | [0.69, 1.03] | 95 |
| D10 | 3.66% | 3.62% | **0.99** | **[0.78, 1.22]** | 85 |

**Conclusão do componente de conversão:** a razão de valor Google/Meta é **indistinguível de 1.0 em todas as bandas, inclusive D10**. Nenhuma tabela de valor específica do Google se justifica por este eixo. (Tabela "pluggable" se algum dia for preciso = `LEAD_VALUE_BY_DECILE_CHALLENGER` × lift_banda — mas como os CIs cobrem 1.0, isso é a própria tabela atual dentro do ruído.)

> ⚠️ Base à-vista ≠ esta escala. Os números acima são taxa × PRODUCT_VALUE cheio (ticket único), pool train-inclusive — servem pra **comparação relativa Google/Meta**, não como substitutos diretos de `LEAD_VALUE_BY_DECILE` (que é cash à-vista líquido, base diferente).

## 4. Componente de ticket — ÚNICO ponto em aberto

`valor = P(compra | decil) × ticket_recebido_à_vista`. A seção 3 fecha o `P(compra)`. Falta o ticket: o comprador do Google é mais jovem / sem renda → hipótese de mais boleto/TMB → **cash à-vista menor por venda mesmo no mesmo decil**. Isso reduziria o valor do Google sem aparecer no ranqueamento nem na taxa de conversão.

**Não foi possível verificar com dado cacheado:** só existe valor realizado do Asaas (boleto/TMB, 1.400 linhas), sem Guru/cartão; o overlap por e-mail com a população scoreada foi de só 13 compradores (janelas diferentes) — insuficiente.

**Como rodar depois (método):**
1. Puxar vendas Guru + TMB + Asaas e aplicar `data_loader.combine_sales` (já tem os fatores de realização/chargeback por canal de venda → `sale_value_realizado`).
2. Cruzar por e-mail com os compradores scoreados (`__email__` em `/tmp/scored_chal.parquet` enquanto durar; ou re-scorear).
3. Comparar **ticket à-vista médio por canal de tráfego** (Google vs Meta), agregado entre todos os compradores (não fatiar por decil — n não aguenta), e o mix Guru/cartão vs boleto/TMB.
4. Se o ticket do Google for materialmente menor → tabela de valor própria; senão, tabela única transfere.

---

## Implicações para "enviar de forma segura pro Google" (3 eixos)

1. **Ranqueamento** — ✅ resolvido (§1, transfere).
2. **Valor/economia** — conversão ✅ (§3); ticket ❓ (§4) — rodar antes de enviar valor.
3. **Encanamento/integridade** — independente da economia: UTMs novos do Google têm que cair na whitelist canônica de `Source`/`Medium` (senão `Source_google_ads` zera calado — degradação silenciosa); pixel/nome de evento de destino corretos; valor não indo a 0 (bug VAL=0 / Gate D).

## Caveats

- n Google: 196 convertedores no pool (train-inclusive), 17 out-of-time. CIs largos no Google refletem isso.
- AUC da §3/§1 sobre população train-inclusive é otimista em nível absoluto; as comparações **relativas** Google↔Meta (razões, lifts) são o produto confiável, não os valores absolutos.
- Tabela de produção (`LEAD_VALUE_BY_DECILE_CHALLENGER`, D10≈20.69) está em base à-vista e foi derivada de outro pool (LF46-53) — não comparar 1:1 com a escala da §3.

---

*Dados: `/tmp/scored_chal.parquet` (população scoreada cacheada). Modelo: Challenger abr28, run MLflow `5d158f0aa6e54b489498470446194a6c`. Identificador histórico do override de valor por canal: análogo a `ab_test.variants[*].conversion_rates` em `configs/active_models/devclub.yaml`.*
