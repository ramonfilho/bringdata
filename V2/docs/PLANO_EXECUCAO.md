# Plano de Execução — Smart Ads V2 (Roadmap Único)

**Atualizado:** 2026-04-27
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

## Estado atual (27/04/2026)

| Componente | Estado |
|---|---|
| **Código em produção** | edf23e9 (05/03/2026) — rollback `00269-jjn`, 100% do tráfego |
| **Modelo em produção** | jan30 ORIGINAL (`d51757f5`) — treinado 30/01/2026, dados até 04/11/2025 |
| **Champion v4 (retreinado)** | `60637bb98b94421b9c7579bb4ac1b1ad` — 23/04/2026, janela até 02/04, AUC 0.748, OHE default |
| **Challenger v4 (retreinado)** | `7d08ae0302da420aa99559d4d4f55025` — 23/04/2026, AUC 0.745 |
| **Branch main** | Portes #1 e #2 da unificação aplicados (23/04); YAML aponta para v4 com `ab_test.enabled: false`. Não deployada |
| **A/B test** | ⏸ **SUSPENSO desde 27/04** — depende do GATE de validação OOS abaixo |
| **Cloud SQL `smart-ads-db`** | Parado desde 26/04 (`activation-policy=NEVER`); subir antes de retreinar — ver `operacoes_gcp_custos.md` |
| **Tier 1 safeguards** | ✅ 11/11 concluídos (até 23/04/2026) |

---

## 🚦 GATE ÚNICO — Validação out-of-sample do Champion v4

**Pergunta a responder:** o Champion v4 (`60637bb9…`) prevê melhor que o jan30 ORIGINAL nos lançamentos que nenhum dos dois treinou?

**Lançamentos elegíveis para o teste:**
- jan30 original treinou até **04/11/2025** → todos os lançamentos pós-novembro/2025 são não vistos
- Champion v4 treinou até **02/04/2026** → lançamentos pós-02/04 (LF51 final + DEV20 quando disponível) são não vistos
- A interseção (não vista por ambos) é o teste mais limpo para comparar diretamente

**Saída esperada da validação:**
- AUC, lift D10, monotonia, ROAS estimado de cada modelo nos mesmos leads não vistos
- Diferença estatisticamente significativa? Em qual direção?

**O que está em standby até esse gate:**
- Qualquer deploy de main em produção (o YAML já aponta para v4 — deployar = servir v4 não validado)
- Toda a frente de A/B test (patch, decisão, novo ciclo, encoding por variante)
- Sprint 2 do `retraining_orchestrator.py` (quality gate automático)

---

## Princípios de execução

1. **A ordem importa.** Não pular ou antecipar itens sem instrução explícita.
2. **Protocolo por item:** implementar → testar → commitar → deployar/integrar **individualmente** antes de avançar para o próximo. Aplica-se a cada T1-X, T2-X, T3-X, R-X, DT-X. Detalhes em `PLANO_SAFEGUARD.md` → "Protocolo obrigatório por item".
3. **Catálogos têm o "como"; este documento tem o "quando".** Para cada item abaixo, link para o catálogo onde a especificação técnica vive.
4. **Toda transformação de dados continua canônica em `src/core/`** — nunca reimplementar fora.

---

## Cronograma agregado

| Horizonte | Janela | Foco principal | Bloqueia? |
|---|---|---|---|
| **H1 — Agora** | semana 27/04 → 11/05 | Validar gate (H1.1). Snapshot e DT-13 deslocados | sim, gate único |
| **H2 — Pós-validação** | +1-3 semanas após gate favorável | Deploy canary main (único item travado pelo gate) | depende H1 |
| **Independente do gate** | qualquer momento (em fila por foco) | Importance weighting, log por etapa | não |
| **H3 — Tier 2/3 restante** | maio-junho 2026 | Safeguards remanescentes (10 itens) | não |
| **H4 — Pré-Cliente B** | em paralelo com H2/H3 | R1/R2/R3, schema check, testes unitários | gate Cliente B |
| **H5 — Cliente B** | depende de dados externos | Onboarding Fase 3b + EDA Generator | dado externo |
| **H6 — Escala 2-4 clientes** | 2-4 meses após Cliente B | CI/CD, drift trigger, dashboard, registry | depende H5 |
| **H7 — Escala 5+ clientes** | quando infra atual virar gargalo | Stack GCP completo (Pub/Sub, Dataflow, etc.) | demand-driven |
| **Standby** | reaberto pós-gate H1 | A/B test completo, quality gate retreino | gate único |

