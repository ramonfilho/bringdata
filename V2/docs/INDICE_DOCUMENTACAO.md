# Índice de Documentação — Bring Data V2

**Atualizado:** 2026-06-23
**Propósito:** mapa de todos os documentos da pasta `docs/`, seus papéis, status e como se relacionam.

> **Reorganização de nomenclatura (10/05/2026):** os docs operacionais (este índice, `PLANO_EXECUCAO`, `registro_erros_ml`, `AUDITORIA_QUEBRA_PRODUCAO`) foram reescritos pra usar linguagem natural primeiro. Os catálogos técnicos (`PLANO_SAFEGUARD`, `PLANO_REFACTOR_MLOPS`) ganharam título verbal por item + identificador codificado (`T1-X`, `DT-X`) movido pro rodapé. Identificadores continuam funcionais pra cruzar com commits e issues antigas, mas o nome verbal é o que aparece no fluxo de leitura.

---

## Roadmap → `PLANO_EXECUCAO.md`

> **A prioridade global, fases, dependências e backlog vivem agora em `PLANO_EXECUCAO.md`** — único documento de "o que fazer e quando". Este índice mapeia papéis e relações entre docs; **não duplica o roadmap**.
>
> Estado atual em uma frase: gate H1.1 (validação OOS do Champion v4) atravessado em 28/04; deploy main em execução em sessão paralela via canary; A/B test reaberto como frente ativa.

---

## Visão geral da estrutura

A documentação se divide em cinco camadas:

```
ESTRATÉGIA          → onde o projeto vai (visão de longo prazo)
PLANEJAMENTO        → o que está sendo feito agora e em que ordem
OPERACIONAL         → como executar tarefas específicas
REFERÊNCIA TÉCNICA  → como o sistema funciona hoje
HISTÓRICO           → decisões passadas, migrações concluídas
```

---

## Camada 1 — Estratégia

### `bring_data_02_execução.md`
**Papel:** visão de negócio, roadmap de escala (Fases 1/2/3 do produto), moat competitivo, backlog de features. Também contém o script de venda e o checklist de onboarding comercial.
**Status:** ativo. Renomeado de `adsmarter_02_execução.md` para `bring_data_02_execução.md` conforme rebrand.
**Relação:** é o "porquê" de tudo. O plano de refactor e o roadmap MLOps são consequências das decisões aqui.
**Ação sugerida:** revisar após Cliente B onboarding.

### `swot_bringdata.md`
**Papel:** análise SWOT completa com dados de mercado, forças, fraquezas, oportunidades e ameaças. Inclui síntese estratégica e prioridades.
**Status:** ativo. Criado em março/2026.
**Relação:** complementa `bring_data_02_execução.md` com profundidade competitiva. Referencia W1 (feedback loop) e W2 (token Meta) como riscos críticos.

### `bring_data_produto.md`
**Papel:** script de reunião comercial — estrutura da conversa de vendas, quebra de objeções, fechamento.
**Status:** ativo.
**Relação:** instrumento de execução comercial. Derivado das forças documentadas no SWOT.

---

## Camada 2 — Planejamento

### `PLANO_EXECUCAO.md` ⭐ ROADMAP ÚNICO
**Papel:** **documento mestre único** de execução. Sequência de horizontes (H1 Agora → H7 Escala 5+ clientes), dependências explícitas, gate único de validação OOS, A/B em Standby, backlog de features, histórico concluído.
**Status:** ativo. Reescrito em 27/04/2026 absorvendo o `ROADMAP_MLOPS_MATURIDADE.md` (arquivado) e a parte de "o que fazer" dos catálogos abaixo.
**Relação:** consome `PLANO_SAFEGUARD.md` (especificação técnica de T1/T2/T3), `PLANO_REFACTOR_MLOPS.md` (especificação de DT-X + histórico) e `AB_TEST.md` (design A/B) como catálogos. Quando houver conflito de status/prioridade entre estes docs, **PLANO_EXECUCAO vence**.

### `PLANO_SAFEGUARD.md` 📚 Catálogo técnico
**Papel:** especificação técnica de cada item de safeguard (T1-X / T2-X / T3-X) — o que faz, como implementar, como testar. Inclui audit de infraestrutura, gap matrix com 9 blocos, protocolo obrigatório por item.
**Status:** ativo. Criado em 16/04/2026. Status canônico vive em `PLANO_EXECUCAO.md`.
- **Tier 1 (11 itens): ✅ todos concluídos até 23/04/2026** (T1-11 em commits `361fc62` + `ba43d30`).
- **Tier 2 (8 itens):** 2 concluídos (T2-1, T2-7); 6 pendentes em H2/H3 do PLANO_EXECUCAO.
- **Tier 3 (7 itens):** 0 iniciados; agendados em H3.
**Relação:** referenciado por `PLANO_EXECUCAO.md` em H2/H3. Motivação histórica em `Erros_cometidos.md`. Skills `/safeguard` e `/investigate` consomem esse documento.

