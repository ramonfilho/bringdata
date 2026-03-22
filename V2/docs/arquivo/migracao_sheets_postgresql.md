## ✅ CAMINHO B — Railway PostgreSQL Polling (19/02/2026)

### Arquitetura de dois caminhos

O sistema roda dois caminhos em paralelo:

**Caminho A: Google Sheets (Apps Script)** — clientes sem banco SQL
```
Google Sheets → Apps Script (polling 5min)
  → POST /predict/batch       (ML scoring)
  → escreve score no Sheets
  → POST /capi/process_daily_batch (Meta CAPI)
```

**Caminho B: Railway PostgreSQL (Python polling)** — clientes com banco SQL
```
Frontend (Prisma) → Railway PostgreSQL
                         ↓
              Cloud Scheduler (*/5min)
              POST /railway/process-pending
                         ↓
              SELECT * FROM "Lead" WHERE "leadScore" IS NULL
                         ↓
              railway_mapping.py
              pesquisa JSONB (camelCase) → formato Google Sheets
                         ↓
              ML pipeline → lead_score + decil
                         ↓
              UPDATE "Lead" SET "leadScore", "decil", "updatedAt"
                         ↓
              Meta CAPI → UPDATE "Lead" SET "capiSentAt", "capiStatus"
```

Decisão de usar polling (não webhook): webhook requer coordenação com dev externo
e cria acoplamento. LISTEN/NOTIFY requer processo persistente no Cloud Run.
O polling funciona como safety net — qualquer lead perdido é capturado na próxima execução.

### Implementação

| Artefato | Arquivo |
|---|---|
| Endpoint `POST /railway/process-pending` | `V2/api/app.py` |
| Mapeamento pesquisa JSONB → colunas Sheets | `V2/api/railway_mapping.py` |
| Variáveis `RAILWAY_DB_*` no deploy | `V2/api/lib/config.sh` |
| Cloud Scheduler job `railway-polling` | us-central1, `*/5 * * * *` |

### Resultado do rollout (19/02/2026)

- Backlog inicial de 405 leads processados em ~4 minutos
- 436 eventos CAPI enviados com 0 erros
- Meta respondeu `events_received: 1, events_rejected: 0` em 100% dos envios
- Scheduler rodando a cada 5 minutos, processando leads em tempo real

### Deduplicação entre Caminho A e Caminho B

Investigação em 19/02/2026: Railway e Sheets capturam **populações distintas** —
dois formulários diferentes na mesma landing page (`parabens-psq-devf-v2`).
Overlap de emails = 0% no período analisado (404 Sheets vs 426 Railway, mesmo período).
Deduplicação cross-path não é necessária para o cliente atual (DevClub).

### Colunas Railway `capiSentAt` e `capiStatus`

Colunas já existem na tabela `Lead` via Prisma migration (nullable).
O endpoint as popula após cada envio CAPI:
- `capiSentAt`: timestamp do envio bem-sucedido
- `capiStatus`: `'success'` ou `'error'`

---

## ✅ INVESTIGAÇÃO CONCLUÍDA - Scores Históricos (16/02/2026)

**Deploy 00202-4wl (30/01 14:35)**: Modelo `20260117_123914` → `20260130_090227`

**Testes:**
- Janeiro (13-27/01): -5.30% diferença
- Fevereiro (01-05/02): -0.29% diferença ✅
- Código 30/01 vs atual: IDÊNTICOS (ambos -2.93%)

**Conclusão**: Commits 15/02 não causaram regressão. Sistema estável desde 30/01

## ✅ WEBHOOK VALIDADO - End-to-End (16/02/2026)

**Teste:** 15 leads reais fev/26 via `/webhook/lead_capture` + `/webhook/update_survey`

**Resultados:**
- 15/15 processados (0 erros)
- Diferença média: **+0.04%**
- 13/15 < 5% diferença

**Fix:** `'utm_content': 'Content'` adicionado ao mapeamento (app.py:861)

**Status:** Backend pronto para produção. Próximo passo: alteração front-end Página 2

---

## 🚨 BUG CRÍTICO ENCONTRADO - Scoring ML (15/02/2026)

**Problema:** Scores gerados pela API PostgreSQL são 41% menores que os esperados (lead D10 do Sheets recalculado vira D7). **Causa raiz:** O pipeline de encoding (`apply_categorical_encoding`) usa `pd.get_dummies()` que só cria colunas one-hot para valores presentes nos dados. Com 1 único lead, cada campo categórico tem apenas 1 valor, então cria apenas 1 coluna em vez de todas as possibilidades (ex: `ocupacao="Sou CLT"` cria só `ocupacao_sou_clt`, mas modelo espera também `ocupacao_sou_autonomo`, `ocupacao_aposentado`, etc.). Resultado: 36 de 52 features ficam ausentes (preenchidas com 0), causando scores drasticamente errados. **Solução em andamento:** Modificar `encoding.py` para usar Feature Registry (`model_input_features.ordered_list`) do MLflow e garantir que TODAS as 52 features esperadas sejam criadas, mesmo que não apareçam nos dados de predição. Isso exige também adicionar campos faltantes no mapeamento PostgreSQL→Sheets (`created_at`, `utm_source`, `utm_medium`, `utm_term`, `tem_comp`) que não estavam sendo passados para o pipeline. **Status:** Testando localmente antes de deploy em produção.

---

## ✅ RESOLUÇÃO - Deploy Modelo 30/01/2026 (15/02/2026)

**Situação:** Modelo de 30/01/2026 (`files/20260130_090227`, 52 features) foi deployado como **modelo principal** em produção.

**Arquivo:** `V2/api/app.py`

