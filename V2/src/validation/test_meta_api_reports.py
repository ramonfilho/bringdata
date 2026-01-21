"""
Script de teste para obter dados de relatórios da Meta via API.

Objetivo: Verificar se conseguimos obter os mesmos dados dos relatórios
CSV exportados manualmente, mas via API (Marketing API).

Requisitos:
- facebook-business SDK: pip install facebook-business
- Token de acesso com permissões: ads_read, ads_management

Dados necessários:
- Access Token
- Ad Account ID (act_188005769808959)
"""

import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import json

# Adicionar path do projeto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

try:
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount
    from facebook_business.adobjects.campaign import Campaign
    from facebook_business.adobjects.adset import AdSet
    from facebook_business.adobjects.ad import Ad
    from facebook_business.adobjects.adsinsights import AdsInsights
except ImportError:
    print("❌ facebook-business não instalado")
    print("Execute: pip install facebook-business")
    sys.exit(1)


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

# Credenciais (ajustar conforme necessário)
ACCESS_TOKEN = os.getenv('META_ACCESS_TOKEN', 'SEU_TOKEN_AQUI')
AD_ACCOUNT_ID = 'act_188005769808959'  # Los Angeles Producciones LTDA

# Período de teste (últimas 7 dias)
DATE_START = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
DATE_END = datetime.now().strftime('%Y-%m-%d')


# =============================================================================
# CAMPOS E MÉTRICAS
# =============================================================================

# Campos base para todos os níveis
BASE_FIELDS = [
    'account_id',
    'account_name',
    'date_start',
    'date_stop',
    'spend',
]

# Métricas/eventos customizados que precisamos
# Baseado nos arquivos CSV: Leads, Faixa A, LeadQualified, LeadQualifiedHighQuality
CONVERSION_METRICS = [
    'actions',  # Contém todos os eventos de conversão
    'action_values',  # Valores das conversões
]

# Campos específicos por nível
CAMPAIGN_FIELDS = BASE_FIELDS + [
    'campaign_id',
    'campaign_name',
    'objective',
    'budget_remaining',
    'daily_budget',
    'lifetime_budget',
] + CONVERSION_METRICS

ADSET_FIELDS = CAMPAIGN_FIELDS + [
    'adset_id',
    'adset_name',
    'targeting',
]

AD_FIELDS = ADSET_FIELDS + [
    'ad_id',
    'ad_name',
    'creative',
]


# =============================================================================
# FUNÇÕES DE EXTRAÇÃO
# =============================================================================

def initialize_api(access_token):
    """Inicializa a API do Facebook."""
    try:
        FacebookAdsApi.init(access_token=access_token)
        print("✅ API inicializada com sucesso")
        return True
    except Exception as e:
        print(f"❌ Erro ao inicializar API: {e}")
        return False


def get_campaigns_insights(account_id, date_start, date_stop, fields):
    """
    Obtém insights de campanhas no período especificado.

    Returns:
        List[dict]: Lista de insights de campanhas
    """
    print(f"\n📊 Buscando insights de CAMPANHAS...")
    print(f"   Período: {date_start} a {date_stop}")

    try:
        account = AdAccount(f'act_{account_id}')

        params = {
            'time_range': {
                'since': date_start,
                'until': date_stop
            },
            'level': 'campaign',
            'time_increment': 1,  # Por dia
        }

        insights = account.get_insights(
            fields=fields,
            params=params
        )

        results = []
        for insight in insights:
            results.append(insight.export_all_data())

        print(f"✅ Encontradas {len(results)} linhas de insights de campanhas")
        return results

    except Exception as e:
        print(f"❌ Erro ao buscar insights de campanhas: {e}")
        return []


