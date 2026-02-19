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
from typing import List, Dict, Any, Optional
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
from src.features.engineering import create_derived_features
from src.features.encoding import apply_categorical_encoding

# Importar integrações
from api.meta_integration import MetaAdsIntegration, enrich_utm_analysis_with_costs, enrich_utm_with_hierarchy
from api.meta_config import META_CONFIG, BUSINESS_CONFIG
from api.economic_metrics import enrich_utm_with_economic_metrics

# Importar módulos CAPI
from api.database import get_db, init_database, create_lead_capi, count_leads, count_leads_with_fbp, count_leads_with_fbc, get_leads_by_emails, LeadCAPI
from api.capi_integration import send_batch_events
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.model.decil_thresholds import atribuir_decil_por_threshold

# Padrões de UTMs inválidos (bare names e genéricos)
BARE_CAMPAIGN_NAMES = ['DEVLF', 'devlf']                      # Prefixos incompletos
BARE_MEDIUM_NAMES = ['dgen', 'paid']                          # Termos genéricos sem estrutura
GENERIC_TERMS = ['fb', 'ig', 'instagram', 'facebook']         # Apenas redes sociais

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

# Inicializar a aplicação FastAPI
app = FastAPI(
    title="Smart Ads Lead Scoring API V2",
    description="API otimizada para predições em batch via Google Sheets",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Adicionar CORS para Google Apps Script e Landing Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://script.google.com",
        "https://script.googleusercontent.com",
        "http://localhost:8001",
        "http://localhost:8000",
        "https://lp.devclub.com.br",
        "*"  # Permitir todos (TEMPORÁRIO - em produção especificar domínios)
    ],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Variável global para o pipeline
pipeline = None

def initialize_pipeline():
    """Inicializa o pipeline de lead scoring com modelo ativo do configs/active_model.yaml"""
    global pipeline
    try:
        logger.info("Inicializando pipeline de Lead Scoring...")
        # Usar modelo ativo do configs/active_model.yaml (não passar model_name)
        pipeline = LeadScoringPipeline()
        logger.info("Pipeline inicializado com sucesso!")
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar pipeline: {e}")
        return False

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
    logger.info("🚀 Iniciando Smart Ads API V2...")
    if not initialize_pipeline():
        logger.error("❌ Falha ao inicializar pipeline!")
    else:
        logger.info("✅ API V2 pronta para receber requisições!")

    # Inicializar database
    if init_database():
        logger.info("✅ Database inicializado com sucesso")
    else:
        logger.warning("⚠️ Database não inicializado (desenvolvimento sem PostgreSQL?)")

@app.get("/")
async def root():
    """Endpoint raiz"""
    return {
        "message": "Smart Ads Lead Scoring API V2",
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
    pipeline_status = "healthy" if pipeline is not None else "unhealthy"
    model_loaded = pipeline is not None

    return {
        "status": "healthy",
        "pipeline_status": pipeline_status,
        "model_loaded": model_loaded,
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0"
    }

@app.get("/model/info")
async def get_model_info():
    """
    Retorna informações sobre o modelo: metadados, performance e feature importances
    """
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline não inicializado")

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
            mapping_file = Path(__file__).parent.parent / "arquivos_modelo" / "feature_name_mapping_v1_devclub_rf_temporal_single.json"
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
async def predict_batch_json(request: BatchPredictionRequest):
    """
    Predição em batch via JSON
    Otimizado para Google Apps Script
    """
    global pipeline

    # Verificar pipeline
    if pipeline is None:
        if not initialize_pipeline():
            raise HTTPException(status_code=500, detail="Pipeline não inicializado")

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
async def predict_batch_csv(file: UploadFile = File(...)):
    """
    Predição em batch via upload CSV
    Para testes ou uploads manuais
    """
    global pipeline

    if pipeline is None:
        if not initialize_pipeline():
            raise HTTPException(status_code=500, detail="Pipeline não inicializado")

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
async def calculate_decils(request: DecilCalculationRequest):
    """
    Calcula decis para scores já existentes (útil para backfill).

    Args:
        request: Lista de lead_scores

    Returns:
        Lista de scores + decis calculados
    """
    global pipeline

    if pipeline is None:
        if not initialize_pipeline():
            raise HTTPException(status_code=500, detail="Pipeline não inicializado")

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
            'cidade': lead_data.cidade
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

                # Mapeamento de colunas normalizadas → nomes do Sheets
                column_mapping = {
                    'email': 'E-mail',
                    'name': 'Nome Completo',
                    'phone': 'Telefone',
                    'genero': 'O seu gênero:',
                    'idade': 'Qual a sua idade?',
                    'ocupacao': 'O que você faz atualmente?',
                    'faixa_salarial': 'Atualmente, qual a sua faixa salarial?',
                    'cartao_credito': 'Você possui cartão de crédito?',
                    'interesse_evento': 'O que mais você quer ver no evento?',
                    'estudou_programacao': 'Já estudou programação?',
                    'pretende_faculdade': 'Você já fez/faz/pretende fazer faculdade?',
                    'investiu_curso_online': 'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?',
                    'interesse_programacao': 'O que mais te chama atenção na profissão de Programador?',
                    'cidade': 'cidade'
                }

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
                }], db)

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
        existing_lead = get_lead_by_email(db, survey_data.email)

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

            # Mapeamento: PostgreSQL → Google Sheets (nomes originais do modelo)
            column_mapping = {
                'email': 'E-mail',
                'name': 'Nome Completo',
                'phone': 'Telefone',
                'genero': 'O seu gênero:',
                'idade': 'Qual a sua idade?',
                'ocupacao': 'O que você faz atualmente?',
                'faixa_salarial': 'Atualmente, qual a sua faixa salarial?',
                'cartao_credito': 'Você possui cartão de crédito?',
                'interesse_evento': 'O que mais você quer ver no evento?',
                'estudou_programacao': 'Já estudou programação?',
                'pretende_faculdade': 'Você já fez/faz/pretende fazer faculdade?',
                'investiu_curso_online': 'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?',
                'interesse_programacao': 'O que mais te chama atenção na profissão de Programador?',
                'cidade': 'cidade',
                # Campos adicionados para fix de scoring (features faltantes)
                'created_at': 'Data',
                'utm_source': 'Source',
                'utm_medium': 'Medium',
                'utm_campaign': 'Campaign',
                'utm_term': 'Term',
                'utm_content': 'Content',
                'tem_comp': 'Tem computador/notebook?'
            }

            # Aplicar mapeamento
            lead_dict_mapped = {}
            for col_pg, col_sheets in column_mapping.items():
                if col_pg in lead_dict_raw:
                    lead_dict_mapped[col_sheets] = lead_dict_raw[col_pg]

            # Criar DataFrame com nomes do Sheets
            lead_df = pd.DataFrame([lead_dict_mapped])
            logger.info(f"   DataFrame criado: {lead_df.shape}, colunas={list(lead_df.columns)[:10]}")

            # Usar pipeline.run() completo (igual /predict/batch)
            # Isso garante que TODAS as transformações de dados sejam aplicadas
            temp_file = None
            try:
                # Salvar em CSV temporário
                with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
                    lead_df.to_csv(tmp, index=False)
                    temp_file = tmp.name

                logger.info("   Executando pipeline completo...")
                result_df = pipeline.run(temp_file, with_predictions=True)

                if result_df is None or len(result_df) == 0:
                    raise HTTPException(status_code=500, detail="Pipeline retornou resultado vazio")

            finally:
                # Limpar arquivo temporário
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)

            # Calcular decil usando thresholds do modelo
            lead_score_value = float(result_df['lead_score'].iloc[0])
            thresholds = pipeline.predictor.metadata.get('decil_thresholds', {}).get('thresholds', {})

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

            capi_result = send_batch_events([{
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
            }], db)

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
            leads = get_recent_leads(db, limit=limit)

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
        leads = get_leads_by_emails(db, emails)

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
        leads_capi = get_leads_by_emails(db, emails)

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
        results = send_batch_events(enriched_leads, db=db)

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
        sent_emails = get_leads_already_sent_to_capi(db, request.emails)

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