### `PLANO_REFACTOR_MLOPS.md` 📚 Catálogo técnico + histórico
**Papel:** (1) histórico completo do refactor MLOps (153 hardcodes, decisões arquiteturais, fases já executadas), (2) especificação técnica de cada DT-X (dívida técnica) e R-X (pré-requisitos do Cliente B).
**Status:** histórico + catálogo. Status canônico de cada item vive em `PLANO_EXECUCAO.md`.
- Fases 1, 2, 3a, 3c → ✅ concluídas
- Item 19 (deploy do refactor) → ✅ CONCLUÍDO em 24/03/2026
- DT-12 (encoding por variante A/B) → ✅ RESOLVIDO em 01/04; ressurgiu via Champion shim em 02/05/2026, refactor monitoring per-variant em 06/05/2026 (ver DT-16)
- DT-14 (nomenclatura `clients/` vs `active_models/` confunde) → registrado em 05/05/2026, prioridade baixa
- DT-15 (`ABTestVariantConfig` campos não-utilizáveis) → registrado em 05/05/2026, candidato a agrupar com DT-14
- DT-16 (matar `encoding_overrides` por convergência) → registrado em 05/05/2026, prioridade alta — bloqueado por treino do próximo Champion
- DT-17 (eliminar duplicação `api/business_config.py` × YAML — fluxo treino→MLflow artifact→`--set-active`→YAML) → registrado em 06/05/2026, prioridade alta arquiteturalmente, fases 1-3 sem dependência de retreino
- DT-20 (calibração de probabilidades de scoring — bloqueante do bloco F da estratégia ROAS V1) → registrado em 08/05/2026, prioridade alta arquiteturalmente e operacionalmente. 5 fases em 3 PRs; caminho mínimo alternativo (fases 2+3) desbloqueia o bloco F com menor esforço. Diagnóstico empírico em `analise_calibracao_jan30_abr28.md`.
- Fase 3b, Fase 4 (EDA), Fase 5 (NLP) → bloqueadas/agendadas em H4-H5 do PLANO_EXECUCAO
- Pré-requisitos R1, R2, R3 + DT-2, DT-7, DT-11, DT-13 → agendados no PLANO_EXECUCAO
**Relação:** consultado por `PLANO_EXECUCAO.md` para detalhes técnicos de cada DT/R. Histórico do deploy em `arquivo/CHECKLIST_DEPLOY_REFACTOR.md`.

### `CHECKLIST_ONBOARDING_NEW_CLIENT.md`
**Papel:** runbook para onboarding de novo cliente — criar YAML, inspecionar dados brutos, treinar modelo, verificar MLflow, deploy.
**Status:** ativo. Pronto para uso quando Cliente B chegar (H5 do PLANO_EXECUCAO).
**Relação:** consumido em H5.3 (Onboarding Cliente B — Fase 3b refactor).

### `PROMOCAO_MODELO_CHECKLIST.md`
**Papel:** protocolo obrigatório de promoção de modelo (Champion / Challenger). Mapeia a "pegadinha" em que `mlflow_run_id`, `encoding_overrides` e `conversion_rates` precisam ser atualizados em conjunto, com checklists separados por tipo (promoção leve, mudança de encoding, nova arm experimental). Documenta os incidentes de 02/05 e 08/05 como lições registradas.
**Status:** ativo. Criado em 08/05/2026 após investigação do moat e cenário de retreino com `--exclude-features`.
**Relação:** consumido por qualquer deploy que altere o `active_model.mlflow_run_id` em `configs/active_models/{cliente}.yaml`. Referencia DT-12, DT-16, DT-17 do `PLANO_REFACTOR_MLOPS.md`. Pré-requisito antes da skill `/safeguard` em deploys de modelo.

### `PLANO_REMEDIACAO_LEAD_SCORE.md` 📚 Catálogo técnico
**Papel:** catálogo "como" da remediação dos consumidores que leem `Lead.leadScore` e `Lead.decil` do Railway como verdade atemporal. Auditoria em 11/05/2026 mostrou que esses campos são fotografia da versão de código que rodou no instante em que cada lead chegou — só 23% de paridade exata com re-score atual do mesmo Champion. Causa: pipeline foi refatorado/patchado/revertido várias vezes (DT-12 do encoding de idade/salário em 02/05, refactor `src/core/`, rollback `edf23e9`, normalizações UTM/Medium). O documento descreve 9 consumidores identificados (L1–L9), princípio único de remediação (re-scorear via pipeline em vez de ler do banco), distinção entre histórico (preservar) e futuro (remediar), e ordem sugerida de execução.
**Status:** ativo, em backlog. Status canônico vive em `PLANO_EXECUCAO.md` (subseção "Sequelas / pendências da sessão de investigação 11/05/2026"). 🟢 BACKLOG até consistência do método de ROAS ser resolvida.
**Relação:** referenciado por `PLANO_EXECUCAO.md` em H4. Memória persistente relacionada: `~/.claude/.../memory/projeto_lead_score_versao_codigo.md`. Itens críticos: L1 (forecast diário do daily-check usa decil contaminado), L2 (backtest comparativo), L4 (teste de equivalência de revisão), L5+L8 (baseline rolling 30d do detector de drift, proposta de cache versionado por `mlflow_run_id + commit_hash`).

