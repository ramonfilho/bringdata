"""
Meta Conversions API (CAPI) Integration
Envio de eventos server-side para melhorar atribuição
"""

import os
import time
import hashlib
import logging
from typing import Dict, List, Optional
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.serverside.event import Event
from facebook_business.adobjects.serverside.event_request import EventRequest
from facebook_business.adobjects.serverside.user_data import UserData
from facebook_business.adobjects.serverside.custom_data import CustomData
from facebook_business.adobjects.serverside.action_source import ActionSource
from facebook_business.adobjects.serverside.gender import Gender
from src.core.client_config import CAPIConfig, BusinessConfig

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

ACCESS_TOKEN = os.getenv('META_ACCESS_TOKEN')  # Obrigatório via env var

# =============================================================================
# MAPEAMENTO DDD → ESTADO (Brasil)
# =============================================================================

DDD_TO_STATE = {
    # São Paulo
    '11': 'SP', '12': 'SP', '13': 'SP', '14': 'SP', '15': 'SP', '16': 'SP', '17': 'SP', '18': 'SP', '19': 'SP',
    # Rio de Janeiro
    '21': 'RJ', '22': 'RJ', '24': 'RJ',
    # Espírito Santo
    '27': 'ES', '28': 'ES',
    # Minas Gerais
    '31': 'MG', '32': 'MG', '33': 'MG', '34': 'MG', '35': 'MG', '37': 'MG', '38': 'MG',
    # Paraná
    '41': 'PR', '42': 'PR', '43': 'PR', '44': 'PR', '45': 'PR', '46': 'PR',
    # Santa Catarina
    '47': 'SC', '48': 'SC', '49': 'SC',
    # Rio Grande do Sul
    '51': 'RS', '53': 'RS', '54': 'RS', '55': 'RS',
    # Distrito Federal
    '61': 'DF',
    # Goiás
    '62': 'GO', '64': 'GO',
    # Tocantins
    '63': 'TO',
    # Mato Grosso
    '65': 'MT', '66': 'MT',
    # Mato Grosso do Sul
    '67': 'MS',
    # Acre
    '68': 'AC',
    # Rondônia
    '69': 'RO',
    # Bahia
    '71': 'BA', '73': 'BA', '74': 'BA', '75': 'BA', '77': 'BA',
    # Sergipe
    '79': 'SE',
    # Pernambuco
    '81': 'PE', '87': 'PE',
    # Alagoas
    '82': 'AL',
    # Paraíba
    '83': 'PB',
    # Rio Grande do Norte
    '84': 'RN',
    # Ceará
    '85': 'CE', '88': 'CE',
    # Piauí
    '86': 'PI', '89': 'PI',
    # Maranhão
    '98': 'MA', '99': 'MA',
    # Pará
    '91': 'PA', '93': 'PA', '94': 'PA',
    # Amazonas
    '92': 'AM', '97': 'AM',
    # Roraima
    '95': 'RR',
    # Amapá
    '96': 'AP',
}

def get_state_from_phone(phone: str) -> Optional[str]:
    """
    Extrai o estado brasileiro a partir do DDD do telefone

    Args:
        phone: Telefone (pode ter +55, espaços, etc)

    Returns:
        Sigla do estado (SP, RJ, etc) ou None se não encontrar
    """
    if not phone:
        return None

    # Garantir que phone é string (Apps Script pode enviar como int)
    phone_str = str(phone)

    # Remove tudo que não é número
    digits = ''.join(filter(str.isdigit, phone_str))

    # Se começar com 55 (código Brasil), remove
    if digits.startswith('55') and len(digits) > 10:
        digits = digits[2:]

    # O DDD são os 2 primeiros dígitos
    if len(digits) >= 2:
        ddd = digits[:2]
        return DDD_TO_STATE.get(ddd)

    return None

def normalize_gender(gender_str) -> Optional[Gender]:
    """
    Normaliza o gênero para o formato Meta CAPI (enum Gender)

    Args:
        gender_str: Resposta do formulário ("Masculino", "Feminino", etc)

    Returns:
        Gender.MALE para masculino, Gender.FEMALE para feminino, None para outros
    """
    if not gender_str:
        return None

    # Converter para string e validar
    try:
        gender_lower = str(gender_str).lower().strip()

        # Ignorar valores numéricos ou muito curtos/longos
        if gender_lower.isdigit() or len(gender_lower) < 1 or len(gender_lower) > 20:
            return None

        if gender_lower in ['masculino', 'homem', 'male', 'm']:
            return Gender.MALE
        elif gender_lower in ['feminino', 'mulher', 'female', 'f']:
            return Gender.FEMALE
    except Exception:
        pass

    return None

