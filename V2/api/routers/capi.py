"""Envio de eventos para a Meta (CAPI): lote diário, conferência e compras.

Gerado a partir do app.py monolítico (corte por domínio, corpo dos handlers intacto)."""
import os
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Annotated, List, Dict, Any, Optional
import time
import uuid
from api.database import get_db, init_database, create_lead_capi, count_leads, count_leads_with_fbp, count_leads_with_fbc, get_leads_by_emails, LeadCAPI
from api.capi_integration import send_batch_events, should_send_to_destination
from fastapi import Depends, Header, Request
from api.auth import exigir_token, exigir_token_interno
from sqlalchemy.orm import Session
from fastapi import APIRouter
import logging
from api.state import PipelineDep, PipelineOptDep

logger = logging.getLogger(__name__)
router = APIRouter()


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
    dry_run: bool = Field(default=False, description="Se True: roda routing A/B + cálculo de value sem chamar Meta nem escrever em DB. Usado por Gate C de equivalência de revisões.")


class CapiCheckSentRequest(BaseModel):
    """Request para verificar quais leads já foram enviados"""
    emails: List[str] = Field(..., description="Lista de emails para verificar")


@router.post("/capi/process_daily_batch")
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
                'survey_data': survey_data,
                # Internos para filtro de allowlist/blocklist (DT-CAPI-01/02). Removidos
                # antes do payload Meta em send_batch_events.
                '_utm_source': lead.get('utm_source') or (capi_data.utm_source if capi_data else None),
                '_utm_campaign': lead.get('utm_campaign') or (capi_data.utm_campaign if capi_data else None),
            }

            # A/B routing: identificar variante pelos UTMs ou URL do lead.
            # Espelha a lógica de /webhook/lead_capture (linha 920) e /railway/process-pending
            # (linha 3395+) pra que /capi/process_daily_batch também respeite o A/B test —
            # antes dessa adição, leads enviados por esse endpoint ignoravam routing e
            # caíam sempre no fallback business_config.conversion_rates.
            ab_test_cfg = getattr(pipeline, '_ab_test_config', None)
            if ab_test_cfg and getattr(ab_test_cfg, 'enabled', False):
                lead_utms = {
                    'utm_source':   lead.get('utm_source') or (capi_data.utm_source if capi_data else None),
                    'utm_medium':   lead.get('utm_medium') or (capi_data.utm_medium if capi_data else None),
                    'utm_campaign': lead.get('utm_campaign') or (capi_data.utm_campaign if capi_data else None),
                    'utm_term':     lead.get('utm_term') or (capi_data.utm_term if capi_data else None),
                    'utm_content':  lead.get('utm_content') or (capi_data.utm_content if capi_data else None),
                }
                ev_url = lead.get('event_source_url') or (capi_data.event_source_url if capi_data else None)
                ab_variant = pipeline.get_ab_variant(lead_utms, event_source_url=ev_url)
                if ab_variant:
                    lead_capi['ab_event_name'] = ab_variant.capi_event_name
                    lead_capi['ab_event_name_hq'] = ab_variant.capi_event_name_high_quality
                    lead_capi['ab_conversion_rates'] = ab_variant.conversion_rates
                    lead_capi['ab_pixel_id'] = ab_variant.pixel_id_override
                    lead_capi['ab_high_quality_decils'] = ab_variant.capi_high_quality_decils
                    lead_capi['ab_secondary_hq_events'] = ab_variant.capi_secondary_hq_events

            enriched_leads.append(lead_capi)

        logger.info(f"   {len(enriched_leads)} leads enriquecidos para envio CAPI")

        # UTM filter: blocklist por campaign + allowlist por source (DT-CAPI-01/02)
        allowed_leads = []
        skipped_by_reason = {}
        for el in enriched_leads:
            _allowed, _reason = should_send_to_destination(
                {'source': el.get('_utm_source'), 'campaign': el.get('_utm_campaign')},
                pipeline._client_config.capi,
                destination='meta',
            )
            if _allowed:
                allowed_leads.append(el)
            else:
                skipped_by_reason[_reason] = skipped_by_reason.get(_reason, 0) + 1
        if skipped_by_reason:
            logger.info(f"   ⏭️ CAPI batch — {sum(skipped_by_reason.values())} leads ignorados: {skipped_by_reason}")

        # Logging de qualidade dos dados (apenas leads que serão enviados)
        leads_with_fbp = len([l for l in allowed_leads if l.get('fbp')])
        leads_with_fbc = len([l for l in allowed_leads if l.get('fbc')])
        leads_with_both = len([l for l in allowed_leads if l.get('fbp') and l.get('fbc')])

        logger.info(f"   📊 Qualidade dos dados CAPI ({len(allowed_leads)} a enviar):")
        if allowed_leads:
            logger.info(f"      - Com FBP: {leads_with_fbp}/{len(allowed_leads)} ({leads_with_fbp/len(allowed_leads)*100:.1f}%)")
            logger.info(f"      - Com FBC: {leads_with_fbc}/{len(allowed_leads)} ({leads_with_fbc/len(allowed_leads)*100:.1f}%)")
            logger.info(f"      - Com AMBOS: {leads_with_both}/{len(allowed_leads)} ({leads_with_both/len(allowed_leads)*100:.1f}%)")

        # Enviar batch (com db session para registrar envios; em dry_run não escreve em DB nem chama Meta)
        results = send_batch_events(allowed_leads, db=db, capi_config=pipeline._client_config.capi,
                                    business_config=pipeline._client_config.business,
                                    client_id=pipeline._client_config.client_id,
                                    dry_run=request.dry_run)

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


@router.post("/capi/check_sent", dependencies=[Depends(exigir_token_interno())])
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
        logger.error(f"❌ Erro ao verificar logs CAPI: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao verificar logs: {str(e)}")


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


@router.post("/capi/send_purchase_events", dependencies=[Depends(exigir_token_interno())])
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
