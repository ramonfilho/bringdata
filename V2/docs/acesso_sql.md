# Acesso aos Bancos PostgreSQL

---

## Banco 2 — Railway (novo, produção futura)

### Credenciais

| Campo    | Valor |
|----------|-------|
| HOST     | `shortline.proxy.rlwy.net` |
| PORT     | `11594` |
| USER     | `postgres` |
| PASSWORD | `$RAILWAY_DB_PASSWORD` (ver `.env`) |
| DB       | `railway` |

Conexão pública direta — **sem proxy**.

### Conexão Python

```python
import pg8000.native
import os

conn = pg8000.native.Connection(
    host=os.environ['RAILWAY_DB_HOST'],
    port=int(os.environ['RAILWAY_DB_PORT']),
    database=os.environ['RAILWAY_DB_NAME'],
    user=os.environ['RAILWAY_DB_USER'],
    password=os.environ['RAILWAY_DB_PASSWORD']
)
rows = conn.run('SELECT COUNT(*) FROM "Lead"')
print(rows)
conn.close()
```

### Tabela Principal: `Lead`

Gerenciada pelo Prisma (frontend). Colunas:

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | text | PK |
| `data` | timestamp | Data/hora do lead |
| `hora` | text | Hora formatada |
| `nomeCompleto` | text | Nome |
| `email` | text | Email |
| `telefone` | text | Telefone |
| `pesquisa` | jsonb | Respostas da pesquisa (survey completo) |
| `source` | text | UTM source |
| `campaign` | text | UTM campaign |
| `medium` | text | UTM medium |
| `content` | text | UTM content |
| `term` | text | UTM term |
| `remoteIp` | text | IP do usuário |
| `userAgent` | text | User agent |
| `fbc` | text | Facebook click ID |
| `fbp` | text | Facebook browser ID |
| `pageUrl` | text | URL da página |
| `leadScore` | double | Score ML (preenchido pelo pipeline) |
| `decil` | integer | Decil 1-10 (preenchido pelo pipeline) |
| `createdAt` | timestamp | Criação do registro |
| `updatedAt` | timestamp | Última atualização |

### Queries de Referência

```sql
-- Leads de hoje
SELECT email, "nomeCompleto", "leadScore", decil, "createdAt"
FROM "Lead"
WHERE "createdAt"::date = CURRENT_DATE
ORDER BY "createdAt" DESC;

-- Leads sem score (pendentes de processamento ML)
SELECT COUNT(*) FROM "Lead" WHERE "leadScore" IS NULL;

-- Distribuição por decil
SELECT decil, COUNT(*) as total
FROM "Lead"
WHERE decil IS NOT NULL
GROUP BY decil ORDER BY decil;
```

### Notas
- Tabela usa camelCase (padrão Prisma) — usar aspas duplas nas queries
- `pesquisa` é JSONB com as respostas do formulário de pesquisa
- `leadScore` e `decil` são nullable — preenchidos pelo pipeline ML após chegada do lead

---

## Banco 1 — Cloud SQL GCP (legado)

> ⚠️ **Instância `bring-data-db` foi descomissionada em 25/02/2026.** Banco operacional migrado para Railway (ver "Banco 2" acima). Os comandos abaixo não funcionam mais — mantidos como referência histórica.
>
> A única instância Cloud SQL ativa hoje é `smart-ads-db` (backend MLflow), atualmente parada — ver `operacoes_gcp_custos.md`.

## Instância
- **Projeto:** smart-ads-451319
- **Instância:** bring-data-db
- **Região:** us-central1
- **Banco:** bring_data
- **Usuário:** postgres
- **Senha:** `$CLOUDSQL_PASSWORD` (ver `.env`)

## Como Acessar Localmente

O banco não aceita conexão IPv6 direta. Usar **Cloud SQL Proxy v2**:

```bash
# 1. Iniciar proxy (manter em background)
cloud-sql-proxy smart-ads-451319:us-central1:bring-data-db --port=5432 &
sleep 8  # aguardar proxy autenticar

# 2. Conectar via Python (pg8000 já está no projeto)
python3 << 'EOF'
import pg8000.native, os
conn = pg8000.native.Connection(
    host='127.0.0.1', port=5432,
    database='bring_data', user='postgres',
    password=os.environ['CLOUDSQL_PASSWORD']
)
rows = conn.run('SELECT COUNT(*) FROM leads_capi')
print(rows)
conn.close()
EOF

# 3. Encerrar proxy quando terminar
kill $(pgrep -f cloud-sql-proxy)
```

## Tabela Principal: leads_capi

```sql
-- Leads de hoje
SELECT email, name, genero, lead_score, decil, created_at
FROM leads_capi
WHERE created_at::date = CURRENT_DATE
ORDER BY created_at DESC;

-- Estatísticas
SELECT
    COUNT(*) as total,
    COUNT(genero) as com_pesquisa,
    COUNT(lead_score) as com_score
FROM leads_capi
WHERE created_at::date = CURRENT_DATE;
```

## Notas
- O proxy precisa de **~8 segundos** para autenticar antes de aceitar conexões
- Em produção (Cloud Run), a conexão é via Unix socket automaticamente
- Script de referência: `V2/src/monitoring/run_monitoring_local.sh`
