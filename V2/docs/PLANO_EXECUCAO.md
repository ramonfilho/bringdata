# Plano de Execução — Smart Ads V2 (Roadmap Único)

**Atualizado:** 2026-05-02
**Propósito:** este é o **único** documento de "o que fazer e quando" no projeto. Toda a sequência de trabalho — segurança, A/B test, unificação, refactor multi-cliente, escala B2B, backlog de features — vive aqui, em horizontes ordenados por dependência.

## Como ler este documento

- **Este documento responde:** o que fazer agora? em que ordem? quem depende de quem?
- **Para o "como" técnico de um item, vá ao catálogo correspondente:**
  - `PLANO_SAFEGUARD.md` — especificação técnica de cada salvaguarda (encoding, gates de deploy, monitoring, validações). Cada item tem título verbal + identificador histórico (`T1-X`, `T2-X`, `T3-X`) no rodapé.
  - `PLANO_REFACTOR_MLOPS.md` — histórico do refactor + especificação de cada item de dívida técnica (renomeação de configs, eliminação de duplicação, normalização de features). Mesmo padrão de título verbal + identificador histórico (`DT-X`) no rodapé.
  - `ARQUITETURA_SISTEMA_COMPLETA.md` — visão de sistema, fluxos, endpoints
  - `AB_TEST.md` — design do teste A/B (executar quando o gate de validação for retomado)
  - `registro_erros_ml.md` — motivação histórica dos safeguards (incidentes 1-17, backtests, frentes preventivas em aberto)
  - `AUDITORIA_QUEBRA_PRODUCAO.md` — checklist operacional de cenários a estressar (linguagem natural, sem códigos)
- **Sobre os identificadores codificados (`T1-X`, `T2-X`, `T3-X`, `DT-X`, `R-X`):** servem pra rastrear commits e issues antigas. Os catálogos têm título verbal primeiro e o ID no rodapé. Os horizontes deste roadmap citam o ID quando faz sentido (atalho), mas o título verbal correspondente está sempre a 1 click no catálogo.
- **Catálogos não definem prioridade.** Status canônico de cada item (em curso, concluído, em standby) está aqui.

---

## Estado atual (28/04/2026)

| Componente | Estado |
|---|---|
| **Validação OOS Champion v4** | ✅ Atravessada favoravelmente em 28/04 — gate único do roadmap. |
| **Código em produção** | ✅ `smart-ads-api-00371-jol` (commit `0e6e21f`) — main em 100% desde 30/04 11:44 BRT, após canary 10% → 50% → 100% (revisões 00367, 00368, 00369, 00371). |
| **Modelo servido** | Champion v4 (`60637bb98b94421b9c7579bb4ac1b1ad`) — AUC 0.748, OHE default. |
| **Challenger v4 (em standby até próximo ciclo A/B)** | `7d08ae0302da420aa99559d4d4f55025` — AUC 0.745. |
| **A/B test** | 🔓 Reaberto em 28/04 — frente ativa. Roteamento por revisões Cloud Run substituiu o roteamento por UTM antigo. |
| **Cloud SQL `smart-ads-db`** | Parado desde 26/04 (`activation-policy=NEVER`); subir antes de retreinar — ver `operacoes_gcp_custos.md` |
| **Tier 1 safeguards** | ✅ 11/11 concluídos (até 23/04/2026) |
| **T2-2 (log por etapa)** | ✅ 28/04/2026 — commits `8b46645` |
| **T2-3 (importance weighting)** | ✅ 28/04/2026 — commits `c03d645`, `f8dc4f7`. Feature pronta no repertório (default desligado). Efeito interno marginal; sinal externo D9+D10 lift 6.88× confirma valor do ML em produção. |
| **DT-13 (utm_term zerando)** | ✅ 28/04/2026 — commit `dafe85d` |
| **Bug do Medium em produção** | ✅ resolvido 02/05 — `_load_valid_categories` (em `core/medium.py:124`, introduzido em `2df0671`) buscava `distribuicoes_esperadas.json` no path errado, retornava `None` silenciosamente, e `unify_medium` caía em modo treino-frequência por batch em vez de aplicar a whitelist canônica. Whitelist Medium ficou desligada em prod desde 30/04 → encoding zerava `Medium_*` para valores fora das 7 categorias canônicas. Fix em `d711227`. |
| **Endpoints `/monitoring/daily-check` e `/monitoring/feature-report`** | ✅ consertados 02/05 — typo no orchestrator (commit `7c69bfd`, T3-5) e subprocess `gcloud` no container Cloud Run (T1-11 Peça B), ambos em HTTP 500 desde a entrega. Commits `8718b00` (endpoints) + `f275d88` (path do drift por feature). |
| **Sequela: Source/telefone_comprimento** | ✅ resolvido 02/05 — `_unify_source` sem fallback whitelist (deixava `tiktok` cru); `telefone_comprimento` ficava `int64` em batches só com telefones BR. Commit `f1082ff`. |
| **Consertos estruturais (E1-E4)** | ✅ deployados 02/05 — fail-loud em `_load_valid_categories` (`fda24ce`), fix do path nos 2 leitores de drift em `data_quality.py` (`f275d88`), gate `/feature-report` no `smoke_test_revision.py` (`563a280`), integration test do `unify_medium` com artifact real (`c396b25`). |

