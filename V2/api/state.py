"""Estado compartilhado da API: pipelines por cliente, CplLookup e as dependencies do FastAPI.

Gerado a partir do app.py monolítico (corte por domínio, corpo dos handlers intacto)."""
import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from typing import Annotated, List, Dict, Any, Optional
import time
from src.production_pipeline import LeadScoringPipeline
from api.capi_integration import send_batch_events, should_send_to_destination
from fastapi import Depends, Header, Request
import logging

logger = logging.getLogger(__name__)


# A2: dicionário de pipelines indexado por client_id
pipelines: Dict[str, LeadScoringPipeline] = {}


# Bloco F do EVENTOS_E_DECIS_PLANO — lookup de CPL por adset (snapshot Railway
# carregado em memória no startup). 1 por cliente. Consumido pelo pubsub_branch
# pra resolver `cost_context` por lead antes de chamar `send_batch_events`.
# None quando o snapshot falha ou cliente não tem dados — caminho ROAS V1
# fica desligado por construção até refresh seguinte popular.
cpl_lookups: Dict[str, "CplLookup"] = {}  # type: ignore  # forward ref evita import-time


TYPE_CHECKING_CPL = False


if TYPE_CHECKING_CPL:
    from src.data.cost_attribution.cpl_lookup import CplLookup  # noqa: F401


def get_cpl_lookup(client_id: str = 'devclub'):
    """Devolve o `CplLookup` global do cliente. None se não inicializado.

    Consumido por `api/pubsub_branch.py` pra resolver `cost_context` por lead
    quando a variante tem ROAS V1 ativa. Retorno None desabilita ROAS V1 pra
    aquele lead — proteção em camada extra além da flag yaml.
    """
    return cpl_lookups.get(client_id)


def initialize_cpl_lookups() -> None:
    """Carrega 1 snapshot de CPL por cliente no startup do FastAPI.

    Falha (ex.: tabelas vazias ou Railway off) não bloqueia o app — só deixa
    `cpl_lookups[client_id]` ausente. ROAS V1 fica desligado pra esse cliente
    até o próximo restart pós refresh job rodar.
    """
    global cpl_lookups
    try:
        import pg8000.native as _pg8000
        from src.data.cost_attribution.cpl_lookup import CplLookup
    except ImportError as e:
        logger.warning(f"[startup_cpl] imports falharam: {e} — ROAS V1 desligado")
        return
    for client_id in pipelines.keys():
        try:
            conn = _pg8000.Connection(
                host=os.environ['RAILWAY_DB_HOST'],
                port=int(os.environ['RAILWAY_DB_PORT']),
                user=os.environ['RAILWAY_DB_USER'],
                password=os.environ['RAILWAY_DB_PASSWORD'],
                database=os.environ['RAILWAY_DB_NAME'],
            )
            try:
                cpl_lookups[client_id] = CplLookup.from_railway(conn, client_id)
                logger.info(f"[startup_cpl] CplLookup carregado pro '{client_id}'")
            finally:
                conn.close()
        except Exception as e:
            logger.warning(
                f"[startup_cpl] falha ao carregar CplLookup pro '{client_id}': {e} "
                f"— ROAS V1 desligado pra esse cliente até próximo restart"
            )


def initialize_pipelines() -> bool:
    """Inicializa pipelines para todos os clientes em configs/clients/*.yaml"""
    global pipelines
    from pathlib import Path
    configs_dir = Path(__file__).parent.parent / 'configs' / 'clients'
    success = False
    for cfg_path in sorted(configs_dir.glob('*.yaml')):
        client_id = cfg_path.stem
        try:
            logger.info(f"Inicializando pipeline '{client_id}'...")
            pipelines[client_id] = LeadScoringPipeline(client_id=client_id)
            logger.info(f"Pipeline '{client_id}' inicializado com sucesso!")
            success = True
        except Exception as e:
            logger.error(f"Erro ao inicializar pipeline '{client_id}': {e}")
    return success


def get_active_pipeline(
    x_client_id: str = Header(default='devclub', alias='X-Client-ID')
) -> LeadScoringPipeline:
    """Dependency: retorna pipeline do cliente indicado pelo header X-Client-ID."""
    p = pipelines.get(x_client_id)
    if p is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cliente '{x_client_id}' nao configurado. Clientes ativos: {list(pipelines.keys())}"
        )
    return p


def get_optional_pipeline(
    x_client_id: str = Header(default='devclub', alias='X-Client-ID')
) -> Optional[LeadScoringPipeline]:
    """Dependency: retorna pipeline ou None se cliente nao configurado."""
    return pipelines.get(x_client_id)


PipelineDep = Annotated[LeadScoringPipeline, Depends(get_active_pipeline)]


PipelineOptDep = Annotated[Optional[LeadScoringPipeline], Depends(get_optional_pipeline)]
