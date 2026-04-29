# Plano de Execução — Smart Ads V2 (Roadmap Único)

**Atualizado:** 2026-04-28
**Propósito:** este é o **único** documento de "o que fazer e quando" no projeto. Toda a sequência de trabalho — segurança, A/B test, unificação, refactor multi-cliente, escala B2B, backlog de features — vive aqui, em horizontes ordenados por dependência.

## Como ler este documento

- **Este documento responde:** o que fazer agora? em que ordem? quem depende de quem?
- **Para o "como" técnico de um item, vá ao catálogo correspondente:**
  - `PLANO_SAFEGUARD.md` — especificação técnica de cada item T1-X / T2-X / T3-X
  - `PLANO_REFACTOR_MLOPS.md` — histórico do refactor + especificação de cada DT-X
  - `ARQUITETURA_SISTEMA_COMPLETA.md` — visão de sistema, fluxos, endpoints
  - `AB_TEST.md` — design do teste A/B (executar quando o gate de validação for retomado)
  - `Erros_cometidos.md` — motivação histórica dos safeguards
- **Catálogos não definem prioridade.** Status canônico de cada item (em curso, concluído, em standby) está aqui.

---

## Estado atual (28/04/2026)

| Componente | Estado |
|---|---|
| **Validação OOS Champion v4** | ✅ **Atravessada favoravelmente em 28/04** — gate único do roadmap. Todo bloco STANDBY destravado. |
| **Deploy main unificada** | 🔄 **Em execução** em sessão paralela — canary 10% → 50% → 100% conforme `AB_TEST.md` "Nova estratégia — canary direto". |
| **Modelo no rollback** (90% / 50% / 0% conforme estágio do canary) | jan30 ORIGINAL (`d51757f5`) |
| **Modelo no canary main** (10% / 50% / 100% conforme estágio) | Champion v4 (`60637bb98b94421b9c7579bb4ac1b1ad`) — AUC 0.748, OHE default |
| **Challenger v4 (em standby até promoção do v4)** | `7d08ae0302da420aa99559d4d4f55025` — AUC 0.745 |
| **A/B test** | 🔓 **Reaberto em 28/04** — frente ativa novamente após gate atravessado. Roteamento exato definido pela sessão de deploy. |
| **Cloud SQL `smart-ads-db`** | Parado desde 26/04 (`activation-policy=NEVER`); subir antes de retreinar — ver `operacoes_gcp_custos.md` |
| **Tier 1 safeguards** | ✅ 11/11 concluídos (até 23/04/2026) |
| **T2-2 (log por etapa)** | ✅ 28/04/2026 — commits `8b46645` |
| **T2-3 (importance weighting)** | ✅ 28/04/2026 — commits `c03d645`, `f8dc4f7`. Feature pronta no repertório (default desligado). Efeito interno marginal; sinal externo D9+D10 lift 6.88× confirma valor do ML em produção. |
| **DT-13 (utm_term zerando)** | ✅ 28/04/2026 — commit `dafe85d` |

---

## 🚦 GATE ÚNICO — Validação out-of-sample do Champion v4 ✅ ATRAVESSADA (28/04/2026)

**Resultado:** decisão de seguir com o A/B — Champion v4 validado para entrar em produção via canary. Detalhes operacionais da validação ficam fora deste plano (registrados na sessão que executou o teste).

**Consequência imediata:** todo o bloco STANDBY abaixo está destravado. H2.1 (deploy canary main) entra em execução em sessão paralela; A/B test reabre como frente ativa; Sprint 2 do `retraining_orchestrator` volta para o backlog ativo.

---

## Princípios de execução

