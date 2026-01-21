"""
Script para replicar relatórios da Meta via API.

Objetivo: Gerar exatamente os mesmos relatórios que foram baixados manualmente,
mas usando a API, para validar que a API funciona corretamente.

Período de teste: 16 de dezembro de 2025 a 12 de janeiro de 2026
Conta: Rodolfo Mori (act_188005769808959)
"""

import os
import sys
import time
from datetime import datetime
import pandas as pd

# Adicionar path do projeto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from api.meta_config import META_CONFIG

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adreportrun import AdReportRun

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

ACCESS_TOKEN = META_CONFIG['access_token']
API_VERSION = META_CONFIG['api_version']
AD_ACCOUNT_ID = 'act_188005769808959'  # Rodolfo Mori

# Período EXATO dos relatórios manuais
DATE_START = '2025-12-16'
DATE_END = '2026-01-12'

# Pasta de saída
OUTPUT_DIR = '/Users/ramonmoreira/Desktop/smart_ads/V2/files/validation/meta_reports/16:12 - 12:01 - API'

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 5

print("="*80)
print("🔄 REPLICANDO RELATÓRIOS DA META VIA API")
print("="*80)
print(f"📅 Período: {DATE_START} a {DATE_END}")
print(f"🏢 Conta: Rodolfo Mori (act_188005769808959)")
print(f"📂 Output: {OUTPUT_DIR}")
print("="*80)

# Criar pasta de saída
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =============================================================================
# CAMPOS
# =============================================================================

BASE_FIELDS = [
    'account_id',
    'account_name',
    'date_start',
    'date_stop',
    'spend',
    'campaign_id',
    'campaign_name',
    'actions',
    'conversions',
]

CAMPAIGN_FIELDS = BASE_FIELDS + [
    'objective',
]

ADSET_FIELDS = CAMPAIGN_FIELDS + [
    'adset_id',
    'adset_name',
]

AD_FIELDS = ADSET_FIELDS + [
    'ad_id',
    'ad_name',
]

# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def wait_for_async_job(async_job, job_name="Job"):
    """Aguarda conclusão de job assíncrono."""
    print(f"\n⏳ Aguardando {job_name}...")

    max_wait_time = 600
    start_time = time.time()

    while True:
        if time.time() - start_time > max_wait_time:
            print(f"❌ Timeout ao aguardar {job_name}")
            return None

        try:
            job = async_job.api_get()
        except Exception as e:
            print(f"❌ Erro ao buscar status: {e}")
            return None

        status = job.get(AdReportRun.Field.async_status, 'Unknown')
        percent = job.get(AdReportRun.Field.async_percent_completion, 0)

        print(f"   Status: {status} - {percent}% concluído", end='\r')

        if status == 'Job Completed':
            print(f"\n✅ {job_name} concluído!")
            return job

        if status == 'Job Failed':
            print(f"\n❌ {job_name} falhou!")
            return None

        time.sleep(2)