# Inicializar API do Facebook (se token disponível)
if ACCESS_TOKEN:
    FacebookAdsApi.init(access_token=ACCESS_TOKEN)

def hash_data(data) -> Optional[str]:
    """
    Hash SHA256 de dados pessoais (formato Meta CAPI)
    Remove espaços, lowercase, depois hash
    """
    if data is None or data == '':
        return None
    try:
        normalized = str(data).lower().strip()
        if not normalized:
            return None
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    except Exception:
        return None

# =============================================================================
# ENVIO DE EVENTOS
# =============================================================================

def parse_meta_capi_response(response) -> Dict:
    """
    Parseia a resposta da Meta CAPI para extrair estatísticas de eventos

    Resposta da Meta tem formato:
    {
        "events_received": 1,  # Eventos que a Meta confirmou receber
        "messages": [],        # Erros/warnings se houver
        "fbtrace_id": "..."    # ID de trace para debug
    }

    Returns:
        {
            "status": "success" | "error" | "partial",
            "events_received": int,
            "events_rejected": int,
            "error_message": str | None
        }
    """
    result = {
        "status": "success",
        "events_received": 0,
        "events_rejected": 0,
        "error_message": None
    }

    try:
        # A resposta pode ser um dict ou objeto com atributos
        if isinstance(response, dict):
            response_data = response
        elif hasattr(response, '__dict__'):
            response_data = response.__dict__
        elif hasattr(response, 'export_value'):
            response_data = response.export_value()
        else:
            response_data = {"raw": str(response)}

        # Extrair events_received (eventos aceitos pela Meta)
        events_received = response_data.get('events_received', 0)
        result['events_received'] = int(events_received) if events_received else 0

        # Extrair mensagens de erro
        messages = response_data.get('messages', [])

        # Se houve erros, marcar como error ou partial
        if messages:
            error_messages = [msg for msg in messages if isinstance(msg, str)]
            result['error_message'] = '; '.join(error_messages) if error_messages else str(messages)

            # Se recebeu alguns eventos mas teve erros = partial
            if result['events_received'] > 0:
                result['status'] = 'partial'
                # Assumir 1 evento rejeitado se teve erro (não sabemos exatamente quantos)
                result['events_rejected'] = 1
            else:
                result['status'] = 'error'
                result['events_rejected'] = 1

        logger.debug(f"📊 Meta CAPI response parsed: {result}")

    except Exception as e:
        logger.warning(f"⚠️  Erro ao parsear resposta Meta CAPI: {e}")
        result['status'] = 'error'
        result['error_message'] = str(e)

    return result