1. **A ordem importa.** Não pular ou antecipar itens sem instrução explícita.
2. **Protocolo por item:** implementar → testar → commitar → deployar/integrar **individualmente** antes de avançar para o próximo. Aplica-se a cada T1-X, T2-X, T3-X, R-X, DT-X. Detalhes em `PLANO_SAFEGUARD.md` → "Protocolo obrigatório por item".
3. **Catálogos têm o "como"; este documento tem o "quando".** Para cada item abaixo, link para o catálogo onde a especificação técnica vive.
4. **Toda transformação de dados continua canônica em `src/core/`** — nunca reimplementar fora.

---

## Cronograma agregado

| Horizonte | Janela | Foco principal | Status |
|---|---|---|---|
| **H1 — Concluído** | 27/04 → 28/04 | DT-13 ✅, ARQUITETURA ✅, gate atravessado ✅ | ✅ |
| **H2 — Em execução** | 28/04 → +1-3 semanas | Deploy canary main em sessão paralela | 🔄 |
| **Independente do gate** | já concluído | Importance weighting ✅, log por etapa ✅ | ✅ |
| **H3 — Tier 2/3 restante** | maio-junho 2026 | Safeguards remanescentes (10 itens) | em fila |
| **H4 — Pré-Cliente B** | em paralelo com H2/H3 | R1/R2/R3, schema check, testes unitários | gate Cliente B |
| **H5 — Cliente B** | depende de dados externos | Onboarding Fase 3b + EDA Generator | dado externo |
| **H6 — Escala 2-4 clientes** | 2-4 meses após Cliente B | CI/CD, drift trigger, dashboard, registry | depende H5 |
| **H7 — Escala 5+ clientes** | quando infra atual virar gargalo | Stack GCP completo (Pub/Sub, Dataflow, etc.) | demand-driven |
| **Standby destravado (28/04)** | volta ao backlog ativo | A/B test, Sprint 2 retraining_orchestrator | ✅ |

---

# ROADMAP

## H1 — CONCLUÍDO (28/04/2026)

### 1.1 — Validação out-of-sample do Champion v4 ✅ ATRAVESSADA
- Saída: decisão favorável ao v4. Detalhes da execução fora deste plano (sessão paralela).
- Consequência: H2 destravado e em execução; STANDBY reaberto.

### 1.2 — ~~Capturar golden snapshot do monitoring~~ → REPOSICIONADO (não rodar agora)
- **Por que não agora:** o sistema está com `distribution_drift HIGH` em Medium e `score_distribution_change HIGH` em D10 desde 22/04. Capturar o snapshot neste estado cristaliza um baseline degradado — regressões futuras seriam comparadas contra um estado já ruim e a divergência atual viraria "normal".
- **Quando capturar:** depois que o sistema estiver saudável. Dois caminhos possíveis (a decisão depende do resultado de H1.1):
  - **Caminho A — pós-deploy v4 a 10%:** Champion v4 foi treinado com janela até 02/04 (pós-explosão Hotmart), então o feature registry dele já reflete o mix atual de Medium. Se promovido, os alertas HIGH tendem a cair sozinhos. Capturar 24-48h depois do canary 10% estável.
  - **Caminho B — pós-retreino corretivo:** se H1.1 mostrar que v4 não resolve, retreinar com importance weighting (T2-3) ou outra correção; capturar só após estabilização.
- **Status:** pendente sem prazo rígido. Não bloqueia H2.1 (canary inicial). Vira resultado de um sistema saudável, não pré-requisito mecânico.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → "Fase 2 — Pendente — validação do monitoramento".

### 1.3 — Fix DT-13 (utm_term numérico zerando encode) ✅ commit `dafe85d`

### 1.4 — Atualizar `ARQUITETURA_SISTEMA_COMPLETA.md` ✅ commit `15fe32a`

---

## H2 — Pós-validação (em execução em sessão paralela)

### 2.1 — Deploy canary da main unificada 🔄 EM EXECUÇÃO
- **Onde:** sessão paralela do usuário (não nesta sessão).
- **Estratégia:** canary direto 10% → 50% → 100% com critério puramente técnico. Detalhes em `AB_TEST.md`.
- **Captura do golden snapshot (H1.2):** 24-48h após canary 10% estável e alertas pré-existentes terem cedido. Se não cederem, pausar antes de avançar para 50% e diagnosticar.
- **Rollback:** ~10s via `gcloud run services update-traffic` para `00269-jjn`.

