# Plano unificado — emissão de eventos CAPI e recalibração de decis

**Criado:** 2026-06-07
**Papel:** plano integrador que orquestra duas frentes que tocam o mesmo subsistema (emissão de eventos CAPI por lead) e antes corriam o risco de colidir. Fan-out atual de eventos HQ em pixels adicionais (cliente-level) + recalibração futura de decis por retorno esperado por real gasto (ROAS V1) viram um único plano com seis blocos sequenciados.
**Origem:** unificação de [FAN_OUT_CAPI.md](FAN_OUT_CAPI.md) (mecanismo de fan-out, vivo em canary) + sessão de desenho com `/sw-architect` em 2026-06-07 (especificação da recalibração de decis por ROAS).

> O documento de fan-out permanece vivo como artefato técnico de detalhe do mecanismo de cópia em pixels extras. Este plano é o "como" orquestrado de todo o subsistema — o caminho que cada bloco de trabalho percorre e a ordem em que entram.

---

## Sumário em uma frase

Cada lead deixa o scoring carregando uma lista de **atribuições** (decil + nome do evento primário + pixel principal), uma por estratégia habilitada (hoje só Propensão; em breve Propensão e ROAS V1 em paralelo); cada atribuição dispara seu evento primário e o **laço de fan-out já existente** copia em pixels adicionais declarados no `extra_hq_destinations` do cliente — sem mecanismo paralelo, sem segunda fonte de verdade para "qual evento copia em qual pixel".

---

## 1. Diagnóstico das duas frentes

### 1.1 Frente do fan-out — pedido do dono em 2026-06-07

O dono pediu que os eventos de alta qualidade (`LeadQualifiedHighQuality` do Champion e `HQLB` do Challenger) voltassem a chegar no pixel `241752320666130` (BM do Rodolfo Mori), por onde o gestor de tráfego precisa cadastrar campanhas que otimizem nesses sinais.

Mecanismo implementado: lista declarativa `capi.extra_hq_destinations` em [configs/clients/devclub.yaml](../configs/clients/devclub.yaml), parseada para uma dataclass `ExtraHQDestination` em [src/core/client_config.py](../src/core/client_config.py), e consumida por um laço dentro de `send_both_lead_events` em [api/capi_integration.py](../api/capi_integration.py). Para cada destinação cujo `event_name` case com o evento HQ que efetivamente saiu, dispara cópia reusando `send_lead_qualified_high_quality` com overrides de pixel, nome de evento e faixa de decis.

**Estado em 2026-06-07:** canary `smart-ads-api-00680-jez` a 0% de tráfego, gates B/D/C.1/C.2 passados (50 leads cada, zero divergências contra produção). Aguardando autorização para promoção.

**Por que o desenho é cliente-level e não variante-level:** a regra "pixel destino para cópias adicionais" não depende de qual variante A/B pontuou o lead — Champion e Challenger têm pixels principais distintos, mas ambos espelham no mesmo pixel adicional. Uma primeira tentativa que colocou essa regra no nível variante (commit `e52469c`, revertida em `06e97ba` em 2026-05-27) precisou tocar sete arquivos para propagar o destino extra pela cadeia inteira; o desenho atual toca três e a informação é lida diretamente onde é usada. Detalhe completo do diagnóstico vive em [FAN_OUT_CAPI.md](FAN_OUT_CAPI.md) seção 2.

### 1.2 Frente da recalibração de decis por ROAS — sessão atual

Hipótese de negócio: o modelo está bom em rankear quem compra, mas o custo por lead na Meta está caro; a métrica de seleção (que decide quem entra no top decil e portanto recebe o evento de alta qualidade) precisa pesar custo, não só probabilidade de compra.

Análise offline em worktree separado (`bring_data-roas`):

