---
title: Registro de Erros — Smart Ads V2 (uso interno)
data_unificacao: 2026-05-08
audiencia: interno (engenharia + MLOps)
origem:
  - V2/docs/Erros_cometidos.md (mtime 2026-04-22)
  - V2/docs/auditoria_dano_bugs_ml.md (mtime 2026-05-07)
politica_merge: versão mais nova vence; auditoria foi re-tecnicada (Champion/Challenger, ordinal vs OHE, encoding_overrides, LQHQ vs LQ) para audiência interna.
---

# Registro de Erros — Smart Ads V2

> Registro técnico consolidado: bugs com impacto real, decisões erradas, padrões que se repetiram, backtests contrafactuais (mar–mai/2026), medidas corretivas implementadas e frentes preventivas em aberto.

> **Nota sobre identificadores codificados (Cluster N, V.1, V.2, T1-X, DT-X, R-X):** este doc usa identificadores curtos pra cruzar com commits, issues e os catálogos técnicos. O significado verbal de cada um vive nos catálogos correspondentes:
> - `T1-X` / `T2-X` / `T3-X` (salvaguardas) — descrição verbal completa em [`PLANO_SAFEGUARD.md`](PLANO_SAFEGUARD.md)
> - `DT-X` / `R-X` (dívida técnica do refactor) — descrição verbal completa em [`PLANO_REFACTOR_MLOPS.md`](PLANO_REFACTOR_MLOPS.md)
> - `Cluster N` do Erro 2 — descrição completa logo abaixo na seção 2 deste doc
> - `V.1` / `V.2` / `V.3` / `V.4` — frentes preventivas em aberto, descritas na seção V deste doc
> - `AUDITORIA_QUEBRA_PRODUCAO.md` — checklist operacional de cenários a estressar (linguagem natural, sem códigos)

---

## Cinco lições fundamentais

1. **Produção não é o lugar de aprender.** Cada bug descoberto ao vivo em vez de antes do deploy foi pago com sinal degradado, dados contaminados ou número errado apresentado ao cliente.
2. **O modelo aprende com o que você decide mostrar a ele — se você não controlar isso, ele decide sozinho.** Sem grupo controle, o sistema criou os próprios dados de treino e entrou em colapso gradual sem que ninguém percebesse por três meses.
3. **A função objetivo errada produz o resultado errado, não importa o quão bom seja o modelo.** O valor enviado ao Meta define o que o algoritmo deles vai otimizar — enquanto esse número estava errado, o resto do sistema estava trabalhando contra si mesmo.
4. **Infraestrutura boa não substitui definição clara do problema.** O refactor, o YAML multi-cliente, o `src/core/` — tudo sólido, mas construído depois dos erros. Escalar para novos clientes exige inverter a ordem.
5. **Você não pode confiar em um número que nunca foi conferido contra a realidade.** O relatório que prova o valor do sistema acumulou erros de cálculo durante meses porque ninguém tinha um total de referência externo. Um número só é confiável quando existe outro independente que deveria bater com ele — e esse check precisa ser automático.

---

## I. Erros estratégicos e operacionais

### 1. Cálculo errado do valor de conversão enviado ao Meta

O `value` enviado em cada `LeadQualified` (sinal que o algoritmo Meta usa para otimizar) foi calculado de forma incorreta em diferentes momentos.

**Primeira forma — tabela hardcoded por decil:** valores fixos no código, descolados do produto em venda e do ticket real. Número arbitrário sem ancoragem no negócio.

**Segunda forma (15/03/2026) — mismatch D1–D9 vs D01–D09:** ao corrigir o formato das chaves de configuração, o mapeamento de `D1`–`D9` para `D01`–`D09` foi feito em parte do código. 9 de 10 decis ficaram com `value=null` por alguns dias.

**Terceira forma (22/03/2026) — fórmula `ticket_médio × taxa_de_conversão_do_decil`:** a tabela hardcoded foi substituída por cálculo em runtime, mas o `ticket_médio` ainda usava média simples — não ponderava Guru (à vista) com TMB (parcelado com inadimplência projetada).

**Correção final (03/04/2026):** fórmula passa a usar ticket Guru real + fator de realização TMB. Só então o número fica consistente ponta a ponta.

---

### 2. Bugs de encoding e divergência treino/produção

Cinco clusters distintos ao longo do período, cada um com causa raiz própria.

#### Cluster 1 — Bugs isolados (jan/2026)

Bootstrap do sistema, problemas pontuais corrigidos sem causa raiz comum:

- **07/01:** features de Medium codificadas duas vezes — sinal duplicado.
- **09–11/01:** ordinal encoding de `idade` e `faixa_salarial` quebrava por divergência de nome de coluna entre YAML e DataFrame em produção.
- **09–11/01:** `'NÃO'` em maiúsculo em "Tem computador?" não era normalizado, gerando categoria nova a cada lançamento.
- **17/01:** `'consegui'` → `'conseguir'` ausente — feature morta criada em produção.
- **17/01:** `utm_source` sem `.lower()` — `Facebook-Ads` e `facebook-ads` viravam features distintas.

#### Cluster 2 — Divergência sistêmica treino/produção (15/03/2026)

Maior bug de encoding do projeto. Ao ativar o Challenger TMB All, percebeu-se que treino e produção aplicavam regras diferentes para encoding, Medium e UTM — divergências há meses no código, mascaradas porque o Champion anterior havia sido treinado e servido com as mesmas regras erradas. Com a troca de modelo, a divergência ficou visível: o score em produção não correspondia ao esperado pelo treino. Corrigido na mesma data, mas o modelo precisou ser retreinado para garantir consistência.

#### Cluster 3 — `Medium_Linguagem_programacao` zerada (13/04/2026)

Bug silencioso de encoding fazia com que `Medium_Linguagem_programacao` — 5ª feature mais importante do modelo (5,31% de peso) — fosse preenchida com zero para 100% dos leads desde que o modelo Challenger foi implantado. Não causava erro explícito, apenas eliminava o sinal.

Descoberto ao investigar a queda de D10% após o rollback: mesmo com o Champion (jan30) correto, D10 estabilizou em ~30% em vez de retornar aos ~42% de P1.

**Janela específica auditada (26/mar–13/abr, ~18 dias):** durante uma reorganização do código que processa origens, uma transformação de texto removeu acentos das categorias. "Linguagem de programação" virou "Linguagem de programacao" — o modelo, treinado com o nome anterior, não a reconhecia. Corrigido em 14/abr.

**Backtest contrafactual (run jan30 ativo):** `Leads em D9–D10 sem bug = 14.227` vs `com bug = 14.234` (Δ +7). Conversões observadas em D9–D10 idênticas. **Dano direto ~R$0** porque a feature pesa ~5% globalmente, mas na janela analisada a audiência veio 78,9% de campanhas "aberto" e apenas 0,1% do segmento "Linguagem de programação" — a feature já estava praticamente vazia para essa audiência. O bug existiu, mas não teve onde causar dano.