### `EVENTOS_E_DECIS_PLANO.md` 📚 Catálogo técnico (frente ativa + futura)
**Papel:** plano integrador que orquestra a emissão de eventos CAPI por lead e a futura recalibração de decis por retorno esperado por real gasto (ROAS V1). Funde duas frentes que tocam o mesmo subsistema (a função `send_both_lead_events` de [api/capi_integration.py](../api/capi_integration.py)) em um único plano de seis blocos: (A) estabilização do fan-out atual de cópias de evento HQ em pixels adicionais cliente-level — vivo em canary, atende pedido do dono de 2026-06-07; (B) lookup de custo por lead com refresh diário; (C) interface `DecileStrategy` extraindo a lógica atual com paridade 100%; (D) adapter `send_all_lead_events` que itera sobre N atribuições mantendo o laço de fan-out idêntico (zero risco de órfão); (E) observabilidade unificada no `registros_ml`; (F) ativação de `RoasV1DecileStrategy` em paralelo + adicionar entrada nova em `extra_hq_destinations`. Decisão arquitetural chave: o `EventEmitter` originalmente proposto morre — comportamento sai naturalmente da combinação `DecileStrategy.assign()` + laço de fan-out existente, evitando segunda fonte de verdade para "qual evento copia em qual pixel". Pendência crítica antes do bloco F: análise de divergência entre `leadScore` puro e probabilidade calibrada (isotônica) para decidir se calibração entra no caminho crítico.
**Status:** ativo. Criado em 2026-06-07. Bloco A em execução (canary `smart-ads-api-00680-jez` 0% tráfego em 2026-06-07); blocos B-E em backlog até priorização pelo `PLANO_EXECUCAO`. **Bloco F arquivado em 2026-06-10** após verificação empírica em 6 lançamentos históricos (LF48-LF53, 129 vendas) com 12 estratégias de atribuição de CPL (3 granularidades × 4 janelas) — nenhuma combinação bate o ranking por score puro consistentemente; lift médio geométrico entre LFs gira em torno de 1×. O ganho original que motivou a frente foi artefato do snapshot agregado 120d, não se sustenta por lançamento. Histórico completo no fim de `EVENTOS_E_DECIS_PLANO.md`.
**Relação:** consome [FAN_OUT_CAPI.md](FAN_OUT_CAPI.md) como artefato técnico vivo do mecanismo de fan-out (referência detalhada do laço dentro de `send_both_lead_events`). Preserva princípio "uma variante = um evento" do [AB_TEST.md](AB_TEST.md). Toca caminhos de lead de [PROCESSO_CAPI_LEAD_SURVEYS.md](PROCESSO_CAPI_LEAD_SURVEYS.md). Segue padrão Repositório + adaptadores de [REFATOR_MONITORAMENTO_CAMADA_ACESSO.md](REFATOR_MONITORAMENTO_CAMADA_ACESSO.md). Frente analítica em worktree separado `bring_data-roas` (scripts em `V2/scripts/pull_roas_dataset.py`, `analise_roas_recalibracao.py`, `analise_roas_a_vista.py`, `validate_roas_analysis.py`); PDF para stakeholders em [propostas_e_apresentacoes/descoberta_roas_devclub.pdf](../propostas_e_apresentacoes/descoberta_roas_devclub.pdf). Roadmap em `PLANO_EXECUCAO.md` (gate único de validação OOS + pré-requisitos do segundo cliente entram aqui).

### `FAN_OUT_CAPI.md` 📚 Catálogo técnico (artefato vivo)
**Papel:** especificação técnica detalhada do mecanismo de cópia de eventos HQ em pixels adicionais declarados no nível cliente. Cobre o porquê (pedido do dono em 2026-06-07 para o evento de alta qualidade voltar ao pixel `241752320666130` do BM Rodolfo Mori), o desenho arquitetural (regra cliente-level e não variante-level — primeira tentativa em nível variante revertida em `06e97ba` em 2026-05-27, custou sete arquivos contra os três da versão atual), o fluxo do lead em dois exemplos (Champion e Challenger), o formato YAML do bloco `extra_hq_destinations`, os três arquivos efetivos da implementação, garantias de fail-loud no parser, três cenários de extensão, pré-deploy obrigatório de cadastro no Events Manager, rollback em cascata, relação com o trabalho paralelo da recalibração de decis (seção 10), pendências (testes unitários, observabilidade) e histórico.
**Status:** ativo. Criado em 2026-06-07. Canary `smart-ads-api-00680-jez` 0% tráfego com gates B/D/C.1/C.2 passados, aguardando autorização para promover.
**Relação:** orquestrado por [EVENTOS_E_DECIS_PLANO.md](EVENTOS_E_DECIS_PLANO.md) (este documento é o bloco A do plano unificado). Princípio "uma variante = um evento" preservado conforme [AB_TEST.md](AB_TEST.md). Caminhos de entrada do lead que convergem em `send_both_lead_events` documentados em [PROCESSO_CAPI_LEAD_SURVEYS.md](PROCESSO_CAPI_LEAD_SURVEYS.md). Artefatos vivos: [src/core/client_config.py](../src/core/client_config.py) (dataclass `ExtraHQDestination` e parser fail-loud), [configs/clients/devclub.yaml](../configs/clients/devclub.yaml) (bloco `extra_hq_destinations`), [api/capi_integration.py](../api/capi_integration.py) (laço dentro de `send_both_lead_events`).

### `google_ads_pendencias.md` 📚 Status da frente (H6)
**Papel:** status da implementação do envio de eventos ao Google Ads (Enhanced Conversions for Leads via Data Manager API). Histórico das decisões + o que foi feito (conversion actions, setup GCP, acesso da SA via MCC, forma do payload `events:ingest` confirmada em `validateOnly`) + o que falta (despachante no consumer Pub/Sub, ligar `enabled`).
**Status:** 🚧 em curso — caminho validado ponta a ponta em `validateOnly` (HTTP 200), código inerte na branch `feat/google-ads`. Atualizado em 2026-06-15. (`gclid` deixou de ser bloqueante; integração é no consumer Pub/Sub, não nos 4 webhooks legado.)
**Relação:** referenciado por `PLANO_EXECUCAO.md` em H6 → "Diversificação de canais". Análise de valor por canal: `analise_valor_decil_por_canal_google_vs_meta.md`. Escopo: só DevClub.