- Descobriu-se que o `utm_campaign` que a Meta grava em todo lead carrega o identificador da campanha no sufixo (depois da barra vertical) — chave que permite casar custo ao lead com unicidade contra campanhas reaproveitadas com mesmo nome.
- Atribuição de custo por lead via composite key `(campaign_id, ad_name)` casado contra o spend da Meta API por adset por dia atingiu 82,8% de cobertura, mediana R$ 5,35 — alinhada ao histórico do gestor de R$ 4-6.
- Aplicando a fórmula `retorno_esperado = (probabilidade × ticket à vista) ÷ custo_por_lead` para reordenar os top-N, o ganho líquido anual projetado fica entre R$ 86 mil (top 10%) e R$ 298 mil (top 50%), usando faturamento recebido à vista (cartão líquido + primeira parcela do boleto, mesma fórmula do `_generate_revenue_forecast` em [src/monitoring/orchestrator.py](../src/monitoring/orchestrator.py)) e corrigindo por uma taxa de rastreamento de 52,8% das vendas reais que de fato casam com um lead nosso.
- Validação por bootstrap em mil iterações: correlação de Spearman entre decil predito e ROAS realizado fica em \[0,92, 1,00] na fórmula nova vs \[0,45, 0,90] na propensão pura.

PDF para stakeholders em [propostas_e_apresentacoes/descoberta_roas_devclub.pdf](../propostas_e_apresentacoes/descoberta_roas_devclub.pdf).

**Estado em 2026-06-07:** especificação arquitetural pronta, zero código em produção.

### 1.3 Onde as duas frentes se cruzavam

Três pontos de colisão identificados durante o desenho com `/sw-architect`:

1. **Mesmo arquivo, mesma função.** As duas frentes mexem em [api/capi_integration.py](../api/capi_integration.py), especificamente em `send_both_lead_events`. O fan-out introduziu um laço logo após o disparo do evento HQ primário; o desenho original da recalibração propunha refatorar a função inteira para usar um conceito novo (chamado então de `EventEmitter`).

2. **Dois mecanismos para o mesmo problema.** "Quais pixels recebem qual evento" estava modelado de duas formas: lista declarativa `extra_hq_destinations` no YAML do cliente (fan-out) versus mapping bipartido `(estratégia, variante) → {decil: nome_do_evento}` em uma classe nova (recalibração). Duas fontes de verdade para a mesma decisão tendem a divergir.

3. **Risco de órfão silencioso.** A própria seção 10 do [FAN_OUT_CAPI.md](FAN_OUT_CAPI.md) antecipou: se a refatoração da recalibração substituísse `send_both_lead_events` por uma função genérica nova, o laço de fan-out continuaria fisicamente no código mas ninguém o chamaria — eventos extras parariam de chegar no pixel destino sem nenhum erro visível.

---

## 2. Decisão arquitetural da fusão

Resolvida a partir dos princípios da skill `/sw-architect` (uma fonte de verdade por conceito; direção das dependências; reuso antes de criar paralelo):

**O conceito `EventEmitter` proposto no desenho original da recalibração morre.** O comportamento que ele cobriria já sai naturalmente da combinação de dois componentes que vão existir de qualquer jeito:

- A interface de estratégia de decil (PropensityDecileStrategy hoje, RoasV1DecileStrategy depois) já retorna, no método `assign`, o trio `(decil, nome do evento primário, pixel principal)` — quem decide qual evento primário sai é a própria estratégia, lendo a configuração de variante que já existe em [configs/active_models/devclub.yaml](../configs/active_models/devclub.yaml).
- O laço de fan-out já existente é a única autoridade sobre "cópias em pixels extras", lendo `extra_hq_destinations` do cliente. Funciona idêntico para qualquer evento primário que passe por ele — Propensão hoje, ROAS V1 amanhã, qualquer outro depois.

Consequências práticas dessa decisão:

1. **Uma única fonte de verdade para "qual pixel destino"** continua sendo `capi.extra_hq_destinations` no YAML do cliente (cliente-level, como o fan-out já estabeleceu).
2. **Mapping decil → nome do evento vive dentro de cada estratégia de decil** (hardcoded na classe, não em YAML). PropensityDecileStrategy lê os campos `event_name_high_quality` e `pixel_id` da variante; RoasV1DecileStrategy lê os mesmos campos e adiciona o sufixo `_ROAS_V1` no nome do evento.
3. **`send_both_lead_events` é envolvida, não refatorada profundamente.** Vira `send_all_lead_events`, que itera sobre N atribuições (uma por estratégia habilitada) e, para cada uma, dispara o primário + roda o laço de fan-out idêntico ao atual. Zero risco de órfão.
4. **As duas frentes ficam independentes na linha do tempo.** Fan-out atual promove a 100% sem esperar pela recalibração; recalibração entra meses depois sem mexer no fan-out.

---

## 3. Fluxo do lead — desenho fundido

Cada lead, na cadeia de scoring de [api/capi_integration.py](../api/capi_integration.py):

