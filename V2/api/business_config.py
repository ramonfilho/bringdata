"""
=============================================================================
BUSINESS CONFIG - Configurações Unificadas do Sistema Smart Ads
=============================================================================

Este arquivo centraliza TODAS as configurações de negócio e métricas do sistema.

HISTÓRICO DE VERSÕES:
- 2025-10-27: Nova lógica de recomendação contínua (sigmoid + multiplicador ROAS)
- 2025-10-22: Unificação de configs (meta_config.py, BUSINESS_CONFIG_CORRECTED.py, metricas_personalizaveis.md)
- 2025-10-20: Correção por recall (2.906x) nas taxas de conversão
- 2025-10-15: Análise inicial de 1.970 vendas DevClub

"""

# =============================================================================
# 1. MÉTRICAS DE PRODUTO
# =============================================================================

# Valor médio do produto (baseado em análise de matches reais - 769 conversões, LTV R$ 1.782)
# Valor arredondado para R$ 2.000 (conservador, considera 13.1% de recompra real)
PRODUCT_VALUE = 2000.00

# =============================================================================
# 2. TAXAS DE CONVERSÃO CORRIGIDAS POR RECALL
# =============================================================================

# CONTEXTO DO RECALL:
# - Conversões observadas (matching email/telefone): 678
# - Vendas reais (Google Sheets): 1.970
# - Recall: 34.4% (678/1970)
# - Fator de correção: 2.906x (1/0.344)
#
# MOTIVOS DO BAIXO RECALL:
# - Emails diferentes entre pesquisa e compra
# - Telefones inválidos/incomparáveis
# - Dados ausentes
#
# MÉTODO: Taxa corrigida = Taxa observada / Recall

# TAXAS ANTIGAS (baseadas em recall 2.906x - DESATUALIZADAS)
# CONVERSION_RATES = {
    "D1": 0.002799,   # 0.28% | Corrigido de 0.06% (×4.666) | 2 conversões / 3,261 leads
    "D2": 0.006999,   # 0.70% | Corrigido de 0.15% (×4.666) | 5 conversões / 3,261 leads
    "D3": 0.002799,   # 0.28% | Corrigido de 0.06% (×4.666) | 2 conversões / 3,261 leads
    "D4": 0.017263,   # 1.73% | Corrigido de 0.37% (×4.666) | 12 conversões / 3,261 leads
    "D5": 0.017263,   # 1.73% | Corrigido de 0.37% (×4.666) | 12 conversões / 3,261 leads
    "D6": 0.031261,   # 3.13% | Corrigido de 0.67% (×4.666) | 22 conversões / 3,262 leads
    "D7": 0.045725,   # 4.57% | Corrigido de 0.98% (×4.666) | 32 conversões / 3,260 leads
    "D8": 0.049924,   # 4.99% | Corrigido de 1.07% (×4.666) | 35 conversões / 3,261 leads
    "D9": 0.067188,   # 6.72% | Corrigido de 1.44% (×4.666) | 47 conversões / 3,261 leads
    "D10": 0.104514,   # 10.45% | Corrigido de 2.24% (×4.666) | 73 conversões / 3,261 leads
}

CONVERSION_RATES_OBSERVADAS = {
    "D1": 0.002137,   # 0.21% | 7 conversões / 3,276 leads
    "D2": 0.002748,   # 0.27% | 9 conversões / 3,275 leads
    "D3": 0.002138,   # 0.21% | 7 conversões / 3,274 leads (quebra monotonia vs D2)
    "D4": 0.005802,   # 0.58% | 19 conversões / 3,275 leads
    "D5": 0.003053,   # 0.31% | 10 conversões / 3,276 leads (quebra monotonia vs D4)
    "D6": 0.006721,   # 0.67% | 22 conversões / 3,274 leads
    "D7": 0.006718,   # 0.67% | 22 conversões / 3,275 leads
    "D8": 0.010382,   # 1.04% | 34 conversões / 3,275 leads
    "D9": 0.014043,   # 1.40% | 46 conversões / 3,276 leads
    "D10": 0.019243,  # 1.92% | 63 conversões / 3,274 leads
}

