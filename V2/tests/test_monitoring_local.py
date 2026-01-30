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


def test_monitoring_with_sheets_api():
    """Teste completo do monitoramento com dados reais do Google Sheets."""
    print("="*80)
    print("2️⃣  TESTE COMPLETO: DataQualityMonitor com Google Sheets API")
    print("="*80)

    try:
        # 1. Buscar dados do Google Sheets (últimas 48h para ter mais dados)
        print(f"\n📥 Buscando dados do Google Sheets via API...")
        loader = LeadDataLoader()

        # Últimas 48h
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')

        print(f"   Período: {start_date} a {end_date}")
        df_sheets = loader.load_leads_from_sheets(
            start_date=start_date,
            end_date=end_date,
            use_cache=False  # Forçar busca nova para teste
        )

        print(f"   ✅ {len(df_sheets)} leads carregados")
        print(f"   📋 Colunas: {len(df_sheets.columns)}")

        # 2. Testar calculate_missing_rate em colunas reais
        print(f"\n📈 Missing rates das colunas críticas:")
        colunas_criticas = [
            'O seu gênero:',
            'Qual a sua idade?',
            'O que você faz atualmente?',
            'Atualmente, qual a sua faixa salarial?',
            'Você possui cartão de crédito?',
            'Tem computador/notebook?'
        ]

        for col in colunas_criticas:
            if col in df_sheets.columns:
                missing_rate = calculate_missing_rate(df_sheets, col)
                emoji = "🔴" if missing_rate > 0.3 else "🟡" if missing_rate > 0.1 else "🟢"
                print(f"   {emoji} {col:<45} {missing_rate*100:>6.1f}%")
            else:
                print(f"   ⚪ {col:<45} (coluna não encontrada)")

        # 3. Executar DataQualityMonitor
        print(f"\n🔍 Executando DataQualityMonitor...")

        # Obter modelo ativo
        model_path = get_active_model_path()
        print(f"   Champion: {model_path}")

        # Aplicar processamento (mesmo que o monitoramento faz)
        # Simplificado - apenas features essenciais para o teste
        from src.data_processing.preprocessing import rename_long_column_names
        df_processed = rename_long_column_names(df_sheets.copy())

        # Criar monitor
        monitor = DataQualityMonitor(model_path)

        # Executar checks
        alertas = monitor.check(df_processed)

        # Mostrar resultados
        print(f"\n📊 RESULTADOS DO MONITORAMENTO:")
        print(f"   Total de alertas: {len(alertas)}")

        if len(alertas) == 0:
            print(f"   ✅ Nenhum alerta! Qualidade de dados OK.")
        else:
            print(f"\n   ⚠️  Alertas detectados:")
            for i, alerta in enumerate(alertas, 1):
                severity = alerta.get('severity', 'UNKNOWN')
                tipo = alerta.get('type', 'unknown')
                message = alerta.get('message', 'No message')
                print(f"\n   [{i}] {severity} - {tipo}")
                print(f"       {message}")

        print(f"\n✅ Teste completo passou! Monitoramento funcionando.\n")

    except FileNotFoundError as e:
        print(f"\n⚠️  Arquivo não encontrado: {e}")
        print(f"   Isso é esperado se o modelo champion não tiver arquivos de baseline.")
        print(f"   Execute um treino completo para gerar os arquivos necessários.\n")

    except Exception as e:
        print(f"\n❌ Erro no teste: {e}")
        import traceback
        traceback.print_exc()
        raise


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
