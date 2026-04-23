"""
API V2 para Lead Scoring - Batch Predictions
Otimizada para Google Sheets + Apps Script + Google Cloud
"""

import os
import sys
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Annotated, List, Dict, Any, Optional
import io
import time
import tempfile
import uuid
from datetime import datetime
import logging

# Adicionar diretório pai ao path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importar pipeline V2
from src.production_pipeline import LeadScoringPipeline

# Importar integrações

# Importar módulos CAPI
from api.database import get_db, init_database, create_lead_capi, count_leads, count_leads_with_fbp, count_leads_with_fbc, get_leads_by_emails, LeadCAPI
from api.capi_integration import send_batch_events
from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.model.decil_thresholds import atribuir_decil_por_threshold

# URL do Google Sheets para monitoramento
GOOGLE_SHEETS_URL = os.getenv(
    'GOOGLE_SHEETS_URL',
    'https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo'
)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === MODELS ===
class LeadData(BaseModel):
    """Modelo para um lead individual"""
    data: Dict[str, Any]
    email: Optional[str] = None  # Para identificação
    row_id: Optional[str] = None  # ID da linha no Google Sheets

class BatchPredictionRequest(BaseModel):
    """Request para predições em batch"""
    leads: List[LeadData] = Field(..., min_items=1, max_items=600)
    request_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))

class PredictionResult(BaseModel):
    """Resultado de uma predição"""
    lead_score: float
    decil: str  # D1-D10
    email: Optional[str] = None
    row_id: Optional[str] = None

class BatchPredictionResponse(BaseModel):
    """Response para predições em batch"""
    request_id: str
    total_leads: int
    predictions: List[PredictionResult]
    processing_time_seconds: float
    timestamp: str

class DailyCheckRequest(BaseModel):
    """Request para check diário de monitoramento"""
    leads: List[Dict[str, Any]] = Field(..., description="Dados do Sheets das últimas 24h")

class DailyCheckResponse(BaseModel):
    """Response do check diário"""
    total_alerts: int
    alerts_by_severity: Dict[str, int]
    alerts_by_category: Dict[str, int]
    alerts: List[Dict[str, Any]]
    critical_summary: str
    timestamp: str
    funnel_metrics: Optional[Dict[str, Any]] = None
    lead_quality_metrics: Optional[Dict[str, Any]] = None
    revenue_forecast: Optional[Dict[str, Any]] = None
    survey_funnel_metrics: Optional[Dict[str, Any]] = None
    traffic_metrics: Optional[Dict[str, Any]] = None
    # revenue_forecast inclui expected_conversion quando conversion_rate_benchmark está configurado