---

## Trabalho técnico já executado (independente do gate)

### Log de registros por etapa do pipeline (T2-2) ✅ commit `8b46645`
- Instrumentação em `train_pipeline.py` (6 pontos) e `production_pipeline.py` (2 pontos).
- Catálogo: `PLANO_SAFEGUARD.md` Tier 2 → T2-2.

### Importance weighting do grupo controle (T2-3) — ✅ implementado / efeito interno marginal
- **Estado (28/04/2026):** feature implementada no `train_pipeline.py` (commits `c03d645`, `f8dc4f7`). Calcula pesos por grupo (CONTROLE/ML/NEUTRO) via inverso de frequência com expoente `alpha`, scope=train. CLI: `--control-group-weights --control-alpha {0..1}` + `--train-ratio` para ajustar split. Validado tecnicamente em sweep de alphas no MLflow remoto (Cloud SQL subido + parado em 28/04).
- **Resultado do experimento (split 80/20, ~44k CONTROLE no train):** efeito sobre métricas de teste interno é marginal — range AUC 0.003 entre `alpha=0` e `alpha=1`; monotonia oscila sem padrão monotônico. A maior parte do ganho sobre o Champion v4 (AUC 0.748 → 0.756) veio do split 80/20 + 5 dias adicionais de dados, não do reweighting.
- **Sinal positivo paralelo (validação real):** investigação D9/D10 ML × CTRL na janela limpa madura 26–30/03 mostrou **lift 6.88×** do top decil ML sobre CTRL total (CR 0.49% vs 0.07%) — o ML em produção funciona; reweighting interno apenas não muda métricas holdout.
- **Conclusão prática:** feature fica pronta no repertório (default desligado). Próxima retomada faz sentido após gate H1.1 — se Champion v4 passar e for promovido, refazer o experimento pós-DEV20 com janela CONTROLE mais madura.
- **Catálogo:** `PLANO_SAFEGUARD.md` Tier 2 → T2-3.

### Refatoração CAPI allowlist (DT-CAPI-01) — ✅ commit `41cc2bf` / pendente deploy
- **Bug histórico (09/04 → 28/04/2026):** `utm_source_allowlist` foi adicionada em 09/04 (commit `6b8fc05`) mas aplicada em apenas 2 de 4 caminhos CAPI no `app.py`. Os paths `/webhook/lead_capture` (principal do frontend) e `/predict/batch` (Apps Script) ficaram sem filtro. Resultado: ~4.200 eventos não-Meta foram para o Pixel da Meta no período (google-ads 2.016, gruposantigos 552, (null) 461, API 431, tiktok 420, ig 159, outros).
- **Fix (29/04/2026):** lógica centralizada em `should_send_to_destination(lead, capi_config, destination='meta')` em `capi_integration.py`. Os 4 paths chamam a mesma função. Parametrizado por `destination` — para ativar Google Ads basta adicionar branch lendo allowlist específica.
- **Validações pré-commit (camadas 1-2):** sintaxe + imports OK; paridade 100% com lógica antiga em 50 casos sintéticos cobrindo allowlist hits/misses, blocklist matches, vazios/None, case sensitivity, chaves alternativas (`source` vs `utm_source`).
- **Validação pós-deploy obrigatória:** critérios genéricos em `PLANO_SAFEGUARD.md` T1-9 (progressão de tráfego) + checks específicos do fix:
  - **Smoke test:** 5 leads sintéticos via curl em produção (mix `facebook-ads`/`google-ads`/`tiktok`/`null`/campaign=`LEAD | LQ`) confirmando capiStatus esperado para cada source.
  - **24h em produção:** `google-ads` com `capiStatus='success'` deve cair de ~91% para ~0% (efeito esperado); `facebook-ads` com `capiStatus='success'` deve permanecer ≥ 95%; `capi_sent` total cai 10-15%.
  - **Meta Events Manager (Pixel `1937807493703815`):** match rate não pode piorar; volume diário de `LeadQualified` cai 10-15% conforme esperado.
  - **Sinais de regressão para rollback:** `facebook-ads success` < 90% (refatoração quebrou); `acceptance_rate` Meta despenca; 5xx em `/webhook/lead_capture` aumentando.