1. Recebe a variante (Champion ou Challenger) pelo `pipeline.get_ab_variant(utm)`.
2. `pipeline.run` pontua o lead — retorna score bruto.
3. **Loop sobre as estratégias de decil habilitadas** do cliente. Cada uma:
   - Recebe o score, as features do lead e a configuração da variante.
   - Retorna uma atribuição: `(decil, nome_do_evento_primário, pixel_principal)`.
4. **Loop sobre as atribuições produzidas.** Para cada uma:
   - Dispara o evento primário (com overrides apontando para o pixel da atribuição).
   - Executa o laço de fan-out atual: para cada `extra_hq_destinations` cujo `event_name` case com o evento primário que acabou de sair, dispara cópia no pixel adicional declarado.
5. Registra no `registros_ml` todas as atribuições, todos os eventos primários disparados, todas as cópias de fan-out disparadas, e a origem do custo usado (quando aplicável).

**Estado hoje (antes do bloco F deste plano):** apenas PropensityDecileStrategy está habilitada. O loop executa uma volta. Comportamento idêntico a `send_both_lead_events` mais o fan-out atual.

**Estado depois (com RoasV1 ligada):** PropensityDecileStrategy + RoasV1DecileStrategy executam em paralelo. Para o mesmo lead, podem sair eventos primários distintos (ex.: `LeadQualifiedHighQuality` no pixel do Champion + `LeadQualifiedHighQuality_ROAS_V1` no mesmo pixel ou em outro, dependendo da decisão de pixel da estratégia). O fan-out copia ambos para o pixel destino do BM, desde que entradas correspondentes existam em `extra_hq_destinations`.

---

## 4. Plano em seis blocos

Cada bloco entra em sequência depois do anterior estar estável em produção. As setas indicam dependências obrigatórias.

### Bloco A — Estabilização do fan-out atual (independente, prioritário)

Está em canary, atende ao pedido do dono, não depende de nenhum trabalho de recalibração para chegar a 100% de tráfego.

**Trabalhos:**
- Cadastrar os eventos `LeadQualifiedHighQuality` e `HQLB` no Events Manager do pixel `241752320666130` por disparo de teste com `test_event_code`. Sem cadastro, a Meta drop silenciosamente.
- Validar 2-3 leads de teste produzindo cópias no pixel destino.
- Promover a revisão canary para 100% de tráfego.
- Adicionar testes unitários pendentes em `V2/tests/test_fan_out_hq.py` cobrindo: lista vazia → sem chamada extra; match → cópia disparada com overrides corretos; mismatch → sem cópia; falha em uma destinação não derruba as outras; parser fail-loud rejeita YAML inválido. Detalhe completo em [FAN_OUT_CAPI.md](FAN_OUT_CAPI.md) seção 11.1.

**Critério de avanço:** revisão a 100% por 48h sem incidente; volume de cópias para `241752320666130` consistente com volume de eventos HQ primários disparados.

### Bloco B — Lookup de custo por lead (não toca caminho do lead)

Camada de dados nova que vai alimentar a fórmula da recalibração. Isolada do caminho do lead — pode ser construída e validada sem qualquer mudança no fluxo de scoring.

**Trabalhos:**
- Schema: duas tabelas novas no **Railway** (mesma instância de `registros_ml`, `lead_surveys`, `UTMTracking` — banco operacional que o scoring container já conecta). **Não** Cloud SQL `smart-ads-db`, que hospeda só MLflow tracking e fica parado entre treinos; obrigá-lo a ficar 24/7 ligado pra servir CPL custaria ~R$ 35/mês a mais sem ganho operacional.
  - `cpl_adset` — chave `(client_id, adset_id)`, colunas `cpl_30d`, `n_leads_30d`, `spend_30d`, `campaign_id`, `window_start`, `window_end`, `updated_at`.
  - `ad_to_adset_map` — chave `(client_id, campaign_id, ad_name)`, coluna `adset_id`, `updated_at`. Resolve a ambiguidade de nome de anúncio reaproveitado em campanhas distintas.

  **Nota — por que `utm_medium` não substitui a `ad_to_adset_map`:** verificação contra o snapshot 120d em 2026-06-07 mostrou que `utm_medium` tem cobertura ótima (98,6%) mas é **categoria de público** no DevClub (`ABERTO`, `MIX QUENTE`, `dgen`, `Linguagem de programação`), não identificador de adset — 61% do volume vive num bucket `ABERTO` espalhado por **74 adsets reais distintos**, indistinguíveis por medium. A `ad_to_adset_map` é justamente o que abre esses 74 em CPLs próprios, via casamento `(campaign_id, ad_name) → adset_id`.