# Inicializar a aplicação FastAPI
app = FastAPI(
    title="Bring Data Lead Scoring API V2",
    description="API otimizada para predições em batch via Google Sheets",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
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

# A2: dicionário de pipelines indexado por client_id
pipelines: Dict[str, LeadScoringPipeline] = {}


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

# DEPRECATED: Decis agora são calculados por janela de análise
# def convert_decile_to_numeric(decile_str: str) -> int:
#     """Converte D1-D10 para 1-10"""
#     try:
#         return int(decile_str.replace('D', ''))
#     except:
#         return 5

@app.on_event("startup")
async def startup_event():
    """Inicialização da aplicação"""
    logger.info("🚀 Iniciando Bring Data API V2...")
    if not initialize_pipelines():
        logger.error("❌ Falha ao inicializar pipelines!")
    else:
        logger.info(f"✅ API V2 pronta — pipelines ativos: {list(pipelines.keys())}")

    # Inicializar database
    if init_database():
        logger.info("✅ Database inicializado com sucesso")
    else:
        logger.warning("⚠️ Database não inicializado (desenvolvimento sem PostgreSQL?)")

@app.get("/")
async def root():
    """Endpoint raiz"""
    return {
        "message": "Bring Data Lead Scoring API V2",
        "status": "online",
        "version": "2.0.0",
        "endpoints": {
            "health": "/health",
            "predict": "/predict/batch (POST)",
            "model_info": "/model/info (GET)",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    """Health check detalhado"""
    pipeline_status = "healthy" if pipelines else "unhealthy"
    model_loaded = bool(pipelines)

    return {
        "status": "healthy",
        "pipeline_status": pipeline_status,
        "model_loaded": model_loaded,
        "active_clients": list(pipelines.keys()),
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0"
    }

@app.get("/model/info")
async def get_model_info(pipeline: PipelineDep):
    """
    Retorna informações sobre o modelo: metadados, performance e feature importances
    """

    try:
        # Garantir que o modelo está carregado
        if pipeline.predictor.model is None:
            pipeline.predictor.load_model()

        # Obter metadados
        metadata = pipeline.predictor.metadata

        # Obter feature importances (todas)
        feature_importances = pipeline.predictor.get_feature_importances(top_n=None)

        # Carregar mapeamento de nomes de features (transformado → legível)
        try:
            import json
            from pathlib import Path
            model_name = metadata.get("model_info", {}).get("model_name", "")
            mapping_file = Path(__file__).parent.parent / "arquivos_modelo" / f"feature_name_mapping_{model_name}.json"
            if mapping_file.exists():
                with open(mapping_file) as f:
                    mapping_data = json.load(f)
                    feature_name_mapping = mapping_data.get("feature_name_mapping", {})

                # Traduzir nomes das features para versão legível
                for feature_importance in feature_importances:
                    transformed_name = feature_importance['feature']
                    readable_name = feature_name_mapping.get(transformed_name, transformed_name.replace('_', ' '))
                    feature_importance['feature_readable'] = readable_name
                    feature_importance['feature_transformed'] = transformed_name
                    feature_importance['feature'] = readable_name  # Usar nome legível por padrão
        except Exception as e:
            logger.warning(f"⚠️ Não foi possível carregar mapeamento de features: {e}")

        # Estruturar resposta
        response = {
            "model_info": metadata.get("model_info", {}),
            "training_data": metadata.get("training_data", {}),
            "performance_metrics": metadata.get("performance_metrics", {}),
            "decil_analysis": metadata.get("decil_analysis", {}),
            "feature_importances": feature_importances,
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"✅ Informações do modelo retornadas com sucesso")
        return response

    except Exception as e:
        logger.error(f"❌ Erro ao obter informações do modelo: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter informações do modelo: {str(e)}")

@app.post("/predict/batch", response_model=BatchPredictionResponse)
async def predict_batch_json(request: BatchPredictionRequest, pipeline: PipelineDep):
    """
    Predição em batch via JSON
    Otimizado para Google Apps Script
    """

    start_time = time.time()
    logger.info(f"📊 Processando {len(request.leads)} leads (Request ID: {request.request_id})")

    temp_file = None

    try:
        # Converter leads para DataFrame
        lead_rows = []
        for i, lead in enumerate(request.leads):
            row = lead.data.copy()
            # Adicionar metadados
            row['_email'] = lead.email
            row['_row_id'] = lead.row_id or str(i)
            lead_rows.append(row)

        df = pd.DataFrame(lead_rows)
        logger.info(f"📋 DataFrame criado: {df.shape}")

        # Criar arquivo temporário para o pipeline
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
            # Salvar sem as colunas de metadados para o modelo
            model_df = df.drop(columns=['_email', '_row_id'], errors='ignore')
            model_df.to_csv(tmp, index=False)
            temp_file = tmp.name

        # Executar pipeline
        logger.info("🔄 Executando pipeline...")
        result_df = pipeline.run(temp_file, with_predictions=True)

        if result_df is None or len(result_df) == 0:
            raise HTTPException(status_code=500, detail="Pipeline retornou resultado vazio")

        # Calcular decis usando thresholds fixos
        logger.info("🎯 Calculando decis...")
        from src.model.decil_thresholds import atribuir_decis_batch

        # Carregar thresholds do modelo ativo
        thresholds = pipeline.predictor.metadata.get('decil_thresholds', {}).get('thresholds')

        if not thresholds:
            logger.error("❌ Thresholds não encontrados no metadata do modelo!")
            raise HTTPException(
                status_code=500,
                detail="Thresholds não configurados no modelo."
            )

        # Calcular decis
        scores = result_df['lead_score'].values
        decis = atribuir_decis_batch(scores, thresholds)
        result_df['decil'] = decis

        logger.info(f"✅ Decis calculados: {pd.Series(decis).value_counts().sort_index().to_dict()}")

        # Processar resultados
        predictions = []
        for i, (_, row) in enumerate(result_df.iterrows()):
            lead_score = float(row['lead_score'])
            decil = row['decil']

            # Recuperar metadados do lead original
            original_lead = request.leads[i] if i < len(request.leads) else None
            email = original_lead.email if original_lead else None
            row_id = original_lead.row_id if original_lead else str(i)

            predictions.append(PredictionResult(
                lead_score=lead_score,
                decil=decil,
                email=email,
                row_id=row_id
            ))

        processing_time = time.time() - start_time

        logger.info(f"✅ Processamento concluído em {processing_time:.2f}s")
        logger.info(f"📈 Scores: min={min(p.lead_score for p in predictions):.3f}, max={max(p.lead_score for p in predictions):.3f}")

        return BatchPredictionResponse(
            request_id=request.request_id,
            total_leads=len(predictions),
            predictions=predictions,
            processing_time_seconds=round(processing_time, 2),
            timestamp=datetime.now().isoformat()
        )

    except Exception as e:
        logger.error(f"❌ Erro no processamento: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro no processamento: {str(e)}")
    finally:
        # Limpar arquivo temporário
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)

@app.post("/predict/csv")
async def predict_batch_csv(pipeline: PipelineDep, file: UploadFile = File(...)):
    """
    Predição em batch via upload CSV
    Para testes ou uploads manuais
    """

    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Apenas arquivos CSV são aceitos")

    start_time = time.time()
    logger.info(f"📄 Processando arquivo CSV: {file.filename}")

    temp_file = None

    try:
        # Salvar arquivo temporário
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            temp_file = tmp.name

        # Executar pipeline
        result_df = pipeline.run(temp_file, with_predictions=True)

        if result_df is None:
            raise HTTPException(status_code=500, detail="Pipeline retornou resultado vazio")

        # Processar resultados
        predictions = []
        for _, row in result_df.iterrows():
            predictions.append({
                "lead_score": float(row['lead_score']),  # Probabilidade
                "email": row.get('E-mail', None),
                "name": row.get('Nome Completo', None)
            })

        processing_time = time.time() - start_time

        logger.info(f"✅ CSV processado: {len(predictions)} leads em {processing_time:.2f}s")

        return {
            "total_leads": len(predictions),
            "predictions": predictions,
            "processing_time_seconds": round(processing_time, 2),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Erro no processamento CSV: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro no processamento: {str(e)}")
    finally:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)

# === ENDPOINT PARA CÁLCULO DE DECIS (BACKFILL) ===

class DecilCalculationRequest(BaseModel):
    """Request para calcular decis de scores existentes"""
    scores: List[float]

class DecilCalculationResult(BaseModel):
    """Resultado de um cálculo de decil"""
    score: float
    decil: str

class DecilCalculationResponse(BaseModel):
    """Response para cálculo de decis"""
    total_scores: int
    results: List[DecilCalculationResult]
    timestamp: str

@app.post("/calculate_decils", response_model=DecilCalculationResponse)
async def calculate_decils(request: DecilCalculationRequest, pipeline: PipelineDep):
    """
    Calcula decis para scores já existentes (útil para backfill).

    Args:
        request: Lista de lead_scores

    Returns:
        Lista de scores + decis calculados
    """

    try:
        logger.info(f"🎯 Calculando decis para {len(request.scores)} scores...")

        # Carregar thresholds do modelo ativo
        from src.model.decil_thresholds import atribuir_decis_batch

        thresholds = pipeline.predictor.metadata.get('decil_thresholds', {}).get('thresholds')

        if not thresholds:
            logger.error("❌ Thresholds não encontrados no metadata do modelo!")
            raise HTTPException(
                status_code=500,
                detail="Thresholds não configurados no modelo."
            )

        # Calcular decis
        scores = np.array(request.scores)
        decis = atribuir_decis_batch(scores, thresholds)

        # Montar resposta
        results = [
            DecilCalculationResult(score=float(score), decil=decil)
            for score, decil in zip(scores, decis)
        ]

        logger.info(f"✅ Decis calculados: {pd.Series(decis).value_counts().sort_index().to_dict()}")

        return DecilCalculationResponse(
            total_scores=len(results),
            results=results,
            timestamp=datetime.now().isoformat()
        )

    except Exception as e:
        logger.error(f"❌ Erro ao calcular decis: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao calcular decis: {str(e)}")

# === WEBHOOK PARA CAPTURA DE LEADS (CAPI) ===

class LeadCaptureRequest(BaseModel):
    """Dados capturados do lead no frontend"""
    # Dados pessoais
    name: str  # Nome completo (mantido para compatibilidade)
    first_name: Optional[str] = None  # Primeiro nome (para CAPI)
    last_name: Optional[str] = None   # Sobrenome (para CAPI)
    email: str
    phone: Optional[str] = None

    # Dados CAPI
    fbp: Optional[str] = None
    fbc: Optional[str] = None
    event_id: str
    user_agent: Optional[str] = None
    event_source_url: Optional[str] = None

    # UTMs
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None

    # Outros
    tem_comp: Optional[str] = None

    # Dados da Pesquisa (Página 2)
    genero: Optional[str] = None
    idade: Optional[str] = None
    ocupacao: Optional[str] = None
    faixa_salarial: Optional[str] = None
    cartao_credito: Optional[str] = None
    interesse_evento: Optional[str] = None
    estudou_programacao: Optional[str] = None
    pretende_faculdade: Optional[str] = None
    investiu_curso_online: Optional[str] = None
    interesse_programacao: Optional[str] = None
    cidade: Optional[str] = None

class UpdateSurveyRequest(BaseModel):
    """Dados da Página 2 - Pesquisa (atualiza lead existente)"""
    # Identificação (para buscar lead existente)
    email: str

    # Dados básicos (opcionais - vindos da URL da Página 1)
    name: Optional[str] = None
    phone: Optional[str] = None

    # Dados CAPI (Página 2 também captura fbp/fbc)
    fbp: Optional[str] = None
    fbc: Optional[str] = None
    event_id: str
    user_agent: Optional[str] = None
    event_source_url: Optional[str] = None

    # UTMs
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None

    # Dados da Pesquisa (obrigatórios na Página 2)
    genero: Optional[str] = None
    idade: Optional[str] = None
    ocupacao: Optional[str] = None
    faixa_salarial: Optional[str] = None
    cartao_credito: Optional[str] = None
    interesse_evento: Optional[str] = None
    estudou_programacao: Optional[str] = None
    pretende_faculdade: Optional[str] = None
    investiu_curso_online: Optional[str] = None
    interesse_programacao: Optional[str] = None
    cidade: Optional[str] = None

@app.post("/webhook/lead_capture")
async def webhook_lead_capture(
    request: Request,
    lead_data: LeadCaptureRequest,
    pipeline: PipelineDep,
    db: Session = Depends(get_db)
):
    """
    Webhook para capturar dados de leads com FBP/FBC
    Chamado pelo formulário frontend após envio do lead
    """
    try:
        # Verificar se é página de parabéns ANTIGA - IGNORAR para evitar duplicatas
        # Página de Parabéns antiga captura dados incompletos (sem first_name/last_name)
        # Lead já foi capturado corretamente na LP (inscricao)
        # IMPORTANTE: Página v2 (parabens-psq-devf-v2) usa endpoint separado /webhook/update_survey
        event_url = lead_data.event_source_url or ''
        if 'parabens' in event_url.lower() and 'v2' not in event_url.lower():
            logger.info(f"⏭️ Ignorando captura da página de Parabéns antiga: {lead_data.email}")
            return {
                "status": "success",
                "message": "Captura já realizada na LP",
                "skipped": True
            }

        # Capturar IP do cliente (real, não do proxy Cloud Run)
        client_ip = request.headers.get('X-Forwarded-For', request.client.host).split(',')[0].strip()

        # Preparar dados para banco
        lead_dict = {
            'email': lead_data.email,
            'name': lead_data.name,
            'first_name': lead_data.first_name,
            'last_name': lead_data.last_name,
            'phone': lead_data.phone,
            'fbp': lead_data.fbp,
            'fbc': lead_data.fbc,
            'event_id': lead_data.event_id,
            'user_agent': lead_data.user_agent,
            'client_ip': client_ip,
            'event_source_url': lead_data.event_source_url,
            'utm_source': lead_data.utm_source,
            'utm_medium': lead_data.utm_medium,
            'utm_campaign': lead_data.utm_campaign,
            'utm_term': lead_data.utm_term,
            'utm_content': lead_data.utm_content,
            'tem_comp': lead_data.tem_comp,
            # Dados da pesquisa
            'genero': lead_data.genero,
            'idade': lead_data.idade,
            'ocupacao': lead_data.ocupacao,
            'faixa_salarial': lead_data.faixa_salarial,
            'cartao_credito': lead_data.cartao_credito,
            'interesse_evento': lead_data.interesse_evento,
            'estudou_programacao': lead_data.estudou_programacao,
            'pretende_faculdade': lead_data.pretende_faculdade,
            'investiu_curso_online': lead_data.investiu_curso_online,
            'interesse_programacao': lead_data.interesse_programacao,
            'cidade': lead_data.cidade,
            'client_id': pipeline._client_config.client_id,
        }

        # Salvar no banco
        lead_record = create_lead_capi(db, lead_dict)

        logger.info(f"✅ Lead capturado na Página 1 (Inscrição): {lead_data.email} (ID: {lead_record.id}, Event ID: {lead_data.event_id})")

        # ================================================================
        # NOTA: Scoring ML será feito no endpoint /webhook/update_survey
        # (Página 2 - Pesquisa) quando o lead preencher os dados da pesquisa
        # ================================================================

        # DEPRECATED: Lógica antiga que tentava fazer scoring aqui
        # Página 1 nunca tem dados de pesquisa, então isso nunca executava
        if False:  # Desabilitado - mantido apenas para referência
            try:
                logger.info(f"🔮 Gerando score ML para {lead_data.email}...")

                # 1. MAPEAMENTO: PostgreSQL → Google Sheets (nomes de colunas)
                # O modelo foi treinado com nomes originais do Sheets
                lead_dict_raw = lead_record.to_dict()

                # Mapeamento de colunas normalizadas → nomes do Sheets (vem de ClientConfig)
                column_mapping = (
                    pipeline._client_config.api.sheets_column_names
                    if pipeline and pipeline._client_config.api and pipeline._client_config.api.sheets_column_names
                    else {}
                )

                # Aplicar mapeamento
                lead_dict_mapped = {}
                for col_pg, col_sheets in column_mapping.items():
                    if col_pg in lead_dict_raw:
                        lead_dict_mapped[col_sheets] = lead_dict_raw[col_pg]

                # 2. SCORING - Usar pipeline existente com nomes do Sheets
                lead_df = pd.DataFrame([lead_dict_mapped])
                logger.info(f"   DataFrame criado: {lead_df.shape}, colunas={list(lead_df.columns)[:10]}")

                # DEBUG: Verificar se tem coluna Data (pode estar filtrando)
                if 'Data' in lead_df.columns:
                    logger.info(f"   Coluna Data: {lead_df['Data'].iloc[0] if len(lead_df) > 0 else 'vazio'}")

                # Processar dados (feature engineering + encoding)
                pipeline.data = lead_df
                pipeline.original_data = lead_df.copy()

                # Aplicar apenas transformações essenciais (SEM filtros de data/duplicatas)
                logger.info("   Aplicando feature engineering...")
                processed_df = create_derived_features(lead_df)

                logger.info("   Aplicando encoding categórico...")
                # Passar mlflow_run_id para garantir que todas as features esperadas sejam criadas
                mlflow_run_id = pipeline.predictor.mlflow_run_id if hasattr(pipeline.predictor, 'mlflow_run_id') else None
                processed_df = apply_categorical_encoding(processed_df, mlflow_run_id=mlflow_run_id)

                logger.info(f"   DataFrame processado: {processed_df.shape}")

                # Fazer predição com dados processados
                result_df = pipeline.predictor.predict(processed_df, original_df=lead_df)

                # 3. Calcular decil usando thresholds do modelo
                lead_score_value = float(result_df['lead_score'].iloc[0])
                thresholds = pipeline.predictor.metadata.get('decil_thresholds', {}).get('thresholds', {})

                if thresholds:
                    decil_value = atribuir_decil_por_threshold(lead_score_value, thresholds)
                else:
                    logger.warning("⚠️ Thresholds não encontrados no modelo, usando decil padrão")
                    decil_value = "D05"  # Fallback

                # 4. Atualizar banco com score + decil
                lead_record.lead_score = lead_score_value
                lead_record.decil = str(decil_value)
                lead_record.scored_at = func.now()
                db.commit()
                db.refresh(lead_record)

                logger.info(f"✅ Score gerado: {lead_record.lead_score:.4f} ({lead_record.decil})")

                # 3. CAPI - Usar função existente (batch com 1 lead)
                logger.info(f"📤 Enviando evento CAPI para {lead_data.email}...")

                capi_result = send_batch_events([{
                    'email': lead_record.email,
                    'phone': lead_record.phone,
                    'first_name': lead_record.first_name,
                    'last_name': lead_record.last_name,
                    'lead_score': lead_record.lead_score,
                    'decil': lead_record.decil,
                    'event_id': lead_record.event_id,
                    'fbp': lead_record.fbp,
                    'fbc': lead_record.fbc,
                    'user_agent': lead_record.user_agent,
                    'client_ip': lead_record.client_ip,
                    'event_source_url': lead_record.event_source_url
                }], db, capi_config=pipeline._client_config.capi,
                    business_config=pipeline._client_config.business,
                    client_id=pipeline._client_config.client_id)

                logger.info(f"✅ CAPI enviado: {capi_result.get('success', 0)}/{capi_result.get('total', 0)} eventos")

            except Exception as e:
                logger.error(f"⚠️ Erro ao processar ML/CAPI (lead salvo): {str(e)}")
                # Não falhar o webhook - lead já está salvo no banco

        return {
            "status": "success",
            "message": "Lead capturado na Página 1 (Inscrição) - aguardando dados da pesquisa",
            "lead_id": lead_record.id,
            "event_id": lead_data.event_id,
            "email": lead_record.email,
            "next_step": "Página 2 deve chamar /webhook/update_survey"
        }

    except Exception as e:
        logger.error(f"❌ Erro ao capturar lead: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao capturar lead: {str(e)}")

@app.post("/webhook/update_survey")
async def webhook_update_survey(
    request: Request,
    survey_data: UpdateSurveyRequest,
    pipeline: PipelineDep,
    db: Session = Depends(get_db)
):
    """
    Webhook para atualizar lead com dados da Página 2 - Pesquisa

    Fluxo:
    1. Busca lead existente por email (criado na Página 1)
    2. Atualiza com dados da pesquisa
    3. Gera score ML + decil
    4. Envia para CAPI

    Chamado pelo formulário da Página 2 após preenchimento da pesquisa
    """
    try:
        from api.database import get_lead_by_email

        logger.info(f"📊 Página 2 - Atualizando lead com dados da pesquisa: {survey_data.email}")

        # 1. BUSCAR LEAD EXISTENTE
        existing_lead = get_lead_by_email(db, survey_data.email, client_id=pipeline._client_config.client_id)

        if not existing_lead:
            logger.error(f"❌ Lead não encontrado: {survey_data.email}")
            raise HTTPException(
                status_code=404,
                detail=f"Lead não encontrado. Por favor, preencha a Página 1 primeiro."
            )

        logger.info(f"✅ Lead encontrado: ID {existing_lead.id} (criado em {existing_lead.created_at})")

        # 2. ATUALIZAR COM DADOS DA PESQUISA
        # Capturar IP do cliente
        client_ip = request.headers.get('X-Forwarded-For', request.client.host).split(',')[0].strip()

        # Atualizar campos de pesquisa
        existing_lead.genero = survey_data.genero
        existing_lead.idade = survey_data.idade
        existing_lead.ocupacao = survey_data.ocupacao
        existing_lead.faixa_salarial = survey_data.faixa_salarial
        existing_lead.cartao_credito = survey_data.cartao_credito
        existing_lead.interesse_evento = survey_data.interesse_evento
        existing_lead.estudou_programacao = survey_data.estudou_programacao
        existing_lead.pretende_faculdade = survey_data.pretende_faculdade
        existing_lead.investiu_curso_online = survey_data.investiu_curso_online
        existing_lead.interesse_programacao = survey_data.interesse_programacao
        existing_lead.cidade = survey_data.cidade

        # Atualizar dados CAPI da Página 2 (podem ser diferentes da Página 1)
        if survey_data.fbp:
            existing_lead.fbp = survey_data.fbp
        if survey_data.fbc:
            existing_lead.fbc = survey_data.fbc
        if survey_data.user_agent:
            existing_lead.user_agent = survey_data.user_agent
        if survey_data.event_source_url:
            existing_lead.event_source_url = survey_data.event_source_url

        # Salvar alterações
        db.commit()
        db.refresh(existing_lead)

        logger.info(f"✅ Lead atualizado com dados da pesquisa: {survey_data.email}")

        # [T1-3] Deduplicação CAPI: não enviar se já foi enviado
        if existing_lead.capi_sent_at is not None:
            logger.warning(
                f"[T1-3] Lead {survey_data.email} já enviado ao CAPI em "
                f"{existing_lead.capi_sent_at} — ignorando duplicata"
            )
            return {
                "status": "success",
                "message": "Lead já processado e enviado ao CAPI",
                "lead_id": existing_lead.id,
                "scored": True,
                "capi_skipped": "already_sent",
            }

        # 3. SCORING ML + CAPI
        try:
            logger.info(f"🔮 Gerando score ML para {survey_data.email}...")

            # Verificar se tem dados mínimos para scoring
            has_survey_data = any([
                existing_lead.genero, existing_lead.idade, existing_lead.ocupacao,
                existing_lead.faixa_salarial, existing_lead.cartao_credito,
                existing_lead.interesse_evento, existing_lead.estudou_programacao,
                existing_lead.pretende_faculdade, existing_lead.investiu_curso_online,
                existing_lead.interesse_programacao, existing_lead.cidade
            ])

            if not has_survey_data:
                logger.warning(f"⚠️ Dados de pesquisa incompletos para {survey_data.email}")
                return {
                    "status": "success",
                    "message": "Lead atualizado, mas sem dados suficientes para scoring",
                    "lead_id": existing_lead.id,
                    "scored": False
                }

            # Preparar dados para ML (com mapeamento de colunas)
            lead_dict_raw = existing_lead.to_dict()

            # Mapeamento: PostgreSQL → Google Sheets (nomes originais do modelo, vem de ClientConfig)
            column_mapping = (
                pipeline._client_config.api.sheets_column_names
                if pipeline and pipeline._client_config.api and pipeline._client_config.api.sheets_column_names
                else {}
            )

            # Aplicar mapeamento
            lead_dict_mapped = {}
            for col_pg, col_sheets in column_mapping.items():
                if col_pg in lead_dict_raw:
                    lead_dict_mapped[col_sheets] = lead_dict_raw[col_pg]

            # Criar DataFrame com nomes do Sheets
            lead_df = pd.DataFrame([lead_dict_mapped])
            logger.info(f"   DataFrame criado: {lead_df.shape}, colunas={list(lead_df.columns)[:10]}")

            # A/B test routing: identificar variante pelos UTMs do lead
            lead_utms = {
                'utm_source': existing_lead.utm_source,
                'utm_medium': existing_lead.utm_medium,
                'utm_campaign': existing_lead.utm_campaign,
                'utm_term': existing_lead.utm_term,
                'utm_content': existing_lead.utm_content,
            }
            ab_variant = pipeline.get_ab_variant(lead_utms)
            predictor_override = None
            enc_overrides_single = None
            if ab_variant:
                # Encontrar nome da variante para obter o predictor correspondente
                ab_variant_name = next(
                    name for name, v in pipeline._ab_test_config.variants.items()
                    if v is ab_variant
                )
                predictor_override = pipeline.get_variant_predictor(ab_variant_name)
                enc_overrides_single = ab_variant.encoding_overrides
                logger.info(f"🔀 A/B test: variante '{ab_variant_name}' selecionada para {existing_lead.email}")
            elif pipeline._ab_test_config.enabled:
                # Sem variante → Champion. Buscar encoding_overrides do Champion pelo run_id.
                champion_run_id = pipeline.predictor.mlflow_run_id if hasattr(pipeline.predictor, 'mlflow_run_id') else None
                champion_cfg = next(
                    (v for v in pipeline._ab_test_config.variants.values() if v.run_id == champion_run_id),
                    None,
                ) if champion_run_id else None
                enc_overrides_single = champion_cfg.encoding_overrides if champion_cfg else None

            # Usar pipeline.run() completo (igual /predict/batch)
            # Isso garante que TODAS as transformações de dados sejam aplicadas
            temp_file = None
            try:
                # Salvar em CSV temporário
                with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
                    lead_df.to_csv(tmp, index=False)
                    temp_file = tmp.name

                logger.info("   Executando pipeline completo...")
                result_df = pipeline.run(temp_file, with_predictions=True, predictor_override=predictor_override, encoding_overrides=enc_overrides_single)

                if result_df is None or len(result_df) == 0:
                    raise HTTPException(status_code=500, detail="Pipeline retornou resultado vazio")

            finally:
                # Limpar arquivo temporário
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)

            # Calcular decil usando thresholds do modelo ativo para este lead
            active_predictor = predictor_override or pipeline.predictor
            lead_score_value = float(result_df['lead_score'].iloc[0])
            thresholds = active_predictor.metadata.get('decil_thresholds', {}).get('thresholds', {})

            if thresholds:
                decil_value = atribuir_decil_por_threshold(lead_score_value, thresholds)
            else:
                logger.warning("⚠️ Thresholds não encontrados, usando decil padrão")
                decil_value = "D05"

            # Atualizar banco com score + decil
            existing_lead.lead_score = lead_score_value
            existing_lead.decil = str(decil_value)
            existing_lead.scored_at = func.now()
            db.commit()
            db.refresh(existing_lead)

            logger.info(f"✅ Score gerado: {existing_lead.lead_score:.4f} ({existing_lead.decil})")

            # 4. ENVIAR PARA CAPI
            logger.info(f"📤 Enviando evento CAPI para {survey_data.email}...")

            # Usar timestamp atual (não created_at) para evitar problema de relógio adiantado
            import time
            event_timestamp = int(time.time()) - 60  # Subtrair 60 segundos para garantir que não está no futuro

            # Montar lead dict com overrides A/B se variante identificada
            lead_capi_dict = {
                'email': existing_lead.email,
                'phone': existing_lead.phone,
                'first_name': existing_lead.first_name,
                'last_name': existing_lead.last_name,
                'lead_score': existing_lead.lead_score,
                'decil': existing_lead.decil,
                'event_id': survey_data.event_id,  # Event ID da Página 2
                'fbp': existing_lead.fbp,
                'fbc': existing_lead.fbc,
                'user_agent': existing_lead.user_agent,
                'client_ip': client_ip,
                'event_source_url': existing_lead.event_source_url,
                'event_timestamp': event_timestamp,  # Timestamp do lead original
                'survey_data': {  # Dados da pesquisa para matching na Meta
                    'genero': existing_lead.genero,
                    'cidade': existing_lead.cidade
                }
            }
            if ab_variant:
                lead_capi_dict['ab_event_name'] = ab_variant.capi_event_name
                lead_capi_dict['ab_event_name_hq'] = ab_variant.capi_event_name_high_quality
                lead_capi_dict['ab_conversion_rates'] = ab_variant.conversion_rates

            # UTM filter: blocklist por campaign + allowlist por source (DT-CAPI-01/02)
            _utm_cam = (existing_lead.utm_campaign or '').lower()
            _utm_src = (existing_lead.utm_source or '').lower()
            _blocklist = pipeline._client_config.capi.utm_blocklist or []
            _allowlist = pipeline._client_config.capi.utm_source_allowlist or []
            _capi_blocked = any(p.lower() in _utm_cam for p in _blocklist)
            _capi_skipped = bool(_allowlist) and not any(s.lower() in _utm_src for s in _allowlist)
            if _capi_blocked:
                logger.info(f"⏭️ CAPI bloqueado por UTM blocklist: {existing_lead.utm_campaign}")
                capi_result = {"success": 0, "total": 0, "errors": 0}
            elif _capi_skipped:
                logger.info(f"⏭️ CAPI ignorado — source não permitido: {existing_lead.utm_source}")
                capi_result = {"success": 0, "total": 0, "errors": 0}
            else:
                capi_result = send_batch_events(
                    [lead_capi_dict], db,
                    capi_config=pipeline._client_config.capi,
                    business_config=pipeline._client_config.business,
                    client_id=pipeline._client_config.client_id)

            logger.info(f"✅ CAPI enviado: {capi_result.get('success', 0)}/{capi_result.get('total', 0)} eventos")

            return {
                "status": "success",
                "message": "Lead atualizado com dados da pesquisa + scoring ML + CAPI enviado",
                "lead_id": existing_lead.id,
                "event_id": survey_data.event_id,
                "scored": True,
                "lead_score": float(existing_lead.lead_score),
                "decil": existing_lead.decil,
                "capi_sent": capi_result.get('success', 0) > 0
            }

        except Exception as e:
            logger.error(f"⚠️ Erro ao processar ML/CAPI: {str(e)}")
            # Não falhar o webhook - lead já está atualizado com dados da pesquisa
            return {
                "status": "partial_success",
                "message": "Lead atualizado, mas erro ao gerar score ou enviar CAPI",
                "lead_id": existing_lead.id,
                "error": str(e),
                "scored": False
            }

    except HTTPException:
        raise  # Re-lançar HTTPException (404 se lead não encontrado)
    except Exception as e:
        logger.error(f"❌ Erro ao atualizar lead com pesquisa: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar lead: {str(e)}")

@app.get("/webhook/lead_capture/stats")
async def lead_capture_stats(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Estatísticas de captura de leads CAPI
    Útil para monitoramento e debug

    Args:
        start_date: Data início (YYYY-MM-DD) - opcional
        end_date: Data fim (YYYY-MM-DD) - opcional
    """
    try:
        from datetime import datetime, timedelta

        # Construir query base
        query = db.query(LeadCAPI)

        # Aplicar filtros de data se fornecidos
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(LeadCAPI.created_at >= start_dt)

        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            # Incluir todo o dia final
            end_dt = end_dt + timedelta(days=1)
            query = query.filter(LeadCAPI.created_at < end_dt)

        # Contar totais
        total = query.count()
        with_fbp = query.filter(LeadCAPI.fbp.isnot(None), LeadCAPI.fbp != '').count()
        with_fbc = query.filter(LeadCAPI.fbc.isnot(None), LeadCAPI.fbc != '').count()
        with_utm = query.filter(LeadCAPI.utm_campaign.isnot(None), LeadCAPI.utm_campaign != '').count()

        return {
            "total_leads": total,
            "leads_with_fbp": with_fbp,
            "leads_with_fbc": with_fbc,
            "leads_with_utm_campaign": with_utm,
            "fbp_fill_rate": round(with_fbp / total * 100, 2) if total > 0 else 0,
            "fbc_fill_rate": round(with_fbc / total * 100, 2) if total > 0 else 0,
            "utm_fill_rate": round(with_utm / total * 100, 2) if total > 0 else 0,
            "period": f"{start_date or 'início'} a {end_date or 'hoje'}"
        }

    except Exception as e:
        logger.error(f"❌ Erro ao obter stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter stats: {str(e)}")

@app.get("/webhook/lead_capture/recent")
async def get_recent_leads_endpoint(
    pipeline: PipelineOptDep,
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retorna leads recentes com filtros opcionais de data

    Args:
        limit: Número máximo de leads (padrão: 10, máx: 10000)
        start_date: Data início (YYYY-MM-DD) - opcional
        end_date: Data fim (YYYY-MM-DD) - opcional
    """
    try:
        from api.database import get_recent_leads
        from datetime import datetime, timedelta

        # Limitar máximo
        if limit > 10000:
            limit = 10000

        # Se tiver filtros de data, usar query customizada
        if start_date or end_date:
            query = db.query(LeadCAPI)

            if start_date:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(LeadCAPI.created_at >= start_dt)

            if end_date:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(LeadCAPI.created_at < end_dt)

            leads = query.order_by(LeadCAPI.created_at.desc()).limit(limit).all()
        else:
            # Sem filtros, usar função existente
            leads = get_recent_leads(db, limit=limit, client_id=pipeline._client_config.client_id if pipeline else 'devclub')

        return {
            "total": len(leads),
            "leads": [lead.to_dict() for lead in leads],
            "period": f"{start_date or 'início'} a {end_date or 'hoje'}" if (start_date or end_date) else "recent"
        }

    except Exception as e:
        logger.error(f"❌ Erro ao buscar leads: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")

@app.post("/webhook/lead_capture/by_emails")
async def get_leads_by_emails_endpoint(
    pipeline: PipelineOptDep,
    request: dict,
    db: Session = Depends(get_db)
):
    """
    Busca leads por lista de emails com filtro de data opcional

    Body:
        {
            "emails": ["email1@example.com", "email2@example.com"],
            "start_date": "2025-11-18",  // opcional
            "end_date": "2025-11-24"     // opcional
        }
    """
    try:
        from datetime import datetime, timedelta
        from api.database import get_leads_by_emails

        emails = request.get('emails', [])
        start_date = request.get('start_date')
        end_date = request.get('end_date')

        if not emails:
            raise HTTPException(status_code=400, detail="Lista de emails é obrigatória")

        # Buscar leads
        leads = get_leads_by_emails(db, emails, client_id=pipeline._client_config.client_id if pipeline else 'devclub')

        # Filtrar por data se fornecido
        if start_date or end_date:
            filtered_leads = []
            for lead in leads:
                if start_date:
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    if lead.created_at < start_dt:
                        continue

                if end_date:
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                    if lead.created_at >= end_dt:
                        continue

                filtered_leads.append(lead)

            leads = filtered_leads

        # Contar com UTM válida
        with_utm = sum(1 for lead in leads if lead.utm_campaign and lead.utm_campaign.strip())

        return {
            "total_requested": len(emails),
            "total_found": len(leads),
            "leads_with_utm": with_utm,
            "utm_fill_rate": round(with_utm / len(leads) * 100, 2) if leads else 0,
            "leads": [lead.to_dict() for lead in leads],
            "period": f"{start_date or 'início'} a {end_date or 'hoje'}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro ao buscar leads por emails: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")

# === CAPI BATCH PROCESSING ===

def _safe_parse_timestamp(data_value) -> int:
    """
    Parse timestamp de forma segura, tratando casos de erro

    Args:
        data_value: Valor da data (pode ser int, float, string, ou "#ERROR!")

    Returns:
        int: Timestamp UNIX (segundos desde epoch)
    """
    try:
        # Caso 1: Já é timestamp numérico
        if isinstance(data_value, (int, float)):
            return int(data_value)

        # Caso 2: String vazia ou None
        if not data_value or str(data_value).strip() == '':
            logger.warning("⚠️ Data vazia, usando timestamp atual")
            return int(time.time())

        # Caso 3: String "#ERROR!" do Google Sheets
        if str(data_value).strip() == '#ERROR!':
            logger.warning("⚠️ Data com erro (#ERROR!), usando timestamp atual")
            return int(time.time())

        # Caso 4: String de data válida
        parsed_date = pd.to_datetime(data_value, errors='coerce')

        # Se parsing falhou (NaT - Not a Time)
        if pd.isna(parsed_date):
            logger.warning(f"⚠️ Não foi possível parsear data '{data_value}', usando timestamp atual")
            return int(time.time())

        return int(parsed_date.timestamp())

    except Exception as e:
        logger.warning(f"⚠️ Erro ao parsear timestamp '{data_value}': {str(e)}, usando timestamp atual")
        return int(time.time())

class CapiBatchRequest(BaseModel):
    """Request para processamento batch CAPI"""
    leads: List[Dict[str, Any]] = Field(..., description="TODOS os leads do dia anterior (D1-D10)")

class CapiCheckSentRequest(BaseModel):
    """Request para verificar quais leads já foram enviados"""
    emails: List[str] = Field(..., description="Lista de emails para verificar")

@app.post("/capi/process_daily_batch")
async def process_daily_batch_capi(
    request: CapiBatchRequest,
    pipeline: PipelineDep,
    db: Session = Depends(get_db)
):
    """
    Processa batch de CAPI com thresholds fixos
    Envia 2 eventos para cada lead:
    - LeadQualified (com valor): TODOS os leads (D1-D10)
    - LeadQualifiedHighQuality (sem valor): Apenas D9-D10

    Chamado pelo Apps Script a cada 3 horas após classificação ML
    """
    try:
        logger.info(f"📊 Processando batch CAPI: {len(request.leads)} leads (D1-D10)")

        # ====================================================================
        # ETAPA 1: CARREGAR THRESHOLDS FIXOS DO MODELO ATIVO
        # ====================================================================
        from src.model.decil_thresholds import atribuir_decis_batch

        # Carregar thresholds do modelo ativo (via pipeline global)
        thresholds = pipeline.predictor.metadata.get('decil_thresholds', {}).get('thresholds')

        if not thresholds:
            logger.error("❌ Thresholds não encontrados no metadata do modelo!")
            raise HTTPException(
                status_code=500,
                detail="Thresholds não configurados no modelo. Retreine o modelo com --save-files."
            )

        logger.info(f"   ✅ Thresholds carregados: {pipeline.predictor.metadata['model_info']['model_name']}")

        # ====================================================================
        # ETAPA 2: CALCULAR DECIS USANDO THRESHOLDS FIXOS
        # ====================================================================
        # Criar DataFrame com lead_scores - APENAS leads com score válido
        # CORREÇÃO: Filtrar leads SEM score para evitar erro "list indices must be integers"
        valid_leads = []
        invalid_count = 0

        for lead in request.leads:
            if 'email' not in lead or 'lead_score' not in lead:
                continue

            score_val = lead['lead_score']

            # Validar que score não é vazio/inválido
            if score_val in [None, '', 'null', 'NaN'] or str(score_val).strip() == '':
                invalid_count += 1
                continue

            try:
                score_float = float(score_val)
                # Validar range (0 < score <= 1)
                if 0 < score_float <= 1:
                    valid_leads.append({
                        'email': lead['email'],
                        'lead_score': score_float
                    })
                else:
                    invalid_count += 1
            except (ValueError, TypeError):
                invalid_count += 1
                continue

        if invalid_count > 0:
            logger.warning(f"⚠️ {invalid_count} leads com lead_score inválido/vazio ignorados")

        leads_df = pd.DataFrame(valid_leads)

        if len(leads_df) == 0:
            logger.warning("⚠️ Nenhum lead com lead_score válido encontrado")
            logger.warning("💡 Sugestão: Gere os scores primeiro usando /predict/batch")
            return {
                "status": "error",
                "message": "Nenhum lead com lead_score válido encontrado. Gere os scores primeiro usando /predict/batch antes de enviar para CAPI.",
                "total": len(request.leads),
                "valid_leads": 0,
                "invalid_leads": invalid_count,
                "success": 0,
                "errors": 0
            }

        # Garantir que lead_score é numérico (conversão final)
        leads_df['lead_score'] = pd.to_numeric(leads_df['lead_score'], errors='coerce')

        # Remover qualquer NaN que possa ter sido gerado
        nan_count = leads_df['lead_score'].isna().sum()
        if nan_count > 0:
            logger.warning(f"⚠️ {nan_count} scores NaN detectados e removidos")
            leads_df = leads_df[leads_df['lead_score'].notna()].copy()

        if len(leads_df) == 0:
            logger.error("❌ Todos os scores são inválidos após conversão numérica")
            return {
                "status": "error",
                "message": "Todos os scores são inválidos",
                "total": len(request.leads),
                "success": 0,
                "errors": len(request.leads)
            }

        # Análise de scores
        logger.info(f"   📊 Análise de scores:")
        logger.info(f"      - Total de leads: {len(leads_df)}")
        logger.info(f"      - Valores únicos: {leads_df['lead_score'].nunique()}")
        logger.info(f"      - Score min: {leads_df['lead_score'].min():.4f}")
        logger.info(f"      - Score max: {leads_df['lead_score'].max():.4f}")
        logger.info(f"      - Score mean: {leads_df['lead_score'].mean():.4f}")
        logger.info(f"      - Score std: {leads_df['lead_score'].std():.4f}")

        # Atribuir decis usando thresholds fixos
        logger.info(f"   🔄 Atribuindo decis usando thresholds fixos...")
        leads_df['decil'] = atribuir_decis_batch(
            leads_df['lead_score'].values,
            thresholds
        )

        # Criar mapeamento email → decil
        decil_map = dict(zip(leads_df['email'], leads_df['decil']))

        logger.info(f"   ✅ Decis calculados para {len(decil_map)} leads (thresholds fixos)")
        logger.info(f"   📊 Distribuição por decil: {leads_df['decil'].value_counts().sort_index().to_dict()}")

        # ====================================================================
        # ETAPA 3: BUSCAR DADOS CAPI DO BANCO
        # ====================================================================
        emails = list(decil_map.keys())
        leads_capi = get_leads_by_emails(db, emails, client_id=pipeline._client_config.client_id)

        # Criar mapeamento email → dados CAPI
        # Prioriza registros com first_name preenchido (evita sobrescrever com registro incompleto)
        capi_map = {}
        for lead in leads_capi:
            existing = capi_map.get(lead.email)
            if existing is None:
                # Primeiro registro para este email
                capi_map[lead.email] = lead
            elif lead.first_name and not existing.first_name:
                # Novo registro tem first_name, existente não tem - usar o novo
                capi_map[lead.email] = lead
            # Caso contrário, manter o existente

        logger.info(f"   {len(capi_map)} leads encontrados no banco CAPI")

        # ====================================================================
        # ETAPA 4: ENRIQUECER LEADS COM DECIS E DADOS CAPI
        # ====================================================================
        enriched_leads = []
        for lead in request.leads:
            email = lead.get('email')
            if not email:
                continue

            # Obter decil calculado
            decil = str(decil_map.get(email, 'D1'))  # Default D1 se não encontrado

            capi_data = capi_map.get(email)

            # Extrair first_name e last_name - prioridade: pesquisa (100% preenchido)
            first_name = None
            last_name = None

            # 1. Tentar da pesquisa (campo 'Nome Completo')
            nome_completo = lead.get('Nome Completo', '')
            if nome_completo and str(nome_completo).strip():
                name_parts = str(nome_completo).strip().split(' ', 1)
                first_name = name_parts[0]
                last_name = name_parts[1] if len(name_parts) > 1 else None
            # 2. Fallback: banco CAPI
            elif capi_data:
                if capi_data.first_name:
                    first_name = capi_data.first_name
                    last_name = capi_data.last_name
                elif capi_data.name:
                    name_parts = capi_data.name.strip().split(' ', 1)
                    first_name = name_parts[0]
                    last_name = name_parts[1] if len(name_parts) > 1 else None

            # Montar dados para CAPI
            # Phone: tentar 'phone' (do Apps Script) ou 'Telefone' (da pesquisa)
            phone = lead.get('phone') or lead.get('Telefone')

            # Dados da pesquisa (enriquecem targeting da Meta)
            # IMPORTANTE: Converter TODOS os valores para string (Apps Script envia valores numéricos)
            # Fix para "'int' object is not iterable" - Meta SDK não aceita valores numéricos em custom_data
            survey_data_raw = {
                'genero': lead.get('O seu gênero:'),
                'estado': lead.get('Qual estado você mora?'),
                'idade': lead.get('Qual a sua idade?'),
                'ocupacao': lead.get('O que você faz atualmente?'),
                'faixa_salarial': lead.get('Atualmente, qual a sua faixa salarial?'),
                'tem_cartao': lead.get('Você possui cartão de crédito?'),
                'ja_estudou_prog': lead.get('Já estudou programação?'),
                'faculdade': lead.get('Você já fez/faz/pretende fazer faculdade?'),
                'investiu_curso': lead.get('Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?'),
                'interesse_prog': lead.get('O que mais te chama atenção na profissão de Programador?'),
                'quer_ver_evento': lead.get('O que mais você quer ver no evento?'),
                'tem_computador': lead.get('Tem computador/notebook?'),
                'cidade': lead.get('cidade'),
                'cep': lead.get('cep')
            }

            # Converter todos os valores para string
            survey_data = {k: str(v) if v is not None else None for k, v in survey_data_raw.items()}

            # Garantir que lead_score é float (Apps Script pode enviar como número ou string)
            lead_score_value = float(lead['lead_score'])

            lead_capi = {
                'email': email,
                'phone': phone,
                'first_name': first_name,
                'last_name': last_name,
                'lead_score': lead_score_value,  # Garantido como float
                'decil': decil,
                'event_id': capi_data.event_id if capi_data else f"lead_{int(time.time())}_{str(email)[:8]}",
                'fbp': capi_data.fbp if capi_data else None,
                'fbc': capi_data.fbc if capi_data else None,
                'user_agent': capi_data.user_agent if capi_data else None,
                'client_ip': capi_data.client_ip if capi_data else None,
                'event_source_url': capi_data.event_source_url if capi_data else None,
                'event_timestamp': _safe_parse_timestamp(lead.get('data')),
                'survey_data': survey_data
            }

            enriched_leads.append(lead_capi)

        logger.info(f"   {len(enriched_leads)} leads enriquecidos para envio CAPI")

        # Logging de qualidade dos dados
        leads_with_fbp = len([l for l in enriched_leads if l.get('fbp')])
        leads_with_fbc = len([l for l in enriched_leads if l.get('fbc')])
        leads_with_both = len([l for l in enriched_leads if l.get('fbp') and l.get('fbc')])

        logger.info(f"   📊 Qualidade dos dados CAPI:")
        logger.info(f"      - Com FBP: {leads_with_fbp}/{len(enriched_leads)} ({leads_with_fbp/len(enriched_leads)*100:.1f}%)")
        logger.info(f"      - Com FBC: {leads_with_fbc}/{len(enriched_leads)} ({leads_with_fbc/len(enriched_leads)*100:.1f}%)")
        logger.info(f"      - Com AMBOS: {leads_with_both}/{len(enriched_leads)} ({leads_with_both/len(enriched_leads)*100:.1f}%)")

        # Enviar batch (com db session para registrar envios)
        results = send_batch_events(enriched_leads, db=db, capi_config=pipeline._client_config.capi,
                                    business_config=pipeline._client_config.business,
                                    client_id=pipeline._client_config.client_id)

        logger.info(f"✅ Batch CAPI processado: {results['success']}/{results['total']} enviados")

        return {
            "status": "success",
            "total": results['total'],
            "success": results['success'],
            "errors": results['errors'],
            "leads_with_capi_data": len([l for l in enriched_leads if l['fbp'] or l['fbc']]),
            "leads_with_fbp": leads_with_fbp,
            "leads_with_fbc": leads_with_fbc,
            "leads_with_both": leads_with_both,
            "capi_data_quality_pct": round(leads_with_both/len(enriched_leads)*100, 1) if enriched_leads else 0,
            "details": results.get('details', [])
        }

    except Exception as e:
        import traceback
        logger.error(f"❌ Erro no batch CAPI: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Erro no batch CAPI: {str(e)}")

@app.post("/capi/check_sent")
async def check_capi_sent(
    request: CapiCheckSentRequest,
    pipeline: PipelineOptDep,
    db: Session = Depends(get_db)
):
    """
    Verifica quais leads da lista já foram enviados para CAPI

    Args:
        request: Lista de emails para verificar

    Returns:
        {
            "total_checked": int,
            "sent_count": int,
            "not_sent_count": int,
            "sent_emails": List[str]
        }
    """
    try:
        from api.database import get_leads_already_sent_to_capi

        logger.info(f"🔍 Verificando {len(request.emails)} emails nos logs CAPI")

        # Buscar leads já enviados
        sent_emails = get_leads_already_sent_to_capi(db, request.emails, client_id=pipeline._client_config.client_id if pipeline else 'devclub')

        logger.info(f"✅ {len(sent_emails)}/{len(request.emails)} já foram enviados para CAPI")

        return {
            "total_checked": len(request.emails),
            "sent_count": len(sent_emails),
            "not_sent_count": len(request.emails) - len(sent_emails),
            "sent_emails": sent_emails
        }

    except Exception as e:
        logger.error(f"❌ Erro ao verificar logs CAPI: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao verificar logs: {str(e)}")

# ============================================================================
# CAPI: PURCHASE EVENTS
# ============================================================================

class PurchaseSaleItem(BaseModel):
    """Uma venda confirmada a ser enviada como evento Purchase"""
    email: str
    nome: Optional[str] = None
    telefone: Optional[str] = None
    valor_venda: float
    sale_date: str  # "YYYY-MM-DD" ou "YYYY-MM-DD HH:MM:SS"

class SendPurchaseEventsRequest(BaseModel):
    """
    Request para envio de eventos Purchase.

    A lista de sales deve ser extraída dos arquivos TMB/Guru via SalesDataLoader
    antes de chamar este endpoint.
    """
    sales: List[PurchaseSaleItem]
    dry_run: bool = False
    test_event_code: Optional[str] = None


def _lookup_railway_capi_data(emails: List[str]) -> Dict[str, Dict]:
    """
    Busca FBP, FBC, telefone e nome no Railway para uma lista de emails.

    Returns:
        {email_normalizado: {fbp, fbc, phone, nome, event_id}}
    """
    import pg8000.native

    if not emails:
        return {}

    try:
        conn = pg8000.native.Connection(
            host=os.environ.get('RAILWAY_DB_HOST', 'shortline.proxy.rlwy.net'),
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
            timeout=30,
        )

        emails_lower = [e.lower().strip() for e in emails if e]

        rows = conn.run(
            'SELECT email, "nomeCompleto", telefone, fbp, fbc, id::text'
            ' FROM "Lead" WHERE LOWER(email) = ANY(:emails)',
            emails=emails_lower
        )
        conn.close()

        result = {}
        for row in rows:
            email_norm = row[0].lower().strip() if row[0] else None
            if email_norm:
                result[email_norm] = {
                    'nome':     row[1],
                    'phone':    row[2],
                    'fbp':      row[3],
                    'fbc':      row[4],
                    'event_id': row[5],
                }

        return result

    except Exception as e:
        logger.error(f"❌ Erro ao consultar Railway para FBP/FBC: {e}")
        return {}


def _send_single_purchase_event(
    email: str,
    phone: Optional[str],
    nome: Optional[str],
    valor_venda: float,
    purchase_timestamp: int,
    fbp: Optional[str],
    fbc: Optional[str],
    event_id: str,
    test_event_code: Optional[str] = None,
) -> Dict:
    """Envia um evento Purchase para a Meta CAPI."""
    import hashlib
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.serverside.event import Event
    from facebook_business.adobjects.serverside.event_request import EventRequest
    from facebook_business.adobjects.serverside.user_data import UserData
    from facebook_business.adobjects.serverside.custom_data import CustomData
    from facebook_business.adobjects.serverside.action_source import ActionSource

    access_token = os.getenv('META_ACCESS_TOKEN')
    pixel_id = os.getenv('META_PIXEL_ID', '1937807493703815')

    if not access_token:
        return {"status": "error", "message": "META_ACCESS_TOKEN não configurado"}

    def _hash(value) -> Optional[str]:
        if not value:
            return None
        return hashlib.sha256(str(value).lower().strip().encode('utf-8')).hexdigest()

    first_name, last_name = None, None
    if nome:
        parts = str(nome).strip().split(' ', 1)
        first_name = parts[0] if parts else None
        last_name = parts[1] if len(parts) > 1 else None

    try:
        FacebookAdsApi.init(access_token=access_token)

        user_data = UserData(
            emails=[_hash(email)] if email else None,
            phones=[_hash(phone)] if phone else None,
            first_names=[_hash(first_name)] if first_name else None,
            last_names=[_hash(last_name)] if last_name else None,
            fbp=fbp,
            fbc=fbc,
        )

        custom_data = CustomData(value=valor_venda, currency='BRL')

        event = Event(
            event_name='Purchase',
            event_time=purchase_timestamp,
            event_id=f"purchase_{event_id}",
            user_data=user_data,
            custom_data=custom_data,
            action_source=ActionSource.WEBSITE,
        )

        params = {
            'events': [event],
            'pixel_id': pixel_id,
            'access_token': access_token,
        }
        if test_event_code:
            params['test_event_code'] = test_event_code

        response = EventRequest(**params).execute()
        return {"status": "success", "response": str(response)}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/capi/send_purchase_events")
async def send_purchase_events(request: SendPurchaseEventsRequest):
    """
    Envia eventos Purchase para a Meta CAPI para compradores confirmados de um lançamento.

    Fluxo:
    1. Recebe lista de vendas (extraída do TMB/Guru via SalesDataLoader)
    2. Busca FBP/FBC no Railway por email (batch)
    3. Envia evento Purchase com timestamp real da compra e valor real da venda
    4. Retorna resumo: enviados / anomalias (sem FBP/FBC no Railway) / erros

    Uso: chamado manualmente após fechamento do carrinho + período de devoluções.
    Anomalias = compradores não encontrados no Railway — enviados sem FBP/FBC,
    com matching menos preciso na Meta. Quantidade registrada para auditoria.
    """
    if not request.sales:
        raise HTTPException(status_code=400, detail="Nenhuma venda fornecida")

    emails = [s.email.lower().strip() for s in request.sales if s.email]
    railway_data = _lookup_railway_capi_data(emails)

    results = {
        "total":      len(request.sales),
        "enviados":   0,
        "anomalias":  0,
        "erros":      0,
        "dry_run":    request.dry_run,
    }

    for sale in request.sales:
        email_norm = sale.email.lower().strip() if sale.email else None
        lead = railway_data.get(email_norm, {})
        has_cookies = bool(lead.get('fbp') or lead.get('fbc'))

        if not has_cookies:
            results["anomalias"] += 1

        try:
            purchase_ts = int(pd.to_datetime(sale.sale_date).timestamp())
        except Exception:
            logger.warning(f"⚠️ Data inválida para {email_norm}: {sale.sale_date}")
            results["erros"] += 1
            continue

        event_id = lead.get('event_id') or email_norm or str(uuid.uuid4())

        if request.dry_run:
            logger.info(
                f"[DRY RUN] Purchase: {email_norm} | "
                f"R$ {sale.valor_venda:.2f} | "
                f"fbp={'sim' if has_cookies else 'não'}"
            )
            results["enviados"] += 1
            continue

        result = _send_single_purchase_event(
            email=sale.email,
            phone=sale.telefone or lead.get('phone'),
            nome=sale.nome or lead.get('nome'),
            valor_venda=sale.valor_venda,
            purchase_timestamp=purchase_ts,
            fbp=lead.get('fbp'),
            fbc=lead.get('fbc'),
            event_id=event_id,
            test_event_code=request.test_event_code,
        )

        if result["status"] == "success":
            results["enviados"] += 1
        else:
            logger.error(f"❌ Falha ao enviar Purchase para {email_norm}: {result.get('message')}")
            results["erros"] += 1

    logger.info(
        f"📊 Purchase events: {results['enviados']} enviados | "
        f"{results['anomalias']} anomalias (sem FBP/FBC) | "
        f"{results['erros']} erros"
    )

    return results


# =============================================================================
# BIGQUERY SYNC ENDPOINTS
# =============================================================================

from api.bigquery_sync import sync_postgres_to_bigquery, get_bigquery_stats

@app.post("/bigquery/sync")
async def bigquery_sync(limit: int = 1000):
    """
    Sincroniza dados do PostgreSQL para BigQuery

    Args:
        limit: Número máximo de registros a sincronizar (default: 1000 últimos)

    Returns:
        Status e estatísticas do sync
    """
    try:
        result = sync_postgres_to_bigquery(limit=limit)
        return result
    except Exception as e:
        logger.error(f"❌ Erro no sync com BigQuery: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/bigquery/stats")
async def bigquery_stats():
    """
    Estatísticas da tabela leads_capi no BigQuery

    Returns:
        Estatísticas da tabela (total de registros, fbp/fbc, última atualização)
    """
    try:
        result = get_bigquery_stats()
        return result
    except Exception as e:
        logger.error(f"❌ Erro ao buscar stats do BigQuery: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/migrate_capi_sent_at")
async def migrate_capi_sent_at(db: Session = Depends(get_db)):
    """Endpoint temporário para executar migração da coluna capi_sent_at"""
    try:
        from sqlalchemy import text

        logger.info("📝 Adicionando coluna capi_sent_at...")
        db.execute(text("""
            ALTER TABLE leads_capi
            ADD COLUMN IF NOT EXISTS capi_sent_at TIMESTAMP NULL
        """))
        db.commit()
        logger.info("✅ Coluna adicionada!")

        logger.info("📝 Criando índice idx_capi_sent_at...")
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_capi_sent_at
            ON leads_capi(capi_sent_at)
        """))
        db.commit()
        logger.info("✅ Índice criado!")

        logger.info("🔍 Verificando estrutura...")
        result = db.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'leads_capi' AND column_name = 'capi_sent_at'
        """))

        row = result.fetchone()
        if row:
            return {
                "status": "success",
                "message": "Migração executada com sucesso",
                "column": {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2]
                }
            }
        else:
            return {
                "status": "error",
                "message": "Coluna não encontrada após migração"
            }

    except Exception as e:
        logger.error(f"❌ Erro na migração: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro na migração: {str(e)}")