#### Cluster 4 — `idade` e `faixa_salarial` ausentes pós-rollback do Challenger (26/03–01/04)

**Janela:** 6 dias.

**Causa:** em 15/03 o Challenger TMB All foi colocado em produção, treinado em pipeline nova que esperava `idade` e `faixa_salarial` em formato distinto (OHE em vez do ordinal do Champion). Em 25/03 o resultado ficou ruim e foi feito rollback do modelo para o Champion (jan30) — mas só o `mlflow_run_id` voltou; o código de encoding permaneceu na versão preparada para o Challenger. O Champion passou a receber idade/salário em OHE em vez do ordinal_encoding que ele esperava — `Qual_a_sua_idade` e `Atualmente_qual_a_sua_faixa_salarial` chegaram zeradas para todos os leads. Essas duas variáveis representam ~8% do peso total das decisões do modelo. Corrigido em 01/04.

**Backtest contrafactual (run jan30, ablação por monkey-patching de `predict_proba`):**

| Decil sem bug | Total | Alterados | % alterado |
|---|---|---|---|
| D01 | 498 | 65 | 13,1% |
| D02 | 491 | 153 | 31,2% |
| D03 | 345 | 163 | 47,2% |
| D04 | 375 | 171 | 45,6% |
| D05 | 562 | 219 | 39,0% |
| D06 | 911 | 327 | 35,9% |
| D07 | 1.003 | 361 | 36,0% |
| D08 | 1.138 | 336 | 29,5% |
| D09 | 1.362 | 320 | 23,5% |
| D10 | 3.891 | 260 | 6,7% |
| **Total** | **10.576** | **2.375** | **22,5%** |

**Dano direto** (referência histórica E clean, suavizada por isotonic regression para garantir monotonicidade D1→D10):
- Rebaixamentos (perda real): R$ 2.620
- Promoções espúrias: R$ 1.832
- **Saldo líquido: R$ 788**
- Movimentação total entre decis: R$ 4.451

**Insight central:** saldo líquido modesto **não significa ausência de impacto**. O bug embaralhou a ordenação em vez de empurrá-la em uma direção — rebaixamentos e promoções se compensaram em valor médio. Mas:
1. **Poder discriminativo degradado** — 22,5% dos leads com decil errado, taxa de erro >35% nos decis médios D3–D7.
2. **Eventos `LeadQualified` enviados ao Meta com decis contaminados** — leads médios entram como D9–D10, parte dos D9–D10 reais cai para decis intermediários. Sinal de otimização ruidoso.
3. **Otimização Meta perdida** durante a janela — algoritmo treinou em sinal contaminado, perdeu capacidade de buscar perfil correto. Efeito acumula no tempo, não quantificado aqui.

#### Cluster 5 — `idade` e `faixa_salarial` ausentes em A/B reativado (29/04–05/05)

**Janela:** 7 dias.

**Causa:** ao reativar o teste A/B em 29/04 (Champion jan30 + Challenger `5d158f`), faltou propagar `encoding_overrides` (`ordinal_variables`) para o caminho do Champion no `configs/active_models/devclub.yaml` — só foi configurado para o Challenger novo. O Champion processava `idade` e `faixa_salarial` como OHE em vez do ordinal_encoding que ele esperava. Como o Champion captava ~90%+ do tráfego do A/B, a maioria dos leads chegou ao modelo sem essas duas variáveis. A correção equivalente já existia em outro trecho do código, mas não tinha sido replicada nesse caminho. Corrigido em 05/05.

**Backtest contrafactual (run jan30, ablação):**

| Decil sem bug | Total | Alterados | % alterado |
|---|---|---|---|
| D01 | 1.066 | 93 | 8,7% |
| D02 | 718 | 209 | 29,1% |
| D03 | 467 | 223 | 47,8% |
| D04 | 596 | 271 | 45,5% |
| D05 | 946 | 433 | 45,8% |
| D06 | 1.652 | 698 | 42,3% |
| D07 | 1.983 | 835 | 42,1% |
| D08 | 2.034 | 674 | 33,1% |
| D09 | 2.184 | 541 | 24,8% |
| D10 | 5.779 | 394 | 6,8% |
| **Total** | **17.425** | **4.371** | **25,1%** |

**Dano direto:**
- Rebaixamentos: R$ 4.218
- Promoções espúrias: R$ 4.318
- **Saldo líquido: ~R$ 0**
- Movimentação total entre decis: R$ 8.536

**Insight central:** mesma classe de dano oculto do Cluster 4. 25,1% dos leads com decil errado, taxa de erro >40% em D3–D7. Dano total = efeito direto (~R$0 medido) + degradação acumulada de otimização Meta (não quantificado). **Janela cruzada com Erros 8 e 10 abaixo** — degradação de sinal sobreposta.

---

### 3. D9 com 0% — decil não enviado ao Meta por ~2 meses

**Janela:** ~mid-jan → 15/03/2026 (com fixes parciais ao longo do período).

**Causa:** comparação de string fazia D9 ser sempre tratado como ausente — código comparava `'D9'` mas o sistema formatava decis como `'D09'`. O acréscimo do zero (`D09` em vez de `D9`) tinha sido pedido pelo gestor de tráfego para facilitar ordenação manual em Google Sheets, mas a mudança foi feita só em parte do código, criando a divergência. A comparação só casava para D10 (igual nos dois formatos) e falhava em D9. Múltiplos fixes parciais ao longo de fev–mar; o último em 15/03 fechou a janela.

**Impacto:** durante ~2 meses, a Meta recebeu LQHQ (sinal de alta qualidade) de **apenas metade dos leads top** — ~10% do volume (apenas D10) em vez dos ~20% esperados (D9 + D10). Algoritmo otimizou para perfil mais estreito do que o ideal. Não há medição financeira direta possível, mas o efeito existiu.

Não havia alerta automático para esse tipo de falha — só foi encontrado ao auditar a distribuição de decis no banco.

---

### 4. Deploy de novo modelo com 100% de tráfego imediato

Em 15/03/2026, o Challenger TMB All foi ativado com 100% do tráfego de produção sem canário ou rollback gradual. A divergência de paridade treino/produção descrita no Cluster 2 veio à tona exatamente nesse momento: D10% colapsou de 20% para 5% em 48h.

Rollback para o Champion jan30 foi feito manualmente alguns dias depois, após análise e confirmação de que o problema era o modelo novo, não a audiência. Tempo total com sinal degradado: ~10 dias.

**Lição direta:** qualquer novo modelo deve ser ativado primeiro para 5–10% do tráfego (canário), com monitoramento de D10% e AUC em produção antes de escalar. Implementado em 21/04 (ver Seção IV).

---

### 5. Mudança de evento de otimização (LQHQ→LQ) com 100% do orçamento + valor superestimado

Em 10/03/2026, o evento de otimização das campanhas foi migrado de `LQHQ` (enviado apenas para D9–D10, sinal de topo) para `LQ` (enviado para todos os decis com valor proporcional). A mudança foi feita de uma vez em todas as campanhas, sem grupo de controle e sem período de transição.