---

## 🚦 GATE ÚNICO — Validação out-of-sample do Champion v4 ✅ ATRAVESSADA (28/04/2026)

**Resultado:** decisão de seguir com o A/B — Champion v4 validado para entrar em produção via canary. Detalhes operacionais da validação ficam fora deste plano (registrados na sessão que executou o teste).

**Consequência imediata:** o deploy canary da main (H2) entra em execução em sessão paralela; A/B test reabre como frente ativa; Sprint 2 do `retraining_orchestrator` (quality gate automático pós-treino) volta ao backlog em H6.

---

## Princípios de execução

1. **A ordem importa.** Não pular ou antecipar itens sem instrução explícita.
2. **Protocolo por item:** implementar → testar → commitar → deployar/integrar **individualmente** antes de avançar para o próximo. Aplica-se a cada T1-X, T2-X, T3-X, R-X, DT-X. Detalhes em `PLANO_SAFEGUARD.md` → "Protocolo obrigatório por item".
3. **Catálogos têm o "como"; este documento tem o "quando".** Para cada item abaixo, link para o catálogo onde a especificação técnica vive.
4. **Toda transformação de dados continua canônica em `src/core/`** — nunca reimplementar fora.
5. **Deploy de produção é canary obrigatório, sem exceção.** Nenhuma revisão pode ir a 100% de tráfego sem antes passar por: (a) revisão criada com 0% de tráfego; (b) smoke test contra a URL direta da revisão (T1-10 + T1-11/E3); (c) progressão manual `10% → 50% → 100%` via `gcloud run services update-traffic`. O `deploy_capi.sh` não pode oferecer caminho que pule esses três passos. Se o operador precisar bypassar em emergência, faz fora do script (assumindo o risco explicitamente). Motivação: sessão de investigação 02/05 expôs que o detector existia mas só pegou os bugs do Medium/Source/telefone porque foi adicionado depois — se um bug futuro de mesma natureza aparecer e alguém deployar "rápido" por hábito, o gate é inútil. Implementação rastreada em E7 (H4).

---

## Cronograma agregado

| Horizonte | Janela | Foco principal | Status |
|---|---|---|---|
| **H1 — Agora** | 27/04 → 28/04 | DT-13, ARQUITETURA, gate de validação | ✅ concluído |
| **H2 — Pós-validação** | 28/04 → 30/04 | Deploy canary da main concluído (100% em `00371-jol`) | ✅ concluído |
| **H3 — Tier 2/3 safeguards** | abr-maio 2026 | Safeguards de qualidade e observabilidade | ✅ concluído (T3-3 adiado) |
| **H4 — Pré-Cliente B** | em curso | DT-9, schema check, testes unitários, bugs latentes | 🔄 atual |
| **H5 — Cliente B** | depende de dados externos | Onboarding + EDA Generator | ⚪ aguardando |
| **H6 — Escala 2-4 clientes** | 2-4 meses após H5 | CI/CD, retreino auto, dashboard, registry, redesign UTM, recalibração, Google Ads, TikTok | depende H5 |
| **H7 — Escala 5+ clientes** | quando infra atual virar gargalo | Stack GCP completo + features data flywheel + LinkedIn + NLP | demand-driven |

---

# ROADMAP

## H1 — CONCLUÍDO (28/04/2026)

### Validação out-of-sample do Champion v4 ✅ ATRAVESSADA
- Saída: decisão favorável ao v4. Detalhes da execução fora deste plano (sessão paralela).
- Consequência: H2 destravado e em execução; frente A/B reaberta no roadmap.

### ~~Capturar golden snapshot do monitoring~~ → REPOSICIONADO (não rodar agora)
- **Por que não agora:** o sistema está com `distribution_drift HIGH` em Medium e `score_distribution_change HIGH` em D10 desde 22/04. Capturar o snapshot neste estado cristaliza um baseline degradado — regressões futuras seriam comparadas contra um estado já ruim e a divergência atual viraria "normal".
- **Quando capturar:** depois que o sistema estiver saudável. Dois caminhos possíveis (a decisão depende do resultado da validação OOS):
  - **Caminho A — pós-deploy v4 a 10%:** Champion v4 foi treinado com janela até 02/04 (pós-explosão Hotmart), então o feature registry dele já reflete o mix atual de Medium. Se promovido, os alertas HIGH tendem a cair sozinhos. Capturar 24-48h depois do canary 10% estável.
  - **Caminho B — pós-retreino corretivo:** se a validação OOS mostrar que v4 não resolve, retreinar com importance weighting (T2-3) ou outra correção; capturar só após estabilização.
