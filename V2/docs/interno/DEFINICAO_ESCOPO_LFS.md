# Definição de Escopo — Estudo de Valor de ML (DevClub)

**Data:** 17/06/2026 (v2 — incorpora respostas e investigação Meta API)
**Propósito:** travar **todas as convenções e definições** antes de regenerar qualquer dado, para a fonte de verdade ser única e consistente em todos os LFs. Só definição — sem análise. 🔵 = decidido · 🟡 = a confirmar.

---

## Resumo

1. **Grupos** — Champion = `LeadQualified(+HighQuality)`, jan30. Challenger = `HQLB`/`HQLB_LQ`/`ML_MAR`/`LEADHQLB`, abr28. `PIXEL NOVO API` é ambíguo (os dois) → desempata pelo `registros_ml.variant`. Controle = sem evento ML (`LEAD`/`SCORE`/`FAIXA`). Fonte = `variant` do ledger; pré-ledger reconstrói pelo padrão da época.
2. **Janela de vendas** — semana de carrinho **e** 60d atribuídos, lado a lado.
3. **Atribuição** — split por grupo só no `matched`; total = dashboard; extrapolada = `matched ÷ tracking_rate`.
4. **Faturamento** — `sale_value` (contratado) **e** `sale_value_realizado` (recebido), incluindo upsell.
5. **Gasto** — gerenciador, janela captação; por grupo via tag.
6. **Leads** — all-leads por época (`leads_capi`+Sheets → `Lead` → `Client`), janela captação; dashboard desempata.
7. **Escopo LFs** — coletar todos (DEV19, LF40–56); remover outliers (LF40, 41, 51, 53) só na análise.
8. **Canônico** — pipeline aplicado ao escopo; validar convergência vs dashboard (LF49–56).

---

## 1. Classificação de grupo — fonte autoritativa = routing de produção

A verdade de qual arm (Champion/Challenger) scoreou cada lead está no **routing de produção** (`active_models/devclub.yaml` → `match_variant` em `src/core/client_config.py`) e é **gravada por lead no campo `registros_ml.variant`** no momento do scoring (`champion_jan30` / `challenger_abr28`). O nome/tag da campanha é só um **proxy** disso — útil, mas não é a verdade.

Regra de routing: se a `utm_campaign` do lead contém o **padrão do Challenger da época** → Challenger; senão → Champion (default jan30). Evento CAPI e pixel seguem o arm:

| Arm | Modelo | Eventos CAPI | Pixel primário |
|---|---|---|---|
| **Champion** | jan30 | `LeadQualified` + `LeadQualifiedHighQuality` | 1937807493703815 |
| **Challenger** | abr28 | `HQLB_LQ` + `HQLB` | 1513132406527995 |
| **Controle** | (nenhum arm ML) | LEAD / score / faixa — **sem** evento ML | — |
| **Externo/Outro** | — | não-captação Meta / outro lançamento | — |

🔵 **Confirmado (sua asserção + config):** `LeadQualified` **E** `LeadQualifiedHighQuality` = **Champion**; `HQLB`/`HQLB_LQ` = **Challenger**. "HighQuality" **não** é Challenger — o marcador do Challenger é **HQLB**. (Corrige meu erro anterior.)

⚠️ **O padrão de routing do Challenger MUDOU no tempo** — classificar lead antigo exige o padrão **vigente na data de captura**, não o de hoje:

| Período | Padrão na `utm_campaign` que = Challenger |
|---|---|
| ~31/03/2026 (precursor) | `ML_MAR` (eventos `LeadQualifiedCha` / `...ChaHighQuality`, pixel 6130) |
| 29/04 → 27/05/2026 | `PIXEL NOVO API` ⚠️ **ambíguo** — esse nome aparece em campanha Champion **e** Challenger; **não** classifica sozinho |
| 27/05 (transitório) | contém `utm_pixel` |
| 27/05/2026 → hoje | contém `LEADHQLB` |

⚠️ **Era "PIXEL NOVO API" (29/04–27/05) é ambígua pelo nome** (Champion e Challenger usam a mesma string). Para esses leads, **só o `registros_ml.variant` desambigua** — onde o ledger não cobre (29/04–17/05), o arm fica incerto pelo nome e precisa de outro sinal (evento/pixel disparado). Mais um motivo para a verdade ser o `variant`, não o nome.