**Erro composto da janela mar/2026:**

1. **Cobertura ampliada:** evento `LeadQualified` passou de D9–D10 para todos os decis com valor proporcional.
2. **Valor superestimado:** o `value` financeiro de cada conversão foi calibrado pelo total de longo prazo descontada a inadimplência projetada (TMB), não pelo recebido à vista. Isso superestimava o retorno reportado ao Meta a curto prazo (ver Erro 1, terceira forma).

A combinação: Meta recebe sinal "todo decil é valioso" + valor inflado → algoritmo busca audiência mais ampla com expectativa irreal de retorno. O D10% caiu de ~42% para ~30% em dois dias. ROAS dos LFs do período abaixo dos LFs limpos (LF44/45). Coincide com instabilidade declarada da Meta em mar/2026, o que confunde atribuição.

A criação do novo Pixel ajudou a cortar o efeito mais rapidamente. Revertido pouco antes do rollback de 13/04.

**Lição:** mudanças de evento de otimização — especialmente as que alteram o perfil aprendido pelo Meta — deveriam ser testadas em subconjunto de campanhas ou com budget reduzido antes de aplicadas ao portfólio inteiro.

---

### 6. Ausência de grupo controle — feedback loop não detectado

O modelo foi treinado em dados produzidos por ele mesmo: ao classificar leads em D10 e direcionar orçamento para esse perfil, o Meta entregou cada vez mais leads desse perfil, super-representados no próximo treino. D10 chegou a 41% dos leads no LF45 (esperado: ~10%), indicando otimização para público progressivamente mais estreito.

O feedback loop estava ativo desde os primeiros lançamentos com o sistema ligado, mas só foi diagnosticado em 11/03/2026. Grupo controle (10–20% do budget fora do ML) ativado apenas em 15/03/2026 — modelo rodou em loop fechado por ~3 meses antes da correção estrutural.

**Atualização (auditoria mai/2026):** testes com pesos por grupo em abril mostraram que o impacto real do feedback loop em performance era pequeno — variação <0,3%. A hipótese que motivou a mudança LQHQ→LQ (Erro 5) nem havia sido confirmada em volume. Mitigação atual: campanha de controle roda em paralelo, ML mostra **lift de 6,88× em D9+D10** sobre ela.

Retreino com importance weighting (pesos maiores para leads da campanha de controle) está pendente para corrigir o viés acumulado no dataset.

---

### 7. Modelo em produção há 3+ meses sem retreino

**Estado:** Champion `d51757f5041c44b7ab1a056fce8c3c35` (jan30) treinado com dados até 24/set/2025. Em produção há mais de 3 meses, com dados de treino com ~7 meses de defasagem.

**Por que não foi resolvido:** tentativas de troca em 15/03 (TMB All, run `2a98e51c`), 25/03 (rollback) e 28/04 (Challenger `5d158f`) falharam por bugs de encoding (Clusters 4 e 5 acima).

**Risco:** drift potencial de perfil de leads e comportamento de conversão. Não medido — depende de Challenger limpo em produção para comparação. Dívida técnica em aberto, não bug pontual. O próximo retreino + deploy controlado (com salvaguardas implementadas — Seção IV) fecha esse risco.

---

### 8. Evento LQ enviado sem `value` por 7 dias

**Janela:** 29/04 → 06/05/2026 (~7 dias).

**Causa:** durante a refatoração para mover valores hardcoded para configuração via YAML, a leitura do mapeamento `decil → value` foi removida do caminho de envio do CAPI sem ser substituída pela leitura de `conversion_rates` do YAML. `LeadQualified` continuou sendo disparado, mas com `value=null`.

**Gasto direto:** **R$ 8.433,19** na campanha *DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO | MACHINE LEARNING | LQ | PG2 | 2025-04-15* (id `120242248118610390`).

**Efeito indireto:** algoritmo Meta sem sinal econômico por 7 dias — perda de capacidade de refinar perfil de leads de maior retorno. Sobrepõe Cluster 5 e Erro 10 na mesma janela.

**Como foi descoberto:** 06/05/2026 via Q1 do BigQuery sink `cloudrun_logs.run_googleapis_com_stdout` (ver [bigquery_sinks.md](bigquery_sinks.md)) — query agrupando events `LeadQualified enviado` por `valor_projetado` mostrou que entre 30/04 e 06/05 todos saíam com `value=0`, expondo a remoção silenciosa de `conversion_rates` do YAML em 06/04 (commit `d40970a`). Esse é o fluxo de auditoria padrão pra detectar este tipo de bug em lançamentos futuros.

**Corrigido:** 06/mai (Fix A — `conversion_rates` recolocado em `clients/devclub.yaml.business`, commit `8dd208f`). Solução arquitetural completa em DT-17 (`PLANO_REFACTOR_MLOPS.md`) — eliminar duplicação `business_config.py` × YAML.

**§ I.8b — Bug irmão: variants A/B com `conversion_rates` zerado (08/05/2026)**

Janela: descoberto durante o canary `00403-cez` em 10% (08/05). Não havia janela em produção 100% — Fix A do mesmo dia mascarou o bug irmão até o canary subir tráfego.

Causa: em `configs/active_models/devclub.yaml`, os variants `champion_jan30` (shim) e `challenger_abr28` tinham `conversion_rates` declarado como `{D01: 0.0, ..., D10: 0.0}`. Comentário do YAML afirmava literalmente que esses campos "NUNCA são lidos" — mas eram lidos em `app.py:1016` (síncrono) e `app.py:3516` (batch Railway), populando `lead['ab_conversion_rates']` que vira `conversion_rates_override` em `capi_integration.py:347` (prioridade sobre `business_config.conversion_rates`).

Sintoma: 17.6% dos events do canary saíram com `value=0` (D08=R$0, D09=R$0) — exatamente os leads que pegaram path A/B Champion via shim. Os outros 82.4% saíram com value correto (path direto, sem A/B match).

Como descoberto: observação direta do canary em 10% via Q1 BQ — **não foi auditoria proativa**. Gate C v0 da sessão usava `/predict/batch` que não toca path A/B, então não pegou o bug pré-promoção.

Corrigido: Patch B (commit `4c1d727`) — populou `conversion_rates` dos dois variants com valores back-calculados de `LEAD_VALUE_BY_DECILE_CHAMPION/CHALLENGER ÷ product_value`.

Salvaguardas adicionadas no mesmo dia para fechar a classe inteira:
- **T1-17 (Gate D)** — auditoria de YAML dentro da imagem deployada (D1: business.conversion_rates não vazio; D2: variants ativos com conversion_rates não-zero). Bloqueia deploy. Detalhes em [PLANO_SAFEGUARD.md](PLANO_SAFEGUARD.md).
- **T1-18 (Gate C revisado)** — equivalência de score+decil entre revisões via `/capi/process_daily_batch?dry_run=true`, com cobertura forçada de Champion + Challenger paths. Detalhes em [PLANO_SAFEGUARD.md](PLANO_SAFEGUARD.md).
- **A/B routing em `/capi/process_daily_batch`** (commit `266d79d`) — antes só `/webhook/lead_capture` e `/railway/process-pending` faziam routing; agora os três endpoints batem. Consistência arquitetural + viabilidade do Gate C.