- **Catálogo:** `ARQUITETURA_SISTEMA_COMPLETA.md` → "Roteamento por plataforma (DT-CAPI-01)" (atualizado de "correção parcial" para "correção completa").

---

## H3 — TIER 2 / TIER 3 SAFEGUARDS RESTANTES (maio–junho)

Implementar sobre o código unificado. Nenhum é bloqueador de produção. Status canônico em `PLANO_SAFEGUARD.md`.

### Tier 2 (qualidade de dados — ✅ todos concluídos)

| ID | Item curto | Status | Catálogo |
|---|---|---|---|
| T2-4 | Remover limite de 10.000 registros em queries de validação | ✅ commit `a578408` | `PLANO_SAFEGUARD.md` Tier 2 |
| T2-5 | Filtro vendas aprovadas | ✅ já implementado em `data_loader.py` | `PLANO_SAFEGUARD.md` Tier 2 |
| T2-6 | Eliminar exceções silenciosas (orchestrator.py db.rollback + parse gspread) | ✅ 28/04 | `PLANO_SAFEGUARD.md` Tier 2 |
| T2-8 | Alerta para feature high-importance com variance baixa | ✅ coberto por `check_distribution_drift` existente | `PLANO_SAFEGUARD.md` Tier 2 |

### Tier 3 (observabilidade — ✅ 5/5 ativos concluídos; T3-3 adiado, T3-4 cancelado)

| ID | Item curto | Catálogo |
|---|---|---|
| T3-1 | Progressão canary documentada no `deploy_capi.sh` | ✅ 29/04 | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-2 | Script de smoke test pós-deploy | ✅ via T1-10 Gate B (`smoke_test_revision.py` + `deploy_capi.sh:542`) | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-3 | Branch protection no GitHub | ⏸ adiável (exige plano Pro ou repo público) | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-5 | Relatório consolidado de rotinas | ✅ 29/04 (no `run_daily_check`) | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-6 | Validação MODEL_PATH | ✅ 29/04 commit `a1213f9` | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-7 | Reconciliação run_id | ✅ 29/04 commit `a1213f9` | `PLANO_SAFEGUARD.md` Tier 3 |
| ~~T3-4~~ | ~~Alerta token Meta < 10 dias~~ — CANCELADO (System User vitalício) | — |

---

## H4 — PRÉ-CLIENTE B (em paralelo com H2/H3)

Itens independentes dos dados do Cliente B. Resolver antes de iniciar Fase 3b do refactor.

### 4.1 — R1 / DT-8: Remover features fantasmas em produção ✅ resolvido (29/04/2026)
- **Estado atual:** verificação confirma que `production_pipeline.py` **não tem nenhuma criação inline** de `nome_valido`/`email_valido`/`telefone_valido`. Toda a lógica vive em `core/feature_engineering.py` atrás da flag `create_valido_features` (default False; DevClub usa True). Sem código fantasma para remover.
- **Quando ficou resolvido:** durante o porte #2 da unificação Fase 3 (23/04/2026) — features migraram para `core/feature_engineering.py` e a versão inline em produção sumiu junto.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-8.

