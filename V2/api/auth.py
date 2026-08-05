"""
Guarda de autenticação das rotas da API.

Fonte única do "esta rota exige token". Antes desta camada, a checagem existia
copiada em três rotas (`/webhook/sendflow_group_join`, `/hotleads/submit-batch`,
`/hotleads/webhook`), sempre com o mesmo miolo: lê a variável de ambiente, compara
com o que veio na requisição, levanta 401 se não bater ou se a variável não estiver
configurada. As outras 33 rotas não tinham guarda nenhuma, e o serviço aceita
chamada de qualquer pessoa na internet (`allUsers` em `roles/run.invoker`).

Duas camadas, e elas não competem:

  - **IAM do Cloud Run** protege quem chama de dentro: os crons do Cloud Scheduler
    apresentam identidade do Google (OIDC) e a conta de serviço deles tem permissão
    própria de invocador. Essa camada é a certa para chamador interno, e é o que vai
    permitir remover o `allUsers`.
  - **Token de aplicação (aqui)** protege o que precisa continuar alcançável sem
    identidade Google: webhook de terceiro (Hotmart, SendFlow), que não tem como
    assinar token do Google.

Por que a guarda daqui NÃO usa o cabeçalho `Authorization`: é exatamente onde o
Cloud Scheduler põe o token OIDC do Google. Se a gente lesse o mesmo cabeçalho,
uma checagem ingênua rejeitaria os nossos próprios crons. Por isso cada guarda usa
cabeçalho próprio (ou parâmetro de query, no caso da Hotmart, que não deixa mandar
cabeçalho customizado).

Sem variável de ambiente configurada, a guarda **nega**. É deliberado: um segredo
ausente tem que fechar a porta, nunca abrir. Foi assim que as três rotas originais
já se comportavam, e o comportamento está preservado.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Token de uso interno, para rota que não é webhook de terceiro e não deveria estar
# aberta. Fica separado dos tokens de webhook para que vazar um não entregue o outro.
ENV_TOKEN_INTERNO = "API_INTERNAL_TOKEN"


def _confere(recebido: Optional[str], esperado: Optional[str]) -> bool:
    """Comparação em tempo constante. `hmac.compare_digest` evita que o tempo de
    resposta revele quantos caracteres do token o atacante acertou."""
    if not esperado or not recebido:
        return False
    return hmac.compare_digest(str(recebido), str(esperado))


def exigir_token(
    env_var: str,
    *,
    header: Optional[str] = None,
    aceita_query: bool = False,
    nome_query: str = "token",
):
    """Devolve uma dependência do FastAPI que exige o token guardado em `env_var`.

    Args:
        env_var: nome da variável de ambiente com o valor esperado.
        header: cabeçalho onde o token é procurado. Nunca use `Authorization`,
            que é do OIDC do Google (ver cabeçalho deste módulo).
        aceita_query: também aceita o token na query string. Só para terceiro que
            não consegue mandar cabeçalho customizado (é o caso da Hotmart).
        nome_query: nome do parâmetro de query, quando `aceita_query`.

    Returns:
        Função para usar em `Depends(...)`. Levanta 401 se o token não bater ou se
        a variável de ambiente não estiver configurada.
    """

    async def _guarda(request: Request) -> None:
        esperado = os.environ.get(env_var)
        recebido = request.headers.get(header) if header else None
        if not recebido and aceita_query:
            recebido = request.query_params.get(nome_query)
        if not _confere(recebido, esperado):
            # Sem detalhe no corpo: dizer "token ausente" vs "token errado" conta ao
            # atacante em que etapa ele está.
            motivo = "não configurado" if not esperado else "inválido ou ausente"
            logger.warning(
                "401 em %s: token de %s %s", request.url.path, env_var, motivo
            )
            raise HTTPException(status_code=401, detail="não autorizado")

    return _guarda


def exigir_token_interno():
    """Guarda das rotas internas: as que não têm chamador externo legítimo.

    Aplicada só a rota com tráfego legítimo medido em ZERO (janela de 20 a 60 dias
    nos logs do Cloud Run, conferido rota a rota antes de ligar a guarda). Assim o
    raio de impacto desta mudança é, por construção, nenhum.
    """
    return exigir_token(ENV_TOKEN_INTERNO, header="x-internal-token")


# ── Exposição por papel do serviço ───────────────────────────────────────────

ENV_PAPEL = "SERVICE_ROLE"

# Rotas que um serviço de papel `webhook` responde. Todo o resto vira 404.
#
# Para que serve: o IAM do Cloud Run é por SERVIÇO, não por rota. Para tirar o
# `allUsers` do serviço principal sem derrubar o callback da Hotmart, o webhook
# precisa morar num serviço separado, que segue público. Como os dois serviços
# rodam a MESMA imagem (o `smart-ads-monitoring` já faz isso hoje), sem esta lista
# o serviço público exporia as 36 rotas de novo, e o problema voltaria pela porta
# dos fundos.
ROTAS_DO_WEBHOOK = frozenset({
    "/",
    "/health",
    "/hotleads/webhook",
    "/webhook/sendflow_group_join",
})


def papel_do_servico(env=None) -> str:
    """'full' (default) ou 'webhook'. Valor desconhecido cai no default.

    Default é o comportamento de hoje, então esta camada nasce inerte: o serviço
    principal não muda em nada até alguém setar `SERVICE_ROLE=webhook` num serviço
    novo.
    """
    v = (env or os.environ).get(ENV_PAPEL, "").strip().lower()
    return v if v in ("full", "webhook") else "full"


def rota_exposta(caminho: str, papel: Optional[str] = None) -> bool:
    """A rota responde neste papel de serviço?"""
    p = papel or papel_do_servico()
    if p != "webhook":
        return True
    return caminho.rstrip("/") in {r.rstrip("/") for r in ROTAS_DO_WEBHOOK} or caminho == "/"
