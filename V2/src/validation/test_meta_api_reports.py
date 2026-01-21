"""
Script de teste para obter dados de relatórios da Meta via API usando ASYNC requests.

Objetivo: Verificar se conseguimos obter os mesmos dados dos relatórios
CSV exportados manualmente, mas via API (Marketing API).

IMPORTANTE: Usa ASYNC insights requests para evitar rate limits.

Requisitos:
- facebook-business SDK: pip install facebook-business
- Token de acesso já configurado em api/meta_config.py

Dados necessários:
- Access Token (importado de meta_config.py)
- Ad Account ID (act_188005769808959)
"""

import os
import sys
import time
from datetime import datetime, timedelta
import pandas as pd
import json

# Adicionar path do projeto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Importar configuração da Meta
try:
    from api.meta_config import META_CONFIG
except ImportError:
    print("❌ Erro ao importar meta_config.py")
    sys.exit(1)

try:
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount
    from facebook_business.adobjects.adreportrun import AdReportRun
    from facebook_business.adobjects.adsinsights import AdsInsights
except ImportError:
    print("❌ facebook-business não instalado")
    print("Execute: pip install facebook-business")
    sys.exit(1)


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

ACCESS_TOKEN = META_CONFIG['access_token']
API_VERSION = META_CONFIG['api_version']
AD_ACCOUNT_ID = 'act_188005769808959'  # Los Angeles Producciones LTDA

# Período de teste (últimas 7 dias)
DATE_START = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
DATE_END = datetime.now().strftime('%Y-%m-%d')

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos


# =============================================================================
# CAMPOS E MÉTRICAS
# =============================================================================

# Métricas base comuns a todos os níveis
BASE_FIELDS = [
    'account_id',
    'account_name',
    'date_start',
    'date_stop',
    'spend',
    'campaign_id',
    'campaign_name',
]

# Campos específicos por nível
CAMPAIGN_FIELDS = BASE_FIELDS + [
    'objective',
    'actions',  # Eventos padrão (Leads, link_click, etc.)
    'conversions',  # IMPORTANTE: Eventos customizados (Faixa A, LeadQualified, etc.)
    'action_values',
    'conversion_values',
]

ADSET_FIELDS = CAMPAIGN_FIELDS + [
    'adset_id',
    'adset_name',
]

AD_FIELDS = ADSET_FIELDS + [
    'ad_id',
    'ad_name',
]

# Actions (eventos de conversão) que precisamos extrair
# Esses são os mesmos do CSV: Leads, Faixa A, LeadQualified, LeadQualifiedHighQuality
ACTIONS_TO_EXTRACT = [
    'offsite_conversion.fb_pixel_lead',  # Leads
    'offsite_conversion.fb_pixel_custom.Faixa A',  # Faixa A
    'offsite_conversion.fb_pixel_custom.LeadQualified',  # LeadQualified
    'offsite_conversion.fb_pixel_custom.LeadQualifiedHighQuality',  # LeadQualifiedHighQuality
]


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def initialize_api(access_token, api_version):
    """Inicializa a API do Facebook."""
    try:
        FacebookAdsApi.init(access_token=access_token, api_version=api_version)
        print("✅ API inicializada com sucesso")
        print(f"   API Version: {api_version}")
        return True
    except Exception as e:
        print(f"❌ Erro ao inicializar API: {e}")
        return False


def wait_for_async_job(async_job, job_name="Job"):
    """
    Aguarda conclusão de job assíncrono.

    Args:
        async_job: Objeto AdReportRun
        job_name: Nome do job para logging

    Returns:
        AdReportRun completado ou None se falhou
    """
    print(f"\n⏳ Aguardando {job_name}...")

    max_wait_time = 600  # 10 minutos
    start_time = time.time()

    while True:
        # Verificar timeout
        if time.time() - start_time > max_wait_time:
            print(f"❌ Timeout ao aguardar {job_name}")
            return None

        # Buscar status do job
        try:
            job = async_job.api_get()
        except Exception as e:
            print(f"❌ Erro ao buscar status do job: {e}")
            return None

        status = job.get(AdReportRun.Field.async_status, 'Unknown')
        percent = job.get(AdReportRun.Field.async_percent_completion, 0)

        print(f"   Status: {status} - {percent}% concluído", end='\r')

        # Verificar se completou
        if status == 'Job Completed':
            print(f"\n✅ {job_name} concluído!")
            return job

        # Verificar se falhou
        if status == 'Job Failed':
            print(f"\n❌ {job_name} falhou!")
            return None

        # Aguardar antes de checar novamente
        time.sleep(2)