### 4.2 — R2 / DT-10: Hardcodes de modelo em treino ✅ resolvido (29/04/2026)
- **Estado:** os fallbacks hardcoded de `PESOS_COMPRADOR` e `DEFAULT_HYPERPARAMS` em `train_pipeline.py` foram removidos. Agora o treino lê obrigatoriamente de `client_config.model.buyer_weights` e `client_config.model.hyperparameters`; se qualquer dos dois faltar no YAML do cliente, o treino aborta com `ValueError [R2/DT-10]` apontando exatamente o que adicionar. Cliente B esquecer = aborta loud em vez de treinar com pesos DevClub.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-10.

### 4.3 — R3 / DT-9: Remover aliases ordinais transitórios
- **O quê:** verificar `'idade'` e `'faixa_salarial'` em `encoding.ordinal_variables` do `configs/clients/devclub.yaml`. Se ainda presentes como aliases curtos, remover — o df chega com nomes longos, alias curto = encoding silenciosamente pulado.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-9.

### 4.4 — `src/core/validation.py` — schema check pré-treino
- **O quê:** novo módulo. Validação no início de `train_pipeline.py`: schema esperado, nulos em features obrigatórias, ranges críticos.
- **Por quê:** sem isso, dado ruim do Cliente B pode corromper o pipeline silenciosamente.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` §12 "Caminho para Nível 2".

### 4.5 — DT-2: Testes unitários parametrizados em `src/core/`
- **O quê:** `pytest tests/core/ --client devclub --client clientb` para `utm.py`, `medium.py`, `encoding.py`. Parametrizados com dois `ClientConfig` reais.
- **Por quê:** hoje toda validação é integration test (~10–20 min). Bloqueia iteração rápida com 2+ clientes.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-2.

---

## H5 — ONBOARDING CLIENTE B (depende de dado externo)

### 5.1 — Dados do Cliente B chegam ⚪ BLOQUEADO
- **O quê:** formulário XLS + export de vendas + cadência do lançamento.
- **Bloqueio:** depende do cliente.

### 5.2 — `clientb.yaml` + inspeção de dados
- **Catálogo:** `CHECKLIST_ONBOARDING_NEW_CLIENT.md`.

### 5.3 — Onboarding Cliente B (Fase 3b do refactor)
- **Pré-condições:** 4.4 (schema check), 4.5 (testes unitários), 5.1 + 5.2.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` §7 Fase 3b.

