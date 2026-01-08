"""
Módulo para aplicar janela de conversão de 14 dias - PIPELINE DE TREINO.

Remove leads que ainda não tiveram tempo suficiente para converter.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def aplicar_janela_conversao(
    df_leads: pd.DataFrame,
    df_vendas: pd.DataFrame,
    janela_dias: int = 14
) -> pd.DataFrame:
    """
    Remove leads que ainda não tiveram tempo de converter (janela de 14 dias).

    LÓGICA:
    - Lead captado no dia X
    - Lead assiste aulas: 7 dias (X até X+7)
    - Lead pode comprar: mais 7 dias (X+7 até X+14)
    - Total: Lead pode converter até X+14

    Portanto, se a última venda é em 2025-11-04, devemos considerar apenas
    leads até 2025-10-21 (14 dias antes), pois leads posteriores ainda
    não tiveram chance de converter.

    Args:
        df_leads: DataFrame de leads com target
        df_vendas: DataFrame de vendas
        janela_dias: Número de dias da janela de conversão (padrão: 14)

    Returns:
        DataFrame de leads filtrado pela janela de conversão
    """
    print(f"\nAPLICANDO JANELA DE CONVERSÃO ({janela_dias} DIAS)")
    print("=" * 70)

    df = df_leads.copy()

    # 1. Encontrar data máxima das vendas
    if 'data' in df_vendas.columns:
        print(f"\n🔍 DEBUG: Tipo da coluna 'data' ANTES da conversão: {df_vendas['data'].dtype}")
        print(f"🔍 DEBUG: Amostra de valores ANTES: {df_vendas['data'].head(3).tolist()}")
        df_vendas['data'] = pd.to_datetime(df_vendas['data'], errors='coerce', dayfirst=True)
        print(f"🔍 DEBUG: Tipo da coluna 'data' DEPOIS da conversão: {df_vendas['data'].dtype}")
        print(f"🔍 DEBUG: Amostra de valores DEPOIS: {df_vendas['data'].head(3).tolist()}")
        data_max_vendas = df_vendas['data'].max()
        print(f"🔍 DEBUG: Data máxima calculada: {data_max_vendas}\n")
    elif 'Data' in df_vendas.columns:
        df_vendas['Data'] = pd.to_datetime(df_vendas['Data'], errors='coerce', dayfirst=True)
        data_max_vendas = df_vendas['Data'].max()
    else:
        raise ValueError("Coluna de data não encontrada em vendas")

    # 2. Calcular data limite dos leads
    data_limite_leads = data_max_vendas - pd.Timedelta(days=janela_dias)

    print(f"Data máxima das vendas: {data_max_vendas.strftime('%Y-%m-%d')}")
    print(f"Data limite dos leads (vendas - {janela_dias} dias): {data_limite_leads.strftime('%Y-%m-%d')}")

    # 3. Converter data dos leads
    if 'Data' in df.columns:
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True)
    else:
        raise ValueError("Coluna 'Data' não encontrada em leads")

    # 4. Estatísticas antes
    total_antes = len(df)
    target_antes = df['target'].sum() if 'target' in df.columns else 0
    data_min_antes = df['Data'].min()
    data_max_antes = df['Data'].max()

    print(f"\nANTES DO FILTRO:")
    print(f"  Total de leads: {total_antes:,}")
    print(f"  Target=1: {target_antes:,} ({target_antes/total_antes*100:.2f}%)")
    print(f"  Período: {data_min_antes.strftime('%Y-%m-%d')} a {data_max_antes.strftime('%Y-%m-%d')}")

    # 5. Filtrar leads
    # Lógica correta: manter leads até data_limite OU que já converteram (target=1)
    # Remover apenas: leads com target=0 após data_limite (potenciais falsos negativos)
    df_filtrado = df[(df['Data'] <= data_limite_leads) | (df['target'] == 1)].copy()

    # 6. Estatísticas depois
    total_depois = len(df_filtrado)
    target_depois = df_filtrado['target'].sum() if 'target' in df_filtrado.columns else 0
    data_max_depois = df_filtrado['Data'].max()

    leads_removidos = total_antes - total_depois
    dias_removidos = (data_max_antes - data_limite_leads).days

    print(f"\nDEPOIS DO FILTRO:")
    print(f"  Total de leads: {total_depois:,}")
    print(f"  Target=1: {target_depois:,} ({target_depois/total_depois*100:.2f}%)")
    print(f"  Período: {data_min_antes.strftime('%Y-%m-%d')} a {data_max_depois.strftime('%Y-%m-%d')}")

    print(f"\nREMOVIDOS:")
    print(f"  Leads removidos: {leads_removidos:,} ({leads_removidos/total_antes*100:.1f}%)")
    print(f"  Dias removidos: {dias_removidos}")
    print(f"  Target=1 removidos: {target_antes - target_depois:,}")

    print(f"\nRAZÃO: Esses {leads_removidos:,} leads ainda não tiveram {janela_dias} dias")
    print(f"       para converter (última venda em {data_max_vendas.strftime('%Y-%m-%d')})")


    return df_filtrado
