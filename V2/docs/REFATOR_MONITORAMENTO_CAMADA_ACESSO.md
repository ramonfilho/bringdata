# Refator do monitoramento — camada de acesso a leads

**Criado:** 2026-05-24 · **Status:** Etapa 1 concluída e commitada, Etapa 2 editada/testada (commit incerto), Etapas 3–7 pendentes.

> Doc de continuidade — escrito durante a sessão pra que, se o terminal do Claude travar, outra sessão consegue retomar sem perder contexto.

---

## Por que este refator existe

Mudar a fonte dos dados do monitoramento (das tabelas mortas `Lead`/`leads_capi` no Railway pro ledger novo `registros_ml` populado pelo consumer Pub/Sub) virou um trabalho de várias etapas porque **cada monitor consultava o banco direto**, sem camada de abstração entre o consumidor e a fonte física. Resultado: trocar de tabela exige N edições com remapeamento de colunas, em vez de uma edição em 1 lugar.

A solução é introduzir uma camada de acesso a leads que isole os consumidores da fonte. Inspiração: padrão repositório clássico + adaptadores na borda. Padrão registrado na skill `/sw-architect` (criada nesta mesma sessão) e na regra obrigatória do `V2/CLAUDE.md` que cobra invocar essa skill antes de qualquer mudança arquitetural.

---

## Arquitetura — dois andares

**Andar 1 — acesso aos dados (`V2/src/data/`)**

Camada fina que sabe **apenas** "me dá leads dessa janela com esses campos, de qualquer fonte". Devolve sempre no mesmo formato interno (`LeadRecord`). Não tem regra de negócio.

- `lead_record.LeadRecord` — dataclass frozen, contrato estável. Campos em português pra não vazar vocabulário físico (camelCase do schema antigo, snake_case do ledger novo, etc.).
- `lead_repository.LeadRepository` — Protocol (PEP 544) com 2 métodos: `recent_leads(window_minutes)` e `leads_in_range(start, end)`. Limites operacionais (janela máx 90d, default limit 10k).
- `lead_repository.compose_repository(source, **conn_kwargs)` — ponto único de composição. Hoje só `source='registros_ml'`; `'legacy'` entra na Etapa 3.
- `adapters/registros_ml.RegistrosMLAdapter` — traduz `registros_ml.base_status` → `LeadRecord.status_envio`. Recebe conexão pg8000.native via injeção.

**Andar 2 — consumidores (`V2/src/monitoring/`, endpoints em `V2/api/app.py`)**

Recebem o repositório como argumento (injeção de dependência) e fazem agregações específicas: baseline 30d, distribuição por decil, taxa de erro, ranking de UTM, etc. Não sabem de onde os dados vieram.

Aggregação compartilhada por 2+ consumidores pode migrar pra função utilitária (ainda no andar 2). Não preemptivamente — só quando duplicação aparece.

---

## Os 4 detalhes operacionais

Princípios obrigatórios na skill `/sw-architect`:

1. **Injeção de dependência** — consumidor recebe o objeto repositório, não importa direto.
2. **Ponto único de composição** — `compose_repository()` é o único lugar que monta adaptadores. Endpoints/schedulers chamam, consumidores não.
3. **Contrato estável** — `LeadRecord` é compromisso. Adicionar campo é livre; renomear/remover migra todos os consumidores junto.
4. **Limites operacionais** — janela máxima 90d, limite default 10k linhas, log de warning se truncar.

---

## Plano de execução (7 etapas)

Migração gradual (estrangulamento). Código antigo vive até consumidores migrarem. Cada etapa = 1 commit (ou 2-3 se grande), com critério verificável de "pronto".

### Etapa 1 — CONCLUÍDA
**Criar `src/data/` com formato interno, interface e adaptador do ledger novo.**

- Commits: `a0090c9` (skill /sw-architect + CLAUDE.md), `b4b8cf4` (módulo src/data/), `06b4316` (fix gitignore __pycache__).
- Critério: adaptador devolve mesma contagem que SQL direto. Validado: 850 = 850 em janela 24h, distribuição por status idêntica, limites rejeitam corretamente.

### Etapa 2 — EDITADA E TESTADA (commit incerto, ver "Estado pendente" abaixo)
**Migrar primeiro alerta crítico (taxa de sucesso CAPI baixa) para usar o repositório.**

Mudanças aplicadas em `V2/src/monitoring/critical_alerts.py`:
- `rule_capi_success_low(repo)` substituiu `rule_capi_success_low(conn)`. Conta status_envio em vez de `capiStatus`.
- `run_critical_checks` agora compõe o repositório uma vez via `compose_repository('registros_ml', railway_conn=railway_conn)` e passa pra regra migrada.
- As outras regras continuam recebendo `railway_conn` durante a migração (coexistência).

Teste novo criado: `V2/tests/test_critical_alerts_via_repo.py` (5 casos com FakeRepo, todos passam).

