# Reconstrução da fonte única de leads (`train_unified`) — metodologia e legenda

> **Regra de ouro (governança de dados deste projeto):** toda modificação de dado feita por ETL
> vive num **script versionado com CLI** (`python -m src.data.leads_unify ...`), **nunca** num
> comando de terminal solto. Cada transformação (rename de coluna, mapa de chave, dedup, janela)
> é registrada e comentada no script. Reconstruir produz auditoria reproduzível. Esta regra existe
> porque uma migração camelCase→snake_case feita "no terminal" deixou dados sem rastro de origem.

Construída sob a skill `/data-architect`. Documento autoritativo da reconstrução.

---

## 1. Legenda das fontes (o que cada nome significa)

### Fontes ATÔMICAS (origem real de um lead+pesquisa — é destas que se reconstrói)

| nome no provenance | o que é | onde vive | janela | survey |
|---|---|---|---|---|
| `registros_ml` | **Ledger ML**: o consumer Pub/Sub grava aqui cada lead já scoreado (decil, score, variante A/B). Nasceu no Railway em 23/05/2026 após a migração de **polling Railway → Pub/Sub**; hoje no **Cloud SQL**. | Cloud SQL `public.registros_ml` | 23/05/26 → hoje | camelCase, data em `created_at` |
| `Lead` | **Tabela `Lead` do front Railway** (a tabela de leads do sistema antigo do cliente). Tem `pesquisa` (jsonb). Espelhada no Cloud SQL como `lead_legado` (renomeada camelCase→snake na cópia). | Railway `Lead` = Cloud SQL `public.lead_legado` | 18/02/26 → 14/06/26 | `pesquisa` jsonb (camelCase) |
| `lead_surveys` | **Tabela transitória de pesquisa** usada durante a migração de schema (11–17/05). Survey em colunas. 1.624 linhas; 1.613 entram (11 dedup). | Railway `lead_surveys` → **espelhada** pelo próprio script em Cloud SQL `public.lead_surveys_stg` (mirror atômico + lossless) | 12–21/05/26 | colunas camelCase |
| `sheet:Producao` / `sheet:Backup` | **Google Sheets** que o front escrevia: Produção (`1VYti8jX…`) e Backup (`1OqNYA5…`). Fontes mortas (não atualizadas desde o ledger). Os dados sobrevivem dentro do `train_pesquisa`. | só dentro de `analytics.leads` source=`train_pesquisa` (`arquivo_origem='[API] Leads Google Sheets'`) | histórico → ~jan/26 | texto-pergunta |
| `xlsx:<arquivo>` | **Exports locais em Excel por lançamento** (LF): `[LF01-04] Leads_Pesquisa.xlsx`, `Lead Score LF 25/26/27.xlsx`, etc. Exports manuais de pesquisa/score por LF. | só dentro de `train_pesquisa` (`arquivo_origem='*.xlsx'`) | dez/24 → ~out/25 | texto-pergunta |

### Tabelas DERIVADAS (blends — NÃO usar como fonte; decompor nas atômicas acima)

| nome | o que é | por que NÃO usar |
|---|---|---|
| `leads_historico` | Consolidação derivada gerada em **23/06/2026** a partir de `lead_legado` (140k) + `planilha` (37k) + `registros_ml` (26k). | É blend de outras fontes → proveniência circular e dupla contagem. |
| `train_pesquisa` | Dump do loader de treino: `[Railway] Leads` (130k, = a `Lead`) + Google Sheets (60k) + xlsx (77k). | Blend. Só extrair dele os pedaços **Sheets** e **xlsx** (que não existem em outro lugar); o pedaço `[Railway] Leads` é a `Lead` (usar a `Lead` direto). |

### Fontes DESCARTADAS (com prova)

| nome | linhas | por que descartar |
|---|---|---|
| `leads_capi` | 299.816 | Colunas de survey **0% preenchidas** (vestígio). Tem identidade/fbp-fbc, mas **não é fonte de pesquisa**. |

---

## 2. Inventário Railway × Cloud SQL (o que ainda só existe no Railway)

No Cloud SQL (`ledger`) só temos: `registros_ml` (ledger migrado), `lead_legado` (= `Lead`),
`leads_historico` (derivada) e o schema `analytics`. **O front inteiro do cliente segue só no Railway:**

| tabela Railway | linhas | categoria | no Cloud SQL? |
|---|---|---|---|
| `Lead` | 142.943 | pesquisa | ✅ (`lead_legado`) |
| `lead_surveys` | 1.624 | pesquisa | ⚠️ espelhada em `public.lead_surveys_stg` pelo script |
| `leads_capi` | 299.816 | identidade (survey vestigial) | ❌ |
| `Client` | 82.519 | registro do lead (isBuyer, fbp/fbc, device, hasComputer) | ❌ |
| `Activity` | 142.970 | log de eventos do lead | ❌ |
| `UTMTracking` | 86.167 | histórico de UTM por lead | ❌ |
| `whatsapp_group_joins` | 112.825 | entradas em grupo (telefone, grupo) | ❌ |
| `ClientTag` / `LeadsClient` / `Tag` | 52.367 / 6.076 / 3.112 | tags/registro secundário | ❌ |
| `ApiKey` `User` `_prisma_migrations` `ad_to_adset_map` `cpl_adset` `integration_logs` | — | infra/operacional (não-lead) | ❌ |