@app.post("/admin/cleanup_duplicates")
async def cleanup_duplicates(ids_to_delete: List[int], db: Session = Depends(get_db)):
    """
    Deleta registros duplicados da página Parabéns

    SEGURANÇA:
    - Requer lista explícita de IDs
    - Executa em transação (rollback automático em caso de erro)
    - Retorna estatísticas da deleção
    """
    try:
        from sqlalchemy import text

        if not ids_to_delete:
            raise HTTPException(status_code=400, detail="Lista de IDs vazia")

        if len(ids_to_delete) > 5000:
            raise HTTPException(status_code=400, detail="Limite de 5000 IDs por execução")

        logger.info(f"🗑️ Iniciando deleção de {len(ids_to_delete)} registros duplicados...")

        # Executar deleção em batches de 100
        batch_size = 100
        total_deleted = 0

        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i:i+batch_size]
            ids_str = ','.join(map(str, batch))

            result = db.execute(text(f"DELETE FROM leads_capi WHERE id IN ({ids_str})"))
            deleted = result.rowcount
            total_deleted += deleted
            logger.info(f"✅ Batch {i//batch_size + 1}: {deleted} registros deletados")

        db.commit()
        logger.info(f"✅ SUCESSO! Total deletado: {total_deleted} registros")

        return {
            "status": "success",
            "total_deleted": total_deleted,
            "expected": len(ids_to_delete),
            "message": f"Deletados {total_deleted} registros duplicados"
        }

    except Exception as e:
        logger.error(f"❌ Erro na deleção: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro na deleção: {str(e)}")