Drain: revisão `smart-ads-api-00412-rag` em 100% desde 08/05 ~14:25 BRT. Q1 pós-promoção: zero events value=0; D04=R$1.97, D05=R$5.62, D06=R$5.62, D08=R$6.75, D10=R$14.97 — todos batendo `LEAD_VALUE_BY_DECILE_CHAMPION`.

---

### 9. Lista de origens (`category_unification`) chegou vazia em produção

**Janela:** 30/04 → 02/05/2026 (~2-3 dias em produção).

**Causa:** `category_unification.py` grava o conjunto de categorias conhecidas em arquivo durante o treino; produção lê esse arquivo. Por divergência de path entre `train_pipeline.py` e `production_pipeline.py`, a lista chegou **vazia** em produção. Resultado: leads com origens raras (tags de criativo novo, lookalike novo, variante de campanha) tinham todas as colunas OHE de origem zeradas.

**Janela curta** porque o bug existia desde meados de março, mas só atingiu produção quando a versão atual subiu a 100% em 30/abr — antes disso o sistema rodava versão anterior do código (rollback).

**Natureza similar ao Cluster 3** (feature de origem zerando), com features distintas afetadas. Sem medição direta de dano financeiro pela curta duração, mas se soma à degradação de sinal vivenciada no mesmo período (Cluster 5, Erros 8 e 10).

**Corrigido:** 02/mai.

---

### 10. A/B otimizando em evento HQLB não aprovado pela Meta

**Janela:** 02/05 → 04/05/2026 (~2-3 dias).

**Causa:** campanha A/B subiu otimizando no evento HQLB antes de a Meta aprovar o evento no painel. Erro inicial do gestor de tráfego (subir sem aprovação), somado à ausência de monitoramento que detectasse evento não aprovado em tempo hábil.

**Gasto:** **R$ 1.444,89** na campanha *DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO API | MACHINE LEARNING | LEAD | PG2 | 2025-04-30* (id `120243354440640390`). Todo o gasto pode ser atribuído como desperdiçado — sem evento aprovado, Meta rodou só por entrega bruta.

**Diferente do Erro 8** (LQ sem `value`): aqui não havia evento algum sendo recebido pela Meta.

---

## II. Erros de implementação e infraestrutura

### 11. Erros sequenciais durante o bootstrap (Nov/25 – Fev/26)

Bugs pequenos descobertos só quando algo parava em produção. Maioria de infra/configuração/integração:

- **18/11/25:** conexão Cloud SQL com socket vs TCP errado — nenhuma consulta chegava ao banco.
- **20/11/25:** envio CAPI iterando sobre int como se fosse lista — crash silencioso interrompia envio.
- **24/11/25:** leads enviados ao Meta em duplicata — sem deduplicação por `event_id` nem por email em reprocessamento.
- **19/11/25:** FBP/FBC capturados só após submit do form — abandono no meio perdia os cookies. Solução: capturar no `pageload` via `/webhook/lead_capture`.
- **15/02/26:** crash com 1 lead — encoding categórico funcionava só com ≥2 linhas (`.str` accessor falhava em `Series` com 1 elemento de tipo não-string).
- **23/03/26:** token Guru com `|` truncado quando carregado via terminal (`|` é separador de pipe). Funcionava só via `python-dotenv`.
- **23/03/26:** credenciais `.env` carregadas em alguns entry points, ausentes em outros. Scripts CLI rodavam sem credenciais Railway/Meta, falhando sem erro claro.
- **12–13/01/26:** modelo salvo pelo `train_pipeline` em path A; `production_pipeline` e Dockerfile buscavam em path B. Deploy subia sem modelo, servidor iniciava em estado inválido.
- **22/03/26:** ID do experimento MLflow hardcoded — runs novos registrados no experimento errado.

**Padrão:** cada componente novo (banco, CAPI, MLflow, deploy) estreou com pelo menos um bug de integração que só apareceu em produção. Causa raiz: ausência de testes de integração no bootstrap.

---

### 12. Migração de banco de dados sem inventário dos pontos de integração

Quando o Cloud SQL `bring-data-db` foi descomissionado e o operacional migrou para Railway (25/02/2026), trocou-se o arquivo central de conexão **sem mapear todos os pontos do código que dependiam do banco antigo**.

Três bugs em dois dias:

- **25/02:** rotas de monitoramento da API ainda pediam conexão ao banco antigo a cada request. Banco antigo não existia mais → qualquer chamada de monitoramento retornava erro.
- **25/02 (mesmo dia):** removida dependência do banco antigo dessas rotas, mas sem garantir que passassem a usar o novo.
- **26/02:** após monitoramento corrigido para Railway, query de cobertura FBP/FBC fazia JOIN errado — resultado 0% para todos os leads.

**Causa raiz:** migração feita sem inventário prévio de todos os pontos do sistema que faziam consultas — teria permitido atualizar tudo de forma coordenada.

---

### 13. Cobertura de cookies no monitoramento — 4 tentativas para acertar o cálculo

FBP e FBC são cookies que o Meta instala no navegador ao clicar em anúncio. Quando o lead é enviado ao Meta via CAPI com esses cookies, o Meta identifica com certeza o anúncio de origem — qualidade de sinal aumenta.

Quatro correções em 03/04/2026, em sequência:

1. **Primeira:** query buscava todos os leads sem filtrar pelo período do lançamento atual — % refletia histórico inteiro.
2. **Segunda:** filtro de período no numerador, mas denominador ainda era a tabela inteira — % artificialmente baixo.
3. **Terceira:** denominador corrigido, mas a query trazia o mesmo lead várias vezes quando atualizado no banco — % inflado por dupla contagem.
4. **Quarta (correta):** dedup por email antes de contar, período correto em ambas as pontas, JOIN pela coluna certa.

**Padrão típico de cálculo incremental sem número de referência conhecido:** cada correção resolvia um problema mas criava outro porque não havia como confirmar o valor correto antes de terminar.

---

### 14. Fuso horário — bugs recorrentes em 3 componentes

Cada integração nova tratou TZ de forma independente. Resultado inconsistente:

- **17/01:** monitoramento comparava timestamps do banco (UTC) com datas do Sheets (BRT) sem converter — leads do fim do dia apareciam como dia seguinte.
- **18/02:** filtro por data no Sheets aplicava correção TZ no sentido errado (somava 3h em vez de subtrair).
- **19/02:** Railway armazena `created_at` em UTC; código de monitoramento comparava com `datetime.now()` do servidor sem converter — leads criados entre 21h e meia-noite BRT desapareciam do sumário diário.

**Causa raiz:** convenção explícita de TZ nunca foi estabelecida para o sistema.

---

### 15. UTM Source: origens não mapeadas + UTM Term reincidência (DT-13)