---

# ROADMAP

## H1 — AGORA (até validação OOS, prazo das próximas 2 semanas)

### 1.1 — Validação out-of-sample do Champion v4 🔴 GATE
- **O quê:** rodar Champion v4 e jan30 ORIGINAL nos leads de LF51 final + DEV20 (já coletado), comparar AUC / lift D10 / monotonia / ROAS estimado nos mesmos leads não vistos por ambos.
- **Saída:** decisão de promover, manter ou retreinar.
- **Bloqueia:** todo deploy de main (YAML já em v4); toda atividade A/B; H2.
- **Catálogo:** este documento, seção "GATE ÚNICO" acima.

### 1.2 — ~~Capturar golden snapshot do monitoring~~ → REPOSICIONADO (não rodar agora)
- **Por que não agora:** o sistema está com `distribution_drift HIGH` em Medium e `score_distribution_change HIGH` em D10 desde 22/04. Capturar o snapshot neste estado cristaliza um baseline degradado — regressões futuras seriam comparadas contra um estado já ruim e a divergência atual viraria "normal".
- **Quando capturar:** depois que o sistema estiver saudável. Dois caminhos possíveis (a decisão depende do resultado de H1.1):
  - **Caminho A — pós-deploy v4 a 10%:** Champion v4 foi treinado com janela até 02/04 (pós-explosão Hotmart), então o feature registry dele já reflete o mix atual de Medium. Se promovido, os alertas HIGH tendem a cair sozinhos. Capturar 24-48h depois do canary 10% estável.
  - **Caminho B — pós-retreino corretivo:** se H1.1 mostrar que v4 não resolve, retreinar com importance weighting (T2-3) ou outra correção; capturar só após estabilização.
- **Status:** pendente sem prazo rígido. Não bloqueia H2.1 (canary inicial). Vira resultado de um sistema saudável, não pré-requisito mecânico.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → "Fase 2 — Pendente — validação do monitoramento".