- Repositório `CplRepository` em [src/data/cost_attribution/](../src/data/cost_attribution/) — interface mais adapter Railway mais adapter em memória (carregado no startup do container, lookup de microssegundos no hot path).
- Resolver `AdResolver` — adaptador `(campaign_id, ad_name) → adset_id` consumindo `ad_to_adset_map`.
- Job de refresh — entry point standalone que puxa Meta Insights API agregando spend e leads dos últimos 30 dias por adset, calcula `cpl_30d`, faz upsert nas duas tabelas. Idempotente.
- Infra do refresh — **Cloud Scheduler → endpoint HTTP no `smart-ads-api`** (mesmo padrão do polling Railway e do monitoramento diário), 1×/dia às 04:00 BRT. Custo praticamente zero, reusa container já rodando, sem Cloud Run Job dedicado.

**Critério de avanço:** job rodando há pelo menos uma semana, tabelas com >800 adsets atualizados em <48h, sem falhas consecutivas; CPL p50 em DevClub na faixa de R$ 4-6 (validação contra histórico do gestor).

**Decisões deliberadas que ficam fora do bloco:** não criar instância de banco nova, não criar Pub/Sub para invalidar cache em memória (TTL de 24h é suficiente), não extrair um `MetaInsightsClient` compartilhado com o `campaign_classifier` ainda (faz quando quota Meta apertar; padrão "padrão pelo padrão é overengineering" da `/sw-architect`).

### Bloco C — Estratégia de decil como interface

Refator preparatório do scoring para aceitar múltiplas estratégias de decil sem mudar comportamento. Sai um arquivo de produção com paridade 100% contra o comportamento atual.

**Trabalhos:**
- Definir interface `DecileStrategy` em [src/core/](../src/core/) (ou diretório a ser combinado com o já existente do scoring). Método único `assign(score, features, variant_config, lead_id)` retornando uma dataclass `DecileAssignment` com decil, identificador da estratégia, nome do evento primário, pixel principal e metadados de observabilidade.
- Implementar `PropensityDecileStrategy` extraindo a lógica de "qual decil vira qual evento" que hoje vive inline em `send_both_lead_events`. Lê `variant_config.event_name_high_quality` e `variant_config.pixel_id`.
- Testar paridade: rodar pelo menos 10 mil leads pelo fluxo antigo e pelo fluxo novo (com `PropensityDecileStrategy` como única estratégia habilitada), asseverar 100% mesmo decil e mesmo evento primário.

**Critério de avanço:** teste de paridade em staging passa com 0 divergências em batch de 10k leads.

### Bloco D — Adapter de transição (zero risco de órfão)

Introduz o caminho que itera sobre múltiplas atribuições, mantendo o ponto de entrada antigo intacto para os consumidores externos da função.

**Trabalhos:**
- Criar `send_all_lead_events` em [api/capi_integration.py](../api/capi_integration.py). Assinatura recebe uma lista de `DecileAssignment` + os mesmos parâmetros de identidade do lead que `send_both_lead_events` já recebe.
- Para cada atribuição: dispara primário com overrides apontando para o pixel principal da atribuição; executa o **laço de fan-out atual idêntico**, lendo `extra_hq_destinations` e copiando onde o `event_name` casar.
- `send_both_lead_events` vira adapter: monta uma lista com uma única atribuição da `PropensityDecileStrategy` e chama `send_all_lead_events`. Comportamento externo idêntico a hoje.
- Atualizar os callers de `send_both_lead_events` somente se houver ganho claro (por exemplo, evitar dupla pontuação do mesmo lead). Não obrigatório para entrar em produção — a função antiga continua funcional.

**Critério de avanço:** canary com a refatoração roda por 48h em paridade contra produção; volume de eventos disparados e taxa de fan-out idênticos ao período anterior.

### Bloco E — Observabilidade unificada

Estende o ledger `registros_ml` para registrar o que cada estratégia decidiu e o que efetivamente saiu para a Meta. Resolve a pendência aberta em [FAN_OUT_CAPI.md](FAN_OUT_CAPI.md) seção 11.2 (observabilidade do fan-out) no mesmo movimento.

