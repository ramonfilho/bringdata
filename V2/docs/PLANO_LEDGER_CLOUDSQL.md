# PLANO — Ledger `registros_ml` sai do Railway do cliente para o Cloud SQL nosso

**Criado:** 2026-06-12 · **Status:** NÃO INICIADO · **Dono:** Ramon
**Documento de execução** — cada etapa tem checklist; marcar à medida que executa. Se a sessão cair, retomar pela seção "Como retomar".

---

## 1. Por quê (motivação)

O ledger `registros_ml` — nossa tabela com `lead_score`, `decil`, `variant` **e** `survey_responses`/`has_computer`/UTMs na mesma linha — vive hoje **dentro do Postgres Railway do cliente**. Qualquer admin daquele banco tem um dataset rotulado completo (features + alvo) crescendo a cada 5 minutos: material suficiente para clonar o modelo por regressão. O mesmo vale para o estoque histórico (`Lead.leadScore`/`decil` + `pesquisa` lado a lado, e as colunas `lead_score`/`decil` da planilha "[LF] Pesquisa").

**Objetivo:** nenhum score/decil/variant persiste na infra do cliente. Atribuição de score e envio CAPI não mudam de lugar (continuam no consumer Pub/Sub); muda só **onde o resultado é gravado**.

**Fica de fora por design:** o Meta continua recebendo valor por decil no evento — isso é o produto, e é canal muito mais difícil de reconstituir lead a lead.

## 2. Decisões registradas (12/06/2026)

| Decisão | Detalhe |
|---|---|
| Destino = **GCP Cloud SQL** `smart-ads-db` | smart-ads-451319, us-central1 (mesma região do Cloud Run), db-f1-micro, Postgres 15, IP público 104.197.138.129. Instância **fica ALWAYS permanentemente** (custo ~US$10-15/mês assumido; era a instância do MLflow que estava parada por economia). |
| Database novo `ledger`, separado do `mlflow` | Mesma instância, databases distintos, user dedicado de privilégio mínimo. |
| Migração por **estrangulamento com dual-write** | Cloud SQL primário, Railway espelho, paridade por ~7 dias, depois corta. Rollback = trocar env var. |
| Limpeza do estoque histórico **ao final**, com dump prévio | Inclui planilha (colunas + trigger Apps Script). |
| LF57/LF58 fora dos relatórios de score até fecharem datas | Já refletido em `scripts/gerar_scores_2026.py` (`FORA_DO_RELATORIO`). |
| **Dataset único consolidado no Cloud SQL** (decisão 12/06) | TODOS os leads do cliente — scorados desde que o sistema entrou em produção E os não-scorados usados só no treino — saem da mistura Google Sheets + Railway + arquivos locais e viram tabelas no database `ledger`. Custo de storage desprezível (<1 GB; disco de 10 GB já pago). |

## 3. Mapa do estado atual (levantado em 12/06/2026)

### 3.1 Escrita (quem grava score na infra do cliente)

| Escritor | Onde | Status |
|---|---|---|
| Consumer Pub/Sub — `_insert_ledger()` | `api/pubsub_branch.py:191-215` — INSERT de 26 colunas, `ON CONFLICT (event_id) DO NOTHING`; gravação na etapa 6 de `process_pending_pubsub` (`:551-558`), **falha de INSERT é engolida com warning** | VIVO (Cloud Scheduler 5/5min → `/pubsub/process-pending`, `api/app.py:5045`) |
| Conexão do consumer | `api/app.py:5082-5089` — pg8000, env `RAILWAY_DB_*`, sem ssl_context | VIVO |
| Env vars no deploy | `api/deploy_capi.sh:548-561` + `api/lib/config.sh:124-156` (`build_env_vars`); **defaults hardcoded com a senha do Railway em texto plano em `config.sh:69`** | VIVO |
| `scripts/backfill_google_scoring.py:118-128` | UPDATE manual de lead_score/decil/variant | Manual |
| `api/survey_branch.py:120` | INSERT no schema antigo | DEPRECATED, off por env |

