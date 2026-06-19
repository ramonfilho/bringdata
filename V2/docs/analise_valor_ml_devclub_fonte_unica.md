# Valor do ML no DevClub — estudo sobre fonte única (resolver)

> Refaz o estudo de retorno do lead-scoring usando **uma régua de classificação
> consistente para todos os lançamentos** (o resolver de braço A/B), corrigindo as
> inconsistências de grupo, base de receita e janela de vendas dos relatórios antigos.
> Supersede `analise_valor_ml_devclub.md` e `analise_valor_ml_devclub_lf49_lf56.md`.

Data: 18/06/2026. Lançamentos: LF40–LF56 + DEV19 (a turma de janeiro). Outliers
removidos da análise: LF40 e LF41 (Black Friday / pós-BF, compra atípica) e LF53
(upsell de segundo produto infla as vendas) — campo `excluded_from_reference` do
launches.yaml. LF51 ("Padrão Ouro") é lançamento de referência e **fica dentro**.
Janela de captação como período de gasto; vendas em duas janelas.

---

## 1. Pergunta

Quanto de receita incremental o modelo de ML (lead-scoring que otimiza as campanhas
da Meta) gerou acima de um cenário sem ML, ao longo dos lançamentos? Duas métricas,
lado a lado:

- **ROAS a mais (%)** — quanto o ROAS dos braços de ML superou o do Controle.
- **Dinheiro novo (R$)** — receita_ML − gasto_ML × ROAS_Controle (contrafactual:
  "se o gasto do ML tivesse rendido como o Controle").

---

## 2. Fonte única e por que ela importa

Cada lead é classificado em **Champion** (modelo jan/30), **Challenger** (modelo
abr/28) ou **Controle** (captação sem evento de ML) por um **resolvedor único**
(`src/core/ab_arm.py`), que lê a verdade de produção (`registros_ml.variant`) quando
existe e reconstrói pela época do nome de campanha quando não existe. Isso resolve a
inconsistência histórica em que "Challenger" significava coisas diferentes em
relatórios diferentes.

A **receita e o gasto por grupo** vêm da aba **Comparação ML** dos relatórios de
validação, que agrega as campanhas Meta pelo grupo do resolver — **mesma régua dos
dois lados**, então o ROAS é internamente consistente.

### Correção metodológica importante
A primeira tentativa somou receita pela aba **Detalhes** (venda-a-venda, casando cada
venda ao lead). Isso **super-credita o grupo maior**: o Champion tem ~4x mais leads
que o Controle, então muito mais venda de fundo casa por coincidência com um lead
Champion. O lift inflava de forma não-uniforme (chegou a "8x" no LF44). A aba
Comparação ML (atribuição via campanha Meta, consistente com o gasto) é a fonte
correta — e nela o LF44 rende modestos +18–53%, não 8x.

---

## 3. Método

- **Grupos:** Champion + Challenger = ML; Controle = baseline.
- **Gasto:** captação Meta por grupo (não inclui escala/remarketing).
- **Duas bases de receita:**
  - **Contratado** — valor cheio do contrato (teto).
  - **Recebido** — caixa à-vista; boleto conta só a 1ª parcela (piso conservador).
    *Obs.: o "recebido até hoje" do dashboard fica ENTRE recebido e contratado,
    porque parcelas de boleto seguem entrando.*
- **Duas janelas de vendas:** semana (7d) e 60d (captura conversão tardia de boleto).
- **Baseline de Controle (pooled):** ROAS de controle agregado **só dos lançamentos
  com holdout saudável** (gasto de controle > R$5k): LF42, LF43, LF44, LF56, DEV19.
  Controles rasos (LF45 gasto R$306, LF54 R$2,7k → ROAS absurdo) são excluídos do
  baseline; o lado ML deles permanece.
- **Dois recortes de valor:**
  - **Medido** — só os 5 lançamentos com controle interno (chão sólido, medição direta).
  - **Portfólio** — aplica o baseline pooled a TODOS os 15 lançamentos de ML
    (extrapolação; mesmo espírito do baseline 1,91x do estudo original).

O recebido por grupo = contratado validado × ratio recebido/contratado do grupo
(ratio é robusto à super-atribuição, pois é proporção).

---

## 4. Resultado

| base | janela | Medido (5 LFs c/ controle) | Portfólio (15 LFs) |
|------|--------|----------------------------|--------------------|
| contratado | semana | +158% · R$194k | +81% · R$539k |
| contratado | 60d    | +133% · R$281k | +185% · R$2,11M |
| **recebido** | semana | +227% · R$121k | +73% · R$210k |
| **recebido** | **60d** | **+215% · R$167k** | **+148% · R$621k** |

**Headline (recebido / 60d):** o ML entregou **+215% de ROAS sobre o Controle**
(medido nos 5 lançamentos com holdout real), equivalente a **R$167k de dinheiro novo**
medido; extrapolado ao portfólio inteiro, **+148% / R$621k**.

### Leituras
- **Direção robusta:** lift positivo em todos os 8 cortes (+73% a +227%). A
  conclusão não depende de base, janela ou recorte.
- **Recebido tem lift MAIOR que contratado** (+215% vs +133% no 60d medido): o
  comprador do ML paga mais à-vista (mais cartão, menos boleto parcelado). O ML não
  só vende mais — vende venda de melhor qualidade de caixa.
- **LF44 é imaterial** na fonte validada (o "8x" era artefato do Detalhes).
- **Reconciliação com o estudo original (R$793k):** cai entre nossos cortes de
  contratado (R$539k semana ↔ R$2,11M 60d) — a metodologia bate, agora com
  atribuição validada e controle saudável.

---

## 5. Ressalvas / em aberto

- **Recebido = à-vista** (boleto 1ª parcela). É piso. O caixa real até hoje é maior.
- **Portfólio é extrapolado:** os 8 lançamentos sem holdout usam o baseline pooled
  dos 5 com controle. Se o público/período deles diferir, a estimativa desloca.
- **Alinhamento de gasto com o dashboard — PENDENTE.** O denominador usa todas as
  campanhas "cap frio" do resolver; a linha CAP do dashboard pode ser subconjunto
  (LF49: 96,6k vs 74,6k; LF56 bateu exato). A fazer campanha-a-campanha com o cliente.
- **Controles rasos** (LF45, LF54) ficaram fora do baseline por gasto ~zero.

---

## 6. Reprodutibilidade

- Relatórios: `outputs/validation/<mês>/<LF> - ...xlsx` (janela 60d via
  `--sales-end-date = vendas_start+60d`; aba Detalhes inclui "Valor Recebido").
- Scripts: `analise_valor_ml/extract_sales.py` (tidy venda-a-venda),
  `rebuild_comparacao.py` (agregado contratado validado),
  `final_recebido.py` (contratado + recebido, medido + portfólio).
- Resolver: `src/core/ab_arm.py` (+ `tests/test_ab_arm.py`).
