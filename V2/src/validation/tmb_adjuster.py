"""
[DEPRECADO em 11/05/2026]

Este módulo aplicava um fator agregado de inadimplência TMB (0.6211) sobre
`sale_value`. Foi substituído pela coluna `sale_value_realizado`, calculada em
`src/validation/data_loader.py:combine_sales`, que aplica fatores **por canal**
(GURU_REALIZACAO_FACTOR, HOTMART_REALIZACAO_FACTOR e 1ª parcela para boleto
parcelado TMB/Asaas). Os fatores estão em `api/business_config.py`.

Mantido temporariamente para não quebrar imports antigos. Deve ser removido
após confirmar que nenhum consumidor ainda chama `adjust_revenue_for_tmb` /
`add_adjusted_metrics_to_campaign_stats` / `calculate_overall_adjusted_stats`.

Consumidor canônico do novo fluxo: `total_revenue` em
`src/validation/metrics_calculator.py:calculate_campaign_metrics` agora soma
`sale_value_realizado` em vez de `sale_value`.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Fator de realização TMB baseado em análise de 442 pedidos com 12+ meses
FATOR_TMB_REALISTA = 0.5605  # 56.05%

# Fator baseado em valor conservador de R$ 1.500 por venda
# (ticket médio TMB = R$ 2.200,40)
FATOR_TMB_CONSERVADOR = 0.6817  # 68.17%

# Fator médio (usado nos cenários)
FATOR_TMB_MEDIO = (FATOR_TMB_REALISTA + FATOR_TMB_CONSERVADOR) / 2  # 62.11%


def adjust_revenue_for_tmb(df: pd.DataFrame, sale_value_col='sale_value',
                           sale_origin_col='sale_origin', fator=FATOR_TMB_MEDIO) -> pd.DataFrame:
    """
    Adiciona coluna de receita ajustada por TMB.

    Args:
        df: DataFrame com dados de vendas
        sale_value_col: Nome da coluna com valor da venda
        sale_origin_col: Nome da coluna com origem ('tmb', 'guru')
        fator: Fator de realização TMB (default: média)

    Returns:
        DataFrame com coluna 'sale_value_adjusted' adicionada
    """
    if sale_value_col not in df.columns:
        logger.warning(f" Coluna '{sale_value_col}' não encontrada")
        return df

    if sale_origin_col not in df.columns:
        logger.warning(f" Coluna '{sale_origin_col}' não encontrada")
        df['sale_value_adjusted'] = df[sale_value_col]
        return df

    # Aplicar fator TMB apenas nas vendas TMB
    df['sale_value_adjusted'] = df.apply(
        lambda row: row[sale_value_col] * fator
        if str(row[sale_origin_col]).lower() == 'tmb'
        else row[sale_value_col],
        axis=1
    )

    return df


def add_adjusted_metrics_to_campaign_stats(campaign_stats: pd.DataFrame,
                                           matched_df: pd.DataFrame,
                                           fator=FATOR_TMB_MEDIO) -> pd.DataFrame:
    """
    Adiciona métricas ajustadas por TMB às estatísticas de campanhas.

    Adiciona colunas:
    - total_revenue_adjusted: Receita ajustada por TMB
    - roas_adjusted: ROAS calculado com receita ajustada

    Args:
        campaign_stats: DataFrame com métricas agregadas por campanha
        matched_df: DataFrame com dados de leads matched
        fator: Fator de realização TMB

    Returns:
        campaign_stats com colunas ajustadas adicionadas
    """
    if 'sale_origin' not in matched_df.columns:
        logger.warning(" Coluna 'sale_origin' não encontrada. Ajuste TMB não aplicado.")
        campaign_stats['total_revenue_adjusted'] = campaign_stats['total_revenue']
        campaign_stats['roas_adjusted'] = campaign_stats['roas']
        return campaign_stats

    # Ajustar valores no matched_df
    matched_adjusted = adjust_revenue_for_tmb(matched_df, fator=fator)

    # IMPORTANTE: Extrair campaign_id (15 dígitos) para fazer merge correto
    # Motivo: Nomes de campanhas podem ter sido atualizados (UTMs  Meta API)
    import re
    def extract_campaign_id_15(campaign_name):
        """Extrai primeiros 15 dígitos do campaign_id do nome"""
        if pd.isna(campaign_name):
            return None
        match = re.search(r'1\d{14,}', str(campaign_name))
        if match:
            return match.group(0)[:15]
        return None

    # Adicionar campaign_id_15 aos dois DataFrames
    matched_adjusted['campaign_id_15'] = matched_adjusted['campaign'].apply(extract_campaign_id_15)
    campaign_stats['campaign_id_15'] = campaign_stats['campaign'].apply(extract_campaign_id_15)

    # Agrupar por campaign_id_15 e calcular receita ajustada
    revenue_by_campaign = matched_adjusted[matched_adjusted['converted'] == True].groupby('campaign_id_15').agg({
        'sale_value': 'sum',  # Nominal
        'sale_value_adjusted': 'sum'  # Ajustada
    }).reset_index()

    # Merge com campaign_stats usando campaign_id_15
    campaign_stats = campaign_stats.merge(
        revenue_by_campaign[['campaign_id_15', 'sale_value_adjusted']],
        on='campaign_id_15',
        how='left'
    )

    # Cleanup: remover coluna temporária
    campaign_stats = campaign_stats.drop(columns=['campaign_id_15'])

    # Preencher NaN com 0
    campaign_stats['sale_value_adjusted'] = campaign_stats['sale_value_adjusted'].fillna(0)

    # Renomear para total_revenue_adjusted
    campaign_stats = campaign_stats.rename(columns={'sale_value_adjusted': 'total_revenue_adjusted'})

    # Calcular ROAS ajustado
    campaign_stats['roas_adjusted'] = campaign_stats.apply(
        lambda row: (row['total_revenue_adjusted'] / row['spend']) if row['spend'] > 0 else 0,
        axis=1
    ).round(2)

    logger.info(f"    Métricas ajustadas por TMB adicionadas (fator: {fator:.2%})")

    return campaign_stats


def calculate_overall_adjusted_stats(matched_df: pd.DataFrame,
                                     spend_total: float,
                                     fator=FATOR_TMB_MEDIO) -> dict:
    """
    Calcula estatísticas gerais ajustadas por TMB.

    Returns:
        Dict com métricas nominais e ajustadas
    """
    if 'sale_origin' not in matched_df.columns:
        logger.warning(" Coluna 'sale_origin' não encontrada")
        return {}

    # Ajustar valores
    matched_adjusted = adjust_revenue_for_tmb(matched_df, fator=fator)

    # Filtrar vendas convertidas
    converted = matched_adjusted[matched_adjusted['converted'] == True]

    # Separar por origem
    tmb_vendas = converted[converted['sale_origin'] == 'tmb']
    guru_vendas = converted[converted['sale_origin'] == 'guru']

    # Receitas
    receita_nominal = converted['sale_value'].sum()
    receita_ajustada = converted['sale_value_adjusted'].sum()
    ajuste_total = receita_nominal - receita_ajustada

    receita_tmb_nominal = tmb_vendas['sale_value'].sum()
    receita_tmb_ajustada = tmb_vendas['sale_value_adjusted'].sum()

    receita_guru = guru_vendas['sale_value'].sum()

    # ROAS
    roas_nominal = (receita_nominal / spend_total) if spend_total > 0 else 0
    roas_ajustado = (receita_ajustada / spend_total) if spend_total > 0 else 0

    return {
        'conversoes_total': len(converted),
        'conversoes_tmb': len(tmb_vendas),
        'conversoes_guru': len(guru_vendas),
        'receita_nominal': round(receita_nominal, 2),
        'receita_ajustada': round(receita_ajustada, 2),
        'ajuste_tmb': round(ajuste_total, 2),
        'receita_tmb_nominal': round(receita_tmb_nominal, 2),
        'receita_tmb_ajustada': round(receita_tmb_ajustada, 2),
        'receita_guru': round(receita_guru, 2),
        'roas_nominal': round(roas_nominal, 2),
        'roas_ajustado': round(roas_ajustado, 2),
        'fator_usado': fator
    }