**O que foi feito:**
1. ✅ Deploy do modelo 30/01 como único modelo ativo (`active_model.yaml` → `model_path: files/20260130_090227`)
2. ✅ Endpoint `/webhook/update_survey` implementado (Página 2 - Pesquisa)
3. ✅ **Limpeza completa** do código legacy (15/02/2026):
   - Removida variável `legacy_pipeline`
   - Removida flag `USE_LEGACY_SCORING`
   - Removida função `initialize_legacy_pipeline()`
   - Removidos endpoints `/predict/legacy` e `/model/legacy/info`
   - Simplificado `/webhook/update_survey` para usar pipeline normal

**Status:** ✅ **EM PRODUÇÃO** - Modelo único, código limpo

**Próximos passos:**
- Quando novo modelo MLflow estiver pronto, atualizar `active_model.yaml` com novo `model_path`
- Deploy automático via `deploy_capi.sh`

---

## URLs das Landing Pages

**Página 1 - Inscrição (captura email, nome, phone, fbp, fbc):**
https://lp.devclub.com.br/inscricao-lf-v2-crt/

**Página 2 - Pesquisa (captura dados da pesquisa):**
https://lp.devclub.com.br/parabens-psq-devf-v2/?nome=ramon&email=ramonfceo%40gmail.com&telefone=%2B5537999610179&computador=SIM

---

### 1. SQL ✅ COMPLETO

**Executado em 14/02/2026** via cloud-sql-proxy. Adicionadas 14 colunas (dados pesquisa + ML scores). Nomes normalizados no banco (ex: "O seu gênero:" → `genero`). Mapeamento Sheets→PostgreSQL será feito no Python (Passo 2). Senha: `SmartAds2026DB!` (em `lib/config.sh`).

```sql
-- Migration executada com sucesso
ALTER TABLE leads_capi ADD COLUMN IF NOT EXISTS
  genero VARCHAR(50), idade VARCHAR(50), ocupacao VARCHAR(255),
  faixa_salarial VARCHAR(100), cartao_credito VARCHAR(50),
  interesse_evento TEXT, estudou_programacao VARCHAR(50),
  pretende_faculdade VARCHAR(100), investiu_curso_online VARCHAR(50),
  interesse_programacao TEXT, cidade VARCHAR(100),
  lead_score DECIMAL(10,8), decil VARCHAR(10), scored_at TIMESTAMP;
```

### 2. Backend Python ✅ COMPLETO

**Status:** Implementada **Abordagem 3** - Endpoint dedicado para Página 2.

**Implementação (15/02/2026):**

**`V2/api/database.py`** - ✅ Pronto:
- 11 campos de pesquisa (genero, idade, ocupacao, etc.)
- 3 campos ML (lead_score, decil, scored_at)

**`V2/api/app.py`** - ✅ Implementado:

**Endpoint 1: `/webhook/lead_capture` (Página 1 - Inscrição)**
```python
# - Recebe dados básicos (email, nome, phone, fbp, fbc)
# - CRIA lead no PostgreSQL
# - NÃO faz scoring (dados de pesquisa ainda não existem)
# - Ignora apenas página "parabens" antiga (sem v2)
```

**Endpoint 2: `/webhook/update_survey` (NOVO - Página 2 - Pesquisa)**
```python
# - Recebe email + dados da pesquisa
# - BUSCA lead existente por email
# - ATUALIZA com dados da pesquisa (11 campos)
# - Gera score ML + calcula decil
# - Envia para CAPI com score
# - Retorna score + decil
```

**Classes Pydantic criadas:**
- `LeadCaptureRequest` - Página 1 (dados básicos)
- `UpdateSurveyRequest` - Página 2 (email + pesquisa)

### 3. Frontend - Página 2 JavaScript ✅ OBSOLETO — Railway já em produção

**Arquivo:** `V2/docs/pagina2_codigo_modificado.js` ✅

**Estratégia:** Shadow Deploy (dual write)
- ✅ MANTÉM envio para Google Sheets (form.action original)
- ✅ ADICIONA envio paralelo para PostgreSQL (/webhook/update_survey)
- ✅ Ambos executam simultaneamente
- ✅ Falhas não bloqueiam UX

**O que muda:**
- Substitui função `submitFormData()` existente
- Coleta manual de 10 campos (steps 7 e 10 ignorados - colunas indevidas)
- NÃO envia fbp/fbc/UTMs (já capturados na Página 1)

**Como testar após deploy:**
1. Console (F12): deve aparecer logs `[SHADOW DEPLOY]`, `[1/2] Google Sheets`, `[2/2] PostgreSQL`
2. Network (F12): deve ter 2 requests (Sheets + /webhook/update_survey → Status 200)
3. UX: loading funciona, tela final aparece normalmente

**Landing Page:** https://lp.devclub.com.br/parabens-psq-devf-v2/

---

## Monitoramento

```sql
-- Últimas 24h
SELECT COUNT(*) total, COUNT(lead_score) com_score,
       COUNT(genero) com_pesquisa
FROM leads_capi
WHERE created_at > NOW() - INTERVAL '24 hours';
```

**Endpoint:** `/admin/migration_status` (comparar PG vs Sheets)

---

## Rollback

**Fase 1:** Manter dual write, corrigir bugs
**Fase 3:** Religar N8N/Apps Script (2 min)

---

## Comandos

```bash
# SQL
gcloud sql connect smart-ads-db --user=postgres --project=smart-ads-451319

# Deploy
gcloud run deploy smart-ads-api --source . --region us-central1

# Logs
gcloud logs tail --filter="resource.type=cloud_run_revision"
```