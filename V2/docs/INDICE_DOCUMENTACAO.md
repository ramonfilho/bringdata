# Índice de Documentação — Bring Data V2

**Atualizado:** 2026-05-17
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

### `google_ads_pendencias.md` 📚 Catálogo técnico (H6)
**Papel:** especificação dos pré-requisitos e passos de implementação para envio de eventos ao Google Ads (Enhanced Conversions for Leads). Documenta decisões fixadas (estratégia, credenciais), bloqueantes abertos (gclid não capturado), e a infra já preparada (`should_send_to_destination`, `CAPIConfig`, dispatcher).
**Status:** ativo. Atualizado em 2026-05-18 (virada de transporte: legacy `UploadClickConversions` → Data Manager API).
**Relação:** referenciado por `PLANO_EXECUCAO.md` em H6 → "Diversificação de canais". Tese estratégica em `swot_bringdata.md` (F8/W4/O4). Escopo: só DevClub.

### `PROCESSO_CAPI_LEAD_SURVEYS.md`
**Papel:** especificação completa de fazer o evento CAPI scoreado por ML (`LeadQualified` + `LeadQualifiedHighQuality`) ser disparado a partir de **duas** tabelas — `Lead` (como hoje) **e** `lead_surveys` — sem tocar no fluxo da `Lead`. Cobre a investigação (esteiras quase disjuntas: só 13 emails em comum em 7d; a esteira nova já manda eventos genéricos próprios pro Meta), cobertura de recuperação por JOIN (fbp/fbc 98%, `computador` ~90% via log vs ~100% no `Lead`), decisões fixadas do usuário (coluna `computador` pedida ao front, `leads_capi` só fallback, forward-only, monitoramento estendido junto, ledger próprio `registros_ml`, isolamento do fluxo `Lead`, fail-loud, restrições duras), verificação de vocabulário das respostas (100% seguro) e pendências obrigatórias pro go-live (vocabulário de `computador` quando a coluna chegar; whitelist de UTM dos survey leads — classe de quebra histórica "Cluster 5"/"cenário 1.2").
**Status:** 🚧 investigação concluída · desenho fechado · ⚪ **implementação BLOQUEADA** até autorização explícita do usuário **e** chegada da coluna `computador` em `lead_surveys`. Nenhum código escrito. Criado em 2026-05-17.
**Relação:** dependência externa rastreada também em `instrucoes_dev_frontend_capi.md`. Classe de quebra histórica referenciada em `AUDITORIA_QUEBRA_PRODUCAO.md`. Toca o endpoint `/railway/process-pending` (`api/app.py`) e o mapeamento `api/railway_mapping.py`; quando ligado, exige extensão do monitoramento (`CRITICAL_ALERTS_SPEC.md` / digest). Regra fail-loud: `CLAUDE.md`.

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
**Status:** ativo (entregue a terceiros).

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
**Status:** ⚠️ **parcialmente desatualizado**. Última atualização: 2026-03-24 (pós-deploy do refactor). Reflete `src/core/` e multi-cliente, mas não reflete o estado atual das branches (rollback em produção, canary ativo, A/B test) — foi atualizado antes do rollback de 13/04. Seções de Cloud SQL/MLflow corrigidas em 2026-04-26 com aviso da parada — ver `operacoes_gcp_custos.md`.
**Relação:** é o documento de referência central (lido no início de toda sessão). Para o estado atual de branches e testes A/B, consultar `PLANO_EXECUCAO.md` e `AB_TEST.md`.
**Ação sugerida:** atualizar para refletir que o rollback edf23e9 está em produção e o A/B test está ativo via canary.

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
  EXPERIMENTO_MOAT_MODELO.md           (decomposição do moat — 24/04)
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
