"""
Configuração da API do Digital Manager Guru
Para obter o token: Meu Perfil → Tokens API → Adicionar

IMPORTANTE: Este token carrega muitos privilégios.
Não compartilhe, não exponha no frontend, e guarde com segurança.

Documentação: https://docs.digitalmanager.guru/developers/
"""

# Credenciais Guru API
GURU_CONFIG = {
    "user_token": "a0e3cf5b-f07f-4ca4-a816-6a3dcf326063|Y4DflXgqFwbBtueBmye8CAB1LgnOO6CsRpdhgr22e32ef538",
    "api_base_url": "https://digitalmanager.guru/api/v2",
    "transactions_endpoint": "https://digitalmanager.guru/api/v2/transactions",
}

# Headers padrão para requisições
GURU_HEADERS = {
    "Authorization": f"Bearer {GURU_CONFIG['user_token']}",
    "Content-Type": "application/json",
}

# Parâmetros de paginação
GURU_PAGINATION = {
    "per_page": 100,  # Máximo de resultados por página (padrão: 50)
}
