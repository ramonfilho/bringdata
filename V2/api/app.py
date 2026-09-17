"""
API V2 para Lead Scoring - Batch Predictions
Otimizada para Google Sheets + Apps Script + Google Cloud

Este arquivo é só o wiring: cria o app, o CORS, o filtro por papel do serviço e o
startup, e inclui os routers. Cada rota vive em api/routers/<domínio>.py (predict,
webhooks, capi, admin, monitoring, daily_check, pending) e o estado compartilhado
(pipelines por cliente, CplLookup, dependencies) em api/state.py. A superfície HTTP
está congelada em tests/fixtures (rotas + OpenAPI); tests/test_app_rotas_congeladas.py
falha se uma rota sumir ou mudar de forma.
"""


import os
import sys
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from api.database import init_database


# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


from api.state import (  # noqa: E402  (estado compartilhado; reexportado para quem importa de api.app)
    pipelines, cpl_lookups, TYPE_CHECKING_CPL, get_cpl_lookup, initialize_cpl_lookups, initialize_pipelines, get_active_pipeline, get_optional_pipeline, PipelineDep, PipelineOptDep,
)


# Inicializar a aplicação FastAPI
# Documentação automática DESLIGADA. `/docs`, `/redoc` e `/openapi.json` serviam,
# anonimamente, 53 KB com o mapa completo da API: toda rota, todo parâmetro e todo
# nome de campo, inclusive `lead_score` e `decil`. Era o índice que tornava as
# outras rotas descobríveis por quem não conhece o sistema. Nada nosso consome
# esses caminhos (conferido em api/, scripts/ e nos gates de deploy); a
# rastreabilidade de "o que roda em produção" vem das labels git da revisão.
# Para reativar em desenvolvimento: exportar API_DOCS_ENABLED=1.
_DOCS = os.environ.get("API_DOCS_ENABLED", "").strip() in ("1", "true", "True")

app = FastAPI(
    title="Bring Data Lead Scoring API V2",
    description="API otimizada para predições em batch via Google Sheets",
    version="2.0.0",
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)

# Adicionar CORS para Google Apps Script e Landing Pages
# Origins base (infra-independente de cliente)
_BASE_ORIGINS = [
    "https://script.google.com",
    "https://script.googleusercontent.com",
    "http://localhost:8001",
    "http://localhost:8000",
]

# Carregar origins específicas de cada cliente a partir de configs/clients/*.yaml
_client_origins: list = []

try:
    from pathlib import Path
    from src.core.client_config import ClientConfig as _ClientConfig
    _clients_dir = Path(__file__).parent.parent / 'configs' / 'clients'
    for _cfg_path in sorted(_clients_dir.glob('*.yaml')):
        try:
            _cfg = _ClientConfig.from_yaml(str(_cfg_path))
            if _cfg.api and _cfg.api.cors_origins:
                _client_origins.extend(_cfg.api.cors_origins)
        except Exception:
            pass
except Exception:
    pass

