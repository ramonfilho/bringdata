"""Webhooks de captação (lead_capture, update_survey, SendFlow) e HotLeads.

Gerado a partir do app.py monolítico (corte por domínio, corpo dos handlers intacto)."""
import os
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Annotated, List, Dict, Any, Optional
import time
import tempfile
from datetime import datetime
from api.database import get_db, init_database, create_lead_capi, count_leads, count_leads_with_fbp, count_leads_with_fbc, get_leads_by_emails, LeadCAPI
from api.capi_integration import send_batch_events, should_send_to_destination
from fastapi import Depends, Header, Request
from api.auth import exigir_token, exigir_token_interno
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.model.decil_thresholds import atribuir_decil_por_threshold
from fastapi import APIRouter
import logging
from api.state import PipelineDep, PipelineOptDep

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.post("/webhook/lead_capture")
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

        # O scoring legado que vivia aqui (bloco `if False:`) foi removido em 14/09/2026:
        # chamava `create_derived_features`/`apply_categorical_encoding`, nomes que não
        # existem mais no projeto, e nunca executava. Histórico no git.

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


@router.post("/webhook/update_survey", dependencies=[Depends(exigir_token_interno())])
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

            # A/B test routing: identificar variante pelos UTMs ou URL do lead
            lead_utms = {
                'utm_source': existing_lead.utm_source,
                'utm_medium': existing_lead.utm_medium,
                'utm_campaign': existing_lead.utm_campaign,
                'utm_term': existing_lead.utm_term,
                'utm_content': existing_lead.utm_content,
            }
            ab_variant = pipeline.get_ab_variant(lead_utms, event_source_url=existing_lead.event_source_url)
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
                lead_capi_dict['ab_pixel_id'] = ab_variant.pixel_id_override
                lead_capi_dict['ab_high_quality_decils'] = ab_variant.capi_high_quality_decils
                lead_capi_dict['ab_secondary_hq_events'] = ab_variant.capi_secondary_hq_events

            # UTM filter: blocklist por campaign + allowlist por source (DT-CAPI-01/02)
            _allowed, _reason = should_send_to_destination(
                {'source': existing_lead.utm_source, 'campaign': existing_lead.utm_campaign},
                pipeline._client_config.capi,
                destination='meta',
            )
            if not _allowed:
                logger.info(f"⏭️ CAPI {_reason}: source={existing_lead.utm_source} campaign={existing_lead.utm_campaign}")
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


@router.post("/webhook/sendflow_group_join",
          dependencies=[Depends(exigir_token("SENDFLOW_SENDTOK", header="sendtok"))])
