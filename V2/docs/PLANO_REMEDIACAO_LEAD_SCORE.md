# Plano de Remediação — `Lead.leadScore` / `Lead.decil` como fotografia do passado

**Criado:** 2026-05-11.

**Papel deste documento:** descrever o conjunto de mudanças necessárias para corrigir os consumidores do projeto que hoje leem `Lead.leadScore` e `Lead.decil` do Railway como se fossem verdade atemporal. Cada item explica **o que precisa mudar**, **por quê**, **como funcionaria** e **onde no código**.

**Status canônico e prioridade vivem em `PLANO_EXECUCAO.md`.** Este documento é o "como"; o "quando" é definido lá.

Referências:
- Auditoria que originou o plano: `docs/relatorio_qualidade_audiencia_2026-05-11.md` (seção 8, limitação 3).
- Memória persistente: `~/.claude/.../memory/projeto_lead_score_versao_codigo.md`.

---

## Contexto da descoberta

Em 11/05/2026, enquanto integrávamos o novo bloco `audience_quality_signal` no `/monitoring/daily-check`, fizemos um teste de paridade: pegamos os leads do LF54 que sabidamente foram pelo Champion `jan30` em produção (default, sem UTM HQLB), re-scoreamos esses mesmos leads agora com o mesmo Champion `jan30`, e comparamos o score gravado em `Lead.leadScore` com o que acabamos de obter.

**Resultado:** **23% de paridade exata em score, 52% em decil.** O mesmo lead, o mesmo modelo, scoreado em dois momentos diferentes, produz scores diferentes em mais de três quartos dos casos.

Testamos e descartamos: round-trip de arquivo temporário (xlsx vs csv produzem score interno idêntico), race condition em `createdAt` vs `updatedAt`, divergência de UTM source entre o que o pipeline viu na hora e o que está agora no Railway. Nada disso correlaciona com a divergência.

## Causa raiz

A causa é **versão de código diferente entre o escorate em produção e o re-score atual**. O identificador do modelo no MLflow permaneceu constante (`d51757f5...` para o Champion `jan30`), mas o pipeline que processa o lead antes do `predict_proba` mudou ao longo do tempo, incluindo pelo menos:
- a correção do bug em que o Champion `jan30` recebia codificação OHE em vez de ordinal em idade e faixa salarial (identificada nos registros do projeto como DT-12, corrigida em 02/05/2026 — ~8% de importância de features ficou cega antes disso);
- o refactor do diretório `src/core/` (preprocessing, feature engineering e encoding reescritos como funções puras parametrizadas por `ClientConfig`);
- o rollback do commit `edf23e9` para a versão pré-refactor, que ficou ativo em parte de abril/2026;
- ajustes pontuais em normalização UTM e mapeamento de Medium.

Cada lead foi escorado com o snapshot de código que estava live no instante exato em que o webhook processou ele.

`Lead.leadScore` e `Lead.decil` são, portanto, **fotografias do código que rodou na hora**, não medições estáveis ao longo do tempo. Comparar `Lead.leadScore` de um lead de janeiro com um de maio não está comparando o mesmo "sistema".

## Princípio único de remediação

**Re-scorear ao invés de ler do Railway.** Qualquer consumidor que precise de score/decil comparável ao longo do tempo deve carregar os leads (com features brutas) e passar pelo `LeadScoringPipeline` atual no momento da consulta. O `_check_audience_quality_signal` que entregamos hoje já segue esse princípio — e é o único consumidor self-consistent do projeto atualmente.

Para consumidores onde re-scorear é caro (volumes grandes, série temporal longa) há duas saídas:
1. **Pré-computar e cachear** o resultado do re-score, invalidando o cache quando o modelo ou o código do pipeline muda.
2. **Calibrar o erro** comparando uma amostra de leads re-scoreados vs gravados e aplicar um fator de correção. Só faz sentido se o erro for sistemático e estável — não é o caso aqui (a divergência tem variância alta).

A opção 1 é mais robusta. A opção 2 é paliativa.