def get_adsets_insights(account_id, date_start, date_stop, fields):
    """
    Obtém insights de conjuntos de anúncios no período especificado.

    Returns:
        List[dict]: Lista de insights de adsets
    """
    print(f"\n📊 Buscando insights de CONJUNTOS DE ANÚNCIOS...")
    print(f"   Período: {date_start} a {date_stop}")

    try:
        account = AdAccount(f'act_{account_id}')

        params = {
            'time_range': {
                'since': date_start,
                'until': date_stop
            },
            'level': 'adset',
            'time_increment': 1,  # Por dia
        }

        insights = account.get_insights(
            fields=fields,
            params=params
        )

        results = []
        for insight in insights:
            results.append(insight.export_all_data())

        print(f"✅ Encontradas {len(results)} linhas de insights de adsets")
        return results

    except Exception as e:
        print(f"❌ Erro ao buscar insights de adsets: {e}")
        return []


def get_ads_insights(account_id, date_start, date_stop, fields):
    """
    Obtém insights de anúncios no período especificado.

    Returns:
        List[dict]: Lista de insights de ads
    """
    print(f"\n📊 Buscando insights de ANÚNCIOS...")
    print(f"   Período: {date_start} a {date_stop}")

    try:
        account = AdAccount(f'act_{account_id}')

        params = {
            'time_range': {
                'since': date_start,
                'until': date_stop
            },
            'level': 'ad',
            'time_increment': 1,  # Por dia
        }

        insights = account.get_insights(
            fields=fields,
            params=params
        )

        results = []
        for insight in insights:
            results.append(insight.export_all_data())

        print(f"✅ Encontradas {len(results)} linhas de insights de ads")
        return results

    except Exception as e:
        print(f"❌ Erro ao buscar insights de ads: {e}")
        return []


def parse_conversion_actions(actions_list):
    """
    Parse das actions para extrair eventos customizados.

    Args:
        actions_list: Lista de dicts com action_type e value

    Returns:
        dict: Mapeamento de action_type -> value
    """
    if not actions_list:
        return {}

    parsed = {}
    for action in actions_list:
        action_type = action.get('action_type', '')
        value = action.get('value', 0)

        # Mapear os tipos de ação relevantes
        if 'lead' in action_type.lower():
            parsed['Leads'] = int(value)
        elif 'Faixa A' in action_type:
            parsed['Faixa_A'] = int(value)
        elif 'LeadQualified' in action_type:
            if 'HighQuality' in action_type:
                parsed['LeadQualifiedHighQuality'] = int(value)
            else:
                parsed['LeadQualified'] = int(value)

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
    formatted_rows = []

    for insight in insights_data:
        row = {
            'Início dos relatórios': insight.get('date_start', ''),
            'Término dos relatórios': insight.get('date_stop', ''),
            'Valor usado (BRL)': float(insight.get('spend', 0)),
        }

        # Campos específicos por nível
        if level == 'campaign':
            row['Nome da campanha'] = insight.get('campaign_name', '')
            row['Identificação da campanha'] = insight.get('campaign_id', '')
            row['Orçamento do conjunto de anúncios'] = insight.get('daily_budget', insight.get('lifetime_budget', ''))

        elif level == 'adset':
            row['Nome da campanha'] = insight.get('campaign_name', '')
            row['Identificação da campanha'] = insight.get('campaign_id', '')
            row['Nome do conjunto de anúncios'] = insight.get('adset_name', '')
            row['Identificação do conjunto de anúncios'] = insight.get('adset_id', '')
            row['Orçamento do conjunto de anúncios'] = insight.get('daily_budget', insight.get('lifetime_budget', ''))

        elif level == 'ad':
            row['Nome da campanha'] = insight.get('campaign_name', '')
            row['Identificação da campanha'] = insight.get('campaign_id', '')
            row['Nome do conjunto de anúncios'] = insight.get('adset_name', '')
            row['Identificação do conjunto de anúncios'] = insight.get('adset_id', '')
            row['Nome do anúncio'] = insight.get('ad_name', '')
            row['Identificação do anúncio'] = insight.get('ad_id', '')
            row['Orçamento do conjunto de anúncios'] = insight.get('daily_budget', insight.get('lifetime_budget', ''))

        # Parse de conversões
        actions = insight.get('actions', [])
        conversions = parse_conversion_actions(actions)

        row['Leads'] = conversions.get('Leads', '')
        row['Faixa A'] = conversions.get('Faixa_A', '')
        row['LeadQualified'] = conversions.get('LeadQualified', '')
        row['LeadQualifiedHighQuality'] = conversions.get('LeadQualifiedHighQuality', '')

        formatted_rows.append(row)

    return pd.DataFrame(formatted_rows)


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