**Trabalhos:**
- Migração aditiva no schema do `registros_ml`:
  - `decile_propensity INTEGER` — decil da estratégia de propensão (sempre populado).
  - `decile_roas_v1 INTEGER` — decil da estratégia ROAS V1 (null enquanto desabilitada).
  - `cpl_source TEXT` — origem do CPL usado: `adset`, `campaign`, `global`, ou `missing`. Permite medir cobertura da atribuição em produção.
  - `events_fired TEXT[]` — array de nomes dos eventos efetivamente disparados (primários, todos eles).
  - `extra_hq_destinations_fired JSONB` — sub-array das cópias de fan-out, com `event_name` e `pixel_id` de cada cópia.
- Logs estruturados nas novas funções, prefixados para serem filtráveis no Cloud Logging.

**Critério de avanço:** colunas populadas para 100% dos leads novos após o deploy; querys de sanidade reproduzem volume de eventos visto no Events Manager da Meta.

### Bloco F — Ativação da estratégia ROAS V1 e cópia no pixel destino [ARQUIVADO 2026-06-10]

> **Frente arquivada.** Verificação empírica em 6 lançamentos (LF48-53, 129 vendas) testando 12 estratégias de atribuição de CPL (3 granularidades × 4 janelas) não mostrou ganho consistente vs ranking por score puro. O ganho que motivou a frente foi artefato do snapshot agregado, não se sustenta por LF. Detalhes na seção 8 (Histórico), entrada de 2026-06-10. Texto abaixo preservado pra contexto histórico do desenho original.

Liga a recalibração em produção. Eventos novos saem com sufixo no nome (`_ROAS_V1`); cópia no pixel destino do BM passa a sair adicionando uma linha no YAML do `extra_hq_destinations`.

**Trabalhos:**
- Implementar `RoasV1DecileStrategy` consumindo `CplRepository` e `AdResolver` por injeção. Fórmula `retorno_esperado = (probabilidade × ticket à vista) ÷ cpl_adset`. Fallback explícito quando o adset não tem 30d de histórico: CPL médio da campaign, depois CPL global do cliente, depois ordenação por propensão pura. Origem registrada em `cpl_source`.
- Adicionar bloco no YAML do cliente:
  ```yaml
  decile_strategies:
    - id: roas_v1
      enabled: false   # kill switch
      event_name_suffix: "_ROAS_V1"
      fallback_on_missing_cpl: propensity
  ```
  Com `enabled: false`, RoasV1DecileStrategy é instanciada mas não atribuída ao `send_all_lead_events`. Lead continua com uma só atribuição.
- Cadastrar os eventos novos (`LeadQualifiedHighQuality_ROAS_V1` e/ou `HQLB_ROAS_V1`, dependendo de em qual variante a estratégia roda — recomendado começar só por Champion, isolar uma variável) no Events Manager da Meta tanto do pixel principal quanto do pixel destino do BM.
- Adicionar as entradas correspondentes em `extra_hq_destinations` do `devclub.yaml`. Exemplo:
  ```yaml
  extra_hq_destinations:
    - event_name: LeadQualifiedHighQuality
      pixel_id: "241752320666130"
      decils: ["D09", "D10"]
    - event_name: HQLB
      pixel_id: "241752320666130"
      decils: ["D08", "D09", "D10"]
    - event_name: LeadQualifiedHighQuality_ROAS_V1   # adicionado quando ROAS V1 for ligada
      pixel_id: "241752320666130"
      decils: ["D09", "D10"]
  ```
- Virar o kill switch para `enabled: true`. Lead passa a receber duas atribuições; fan-out copia ambos os eventos primários para o pixel do BM.

**Critério de avanço:** decisão go/no-go baseada em ROAS realizado por estratégia analisado em `registros_ml` ao longo de 4 semanas, com critério de significância a ser definido caso a caso.

### Pendência crítica antes do bloco F — calibração de probabilidades é pré-requisito não-negociável

A fórmula `(probabilidade × ticket à vista) ÷ custo` assume que o número que entra no lugar da probabilidade é, de fato, uma probabilidade. O `leadScore` do RF treinado com `class_weight='balanced'` **não é** probabilidade real de compra — é uma medida de ordenação. Quando o leadScore entra direto na multiplicação (como pretende a fórmula nova no nível do lead), a distorção entra na decisão econômica.