## Histórico vs futuro — o que entra no escopo e o que não entra

O princípio "re-scorear ao invés de ler do Railway" só se aplica a **consumidores cuja decisão é tomada agora**. Para esses, um decil contaminado por versões antigas de código gera ruído ou decisão errada hoje — então a correção é olhar o passado com o pipeline atual.

**Relatórios e métricas que descrevem o que de fato aconteceu no passado não devem ser tocados.** Cada lead foi escorado pela versão de código vigente no momento, recebeu o decil que recebeu, foi enviado pro Meta com aquele valor e gerou (ou não) a compra que está nos registros. Esse é o histórico operacional real. Re-scorear retroativamente cria uma "história alternativa" que nunca rodou — não é mais verdadeiro, é menos.

Aplicando aos consumidores listados a seguir: itens que alimentam **decisões correntes** (forecast diário, baseline de detecção de drift, equivalência de revisão antes de deploy, validação de promoção de Challenger novo) entram no escopo. Itens que apenas **descrevem o passado** (ROI por decil ao longo dos lançamentos, séries temporais por LF) ficam como estão.

---

## Itens por prioridade

### CRÍTICO — afeta números que vão pro cliente ou decisões importantes

#### L1. Forecast de receita do daily-check usa decis contaminados

**O que precisa mudar:** o `revenue_forecast` que aparece no `/monitoring/daily-check` calcula dois cenários de faturamento esperado — `expected_conversion` e `cenario_ml_aware` — multiplicando a contagem de leads por decil pelas taxas históricas de conversão por decil. A contagem de leads por decil vem direto de `Lead.decil` no Railway. Como esse campo é fotografia do passado, a previsão fica enviesada pela soma de versões de código diferentes.

**Por quê:** esses dois números aparecem no digest diário e são lidos como "quanto o sistema espera faturar com o público atual". Decisões de ajuste de campanha durante o lançamento podem ser baseadas neles.

**Como funcionaria:** trocar a query `SELECT decil FROM "Lead"` por re-scorear os leads do cap atual com o pipeline atual (mesma chain que já implementamos no `_check_audience_quality_signal`). Isso adiciona ~10-30s ao daily-check para uns 30k leads — aceitável porque já estamos chamando `pipeline.run` uma vez por dia.

**Onde no código:**
- `api/app.py:2433-2447` — query que alimenta `forecast_decil_dist`.
- `src/monitoring/orchestrator.py:967-1041` — `_generate_revenue_forecast` (consome a distribuição).

---

#### L2. Backtest comparativo usa Champion contaminado como baseline

**O que precisa mudar:** `_attach_production_decil` em `src/validation/backtest_data.py` anexa `Lead.decil` e `Lead.leadScore` aos resultados de `load_match_spend_for_lf`. Esse campo é consumido por `backtest_compare_models.py` como baseline "produção" para comparar com revisões novas. Como o decil de produção foi gravado por código que mudou várias vezes, a comparação "modelo novo vs produção" não tem baseline estável.

**Por quê:** o backtest é usado pra validar se um Challenger candidato bate o Champion antes de promover. Se o "Champion" no baseline é uma média de versões diferentes, o teste produz conclusão ambígua — não dá pra saber se a diferença vem do modelo novo ou da inconsistência do baseline.

**Como funcionaria:** dentro do `_attach_production_decil`, em vez de fazer `SELECT decil FROM "Lead"`, re-scorear os leads usando o Champion atual (o que está em `active_models/devclub.yaml`). Renomear o output de `decil_production` → `decil_champion_current` para deixar claro que é re-score atual, não fotografia.

**Onde no código:**
- `src/validation/backtest_data.py:415-464` — função `_attach_production_decil`.
- `scripts/backtest_compare_models.py` — consumidor.

---

#### L3. Relatório evolutivo de ML — HISTÓRICO, preservar como está

