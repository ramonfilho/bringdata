"""
Configuração da API do Meta (Facebook Ads)
Para produção: Cliente adiciona você como admin no Business Manager

NOTA: Métricas de negócio foram movidas para business_config.py
Este arquivo contém APENAS credenciais da API Meta.
"""

# Credenciais Meta Ads - PRODUÇÃO
META_CONFIG = {
    # Token anterior (TESTE - para verificar se funciona):
    "access_token": "EAAS9hlWC7lkBPmTFNOvHZBVZAW6ESTsmVCStlrcslFvNLxr2xBkKrI0kTmI6dou1aB5UOJLFwQo9gwAg1NZBCSWZCZAkxflALfnFeZC8nYRJJO5TZAfy1vswWFs0nCsZBpOanId4ULYCJMzPqt7UuhfuNBablHZAIchs1T7vEGWXgk6Sq2t8YirZBIPldNDVtyp7DxYQZDZD",

    # Token novo (comentado temporariamente para teste):
    # "access_token": "EAAS9hlWC7lkBQvgWoX63g8x9uYoOWiBBZAojXZCLmBA4nELAXTyLwqNDHARK0stbWj8kAJXqAcN0dO0ZAq0Fc0R379r3ReWKtJ0YxOddVnY6lwsBSCo2PJZCdIayynGG08w0dBnvn87ArMrZBGFMPVhSF5KJnBhmcZAB5THR4ZAZB81ArTCZCzxGai8rKG1QovQZDZD",

    "api_version": "v18.0",
    # Account ID principal: act_188005769808959
    # Account ID será passado por Apps Script
}

# DEPRECATED: BUSINESS_CONFIG movido para business_config.py
# Mantido aqui para compatibilidade com código existente
from api.business_config import BUSINESS_CONFIG