_ALL_ORIGINS = _BASE_ORIGINS + list(dict.fromkeys(_client_origins))  # preserva ordem, remove dups

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALL_ORIGINS,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Exposição por papel do serviço. Inerte por default (`SERVICE_ROLE` ausente = `full`
# = tudo responde, comportamento de hoje). Existe para o dia em que o callback da
# Hotmart passar a morar num serviço separado e público: como os dois serviços rodam
# a MESMA imagem, sem este filtro o serviço público reexporia as 36 rotas e o buraco
# voltaria pela porta dos fundos. Ver api/auth.py.
@app.middleware("http")
async def _filtrar_por_papel(request: Request, call_next):
    from api.auth import papel_do_servico, rota_exposta
    papel = papel_do_servico()
    if papel != "full" and not rota_exposta(request.url.path, papel):
        # 404 e não 403: para quem sonda de fora, a rota simplesmente não existe
        # neste serviço. 403 confirmaria que ela existe em algum lugar.
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return await call_next(request)

@app.on_event("startup")
async def startup_event():
    """Inicialização da aplicação"""
    logger.info("🚀 Iniciando Bring Data API V2...")
    if not initialize_pipelines():
        logger.error("❌ Falha ao inicializar pipelines!")
    else:
        logger.info(f"✅ API V2 pronta — pipelines ativos: {list(pipelines.keys())}")
        # Bloco F do EVENTOS_E_DECIS_PLANO — snapshot do CPL lookup por cliente.
        # Não bloqueia startup se falhar (ROAS V1 só liga quando flag yaml +
        # variante calibrada + cpl_lookup todos presentes).
        initialize_cpl_lookups()

    # Inicializar database
    if init_database():
        logger.info("✅ Database inicializado com sucesso")
    else:
        logger.warning("⚠️ Database não inicializado (desenvolvimento sem PostgreSQL?)")

    # [S1] Validação de configuração CAPI: cada (pixel_id, event_name) tem que
    # estar acessível via Meta API. Hard fail (config errada) gera log
    # `[STARTUP CHECK] ❌ FATAL` que é detectado pelo smoke_test_revision.py
    # e bloqueia progressão de tráfego.
    try:
        from api.startup_capi_check import validate_capi_destinations
        for client_id, _pipeline in pipelines.items():
            validate_capi_destinations(
                _pipeline._client_config,
                _pipeline._ab_test_config,
                client_id=client_id,
            )
    except Exception as e:
        # Falha do próprio check (não da config) — log e continua, sem bloquear startup
        logger.warning(f"[STARTUP CHECK] ⚠️ erro ao executar validação: {e}")


from api.routers import predict, webhooks, capi, admin, monitoring, daily_check, pending  # noqa: E402

app.include_router(predict.router)
app.include_router(webhooks.router)
app.include_router(capi.router)
app.include_router(admin.router)
app.include_router(monitoring.router)
app.include_router(daily_check.router)
app.include_router(pending.router)


# Nomes movidos para os routers, reexportados para consumidores antigos de `api.app`.
from api.routers.predict import (  # noqa: E402,F401
    LeadData,
    BatchPredictionRequest,
    PredictionResult,
    BatchPredictionResponse,
    root,
    health_check,
    get_model_info,
    predict_batch_json,
    predict_batch_csv,
    DecilCalculationRequest,
    DecilCalculationResult,
    DecilCalculationResponse,
    calculate_decils,
    ExplainRequest,
    predict_explain,
)
from api.routers.webhooks import (  # noqa: E402,F401
    LeadCaptureRequest,
    UpdateSurveyRequest,
    webhook_lead_capture,
    webhook_update_survey,
    webhook_sendflow_group_join,
    _hotleads_webhook_url,
    hotleads_submit_batch,
    hotleads_webhook,
    lead_capture_stats,
    get_recent_leads_endpoint,
    get_leads_by_emails_endpoint,
)
from api.routers.capi import (  # noqa: E402,F401
    _safe_parse_timestamp,
    CapiBatchRequest,
    CapiCheckSentRequest,
    process_daily_batch_capi,
    check_capi_sent,
    PurchaseSaleItem,
    SendPurchaseEventsRequest,
    _lookup_railway_capi_data,
    _send_single_purchase_event,
    send_purchase_events,
)
from api.routers.admin import (  # noqa: E402,F401
    migrate_capi_sent_at,
    cleanup_duplicates,
    cleanup_canary_tags,
    refresh_cpl,
)
from api.routers.monitoring import (  # noqa: E402,F401
    GOOGLE_SHEETS_URL,
    fetch_leads_from_sheets,
    feature_report,
    audience_drift_endpoint,
    audience_quality_endpoint,
    UTM_QUALITY_TRAFEGO_CHANNEL,
    _utm_quality_day_range_brt,
    _utm_quality_compute,
    _build_top5_for,
    _build_top5_window,
    utm_quality_endpoint,
    _resolve_report_channel,
    utm_quality_daily_trafego,
    cost_alert,
    painel_vigia,
    smoke_run_variants,
    test_validation_dependencies,
    execute_weekly_validation,
    _parse_validation_metrics,
)
from api.routers.daily_check import (  # noqa: E402,F401
    DailyCheckRequest,
    DailyCheckResponse,
    daily_monitoring_check_auto,
    daily_monitoring_check_railway,
    post_slack_digest,
    daily_monitoring_check,
)
from api.routers.pending import (  # noqa: E402,F401
    railway_process_pending,
    pubsub_process_pending,
)


if __name__ == "__main__":
    import uvicorn

    # Inicializar pipelines antes de iniciar o servidor
    print("Inicializando pipelines...")
    if initialize_pipelines():
        print(f"Pipelines inicializados: {list(pipelines.keys())}")
    else:
        print("AVISO: Nenhum pipeline inicializado.")

    # Iniciar o servidor
    print("Iniciando servidor na porta 8080...")
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)
