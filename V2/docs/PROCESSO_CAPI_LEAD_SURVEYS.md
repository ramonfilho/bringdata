# Disparar o evento scoreado também para quem responde a pesquisa pela esteira nova

**Criado:** 2026-05-17
**Status:** investigação concluída · desenho fechado · decisão de fonte **resolvida** (§6) · **I0–I4 (código) concluídos e commitados** no branch `feat/capi-lead-surveys-scoring` · ⏸️ **PAUSADO em 2026-05-19 a pedido do usuário, ANTES do deploy canary do I4** · **nada em produção** (`SURVEY_CAPI_ENABLED` off, sem revisão canary, schedulers pausados) · falta: validação canary (fecha I4) + I5–I7
**Papel:** especificação completa do processo de fazer o evento CAPI scoreado por ML (`LeadQualified` + `LeadQualifiedHighQuality`) ser disparado a partir de **duas** tabelas — a `Lead` (como hoje) **e** a `lead_surveys` — sem tocar no fluxo da `Lead`.

> Linguagem natural primeiro (regra do `CLAUDE.md`). Identificadores de código e nomes de tabela aparecem no corpo porque o documento é técnico-operacional; o rodapé lista os artefatos.

> **⏸️ PAUSA — 2026-05-19:** trabalho **pausado a pedido do usuário antes do deploy canary do I4**. Onde paramos, exatamente:
> - **Código I0–I4 concluído e commitado** no worktree/branch `feat/capi-lead-surveys-scoring` (commits `9b57c0d`/`31d1151` I1, `2a802db` I2, `160562c` I3, `d2587f0` I4). Worktree limpo.
> - **Nada deployado, nada ligado:** sem revisão canary; `SURVEY_CAPI_ENABLED` off (default); fluxo `Lead` byte-idêntico; schedulers `slack-digest-daily`+`railway-polling` seguem **PAUSADOS**. Produção 100% na revisão atual, intocada.
> - **Próximo passo quando retomar:** rodar `deploy_capi.sh` (gates B/D/C.1/C.2 + canary `NO_TRAFFIC` 0%) e validar o ramo em dry-run na URL da canary → fecha o I4. Depois I5 (monitoramento + alarme rolling sobre `registros_ml`), I6 (whitelist UTM dos survey leads — classe "Cluster 5"), I7 (ligar+promover+religar schedulers, com dependências do §9).
> - **Contexto de prazo:** a estrutura nova do dono ("banco novo, tudo do zero") estava prevista pra "semana que vem" (declarado 17/05) — pesar valor do go-live interino vs. mirar direto a estrutura nova ao retomar.
> - Sessão paralela commitou no `main` `51951ee` (investigação "gate trava por UTM vazia/quebrada") — intersecta o I6; revisar ao retomar.
>
> **⚠️ ESTADO OPERACIONAL — 2026-05-17:** a captação de produção **migrou para `lead_surveys`** — `Lead` ficou com **0 entradas nas últimas 6h** (51 em 24h, última às 00:35 UTC). Como o monitoramento ainda lê `Lead`, ele produzia (a) digest das 6h vazio/errado pro canal do cliente `#team-dados` e (b) critical_alerts errado a cada 5min no privado. **Mitigação aplicada:** os dois Cloud Scheduler jobs foram **PAUSADOS** — `slack-digest-daily` (`0 6 * * *`) e `railway-polling` (`*/5`). Reverter com `gcloud scheduler jobs resume <job> --project=smart-ads-451319 --location=us-central1`.