DDL existente: `scripts/create_registros_ml.py` (12 colunas base + 6 UTM + índice `created_at`) e `scripts/add_observability_columns_registros_ml.py` (5 colunas). **Gap:** as 9 colunas de enriquecimento que o INSERT usa (`survey_responses`, `first_name`, `last_name`, `phone`, `fbp`, `fbc`, `user_agent`, `ip`, `has_computer`) não têm migração no repo — foram criadas direto no banco.

### 3.2 Leitura (quem consome o ledger)

A maioria já passa pela camada de acesso `src/data/` (`LeadRepository` + `RegistrosMLAdapter` + `LegacyAdapter`, compostos via `compose_repository()` — refator do monitoramento, Etapas 1-7 fechadas). **Quatro famílias ainda fazem SQL direto / conexão própria** e precisam de tratamento individual no repoint:

| # | Leitor fora da camada | Onde | Acionamento |
|---|---|---|---|
| a | 3 regras Pub/Sub dos alertas críticos (consumer parado, taxa de erro, skipped alto) | `src/monitoring/critical_alerts.py:396-514` — SQL direto na conn injetada | 5/5min via `/railway/process-pending` |
| b | Bloco de contagens do daily-check (T3-5) | `src/monitoring/orchestrator.py:392-474` — conn própria + 3 queries inline | 1×/dia |
| c | `load_ml_ledger` (validação) + anti-join da Fonte 4 | `src/validation/data_loader.py:1387-1492`; `validate_ml_performance.py:1256-1280` — conns próprias, **defaults hardcoded do Railway** | manual + `/validation/weekly` |
| d | Scripts ad-hoc | `gerar_scores_2026.py`, `analise_decis_por_optimization_goal.py`, `auditar_*`, `validar_paridade_scoring.py`, `test_revision_equivalence.py` (**Gate C — roda em todo deploy**, `deploy_capi.sh:633-638`) | manual/deploy |

### 3.3 Baselines que leem a tabela morta `Lead` (afetados pela limpeza E pelo calendário)

- **Regra de desvio de score** — janela 60min lê o ledger via repo; baseline 30d lê `Lead` via `LegacyAdapter` (`critical_alerts.py:778`, `src/data/adapters/legacy.py:93`). ⚠️ **Janela cega já contratada:** `Lead` parou 17/05 → a janela `[hoje-31d, hoje-1d]` seca ~17-18/06; o ledger só completa 30 dias ~22/06. Entre **~18/06 e ~22/06** a regra skipa em silêncio.
- **Segundo baseline escondido:** `api/app.py:3330-3336` (bloco E6 do daily-check) computa `expected_decil_dist` com `SELECT decil FROM "Lead" ... 31 days` para o `_check_score_distribution` — seca nas mesmas datas.
- Relatórios históricos (`ml_evolution_report.py:351`, decisão "não remediar" do catálogo de consumidores de score) leem `Lead.decil` — ver conflito na Etapa 5.

### 3.4 Estoque a limpar na infra do cliente (inventário live 12/06)

| Onde | O quê | Volume |
|---|---|---|
| Railway `Lead` | `leadScore`, `decil` | 142.940 linhas preenchidas |
| Railway `leads_capi` | `lead_score`, `decil`, `scored_at` | só 21 preenchidas |
| Railway `registros_ml` | tabela inteira (inclui `variant`, `decile_propensity`, `decile_roas_v1`) | ~19k linhas, crescendo |
| Planilha "[LF] Pesquisa" (`1VYti8jX...`) | colunas `lead_score`/`decil` + Apps Script: trigger `executarPolling5Min` (5/5min), funções `buscarLeadsPendentes`/`processarLeads`/`reprocessarLeadsSemScore` (`api/apps-script-code.js`) | histórico até 17/05; polling roda no vazio |

---

## 4. Etapas

### Etapa 0 — Preparo (não toca produção) ✅ CONCLUÍDA 12/06/2026

