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
    df = df_leads.copy()

    # 1. Encontrar data máxima das vendas
    if 'data' in df_vendas.columns:
        logger.debug(f"  DEBUG: Tipo da coluna 'data': {df_vendas['data'].dtype}")
        logger.debug(f"  DEBUG: Valores não-nulos em 'data': {df_vendas['data'].notna().sum()}/{len(df_vendas)}")
        logger.debug(f"  DEBUG: Max ANTES da conversão: {df_vendas['data'].max()}")
        df_vendas['data'] = pd.to_datetime(df_vendas['data'], errors='coerce', dayfirst=True)
        logger.debug(f"  DEBUG: Max DEPOIS da conversão: {df_vendas['data'].max()}")
        data_max_vendas = df_vendas['data'].max()
    elif 'Data' in df_vendas.columns:
        df_vendas['Data'] = pd.to_datetime(df_vendas['Data'], errors='coerce', dayfirst=True)
        data_max_vendas = df_vendas['Data'].max()
    else:
        raise ValueError("Coluna de data não encontrada em vendas")

    # 2. Calcular data limite dos leads
    data_limite_leads = data_max_vendas - pd.Timedelta(days=janela_dias)

    logger.info(f"  Data limite dos leads (último dia de venda): {data_max_vendas.strftime('%Y-%m-%d')} - {janela_dias} dias = {data_limite_leads.strftime('%Y-%m-%d')}")

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

    logger.info(f"  Antes do filtro: {total_antes:,} leads, {target_antes:,} target=1 ({target_antes/total_antes*100:.2f}%)")

    # 5. Filtrar leads
    # Lógica correta: manter leads até data_limite OU que já converteram (target=1)
    # Remover apenas: leads com target=0 após data_limite (potenciais falsos negativos)
    df_filtrado = df[(df['Data'] <= data_limite_leads) | (df['target'] == 1)].copy()

    # 6. Estatísticas depois
    total_depois = len(df_filtrado)
    target_depois = df_filtrado['target'].sum() if 'target' in df_filtrado.columns else 0
    data_max_depois = df_filtrado['Data'].max()

    leads_removidos = total_antes - total_depois

    logger.info(f"  Depois do filtro: {total_depois:,} leads, {target_depois:,} target=1 ({target_depois/total_depois*100:.2f}%)")
    logger.info(f"  Leads removidos: {leads_removidos:,} ({leads_removidos/total_antes*100:.1f}%)")
    logger.info("")


    return df_filtrado