# === ANÁLISE UTM COM CUSTOS ===

class UTMAnalysisRequest(BaseModel):
    """Request para análise UTM com custos"""
    leads: List[LeadData] = Field(..., min_items=1)  # Sem limite máximo - batching interno
    account_id: str = Field(..., description="ID da conta Meta Ads (ex: act_123456)")
    product_value: Optional[float] = Field(default=None, description="Valor do produto (padrão: config)")
    min_roas: Optional[float] = Field(default=None, description="ROAS mínimo (padrão: 2.0)")

class UTMDimensionMetrics(BaseModel):
    """Métricas de uma dimensão UTM"""
    campaign: Optional[str] = None  # Para adsets e ads: nome da campanha de origem
    adset: Optional[str] = None     # Para ads: nome do adset de origem
    value: str
    leads: int
    spend: float
    cpl: float
    taxa_proj: float
    receita_proj: float     # Receita projetada (NOVO - Margem de Contribuição)
    margem_contrib: float   # Margem de Contribuição (NOVO - substitui margem%)
    roas_proj: float
    acao: str
    budget_current: float  # Orçamento atual (gasto do período)
    budget_target: float   # Orçamento alvo (baseado na ação)

class UTMPeriodAnalysis(BaseModel):
    """Análise UTM para um período"""
    campaign: List[UTMDimensionMetrics]
    medium: List[UTMDimensionMetrics]
    ad: List[UTMDimensionMetrics]
    google_ads: List[UTMDimensionMetrics]
    # Metadados do período
    period_start: str  # Data/hora do lead mais antigo (ISO format)
    period_end: str    # Data/hora do lead mais recente (ISO format)
    total_leads: int   # Total de leads analisados
    meta_leads: int    # Leads do Meta/Facebook
    google_leads: int  # Leads do Google Ads

class UTMAnalysisResponse(BaseModel):
    """Response completa da análise UTM"""
    request_id: str
    periods: Dict[str, UTMPeriodAnalysis]  # '1D', '3D', '7D', 'Total'
    config: Dict[str, Any]  # product_value, min_roas usado
    processing_time_seconds: float
    timestamp: str