# =============================================================================
# MONITORING HELPERS
# =============================================================================

def fetch_leads_from_sheets(hours: int = 24) -> List[Dict[str, Any]]:
    """
    Busca leads do Google Sheets das últimas N horas.

    Args:
        hours: Número de horas para buscar (padrão: 24)

    Returns:
        Lista de dicts com dados dos leads

    Raises:
        Exception: Se falhar ao buscar dados
    """
    import gspread
    from google.auth import default as gauth_default
    from datetime import timedelta

    try:
        logger.info(f"📊 Buscando leads do Google Sheets (últimas {hours}h)...")

        # Autenticar com Application Default Credentials
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets.readonly',
            'https://www.googleapis.com/auth/drive.readonly'
        ]
        creds, _ = gauth_default(scopes=scopes)
        gc = gspread.authorize(creds)

        # Abrir planilha
        spreadsheet = gc.open_by_url(GOOGLE_SHEETS_URL)
        worksheet = spreadsheet.get_worksheet(0)  # Primeira aba

        # Buscar todos os dados usando get_all_values() para evitar erro com headers duplicados
        valores = worksheet.get_all_values()
        headers = valores[0]
        dados = valores[1:]

        # Converter para lista de dicts
        all_data = [dict(zip(headers, row)) for row in dados]

        # Tentar filtrar por data (últimas N horas)
        try:
            df = pd.DataFrame(all_data)

            # Identificar coluna de data
            date_columns = [col for col in df.columns if any(
                term in col.lower() for term in ['data', 'timestamp', 'hora', 'date', 'time']
            )]

            if date_columns:
                date_col = date_columns[0]
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                # Sheets armazena datas em BRT (naive). Cloud Run roda em UTC.
                # datetime.now() em Cloud Run = UTC, causando janela 3h curta.
                # Usar BRT naive para comparar com datas BRT do Sheets.
                from datetime import timezone as _tz
                _brt = _tz(timedelta(hours=-3))
                cutoff = datetime.now(_tz.utc).astimezone(_brt).replace(tzinfo=None) - timedelta(hours=hours)
                df_filtered = df[df[date_col] >= cutoff]

                if len(df_filtered) > 0:
                    leads = df_filtered.to_dict('records')
                    logger.info(f"✅ {len(leads)} leads encontrados das últimas {hours}h")
                    return leads
                else:
                    logger.warning(f"⚠️ Nenhum lead nas últimas {hours}h, usando últimos 100")
                    leads = all_data[-100:] if len(all_data) > 100 else all_data
                    return leads
            else:
                logger.warning(f"⚠️ Coluna de data não encontrada, usando últimos 100 leads")
                leads = all_data[-100:] if len(all_data) > 100 else all_data
                return leads

        except Exception as e:
            logger.warning(f"⚠️ Erro ao filtrar por data: {e}, usando últimos 100 leads")
            leads = all_data[-100:] if len(all_data) > 100 else all_data
            return leads

    except Exception as e:
        logger.error(f"❌ Erro ao buscar dados do Google Sheets: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao buscar dados do Google Sheets: {str(e)}"
        )