> **Reconciliação com sessão paralela (17/05, ~12h BRT):** outro terminal já commitou na `main` o repoint do `critical_alerts` para `lead_surveys` (`52b507d` + `642ffa4`, 17/05 ~10:45–10:50 BRT) — alarme `no_leads_arriving` correto, demais regras auto-skip por amostra. **PORÉM** a revisão Cloud Run servindo 100% (`smart-ads-api-00487-nid`) foi buildada em **16/05 14:03 BRT**, ~20h antes desses commits → **o fix está commitado mas NÃO deployado**. Consequência: **manter os dois schedulers pausados**; religar `railway-polling` agora reintroduz o ruído falso (revisão viva roda o `critical_alerts` antigo com `CRITICAL_ALERTS_DRY_RUN=false`). A pausa só pode ser levantada com segurança após uma revisão contendo `642ffa4` ser promovida — **ação pertencente ao terminal de monitoramento**, não a esta frente. Divisão: monitoramento/`critical_alerts` = outro terminal; **scoring/CAPI → `lead_surveys` = esta frente**, isolada em worktree próprio. **Consequência:** enquanto `railway-polling` está pausado, nenhum lead novo é scoreado/enviado por CAPI por nenhuma esteira — mas o sinal scoreado para a inflow nova **já estava efetivamente desligado desde a migração** (nosso código nunca leu `lead_surveys`); a pausa só silencia o alarme falso, não muda a realidade do CAPI. Despausar só faz sentido depois que o código ler `lead_surveys` (a implementação bloqueada em §6) **ou** se a inflow voltar para `Lead`.

---

## 1. Objetivo

Hoje o job que scoreia leads e dispara o evento de qualidade pro Meta lê de **uma** tabela (`Lead`). Existe uma segunda esteira de captação que grava respostas de pesquisa numa tabela diferente (`lead_surveys`) — e esses leads **nunca recebem o nosso evento scoreado**. O objetivo é: o mesmo job passar a scorear e disparar o evento também para os leads da `lead_surveys`, mantendo o fluxo da `Lead` exatamente como está.

## 2. O que a investigação encontrou (2026-05-16/17)

### 2.1 São duas esteiras quase disjuntas

- `Lead` é o funil antigo (gravado pelo front via Prisma quando o lead completa a pesquisa). `lead_surveys` é um sistema separado, mais novo (ativo desde 12/05/2026).
- Sobreposição (janela de 7 dias): **720** emails distintos em `lead_surveys` vs **3.765** em `Lead`; **só 13** em comum. Por linha: das 725 linhas de `lead_surveys`, **15** têm linha correspondente em `Lead` (e todas as 15 já tinham CAPI disparado pelo fluxo normal).
- **Conclusão:** ~98% dos leads de pesquisa não existem na `Lead`. Não há de onde "fazer lookup". É população nova, invisível ao nosso scoring/CAPI hoje.

### 2.2 A esteira nova já dispara eventos próprios pro Meta (genéricos)

`integration_logs` (mesmo banco Railway) mostra, em 7 dias: `meta_capi/Lead` 1.039 sucessos, `meta_capi/CompleteRegistration` 726, `activecampaign/subscribe` 1.177, `n8n_onboarding/onboarding` 925. Ou seja: o Meta **já recebe eventos bem casados** desses leads — mas **genéricos** (`Lead`, `CompleteRegistration`), **nunca** o nosso `LeadQualified`/`LeadQualifiedHighQuality` com valor por decil. O gap é o sinal de qualidade scoreado, não a existência de evento.

> Nomes de evento distintos (nosso `LeadQualified`/`HighQuality` vs o `Lead`/`CompleteRegistration` deles) ⇒ o Meta **não** dedupica automaticamente; é uma decisão consciente adicionar o nosso sinal por cima, não uma duplicata literal.

### 2.3 O que falta na `lead_surveys` para scorear/disparar

Schema real: `id, clientEmail, genero, idade, ocupacao, faixaSalarial, cartaoCredito, estudouProgramacao, faculdade, investiuCurso, atracaoProfissao, interesseEvento, eventId, ip, submittedAt`.

| O scorer/CAPI usa | Em `Lead` | Em `lead_surveys` | Onde recuperar |
|---|---|---|---|
| Respostas de pesquisa (10 campos) | ✓ | ✓ | — |
| `computador` (feature **principal** do modelo) | ✓ ~100% | ✗ não existe | hoje só no log `n8n_onboarding` (`tem_computador`), ~90% |
| UTM (source/medium/campaign/content/term + url) — modelo + roteamento A/B + allowlist | ✓ | ✗ | `UTMTracking` por email (98% match, ~1,2 linha/email) |
| fbp / fbc / ip / user_agent (match quality Meta) | ✓ | só `ip` | payload `meta_capi` em `integration_logs`, ~98% |
| telefone / nome (match quality Meta) | ✓ | ✗ | payload `n8n_onboarding`, ~90% |
| dedup (`capiSentAt`) | ✓ coluna | ✗ | precisa de store próprio (ver §5) |

