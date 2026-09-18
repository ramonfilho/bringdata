"""
core/mlflow_setup.py — Fonte única da URI de tracking do MLflow.

Um só lugar define para onde treino, ativação de run e gerador de model card
leem/escrevem (backend Postgres). Antes a URI (com credencial) vivia embutida
no training_model; centralizar evita que o gerador standalone caia num MLflow
local vazio por esquecer de setá-la, e deixa um único ponto pra trocar o host.

A URI vem SEMPRE do ambiente, por um de dois caminhos: `MLFLOW_TRACKING_URI`
pronta (tipicamente do `V2/.env`, que é gitignored), ou `MLFLOW_DB_HOST` +
`MLFLOW_DB_PASSWORD` (mais `MLFLOW_DB_USER`, `MLFLOW_DB_PORT`, `MLFLOW_DB_NAME`,
com default do projeto), que é como o Cloud Run Job de retreino recebe a senha do
Secret Manager, e o código monta a URI. NÃO existe mais default com credencial
embutida, e a ausência é deliberada: até 05/08/2026 a senha do usuário `postgres` do nosso Cloud SQL
estava escrita neste arquivo, num repositório PÚBLICO. Como a instância aceita
conexão de qualquer IP, qualquer pessoa que lesse o GitHub tinha acesso de DONO a
`analytics.leads` (366 mil leads com e-mail, telefone e nome) e a
`analytics.sales`. A senha foi rotacionada; o default saiu para que o próximo
erro possível seja "falta configurar", nunca "vazou de novo".

Sem fallback silencioso: se nenhum dos dois caminhos estiver completo,
`resolve_tracking_uri` levanta exceção com a instrução de correção para os dois
ambientes (Mac com `.env`; Job com variáveis). Cair num MLflow local vazio sem avisar seria
pior: o treino gravaria o run em lugar nenhum e ninguém perceberia.
"""

from __future__ import annotations

import os
from pathlib import Path

_V2_ROOT = Path(__file__).resolve().parents[2]

_COMO_CONFIGURAR = (
    "Backend do MLflow sem configuração. Dois caminhos:\n"
    f"  (a) no Mac: coloque no {_V2_ROOT / '.env'} (gitignored, a senha NUNCA volta pro código)\n"
    "      MLFLOW_TRACKING_URI=postgresql+psycopg2://postgres:<senha>@<host>:5432/mlflow\n"
    "  (b) no Cloud Run Job (scripts/setup_retreino_job.sh): MLFLOW_DB_HOST e MLFLOW_DB_PASSWORD "
    "no ambiente (a senha vem do segredo mlflow-db-password; se só o host chegou, o bind do "
    "segredo falhou).\n"
    "A senha vive no Secret Manager:\n"
    "  gcloud secrets versions access latest --secret=mlflow-db-password "
    "--project=smart-ads-451319"
)


def _uri_das_partes() -> str:
    """Monta a URI do backend a partir de MLFLOW_DB_HOST e MLFLOW_DB_PASSWORD.

    É como o Cloud Run Job de retreino recebe a credencial: a senha vem do Secret
    Manager (`mlflow-db-password`) como variável própria, sem ninguém montar uma URI
    com senha dentro num arquivo. Usuário, porta e banco têm o default do projeto.
    Vazio quando o host ou a senha faltam.
    """
    host, senha = os.environ.get("MLFLOW_DB_HOST"), os.environ.get("MLFLOW_DB_PASSWORD")
    if not host or not senha:
        return ""
    from urllib.parse import quote
    user = os.environ.get("MLFLOW_DB_USER", "postgres")
    port = os.environ.get("MLFLOW_DB_PORT", "5432")
    db = os.environ.get("MLFLOW_DB_NAME", "mlflow")
    return f"postgresql+psycopg2://{quote(user)}:{quote(senha, safe='')}@{host}:{port}/{db}"


def resolve_tracking_uri() -> str:
    """URI efetiva, lida do ambiente (carrega o `V2/.env` se ainda não estiver lá).

    Raises:
        RuntimeError: se `MLFLOW_TRACKING_URI` não estiver configurada.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI") or _uri_das_partes()
    if not uri:
        # O gerador de model card roda standalone, fora do train_pipeline (que já
        # carrega o .env). Carregar aqui mantém ele funcionando sem criar mais um
        # ponto pra esquecer.
        try:
            from dotenv import load_dotenv
            load_dotenv(_V2_ROOT / ".env")
        except ImportError:
            pass
        uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        raise RuntimeError(_COMO_CONFIGURAR)
    return uri


def ensure_tracking_uri() -> str:
    """Aponta o MLflow pro backend do projeto e devolve a URI usada. Idempotente."""
    import mlflow
    uri = resolve_tracking_uri()
    mlflow.set_tracking_uri(uri)
    return uri