**Decisão:** não remediar. `scripts/ml_evolution_report.py` agrega por `Lead.decil` para gerar a tabela "ROI por decil" e "ticket médio por decil" usada como evidência do sistema ao longo dos lançamentos. Esses números descrevem o que de fato aconteceu — cada lead foi enviado pro Meta com o decil que tinha naquela hora, gerando o ROI (ou a ausência dele) que está registrado. Re-scorear hoje misturaria realidade operacional com hipótese contrafactual.

**Como interpretar a partir de agora:** o relatório responde "qual ROI foi gerado pelos decis que foram efetivamente enviados ao Meta ao longo dos lançamentos", não "qual ROI o modelo atual atribuiria a esses leads se rodasse agora". A primeira leitura permanece válida; a segunda exigiria estudo separado.

**Onde no código:**
- `scripts/ml_evolution_report.py:351-358` — sem mudança.

---

#### L4. Teste de equivalência de revisão usa Champion gravado como baseline

**O que precisa mudar:** `scripts/test_revision_equivalence.py` valida que uma revisão nova produz os mesmos scores que a anterior. Ele puxa `Lead.leadScore` do Railway pra usar como "ground truth" do Champion. Como o Champion gravado pode ter sido produto de várias versões de código, a equivalência fica testada contra um alvo móvel.

**Por quê:** esse teste protege contra deploys que quebram o pipeline (ex: mudança em encoding que muda score de todo mundo). Se o alvo está sujo, o teste pode aprovar deploys ruins ou reprovar deploys bons.

**Como funcionaria:** em vez de puxar `Lead.leadScore`, scorear a amostra duas vezes em paralelo — uma com o pipeline na revisão atual (rev N) e uma com o pipeline na revisão candidata (rev N+1). Comparar score lead-a-lead. Se a diferença média for menor que um threshold (ex: 1e-6), revisões são equivalentes.

**Onde no código:**
- `scripts/test_revision_equivalence.py:123-168` — uso de `Lead.leadScore`.

---

### MÉDIO — alertas e séries temporais ruidosos, mas não vão direto pro cliente

#### L5. Rolling 30d (baseline da detecção de drift) usa decis contaminados

**O que precisa mudar:** o daily-check computa um baseline rolling 30d via `SELECT decil, COUNT(*) FROM "Lead" GROUP BY decil`. Essa distribuição é injetada no `_check_score_distribution` como "qual a distribuição esperada de decis no momento". A janela de 30d cobre múltiplos deploys e versões de código diferentes, então a distribuição "esperada" é uma média de várias versões — não uma referência estável.

**Por quê:** alimenta o check que detecta drift de distribuição de decis. Baseline contaminado significa: ou o alerta dispara à toa quando o sistema está saudável, ou demora a disparar quando há regressão real.

**Como funcionaria (recomendação):** **cache versionado por modelo + commit**. Uma vez por dia (no próprio daily-check), o sistema roda o pipeline atual sobre os leads dos últimos 30 dias e salva um parquet local. O `_check_score_distribution` lê esse parquet em vez de chamar o pipeline a cada execução. O cache leva uma chave composta `mlflow_run_id + commit_hash do src/core/`: quando o modelo trocar ou o código do `core/` mudar, o cache invalida automaticamente e regenera na próxima rodada. Custo: ~3 minutos/dia em 150k leads, em chunks. Em memória, o resultado é a "distribuição esperada" produzida por uma única versão do pipeline — exatamente o que o check precisa.

**Alternativa mais fraca:** desabilitar o baseline rolling 30d e usar apenas o `model_metadata` (gerado uma vez no momento do treino). Mais barato, mas perde 30 dias de amostra real como referência — qualquer drift que aconteça pós-treino fica invisível.

**Onde no código:**
- `api/app.py:2700-2724` — query rolling 30d.
- `src/monitoring/data_quality.py:922-1020` — `_check_score_distribution`.

---

#### L6. Métricas evolutivas por LF — HISTÓRICO, preservar como está

**Decisão:** não remediar. `scripts/extract_evolution_metrics.py` calcula `% D10`, taxa de CAPI, etc. por LF ao longo do tempo. Esses números refletem o que foi gravado e enviado pro Meta em cada lançamento. Re-scorear retroativamente apagaria a realidade operacional.

