"""Autenticação OAuth da Hotmart — FONTE ÚNICA do access token.

A mesma credencial Basic (`HOTMART_BASIC`) e o mesmo endpoint de token servem
duas integrações diferentes:
  - ingestão de VENDAS (`src/validation/data_loader.load_hotmart_sales_from_api`)
  - lead scoring HOTLEADS (`api/hotleads_integration`)

O trecho de auth nasceu embutido no meio do loader de vendas; ao surgir o
segundo consumidor, ele foi extraído pra cá em vez de copiado (o loader passou
a consumir esta função). Se um dia a Hotmart mudar o fluxo de token, muda aqui.

O token da Hotmart vale ~1h; como cada consumidor roda em processo curto
(job/request), não há cache — pedir token é barato perto do resto da chamada.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api-sec-vlc.hotmart.com/security/oauth/token"


def get_hotmart_access_token(basic_env_var: str = "HOTMART_BASIC",
                             timeout: int = 30) -> Optional[str]:
    """Troca a credencial Basic por um access token. None se faltar credencial
    ou a troca falhar (o chamador decide se isso é fatal).

    ATENÇÃO: `HOTMART_BASIC` contém um espaço ("Basic xxx") e por isso é mutilada
    por `set -a; source .env` — quem roda fora do Cloud Run precisa de
    `load_dotenv` ou export seletivo (ver reference_env_source_mutila_credenciais).
    """
    import requests

    basic = os.getenv(basic_env_var)
    if not basic:
        logger.error(f"{basic_env_var} não encontrado no ambiente")
        return None
    if basic.strip() == "Basic":
        logger.error(
            f"{basic_env_var} veio mutilada (só 'Basic', sem o segredo) — "
            "provavelmente `source .env` comeu o resto da linha no espaço"
        )
        return None
    try:
        resp = requests.post(
            TOKEN_URL,
            headers={"Authorization": basic, "Content-Type": "application/json"},
            params={"grant_type": "client_credentials"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as e:
        logger.error(f"Falha na autenticação Hotmart: {e}")
        return None
