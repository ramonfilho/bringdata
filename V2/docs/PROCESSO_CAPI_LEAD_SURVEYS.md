# Disparar o evento scoreado por ML também para quem responde a pesquisa pela esteira nova

**Criado:** 2026-05-17 · **Atualizado:** 2026-05-19 · **Papel:** especificação e diário desta frente — fazer o evento CAPI scoreado por ML (`LeadQualified`/`LeadQualifiedHighQuality`, com valor por decil) ser disparado também a partir da tabela `lead_surveys`, sem tocar no fluxo `Lead`.

> Linguagem natural primeiro (regra do `CLAUDE.md`). Nomes de tabela/código aparecem no corpo porque o doc é técnico-operacional; o rodapé lista os artefatos. Datas absolutas. Documento consolidado em 2026-05-19 via skill `/docs` — versões anteriores ficam no histórico git (`PROCESSO_CAPI_LEAD_SURVEYS.md` no `main`).

---

## ⏸️ ESTADO ATUAL — 2026-05-19 (PAUSADO a pedido do usuário)

**Onde estamos:** código dos itens **I0–I4 concluído, testado offline e commitado** no branch/worktree isolado `feat/capi-lead-surveys-scoring`. Trabalho **pausado pelo usuário antes do deploy canary do I4**.

**Produção: intocada.** Não há revisão canary; `SURVEY_CAPI_ENABLED` está off (default); o fluxo `Lead` é byte-idêntico ao de antes; os schedulers `slack-digest-daily` e `railway-polling` seguem **PAUSADOS**. Nenhum evento foi ao Meta por esta frente.

**O que falta para ligar (na ordem):**
1. Fechar o I4 — rodar `deploy_capi.sh` (gates B/D/C.1/C.2 + revisão canary com 0% de tráfego) e validar o ramo em **dry-run** na URL da canary.
2. **I5** — extensão de monitoramento (bloqueios duros B1–B4 do §7) + o alarme rolling sobre o ledger `registros_ml`.
3. **I6** — verificar a whitelist/encoding de UTM dos survey leads (a classe de quebra histórica "Cluster 5" — categoria de UTM nova fora da whitelist degradando o sinal calado).
4. **I7** — ligar (`SURVEY_CAPI_ENABLED=true`), promover tráfego, religar schedulers (com as dependências do §5/I7).

**Nota de prazo:** o dono da empresa anunciou (17/05) que vai reconstruir tudo do zero — banco e estrutura novos — previsto para "semana que vem". O valor desta frente é interino (~poucos dias de sinal scoreado até a virada). Ao retomar, pesar go-live interino vs. mirar direto a estrutura nova.

**Reconciliação com sessões paralelas (o usuário roda vários terminais):**
- O **monitoramento/`critical_alerts`** pertence a **outro terminal**, não a esta frente. Esse terminal já commitou no `main` o repoint do `critical_alerts` para `lead_surveys` (commits `52b507d`+`642ffa4`, 17/05) — mas a revisão Cloud Run servindo 100% (`smart-ads-api-00487-nid`, build 16/05 14:03 BRT) **não inclui** esse fix. Por isso os schedulers **continuam pausados**: religar `railway-polling` agora reintroduz o ruído falso do `critical_alerts` antigo. Levantar a pausa só é seguro depois que uma revisão contendo `642ffa4` for promovida — **ação do terminal de monitoramento**.
- Esta frente = **scoring/CAPI → `lead_surveys`**, isolada no worktree próprio.
- O terminal de monitoramento também investiga "gate trava por UTM vazia/quebrada" (commit `51951ee` no `main`, 18/05) — **intersecta o I6**; revisar em conjunto ao retomar.

---

## 1. O quê e por quê

**O quê:** o job que scoreia leads e dispara o evento de qualidade ao Meta lê de **uma** tabela (`Lead`). Esta frente faz o **mesmo** job ler **também** da `lead_surveys` (a esteira nova de captação), mantendo o fluxo `Lead` exatamente como está.

**Por quê (o que forçou a frente):** a captação de produção **migrou** da `Lead` para a `lead_surveys` por volta de 12/05/2026. Medições de 17–18/05: a `Lead` ficou com **0 entradas** desde 17/05 00:35 BRT e a `leads_capi` desde 17/05 18:29 BRT — ambas mortas. As únicas tabelas vivas recebendo dado são `lead_surveys` (~380/dia), `UTMTracking`, `integration_logs`, `Client`. Como nosso pipeline só lê `Lead`, **o sinal CAPI scoreado por ML está OFF para toda a captação viva** desde a migração. Esta frente restaura esse sinal.

