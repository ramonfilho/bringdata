"""
Configurações e thresholds do sistema de monitoramento.
"""

# Thresholds para detecção de alertas
THRESHOLDS = {
    # Category drift: detecta categorias não vistas no treino
    'category_drift': {
        'enabled': True
    },

    # Distribution drift: detecta mudanças nas proporções
    'distribution_drift': {
        'enabled': True,
        'categorical': 0.15,  # 15 pontos percentuais
        'numerical': 2.0      # 2 desvios padrão
    },

    # Missing rate: detecta colunas com muitos valores faltando
    'missing_rate': {
        'enabled': True,
        'threshold': 0.20  # 20% de missing
    },

    # Score distribution: detecta mudanças nas proporções de decis
    'score_distribution': {
        'enabled': True,
        'threshold': 0.10  # 10pp de mudança por decil
    },

    # Operational: detecta problemas operacionais
    'operational': {
        'enabled': True,
        'no_leads_hours': 6,   # Alerta se não receber leads por 6h
        'no_capi_hours': 6     # Alerta se não enviar CAPI por 6h
    },

    # CAPI quality: detecta problemas de qualidade CAPI
    'capi_quality': {
        'enabled': True,
        'missing_rate': 0.50,  # 50% de missing em fbp/fbc
        'rejection_rate': 0.20 # 20% de taxa de rejeição (futuro)
    }
}

# Distribuições esperadas de decis (referência)
# Usada para comparar com distribuição em produção
EXPECTED_DECIL_DISTRIBUTION = {
    'D1': 0.10,
    'D2': 0.10,
    'D3': 0.10,
    'D4': 0.10,
    'D5': 0.10,
    'D6': 0.10,
    'D7': 0.10,
    'D8': 0.10,
    'D9': 0.10,
    'D10': 0.10
}
