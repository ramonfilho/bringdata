"""
Configuração da API do Digital Manager Guru
Para obter o token: Meu Perfil → Tokens API → Adicionar

IMPORTANTE: Este token carrega muitos privilégios.
Não compartilhe, não exponha no frontend, e guarde com segurança.

Documentação: https://docs.digitalmanager.guru/developers/

Env var obrigatória: GURU_API_TOKEN
"""
import os

# Credenciais Guru API
GURU_CONFIG = {
    "user_token": os.getenv("GURU_API_TOKEN"),  # Obrigatório via env var — nunca hardcodar
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