> O sinal scoreado já estava efetivamente desligado **desde a migração** — a pausa dos schedulers só silencia alarme falso de monitoramento; não foi ela que desligou o CAPI.

## 2. O que a investigação encontrou (16–18/05)

**Duas esteiras quase disjuntas.** `Lead` (funil antigo, front via Prisma) vs `lead_surveys` (sistema novo desde 12/05). Em 7 dias só ~2% de sobreposição de email (13 de ~720). É população nova, invisível ao nosso scoring/CAPI — não dá para "fazer lookup" na `Lead`.

**A esteira nova já manda evento próprio pro Meta, mas genérico.** O `integration_logs` mostra a stack do front (n8n) enviando `meta_capi/Lead` e `meta_capi/CompleteRegistration` (~1.765/7d) — bem casados (email/telefone/fbp/fbc). O que **nunca** vai para esses leads é o **nosso** evento scoreado (`LeadQualified` com valor por decil). O gap é o sinal de qualidade, não a existência de evento. Nomes de evento distintos ⇒ o Meta não deduplica automaticamente; somar o nosso é decisão consciente, não duplicata.

**A `lead_surveys` não tem tudo que o scorer/CAPI precisam — mas dá para recuperar.** Schema: `id, clientEmail, genero, idade, ocupacao, faixaSalarial, cartaoCredito, estudouProgramacao, faculdade, investiuCurso, atracaoProfissao, interesseEvento, eventId, ip, submittedAt`. Falta: `computador` (feature principal do modelo), UTM, fbp/fbc, telefone, nome. Recuperação por email/eventId em tabelas do mesmo Railway:

| Campo | Fonte de recuperação | Cobertura final medida |
|---|---|---|
| Respostas de pesquisa (10 campos) | colunas da própria `lead_surveys` | 100% |
| `computador` | `integration_logs`: `n8n_onboarding.tem_computador` **ou** `activecampaign` campo 144 | **≈100%** combinado |
| UTM (source/medium/campaign/content/term + url) | `UTMTracking` por email (linha mais recente ≤ `submittedAt`) | ~98% |
| fbp/fbc/ip/user_agent | `integration_logs` `meta_capi`: JOIN preciso por `eventId` (1:1) com fallback email | ~98% (e **100% entre os Meta-elegíveis**) |
| telefone/nome | `integration_logs` `n8n_onboarding` por email | ~90% |

**Pontos validados (read-only contra o Railway):**
- **`computador`**: o campo 144 do `activecampaign` **é** o `computador` — onde há as duas fontes (1.011 leads), bate com `n8n_onboarding.tem_computador` em **1.011/1.011, zero divergência**, domínio `{SIM,NAO}`. Combinando as duas fontes, cobertura ≈100%.
- **fbp/fbc**: medido só entre **Meta-elegíveis** (`source` ∈ facebook-ads/fb/ig) dá **100%** (242/242 numa amostra de 300). O "buraco" aparente é google-ads (não tem `fbc` por natureza) — mas google-ads **já é bloqueado pela allowlist** no envio ao Meta, então não é perda de sinal.
- **Vocabulário das respostas: 100% seguro.** Cada valor de `lead_surveys`, após a normalização que já roda em produção (`_normalizar` + mapas em `api/railway_mapping.py`), cai só em categorias que o funil `Lead` já produz. Zero categoria nova.
- **`computador` no `Lead` é ~100%** (3.812/3.812 em 7d) — o modelo nunca rodou sem essa feature; por isso a regra dura de não enviar sem ela. Com a recuperação combinada ≈100%, o limitante real de envio passa a ser fbp/fbc (~poucos % de skip), não `computador`.

## 3. Decisões (datas absolutas)

