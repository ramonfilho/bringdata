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
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Optional[str]] = {}


# Conta de serviço a personificar. O `gcloud auth print-identity-token
# --audiences=X` **exige conta de serviço**: com conta de usuário ele responde
# "Invalid account type for --audiences". Como quem roda os gates é uma pessoa,
# o caminho é personificar a mesma conta que os crons usam, que já tem
# `roles/run.invoker` no serviço. Quem for rodar precisa de
# `roles/iam.serviceAccountTokenCreator` sobre ela.
SA_PADRAO = "scheduler-invoker@smart-ads-451319.iam.gserviceaccount.com"


def token_de_identidade(audiencia: str) -> Optional[str]:
    """Token de identidade do Google para a audiência dada, ou None.

    Tenta primeiro direto (funciona quando quem roda JÁ é conta de serviço, como
    numa esteira automática) e, se o gcloud recusar por tipo de conta, personifica
    a conta de serviço dos crons.

    Cacheado por audiência: o gate faz dezenas de chamadas e cada chamada ao gcloud
    custa perto de um segundo.
    """
    if audiencia in _CACHE:
        return _CACHE[audiencia]

    sa = os.environ.get("GCP_IMPERSONATE_SA", SA_PADRAO)
    tentativas = [
        (["gcloud", "auth", "print-identity-token", f"--audiences={audiencia}"],
         "direto"),
        (["gcloud", "auth", "print-identity-token",
          f"--impersonate-service-account={sa}", f"--audiences={audiencia}"],
         f"personificando {sa.split('@')[0]}"),
    ]
    tok, ultimo_erro = None, ""
    for cmd, comoquem in tentativas:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            ultimo_erro = str(e)
            continue
        # A personificação escreve aviso no stderr e o token no stdout; pega só a
        # última linha não vazia, que é o token.
        cand = (out.stdout or "").strip().splitlines()
        cand = cand[-1].strip() if cand else ""
        if out.returncode == 0 and len(cand) > 100:
            tok = cand
            logger.info("[auth] token obtido %s", comoquem)
            break
        ultimo_erro = (out.stderr or "").strip()[:160]

    if not tok:
        logger.warning(
            "[auth] SEM token para %s (%s). As chamadas vão sem cabeçalho e o "
            "serviço, que está fechado, vai responder 403.", audiencia, ultimo_erro)
    _CACHE[audiencia] = tok
    return tok


def audiencia_de(url: str) -> str:
    """Audiência esperada pelo Cloud Run para esta URL.

    Para a URL normal do serviço é esquema + host. Para URL de TAG
    (`https://<tag>---<servico>-<hash>-<regiao>.a.run.app`, que é como os gates de
    deploy falam com a revisão canário) a audiência continua sendo a **URL base do
    serviço**, sem o prefixo da tag.

    Isso foi MEDIDO, e contra a minha suposição inicial: token com audiência igual à
    URL de tag leva 401 na própria URL de tag; token com audiência igual à URL base
    leva 200 nela. A primeira versão deste módulo derivava a audiência da URL literal
    e por isso o gate levou 401 assim que o serviço foi fechado.
    """
    p = urllib.parse.urlsplit(url)
    host = p.netloc
    if "---" in host:
        host = host.rsplit("---", 1)[1]
    return f"{p.scheme}://{host}"


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
