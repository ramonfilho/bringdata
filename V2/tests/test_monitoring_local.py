"""
Script para testar pipeline de monitoramento localmente usando Google Sheets API.

Testa:
1. Busca de dados do Google Sheets via API
2. Função calculate_missing_rate() centralizada
3. DataQualityMonitor com dados reais

Uso:
    python tests/test_monitoring_local.py
"""

import sys
import os
from pathlib import Path

# Adicionar src ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta
import pandas as pd
from src.validation.data_loader import LeadDataLoader
from src.monitoring.data_quality import DataQualityMonitor, calculate_missing_rate
from src.retrain.data_validation import get_active_model_path


def test_calculate_missing_rate():
    """Teste unitário da função calculate_missing_rate."""
    print("="*80)
    print("1️⃣  TESTE UNITÁRIO: calculate_missing_rate()")
    print("="*80)

    # Criar dados de teste
    df_teste = pd.DataFrame({
        'col_com_nan': [1, None, 3, None, 5],           # 40% missing (2/5)
        'col_com_string_vazia': ['a', '', 'c', '  ', 'd'],  # 40% missing (2/5)
        'col_mista': [1, None, 3, '', 5],              # Numérico com None
        'col_ok': [1, 2, 3, 4, 5]                      # 0% missing
    })

    print(f"\n📊 Dataset de teste: {len(df_teste)} registros")
    print(df_teste)

    # Testar função
    print(f"\n📈 Resultados:")
    for col in df_teste.columns:
        missing_rate = calculate_missing_rate(df_teste, col)
        print(f"   {col:<25} {missing_rate*100:>6.1f}% missing")

    # Validação
    assert calculate_missing_rate(df_teste, 'col_com_nan') == 0.4
    assert calculate_missing_rate(df_teste, 'col_com_string_vazia') == 0.4
    assert calculate_missing_rate(df_teste, 'col_ok') == 0.0

    print(f"\n✅ Teste passou! Função calculate_missing_rate() funciona corretamente.\n")


# `test_monitoring_with_sheets_api` foi REMOVIDO em 08/08/2026, junto com a fonte que
# ele exercitava. Ele pedia as últimas 48h de uma planilha do Google que parou de ser
# atualizada em 27/03/2026 — recebia zero linha e falhava. E o monitoramento deixou de
# ler planilha nesta mesma mudança: score médio, %D9 e %D10 agora saem de
# `registros_ml`, o ledger vivo. Testar o caminho antigo passou a testar o que não
# existe. O teste unitário acima (taxa de ausência) continua e não depende de rede.

if __name__ == '__main__':
    print("\n")
    print("="*80)
    print("🧪 TESTE LOCAL DO PIPELINE DE MONITORAMENTO")
    print("="*80)
    print(f"Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    # Teste 1: Função isolada
    test_calculate_missing_rate()

    # Teste 2: Monitoramento completo
    test_monitoring_with_sheets_api()

    print("="*80)
    print("✅ TODOS OS TESTES PASSARAM!")
    print("="*80)
    print()