def main():
    """Função principal de teste."""
    print("="*80)
    print("🔍 TESTE DE EXTRAÇÃO DE DADOS VIA META MARKETING API")
    print("="*80)

    # Verificar token
    if ACCESS_TOKEN == 'SEU_TOKEN_AQUI' or not ACCESS_TOKEN:
        print("\n❌ ERRO: Configure o META_ACCESS_TOKEN")
        print("\nPara obter um token de acesso:")
        print("1. Acesse: https://developers.facebook.com/tools/explorer/")
        print("2. Selecione o App 'Smart Ads' (ou crie um)")
        print("3. Gere um token com permissões: ads_read, ads_management")
        print("4. Defina a variável de ambiente: export META_ACCESS_TOKEN='seu_token'")
        return

    # Inicializar API
    if not initialize_api(ACCESS_TOKEN):
        return

    print(f"\n📅 Período de teste: {DATE_START} a {DATE_END}")
    print(f"🏢 Ad Account: {AD_ACCOUNT_ID}")

    # =============================================================================
    # TESTE 1: Insights de Campanhas
    # =============================================================================
    campaigns_insights = get_campaigns_insights(
        AD_ACCOUNT_ID.replace('act_', ''),
        DATE_START,
        DATE_END,
        CAMPAIGN_FIELDS
    )

    if campaigns_insights:
        print(f"\n📄 Exemplo de dados brutos (primeira campanha):")
        print(json.dumps(campaigns_insights[0], indent=2, default=str))

        # Formatar como CSV
        df_campaigns = format_insights_as_csv(campaigns_insights, level='campaign')
        print(f"\n✅ DataFrame de campanhas criado: {df_campaigns.shape}")
        print(f"\nColunas disponíveis:")
        print(df_campaigns.columns.tolist())
        print(f"\nPrimeiras linhas:")
        print(df_campaigns.head())

        # Salvar CSV de teste
        output_path = '/Users/ramonmoreira/Desktop/smart_ads/V2/files/validation/meta_reports/test_api_campaigns.csv'
        df_campaigns.to_csv(output_path, index=False)
        print(f"\n💾 Salvo em: {output_path}")

    # =============================================================================
    # TESTE 2: Insights de Ad Sets
    # =============================================================================
    adsets_insights = get_adsets_insights(
        AD_ACCOUNT_ID.replace('act_', ''),
        DATE_START,
        DATE_END,
        ADSET_FIELDS
    )

    if adsets_insights:
        df_adsets = format_insights_as_csv(adsets_insights, level='adset')
        print(f"\n✅ DataFrame de adsets criado: {df_adsets.shape}")

        output_path = '/Users/ramonmoreira/Desktop/smart_ads/V2/files/validation/meta_reports/test_api_adsets.csv'
        df_adsets.to_csv(output_path, index=False)
        print(f"💾 Salvo em: {output_path}")

    # =============================================================================
    # TESTE 3: Insights de Ads
    # =============================================================================
    ads_insights = get_ads_insights(
        AD_ACCOUNT_ID.replace('act_', ''),
        DATE_START,
        DATE_END,
        AD_FIELDS
    )

    if ads_insights:
        df_ads = format_insights_as_csv(ads_insights, level='ad')
        print(f"\n✅ DataFrame de ads criado: {df_ads.shape}")

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
    print("3. Ajuste os campos se necessário")
    print("4. Se OK, implemente na automação de validação")


if __name__ == '__main__':
    main()
