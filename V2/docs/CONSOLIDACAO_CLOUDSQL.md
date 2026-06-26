# Consolidação no Cloud SQL — leads, vendas e resultados

**Criado:** 2026-06-24 · **Branch:** `feat/consolidacao-cloudsql` · **Worktree:** `~/bring_data.worktrees/consolidacao-cloudsql`

> Doc de continuidade. Frente consultada com `/sw-architect` e `/mlops-architect` antes de codar (regra do CLAUDE.md).

---

## Por que esta frente existe

Hoje, toda execução de **treino** e de **validação** puxa os dados ao vivo de muitas fontes separadas: arquivos locais, parquets, Google Sheets (backup + produção), Railway antigo (jan–mai), Railway novo, o ledger `registros_ml` no Cloud SQL, os gateways de venda (Guru, Hotmart, Asaas, Boletex, TMB) e a Meta API. É lento, frágil e repetido em cada script.

A solução: **os dados passam a viver em tabelas no nosso Cloud SQL**, e os pipelines **leem de lá** pela camada de repositório (`src/data/`). Os loaders de API de hoje deixam de ser chamados pelo consumidor e viram o **ETL** que alimenta as tabelas — separando "trazer o dado" (lento, preso a API) de "ler o dado" (rápido, preso a banco).

**Migração (definição do dono):** trocar arquivos locais + N chamadas de API soltas (e parquets) por leitura de tabela. O **enriquecimento de compradores do treino** (trazer Hotmart/Asaas/Boletex, que hoje o treino não lê — só Guru+TMB) vem **depois** desta consolidação, e cai naturalmente na Fase 2.

---

## Decisões de arquitetura (já fechadas)

| Decisão | Escolha | Por quê |
|---|---|---|
| Reuso vs paralelo | **Estender `src/data/`** | A camada de repositório já existe e está completa (refator de monitoramento, Etapas 1–7). `LeadRecord` já é o contrato canônico de lead. |
| Granularidade de tabela | **Uma por conceito** (leads / sales / resultados), não por fonte | Fonte vira coluna de proveniência (`source`/`gateway`). Fonte única por conceito. |
| Mutabilidade | **Append-only + temporal** (`ingested_at` em tudo) | Reprodutibilidade do treino + point-in-time (reconstruir "o que sabíamos na data X"). Resolve a tensão SW (tabela limpa) × MLOps (sem leakage). |
| Onde calcula feature | **Em `src/core/` apenas** — banco guarda dado CRU | Feature/normalização no SQL viraria 4º ponto de divergência de paridade (o bug que zerou Medium). |
| Multi-cliente | **`client_id` em todas as tabelas** desde o dia 1 | Cliente B chegando. |
| Feature store "de verdade" | **Adiada** (fase travada) | Só quando point-in-time estiver provado por parity audit. Por ora isto é um data lake consolidado, não feature store. |
| Resultados de validação | **Tabela relacional** (`validation_*`), não MLflow | Quer consultar cruzando lançamentos (SQL); MLflow continua dono de modelo/dataset-version. |
| Onde mora | **Schema `analytics` no database `ledger`** (decisão do dono, 24/06) | Mesma conexão do `ledger_connection.py`; setup leve (`CREATE SCHEMA`). Contenção é instância-level de qualquer jeito, então database à parte não isolaria performance. |

---

## Arquitetura

```
ETL (loaders de API/arquivo de hoje)  ──escreve──►  Cloud SQL `analytics`
                                                      ├─ leads
                                                      ├─ sales
                                                      ├─ validation_runs / validation_metrics
                                                      └─ meta_insights
                                                            │
                                          Repositórios (src/data/)  ──lê──►  treino / validação
```

- **Reuso:** `LeadRecord` (contrato), `compose_repository(source=...)` (composição única), padrão de conexão de `ledger_connection.py`.
- **Novo:** `SalesRecord` + `SalesRepository` + adaptadores por gateway; store de resultados; conexão `analytics`.

---

## Plano de execução (faseado — estrangulamento, parity audit antes de cada virada)

Cada fase roda dual-read (tabela vs API ao vivo) e só vira a chave quando a paridade bater coluna-a-coluna. Rollback = repositório volta ao adaptador de API ao vivo (um arquivo, minutos).

### Fase 0 — Fundação ✅ CONCLUÍDA (24/06)
- [x] Worktree + branch.
- [x] DDL das tabelas: `api/db/analytics_schema.sql` (leads, sales, validation_runs/metrics, meta_insights).
- [x] **DDL aplicado no Cloud SQL**: schema `analytics` no database `ledger` (instância `smart-ads-db`, RUNNABLE/ALWAYS, IP 104.197.138.129). 5 tabelas, 87 colunas. Owner `postgres` (ledger_app não tem DDL na database); `ledger_app` recebeu USAGE/CREATE no schema + ALL em tables/sequences.
- [x] **Smoke `ledger_app`** (usuário do pipeline): SELECT nas 5 tabelas + INSERT em validation_runs/metrics + JOIN por FK + DELETE CASCADE. Tudo OK.
- [x] Conexão: helper próprio `src/data/analytics_connection.py` (Cloud SQL `ledger` + `SET search_path TO analytics`). `ledger_connection.py` é leitura do `registros_ml` e o docstring dele proíbe escrita — por isso helper à parte.