**Como interpretar a partir de agora:** as séries temporais mostram o que **rodou em cada lançamento** com a versão de código vigente, não o que o modelo atual produziria nos leads daquela época. Para comparar qualidade de público entre lançamentos sob um pipeline consistente, usar o sinal de qualidade de audiência (bloco `audience_quality_signal` do `/monitoring/daily-check`) daqui pra frente — ele re-scoreia em tempo real e garante consistência prospectiva.

**Onde no código:**
- `scripts/extract_evolution_metrics.py:139-174` — sem mudança.

---

#### L7. Análise retrospectiva do bug de codificação no Champion — CONCLUÍDO

**Status:** concluído. A quantificação do dano do bug em que o Champion `jan30` recebia codificação OHE em vez de ordinal em idade e faixa salarial (identificado no projeto como DT-12) já foi feita em sessão anterior e está registrada em `docs/registro_erros_ml.md`. Não há ação remanescente neste plano.

---

#### L8. `_check_score_distribution` (consumidor do baseline E6)

**O que precisa mudar:** depende de L5 (baseline rolling 30d). Não tem código próprio a corrigir aqui — só lê o que L5 produz.

**Por quê:** mencionado pra deixar explícito que o impacto se propaga.

**Onde no código:**
- `src/monitoring/data_quality.py:922-1020`.

---

### BAIXO — display, não afeta decisões

#### L9. Alerta de zero-decil em CAPI — FORA DE ESCOPO

**Status:** fora de escopo deste plano. O check `_check_zero_decil_events` em `src/monitoring/capi_monitor.py` lê `LeadCAPI.decil` para verificar se algum decil parou de receber eventos nas últimas 24h. O alerta pergunta apenas "todos os decis tiveram pelo menos N eventos hoje?" — uma checagem de presença/ausência. Mesmo que o decil gravado seja fotografia de versão antiga de código, todos os decis vão ter eventos quando o sistema está saudável. A contaminação de versão não afeta a função deste alerta, portanto não há remediação a fazer.

---

## Ordem sugerida de execução

A ordem de cima pra baixo respeita o impacto direto no cliente e a dependência entre itens. **L3 e L6 não aparecem aqui — são relatórios históricos preservados como estão (ver seção "Histórico vs futuro"). L7 (já concluído) e L9 (fora de escopo) também não aparecem.**

1. **L1** (forecast). Mais alto impacto: afeta o número de faturamento esperado que aparece no digest diário e é consumido em decisões durante o lançamento.
2. **L2** (backtest comparativo). Crítico pra promoção de modelo. Será corrigido em conjunto com L4 — mesma técnica de re-score.
3. **L4** (teste de equivalência de revisão). Crítico pra confiança no deploy.
4. **L5** + **L8** (rolling 30d + score distribution). Cache versionado por modelo + commit do `core/`, regerado pelo daily-check.

## Princípio de aceitação

Cada item está concluído quando:
1. O código não lê mais `Lead.leadScore` ou `Lead.decil` para gerar a métrica de saída.
2. O score/decil é produzido pelo `LeadScoringPipeline` atual no momento da consulta (ou de cache versionado por `mlflow_run_id` + commit do `core/`).
3. Existe teste/smoke que comprova que duas execuções consecutivas produzem o mesmo resultado (self-consistency).

## O que não está neste plano

- **Recalibração isotônica do score do Champion** — item separado no backlog, com propósito diferente (resolver `Σ(score)×ticket` para o forecast).
- **Investigar causa raiz mais a fundo** — sabemos que é versão de código, não precisamos diagnosticar caso a caso. A remediação é a mesma para qualquer causa de drift de versão.
- **Substituir `Lead.leadScore`/`Lead.decil` no banco** — manter os campos como histórico. Apenas parar de consumi-los como se fossem verdade atemporal.

---

*Plano gerado em 11/05/2026 após auditoria de paridade no `audience_quality_signal` (revisão `smart-ads-api-00439-fir`).*
