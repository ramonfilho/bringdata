# Plano — Decil dos dois modelos no ledger (aposentar o refresh e a `scores_historicos`)

**Resumo em uma frase:** em vez de re-scorear todo mundo uma vez por dia numa tabela separada (`scores_historicos`), o consumer passa a scorear cada lead pelos **dois** modelos no momento do scoreamento e gravar os dois decis direto no ledger `registros_ml` — o que mata a corrida do relatório, o estouro de memória e o backfill diário, e faz os relatórios lerem uma tabela só (sem join).

Origem: decisão do operador (05/07/2026) após diagnóstico da corrida do painel de decis (o "Google 40%" falso das 06:00). Skills: `/sw-architect` (desenho) + `/data-architect` (schema). Direção escolhida: **B** — ir direto ao refator, sem o stopgap de adiantar o refresh.

---

## O problema de hoje

Os relatórios de qualidade (painel de decis, score geral, relatório de criativo) precisam de uma **régua única**: todo lead avaliado pelo **mesmo modelo Challenger** (abr28), pra os decis serem comparáveis. A produção, porém, scoreia cada lead por **um** modelo só (o roteado no teste A/B) e grava **um** decil no `registros_ml`.

Pra cobrir esse buraco existe o **refresh** (`api/scores_refresh.refresh_launch_scores`): 1×/dia, dentro do relatório das 06:00, ele re-scoreia todos os leads do lançamento pelos dois modelos e grava na tabela `scores_historicos`. Isso custa caro:

- **Corrida:** o refresh roda no mesmo request do relatório, e o painel **lê a `scores_historicos` antes do refresh terminar** — em 05/07 o painel de "ontem" saiu com 122 de 1.199 leads (10%), e o Google com 15 leads virou "40% D9-D10" (ruído puro).
- **Estouro de memória:** re-scorear o lançamento inteiro num lote grande estoura os 2GB do Cloud Run em catch-up de ~9k leads.
- **Backfill manual:** todo lançamento novo precisa de backfill local porque o refresh online não dá conta do catch-up grande.
- **Join extra:** a `scores_historicos` não tem UTM; todo relatório junta ela com o `registros_ml` por email pra saber de qual fonte o lead veio.

## A ideia

1. **Scorear os dois modelos na produção** (no consumer, no scoreamento de 5/5 min). A produção **já carrega os dois modelos em memória** — hoje só prediz pelo roteado. Passa a predizer pelos dois.
2. **Desacoplar scoreamento de envio:** scoreia os dois; **envia o CAPI só pelo decil roteado** (integridade do A/B intacta — o evento enviado não muda).
3. **Gravar os dois decis + run_ids no `registros_ml`.** O decil nasce com o lead, junto da UTM.
4. **Relatórios leem o `registros_ml`** — o join com `scores_historicos` desaparece.
5. **O scorer em lote (`_score_population`) fica vivo**, mas só para **backfill one-time** (retreino / histórico), não mais como job diário.

### Reuso (checado contra o código concreto)
A capacidade "scorear um lead por uma variante" **já existe** — versão de 1 lead em `src/scoring/service.score_lead_from_payload` (resolve variante → predictor → thresholds) e versão em lote em `scores_refresh._score_population`. **Não escrever um scorer novo:** generalizar `score_lead_from_payload` pra iterar sobre as variantes e devolver os dois decis. O envio continua usando só o roteado.

## Schema — o que muda no `registros_ml`

Adicionar (nulas, additivas):

| Coluna | Tipo | Observação |
|---|---|---|
| `score_champion` | DOUBLE | |
| `score_challenger` | DOUBLE | |
| `decil_champion` | SMALLINT (1..10) | **INT, não TEXT 'D01'** — casa com o `decil` roteado que já é INT; formatação 'D0x' fica na renderização. Evita a classe de bug 'D01' vs 'D1'. |
| `decil_challenger` | SMALLINT (1..10) | idem |
| `champion_run_id` | TEXT | "qual régua" — por LINHA |
| `challenger_run_id` | TEXT | idem |
| `scored_at` | TIMESTAMP | quando scoreou (o ledger só tem `created_at` = hora do lead) |
| `core_commit` | TEXT | lineage: versão do código que scoreou |

