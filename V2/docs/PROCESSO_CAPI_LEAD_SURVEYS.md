# Disparar o evento scoreado por ML também para quem responde a pesquisa pela esteira nova

**Criado:** 2026-05-17 · **Atualizado:** 2026-05-24 (pós P17 deployed) · **Papel:** especificação e diário desta frente — fazer o evento CAPI scoreado por ML (`LeadQualified`/`LeadQualifiedHighQuality`, com valor por decil) ser disparado também a partir das mensagens publicadas pelo sistema novo do dono no Pub/Sub do GCP.

> Linguagem natural primeiro (regra do `CLAUDE.md`). Nomes de tabela/código aparecem no corpo porque o doc é técnico-operacional; o rodapé lista os artefatos. Datas absolutas.
>
> **Histórico de consolidação via /docs:**
> - 2026-05-19 — consolidação após I0–I4 da arquitetura SQL/Railway concluídos e pausados.
> - 2026-05-24 (manhã) — consolidação após virada de arquitetura: a abordagem SQL foi descartada e substituída pelo consumer Pub/Sub. Frente em produção.
> - 2026-05-24 (tarde) — registro de P17 deployed + 3 bônus emergentes do deploy (DeadlineExceeded fix, env propagada no build, Gate C script adaptado pra arquitetura nova).

---

## ✅ ESTADO ATUAL — 2026-05-24 (LIVE em produção)

**Onde estamos:** a esteira nova de scoring CAPI **está LIVE em produção desde 2026-05-23 19:45 BRT**, processando mensagens publicadas pelo sistema novo do dono no Pub/Sub do GCP. Arquitetura completamente reescrita em relação ao que estava pausado em 19/05 — a abordagem anterior (ler `lead_surveys` no Railway + enriquecer via JOIN em `integration_logs`) foi descartada e substituída por um consumer Pub/Sub que recebe o payload completo direto do sistema do dono, sem dependência de tabelas intermediárias.

### O que está rodando