- [x] Database `ledger` criado na `smart-ads-db`; user `ledger_app` com privilégio mínimo (CONNECT só no `ledger`, USAGE+CREATE no schema; `mlflow` revogado de PUBLIC — testado que `ledger_app` não conecta nele)
- [x] **DDL consolidado** em `scripts/create_ledger_cloudsql.py`: espelho do schema live (32 colunas — 12 base + 6 UTM + 9 enriquecimento sem migração + 5 observabilidade) + índices `created_at` e `lower(email)`; idempotente, com `--verify`
- [x] Conectividade decidida: **IP público por ora** (a instância já estava aberta em `0.0.0.0/0` desde a era MLflow — ver risco §6.8); endurecimento (connector + fechar a rede) registrado pra Etapa 4-5
- [x] Senha do `ledger_app` no **Secret Manager** (`ledger-db-password`, projeto smart-ads-451319) + `LEDGER_DB_*` no `V2/.env` local. A injeção no `config.sh`/deploy fica pra Etapa 1 (quando o consumer passar a usar)
- [x] Smoke como `ledger_app`: INSERT (com JSONB) + SELECT + DELETE ok

**Rollback:** n/a (nada em produção foi tocado).

### Etapa 1 — Dual-write no consumer (código pronto 12/06 — falta deploy)

Implementação final usou **uma env var de 3 estados** em vez do boolean planejado: `LEDGER_TARGET = railway (default) | dual | cloudsql` — mesma flag serve as Etapas 1 e 4, flip sem rebuild via `gcloud run services update`.

- [x] `api/pubsub_branch.py`: `ledger_target()` + `_insert_ledger` não-destrutivo (dual-write insere a mesma linha 2×) + etapa de persistência com primário/espelho
- [x] **Fail-loud no primário**: INSERT que falha no Cloud SQL deixa a mensagem **sem ack** (pareamento linha↔ack_id novo no `pending_ledger`) → Pub/Sub reentrega, `ON CONFLICT` dedupa. Espelho Railway segue tolerante (warning). Sem `ledger_conn`, degrada pra railway com erro no log (não perde linha).
- [x] `api/app.py` (endpoint `/pubsub/process-pending`): conexão Cloud SQL aberta quando `LEDGER_TARGET≠railway`; falha na conexão → 500 (Scheduler re-tenta, fila segura as mensagens)
- [x] Deploy: `config.sh` injeta `LEDGER_TARGET` + `LEDGER_DB_*` com senha do **Secret Manager** no momento do deploy (sentinela aborta o deploy se o secret não vier); `deploy_capi.sh` checa a sentinela
- [x] Testes: 7 novos em `tests/test_pubsub_branch.py` (24/24 verdes; vizinhos `test_critical_alerts_pubsub` 10/10 e `test_pubsub_summary` 7/7 ok)
- [x] **Deploy canary** 12/06 ~18h: revisão `smart-ads-api-00701-tud`, gates B/D/C.1/C.2 todos verdes, 10% → verificação live (7 leads reais gravados nos DOIS bancos, 0 erros) → 100%. Embarcou junto o fix do baseline (`5f3994e`). Rollback: `--to-revisions smart-ads-api-00699-bom=100`
- [ ] Checagem de paridade diária por ~7 dias: count + amostra por dia nos dois bancos (início 13/06; cortar pra Etapa 4 ~19-20/06 se limpa)

**Rollback:** `LEDGER_TARGET=railway` via `gcloud run services update` → comportamento atual em ~2min, sem rebuild.

### Etapa 2 — Backfill + consolidação do dataset histórico completo

**2a — Ledger vivo:** ✅ 13/06
- [x] `scripts/backfill_ledger_railway_to_cloudsql.py` (idempotente, `ON CONFLICT`, insert multi-row): 20.302 linhas → Cloud SQL, **0 event_ids ausentes**, spot-check 5/5 idêntico e contagens de não-nulos batendo (score/decil/survey/computador/variante)