### 2.4 Cobertura de recuperação por JOIN (janela 7d)

Medição inicial (16/05, 728 linhas): fbp+fbc **98%** (711/728) · `computador` via `n8n_onboarding` **90%** (654/728) · telefone **90%** · ambos **89%**.

**Re-medição 17/05 20:30 (1117 linhas):** fbp+fbc **97,0%** (1083/1117) · `computador` só `n8n_onboarding` **91,3%** · `computador` só `activecampaign` (campo 144) **99,9%** (1107/1108) · `n8n_onboarding` **ou** `activecampaign` **100,0%** · fbp/fbc **e** `computador` (combinado) **97,0%**. Conclusão: com as duas fontes `computador` ≈100% (nesta janela); limitante de envio passa a ser **fbp/fbc ≈97%** → ~3% skip pela regra dura, não ~10%. Não é garantia estrutural — pedido da coluna limpa segue por durabilidade.

**Validação de proveniência do campo 144 (17/05):** onde o lead tem as duas fontes (1.011 leads), `activecampaign` campo 144 = `n8n_onboarding` `tem_computador` em **1.011/1.011 (100,00%, zero divergência)**; ambos domínio `{SIM,NAO}`. Evidência empírica forte de que campo 144 **é** o `computador` (as demais perguntas SIM/NAO da pesquisa são independentes — não dariam 100% de correlação). Ressalva: validação empírica, não a config de campos do ActiveCampaign do front — confirmar com quem mantém o front fecha a certeza.

### 2.5 `computador` no `Lead` é ~100% — o 90% da esteira nova é degradação real

Fill-rate de `Lead.pesquisa.computador`: 7d **100,0%** (3.812/3.812), 30d **99,95%**, 90d **99,96%**. Em 7d, leads com `computador` em branco = **0** — o modelo **nunca** rodou em produção sem essa feature. Logo, recuperar `computador` a 90% via log é degradação de ~10% contra o baseline que o modelo conhece — vetado pela regra dura do usuário ("não pode mandar evento sem ela"). **Atualização 17/05:** combinando `n8n_onboarding`+`activecampaign` (campo 144), `computador` recupera ≈100% nesta janela (§2.4 re-medição) — a degradação de ~10% deixa de se aplicar na prática; mantém-se o pedido da coluna limpa por durabilidade, mas o limitante real de envio passa a ser fbp/fbc (~3% skip).

O dado existe na origem (o front captura `computador` em ~100% no funil `Lead`); ele só **não é persistido na tabela `lead_surveys`**. Daí a decisão de pedir a coluna (ver §3).

### 2.6 Verificação de vocabulário das respostas — **100% seguro**

Cada valor distinto de `lead_surveys`, após a normalização que **já roda em produção** (`_normalizar` + mapas semânticos em `api/railway_mapping.py`), cai **somente** em categorias que o funil `Lead` já produz. Zero categoria nova. Os mapas (`MAPA_IDADE`, `MAPA_OCUPACAO`, `MAPA_FAIXA_SALARIAL`, `MAPA_INTERESSE_EVENTO`, `MAPA_ATRACAO_PROFISSAO`) já contêm exatamente as frases que `lead_surveys` usa. Campos sem mapa (`cartaoCredito`, `genero`, `estudouProgramacao`, `faculdade`, `investiuCurso`) produzem `sim/nao`/`Masculino/Feminino`/`Sim/Não`, idênticos ao `Lead`. Únicas exceções: 2 linhas com resposta vazia (1 `idade`, 1 `investiuCurso`) → NULL, não sistêmico.

## 3. Decisões do usuário (2026-05-17)