### `PROCESSO_CAPI_LEAD_SURVEYS.md`
**Papel:** especificação **e diário** da frente que faz o evento CAPI scoreado por ML (`LeadQualified`/`LeadQualifiedHighQuality`) ser disparado também a partir da esteira nova do dono. A captação migrou de `Lead`→`lead_surveys` em ~12/05/2026 e o sinal scoreado ficou OFF para a inflow viva; em 2026-05-23 a esteira nova de scoring foi reaberta via consumer Pub/Sub que substituiu o desenho anterior (leitura Railway + parse de log). Cobre porquê (migração da captação + virada de arquitetura), histórico da investigação SQL (esteiras disjuntas, recuperação de campos via JOIN com `UTMTracking`+`integration_logs` etc — agora superado), decisões cronológicas, protocolo de implementação (I0–I7 do design SQL pausado + P1–P18 do design Pub/Sub atual), desenho técnico Pub/Sub e plano de monitoramento pós-Pub/Sub com tabela completa de 26 itens (8 mantém, 13 adapta, 1 remove, 4 cria do zero).
**Status:** ✅ **LIVE em produção desde 2026-05-23 19:45 BRT.** Consumer Pub/Sub (`api/pubsub_branch.py`) processando mensagens da sub `lead-capture-ingest-sub`; revisão `smart-ads-api-00341-ml6` a 100% tráfego com `PUBSUB_CAPI_ENABLED=true`; Cloud Scheduler `pubsub-process-pending` ENABLED (`*/5 * * * *`); IAM `roles/pubsub.subscriber` concedido ao Cloud Run SA; ledger `registros_ml` operacional (PK migrada `lead_id`→`event_id` UUID v7). Smoke real: 25 mensagens processadas, 0 enviadas ao Meta (todas do load test antigo, source não-Meta). Backlog do load test purgado em 24/05. Testes 26/26 verdes. Gates B/D/C.1/C.2 passaram (bonus: fix do Gate C.1 que tornou o gate intrínseco, commit `c09e0d2`). Consolidado 2026-05-24 via `/docs`. **Pendências:** P17 colunas UTM no `registros_ml` + P18 refator do monitoramento (13 itens adaptar, 4 criar) + verificação UTM cliente pré-go-live (depende do gestor de tráfego subir tags do sistema novo, previsto 2026-05-26+). **Deprecado:** módulos `api/survey_branch.py` e `api/survey_enrichment.py` do design SQL pausado (header `[DEPRECATED 2026-05-23]`); hook `_run_survey_branch_safely` em `app.py` continua mas off por `SURVEY_CAPI_ENABLED` default false.
**Relação:** roadmap em `PLANO_EXECUCAO.md`. Contrato cliente do payload Pub/Sub em `REQUISITOS_SISTEMA_NOVO.md` + PDF + JSON schema em `propostas_e_apresentacoes/`. Classe de quebra histórica "Cluster 5" em `AUDITORIA_QUEBRA_PRODUCAO.md` e `registro_erros_ml.md`. Toca endpoint novo `/pubsub/process-pending` (`api/app.py`), reusa `pipeline.run`+`send_batch_events`+`api/railway_mapping.py` (com função nova `traduzir_survey_slugs`). Tabelas Railway: `registros_ml` (nossa, viva); `lead_surveys`/`UTMTracking`/`Client` (vivas, sistema novo); `Lead`/`leads_capi` (mortas desde 17/05). Infra GCP: tópico `lead-capture-ingest`, sub `lead-capture-ingest-sub` (retenção 31d); SA publisher `lead-capture-publisher@…` (entregue ao dono); SA consumer = Cloud Run default. `instrucoes_dev_frontend_capi.md` continua **deprecado**.

### `REQUISITOS_SISTEMA_NOVO.md`
**Papel:** contrato de dados cliente-facing entregue ao dono do sistema novo (DevClub) em 2026-05-22. Define o payload JSON que o backend dele tem que publicar no nosso tópico Pub/Sub `lead-capture-ingest` por lead: 1 evento, identificador estável (`eventId` UUID v7), identidade (email/firstName/lastName/phone), captura Meta (`fbp`/`fbc` ou null nunca string vazia), `hasComputer` top-level (`SIM`/`NAO`), userAgent cru, `ip4`, objeto `survey` com as 10 respostas em vocabulário fechado (slugs lowercase + lowercase de cortesia, listados no Anexo A.2), objeto `utm` cru do anúncio. Inclui correções obrigatórias antes de ir ao ar (1: `eventId` único por lead, hoje produção gera dois ids diferentes pro mesmo lead; 2: `fbc` vazio vira `null` não `""`; 3: macros do Facebook tipo `{{adset.name}}` precisam ser renderizadas, não literais). Anexo C ensina como publicar (browser → backend dele → publish server-side via SA + chave JSON que entregamos). Anexo D lista as correções.
**Status:** ativo. Criado em 2026-05-22; entregue ao dono em PDF (`propostas_e_apresentacoes/requisitos_sistema_novo.pdf`) + JSON schema (`propostas_e_apresentacoes/requisitos_sistema_novo_payload.json`). Substitui o `instrucoes_dev_frontend_capi.md` (deprecado).
**Relação:** é o contrato consumido por `PROCESSO_CAPI_LEAD_SURVEYS.md` (esteira nova de scoring CAPI). Quando o dono publica seguindo este contrato, o nosso consumer Pub/Sub (`api/pubsub_branch.py`) parseia, traduz slugs via `traduzir_survey_slugs`, scoreia e envia ao Meta. Geradores de PDF: `scripts/gerar_pdf_requisitos_sistema_novo.py` + `scripts/pdf_base.py` (base compartilhada de paleta/estilos).

### `arquivo/ROADMAP_MLOPS_MATURIDADE.md` 📦 ARQUIVADO
**Status:** ✅ **ARQUIVADO em 27/04/2026.** Conteúdo absorvido pelos horizontes H1–H7 do `PLANO_EXECUCAO.md`. Consultar apenas como referência histórica.

### `arquivo/CHECKLIST_DEPLOY_REFACTOR.md` 📦 ARQUIVADO
**Papel:** runbook operacional do deploy do refactor (24/03/2026).
**Status:** ✅ ARQUIVADO. Concluído. Revisão `00254-dh5` em produção com 100% de tráfego na época.

