"""
Autenticação dos nossos scripts contra o Cloud Run.

Os gates de deploy (`smoke_test_revision`, `progression_gate`,
`test_revision_equivalence`) chamam o serviço com `urllib` **sem credencial
nenhuma**. Isso só funciona porque o serviço aceita chamada anônima
(`allUsers` em `roles/run.invoker`), que é exatamente o que estamos removendo.
Sem esta camada, fechar o serviço quebraria o deploy inteiro, não só o health
check.

Como funciona: instala um handler no `urllib` que anexa
`Authorization: Bearer <token de identidade>` em toda requisição. Um ponto de
inserção por script, em vez de mexer em cada chamada.

**A audiência é derivada da URL de cada requisição**, e isso importa: o Cloud Run
exige que o `aud` do token bata com a URL chamada. Os gates falam tanto com a URL
do serviço quanto com as URLs de tag (`canary-xxxx---servico...`), que são hosts
diferentes. Token com audiência fixa funcionaria num caso e daria 401 no outro.

Degrada com aviso, não com queda: sem `gcloud` disponível, ou fora de sessão
autenticada, a requisição segue sem cabeçalho. Enquanto o serviço aceitar
anônimo, continua passando; quando não aceitar, o 401 aparece com o motivo no
log em vez de virar mistério.
"""

from __future__ import annotations

import logging
import subprocess
import urllib.parse
import urllib.request
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Optional[str]] = {}


def token_de_identidade(audiencia: str) -> Optional[str]:
    """Token de identidade do Google para a audiência dada, ou None.

    Cacheado por audiência: o gate faz dezenas de chamadas e cada `gcloud auth
    print-identity-token` custa perto de um segundo.
    """
    if audiencia in _CACHE:
        return _CACHE[audiencia]
    try:
        out = subprocess.run(
            ["gcloud", "auth", "print-identity-token", f"--audiences={audiencia}"],
            capture_output=True, text=True, timeout=30,
        )
        tok = out.stdout.strip() if out.returncode == 0 else None
        if not tok:
            logger.warning("[auth] sem token para %s (%s). Seguindo sem cabeçalho.",
                           audiencia, (out.stderr or "").strip()[:120])
    except (OSError, subprocess.SubprocessError) as e:
        tok = None
        logger.warning("[auth] gcloud indisponível (%s). Seguindo sem cabeçalho.", e)
    _CACHE[audiencia] = tok
    return tok


def audiencia_de(url: str) -> str:
    """Audiência esperada pelo Cloud Run: esquema + host, sem caminho."""
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


class _AnexaIdentidade(urllib.request.BaseHandler):
    """Anexa o token de identidade em toda requisição que sair por este opener."""

    # Roda depois dos handlers padrão, antes do envio.
    handler_order = 900

    def https_request(self, req):
        if not req.has_header("Authorization"):
            tok = token_de_identidade(audiencia_de(req.full_url))
            if tok:
                req.add_unredirected_header("Authorization", f"Bearer {tok}")
        return req

    # Cloud Run é sempre https; http fica aqui só para não surpreender em teste local.
    http_request = https_request


def instalar_auth_gcp() -> None:
    """Faz todo `urllib.request.urlopen` deste processo levar identidade.

    Idempotente: chamar duas vezes não empilha handler.
    """
    opener = urllib.request.build_opener(_AnexaIdentidade())
    urllib.request.install_opener(opener)