### 1.3 — Fix DT-13 (utm_term numérico zerando encode) 🟡
- **O quê:** 1 linha em `src/core/utm.py` — remover exceção numérica do fallback. `utm_term='0405'` (669 leads/dia em 22/04) e `'2104'` (232/dia em 23/04) escapam para encoded zerado.
- **Pode rodar em paralelo com 1.1 e 1.2.**
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` §11 "DT-13".

### 1.4 — Atualizar `ARQUITETURA_SISTEMA_COMPLETA.md` 🟡
- **O quê:** refletir rollback edf23e9 em produção, retreinos v4, A/B suspenso, canary direto como estratégia.
- **Pode rodar a qualquer momento.**

---

## H2 — Pós-validação (o que de fato depende do gate)

**Único item realmente travado pelo gate.**

### 2.1 — Deploy canary da main unificada
- **Pré-condições:** 1.1 favorável + smoke test em `--no-traffic` OK. (1.2 não bloqueia — golden snapshot é capturado depois.)
- **Estratégia:** canary direto 10% → 50% → 100% com critério puramente técnico. Detalhes em `AB_TEST.md` → "Nova estratégia — canary direto".
- **Critério de avanço:** ausência de alertas HIGH **novos** na janela exigida (alertas pré-existentes de drift Medium e D10 são esperados a princípio e devem reduzir após v4 estável) + paridade observada vs rollback + nenhum decil com 0 eventos. Sem gancho com ROAS A/B.
- **Captura do golden snapshot (H1.2):** 24-48h após canary 10% estável e alertas pré-existentes terem cedido. Se não cederem, pausar antes de avançar para 50% e diagnosticar.
- **Rollback:** ~10s via `gcloud run services update-traffic` para `00269-jjn`.

---

## Trabalho técnico independente do gate (na fila por foco, não por restrição)

Itens abaixo **não dependem** do gate H1.1 nem do canary. Estão adiados apenas pela disciplina de fazer um item por vez. Tecnicamente podem rodar a qualquer momento, e em qualquer cenário do gate (favorável ou não) continuam fazendo sentido.

### Importance weighting do grupo controle (T2-3)
- **O quê:** retreinar com pesos maiores para leads da campanha de controle e pesos menores para leads D10 sobre-representados; hook no `retraining_orchestrator.py`.
- **Por quê:** corrige viés do feedback loop documentado (W1 SWOT, Erros_cometidos.md cluster 2). Prazo original era 15/04 — vencido.
- **Por que é independente do gate:** produz um modelo novo independente do que aconteça com o Champion v4. Se v4 passar no gate, esse vira o próximo Challenger. Se v4 falhar, vira a alternativa direta.
- **Catálogo:** `PLANO_SAFEGUARD.md` Tier 2 → T2-3.

### Log de registros por etapa do pipeline (T2-2)
- **O quê:** instrumentar `core/preprocessing.py` para logar a contagem de registros (e nulos críticos) entre cada etapa.
- **Por quê:** auditabilidade — sem isso, descobrir onde linhas somem é arqueologia.
- **Por que é independente do gate:** instrumentação pura, não toca em modelo nem em encoding.
- **Catálogo:** `PLANO_SAFEGUARD.md` Tier 2 → T2-2.

---

## H3 — TIER 2 / TIER 3 SAFEGUARDS RESTANTES (maio–junho)

Implementar sobre o código unificado. Nenhum é bloqueador de produção. Status canônico em `PLANO_SAFEGUARD.md`.

### Tier 2 (qualidade de dados — 4 restantes)

| ID | Item curto | Catálogo |
|---|---|---|
| T2-4 | Remover limite de 10.000 registros em queries de validação | `PLANO_SAFEGUARD.md` Tier 2 |
| T2-5 | Filtro vendas aprovadas | `PLANO_SAFEGUARD.md` Tier 2 |
| T2-6 | Eliminar exceções silenciosas (3 pontos identificados em `app.py:1638-1640` e `orchestrator.py`) | `PLANO_SAFEGUARD.md` Tier 2 |
| T2-8 | Alerta para feature high-importance com variance baixa | `PLANO_SAFEGUARD.md` Tier 2 |

### Tier 3 (observabilidade — 7 itens)

| ID | Item curto | Catálogo |
|---|---|---|
| T3-1 | Smoke test automatizado pós-deploy | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-2 | Progressão canary documentada no `deploy_capi.sh` | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-3 | Branch protection no GitHub | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-5 | Relatório consolidado de rotinas | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-6 | Validação MODEL_PATH | `PLANO_SAFEGUARD.md` Tier 3 |
| T3-7 | Reconciliação run_id | `PLANO_SAFEGUARD.md` Tier 3 |
| ~~T3-4~~ | ~~Alerta token Meta < 10 dias~~ — CANCELADO (System User vitalício) | — |

---

## H4 — PRÉ-CLIENTE B (em paralelo com H2/H3)

Itens independentes dos dados do Cliente B. Resolver antes de iniciar Fase 3b do refactor.

### 4.1 — R1 / DT-8: Remover features fantasmas em produção
- **O quê:** `src/production_pipeline.py` cria `nome_valido`/`email_valido`/`telefone_valido`. Após o porte #2 da Fase 3, essas features também passam a ser criadas via `core/feature_engineering.py` quando `create_valido_features=true` está no YAML — verificar e remover o bloco fantasma do `production_pipeline.py` para não duplicar.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-8.

### 4.2 — R2 / DT-10: Hardcodes de modelo em treino
- **O quê:** `src/train_pipeline.py:~763,~788` — `PESOS_COMPRADOR` e `DEFAULT_HYPERPARAMS` reimplementados inline apesar de existirem no YAML do cliente. Substituir por `client_config.model.buyer_weights` e `client_config.model.hyperparameters`.
- **Por quê:** sem isso, treino do Cliente B usaria pesos DevClub silenciosamente.
- **Validação:** Camada 2 (AUC ±0.5%) antes/depois.
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

## ⏸ STANDBY — Aguardando o GATE H1

Itens que só voltam à execução se a validação do Champion v4 for favorável (ou se uma decisão explícita reabrir o teste A/B com outra configuração).

- **A/B test completo** — toda a Fase 1 original (patch no rollback, monitoramento DEV20, decisão de promoção). Design preservado em `AB_TEST.md`.
- **Quality gate automático pós-treino** (Sprint 2 `retraining_orchestrator.py`) — depende do A/B fornecer thresholds calibrados.
- **DT-12: Encoding por variante A/B (`encoding_overrides`)** — só faz sentido se A/B retomar com modelos que tenham encoding diferente entre si. Resolvido na configuração atual; documentado em `PLANO_REFACTOR_MLOPS.md` § DT-12.
- **Novo ciclo A/B com modelo retreinado** (Fase 5 original) — depende da decisão de promoção da Fase 1.

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