---

---

## Camada 3 — Operacional (runbooks)

### `acesso_sql.md`
**Papel:** como conectar ao PostgreSQL local e em produção (Cloud SQL Proxy, Railway).
**Status:** ativo, provavelmente atualizado.

### `acesso_sheets.md`
**Papel:** como acessar Google Sheets via ADC (Application Default Credentials).
**Status:** ativo.

### `MLFLOW.md`
**Papel:** acesso ao MLflow — URLs, credenciais de tracking, como criar experimentos.
**Status:** ativo. Complementa `MIGRACAO_MLFLOW_GCS.md` (histórico).

### `monitoring-api.md`
**Papel:** documentação dos endpoints de monitoring para o front-end.
**Status:** ativo enquanto a API de monitoring estiver sendo consumida externamente.

### `revenue_forecast.md`
**Papel:** documentação completa da feature de previsão de faturamento por lançamento — metodologia, parâmetros calibrados, backtest, estrutura do response e limitações conhecidas.
**Status:** ativo. Implementado em abril/2026. MAE 2,6% validado em LF42–LF47.

### `instrucoes_dev_frontend_capi.md` e `instrucao_frontend_fbp_fbc.txt`
**Papel:** instruções para o dev front-end sobre CAPI e captura de FBP/FBC.
**Status:** ⚠️ **DEPRECADO (2026-05-19, reforçado 2026-05-24).** O contrato de dados de fato vive em **`REQUISITOS_SISTEMA_NOVO.md`** (payload Pub/Sub formal entregue ao dono em 22/05) + PDF + JSON schema em `propostas_e_apresentacoes/`. Mantido só para referência histórica. Ver `PROCESSO_CAPI_LEAD_SURVEYS.md` (estado LIVE 2026-05-24).

### `operacoes_gcp_custos.md`
**Papel:** registro das otimizações de custo aplicadas no GCP em 2026-04-26 (~R$ 167/mês), procedimento de stop/start do Cloud SQL `smart-ads-db` para retreino, cleanup policy do Artifact Registry e bugs latentes descobertos durante a auditoria. Inclui investigações de spike: 06/mai/2026 (worker timeout do gunicorn) e 14/mai/2026 (acúmulo de tags `canary-*` no Cloud Run mantendo instâncias always-on — remediado com cleanup automático no `deploy_capi.sh`). Em 14/mai também documentou a eliminação de min-instances no Cloud Run (de ~R$ 14/dia pra ~R$ 4-5/dia), guardrails nos scripts de treino contra esquecer de ligar/desligar Cloud SQL, e checklist de monitoramento pós-mudança.

### `MIGRACAO_MLFLOW_PARA_SQLITE.md` 📚 Catálogo técnico (frente futura)
**Papel:** especificação da migração do tracking server MLflow do Cloud SQL `smart-ads-db` (PostgreSQL ~R$ 50/mês ligado, R$ 15/mês parado) para SQLite + GCS (~R$ 0,10/mês). Documenta o mapa completo de dependências (quem precisa do Cloud SQL ligado vs quem não precisa), onde os artefatos do modelo realmente vivem em produção hoje (baked-in no Docker, independente do MLflow remoto), plano em 5 fases (~5-6 dias de trabalho), riscos e pré-condições.
**Status:** 📚 catálogo. Não iniciado em 14/mai/2026. Status canônico vive em `PLANO_EXECUCAO.md`.
**Relação:** referenciado por `operacoes_gcp_custos.md` na pendência "MLflow tracking → SQLite+GCS".
**Status:** ativo. Atualizar quando novas otimizações forem aplicadas ou recursos parados forem retomados.
**Relação:** referência operacional para retomar Cloud SQL antes de retreinar; consultar antes de mudar `min-instances`/`memory`/`cpu` do `smart-ads-api`.

### `bigquery_sinks.md`
**Papel:** mapa dos datasets BigQuery do projeto (`cloudrun_logs`, `devclub`, `billing_export`), schema de `run_googleapis_com_stdout`, queries comuns para investigar value/decil/erros por revisão.
**Status:** ativo. Criado em 2026-05-08 após investigação do bug VAL=0 (que usou Q1 sem documentação).
**Relação:** referência operacional para observar canary pós-deploy e investigar comportamento histórico do CAPI/scoring sem subir Cloud SQL.

### `AUDITORIA_QUEBRA_PRODUCAO.md`
**Papel:** documento operacional em linguagem natural — lista os cenários que podem efetivamente quebrar produção (degradar score em massa, zerar valor enviado ao Meta, bloquear retreino) e que valem o tempo de atacar agora. Critério de entrada: precedente histórico OU pré-condição clara pra afetar ≥2% dos leads. Estrutura em 5 seções-pergunta (features chegam certas, modelo+config consistentes, promoção não quebra, detectamos quebra, retreino vai funcionar).
**Status:** ativo. Criado em 2026-05-10. Sucessor da seção V.3 do `registro_erros_ml.md` (que continua válida como histórico mas perde papel operacional).
**Relação:** camada operacional de auditoria. Quando precisa de detalhe técnico, links pra `PLANO_SAFEGUARD.md`, `PLANO_REFACTOR_MLOPS.md` ou `registro_erros_ml.md`. Não duplica conteúdo, apenas referencia.

---

---

## Camada 4 — Referência técnica (como o sistema funciona hoje)