- **Status:** pendente sem prazo rígido. Não bloqueia o canary inicial. Vira resultado de um sistema saudável, não pré-requisito mecânico.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → "Fase 2 — Pendente — validação do monitoramento".

### Fix DT-13 (utm_term numérico zerando encode) ✅ commit `dafe85d`

### Atualizar `ARQUITETURA_SISTEMA_COMPLETA.md` ✅ commit `15fe32a`

---

## H2 — Pós-validação ✅ CONCLUÍDO (30/04/2026)

### Deploy canary da main unificada ✅
- **Quando:** progredido em sessão paralela do usuário entre 29/04 e 30/04. Canary 10% → 50% → 100% executado em 4 revisões (`00367-cat`, `00368-yuq`, `00369-zul`, `00371-jol`).
- **Em produção:** `smart-ads-api-00371-jol` (commit `0e6e21f`, tag `deploy/2026-04-30-00371-jol`) com 100% do tráfego desde 30/04 11:44 BRT. Inclui o fix DT-CAPI-01 (commit `41cc2bf`).
- **Estratégia executada:** canary direto, critério técnico (sem gancho A/B). Detalhes em `AB_TEST.md`.
- **Captura do golden snapshot:** ainda pendente — só faz sentido quando alertas HIGH pré-existentes (drift Medium / score_distribution_change D10) tiverem cedido com o v4 em 100%. Verificar 24-48h após estabilização.
- **Rollback rápido:** ~10s via `gcloud run services update-traffic smart-ads-api --to-revisions=<revisão_anterior>=100` se necessário.

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

### DT-8: Remover features fantasmas em produção ✅ resolvido (29/04/2026)
- **Estado atual:** verificação confirma que `production_pipeline.py` **não tem nenhuma criação inline** de `nome_valido`/`email_valido`/`telefone_valido`. Toda a lógica vive em `core/feature_engineering.py` atrás da flag `create_valido_features` (default False; DevClub usa True). Sem código fantasma para remover.
- **Quando ficou resolvido:** durante o porte #2 da unificação Fase 3 (23/04/2026) — features migraram para `core/feature_engineering.py` e a versão inline em produção sumiu junto.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-8.

### DT-10: Hardcodes de modelo em treino ✅ resolvido (29/04/2026)
- **Estado:** os fallbacks hardcoded de `PESOS_COMPRADOR` e `DEFAULT_HYPERPARAMS` em `train_pipeline.py` foram removidos. Agora o treino lê obrigatoriamente de `client_config.model.buyer_weights` e `client_config.model.hyperparameters`; se qualquer dos dois faltar no YAML do cliente, o treino aborta com `ValueError [R2/DT-10]` apontando exatamente o que adicionar. Cliente B esquecer = aborta loud em vez de treinar com pesos DevClub.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-10.

### DT-9: Remover aliases ordinais transitórios ✅ resolvido (29/04/2026)
- **Estado atual:** `encoding.ordinal_variables` no `devclub.yaml` tem apenas `dia_semana`. Não há mais `'idade'` nem `'faixa_salarial'`.
- **Quando ficou resolvido:** durante a Opção A da unificação Fase 3 (23/04/2026), quando idade e faixa salarial migraram de ordinal para OHE como default do cliente. Os aliases curtos saíram junto na mesma edição do YAML.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-9.
- **O quê:** verificar `'idade'` e `'faixa_salarial'` em `encoding.ordinal_variables` do `configs/clients/devclub.yaml`. Se ainda presentes como aliases curtos, remover — o df chega com nomes longos, alias curto = encoding silenciosamente pulado.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-9.