def send_lead_qualified_with_value(
    email: str,
    phone: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    lead_score: float,
    decil: str,
    event_id: str,
    fbp: Optional[str],
    fbc: Optional[str],
    user_agent: Optional[str],
    client_ip: Optional[str],
    event_source_url: Optional[str],
    event_timestamp: int,
    test_event_code: Optional[str] = None,
    survey_data: Optional[Dict] = None,
    db = None,
    capi_config: Optional[CAPIConfig] = None,
    business_config: Optional[BusinessConfig] = None,
    client_id: str = 'devclub',
    event_name_override: Optional[str] = None,
    conversion_rates_override: Optional[Dict[str, float]] = None,
    pixel_id_override: Optional[str] = None,
    dry_run: bool = False,
) -> Dict:
    """
    ESTRATÉGIA 1: Envia TODOS os leads (D1-D10) com VALOR DIFERENCIADO por decil

    Comportamento:
    - Envia todos os leads independente do decil
    - Cada decil tem um valor diferente baseado na taxa de conversão corrigida
    - D10 = R$ 69.10, D1 = R$ 7.67, etc.
    - Meta otimiza para VALOR (Expected Value = Probabilidade × Valor)

    Quando usar:
    - Quer que Meta priorize leads de alta qualidade através de valores mais altos
    - Tem dados suficientes para calibrar valores por decil
    - Prefere otimização por valor monetário

    Args:
        email: Email do lead
        phone: Telefone do lead
        lead_score: Score do modelo ML
        decil: Decil (D1-D10)
        event_id: ID único do evento (deduplicação)
        fbp: Facebook Browser ID (_fbp cookie)
        fbc: Facebook Click ID (_fbc cookie)
        user_agent: User agent do navegador
        client_ip: IP do cliente
        event_source_url: URL da página de origem
        event_timestamp: Timestamp UNIX do lead original (não atual!)

    Returns:
        Dict com resultado do envio
    """
    if not ACCESS_TOKEN:
        logger.error("❌ META_ACCESS_TOKEN não configurado")
        return {"status": "error", "message": "ACCESS_TOKEN não configurado"}

    # Resolver valores do CAPIConfig (com fallbacks para compatibilidade)
    # pixel_id_override permite variante A/B enviar para pixel diferente do default.
    pixel_id = pixel_id_override or (capi_config.pixel_id if capi_config and capi_config.pixel_id else os.getenv('META_PIXEL_ID'))
    event_name = event_name_override or (capi_config.event_name_with_value if capi_config and capi_config.event_name_with_value else 'LeadQualified')
    currency = (capi_config.currency if capi_config and capi_config.currency else 'BRL')
    country_code = (capi_config.country_code if capi_config and capi_config.country_code else 'br')

    try:
        # Extrair dados adicionais para melhor matching
        # 1. Estado: inferir do DDD do telefone
        state = get_state_from_phone(phone)

        # 2. País: do CAPIConfig ou Brasil como padrão
        country = country_code if phone else None

        # 3. Cidade, CEP e Gênero: do survey_data se disponível
        city = None
        zip_code = None
        gender = None

        if survey_data:
            city = survey_data.get('cidade')
            zip_code = survey_data.get('cep')
            # Gênero: normalizar para formato Meta (m/f)
            # Nota: app.py monta survey_data com chave 'genero' (não 'O seu gênero:')
            gender_raw = survey_data.get('genero')
            gender = normalize_gender(gender_raw)

        # UserData (dados do usuário hashados)
        # IMPORTANTE: Esses campos melhoram o Event Quality Score do Meta
        user_data = UserData(
            emails=[hash_data(email)] if email else None,
            phones=[hash_data(phone)] if phone else None,
            first_names=[hash_data(first_name)] if first_name else None,
            last_names=[hash_data(last_name)] if last_name else None,
            # Novos campos para melhorar matching:
            states=[hash_data(state)] if state else None,
            cities=[hash_data(city)] if city else None,
            country_codes=[hash_data(country)] if country else None,
            zip_codes=[hash_data(zip_code)] if zip_code else None,
            genders=[gender] if gender else None,
            # Campos de contexto (não hashados):
            client_ip_address=client_ip,
            client_user_agent=user_agent,
            fbp=fbp,
            fbc=fbc
        )

        # CustomData (valor projetado = product_value × taxa_conversao do decil)
        # conversion_rates_override tem prioridade (usado no A/B test para a variante challenger)
        rates = conversion_rates_override or (business_config.conversion_rates if business_config and business_config.conversion_rates else None)
        taxa = 0.0
        if rates and business_config:
            taxa = rates.get(decil, 0.0)
            valor_projetado = round(business_config.product_value * taxa, 2)
        else:
            valor_projetado = 0.0

        # Preparar custom_properties com dados ML
        # IMPORTANTE: Converter valores para string para compatibilidade com Meta API
        custom_props = {
            'lead_score': str(lead_score),
            'decil': decil,  # já é string
            'valor_projetado': str(valor_projetado)
        }

        # Adicionar dados da pesquisa se disponíveis (enriquecem targeting)
        if survey_data:
            # Filtrar valores None/vazios e converter tudo para string
            survey_clean = {k: str(v) for k, v in survey_data.items() if v is not None and str(v).strip() != ''}
            custom_props.update(survey_clean)

        custom_data = CustomData(
            value=valor_projetado,
            currency=currency,
            custom_properties=custom_props
        )

        # Event
        event = Event(
            event_name=event_name,
            event_time=event_timestamp,
            event_id=f"qualified_{event_id}",  # Prefixo para diferenciar do Pixel
            user_data=user_data,
            custom_data=custom_data,
            event_source_url=event_source_url,
            action_source=ActionSource.WEBSITE
        )

        # EventRequest
        event_request_params = {
            'events': [event],
            'pixel_id': pixel_id,
            'access_token': ACCESS_TOKEN
        }
        if test_event_code:
            event_request_params['test_event_code'] = test_event_code

        event_request = EventRequest(**event_request_params)

        # [Gate C dry_run] Skip Meta call e DB writes — preserva todo o caminho de
        # routing A/B + cálculo de valor pra inspeção sem efeito colateral.
        if dry_run:
            logger.info(f"🧪 [DRY_RUN] LeadQualified calculado: {email} (decil: {decil}, valor proj: R$ {valor_projetado:.2f}, event_name: {event_name}, pixel: {pixel_id})")
            return {
                "status": "dry_run",
                "event_id": event_id,
                "email": email,
                "decil": decil,
                "valor_projetado": valor_projetado,
                "event_name": event_name,
                "pixel_id": pixel_id,
            }

        # Enviar
        response = event_request.execute()

        # Parsear resposta da Meta
        parsed_response = parse_meta_capi_response(response)

        # Salvar resposta no banco (se db session disponível)
        if db:
            try:
                from api.database import update_capi_response
                update_capi_response(
                    db=db,
                    email=email,
                    status=parsed_response['status'],
                    events_received=parsed_response['events_received'],
                    events_rejected=parsed_response['events_rejected'],
                    error_message=parsed_response['error_message'],
                    client_id=client_id
                )
            except Exception as db_err:
                logger.warning(f"⚠️  Erro ao salvar CAPI response no banco para {email}: {db_err}")

        logger.info(f"✅ {event_name} enviado: {email} (decil: {decil}, valor proj: R$ {valor_projetado:.2f}, status: {parsed_response['status']})")

        return {
            "status": parsed_response['status'],
            "event_id": event_id,
            "email": email,
            "decil": decil,
            "valor_projetado": valor_projetado,
            "capi_response": parsed_response,
            "response": str(response)
        }

    except Exception as e:
        import traceback
        logger.error(f"❌ Erro ao enviar LeadQualified com valor: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "event_id": event_id,
            "email": email,
            "message": str(e)
        }