def get_insights_with_retry(account, params, fields, level_name):
    """Obtém insights com retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            print(f"\n📊 Iniciando requisição ASYNC para {level_name}...")
            print(f"   Período: {params['time_range']['since']} a {params['time_range']['until']}")
            print(f"   Level: {params['level']}")

            async_job = account.get_insights(
                fields=fields,
                params=params,
                is_async=True
            )

            completed_job = wait_for_async_job(async_job, f"{level_name} insights")

            if not completed_job:
                raise Exception(f"Job assíncrono falhou para {level_name}")

            print(f"📥 Baixando resultados de {level_name}...")
            insights = completed_job.get_result()

            results = []
            for insight in insights:
                results.append(insight.export_all_data())

            print(f"✅ Obtidos {len(results)} registros de {level_name}")
            return results

        except Exception as e:
            error_msg = str(e)

            if 'rate limit' in error_msg.lower() or 'error code 613' in error_msg.lower():
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (attempt + 1)
                    print(f"⚠️  Rate limit. Aguardando {wait_time}s...")
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
    """Parse de actions e conversions."""
    parsed = {}

    if actions_list:
        for action in actions_list:
            action_type = action.get('action_type', '')
            value = action.get('value', '0')

            try:
                value_int = int(float(value))
            except (ValueError, TypeError):
                value_int = 0

            if action_type == 'offsite_conversion.fb_pixel_lead':
                parsed['Leads'] = value_int

    if conversions_list:
        for conversion in conversions_list:
            action_type = conversion.get('action_type', '')
            value = conversion.get('value', '0')

            try:
                value_int = int(float(value))
            except (ValueError, TypeError):
                value_int = 0

            if 'Faixa A' in action_type or 'FaixaA' in action_type:
                parsed['Faixa_A'] = value_int
            elif action_type == 'offsite_conversion.fb_pixel_custom.LeadQualified':
                parsed['LeadQualified'] = value_int
            elif action_type == 'offsite_conversion.fb_pixel_custom.LeadQualifiedHighQuality':
                parsed['LeadQualifiedHighQuality'] = value_int

    return parsed


def aggregate_by_campaign(insights_data):
    """
    Agrega insights por campanha (soma todo o período).

    Args:
        insights_data: Lista de insights diários

    Returns:
        Lista de insights agregados por campanha
    """
    if not insights_data:
        return []

    # Agrupar por campaign_id
    campaigns = {}

    for insight in insights_data:
        campaign_id = insight.get('campaign_id')

        if campaign_id not in campaigns:
            # Primeira vez vendo essa campanha
            campaigns[campaign_id] = {
                'campaign_id': campaign_id,
                'campaign_name': insight.get('campaign_name', ''),
                'spend': 0.0,
                'actions': {},
                'conversions': {},
                'date_start': insight.get('date_start', DATE_START),
                'date_stop': insight.get('date_stop', DATE_END),
            }

        # Somar spend
        campaigns[campaign_id]['spend'] += float(insight.get('spend', 0))

        # Agregar actions
        actions = insight.get('actions', [])
        for action in actions:
            action_type = action.get('action_type', '')
            value = int(float(action.get('value', 0)))

            if action_type not in campaigns[campaign_id]['actions']:
                campaigns[campaign_id]['actions'][action_type] = 0
            campaigns[campaign_id]['actions'][action_type] += value

        # Agregar conversions
        conversions = insight.get('conversions', [])
        for conversion in conversions:
            action_type = conversion.get('action_type', '')
            value = int(float(conversion.get('value', 0)))

            if action_type not in campaigns[campaign_id]['conversions']:
                campaigns[campaign_id]['conversions'][action_type] = 0
            campaigns[campaign_id]['conversions'][action_type] += value

    # Converter de volta para lista
    aggregated = []
    for campaign_id, data in campaigns.items():
        # Reconstruir listas de actions e conversions
        actions_list = [{'action_type': k, 'value': str(v)} for k, v in data['actions'].items()]
        conversions_list = [{'action_type': k, 'value': str(v)} for k, v in data['conversions'].items()]

        aggregated.append({
            'campaign_id': campaign_id,
            'campaign_name': data['campaign_name'],
            'date_start': DATE_START,
            'date_stop': DATE_END,
            'spend': str(data['spend']),
            'actions': actions_list,
            'conversions': conversions_list,
        })

    return aggregated


def aggregate_by_adset(insights_data):
    """Agrega insights por adset."""
    if not insights_data:
        return []

    adsets = {}

    for insight in insights_data:
        adset_id = insight.get('adset_id')

        if adset_id not in adsets:
            adsets[adset_id] = {
                'campaign_id': insight.get('campaign_id'),
                'campaign_name': insight.get('campaign_name', ''),
                'adset_id': adset_id,
                'adset_name': insight.get('adset_name', ''),
                'spend': 0.0,
                'actions': {},
                'conversions': {},
            }

        adsets[adset_id]['spend'] += float(insight.get('spend', 0))

        for action in insight.get('actions', []):
            action_type = action.get('action_type', '')
            value = int(float(action.get('value', 0)))
            if action_type not in adsets[adset_id]['actions']:
                adsets[adset_id]['actions'][action_type] = 0
            adsets[adset_id]['actions'][action_type] += value

        for conversion in insight.get('conversions', []):
            action_type = conversion.get('action_type', '')
            value = int(float(conversion.get('value', 0)))
            if action_type not in adsets[adset_id]['conversions']:
                adsets[adset_id]['conversions'][action_type] = 0
            adsets[adset_id]['conversions'][action_type] += value

    aggregated = []
    for adset_id, data in adsets.items():
        actions_list = [{'action_type': k, 'value': str(v)} for k, v in data['actions'].items()]
        conversions_list = [{'action_type': k, 'value': str(v)} for k, v in data['conversions'].items()]

        aggregated.append({
            'campaign_id': data['campaign_id'],
            'campaign_name': data['campaign_name'],
            'adset_id': adset_id,
            'adset_name': data['adset_name'],
            'date_start': DATE_START,
            'date_stop': DATE_END,
            'spend': str(data['spend']),
            'actions': actions_list,
            'conversions': conversions_list,
        })

    return aggregated


def aggregate_by_ad(insights_data):
    """Agrega insights por ad."""
    if not insights_data:
        return []

    ads = {}

    for insight in insights_data:
        ad_id = insight.get('ad_id')

        if ad_id not in ads:
            ads[ad_id] = {
                'campaign_id': insight.get('campaign_id'),
                'campaign_name': insight.get('campaign_name', ''),
                'adset_id': insight.get('adset_id'),
                'adset_name': insight.get('adset_name', ''),
                'ad_id': ad_id,
                'ad_name': insight.get('ad_name', ''),
                'spend': 0.0,
                'actions': {},
                'conversions': {},
            }

        ads[ad_id]['spend'] += float(insight.get('spend', 0))

        for action in insight.get('actions', []):
            action_type = action.get('action_type', '')
            value = int(float(action.get('value', 0)))
            if action_type not in ads[ad_id]['actions']:
                ads[ad_id]['actions'][action_type] = 0
            ads[ad_id]['actions'][action_type] += value

        for conversion in insight.get('conversions', []):
            action_type = conversion.get('action_type', '')
            value = int(float(conversion.get('value', 0)))
            if action_type not in ads[ad_id]['conversions']:
                ads[ad_id]['conversions'][action_type] = 0
            ads[ad_id]['conversions'][action_type] += value

    aggregated = []
    for ad_id, data in ads.items():
        actions_list = [{'action_type': k, 'value': str(v)} for k, v in data['actions'].items()]
        conversions_list = [{'action_type': k, 'value': str(v)} for k, v in data['conversions'].items()]

        aggregated.append({
            'campaign_id': data['campaign_id'],
            'campaign_name': data['campaign_name'],
            'adset_id': data['adset_id'],
            'adset_name': data['adset_name'],
            'ad_id': ad_id,
            'ad_name': data['ad_name'],
            'date_start': DATE_START,
            'date_stop': DATE_END,
            'spend': str(data['spend']),
            'actions': actions_list,
            'conversions': conversions_list,
        })

    return aggregated


def format_as_csv(insights_data, level='campaign', apply_filters=True):
    """
    Formata insights no formato CSV da Meta.

    Args:
        insights_data: Lista de insights
        level: 'campaign', 'adset' ou 'ad'
        apply_filters: Se True, aplica filtros (gasto > 0 e contém 'CAP')
    """
    if not insights_data:
        return pd.DataFrame()

    rows = []

    for insight in insights_data:
        row = {
            'Início dos relatórios': insight.get('date_start', DATE_START),
            'Término dos relatórios': insight.get('date_stop', DATE_END),
            'Nome da campanha': insight.get('campaign_name', ''),
            'Identificação da campanha': insight.get('campaign_id', ''),
            'Orçamento do conjunto de anúncios': '',  # Não disponível via API de insights
            'Tipo de orçamento do conjunto de anúncios': '',
            'Valor usado (BRL)': float(insight.get('spend', 0)),
        }

        if level in ['adset', 'ad']:
            row['Nome do conjunto de anúncios'] = insight.get('adset_name', '')
            row['Identificação do conjunto de anúncios'] = insight.get('adset_id', '')

        if level == 'ad':
            row['Nome do anúncio'] = insight.get('ad_name', '')
            row['Identificação do anúncio'] = insight.get('ad_id', '')

        actions = insight.get('actions', [])
        conversions = insight.get('conversions', [])
        events = parse_events(actions, conversions)

        row['Leads'] = events.get('Leads', '')
        row['Faixa A'] = events.get('Faixa_A', '')
        row['LeadQualified'] = events.get('LeadQualified', '')
        row['LeadQualifiedHighQuality'] = events.get('LeadQualifiedHighQuality', '')

        # Resultados = Leads ou primeiro evento disponível
        row['Resultados'] = events.get('Leads', '')

        # Indicador de resultados
        if conversions and len(conversions) > 0:
            row['Indicador de resultados'] = f"conversions:{conversions[0].get('action_type', '')}"
        elif actions and len(actions) > 0:
            row['Indicador de resultados'] = f"actions:{actions[0].get('action_type', '')}"
        else:
            row['Indicador de resultados'] = ''

        rows.append(row)

    df = pd.DataFrame(rows)

    # Aplicar filtros se solicitado
    if apply_filters and len(df) > 0:
        print(f"   📌 Aplicando filtros (gasto > 0 e contém 'CAP')...")
        print(f"      Antes: {len(df)} registros")

        # Filtro 1: Gasto > 0
        df = df[df['Valor usado (BRL)'] > 0]

        # Filtro 2: Nome da campanha contém 'CAP' (campanhas de captação)
        df = df[df['Nome da campanha'].str.contains('CAP', case=False, na=False)]

        print(f"      Depois: {len(df)} registros")
        print(f"      Removidos: {len(rows) - len(df)} registros")

    return df


# =============================================================================
# MAIN
# =============================================================================

def main():
    # Inicializar API
    FacebookAdsApi.init(access_token=ACCESS_TOKEN, api_version=API_VERSION)
    account = AdAccount(AD_ACCOUNT_ID)

    # Parâmetros base (período agregado, não por dia)
    base_params = {
        'time_range': {
            'since': DATE_START,
            'until': DATE_END
        },
        'time_increment': 'all_days',  # Agregar todo o período
        'filtering': [],
        'breakdowns': [],
    }

    # =============================================================================
    # 1. CAMPANHAS
    # =============================================================================

    params_campaign = {**base_params, 'level': 'campaign'}

    campaigns_insights = get_insights_with_retry(
        account,
        params_campaign,
        CAMPAIGN_FIELDS,
        'Campanhas'
    )

    if campaigns_insights:
        df_campaigns = format_as_csv(campaigns_insights, level='campaign', apply_filters=True)
        print(f"\n✅ DataFrame de campanhas (filtrado): {df_campaigns.shape}")

        output_path = os.path.join(OUTPUT_DIR, 'Ads---Rodolfo-Mori-Campanhas-16-de-dez-de-2025-12-de-jan-de-2026.csv')
        df_campaigns.to_csv(output_path, index=False)
        print(f"💾 Salvo em: {output_path}")

    # =============================================================================
    # 2. CONJUNTOS DE ANÚNCIOS
    # =============================================================================

    params_adset = {**base_params, 'level': 'adset'}

    adsets_insights = get_insights_with_retry(
        account,
        params_adset,
        ADSET_FIELDS,
        'Conjuntos de Anúncios'
    )

    if adsets_insights:
        df_adsets = format_as_csv(adsets_insights, level='adset', apply_filters=True)
        print(f"\n✅ DataFrame de ad sets (filtrado): {df_adsets.shape}")

        output_path = os.path.join(OUTPUT_DIR, 'Ads---Rodolfo-Mori-Conjuntos-de-anúncios-16-de-dez-de-2025-12-de-jan-de-2026.csv')
        df_adsets.to_csv(output_path, index=False)
        print(f"💾 Salvo em: {output_path}")

    # =============================================================================
    # 3. ANÚNCIOS
    # =============================================================================

    params_ad = {**base_params, 'level': 'ad'}

    ads_insights = get_insights_with_retry(
        account,
        params_ad,
        AD_FIELDS,
        'Anúncios'
    )

    if ads_insights:
        df_ads = format_as_csv(ads_insights, level='ad', apply_filters=True)
        print(f"\n✅ DataFrame de ads (filtrado): {df_ads.shape}")

        output_path = os.path.join(OUTPUT_DIR, 'Ads---Rodolfo-Mori-Anúncios-16-de-dez-de-2025-12-de-jan-de-2026.csv')
        df_ads.to_csv(output_path, index=False)
        print(f"💾 Salvo em: {output_path}")

    # =============================================================================
    # RESUMO
    # =============================================================================
    print("\n" + "="*80)
    print("📊 REPLICAÇÃO CONCLUÍDA!")
    print("="*80)
    print(f"✅ Campanhas: {len(campaigns_insights)} registros")
    print(f"✅ Ad Sets: {len(adsets_insights)} registros")
    print(f"✅ Ads: {len(ads_insights)} registros")
    print(f"\n📂 Arquivos salvos em: {OUTPUT_DIR}")
    print("\n🎯 Próximo passo: Compare os arquivos com os originais")


if __name__ == '__main__':
    main()