| # | Decisão | Quando |
|---|---|---|
| 1 | **Implementar já**, recuperando `computador`/fbp/fbc de `integration_logs` (≈100%/~98%) — **não esperar** uma coluna limpa. Pedir colunas limpas (`computador`/fbp/fbc/telefone/nome) ao front segue **em paralelo**, como durabilidade (remove a fragilidade do parse de log), não como bloqueio. | 17/05 |
| 2 | **`leads_capi` só como fallback** (e hoje está morta de qualquer forma). | 17/05 |
| 3 | **Recuperação de 24h + forward**: ao ligar, processar `lead_surveys` com `submittedAt` nas últimas 24h e dali pra frente (cutoff = enable − 24h); dedup pelo ledger; **não** re-disparar nada mais antigo que 24h (conversão velha suja a otimização; até ~24h o Meta aceita p/ atribuição). | 18/05 (revisou "forward-only puro") |
| 4 | **Extensão de monitoramento entra junto** (não vira follow-up). | 17/05 |
| 5 | **Ledger próprio `registros_ml`** para dedup/registro — não escreve na tabela do front, não polui `leads_capi`. | 17/05 |
| 6 | **Fluxo `Lead` intocado**; ramo `lead_surveys` roda **isolado** (try/except próprio), nunca derruba o `Lead`. | 17/05 |
| 7 | **Fail-loud**: cobertura caindo → alerta; categoria desconhecida → falha alto; batch zerado → assert. | 17/05 |
| 8 | **Restrições duras**: lead sem `computador` **ou** sem fbp/fbc → **não dispara**, registra skip no ledger. | 17/05 |

## 4. Como foi feito — protocolo por item

Cada item é um ciclo fechado: implementa → testa → commita → (deploy canary 0% → valida → promove, com OK explícito). Nada começa sem autorização por item. Tudo no worktree isolado `feat/capi-lead-surveys-scoring` (criado de `main@642ffa4`, que já contém o fix de `critical_alerts` da sessão paralela).

| Item | O que é | Status |
|---|---|---|
| **I0** | Decisão de fonte + registro da frente no roadmap (`PLANO_EXECUCAO.md`) | ✅ 17/05 |
| **I1** | Tabela-ledger `registros_ml` — script idempotente `scripts/create_registros_ml.py`; aplicado/testado no Railway (12 colunas, PK `lead_id`, idempotência + PK-conflict + smoke OK; renomeada de `survey_capi_sent` a pedido do usuário) | ✅ commits `9b57c0d`+`31d1151` |
| **I2** | Adaptador `api/survey_mapping.py` — função **pura** que monta dict formato-`Lead` e delega à canônica `railway_lead_to_sheets_row` (zero normalização reimplementada; equivalência por construção). `tests/test_survey_mapping.py` 5/5 | ✅ commit `2a802db` |
| **I3** | Enriquecimento `api/survey_enrichment.py` — lote **read-only**; por lead `utm`+`enrich`+flag `meta_eligible`; fbp/fbc por `eventId` preciso com fallback email; `computador` n8n→ac144. Cobertura fbp/fbc medida só entre Meta-elegíveis. `tests/test_survey_enrichment.py` 7/7; integração read-only 300 leads (242/242 enviáveis). Alarme sistêmico **migrado para o I5** (rolling sobre o ledger; lotes do polling são pequenos, guard per-batch cegaria) | ✅ commit `160562c` |
| **I4** | Ramo isolado `api/survey_branch.py` + hook mínimo no `api/app.py` (`+18` linhas; helper `_run_survey_branch_safely` gated por `SURVEY_CAPI_ENABLED`, chamado nos 2 returns, nunca propaga, `Lead` byte-idêntico). Lê 24h+forward, dedup ledger, classifica (allowlist/missing_data/send), mapa I2, **mesmo** `pipeline.run`/A-B/`send_batch_events` do `Lead`, `event_id` namespaced `survey_<id>`, grava no `registros_ml`. `dry_run` não chama Meta nem grava ledger. `tests/test_survey_branch.py` 7/7 + regressão I2/I3 | 🟡 **código ✅ commit `d2587f0`**; **validação canary PENDENTE** (pausado 19/05) |
| **I5** | Extensão de monitoramento — bloqueios duros B1–B4 (§7) **antes de religar o digest** + o **fail-loud sistêmico rolling** sobre `registros_ml` (janela no tempo; entre Meta-elegíveis, se `skipped_missing_data` acima do limiar e volume da janela ≥ N → alarme; imune a tamanho de lote) | ⏳ pendente |
| **I6** | Verificações pré-go-live: vocabulário de `computador`; **whitelist/encoding de UTM dos survey leads** (classe de quebra "Cluster 5" — categoria UTM nova fora da whitelist degradando sinal calado). Intersecta investigação paralela `51951ee` | ⏳ pendente |
| **I7** | Ligar (`SURVEY_CAPI_ENABLED=true`) + promover tráfego + religar schedulers. Religar `railway-polling` depende do fix de `critical_alerts` paralelo ser deployado; religar `slack-digest-daily` depende do I5 | ⏳ pendente |

## 5. Desenho técnico (implementado em I1–I4)

