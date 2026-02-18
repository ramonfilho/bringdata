# Decisões de Arquitetura — Smart Ads Lead Scoring

## Contexto

O sistema suporta dois tipos de clientes:
- **Clientes com banco SQL** (Railway PostgreSQL): frontend Prisma gerencia os leads
- **Clientes sem banco SQL**: leads chegam via Google Sheets

Ambos os caminhos precisam de scoring ML e envio de eventos CAPI para Meta.

---

## Decisão 1 — Dois caminhos de processamento em paralelo

### Caminho A: Google Sheets (Apps Script)
Para clientes sem banco SQL. Permanece ativo e sem alterações.

```
Google Sheets → Apps Script (polling 5min)
  → POST /predict/batch         (ML scoring)
  → escreve score no Sheets
  → POST /capi/process_daily_batch  (Meta CAPI)
```

### Caminho B: Railway PostgreSQL (Python polling)
Para clientes com banco SQL gerenciado pelo frontend.

```
Frontend (Prisma) → Railway PostgreSQL
                         ↓
              Python polling (5min)
              SELECT * FROM "Lead" WHERE "leadScore" IS NULL
                         ↓
              ML pipeline → lead_score + decil
                         ↓
              UPDATE "Lead" SET "leadScore", "decil"
                         ↓
              Meta CAPI (envia eventos)
```

**Os dois caminhos coexistem.** Apps Script não será desligado enquanto houver clientes Sheets.

---

## Decisão 2 — Polling, não webhook

**Escolhido:** Python consulta o Railway a cada 5 minutos buscando leads sem score.

**Alternativas descartadas:**
- *Webhook do frontend*: requer coordenação com desenvolvedor externo, cria acoplamento
- *PostgreSQL LISTEN/NOTIFY*: requer processo persistente no Cloud Run, complexidade sem benefício proporcional

**Fallback:** o polling já serve como safety net — qualquer lead não processado é capturado na próxima execução.

---

## Decisão 3 — Python é responsável pelo UPDATE no Railway

Após calcular o score, o Python faz:
```sql
UPDATE "Lead"
SET "leadScore" = <valor>, "decil" = <valor>, "updatedAt" = NOW()
WHERE email = '<email>'
```

As colunas `leadScore` e `decil` já existem na tabela (nullable). O frontend não escreve nessas colunas — é responsabilidade exclusiva do pipeline ML.

---

## Decisão 4 — Estratégia de migração (quando aplicável)

Quando o cliente migrar completamente para Railway:
1. Rodar os dois caminhos em paralelo por 24-48h, comparando scores
2. Confirmar que Railway path produz resultados idênticos ao Sheets path
3. Desligar Apps Script em um único cutover — sem janela de manutenção curta

**Não desabilitar CAPI durante coexistência** — deduplicação por email garante que o mesmo lead não receba evento duplicado.

---

## Pendências (pré-implementação do Caminho B)

- [ ] Inspecionar conteúdo do campo `pesquisa` (JSONB) com o primeiro lead real
- [ ] Criar mapeamento `pesquisa` → nomes de features esperados pelo modelo ML
- [ ] Implementar endpoint/job de polling no `app.py`
- [ ] Adicionar audit trail CAPI na tabela `Lead` (campos `capiSentAt`, `capiStatus`) via Prisma migration