# =============================================================================
# MONITORING ENDPOINTS
# =============================================================================

@app.get("/monitoring/feature-report")
async def feature_report(
    hours: int = 24,
    revision: Optional[str] = None,
):
    """
    [T1-11 Peça B] Agrega os logs do feature_validator das últimas N horas
    e retorna relatório consolidado do monitoramento pré-encoding.

    Consome os logs estruturados [FV_JSON] emitidos por
    `src/core/feature_validator.py` em produção (um log por batch scoreado).

    Args:
        hours:    janela em horas a consultar (default: 24)
        revision: se informado, filtra só essa revisão Cloud Run

    Returns:
        {
          'window': {'hours': N, 'since': iso_ts},
          'total_batches': int,
          'batches_by_severity': {'OK': N, 'INFO': N, 'WARNING': N, 'ERROR': N},
          'issues_by_feature': {feature_name: {'count': N, 'problems': {problem_type: N}, 'latest_details': {...}}},
          'overall_status': 'OK' | 'INFO' | 'WARNING' | 'ERROR',
          'recommended_action': str,
          'sample_error_log': {... snippet do log mais recente com severity=ERROR ...}  # se houver
        }

    Filtros Cloud Logging:
      resource.type=cloud_run_revision AND
      resource.labels.service_name=smart-ads-api AND
      textPayload:"[FV_JSON]"
    """
    import subprocess
    import json as _json
    from datetime import timedelta

    project = os.getenv('PROJECT_ID', 'smart-ads-451319')
    service = 'smart-ads-api'

    # Construir filtro
    filter_parts = [
        'resource.type=cloud_run_revision',
        f'resource.labels.service_name={service}',
        'textPayload:"[FV_JSON]"',
    ]
    if revision:
        filter_parts.append(f'resource.labels.revision_name={revision}')
    filter_str = ' AND '.join(filter_parts)

    freshness = f'{hours}h'

    try:
        result = subprocess.run(
            ['gcloud', 'logging', 'read', filter_str,
             '--project', project,
             '--freshness', freshness,
             '--format=value(textPayload)',
             '--limit', '5000'],
            capture_output=True, text=True, check=True, timeout=60,
        )
        raw_lines = result.stdout.splitlines()
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"gcloud logging read falhou: {e.stderr.strip()[:300]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout ao consultar Cloud Logging (>60s)")

    # Parse dos payloads
    payloads = []
    for line in raw_lines:
        idx = line.find('[FV_JSON] ')
        if idx < 0:
            continue
        try:
            payload = _json.loads(line[idx + len('[FV_JSON] '):])
            if payload.get('event') == 'feature_validator':
                payloads.append(payload)
        except Exception:
            continue

    # Agregação
    batches_by_severity = {'OK': 0, 'INFO': 0, 'WARNING': 0, 'ERROR': 0}
    issues_by_feature: Dict[str, Dict[str, Any]] = {}
    latest_error_log = None
    latest_error_ts = None

    for p in payloads:
        sev = p.get('severity', 'UNKNOWN')
        batches_by_severity[sev] = batches_by_severity.get(sev, 0) + 1

        if sev == 'ERROR':
            ts = p.get('timestamp', '')
            if latest_error_ts is None or ts > latest_error_ts:
                latest_error_ts = ts
                latest_error_log = p

        for issue in p.get('issues', []):
            feat = issue.get('feature', '?')
            prob = issue.get('problem', '?')
            entry = issues_by_feature.setdefault(feat, {
                'count': 0,
                'problems': {},
                'latest_details': None,
                'latest_timestamp': None,
            })
            entry['count'] += 1
            entry['problems'][prob] = entry['problems'].get(prob, 0) + 1
            ts = p.get('timestamp', '')
            if entry['latest_timestamp'] is None or ts > entry['latest_timestamp']:
                entry['latest_timestamp'] = ts
                entry['latest_details'] = issue.get('details')

    # Overall status e ação recomendada
    if batches_by_severity['ERROR'] > 0:
        overall_status = 'ERROR'
        recommended_action = (
            "BLOQUEAR progressão de tráfego. Investigar features com problem in "
            "{missing_column, wrong_dtype, null_rate_high} — o modelo está sendo "
            "scoreado com sinal incompleto. Ver sample_error_log para exemplo concreto."
        )
    elif batches_by_severity['WARNING'] > 0:
        overall_status = 'WARNING'
        recommended_action = (
            "Avaliar novas categorias detectadas (drift em categóricas). Não bloqueia "
            "progressão, mas pode indicar que o modelo está saindo do domínio de treino. "
            "Se frequente, agendar retreino."
        )
    elif batches_by_severity['INFO'] > 0:
        overall_status = 'INFO'
        recommended_action = (
            "Valores numéricos fora do range observado em treino (drift numérico suave). "
            "Progressão liberada. Monitorar tendência para decidir retreino futuro."
        )
    elif batches_by_severity['OK'] > 0:
        overall_status = 'OK'
        recommended_action = "Nenhum problema detectado. Progressão de tráfego liberada do ponto de vista de T1-11."
    else:
        overall_status = 'NO_DATA'
        recommended_action = (
            "Nenhum log [FV_JSON] encontrado na janela. Pipeline pode não estar sendo "
            "exercitado, schema pode não estar carregado na revisão, ou a revisão não "
            "recebeu tráfego. Se revisão é nova, gerar tráfego antes de consultar."
        )

    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=hours)

    return {
        'window': {
            'hours': hours,
            'since': since_utc.isoformat(),
            'until': now_utc.isoformat(),
        },
        'revision_filter': revision,
        'total_batches': sum(batches_by_severity.values()),
        'batches_by_severity': batches_by_severity,
        'issues_by_feature': issues_by_feature,
        'overall_status': overall_status,
        'recommended_action': recommended_action,
        'sample_error_log': latest_error_log,
    }