**Run_id por linha (não tabela satélite):** é filtro curto (`WHERE challenger_run_id = :pinned`); satélite só somaria join. Como o `registros_ml` é 1 linha por `event_id` (pode ter >1 por email), o run_id **precisa** ficar por linha — dois eventos do mesmo email podem ter run_ids diferentes se houve retreino entre eles.

**Metadados de lançamento da `scores_historicos` (`lf`, `mes_lancamento`, `semana_captacao`, `vendas_inicio`, `vendas_estimada`, `data_captura`) NÃO migram** — são deriváveis de `created_at` + o calendário (`launches.yaml`). Se materializados algum dia, moram numa **dimensão de lançamento** (`analytics.launch_curation`, no backlog), não repetidos em cada lead.

## A régua-por-run_id nos relatórios

Os read-models (`challenger_decil_dist_by_source`, `launch_score_geral`, `challenger_quality_by_utm`) passam a: **filtrar `challenger_run_id = :pinned` → deduplicar por email (evento mais recente)** — mesmo `DISTINCT ON (email)` que já usam. Predicado de decil muda de `IN ('D09','D10')` pra `IN (9,10)` (contrato coordenado). O join `scores_historicos ⋈ registros_ml` some (decil e UTM na mesma tabela).

## Backfill só no retreino (não mais diário)

Sem retreino, a régua é única automática (todo lead nasce com o decil do challenger vigente). **Só um retreino do challenger** (novo run_id, thresholds diferentes) quebra a comparabilidade de um lançamento que atravessa o retreino → aí roda um **backfill one-time** (o `_score_population` que ficou vivo) re-scoreando o histórico que se quer manter comparável, com o run_id novo. Isso é raro (mensal no máximo) contra o refresh diário de hoje — ganho estrito. A barra-alvo Top5 também é por-run_id: um retreino pede regenerá-la (o guard de run_id-mismatch já suprime a seção enquanto não bate).

## Fases (estrangulamento — legado vivo até prova de valor)

- **Fase 1 — schema.** Adiciona as 8 colunas nulas no `registros_ml`. Zero comportamento. *Rollback: DROP das colunas (nulas, sem consumidor).*
- **Fase 2 — escrita dupla.** Consumer scoreia os dois e grava ambos + run_ids + `scored_at`/`core_commit`; o roteado ainda manda CAPI igual. O 2º score é protegido (falha loga, não bloqueia envio/ledger). **Canary + Gate C de paridade** — passa porque o evento enviado não muda (mesmo decil roteado, mesmo value). *Rollback: para de gravar os 2; roteado/envio intactos.*
- **Fase 3 — leitura.** Read-models apontam pro `registros_ml`; `scores_historicos` fica viva em paralelo até o ledger cobrir um lançamento inteiro. *Rollback: read-models voltam pra `scores_historicos` (refresh ainda roda).*
- **Fase 4 — backfill histórico.** One-time (lote) dos leads antigos que só têm 1 decil, pra história dos relatórios. Com auditoria de cobertura. **Spec completo em "Fase 4 em detalhe" abaixo.**
- **Fase 5 — aposentadoria.** Tira o refresh do daily-check 06:00 e **dropa a `scores_historicos`** (após o gate abaixo). O `_score_population` fica só pra retreino-backfill.