**Status atualizado em 2026-05-08.** A primeira parte da pendência (medir quanto os modelos atuais estão miscalibrados e qual o impacto de não calibrar) foi executada. Os critérios originalmente propostos — interseção do top 10% e Spearman ρ entre rankings — foram revistos e descartados porque a calibração isotônica preserva ordenação por construção (é monotônica): ambos os critérios passam quase automaticamente em qualquer calibrador isotônico, sem dizer nada sobre miscalibração. Substituídos por Expected Calibration Error (ECE).

#### Medições já feitas

Análise empírica completa em [`analise_calibracao_jan30_abr28.md`](analise_calibracao_jan30_abr28.md), baseada nos `model_metadata.json` salvos no treino original (33k leads no test set do Champion, 40k no test set do Challenger).

- **Champion `jan30`:** ECE pré-calibração de 26.32 pp. Decis críticos D8-D10 com ECE de 43.43 pp. Razão de inflação D10 = 33× (score 0.578 versus probabilidade real 0.018).
- **Challenger `abr28`:** ECE pré-calibração de 39.58 pp. Decis críticos D8-D10 com ECE de 53.87 pp. Razão de inflação D10 = 27× (score 0.615 versus probabilidade real 0.023).
- **Direção do viés:** superestimação sistemática em todos os decis. Confirma efeito mecânico do `class_weight='balanced'`.

Comparado com a faixa de referência da literatura (ECE < 5 pp = bem calibrado; > 10 pp = severamente miscalibrado), os dois modelos estão entre cinco e oito vezes acima do limite "severamente miscalibrado". A calibração precisa entrar antes da ativação do bloco F.

#### Bloqueante remanescente — validação out-of-sample do calibrador

A medição feita usou apenas o test set do treino original. Mostra que a calibração **vai** corrigir o gap nos dados onde os modelos foram treinados. **Não responde** se a função de calibração ajustada nesses dados antigos continua válida em leads recentes (drift de público desde então pode ter mudado a relação score → probabilidade real). A análise atual é cota superior do ganho; out-of-sample mede o ganho real disponível em produção.

**Trabalho bloqueante antes do bloco F:**

1. Pegar leads dos últimos 30 a 60 dias do Railway com label real de conversão (matching com vendas).
2. Rodar `predict_proba` do Champion e Challenger atuais nesses leads.
3. Aplicar a função isotônica ajustada nos dados antigos (test set do treino original) sobre esses scores recentes.
4. Medir o ECE residual entre `score_calibrado` e probabilidade real observada em bins de 10 ou 20.

**Critério de decisão do bloco F:**

- ECE residual out-of-sample ≤ 5 pp em ambos os modelos → calibração generalizou. Pode prosseguir com bloco F após implementação técnica do calibrador no pipeline (DT-20).
- ECE residual > 5 pp e ≤ 10 pp → calibração ajuda mas há drift adicional. Avaliar se o ganho ainda vale; eventual decisão de recalibrar periodicamente (a cada N lançamentos) entra no escopo do bloco F.
- ECE residual > 10 pp → drift de público pós-treino é dominante. Calibração ajustada uma vez não basta; bloco F precisa de mecanismo de recalibração contínua antes de ligar.

Em todos os cenários acima a Spearman ρ tende a ser ≈ 1.0 e a interseção do top 10% ≈ 100% — esses critérios continuam não discriminando e foram removidos.

#### Coordenação

A implementação técnica do calibrador no pipeline (interface `Calibrator`, integração com `LeadScoringPredictor`, script de calibração pós-hoc, bloco `scoring.calibration` no YAML do cliente) está catalogada como **DT-20** em `PLANO_REFACTOR_MLOPS.md`. A validação out-of-sample descrita acima é pré-requisito para promover qualquer calibrador a produção e bloqueante do bloco F.

---

## 5. Rollback unificado

| Cenário | Ação | Tempo |
|---|---|---|
| Bug em alguma cópia de fan-out | Deletar a entrada correspondente em `extra_hq_destinations` no YAML do cliente, redeployar | Segundos |
| Bug na `RoasV1DecileStrategy` | `enabled: false` no bloco `decile_strategies`, redeployar | Segundos |
| Bug na refatoração de `send_both_lead_events` para `send_all_lead_events` | Reverter o commit do bloco D | ~15 min |
| Job de refresh do CPL falhando em cadeia | Lookup em memória continua usando o último snapshot conhecido até 48h; alerta dispara após esse prazo | Manual, horas |
| Tabela `cpl_adset` corrompida | `DROP` + recriar + rodar o refresh manualmente (idempotente) | ~5 min |
| Decisão estratégica de abandonar a recalibração | Kill switch permanente `enabled: false`; código fica vivo por 3 meses como exit option | Sem urgência |