1. **Coluna `computador` solicitada ao front** para ser persistida em `lead_surveys` (não é coleta nova — o front comprovadamente já captura em ~100%; é só gravar na tabela).
2. **`leads_capi` só como fallback** — não será mais fonte primária (survey leads ~98% disjuntos dela).
3. **Recuperação de 24h + forward** _(revisado pelo usuário 18/05; era "forward-only puro")_ — ao ligar, processar `lead_surveys` com `submittedAt` nas **últimas 24h** e dali pra frente (cutoff = instante do enable − 24h). Dedup do ledger evita duplicar. **Não** re-disparar nada mais antigo que 24h (conversão velha suja a otimização do Meta; até ~24h o Meta aceita p/ atribuição).
4. **Extensão de monitoramento entra junto** (não vira follow-up): digest e alertas críticos precisam enxergar a nova fonte, senão volume/CAPI parecem anômalos.
5. **Tabela-ledger própria** (`registros_ml`) para dedup — não escreve na tabela do front, não polui `leads_capi`.
6. **Fluxo `Lead` intocado**; ramo `lead_surveys` roda **isolado** (try/except próprio) — falha no survey nunca derruba o `Lead`.
7. **Fail-loud** (exigência do `CLAUDE.md`): cobertura de JOIN abaixo do limite → alerta; valor que não mapeia → falha alto; batch zerado → assert.
8. **Restrições duras:** lead sem `computador` **ou** sem fbp/fbc → **não dispara**; desfecho `skipped` registrado no ledger.

## 4. Pendências obrigatórias antes do go-live

1. **Vocabulário de `computador`** — repetir a verificação da §2.6 sobre a nova coluna quando ela chegar (no `Lead` é `SIM/NAO/Não`).
2. **Whitelist/encoding de UTM dos survey leads** (source/medium/campaign/content/term) — vêm do `UTMTracking`, codificados pela whitelist de UTM do modelo, **não** pelos mapas de pesquisa. Esta é a classe de quebra histórica do projeto (categoria de UTM nova fora da whitelist degradando o sinal calado — registrada como "Cluster 5" / "cenário 1.2" na auditoria de quebra de produção). Verificação separada e ainda pendente.
3. **Recomendado:** pedir ao front, na mesma leva da coluna `computador`, também `fbp`/`fbc`/`telefone`/`nome` como colunas limpas. Hoje vêm de parse de JSON de log (98%/90%) com a mesma fragilidade que motivou a decisão sobre `computador`; sem isso, ~2% continuam descartados e o parse pode quebrar calado se o front mudar o formato do payload.

## 5. Desenho da implementação (aguardando autorização)

Nenhum código foi escrito. Quando autorizado **e** com a coluna `computador` disponível:

1. **Ledger** `registros_ml` (nosso): `lead_id` (PK = `lead_surveys.id`), `email`, `variant`, `lead_score`, `decil`, `base_meta_event_id`/`base_status`, `hq_meta_event_id`/`hq_status` (HQ NULL se decil<9), `capi_sent_at`, `error_message`, `created_at`. **✅ implementado no I1** (renomeada de `survey_capi_sent` a pedido do usuário).
2. **Ramo isolado** dentro de `/railway/process-pending`, **depois** do batch da `Lead`, em try/except próprio.
3. **Seleção:** `lead_surveys` sem registro no ledger, `submittedAt >= NOW() - 24h`, ordem `submittedAt ASC`, batch próprio `SURVEY_CAPI_BATCH=25`.
4. **Enriquecimento por email:** UTM via `UTMTracking` (linha mais recente com `trackedAt ≤ submittedAt`); fbp/fbc/ip/user_agent via último `meta_capi`; telefone/nome via `n8n_onboarding`; `computador` da nova coluna; `leads_capi` só fallback.
5. **Mapeamento → formato idêntico** ao de `railway_lead_to_sheets_row()` → mesmo `pipeline.run()` → mesmo roteamento A/B (`match_variant`, com UTM+url disponíveis) → mesmo `send_batch_events()`. Allowlist de `utm_source` mantida. `event_id` próprio e namespaced (ex.: `qualified_survey_<id>`), nomes de evento nossos — sem reusar o `eventId` deles.
6. **Restrições duras + fail-loud** conforme §3.7/§3.8.
7. **Registrar todo desfecho** (sent/skipped/blocked) no ledger → o polling de 5min não reprocessa.
8. **Extensão de monitoramento** (§3.4).
9. **Validação:** verificações da §4, depois mapeamento→scorer num sample em **dry-run de CAPI** conferindo payloads (PII com hash, fbp/fbc presentes, nomes de evento, decis sãos) antes de qualquer evento real.

