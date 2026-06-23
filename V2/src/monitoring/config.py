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
        'missing_rate': 0.50,            # 50% de missing em fbp/fbc
        'rejection_rate': 0.10,          # 10% de taxa de rejeição pela Meta
        'zero_decil_lookback_hours': 24, # [T1-2] janela de verificação de decis zerados
        'zero_decil_min_leads': 100,     # [T1-2] mínimo de eventos para ativar o check
                                         # (subido de 20→100 em 2026-05-24 — campanhas
                                         # do gestor sobem em 25/05; antes disso o
                                         # volume não justifica disparar HIGH)
    },

    # [T1-13] Audience profile drift: compara último dia completo de captação
    # contra snapshot do pool de referência (Top 5 ROAS) em
    # configs/reference_audience_profiles/{client_id}.json.
    #
    # Cada item do top_list traz tanto a comparação contra ontem (`day_pct`,
    # `delta_pp`) quanto contra hoje parcial 00:00 BRT → agora (`today_pct`,
    # `today_delta_pp`). Detalhes do alerta carregam `today_window` (label
    # com horário) e `today_n_responses` pra deixar fraqueza de amostra
    # explícita.
    #
    # Severity: sempre HIGH se top_list não-vazia, sem alerta se vazia.
    'audience_profile_drift': {
        'enabled': True,
        'top_threshold_pp': 2.0,    # |Δpp vs ontem| mínimo pra entrar no top_list
        'min_responses': 50,        # mínimo de respostas em ontem pra rodar o check
    },

    # Bucket 'outros' inflado (Source/Term/Medium). Separa dois tipos de 'outros'
    # que antes eram contados juntos:
    #   - categoria-nova: valor de UTM nunca visto no treino (sinal valioso — o
    #     modelo não tem feature pra ele). Alerta no nível normal (>2%).
    #   - macro Meta não-resolvido: placeholder `{{...}}` que o Meta não
    #     substituiu (tráfego in-app; ~1-3% do volume, estável). É artefato de
    #     tracking conhecido — só alerta se ESTOURAR (spike >10%), não no nível
    #     normal. O conserto real (descodificar o macro no anúncio) é
    #     operacional, não de modelo.
    # `restrict_to_sources_by_column` mantém Term restrito a Meta porque Google
    # põe IDs no term legitimamente (cai em 'outros' por design, não é misconfig).
    'outros_buckets': {
        'enabled': True,
        'min_pct_threshold': 0.02,       # categoria-nova: alerta se >2% do volume
        'macro_spike_threshold': 0.10,   # macro {{...}}: só alerta se estourar >10%
        'macro_markers': ['{', '%7b'],   # marca raw_value como macro Meta não-resolvido
        'window_hours': 24,
        'top_n': 8,
        'columns': ['Source', 'Term', 'Medium'],
        'restrict_to_sources_by_column': {'Term': ['facebook-ads']},
    },
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
    'tem_computador',
]