# TAXAS CORRIGIDAS - Aplicando recall 55.7% (fator 1.795x)
# Análise: 769 conversões observadas / 1,380 vendas reais = 55.7% recall
# Data: 2025-11-10 | Total leads: 108,700 | Vendas reais (sem duplicatas): 1,380
CONVERSION_RATES = {
    "D1": 0.002799,   # 0.28% | Corrigido de 0.06% (×4.666) | 2 conversões / 3,261 leads
    "D2": 0.006999,   # 0.70% | Corrigido de 0.15% (×4.666) | 5 conversões / 3,261 leads
    "D3": 0.002799,   # 0.28% | Corrigido de 0.06% (×4.666) | 2 conversões / 3,261 leads
    "D4": 0.017263,   # 1.73% | Corrigido de 0.37% (×4.666) | 12 conversões / 3,261 leads
    "D5": 0.017263,   # 1.73% | Corrigido de 0.37% (×4.666) | 12 conversões / 3,261 leads
    "D6": 0.031261,   # 3.13% | Corrigido de 0.67% (×4.666) | 22 conversões / 3,262 leads
    "D7": 0.045725,   # 4.57% | Corrigido de 0.98% (×4.666) | 32 conversões / 3,260 leads
    "D8": 0.049924,   # 4.99% | Corrigido de 1.07% (×4.666) | 35 conversões / 3,261 leads
    "D9": 0.067188,   # 6.72% | Corrigido de 1.44% (×4.666) | 47 conversões / 3,261 leads
    "D10": 0.104514,   # 10.45% | Corrigido de 2.24% (×4.666) | 73 conversões / 3,261 leads
}

# =============================================================================
# 3. THRESHOLD DE GASTO SEM LEADS
# =============================================================================

# Valor mínimo de gasto com 0 leads que indica item comprovadamente ruim
# Ação: Remover (anúncios) ou Pausar (campanhas/adsets)
# IMPORTANTE: Aplicado em TODAS as janelas (1D, 3D, 7D) e TODOS os níveis (campaign, adset, ad)

SPEND_THRESHOLD_ZERO_LEADS = 100.0  # R$ 100,00

# Threshold mínimo de leads para ter dados suficientes
# Abaixo disso, a ação será "Aguardar dados"
MINIMUM_LEADS_THRESHOLD = 3  # < 3 leads = dados insuficientes

# =============================================================================
# 4. CORES DA COLUNA AÇÃO (Google Sheets)
# =============================================================================

# Lógica de cores aplicada na coluna Ação, baseada no % de variação recomendado

COLOR_THRESHOLDS = {
    "green_min": 30,   # Verde: Aumentar > 30%
    "yellow_min": 1,   # Amarelo: Aumentar 1-30%
    # Vermelho: Reduzir (qualquer %) ou Remover
    # Cinza: Manter, Aguardar dados, ABO, CBO
}

# =============================================================================
# 5. PARÂMETROS DE OTIMIZAÇÃO (MARGEM DE CONTRIBUIÇÃO)
# =============================================================================

# ROAS Mínimo de Segurança (safety check)
# Campanhas com ROAS < MIN_ROAS_SAFETY não serão escaladas mesmo que lucrativas
# Serve como proteção contra campanhas arriscadas
MIN_ROAS_SAFETY = 2.5

# CAP de Variação Máxima (limite de aumento de budget)
# Mesmo que campanha tenha margem muito alta, nunca recomendar aumentar mais que isso
# IMPORTANTE: Limite de 100% para não quebrar Learning Phase do Meta
CAP_VARIATION_MAX = 100.0  # Máximo: aumentar 100% do orçamento atual (dobrar)

# =============================================================================
# 6. PARÂMETROS DA NOVA LÓGICA DE RECOMENDAÇÃO CONTÍNUA (v2.0 - 2025-10-27)
# =============================================================================
#
# SUBSTITUIU O SISTEMA ANTIGO DE FAIXAS DISCRETAS:
# - Antes: 3 valores possíveis (24%, 40%, 64%)
# - Agora: Valores contínuos de 0% até 100%
#
# FÓRMULA NOVA:
#   variacao = min(margem%, 100%) × f_confianca(leads) × f_roas(ROAS)
#
# BENEFÍCIOS:
#   1. Granularidade: Cada campanha recebe recomendação única
#   2. Sem saltos: Transições suaves (19 leads → 63%, 20 leads → 65%)
#   3. Considera ROAS: ROAS alto permite mais agressividade
#   4. Explicável: Cada componente é claro e interpretável
#
# =============================================================================