### 5.4 — EDA Generator (`src/eda/generate_client_config.py`)
- **O quê:** geração automática de `clientX.yaml` a partir dos dados brutos do cliente.
- **Pré-condição:** dois configs (`devclub.yaml` + `clientb.yaml`) escritos manualmente — padrão claro o suficiente para automatizar.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` §7 Fase 4.

---

## H6 — ESCALA 2-4 CLIENTES (após Cliente B estável)

| ID | Item | Pré-condição | Catálogo |
|---|---|---|---|
| 6.1 | GitHub Actions CI — push → lint → `pytest tests/core/` → parity check → merge liberado | DT-2 (4.5) + 2 clientes ativos | absorvido |
| 6.2 | Sprint 3 `retraining_orchestrator.py` — trigger de retreino por drift | 500+ leads/mês por cliente | absorvido |
| 6.3 | Looker Studio — dashboard de ROAS, CPL, distribuição de decis por cliente/lançamento | Cliente B ativo | absorvido |
| 6.4 | Vertex AI Model Registry — substituir `configs/active_models/*.yaml` manual por registro centralizado | 3+ clientes ativos | absorvido |

---

## H7 — ESCALA 5+ CLIENTES (B2B)

Componentes que só fazem sentido quando a infraestrutura atual virar gargalo real. Ver tabela completa em conteúdo absorvido do antigo `ROADMAP_MLOPS_MATURIDADE.md` (arquivado).

| Componente | Substitui | Condição real para entrar |
|---|---|---|
| Pub/Sub + Apache Beam + Dataflow | Webhook síncrono no Cloud Run | 10k+ leads/dia ou múltiplas fontes simultâneas |
| BigQuery Feature Store | Features computadas a cada treino em `src/core/` | Features caras de computar ou compartilhadas entre múltiplos modelos |
| Kubeflow / Vertex AI Pipelines | `train_pipeline.py` manual | Múltiplos engenheiros editando o pipeline ou treino > diário |
| Vertex AI Endpoints | Cloud Run para serving | Cloud Run mais caro que Vertex AI na escala atingida |
| Vertex AI Model Monitoring | `monitoring/orchestrator.py` customizado | 5+ clientes — monitor customizado não escala mais |

> MLflow permanece mesmo no stack completo — é portável e trackeia experimentos de forma que o Vertex AI não replica.

---

## ✅ STANDBY DESTRAVADO (28/04/2026)

Itens que estavam suspensos até o gate H1.1. Com gate atravessado, voltam ao backlog ativo:

- **A/B test completo** — frente ativa novamente; design em `AB_TEST.md`. Roteamento exato (UTM, Cloud Run revision split, ou híbrido) é decisão da sessão de deploy.
- **Sprint 2 do `retraining_orchestrator.py` — quality gate automático pós-treino** — pode retomar; espera-se que use thresholds informados pela primeira rodada de A/B pós-deploy.
- **DT-12 — encoding por variante A/B (`encoding_overrides`)** — só relevante se o A/B usar dois modelos com encoding diferente. Resolvido na configuração atual de v4 (OHE default); documentado em `PLANO_REFACTOR_MLOPS.md` § DT-12.
- **Novo ciclo A/B com modelo retreinado** (Fase 5 original) — destravado; aguarda apenas resultado do canary corrente.

---

## 📋 BACKLOG — Features e melhorias sem prazo imediato

### Modelo

- **Redesign UTM:** remover do scoring, manter só em atribuição downstream. UTM diluiu AUC em −0.0024 vs survey-only no test set (Champion v4). Investigado em `EXPERIMENTO_MOAT_MODELO.md` (24/04).
- **Holdout contrafactual permanente** 5–10% de leads sem ML para calibração contínua de baseline. W1 do SWOT — risco crítico antes de cliente B.
- **Retreino com dados pós-01/04/2026** para refletir mix atual de públicos (5/6 categorias Medium do treino jan30 sumiram). Pré-requisitos: fix DT-13 (1.3) + decisão sobre `Source='org'`. Investigado em 22/04 — ver `INVESTIGACAO_BAIXO_DESEMPENHO.md`.
- **Recalibração `revenue_forecast.md`** após fechamento DEV20 e LF48 — taxa histórica (1,23%) pode ficar desatualizada se audiência mudar.

### Diversificação de canais (mitigação W4 SWOT)

- **Google Ads Enhanced Conversions** — arquitetura F8 já conceptualmente resolvida; falta implementação. Mitigação parcial (utm_source_allowlist) aplicada em 09/04.
- **TikTok Events API** — público jovem em crescimento, especialmente cursos.
- **LinkedIn Insight Tag** — para verticais B2B futuros.

### Features futuras (data flywheel)

- **User Agent + dispositivos** — sinal hoje ausente.
- **Similar leads** (kNN no espaço de features) — leverage do flywheel.
- **LTV por comprador** — recompra/upsell.
- **Histórico de lead_scores anteriores** — quando o mesmo lead reaparece em lançamento posterior.
- **Interação na página de checkout** — sinal de proximidade real à compra.

### Bugs latentes (não bloqueadores)

- **DT-7:** threshold de Medium calculado sobre janela errada (`src/core/medium.py`). Catálogo: `PLANO_REFACTOR_MLOPS.md` → DT-7.
- **DT-11 / R5:** imports dinâmicos em `monitoring/orchestrator.py` (5 imports dentro de `run_daily_check()` em vez do topo). Catálogo: `PLANO_REFACTOR_MLOPS.md` → DT-11.
- **R4:** guard de coluna Medium ausente em `production_pipeline.py` (treino tem; produção não).
- **`/railway/process-pending`:** `.str accessor` em batches de 1 lead com NaN em UTM (~0,3% polls). Auto-recupera no próximo poll. Documentado em `operacoes_gcp_custos.md`.
- **`/bigquery/stats`:** retorna 0 rows — sync nunca foi ativado; considerar deletar se não em uso.

### NLP (sem prazo)

- **`src/nlp/`** — campo de texto livre no formulário. Fase 5 do refactor. Catálogo: `PLANO_REFACTOR_MLOPS.md` §7 Fase 5.

---

## ✅ CONCLUÍDO — Histórico (2026)

| Marco | Data | Catálogo |
|---|---|---|
| Fase 1 do refactor — módulos `src/core/` | jan-mar/2026 | `PLANO_REFACTOR_MLOPS.md` Fase 1 |
| Migração Sheets → Railway PostgreSQL | 25/02/2026 | `arquivo/migracao_sheets_postgresql.md` |
| Migração MLflow tracking → Cloud SQL | 17/03/2026 | `arquivo/MIGRACAO_MLFLOW_GCS.md` |
| Fase 2 — Deploy do refactor (item 19) | 24/03/2026 | `arquivo/CHECKLIST_DEPLOY_REFACTOR.md` |
| DT-CAPI-01: `utm_source_allowlist` (só Meta/Instagram) | 09/04/2026 | `ARQUITETURA_SISTEMA_COMPLETA.md` |
| DT-CAPI-02: `utm_blocklist` LEAD\|LQ | 09/04/2026 | `ARQUITETURA_SISTEMA_COMPLETA.md` |
| Rollback decision — worktrees locais aposentados | 13/04/2026 | `ROLLBACK_DECISION.md` |
| Fase 3 — Porte #1 (Opção A encoding) | 23/04/2026 | Anexo "Log histórico de portes" abaixo |
| Fase 3 — Porte #2 (valido features) | 23/04/2026 | Anexo "Log histórico de portes" abaixo |
| Retreinos coordenados v4 (Champion + Challenger) | 23/04/2026 | Anexo "Retreinos v4" abaixo |
| Tier 1 safeguards (11/11 itens) | 20-23/04/2026 | `PLANO_SAFEGUARD.md` |
| EXPERIMENTO_MOAT_MODELO — decomposição moat | 24/04/2026 | `EXPERIMENTO_MOAT_MODELO.md` |
| Otimização GCP (~R$167/mês) | 26/04/2026 | `operacoes_gcp_custos.md` |

---

## Skills disponíveis

| Skill | Quando usar |
|---|---|
| `/investigate` | Investigar por que um lançamento foi ruim — números históricos e causas conceituais |
| `/investigate-ab` | Verificar se o A/B test está tecnicamente válido (quando retomar) |
| `/safeguard` | Auditoria completa de integridade — encoding, CAPI, deploy, timezone, monitoramento |
| `/plan-integrator` | Releitura completa de docs + reconciliação de status |
| `/ctx` | Onboarding e contexto operacional |
| `/mlops-architect` | Decisões arquiteturais profundas |

---

# ANEXO — Histórico operacional preservado

## Log de portes — Fase 3 da unificação (2026-04-23)

Cada porte de edf23e9 → main passou pelo protocolo: parity audit antes → mudança → parity audit depois → T1-11 → commit isolado.

| Data | Arquivo | De | Para | T1-7 antes | T1-7 depois | T1-11 | Status | Observação |
|---|---|---|---|---|---|---|---|---|
| 2026-04-23 | `configs/clients/devclub.yaml` | ordinal idade/salário | OHE idade/salário (Opção A) | OK (51 cols) | OK (60 cols, 0 divergências) | n/a (mudança de config) | ✅ | Gap do Challenger 13 → 2 features. Champion mantém ordinal via override. |
| 2026-04-23 | `src/core/feature_engineering.py` + `client_config.py` + `devclub.yaml` | `valido` features não criadas | Criadas via flag `create_valido_features=true` | OK (60 cols) | OK (66 cols, 0 divergências) | Unitários + 67k leads reais (99.9% válidos) | ✅ | Gap do Champion 8 → 2 features. As 2 restantes resolvem só com retreino (telefone_comprimento_4/10). |

## Decisão arquitetural — Opção A (encoding idade/salário)

Tomada em 2026-04-21. Rationale e alternativa rejeitada:

- **Default do cliente:** OHE para idade e faixa salarial.
- **Champion (jan30):** mantém `encoding_overrides` com ordinal — é como foi treinado.
- **Challenger (mar24):** herda OHE — é como foi treinado.

Racional: o default representa "o encoding mais comum nos modelos atuais e futuros"; overrides representam exceções explícitas. A alternativa (manter ordinal como default e adicionar override OHE para mar24) foi rejeitada porque exigiria que `merge_encoding` suportasse "anular override do base", aumentando complexidade.

## Retreinos coordenados v4 (2026-04-23)

5 retreinos em sequência durante o dia, cada um corrigindo um gap do anterior:

| Geração | Fontes | Dataset | Positivos | Janela limite | Champion AUC | Challenger AUC | Status |
|---|---|---|---|---|---|---|---|
| v0 originais (jan30/mar24) | Sheets + Guru velhos | ~110k / 67k | ~415 | — | 0.7311 | 0.7372 | Produção atual |
| v1 cache 03/03 | Sheets + Guru | 67k | 415 | 2026-03-06 | 0.724 | 0.728 | MLflow |
| v2 fresh 06/03 | Sheets + Guru fresh | 72k | 430 | 2026-03-06 | 0.743 | 0.756 | MLflow |
| v3 + Hotmart | Sheets + Guru + Hotmart | 72k | 430 | 2026-03-06 | 0.743 | 0.756 | Hotmart não moveu ponteiro |
| **v4 + Railway (final)** | **Sheets + Guru + Hotmart + Railway** | **192k** | **1,104** | **2026-04-02** | **0.748** | **0.745** | **Aguardando validação OOS** |

**Run IDs v4 (estado atual):**
- Champion: `60637bb98b94421b9c7579bb4ac1b1ad`
- Challenger: `7d08ae0302da420aa99559d4d4f55025`

**O que mudou em v4:**
- 2.6× mais positivos que gerações anteriores (1.104 vs 430) — muito mais robusto.
- Janela de treino até 2026-04-02 (vs 2026-03-06) — capta a explosão Hotmart de março.
- Top 3 decis 62.8% → 67.3%; monotonia 66.7% → 77.8%.
- 60 features esperadas, 0 ausentes em ambos os modelos. T1-7 parity audit passa.

**Gaps resolvidos em v4:**
- Hotmart carregado (219 vendas, 131 em março).
- Railway carregado (109.284 leads desde 18/02 via webhook).
- Dedup cross-source por email (118k duplicatas removidas; Railway prioritário).
- Threshold de missing rate ajustado.
- Sheets truncado em 27/03 não bloqueia mais — Railway estende a data máxima até 23/04.

## Retreinos preliminares (1ª rodada, obsoleta)

> **Obsoleto:** rodada antes das descobertas sobre Hotmart, Railway e Sheets truncado. Substituída pelos modelos v4 acima. Preservada como histórico.

| Modelo | Run ID antigo | Run ID novo | AUC antigo | AUC novo | Lift antigo | Lift novo |
|---|---|---|---|---|---|---|
| Champion (jan30) | `d51757f5...` | `d67bf550e51243b19d83687c4e7d9613` | 0.7311 | 0.724 | 2.65× | 3.4× ↑ |
| Challenger (mar24) | `a859c68b...` | `97bf18cde3d44129aa1eb58798d744f8` | 0.7372 | 0.728 | 3.26× | 3.4× |