`utm_source` identifica origem do lead. Modelo aprende a partir das origens que existiam no treino. Origem nova em produção que não existia no treino → coluna OHE nova com valor zero para todo mundo, ruído sem benefício.

Três correções pontuais reativas:

- **20/02:** `'ig'` (Instagram informal) e `'manychat'` ausentes da lista — tratadas como origem desconhecida.
- **25/02:** `'org'` (orgânico) adicionado.
- **26/02:** `utm_source` vazio criava categoria fantasma `""` em vez de tratar como `null`.

**Reincidência em UTM Term — 22/04/2026 (DT-13).** Mesma lição em outro eixo. `core/utm.py` agrupa termos não-reconhecidos em `'outros'` via fallback. A condição tinha exceção para preservar códigos numéricos curtos, mas nenhuma categoria numérica existia na whitelist de treino — exceção só criava brecha. Em produção, `utm_term='0405'` (669 leads/dia, 16% do volume) escapava para o modelo como categoria inédita, saindo do encoding com as três features de Term zeradas. Monitoramento detectou a categoria nova, mas a lógica de unificação continuava deixando escapar. Fix de uma linha (remover exceção numérica).

**Lição:** regras de unificação UTM precisam ser whitelist estrita — o que não está na lista vai para `'outros'`, sem ramos condicionais que "preservam" casos específicos.

---

### 16. Dataset de treino com 2 erros silenciosos de preparação

Corrigidos em 06/03/2026. Existiam desde o início do projeto, identificados só durante auditoria do refactor.

**Janela de conversão com corte assimétrico:** o correto é remover do dataset todos os leads que chegaram tarde demais para terem tempo de comprar (independente do label). O código removia apenas os compradores que chegaram tarde — não-compradores que chegaram no mesmo período ficavam, criando ilusão de "leads que chegaram perto do fim raramente compram". Modelo aprendia padrão falso.

**Filtro de risco TMB aplicado na ordem errada:** filtro existia para excluir compradores TMB com histórico de inadimplência ("compras" que não se concretizaram). Mas era aplicado **depois** do cruzamento leads × vendas: esses casos já estavam marcados como `target=1` antes de serem filtrados, e ao saírem do dataset deixavam o sinal positivo com menos exemplos do que deveria, sem remover os casos contaminados que já haviam influenciado a distribuição. Correção: aplicar filtro **antes** do cruzamento.

---

### 17. Relatório de validação com contagens e receitas imprecisas

Documento principal para provar valor do sistema. Acumulou erros de cálculo durante meses, todos descobertos ao comparar com dados reais do lançamento:

- **28–30/12/2025:** contagem de leads usava dados pós-processados em vez da fonte Meta original (deduplicações divergentes). Atribuição de campanha por ID numérico isolado em vez de `(ID, conta_anunciante)` — em contas com múltiplas campanhas, leads atribuídos à campanha errada. Vendas Guru com status "não aprovado" (estornos, recusas) contadas como conversões.
- **17/01:** mapeamento conta ↔ anunciante errado ao cruzar relatórios manuais Meta com dados via API.
- **01/04:** query de leads de pesquisa com `LIMIT 10000` interno — lançamentos maiores eram truncados silenciosamente (15.000 leads viram 10.000 sem aviso).
- **02/04:** receita Asaas somada com duplicatas em alguns cenários; tabela de evolução histórica calculando variação % a partir de bases diferentes.
- **03/04:** fórmula de faturamento com ticket médio em vez de ticket real (ver Erro 1).
- **08/04:** ajustes nos filtros de valor mínimo de venda e tratamento de vendas parcialmente pagas via Asaas.

**Padrão:** relatório construído adicionando uma fonte por vez (Guru, TMB, Asaas, Meta API) sem teste de consistência que comparasse total calculado com número real a cada adição.

---

## III. Backtests de dano (mar–mai/2026)

Esta seção consolida os backtests contrafactuais executados em mai/2026 para quantificar dano dos bugs de encoding e features faltantes.

**Metodologia:** ablação por monkey-patching de `LeadScoringPredictor.model.predict_proba` para zerar colunas pós-encoding antes do scoring. Implementação em [V2/scripts/backtest_compare_models.py](V2/scripts/backtest_compare_models.py) com flag `--ablate-features`. Comparação score com/sem bug usando o run MLflow ativo na janela. Valor por decil suavizado por isotonic regression sobre referência histórica E clean para garantir monotonicidade D1→D10.

**Tabela consolidada:**

| Erro | Janela | Run ativo | Leads | Alterados | Saldo líquido | Movimentação |
|---|---|---|---|---|---|---|
| Cluster 3 — `Medium_LP` zerada | 26/mar–13/abr | jan30 (`d51757f5`) | 14.227 | +7 (~0%) | ~R$ 0 | ~R$ 0 |
| Cluster 4 — idade/salário pós-rollback | 26/mar–01/abr | jan30 | 10.576 | 2.375 (22,5%) | R$ 788 | R$ 4.451 |
| Cluster 5 — idade/salário A/B reativado | 29/abr–05/mai | jan30 | 17.425 | 4.371 (25,1%) | ~R$ 0 | R$ 8.536 |

**Insight transversal:** saldos líquidos próximos de zero **não significam ausência de dano**. O bug embaralha a ordenação dos leads em vez de empurrá-la em uma direção — rebaixamentos e promoções se compensam em valor médio. O dano real, não quantificado nestes números:

1. **Poder discriminativo degradado** durante a janela (taxa de erro >35% nos decis médios D3–D7).
2. **Eventos `LeadQualified` enviados ao Meta com decis contaminados** — leads médios entram como D9–D10 e D9–D10 reais caem para decis intermediários, contaminando o sinal de otimização da campanha.
3. **Otimização Meta perdida** durante a janela — algoritmo treinou em sinal contaminado, perdeu capacidade de buscar perfil correto. Efeito acumula no tempo.

---

## IV. Medidas corretivas implementadas (abr–mai/2026)

Todas em produção, com data de deploy verificável. Atacam o bug-raiz "deploy de modelo com 100% sem testes prévios + falhas silenciosas de encoding".

### Deploy controlado e testado
- **Progressão obrigatória 0% → 10% (1h) → 50% (24h) → 100%** com critérios de gate. Permite rollback instantâneo. *(21/abr)*
- **Smoke test pré-deploy:** 5 leads de teste reais, bloqueia deploy se score/decil/evento divergem. *(21/abr)*
- **Atalho de deploy direto a 100% removido** do código. *(02/mai)*

