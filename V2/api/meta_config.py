"""
Configuração da API do Meta (Facebook Ads)
Para produção: Cliente adiciona você como admin no Business Manager

NOTA: Métricas de negócio foram movidas para business_config.py
Este arquivo contém APENAS credenciais da API Meta.

Env var obrigatória: META_ACCESS_TOKEN
"""
import os

# Credenciais Meta Ads - PRODUÇÃO
META_CONFIG = {
    "access_token": os.getenv("META_ACCESS_TOKEN"),  # Obrigatório via env var — nunca hardcodar
    "api_version": "v18.0",
    # Account ID principal: act_188005769808959
    # Account ID será passado por Apps Script
}

# DEPRECATED: BUSINESS_CONFIG movido para business_config.py
# Mantido aqui para compatibilidade com código existente
from api.business_config import BUSINESS_CONFIG