1. **Ledger `registros_ml`** (nosso): `lead_id` PK (= `lead_surveys.id`), `email`, `variant`, `lead_score`, `decil`, `base_meta_event_id`/`base_status`, `hq_meta_event_id`/`hq_status` (HQ NULL se decil<9), `capi_sent_at`, `error_message`, `created_at`. Dedup por `lead_id`; fonte de leitura do monitoramento.
2. **Ramo isolado** dentro de `/railway/process-pending`, depois do batch do `Lead`, em try/except próprio que nunca propaga. Gated por `SURVEY_CAPI_ENABLED` (default off) — **deploy ≠ ligar**. Roda nos dois pontos de return do endpoint (hoje, com `Lead` morto, o endpoint cai no early-return "nenhum lead pendente").
3. **Seleção:** `lead_surveys` sem registro no ledger, `submittedAt >= NOW() - 24h`, ordem `submittedAt ASC`, batch próprio `SURVEY_CAPI_BATCH=25` (independente do batch do `Lead`).
4. **Enriquecimento (I3):** UTM via `UTMTracking`; fbp/fbc/ip/ua via `meta_capi` (eventId preciso → fallback email); `computador` n8n→ac144; telefone/nome via `n8n_onboarding`.
5. **Classificação por lead:** não Meta-elegível (google-ads/sem-utm) → `skipped_allowlist`; Meta-elegível sem `computador`/fbp/fbc → `skipped_missing_data`; senão → scoreia e envia.
6. **Scoring/CAPI por reuso total:** mapa I2 → **mesmo** `pipeline.run()` + **mesmo** roteamento A/B (`get_ab_variant`/`match_variant`) + **mesmo** `send_batch_events` do `Lead` (nada de scoring/CAPI reimplementado → Gate C.1/C.2 trivial). `event_id` determinístico `survey_<id>` → `send_batch_events` prefixa `qualified_`/`hq_` → `qualified_survey_<id>`/`hq_survey_<id>` (dedup Meta independente do `Lead` e do `survey_…` da própria Pipeline B). Variante/pixel pela mesma regra: Champion → `LeadQualified` (+`LeadQualifiedHighQuality` se decil 9–10), pixel original; Challenger → `HQLB_LQ` (+`HQLB` se 9–10), pixel `1513…`.
7. **Registro:** todo desfecho (sent/skipped) gravado em `registros_ml` → o polling de 5min não reprocessa.
8. **Validação (fecha o I4, pendente):** gates B/D/C.1/C.2 + canary `NO_TRAFFIC` (0% tráfego) + dry-run na URL da canary conferindo decis, payloads (PII hash, fbp/fbc, nomes de evento por variante, `event_id` namespaced), categorias de skip, e que o ledger gravaria certo. Zero evento real, zero tráfego.

## 6. Pendências obrigatórias antes do go-live

1. **Whitelist/encoding de UTM dos survey leads** — UTM vem do `UTMTracking` e é codificada pela whitelist de UTM do modelo (não pelos mapas de pesquisa, que já estão 100% seguros). Categoria de UTM nova fora da whitelist degrada o sinal calado — é a classe de quebra histórica do projeto. Verificar em dry-run no canary antes de ligar. (Intersecta `51951ee` da sessão paralela.)
2. **Vocabulário de `computador`** — se/quando a coluna limpa chegar do front, repetir a verificação de vocabulário sobre ela.
3. **Recomendado (durabilidade):** pedir ao front `computador`/fbp/fbc/telefone/nome como colunas limpas em `lead_surveys`. Hoje vêm de parse de JSON de log; se o front mudar o formato, o parse quebra — mitigado pelo fail-loud, mas a coluna limpa elimina a fragilidade. Rastrear em `docs/instrucoes_dev_frontend_capi.md`.

## 7. Estudo: extensão de monitoramento (I5)

Hoje **todo** o monitoramento lê só `Lead` (e `leads_capi` por JOIN); nenhuma parte lê `lead_surveys`/`UTMTracking`/`integration_logs`/`registros_ml` — **exceção**: a regra crítica "não chega lead" (Regra 4) já lê `lead_surveys.submittedAt` desde 12/05, e não muda. A fonte viva do digest é o **Railway** (`Lead`/`leads_capi` via pg8000) — código `gspread` remanescente é legado inerte.