## 6. Bloqueador atual

**Decisão resolvida (2026-05-17):** o usuário optou por **não esperar a coluna limpa**. A esteira nova é implementada **já**, recuperando `computador`/fbp/fbc de `integration_logs` (re-medição 17/05: `computador` ≈100% combinando `n8n_onboarding`+`activecampaign` campo 144; fbp/fbc ≈97% — §2.4). O limitante real do envio passa a ser **fbp/fbc**: os ~3% sem fbp/fbc **não são enviados** (skip registrado no ledger, consistente com a regra dura — sem fbp/fbc também não se envia), e há guarda fail-loud se a cobertura cair (§3.7/§3.8). Pedir a coluna `computador` (e idealmente fbp/fbc/telefone/nome) como campo limpo ao front **continua valendo, em paralelo**, como melhoria de durabilidade (fecha os ~10% e remove a fragilidade do parse de log) — rastrear em `instrucoes_dev_frontend_capi.md` (follow-up sugerido, não executado aqui).

Motivo da mudança de postura: a captação de produção migrou para `lead_surveys` e o sinal CAPI scoreado ficou OFF para a inflow viva (ver estado operacional no topo) — esperar a coluna mantém o sinal em 0%; recuperar de log restaura ~90% agora.

**Único bloqueio remanescente:** a implementação segue o **protocolo por item** (cada item implementado → testado → commitado → deployado em canary 0% → validado → promovido com OK explícito), conforme `PLANO_EXECUCAO.md` e `PLANO_SAFEGUARD.md`. Cada item I1–I7 (§9) exige autorização explícita do usuário antes de tocar código.

## 9. Sequência de implementação (protocolo por item)

Cada item é um ciclo completo implementa → testa → commita → deploya canary 0% → valida → promove (com OK). Nada começa sem autorização explícita por item.

- **I0 — Decisão + roadmap** ✅ (2026-05-17): decisão de fonte resolvida (acima); frente registrada como ativa urgente no `PLANO_EXECUCAO.md`.
- **I1 — Tabela-ledger** `registros_ml` ✅ (2026-05-17): script idempotente `scripts/create_registros_ml.py`, aplicado e testado no Railway (12 colunas, PK `lead_id`, idempotência + PK-conflict + smoke OK, tabelas críticas intactas; renomeada de `survey_capi_sent` a pedido do usuário); commits `9b57c0d`+`31d1151` no branch `feat/capi-lead-surveys-scoring`. Nada lê/escreve até o I4.
- **I2 — Adaptador de mapeamento** `api/survey_mapping.py` ✅ (2026-05-18): função pura que monta dict formato-`Lead` (survey+utm+enrich) e delega à canônica `railway_lead_to_sheets_row` — zero normalização reimplementada, equivalência por construção. `tests/test_survey_mapping.py` 5/5 (equivalência Lead-direto vs survey, vocabulário canônico, computador do enrich, UTM ausente). Não importado por nada do fluxo `Lead`. Commit `2a802db` no branch `feat/capi-lead-surveys-scoring`. Sem Cloud Run.
- **I3 — JOINs de enriquecimento** `api/survey_enrichment.py` ✅ (2026-05-18): lote read-only; por lead `utm` (UTMTracking, recência ≤ submittedAt), `enrich` (fbp/fbc/ip/ua por `eventId` preciso 1:1 com fallback email; computador n8n→ac144; telefone/nome n8n) e flag `meta_eligible`. Cobertura fbp+fbc medida **só entre Meta-elegíveis** (google-ads não tem fbc e é allowlist-blocked — medir global daria alarme crônico falso). **Alarme migrou pro I5** (rolling sobre o ledger; lotes do polling são pequenos, guard per-batch cegaria). `tests/test_survey_enrichment.py` 7/7; integração read-only 300 leads: utm 96% / computador 100% / fbp+fbc(meta) 100% / enviáveis 242/242. Commit `160562c`. Não importado pelo fluxo `Lead`; sem Cloud Run.
- **I4 — Ramo isolado** no `/railway/process-pending` — **código ✅ (2026-05-19, commit `d2587f0`)**: `api/survey_branch.py` (lê 24h+forward, dedup ledger, classify allowlist/missing_data/send, mapa I2, MESMO pipeline.run/A-B/send_batch_events, event_id `survey_<id>`, grava `registros_ml`); hook `+18` linhas em `app.py` (helper `_run_survey_branch_safely` gated por `SURVEY_CAPI_ENABLED`, chamado nos 2 returns, nunca propaga, `Lead` byte-idêntico); `tests/test_survey_branch.py` 7/7 + regressão I2 5/5 / I3 7/7. **Validação canary (gates B/D/C.1/C.2 + `NO_TRAFFIC` 0% + dry-run) PENDENTE — pausado pelo usuário 19/05.**
- **I5 — Bloqueios duros de monitoramento** (B1–B4 da §8) — antes de religar o digest. **Inclui o fail-loud sistêmico da esteira (migrado do I3):** regra rolling no tempo sobre o ledger `registros_ml` — janela (ex.: últimas 6h), entre Meta-elegíveis, se `skipped_missing_data` > limiar (cobertura < ~90%) E volume da janela ≥ N → alarme. Imune a tamanho de lote.
- **I6 — Verificações pré-go-live** (vocabulário de `computador`, whitelist de UTM — §4).
- **I7 — Promoção + religar schedulers + reconciliação de monitoramento** (R/C da §8, decididos 1 a 1).