def send_lead_qualified_high_quality(
    email: str,
    phone: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    lead_score: float,
    decil: str,
    event_id: str,
    fbp: Optional[str],
    fbc: Optional[str],
    user_agent: Optional[str],
    client_ip: Optional[str],
    event_source_url: Optional[str],
    event_timestamp: int,
    test_event_code: Optional[str] = None,
    survey_data: Optional[Dict] = None,
    db = None,
    capi_config: Optional[CAPIConfig] = None,
    client_id: str = 'devclub',
    event_name_override: Optional[str] = None,
    pixel_id_override: Optional[str] = None,
    high_quality_decils_override: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Dict:
    """
    ESTRATÉGIA 2: Envia APENAS D9 e D10 SEM VALOR

    Comportamento:
    - Filtra: só envia se decil in ['D9', 'D10']
    - SEM valor monetário (Meta otimiza para volume de conversões)
    - Meta aprende com perfil de alta qualidade (top 20% dos leads)
    - Volume menor mas mais focado

    Quando usar (Gestor de Tráfego):
    - Criar campanha separada otimizando para "LeadQualifiedHighQuality"
    - Usar Cost Cap ou Lowest Cost (não Target ROAS)
    - Foco em volume de leads qualificados (top 20%)

    Args:
        email: Email do lead
        phone: Telefone do lead
        lead_score: Score do modelo ML
        decil: Decil (D1-D10)
        event_id: ID único do evento (deduplicação)
        fbp: Facebook Browser ID (_fbp cookie)
        fbc: Facebook Click ID (_fbc cookie)
        user_agent: User agent do navegador
        client_ip: IP do cliente
        event_source_url: URL da página de origem
        event_timestamp: Timestamp UNIX do lead original (não atual!)

    Returns:
        Dict com resultado do envio (ou skipped se não for D9-D10)
    """
    # Resolver valores do CAPIConfig (com fallbacks para compatibilidade)
    pixel_id = pixel_id_override or (capi_config.pixel_id if capi_config and capi_config.pixel_id else os.getenv('META_PIXEL_ID'))
    event_name_hq = event_name_override or (capi_config.event_name_high_quality if capi_config and capi_config.event_name_high_quality else 'LeadQualifiedHighQuality')
    # Faixa de decis que dispara HQ: prioriza override da variante A/B, depois config global do cliente, depois fallback default.
    high_quality_decils = high_quality_decils_override or (capi_config.high_quality_decils if capi_config and capi_config.high_quality_decils else ['D09', 'D10'])
    currency = (capi_config.currency if capi_config and capi_config.currency else 'BRL')
    country_code = (capi_config.country_code if capi_config and capi_config.country_code else 'br')

    # Filtro: só envia decis de alta qualidade (do config ou D09-D10 como fallback)
    if decil not in high_quality_decils:
        logger.debug(f"⏭️  Lead {decil} ignorado (estratégia high quality only: {high_quality_decils})")
        return {
            "status": "skipped",
            "event_id": event_id,
            "email": email,
            "decil": decil,
            "reason": f"Decil fora de {high_quality_decils} (filtrado)"
        }

    if not ACCESS_TOKEN:
        logger.error("❌ META_ACCESS_TOKEN não configurado")
        return {"status": "error", "message": "ACCESS_TOKEN não configurado"}

    try:
        # Extrair dados adicionais para melhor matching
        # 1. Estado: inferir do DDD do telefone
        state = get_state_from_phone(phone)

        # 2. País: do CAPIConfig ou Brasil como padrão
        country = country_code if phone else None

        # 3. Cidade, CEP e Gênero: do survey_data se disponível
        city = None
        zip_code = None
        gender = None

        if survey_data:
            city = survey_data.get('cidade')
            zip_code = survey_data.get('cep')
            # Gênero: normalizar para formato Meta (m/f)
            # Nota: app.py monta survey_data com chave 'genero' (não 'O seu gênero:')
            gender_raw = survey_data.get('genero')
            gender = normalize_gender(gender_raw)

        # UserData (dados do usuário hashados)
        # IMPORTANTE: Esses campos melhoram o Event Quality Score do Meta
        user_data = UserData(
            emails=[hash_data(email)] if email else None,
            phones=[hash_data(phone)] if phone else None,
            first_names=[hash_data(first_name)] if first_name else None,
            last_names=[hash_data(last_name)] if last_name else None,
            # Novos campos para melhorar matching:
            states=[hash_data(state)] if state else None,
            cities=[hash_data(city)] if city else None,
            country_codes=[hash_data(country)] if country else None,
            zip_codes=[hash_data(zip_code)] if zip_code else None,
            genders=[gender] if gender else None,
            # Campos de contexto (não hashados):
            client_ip_address=client_ip,
            client_user_agent=user_agent,
            fbp=fbp,
            fbc=fbc
        )

        # CustomData (SEM valor - Meta otimiza para volume)
        # Preparar custom_properties
        # IMPORTANTE: Converter valores para string para compatibilidade com Meta API
        custom_props = {
            'lead_score': str(lead_score),
            'decil': decil,  # já é string
            'estrategia': 'high_quality_only'
        }

        # Adicionar dados da pesquisa se disponíveis
        if survey_data:
            # Filtrar valores None/vazios e converter tudo para string
            survey_clean = {k: str(v) for k, v in survey_data.items() if v is not None and str(v).strip() != ''}
            custom_props.update(survey_clean)

        custom_data = CustomData(
            currency=currency,
            custom_properties=custom_props
        )

        # Event
        event = Event(
            event_name=event_name_hq,
            event_time=event_timestamp,
            event_id=f"hq_{event_id}",  # Prefixo diferente para evitar dedup
            user_data=user_data,
            custom_data=custom_data,
            event_source_url=event_source_url,
            action_source=ActionSource.WEBSITE
        )

        # EventRequest
        event_request_params = {
            'events': [event],
            'pixel_id': pixel_id,
            'access_token': ACCESS_TOKEN
        }
        if test_event_code:
            event_request_params['test_event_code'] = test_event_code

        event_request = EventRequest(**event_request_params)

        # [Gate C dry_run] Skip Meta call e DB writes — preserva cálculo de event_name
        # e pixel pra inspeção sem efeito colateral.
        if dry_run:
            logger.info(f"🧪 [DRY_RUN] LeadQualifiedHighQuality calculado: {email} (decil: {decil}, event_name: {event_name_hq}, pixel: {pixel_id})")
            return {
                "status": "dry_run",
                "event_id": event_id,
                "email": email,
                "decil": decil,
                "estrategia": "high_quality_only",
                "event_name": event_name_hq,
                "pixel_id": pixel_id,
            }

        # Enviar
        response = event_request.execute()

        # Parsear resposta da Meta
        parsed_response = parse_meta_capi_response(response)

        # Salvar resposta no banco (se db session disponível)
        if db:
            try:
                from api.database import update_capi_response
                update_capi_response(
                    db=db,
                    email=email,
                    status=parsed_response['status'],
                    events_received=parsed_response['events_received'],
                    events_rejected=parsed_response['events_rejected'],
                    error_message=parsed_response['error_message'],
                    client_id=client_id
                )
            except Exception as db_err:
                logger.warning(f"⚠️  Erro ao salvar CAPI response no banco para {email}: {db_err}")

        logger.info(f"✅ {event_name_hq} enviado: {email} (decil: {decil}, status: {parsed_response['status']})")

        return {
            "status": parsed_response['status'],
            "event_id": event_id,
            "email": email,
            "decil": decil,
            "estrategia": "high_quality_only",
            "capi_response": parsed_response,
            "response": str(response)
        }

    except Exception as e:
        import traceback
        logger.error(f"❌ Erro ao enviar LeadQualifiedHighQuality: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "event_id": event_id,
            "email": email,
            "message": str(e)
        }

def send_both_lead_events(
    email: str,
    phone: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    lead_score: float,
    decil: str,
    event_id: str,
    fbp: Optional[str],
    fbc: Optional[str],
    user_agent: Optional[str],
    client_ip: Optional[str],
    event_source_url: Optional[str],
    event_timestamp: int,
    test_event_code: Optional[str] = None,
    survey_data: Optional[Dict] = None,
    db = None,
    capi_config: Optional[CAPIConfig] = None,
    business_config: Optional[BusinessConfig] = None,
    client_id: str = 'devclub',
    event_name_override: Optional[str] = None,
    event_name_hq_override: Optional[str] = None,
    conversion_rates_override: Optional[Dict[str, float]] = None,
    pixel_id_override: Optional[str] = None,
    high_quality_decils_override: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Dict:
    """
    TESTE A/B: Envia AMBOS os eventos para permitir teste de 2 estratégias

    Esta função envia:
    1. LeadQualified (com valor, D1-D10)
    2. LeadQualifiedHighQuality (sem valor, D9-D10 only)

    O gestor de tráfego cria 2 campanhas:
    - Campanha A (50% budget): Otimiza para "LeadQualified"
    - Campanha B (50% budget): Otimiza para "LeadQualifiedHighQuality"

    Após 4 semanas, compara:
    - CPL, Volume, Taxa conversão real, ROAS

    Args:
        Mesmos args das funções individuais

    Returns:
        Dict com resultado de ambos os envios
    """
    logger.info(f"📤 Enviando AMBOS eventos para teste A/B: {email} ({decil})")

    # Evento 1: COM VALOR (D1-D10)
    # NOTA: reativado em 2026-05-06 — confirmação de que campanhas Meta ativas em
    # produção usam o evento `LeadQualified` para otimização baseada em value.
    # Mitigação do worker timeout que motivou a desativação anterior: blocos DEBUG
    # foram removidos (~50-100ms/lead), reduzindo o tempo total de processing.
    result_with_value = send_lead_qualified_with_value(
        email=email,
        phone=phone,
        first_name=first_name,
        last_name=last_name,
        lead_score=lead_score,
        decil=decil,
        event_id=event_id,
        fbp=fbp,
        fbc=fbc,
        user_agent=user_agent,
        client_ip=client_ip,
        event_source_url=event_source_url,
        event_timestamp=event_timestamp,
        test_event_code=test_event_code,
        survey_data=survey_data,
        db=db,
        capi_config=capi_config,
        business_config=business_config,
        client_id=client_id,
        event_name_override=event_name_override,
        conversion_rates_override=conversion_rates_override,
        pixel_id_override=pixel_id_override,
        dry_run=dry_run,
    )

    # Evento 2: HighQuality SEM VALOR (D9-D10 only — função filtra internamente)
    result_high_quality = send_lead_qualified_high_quality(
        email=email,
        phone=phone,
        first_name=first_name,
        last_name=last_name,
        lead_score=lead_score,
        decil=decil,
        event_id=event_id,
        fbp=fbp,
        fbc=fbc,
        user_agent=user_agent,
        client_ip=client_ip,
        event_source_url=event_source_url,
        event_timestamp=event_timestamp,
        test_event_code=test_event_code,
        survey_data=survey_data,
        db=db,
        capi_config=capi_config,
        client_id=client_id,
        event_name_override=event_name_hq_override,
        pixel_id_override=pixel_id_override,
        high_quality_decils_override=high_quality_decils_override,
        dry_run=dry_run,
    )

    # Fan-out HQ: duplica o disparo primário em pixels adicionais declarados
    # no client_config.capi.extra_hq_destinations. Match case-sensitive pelo
    # nome de evento HQ que efetivamente saiu acima. Cada destinação tem sua
    # própria faixa de decis (filtragem é da send_lead_qualified_high_quality).
    # Falhas isoladas não derrubam o primário nem as outras cópias.
    extra_results: List[Dict] = []
    extras = capi_config.extra_hq_destinations if (capi_config and capi_config.extra_hq_destinations) else []
    if extras:
        primary_hq_event_name = event_name_hq_override or (
            capi_config.event_name_high_quality if capi_config and capi_config.event_name_high_quality
            else 'LeadQualifiedHighQuality'
        )
        for i, dest in enumerate(extras):
            if dest.event_name != primary_hq_event_name:
                continue
            try:
                r = send_lead_qualified_high_quality(
                    email=email,
                    phone=phone,
                    first_name=first_name,
                    last_name=last_name,
                    lead_score=lead_score,
                    decil=decil,
                    event_id=event_id,
                    fbp=fbp,
                    fbc=fbc,
                    user_agent=user_agent,
                    client_ip=client_ip,
                    event_source_url=event_source_url,
                    event_timestamp=event_timestamp,
                    test_event_code=test_event_code,
                    survey_data=survey_data,
                    db=db,
                    capi_config=capi_config,
                    client_id=client_id,
                    event_name_override=dest.event_name,
                    pixel_id_override=dest.pixel_id,
                    high_quality_decils_override=list(dest.decils),
                    dry_run=dry_run,
                )
                extra_results.append(r)
            except Exception as e:
                logger.warning(
                    f"⚠️  Fan-out HQ [{i}] '{dest.event_name}' → pixel {dest.pixel_id} "
                    f"falhou para {email}: {e}"
                )

    return {
        "status": "success",
        "email": email,
        "decil": decil,
        "evento_com_valor": result_with_value,
        "evento_high_quality": result_high_quality,
        "extra_hq_results": extra_results,
    }

def send_purchase_event(
    email: str,
    phone: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    valor_venda: float,
    original_event_id: str,
    fbp: Optional[str],
    fbc: Optional[str],
    user_agent: Optional[str],
    client_ip: Optional[str],
    event_source_url: Optional[str],
    capi_config: Optional[CAPIConfig] = None
) -> Dict:
    """
    Envia evento Purchase quando lead vira venda

    Args:
        email: Email do lead
        phone: Telefone do lead
        valor_venda: Valor REAL da venda
        original_event_id: Event ID do lead original (para linking)
        fbp: Facebook Browser ID
        fbc: Facebook Click ID
        user_agent: User agent
        client_ip: IP do cliente
        event_source_url: URL de origem

    Returns:
        Dict com resultado do envio
    """
    pixel_id = (capi_config.pixel_id if capi_config and capi_config.pixel_id else os.getenv('META_PIXEL_ID'))
    currency = (capi_config.currency if capi_config and capi_config.currency else 'BRL')

    if not ACCESS_TOKEN:
        logger.error("❌ META_ACCESS_TOKEN não configurado")
        return {"status": "error", "message": "ACCESS_TOKEN não configurado"}

    try:
        # UserData
        user_data = UserData(
            emails=[hash_data(email)] if email else None,
            phones=[hash_data(phone)] if phone else None,
            first_names=[hash_data(first_name)] if first_name else None,
            last_names=[hash_data(last_name)] if last_name else None,
            client_ip_address=client_ip,
            client_user_agent=user_agent,
            fbp=fbp,
            fbc=fbc
        )

        # CustomData (valor REAL da venda)
        custom_data = CustomData(
            value=valor_venda,
            currency=currency
        )

        # Event
        event = Event(
            event_name='Purchase',
            event_time=int(time.time()),
            event_id=f"purchase_{original_event_id}",
            user_data=user_data,
            custom_data=custom_data,
            event_source_url=event_source_url,
            action_source=ActionSource.SYSTEM_GENERATED  # Conversão offline
        )

        # EventRequest
        event_request_params = {
            'events': [event],
            'pixel_id': pixel_id,
            'access_token': ACCESS_TOKEN
        }
        if test_event_code:
            event_request_params['test_event_code'] = test_event_code

        event_request = EventRequest(**event_request_params)

        # Enviar
        response = event_request.execute()

        logger.info(f"✅ Purchase enviado: {email} (valor: R$ {valor_venda:.2f})")

        return {
            "status": "success",
            "event_id": original_event_id,
            "email": email,
            "valor_venda": valor_venda,
            "response": str(response)
        }

    except Exception as e:
        logger.error(f"❌ Erro ao enviar Purchase: {str(e)}")
        return {
            "status": "error",
            "event_id": original_event_id,
            "email": email,
            "message": str(e)
        }


def should_send_to_destination(
    lead: Dict,
    capi_config: Optional[CAPIConfig],
    destination: str = 'meta',
) -> tuple:
    """
    Decide se um lead deve enviar evento para uma plataforma de ads.

    Centraliza a lógica de blocklist/allowlist por UTM que estava duplicada em 4
    pontos do app.py. Resolve o vazamento histórico (DT-CAPI-01): leads não-Meta
    indo para o Pixel da Meta via paths que esqueciam de aplicar o filtro.

    Estrutura preparada para futuras integrações (Google Ads, TikTok): cada
    destination tem seu próprio branch carregando allowlist/blocklist específicas
    do CAPIConfig. Hoje suporta apenas 'meta'.

    Args:
        lead: dict com 'source'/'utm_source' e 'campaign'/'utm_campaign'.
              Aceita ambas as nomenclaturas (ORM vs Railway dict vs payload bruto).
        capi_config: CAPIConfig do cliente. Se None, retorna allowed=True
                     (sem config = comportamento legado, não filtra).
        destination: 'meta' (default). Outras destinations retornam allowed=False
                     com reason='unknown_destination' até que sejam implementadas.

    Returns:
        (allowed: bool, reason: str)
        reasons:
          - 'allowed'              : passou nos filtros, deve enviar
          - 'blocked_by_blocklist' : utm_campaign casou com blocklist
          - 'skipped_by_allowlist' : utm_source não está na allowlist
          - 'no_config'            : capi_config=None, passa por padrão
          - 'unknown_destination'  : destination não suportado ainda
    """
    if capi_config is None:
        return True, 'no_config'

    src = (lead.get('source') or lead.get('utm_source') or '').lower()
    cam = (lead.get('campaign') or lead.get('utm_campaign') or '').lower()

    if destination == 'meta':
        blocklist = capi_config.utm_blocklist or []
        allowlist = capi_config.utm_source_allowlist or []
    else:
        # Quando integração Google Ads / TikTok for adicionada:
        #   - adicionar campos `google_source_allowlist` etc. em CAPIConfig
        #   - adicionar branch aqui carregando-os
        # Até lá, qualquer destination diferente de 'meta' bloqueia por segurança.
        return False, 'unknown_destination'

    if blocklist and any(p.lower() in cam for p in blocklist):
        return False, 'blocked_by_blocklist'
    # Allowlist: exact match (case-insensitive). Substring match causa false positives
    # — ex: "ig" no allowlist deixaria passar source=gruposantigos (contém "ig").
    if allowlist and not any(s.lower() == src for s in allowlist):
        return False, 'skipped_by_allowlist'
    return True, 'allowed'


def send_batch_events(leads: List[Dict], db=None, capi_config: Optional[CAPIConfig] = None, business_config: Optional[BusinessConfig] = None, client_id: str = 'devclub', dry_run: bool = False) -> Dict:
    """
    Envia múltiplos eventos CAPI em batch (AMBAS AS ESTRATÉGIAS)
    Usado pelo processamento diário

    Para cada lead, envia:
    - LeadQualified (com valor, todos os decis)
    - LeadQualifiedHighQuality (sem valor, D9-D10 only)

    Args:
        leads: Lista de dicts com dados dos leads
        db: SQLAlchemy session para registrar envios (opcional)

    Returns:
        Dict com estatísticas do envio
    """
    if not ACCESS_TOKEN:
        logger.error("❌ META_ACCESS_TOKEN não configurado")
        return {
            "status": "error",
            "message": "ACCESS_TOKEN não configurado",
            "total": 0,
            "success": 0,
            "errors": 0
        }

    results = {
        "total": len(leads),
        "success": 0,
        "errors": 0,
        "details": []
    }

    for lead in leads:
        lead_score_value = lead['lead_score']

        # Usar send_both_lead_events para enviar ambas as estratégias
        result = send_both_lead_events(
            email=lead['email'],
            phone=lead.get('phone'),
            first_name=lead.get('first_name'),
            last_name=lead.get('last_name'),
            lead_score=lead_score_value,
            decil=lead['decil'],
            event_id=lead['event_id'],
            fbp=lead.get('fbp'),
            fbc=lead.get('fbc'),
            user_agent=lead.get('user_agent'),
            client_ip=lead.get('client_ip'),
            event_source_url=lead.get('event_source_url'),
            event_timestamp=lead['event_timestamp'],
            survey_data=lead.get('survey_data'),  # Dados da pesquisa
            db=db,  # Passar db session para salvar resposta CAPI
            capi_config=capi_config,
            business_config=business_config,
            client_id=client_id,
            # A/B test overrides — preenchidos pelo app.py quando variante identificada
            event_name_override=lead.get('ab_event_name'),
            event_name_hq_override=lead.get('ab_event_name_hq'),
            conversion_rates_override=lead.get('ab_conversion_rates'),
            pixel_id_override=lead.get('ab_pixel_id'),
            high_quality_decils_override=lead.get('ab_high_quality_decils'),
            dry_run=dry_run,
            # test_event_code=None (padrão) -> vai para PRODUÇÃO
        )

        if result['status'] == 'success':
            results['success'] += 1

            # Registrar envio no banco (se db session disponível e não-dry_run)
            if db and not dry_run:
                try:
                    from api.database import mark_lead_capi_sent
                    mark_lead_capi_sent(db, lead['email'], client_id=client_id)
                except Exception as mark_error:
                    logger.warning(f"⚠️ Não foi possível marcar CAPI sent para {lead['email']}: {mark_error}")
        else:
            results['errors'] += 1

        results['details'].append(result)

    logger.info(f"📊 Batch CAPI: {results['success']}/{results['total']} enviados com sucesso")

    return results