**2b — Acervo completo de leads (decisão 12/06 — dataset único consolidado):**
O acervo vai de **dez/2024 (LF01, leads a partir de 30/12/2024) até hoje**, espalhado em (verificado em 12/06):
- `data/devclub/*.xlsx` locais — arquivos originais de treino: `[LF01]`-`[LF08] Pesquisa`, `LF10`-`LF34 Lead Score` e variantes (dez/2024 → out/2025)
- Planilha central Backup (set/2025 → fev/2026, 66,8k) e Produção (dez/2025 → mai/2026, 105k) — incluem não-scorados que só serviram pro treino
- `data/backups/cloud-sql-final-export-20260225.sql` — dump do Cloud SQL pré-Railway (cross-check da era fev/2026)
- Railway `Lead` (fev → 17/mai/2026, 143k) · `lead_surveys`+`Client`+`UTMTracking` (12-21/05) · `registros_ml` (23/05+)
- Parquets locais de backtest · planilhas "[LFxx] Leads" (computador pós-migração)

Consolidar em DUAS tabelas no database `ledger`:

- [ ] `leads_historico` — 1 linha por lead: identidade (email/telefone/nome), `captured_at`, UTMs, TODAS as respostas da pesquisa (schema canônico PT), `tem_computador`, e colunas de proveniência (`fonte`, `lf`, `score_producao`/`decil_producao` da época quando existirem)
- [ ] `scores_historicos` — re-scores versionados: começa com os 192k de 2026 (`scores_2026_por_lead.csv` + LF57/LF58, que já estão scorados e só foram filtrados do relatório), **com chave de versão** (`mlflow_run_id` champion/challenger + commit do `core/`) — ver §5
- [ ] Loaders por fonte: **reusar os de `scripts/gerar_scores_2026.py`** (planilha central com dedup captura/pesquisa, cache Lead, híbrido lead_surveys, ledger com `has_computer`) — já resolveram era por era
- [ ] Dedup por email×LF com proveniência preservada; conferência de counts por fonte vs origem
- [ ] Conferir cobertura: leads de treino (pré-produção, sem score) presentes; sem janelas órfãs entre eras

**Ganhos colaterais:** (1) o conflito da Etapa 5 com relatórios históricos morre — eles apontam pra cá; (2) materializa o backlog "SQLite local para análises ad-hoc" direto no Cloud SQL; (3) datasets de retreino passam a sair de uma fonte só.

**Rollback:** DROP das tabelas novas; nada upstream depende delas ainda.

### Etapa 3 — Repoint dos leitores (um por commit)

Ordem do menor risco pro maior:

- [ ] 3.1 Camada `src/data/`: `compose_repository('registros_ml')` passa a conectar no Cloud SQL (a decisão de fonte é por env — ponto único de composição). Cobre: alertas críticos via repo, capi_monitor, operational_monitor, data_quality, pubsub_summary, endpoints de diagnóstico.
- [ ] 3.2 As 3 regras Pub/Sub com SQL direto (`critical_alerts.py:396-514`): recebem conn do Cloud SQL (ou migram pro repo, melhor)
- [ ] 3.3 Bloco T3-5 do orchestrator (`orchestrator.py:392-474`): conn própria → Cloud SQL
- [ ] 3.4 `data_loader.load_ml_ledger` + anti-join de `validate_ml_performance.py:1256-1280`: trocar para `LEDGER_DB_*`; **varrer defaults hardcoded `shortline.proxy.rlwy.net` nesses arquivos**
- [ ] 3.5 Gate C (`test_revision_equivalence.py:176,244`) + carregamento de env no `deploy_capi.sh:638`
- [ ] 3.6 Scripts ad-hoc (lista em §3.2-d) — podem migrar em lote
- [ ] 3.7 Baselines: trocar `compose_repository('legacy')` (`critical_alerts.py:778`) e o E6 (`app.py:3330-3336`) para a fonte nova — ver §5 (baseline interino com scores 2026 cobre a janela cega)

**Rollback:** cada commit é pequeno e reversível individualmente; env vars decidem a fonte.

### Etapa 4 — Cortar o espelho Railway

- [ ] `LEDGER_DUAL_WRITE=false` (consumer grava SÓ no Cloud SQL)
- [ ] Critério: ≥7 dias de paridade limpa + monitoramento verde + `/validation/weekly` rodou ok na fonte nova

