# =============================================================================
# 1. MÉTRICAS DE PRODUTO
# =============================================================================

# Valor médio do produto (atualizado em 15/03/2026)
# Fonte: analyze_tmb_inadimplencia.py — 5.608 pedidos maduros (files/analises/tmb_inadimplencia_relatorio.xlsx)
# - Guru: R$ 1.973,95 (42.3% das conversões, 100% realizado)
# - TMB:  R$ 1.262,86 (57.7% das conversões, 57.4% realizado — média ponderada por grau de risco)
#   Alto 48.6% (R$1.068,47) | Médio 67.1% (R$1.475,47) | Baixo 83.5% (R$1.837,40) | S/C 42.1% (R$925,27)
# Proporção baseada no modelo TMB All 15/03 (109f64c4e53b4d0d85f8843443f2a52f): 317 Guru / 433 TMB
# Valor ponderado: 0.423×1973.95 + 0.577×1262.86 = R$ 1.563,75
PRODUCT_VALUE = 1563.75

# =============================================================================
# 2. TAXAS DE CONVERSÃO CORRIGIDAS POR RECALL
# =============================================================================

# CONTEXTO:
# Modelo: Guru Only Jan/30 (MLflow: d51757f5041c44b7ab1a056fce8c3c35)
# Período test set: 2025-09-24 → 2025-11-04 | 33.152 leads | 219 conversões
# D01-D06 zerados — Meta não otimiza para perfis de baixa qualidade
# D07/D08 PAV pooled (quebra de monotonia). Taxas brutas sem fator de recall aplicado.

CONVERSION_RATES = {
    "D01": 0.000000,
    "D02": 0.000000,
    "D03": 0.000000,
    "D04": 0.000000,
    "D05": 0.000000,
    "D06": 0.000000,
    "D07": 0.008100,   # PAV pooled D07+D08 | obs: 0.840% | 28 conv / 3,316 leads
    "D08": 0.008100,   # PAV pooled D07+D08 | obs: 0.780% | 26 conv / 3,315 leads
    "D09": 0.015700,   # obs: 1.570% | 52 conv / 3,313 leads
    "D10": 0.017500,   # obs: 1.750% | 58 conv / 3,316 leads
}

# =============================================================================
# 2.1 LEAD VALUE POR DECIL — VALOR RECEBIDO À VISTA (Champion + Challenger)
# =============================================================================
#
# Substitui PRODUCT_VALUE × CONVERSION_RATES pelo valor recebido à vista
# esperado por lead em cada decil. Este é o `value` que vai no LeadQualified.
#
# Frame: cash recebido na semana da venda (visão mensal do dono — não LTV).
#   - cartão Guru/Hotmart: R$ 1.997 × 0,87 = R$ 1.737,39 (líquido após chargeback)
#   - boleto Asaas/TMB:    R$ 2.200 / 12  = R$   183,33 (1ª parcela apenas)
#
# Pipeline de cálculo (script ad-hoc /tmp/decile_value_final.py):
#   1. Pool LF46→LF53 — 8 lançamentos, ~96k leads, 555 buyers matched
#   2. Match unificado email+telefone (core/matching.match_leads_to_sales_unified)
#   3. TMB local incluído em LF46–LF52 (contas_a_receber_28042026_1033.xlsx);
#      LF53 sem TMB (vendas iniciam 27/04, fora do contas_a_receber)
#   4. Extrapolação per-LF: scale_lf = vendas_total_xlsx / buyers_pool_lf
#      (1,34×–2,54×; hipótese: tracking uniforme entre decis — mesma do PDF
#      assertividade)
#   5. Shrinkage k=10 no avg_recv por decil (atenua decis de baixa amostra)
#   6. IsotonicRegression(increasing=True) sobre lead_value final — mesma
#      aplicação canônica de src/model/training_model.py:87 — garante
#      monotonia D1→D10 sem inversão na hora de enviar pra Meta.
#
# Champion = jan30  (run_id d51757f5041c44b7ab1a056fce8c3c35) — modelo em prod
# Challenger = abr28 (run_id 5d158f0aa6e54b489498470446194a6c) — A/B HQLB