@app.get("/monitoring/daily-check", response_model=DailyCheckResponse)
async def daily_monitoring_check_auto(
    pipeline: PipelineOptDep,
    hours: int = 24,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """
    Executa check diário de monitoramento com dados do Railway PostgreSQL.

    Delega para /monitoring/daily-check/railway, que é a fonte primária de dados.
    Railway cobre 99.9% dos leads (verificado em 23/02/2026).

    Args:
        hours: Número de horas para buscar (padrão: 24). Ignorado se start_date/end_date forem passados.
        start_date: Data de início no formato YYYY-MM-DD (BRT). Ex: 2026-02-01
        end_date: Data de fim no formato YYYY-MM-DD (BRT). Ex: 2026-02-20

    Returns:
        Alertas consolidados por severidade e categoria
    """
    return await daily_monitoring_check_railway(
        pipeline=pipeline,
        hours=hours,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/monitoring/daily-check/railway", response_model=DailyCheckResponse)
async def daily_monitoring_check_railway(
    pipeline: PipelineOptDep,
    hours: int = 24,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """
    Executa check diário de monitoramento 100% com dados do Railway PostgreSQL.

    Fluxo:
    1. Busca leads scored das últimas N horas (para alertas/drift ML)
    2. Busca stats agregados da janela (total, CAPI, qualidade de dados)
    3. Busca todos os leads scored (para métricas de qualidade por período)
    4. Constrói funnel_metrics e lead_quality_metrics do Railway — sem Sheets/Cloud SQL
    5. Executa orchestrator.run_daily_check() para gerar alertas de drift/qualidade
    6. Substitui funnel_metrics e lead_quality_metrics pelo resultado Railway

    Args:
        hours: Número de horas para buscar (padrão: 24). Ignorado se start_date/end_date forem passados.
        start_date: Data de início no formato YYYY-MM-DD (BRT). Ex: 2026-02-01
        end_date: Data de fim no formato YYYY-MM-DD (BRT). Ex: 2026-02-20
        db: Sessão PostgreSQL Cloud SQL (mantida para assinatura, não usada nas métricas)
    """
    import pg8000.native
    import json as _json
    import yaml
    from src.monitoring.orchestrator import MonitoringOrchestrator
    from api.railway_mapping import railway_lead_to_sheets_row
    from datetime import timezone as _tz, timedelta

    start_time = time.time()

    try:
        # ------------------------------------------------------------------
        # 0. Calcular janela de tempo (UTC) — start_date/end_date têm prioridade
        # ------------------------------------------------------------------
        brt = _tz(timedelta(hours=-3))
        now_utc = datetime.now(_tz.utc)

        if start_date and end_date:
            try:
                from datetime import date as _date
                _start = datetime.strptime(start_date, '%Y-%m-%d').replace(
                    hour=0, minute=0, second=0,
                    tzinfo=brt
                ).astimezone(_tz.utc)
                _end = datetime.strptime(end_date, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59,
                    tzinfo=brt
                ).astimezone(_tz.utc)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Formato de data inválido. Use YYYY-MM-DD. Ex: start_date=2026-02-01&end_date=2026-02-20"
                )
            window_start = _start
            window_end   = _end
            window_label = f"{start_date} → {end_date}"
        else:
            window_start = now_utc - timedelta(hours=hours)
            window_end   = now_utc
            window_label = f"últimas {hours}h"

        # ------------------------------------------------------------------
        # 1. Conectar ao Railway e buscar todos os dados necessários
        # ------------------------------------------------------------------
        railway_conn = pg8000.native.Connection(
            host=os.environ['RAILWAY_DB_HOST'],
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
            timeout=30,
        )

        # 1a. Leads com score na janela (para alertas de drift ML)
        scored_rows = railway_conn.run(
            'SELECT id, data, "nomeCompleto", email, telefone, pesquisa, '
            'source, medium, campaign, content, term, '
            '"remoteIp", "userAgent", fbc, fbp, "pageUrl", '
            '"leadScore", decil '
            'FROM "Lead" '
            'WHERE "leadScore" IS NOT NULL '
            'AND "createdAt" >= :start AND "createdAt" <= :end '
            'ORDER BY "createdAt" DESC',
            start=window_start,
            end=window_end
        )

        # 1b. Stats agregados da janela (total, CAPI, phone)
        stats_row = railway_conn.run(
            'SELECT '
            '  COUNT(*) AS total, '
            '  COUNT(*) FILTER (WHERE "leadScore" IS NOT NULL) AS scored, '
            '  COUNT(*) FILTER (WHERE "capiSentAt" IS NOT NULL AND "capiStatus" NOT IN (\'blocked\', \'skipped\')) AS capi_sent, '
            '  COUNT(*) FILTER (WHERE "capiStatus" = \'success\') AS capi_success, '
            '  COUNT(*) FILTER (WHERE "capiStatus" = \'error\') AS capi_error, '
            '  COUNT(*) FILTER (WHERE telefone IS NOT NULL AND telefone <> \'\') AS with_phone '
            'FROM "Lead" '
            'WHERE "createdAt" >= :start AND "createdAt" <= :end',
            start=window_start,
            end=window_end
        )

        # FBP/FBC: join Lead (janela) x leads_capi (fonte dos cookies) por email
        capi_fbp_row = railway_conn.run(
            'SELECT '
            '  COUNT(DISTINCT CASE WHEN lc.fbp IS NOT NULL AND lc.fbp <> \'\' THEN l.email END) AS with_fbp, '
            '  COUNT(DISTINCT CASE WHEN lc.fbc IS NOT NULL AND lc.fbc <> \'\' THEN l.email END) AS with_fbc '
            'FROM "Lead" l '
            'LEFT JOIN leads_capi lc ON LOWER(l.email) = LOWER(lc.email) '
            'WHERE l."createdAt" >= :start AND l."createdAt" <= :end',
            start=window_start,
            end=window_end
        )

        # 1c. Todos os leads com score (para métricas de qualidade por período)
        quality_rows = railway_conn.run(
            'SELECT "leadScore"::float, decil::int, "createdAt" '
            'FROM "Lead" '
            'WHERE "leadScore" IS NOT NULL AND decil IS NOT NULL '
            'ORDER BY "createdAt" DESC'
        )

        # 1d. Leads do lançamento atual — exclusivo para revenue_forecast
        # Se start_date/end_date foram passados, usa essa janela; senão, desde a última terça-feira BRT
        now_brt = now_utc.astimezone(brt)
        if start_date and end_date:
            launch_window_start     = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=brt)
            launch_window_start_utc = window_start
            launch_window_end_utc   = window_end
            launch_window_label     = f"{start_date} → {end_date}"
        else:
            days_since_tuesday = (now_brt.weekday() - 1) % 7  # terça = weekday 1
            launch_window_start = now_brt.replace(hour=0, minute=0, second=0, microsecond=0) \
                - timedelta(days=days_since_tuesday)
            launch_window_start_utc = launch_window_start.astimezone(_tz.utc)
            launch_window_end_utc   = now_utc
            launch_window_label     = launch_window_start.strftime('%d/%m/%Y')

        forecast_decil_rows = railway_conn.run(
            'SELECT decil '
            'FROM "Lead" '
            'WHERE "leadScore" IS NOT NULL AND decil IS NOT NULL '
            'AND "createdAt" >= :start AND "createdAt" <= :end',
            start=launch_window_start_utc,
            end=launch_window_end_utc,
        )

        # Distribuição de decis na janela do lançamento — usada pelo expected_conversion
        forecast_decil_dist: Dict[str, int] = {}
        for (decil_val,) in forecast_decil_rows:
            if decil_val is not None:
                key = f"D{int(decil_val):02d}"
                forecast_decil_dist[key] = forecast_decil_dist.get(key, 0) + 1

        # 1e. Survey funnel metrics por janela histórica (DB side)
        _sfm_db: Dict[str, Dict] = {}
        try:
            _sfm_windows = {
                'historico':     datetime(2020, 1, 1, tzinfo=_tz.utc),
                'ultimo_mes':    now_utc - timedelta(days=30),
                'ultima_semana': now_utc - timedelta(days=7),
                'ultimas_24h':   now_utc - timedelta(hours=24),
            }
            for _lbl, _cut in _sfm_windows.items():
                _sfm_r = railway_conn.run(
                    'SELECT '
                    '  COUNT(*) AS db_leads, '
                    '  COUNT(*) FILTER (WHERE "capiSentAt" IS NOT NULL '
                    '    AND "capiStatus" NOT IN (\'blocked\', \'skipped\')) AS capi_sent '
                    'FROM "Lead" '
                    'WHERE "createdAt" >= :start AND "createdAt" <= :end',
                    start=_cut, end=now_utc
                )
                _r = _sfm_r[0] if _sfm_r else (0, 0)
                _db_l, _capi_s = (_r[0] or 0), (_r[1] or 0)
                _sfm_db[_lbl] = {
                    'db_leads': _db_l,
                    'capi_sent': _capi_s,
                    'capi_rate': round(_capi_s / _db_l * 100, 1) if _db_l > 0 else 0,
                }
            # periodo_query usa a janela da query
            _sfm_pq = railway_conn.run(
                'SELECT '
                '  COUNT(*) AS db_leads, '
                '  COUNT(*) FILTER (WHERE "capiSentAt" IS NOT NULL '
                '    AND "capiStatus" NOT IN (\'blocked\', \'skipped\')) AS capi_sent '
                'FROM "Lead" '
                'WHERE "createdAt" >= :start AND "createdAt" <= :end',
                start=window_start, end=window_end
            )
            _r_pq = _sfm_pq[0] if _sfm_pq else (0, 0)
            _db_pq, _capi_pq = (_r_pq[0] or 0), (_r_pq[1] or 0)
            _sfm_db['periodo_query'] = {
                'db_leads': _db_pq,
                'capi_sent': _capi_pq,
                'capi_rate': round(_capi_pq / _db_pq * 100, 1) if _db_pq > 0 else 0,
            }
        except Exception as _sfm_e:
            logger.warning(f"⚠️ survey_funnel DB queries: {_sfm_e}")

        railway_conn.close()

        # ------------------------------------------------------------------
        # 2. Processar scored_rows → leads_data (para o orquestrador)
        # ------------------------------------------------------------------
        if not scored_rows:
            logger.info(f"⚠️ Railway: nenhum lead com score no período {window_label}")
            return DailyCheckResponse(
                total_alerts=0,
                alerts_by_severity={"HIGH": 0, "MEDIUM": 0, "LOW": 0},
                alerts_by_category={},
                alerts=[],
                critical_summary=f"Nenhum lead Railway no período {window_label}.",
                timestamp=datetime.now().isoformat()
            )

        logger.info(f"🔍 Railway monitoring: {len(scored_rows)} leads com score — {window_label}")

        col_names = [
            'id', 'data', 'nomeCompleto', 'email', 'telefone', 'pesquisa',
            'source', 'medium', 'campaign', 'content', 'term',
            'remoteIp', 'userAgent', 'fbc', 'fbp', 'pageUrl',
            'leadScore', 'decil',
        ]

        leads_data = []
        for row in scored_rows:
            lead = dict(zip(col_names, row))

            if isinstance(lead.get('pesquisa'), str):
                try:
                    lead['pesquisa'] = _json.loads(lead['pesquisa'])
                except Exception:
                    lead['pesquisa'] = {}
            elif lead.get('pesquisa') is None:
                lead['pesquisa'] = {}

            try:
                sheets_row = railway_lead_to_sheets_row(lead, client_config=pipeline._client_config if pipeline else None)
                sheets_row['lead_score'] = float(lead['leadScore']) if lead.get('leadScore') else None
                sheets_row['decil']      = f"D{int(lead['decil']):02d}" if lead.get('decil') else None
                leads_data.append(sheets_row)
            except Exception as e:
                logger.warning(f"⚠️ Erro ao mapear lead {lead.get('email')}: {e}")

        logger.info(f"✅ {len(leads_data)} leads convertidos")

        # ------------------------------------------------------------------
        # 3. Construir funnel_metrics 100% Railway
        # ------------------------------------------------------------------
        stats = dict(zip(
            ['total', 'scored', 'capi_sent', 'capi_success', 'capi_error', 'with_phone'],
            stats_row[0]
        ))
        total = stats['total'] or 0
        capi_sent = stats['capi_sent'] or 0
        capi_success = stats['capi_success'] or 0
        capi_error = stats['capi_error'] or 0
        with_phone = stats['with_phone'] or 0

        fbp_stats = dict(zip(['with_fbp', 'with_fbc'], capi_fbp_row[0]))
        with_fbp = fbp_stats['with_fbp'] or 0
        with_fbc = fbp_stats['with_fbc'] or 0

        railway_funnel_metrics = {
            'window': {
                'start_utc': window_start.isoformat(),
                'end_utc': window_end.isoformat(),
                'start_brt': window_start.astimezone(brt).strftime('%d/%m/%Y %H:%M'),
                'end_brt': window_end.astimezone(brt).strftime('%d/%m/%Y %H:%M'),
            },
            'capture': {
                'total_database': total,
                'total_scored': stats['scored'] or 0,
            },
            'data_quality': {
                'total_leads': total,
                'fbp_present': with_fbp,
                'fbp_percentage': (with_fbp / total * 100) if total > 0 else 0,
                'fbc_present': with_fbc,
                'fbc_percentage': (with_fbc / total * 100) if total > 0 else 0,
                'phone_present': with_phone,
                'phone_percentage': (with_phone / total * 100) if total > 0 else 0,
            },
            'scoring': {
                'total_scored': len(leads_data),
                'decil_distribution': {},
                'avg_score': None,
            },
            'capi_sent': {
                'leads_sent': capi_sent,
                'send_rate': (capi_sent / total * 100) if total > 0 else 0,
                'estimated_events': int(capi_sent * 1.3),
            },
            'meta_response': {
                'leads_with_response': capi_sent,
                'success_count': capi_success,
                'error_count': capi_error,
                'partial_count': 0,
                'acceptance_rate': (capi_success / capi_sent * 100) if capi_sent > 0 else 0,
                # Railway não armazena eventos individuais recebidos/rejeitados pela Meta
                'events_received': None,
                'events_rejected': None,
            },
            'conversion': {
                # No Railway pesquisa e inscrição chegam juntos — 100% dos leads têm pesquisa
                'total_with_survey': stats['scored'] or 0,
                'survey_rate': 100.0 if (stats['scored'] or 0) > 0 else 0,
            },
        }

        # Distribuição de decis e score médio dos leads da janela
        if leads_data:
            decil_dist: dict = {}
            scores = []
            for ld in leads_data:
                d = ld.get('decil')
                if d:
                    decil_dist[d] = decil_dist.get(d, 0) + 1
                s = ld.get('lead_score')
                if s is not None:
                    scores.append(s)
            railway_funnel_metrics['scoring']['decil_distribution'] = decil_dist
            railway_funnel_metrics['scoring']['avg_score'] = (
                sum(scores) / len(scores) if scores else None
            )

        # ------------------------------------------------------------------
        # 4. Construir lead_quality_metrics 100% Railway
        # ------------------------------------------------------------------
        def _calc_quality(rows_subset):
            if not rows_subset:
                return {'score': 0, 'd9': 0, 'd10': 0, 'count': 0}
            scores_q = [r[0] for r in rows_subset if r[0] is not None]
            decils_q  = [r[1] for r in rows_subset if r[1] is not None]
            n = len(rows_subset)
            return {
                'score': sum(scores_q) / len(scores_q) if scores_q else 0,
                'd9':  (sum(1 for d in decils_q if d == 9)  / n * 100) if n > 0 else 0,
                'd10': (sum(1 for d in decils_q if d == 10) / n * 100) if n > 0 else 0,
                'count': n,
            }

        # Cortes em UTC — Railway armazena createdAt em UTC
        now_utc_q = datetime.now(_tz.utc)
        cut_24h   = now_utc_q - timedelta(hours=24)
        cut_week  = now_utc_q - timedelta(days=7)
        cut_month = now_utc_q - timedelta(days=30)

        def _after(rows_q, cutoff):
            # quality_rows: (leadScore, decil, createdAt)
            # Garante comparação UTC vs UTC
            result_q = []
            for r in rows_q:
                created = r[2]
                if created is None:
                    continue
                if hasattr(created, 'tzinfo') and created.tzinfo is None:
                    created = created.replace(tzinfo=_tz.utc)  # assume UTC se naive
                if created >= cutoff:
                    result_q.append(r)
            return result_q

        railway_lead_quality = {
            'historico':     _calc_quality(quality_rows),
            'ultimo_mes':    _calc_quality(_after(quality_rows, cut_month)),
            'ultima_semana': _calc_quality(_after(quality_rows, cut_week)),
            'ultimas_24h':   _calc_quality(_after(quality_rows, cut_24h)),
        }

        # ------------------------------------------------------------------
        # 5. Executar orquestrador (apenas para alertas de drift/qualidade ML)
        # ------------------------------------------------------------------
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'configs/active_models/devclub.yaml'
        )
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            active_model = config['active_model']
            if 'mlflow_run_id' in active_model:
                model_path = os.path.join('mlruns', '1', active_model['mlflow_run_id'], 'artifacts')
            else:
                model_path = active_model['model_path']

        if not os.path.isabs(model_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, model_path)

        orchestrator = MonitoringOrchestrator(model_path=model_path, db=None)
        result = orchestrator.run_daily_check(leads_data)

        # Substituir funnel_metrics e lead_quality_metrics pelos dados Railway
        result['funnel_metrics'] = railway_funnel_metrics
        result['lead_quality_metrics'] = railway_lead_quality

        # Buscar métricas Meta Ads (campanhas CAP, hoje) — falha silenciosa
        meta_metrics = None
        total_meta_leads_forecast = 0   # leads Meta na janela do lançamento — usado no revenue_forecast
        try:
            from api.meta_integration import MetaAdsIntegration
            from api.meta_config import META_CONFIG
            _token = os.getenv('META_ACCESS_TOKEN')
            _account = os.getenv('META_ACCOUNT_ID', META_CONFIG.get('account_id', 'act_188005769808959'))
            if _token:
                _today      = datetime.now(_tz(timedelta(hours=-3))).strftime('%Y-%m-%d')
                _launch_str = launch_window_start.strftime('%Y-%m-%d')
                _meta = MetaAdsIntegration(access_token=_token)

                # --- métricas do dia (spend/clicks) ---
                _rows_hoje = _meta.get_insights(
                    account_id=_account,
                    level='campaign',
                    fields=['campaign_name', 'spend', 'clicks'],
                    since_date=_today,
                    until_date=_today,
                    filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
                )
                _spend  = sum(float(r.get('spend', 0) or 0) for r in _rows_hoje)
                _clicks = sum(int(r.get('clicks', 0) or 0) for r in _rows_hoje)
                _midnight_brt = datetime.now(brt).replace(hour=0, minute=0, second=0, microsecond=0)
                _midnight_utc = _midnight_brt.astimezone(_tz.utc)
                _leads_hoje = len(_after(quality_rows, _midnight_utc))
                meta_metrics = {
                    'date':             _today,
                    'spend':            _spend,
                    'clicks':           _clicks,
                    'cpl':              (_spend / _leads_hoje) if _leads_hoje > 0 else None,
                    'taxa_clique_lead': (_leads_hoje / _clicks * 100) if _clicks > 0 else None,
                }
                logger.info(f"📊 Meta Ads CAP: spend=R${_spend:.2f}, clicks={_clicks}, leads={_leads_hoje}")

                # --- total de leads Meta desde o início da janela de lançamento ---
                # Usado pelo revenue_forecast (flat-rate) como denominador real da população.
                # Inclui leads que não responderam à pesquisa e não chegam ao DB.
                _rows_launch = _meta.get_insights(
                    account_id=_account,
                    level='campaign',
                    fields=['campaign_name', 'actions'],
                    since_date=_launch_str,
                    until_date=_today,
                    filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
                )
                for _r in _rows_launch:
                    for _a in (_r.get('actions') or []):
                        if _a.get('action_type') == 'offsite_conversion.fb_pixel_lead':
                            total_meta_leads_forecast += int(_a.get('value', 0) or 0)
                logger.info(f"📊 Meta leads janela lançamento ({_launch_str}–{_today}): {total_meta_leads_forecast}")

                # --- métricas Meta por janela histórica (para survey_funnel_metrics e traffic_metrics) ---
                _brt_now = datetime.now(_tz(timedelta(hours=-3)))
                _meta_hist_windows = {
                    'ultimo_mes':    (_brt_now - timedelta(days=30)).strftime('%Y-%m-%d'),
                    'ultima_semana': (_brt_now - timedelta(days=7)).strftime('%Y-%m-%d'),
                    'ultimas_24h':   (_brt_now - timedelta(hours=24)).strftime('%Y-%m-%d'),
                    'periodo_query': _launch_str,
                }
                _meta_hist_end = {
                    'ultimo_mes':    _today,
                    'ultima_semana': _today,
                    'ultimas_24h':   _today,
                    'periodo_query': (_brt_now if not end_date else
                                      datetime.strptime(end_date, '%Y-%m-%d').replace(
                                          tzinfo=_tz(timedelta(hours=-3))
                                      )).strftime('%Y-%m-%d'),
                }
                meta_window_data: Dict[str, Any] = {}

                def _fetch_meta_window(_wlbl, _wsince, _wuntil):
                    _wrows = _meta.get_insights(
                        account_id=_account,
                        level='campaign',
                        fields=['campaign_name', 'spend', 'clicks', 'actions'],
                        since_date=_wsince,
                        until_date=_wuntil,
                        filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
                    )
                    _w_spend  = sum(float(r.get('spend',  0) or 0) for r in _wrows)
                    _w_clicks = sum(int(r.get('clicks', 0) or 0) for r in _wrows)
                    _w_leads  = 0
                    for _wr in _wrows:
                        for _wa in (_wr.get('actions') or []):
                            if _wa.get('action_type') == 'offsite_conversion.fb_pixel_lead':
                                _w_leads += int(_wa.get('value', 0) or 0)
                    return {
                        'meta_leads': _w_leads,
                        'clicks':     _w_clicks,
                        'spend':      round(_w_spend, 2),
                        'cpl':        round(_w_spend / _w_leads, 2) if _w_leads > 0 else None,
                        'ctr_lead':   round(_w_leads / _w_clicks * 100, 1) if _w_clicks > 0 else None,
                    }

                import concurrent.futures as _cf
                _meta_futures = {}
                with _cf.ThreadPoolExecutor(max_workers=4) as _executor:
                    for _wlbl, _wsince in _meta_hist_windows.items():
                        _meta_futures[_wlbl] = _executor.submit(
                            _fetch_meta_window, _wlbl, _wsince, _meta_hist_end[_wlbl]
                        )
                for _wlbl, _fut in _meta_futures.items():
                    try:
                        meta_window_data[_wlbl] = _fut.result(timeout=12)
                    except Exception as _we:
                        logger.warning(f"⚠️ Meta window {_wlbl}: {_we}")
                        meta_window_data[_wlbl] = None

        except Exception as _e:
            logger.warning(f"⚠️ Meta Ads metrics indisponível: {_e}")

        # Regenerar critical_summary com dados Railway (lead_quality_metrics corretos)
        from src.monitoring.models import Alert as AlertModel
        alerts_objs = [AlertModel.from_dict(a) for a in result['alerts']]
        result['critical_summary'] = orchestrator._generate_critical_summary(
            alerts_objs, railway_funnel_metrics, railway_lead_quality, meta_metrics
        )

        # Gerar previsão de faturamento (falha silenciosa — não deve bloquear monitoring)
        # Metodologia flat-rate: buyers = total_leads_meta × (conv_rastr_mediana / tracking_rate)
        # total_leads_meta vem da Meta Ads API (janela desde terça BRT) — inclui não-respondentes.
        revenue_forecast = None
        try:
            revenue_forecast = orchestrator._generate_revenue_forecast(
                total_meta_leads=total_meta_leads_forecast,
                funnel_metrics=railway_funnel_metrics,
                lead_quality_metrics=railway_lead_quality,
                decil_distribution=forecast_decil_dist or None,
            ) or None

            if revenue_forecast:
                revenue_forecast['inputs']['launch_window_start_brt'] = launch_window_label
        except Exception as _fe:
            logger.warning(f"⚠️ revenue_forecast indisponível: {_fe}")

        # ------------------------------------------------------------------
        # Build survey_funnel_metrics e traffic_metrics
        # ------------------------------------------------------------------
        _meta_wd = locals().get('meta_window_data', {})

        survey_funnel_metrics: Dict[str, Any] = {}
        for _lbl, _sfm in _sfm_db.items():
            _mw = _meta_wd.get(_lbl) if _meta_wd else None
            _meta_leads = _mw['meta_leads'] if _mw else None
            _db_leads   = _sfm['db_leads']
            _rr = (round(_db_leads / _meta_leads * 100, 1)
                   if (_meta_leads and _meta_leads > 0) else None)
            survey_funnel_metrics[_lbl] = {
                'db_leads':      _db_leads,
                'capi_sent':     _sfm['capi_sent'],
                'capi_rate':     _sfm['capi_rate'],
                'meta_leads':    _meta_leads,
                'response_rate': _rr,
            }

        traffic_metrics: Optional[Dict[str, Any]] = (
            {k: v for k, v in _meta_wd.items() if v is not None}
            if _meta_wd else None
        ) or None

        processing_time = time.time() - start_time
        logger.info(f"✅ Railway monitoring concluído em {processing_time:.2f}s — "
                    f"{result['total_alerts']} alertas")

        return DailyCheckResponse(
            total_alerts=result['total_alerts'],
            alerts_by_severity=result['alerts_by_severity'],
            alerts_by_category=result['alerts_by_category'],
            alerts=result['alerts'],
            critical_summary=result.get('critical_summary', ''),
            timestamp=datetime.now().isoformat(),
            funnel_metrics=result.get('funnel_metrics'),
            lead_quality_metrics=result.get('lead_quality_metrics'),
            revenue_forecast=revenue_forecast if revenue_forecast else None,
            survey_funnel_metrics=survey_funnel_metrics or None,
            traffic_metrics=traffic_metrics,
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Modelo não encontrado: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Erro no Railway monitoring: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erro no Railway monitoring: {str(e)}")


@app.post("/monitoring/daily-check", response_model=DailyCheckResponse)
async def daily_monitoring_check(
    request: DailyCheckRequest,
    db: Session = Depends(get_db)
):
    """
    Executa check diário de monitoramento consolidado.

    Verifica:
    - Data Quality: category drift, distribution drift, missing rate, score distribution
    - Operational: 6h sem leads, 6h sem CAPI
    - CAPI Quality: missing rate fbp/fbc

    Args:
        request: Dados do Sheets (últimas 24h)
        db: Sessão PostgreSQL (injetada automaticamente)

    Returns:
        Alertas consolidados por severidade e categoria
    """
    from src.monitoring.orchestrator import MonitoringOrchestrator
    import yaml

    start_time = time.time()
    logger.info(f"🔍 Executando check diário de monitoramento ({len(request.leads)} leads)")

    try:
        # Obter model_path do modelo ativo
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'configs/active_models/devclub.yaml'
        )

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            active_model = config['active_model']
            if 'mlflow_run_id' in active_model:
                model_path = os.path.join('mlruns', '1', active_model['mlflow_run_id'], 'artifacts')
            else:
                model_path = active_model['model_path']

        # Garantir path absoluto
        if not os.path.isabs(model_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, model_path)

        logger.info(f"📂 Usando modelo: {model_path}")

        # Inicializar orquestrador
        orchestrator = MonitoringOrchestrator(model_path=model_path, db=db)

        # Executar checks
        result = orchestrator.run_daily_check(request.leads)

        processing_time = time.time() - start_time

        logger.info(f"✅ Check concluído em {processing_time:.2f}s")
        logger.info(f"📊 Alertas: {result['total_alerts']} total "
                   f"(HIGH: {result['alerts_by_severity']['HIGH']}, "
                   f"MEDIUM: {result['alerts_by_severity']['MEDIUM']}, "
                   f"LOW: {result['alerts_by_severity']['LOW']})")

        # Logar alertas detalhados
        if result['total_alerts'] > 0:
            logger.info(f"\n🚨 ALERTAS DETECTADOS ({result['total_alerts']}):\n")

            # Logar TODOS os alertas (sem limite)
            for i, alert in enumerate(result['alerts'], 1):
                logger.info(f"{i}. [{alert['severity']}] {alert['type']}")
                logger.info(f"   {alert['message']}")
                if alert.get('metric_value'):
                    threshold_msg = f" (threshold: {alert['threshold']})" if alert.get('threshold') else ""
                    logger.info(f"   Valor: {alert['metric_value']}{threshold_msg}")
                logger.info("")  # Linha em branco
        else:
            logger.info("✅ Nenhum alerta detectado - sistema operando normalmente")

        return DailyCheckResponse(
            total_alerts=result['total_alerts'],
            alerts_by_severity=result['alerts_by_severity'],
            alerts_by_category=result['alerts_by_category'],
            alerts=result['alerts'],
            critical_summary=result.get('critical_summary', ''),
            timestamp=datetime.now().isoformat(),
            funnel_metrics=result.get('funnel_metrics'),
            lead_quality_metrics=result.get('lead_quality_metrics'),
        )

    except FileNotFoundError as e:
        logger.error(f"❌ Arquivo não encontrado: {e}")
        raise HTTPException(status_code=500, detail=f"Modelo não encontrado: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Erro no check de monitoramento: {str(e)}")
        logger.error(f"Traceback: {e.__class__.__name__}")
        raise HTTPException(status_code=500, detail=f"Erro no monitoramento: {str(e)}")


