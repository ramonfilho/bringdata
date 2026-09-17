"""Rotas de scoring: raiz, health, info do modelo, predição em lote/CSV, decis e explicação.

Gerado a partir do app.py monolítico (corte por domínio, corpo dos handlers intacto)."""
import os
from pathlib import Path
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Annotated, List, Dict, Any, Optional
import time
import tempfile
import uuid
from datetime import datetime
from fastapi import Depends, Header, Request
from api.auth import exigir_token, exigir_token_interno
from fastapi import APIRouter
import logging
from api.state import PipelineDep, pipelines

# Raiz do V2 (onde vivem configs/, src/, vendas/, files/). Este arquivo está em
# api/routers/, dois níveis abaixo; `Path(__file__).parent.parent` apontaria para api/.
# Foi o que quebrou o daily-check na revisão 01179-jux (17/09/2026): 500 por
# 'api/configs/active_models/devclub.yaml' não existir.
_RAIZ = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.get("/")
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


@router.get("/health")
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


@router.get("/model/info", dependencies=[Depends(exigir_token_interno())])
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
            mapping_file = _RAIZ / "arquivos_modelo" / f"feature_name_mapping_{model_name}.json"
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


@router.post("/predict/batch", response_model=BatchPredictionResponse)
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
        # [Correção 3] /predict/batch é caminho de scoring / equivalência de
        # deploy (NÃO envia ao Meta) → o validador de conservação observa mas
        # não bloqueia a comparação entre revisões. Produção (polling) usa o
        # default True e continua bloqueando.
        result_df = pipeline.run(temp_file, with_predictions=True, enforce_post_encoding=False)

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


@router.post("/predict/csv", dependencies=[Depends(exigir_token_interno())])
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
        # [Correção 3] /predict/batch (CSV) — caminho de equivalência, não
        # envia ao Meta: validador observa, não bloqueia. Produção = default.
        result_df = pipeline.run(temp_file, with_predictions=True, enforce_post_encoding=False)

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


@router.post("/calculate_decils", response_model=DecilCalculationResponse,
          dependencies=[Depends(exigir_token_interno())])
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


class ExplainRequest(BaseModel):
    event_id: str = Field(..., description="event_id do lead em registros_ml (UUID v7) ou 'legacy-{id}' pra Lead antiga")
    source: str = Field('registros_ml', description="Fonte do lead: 'registros_ml' (default) ou 'legacy'")


@router.post("/predict/explain", dependencies=[Depends(exigir_token_interno())])
async def predict_explain(request: ExplainRequest, pipeline: PipelineDep):
    """Re-scoreia 1 lead já persistido e devolve todo o caminho de scoring.

    Útil pra auditoria de integridade do pipeline lead→score:
      - paridade: o `lead_score` recalculado deve bater com o `lead_score`
        persistido (mesma versão de código + mesmo payload → mesmo resultado).
      - inspeção: o vetor encodado (52 colunas) revela features canônicas
        zeradas quando o payload tinha o dado correspondente (cenário
        clássico de divergência de nomenclatura).

    Não envia CAPI, não persiste nada, não muta estado.
    """
    import pg8000.native

    from src.data import compose_repository
    from src.data.ledger_connection import open_ledger_read_connection
    from src.scoring.service import payload_from_record, score_lead_from_payload

    railway_conn = None
    try:
        if request.source == 'registros_ml':
            # Ledger: respeita LEDGER_READ_SOURCE (railway|cloudsql).
            railway_conn = open_ledger_read_connection()
        else:
            # 'legacy' lê a tabela `Lead`, que só existe no Railway do cliente.
            railway_conn = pg8000.native.Connection(
                host=os.environ['RAILWAY_DB_HOST'],
                port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
                database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
                user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
                password=os.environ['RAILWAY_DB_PASSWORD'],
                timeout=30,
            )
        repo = compose_repository(request.source, railway_conn=railway_conn)
        record = repo.get_by_event_id(request.event_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"event_id '{request.event_id}' não encontrado em {request.source!r}",
            )

        payload = payload_from_record(record)

        try:
            explanation = score_lead_from_payload(payload, pipeline)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"slug inválido no payload: {e}")

        return {
            "event_id": record.event_id,
            "source": request.source,
            "payload_reconstruido": payload,
            "payload_normalizado": explanation.payload_normalizado,
            "dataframe_row": explanation.dataframe_row,
            "encoded_features": explanation.encoded_features,
            "prediction_recalculada": {
                "lead_score": explanation.lead_score,
                "decil": explanation.decil,
                "variant": explanation.variant,
            },
            "prediction_persistida": {
                "lead_score": record.score,
                "decil": record.decil,
                "variant": record.variant,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[/predict/explain] falhou")
        raise HTTPException(status_code=500, detail=f"explain falhou: {type(e).__name__}: {e}")
    finally:
        if railway_conn is not None:
            try:
                railway_conn.close()
            except Exception:
                pass