- **Consumer Pub/Sub** ([api/pubsub_branch.py](../api/pubsub_branch.py), módulo novo): puxa mensagens da assinatura `lead-capture-ingest-sub`, traduz os slugs do payload em strings PT-Long que o modelo conhece, classifica (Meta-elegível / pular-allowlist / pular-faltando-dado / enviar), scoreia via o mesmo `pipeline.run` do fluxo `Lead` antigo, envia CAPI via o mesmo `send_batch_events`, grava 1 linha por lead em `registros_ml`, dá ack na mensagem.
- **Endpoint HTTP**: `POST /pubsub/process-pending` em [api/app.py](../api/app.py). Off por padrão via env `PUBSUB_CAPI_ENABLED`. Atualmente **ligado** em produção.
- **Mapa de tradução**: função `traduzir_survey_slugs` em [api/railway_mapping.py](../api/railway_mapping.py) cobre os 10 campos da pesquisa do sistema novo. Cinco têm slug nada-trivial (`idade=<18`, `ocupacao=clt`, `faixaSalarial=0`/`1000-2000`, `atracaoProfissao=trabalhar_exterior`, `interesseEvento=transicao_carreira`), cinco têm lowercase de cortesia (`genero=feminino`/`masculino`, `cartaoCredito`/`estudouProgramacao`/`faculdade`/`investiuCurso = sim`/`nao`). É idempotente em PT-Long, fail-loud em slug fora do vocabulário declarado.
- **Ledger** [`registros_ml`](../scripts/create_registros_ml.py): tabela nossa no Railway PostgreSQL, 1 linha por lead processado. PK `event_id` (UUID v7 do payload, antes era `lead_id` integer; DDL migrado idempotente em 2026-05-23). Colunas: `email`, `variant` (champion/challenger), `lead_score`, `decil`, `base_meta_event_id`, `base_status` (`sent`/`error`/`skipped_allowlist`/`skipped_missing_data`), `hq_meta_event_id`, `hq_status`, `capi_sent_at`, `error_message`, `created_at`.

  **Decisão 2026-05-24** (será implementada em seguida): adicionar também colunas `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `utm_url`. Motivo: simplificar queries de monitoramento (ranking de UTM por decil, source missing, etc.) que precisariam fazer JOIN com `lead_surveys × UTMTracking`. Single-table fica mais rápido e mais fácil de ler. Consumer Pub/Sub vai passar a gravar essas colunas no INSERT.

- **Infraestrutura GCP**:
  - Pub/Sub: projeto `smart-ads-451319`, tópico `lead-capture-ingest`, assinatura `lead-capture-ingest-sub` (retenção 31 dias, `--expiration-period=never`).
  - Service account publisher: `lead-capture-publisher@smart-ads-451319.iam.gserviceaccount.com` (entregue ao dono via chave JSON local; só pode publicar nesse tópico).
  - IAM consumer: Cloud Run SA (`smart-ads-451319@appspot.gserviceaccount.com`) tem `roles/pubsub.subscriber` na assinatura.
  - Cloud Run: revisão `smart-ads-api-00503-mip` a 100% de tráfego (promovida em 2026-05-24 após P17), com `PUBSUB_CAPI_ENABLED=true`. Tag `prod` apontando pra essa revisão. Revisões anteriores (`00341-ml6`, `00494-xoj`, `00501-xom`) ficaram a 0% como histórico recuperável.
  - Cloud Scheduler: job `pubsub-process-pending`, `*/5 * * * *` America/Sao_Paulo, ENABLED.

### Gates passados (deploy de 2026-05-23)

- **Gate B** (smoke test pós-deploy): passou.
- **Gate D** (auditoria do YAML dentro da imagem): passou — variants `champion_jan30` e `challenger_abr28` consistentes.
- **Gate C.1** (equivalência de score raw + decil contra revisão de referência em produção): passou, 7 leads do Railway comparados, 0 divergências.
- **Gate C.2** (equivalência de decil + value + event_name no caminho A/B): passou, 9 leads, 0 divergências.
- **Bonus**: o script do Gate C.1 ([scripts/test_revision_equivalence.py](../scripts/test_revision_equivalence.py)) foi corrigido no commit `c09e0d2`. Antes ele exigia que a revisão de referência tivesse tag de URL, e falhava com "revisão sem URL tagged" se quem fez o deploy anterior não tivesse movido a tag `prod` ao promover. O fix devolve a URL principal do serviço como fallback quando a revisão alvo serve 100% e está sem tag — a URL principal sempre roteia pra quem está a 100%. O gate ficou intrínseco, não depende mais de convenção operacional frágil.

### Smoke real do primeiro ciclo

2026-05-23 19:45 BRT, 25 mensagens processadas no primeiro disparo manual do endpoint:

- **14** → `skipped_allowlist` (source não-Meta — todos QA: `org`, `acfields`, `google`, `tiktok`, `organic`).
- **3** → `skipped_missing_data` (Meta-eligible mas sem `fbp`/`fbc`/`hasComputer` no payload — emails `loadtest-meta-*@test.dev`).
- **8** → `error` — bug residual **não-bloqueante**: o load test antigo (publicado em 21–22/05 simulando o contrato anterior) enviou `Sou autônomo` com acento; o `traduzir_survey_slugs` só aceita o slug `autonomo` ou a forma canônica `Sou autonomo` sem acento. Como o contrato com o dono (REQUISITOS_SISTEMA_NOVO.md Anexo A.2) usa slug, essa forma só apareceu por dado sintético antigo. **Decisão: não corrigir** — em produção real não dispara.
- **0 enviados** ao Meta (nenhum lead Meta-source no backlog).

Backlog do load test antigo (744 mensagens restantes) **purgado** em 2026-05-24 via `gcloud pubsub subscriptions seek lead-capture-ingest-sub --time=now`. Assinatura ficou vazia, pronta para receber só leads reais a partir da semana de 2026-05-26 (quando o gestor de tráfego ativar os anúncios do sistema novo).

### Testes automatizados

| Arquivo | Cobertura | Status |
|---|---|---|
| [tests/test_traduzir_survey_slugs.py](../tests/test_traduzir_survey_slugs.py) | Tradução slug→PT, paridade encoding(slug)==encoding(PT-Long), idempotência, fail-loud, não-mutação | 7/7 |
| [tests/test_pubsub_branch.py](../tests/test_pubsub_branch.py) | Funções puras do consumer (parse, payload→survey_dict, payload→enrich, payload→utm, is_meta_eligible, classify, ledger_row) — contra payload real | 14/14 |
| [tests/test_survey_mapping.py](../tests/test_survey_mapping.py) | Regressão do adaptador I2 (continua válida) | 5/5 |

### Pendências antes da próxima fase

1. **Colunas UTM no `registros_ml`** — DDL `ALTER TABLE ADD COLUMN IF NOT EXISTS` + ajuste do consumer pra gravar. Curto (1 commit).
2. **Refatorar monitoramento** (§7 abaixo). 26 itens mapeados; 13 precisam adaptar query, 1 vai ser removido, 4 vão ser criados do zero.
3. **Verificação de UTM pré-go-live cliente** — quando o gestor de tráfego subir as tags do sistema novo (previsto 2026-05-26+), rodar dry-run medindo distribuição de `utm.medium` nas 7 categorias canônicas do modelo (`Aberto`, `Linguagem de programação`, 3× Lookalike, `dgen`, `Outros`). Se vier tudo em `Outros`, é a quebra histórica chamada "Cluster 5" voltando — sinal degrada sem barulho. Era a antiga frente "I6"; segue válida.

### Pausa anterior superada

O design original (chamado nos protocolos antigos de **I3** = enriquecimento por JOIN com `integration_logs` e **I4** = ramo isolado lendo `lead_surveys`) ficou pausado em 2026-05-19 antes do deploy canary. **Em 2026-05-23 a pausa foi superada por uma virada de arquitetura** — em vez de retomar I3/I4, foi construído o consumer Pub/Sub do zero, com payload completo do dono. Os módulos do design antigo continuam no repositório mas com header `[DEPRECATED 2026-05-23]`:

- [api/survey_enrichment.py](../api/survey_enrichment.py) — enriquecimento por log; substituído porque o payload Pub/Sub já traz `hasComputer`/`fbp`/`fbc`/`firstName`/`lastName`/`phone`/`userAgent`/`ip` direto.
- [api/survey_branch.py](../api/survey_branch.py) — ramo isolado lendo Railway; substituído pelo consumer Pub/Sub.

O hook `_run_survey_branch_safely` em [api/app.py](../api/app.py) continua presente mas off por env (`SURVEY_CAPI_ENABLED` default false), pronto para remoção na próxima limpeza.

---

## 1. O quê e por quê

**O quê:** o job que scoreia leads e dispara o evento de qualidade ao Meta passou a ler **também** das mensagens publicadas pelo sistema novo do dono no Pub/Sub do GCP, mantendo o fluxo `Lead` antigo exatamente como estava (mesmo modelo `jan30`, mesma `pipeline.run`, mesmo `send_batch_events`, mesma rotina A/B Champion/Challenger).

**Por quê (o que forçou a frente):** a captação de produção **migrou** da tabela `Lead` para a tabela `lead_surveys` por volta de 2026-05-12. Medições de 17–18/05 mostraram que a `Lead` ficou com 0 entradas desde 17/05 00:35 BRT e a `leads_capi` desde 17/05 18:29 BRT — ambas mortas. Como nosso pipeline lia só da `Lead`, **o sinal CAPI scoreado por ML estava OFF para toda a captação viva** desde a migração. Esta frente restaura esse sinal.

**Por que virou Pub/Sub:** o desenho inicial (ler `lead_surveys` do Railway + enriquecer via JOIN frágil em `integration_logs`) ficou pausado em 2026-05-19. Antes de retomar, o dono do sistema novo aceitou publicar o payload completo (com todos os campos que precisamos — `hasComputer`, `fbp`, `fbc`, identidade, UTM, etc.) num tópico Pub/Sub que nós controlamos. Isso eliminou três fragilidades de uma vez:

- Acoplamento ao schema do Railway dele (que pode mudar quando ele decidir).
- JOIN entre múltiplas tabelas dele (`lead_surveys` + `integration_logs` + `UTMTracking` + `Client`).
- Parse de JSON dentro de log do n8n pra recuperar campos que a tabela não tinha (`computador`, `fbp`, `fbc`).

A fronteira virou contratual: ele publica payload no formato declarado em [REQUISITOS_SISTEMA_NOVO.md](REQUISITOS_SISTEMA_NOVO.md) (Anexo A), nós consumimos.

## 2. O que a investigação encontrou (16–18/05) — histórico

Esta seção descreve a investigação que motivou a frente original. Mantida como contexto; o desenho final (Pub/Sub) tornou várias dessas descobertas irrelevantes na prática, mas elas explicam o caminho.

**Duas esteiras quase disjuntas.** `Lead` (funil antigo, front via Prisma) vs `lead_surveys` (sistema novo desde 12/05). Em 7 dias, só ~2% de sobreposição de email (13 de ~720). Era população nova, invisível ao nosso scoring/CAPI — não dava para "fazer lookup" na `Lead`.

**A esteira nova já mandava evento próprio pro Meta, mas genérico.** O `integration_logs` mostrava a stack do front (n8n) enviando `meta_capi/Lead` e `meta_capi/CompleteRegistration` (~1.765/7d), bem casados (email/telefone/fbp/fbc). O que **nunca** ia para esses leads era o **nosso** evento scoreado (`LeadQualified` com valor por decil). O gap era o sinal de qualidade, não a existência de evento.

**A `lead_surveys` não tinha tudo que o scorer/CAPI precisavam.** Schema dela: `id, clientEmail, genero, idade, ocupacao, faixaSalarial, cartaoCredito, estudouProgramacao, faculdade, investiuCurso, atracaoProfissao, interesseEvento, eventId, ip, submittedAt`. Faltava: `computador` (feature principal do modelo), UTM, fbp/fbc, telefone, nome. Esses campos precisavam ser recuperados por JOIN com outras tabelas vivas do mesmo Railway:

| Campo | Fonte de recuperação | Cobertura final medida |
|---|---|---|
| Respostas de pesquisa (10 campos) | colunas da própria `lead_surveys` | 100% |
| `computador` | `integration_logs`: `n8n_onboarding.tem_computador` **ou** `activecampaign` campo 144 | **≈100%** combinado |
| UTM (source/medium/campaign/content/term + url) | `UTMTracking` por email (linha mais recente ≤ `submittedAt`) | ~98% |
| fbp/fbc/ip/user_agent | `integration_logs` `meta_capi`: JOIN por `eventId` (1:1) com fallback email | ~98% (e **100% entre os Meta-elegíveis**) |
| telefone/nome | `integration_logs` `n8n_onboarding` por email | ~90% |

**Achado de 2026-05-19 (já refletindo na decisão pela mudança de arquitetura):** o sistema novo já tem três tabelas vivas atualizadas todos os dias (`Client`, `lead_surveys`, `UTMTracking`). Na população alvo — quem respondeu pesquisa nos últimos 7 dias, n=1.588 —, o `Client` expõe `hasComputer` 100%, `eventId` 100%, `fbp` 99,9% e `fbc` 92,8% (99,9% entre Meta-elegíveis facebook/instagram). Ou seja: o que esta frente recuperava por parse de log já existia como coluna limpa no `Client`. Esse achado foi um dos gatilhos pra reconsiderar a arquitetura — em vez de parsear log, ler do `Client`. Mas a virada final foi mais radical (Pub/Sub direto do dono), porque elimina também a dependência do Railway dele.

**Vocabulário das respostas: 100% seguro.** Cada valor de `lead_surveys`, após a normalização que já roda em produção (`_limpar_texto` + mapas em `api/railway_mapping.py`), cai só em categorias que o funil `Lead` já produzia. Zero categoria nova. Esse achado ficou na arquitetura nova como teste de paridade — `tests/test_traduzir_survey_slugs.py::test_paridade_encoding_slug_vs_pt` prova que `encoding(payload_slug_do_PubSub) == encoding(payload_PT_Long_do_Lead_antigo)`, vetor bit-idêntico.

## 3. Decisões (datas absolutas)

| # | Decisão | Quando |
|---|---|---|
| 1 | Implementar já uma esteira nova de scoring CAPI, não esperar o dono fazer mudanças no schema dele | 2026-05-17 |
| 2 | `leads_capi` só como fallback (e na prática já estava morta) | 2026-05-17 |
| 3 | Recuperação de 24h + forward ao ligar — processar `lead_surveys` com `submittedAt` nas últimas 24h e dali pra frente; dedup pelo ledger; não re-disparar nada mais antigo que 24h (conversão velha suja a otimização do Meta) | 2026-05-18 (revisou "forward-only puro") |
| 4 | Extensão de monitoramento entra junto, não vira follow-up | 2026-05-17 |
| 5 | Ledger próprio `registros_ml` para dedup/registro — não escreve na tabela do front, não polui `leads_capi` | 2026-05-17 |
| 6 | Fluxo `Lead` intocado; ramo da esteira nova roda isolado (try/except próprio), nunca derruba o `Lead` | 2026-05-17 |
| 7 | Fail-loud: cobertura caindo → alerta; categoria desconhecida → falha alto; batch zerado → assert | 2026-05-17 |
| 8 | Restrições duras: lead sem `hasComputer` **ou** sem `fbp`/`fbc` → não dispara, registra skip no ledger | 2026-05-17 |
| 9 | **Virar arquitetura pra Pub/Sub** — descartar leitura Railway + parse de log; dono publica payload completo no nosso tópico, nós consumimos. Contrato em [REQUISITOS_SISTEMA_NOVO.md](REQUISITOS_SISTEMA_NOVO.md). | 2026-05-22 (combinado com o dono) |
| 10 | **Trocar PK do ledger** de `lead_id` integer (referência à `lead_surveys.id`) para `event_id` string (UUID v7 do payload Pub/Sub) | 2026-05-23 |
| 11 | **Não criar módulo paralelo** de monitoramento — refatorar in-place. As tabelas antigas (`Lead`/`leads_capi`) estão mortas e o "preservar caminho SQL" foi reconsiderado | 2026-05-24 |
| 12 | **Adicionar colunas UTM ao `registros_ml`** — `utm_source`/`utm_medium`/`utm_campaign`/`utm_content`/`utm_term`/`utm_url`. Single-table em vez de JOIN | 2026-05-24 |

## 4. Como foi feito — protocolo por item

Cada item foi um ciclo fechado: implementa → testa → commita → (deploy canary 0% → valida → promove, com OK explícito do usuário). Tudo em worktree isolado `feat/capi-lead-surveys-scoring`.

### Fase 1 — Design SQL/Railway (pausado e descartado em 2026-05-23)

| Item | O que é | Status final |
|---|---|---|
| **I0** | Decisão de fonte + registro da frente no roadmap | ✅ 2026-05-17 |
| **I1** | Tabela-ledger `registros_ml` (script idempotente, aplicado/testado no Railway) | ✅ commits `9b57c0d`+`31d1151` |
| **I2** | Adaptador `api/survey_mapping.py` — função pura que monta dict formato-`Lead` a partir de survey+utm+enrich | ✅ commit `2a802db`. **Reaproveitado** na arquitetura Pub/Sub. |
| **I3** | Enriquecimento `api/survey_enrichment.py` — lote read-only por lead, fbp/fbc/computador via log | ✅ commit `160562c`. **[DEPRECATED 2026-05-23]** — payload Pub/Sub já traz tudo direto. |
| **I4** | Ramo isolado `api/survey_branch.py` + hook no `/railway/process-pending` | ✅ commit `d2587f0`. **[DEPRECATED 2026-05-23]** — substituído pelo consumer Pub/Sub. |
| **I5–I7** | Monitoramento + verificação UTM + ligar | Recalibrado na arquitetura nova (§6 + §7 abaixo) |

### Fase 2 — Arquitetura Pub/Sub (live em 2026-05-23)

| Item | O que é | Status |
|---|---|---|
| **P1** | Contrato cliente — JSON schema do payload + PDF entregue ao dono | ✅ commit `c1aa3bf` ([REQUISITOS_SISTEMA_NOVO.md](REQUISITOS_SISTEMA_NOVO.md)) |
| **P2** | Pub/Sub provisionado — tópico + sub 31d + SA publisher + chave entregue ao dono | ✅ 2026-05-22 |
| **P3** | Verificação dos primeiros 9 leads que o dono publicou — formato slug confirmado | ✅ 2026-05-23 |
| **P4** | DDL do ledger migrado — PK `lead_id` integer → `event_id` string (UUID v7) | ✅ aplicado idempotente |
| **P5** | Mapa slug→PT em [api/railway_mapping.py](../api/railway_mapping.py) — `traduzir_survey_slugs` para os 10 campos da pesquisa | ✅ commit `3457916` |
| **P6** | Consumer [api/pubsub_branch.py](../api/pubsub_branch.py) — pull/parse/translate/classify/score/send/ledger/ack | ✅ commit `3457916` |
| **P7** | Endpoint `POST /pubsub/process-pending` em [api/app.py](../api/app.py) | ✅ commit `3457916` |
| **P8** | Deprecar `survey_branch.py` + `survey_enrichment.py` via header `[DEPRECATED 2026-05-23]` | ✅ commit `3457916` |
| **P9** | Merge `feat/capi-lead-surveys-scoring` → `main` (sem conflitos, auto-merge no `app.py`) | ✅ commit `43a0d98` |
| **P10** | Fix Gate C.1 — `scripts/test_revision_equivalence.py` aceita revisão de 100% sem tag | ✅ commit `c09e0d2` |
| **P11** | Deploy canary `00494-xoj` 0% tráfego + Gates B/D/C.1/C.2 + promoção a 100% | ✅ 2026-05-23 |
| **P12** | IAM `roles/pubsub.subscriber` concedido ao Cloud Run SA | ✅ 2026-05-23 |
| **P13** | Cloud Scheduler `pubsub-process-pending` criado (`*/5 * * * *`, ENABLED) | ✅ 2026-05-23 |
| **P14** | `PUBSUB_CAPI_ENABLED=true` em prod (revisão `00341-ml6` a 100%) | ✅ 2026-05-23 19:45 BRT |
| **P15** | Smoke real do primeiro ciclo: 25 mensagens processadas, 0 enviadas ao Meta | ✅ 2026-05-23 |
| **P16** | Purga do backlog do load test antigo (744 msgs) via `seek --time=now` | ✅ 2026-05-24 |
| **P17** | Colunas UTM no `registros_ml` (DDL + consumer) | ✅ 2026-05-24 commit `fe201bf` (DDL+consumer+testes 16/16) — deploy `00503-mip` |
| **P17.1** | Fix DeadlineExceeded no pull do Pub/Sub em fila vazia (consumer não pode responder 500 quando queue está vazia) | ✅ 2026-05-24 commit `0a8091e` — descoberto no smoke do canary P17 |
| **P17.2** | `PUBSUB_CAPI_ENABLED=true` propagado pelo `build_env_vars` (não precisa mais setar manual a cada redeploy) | ✅ 2026-05-24 commit `4768843` |
| **P17.3** | Gate C.1/C.2 script (`scripts/test_revision_equivalence.py`) adaptado pra ler de `lead_surveys`+`Client`+`UTMTracking`+`registros_ml` em vez de `Lead`+`leads_capi` mortas | ✅ 2026-05-24 commit `56f61c4` — validado manual com 30 leads no predict-mode e 3 leads no capi-dry-run mode, 0 divergências |
| **P18** | Refatorar monitoramento (§7) | ⏳ próximo |

## 5. Desenho técnico (Pub/Sub, implementado em P1–P16)

1. **Contrato com o dono** ([REQUISITOS_SISTEMA_NOVO.md](REQUISITOS_SISTEMA_NOVO.md)): 1 payload JSON por lead, publicado no tópico `lead-capture-ingest`. Identificador estável (`eventId` UUID v7 que o dono persiste no lado dele), `submittedAt` ISO-8601, identidade (`email`/`firstName`/`lastName`/`phone` em E.164), captura Meta (`fbp`/`fbc` ou null, nunca string vazia), `hasComputer` top-level, `userAgent` cru, `ip4`, objeto `survey` com as 10 respostas em forma slug ou lowercase, objeto `utm` cru do anúncio.

2. **Ledger `registros_ml`** (nosso): `event_id` TEXT PRIMARY KEY (UUID v7 do payload, estável entre reenvios). Demais colunas em §"O que está rodando" acima. Dedup é trivial: `ON CONFLICT (event_id) DO NOTHING`. Fonte de leitura do monitoramento (§7).

3. **Consumer** ([api/pubsub_branch.py](../api/pubsub_branch.py)): chamado a cada 5 min pelo Cloud Scheduler via `POST /pubsub/process-pending`. Off por padrão via env `PUBSUB_CAPI_ENABLED` (deploy ≠ ligar). Quando ligado:
   - **Pull** batch de até 25 mensagens da assinatura.
   - **Parse** JSON. Payload inválido vira erro de log + ack (não recicla).
   - **Traduz slugs** via `traduzir_survey_slugs`. Slug fora do vocabulário declarado → `ValueError`, registra lead com `base_status='error'`, ack.
   - **Classifica**:
     - Source não está na allowlist Meta (`facebook-ads`/`instagram`/`ig`/`fb`/`facebook` per [configs/clients/devclub.yaml](../configs/clients/devclub.yaml)) → `skipped_allowlist`.
     - Meta-elegível mas faltando `hasComputer` ou `fbp` ou `fbc` → `skipped_missing_data`.
     - Caso contrário → `send`.
   - **Scoreia** os de `send` usando o **mesmo** `pipeline.run` do fluxo `Lead`, mesmo roteamento A/B Champion/Challenger, mesmo `atribuir_decil_por_threshold`. Nenhuma transformação reimplementada → equivalência por construção (Gate C.1/C.2 trivial).
   - **Envia CAPI** via o **mesmo** `send_batch_events`. `event_id` Meta = `qualified_<eventId-do-payload>` para o evento base, `hq_<eventId>` para o high-quality (se decil ≥ 9).
   - **Grava ledger** para todos os desfechos (sent/error/skipped_*).
   - **Ack** as mensagens processadas. Dry-run não acka — permite re-rodar contra o backlog em canary.

4. **Idempotência ponta-a-ponta**: o `eventId` do payload é o mesmo entre reenvios do dono (contrato), é nosso PK no ledger (`ON CONFLICT DO NOTHING`), e é o que vira o `event_id` no Meta CAPI (Meta deduplica por isso também). Reentregar a mesma mensagem 10 vezes resulta em 1 linha no ledger e 1 evento no Meta.

5. **Allowlist do envio ao Meta** ([configs/clients/devclub.yaml](../configs/clients/devclub.yaml) → `utm_source_allowlist`): hoje contém `facebook-ads`, `instagram`, `ig`, `fb`, `facebook`. Source fora dela não dispara evento Meta. Verificada contra o **valor bruto** de `utm.source` no payload — não depende do mapeamento de sinônimos.

## 6. Pendências obrigatórias antes da próxima fase

1. **Colunas UTM no `registros_ml`** (item 12 das decisões). DDL idempotente via `ALTER TABLE ADD COLUMN IF NOT EXISTS utm_source TEXT`, idem para os outros 5. Ajustar `_insert_ledger` no consumer pra popular as novas colunas a partir do `payload.utm`. Sem isso, as queries de monitoramento (§7) precisam JOIN com `lead_surveys × UTMTracking` por email — mais lento, mais frágil.

2. **Verificação UTM pré-go-live cliente** — quando o gestor de tráfego do cliente (DevClub) ativar as campanhas do sistema novo, rodar dry-run medindo:
   - Distribuição de `utm.medium` nas 7 categorias canônicas do modelo (`Aberto`, `Linguagem de programação`, `Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação`, `Lookalike 2% Cadastrados - DEV 2.0 + Interesses`, `Lookalike 2% Alunos + Interesse Linguagem de Programação`, `dgen`, `Outros`).
   - Distribuição de `utm.source` (deve casar com `facebook-ads`/`instagram`/etc após sinônimos).
   - Distribuição final de decil — se vier concentrada em 1 só valor, é sinal de colapso por encoding pra "outros".

   Se vier tudo em `Outros`, é a quebra histórica chamada **Cluster 5** (categoria UTM nova fora da whitelist do modelo degradando sinal sem barulho). É a frente que estava chamada "I6" no protocolo SQL/Railway antigo. Não bloqueia ligar (já está ligado em modo "QA + orgânico vai pra skipped"), mas bloqueia confiar no decil dos leads pagos do sistema novo.

3. **Refator do monitoramento** — ver §7.

## 7. Plano de monitoramento — revisão pós-Pub/Sub

A virada de arquitetura aposentou o protocolo "B1–B4" que estava na versão anterior deste doc (bloqueios duros de monitoramento que eram pré-requisito do go-live SQL). O que entra no lugar é um **plano de refator do monitoramento existente** baseado em mapeamento completo do que existe hoje. A discussão "criar módulo separado pra preservar o caminho SQL" foi reconsiderada — as tabelas antigas (`Lead`/`leads_capi`) estão mortas e não há cliente futuro com pipeline SQL direto a preservar; melhor refatorar in-place substituindo as queries.

### Mapa completo (26 itens)

| # | Item | Arquivo:linha | Sinal/propósito | Fonte que lê | Estado fonte | Útil hoje? | Adaptação |
|---|---|---|---|---|---|---|---|
| **Critical alerts** — DM pessoal, a cada 5 min via `/railway/process-pending` |
| 1 | `rule_no_leads_arriving` | critical_alerts.py:283 | lead novo não chega há X min | `lead_surveys` | ✓ viva | ✓ | **Manter** |
| 2 | `rule_capi_success_low` | critical_alerts.py:315 | taxa CAPI sucesso<X em 60min | `Lead` | ✗ morta | ✓ | **Adaptar** → `registros_ml.base_status='sent'/'error'` |
| 3 | `rule_variant_no_capi` | critical_alerts.py:341 | variante A/B sem evento CAPI | `Lead` | ✗ morta | ✓ | **Adaptar** → `registros_ml.variant + base_meta_event_id` |
| 4 | `rule_fbp_fbc_low` | critical_alerts.py:370 | fbp/fbc fill rate baixo | `Lead × leads_capi` | ✗ ambas mortas | parcial | **Remover** (redundante com R3 nova `skipped_missing_data`) |
| 5 | `rule_utm_source_missing` | critical_alerts.py:399 | utm_source vazio/lixo | `Lead` | ✗ morta | ✓ | **Adaptar** → `registros_ml.utm_source` (após P17) |
| 6 | `rule_polling_500` | critical_alerts.py:432 | endpoint polling deu erro 500 | state store GCS | ✓ ok | ✓ | **Manter** |
| 7 | `rule_score_drift` | critical_alerts.py:456 | desvio de score/decil | `Lead.leadScore/decil` | ✗ morta | ✓ | **Adaptar** → `registros_ml.lead_score/decil` |
| **Daily check orchestrator** — output: Slack canal cliente + Slack DM pessoal via `slack-digest` |
| 8 | `MonitoringOrchestrator` | orchestrator.py:88 | agrega monitors abaixo | `Lead`, `leads_capi` | ✗ mortas | ✓ | **Adaptar fontes** dos monitors filhos (9/10/11) |
| 9 | `CAPIQualityMonitor` | capi_monitor.py:18 | fbp/fbc missing + rejection rate | `leads_capi` | ✗ morta | ✓ | **Adaptar** → `registros_ml.skipped_missing_data` + `.base_status='error'` |
| 10 | `OperationalMonitor` | operational_monitor.py:15 | timestamp do inflow | `leads_capi` | ✗ morta | ✓ | **Adaptar** → `registros_ml.created_at` ou `lead_surveys.submittedAt` |
| 11 | `DataQualityMonitor` | data_quality.py:573 | drift de categorias vs baseline | `Lead` + artefatos do modelo | ✗ morta | ✓ | **Adaptar** → features de `lead_surveys` + `UTMTracking` ou log `[FV_JSON]` |
| **Slack digest** — 2 canais |
| 12 | `render_slack_blocks` (DM) | digest.py:793 | view completa — severity, alertas, funil, lead quality, revenue | DailyCheckResponse | indireto | ✓ | **Adapta sozinha** quando 8–11 adaptarem |
| 13 | `render_slack_blocks_client` (cliente) | digest.py:812 | view enxuta — A/B, drift por variante, decis | DailyCheckResponse | indireto | ✓ | Idem |
| 14 | Seção "📨 Pub/Sub 24h" | digest.py (a criar) | counts por status + decil + top erros | `registros_ml` | ✓ viva | ✓ | **Criar nova seção** |
| **Endpoints HTTP** |
| 15 | `/monitoring/feature-report` | app.py:2159 | distribuição de features observadas | Cloud Logging `[FV_JSON]` | ✓ ok (consumer Pub/Sub emite) | ✓ | **Manter** |
| 16 | `/monitoring/daily-check` | app.py:2317 | wrapper que delega pro railway | — | indireto | ✓ | Idem 8–11 |
| 17 | `/monitoring/daily-check/railway` | app.py:2348 | endpoint que invoca orchestrator | `Lead`, `leads_capi` | ✗ mortas | ✓ | Idem 8–11 |
| 18 | `/monitoring/slack-digest` | app.py:3461 | postar digest no Slack | invoca 16 | indireto | ✓ | Adapta sozinho |
| 19 | `/monitoring/utm-quality` | app.py:3560 | ranking de UTMs por decil | `Lead × leads_capi` | ✗ ambas mortas | ✓ | **Adaptar** → `registros_ml` (após P17) |
| 20 | `/smoke/run-variants` | app.py:3621 | smoke pré-deploy do A/B | `Lead WHERE pesquisa IS NOT NULL` | ✗ morta | ✓ | **Adaptar** → `lead_surveys` |
| 21 | `/validation/test` | app.py:3906 | health check de imports/Cloud Storage | — | sem DB | ✓ | **Manter** |
| 22 | `/validation/weekly` | app.py:3978 | report semanal Excel + Slack | `Lead`, `leads_capi`, Guru, Meta | parcial morta | ✓ | **Adaptar parcial** (Lead/leads_capi → `registros_ml`+`lead_surveys`; Guru/Meta seguem) |
| **Auxiliares (mantém)** |
| 23 | `ValidationSlackNotifier` | validation/slack_notifier.py:14 | notifica /validation/weekly | sem DB | ✓ | ✓ | **Manter** |
| 24 | `post_to_slack` | utm_quality.py:459 | helper genérico de POST Slack | sem DB | ✓ | ✓ | **Manter, reutilizar** |
| 25 | `GcsStateStore` | critical_alerts.py:82 | dedup de alertas via GCS | GCS | ✓ | ✓ | **Manter, reutilizar** |
| 26 | `payload_schema` | payload_schema.py | audita chaves do payload | DailyCheckResponse | indireto | ✓ | **Estender** com colunas de `registros_ml` |

**Legenda:** **Manter** = nada a fazer; **Adaptar** = mudar a query da fonte morta pra fonte viva equivalente, lógica fica; **Remover** = sinal redundante; **Criar** = item novo.

### 3 regras novas a criar

São parte do item 14 (seção do digest) + adicionadas ao `critical_alerts.py` como regras paralelas às existentes:

- **R1 — Consumer Pub/Sub parado**: `PUBSUB_CAPI_ENABLED=true` e zero linhas novas em `registros_ml` nos últimos 60 min → DM pessoal.
- **R2 — Taxa de erro alta**: `count(base_status='error') / count(*) > 10%` nas últimas 24h → DM pessoal.
- **R3 — Skipped_missing_data alto**: entre Meta-elegíveis, `count(skipped_missing_data) / total > 30%` nas últimas 24h → DM pessoal. Sinal de que o dono parou de mandar `fbp`/`fbc`/`hasComputer`.

### Resumo numérico

- **Manter** sem tocar: 8 itens (1, 6, 12, 13, 15, 21, 23–25).
- **Adaptar** (queries mudam, lógica fica): 13 itens (2, 3, 5, 7, 8, 9, 10, 11, 17, 19, 20, 22, 26).
- **Remover**: 1 item (4).
- **Criar do zero**: 4 itens (R1, R2, R3 + seção 14 do digest).

## 8. Riscos e mitigações

| Risco | Mitigação atual |
|---|---|
| Dono envia slug fora do vocabulário declarado | Fail-loud em `traduzir_survey_slugs` → lead vira `base_status='error'` no ledger, R2 dispara DM se acumular |
| Dono envia payload mal-formado (JSON inválido, eventId vazio) | Parser exception → log ERROR + ledger error + ack (não recicla) |
| UTM nova fora da whitelist do modelo cai em "outros" calado (Cluster 5 histórico) | Verificação UTM pré-go-live (§6 item 2) + monitoramento de distribuição de decil (§7 seção do digest) |
| Consumer Pub/Sub para de processar (bug, deploy ruim, IAM revogado) | R1 (consumer parado) DM em 60 min |
| Distribuição de decil colapsa (sinal de feature ruim) | R3 (skipped_missing_data alto) + seção do digest com distribuição de decil + Gate C.1/C.2 no próximo deploy |
| Re-disparo de conversões velhas pro Meta | `event_id` Meta = `qualified_<UUID v7 estável>`, Meta deduplica + nosso ledger deduplica via `ON CONFLICT DO NOTHING` |
| Falha no consumer derruba o fluxo `Lead` | Endpoints separados: `/pubsub/process-pending` é independente do `/railway/process-pending` |
| Trabalho descartado por mudança de planos do dono | Risco realizado em 2026-05-22 (descartamos a abordagem SQL/Railway). Mitigação ex-ante: arquitetura Pub/Sub é mais defensiva (fronteira contratual clara) |

## 9. Histórico de medições e marcos (rastreabilidade)

- **2026-05-12** — Captação migra da `Lead` (front Prisma) para `lead_surveys` (sistema novo do dono) sem aviso.
- **2026-05-16** (728 linhas analisadas): fbp+fbc 98%; `computador` via `n8n_onboarding` 90%.
- **2026-05-17 20:30** (1.117 linhas): fbp+fbc 97%; `computador` n8n-só 91,3%; `computador` n8n **ou** activecampaign(144) **100%**.
- **2026-05-17** — Validação de proveniência do campo 144 do activecampaign == `tem_computador`: 1.011/1.011, zero divergência.
- **2026-05-17 → 19/05** — Implementação dos itens I0–I4 (design SQL/Railway). Código concluído, testado offline, commitado. Pausado antes do deploy canary.
- **2026-05-18** (300 leads, escopo Meta-elegível): utm 96%; `computador` 100%; fbp+fbc entre Meta-elegíveis **100%**; enviáveis 242/242.
- **2026-05-18** — Auditoria de tabelas: `Lead` morta desde 17/05 00:35 BRT; `leads_capi` morta desde 17/05 18:29 BRT; vivas: `lead_surveys`/`UTMTracking`/`integration_logs`/`Client`.
- **2026-05-19** — Colunas limpas no `Client` (respondentes de pesquisa 7d, n=1.588): `hasComputer` 100%; `eventId` 100%; `fbp` 99,9%; `fbc` 92,8% (99,9% entre Meta-elegíveis fb/ig); `lead_surveys`↔`Client` por email ~100%.
- **2026-05-19** — Consolidação 1 do doc via `/docs`. Frente pausada antes do deploy canary do I4.
- **2026-05-22** — Decisão de virar arquitetura pra Pub/Sub combinada com o dono. Tópico/sub/SA provisionados.
- **2026-05-23** — Implementação do consumer Pub/Sub + DDL do ledger migrada (PK `lead_id`→`event_id`) + testes (26/26) + merge feat→main + fix Gate C.1 + deploy canary + gates B/D/C.1/C.2 passados + promoção a 100% + IAM concedido + Cloud Scheduler criado + `PUBSUB_CAPI_ENABLED=true`. Smoke real às 19:45 BRT: 25 mensagens processadas, 0 enviadas ao Meta.
- **2026-05-24** — Purga do backlog do load test (744 msgs) via `seek`. Consolidação 2 do doc via `/docs` — reflete arquitetura Pub/Sub LIVE e plano de monitoramento revisto.

---

*Artefatos vivos (caminho Pub/Sub):* [api/pubsub_branch.py](../api/pubsub_branch.py), [api/railway_mapping.py](../api/railway_mapping.py) (mapa slug→PT), [api/survey_mapping.py](../api/survey_mapping.py) (reaproveitado do I2), [scripts/create_registros_ml.py](../scripts/create_registros_ml.py), [api/app.py](../api/app.py) (endpoint `/pubsub/process-pending`), testes em `tests/test_traduzir_survey_slugs.py` e `tests/test_pubsub_branch.py`.

*Artefatos deprecados (caminho SQL/Railway, mantidos por histórico):* [api/survey_branch.py](../api/survey_branch.py), [api/survey_enrichment.py](../api/survey_enrichment.py) (ambos com header `[DEPRECATED 2026-05-23]`).

*Reuso canônico (compartilhado com o fluxo `Lead` antigo):* `pipeline.run`, `pipeline.get_ab_variant`, `pipeline.get_variant_predictor`, `atribuir_decil_por_threshold`, `send_batch_events`.

*Tabelas Railway:* `registros_ml` (ledger nosso, viva); `lead_surveys`, `UTMTracking`, `Client` (vivas, do sistema novo); `Lead`, `leads_capi` (mortas desde 17/05).

*Infra GCP:* projeto `smart-ads-451319`; tópico `lead-capture-ingest`; sub `lead-capture-ingest-sub`; SA publisher `lead-capture-publisher@…`; SA consumer (Cloud Run default) `smart-ads-451319@appspot…`.

*Contrato cliente:* [REQUISITOS_SISTEMA_NOVO.md](REQUISITOS_SISTEMA_NOVO.md) + [propostas_e_apresentacoes/requisitos_sistema_novo.pdf](../propostas_e_apresentacoes/requisitos_sistema_novo.pdf) + [propostas_e_apresentacoes/requisitos_sistema_novo_payload.json](../propostas_e_apresentacoes/requisitos_sistema_novo_payload.json).

*Classe de quebra histórica relevante:* "Cluster 5" / "cenário 1.2" em [AUDITORIA_QUEBRA_PRODUCAO.md](AUDITORIA_QUEBRA_PRODUCAO.md) e [registro_erros_ml.md](registro_erros_ml.md).

*Identificadores históricos (rodapé):* itens **I0–I7** do protocolo SQL/Railway; itens **P1–P18** do protocolo Pub/Sub atual.