### Schema check pré-treino (`src/core/validation.py`) ✅ resolvido (29/04/2026)
- **Estado atual:** módulo `src/core/validation.py` (201 linhas) já existe com `validate_ingestion` (colunas obrigatórias, tamanho do dataset, parseabilidade de datas) e `validate_features` (missing rates de features críticas vs thresholds do YAML). Integrados no `train_pipeline.py` em dois pontos: após Célula 4 (linhas 549-555) e após Célula 8 (linhas 652-658). `ValidationConfig` no `ClientConfig` controla thresholds e modo `on_error` (`raise` aborta, `warn` só registra).
- **Quando ficou resolvido:** durante a Fase 2 do refactor (mar-2026). O item ficou listado como pendente no roadmap original mas, na verdade, foi entregue junto com o resto do `src/core/`.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` §12 "Caminho para Nível 2".

### Bugs latentes (limpezas opcionais)
Itens menores de qualidade técnica que valem fechar antes de escalar. Nenhum bloqueia produção; cada um é independente.
- **DT-7** — `core/medium.py` calcula threshold de Medium sobre janela errada (pré-cutoff), gerando alertas falsos no monitoramento.
- **DT-11** — ✅ resolvido (29/04/2026): verificação confirma que os 6 imports de `core/` já estão no topo do `monitoring/orchestrator.py` (linhas 22-27). `grep` por imports de core dentro de funções retorna vazio. Os imports lazy que ainda existem dentro de funções são de bibliotecas pesadas (`gspread`, `google.auth`) ou potenciais ciclos (`api.database`) — intencionais, não relacionados a DT-11.
- **DT-CAPI-01 fix** — ✅ deployado 30/04/2026: commit `41cc2bf` (refatoração `should_send_to_destination` centralizando allowlist nos 4 paths de CAPI) está em produção via revisão `smart-ads-api-00371-jol`. Eventos de `google-ads`, `gruposantigos`, `(null)`, `api`, `tiktok`, `ig` (que escapavam) deixam de ir ao Pixel Meta a partir desta revisão.
- **Guard de coluna Medium em produção** — `production_pipeline.py` chama `medium.unify_medium` sem guard `if 'Medium' in df.columns`; treino tem o guard. Se Medium sumir do formulário, produção quebra.
- **`/railway/process-pending`** — `.str` accessor em batches de 1 lead com NaN em UTM (~0,3% polls). Auto-recupera no próximo poll. `fillna('')` resolve.
- **`/bigquery/stats`** — sync nunca foi ativado, retorna 0 rows. Considerar deletar se confirmado fora de uso.

#### Sequelas / pendências da sessão de investigação 02/05/2026

Itens descobertos enquanto rastreávamos o bug do Medium. Nenhum afeta scoring (esses já foram consertados em 02/05); são de qualidade do monitoramento + decisões de schema.

- **F0** ✅ RESOLVIDO — entrada `target` removida de `configs/pre_encoding_schemas/devclub.json`. `grep "target"` no JSON retorna vazio.
- **F3** — `Term` `null_rate` em produção (14.3%) ultrapassou marginalmente o `max_null_rate` do schema (13.9%). **Decisão pendente:** investigar Meta Ads (`act_188005769808959`) se há ads/adsets ativos sem `utm_term` no `url_tags` → corrigir tracking, OU aumentar `max_null_rate` para ~0.18.
- **F5** — coluna `Você já fez/faz/pretende fazer faculdade?` com `null_rate_high` recorrente. **Decisão pendente:** a pergunta continua opcional na pesquisa? Se sim, aumentar `max_null_rate` no schema; se virou obrigatória, investigar form/webhook.
- **O1** ✅ RESOLVIDO — commits `d129452` (preenche `operational_routines` no daily-check) + `d9bcd96` (log Champion + Challenger). Os 3 sub-blocos voltaram a popular `active_run_id`, `cloud_run_revision`, `leads_received_24h`.
- **E5** — `EXPECTED_DECIL_DISTRIBUTION` em `monitoring/config.py:50` está hardcoded como uniforme `{Dx: 0.10}`. Em produção D10 sempre rodou em ~30% (jamais em 10%), então o alerta `"D10: 10% → 32%"` é falso positivo crônico desde o início desse modelo. **Fix:** substituir por leitura de `model_metadata.json:decil_analysis` (distribuição real onde decis foram calibrados pelo treino). ~10 linhas.
- **E7** ✅ RESOLVIDO — `deploy_capi.sh:51` define `NO_TRAFFIC=true` como default e linha 584 confirma "Caminho de deploy direto a 100% foi removido. Canary é obrigatório". Sem flag de escape no script. Bypass de emergência só via `gcloud run services update-traffic` manual.
- **VAL=0 LeadQualified** ✅ Fix A aplicado 06/05/2026 — `conversion_rates` recolocados em `configs/clients/devclub.yaml:business` (back-calculados de `LEAD_VALUE_BY_DECILE_CHAMPION`). Bug ativo entre 30/04 e 06/05 (7 dias 100% value=0). Próximo deploy aplica o fix em produção. Sequela arquitetural está documentada em **DT-17** (`PLANO_REFACTOR_MLOPS.md`) — eliminar duplicação `business_config.py` × YAML.

#### Sequelas / pendências da sessão de investigação 05/05/2026

Itens descobertos durante o fix do encoding ordinal jan30 (DT-12 complemento).

- **M1 — MIX QUENTE deve ser categoria canônica distinta no próximo retreino.** Hoje `configs/clients/devclub.yaml:medium.category_mappings` mapeia `MIX QUENTE: Outros`, jogando ~7.3% do volume histórico em "Outros" (ver `INVESTIGACAO_BAIXO_DESEMPENHO.md` linha 133). Esse Medium é uma audiência distinta do gestor (não é fallback nem ruído) — preservar como categoria reconhecida pelo modelo permite o RF aprender o sinal específico dela. **Regra a aplicar no próximo retreino:** (a) escolher um nome canônico único (sugestão: `MIX QUENTE`); (b) no `category_mappings` mapear **todas as variações observadas** (`MIX QUENTE`, `mix quente`, `Mix Quente`, eventuais `MIX_QUENTE`, etc. — auditar com `SELECT DISTINCT medium FROM "Lead" WHERE medium ILIKE '%mix%quente%'`) para esse canônico; (c) confirmar que sobrevive ao threshold de frequência (`medium.frequency_threshold=0.025` ou ajustar). **Por que esperar próximo retreino:** mudar agora cria a coluna `Medium_MIX_QUENTE` no DataFrame mas o feature_registry do jan30 não a tem → step 7 do encoding descarta → bug igual ao que estamos consertando hoje. Aplicar simultaneamente com o treino que vai gerar o registry novo. Local de aplicação: `configs/clients/devclub.yaml:medium.category_mappings`. **Esforço:** ~5min na hora do retreino + auditoria SQL das variações.
- **M2 — `Medium_Linguagem_programacao` extinto.** Categoria saiu da campanha do gestor há semanas. Atualmente jan30 espera essa coluna no feature_registry (importância 5.31%) e ela vem missing em todo poll → T1-10 ERROR crônico. Drift legítimo, não tem fix de encoding. **Decisão pendente:** (a) aceitar como esperado e silenciar T1-10 pra essa coluna específica até o retreino, ou (b) retreinar sem ela. Opção (b) sai automaticamente quando rodar próximo retreino com data mais recente — a feature deixa de aparecer no top-10. **Status do alarme T1-10:** agora aparece como alerta formal `critical_feature_coverage` no daily-check (commit `287e833`, 05/05/2026), não mais só como log Cloud Run — atende a decisão pendente sobre visibilidade enquanto a decisão (a) ou (b) não é tomada.
- **M3 — DT-16 (matar `encoding_overrides` por convergência).** Prioridade ALTA segundo PLANO_REFACTOR_MLOPS.md. Resolve simultaneamente DT-12, DT-15, bug do jan30 cego em idade/salário e o bug do monitoring assimétrico. Bloqueio único: treinar próximo Champion com pipeline atual (OHE-nativo). Esforço total ~30min ponta a ponta após Champion novo disponível. Ver DT-16 sequência de execução.
- **M4 — DT-18 (normalizar 4 features binárias raw `genero`/`estudou_programacao`/`fez_faculdade`/`investiu_curso_online`).** Prioridade ALTA. **Bloqueia A/B com Challenger novo enquanto o Champion legado `jan30` estiver ativo** — fix isolado em produção quebraria 100% das 4 features no caminho do Champion (8% do peso do modelo cego, similar ao dano dos Clusters 4/5 do Erro 2). Tem que ir **junto** com retreino: (1) implementar normalização em `core/category_unification.py:91-115` (treino+produção pelo mesmo `core/`); (2) treinar próximo Champion com código novo; (3) NÃO promover sem retreino. Faz UM retreino só com DT-16+DT-18 (e DT-17 fases 4-5) — sem retrabalho. Risco operacional atual baixo (front estável); detecção via `actionable_alerts` do daily-check (V.2 vetor 3 implementado 08/05/2026) cobre janelas de até 24h. Ver DT-18 em PLANO_REFACTOR_MLOPS.md e V.2 do `registro_erros_ml.md`.

#### Sequelas / pendências da sessão de investigação 06/05/2026

Itens descobertos durante a investigação do spike de custo + comprovação CAPI no canary `00402-hoq`.

- **DT-17 — Eliminar duplicação `api/business_config.py` × YAML do cliente.** Prioridade ALTA arquiteturalmente, MÉDIA em urgência (Fix A já estancou o sangramento). Bug latente que causou 7 dias 100% value=0 entre 30/04 e 06/05. Fluxo desejado: treino popula rates como artifact dentro do MLflow run; `--set-active` copia pro YAML autoritativo no momento da promoção (não no momento do treino). Sequência completa em PLANO_REFACTOR_MLOPS.md DT-17. Fases 1-3 (preparação) podem rodar em paralelo a DT-16; fases 4-5 disparam junto com próximo retreino.
- **VAL=0 follow-up** ✅ **RESOLVIDO 08/05/2026.** Revisão `smart-ads-api-00412-rag` em 100% desde 14:25 BRT após canary 0% → 10% → 100% com Gates B/D/C automatizados. Drain confirmado via Q1: zero events value=0 pós-promoção; D04=R$1.97, D05=R$5.62, D06=R$5.62, D08=R$6.75, D10=R$14.97 — todos batendo `LEAD_VALUE_BY_DECILE_CHAMPION`. Bug irmão dos variants A/B (`conversion_rates` zerado em `champion_jan30`/`challenger_abr28`) descoberto e corrigido durante o canary via Patch B (commit `4c1d727`). Salvaguardas T1-17 (Gate D) + T1-18 (Gate C) introduzidas pra fechar a classe — ver `registro_erros_ml.md § I.8b` e `PLANO_SAFEGUARD.md`. DT-17 (refactor arquitetural) continua pendente como solução estrutural.

#### Sequelas / pendências da sessão de investigação 08/05/2026

- **🔴 P2: Fortalecer salvaguardas que falharam no Cluster 5 (T1-14, T1-15, T1-16).** Investigação V.1 do `registro_erros_ml.md` (08/05/2026) confirmou 3 gaps que deixaram o bug do `encoding_overrides` ausente passar em 29/abr: (1) **T1-14** — smoke test pré-deploy não exercita variantes A/B (chama `/monitoring/daily-check/railway` sem contexto A/B, nunca testa Champion com `encoding_overrides`); (2) **T1-15** — parity audit ignora `encoding_overrides` de variantes (testa só `config.encoding` padrão); (3) **T1-16** — validação ">X% zerados → bloqueia" foi **declarada como entregue em 21/abr mas nunca foi implementada** (existe só log de feature ausente, não de feature zerada após encoding). Especificação técnica completa em [PLANO_SAFEGUARD.md](PLANO_SAFEGUARD.md) e investigação detalhada em `registro_erros_ml.md` § V.1. **Ordem de execução:** T1-14 → T1-15 → T1-16. Os dois primeiros são independentes do retreino e podem ser feitos antes; T1-16 tem pré-condição de capturar `proporcao_esperada_zero` por feature em `distribuicoes_esperadas.json`, então fica para o próximo retreino. **Por que P2 (não P1 como T1-13):** os 3 gaps só causam dano quando A/B está ativo + um modelo precisa de override; com A/B Standby hoje, o risco operacional é baixo. Mas **bloqueiam reativação segura do A/B** quando o próximo Champion sair (DT-16 + DT-18). Sem T1-14/15, qualquer A/B novo herda os mesmos gaps.

- **🔴 PRIORIDADE MÁXIMA — P1: Implementar `audience_profile_drift` no monitoring (T1-13).** Descoberto em 08/05/2026 via análise ad-hoc do LF54 em captação: o perfil de público está significativamente deslocado do Top 5 ROAS histórico (recorte usado nessa análise: LF40, LF41, LF44, LF45, LF47, n=39.771 — Top 5 canonical atualizado em 2026-05-14 está em `docs/METODOLOGIA_TOP5_ROAS.md` e é LF45, LF44, LF46, LF41, LF43) — "Sem computador" 12,5% → 22,9%, Feminino 18,3% → 28,0%, CLT/funcionário público 44,9% → 35,6%, "Já estudou programação Sim" 36,8% → 30,9% (todos com chi² p < 1e-4). Esse drift pode explicar parte do baixo desempenho dos LFs recentes e **deveria** ter sido detectado automaticamente pelo monitoring — não foi porque o `DataQualityMonitor.check_distribution_drift` em [src/monitoring/data_quality.py:397](../src/monitoring/data_quality.py#L397) só compara contra `distribuicoes_esperadas.json` capturado **no treino**, não contra um perfil de "audiência winner" histórica. **Especificação técnica vai em PLANO_SAFEGUARD.md como T1-13** (catálogo). **Por que máxima prioridade:** gap deixou produção rodando às cegas para drift de público durante todos os LFs entre o último Top 5 ROAS e hoje; cada lançamento sem esse check é exposição cega; é também um erro registrado em `registro_erros_ml.md` § V.4. **Decisões já tomadas nesta sessão:** (a) referência **fixa** no Top 5 ROAS atual em snapshot estático (`configs/clients/devclub/reference_audience_profile.json`); refresh do pool é tarefa manual anexa a "fechamento de lançamento" — não é rolling; (b) janela comparada no alerta automático = **último dia completo** (BRT 00:00→23:59 anterior a hoje), NÃO o LF acumulado nem o dia parcial; (c) threshold = ⚠ se |Δpp| ≥ 5 em qualquer categoria canônica; severity HIGH se |Δpp| ≥ 5 em qualquer das 5 features socioeconômicas críticas (computador, gênero, ocupação CLT, programação, cartão); (d) categorias canônicas reaproveitadas da constante `UNIFICATION` em [scripts/perfil_audiencia.py](../scripts/perfil_audiencia.py); (e) drift é pré-encoding e independente de modelo → NÃO precisa loop per-variant. **Artefatos já existentes (não bloqueiam, apoiam):** [docs/perfil_audiencia_dev20.md](perfil_audiencia_dev20.md), [docs/perfil_audiencia_lf54.md](perfil_audiencia_lf54.md), [scripts/perfil_audiencia.py](../scripts/perfil_audiencia.py). **Esforço estimado:** ~1h implementação + revisão de threshold com 1-2 ciclos de produção. **Sem dependências bloqueadoras** — pode ser implementado imediatamente.

#### Sequelas / pendências da sessão de investigação 11/05/2026

- **🟢 Remediação dos consumidores de `Lead.leadScore` / `Lead.decil` (versão de código como fotografia do passado).** Investigação em 11/05/2026 enquanto integrávamos o sinal de qualidade de audiência (bloco `audience_quality_signal` do daily-check) mostrou que `Lead.leadScore` e `Lead.decil` no Railway têm apenas **23% de paridade exata** com o re-score atual do mesmo Champion (52% no decil). Causa raiz confirmada (descartado pesquisa jsonb, race condition, encoding round-trip): **versão de código diferente entre o escorate em produção e o re-score atual** — o pipeline foi refatorado, revertido e patchado várias vezes ao longo dos últimos meses (correção do bug do encoding ordinal de idade/salário em 02/05, refactor `src/core/`, rollback `edf23e9`, normalizações UTM/Medium), e cada lead carrega o snapshot que rodou no instante exato em que ele chegou. Esses campos são "fotografia do código que rodou na hora", não medições estáveis. **Catálogo técnico criado:** [PLANO_REMEDIACAO_LEAD_SCORE.md](PLANO_REMEDIACAO_LEAD_SCORE.md) — descreve os 9 consumidores identificados (L1–L9), princípio único de remediação ("re-scorear em vez de ler do Railway"), distinção entre histórico (preservar) e futuro (remediar), e ordem sugerida de execução. Itens vivos no plano: forecast diário usando decil contaminado (L1, crítico — afeta o número que vai pro digest diário do cliente), backtest comparativo lendo decil do Railway como baseline do Champion (L2), teste de equivalência de revisão lendo `Lead.leadScore` como ground truth (L4), baseline rolling 30d do detector de drift contaminado (L5 + L8, proposta: cache versionado por `mlflow_run_id + commit_hash`). Itens já fechados: análise retrospectiva do bug DT-12 (L7, concluído em sessão anterior), alerta zero-decil CAPI (L9, fora de escopo — alerta de presença/ausência não depende de decil estável). **Status atual:** 🟢 **BACKLOG até consistência do método de ROAS ser resolvida.** O usuário pausou as 4 frentes vivas em 11/05/2026 para focar prioritariamente na consolidação de ROAS por lançamento sob metodologia única (descoberto que a metodologia `validation/load_match_spend_for_lf` produz números muito diferentes dos ROAS oficiais que aparecem em deck comercial — precisa reconciliar antes de mexer em consumidor do score). **Retomar:** quando a frente de ROAS estabilizar. Esforço estimado total: L1 ~1h, L2+L4 ~1h, L5+L8 ~2h (cache versionado + invalidação por hash). **Memória persistente relacionada:** `~/.claude/.../memory/projeto_lead_score_versao_codigo.md`.

---

## H5 — ONBOARDING CLIENTE B (depende de dado externo)

### Dados do Cliente B chegam ⚪ BLOQUEADO
- **O quê:** formulário XLS + export de vendas + cadência do lançamento.
- **Bloqueio:** depende do cliente.

### `clientb.yaml` + inspeção de dados
- **Catálogo:** `CHECKLIST_ONBOARDING_NEW_CLIENT.md`.

### Onboarding Cliente B (Fase 3b do refactor)
- **Pré-condições:** schema check pré-treino (de H4) + dados do Cliente B chegando + `clientb.yaml` escrito.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` §7 Fase 3b.