@app.post("/analyze_utms_with_costs", response_model=UTMAnalysisResponse)
async def analyze_utms_with_costs(request: UTMAnalysisRequest):
    """
    Análise UTM enriquecida com custos do Meta Ads e métricas econômicas

    Fluxo:
    1. Executar predições (lead_score, decile)
    2. Buscar custos da API Meta (1D, 3D, 7D, Total)
    3. Calcular análise UTM por dimensão
    4. Enriquecer com métricas econômicas (CPL, ROAS, Margem, Ação)
    5. Retornar estrutura por período
    """
    global pipeline

    # Verificar pipeline
    if pipeline is None:
        if not initialize_pipeline():
            raise HTTPException(status_code=500, detail="Pipeline não inicializado")

    start_time = time.time()
    request_id = str(uuid.uuid4())

    logger.info(f"📊 Iniciando análise UTM com custos (Request ID: {request_id})")
    logger.info(f"   Leads: {len(request.leads)} | Account: {request.account_id}")

    temp_file = None  # Para limpeza no finally (apenas para caso de lote único)

    try:
        # Configuração
        product_value = request.product_value or BUSINESS_CONFIG['product_value']
        min_roas = request.min_roas or BUSINESS_CONFIG['min_roas']
        conversion_rates = BUSINESS_CONFIG['conversion_rates']

        logger.info(f"   Product Value: R$ {product_value:.2f} | Min ROAS: {min_roas}x")

        # 1. VERIFICAR SE JÁ EXISTEM PREDIÇÕES
        total_leads = len(request.leads)
        logger.info(f"   Total de leads: {total_leads}")

        # Debug: mostrar estrutura do primeiro lead
        if total_leads > 0:
            first_lead = request.leads[0].data
            logger.info(f"   🔍 DEBUG: Chaves do primeiro lead: {list(first_lead.keys())[:10]}...")
            logger.info(f"   🔍 DEBUG: Tem 'lead_score'? {'lead_score' in first_lead}")
            logger.info(f"   🔍 DEBUG: Tem 'decile'? {'decile' in first_lead}")

            # Verificar se leads já têm predições (apenas lead_score é necessário)
            has_predictions = 'lead_score' in first_lead
            logger.info(f"   🔍 DEBUG: has_predictions = {has_predictions}")
        else:
            logger.error("   ❌ ERRO: Nenhum lead recebido!")
            raise HTTPException(status_code=400, detail="Nenhum lead recebido")

        if has_predictions:
            logger.info("✅ Leads já possuem predições existentes, pulando etapa de predição...")

            # Construir DataFrame com predições existentes
            lead_rows = []
            for i, lead in enumerate(request.leads):
                row = lead.data.copy()
                row['_email'] = lead.email
                row['_row_id'] = lead.row_id or str(i)
                lead_rows.append(row)

            result_df = pd.DataFrame(lead_rows)
            result_df['email'] = result_df['_email']
            result_df['row_id'] = result_df['_row_id']
            result_df = result_df.drop(columns=['_email', '_row_id'], errors='ignore')

            # Renomear colunas se necessário para padronizar
            if 'decile' in result_df.columns:
                result_df = result_df.rename(columns={'decile': 'decil'})

            logger.info(f"✅ {len(result_df)} leads carregados com predições existentes")

        else:
            # 1. PREDIÇÕES COM BATCHING INTERNO
            logger.info("🔄 Executando predições...")

            # Processar em lotes se necessário
            BATCH_SIZE = 500
            all_results = []

            if total_leads <= BATCH_SIZE:
                # Processar todos de uma vez
                logger.info("   Processando em lote único")
                lead_rows = []
                for i, lead in enumerate(request.leads):
                    row = lead.data.copy()
                    row['_email'] = lead.email
                    row['_row_id'] = lead.row_id or str(i)
                    lead_rows.append(row)

                df = pd.DataFrame(lead_rows)

                with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
                    model_df = df.drop(columns=['_email', '_row_id'], errors='ignore')
                    model_df.to_csv(tmp, index=False)
                    temp_file = tmp.name

                result_df = pipeline.run(temp_file, with_predictions=True)

                if result_df is None or len(result_df) == 0:
                    raise HTTPException(status_code=500, detail="Pipeline retornou resultado vazio")

                result_df['email'] = df['_email'].values
                result_df['row_id'] = df['_row_id'].values

                all_results.append(result_df)

            else:
                # Processar em lotes
                num_batches = (total_leads + BATCH_SIZE - 1) // BATCH_SIZE
                logger.info(f"   Processando em {num_batches} lotes de ~{BATCH_SIZE} leads")

                for batch_idx in range(num_batches):
                    start_idx = batch_idx * BATCH_SIZE
                    end_idx = min(start_idx + BATCH_SIZE, total_leads)
                    batch_leads = request.leads[start_idx:end_idx]

                    logger.info(f"   Lote {batch_idx + 1}/{num_batches}: {len(batch_leads)} leads")

                    lead_rows = []
                    for i, lead in enumerate(batch_leads):
                        row = lead.data.copy()
                        row['_email'] = lead.email
                        row['_row_id'] = lead.row_id or str(start_idx + i)
                        lead_rows.append(row)

                    batch_df = pd.DataFrame(lead_rows)

                    batch_temp_file = None
                    try:
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
                            model_df = batch_df.drop(columns=['_email', '_row_id'], errors='ignore')
                            model_df.to_csv(tmp, index=False)
                            batch_temp_file = tmp.name

                        batch_result = pipeline.run(batch_temp_file, with_predictions=True)

                        if batch_result is None or len(batch_result) == 0:
                            logger.warning(f"   Lote {batch_idx + 1} retornou vazio")
                            continue

                        batch_result['email'] = batch_df['_email'].values
                        batch_result['row_id'] = batch_df['_row_id'].values

                        all_results.append(batch_result)

                    finally:
                        if batch_temp_file and os.path.exists(batch_temp_file):
                            os.remove(batch_temp_file)

            # Consolidar resultados
            if not all_results:
                raise HTTPException(status_code=500, detail="Nenhum resultado de predição obtido")

            result_df = pd.concat(all_results, ignore_index=True)
            logger.info(f"✅ Predições concluídas: {len(result_df)} leads consolidados")

        # 2. CALCULAR JANELAS TEMPORAIS (dias completos: 00:00-23:59)
        now = pd.Timestamp.now(tz=None)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Usar até 00:00 de hoje (= fim de ontem 23:59:59)
        cutoff_end = today_start

        # Calcular início para cada período
        period_windows = {
            '1D': cutoff_end - pd.Timedelta(days=1),
            '3D': cutoff_end - pd.Timedelta(days=3),
            '7D': cutoff_end - pd.Timedelta(days=7)
        }

        logger.info(f"📅 Janelas temporais (dias completos):")
        for period, start_date in period_windows.items():
            logger.info(f"   {period}: {start_date.strftime('%Y-%m-%d %H:%M')} até {cutoff_end.strftime('%Y-%m-%d %H:%M')}")

        # 3. BUSCAR CUSTOS DA API META (HIERARQUIA COMPLETA POR PERÍODO)
        logger.info("💰 Buscando hierarquia de custos da API Meta...")
        meta_client = MetaAdsIntegration(
            access_token=META_CONFIG['access_token'],
            api_version=META_CONFIG['api_version']
        )

        # Buscar hierarquia completa para cada período separadamente
        # IMPORTANTE: Meta API retorna dados AGREGADOS do período solicitado
        # Não é possível buscar 7D e filtrar para 1D - os custos são diferentes!
        hierarchy_by_period = {}
        for period_key, start_date in period_windows.items():
            # Converter timestamps para strings no formato YYYY-MM-DD
            since_str = start_date.strftime('%Y-%m-%d')
            until_str = cutoff_end.strftime('%Y-%m-%d')

            logger.info(f"🔍 Buscando hierarquia Meta para {period_key} (de {since_str} até {until_str} exclusivo)...")

            hierarchy_by_period[period_key] = meta_client.get_costs_hierarchy(
                account_id=request.account_id,
                since_date=since_str,
                until_date=until_str
            )

        logger.info(f"✅ Hierarquia obtida para {len(hierarchy_by_period)} períodos")

        # Log detalhado de hierarquia por período
        for period_key, hierarchy in hierarchy_by_period.items():
            total_campaigns = len(hierarchy['campaigns'])
            total_spend = sum(c['spend'] for c in hierarchy['campaigns'].values())
            total_adsets = sum(len(c['adsets']) for c in hierarchy['campaigns'].values())
            total_ads = sum(sum(len(a['ads']) for a in c['adsets'].values()) for c in hierarchy['campaigns'].values())
            logger.info(f"   {period_key}: {total_campaigns} campaigns, {total_adsets} adsets, {total_ads} ads | R$ {total_spend:.2f}")

        # 4. CALCULAR DECIS USANDO THRESHOLDS FIXOS DO MODELO
        logger.info("📊 Calculando decis usando thresholds fixos do modelo...")

        from src.model.decil_thresholds import atribuir_decis_batch

        # Carregar thresholds do modelo ativo
        thresholds = pipeline.predictor.metadata.get('decil_thresholds', {}).get('thresholds')
        threshold_name = pipeline.predictor.metadata.get('decil_thresholds', {}).get('name', 'unknown')

        if not thresholds:
            logger.error("❌ Thresholds não encontrados no modelo!")
            raise HTTPException(status_code=500, detail="Thresholds do modelo não configurados")

        logger.info(f"   ✅ Thresholds carregados: {threshold_name}")

        # Garantir que lead_score é numérico
        result_df['lead_score'] = pd.to_numeric(result_df['lead_score'], errors='coerce')

        # Remover linhas com lead_score inválido
        result_df = result_df[result_df['lead_score'].notna()].copy()

        # Atribuir decis usando thresholds fixos
        result_df['decil'] = atribuir_decis_batch(
            result_df['lead_score'].values,
            thresholds
        )

        logger.info(f"✅ Decis calculados para {len(result_df)} leads (thresholds fixos)")
        logger.info(f"   📊 Distribuição: {result_df['decil'].value_counts().sort_index().to_dict()}")

        # 5. GERAR ANÁLISE UTM POR PERÍODO E DIMENSÃO
        logger.info("📈 Gerando análise UTM...")

        periods_analysis = {}

        for period_key, hierarchy in hierarchy_by_period.items():
            logger.info(f"   Processando período: {period_key}")

            # Extrair número de dias do período ('1D' → 1, '3D' → 3, etc.)
            if period_key == 'Total':
                # Para Total, calcular diferença real entre datas
                period_days = 30  # Default conservador
            else:
                try:
                    period_days = int(period_key.replace('D', ''))
                except:
                    period_days = 1  # Fallback

            # Usar janela pré-calculada
            cutoff_start = period_windows[period_key]

            # Filtrar do dataset (que já tem decis calculados via thresholds)
            if 'Data' in result_df.columns:
                dates_df = pd.to_datetime(result_df['Data'], errors='coerce')
                if dates_df.dt.tz is not None:
                    dates_df = dates_df.dt.tz_localize(None)

                # Filtrar: Data >= cutoff_start AND Data < cutoff_end
                valid_dates_mask = dates_df.notna()
                period_df = result_df[valid_dates_mask & (dates_df >= cutoff_start) & (dates_df < cutoff_end)].copy()
                logger.info(f"   Leads no período {period_key}: {len(period_df)}")
            else:
                period_df = result_df.copy()
                logger.warning(f"   Coluna 'Data' não encontrada, usando todos os leads")

            # Capturar metadados: timestamps reais dos leads dentro da janela
            if 'Data' in period_df.columns and len(period_df) > 0:
                period_dates = pd.to_datetime(period_df['Data'], errors='coerce')
                if period_dates.dt.tz is not None:
                    period_dates = period_dates.dt.tz_localize(None)

                # Filtrar apenas datas válidas para min/max
                valid_period_dates = period_dates[period_dates.notna()]
                if len(valid_period_dates) > 0:
                    period_start = valid_period_dates.min().isoformat()
                    period_end = valid_period_dates.max().isoformat()
                else:
                    period_start = cutoff_start.isoformat()
                    period_end = cutoff_end.isoformat()
            else:
                period_start = cutoff_start.isoformat()
                period_end = cutoff_end.isoformat()

            # Contar leads por fonte
            total_leads = len(period_df)
            if 'Source' in period_df.columns:
                meta_leads = (period_df['Source'] == 'facebook-ads').sum()
                google_leads = (period_df['Source'] == 'google-ads').sum()
            else:
                meta_leads = total_leads
                google_leads = 0

            logger.info(f"   📊 Metadados: {period_start} até {period_end} | Total: {total_leads} | Meta: {meta_leads} | Google: {google_leads}")

            # Validar que temos leads e decis
            if len(period_df) == 0:
                logger.warning(f"   ⚠️ Nenhum lead no período {period_key}")
                continue

            if 'decil' not in period_df.columns:
                logger.error(f"   ❌ ERRO: Coluna 'decil' não encontrada após filtro")
                # Fallback emergencial
                period_df['decil'] = 'D5'

            period_analysis = {}

            # Dimensões a analisar (incluindo google_ads como dimensão separada)
            # Removido 'term' - não tem custo no Meta API, análise inútil
            dimensions = ['campaign', 'medium', 'ad', 'google_ads']

            for dimension in dimensions:
                # Tratamento especial para Google Ads
                if dimension == 'google_ads':
                    # Filtrar apenas leads do Google Ads
                    if 'Source' in period_df.columns:
                        google_df = period_df[period_df['Source'] == 'google-ads']

                        if len(google_df) == 0:
                            logger.info(f"   ℹ️ Nenhum lead Google Ads no período {period_key}")
                            period_analysis[dimension] = []
                            continue

                        logger.info(f"   📊 {len(google_df)} leads Google Ads no período {period_key}")

                        # Agrupar por Term (formato: "keyword--campaign_id--ad_id")
                        # Extrair apenas keyword (primeira parte)
                        def extract_keyword_from_term(term_value):
                            """Extrai keyword da primeira parte do Term"""
                            if pd.isna(term_value) or str(term_value).strip() == '':
                                return None
                            # Formato: "keyword--campaign_id--ad_id"
                            parts = str(term_value).split('--')
                            if len(parts) >= 1 and parts[0].strip() != '':
                                return parts[0].strip()  # Keyword
                            return None

                        google_df['keyword'] = google_df['Term'].apply(extract_keyword_from_term)

                        # Filtrar valores genéricos e vazios
                        google_df_filtered = google_df[
                            google_df['keyword'].notna() &
                            ~google_df['keyword'].isin(['fb', 'ig', 'instagram', 'facebook'])
                        ].copy()

                        if len(google_df_filtered) == 0:
                            logger.info(f"   ⚠️ Nenhum keyword válido encontrado para Google Ads")
                            period_analysis[dimension] = []
                            continue

                        grouped = google_df_filtered.groupby('keyword').agg({
                            'lead_score': 'count',
                            'decil': lambda x: (x == 'D10').sum() / len(x) * 100 if len(x) > 0 else 0,
                        }).rename(columns={'lead_score': 'leads', 'decil': 'pct_d10'})

                        # Calcular distribuição de decis
                        for value in grouped.index:
                            value_df = google_df_filtered[google_df_filtered['keyword'] == value]
                            for i in range(1, 11):
                                decile_key = f'D{i}'
                                pct = (value_df['decil'] == decile_key).sum() / len(value_df) * 100 if len(value_df) > 0 else 0
                                grouped.at[value, f'%{decile_key}'] = pct

                        grouped = grouped.reset_index().rename(columns={'keyword': 'value'})

                        # Google Ads não tem custos no Meta API
                        grouped['spend'] = 0.0

                        # Enriquecer com métricas econômicas (todas zeradas/não aplicáveis)
                        enriched = enrich_utm_with_economic_metrics(
                            utm_df=grouped,
                            product_value=product_value,
                            min_roas=min_roas,
                            conversion_rates=conversion_rates,
                            dimension=dimension,
                            period_days=period_days
                        )

                        enriched = enriched.fillna({
                            'leads': 0,
                            'spend': 0.0,
                            'cpl': 0.0,
                            'taxa_proj': 0.0,
                            'receita_proj': 0.0,
                            'margem_contrib': 0.0,
                            'roas_proj': 0.0,
                            'acao': 'N/A - Google Ads',
                            'budget_current': 0.0,
                            'budget_target': 0.0
                        })

                        period_analysis[dimension] = [
                            UTMDimensionMetrics(
                                campaign=None,
                                value=str(row['value']) if pd.notna(row['value']) else '(vazio)',
                                leads=int(row['leads']),
                                spend=float(row['spend']),
                                cpl=float(row['cpl']),
                                taxa_proj=float(row['taxa_proj']),
                                receita_proj=float(row['receita_proj']),
                                margem_contrib=float(row['margem_contrib']),
                                roas_proj=float(row['roas_proj']),
                                acao=str(row['acao']),
                                budget_current=float(row.get('budget_current', 0.0)),
                                budget_target=float(row.get('budget_target', 0.0))
                            )
                            for _, row in enriched.iterrows()
                        ]

                        logger.info(f"✅ Google Ads analisado: {len(period_analysis[dimension])} grupos")
                        continue
                    else:
                        period_analysis[dimension] = []
                        continue

                # Processar dimensões Meta normalmente
                # Mapear para coluna do DataFrame
                utm_col_map = {
                    'campaign': 'Campaign',
                    'medium': 'Medium',
                    'term': 'Term',
                    'ad': 'Content'  # Ad = Criativo = Coluna Content
                }

                utm_col = utm_col_map.get(dimension, 'Campaign')

                # Agrupar por dimensão
                if utm_col not in period_df.columns:
                    logger.warning(f"⚠️  Coluna '{utm_col}' não encontrada, pulando dimensão '{dimension}'")
                    period_analysis[dimension] = []
                    continue

                # Filtrar UTMs vazios e inválidos
                utm_mask = (
                    (period_df[utm_col].notna()) &
                    (period_df[utm_col] != '') &
                    (~period_df[utm_col].astype(str).str.contains('{{', regex=False))  # Placeholders
                )

                # Filtros específicos por dimensão
                if dimension == 'campaign':
                    # Remover bare names (case insensitive)
                    for bare in BARE_CAMPAIGN_NAMES:
                        utm_mask &= ~(period_df[utm_col].astype(str).str.upper() == bare.upper())

                elif dimension == 'medium':
                    # Remover bare names
                    for bare in BARE_MEDIUM_NAMES:
                        utm_mask &= ~(period_df[utm_col].astype(str).str.upper() == bare.upper())

                elif dimension == 'term':
                    # Remover termos genéricos (fb, ig, etc)
                    for generic in GENERIC_TERMS:
                        utm_mask &= ~(period_df[utm_col].astype(str).str.upper() == generic.upper())

                # Aplicar filtro
                period_df_filtered = period_df[utm_mask]

                # Log detalhado de valores filtrados
                filtered_count = len(period_df) - len(period_df_filtered)
                if filtered_count > 0:
                    filtered_df = period_df[~utm_mask]
                    filtered_values = filtered_df[utm_col].value_counts()

                    logger.info(f"   ⚠️ {filtered_count} leads filtrados de '{dimension}' ({period_key}):")
                    for val, count in filtered_values.head(5).items():
                        logger.info(f"      - '{val}': {count} leads (bare name/genérico)")

                if len(period_df_filtered) == 0:
                    logger.warning(f"⚠️ Nenhum lead com '{utm_col}' válido no período, pulando dimensão '{dimension}'")
                    period_analysis[dimension] = []
                    continue

                # CORREÇÃO: Para Campaign, agrupar por Campaign ID (não por UTM completo)
                if dimension == 'campaign':
                    from api.meta_integration import extract_id_from_utm

                    # Extrair Campaign ID de cada UTM
                    period_df_filtered = period_df_filtered.copy()
                    period_df_filtered['campaign_id'] = period_df_filtered[utm_col].apply(extract_id_from_utm)

                    # Remover linhas sem Campaign ID
                    period_df_filtered = period_df_filtered[period_df_filtered['campaign_id'].notna()]

                    # Agrupar por Campaign ID
                    grouped = period_df_filtered.groupby('campaign_id').agg({
                        'lead_score': 'count',
                        'decil': lambda x: (x == 'D10').sum() / len(x) * 100 if len(x) > 0 else 0,
                    }).rename(columns={'lead_score': 'leads', 'decil': 'pct_d10'})

                    # Calcular distribuição de decis
                    for campaign_id in grouped.index:
                        value_df = period_df_filtered[period_df_filtered['campaign_id'] == campaign_id]
                        for i in range(1, 11):
                            decile_key = f'D{i}'
                            pct = (value_df['decil'] == decile_key).sum() / len(value_df) * 100 if len(value_df) > 0 else 0
                            grouped.at[campaign_id, f'%{decile_key}'] = pct

                    # Resetar index e renomear para 'value' (será o Campaign ID)
                    grouped = grouped.reset_index().rename(columns={'campaign_id': 'value'})

                elif dimension == 'medium':
                    # Para adsets, agrupar por (campaign, adset) para separar mesmo nome em campanhas diferentes
                    # Extrair campaign_id da coluna Campaign
                    period_df_filtered = period_df_filtered.copy()

                    # Verificar se temos coluna Campaign (utm_campaign)
                    if 'Campaign' not in period_df_filtered.columns:
                        logger.warning(f"⚠️  Coluna 'Campaign' não encontrada para matchear adsets. Usando apenas nome do adset.")
                        # Fallback: agrupar só por nome do adset (comportamento antigo)
                        grouped = period_df_filtered.groupby(utm_col).agg({
                            'lead_score': 'count',
                            'decil': lambda x: (x == 'D10').sum() / len(x) * 100 if len(x) > 0 else 0,
                        }).rename(columns={'lead_score': 'leads', 'decil': 'pct_d10'})

                        for value in grouped.index:
                            value_df = period_df_filtered[period_df_filtered[utm_col] == value]
                            for i in range(1, 11):
                                decile_key = f'D{i}'
                                pct = (value_df['decil'] == decile_key).sum() / len(value_df) * 100 if len(value_df) > 0 else 0
                                grouped.at[value, f'%{decile_key}'] = pct

                        grouped = grouped.reset_index().rename(columns={utm_col: 'value'})
                        grouped['campaign_name'] = None  # Sem campaign info
                    else:
                        period_df_filtered['campaign_id'] = period_df_filtered['Campaign'].apply(extract_id_from_utm)

                        # Criar mapeamento (campaign_id, adset_name) → adset_id da hierarquia
                        campaign_adset_to_info = {}
                        for campaign_id, campaign_data in hierarchy['campaigns'].items():
                            for adset_id, adset_data in campaign_data['adsets'].items():
                                key = (campaign_id, adset_data['name'])
                                campaign_adset_to_info[key] = {
                                    'adset_id': adset_id,
                                    'campaign_name': campaign_data['name']
                                }

                        # Matchear cada lead para adset_id específico
                        def match_adset(row):
                            campaign_id = row['campaign_id']
                            adset_name = row[utm_col]
                            if pd.isna(campaign_id) or pd.isna(adset_name):
                                return None, None
                            key = (str(campaign_id), str(adset_name))
                            info = campaign_adset_to_info.get(key)
                            if info:
                                return info['adset_id'], info['campaign_name']
                            return None, None

                        period_df_filtered[['adset_id', 'campaign_name']] = period_df_filtered.apply(
                            match_adset, axis=1, result_type='expand'
                        )

                        # Remover linhas sem match
                        before_match = len(period_df_filtered)
                        period_df_filtered = period_df_filtered[period_df_filtered['adset_id'].notna()]
                        after_match = len(period_df_filtered)
                        if before_match > after_match:
                            logger.info(f"   ⚠️  {before_match - after_match} leads sem match campaign+adset (removidos)")

                        # Agrupar por adset_id (já é único por campanha)
                        grouped = period_df_filtered.groupby('adset_id').agg({
                            'lead_score': 'count',
                            'campaign_name': 'first',  # Pegar o nome da campanha
                            'decil': lambda x: (x == 'D10').sum() / len(x) * 100 if len(x) > 0 else 0,
                        }).rename(columns={'lead_score': 'leads', 'decil': 'pct_d10'})

                        # Calcular distribuição de decis
                        for adset_id in grouped.index:
                            value_df = period_df_filtered[period_df_filtered['adset_id'] == adset_id]
                            for i in range(1, 11):
                                decile_key = f'D{i}'
                                pct = (value_df['decil'] == decile_key).sum() / len(value_df) * 100 if len(value_df) > 0 else 0
                                grouped.at[adset_id, f'%{decile_key}'] = pct

                        # Resetar index e renomear
                        grouped = grouped.reset_index().rename(columns={'adset_id': 'value'})

                elif dimension == 'ad':
                    # Para ads, agrupar por nome e extrair campaign/adset das colunas Campaign/Medium
                    period_df_filtered = period_df_filtered.copy()

                    # Extrair campaign e adset names das colunas UTM
                    if 'Campaign' in period_df_filtered.columns and 'Medium' in period_df_filtered.columns:
                        # Campaign: extrair ID (formato "nome|ID")
                        period_df_filtered['campaign_id'] = period_df_filtered['Campaign'].apply(extract_id_from_utm)

                        # Medium: já contém NOME do adset (não ID), usar diretamente
                        period_df_filtered['adset_name_from_utm'] = period_df_filtered['Medium']

                        # Mapear campaign_id para nome
                        campaign_id_to_name = {
                            campaign_id: campaign_data['name']
                            for campaign_id, campaign_data in hierarchy['campaigns'].items()
                        }

                        def get_campaign_name(row):
                            """Obtém nome da campanha por ID, com fallback para nome do UTM"""
                            campaign_id = row['campaign_id']
                            if pd.notna(campaign_id):
                                # Tentar buscar na hierarquia primeiro
                                name = campaign_id_to_name.get(str(campaign_id))
                                if name:
                                    return name
                            # Fallback: extrair nome do UTM Campaign (remover data e ID)
                            campaign_utm = row.get('Campaign')
                            if pd.notna(campaign_utm):
                                import re
                                # Remover campaign ID do final (|números)
                                clean = re.sub(r'\|\d{18}$', '', str(campaign_utm))
                                # Remover data do final (| YYYY-MM-DD)
                                clean = re.sub(r'\|\s*\d{4}-\d{2}-\d{2}$', '', clean)
                                return clean.strip()
                            return None

                        period_df_filtered['campaign_name'] = period_df_filtered.apply(get_campaign_name, axis=1)

                        # adset_name inicial vem da coluna Medium
                        period_df_filtered['adset_name'] = period_df_filtered['adset_name_from_utm']

                        # CORREÇÃO: Detectar e corrigir UTMs genéricas usando hierarquia Meta
                        GENERIC_UTMS = {'paid', 'dgen', 'facebook', 'instagram', 'meta', 'fb', 'ig', 'cpc'}

                        def correct_generic_adset(row):
                            """Corrige adset_name genérico buscando na hierarquia Meta por nome do ad"""
                            try:
                                adset_name = row['adset_name'] if 'adset_name' in row else None
                                ad_name = row[utm_col] if utm_col in row else None

                                # Se adset_name não é genérico ou está vazio, retornar como está
                                if pd.isna(adset_name) or str(adset_name).lower() not in GENERIC_UTMS:
                                    return adset_name

                                # Se ad_name está vazio, não podemos corrigir
                                if pd.isna(ad_name) or str(ad_name).strip() == '':
                                    logger.debug(f"      ⚠️ Ad sem nome: adset_name='{adset_name}' (será filtrado)")
                                    return None  # Será filtrado

                                # Buscar ad_name na hierarquia para encontrar adset correto
                                ad_name_lower = str(ad_name).lower()
                                for campaign_id, campaign_data in hierarchy['campaigns'].items():
                                    if not isinstance(campaign_data, dict) or 'adsets' not in campaign_data:
                                        continue
                                    for adset_id, adset_data in campaign_data['adsets'].items():
                                        if not isinstance(adset_data, dict) or 'ads' not in adset_data:
                                            continue
                                        for ad_id, ad_data in adset_data['ads'].items():
                                            if not isinstance(ad_data, dict) or 'name' not in ad_data:
                                                continue
                                            # Match por nome (case insensitive)
                                            if ad_data['name'].lower() == ad_name_lower:
                                                logger.info(f"      ✓ Corrigido '{adset_name}' → '{adset_data.get('name', 'Unknown')}' (ad: {str(ad_name)[:40]}...)")
                                                return adset_data.get('name')

                                # Não encontrou na hierarquia, filtrar
                                logger.info(f"      🗑️ UTM genérica sem match: adset='{adset_name}', ad='{str(ad_name)[:40]}...'")
                                return None
                            except Exception as e:
                                logger.error(f"      ❌ Erro em correct_generic_adset: {str(e)}")
                                return row.get('adset_name') if hasattr(row, 'get') else None

                        # Aplicar correção
                        logger.info(f"   🔍 Verificando UTMs genéricas em {len(period_df_filtered)} ads...")
                        period_df_filtered['adset_name'] = period_df_filtered.apply(correct_generic_adset, axis=1)

                        # Filtrar ads com adset_name None (genéricos sem match)
                        before_filter = len(period_df_filtered)
                        period_df_filtered = period_df_filtered[period_df_filtered['adset_name'].notna()].copy()
                        after_filter = len(period_df_filtered)
                        if before_filter > after_filter:
                            removed = before_filter - after_filter
                            logger.info(f"   🗑️ Removidos {removed} ads com UTMs genéricas (sem match na hierarquia)")
                    else:
                        logger.warning(f"   ⚠️ Colunas Campaign ou Medium não encontradas para ads")
                        period_df_filtered['campaign_name'] = None
                        period_df_filtered['adset_name'] = None

                    # Agrupar por nome do ad (coluna Content)
                    grouped = period_df_filtered.groupby(utm_col).agg({
                        'lead_score': 'count',
                        'campaign_name': 'first',  # Pegar primeira ocorrência
                        'adset_name': 'first',
                        'decil': lambda x: (x == 'D10').sum() / len(x) * 100 if len(x) > 0 else 0,
                    }).rename(columns={'lead_score': 'leads', 'decil': 'pct_d10'})

                    # Calcular distribuição de decis
                    for value in grouped.index:
                        value_df = period_df_filtered[period_df_filtered[utm_col] == value]
                        for i in range(1, 11):
                            decile_key = f'D{i}'
                            pct = (value_df['decil'] == decile_key).sum() / len(value_df) * 100 if len(value_df) > 0 else 0
                            grouped.at[value, f'%{decile_key}'] = pct

                    # Resetar index e renomear
                    grouped = grouped.reset_index().rename(columns={utm_col: 'value'})

                else:
                    # Para outras dimensões, agrupar normalmente pelo UTM
                    grouped = period_df_filtered.groupby(utm_col).agg({
                        'lead_score': 'count',  # Número de leads
                        'decil': lambda x: (x == 'D10').sum() / len(x) * 100 if len(x) > 0 else 0,  # %D10
                    }).rename(columns={'lead_score': 'leads', 'decil': 'pct_d10'})

                    # Calcular distribuição de decis para cada valor
                    for value in grouped.index:
                        value_df = period_df_filtered[period_df_filtered[utm_col] == value]
                        for i in range(1, 11):
                            decile_key = f'D{i}'
                            pct = (value_df['decil'] == decile_key).sum() / len(value_df) * 100 if len(value_df) > 0 else 0
                            grouped.at[value, f'%{decile_key}'] = pct

                    grouped = grouped.reset_index().rename(columns={utm_col: 'value'})

                # Adicionar custos usando hierarquia (evita duplicação)
                grouped = enrich_utm_with_hierarchy(
                    utm_analysis_df=grouped,
                    hierarchy=hierarchy,
                    dimension=dimension
                )

                # FILTRO: Para Campaign, remover linhas com spend=0 (indicam Campaign IDs inválidos)
                if dimension == 'campaign':
                    before_filter = len(grouped)
                    grouped = grouped[grouped['spend'] > 0].copy()
                    after_filter = len(grouped)
                    if before_filter > after_filter:
                        removed = before_filter - after_filter
                        logger.info(f"   🗑️ Removidas {removed} campanhas com spend=0 (IDs inválidos)")

                    # Substituir Campaign ID pelo nome legível
                    id_to_name = {
                        campaign_id: campaign_data['name']
                        for campaign_id, campaign_data in hierarchy['campaigns'].items()
                    }

                    grouped['value'] = grouped['value'].apply(
                        lambda x: id_to_name.get(str(x), str(x))
                    )
                    logger.info(f"   ✏️ IDs substituídos por nomes de campanha para exibição")

                elif dimension == 'medium':
                    # Filtrar adsets com spend=0
                    before_filter = len(grouped)
                    grouped = grouped[grouped['spend'] > 0].copy()
                    after_filter = len(grouped)
                    if before_filter > after_filter:
                        removed = before_filter - after_filter
                        logger.info(f"   🗑️ Removidos {removed} adsets com spend=0 (IDs inválidos)")

                    # Substituir Adset ID pelo nome legível
                    id_to_info = {}
                    for campaign_id, campaign_data in hierarchy['campaigns'].items():
                        for adset_id, adset_data in campaign_data['adsets'].items():
                            id_to_info[adset_id] = adset_data['name']

                    grouped['value'] = grouped['value'].apply(
                        lambda x: id_to_info.get(str(x), str(x))
                    )
                    logger.info(f"   ✏️ IDs substituídos por nomes de adset para exibição")

                elif dimension == 'ad':
                    # Filtrar ads com spend=0
                    before_filter = len(grouped)
                    grouped = grouped[grouped['spend'] > 0].copy()
                    after_filter = len(grouped)
                    if before_filter > after_filter:
                        removed = before_filter - after_filter
                        logger.info(f"   🗑️ Removidos {removed} ads com spend=0")

                    # Para ads, 'value' já é o nome (não ID), então não precisa substituir
                    logger.info(f"   ✅ {len(grouped)} ads com custo > 0")

                # Enriquecer com métricas econômicas
                # Para campaigns e adsets (medium), usar budget info para condicionar ação
                if dimension == 'campaign':
                    budget_control_col = 'has_campaign_budget'
                elif dimension == 'medium':
                    budget_control_col = 'has_adset_budget'
                else:
                    budget_control_col = None

                enriched = enrich_utm_with_economic_metrics(
                    utm_df=grouped,
                    product_value=product_value,
                    min_roas=min_roas,
                    conversion_rates=conversion_rates,
                    dimension=dimension,
                    budget_control_col=budget_control_col,
                    period_days=period_days
                )

                # Tratar NaN em métricas calculadas (podem surgir de divisões por zero)
                enriched = enriched.fillna({
                    'leads': 0,
                    'spend': 0.0,
                    'cpl': 0.0,
                    'taxa_proj': 0.0,
                    'receita_proj': 0.0,
                    'margem_contrib': 0.0,
                    'roas_proj': 0.0,
                    'acao': ''
                })

                # Converter para lista de dicts
                metrics_list = []
                for _, row in enriched.iterrows():
                    # Para adsets, incluir campaign_name
                    # Para ads, incluir campaign_name e adset_name
                    campaign_value = None
                    adset_value = None

                    if dimension == 'medium':
                        campaign_value = row.get('campaign_name')
                    elif dimension == 'ad':
                        campaign_value = row.get('campaign_name')
                        adset_value = row.get('adset_name')

                    metrics_list.append(UTMDimensionMetrics(
                        campaign=campaign_value,
                        adset=adset_value,
                        value=str(row['value']) if pd.notna(row['value']) else '(vazio)',
                        leads=int(row['leads']),
                        spend=float(row['spend']),
                        cpl=float(row['cpl']),
                        taxa_proj=float(row['taxa_proj']),
                        receita_proj=float(row['receita_proj']),
                        margem_contrib=float(row['margem_contrib']),
                        roas_proj=float(row['roas_proj']),
                        acao=row['acao'],
                        budget_current=float(row.get('budget_current', 0.0)),
                        budget_target=float(row.get('budget_target', 0.0))
                    ))

                period_analysis[dimension] = metrics_list

            # Adicionar metadados do período
            period_analysis['period_start'] = period_start
            period_analysis['period_end'] = period_end
            period_analysis['total_leads'] = total_leads
            period_analysis['meta_leads'] = meta_leads
            period_analysis['google_leads'] = google_leads

            periods_analysis[period_key] = UTMPeriodAnalysis(**period_analysis)

        processing_time = time.time() - start_time

        logger.info(f"✅ Análise concluída em {processing_time:.2f}s")

        return UTMAnalysisResponse(
            request_id=request_id,
            periods=periods_analysis,
            config={
                'product_value': product_value,
                'min_roas': min_roas
            },
            processing_time_seconds=round(processing_time, 2),
            timestamp=datetime.now().isoformat()
        )

    except Exception as e:
        import traceback
        logger.error(f"❌ Erro na análise UTM: {str(e)}")
        logger.error(f"Traceback completo:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Erro na análise: {str(e)}")
    finally:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)

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

