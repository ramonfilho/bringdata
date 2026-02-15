# Migração: Sheets → PostgreSQL

**Objetivo:** Unificar dados em PostgreSQL (dual write → validação → cutover)
**Status:** Planejamento | **Timeline:** 2-3 meses

---

## Situação Atual

**Problema:** Sheets com 68k/100k linhas, dados fragmentados em 4 sistemas

**Arquitetura:**
```
Formulário → N8N → Sheets (pesquisa) ❌ limite
          → Cloud Run → PostgreSQL (CAPI) ✅
Apps Script → Lê Sheets → Gera scores → Escreve Sheets
```

---

## Arquitetura Alvo

```
Formulário → Cloud Run → PostgreSQL (tudo)
                       → Gera ML scores
                       → Envia CAPI
```

**Eliminados:** N8N, Sheets, Apps Script

---

## Implementação (3 passos)

### 1. SQL (5 min)

```sql
ALTER TABLE leads_capi ADD COLUMN IF NOT EXISTS
  genero VARCHAR(50), idade VARCHAR(50), ocupacao VARCHAR(255),
  faixa_salarial VARCHAR(100), cartao_credito VARCHAR(50),
  interesse_evento TEXT, estudou_programacao VARCHAR(50),
  pretende_faculdade VARCHAR(100), investiu_curso_online VARCHAR(50),
  interesse_programacao TEXT, lead_score DECIMAL(10,8),
  decil VARCHAR(10), scored_at TIMESTAMP;
```

### 2. Backend Python

**`V2/api/database.py`** - Adicionar colunas no model:
```python
genero = Column(String(50))
# ... (todos os campos acima)
```

**`V2/api/app.py`** - Request + Processamento ML:
```python
class LeadCaptureRequest(BaseModel):
    genero: Optional[str] = None
    # ... (todos os campos)

@app.post("/webhook/lead_capture")
async def webhook_lead_capture(...):
    lead = create_lead_capi(db, lead_data.dict())

    # Gerar score ML
    predictor = LeadScoringPredictor(use_active_model=True)
    score = predictor.predict_single(prepare_features(lead))
    lead.lead_score = score['lead_score']
    lead.decil = score['decil']
    db.commit()
```

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

## Fases

| Fase | Duração | Ação |
|------|---------|------|
| 1. Dual Write | 2 sem | Ambos sistemas funcionam |
| 2. Validação | 1 sem | Comparar dados, validar scores |
| 3. Cutover | 1 sem | Desligar Apps Script → N8N |
| 4. Cleanup | 1 mês | Backup Sheets, remover triggers |

---

## Checklist Fase 1

**Backend:**
- [ ] SQL migration
- [ ] Atualizar `database.py` e `app.py`
- [ ] Deploy Cloud Run

**Frontend:**
- [ ] Modificar JS (dual write)
- [ ] Deploy

**Validação:**
- [ ] Teste end-to-end (10 leads)
- [ ] Verificar PostgreSQL + Sheets
- [ ] Monitorar 24h

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

---

**Riscos:** Baixo (zero downtime com dual write)
**Próximo:** Implementar Fase 1
