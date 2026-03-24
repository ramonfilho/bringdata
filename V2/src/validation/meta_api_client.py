"""
Cliente para extração de dados da Meta Marketing API.

Módulo consolidado para obter relatórios de campanhas, ad sets e anúncios
via Meta Marketing API, com as mesmas métricas e filtros dos relatórios manuais.

Uso:
    from src.validation.meta_api_client import MetaAPIClient

    client = MetaAPIClient()

    # Extrair campanhas
    df = client.get_campaigns(
        date_start='2025-12-16',
        date_end='2026-01-12',
        apply_filters=True
    )
"""

import time
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from api.meta_config import META_CONFIG

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adreportrun import AdReportRun


class MetaAPIClient:
    """Cliente para extração de dados da Meta Marketing API."""

    # Configuração
    DEFAULT_ACCOUNT_ID = 'act_188005769808959'  # Rodolfo Mori
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # segundos
    MAX_WAIT_TIME = 600  # 10 minutos

    # Campos para cada nível
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

    CAMPAIGN_FIELDS = BASE_FIELDS + ['objective']
    ADSET_FIELDS = CAMPAIGN_FIELDS + ['adset_id', 'adset_name']
    AD_FIELDS = ADSET_FIELDS + ['ad_id', 'ad_name']

    def __init__(self, account_id: Optional[str] = None, api_version: Optional[str] = None):
        """
        Inicializa o cliente da Meta API.

        Args:
            account_id: ID da conta de anúncios (padrão: Rodolfo Mori)
            api_version: Versão da API (padrão: v18.0 de meta_config)
        """
        self.account_id = account_id or self.DEFAULT_ACCOUNT_ID
        self.api_version = api_version or META_CONFIG['api_version']
        self.access_token = META_CONFIG['access_token']

        # Inicializar API
        FacebookAdsApi.init(
            access_token=self.access_token,
            api_version=self.api_version
        )

        self.account = AdAccount(self.account_id)

    def _wait_for_async_job(self, async_job, job_name: str = "Job") -> Optional[AdReportRun]:
        """
        Aguarda conclusão de job assíncrono.

        Args:
            async_job: Job assíncrono
            job_name: Nome do job para logging

        Returns:
            Job completado ou None se falhou
        """
        start_time = time.time()

        while True:
            # Verificar timeout
            if time.time() - start_time > self.MAX_WAIT_TIME:
                print(f" Timeout ao aguardar {job_name}")
                return None

            try:
                job = async_job.api_get()
            except Exception as e:
                print(f" Erro ao buscar status: {e}")
                return None

            status = job.get(AdReportRun.Field.async_status, 'Unknown')
            percent = job.get(AdReportRun.Field.async_percent_completion, 0)

            # Status silencioso para não poluir logs

            if status == 'Job Completed':
                return job

            if status == 'Job Failed':
                print(f" {job_name} falhou!")
                return None

            time.sleep(2)

    def _get_insights_with_retry(
        self,
        params: Dict,
        fields: List[str],
        level_name: str
    ) -> List[Dict]:
        """
        Obtém insights com retry logic.

        Args:
            params: Parâmetros da requisição
            fields: Lista de campos a extrair
            level_name: Nome do nível (para logging)

        Returns:
            Lista de insights
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                # Fazer requisição assíncrona
                async_job = self.account.get_insights(
                    fields=fields,
                    params=params,
                    is_async=True
                )

                # Aguardar conclusão
                completed_job = self._wait_for_async_job(async_job, f"{level_name}")

                if not completed_job:
                    raise Exception(f"Job assíncrono falhou")

                # Obter resultados
                insights = completed_job.get_result()

                results = []
                for insight in insights:
                    data = insight.export_all_data()
                    # CORREÇÃO: Forçar account_id se não retornado pela API
                    # A Meta API nem sempre inclui account_id nos insights, mesmo solicitado
                    if 'account_id' not in data or not data.get('account_id'):
                        # Garantir que tem prefixo act_
                        account_id = self.account_id if self.account_id.startswith('act_') else f"act_{self.account_id}"
                        data['account_id'] = account_id
                    else:
                        # Se veio da API, garantir formato consistente (com prefixo)
                        if not str(data['account_id']).startswith('act_'):
                            data['account_id'] = f"act_{data['account_id']}"
                    results.append(data)

                return results

            except Exception as e:
                error_msg = str(e)

                # Rate limit
                if 'rate limit' in error_msg.lower() or 'error code 613' in error_msg.lower():
                    if attempt < self.MAX_RETRIES - 1:
                        wait_time = self.RETRY_DELAY * (attempt + 1)
                        print(f"  Rate limit. Aguardando {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f" Rate limit persistente")
                        return []
                else:
                    print(f" Erro: {e}")
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(self.RETRY_DELAY)
                        continue
                    return []

        return []

    @staticmethod
    def _parse_events(actions_list: List[Dict], conversions_list: List[Dict]) -> Dict:
        """
        Parse de actions e conversions.

        Args:
            actions_list: Lista de actions da API
            conversions_list: Lista de conversions da API

        Returns:
            Dict com eventos parseados
        """
        parsed = {}

        # Actions (eventos padrão)
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

        # Conversions (eventos customizados)
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

    def _format_insights_to_dataframe(
        self,
        insights_data: List[Dict],
        level: str,
        date_start: str,
        date_end: str,
        apply_filters: bool = True
    ) -> pd.DataFrame:
        """
        Formata insights em DataFrame.

        Args:
            insights_data: Lista de insights
            level: 'campaign', 'adset' ou 'ad'
            date_start: Data de início do período
            date_end: Data de fim do período
            apply_filters: Se True, aplica filtros (gasto > 0 e contém 'CAP')

        Returns:
            DataFrame formatado
        """
        if not insights_data:
            return pd.DataFrame()

        rows = []

        for insight in insights_data:
            row = {
                'Início dos relatórios': insight.get('date_start', date_start),
                'Término dos relatórios': insight.get('date_stop', date_end),
                'Nome da campanha': insight.get('campaign_name', ''),
                'Identificação da campanha': insight.get('campaign_id', ''),
                'Valor usado (BRL)': float(insight.get('spend', 0)),
                'account_id': insight.get('account_id', ''),  # CRÍTICO: necessário para mapear account_name
            }

            # Campos específicos por nível
            if level in ['adset', 'ad']:
                row['Nome do conjunto de anúncios'] = insight.get('adset_name', '')
                row['Identificação do conjunto de anúncios'] = insight.get('adset_id', '')

            if level == 'ad':
                row['Nome do anúncio'] = insight.get('ad_name', '')
                row['Identificação do anúncio'] = insight.get('ad_id', '')

            # Parse de eventos
            actions = insight.get('actions', [])
            conversions = insight.get('conversions', [])
            events = self._parse_events(actions, conversions)

            row['Leads'] = events.get('Leads', '')
            row['Faixa A'] = events.get('Faixa_A', '')
            row['LeadQualified'] = events.get('LeadQualified', '')
            row['LeadQualifiedHighQuality'] = events.get('LeadQualifiedHighQuality', '')

            # Resultados
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

        # Aplicar filtros
        if apply_filters and len(df) > 0:
            # Filtro 1: Gasto > 0
            df = df[df['Valor usado (BRL)'] > 0]

            # Filtro 2: Campanhas de captação (contém 'CAP')
            df = df[df['Nome da campanha'].str.contains('CAP', case=False, na=False)]

        return df

    def get_campaigns(
        self,
        date_start: str,
        date_end: str,
        apply_filters: bool = True
    ) -> pd.DataFrame:
        """
        Obtém dados de campanhas.

        Args:
            date_start: Data de início (formato: YYYY-MM-DD)
            date_end: Data de fim (formato: YYYY-MM-DD)
            apply_filters: Se True, aplica filtros (gasto > 0 e contém 'CAP')

        Returns:
            DataFrame com dados de campanhas
        """
        params = {
            'time_range': {
                'since': date_start,
                'until': date_end
            },
            'level': 'campaign',
            'time_increment': 'all_days',
            'filtering': [],
            'breakdowns': [],
        }

        insights = self._get_insights_with_retry(
            params,
            self.CAMPAIGN_FIELDS,
            'Campanhas'
        )

        return self._format_insights_to_dataframe(
            insights,
            level='campaign',
            date_start=date_start,
            date_end=date_end,
            apply_filters=apply_filters
        )

    def get_adsets(
        self,
        date_start: str,
        date_end: str,
        apply_filters: bool = True
    ) -> pd.DataFrame:
        """
        Obtém dados de conjuntos de anúncios.

        Args:
            date_start: Data de início (formato: YYYY-MM-DD)
            date_end: Data de fim (formato: YYYY-MM-DD)
            apply_filters: Se True, aplica filtros (gasto > 0 e contém 'CAP')

        Returns:
            DataFrame com dados de ad sets
        """
        params = {
            'time_range': {
                'since': date_start,
                'until': date_end
            },
            'level': 'adset',
            'time_increment': 'all_days',
            'filtering': [],
            'breakdowns': [],
        }

        insights = self._get_insights_with_retry(
            params,
            self.ADSET_FIELDS,
            'Ad Sets'
        )

        return self._format_insights_to_dataframe(
            insights,
            level='adset',
            date_start=date_start,
            date_end=date_end,
            apply_filters=apply_filters
        )

    def get_ads(
        self,
        date_start: str,
        date_end: str,
        apply_filters: bool = True
    ) -> pd.DataFrame:
        """
        Obtém dados de anúncios.

        Args:
            date_start: Data de início (formato: YYYY-MM-DD)
            date_end: Data de fim (formato: YYYY-MM-DD)
            apply_filters: Se True, aplica filtros (gasto > 0 e contém 'CAP')

        Returns:
            DataFrame com dados de ads
        """
        params = {
            'time_range': {
                'since': date_start,
                'until': date_end
            },
            'level': 'ad',
            'time_increment': 'all_days',
            'filtering': [],
            'breakdowns': [],
        }

        insights = self._get_insights_with_retry(
            params,
            self.AD_FIELDS,
            'Ads'
        )

        return self._format_insights_to_dataframe(
            insights,
            level='ad',
            date_start=date_start,
            date_end=date_end,
            apply_filters=apply_filters
        )

    def get_all_levels(
        self,
        date_start: str,
        date_end: str,
        apply_filters: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Obtém dados de todos os níveis (campanhas, ad sets, ads).

        Args:
            date_start: Data de início (formato: YYYY-MM-DD)
            date_end: Data de fim (formato: YYYY-MM-DD)
            apply_filters: Se True, aplica filtros (gasto > 0 e contém 'CAP')

        Returns:
            Dict com 'campaigns', 'adsets', 'ads' como chaves
        """
        print(f" Extraindo dados da Meta API")
        print(f"   Período: {date_start} a {date_end}")
        print(f"   Filtros: {'Sim (gasto > 0, contém CAP)' if apply_filters else 'Não'}")

        campaigns = self.get_campaigns(date_start, date_end, apply_filters)
        print(f"    Campanhas: {len(campaigns)} registros")

        adsets = self.get_adsets(date_start, date_end, apply_filters)
        print(f"    Ad Sets: {len(adsets)} registros")

        ads = self.get_ads(date_start, date_end, apply_filters)
        print(f"    Ads: {len(ads)} registros")

        return {
            'campaigns': campaigns,
            'adsets': adsets,
            'ads': ads
        }



    def get_daily_campaign_metrics(
        self,
        date_start: str,
        date_end: str,
        apply_filters: bool = True,
    ) -> pd.DataFrame:
        """
        Busca métricas diárias por campanha para feature engineering.

        Uma linha por (campanha, dia). Inclui impressions, reach, frequency.
        Usado como fallback quando utm_content não identifica o anúncio.

        Retorna colunas:
            campaign_id_15, campaign_name, date,
            spend_dia, impressions_dia, reach_dia, frequency_dia,
            leads_dia, cpl_dia, cpm_dia
        """
        FIELDS = [
            'campaign_id', 'campaign_name', 'date_start',
            'spend', 'impressions', 'reach', 'frequency', 'actions',
        ]
        params = {
            'time_range': {'since': date_start, 'until': date_end},
            'level': 'campaign',
            'time_increment': 1,
            'filtering': [],
            'breakdowns': [],
        }
        return self._parse_daily_insights(
            self._get_insights_with_retry(params, FIELDS, 'DailyCampaign'),
            level='campaign',
            apply_filters=apply_filters,
        )

    def get_daily_adset_metrics(
        self,
        date_start: str,
        date_end: str,
        apply_filters: bool = True,
    ) -> pd.DataFrame:
        """
        Busca métricas diárias por adset para feature engineering.

        Retorna colunas:
            adset_id, adset_name, campaign_id, date,
            spend_dia, impressions_dia, reach_dia, frequency_dia,
            leads_dia, cpl_dia, cpm_dia
        """
        FIELDS = [
            'adset_id', 'adset_name',
            'campaign_id', 'campaign_name', 'date_start',
            'spend', 'impressions', 'reach', 'frequency', 'actions',
        ]
        params = {
            'time_range': {'since': date_start, 'until': date_end},
            'level': 'adset',
            'time_increment': 1,
            'filtering': [],
            'breakdowns': [],
        }
        return self._parse_daily_insights(
            self._get_insights_with_retry(params, FIELDS, 'DailyAdset'),
            level='adset',
            apply_filters=apply_filters,
        )

    def get_ad_adset_mapping(
        self,
        date_start: str,
        date_end: str,
    ) -> pd.DataFrame:
        """
        Retorna mapeamento ad_name → adset_id para o período.

        Usado para enriquecer leads via utm_content:
            utm_content → ad_name → adset_id → métricas diárias de adset

        Retorna colunas:
            ad_id, ad_name, adset_id, adset_name, campaign_id
        """
        FIELDS = ['ad_id', 'ad_name', 'adset_id', 'adset_name', 'campaign_id', 'campaign_name']
        params = {
            'time_range': {'since': date_start, 'until': date_end},
            'level': 'ad',
            'time_increment': 'all_days',
            'filtering': [],
            'breakdowns': [],
        }
        insights = self._get_insights_with_retry(params, FIELDS, 'AdAdsetMapping')
        if not insights:
            return pd.DataFrame()

        rows = []
        for ins in insights:
            if 'CAP' not in ins.get('campaign_name', '').upper():
                continue
            rows.append({
                'ad_id':       ins.get('ad_id', ''),
                'ad_name':     ins.get('ad_name', ''),
                'adset_id':    ins.get('adset_id', ''),
                'adset_name':  ins.get('adset_name', ''),
                'campaign_id': ins.get('campaign_id', ''),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _parse_daily_insights(
        insights: list,
        level: str,
        apply_filters: bool,
    ) -> pd.DataFrame:
        """
        Converte lista de insights diários em DataFrame normalizado.
        Compartilhado por get_daily_campaign_metrics e get_daily_adset_metrics.
        """
        if not insights:
            return pd.DataFrame()

        rows = []
        for ins in insights:
            spend       = float(ins.get('spend', 0) or 0)
            impressions = int(ins.get('impressions', 0) or 0)
            frequency   = float(ins.get('frequency', 0) or 0)
            reach       = int(ins.get('reach', 0) or 0)
            campaign_name = ins.get('campaign_name', '')

            leads = 0
            for action in (ins.get('actions') or []):
                if action.get('action_type') == 'offsite_conversion.fb_pixel_lead':
                    try:
                        leads = int(float(action.get('value', 0)))
                    except (ValueError, TypeError):
                        pass

            if apply_filters:
                if spend == 0:
                    continue
                if 'CAP' not in campaign_name.upper():
                    continue

            cpl_dia = round(spend / leads, 2)       if leads > 0       else None
            cpm_dia = round(spend / impressions * 1000, 2) if impressions > 0 else None

            row = {
                'campaign_id':    ins.get('campaign_id', ''),
                'campaign_name':  campaign_name,
                'date':           ins.get('date_start', ''),
                'spend_dia':      round(spend, 2),
                'impressions_dia': impressions,
                'reach_dia':      reach,
                'frequency_dia':  round(frequency, 4),
                'leads_dia':      leads,
                'cpl_dia':        cpl_dia,
                'cpm_dia':        cpm_dia,
            }

            if level == 'adset':
                row['adset_id']   = ins.get('adset_id', '')
                row['adset_name'] = ins.get('adset_name', '')
            else:
                campaign_id = str(ins.get('campaign_id', ''))
                row['campaign_id_15'] = campaign_id[:15]

            rows.append(row)

        return pd.DataFrame(rows)

# =============================================================================
# FUNÇÃO AUXILIAR PARA USO STANDALONE
# =============================================================================

def extract_meta_reports(
    date_start: str,
    date_end: str,
    output_dir: Optional[str] = None,
    apply_filters: bool = True
) -> Dict[str, pd.DataFrame]:
    """
    Função auxiliar para extrair relatórios da Meta.

    Uso standalone:
        from src.validation.meta_api_client import extract_meta_reports

        data = extract_meta_reports(
            date_start='2025-12-16',
            date_end='2026-01-12'
        )

        # Acessar DataFrames
        df_campaigns = data['campaigns']

    Args:
        date_start: Data de início (YYYY-MM-DD)
        date_end: Data de fim (YYYY-MM-DD)
        output_dir: Se fornecido, salva CSVs neste diretório
        apply_filters: Se True, aplica filtros (gasto > 0 e contém 'CAP')

    Returns:
        Dict com DataFrames de campaigns, adsets e ads
    """
    client = MetaAPIClient()
    data = client.get_all_levels(date_start, date_end, apply_filters)

    # Salvar CSVs se output_dir fornecido
    if output_dir:
        import os
        os.makedirs(output_dir, exist_ok=True)

        data['campaigns'].to_csv(
            os.path.join(output_dir, 'meta_campaigns.csv'),
            index=False
        )
        data['adsets'].to_csv(
            os.path.join(output_dir, 'meta_adsets.csv'),
            index=False
        )
        data['ads'].to_csv(
            os.path.join(output_dir, 'meta_ads.csv'),
            index=False
        )

        print(f"\n Arquivos salvos em: {output_dir}")

    return data



if __name__ == '__main__':
    # Exemplo de uso standalone
    import sys

    # Usar período de teste ou dos argumentos
    if len(sys.argv) == 3:
        date_start = sys.argv[1]
        date_end = sys.argv[2]
    else:
        # Padrão: últimos 7 dias
        date_end = datetime.now().strftime('%Y-%m-%d')
        date_start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    print(f"Extraindo dados: {date_start} a {date_end}")

    data = extract_meta_reports(
        date_start=date_start,
        date_end=date_end,
        output_dir='files/validation/meta_reports/test_output'
    )

    print(f"\n Extração concluída!")
    print(f"   Campanhas: {len(data['campaigns'])} registros")
    print(f"   Ad Sets: {len(data['adsets'])} registros")
    print(f"   Ads: {len(data['ads'])} registros")