@app.get("/monitoring/daily-check", response_model=DailyCheckResponse)
async def daily_monitoring_check_auto(
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Executa check diário de monitoramento com dados do Google Sheets.

    Busca automaticamente leads das últimas N horas e executa todos os checks:
    - Data Quality: category drift, distribution drift, missing rate, score distribution
    - Operational: 6h sem leads, 6h sem CAPI
    - CAPI Quality: missing rate fbp/fbc

    Args:
        hours: Número de horas para buscar (padrão: 24)
        db: Sessão PostgreSQL (injetada automaticamente)

    Returns:
        Alertas consolidados por severidade e categoria
    """
    from src.monitoring.orchestrator import MonitoringOrchestrator
    import yaml

    start_time = time.time()

    try:
        # Buscar dados do Google Sheets
        leads_data = fetch_leads_from_sheets(hours=hours)

        logger.info(f"🔍 Executando check diário de monitoramento ({len(leads_data)} leads)")

        # Obter model_path do modelo ativo
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'configs/active_model.yaml'
        )

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            model_path = config['active_model']['model_path']

        # Garantir path absoluto
        if not os.path.isabs(model_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, model_path)

        logger.info(f"📂 Usando modelo: {model_path}")

        # Inicializar orquestrador
        orchestrator = MonitoringOrchestrator(model_path=model_path, db=db)

        # Executar checks
        result = orchestrator.run_daily_check(leads_data)

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
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erro no monitoramento: {str(e)}")


@app.get("/monitoring/daily-check/railway", response_model=DailyCheckResponse)
async def daily_monitoring_check_railway(
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Executa check diário de monitoramento com dados do Railway PostgreSQL.

    Mesmo pipeline do /monitoring/daily-check (Sheets), mas usando os leads
    do Railway como fonte. Fluxo:
    1. Busca leads das últimas N horas no Railway (com leadScore preenchido)
    2. Converte cada lead via railway_mapping.railway_lead_to_sheets_row()
    3. Chama orchestrator.run_daily_check() — mesmo pipeline de monitoramento

    Args:
        hours: Número de horas para buscar (padrão: 24)
        db: Sessão PostgreSQL Cloud SQL (para checks operacionais CAPI)
    """
    import pg8000.native
    import json as _json
    import yaml
    from src.monitoring.orchestrator import MonitoringOrchestrator
    from api.railway_mapping import railway_lead_to_sheets_row

    start_time = time.time()

    try:
        # 1. Buscar leads do Railway das últimas N horas
        railway_conn = pg8000.native.Connection(
            host=os.environ['RAILWAY_DB_HOST'],
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
        )

        rows = railway_conn.run(
            'SELECT id, data, "nomeCompleto", email, telefone, pesquisa, '
            'source, medium, campaign, content, term, '
            '"remoteIp", "userAgent", fbc, fbp, "pageUrl", '
            '"leadScore", decil '
            'FROM "Lead" '
            'WHERE "leadScore" IS NOT NULL '
            'AND "createdAt" >= NOW() - :intervalo * INTERVAL \'1 hour\' '
            'ORDER BY "createdAt" DESC',
            intervalo=hours
        )
        railway_conn.close()

        if not rows:
            logger.info(f"⚠️ Railway: nenhum lead com score nas últimas {hours}h")
            return DailyCheckResponse(
                total_alerts=0,
                alerts_by_severity={"HIGH": 0, "MEDIUM": 0, "LOW": 0},
                alerts_by_category={},
                alerts=[],
                critical_summary=f"Nenhum lead Railway nas últimas {hours}h.",
                timestamp=datetime.now().isoformat()
            )

        logger.info(f"🔍 Railway monitoring: {len(rows)} leads das últimas {hours}h")

        # 2. Converter para formato Sheets via railway_mapping
        col_names = [
            'id', 'data', 'nomeCompleto', 'email', 'telefone', 'pesquisa',
            'source', 'medium', 'campaign', 'content', 'term',
            'remoteIp', 'userAgent', 'fbc', 'fbp', 'pageUrl',
            'leadScore', 'decil',
        ]

        leads_data = []
        for row in rows:
            lead = dict(zip(col_names, row))

            if isinstance(lead.get('pesquisa'), str):
                try:
                    lead['pesquisa'] = _json.loads(lead['pesquisa'])
                except Exception:
                    lead['pesquisa'] = {}
            elif lead.get('pesquisa') is None:
                lead['pesquisa'] = {}

            try:
                sheets_row = railway_lead_to_sheets_row(lead)
                # Adicionar lead_score e decil no formato esperado pelo orquestrador
                sheets_row['lead_score'] = float(lead['leadScore']) if lead.get('leadScore') else None
                sheets_row['decil']      = f"D{int(lead['decil']):02d}" if lead.get('decil') else None
                leads_data.append(sheets_row)
            except Exception as e:
                logger.warning(f"⚠️ Erro ao mapear lead {lead.get('email')}: {e}")

        logger.info(f"✅ {len(leads_data)} leads convertidos para formato Sheets")

        # 3. Carregar model_path
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'configs/active_model.yaml'
        )
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            model_path = config['active_model']['model_path']

        if not os.path.isabs(model_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, model_path)

        # 4. Executar pipeline de monitoramento
        orchestrator = MonitoringOrchestrator(model_path=model_path, db=db)
        result = orchestrator.run_daily_check(leads_data)

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
            'configs/active_model.yaml'
        )

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            model_path = config['active_model']['model_path']

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
        bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET', 'smart-ads-validation-reports')

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
        bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET', 'smart-ads-validation-reports')

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
async def railway_process_pending():
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
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline não inicializado")

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
        )

        # 2. Buscar leads sem score (máximo 50 por execução)
        rows = railway_conn.run(
            'SELECT id, data, "nomeCompleto", email, telefone, pesquisa, '
            'source, medium, campaign, content, term, '
            '"remoteIp", "userAgent", fbc, fbp, "pageUrl" '
            'FROM "Lead" WHERE "leadScore" IS NULL '
            'ORDER BY "createdAt" ASC LIMIT 50'
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
            lead_dicts.append(lead)

        # 4. Converter para formato Google Sheets via railway_mapping
        sheets_rows = []
        valid_leads = []
        for lead in lead_dicts:
            try:
                sheets_row = railway_lead_to_sheets_row(lead)
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

        # 5. Rodar pipeline ML em batch
        leads_df = pd.DataFrame(sheets_rows)
        temp_file = None
        result_df = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
                leads_df.to_csv(tmp, index=False)
                temp_file = tmp.name

            logger.info(f"   Executando pipeline para {len(sheets_rows)} leads Railway...")
            result_df = pipeline.run(temp_file, with_predictions=True)
        finally:
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)

        if result_df is None or len(result_df) == 0:
            raise HTTPException(status_code=500, detail="Pipeline retornou resultado vazio")

        # 6. Obter thresholds do modelo
        thresholds = pipeline.predictor.metadata.get('decil_thresholds', {}).get('thresholds', {})
        if not thresholds:
            logger.warning("⚠️ Thresholds não encontrados, usando D05 como padrão")

        # 7. Atualizar Railway + preparar payload CAPI
        processed = 0
        skipped = 0
        capi_leads = []

        for i, lead in enumerate(valid_leads):
            try:
                lead_score_value = float(result_df['lead_score'].iloc[i])

                if thresholds:
                    decil_str = atribuir_decil_por_threshold(lead_score_value, thresholds)
                else:
                    decil_str = "D05"

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

                # Preparar evento CAPI
                nome = (lead.get('nomeCompleto') or '').strip()
                parts = nome.split(' ', 1)
                capi_leads.append({
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
                })

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
            capi_result = send_batch_events(capi_leads, db=None)
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

        logger.info(
            f"✅ Railway polling concluído: {processed} processados, "
            f"{skipped} erros, {capi_result.get('success', 0)} CAPI enviados"
        )

        return {
            "processed":   processed,
            "skipped":     skipped,
            "capi_sent":   capi_result.get('success', 0),
            "capi_errors": capi_result.get('errors', 0),
            "timestamp":   datetime.now().isoformat(),
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

    # Inicializar pipeline antes de iniciar o servidor
    print("Inicializando pipeline...")
    if initialize_pipeline():
        print("Pipeline inicializado com sucesso!")
    else:
        print("AVISO: Pipeline não foi inicializado. Será inicializado na primeira requisição.")

    # Iniciar o servidor
    print("Iniciando servidor na porta 8080...")
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)