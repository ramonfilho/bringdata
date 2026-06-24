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
| Onde mora | **Mesma instância do `ledger`**, database/schema `analytics` separado | Isola escrita OLTP do consumer Pub/Sub da leitura analítica pesada do treino. |

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

### Fase 0 — Fundação ◐ EM ANDAMENTO
- [x] Worktree + branch.
- [x] DDL das tabelas: `api/db/analytics_schema.sql` (leads, sales, validation_runs/metrics, meta_insights).
- [ ] **Rodar o DDL contra o Cloud SQL** (database/schema `analytics`) — *único passo que toca infra; pede "go" + verificar estado live antes.*
- [ ] Helper de conexão `analytics` (espelha `ledger_connection.py`).

### Fase 1 — Resultados (risco mínimo, valor imediato, zero implicação de paridade)
- Writer da validação grava em `validation_runs`/`validation_metrics` **além** do `.xlsx`.
- `meta_insights` populado pelo loader da Meta.
- Arquivo continua como export sob demanda.

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

1. **DDL já foi aplicado no Cloud SQL?** `\dt analytics.*` deve listar as 5 tabelas. Se não, é a próxima ação (Fase 0, pede "go").
2. **Helper de conexão `analytics` existe?** (`src/data/analytics_connection.py` ou equivalente).
3. **Verificações sanitárias antes de qualquer virada de consumidor:** parity audit da fase correspondente passou?

---

## Documentos relacionados

- `docs/REFATOR_MONITORAMENTO_CAMADA_ACESSO.md` — a camada `src/data/` que esta frente estende.
- `docs/PLANO_LEDGER_CLOUDSQL.md` — precedente de criar database no Cloud SQL (Etapa 0 do ledger).
- `api/db/analytics_schema.sql` — o DDL desta frente.
