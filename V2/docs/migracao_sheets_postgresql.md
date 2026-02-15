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

### 3. Frontend - Página 2 JavaScript ⚠️ PENDENTE DEPLOY

**Problema identificado:** Inputs do formulário **não têm** atributos `name`, então `FormData` não captura nada.

**Solução implementada:** Modificar `submitFormData()` para coletar respostas manualmente.

**Arquivo criado:** `V2/docs/pagina2_codigo_modificado.js` ✅

**Mudanças principais:**
1. Função `getSelectedAnswer(stepIndex)` - coleta resposta selecionada de cada step
2. Payload completo com 11 campos de pesquisa
3. **Endpoint atualizado:** `/webhook/update_survey` (antes era `/webhook/lead_capture`)
4. Event_id único para Página 2 (diferente da Página 1)

**Próximo passo:** Aplicar código na landing page `https://lp.devclub.com.br/parabens-psq-devf-v2/`

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