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

**Executado em 15/02/2026**. Webhook agora recebe dados da pesquisa, gera score ML em tempo real e envia CAPI automaticamente.

**`V2/api/database.py`** - ✅ Colunas adicionadas:
- 11 campos de pesquisa (genero, idade, ocupacao, etc.)
- 3 campos ML (lead_score, decil, scored_at)

**`V2/api/app.py`** - ✅ Lógica implementada:
- `LeadCaptureRequest`: recebe dados da pesquisa
- Após salvar lead: SE tem dados pesquisa → scoring ML + CAPI
- Reutiliza `pipeline.predictor.predict()` e `send_batch_events()`
- Apps Script **não é mais necessário** (pode ser desativado)

### 3. Frontend (Dual Write)

**Página 2 JavaScript** - Enviar para AMBOS:
```javascript
const data = { email, name, genero, idade, ... };

// Antigo (fallback)
fetch('https://n8n-webhook.../fantasma_onboarding', {...});

// Novo (principal)
fetch('https://smart-ads-api.../webhook/lead_capture', {...});
```

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