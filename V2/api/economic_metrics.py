"""
Módulo de Cálculo de Métricas Econômicas
Calcula CPL, ROAS projetado, margem de manobra e ações recomendadas

VERSÃO 2.0 (2025-10-27): Nova lógica de recomendação contínua
- Função sigmoid para confiança baseada em leads
- Multiplicador de ROAS para ajuste fino
- Eliminação de saltos bruscos entre categorias
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
import logging
from api.business_config import (
    SPEND_THRESHOLD_ZERO_LEADS,
    MINIMUM_LEADS_THRESHOLD,
    MIN_ROAS_SAFETY,
    CAP_VARIATION_MAX,
    CONFIDENCE_SIGMOID_L50,
    CONFIDENCE_SIGMOID_K,
    ROAS_TARGET
)

logger = logging.getLogger(__name__)


def calculate_cpl(spend: float, leads: int) -> float:
    """
    Calcula Custo por Lead (CPL)

    Args:
        spend: Gasto total em R$
        leads: Número de leads

    Returns:
        CPL em R$ (0.0 se leads = 0)
    """
    if leads == 0:
        return 0.0
    return spend / leads


def calculate_projected_conversion_rate(
    decile_distribution: Dict[str, float],
    conversion_rates: Dict[str, float]
) -> float:
    """
    Calcula taxa de conversão projetada baseada na distribuição de decis

    Args:
        decile_distribution: {'D1': 0.10, 'D2': 0.15, ...} (percentuais que somam 1.0)
        conversion_rates: {'D1': 0.0026, 'D2': 0.0026, ...} (taxas históricas)

    Returns:
        Taxa de conversão projetada (valor decimal, ex: 0.035 = 3.5%)
    """
    projected_rate = 0.0

    for decile, percentage in decile_distribution.items():
        rate = conversion_rates.get(decile, 0.0)
        projected_rate += percentage * rate

    return projected_rate


def calculate_projected_roas(
    product_value: float,
    projected_conversion_rate: float,
    cpl: float
) -> float:
    """
    Calcula ROAS projetado

    Formula: (Valor Produto × Taxa Projetada) / CPL

    Args:
        product_value: Valor do produto em R$
        projected_conversion_rate: Taxa de conversão projetada (decimal, ex: 0.035 = 3.5%)
        cpl: Custo por Lead em R$

    Returns:
        ROAS projetado (0.0 se CPL = 0)
    """
    if cpl == 0:
        return 0.0

    expected_revenue = product_value * projected_conversion_rate
    return expected_revenue / cpl


def calculate_contribution_margin(
    product_value: float,
    projected_conversion_rate: float,
    leads: int,
    spend: float
) -> Tuple[float, float]:
    """
    Calcula Receita Projetada e Margem de Contribuição

    Args:
        product_value: Valor do produto em R$
        projected_conversion_rate: Taxa de conversão projetada (decimal, ex: 0.035 = 3.5%)
        leads: Número de leads
        spend: Gasto em R$

    Returns:
        Tuple (receita_projetada, margem_contribuicao)

    Example:
        >>> calculate_contribution_margin(2027.38, 0.035, 50, 1000.0)
        (3547.91, 2547.91)
    """
    receita_proj = leads * projected_conversion_rate * product_value
    margem_contrib = receita_proj - spend

    return receita_proj, margem_contrib


def calculate_confidence_sigmoid(leads: int, period_days: int = 1) -> float:
    """
    Calcula fator de confiança contínuo usando função sigmoid

    Substitui as faixas discretas (baixa/média/alta) por curva suave.
    Quanto mais leads, maior a confiança, de forma gradual.

    Fórmula: f(leads) = 1 / (1 + e^(-k * (leads_per_day - L50)))

    Args:
        leads: Número total de leads no período
        period_days: Número de dias do período (default: 1)

    Returns:
        Fator de confiança entre 0.0 e 1.0

    Example:
        >>> calculate_confidence_sigmoid(15, 1)  # 15 leads em 1 dia
        0.50  # 50% de confiança (ponto médio)

        >>> calculate_confidence_sigmoid(30, 1)  # 30 leads em 1 dia
        0.80  # 80% de confiança (alta)
    """
    # Leads por dia (normalizar pelo período)
    leads_per_day = leads / period_days

    # Sigmoid: 1 / (1 + e^(-k*(x - L50)))
    confidence = 1.0 / (1.0 + np.exp(-CONFIDENCE_SIGMOID_K * (leads_per_day - CONFIDENCE_SIGMOID_L50)))

    return confidence


def calculate_roas_multiplier(roas_proj: float) -> float:
    """
    Calcula multiplicador baseado na magnitude do ROAS

    ROAS alto permite escalada mais agressiva, pois há mais "margem de erro".

    Lógica:
    - ROAS < MIN_ROAS_SAFETY (2.5x): multiplicador = 0 (não escala, safety check)
    - ROAS entre 2.5x e ROAS_TARGET (8.0x): multiplicador cresce linearmente de 0.5 a 1.0
    - ROAS > ROAS_TARGET: multiplicador = 1.0 (confiança máxima)

    Args:
        roas_proj: ROAS projetado

    Returns:
        Multiplicador entre 0.0 e 1.0

    Example:
        >>> calculate_roas_multiplier(2.0)   # Abaixo do mínimo
        0.0

        >>> calculate_roas_multiplier(2.5)   # No limite mínimo
        0.5

        >>> calculate_roas_multiplier(5.0)   # Médio
        0.73

        >>> calculate_roas_multiplier(10.0)  # Muito alto
        1.0
    """
    if roas_proj < MIN_ROAS_SAFETY:
        return 0.0

    if roas_proj >= ROAS_TARGET:
        return 1.0

    # Interpolação linear entre MIN_ROAS_SAFETY e ROAS_TARGET
    # De 0.5 (no mínimo) até 1.0 (no target)
    normalized = (roas_proj - MIN_ROAS_SAFETY) / (ROAS_TARGET - MIN_ROAS_SAFETY)
    multiplier = 0.5 + 0.5 * normalized

    return multiplier


def calculate_budget_variation(
    margem_contrib: float,
    spend: float,
    roas_proj: float,
    leads: int,
    period_days: int = 1
) -> float:
    """
    Calcula variação de budget usando lógica contínua (sigmoid + multiplicador ROAS)

    NOVA LÓGICA (v2.0 - 2025-10-27):
    variacao = min(margem%, CAP_MAX) × f_confianca(leads) × f_roas(ROAS)

    Onde:
    - f_confianca: função sigmoid contínua baseada em leads
    - f_roas: multiplicador linear baseado em ROAS
    - CAP_MAX: 100% (limite para não quebrar Learning Phase do Meta)

    Args:
        margem_contrib: Margem de contribuição em R$ (receita - gasto)
        spend: Gasto atual em R$
        roas_proj: ROAS projetado
        leads: Número de leads no período
        period_days: Número de dias do período (default: 1)

    Returns:
        Percentual de variação (-100 a +100)
        Positivo = aumentar, Negativo = reduzir

    Example:
        >>> calculate_budget_variation(918.26, 100.84, 10.11, 15, 1)
        50.0  # Aumentar 50%
        # Cálculo: min(910%, 100%) × sigmoid(15) × roas_mult(10.11)
        #        = 100% × 0.50 × 1.0 = 50%
    """
    if spend == 0:
        return 0.0

    # CENÁRIO 1: Margem POSITIVA (lucrativa)
    if margem_contrib > 0:
        # 1. Calcular percentual de margem em relação ao gasto
        margem_pct = (margem_contrib / spend) * 100

        # 2. Aplicar CAP absoluto (100% = dobrar orçamento, limite do Meta)
        margem_capped = min(margem_pct, CAP_VARIATION_MAX)

        # 3. Fator de confiança contínuo (sigmoid baseado em leads)
        confidence_factor = calculate_confidence_sigmoid(leads, period_days)

        # 4. Multiplicador de ROAS (considera magnitude do ROAS)
        roas_multiplier = calculate_roas_multiplier(roas_proj)

        # 5. Variação final
        variation = margem_capped * confidence_factor * roas_multiplier

        return round(variation, 1)

    # CENÁRIO 2: Margem NEGATIVA (prejuízo)
    else:
        # Redução proporcional ao prejuízo
        # Usar confiança para determinar quão agressivo ser no corte
        margem_pct = (margem_contrib / spend) * 100
        confidence_factor = calculate_confidence_sigmoid(leads, period_days)

        variation = margem_pct * confidence_factor  # Será negativo

        # Limitar redução máxima em -100% (pausar)
        variation = max(variation, -100.0)

        return round(variation, 1)


def determine_action(
    dimension: str,
    has_budget_control: bool = True,
    leads: int = 0,
    period_days: int = 1,
    spend: float = 0.0,
    margem_contrib: float = 0.0,
    roas_proj: float = 0.0
) -> str:
    """
    Determina ação recomendada baseada em Margem de Contribuição

    Args:
        dimension: Tipo de dimensão (campaign, adset, ad, medium, term, content)
        has_budget_control: Se False, indica que não pode controlar orçamento neste nível
        leads: Número de leads (para validação estatística)
        period_days: Número de dias do período analisado
        spend: Gasto total em R$ (para detectar alto gasto sem leads)
        margem_contrib: Margem de contribuição em R$ (receita - gasto)
        roas_proj: ROAS projetado

    Returns:
        Ação recomendada como string (ex: "Aumentar 25%", "Reduzir 30%", "Manter")
    """
    # REGRA ESPECIAL 1: Gasto alto sem NENHUM lead = Remover/Pausar imediatamente
    # Threshold importado de business_config.py
    if leads == 0 and spend > SPEND_THRESHOLD_ZERO_LEADS:
        # Dimensões sem controle de orçamento (apenas on/off)
        onoff_dimensions = ['ad', 'content']
        if dimension in onoff_dimensions:
            return "Remover"
        else:
            # Dimensões com budget: pausar completamente
            return "Reduzir 100%"

    # REGRA ESPECIAL 2: Poucos leads MAS performance comprovadamente RUIM
    # Caso: 1-2 leads, gasto alto (>R$50), ROAS <1.0 (prejuízo confirmado)
    # Ação: Não aguardar mais dados, remover/pausar imediatamente
    threshold_min = MINIMUM_LEADS_THRESHOLD * period_days
    if leads < threshold_min and spend > SPEND_THRESHOLD_ZERO_LEADS and roas_proj < 1.0:
        onoff_dimensions = ['ad', 'content']
        if dimension in onoff_dimensions:
            return "Remover (ROAS < 1.0)"
        else:
            return "Reduzir 100%"

    # Se dados insuficientes mas sem indicação de performance ruim, aguardar
    if leads < threshold_min:
        faltam = threshold_min - leads
        if faltam == 1:
            return "Aguardar dados (falta 1 lead)"
        else:
            return f"Aguardar dados (faltam {faltam} leads)"

    # Se não tem controle de orçamento nessa dimensão
    if not has_budget_control:
        # Campaign sem budget → orçamento está no AdSet (ABO)
        if dimension == 'campaign':
            return "ABO"
        # AdSet sem budget → orçamento está na Campaign (CBO)
        elif dimension == 'medium':
            # AdSet em campanha CBO: recomendar ações baseadas em performance
            # Não pode alterar orçamento, mas pode pausar ou manter

            # Poucos dados: aguardar
            if leads < threshold_min:
                faltam = threshold_min - leads
                if faltam == 1:
                    return "CBO - Aguardar dados (falta 1 lead)"
                else:
                    return f"CBO - Aguardar dados (faltam {faltam} leads)"

            # Dados suficientes: analisar performance
            if margem_contrib < 0 or roas_proj < MIN_ROAS_SAFETY:
                # Prejuízo ou ROAS muito baixo
                return "CBO - Pausar / Alterar"
            else:
                # Performance aceitável ou boa
                return "CBO - Manter"
        else:
            return "N/A"

    # Dimensões com controle de orçamento
    budget_dimensions = ['campaign', 'adset', 'medium', 'term']

    # Dimensões sem controle de orçamento (apenas on/off)
    onoff_dimensions = ['ad', 'content']

    if dimension in budget_dimensions:
        # Calcular variação baseada em nova lógica contínua
        variation_pct = calculate_budget_variation(margem_contrib, spend, roas_proj, leads, period_days)

        if variation_pct > 0:
            return f"Aumentar {variation_pct:.1f}%"
        elif variation_pct < 0:
            return f"Reduzir {abs(variation_pct):.1f}%"
        else:
            return "Manter (ROAS baixo)"

    elif dimension in onoff_dimensions:
        if margem_contrib >= 0:
            return "Manter"
        else:
            return "Remover"

    else:
        # Dimensão desconhecida, usar lógica padrão de orçamento
        variation_pct = calculate_budget_variation(margem_contrib, spend, roas_proj, leads, period_days)

        if variation_pct > 0:
            return f"Aumentar {variation_pct:.1f}%"
        elif variation_pct < 0:
            return f"Reduzir {abs(variation_pct):.1f}%"
        else:
            return "Manter"


def enrich_utm_with_economic_metrics(
    utm_df: pd.DataFrame,
    product_value: float,
    min_roas: float,
    conversion_rates: Dict[str, float],
    dimension: str,
    budget_control_col: str = None,
    period_days: int = 1
) -> pd.DataFrame:
    """
    Enriquece DataFrame de análise UTM com métricas econômicas (Margem de Contribuição)

    Args:
        utm_df: DataFrame com colunas: value, leads, spend, decile distribution
        product_value: Valor do produto em R$
        min_roas: ROAS mínimo desejado (não usado mais, mantido por compatibilidade)
        conversion_rates: Dict com taxas de conversão por decil
        dimension: Tipo de dimensão (campaign, adset, ad, etc.)
        budget_control_col: Nome da coluna que indica se tem controle de orçamento (opcional)
        period_days: Número de dias do período analisado (para ajustar thresholds)

    Returns:
        DataFrame enriquecido com colunas adicionais:
        - cpl: Custo por Lead
        - taxa_proj: Taxa de conversão projetada
        - receita_proj: Receita projetada (NOVO)
        - margem_contrib: Margem de Contribuição em R$ (NOVO)
        - roas_proj: ROAS projetado
        - acao: Ação recomendada
        - budget_current: Orçamento atual
        - budget_target: Orçamento alvo
    """
    df = utm_df.copy()

    # Inicializar colunas
    df['cpl'] = 0.0
    df['taxa_proj'] = 0.0
    df['receita_proj'] = 0.0       # NOVO
    df['margem_contrib'] = 0.0     # NOVO
    df['roas_proj'] = 0.0
    df['acao'] = ""
    df['budget_current'] = 0.0
    df['budget_target'] = 0.0

    for idx, row in df.iterrows():
        spend = row.get('spend', 0.0)
        leads = row.get('leads', 0)

        # CPL
        cpl = calculate_cpl(spend, leads)
        df.at[idx, 'cpl'] = cpl

        # Distribuição de decis (assumindo colunas %D1, %D2, ..., %D10)
        decile_dist = {}
        for i in range(1, 11):
            decile_key = f'D{i}'
            pct_col = f'%{decile_key}'
            if pct_col in row:
                # Converter de % para decimal (ex: 15.5% -> 0.155)
                decile_dist[decile_key] = row[pct_col] / 100.0

        # Taxa de conversão projetada
        if decile_dist:
            taxa_proj = calculate_projected_conversion_rate(decile_dist, conversion_rates)
        else:
            taxa_proj = 0.0
        df.at[idx, 'taxa_proj'] = taxa_proj

        # NOVO: Receita Projetada e Margem de Contribuição
        receita_proj, margem_contrib = calculate_contribution_margin(
            product_value, taxa_proj, leads, spend
        )
        df.at[idx, 'receita_proj'] = receita_proj
        df.at[idx, 'margem_contrib'] = margem_contrib

        # ROAS projetado
        roas_proj = calculate_projected_roas(product_value, taxa_proj, cpl)
        df.at[idx, 'roas_proj'] = roas_proj

        # Verificar se tem controle de orçamento
        has_budget_control = True
        if budget_control_col and budget_control_col in row:
            has_budget_control = bool(row[budget_control_col])

        # NOVO: Ação baseada em Margem de Contribuição
        action = determine_action(
            dimension=dimension,
            has_budget_control=has_budget_control,
            leads=leads,
            period_days=period_days,
            spend=spend,
            margem_contrib=margem_contrib,
            roas_proj=roas_proj
        )
        df.at[idx, 'acao'] = action

        # Orçamento atual (gasto do período)
        budget_current = spend
        df.at[idx, 'budget_current'] = budget_current

        # Orçamento alvo (baseado na ação)
        budget_target = spend  # Default: manter

        # Extrair variação percentual da ação
        import re
        if 'Aumentar' in action or 'Reduzir' in action:
            match = re.search(r'(\d+\.?\d*)%', action)
            if match:
                variation_pct = float(match.group(1))
                if 'Reduzir' in action:
                    variation_pct = -variation_pct
                budget_target = spend * (1 + variation_pct / 100.0)
        elif action == 'Remover' or 'Reduzir 100' in action:
            budget_target = 0.0

        df.at[idx, 'budget_target'] = budget_target

    logger.info(f"✅ Métricas econômicas calculadas para dimensão '{dimension}': {len(df)} registros")

    return df