async def webhook_sendflow_group_join(request: Request):
    """
    Recebe o Sendhook do SendFlow (membro adicionado ao grupo de WhatsApp) e grava a
    entrada em whatsapp_group_joins (feature "entrou no grupo"). Valida o header `sendtok`.
    Lógica de tradução/persistência em api/sendflow_receiver (anti-corrupção + idempotente).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="payload inválido (JSON esperado)")
    from api.sendflow_receiver import parse_sendhook, store_group_joins
    rows = parse_sendhook(body)
    inserted = store_group_joins(rows)
    logger.info(f"[sendhook] evento={body.get('event')} | entradas={len(rows)} | inseridas={inserted}")
    return {"status": "ok", "received": len(rows), "inserted": inserted}


def _hotleads_webhook_url() -> str:
    """URL pública deste serviço que a Hotmart vai chamar de volta, com o token.
    `HOTLEADS_PUBLIC_URL` permite apontar pra outra revisão em teste."""
    import os as _os
    base = (_os.environ.get('HOTLEADS_PUBLIC_URL')
            or _os.environ.get('SERVICE_PUBLIC_URL') or '').rstrip('/')
    token = _os.environ.get('HOTLEADS_WEBHOOK_TOKEN', '')
    return f"{base}/hotleads/webhook?token={token}"


@router.post("/hotleads/submit-batch",
          dependencies=[Depends(exigir_token("HOTLEADS_CRON_TOKEN",
                                             header="x-hotleads-token",
                                             aceita_query=True))])
async def hotleads_submit_batch(
    request: Request,
    pipeline: PipelineDep,
    limit: Optional[int] = None,
    dry_run: bool = False,
):
    """Submete leads recentes sem selo ao batch_enrich da Hotmart (sem pixel).
    Idempotente por construção: só pega quem está com `hotleads_status` NULL ou
    'submitted' vencido, então rodar duas vezes seguidas não duplica."""
    cfg = pipeline._client_config
    if not cfg.hotleads.enabled:
        return {"status": "disabled", "submitted": 0}

    webhook_url = _hotleads_webhook_url()
    if not dry_run and not webhook_url.startswith('http'):
        raise HTTPException(
            status_code=500,
            detail="HOTLEADS_PUBLIC_URL/SERVICE_PUBLIC_URL não configurada — "
                   "sem URL de retorno o selo nunca voltaria"
        )

    from api.hotleads_integration import run_retry_failed, run_submit_batch
    from src.data.ledger_connection import open_cloudsql_ledger_connection
    conn = open_cloudsql_ledger_connection()
    try:
        # Antes de puxar leads novos, destrava os quentes cujo evento falhou —
        # o selo deles já está pago, só o envio ao Meta ficou pendente. Sem isso
        # eles ficariam órfãos (nenhum outro caminho os pega de volta).
        #
        # A repesca é CONTIDA: falha nela não pode derrubar a submissão, que é o
        # trabalho principal desta rota. Em 11-12/08/2026 o oposto aconteceu 23
        # vezes em 24h — a query da repesca estourava o timeout de 30s (Seq Scan
        # de 220 MB, resolvido depois com índice parcial) e a request inteira
        # morria em 500, então os leads NOVOS não eram submetidos naquela rodada.
        # A causa daquele timeout já foi corrigida, mas o acoplamento não: qualquer
        # falha futura aqui (Hotmart fora, soluço de rede, bug novo) voltaria a
        # custar a submissão.
        #
        # É o mesmo princípio que `run_process_webhook` já aplica um nível abaixo
        # ("falha de um lead não derruba o lote"), agora no nível do passo. Conter
        # NÃO é engolir: o erro é logado em ERROR e volta no payload, em `retry`.
        try:
            retry = run_retry_failed(conn, cfg, dry_run=dry_run)
        except Exception as e:
            logger.error(
                f"[hotleads] repesca falhou ({type(e).__name__}: {e}) — "
                f"submissão segue normalmente; os quentes em 'error' ficam para "
                f"a próxima rodada (15min)"
            )
            retry = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
        result = run_submit_batch(conn, cfg, webhook_url=webhook_url,
                                  limit=limit, dry_run=dry_run)
        return {**result, "retry": retry}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.post("/hotleads/webhook",
          dependencies=[Depends(exigir_token("HOTLEADS_WEBHOOK_TOKEN",
                                             aceita_query=True))])
async def hotleads_webhook(request: Request, pipeline: PipelineDep,
                           token: Optional[str] = None, dry_run: bool = False):
    """Recebe o selo (quente/frio) por lead e dispara o evento dos quentes.

    Responde 200 mesmo com falhas parciais: a Hotmart não reentrega, então
    devolver erro só jogaria fora os selos que deram certo. O que falhou fica
    registrado em `hotleads_error` no ledger.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="payload inválido (JSON esperado)")

    from api.hotleads_integration import run_process_webhook
    from src.data.ledger_connection import open_cloudsql_ledger_connection
    conn = open_cloudsql_ledger_connection()
    try:
        return run_process_webhook(conn, pipeline._client_config, body,
                                   dry_run=dry_run)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/webhook/lead_capture/stats", dependencies=[Depends(exigir_token_interno())])
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


@router.get("/webhook/lead_capture/recent", dependencies=[Depends(exigir_token_interno())])
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


@router.post("/webhook/lead_capture/by_emails", dependencies=[Depends(exigir_token_interno())])
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