🔵 **ML_MAR = Challenger (confirmado por você).** O "Cha" dos eventos = Challenger. Foi um teste de Challenger em mar/2026, antes da reativação formal do A/B em 29/04. **Tanto `LQC` quanto `HLQC` sob `ML_MAR` são Challenger.** (Corrige meu palpite anterior de que LQC=Champion.)

⚠️ **Depende do (pixel, evento)** (sua asserção): o mesmo nome de evento significa modelos diferentes em pixels diferentes. O pixel **241752320666130** é **fan-out** (recebe cópia de Champion E Challenger), então campanha nele é ambígua pelo evento — só a rota/variant (ou a tag `ML_MAR`) desambigua.

### 1.1 Fonte de classificação do arm, por época (recomendado)

| Período do lead | Fonte autoritativa do arm |
|---|---|
| ≥ ~17/05/2026 (ledger vivo) | **`registros_ml.variant`** — gravado pela produção no scoring. Verdade direta. |
| < 17/05/2026 | Reconstruir via **padrão de routing vigente na data** (tabela acima) aplicado à `utm_campaign` do lead |
| Controle | Lead cuja campanha **não tem evento ML** (LEAD puro / score / faixa) |

### 1.2 Divergência do pipeline atual (achado da auditoria)

O relatório de validação **NÃO usa `registros_ml.variant`**. Ele classifica por **nome de campanha** (`classify_campaign` → `ml_type` → `create_refined_campaign_map` / `map_to_refined_group` em `validate_ml_performance.py:1937`), reconhecendo só as tags recentes (`MACHINE LEARNING`/`LEADQUALIFIED`→Champion, `LEADHQLB`→Challenger, resto→Controle). Consequências:

1. **Ignora o padrão temporal**: lead da era "PIXEL NOVO API" (29/04–27/05) que a produção mandou pro Challenger é classificado **Champion** (tem MACHINE LEARNING, não tem LEADHQLB).
2. **Tags antigas** (`ML_MAR`/`LQ`/`LQC`) caem em **Controle** → contaminou o "controle" do LF54.
3. **Esquema antigo** "Eventos ML / Controle" (DEV19) é incompatível.
4. **Não separa por pixel**.

**Correção proposta:** classificar o arm pela fonte autoritativa da Seção 1.1 — `registros_ml.variant` onde existe; reconstrução por padrão temporal antes; Controle = sem evento ML. Centralizar num único classificador, alimentado por nome **ou** UTM, com o histórico de padrões versionado por data.

---

## 2. Janela de vendas

🔵 **Reportar AS DUAS, lado a lado.**

| Janela | Definição |
|---|---|
| **Semana de vendas** | `data_venda` dentro da semana de carrinho aberto (datas em PC FORMULÁRIOS) |
| **60 dias (atribuída)** | `data_venda` em até 60 dias da captura do lead — verdade de atribuição do negócio |

---

## 3. Atribuição de vendas (cobertura)

| Tipo | Definição | Tem grupo? |
|---|---|---|
| **Matched / atribuída** | Venda vinculada a um lead por email/telefone → sabemos a campanha → **tem grupo** | ✅ |
| **Total** | Todas as vendas do período | ❌ |
| **Extrapolada** | `matched ÷ tracking_rate` | ❌ |

🔵 Split por grupo (Champion/Challenger/Controle) **só existe no matched**.

---

## 4. Base de faturamento

🔵 Reportar as duas, **incluindo upsell / 2º produto** (sem filtrar Mentoria — o dashboard conta tudo).

| Base | Definição |
|---|---|
| **Contratado** | Valor cheio da venda (cartão + boleto cheio) |
| **Recebido / à vista** | Valor efetivamente entrado: cartão + parcela(s) já paga(s) do boleto |

🔵 **Sobre nº de parcelas (sua dúvida "que diferença faz"):** não faz diferença — o recebido vem do **valor real cobrado nos registros**, não de fórmula ÷N. **Confirmado no código:** o pipeline já carrega as duas colunas — `sale_value` (contratado, forçado ao valor do produto) e **`sale_value_realizado`** (do campo `_asaas_payment_value` = valor real cobrado na transação Asaas). Então as duas bases são extraíveis do pipeline.

🟡 **A confirmar no código:** o `sale_value_realizado` está completo para **todas** as plataformas (Asaas confirmado; TMB usa `Ticket` cheio = contratado; Guru/Hotmart usam preço gross = contratado). Para recebido real de TMB/Guru/Hotmart, verificar se há coluna realizado equivalente ou se assume-se contratado.

---

## 5. Gasto