LEAD_VALUE_BY_DECILE_CHAMPION = {
    "D01": 1.51,
    "D02": 1.97,
    "D03": 1.97,
    "D04": 1.97,
    "D05": 5.62,
    "D06": 5.62,
    "D07": 5.62,
    "D08": 6.75,
    "D09": 7.77,
    "D10": 14.97,
}

LEAD_VALUE_BY_DECILE_CHALLENGER = {
    "D01": 0.71,
    "D02": 2.84,
    "D03": 2.84,
    "D04": 4.81,
    "D05": 4.81,
    "D06": 7.69,
    "D07": 9.22,
    "D08": 11.94,
    "D09": 11.94,
    "D10": 20.69,
}

# =============================================================================
# 2.2 FATORES DE REALIZAÇÃO POR CANAL — VALOR RECEBIDO À VISTA
# =============================================================================
#
# Cada canal de venda tem uma taxa de chargeback/refund diferente. Esses fatores
# são aplicados em src/validation/data_loader.py:combine_sales para gerar a coluna
# `sale_value_realizado` — a receita que efetivamente entra no caixa na semana
# da venda (não o valor nominal contratado).
#
# Substitui o sistema antigo (tmb_adjuster.py) que aplicava 0.6211 só nas vendas
# TMB. Esse fator agregado escondia a heterogeneidade entre canais; agora cada
# canal recebe o fator próprio derivado dos seus dados.
#
# Janela de cálculo: últimos 12 meses (2025-05-11 → 2026-05-11).
# Calculados em 11/05/2026 via APIs Guru e Hotmart.
#
# Fórmulas por sale_origin (aplicadas em combine_sales):
#   guru     → sale_value × GURU_REALIZACAO_FACTOR
#   hotmart  → sale_value × HOTMART_REALIZACAO_FACTOR
#   tmb      → sale_value / N_PARCELAS_BOLETO       (só a 1ª parcela)
#   asaas    → depende de _asaas_billing_type:
#                BOLETO/UNDEFINED → sale_value / N_PARCELAS_BOLETO
#                CREDIT_CARD      → sale_value × HOTMART_REALIZACAO_FACTOR
#                PIX              → sale_value × 1.0  (já entrou no caixa)

GURU_REALIZACAO_FACTOR = 0.9198     # 2.364 aprov / (2.364 + 29 charge + 177 refund) — 12M, 4.743 txns
HOTMART_REALIZACAO_FACTOR = 0.9121  # 218 aprov / (218 + 2 charge + 19 refund) — 12M, 239 txns
N_PARCELAS_BOLETO = 12              # número de parcelas padrão do boleto parcelado DevClub

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
    "lead_value_by_decile_champion": LEAD_VALUE_BY_DECILE_CHAMPION,
    "lead_value_by_decile_challenger": LEAD_VALUE_BY_DECILE_CHALLENGER,
}

# =============================================================================
# GUIA DE ALTERAÇÃO DAS MÉTRICAS
# =============================================================================

"""
1. VALOR DO PRODUTO:
   - Linha 10: PRODUCT_VALUE = 1649.73
   - Impacto: Cálculo de receita, margem de contribuição e valor do LeadQualified (CAPI)

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

EXEMPLO COMPLETO DE CÁLCULO - LEADQUALIFIED (CAPI):
   Lead D10 com taxa de conversão de 5.37%

   Valor projetado = PRODUCT_VALUE × taxa_conversão
   Valor projetado = R$ 1.649,73 × 0.0537
   Valor projetado = R$ 88,59

   Antes (PRODUCT_VALUE = 2.000): R$ 107,40
   Depois (PRODUCT_VALUE = 1.649,73): R$ 88,59
   Diferença: -17.5% (mais realista, considera inadimplência TMB)
"""