### DT-2: Testes unitários parametrizados em `src/core/`
- **O quê:** `pytest tests/core/ --client devclub --client clientb` para `utm.py`, `medium.py`, `encoding.py`. Parametrizados com dois `ClientConfig` reais.
- **Por quê:** hoje toda validação é integration test (~10–20 min). Com 2 clientes ativos, qualquer mudança em `core/` exige rodar pipeline completo por cliente — inviável.
- **Por que está em H5 (e não em H4):** a spec original diz "antes de qualquer mudança em `core/` com dois clientes ativos". Hoje só DevClub está ativo. Sem `clientb.yaml` real, parametrização vira teste único disfarçado. Faz sentido implementar logo após Cliente B onboardado.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` → DT-2.

### EDA Generator (`src/eda/generate_client_config.py`)
- **O quê:** geração automática de `clientX.yaml` a partir dos dados brutos do cliente.
- **Pré-condição:** dois configs (`devclub.yaml` + `clientb.yaml`) escritos manualmente — padrão claro o suficiente para automatizar.
- **Catálogo:** `PLANO_REFACTOR_MLOPS.md` §7 Fase 4.

---

## H6 — ESCALA 2-4 CLIENTES (após Cliente B estável)

### Infraestrutura
| Item | Pré-condição |
|---|---|
| GitHub Actions CI — push → lint → `pytest tests/core/` → parity check → merge liberado | DT-2 (testes unitários de H4) + 2 clientes ativos |
| Sprint 2 `retraining_orchestrator` — quality gate automático pós-treino (auto-promote por threshold de AUC/lift/monotonia) | thresholds calibrados pelo primeiro ciclo A/B pós-canary |
| Sprint 3 `retraining_orchestrator` — trigger de retreino por drift | 500+ leads/mês por cliente |
| **E6 — Rolling baseline 30d para drift de decis e features.** Comparar janela atual de produção contra histórico recente de produção (não contra treino). Hoje todo drift compara contra distribuições do treino, que divergem estruturalmente de produção (D10 calibrado a ~10% no treino, ~30% sustentado em produção desde o início do modelo). Detector real do que importa em prod: "mudou em relação ao normal" em vez de "mudou em relação ao treino". Design: query Railway com janela móvel + storage do baseline + recompute periódico. Discutir antes de implementar. | E5 implementado primeiro (corrige falso positivo crônico D10 sem mudar arquitetura) + 2+ clientes ativos OU sinal claro de que baseline atual é insuficiente |
| Looker Studio — dashboard de ROAS, CPL, distribuição de decis por cliente/lançamento | Cliente B ativo |
| Vertex AI Model Registry — substituir `configs/active_models/*.yaml` manual por registro centralizado | 3+ clientes ativos |

### Modelo
| Item | Pré-condição |
|---|---|
| Redesign UTM — remover do scoring, manter só em atribuição downstream. UTM diluiu AUC em −0.0024 vs survey-only (`EXPERIMENTO_MOAT_MODELO`, 24/04). | retreino dedicado para validar |
| Recalibração `revenue_forecast.md` — taxa histórica (1,23%) pode ficar desatualizada se audiência mudar. | fechamento DEV20 + LF48 com janela completa |

### Diversificação de canais
| Item | Pré-condição |
|---|---|
| Google Ads Enhanced Conversions — arquitetura F8 já conceptualmente resolvida; falta implementação. Mitigação parcial via `utm_source_allowlist` (DT-CAPI-01) já aplicada. Catálogo: `google_ads_pendencias.md`. | budget significativo no canal + gclid capturado no front |
| TikTok Events API — público jovem em crescimento, especialmente cursos. | budget significativo no canal |

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

### Features futuras (data flywheel)
Aproveitam volume agregado de múltiplos clientes:
- **User Agent + dispositivos** — sinal hoje ausente.
- **Similar leads** (kNN no espaço de features) — leverage do flywheel cross-cliente.
- **LTV por comprador** — recompra/upsell.
- **Histórico de lead_scores anteriores** — quando o mesmo lead reaparece em lançamento posterior.
- **Interação na página de checkout** — sinal de proximidade real à compra.
- **NLP** (`src/nlp/`) — campo de texto livre no formulário. Fase 5 do refactor.

### Diversificação de canais (B2B / verticais novas)
- **LinkedIn Insight Tag** — para verticais B2B futuros.

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
| T2-2 (log por etapa do pipeline) | 28/04/2026 — commit `8b46645` | `PLANO_SAFEGUARD.md` Tier 2 |
| T2-3 (importance weighting do grupo controle) | 28/04/2026 — commits `c03d645`, `f8dc4f7` | `PLANO_SAFEGUARD.md` Tier 2 |
| Tier 2 safeguards (8/8 itens) | 23-29/04/2026 | `PLANO_SAFEGUARD.md` |
| Tier 3 safeguards (5/5 ativos) | 21-29/04/2026 | `PLANO_SAFEGUARD.md` |
| DT-CAPI-01 fix (allowlist nos 4 paths CAPI) | 29/04/2026 — commit `41cc2bf` | `ARQUITETURA_SISTEMA_COMPLETA.md` |
| Validação OOS Champion v4 + gate atravessado | 28/04/2026 | sessão paralela |
| Retreinos coordenados v4 → modelo treinado pós-01/04 | 23/04/2026 | acima |
| DT-12 (encoding por variante A/B) | resolvido pela configuração v4 (OHE default) | `PLANO_REFACTOR_MLOPS.md` § DT-12 |
| Conserto endpoints `/monitoring/daily-check` (typo `7c69bfd`) e `/monitoring/feature-report` (subprocess `gcloud` → `google-cloud-logging`) | 02/05/2026 — commits `8718b00`, `8a54de3` | sessão de investigação 02/05 |
| Bug-mãe Medium em produção (`_load_valid_categories` path errado em `core/medium.py:124` — introduzido `2df0671`, 18/03; ativo em prod 30/04→02/05) | 02/05/2026 — commit `d711227` | sessão de investigação 02/05 |
| Sequela Source/`telefone_comprimento` (Source sem fallback whitelist em `_unify_source`; `telefone_comprimento` ficava `int64` em batches só com BR) | 02/05/2026 — commit `f1082ff` | sessão de investigação 02/05 |
| Consertos estruturais E1-E4 (fail-loud em `_load_valid_categories`; fix path nos 2 leitores de drift em `data_quality.py`; gate `/feature-report` no `smoke_test_revision.py`; integration test `unify_medium` com artifact real) | 02/05/2026 — commits `fda24ce`, `f275d88`, `563a280`, `c396b25` | sessão de investigação 02/05 |

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
