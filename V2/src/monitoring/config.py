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

# Colunas ignoradas no check de missing_rate
# Não alertar se essas colunas tiverem valores ausentes
MISSING_RATE_IGNORE_COLUMNS = [
    # Outputs do modelo (não devem estar no input)
    'Pontuação', 'Pontuação.1', 'Pontuação.2', 'Pontuação.3', 'Pontuação.4',
    'Score', 'Score.1', 'Score.2', 'Score.3', 'Score.4',
    'Faixa', 'Faixa.1', 'Faixa.2', 'Faixa.3', 'Faixa.4',
    'Faixa A', 'Faixa A.1', 'Faixa A.2', 'Faixa A.3', 'Faixa A.4',
    'Faixa B', 'Faixa B.1', 'Faixa B.2', 'Faixa B.3', 'Faixa B.4',
    'Faixa C', 'Faixa C.1', 'Faixa C.2', 'Faixa C.3', 'Faixa C.4',
    'Faixa D', 'Faixa D.1', 'Faixa D.2', 'Faixa D.3', 'Faixa D.4',
    'lead_score',
    'decil',

    # Colunas sem nome (Unnamed:)
    'Unnamed: 38', 'Unnamed: 48', 'Unnamed: 56', 'Unnamed: 64',

    # Dados técnicos não-críticos
    'Remote IP',
    'User Agent',
    'Page URL',
    'externalid',

    # Geolocalização (depende de API externa, pode falhar)
    'cidade',
    'estado',
    'pais',
    'cep',

    # CAPI (já tem monitor específico)
    'fbc',
    'fbp',

    # Colunas sem nome ou vazias
    '',

    # Campos de formulário antigos que não são mais usados
    'Qual estado você mora?',

    # Campo que pode estar vazio temporariamente
    'Tem computador/notebook?',
]