### Fase 1 — Resultados ✅ CONCLUÍDA (writer; 24/06)
- [x] `src/data/analytics_connection.py` — conexão de leitura/escrita do schema analytics.
- [x] `src/validation/results_store.py` — writer **append-only** (`run_id` com timestamp); mapeia decile/campaign/overall → `validation_runs` + `validation_metrics`. Não calcula nada (recebe as estruturas já computadas).
- [x] Plugado em `validate_ml_performance.py` logo após o Excel salvo, **guardado em try/except** (falha de banco loga alto, não derruba o `.xlsx`).
- [x] Smoke do writer contra o banco real: cabeçalho + 2 decis + 1 campanha + overall, `extra` jsonb, FK cascade. Verde.
- [ ] Validação fim-a-fim no próximo run real (bloco aditivo/guardado; roda naturalmente — só não foi rodado fim-a-fim ainda).
- **`meta_insights` ADIADO (decisão 25/06):** a feature de gasto/CPL não se provou útil por ora. A tabela fica criada e **vazia**; se precisar, populamos depois **retroativamente com script separado**. Nenhum loader Meta grava nela agora.
- Arquivo `.xlsx` continua como export sob demanda.

### Fase 2 — Vendas (`sales`) ◐ EM ANDAMENTO (26/06) — **habilita o enriquecimento de compradores**
- [x] Índice natural `uq_sales_natural` (gateway+email+data+valor) — arbiter do ON CONFLICT (loaders não expõem id de transação).
- [x] `src/validation/sales_store.py` — upsert idempotente; grava **por gateway** (sem dedup cross-gateway, isso é leitura); só valor cru (`sale_value_realizado` fica pra leitura/`src/core`). Resultado expõe inserted/skipped/**filtered** (não dropa em silêncio).
- [x] `src/validation/etl_sales.py` — orquestrador + CLI: puxa guru/hotmart/asaas/boletex (API) + tmb/hotpay (arquivo) e faz upsert. Um gateway fora não derruba o resto.
- [x] Smoke do upsert (sintético): inserção + idempotência (2ª vez insere 0) + linha sem data filtrada visível. Verde.
- [x] **ETL real rodado** (26/05–25/06, só APIs): **297 vendas** — guru 124, hotmart 24, asaas 61, boletex 88. Todas com email, 0 erro. **173 vêm de gateways que o treino hoje NÃO lê** (hotmart/asaas/boletex) — só num mês = o enriquecimento, concreto. (asaas/boletex têm `sale_value` baixo = valor por parcela; agregação/realizado é transform de leitura.)
- [ ] **TMB**: arquivo confirmado `contas_a_receber_09062026_1028.xlsx` (78 MB; único que casa Pedido+Parcela+Grau de risco). Aguarda go + `--report-type`.
- [ ] **Backfill amplo** (janela que o treino usa) depois de validada a janela recente.
- [ ] `SalesRecord` + leitura: treino lê vendas do `sales` (todos os gateways) via repositório, em vez de só Guru+TMB. **← fecha o enriquecimento**
- [ ] Parity audit: venda do DB == soma dos gateways via API, antes de virar a chave no treino.

### Fase 3 — Leads (`leads`)
- Backfill **único** do histórico estático: Sheets backup, Railway antigo (jan–mai), Railway novo (congelado ~28.575).
- Ongoing (sob demanda): ledger `registros_ml` (live) + Sheets produção.
- Treino e validação leem leads pelo repositório.
- Parity audit coluna-a-coluna contra o pull atual.

### Fase 4 — Feature store de verdade (TRAVADA)
- Só depois de point-in-time provado: materializar features via o *mesmo* `src/core/`, com parity audit como gate de promoção.

---

## Backlog absorvido por esta frente

- `projeto_sqlite_local_analise` (memória) — o "SQLite local para análises ad-hoc" era o precursor disto em escala menor; esta frente o supersede.

---

## Estado pendente — o que verificar ao retomar

1. **DDL já foi aplicado no Cloud SQL?** ✅ SIM (24/06). `\dt analytics.*` lista as 5 tabelas. Próxima ação é a Fase 1.
2. **Helper de conexão `analytics` existe?** (`src/data/analytics_connection.py` ou equivalente).
3. **Verificações sanitárias antes de qualquer virada de consumidor:** parity audit da fase correspondente passou?

---

## Documentos relacionados

- `docs/REFATOR_MONITORAMENTO_CAMADA_ACESSO.md` — a camada `src/data/` que esta frente estende.
- `docs/PLANO_LEDGER_CLOUDSQL.md` — precedente de criar database no Cloud SQL (Etapa 0 do ledger).
- `api/db/analytics_schema.sql` — o DDL desta frente.