## 7. Riscos

| Risco | Mitigação |
|---|---|
| Parse de payload de log quebra calado se o front mudar formato | Pedir colunas limpas (§4.3) + fail-loud na cobertura (§3.7) |
| UTM nova fora da whitelist degrada sinal calado (quebra histórica) | Verificação obrigatória §4.2 antes do go-live |
| Re-disparo de histórico com conversões velhas pro Meta | Forward-only (§3.3) + ledger (§5.1/§5.7) |
| Falha no ramo survey derruba o fluxo `Lead` | Isolamento try/except (§3.6) |
| Percepção de "double count" no Meta | Nomes de evento distintos; decisão consciente (§2.2) |

## 8. Estudo: extensão de monitoramento (2026-05-17)

Estudo completo do que o monitoramento precisa para ter eficácia sobre a esteira nova. Hoje **todo** o monitoramento lê só `Lead` (e `leads_capi` por JOIN); **nenhuma** parte lê `lead_surveys`/`UTMTracking`/`integration_logs`/`registros_ml`, **com uma exceção**: a regra de alerta crítico "não chega lead" (Regra 4) já lê `lead_surveys.submittedAt` desde 12/05/2026 — essa não muda.

### 8.1 Bloqueio duro (sem isto, ligar quebra o monitoramento ou gera falso positivo constante)

- **B1 — Guarda de schema do payload:** o auditor (`payload_schema.py`/`digest.py`) falha alto se o endpoint produzir qualquer chave nova não declarada, então todo breakdown/seção novo de pesquisa precisa ser pré-declarado **antes** de ligar, senão o digest inteiro quebra.
- **B2 — Baseline do detector de desvio:** a regra de desvio de score/decil (Regra +) compara janela atual contra baseline de 30d só do `Lead`; ao ligar, a janela passa a misturar survey leads e o baseline fica defasado, disparando falso positivo até incorporar a fonte nova.
- **B3 — Regra "CAPI com sucesso baixo" (Regra 5):** olha só `Lead.capiSentAt`; se a esteira de pesquisa falhar o envio, o alerta fica mudo (falso negativo) — precisa enxergar `registros_ml`.
- **B4 — Ledger como fonte:** nada disso funciona se `registros_ml` não registrar `leadScore`/`decil`/`capiStatus`/`capiSentAt` por survey lead (já previsto em §5.1) — o monitoramento lê o ledger.

### 8.2 Reconciliação de números (sem isto, o relatório diário fica sem sentido, mas não quebra)