def get_insights_with_retry(account, params, fields, level_name):
    """
    Obtém insights com retry logic para rate limits.

    Args:
        account: AdAccount object
        params: Parâmetros para get_insights
        fields: Lista de campos
        level_name: Nome do nível (para logging)

    Returns:
        Lista de insights ou lista vazia se falhou
    """
    for attempt in range(MAX_RETRIES):
        try:
            print(f"\n📊 Iniciando requisição ASYNC para {level_name}...")
            print(f"   Período: {params['time_range']['since']} a {params['time_range']['until']}")
            print(f"   Level: {params['level']}")

            # Fazer requisição assíncrona
            async_job = account.get_insights(
                fields=fields,
                params=params,
                is_async=True  # IMPORTANTE: Requisição assíncrona
            )

            # Aguardar conclusão
            completed_job = wait_for_async_job(async_job, f"{level_name} insights")

            if not completed_job:
                raise Exception(f"Job assíncrono falhou para {level_name}")

            # Obter resultados
            print(f"📥 Baixando resultados de {level_name}...")
            insights = completed_job.get_result()

            results = []
            for insight in insights:
                results.append(insight.export_all_data())

            print(f"✅ Obtidos {len(results)} registros de {level_name}")
            return results

        except Exception as e:
            error_msg = str(e)

            # Verificar se é erro de rate limit
            if 'rate limit' in error_msg.lower() or 'error code 613' in error_msg.lower():
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (attempt + 1)
                    print(f"⚠️  Rate limit atingido. Aguardando {wait_time}s antes de tentar novamente...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ Rate limit persistente após {MAX_RETRIES} tentativas")
                    return []
            else:
                print(f"❌ Erro ao buscar {level_name}: {e}")
                if attempt < MAX_RETRIES - 1:
                    print(f"   Tentativa {attempt + 2}/{MAX_RETRIES}...")
                    time.sleep(RETRY_DELAY)
                    continue
                return []

    return []


def parse_events(actions_list, conversions_list):
    """
    Parse de actions E conversions para extrair todos os eventos.

    Args:
        actions_list: Lista de dicts com action_type e value (actions)
        conversions_list: Lista de dicts com action_type e value (conversions customizadas)

    Returns:
        dict: Mapeamento de eventos
    """
    parsed = {}

    # Processar actions (eventos padrão)
    if actions_list:
        for action in actions_list:
            action_type = action.get('action_type', '')
            value = action.get('value', '0')

            try:
                value_int = int(float(value))
            except (ValueError, TypeError):
                value_int = 0

            # Capturar evento de Lead padrão
            if action_type == 'offsite_conversion.fb_pixel_lead':
                parsed['Leads'] = value_int

    # Processar conversions (eventos customizados)
    if conversions_list:
        for conversion in conversions_list:
            action_type = conversion.get('action_type', '')
            value = conversion.get('value', '0')

            try:
                value_int = int(float(value))
            except (ValueError, TypeError):
                value_int = 0

            # Mapear eventos customizados
            if 'Faixa A' in action_type or 'FaixaA' in action_type:
                parsed['Faixa_A'] = value_int
            elif action_type == 'offsite_conversion.fb_pixel_custom.LeadQualified':
                parsed['LeadQualified'] = value_int
            elif action_type == 'offsite_conversion.fb_pixel_custom.LeadQualifiedHighQuality':
                parsed['LeadQualifiedHighQuality'] = value_int

    return parsed


def format_insights_as_csv(insights_data, level='campaign'):
    """
    Formata os insights no mesmo formato dos CSVs da Meta.

    Args:
        insights_data: Lista de insights da API
        level: 'campaign', 'adset' ou 'ad'

    Returns:
        pd.DataFrame
    """
    if not insights_data:
        print(f"⚠️  Nenhum dado para formatar (level={level})")
        return pd.DataFrame()

    formatted_rows = []

    for insight in insights_data:
        row = {
            'Início dos relatórios': insight.get('date_start', ''),
            'Término dos relatórios': insight.get('date_stop', ''),
            'Valor usado (BRL)': float(insight.get('spend', 0)),
            'Nome da campanha': insight.get('campaign_name', ''),
            'Identificação da campanha': insight.get('campaign_id', ''),
        }

        # Campos específicos por nível
        if level in ['adset', 'ad']:
            row['Nome do conjunto de anúncios'] = insight.get('adset_name', '')
            row['Identificação do conjunto de anúncios'] = insight.get('adset_id', '')

        if level == 'ad':
            row['Nome do anúncio'] = insight.get('ad_name', '')
            row['Identificação do anúncio'] = insight.get('ad_id', '')

        # Parse de ações E conversões customizadas
        actions = insight.get('actions', [])
        conversions_raw = insight.get('conversions', [])
        events = parse_events(actions, conversions_raw)

        row['Leads'] = events.get('Leads', '')
        row['Faixa A'] = events.get('Faixa_A', '')
        row['LeadQualified'] = events.get('LeadQualified', '')
        row['LeadQualifiedHighQuality'] = events.get('LeadQualifiedHighQuality', '')

        # Indicador de resultados (priorizar conversions customizadas, senão actions)
        if conversions_raw and len(conversions_raw) > 0:
            row['Indicador de resultados'] = f"conversions:{conversions_raw[0].get('action_type', '')}"
        elif actions and len(actions) > 0:
            row['Indicador de resultados'] = f"actions:{actions[0].get('action_type', '')}"
        else:
            row['Indicador de resultados'] = ''

        formatted_rows.append(row)

    return pd.DataFrame(formatted_rows)


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