**Bloqueio duro (sem isto, ligar quebra o monitoramento ou gera falso positivo constante):**
- **B1 — Schema do payload:** o auditor (`payload_schema.py`/`digest.py`) falha alto em qualquer chave nova não declarada → toda seção/breakdown de pesquisa precisa ser pré-declarado antes de ligar.
- **B2 — Baseline do detector de desvio:** a regra de desvio de score/decil compara contra baseline de 30d só do `Lead`; ao ligar, a janela mistura survey leads e o baseline fica defasado → falso positivo até incorporar a fonte.
- **B3 — Regra "CAPI com sucesso baixo":** olha só `Lead.capiSentAt`; precisa enxergar `registros_ml`, senão falha de envio da esteira nova fica muda.
- **B4 — Ledger como fonte:** o `registros_ml` precisa registrar score/decil/status/envio por lead — é dele que o monitoramento lê.

**Reconciliação de números (sem isto, o relatório fica sem sentido, mas não quebra):** funil unificado, contadores 24h e qualidade/decil por período leem só `Lead` → sem breakdown por fonte os ratios quebram e a qualidade aparenta degradar conforme o ledger cresce.

**Cobertura de detecção (sem isto, problema na esteira nova passa despercebido):** alerta novo de saúde da esteira (ingest parou / scoreado preso sem CAPI); o **fail-loud rolling** sobre `registros_ml` (migrado do I3); regras "scoreado sem CAPI"/"FBP-FBC baixo" e detectores de deriva/ranking de UTM hoje cegos à coorte de pesquisa.

Escopo acordado (17/05): todos esses pontos entram; a profundidade de cada um é decidida 1 a 1 na implementação do I5.

## 8. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Parse de payload de log quebra calado se o front mudar formato | Fail-loud de cobertura (I3/I5) + pedir colunas limpas (§6.3) |
| UTM nova fora da whitelist degrada sinal calado (quebra histórica "Cluster 5") | Verificação obrigatória I6 antes do go-live |
| Re-disparo de conversões velhas pro Meta | Janela de recuperação de 24h + dedup pelo ledger (§3.3) |
| Falha no ramo survey derruba o fluxo `Lead` | Isolamento try/except + `SURVEY_CAPI_ENABLED` off por default |
| Percepção de "double count" no Meta | Nomes de evento distintos do `Lead` e da Pipeline B; decisão consciente |
| Religar `railway-polling` reintroduz ruído do `critical_alerts` antigo | Pausa mantida até o fix paralelo (`642ffa4`) ser promovido — ação do terminal de monitoramento |
| Trabalho descartado pela estrutura nova do dono | Decisão consciente do usuário (valor interino); reavaliar ao retomar |

## 9. Histórico de medições (rastreabilidade)

- **16/05** (728 linhas): fbp+fbc 98% · `computador` via `n8n_onboarding` 90%.
- **17/05 20:30** (1.117 linhas): fbp+fbc 97% · `computador` n8n-só 91,3% · `computador` n8n **ou** activecampaign(144) **100%**.
- **17/05** validação proveniência campo 144 == `tem_computador`: **1.011/1.011, zero divergência**.
- **18/05** (300 leads, com escopo Meta-elegível): utm 96% · `computador` 100% · fbp+fbc entre Meta-elegíveis **100%** · enviáveis **242/242**.
- **18/05** auditoria de tabelas: `Lead` morta desde 17/05 00:35; `leads_capi` morta desde 17/05 18:29; vivas: `lead_surveys`/`UTMTracking`/`integration_logs`/`Client`.

---

*Artefatos:* branch `feat/capi-lead-surveys-scoring` — `scripts/create_registros_ml.py` (I1), `api/survey_mapping.py` (I2), `api/survey_enrichment.py` (I3), `api/survey_branch.py` + hook em `api/app.py` (I4), testes em `tests/test_survey_*.py`. Commits: I1 `9b57c0d`/`31d1151`, I2 `2a802db`, I3 `160562c`, I4 `d2587f0`. Tabelas Railway: `lead_surveys`, `UTMTracking`, `integration_logs`, `registros_ml`, `Lead`, `leads_capi`. Reuso canônico: `api/railway_mapping.py`, `pipeline.run`, `send_batch_events`. Classe de quebra histórica: "Cluster 5" / "cenário 1.2" em `docs/AUDITORIA_QUEBRA_PRODUCAO.md`. Roadmap: `docs/PLANO_EXECUCAO.md` ("Frente ativa urgente"). Front: `docs/instrucoes_dev_frontend_capi.md`. Reconciliação com monitoramento (outro terminal): commits `52b507d`/`642ffa4`/`51951ee` no `main`.