# =============================================================================
# VALIDAÇÃO SEMANAL
# =============================================================================

@app.get("/validation/test")
async def test_validation_dependencies():
    """
    Testa rapidamente se todas as dependências para validação estão OK.
    Retorna em segundos, não minutos.
    """
    try:
        errors = []
        warnings = []

        # 1. Testar imports críticos
        try:
            from src.validation.period_calculator import PeriodCalculator
            from src.validation.slack_notifier import ValidationSlackNotifier
            import matplotlib.pyplot as plt
            import seaborn as sns
            from tabulate import tabulate
            import openpyxl
            import xlsxwriter
        except ImportError as e:
            errors.append(f"Import failed: {str(e)}")

        # 2. Testar paths críticos
        from pathlib import Path
        script_path = Path(__file__).parent.parent / 'src' / 'validation' / 'validate_ml_performance.py'
        if not script_path.exists():
            errors.append(f"Script not found: {script_path}")

        vendas_dir = Path(__file__).parent.parent / 'vendas'
        if not vendas_dir.exists():
            warnings.append(f"Vendas dir not found: {vendas_dir}")

        # 3. Testar env vars
        meta_source = os.getenv('META_DATA_SOURCE', 'local')
        bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET', 'bring-data-validation-reports')

        # 4. Testar Cloud Storage
        try:
            from google.cloud import storage
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)
            if not bucket.exists():
                warnings.append(f"Bucket doesn't exist: {bucket_name}")
        except Exception as e:
            warnings.append(f"Cloud Storage test failed: {str(e)}")

        # 5. Testar cálculo de datas
        from datetime import datetime, timedelta
        today = datetime.now()
        test_monday = today - timedelta(days=today.weekday() + 28)

        return {
            "status": "error" if errors else "ok",
            "errors": errors,
            "warnings": warnings,
            "config": {
                "meta_data_source": meta_source,
                "bucket": bucket_name,
                "script_exists": script_path.exists(),
                "test_date_calc": test_monday.strftime('%Y-%m-%d')
            },
            "dependencies_ok": len(errors) == 0
        }

    except Exception as e:
        return {
            "status": "error",
            "errors": [str(e)],
            "dependencies_ok": False
        }


@app.post("/validation/weekly")
async def execute_weekly_validation(db: Session = Depends(get_db)):
    """
    Executa validação semanal do modelo ML.

    - Calcula período automaticamente (semana anterior)
    - Executa validate_ml_performance.py com flags apropriadas
    - Faz upload do Excel para Cloud Storage
    - Envia sumário para Slack

    Chamado automaticamente por Cloud Scheduler toda segunda-feira às 10h.
    """
    import subprocess
    from pathlib import Path
    from datetime import timedelta
    from google.cloud import storage
    from src.validation.period_calculator import PeriodCalculator
    from src.validation.slack_notifier import ValidationSlackNotifier

    try:
        from datetime import datetime
        today = datetime.now()

        logger.info("🚀 Iniciando validação semanal...")

        # TEMPORÁRIO: Testando com Campanha Atípica 1 (16/12/2025 - 25/01/2026)
        # TODO: Voltar para cálculo automático depois do teste
        start_date = '2025-12-16'
        end_date = '2026-01-12'
        sales_start = '2026-01-19'
        sales_end = '2026-01-25'

        logger.info(f"📅 TESTE Campanha Atípica 1: captação={start_date} a {end_date}, vendas={sales_start} a {sales_end}")

        # 2. Executar script de validação
        script_path = Path(__file__).parent.parent / 'src' / 'validation' / 'validate_ml_performance.py'

        cmd = [
            'python',
            str(script_path),
            '--start-date', start_date,
            '--end-date', end_date,
            '--sales-start-date', sales_start,
            '--sales-end-date', sales_end
        ]

        # Configurar environment variables
        env = os.environ.copy()
        env['GURU_DATA_SOURCE'] = 'api'
        env['META_DATA_SOURCE'] = os.getenv('META_DATA_SOURCE', 'local')  # local para testes, api para produção
        env['INTERNAL_API_URL'] = 'http://localhost:8080'  # Script usa localhost para acessar a própria API

        logger.info(f"🔧 Executando validação (GURU=api, META={env['META_DATA_SOURCE']})...")
        logger.info(f"🔧 Comando: {' '.join(cmd)}")

        # CRÍTICO: NÃO usar capture_output=True para permitir streaming de logs em tempo real
        # Isso faz os logs do script aparecerem diretamente no Cloud Run
        result = subprocess.run(
            cmd,
            capture_output=False,  # Permite streaming de logs!
            text=True,
            cwd=Path(__file__).parent.parent,
            env=env,
            timeout=600  # 10 minutos timeout
        )

        # Nota: Como não estamos capturando output, não temos result.stdout/stderr
        # Mas os logs aparecem em tempo real no Cloud Run, facilitando debug

        if result.returncode != 0:
            error_msg = f"Script falhou (exit code {result.returncode})"
            logger.error(f"❌ {error_msg}")

            # Notificar erro no Slack
            notifier = ValidationSlackNotifier()
            notifier.send_error_notification(
                error_message=error_msg,
                period={'start': start_date, 'sales_start': sales_start, 'sales_end': sales_end}
            )

            raise HTTPException(status_code=500, detail=error_msg)

        logger.info("✅ Script de validação executado com sucesso")

        # 3. Encontrar Excel gerado
        results_dir = Path(__file__).parent.parent / 'files' / 'validation' / 'resultados'
        excel_files = sorted(results_dir.glob('validation_report_*.xlsx'), key=lambda p: p.stat().st_mtime)

        if not excel_files:
            raise HTTPException(status_code=500, detail="Excel não foi gerado")

        latest_excel = excel_files[-1]
        logger.info(f"📊 Excel encontrado: {latest_excel.name}")

        # 4. Upload para Cloud Storage
        bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET', 'bring-data-validation-reports')

        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)

            # Nome do blob: validation/2026/01/validacao_20260127_103045.xlsx
            blob_name = f"validation/{today.year}/{today.month:02d}/{latest_excel.name}"
            blob = bucket.blob(blob_name)

            blob.upload_from_filename(str(latest_excel))
            blob.make_public()

            excel_url = blob.public_url
            logger.info(f"☁️ Upload concluído: {excel_url}")

        except Exception as storage_error:
            logger.warning(f"⚠️ Erro no upload Cloud Storage: {storage_error}")
            excel_url = None

        # 5. Enviar notificação Slack (sem métricas detalhadas, apenas sucesso)
        # Nota: Como não estamos capturando stdout, não temos acesso às métricas parseadas
        # Mas o Excel tem todas as informações necessárias
        notifier = ValidationSlackNotifier()
        notifier.send_validation_summary(
            metrics={"status": "success", "message": "Validação concluída - detalhes no Excel"},
            excel_url=excel_url,
            period={
                'start': start_date,
                'sales_start': sales_start,
                'sales_end': sales_end
            }
        )

        logger.info("✅ Validação semanal concluída com sucesso!")

        return {
            "status": "success",
            "message": "Validação semanal executada com sucesso",
            "period": {
                "captacao": start_date,
                "vendas": f"{sales_start} a {sales_end}"
            },
            "excel_url": excel_url
        }

    except subprocess.TimeoutExpired:
        error_msg = "Validação excedeu timeout de 10 minutos"
        logger.error(f"❌ {error_msg}")

        notifier = ValidationSlackNotifier()
        notifier.send_error_notification(error_msg)

        raise HTTPException(status_code=408, detail=error_msg)

    except Exception as e:
        logger.error(f"❌ Erro na validação semanal: {str(e)}")

        notifier = ValidationSlackNotifier()
        notifier.send_error_notification(str(e))

        raise HTTPException(status_code=500, detail=str(e))