### Status da Fase 2 (05/07/2026)
Fases 1+2 **LIVE** (PR #56, rev 00851-woh a 100%; validação em prod: Gate C 0 divergências, batch real de 20 leads com colunas populadas, prod intacta por log). O `core_commit` foi cabeado no consumer num follow-up no mesmo dia (antes era gravado NULL) — cada linha scoreada online agora carrega a revisão do Cloud Run que a scoreou.

## Gate de cobertura antes de dropar (obrigatório)

Reconciliação: **todo `(email, lf)` da `scores_historicos` tem decil_challenger correspondente no `registros_ml`** pós-backfill, com contagem de não-cobertos = 0. Só então dropa, com **dump em GCS antes** (mesma reversibilidade do drop da `Lead`/`registros_ml` do Railway).

## Fase 4 em detalhe — backfill histórico do ledger

**Objetivo.** Os relatórios de qualidade de lançamentos passados (painel de decis, score geral, relatório de criativo com `date=`) precisam ler o `registros_ml` pela régua única do challenger. Os leads gravados **antes da Fase 2 (05/07/2026)** têm só o decil roteado — falta `decil_champion`/`decil_challenger`. O backfill preenche essas colunas nesses leads, one-time.

**População-alvo.** Linhas do `registros_ml` com `survey_responses IS NOT NULL AND email IS NOT NULL AND decil_challenger IS NULL` (ainda não dual-scoreadas), na janela que o ledger cobre — **do nascimento do ledger (~25/05/2026) até 05/07/2026** (quando a Fase 2 subiu). O predicado `decil_challenger IS NULL` torna o backfill **idempotente**: re-rodar pula quem já tem.

**Como scoreia.** Reusa o `_score_population` (o scorer em lote que ficou vivo) com champion + challenger **vigentes** (run_ids pinados — os MESMOS do scoring online, pra régua idêntica). **Chunked + local:** processa em lotes (por janela de `created_at`, ex. por semana, ou por N≈2–3k eventos) rodando **na máquina local**, não no Cloud Run de 2GB — foi exatamente esse teto que estourou no refresh (~9k leads). Grava por `UPDATE registros_ml SET (as 6 colunas) WHERE event_id = :eid` — **grão de evento, não de email** (o ledger é 1 linha por `event_id`; o dedup-por-email que o refresh faz **não** vale aqui, senão perde eventos do mesmo email).

**Lineage / reversibilidade (data-architect).** Cada linha backfillada leva `core_commit = 'backfill_fase4_YYYYMMDD'` e `scored_at = now()` — rótulo de proveniência que separa backfill de scoring online. **Rollback:** `UPDATE ... SET decil_champion=NULL, decil_challenger=NULL, ... WHERE core_commit='backfill_fase4_YYYYMMDD'` — desfaz só o backfill, sem tocar os leads scoreados online. Aditivo e reversível em minutos.

**Auditoria de cobertura (obrigatória — alimenta o gate da Fase 5).**
1. **Reconciliação vs `scores_historicos`:** todo `(email, lf)` que a `scores_historicos` tem com `decil_challenger` (no run_id pinado) tem `decil_challenger` correspondente no `registros_ml` pós-backfill; não-cobertos por LF = 0.
2. **Fill-rate por período:** % de linhas com `decil_challenger` preenchido por LF/semana — **sem buraco no meio** (pega o caso "completo no passado, vazio no recente", que é a razão de existir a auditoria por período).
3. **Grão:** nº de eventos scoreados == nº de eventos elegíveis (survey não-nulo) na janela; zero perda.

**Buraco estrutural a decidir (não silenciar).** O `registros_ml` só nasce ~25/05/2026; a `scores_historicos` tem LFs **anteriores** ao ledger (via backfill de `lead_legado`/`leads_historico`). Esses leads **não existem** no `registros_ml` → o backfill não os alcança. Antes de dropar a `scores_historicos` (Fase 5), decidir e **registrar**: esses lançamentos pré-ledger ainda são consultados nos relatórios? Se **sim** → precisam de ingest histórico próprio no `registros_ml` (escopo maior, vizinho da consolidação `analytics`) OU a `scores_historicos` sobrevive só pra eles; se **não** → o gate cobre só a janela do ledger e o drop é seguro. **Não dropar sem essa decisão registrada.**

## Riscos

- **Hot path do scoring/CAPI:** tocar o consumer exige parity audit + canary. Mitigado: o evento enviado não muda (só adiciona escrita); o 2º score é best-effort pro storage, nunca bloqueia o envio.
- **Run_id pinado vs retreino:** resolvido gravando o run_id por linha + backfill one-time no retreino (acima).
- **Latência/CPU do 2º predict:** modelo já em memória; custo marginal pequeno. Medir no canary.

## Relação com outras frentes

- Substitui o stopgap de "adiantar o refresh 30 min" (descartado, worktree removida).
- A dimensão de lançamento (`analytics.launch_curation`) e a consolidação `analytics` são frentes vizinhas — os metadados de lançamento que a `scores_historicos` denormalizava pertencem a elas, não ao ledger.
- Régua única do painel de decis (abr28) e o refresh atual: `V2/docs/` + memórias do projeto.
