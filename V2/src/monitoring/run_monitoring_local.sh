#!/bin/bash
# =============================================================================
# Script para executar monitoramento localmente com acesso PostgreSQL
# =============================================================================

set -e  # Exit on error

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🔌 Iniciando Cloud SQL Proxy...${NC}"

# Iniciar Cloud SQL Proxy em background
cloud-sql-proxy smart-ads-451319:us-central1:smart-ads-db &
PROXY_PID=$!

# Função para matar o proxy ao sair
cleanup() {
    echo -e "\n${YELLOW}🔌 Encerrando Cloud SQL Proxy (PID: $PROXY_PID)...${NC}"
    kill $PROXY_PID 2>/dev/null || true
    wait $PROXY_PID 2>/dev/null || true
    echo -e "${GREEN}✅ Cloud SQL Proxy encerrado${NC}"
}

# Registrar cleanup para execução ao sair
trap cleanup EXIT INT TERM

# Aguardar Cloud SQL Proxy ficar pronto
echo -e "${YELLOW}⏳ Aguardando Cloud SQL Proxy ficar pronto...${NC}"
sleep 3

# Verificar se proxy está rodando
if ! kill -0 $PROXY_PID 2>/dev/null; then
    echo -e "${RED}❌ Erro: Cloud SQL Proxy falhou ao iniciar${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Cloud SQL Proxy pronto (PID: $PROXY_PID)${NC}\n"

# Configurar variáveis de ambiente para PostgreSQL (mesmas do Cloud Run)
export DB_HOST=127.0.0.1
export DB_PORT=5432
export DB_NAME=smart_ads
export DB_USER=postgres
export DB_PASSWORD=SmartAds2025!

# Executar monitoramento
python -c "
import sys
import os
import yaml

# Adicionar diretório ao path
sys.path.insert(0, os.path.dirname(os.path.abspath('__file__')))

from src.monitoring.orchestrator import MonitoringOrchestrator
from api.app import fetch_leads_from_sheets, get_db

# Buscar leads do Google Sheets
print('🔍 Buscando leads do Google Sheets...')
leads_data = fetch_leads_from_sheets(hours=12)
print(f'✅ {len(leads_data)} leads encontrados\n')

# Obter model_path do modelo ativo
with open('configs/active_model.yaml', 'r') as f:
    config = yaml.safe_load(f)
    model_path = config['active_model']['model_path']

# Garantir path absoluto
if not os.path.isabs(model_path):
    model_path = os.path.join(os.getcwd(), model_path)

print(f'📂 Usando modelo: {model_path}\n')

# Obter sessão do banco (usa get_db do app.py)
db = next(get_db())

try:
    # Inicializar orquestrador
    orchestrator = MonitoringOrchestrator(model_path=model_path, db=db)

    # Executar checks
    result = orchestrator.run_daily_check(leads_data)

    # Mostrar resumo
    print('\n' + '='*80)
    print('RESULTADO DO MONITORAMENTO')
    print('='*80)
    print(f'Total de alertas: {result[\"total_alerts\"]}')
    print(f'Por severidade: HIGH={result[\"alerts_by_severity\"][\"HIGH\"]}, MEDIUM={result[\"alerts_by_severity\"][\"MEDIUM\"]}, LOW={result[\"alerts_by_severity\"][\"LOW\"]}')
    print(f'Por categoria: data_quality={result[\"alerts_by_category\"][\"data_quality\"]}, operational={result[\"alerts_by_category\"][\"operational\"]}, capi_quality={result[\"alerts_by_category\"][\"capi_quality\"]}')
    print('='*80)

finally:
    db.close()
"