# Função Sigmoid de Confiança (baseada em leads)
# Substitui faixas discretas por curva contínua
# f_confianca(leads) = 1 / (1 + e^(-k * (leads_per_day - L50)))
#
# Exemplos de valores:
#   5 leads  → 12% de confiança
#   10 leads → 27% de confiança
#   15 leads → 50% de confiança (ponto médio)
#   20 leads → 73% de confiança
#   30 leads → 95% de confiança
#
CONFIDENCE_SIGMOID_L50 = 15.0    # Ponto médio: 15 leads = 50% de confiança
CONFIDENCE_SIGMOID_K = 0.15      # Inclinação: controla suavidade da curva

# Multiplicador de ROAS
# Ajusta recomendação baseado na magnitude do ROAS
# Permite escalada mais agressiva quando há "margem de segurança"
#
# Lógica:
#   ROAS < 2.5x              → multiplicador = 0.0 (não escala, safety check)
#   ROAS = 2.5x              → multiplicador = 0.5 (no limite mínimo)
#   ROAS entre 2.5x e 8.0x   → multiplicador cresce linearmente de 0.5 a 1.0
#   ROAS ≥ 8.0x              → multiplicador = 1.0 (confiança máxima)
#
# Exemplos:
#   ROAS 3.0x  → multiplicador 0.55
#   ROAS 5.0x  → multiplicador 0.73
#   ROAS 10.0x → multiplicador 1.00
#
ROAS_TARGET = 8.0  # ROAS a partir do qual temos confiança máxima (multiplicador = 1.0)

# =============================================================================
# 7. DICT CONSOLIDADO (para compatibilidade com código existente)
# =============================================================================

BUSINESS_CONFIG = {
    "product_value": PRODUCT_VALUE,
    "min_roas": MIN_ROAS_SAFETY,  # Usar ROAS de segurança (2.5x) como padrão
    "conversion_rates": CONVERSION_RATES,
}

# =============================================================================
# GUIA DE ALTERAÇÃO DAS MÉTRICAS
# =============================================================================

"""
1. VALOR DO PRODUTO:
   - Linha 21: PRODUCT_VALUE = 2027.38
   - Impacto: Cálculo de receita e margem de contribuição

2. TAXAS DE CONVERSÃO POR DECIL:
   - Linhas 40-51: CONVERSION_RATES
   - Impacto: Receita projetada para cada campanha/adset/ad

3. THRESHOLD DE GASTO SEM LEADS:
   - Linha 61: SPEND_THRESHOLD_ZERO_LEADS = 100.0
   - Impacto: Se gasto ≥ R$ 100 com 0 leads, pausar/remover (todas janelas e níveis)

4. THRESHOLD MÍNIMO DE LEADS:
   - Linha 64: MINIMUM_LEADS_THRESHOLD = 3
   - Impacto: Quando mostrar "Aguardar dados"

5. CORES DA COLUNA AÇÃO:
   - Linhas 72-77: COLOR_THRESHOLDS
   - Impacto: Verde >30%, Amarelo 1-30%, Vermelho (reduzir), Cinza (neutro)

6. ROAS MÍNIMO DE SEGURANÇA:
   - Linha 86: MIN_ROAS_SAFETY = 2.5
   - Impacto: Campanhas com ROAS < 2.5 não são escaladas

7. CAP DE VARIAÇÃO MÁXIMA:
   - Linha 91: CAP_VARIATION_MAX = 100.0
   - Impacto: Limita aumentos de budget (máximo 100%)

8. FUNÇÃO SIGMOID DE CONFIANÇA:
   - Linhas 123-124: CONFIDENCE_SIGMOID_L50, CONFIDENCE_SIGMOID_K
   - Impacto: Curva contínua de confiança baseada em leads

9. MULTIPLICADOR DE ROAS:
   - Linha 141: ROAS_TARGET = 8.0
   - Impacto: ROAS alto permite recomendações mais agressivas

EXEMPLO COMPLETO DE CÁLCULO (Linha 8 da planilha):
   Dados: 15 leads, ROAS 10.11x, margem 910%, gasto R$ 100,84

   Passo 1: Margem % = 910%, Capped = min(910%, 100%) = 100%
   Passo 2: Confiança = sigmoid(15) = 0.50 (50%)
   Passo 3: Mult. ROAS = 1.0 (ROAS > 8x)
   Passo 4: Variação = 100% × 0.50 × 1.0 = 50%

   Resultado: "Aumentar 50.0%"
   Orçamento: R$ 100,84 → R$ 151,26

   Sistema anterior: 40% (faixas discretas)
   Sistema novo: 50% (contínuo, considera ROAS)
"""
