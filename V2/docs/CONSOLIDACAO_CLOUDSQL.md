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

### Fase 1 — Resultados ◐ EM ANDAMENTO (24/06)
- [x] `src/data/analytics_connection.py` — conexão de leitura/escrita do schema analytics.
- [x] `src/validation/results_store.py` — writer **append-only** (`run_id` com timestamp); mapeia decile/campaign/overall → `validation_runs` + `validation_metrics`. Não calcula nada (recebe as estruturas já computadas).
- [x] Plugado em `validate_ml_performance.py` logo após o Excel salvo, **guardado em try/except** (falha de banco loga alto, não derruba o `.xlsx`).
- [x] Smoke do writer contra o banco real: cabeçalho + 2 decis + 1 campanha + overall, `extra` jsonb, FK cascade. Verde.
- [ ] **Exercitar no próximo run real** de validação (o pipeline pesado puxa Meta/Guru; o bloco roda naturalmente lá — só não foi rodado fim-a-fim ainda).
- [ ] `meta_insights` populado pelo loader da Meta (próximo passo da Fase 1).
- Arquivo `.xlsx` continua como export sob demanda.

### Fase 2 — Vendas (`sales`) — **habilita o enriquecimento de compradores**
- ETL dos gateways (loaders do `data_loader` viram readers do ETL): guru, hotmart, asaas, boletex, hotpay, tmb.
- `SalesRecord` + `SalesRepository`.
- Treino passa a ler vendas pelo repositório (todos os gateways) em vez de só Guru+TMB.
- Parity audit: venda do DB == soma dos gateways via API.

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