Validação contra ledger vivo:
- Janela 60min: SQL e regra concordam em "amostra insuficiente (sent=0)".
- Janela 24h: regra calcula sent=151, ok=3, err=148, rate=2.0% — idêntico ao SQL direto.
- Testes antigos R1/R2/R3 (`test_critical_alerts_pubsub.py`): 10/10 ainda passam.

### Etapa 3 — PENDENTE
**Migrar as outras 3 regras críticas + criar adaptador legado.**

- `rule_variant_no_capi` (variante do A/B parou de mandar evento) — passa a usar `repo`, **e agora pode ser per-variant** porque o ledger tem `variant`. Versão antiga era agregada por falta dessa info na tabela `Lead`.
- `rule_utm_source_missing` (leads sem source de UTM) — passa a usar `repo.utm_source`. Ledger tem a coluna desde o deploy do P17.
- `rule_score_drift` (desvio de score) — janela 60min lê do ledger novo, **baseline 30d continua na tabela `Lead` antiga** (decisão registrada na memória `projeto_baseline_drift_split_railway_ledger.md`). Cria adaptador legado em `src/data/adapters/legacy.py` com método `leads_in_range` só pra esse uso. Migração automática quando ledger acumular 30d (≈22/06/2026).

### Etapa 4 — PENDENTE
**Migrar monitor operacional + monitor de qualidade CAPI.**

- `V2/src/monitoring/operational_monitor.py` — check "último lead recebido" passa pro repositório (ou direto `lead_surveys.submittedAt` como já faz `rule_no_leads_arriving`); "último CAPI enviado" passa a olhar `LeadRecord.capi_enviado_em`.
- `V2/src/monitoring/capi_monitor.py` — missing rate vira "% skipped_missing_data nas últimas 24h"; rejection rate vira "% status_envio='error'"; check de decis sem evento (`_check_zero_decil_events`, T1-2) sobe `min_leads_threshold` de 20 → 100 pra esperar volume real (campanhas do gestor sobem 2026-05-25).

Critério: daily-check devolve mesma estrutura de alertas que antes pros mesmos dados.

### Etapa 5 — PENDENTE
**Migrar monitor de qualidade de dados (`data_quality.py`, 2731 linhas).**

Maior em volume de código, mesma mecânica de troca de fonte. Detecta drift de categorias vs baseline do modelo + features novas após encoding. Fonte passa a ser `lead_surveys` + `UTMTracking` (banco do dono) ou logs estruturados `[FV_JSON]` que o consumer Pub/Sub já emite.

### Etapa 6 — PENDENTE
**Migrar endpoints + validador.**

- `/monitoring/utm-quality` (ranking de UTMs por decil) — usa `repo`.
- `/smoke/run-variants` (teste de fumaça do A/B antes de promover deploy) — usa `lead_surveys`.
- `/validation/weekly` (relatório semanal em Excel + Slack) — parte que lê tabelas mortas vira `repo`; parte que lê Guru/Meta não muda.
- `V2/src/monitoring/payload_schema.py` — estender com campos novos.

### Etapa 7 — PENDENTE
**Seção nova "📨 Pub/Sub 24h" no resumo diário do Slack + avaliar remoção do adaptador legado.**

Bloco no digest mostrando, das últimas 24h: contagem por status, distribuição de decil, top erros. Lê do `repo`. Avaliar remover adaptador legado quando zero consumidores estiverem usando.

---

## Estado pendente — o que verificar primeiro ao retomar

1. **Etapa 2 foi commitada?**
   - Esperado: `git log` mostrando um commit com título `refactor(monitoring): migra alerta de taxa de sucesso CAPI para LeadRepository`.
   - Se sim: marcar Etapa 2 como concluída e seguir pra Etapa 3.
   - Se não: arquivos editados estão no working tree (`V2/src/monitoring/critical_alerts.py`, `V2/tests/test_critical_alerts_via_repo.py`). Rodar os testes (`python tests/test_critical_alerts_via_repo.py` da pasta `V2/`) e commitar com a mensagem acima.

2. **Verificações sanitárias antes de Etapa 3:**
   - Consumer Pub/Sub ainda rodando (revisão `smart-ads-api-00503-mip` a 100%).
   - `registros_ml` recebendo dados (`SELECT MAX(created_at) FROM registros_ml`).

---

## Documentos relacionados

- `V2/CLAUDE.md` — regra obrigatória de invocar `/sw-architect` antes de mudança arquitetural.
- `.claude/commands/sw-architect.md` — a skill em si.
- `docs/PROCESSO_CAPI_LEAD_SURVEYS.md` — contexto da virada de arquitetura SQL→Pub/Sub e do que vive em `registros_ml`. P18 desse doc é exatamente este refator.
- Memória: `projeto_baseline_drift_split_railway_ledger.md` — decisão sobre baseline 30d ficar no Railway antigo durante transição.
- Memória: `projeto_migracao_lead_surveys.md` — contexto do porquê `Lead` parou em 17/05.

---

*Atualizar este doc ao final de cada etapa com a referência do commit e o critério de pronto que foi verificado.*