> Para a reconstrução de **pesquisa** só importam as fontes atômicas da seção 1. As tabelas de
> identidade (Client/UTMTracking/Activity/whatsapp_group_joins) ficam registradas aqui para um
> espelhamento futuro, mas não entram no `train_unified` (não carregam pesquisa).

---

## 3. Metodologia de integridade (lei de conservação)

A reconstrução obedece, **por fonte**, à identidade (`na_fonte` = linhas físicas da fonte):

```
na_fonte  =  excl_data  +  excl_email  +  deduplicadas  +  incluídas
```

`excl_data` = data nula / fora do padrão ISO; `excl_email` = sem email. Cada categoria é contável,
não-negativa, e tem motivo. Nenhuma linha "some". O write **aborta** se alguma fonte não fechar.

1. **Proveniência por linha (sidecar).** A linhagem NÃO vai como coluna na `analytics.leads` — o
   usuário `ledger_app` **não é dono** dessa tabela (dono = `postgres`), então não pode `ALTER`; e
   embutir no `survey_responses` jsonb arriscaria poluir features de treino. Vai numa tabela-sidecar
   **`analytics.leads_provenance`** (`source`, `event_id`, `provenance`, `prio`, `ingested_at`),
   1:1 com `leads` por `event_id`. Cada linha é rastreável à fonte atômica real
   (`registros_ml` / `Lead` / `lead_surveys` / `sheet:<nome>` / `xlsx:<arquivo>`).
2. **Dedup determinístico e auditável.** Chave natural = (`lower(email)`, dia da captação). Em
   empate, vence a prioridade: `registros_ml` > `Lead` > `lead_surveys` > `sheet` > `xlsx`
   (produção > front > transitória > planilha > export). Quem perde é contado como `deduplicada`.
3. **Snapshot congelado (REPEATABLE READ).** `registros_ml` é tabela VIVA (produção insere ~1/min).
   Medir `na_fonte`, `in_branch` e `incluídas` em queries separadas dava `deduplicadas = -1` (linha
   nova chegava entre as medições). O write roda em `BEGIN ISOLATION LEVEL REPEATABLE READ`,
   materializa `_src` (pré-dedup) e `_u` (dedup) e mede TUDO no mesmo snapshot → conservação exata.
4. **Auditoria emitida pelo write, não recomputada.** A reconciliação é gravada em
   `analytics.leads_unified_audit` **dentro da mesma transação** que grava `leads`/`leads_provenance`
   (mesmo snapshot). `--audit` é só um verificador READ-ONLY que lê a última reconciliação e confere
   `leads == linhagem == Σ incluídas`. Não recomputa sobre fonte viva (seria inconsistente).
5. **Idempotência e atomicidade.** Re-rodar produz output idêntico (tie-break determinístico). Tudo
   numa transação: falha → rollback, `train_unified` antigo intacto. Rótulo próprio
   (`source='train_unified'`) → rollback manual = `DELETE WHERE source='train_unified'` (+ sidecar).
6. **Mirror atômico + lossless.** `lead_surveys` (Railway) → `public.lead_surveys_stg` em transação
   (kill no meio = rollback, nunca tabela parcial), em lotes, com assert `staging == origem`.
7. **Tudo por script.** `python -m src.data.leads_unify [--write] [--audit] [--skip-mirror]`.
   Nunca inline no terminal.

---

## 3a. Resultado da reconstrução (execução de 29/06/2026)

`source='train_unified'` em `analytics.leads`: **318.229 linhas**, linhagem 1:1 em
`analytics.leads_provenance` (318.229), `conserva_tudo = true`, `tudo_bate = true`. Cobertura
temporal contínua **2024-12 → 2026-06** (sem gaps); fill rate de `idade` ~100% em toda a série.

| prio | fonte | na_fonte | excl_data | excl_email | deduplicadas | incluídas |
|---|---|---|---|---|---|---|
| 1 | `registros_ml` | 37.325 | 0 | 0 | 2 | 37.323 |
| 2 | `Lead` | 142.943 | 0 | 51 | 916 | 141.976 |
| 3 | `lead_surveys` | 1.624 | 0 | 0 | 11 | 1.613 |
| 4 | `sheet:*` | 59.726 | 0 | 0 | 0 | 59.726 |
| 5 | `xlsx:*` | 77.703 | 2 | 110 | 0 | 77.591 |
| | **total** | | | | | **318.229** |

---

## 4. Procedência cruzada conhecida (armadilhas)

- A **`Lead`** aparece em três lugares: a tabela `Lead` (Railway), o `lead_legado` (cópia Cloud SQL)
  e dentro do `train_pesquisa` como `[Railway] Leads` (puxada via API). **Usar só `lead_legado`**;
  ignorar a cópia dentro do `train_pesquisa` (senão dupla contagem).
- O **`registros_ml`** também foi parcialmente copiado pra dentro do `leads_historico` e do
  `train_pesquisa`. **Usar só o `registros_ml` cru**; ignorar as cópias.
- **Datas:** `registros_ml` usa `created_at` (a chave `'Data'` no jsonb é nula no cru); `Lead` usa
  `data`; `lead_surveys` usa `submittedAt`. Normalizar todas pra ISO tz-naive `YYYY-MM-DD"T"HH24:MI:SS`.

*Identificador histórico: frente de unificação de leads (jun/2026), pós-descoberta de que o treino
lia do Google Sheets morto.*