- **R1 — Funil unificado:** "Pesquisa/Scoreado/CAPI enviado/Aceito" só conta `Lead`/`leads_capi`; sem uma linha/breakdown por fonte incluindo a esteira de pesquisa, os ratios (clique/lead, taxa de envio, taxa de aceite) quebram silenciosamente.
- **R2 — Contadores operacionais 24h:** leads recebidos/scoreados/CAPI enviado leem só `Lead`; sem somar a fonte de pesquisa, parece que o volume caiu.
- **R3 — Qualidade por período e distribuição de decil:** vêm só do `Lead` (Railway, via pg8000 — **não** Sheets); a coorte de pesquisa fica invisível e a qualidade aparenta degradar conforme o ledger cresce.

### 8.3 Cobertura de detecção (sem isto, problemas na esteira nova passam despercebidos)

- **C1 — Regra nova de saúde da esteira de pesquisa:** falta alerta para "ingest de `lead_surveys` parou" e "survey lead scoreado mas preso sem CAPI no ledger" — a Regra 4 só cobre "chegou lead", não "parou de ser enviado".
- **C2 — Fail-loud da esteira nova:** cobertura de JOIN (UTM/fbp/fbc) caindo e categoria/UTM desconhecida precisam de alerta próprio (já decidido em §3.7/§4.2; aqui entra como item de monitoramento).
- **C3 — Regras "scoreado sem CAPI" (Regra 1) e "FBP/FBC baixo" (Regra 6):** olham só `Lead`; sem incluir os survey leads, ou disparam falso ou ficam cegas pra cobertura de match da fonte nova.
- **C4 — Detectores de deriva de dados:** categoria nova / deriva de distribuição / taxa de não-resposta operam sobre a janela de produção da esteira `Lead` (Railway); a coorte de pesquisa (respostas + UTM via `UTMTracking`) fica fora — e detectar UTM nova fora da whitelist é a classe de quebra histórica (§4.2). _(Há código legado `gspread` em `data_drift_detection.py`/`orchestrator.py` "aba 2", inerte sem `GOOGLE_SHEETS_URL`; os números vivos vêm do Railway.)_
- **C5 — Ranking de qualidade de UTM (criativos):** lê só `Lead`+`leads_capi`; sem unir a fonte de pesquisa, o ranking de criativos ignora essa parte do tráfego.

### 8.4 Não muda

- Regra 4 ("não chega lead") já lê `lead_surveys`. Regra "polling com erro 500" independe de qual esteira roda dentro do endpoint.

> Nota de fidelidade: o desenho usa **um único ledger** `registros_ml` (§5.1) — score, status e envio vivem nele; o monitoramento lê dele e de `lead_surveys`. Não há tabelas auxiliares adicionais.

**Correção (2026-05-17):** a primeira versão deste estudo atribuía as métricas de período/decil e os detectores de deriva ao Google Sheets — **erro**. A fonte viva do digest é o Railway (`Lead`/`leads_capi` via pg8000); o código `gspread` remanescente é legado inerte. A conclusão de cada ponto (cegueira à coorte de pesquisa) se mantém, porque o que esses componentes leem é `Lead`, não `lead_surveys`.

**Escopo acordado (2026-05-17):** os pontos **B1–B4, R1–R3, C1–C5 entram no escopo** do trabalho. A decisão de incluir cada um, e em que profundidade, é tomada **1 a 1 na fase de implementação** — que segue bloqueada por autorização explícita + chegada da coluna `computador` (§6).

---

*Identificadores e artefatos:* tabelas Railway `Lead`, `lead_surveys`, `UTMTracking`, `integration_logs`, `leads_capi`; endpoint `/railway/process-pending` em `api/app.py`; mapeamento `api/railway_mapping.py`; scripts read-only de investigação em `scripts/_inspect_pipeline_b*.py`, `scripts/_inspect_computador_fill.py`, `scripts/_verify_survey_vocab.py`. Classe de quebra histórica referenciada: "Cluster 5" / "cenário 1.2" em `docs/AUDITORIA_QUEBRA_PRODUCAO.md`. Regra fail-loud: `CLAUDE.md`. Instruções ao front: `docs/instrucoes_dev_frontend_capi.md`.