### Detecção de features faltando (fail-loud)
- **Validação pré-encoding:** features críticas com nome/tipo errado bloqueiam pipeline. *(23/abr)*
- ~~**Validação pós-encoding:** feature zerada em >5% dos leads gera alerta + bloqueia.~~ **STATUS REAL (verificado 08/05/2026): NÃO IMPLEMENTADA.** Existe apenas log de feature **ausente do DataFrame** em [encoding.py:337-344](../src/core/encoding.py#L337-L344) (importância ≥5% → ERROR; <5% → WARNING), mas log nunca bloqueia o pipeline e não detecta encoding **zerado** após `pd.get_dummies()`. Falsa segurança que contribuiu para Clusters 4 e 5 do Erro 2 passarem. Pendente — ver V.1.3 abaixo.
- **Painel de cobertura de features:** dashboard últimas 24h. *(23/abr)*

### Paridade treino ↔ produção
- **Auditoria automática pré-deploy:** dados do treino rodam no `production_pipeline`, comparam coluna a coluna, bloqueia se divergem. *(21/abr)*
- **Verificação na inicialização:** modelo carregado vs declarado em `configs/active_models/devclub.yaml`. *(29/abr)*
- **Reconciliação de `mlflow_run_id`:** confirma que o run em produção bate com o YAML. *(29/abr)*

### Monitoramento e alertas
- **Alerta para decis sem eventos:** D1–D10 sem evento por 24h → alerta vermelho. *(20/abr)* — preveniria Erro 3 (D9 invisível por 2 meses).
- **Encoding falha alto:** divergência de nome de coluna treino/produção falha visível em vez de silenciosa. *(20/abr)*
- **Eliminação de exceções silenciosas:** pontos com `except: pass` virados em falhas auditáveis. *(28/abr)*

### Filtros e correções pontuais
- **Whitelist de origens válidas para CAPI:** só envia evento para leads com `utm_source` rastreável. *(30/abr)*
- **Path de `category_unification` corrigido** (Erro 9). *(02/mai)*

### Itens em andamento
- Auditoria automática de paridade durante o treino (próximo retreino).
- Resolução final de categorias residuais de origem (próximo retreino).
- Retreino com importance weighting para corrigir feedback loop acumulado (Erro 6).

---

## V. Frentes preventivas em aberto

Seção viva — listar pontos de fragilidade conhecidos que **não são bug ativo hoje** mas merecem auditoria preventiva. Objetivo: tentar quebrar produção de propósito antes que ela quebre sozinha.

### V.1 — Por que parquets + smoke test pré-deploy não pegaram o Cluster 5 (idade/salário A/B reativado, 29/04)?

**Investigação concluída em 08/05/2026.** As 3 salvaguardas que existiam em 21/abr foram mapeadas. Resultado: **uma das 3 nunca foi implementada de fato (apenas declarada como entregue), e as outras 2 não cobrem o caminho A/B com `encoding_overrides`.** O bug do Cluster 5 passou pelas 3 sem disparo.

#### V.1.1 — Smoke test pré-deploy: roda no caminho default, não no A/B

**Localização:** [scripts/smoke_test_revision.py:91-107](../scripts/smoke_test_revision.py#L91-L107).
**O que faz hoje:** chama `/monitoring/daily-check/railway?hours=1` na URL da revisão alvo, processa logs `[T1-10]` e `[STARTUP CHECK]`. O endpoint inicializa `LeadScoringPipeline(client_id=client_id)` **sem contexto A/B** — não passa `encoding_overrides` nem flags de variante.
**Gap:** o Champion dentro de `/predict/batch` com A/B ativo chama `pipeline.run(..., predictor_override=predictor, encoding_overrides=champion_cfg.encoding_overrides)` ([api/app.py:1734-1738](../api/app.py#L1734-L1738)). O smoke test nunca exercita esse caminho. Hipótese **(d) confirmada**.

**Fix proposto:** smoke test deve detectar `ab_test.enabled: true` em `configs/active_models/{client}.yaml` e, quando ativo, exercitar **cada variante explicitamente** (Champion + Challenger) — chamar endpoint que respeite o roteamento A/B com payloads que caem em ambos. Comparar o output (decil + score + value) com baseline esperado por variante.

#### V.1.2 — Auditoria paridade treino↔produção: ignora `encoding_overrides`

**Localização:** [tests/parity_audit.py:182-228](../tests/parity_audit.py#L182-L228).
**O que faz hoje:** carrega `ClientConfig.from_yaml('devclub.yaml')`, chama `apply_encoding(df_input, config.encoding, artifacts={})` com `config.encoding` **padrão** e `artifacts={}` (sem feature_registry de variante).
**Gap:** o teste roda como se A/B não existisse. Quando o Champion no A/B precisa de `encoding_overrides` (caso jan30 com ordinal_variables), a auditoria passa porque está testando a configuração base, não a configuração efetiva da variante. Hipótese **(a) confirmada**.

**Fix proposto:** parity_audit deve iterar por variante ativa em `configs/active_models/{client}.yaml` quando `ab_test.enabled: true`. Para cada variante: aplicar o `encoding_overrides_merged` (config base + overrides), carregar o `feature_registry` correto, e comparar contra o output esperado da variante. Sem isso, qualquer divergência específica de variante passa silenciosa.

**Status (09/05/2026):** parte de iteração + comparação coluna-a-coluna contra snapshot por-variante implementada em T1-15 (acima). Validação contra `feature_registry` real do MLflow ainda pendente — ver T1-19.

#### V.1.3 — Validação ">5% zerados → bloqueia" não existe

**Achado mais grave:** essa salvaguarda foi **declarada como entregue em 21/abr** (Seção IV deste documento, agora corrigida) mas nunca foi implementada. O que existe em [encoding.py:337-344](../src/core/encoding.py#L337-L344) é apenas log de feature **ausente do DataFrame** (não de feature zerada após encoding) — e o log nunca bloqueia o pipeline.

**Por que importa:** o bug típico dos Clusters 3, 4, 5 do Erro 2 produz colunas que **existem no DataFrame** (`pd.get_dummies()` cria a coluna) mas chegam zeradas (sem casar com o valor esperado). O log atual não pega esse caso. Encoding zerado em 25% dos leads (Cluster 5) não dispararia nada.

**Fix proposto:** implementar de fato. Pós-encoding, para cada feature com `importance ≥ 0.03` no `feature_registry` ativo, calcular `(df[feature] == 0).mean()`. Se >X% dos leads tiverem zero E a distribuição esperada do treino tiver <X% (capturada em `distribuicoes_esperadas.json`), `raise ValueError` com nome da feature e variante. Threshold X precisa ser feature-aware: features ordinais (idade, salário) podem ter "0" como categoria válida; features OHE (Medium_*) não.

**Encaixe (formalizado em 08/05/2026):** os 3 fixes foram registrados como itens no [PLANO_SAFEGUARD.md](PLANO_SAFEGUARD.md):
- **T1-14** ✅ **Concluído (08/05/2026)** — novo endpoint `GET /smoke/run-variants` em [api/app.py](../api/app.py) busca leads do Railway e força cada variante (Champion default + variantes do `ab_test.variants`, incluindo shims) a scorear com seu `predictor_override` + `encoding_overrides`. Valida score ∈ [0,1], decis ∈ {D01..D10}, e `mlflow_run_id` casando esperado. [scripts/smoke_test_revision.py](../scripts/smoke_test_revision.py) ganhou novo gate T1-14 que bloqueia o deploy quando qualquer variante quebra.
- **T1-15** ✅ **Concluído (08/05/2026)** — nova função `audit_encoding_ab_variants` em [tests/parity_audit.py](../tests/parity_audit.py) itera por cada variante de `configs/active_models/{client}.yaml` aplicando `merge_encoding(base, variant.encoding_overrides)` antes de chamar `apply_encoding`. Por variante: (1) comparação coluna-a-coluna contra `snapshot_encoding_output_{variant}.pkl` capturado via [tests/capture_encoding_snapshots_ab.py](../tests/capture_encoding_snapshots_ab.py) — pega divergência de schema E de valor; (2) smoke checks (ordinais numéricas, sem NaN, nomes válidos) como segunda linha de defesa. `deploy_capi.sh` Gate A agora chama `--function encoding_ab`. Validação 09/05/2026: 192.386 linhas, Champion 52 colunas, Challenger 61 colunas — outputs idênticos.
- **T1-19** (follow-up de T1-15) — **alinhamento contra `feature_registry` real de cada variante (via MLflow).** Hoje `audit_encoding_ab_variants` chama `apply_encoding(df, eff_encoding, artifacts={})` com `artifacts={}`. Isso significa que a auditoria valida que o output não tem NaN, dtype certo e nomes válidos, mas **não valida que o conjunto de colunas produzidas casa exatamente com o que o modelo da variante espera consumir** (`feature_names_in_`). Se a variante registra no MLflow um `feature_registry` com 87 colunas e o `apply_encoding` mesclado produz 86 ou 88, T1-15 passa silenciosa. **Fix proposto**: para cada variante, baixar o `feature_registry.json` do `mlflow_run_id` correspondente, passar como `artifacts={'feature_registry': variant_registry}` para `apply_encoding`, e comparar `set(df_actual.columns) == set(variant_registry['feature_names'])`. Falha por divergência de schema bloqueia. Pré-condição: rotina de download de artifact do MLflow no parity_audit (não existe hoje) — T1-19 depende de Cloud SQL `smart-ads-db` estar rodando ou de cachear o `feature_registry.json` localmente sob `configs/active_models/registry_cache/{run_id}.json` no momento do `--set-active`.
- **T1-16** — validação pós-encoding ">X% zerados → raise" feature-aware (resolve V.1.3, item que estava declarado como entregue mas nunca foi implementado)

Ordem de execução recomendada: T1-14 → T1-15 → T1-19 → T1-16. T1-14 e T1-15 são independentes mas T1-15 reusa lógica de variante que T1-14 também precisa. T1-19 é a evolução natural de T1-15 — fecha o gap entre "encoding produz output válido" e "output bate com schema do modelo". T1-16 tem pré-condição de novo snapshot `distribuicoes_esperadas.json` por feature, então fica para o próximo retreino.

### V.2 — 4 features binárias passam raw sem `_normalizar`

**Estado atual (mapeado em 08/05/2026):**

| Feature (front camelCase) | Pós-`data_loader` ([validation/data_loader.py:448-458](../src/validation/data_loader.py#L448-L458)) | Em `categorias_esperadas.json` (treino jan30) | Valores canônicos |
|---|---|---|---|
| `genero` | `genero` | `'O seu gênero:'` | `['Feminino', 'Masculino']` |
| `estudouProgramacao` | `estudou_programacao` | `'Já estudou programação?'` | `['Não', 'Sim']` |
| `faculdade` | `pretende_faculdade` (sic — `df.get('fez_faculdade')`) | `'Você já fez/faz/pretende fazer faculdade?'` | `['Não', 'Sim']` |
| `investiuCurso` | `investiu_curso_online` | `investiu_curso_online` | `['Não', 'Sim']` |

**Por que ficaram fora da normalização (deliberado):** [category_unification.py:91-115](../src/data_processing/category_unification.py#L91-L115) tem comentário explícito documentando a exclusão. Modelo jan30 foi treinado com valores ORIGINAIS (com acento e capital). Passar pelo `limpar_texto` (lowercase + unidecode) quebraria o OHE — `'Não' → '_N_o'` viraria `'nao' → '_nao'`, feature inexistente no treino. Logo, **não é descuido — é a única forma de o modelo atual reconhecer essas features**.

**Por que não é bug hoje:** o front sempre manda formato exato (`'Masculino'`/`'Feminino'`, `'Sim'`/`'Não'`). Modelo protegido nas duplicações que existem hoje. Não há perda de sinal.

**Por que é armadilha latente:** se o front mandar `'sim'` minúsculo, `'SIM'` caps, ou whitespace extra, [encoding.py:265-274](../src/core/encoding.py#L265-L274) (`pd.get_dummies()` puro) gera coluna OHE inédita — **silencioso**. Mesma classe de bug do Cluster 1 (07/01: `'NÃO'` em "Tem computador?") e do Erro 15 (UTM Source/Term).

**Caminho de produção confirmado (08/05/2026):** [production_pipeline.py:212-346](../src/production_pipeline.py#L212-L346). Sequência:
1. `[1/8] _preprocess` (core/preprocessing.py) faz rename — snake → questão longa.
2. `[4/11] unify_utm` → `[5/11] _unify_medium` → `[6/11] _unify_categories` (category_unification.py — onde as 4 features são deliberadamente excluídas, ver acima).
3. `[8/12] check_category_drift` ([production_pipeline.py:333-346](../src/production_pipeline.py#L333-L346)) — quando este roda, os nomes já casam com `categorias_esperadas.json`. **Hipótese (a) confirmada: não há `missing_column` HIGH disparando hoje.**

**Status real do monitoramento das 4 features:** `check_category_drift` já cobre tecnicamente — se `'sim'` minúsculo aparecesse, dispararia `new_categories` alert. **Porém** o alerta hoje só faz `logger.warning` e armazena em `self.alerts` ([production_pipeline.py:341-344](../src/production_pipeline.py#L341-L344) — comentário literal: *"Armazenar alertas para enviar depois (implementação futura)"*). Não chega ao Slack. Em outras palavras: o sensor existe; o cabo do alarme até a sirene não foi puxado.

**Mitigação proposta — 3 vetores:**
1. **Fail-loud no encoding (seguro, sem retreino):** validação em [encoding.py:265-274](../src/core/encoding.py#L265-L274) antes do `get_dummies`. Se valor fora de `{Sim, Não, Masculino, Feminino}` aparece em >0 leads, bloqueia e loga.
2. **Normalização em `data_loader` (precisa retreino):** novo `_normalizar_categorico_binario` (strip + lower) em `core/`, aplicado em treino E produção. Exige retreinar para que o modelo aprenda com valores normalizados — não pode ser inserido sozinho em produção (quebraria jan30).
3. **Alerta de monitoramento (defesa em profundidade):** `check_binary_feature_canonical_values` em `monitoring/data_quality.py` com dict explícito `{coluna: [valores_canônicos]}`. Alerta no Slack se valor fora aparece. Não bloqueia — apenas avisa.

**Decisão na sessão de 08/05/2026:** atacar o vetor 3 primeiro (defesa em profundidade). Bloqueador antes de implementar: confirmar onde inserir o check no caminho de produção — se nomes são snake (pós-`data_loader`) ou longos (pós-renomeação a localizar) na hora em que o check rodar.

**Implementado (08/05/2026) — vetor 3 fechado:** sem criar check novo. `check_category_drift` já cobre tecnicamente as 4 features (nomes alinhados pós-`_preprocess`). Lacuna real era leitura humana — alerts ficavam diluídos na lista completa do response. Mudanças aplicadas:
- [orchestrator.py:215-237](../src/monitoring/orchestrator.py#L215-L237) — `alerts` ordenados por severity desc (HIGH → MEDIUM → LOW) + novo subset `actionable_alerts` (HIGH+MEDIUM, formato compacto `{type, severity, category, column, percentage, message}`).
- `DailyCheckResponse` em `api/app.py:79-93` ganhou o campo `actionable_alerts` (default `[]`).
- Endpoints `/monitoring/daily-check/railway` e `/monitoring/daily-check` passam o campo.

**Vetores 1 e 2 ainda em aberto:**
- Vetor 1 (fail-loud no encoding) — não implementado. Próximo passo se a V.2 ressurgir.
- Vetor 2 (normalização + retreino) — formalizado como **DT-18** em [PLANO_REFACTOR_MLOPS.md](PLANO_REFACTOR_MLOPS.md) com bloqueio crítico documentado: **fix isolado em produção quebra Champion legado `jan30`** (100% das 4 features zeradas pra todos os leads, ~8% do peso do modelo). Pré-requisito: retreino do Champion com código novo. **A/B com Challenger usando código novo é condicional ao retreino do Champion** — sem isso, leads que caem no Champion ficam expostos à variação de casing. Cross-refs no checklist de [onboarding](CHECKLIST_ONBOARDING_NEW_CLIENT.md) e em [PLANO_EXECUCAO.md M4](PLANO_EXECUCAO.md).

### V.3 — Backlog "tentar quebrar produção"

Lista aberta de cenários a estressar. Cada item: descrição + verificação proposta + status.

- [ ] **Front muda casing de feature binária** (`'sim'` em vez de `'Sim'`) — verificar se o modelo a recebe ou se vira OHE nova. Cobertura: V.2.
- [ ] **Categoria nova de UTM Term** que escapa do fallback de `core/utm.py` — verificar se o monitoramento atual detecta antes de degradar score (DT-13 mitigou, mas a classe do bug persiste se aparecer em outros eixos).
- [ ] **Lead com 1 único registro em batch** — `.str` accessor falha com tipo não-string (Erro 11, fev/26). Verificar se `_railway/process-pending` ainda quebra com batch=1 e UTM não-string (memória `projeto_bug_railway_polling_str.md` indica que sim — auto-recupera no próximo poll).
- [ ] **Deploy de modelo com `mlflow_run_id` no YAML mas artefato ausente no GCS** — verificar se a inicialização do servidor falha alto (Erro 11 — modelo salvo em path diferente).
- [ ] **Token Guru renovado com `|` na nova string** — verificar se o load via `python-dotenv` continua robusto.
- [ ] **`utm_source` recebido como `null` vs `""` vs ausente** — verificar se as 3 variações vão todas para a mesma categoria no encoding (Erro 15 trata `""`, mas vale revalidar).
- [ ] **Lead com TZ na borda (23h59 BRT)** — verificar se aparece no dia correto em todos os componentes (monitoramento, retreino, relatório de validação) — Erro 14 era em 3 lugares.
- [ ] **A/B com 100% no Challenger e 0% no Champion** — verificar se as salvaguardas de paridade do Champion ainda disparam (cenário de "esvaziar Champion").
- [ ] **Feature crítica com >5% de NaN em vez de 0** — verificar se a validação pós-encoding também bloqueia, não só zeros.
- [ ] **Categoria de Medium nova que escapa de `core/medium.py`** — Cluster 3 era `Medium_Linguagem_programacao`. E se aparecer `Medium_Banco_de_Dados`?
- [ ] **`Lead.pesquisa` jsonb com chave nova** que o `core/feature_engineering` não trata — verificar comportamento (silencioso ou fail-loud?).
- [ ] **Cloud SQL MLflow parado durante retreino agendado** — verificar se a parada explícita (`activation-policy=NEVER` desde 26/abr) é detectada antes do treino tentar conectar.

**Critério para tirar do backlog:** cenário foi reproduzido em ambiente de staging ou validado por leitura de código + execução parcial; resultado documentado nesta seção; mitigação implementada (ou aceita como risco residual com justificativa).

### V.4 — Ausência de check de drift de perfil de audiência vs Top 5 ROAS no monitoring (descoberto 08/05/2026)

**Estado atual:** o `DataQualityMonitor` em [src/monitoring/data_quality.py:397](../src/monitoring/data_quality.py#L397) só compara distribuições contra `distribuicoes_esperadas.json` capturado **no treino**. Não há nenhum check contra um perfil de audiência **winner histórico** (ex.: Top 5 ROAS). Resultado: drift de público que afeta diretamente performance de lançamento passa silencioso até alguém abrir uma análise ad-hoc.

**Como foi descoberto:** comparação manual em 08/05/2026 do LF54 em captação contra Top 5 ROAS histórico (LF40, LF41, LF44, LF45, LF47, n=39.771) revelou shift forte e estatisticamente robusto:
- "Sem computador": 12,5% → 22,9% (+10,4pp, ⚠⚠)
- Feminino: 18,3% → 28,0% (+9,7pp, ⚠⚠)
- CLT/funcionário público: 44,9% → 35,6% (−9,3pp, ⚠⚠)
- "Já estudou programação Sim": 36,8% → 30,9% (−5,9pp, ⚠⚠)
- Tudo com chi² p < 1e-4.

**Por que conta como erro:** o monitoring deveria ter levantado essa bandeira automaticamente. Não levantou. Cada lançamento entre o último Top 5 ROAS e hoje rodou às cegas para esse drift. Drift de público é causa direta de queda de ROAS — e o sistema atual não tem antena para isso.

**Mitigação proposta (T1-13):** novo check method `audience_profile_drift` em `DataQualityMonitor`, comparando o último dia completo de captação contra snapshot estático do Top 5 ROAS (`configs/clients/devclub/reference_audience_profile.json`). Threshold ⚠ ≥ 5pp por categoria canônica; severity HIGH se ≥ 5pp nas 5 features socioeconômicas críticas (computador, gênero, ocupação CLT, programação, cartão). Especificação completa em [PLANO_SAFEGUARD.md § T1-13](PLANO_SAFEGUARD.md). Prioridade máxima registrada em [PLANO_EXECUCAO.md § H4 — Sequelas 08/05/2026](PLANO_EXECUCAO.md).

**Lição estrutural:** monitoring de drift contra "snapshot do treino" é necessário mas não suficiente. Treino antigo + drift de público = baseline cego. Faltava monitoring contra um pool histórico de **performance** (não apenas estatístico).

---