def _parse_validation_metrics(stdout: str) -> dict:
    """
    Extrai métricas do output do script de validação.

    Procura por linhas como:
    - "AUC Produção: 0.8234 (Test Set: 0.8156, Δ: +0.0078)"
    - "Conversões: 177"
    - "ROAS COM ML: 2.04x"
    """
    import re

    metrics = {
        'auc_production': 0.0,
        'auc_test_set': 0.0,
        'conversoes': 0,
        'roas': 0.0,
        'leads_analisados': 0,
        'top3_production': 0.0,
        'top3_test_set': 0.0
    }

    try:
        # AUC
        auc_match = re.search(r'AUC Produção:\s*([\d.]+)\s*\(Test Set:\s*([\d.]+)', stdout)
        if auc_match:
            metrics['auc_production'] = float(auc_match.group(1))
            metrics['auc_test_set'] = float(auc_match.group(2))

        # Concentração Top 3
        top3_match = re.search(r'Top 3 Decis:\s*([\d.]+)%\s*\(Test Set:\s*([\d.]+)%', stdout)
        if top3_match:
            metrics['top3_production'] = float(top3_match.group(1))
            metrics['top3_test_set'] = float(top3_match.group(2))

        # Conversões
        conv_match = re.search(r'(\d+)\s+trackeadas', stdout)
        if conv_match:
            metrics['conversoes'] = int(conv_match.group(1))

        # ROAS
        roas_match = re.search(r'ROAS COM ML:\s*([\d.]+)x', stdout)
        if roas_match:
            metrics['roas'] = float(roas_match.group(1))

        # Leads
        leads_match = re.search(r'(\d+)\s+leads.*com score válido', stdout)
        if leads_match:
            metrics['leads_analisados'] = int(leads_match.group(1))

    except Exception as e:
        logger.warning(f"⚠️ Erro ao extrair métricas: {e}")

    return metrics


# =============================================================================
# RAILWAY POSTGRESQL — Polling de leads pendentes
# =============================================================================

@app.post("/railway/process-pending")
async def railway_process_pending(pipeline: PipelineDep):
    """
    Processa leads pendentes do Railway PostgreSQL (leadScore IS NULL).

    Chamado pelo Cloud Scheduler a cada 5 minutos.

    Fluxo:
    1. Conecta ao Railway PostgreSQL via pg8000
    2. Busca até 50 leads sem score (ORDER BY createdAt ASC)
    3. Converte pesquisa JSONB → formato Google Sheets via railway_mapping
    4. Roda pipeline ML em batch → lead_score + decil
    5. Atualiza Railway: leadScore, decil, updatedAt
    6. Envia eventos CAPI para Meta
    """

    import pg8000.native
    import json as _json
    from api.railway_mapping import railway_lead_to_sheets_row

    railway_conn = None
    try:
        # 1. Conectar ao Railway PostgreSQL
        railway_conn = pg8000.native.Connection(
            host=os.environ['RAILWAY_DB_HOST'],
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
            timeout=30,
        )

        # 2. Buscar leads sem score (máximo configurável por execução)
        _polling_limit = pipeline._client_config.api.railway_polling_batch_size
        rows = railway_conn.run(
            'SELECT id, data, "nomeCompleto", email, telefone, pesquisa, '
            'source, medium, campaign, content, term, '
            '"remoteIp", "userAgent", fbc, fbp, "pageUrl" '
            f'FROM "Lead" WHERE "leadScore" IS NULL '
            f'ORDER BY "createdAt" ASC LIMIT {_polling_limit}'
        )

        if not rows:
            logger.info("✅ Railway polling: nenhum lead pendente")
            return {"processed": 0, "skipped": 0, "message": "Nenhum lead pendente"}

        logger.info(f"📋 Railway polling: {len(rows)} leads pendentes encontrados")

        # 3. Construir lista de dicts (pg8000.native retorna listas, não dicts)
        col_names = [
            'id', 'data', 'nomeCompleto', 'email', 'telefone', 'pesquisa',
            'source', 'medium', 'campaign', 'content', 'term',
            'remoteIp', 'userAgent', 'fbc', 'fbp', 'pageUrl',
        ]

        lead_dicts = []
        for row in rows:
            lead = dict(zip(col_names, row))
            # pesquisa JSONB: pg8000 pode retornar string ou dict
            if isinstance(lead.get('pesquisa'), str):
                try:
                    lead['pesquisa'] = _json.loads(lead['pesquisa'])
                except Exception:
                    lead['pesquisa'] = {}
            elif lead.get('pesquisa') is None:
                lead['pesquisa'] = {}
            # Fallback: fbp/fbc podem estar no JSONB pesquisa (frontend v2)
            if not lead.get('fbp') and lead['pesquisa'].get('fbp'):
                lead['fbp'] = lead['pesquisa']['fbp']
            if not lead.get('fbc') and lead['pesquisa'].get('fbc'):
                lead['fbc'] = lead['pesquisa']['fbc']
            lead_dicts.append(lead)

        # 4. Converter para formato Google Sheets via railway_mapping
        sheets_rows = []
        valid_leads = []
        for lead in lead_dicts:
            try:
                sheets_row = railway_lead_to_sheets_row(lead, client_config=pipeline._client_config if pipeline else None)
                sheets_rows.append(sheets_row)
                valid_leads.append(lead)
            except Exception as e:
                logger.warning(f"⚠️ Erro ao mapear lead {lead.get('email')}: {e}")

        if not sheets_rows:
            return {
                "processed": 0,
                "skipped": len(lead_dicts),
                "message": "Todos os leads falharam no mapeamento",
            }

        # 5. A/B routing: particionar leads por variante antes de rodar o pipeline
        # Cada grupo usa o predictor e os thresholds da sua variante
        ab_variant_per_lead = []   # índice → ABTestVariantConfig ou None
        ab_name_per_lead = []      # índice → nome da variante ou None
        for lead in valid_leads:
            lead_utms = {
                'utm_campaign': lead.get('campaign'),
                'utm_content':  lead.get('content'),
                'utm_source':   lead.get('source'),
                'utm_medium':   lead.get('medium'),
                'utm_term':     lead.get('term'),
            }
            ab_variant = pipeline.get_ab_variant(lead_utms)
            ab_variant_per_lead.append(ab_variant)
            if ab_variant:
                ab_variant_name = next(
                    n for n, v in pipeline._ab_test_config.variants.items() if v is ab_variant
                )
                ab_name_per_lead.append(ab_variant_name)
            else:
                ab_name_per_lead.append(None)

        # Agrupar índices por nome de variante (None = fora do teste)
        from collections import defaultdict
        variant_groups = defaultdict(list)   # variant_name_or_None → [i, ...]
        for i, vname in enumerate(ab_name_per_lead):
            variant_groups[vname].append(i)

        # Rodar pipeline por grupo, coletar score+decil por índice
        score_by_index = {}   # i → (lead_score, decil_str)
        for vname, indices in variant_groups.items():
            predictor_ov = pipeline.get_variant_predictor(vname) if vname else pipeline.predictor
            # DT-12: encoding_overrides por variante (ex: jan30 usa ordinal para idade/salário).
            # Leads sem variante (vname=None) vão para o Champion — buscar o config da variante
            # cujo run_id coincide com pipeline.predictor para aplicar os mesmos overrides.
            if vname:
                variant_cfg = pipeline._ab_test_config.variants.get(vname)
            else:
                champion_run_id = pipeline.predictor.mlflow_run_id if hasattr(pipeline.predictor, 'mlflow_run_id') else None
                variant_cfg = next(
                    (v for v in pipeline._ab_test_config.variants.values() if v.run_id == champion_run_id),
                    None,
                ) if champion_run_id else None
            enc_overrides = variant_cfg.encoding_overrides if variant_cfg else None
            group_sheets = [sheets_rows[i] for i in indices]
            group_df = pd.DataFrame(group_sheets)
            temp_file = None
            group_result = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
                    group_df.to_csv(tmp, index=False)
                    temp_file = tmp.name
                group_label = vname or 'default'
                logger.info(f"   Executando pipeline para {len(group_sheets)} leads [{group_label}]...")
                group_result = pipeline.run(temp_file, with_predictions=True, predictor_override=predictor_ov, encoding_overrides=enc_overrides)
            finally:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)

            if group_result is None or len(group_result) == 0:
                logger.warning(f"⚠️ Pipeline retornou resultado vazio para grupo [{vname}]")
                continue

            group_thresholds = predictor_ov.metadata.get('decil_thresholds', {}).get('thresholds', {})
            for j, orig_i in enumerate(indices):
                try:
                    score = float(group_result['lead_score'].iloc[j])
                    decil = atribuir_decil_por_threshold(score, group_thresholds) if group_thresholds else "D05"
                    score_by_index[orig_i] = (score, decil)
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao extrair score para índice {orig_i}: {e}")

        if not score_by_index:
            raise HTTPException(status_code=500, detail="Pipeline retornou resultado vazio para todos os grupos")

        # 7. Atualizar Railway + preparar payload CAPI
        processed = 0
        skipped = 0
        capi_leads = []
        blocked_lead_ids = []  # leads bloqueados (utm_blocklist) — capiStatus='blocked'
        skipped_lead_ids = []  # leads ignorados (utm_source_allowlist) — capiStatus='skipped'

        for i, lead in enumerate(valid_leads):
            try:
                if i not in score_by_index:
                    skipped += 1
                    continue

                lead_score_value, decil_str = score_by_index[i]
                decil_int = int(decil_str[1:])  # 'D05' → 5

                # Atualizar Railway (pg8000 named parameters com :name)
                railway_conn.run(
                    'UPDATE "Lead" SET "leadScore" = :score, decil = :decil, '
                    '"updatedAt" = NOW() WHERE id = :lead_id',
                    score=lead_score_value,
                    decil=decil_int,
                    lead_id=lead['id'],
                )
                processed += 1

                # Preparar evento CAPI com overrides A/B se variante identificada
                nome = (lead.get('nomeCompleto') or '').strip()
                parts = nome.split(' ', 1)
                capi_lead = {
                    '_railway_id':      lead['id'],   # para UPDATE capiSentAt/capiStatus
                    'email':            lead.get('email'),
                    'phone':            lead.get('telefone'),
                    'first_name':       parts[0] if parts else None,
                    'last_name':        parts[1] if len(parts) > 1 else None,
                    'lead_score':       lead_score_value,
                    'decil':            decil_str,
                    'event_id':         str(uuid.uuid4()),
                    'fbp':              lead.get('fbp'),
                    'fbc':              lead.get('fbc'),
                    'user_agent':       lead.get('userAgent'),
                    'client_ip':        lead.get('remoteIp'),
                    'event_source_url': lead.get('pageUrl'),
                    'event_timestamp':  int(time.time()) - 60,
                    'survey_data':      None,
                }
                ab_v = ab_variant_per_lead[i]
                if ab_v:
                    capi_lead['ab_event_name'] = ab_v.capi_event_name
                    capi_lead['ab_event_name_hq'] = ab_v.capi_event_name_high_quality
                    capi_lead['ab_conversion_rates'] = ab_v.conversion_rates

                # UTM filter: blocklist por campaign + allowlist por source (DT-CAPI-01/02)
                _utm_cam = (lead.get('campaign') or '').lower()
                _utm_src = (lead.get('source') or '').lower()
                _blocklist = pipeline._client_config.capi.utm_blocklist or []
                _allowlist = pipeline._client_config.capi.utm_source_allowlist or []
                _capi_blocked = any(p.lower() in _utm_cam for p in _blocklist)
                _capi_skipped = bool(_allowlist) and not any(s.lower() in _utm_src for s in _allowlist)
                if _capi_blocked:
                    logger.info(f"   ⏭️ CAPI bloqueado por UTM blocklist: {lead.get('campaign')}")
                    blocked_lead_ids.append(lead['id'])
                elif _capi_skipped:
                    logger.info(f"   ⏭️ CAPI ignorado — source não permitido: {lead.get('source')}")
                    skipped_lead_ids.append(lead['id'])
                else:
                    capi_leads.append(capi_lead)

                logger.info(
                    f"   ✅ {lead.get('email')}: score={lead_score_value:.4f} ({decil_str})"
                )

            except Exception as e:
                logger.error(f"⚠️ Erro ao processar lead {lead.get('email')}: {e}")
                skipped += 1

        # 8. Enviar eventos CAPI (db=None — Railway não usa Cloud SQL)
        capi_result: Dict = {"success": 0, "total": 0, "errors": 0}
        if capi_leads:
            logger.info(f"📤 Enviando {len(capi_leads)} eventos CAPI (Railway)...")
            capi_result = send_batch_events(capi_leads, db=None, capi_config=pipeline._client_config.capi,
                                            business_config=pipeline._client_config.business,
                                            client_id=pipeline._client_config.client_id)
            logger.info(
                f"✅ CAPI Railway: {capi_result.get('success', 0)}/"
                f"{capi_result.get('total', 0)} enviados"
            )

        # 9. Atualizar capiSentAt + capiStatus no Railway
        details = capi_result.get('details', [])
        for i, detail in enumerate(details):
            if i >= len(capi_leads):
                break
            capi_status = 'success' if detail.get('status') == 'success' else 'error'
            try:
                railway_conn.run(
                    'UPDATE "Lead" SET "capiSentAt" = NOW(), "capiStatus" = :status, '
                    '"updatedAt" = NOW() WHERE id = :lead_id',
                    status=capi_status,
                    lead_id=capi_leads[i]['_railway_id'],
                )
            except Exception as e:
                logger.warning(f"⚠️ Erro ao atualizar capiSentAt para {capi_leads[i].get('email')}: {e}")

        # 9b. Marcar leads bloqueados (utm_blocklist) e ignorados (utm_source_allowlist)
        for lead_id, status in [(lid, 'blocked') for lid in blocked_lead_ids] + \
                               [(lid, 'skipped') for lid in skipped_lead_ids]:
            try:
                railway_conn.run(
                    'UPDATE "Lead" SET "capiSentAt" = NOW(), "capiStatus" = :status, '
                    '"updatedAt" = NOW() WHERE id = :lead_id',
                    status=status,
                    lead_id=lead_id,
                )
            except Exception as e:
                logger.warning(f"⚠️ Erro ao marcar lead {status} {lead_id}: {e}")

        logger.info(
            f"✅ Railway polling concluído: {processed} processados, "
            f"{skipped} erros, {capi_result.get('success', 0)} CAPI enviados, "
            f"{len(blocked_lead_ids)} bloqueados, {len(skipped_lead_ids)} ignorados por source"
        )

        return {
            "processed":     processed,
            "skipped":       skipped,
            "capi_sent":     capi_result.get('success', 0),
            "capi_errors":   capi_result.get('errors', 0),
            "capi_blocked":  len(blocked_lead_ids),
            "capi_skipped":  len(skipped_lead_ids),
            "timestamp":     datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro no polling Railway: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro no polling Railway: {str(e)}")
    finally:
        if railway_conn:
            try:
                railway_conn.close()
            except Exception:
                pass


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