**Rollback:** religar o dual-write (os dados do período sem espelho podem ser re-copiados do Cloud SQL pro Railway se precisar voltar — improvável).

### Etapa 5 — Limpeza do estoque histórico na infra do cliente

**Pré-condições:** Etapas 3-4 estáveis; baseline do drift já apontado pra fonte nova (3.7); **decisão do conflito histórico abaixo tomada.**

⚠️ **Conflito (resolvido pela Etapa 2b):** os relatórios históricos (`ml_evolution_report.py` lê `Lead.decil`; catálogo de consumidores de score decidiu "preservar histórico operacional") quebrariam quando `Lead.leadScore`/`decil` fossem anulados. Com a consolidação da Etapa 2b, `leads_historico` preserva o score de produção da época (`score_producao`/`decil_producao`) — basta repointar esses relatórios pra lá ANTES de anular as colunas no Railway. Adicionar checkbox: repoint de `ml_evolution_report.py`/`extract_evolution_metrics.py` pro Cloud SQL.

- [ ] Dump completo pro nosso lado: `Lead` (id, email, createdAt, leadScore, decil, capiSentAt), `leads_capi` (colunas de score), `registros_ml` inteira → GCS nosso + (opcional) tabela `lead_legado` no Cloud SQL
- [ ] `UPDATE "Lead" SET "leadScore"=NULL, decil=NULL` (142.940 linhas)
- [ ] `UPDATE leads_capi SET lead_score=NULL, decil=NULL, scored_at=NULL` (21 linhas)
- [ ] `DROP TABLE registros_ml` no Railway
- [ ] Planilha "[LF] Pesquisa": deletar trigger `executarPolling5Min` (e avaliar `executarMonitoramentoDiario`), apagar/limpar as colunas `lead_score` e `decil` (backup CSV antes)
- [ ] Nosso código tolera a planilha sem score (`data_loader.py:487-517` condiciona; `validate_ml_performance.py:1513-1514` põe NaN) — smoke do relatório de validação depois

**Rollback:** restore do dump (GCS) de volta pro Railway. Janela de arrependimento: manter o dump para sempre; não há pressa em apagar nada do nosso lado.

---

## 5. Sinergia — o que fazer com os 180k scores re-scorados de 2026

Dataset: `outputs/validation/scores_2026/scores_2026_por_lead.csv` (179.849 leads, DEV19→LF56; LF57/58 scorados e filtráveis de volta), Champion jan30 + Challenger abr28 sob código atual, paridade exata com produção validada no LF57. Oportunidades por ordem de valor/urgência:

| # | Uso | Esforço | Quando |
|---|---|---|---|
| 1 | **Baseline interino da regra de desvio de score + E6** — cobre a janela cega ~18-22/06 e substitui o baseline da `Lead` morta. Formato: JSON estático por variante (precedente: `configs/reference_audience_profiles/devclub.json`, carregado em `app.py:3141`) ou tabela `scores_historicos` no Cloud SQL lida por um adapter. Cuidados: decil "D09"→int, baseline por variante, divergência re-score↔online ~6% pode pedir recalibração do threshold de 1σ. | baixo-médio | **urgente — antes de 18/06**, independe do resto do plano |
| 2 | **Baseline "produção" do backtest comparativo** — `_attach_production_decil` (`backtest_data.py:415-464`) lê a `Lead` morta e volta vazio pra LF54+; merge por email com o dataset entrega decil dos dois modelos re-scorados pros 16 LFs. | baixo | junto da Etapa 2 |
| 3 | **Gate offline Champion vs Challenger** (A/B em standby) — os dois scores nos mesmos leads eliminam a assimetria "challenger re-scorado vs champion fotografado" da rodada anterior. Falta: telefone (re-join com fontes de leads pro matching), vendas matched, spend, janela de conversão fechada (LF56 só ~11/07), e recorte out-of-sample honesto (≈LF54+ para ambos). | médio | depois da migração |
| 4 | **Recalcular tabelas de valor por decil** (decile_value) — dataset dá o denominador num pool 2× maior e sem mistura de versões de código; falta reconstruir o pipeline de valor (buyers matched + shrinkage + isotônica — o script original era ad-hoc em /tmp e se perdeu). ⚠️ Mexe no `value` enviado ao Meta → fluxo da dívida de valor por decil (DT-17) + Gate D, nunca sem aprovação. | médio-alto | frente separada |
| 5 | **Não usar para:** forecast do lançamento corrente (precisa de re-score vivo, não fotografia — reusar os *loaders* do gerador, não o CSV) e relatórios históricos L3/L6 (decisão registrada: preservar números operacionais da época; contrafactual só como coluna adicional rotulada). | — | — |