def main():
    """Função principal de teste."""
    print("="*80)
    print("🔍 TESTE DE EXTRAÇÃO VIA META MARKETING API (ASYNC)")
    print("="*80)

    # Inicializar API
    if not initialize_api(ACCESS_TOKEN, API_VERSION):
        return

    print(f"\n📅 Período de teste: {DATE_START} a {DATE_END}")
    print(f"🏢 Ad Account: {AD_ACCOUNT_ID}")
    print(f"⚡ Modo: ASYNC (evita rate limits)")

    # Obter account object
    try:
        account = AdAccount(AD_ACCOUNT_ID)
    except Exception as e:
        print(f"❌ Erro ao acessar conta de anúncios: {e}")
        return

    # =============================================================================
    # TESTE 1: Insights de Campanhas (ASYNC)
    # =============================================================================

    params_campaign = {
        'time_range': {
            'since': DATE_START,
            'until': DATE_END
        },
        'level': 'campaign',
        'time_increment': 1,  # Por dia
        'filtering': [],
        'breakdowns': [],
    }

    campaigns_insights = get_insights_with_retry(
        account,
        params_campaign,
        CAMPAIGN_FIELDS,
        'Campanhas'
    )

    if campaigns_insights:
        print(f"\n📄 Exemplo de dados brutos (primeira campanha):")
        print(json.dumps(campaigns_insights[0], indent=2, default=str)[:500] + "...")

        # Formatar como CSV
        df_campaigns = format_insights_as_csv(campaigns_insights, level='campaign')
        print(f"\n✅ DataFrame de campanhas: {df_campaigns.shape}")
        print(f"\nColunas: {df_campaigns.columns.tolist()}")
        print(f"\nPrimeiras linhas:")
        print(df_campaigns.head())

        # Salvar
        output_path = '/Users/ramonmoreira/Desktop/smart_ads/V2/files/validation/meta_reports/test_api_campaigns.csv'
        df_campaigns.to_csv(output_path, index=False)
        print(f"\n💾 Salvo em: {output_path}")

    # =============================================================================
    # TESTE 2: Insights de Ad Sets (ASYNC)
    # =============================================================================

    params_adset = {
        'time_range': {
            'since': DATE_START,
            'until': DATE_END
        },
        'level': 'adset',
        'time_increment': 1,
        'filtering': [],
        'breakdowns': [],
    }

    adsets_insights = get_insights_with_retry(
        account,
        params_adset,
        ADSET_FIELDS,
        'Ad Sets'
    )

    if adsets_insights:
        df_adsets = format_insights_as_csv(adsets_insights, level='adset')
        print(f"\n✅ DataFrame de ad sets: {df_adsets.shape}")

        output_path = '/Users/ramonmoreira/Desktop/smart_ads/V2/files/validation/meta_reports/test_api_adsets.csv'
        df_adsets.to_csv(output_path, index=False)
        print(f"💾 Salvo em: {output_path}")

    # =============================================================================
    # TESTE 3: Insights de Ads (ASYNC)
    # =============================================================================

    params_ad = {
        'time_range': {
            'since': DATE_START,
            'until': DATE_END
        },
        'level': 'ad',
        'time_increment': 1,
        'filtering': [],
        'breakdowns': [],
    }

    ads_insights = get_insights_with_retry(
        account,
        params_ad,
        AD_FIELDS,
        'Ads'
    )

    if ads_insights:
        df_ads = format_insights_as_csv(ads_insights, level='ad')
        print(f"\n✅ DataFrame de ads: {df_ads.shape}")

        output_path = '/Users/ramonmoreira/Desktop/smart_ads/V2/files/validation/meta_reports/test_api_ads.csv'
        df_ads.to_csv(output_path, index=False)
        print(f"💾 Salvo em: {output_path}")

    # =============================================================================
    # RESUMO
    # =============================================================================
    print("\n" + "="*80)
    print("📊 RESUMO DOS TESTES")
    print("="*80)
    print(f"✅ Campanhas: {len(campaigns_insights)} registros")
    print(f"✅ Ad Sets: {len(adsets_insights)} registros")
    print(f"✅ Ads: {len(ads_insights)} registros")
    print("\n🎯 Próximos passos:")
    print("1. Compare os CSVs gerados com os relatórios manuais")
    print("2. Verifique se todas as métricas estão presentes")
    print("3. Ajuste os campos/actions se necessário")
    print("4. Se OK, implemente na automação de validação")
    print("\n💡 Observações:")
    print("- Usamos ASYNC requests para evitar rate limits")
    print("- Cada requisição aguarda conclusão antes de prosseguir")
    print("- Retry automático em caso de rate limit (até 3 tentativas)")


if __name__ == '__main__':
    main()