---

## 6. Vínculo com o roadmap único

Conforme [CLAUDE.md](../CLAUDE.md) e a hierarquia descrita em [PLANO_EXECUCAO.md](PLANO_EXECUCAO.md): este documento é um **catálogo técnico** ("como"). O **quando** vive no `PLANO_EXECUCAO.md`. Quando houver divergência de prioridade ou status, vence o `PLANO_EXECUCAO`.

- **Bloco A** entra no horizonte imediato — já em canary, atende ao pedido do dono de 2026-06-07.
- **Blocos B–E** são candidatos a horizonte futuro; depende da priorização de `PLANO_EXECUCAO` contra o gate único (validação OOS) e os pré-requisitos do segundo cliente.
- **Bloco F** depende de o bloco E estar estável e da pendência crítica (análise de divergência leadScore vs probabilidade calibrada) ter sido resolvida.

---

## 7. Princípios que não devem ser violados ao longo da execução

1. **Fonte de verdade única para "qual pixel destino"** continua sendo `capi.extra_hq_destinations`. Não criar tabela paralela, não modelar pixel destino dentro de `DecileStrategy`.
2. **A regra do fan-out é cliente-level**, não variante-level. Repetir o erro custou sete arquivos na primeira tentativa, revertida em 2026-05-27.
3. **`send_both_lead_events` é envolvida, não substituída.** O laço de fan-out atual permanece idêntico — só passa a ser executado uma vez por atribuição produzida pela cadeia de estratégias.
4. **Eventos novos não sobrepõem eventos existentes.** `LeadQualifiedHighQuality_ROAS_V1` é nome novo, evento novo no Events Manager. Quem otimiza no antigo continua otimizando; quem quiser testar o novo cadastra campanha separada.
5. **Default vazio é no-op para qualquer mecanismo.** Cliente sem `extra_hq_destinations` mantém comportamento legado; cliente sem `decile_strategies` mantém só PropensityDecileStrategy. Comportamento herdado é o caminho sem configuração nova.

---

## 8. Histórico

- **2026-05-27** — Primeira tentativa de fan-out, no nível variante. Sete arquivos mexidos, revertida no mesmo dia. Aprendizado registrado em [FAN_OUT_CAPI.md](FAN_OUT_CAPI.md) seção 2.
- **2026-06-07 manhã** — Desenho de cliente-level do fan-out via `/sw-architect`. Implementação em três arquivos. Canary deployada a 0% tráfego em `smart-ads-api-00680-jez`.
- **2026-06-07 sessão analítica paralela** — análise offline da recalibração de decis por ROAS no worktree `bring_data-roas` valida ganho de R$ 86k-R$ 298k anuais. PDF para stakeholders gerado.
- **2026-06-07 final do dia** — Desenho arquitetural da recalibração com `/sw-architect`. Identificado o risco de conflito com o fan-out (`EventEmitter` substituiria `send_both_lead_events`, deixando o laço órfão).
- **2026-06-07 final do dia** — Fusão das duas frentes neste plano único via `/sw-architect`. Conceito `EventEmitter` morre; comportamento sai naturalmente do par `DecileStrategy.assign()` + laço de fan-out existente.
- **2026-06-09 → 2026-06-10** — Pipeline `validate_ml_performance.py --lf LF56` rodado ponta a ponta após plugar fontes que estavam faltando (API Boletex nova; lista VIP local; tabelas `Client` + `UTMTracking` do Railway; ledger `registros_ml` com `base_status` no SELECT; janela de leads estendida de cap_start até vendas_end; classificador de campanhas marcando leads de Google Ads/orgânico como `EXTERNO` ao invés de dropar; skip da tabela `Lead` morta quando a janela não cobre datas pré-17/05; sete fixes de NaN em métricas; split A/B gerando `matched_champion.parquet` / `matched_challenger.parquet` / `matched_fora_do_ab.parquet`). Resultado oficial do LF56 (relatório do dono, captação 25-31/05, vendas 08-14/06, todas plataformas, sem imposto): Champion ML (LEADQUALIFIED) 25 vendas / ROAS 2,34×; Challenger ML (LEADHQLB) 5 vendas / ROAS 3,00×; Controle (DEVLF s/sufixo) 15 vendas / ROAS 1,55×; Google Ads 9 vendas / ROAS 3,04×. Pelo relatório oficial **Challenger ML supera Champion ML em 28%** (3,00× vs 2,34×) sem nenhum reranqueamento por custo.