O item 1 do plano de remediação de score (cache versionado regenerado no daily-check, item L5 do catálogo) descreve exatamente isso — o CSV é a primeira geração manual desse cache; a tabela `scores_historicos` com chave de versão é o caminho de oficializar.

## 6. Riscos e pontos de atenção

1. **Janela cega do baseline 18-22/06** — tratável já pelo item 1 da §5, antes mesmo da Etapa 0.
2. **Senha do Railway em texto plano** em `api/lib/config.sh:69` — não repetir o padrão com o Cloud SQL; aproveitar a Etapa 0 para Secret Manager (a senha antiga sai de cena com a Etapa 4-5 de qualquer forma).
3. **Falha de INSERT engolida** no consumer — vira fail-loud no destino primário (Etapa 1).
4. **Semânticas de variant divergentes**: `load_ml_ledger(variant_filter=None)` filtra `variant IS NULL`; o `RegistrosMLAdapter` traz tudo. Ao repointar baselines, decidir o filtro explicitamente.
5. **Múltiplos terminais** — `critical_alerts.py`/`app.py` estão sob o refator da camada de acesso; coordenar commits (escopo restrito, um leitor por commit).
6. **`rule_no_leads_arriving` lê `lead_surveys` morta** (`critical_alerts.py:300-309`) — achado correlato, escopo separado; registrar e não emendar aqui.
7. **Latência/limites do db-f1-micro** (shared core, ~25 conexões úteis): consumer + monitoramento + MLflow no mesmo micro. Observar na Etapa 1; subir tier é mudança de 1 flag.
8. **Instância aberta em `0.0.0.0/0`** (herança da era MLflow; só senha protege). Aceito temporariamente pra não bloquear a migração; endurecer na Etapa 4-5: Cloud SQL connector no Cloud Run + remover a authorized network aberta + (opcional) trocar a senha do `postgres`, que está hardcoded em `src/model/training_model.py:28`.

## 7. Registro de execução

| Data | Etapa | O que foi feito | Commit |
|---|---|---|---|
| 12/06 | pré | Fix do baseline do desvio de score (fallback pro ledger; cobre janela cega 18-22/06) — **pendente deploy** | `5f3994e` |
| 12/06 | 0 | Database `ledger` + user `ledger_app` (Secret Manager) + DDL 32 colunas + smoke ok | `4f30266` |
| 12/06 | 1 | Dual-write implementado (`LEDGER_TARGET` 3 estados, fail-loud + ack seletivo, 24/24 testes) | `337609c` |
| 12/06 | 1 | **Deploy em produção**: rev `00701-tud` @100%, gates verdes, dual-write verificado live (7/7 linhas nos 2 bancos). Fix do baseline embarcado. Falta: paridade diária ~7d | — |

## 8. Como retomar numa sessão nova

1. Ler este doc inteiro (5 min).
2. Conferir o registro de execução (§7) e o estado live: `gcloud sql databases list --instance=smart-ads-db --project=smart-ads-451319`, env vars do serviço `smart-ads-api` (`gcloud run services describe`), e `git log --oneline -10`.
3. A regra do projeto exige `/sw-architect` antes de mexer na camada de acesso a dados — o desenho já foi feito (12/06, esta sessão); mudanças de rota em relação a este doc passam por ele de novo.
4. Próxima ação = primeira checkbox vazia da menor etapa incompleta. Exceção: o item urgente da §5 (#1, baseline interino) pode ser feito a qualquer momento, antes de tudo.
