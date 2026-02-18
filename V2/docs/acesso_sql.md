# Acesso ao Banco PostgreSQL (Cloud SQL)

## Instância
- **Projeto:** smart-ads-451319
- **Instância:** smart-ads-db
- **Região:** us-central1
- **Banco:** smart_ads
- **Usuário:** postgres
- **Senha:** SmartAds2026DB!

## Como Acessar Localmente

O banco não aceita conexão IPv6 direta. Usar **Cloud SQL Proxy v2**:

```bash
# 1. Iniciar proxy (manter em background)
cloud-sql-proxy smart-ads-451319:us-central1:smart-ads-db --port=5432 &
sleep 8  # aguardar proxy autenticar

# 2. Conectar via Python (pg8000 já está no projeto)
python3 << 'EOF'
import pg8000.native
conn = pg8000.native.Connection(
    host='127.0.0.1', port=5432,
    database='smart_ads', user='postgres', password='SmartAds2026DB!'
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