### `ARQUITETURA_SISTEMA_COMPLETA.md`
**Papel:** visão geral de toda a arquitetura — pipelines, componentes, fluxo de dados, decisões de design.
**Status:** ⚠️ **parcialmente desatualizado**. Seção **BANCO DE DADOS atualizada em 2026-06-08** com a migração de schema (11–17/05): tabelas vivas `registros_ml`/`Client`/`UTMTracking`/`Activity`, antigas `Lead`/`leads_capi` marcadas mortas. Resto do doc (branches, A/B, modelo) ainda reflete 2026-04-28. Seções de Cloud SQL/MLflow corrigidas em 2026-04-26 — ver `operacoes_gcp_custos.md`.
**Relação:** é o documento de referência central (lido no início de toda sessão). Schema/tabelas: fonte autoritativa da virada é `PROCESSO_CAPI_LEAD_SURVEYS.md`. Para estado de branches e A/B, consultar `PLANO_EXECUCAO.md` e `AB_TEST.md`.
**Ação sugerida:** atualizar o resto (rollback edf23e9 em produção, A/B via canary). Seção de banco já atualizada.

### `AB_TEST.md`
**Papel:** documentação operacional do teste A/B champion/challenger — arquitetura de roteamento, configuração, critério de promoção, como ler resultados, problema DT-12, janela de dados válidos.
**Status:** 🔓 **REABERTO em 2026-04-28** após validação out-of-sample do Champion v4 (`60637bb9…`) atravessada. Deploy do v4 em curso via canary em sessão paralela.

### `SISTEMA_VALIDACAO_ML.md`
**Papel:** documenta o sistema de validação — como `validate_ml_performance.py` funciona, métricas calculadas.
**Status:** ativo, atualizado em 2026-03-17.

### `analise_valor_ml_devclub.md`
**Papel:** análise de valor real do ML para DevClub (LF40→LF46), responde se o sistema gera ROAS genuíno.
**Status:** snapshot — válido para o período analisado, não atualizado automaticamente.

### `EXPERIMENTO_MOAT_MODELO.md`
**Papel:** decomposição do moat — ablação de RF vs baselines (regras, conversion_rate_score, shallow tree). Mede quanto da AUC vem da survey unification, do feature engineering, da UTM normalization e do algoritmo RF em si.
**Status:** snapshot. Criado em 2026-04-24.
**Relação:** sugere redesign de UTM (remover do scoring; manter só em atribuição) — UTM diluiu AUC em −0.0024 vs survey-only no dataset atual. Item de backlog.

### `analise_perfil_leads_devclub.md`
**Papel:** breakdown de características dos leads por período P1/P2/P3 — composição de dispositivo, renda, medium, criativos.
**Status:** snapshot — conclusões já integradas em `INVESTIGACAO_BAIXO_DESEMPENHO.md`.

### `perfil_audiencia_dev20.md` e `perfil_audiencia_lf54.md`
**Papel:** snapshots da comparação de perfil de público entre o lançamento corrente (DEV20 / LF54) e o pool Top 5 ROAS histórico (LF40, LF41, LF44, LF45, LF47, n=39.771). Identificam drift de audiência por característica (gênero, idade, ocupação, faixa salarial, cartão, programação, computador) com Δpp e chi².
**Status:** ativos como artefatos de análise. Reproduzíveis via [scripts/perfil_audiencia.py](../scripts/perfil_audiencia.py) — `python -m scripts.perfil_audiencia --target <LF>`.
**Relação:** motivam **T1-13** em `PLANO_SAFEGUARD.md` (`audience_profile_drift` no monitoring) e a sequela 08/05/2026 em `PLANO_EXECUCAO.md`. A ausência desse check no monitoring está registrada como erro em `registro_erros_ml.md` § V.4.

### `monitoramento_term_google_vs_meta.md`
**Papel:** explica por que o bucket "outros" do `utm_term` no monitoramento juntava dois problemas distintos — placeholder do Meta não-renderizado (`{{...}}`, problema operacional pequeno) e ID de campanha do Google Ads (legítimo, ~23% do volume e crescendo) — e documenta as duas mudanças de monitoramento que separam os dois: (A) o alerta de bucket inflado passa a distinguir "categoria-nova" (alerta >2%) de "macro Meta" (só alerta se estourar >10%); (B) o drift cego-de-fonte de `Term/outros` foi silenciado, deixando o alerta restrito a Meta como autoridade única. Carrega a **nota de retreino**: dar ao Google categoria própria no `utm_term` (ex.: `Term_google`) em vez de "outros".
**Status:** ✅ ativo. Criado em 2026-06-23 na frente `feat/monitoring-term-source-aware` (só monitoramento, sem retreino).
**Relação:** o item de retreino se conecta a `analise_valor_decil_por_canal_google_vs_meta.md` (decil transfere pro Google, valor ≈ igual). Código: `src/monitoring/data_quality.py` (`_check_outros_buckets`, `_query_railway_outros_breakdown_enriched`), `src/monitoring/config.py` (`THRESHOLDS['outros_buckets']`), `configs/clients/devclub.yaml` (`silenced_drift_changes`).

### `analise_calibracao_jan30_abr28.md`
**Papel:** medição empírica de quão miscalibrados estão os scores brutos do Random Forest dos dois modelos em produção. Computa Expected Calibration Error (ECE) por decil a partir dos `model_metadata.json` dos runs `d51757f5...` (Champion `jan30`, 33k leads no test set) e `5d158f0a...` (Challenger `abr28`, 40k leads). Ajusta calibração isotônica in-sample e projeta razões de inflação que a fórmula `leadScore × ticket / CPL` sofreria sem calibração (D10 do Champion: 33×; D10 do Challenger: 27×). Declara 6 limitações honestamente, incluindo a ausência de validação out-of-sample como cota superior do ganho.
**Status:** ativo. Criado em 08/05/2026 como subsídio empírico à decisão de tratar calibração como caminho crítico.
**Relação:** motiva a criação de **DT-20** em `PLANO_REFACTOR_MLOPS.md` (calibração de probabilidades de scoring) e expõe a direção real do viés do `class_weight='balanced'` (superestima, não subestima). Validação out-of-sample com leads recentes do Railway é próximo passo declarado.