🔵 Fonte canônica = **gerenciador Meta**.
🔵 **Janela = captação apenas** (a semana de CPL já cai na captação do ciclo seguinte — não somar, pra não duplicar).
🔵 Gasto **por grupo** = soma das campanhas de cada grupo (via tag, mapa 1.1).

---

## 6. Leads

🔵 **All-leads** (todas as fontes, não só respondentes de pesquisa), na **janela de captação**. Fonte da verdade = **número do cliente (dashboard)**; na ausência dele, união do banco por época:

| Época | Fonte all-leads |
|---|---|
| < 2026-02-18 | Backup Cloud SQL `leads_capi` + Google Sheets (pesquisa) |
| 2026-02-18 → ~2026-05-17 | Railway `Lead` + Google Sheets (pesquisa) |
| ≥ ~2026-05-17 | Railway `Client` (all) + `registros_ml` (subset ML) + Google Sheets |

🟡 **Sua observação é válida:** "leads = Lead" não é uma fonte única — varia por época (Sheets backup, `leads_capi`, `Lead`, `Client`). O número do **dashboard** é o desempate canônico quando existir.

---

## 7. Escopo de lançamentos

🔵 **Coletar TODOS** com dados corretos primeiro; **remover outliers só na hora da análise** (não na coleta).
🔵 **Outliers combinados (removidos na análise):** LF40, LF41 (gasto baixo + N inconclusivo), LF51 (boleto anômalo — fica de fora), LF53 (upsell/2º produto).
🔵 **DEV19 entra** na coleta (decisão "todos entram"); avaliar como outlier "escala atípica" só na análise.
🔵 Conjunto de coleta: DEV19, LF40–LF56 (todos), aplicando a definição corretamente.

---

## 8. Fonte canônica — posição acordada

🔵 **A fonte canônica É o pipeline, SE todos os passos deste escopo forem aplicados corretamente** (classificação completa, janela certa, base certa, incluindo upsell, gasto do gerenciador, leads all-source). Não puxar LF40–48 manualmente do dashboard.
🔵 **Validação:** onde temos o dashboard (LF49–56), conferir que o pipeline regenerado **converge** com ele. Convergiu → confiar no pipeline para LF40–48 também. Não convergiu → investigar o passo que falta antes de seguir.

> Racional: as divergências pipeline×dashboard vistas antes vinham de (a) relatórios velhos de 12/05 (staleness), (b) classificação errada de grupo, (c) filtro de upsell. Corrigindo os três + regenerando fresco, o pipeline deve bater com o dashboard.

---

## 9. Pendências antes de regenerar

| # | Pendência | Tipo |
|---|---|---|
| 1 | ✅ Eventos→arm: LeadQualified(+HQ)=Champion; HQLB/HQLB_LQ=Challenger — **confirmado (config + sua asserção)** | resolvido |
| 1b | ✅ ML_MAR (`LeadQualifiedCha`/`...ChaHighQuality`, mar/2026) = **Challenger** — confirmado por você | resolvido |
| 2 | ✅ Parcelas irrelevantes se ler recebido real dos registros | resolvido (validar no código) |
| 3 | ✅ Gasto = captação apenas | resolvido |
| 4 | ✅ Todos entram; outliers removidos na análise | resolvido |
| 5 | Classificar arm pela fonte autoritativa (`registros_ml.variant` + padrão temporal), **não** pelo nome só | 🔧 worktree + teste |
| 6 | Auditar pipeline: janela de gasto, upsell/filtro de produto, cálculo de recebido | 🔧 (parcial: classificação já auditada) |
| 7 | Mapear pixel `241752320666130` (fan-out) — quais arms passaram por ele | 🟡 investigar |

---

## 10. Plano de execução (após sign-off)

1. **Auditar o pipeline** (#6): como ele hoje (a) classifica grupo, (b) define janela de gasto, (c) trata upsell, (d) calcula recebido. Listar o que diverge deste escopo.
2. **Estender `classify_variant`** (mapa 1.1) + ajustar janela de gasto/base de receita conforme o escopo — em **worktree**, com teste.
3. **Regenerar todos** (DEV19, LF40–56) fresco com o pipeline corrigido.
4. **Validar convergência** com o dashboard (LF49–56).
5. **Montar a tabela única** (todos os LFs; gasto gerenciador; faturamento contratado+recebido; 2 janelas; split por grupo consistente).
6. **Remover outliers** e refazer a análise de retorno.

---

*Procedência e inconsistências em `FONTE_DE_VERDADE_LFS.md`. Confirmações da Meta API (custom_event_str, datas de criação) em 17/06/2026.*