- **2026-06-10 — Bloco F arquivado por falta de evidência empírica.** Testadas 12 estratégias de atribuição de custo por lead (3 granularidades × 4 janelas: campanha/adset/ad × LF agregado/D-1/3d/30d) em 6 lançamentos históricos (LF48-LF53; 64.525 leads, 129 vendas; só Champion porque Challenger só entrou em 28/abr). Pool de cada LF veio do snapshot 120d `bring_data-roas/V2/outputs/roas/analise_roas_matched.parquet`; CPLs por entidade×dia puxados fresh da Meta API; reranqueamento por `score × ticket ÷ CPL`, qcut em 10 decis, comparação ROAS top 10%/20%/30%/40% vs baseline (rank por score puro). **Nenhuma estratégia bate o baseline em mais da metade dos 6 LFs em qualquer faixa**; a média geométrica do lift V1/baseline entre LFs gira em torno de 1× (0,76× a 1,05×) com erro grande lançamento a lançamento. O sinal positivo aparente do LF56 (ad_d1 D10 = 9,87× vs baseline 2,43×) não se replica — em LF52 (modelo mais fresco, 32 vendas, sample mais robusto) o baseline D10 = 5,21× com 11 vendas vence todas as variantes V1 (melhor: ad_d1 3,00× com 3 vendas). Padrão emergente: quando o score do Champion funciona bem, V1 atrapalha porque dispersa as vendas concentradas no D10; quando o score está degradado (LF56, Champion 5 meses pós-treino), V1 parece ajudar mas é ruído amostral (D10 tem 2 vendas). **A hipótese original de ganho de R$ 86k-R$ 298k anuais era artefato do snapshot agregado 120d, não se sustenta por LF.** O ganho real está em trocar o modelo — Challenger já supera Champion em 28% no relatório oficial do LF56 — não em reranquear pelo custo. Scripts da investigação em `scripts/_verifica_roas_champion_v2.py`, `scripts/_estrategias_cpl_lf56.py`, `scripts/_estrategias_cpl_multi_lf.py`. JSON com todos os números: `outputs/_estrategias_cpl_multi_lf.json`. **Bloco F desativado do roadmap.** Próximo passo: focar Challenger em produção (item ainda em backlog do `PLANO_EXECUCAO.md`).

---

*Documentos relacionados:* [FAN_OUT_CAPI.md](FAN_OUT_CAPI.md) (artefato vivo do mecanismo de fan-out — referência técnica detalhada); [AB_TEST.md](AB_TEST.md) (princípio "uma variante = um evento" — preservado); [PROCESSO_CAPI_LEAD_SURVEYS.md](PROCESSO_CAPI_LEAD_SURVEYS.md) (caminhos de entrada do lead que convergem em `send_both_lead_events`); [REFATOR_MONITORAMENTO_CAMADA_ACESSO.md](REFATOR_MONITORAMENTO_CAMADA_ACESSO.md) (padrão de Repositório + adaptadores que estamos seguindo); [PLANO_EXECUCAO.md](PLANO_EXECUCAO.md) (roadmap único — fonte do "quando").

*Pixels envolvidos:* `1937807493703815` (Champion, primário), `1513132406527995` (Challenger, primário), `241752320666130` (BM Rodolfo Mori, destino do fan-out).

*Modelos:* Champion ativo `5d158f0aa6e54b489498470446194a6c` (`jan30`).

*Commits relevantes do fan-out:* `e52469c` (primeira tentativa variante-level, revertida), `06e97ba` (revert), `3d950ad` (versão cliente-level atual).

*Worktree da análise de ROAS:* `bring_data-roas` (branch separada, scripts em `V2/scripts/pull_roas_dataset.py`, `V2/scripts/analise_roas_recalibracao.py`, `V2/scripts/analise_roas_a_vista.py`, `V2/scripts/validate_roas_analysis.py`).