### `analise_lift_entrada_grupo_whatsapp.md`
**Papel:** mede se entrar no grupo de WhatsApp do lançamento prevê compra, sem artefato de match. "Entrou" casado por **telefone** (única chave do SendFlow, DDD+8); "comprou" por **e-mail** (chave neutra) — desenho que descarta a hipótese de o lift ser só maior casabilidade de telefone. Base = **todos os leads** (tabela `Lead`), não a pesquisa. Lift agregado **2,52x** (entrou 0,70% vs não 0,28%; ~110k leads, LF48–55+DEV20). Verificação: conversão é 100% casada por e-mail → chaves disjuntas.
**Status:** snapshot — criado em 2026-06-10. Reproduzível (leads via `load_match_spend_for_lf`; grupo via CSVs `data/devclub/SendFlow*.csv`).
**Relação:** subsídio empírico da feature "entrou no grupo de WhatsApp" (coleta live em produção via Sendhook). O confounder de **seleção/causalidade** (quem entra já tende a comprar) fica em aberto — só um grupo de controle resolve; o artefato de **match** está descartado.

### `analise_feature_user_agent.md`
**Papel:** avaliação da feature **User Agent** (aparelho do lead) com a skill `/data-scientist` — e, de passagem, o que prediz o grau de risco da TMB. Veredito: UA **arquivada** (valor marginal ~zero, redundante com a pesquisa: +0,005 AUC, zero de concentração de decis); o grau de risco TMB é dominado por uma única feature ("Você possui cartão de crédito?" — sem cartão ~dobra a chance de "Alto"). Inclui o desenho do teste mínimo no modelo real, caso reabra.
**Status:** snapshot — criado em 2026-06-29. Modelos de adaptação (RF simplificado) reproduzíveis; dados via `analytics.leads`/`analytics.sales`.
**Relação:** fecha o item "User Agent + dispositivos" do backlog de features (`PLANO_EXECUCAO.md`, `EXPERIMENTO_MOAT_MODELO.md`). Dados do UA: `CONSOLIDACAO_CLOUDSQL.md`.

### `INVESTIGACAO_BAIXO_DESEMPENHO.md`
**Papel:** investigação completa da queda do D10 de ~42% (P1) para ~30% (P3). Documenta hipóteses testadas, causas confirmadas (mudança LQHQ→LQ em 10/03, crash P2 por TMB All + encoding quebrado), análise do gap residual e rollback executado em 13/04/2026.
**Status:** ativo. Última atualização: 2026-04-13. Investigação encerrada — todas as hipóteses testadas, nenhuma pendente de verificação.
**Relação:** documenta o contexto que motivou o rollback e o A/B test atual. Referenciado por `AB_TEST.md` e `PLANO_EXECUCAO.md`.

### `registro_erros_ml.md` 🔄 SUBSTITUI `Erros_cometidos.md` + `auditoria_dano_bugs_ml.md`
**Papel:** registro técnico unificado — bugs com impacto real, decisões erradas, padrões repetidos, **backtests contrafactuais (mar–mai/2026)** quantificando dano dos clusters de encoding, **medidas corretivas implementadas** (abr–mai/2026) e **frentes preventivas em aberto** (auditoria viva: por que parquets+smoke não pegaram Cluster 5, 4 features binárias raw, backlog "tentar quebrar produção").
**Status:** ativo. Documento vivo — adicionar novos erros conforme ocorrem; expandir Seção V conforme cada cenário do backlog é validado.
**Origem:** unificação de `Erros_cometidos.md` (criado abr/2026) + `auditoria_dano_bugs_ml.md` (criado mai/2026, audiência cliente externo, re-tecnicado para uso interno).
**Relação:** é a motivação de cada item do `PLANO_SAFEGUARD.md`. Leitura obrigatória antes de qualquer mudança de infraestrutura. Seção V (Frentes preventivas em aberto) alimenta H1/H2 do `PLANO_EXECUCAO.md`.

### `arquivo/Erros_cometidos.md` 📦 ARQUIVADO
**Status:** ✅ **ARQUIVADO em 2026-05-08.** Conteúdo migrado para `registro_erros_ml.md`. Permanece para referência histórica.

### `arquivo/auditoria_dano_bugs_ml.md` 📦 ARQUIVADO
**Status:** ✅ **ARQUIVADO em 2026-05-08.** Conteúdo (audiência cliente externo) migrado e re-tecnicado para `registro_erros_ml.md`. PDF entregue ao cliente em `V2/propostas_e_apresentacoes/auditoria_dano_bugs_ml.pdf`.

### `modelo_producao_devclub_15mar2026_interno.txt`
**Papel:** documentação interna do modelo em produção (run `2a98e51c`, 59 features, AUC 0.745).
**Status:** snapshot histórico — o modelo ativo em produção hoje é o jan30 (`d51757f5`), não o `2a98e51c`. Complementa `memory/project_active_model.md`.

---

## Camada 5 — Histórico (decisões passadas, concluídas)

> Os documentos abaixo já estão fisicamente em `docs/arquivo/` desde 2026-04. Permanecem listados aqui apenas como mapa do que foi resolvido — não há ação pendente em nenhum deles.

### `arquivo/DIVERGENCIAS_TREINO_PRODUCAO.md`
**Papel:** documentou as divergências entre treino e produção em março/2026 — motivação central do refactor.
**Status:** ✅ ARQUIVADO. Resolvido pelo refactor (deploy 24/03/2026).

### `arquivo/MIGRACAO_MLFLOW_GCS.md`
**Papel:** plano de migração do MLflow de SQLite para Cloud SQL.
**Status:** ✅ ARQUIVADO. Migrado em 17/03/2026, 50 runs no Cloud SQL.

### `arquivo/unificacao-mlflow.md`
**Papel:** plano de unificação do feature registry no MLflow.
**Status:** ✅ ARQUIVADO. MLflow unificado: 1 tracking URI PostgreSQL + 1 artifact store GCS.

### `arquivo/migracao_sheets_postgresql.md`
**Papel:** migração de Sheets para PostgreSQL (Railway).
**Status:** ✅ ARQUIVADO. Railway PostgreSQL ativo desde 25/02/2026 para `leads_capi`.

### `arquivo/purchase_events_status.md`
**Papel:** status de implementação dos eventos de compra CAPI.
**Status:** ✅ ARQUIVADO. Purchase events implementados (FBP/FBC + value enviados ao Meta após carrinho).

### `arquivo/CHECKLIST_DEPLOY_REFACTOR.md`
**Papel:** runbook operacional de uso único para o merge e deploy da branch `refactor/mlops-core`.
**Status:** ✅ ARQUIVADO. Concluído em 24/03/2026, todos os 15 itens executados.

---

## Arquivo fora de lugar

### `pagina2_codigo_modificado.js`
**Papel:** snippet de código JavaScript — provavelmente instrução para dev front-end.
**Status:** não pertence a `docs/`. Mover para `docs/frontend/` ou entregar e deletar.

---

## Como os documentos se relacionam

```
ESTRATÉGIA (porquê)
  bring_data_02_execução.md      (visão de negócio)
  swot_bringdata.md              (forças, fraquezas, oportunidades, ameaças)
  bring_data_produto.md          (script comercial)

REFERÊNCIA TÉCNICA (como o sistema funciona)
  ARQUITETURA_SISTEMA_COMPLETA.md    ← atualizar para estado atual

ROADMAP ÚNICO (o que fazer e quando)  ⭐ leitura diária
  PLANO_EXECUCAO.md
        ↓ consome (catálogos técnicos = "como")
        ├── PLANO_SAFEGUARD.md        (T1-X / T2-X / T3-X — spec)
        │       └── Erros_cometidos.md   (motivação histórica)
        ├── PLANO_REFACTOR_MLOPS.md   (DT-X + histórico do refactor)
        │       └── arquivo/CHECKLIST_DEPLOY_REFACTOR.md  (deploy 24/03)
        ├── AB_TEST.md                (design A/B — em Standby)
        │       └── INVESTIGACAO_BAIXO_DESEMPENHO.md  (rollback P1→P3)
        └── CHECKLIST_ONBOARDING_NEW_CLIENT.md  (quando Cliente B chegar)

ANÁLISES (snapshots históricos)
  analise_valor_ml_devclub.md          (ROAS LF40→LF48)
  analise_perfil_leads_devclub.md      (perfil P1→P3)
  analise_calibracao_jan30_abr28.md    (ECE Champion + Challenger — 08/05)
  EXPERIMENTO_MOAT_MODELO.md           (decomposição do moat — 24/04)
  analise_feature_user_agent.md        (avaliação da feature User Agent — 29/06)
  SISTEMA_VALIDACAO_ML.md              (validate_ml_performance.py)
  revenue_forecast.md                  (previsão de faturamento — MAE 2,6%)

RUNBOOKS (tarefas específicas)
  acesso_sql.md / acesso_sheets.md / MLFLOW.md / monitoring-api.md
  operacoes_gcp_custos.md              (otimizações + protocolo Cloud SQL)

ARQUIVADOS (concluído, referência)
  arquivo/ROADMAP_MLOPS_MATURIDADE.md  (absorvido pelo PLANO_EXECUCAO)
  arquivo/CHECKLIST_DEPLOY_REFACTOR.md (deploy 24/03)
  arquivo/DIVERGENCIAS_TREINO_PRODUCAO.md / MIGRACAO_MLFLOW_GCS.md
  arquivo/unificacao-mlflow.md / migracao_sheets_postgresql.md / purchase_events_status.md
```

---

## Resumo das ações pendentes na documentação

| Documento | Ação | Quando |
|---|---|---|
| `ARQUITETURA_SISTEMA_COMPLETA.md` | Atualizar: rollback edf23e9 em prod, retreinos v4, A/B em standby, canary direto | H1.4 do PLANO_EXECUCAO |
| `pagina2_codigo_modificado.js` | Mover para `docs/frontend/` ou deletar | Qualquer momento |
| `monitoring_golden_snapshot.json` | Capturar — pré-requisito do deploy canary (H1.2 do PLANO_EXECUCAO) | 🔴 antes do próximo deploy |

---

## Skills disponíveis

Skills invocáveis via `/skill` para tarefas recorrentes:

| Skill | Quando usar | Documenta-ção |
|---|---|---|
| `/investigate` | Investigar por que um lançamento foi ruim — números históricos, causas do baixo ROAS, D10% anormal | `INVESTIGACAO_BAIXO_DESEMPENHO.md` |
| `/investigate-ab` | Verificar se o teste A/B está tecnicamente válido — roteamento correto, eventos chegando, janela limpa | `AB_TEST.md` |
| `/safeguard` | Auditoria completa de integridade — encoding, CAPI, deploy, timezone, monitoramento | `PLANO_SAFEGUARD.md` |
| `/docs` | Skill master de documentação — modos `mapear`, `unificar`, `arquivar`, `indexar`, `auditar`. Substitui `/plan-integrator`. | Este índice + `V2/.claude/skills/docs/SKILL.md` |
