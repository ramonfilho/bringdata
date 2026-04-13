"""
Módulo para cálculo de métricas de performance de campanhas e decis.

Calcula todas as métricas necessárias para validação:
- Por campanha: leads, conversões, CPL, ROAS, margem
- Por decil: performance real vs esperada (Guru vs Guru+TMB)
- Integração com Meta API para buscar custos
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, List
import logging
import requests
from datetime import datetime

# Importar integrações existentes
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from api.meta_integration import MetaAdsIntegration
from api.economic_metrics import calculate_cpl, calculate_contribution_margin
from api.business_config import CONVERSION_RATES

# Importar módulo de ajuste TMB
from src.validation.tmb_adjuster import (
    add_adjusted_metrics_to_campaign_stats,
    calculate_overall_adjusted_stats,
    FATOR_TMB_MEDIO
)

logger = logging.getLogger(__name__)


class CampaignMetricsCalculator:
    """
    Calcula métricas de performance por campanha.

    Busca custos via Meta API e calcula:
    - CPL (Custo por Lead)
    - Taxa de conversão
    - ROAS (Return on Ad Spend)
    - Margem de Contribuição
    """

    def __init__(self, meta_api_integration: MetaAdsIntegration, product_value: float, use_cache: bool = True):
        """
        Args:
            meta_api_integration: Cliente da Meta Ads API
            product_value: Valor do produto em R$
            use_cache: Se True, usa cache em arquivo para evitar chamadas repetidas à API
        """
        self.meta_api = meta_api_integration
        self.product_value = product_value
        self.use_cache = use_cache
        self.cache_dir = Path(__file__).parent.parent.parent / 'files' / 'validation' / 'cache'
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, prefix: str, account_id: str, period_start: str, period_end: str) -> str:
        """Gera chave única para cache baseado nos parâmetros"""
        import hashlib
        key = f"{prefix}_{account_id}_{period_start}_{period_end}"
        return hashlib.md5(key.encode()).hexdigest()

    def _load_from_cache(self, cache_key: str) -> Dict:
        """Carrega dados do cache se existir"""
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            import json
            with open(cache_file, 'r') as f:
                data = json.load(f)
                logger.info(f"    Cache HIT: {cache_file.name}")
                return data
        return None

    def _save_to_cache(self, cache_key: str, data: Dict):
        """Salva dados no cache"""
        import json
        cache_file = self.cache_dir / f"{cache_key}.json"
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"    Cache SAVED: {cache_file.name}")

    def _get_campaign_leads_from_meta(
        self,
        account_id: str,
        period_start: str,
        period_end: str
    ) -> Dict[str, Dict[str, int]]:
        """
        Busca eventos 'lead' e eventos personalizados por campanha via Meta API.

        Eventos buscados:
        - 'lead': Total de cadastros (padrão)
        - 'offsite_conversion.fb_pixel_custom.LeadQualified': Leads qualificados
        - 'offsite_conversion.fb_pixel_custom.LeadQualifiedHighQuality': Leads alta qualidade
        - 'offsite_conversion.fb_pixel_custom.Faixa A': Leads Faixa A

        Args:
            account_id: ID da conta (formato: act_XXXXXXXXX) ou lista de IDs separados por vírgula
            period_start: Data início (formato YYYY-MM-DD)
            period_end: Data fim (formato YYYY-MM-DD)

        Returns:
            Dict mapeando campaign_id  {evento: contagem}
            Ex: {'120220370119870390': {'lead': 289, 'LeadQualified': 150, 'LeadQualifiedHighQuality': 80}}
        """
        logger.info("    Buscando eventos 'lead' da Meta API...")

        # Tentar carregar do cache primeiro
        if self.use_cache:
            cache_key = self._get_cache_key('leads', account_id, period_start, period_end)
            cached_data = self._load_from_cache(cache_key)
            if cached_data is not None:
                return cached_data

        # Estrutura: {campaign_id: {evento: contagem}}
        campaign_events = {}

        # Eventos personalizados para buscar
        CUSTOM_EVENTS = [
            'offsite_conversion.fb_pixel_custom.LeadQualified',
            'offsite_conversion.fb_pixel_custom.LeadQualifiedHighQuality',
            'offsite_conversion.fb_pixel_custom.Faixa A'
        ]

        # Suportar múltiplas contas
        if isinstance(account_id, str):
            account_ids = [acc.strip() for acc in account_id.split(',')]
        else:
            account_ids = [account_id]

        for acc_id in account_ids:
            # Buscar no nível 'adset' para obter eventos personalizados separadamente
            fields = ['campaign_id', 'campaign_name', 'adset_id', 'adset_name', 'actions', 'action_values', 'impressions']

            try:
                logger.info(f"    Buscando no nível 'adset' para capturar eventos por adset...")
                logger.info(f"    Usando janela de atribuição padrão da conta (não especificada na API)")
                # Usar action_breakdowns para separar eventos individuais
                insights = self.meta_api.get_insights(
                    account_id=acc_id,
                    level='adset',
                    fields=fields,
                    since_date=period_start,
                    until_date=period_end,
                    action_breakdowns=['action_type']
                )

                # Log primeiros insights com datas para debug
                if len(insights) > 0:
                    logger.info(f"    DEBUG - Primeiros 3 insights com datas:")
                    for i, insight in enumerate(insights[:3]):
                        date_start = insight.get('date_start', 'N/A')
                        date_stop = insight.get('date_stop', 'N/A')
                        camp_id = insight.get('campaign_id', 'N/A')[:15]
                        logger.info(f"      Insight #{i+1}: Campaign {camp_id}..., Período: {date_start} a {date_stop}")

                # Processar actions para extrair eventos
                for adset_data in insights:
                    campaign_id = adset_data.get('campaign_id')
                    campaign_name = adset_data.get('campaign_name', '')
                    adset_id = adset_data.get('adset_id')
                    adset_name = adset_data.get('adset_name', 'Unknown')
                    actions = adset_data.get('actions', [])

                    # Log date_start e date_stop para debug
                    date_start = adset_data.get('date_start')
                    date_stop = adset_data.get('date_stop')

                    # Inicializar dicionário de eventos para esta campanha
                    if campaign_id not in campaign_events:
                        campaign_events[campaign_id] = {}

                    # DEBUG: Log all custom event actions for ML campaign
                    if '120234062599950534' in campaign_id and actions:
                        logger.info(f"    DEBUG - Adset {adset_id[:15]}... ({adset_name[:50]}):")
                        for action in actions:
                            action_type = action.get('action_type')
                            value = action.get('value', 0)
                            if 'custom' in action_type or 'Lead' in action_type:
                                logger.info(f"      {action_type}: {value}")

                    # Buscar todos os eventos (lead + custom events)
                    for action in actions:
                        action_type = action.get('action_type')
                        value = int(action.get('value', 0))

                        # Evento 'lead' padrão
                        if action_type == 'lead':
                            if 'lead' in campaign_events[campaign_id]:
                                campaign_events[campaign_id]['lead'] += value
                            else:
                                campaign_events[campaign_id]['lead'] = value

                        # Eventos personalizados genéricos - precisam ser mapeados
                        elif action_type == 'offsite_conversion.fb_pixel_custom' and adset_id:
                            # Meta API retorna evento genérico, buscar o custom_event deste adset
                            # Log para debug: adset_id e adset_name
                            adset_name = adset_data.get('adset_name', 'Unknown')

                            try:
                                # Buscar promoted_object do adset específico
                                adset_url = f"{self.meta_api.base_url}/{adset_id}"
                                adset_response = requests.get(adset_url, params={
                                    'access_token': self.meta_api.access_token,
                                    'fields': 'promoted_object'
                                }, timeout=3)

                                if adset_response.status_code == 200:
                                    adset_info = adset_response.json()
                                    promoted_obj = adset_info.get('promoted_object', {})
                                    custom_event = promoted_obj.get('custom_event_str')

                                    if custom_event and custom_event in ['LeadQualified', 'LeadQualifiedHighQuality', 'Faixa A']:
                                        # DEBUG: Log detalhado com nome do adset e impressions
                                        impressions = adset_data.get('impressions', 0)
                                        logger.info(f"    Camp {campaign_id[:15]}..., Adset {adset_id[:15]}... ({adset_name[:50]}): {custom_event} = {value}, Impressions = {impressions}")

                                        if custom_event in campaign_events[campaign_id]:
                                            campaign_events[campaign_id][custom_event] += value
                                        else:
                                            campaign_events[campaign_id][custom_event] = value
                            except Exception as e:
                                logger.debug(f"      Erro ao buscar custom_event do adset {adset_id}: {e}")

            except Exception as e:
                logger.error(f"    Erro ao buscar leads da conta {acc_id}: {e}")
                continue

        # Estatísticas de resumo
        total_leads = sum(events.get('lead', 0) for events in campaign_events.values())
        total_lead_qualified = sum(events.get('LeadQualified', 0) for events in campaign_events.values())
        total_lead_qualified_hq = sum(events.get('LeadQualifiedHighQuality', 0) for events in campaign_events.values())
        total_faixa_a = sum(events.get('Faixa A', 0) for events in campaign_events.values())

        logger.info(f"    {len(campaign_events)} campanhas encontradas")
        logger.info(f"       Leads: {total_leads}")
        logger.info(f"       LeadQualified: {total_lead_qualified}")
        logger.info(f"       LeadQualifiedHighQuality: {total_lead_qualified_hq}")
        logger.info(f"       Faixa A: {total_faixa_a}")

        # DEBUG: Mostrar detalhes das campanhas com eventos personalizados
        logger.info(f"    DEBUG - Campanhas com eventos personalizados:")
        for campaign_id, events in campaign_events.items():
            if any(e in events for e in ['LeadQualified', 'LeadQualifiedHighQuality', 'Faixa A']):
                # Buscar nome da campanha
                try:
                    camp_url = f"{self.meta_api.base_url}/{campaign_id}"
                    camp_response = requests.get(camp_url, params={
                        'access_token': self.meta_api.access_token,
                        'fields': 'name'
                    }, timeout=2)
                    if camp_response.status_code == 200:
                        camp_name = camp_response.json().get('name', 'Unknown')[:60]
                        logger.info(f"       {campaign_id}: {camp_name}")
                        logger.info(f"        {events}")
                    else:
                        logger.info(f"       {campaign_id}: {events}")
                except:
                    logger.info(f"       {campaign_id}: {events}")

        # Salvar no cache para próxima execução
        if self.use_cache:
            cache_key = self._get_cache_key('leads', account_id, period_start, period_end)
            self._save_to_cache(cache_key, campaign_events)

        return campaign_events

    def _get_campaign_lead_count(self, campaign_name: str, campaign_events: Dict[str, Dict[str, int]]) -> int:
        """
        Busca o lead count de uma campanha específica no dicionário retornado pela Meta API.

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            campaign_events: Dicionário {campaign_id: {evento: contagem}}

        Returns:
            Número de leads (int)
        """
        if not campaign_events:
            return 0

        # Extrair Campaign ID do nome
        campaign_id = self._extract_campaign_id(campaign_name)

        if campaign_id and campaign_id in campaign_events:
            return campaign_events[campaign_id].get('lead', 0)

        return 0

    def _get_campaign_custom_event_count(self, campaign_name: str, campaign_events: Dict[str, Dict[str, int]], event_name: str) -> int:
        """
        Busca a contagem de um evento personalizado para uma campanha específica.

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            campaign_events: Dicionário {campaign_id: {evento: contagem}}
            event_name: Nome do evento (ex: 'LeadQualified', 'LeadQualifiedHighQuality', 'Faixa A')

        Returns:
            Contagem do evento (int)
        """
        if not campaign_events:
            return 0

        # Extrair Campaign ID do nome
        campaign_id = self._extract_campaign_id(campaign_name)

        if campaign_id and campaign_id in campaign_events:
            return campaign_events[campaign_id].get(event_name, 0)

        return 0

    def calculate_campaign_metrics(
        self,
        matched_df: pd.DataFrame,
        account_id: str,
        period_start: str,
        period_end: str,
        global_tracking_rate: float = None,
        costs_hierarchy_consolidated: Dict = None
    ) -> pd.DataFrame:
        """
        Calcula métricas completas por campanha.

        NOVO: Suporta custos pré-carregados de múltiplas contas Meta.

        Args:
            matched_df: DataFrame com matching realizado (leads + vendas)
            account_id: ID da conta Meta (act_XXXXXXXXX) ou lista de IDs separados por vírgula
            period_start: Data início (YYYY-MM-DD)
            period_end: Data fim (YYYY-MM-DD)
            global_tracking_rate: Taxa de trackeamento global (%) - opcional
            costs_hierarchy_consolidated: Dicionário com custos pré-carregados de múltiplas contas (opcional)

        Returns:
            DataFrame com métricas por campanha:
            - ml_type: COM_ML ou SEM_ML
            - campaign: Nome da campanha
            - leads: Total de leads
            - conversions: Total de conversões
            - conversion_rate: Taxa de conversão (%)
            - total_revenue: Receita total
            - spend: Gasto total (Meta API)
            - budget: Orçamento total (CBO ou soma ABO)
            - num_creatives: Número de criativos
            - cpl: Custo por lead
            - roas: Return on Ad Spend
            - contribution_margin: Margem de contribuição (R$)
            - margin_percent: Margem (%)
        """
        logger.info(" Calculando métricas por campanha...")

        # 0. FILTRAR respostas apenas de leads captados NO PERÍODO
        # TEMPORARIAMENTE DESATIVADO - usando todos os dados
        logger.info("    Filtro temporal DESATIVADO - usando todos os dados do matched_df")
        original_count = len(matched_df)

        if False and 'data_captura' in matched_df.columns:  # DESATIVADO
            # Converter period_start e period_end para datetime
            period_start_dt = pd.to_datetime(period_start)
            period_end_dt = pd.to_datetime(period_end)

            # Filtrar apenas leads captados no período
            matched_df = matched_df[
                (matched_df['data_captura'] >= period_start_dt) &
                (matched_df['data_captura'] <= period_end_dt)
            ].copy()

            filtered_count = len(matched_df)
            excluded_count = original_count - filtered_count

            logger.info(f"    Respostas no período: {filtered_count:,}")
            logger.info(f"     Respostas excluídas (captadas fora do período): {excluded_count:,}")
            logger.info(f"    Período de captura: {period_start} a {period_end}")
        else:
            logger.warning("     Coluna 'data_captura' não encontrada - não foi possível filtrar por período!")
            logger.warning("     ATENÇÃO: % de resposta pode estar distorcido!")

        # 1. Agregar dados de conversão por campanha
        logger.info("   Agregando dados de conversão...")

        # FIX: Consolidar campanhas por campaign_id + nome base normalizado
        logger.info("    Consolidando variações de campanha por Campaign ID...")

        # Extrair campaign_id e nome base de cada linha
        matched_df['campaign_id_extracted'] = matched_df['campaign'].apply(
            lambda camp: self._extract_campaign_id(camp)
        )
        matched_df['campaign_base_normalized'] = matched_df['campaign'].apply(
            lambda camp: self._normalize_campaign_name(camp)
        )

        # Agrupar por campaign_id
        from collections import defaultdict
        campaigns_by_id = defaultdict(list)
        campaigns_without_id = []  # Campanhas sem ID

        for _, row in matched_df[['campaign', 'campaign_id_extracted', 'campaign_base_normalized']].drop_duplicates().iterrows():
            camp_id = row['campaign_id_extracted']
            full_name = row['campaign']
            base_name = row['campaign_base_normalized']

            if camp_id:
                # Tem ID: agrupar por ID
                campaigns_by_id[camp_id].append((full_name, base_name))
            else:
                # Sem ID: guardar para matching posterior
                campaigns_without_id.append((full_name, base_name))

        # Para cada ID, escolher o nome MAIS COMPLETO (maior length)
        campaign_id_to_best_name = {}
        campaign_base_to_best_name = {}  # Mapeamento nome_base  melhor nome COM ID

        for camp_id, variations in campaigns_by_id.items():
            # Escolher nome mais longo (mais completo)
            best_name = max(variations, key=lambda x: len(x[0]))[0]
            campaign_id_to_best_name[camp_id] = best_name

            # Também mapear o nome base (sem ID) para o melhor nome COM ID
            # Isso permite consolidar campanhas SEM ID que correspondem a campanhas COM ID
            for full_name, base_name in variations:
                if base_name:
                    campaign_base_to_best_name[base_name] = best_name

        def get_consolidated_name(campaign_name):
            """Retorna nome consolidado baseado no campaign_id ou nome base"""
            camp_id = self._extract_campaign_id(campaign_name)
            base_name = self._normalize_campaign_name(campaign_name)

            # 1. Se tem ID, usar mapping por ID (mais preciso)
            if camp_id:
                # Match exato
                if camp_id in campaign_id_to_best_name:
                    return campaign_id_to_best_name[camp_id]

                # FALLBACK: Match pelos primeiros 15 dígitos
                # Isso garante que TODAS as variações com mesmo ID sejam consolidadas
                camp_id_prefix = camp_id[:15] if len(camp_id) >= 15 else camp_id
                for mapped_id, best_name in campaign_id_to_best_name.items():
                    mapped_id_prefix = mapped_id[:15] if len(mapped_id) >= 15 else mapped_id
                    if camp_id_prefix == mapped_id_prefix:
                        return best_name

            # 2. Se não tem ID, tentar match por nome base normalizado
            # Isso consolida respostas órfãs (sem ID) com campanhas COM ID
            if base_name and base_name in campaign_base_to_best_name:
                return campaign_base_to_best_name[base_name]

            # 3. Fallback: retornar nome original
            return campaign_name

        # Log de consolidações
        consolidations = [(key, vars) for key, vars in campaigns_by_id.items() if len(vars) > 1]
        if consolidations:
            logger.info(f"    {len(consolidations)} IDs com múltiplas variações serão consolidadas:")
            for key, variations in consolidations[:5]:  # Mostrar 5 primeiros
                best_name = campaign_id_to_best_name[key]
                # Truncar ID para exibição
                display_key = key[:15] + "..." if len(key) > 15 else key
                logger.info(f"       ID {display_key}:")
                logger.info(f"         Nome escolhido: {best_name[:70]}")
                for full_name in variations:
                    count = len(matched_df[matched_df['campaign'] == full_name])
                    logger.info(f"         - {count:3d} respostas: {full_name[:70]}")

        # Aplicar consolidação
        matched_df['campaign_consolidated'] = matched_df['campaign'].apply(get_consolidated_name)

        # DEBUG: Verificar vendas antes da agregação
        vendas_antes_groupby = matched_df['converted'].sum()
        vendas_unicas_antes = matched_df[matched_df['converted'] == True]['email'].nunique()
        logger.info(f"    DEBUG - matched_df: {len(matched_df)} total de linhas, {int(vendas_antes_groupby)} conversões, {vendas_unicas_antes} emails únicos convertidos")

        # Verificar se há vendas com campaign_consolidated inválido
        vendas_df = matched_df[matched_df['converted'] == True]
        invalid_campaigns = vendas_df[vendas_df['campaign_consolidated'].isna()]
        if len(invalid_campaigns) > 0:
            logger.warning(f"    {len(invalid_campaigns)} vendas com campaign_consolidated NULO!")

        # Groupby usando nome consolidado
        # CRÍTICO: Contar emails únicos para conversões, não somar linhas (evita duplicatas)

        # 1. Agregar respostas e receita (podem usar sum)
        # IMPORTANTE: dropna=False para incluir campanhas com nome NULL/estranho
        campaign_stats = matched_df.groupby(['ml_type', 'campaign_consolidated'], dropna=False).agg({
            'email': 'count',  # respostas na pesquisa (leads que responderam)
            'sale_value': 'sum'  # revenue total
        }).reset_index()
        campaign_stats.columns = ['ml_type', 'campaign', 'respostas_pesquisa', 'total_revenue']

        # 2. Contar conversões únicas (por email, não agregação de linhas)
        # IMPORTANTE: dropna=False para incluir campanhas com nome NULL/estranho
        conversions_df = matched_df[matched_df['converted'] == True].groupby(
            ['ml_type', 'campaign_consolidated'], dropna=False
        )['email'].nunique().reset_index(name='conversions')
        conversions_df.columns = ['ml_type', 'campaign', 'conversions']

        # 3. Merge: conversions pode estar vazio se campanha não tem vendas
        campaign_stats = campaign_stats.merge(
            conversions_df,
            on=['ml_type', 'campaign'],
            how='left'
        )
        campaign_stats['conversions'] = campaign_stats['conversions'].fillna(0).astype(int)

        # DEBUG: Verificar vendas depois da agregação
        vendas_depois_groupby = campaign_stats['conversions'].sum()
        logger.info(f"    DEBUG - Vendas depois do groupby: {int(vendas_depois_groupby)}")
        if vendas_antes_groupby != vendas_depois_groupby:
            logger.warning(f"    PERDA DE VENDAS NO GROUPBY: {int(vendas_antes_groupby - vendas_depois_groupby)} vendas perdidas!")

        # DEBUG: Mostrar campanhas com vendas e sua classificação
        campanhas_com_vendas = campaign_stats[campaign_stats['conversions'] > 0].copy()
        if len(campanhas_com_vendas) > 0:
            logger.info(f"    CAMPANHAS COM VENDAS ({len(campanhas_com_vendas)} campanhas):")
            for _, row in campanhas_com_vendas.iterrows():
                grupo = row['ml_type']
                campanha = str(row['campaign'])[:80]
                vendas = int(row['conversions'])
                logger.info(f"       [{grupo}] {campanha}: {vendas} vendas")

        # DEBUG: Verificar se comparison_group já existe no matched_df
        if 'comparison_group' in matched_df.columns:
            eventos_ml_matched = matched_df[matched_df['comparison_group'] == 'Champion']
            total_leads_eventos_ml_matched = len(eventos_ml_matched)
            total_vendas_eventos_ml_matched = eventos_ml_matched['converted'].sum()
            logger.info(f"    DEBUG - Eventos ML no matched_df: {total_leads_eventos_ml_matched} leads, {int(total_vendas_eventos_ml_matched)} vendas")

        # Limpar colunas auxiliares do matched_df
        matched_df = matched_df.drop(['campaign_id_extracted', 'campaign_base_normalized', 'campaign_consolidated'], axis=1)

        # Nota: conversion_rate será calculado DEPOIS de carregar leads do Excel e ajustar campanha especial

        # Se sale_value não estava disponível, calcular receita baseado em product_value
        if campaign_stats['total_revenue'].sum() == 0:
            campaign_stats['total_revenue'] = campaign_stats['conversions'] * self.product_value

        logger.info(f"   {len(campaign_stats)} campanhas agregadas")
        logger.info(f"   Conversões totais em campaign_stats: {int(campaign_stats['conversions'].sum())}")

        # Usar dados dos relatórios Excel (não usar Meta API)
        logger.info("    Carregando leads dos relatórios Excel...")

        # Usar costs_hierarchy_consolidated que foi passado como parâmetro
        costs = costs_hierarchy_consolidated if costs_hierarchy_consolidated else {}

        # DEBUG: Verificar IDs disponíveis
        if costs and costs.get('campaigns'):
            available_ids = list(costs['campaigns'].keys())
            logger.info(f"    DEBUG - Primeiros 3 IDs: {available_ids[:3]}")
            logger.info(f"    DEBUG - Primeiras 3 campanhas em campaign_stats:")
            for camp in campaign_stats['campaign'].head(3):
                extracted_id = self._extract_campaign_id(camp)
                logger.info(f"       {camp[:60]}...  ID: {extracted_id}")

        campaign_stats['leads'] = campaign_stats['campaign'].apply(
            lambda camp: self._get_campaign_leads_from_costs(camp, costs)
        )
        campaign_stats['LeadQualified'] = campaign_stats['campaign'].apply(
            lambda camp: self._get_campaign_custom_event_from_costs(camp, costs, 'LeadQualified')
        )
        campaign_stats['LeadQualifiedHighQuality'] = campaign_stats['campaign'].apply(
            lambda camp: self._get_campaign_custom_event_from_costs(camp, costs, 'LeadQualifiedHighQuality')
        )
        campaign_stats['Faixa A'] = campaign_stats['campaign'].apply(
            lambda camp: self._get_campaign_custom_event_from_costs(camp, costs, 'Faixa A')
        )

        total_leads_excel = campaign_stats['leads'].sum()
        total_lq = campaign_stats['LeadQualified'].sum()
        total_lqhq = campaign_stats['LeadQualifiedHighQuality'].sum()
        total_faixa_a = campaign_stats['Faixa A'].sum()
        logger.info(f"    Leads carregados do Excel: {total_leads_excel}")
        logger.info(f"      'lead' padrão: {total_leads_excel}")
        logger.info(f"      LeadQualified: {total_lq}")
        logger.info(f"      LeadQualifiedHighQuality: {total_lqhq}")
        logger.info(f"      Faixa A: {total_faixa_a}")

        # AJUSTE ESPECIAL: Campanha com evento Lead não disparando corretamente
        # Calcular proporção média LQ/Leads das campanhas normais (excluindo a especial)
        # Usando MÉDIA PONDERADA (Total LQ / Total Leads) para dar peso correto a cada campanha
        campaign_special_id_prefix = '120234062599950'  # Primeiros 15 dígitos
        total_leads_normal = 0
        total_lq_normal = 0

        for idx, row in campaign_stats.iterrows():
            camp_id = self._extract_campaign_id(row['campaign'])
            # Excluir campanha especial do cálculo da proporção
            if camp_id and not camp_id.startswith(campaign_special_id_prefix):
                leads = row['leads']
                lq = row['LeadQualified']
                # Somar apenas campanhas que geram LQ (excluir FAIXA A com LQ=0)
                if leads > 0 and lq > 0:
                    total_leads_normal += leads
                    total_lq_normal += lq

        # Ajustar campanha especial com leads artificiais
        if total_leads_normal > 0 and total_lq_normal > 0:
            avg_ratio = total_lq_normal / total_leads_normal
            logger.info(f"    Proporção média LQ/Leads (campanhas normais): {avg_ratio:.2%}")
            logger.info(f"      Total leads: {int(total_leads_normal)}, Total LQ: {int(total_lq_normal)}")

            # Identificar e ajustar campanha especial
            for idx, row in campaign_stats.iterrows():
                camp_id = self._extract_campaign_id(row['campaign'])
                if camp_id and camp_id.startswith(campaign_special_id_prefix):
                    leads_original = row['leads']
                    lq = row['LeadQualified']

                    # Calcular leads artificiais baseado na proporção média
                    if lq > 0 and avg_ratio > 0:
                        leads_artificial = int(lq / avg_ratio)
                        campaign_stats.at[idx, 'leads'] = leads_artificial
                        logger.info(f"    Campanha especial ajustada ({camp_id[:15]}...):")
                        logger.info(f"      Leads original: {leads_original}")
                        logger.info(f"      LeadQualified: {lq}")
                        logger.info(f"      Leads artificial: {leads_artificial} (baseado em proporção {avg_ratio:.2%})")

        # NOTA: Não calcular total_conversion_events como soma
        # Eventos customizados (LQ, LQHQ, Faixa A) são SUBSETS dos leads, não adicionais
        # O campo 'leads' já contém o valor correto (incluindo ajuste para campanha especial)
        # Manter coluna para compatibilidade, mas igual a 'leads'
        campaign_stats['total_conversion_events'] = campaign_stats['leads']

        # Calcular taxa de resposta usando 'leads' no denominador
        # Nota: 'leads' já foi ajustado acima para incluir leads artificiais na campanha especial
        # que não dispara o evento Lead corretamente (usando proporção LQ/Leads média)
        campaign_stats['taxa_resposta'] = campaign_stats.apply(
            lambda row: (row['respostas_pesquisa'] / row['leads'] * 100) if row['leads'] > 0 else 0,
            axis=1
        ).round(2)

        # Calcular taxa de conversão (baseada em leads)
        # Usa 'leads' ajustado que inclui leads artificiais para campanha especial
        campaign_stats['conversion_rate'] = campaign_stats.apply(
            lambda row: (row['conversions'] / row['leads'] * 100) if row['leads'] > 0 else 0,
            axis=1
        ).round(2)

        # IMPORTANTE: Salvar total de leads ANTES de filtrar campanhas com spend=0
        # NÃO somar eventos customizados - eles são subsets dos leads, não adicionais
        total_leads_standard = campaign_stats['leads'].sum()
        total_lq = campaign_stats['LeadQualified'].sum()
        total_lqhq = campaign_stats['LeadQualifiedHighQuality'].sum()
        total_faixa_a = campaign_stats['Faixa A'].sum()

        # Usar apenas total de leads (que já inclui ajuste da campanha especial)
        self.total_leads_meta_before_filter = total_leads_standard

        # Salvar também total de respostas ANTES do filtro para comparação
        self.total_respostas_before_filter = campaign_stats['respostas_pesquisa'].sum()

        logger.info(f"    Total de leads (Meta): {self.total_leads_meta_before_filter}")
        logger.info(f"      'lead' padrão: {total_leads_standard}")
        logger.info(f"      LeadQualified: {total_lq}")
        logger.info(f"      LeadQualifiedHighQuality: {total_lqhq}")
        logger.info(f"      Faixa A: {total_faixa_a}")
        logger.info(f"    Total de respostas (antes do filtro): {self.total_respostas_before_filter}")
        # Calcular taxa de resposta média usando leads no denominador
        total_leads = campaign_stats['leads'].sum()
        taxa_media = campaign_stats['respostas_pesquisa'].sum() / total_leads * 100 if total_leads > 0 else 0
        logger.info(f"    Taxa de resposta média: {taxa_media:.2f}%")

        # 2. Buscar custos via Meta API (se não fornecidos)
        if costs_hierarchy_consolidated:
            logger.info("   Usando custos pré-carregados de múltiplas contas")
            costs_hierarchy = costs_hierarchy_consolidated
        else:
            logger.info("   Buscando custos via Meta API...")
            try:
                costs_hierarchy = self.meta_api.get_costs_hierarchy(
                    account_id=account_id,
                    since_date=period_start,
                    until_date=period_end
                )
            except Exception as e:
                logger.error(f"    Erro ao buscar custos Meta API: {e}")
                logger.warning("   Usando spend = 0 para todas as campanhas")
                costs_hierarchy = {'campaigns': {}}

        # Mapear custos para campanhas (sempre, independente da fonte)
        if costs_hierarchy and costs_hierarchy.get('campaigns'):
            campaign_stats['spend'] = campaign_stats['campaign'].apply(
                lambda camp: self._get_campaign_spend(camp, costs_hierarchy)
            )

            # Adicionar budget e número de criativos
            campaign_stats['budget'] = campaign_stats['campaign'].apply(
                lambda camp: self._get_campaign_budget(camp, costs_hierarchy)
            )
            campaign_stats['num_creatives'] = campaign_stats['campaign'].apply(
                lambda camp: self._get_campaign_num_creatives(camp, costs_hierarchy)
            )

            # DEBUG: Verificar quais IDs estamos tentando buscar
            logger.info("    DEBUG - Tentando buscar optimization_goals para:")
            ml_campaigns = campaign_stats[campaign_stats['ml_type'] == 'COM_ML']
            for idx, row in ml_campaigns.head(3).iterrows():
                camp_name = row['campaign']
                camp_id = self._extract_campaign_id(camp_name)
                logger.info(f"       {camp_name[:70]}...")
                logger.info(f"        Extracted ID: {camp_id}")
                logger.info(f"        First 15: {camp_id[:15] if camp_id else 'None'}")

            if costs_hierarchy and costs_hierarchy.get('campaigns'):
                for camp_id in list(costs_hierarchy['campaigns'].keys())[:5]:
                    camp_data = costs_hierarchy['campaigns'][camp_id]
                    logger.info(f"       {camp_id} (first 15: {camp_id[:15]})")
                    logger.info(f"        Name: {camp_data.get('name', 'N/A')[:70]}")

            # Adicionar optimization_goals (eventos de conversão customizados)
            campaign_stats['optimization_goal'] = campaign_stats['campaign'].apply(
                lambda camp: self._get_campaign_optimization_goals(camp, costs_hierarchy)
            )

            # Adicionar account_id para cada campanha
            campaign_stats['account_id'] = campaign_stats['campaign'].apply(
                lambda camp: self._get_campaign_account_id(camp, costs_hierarchy)
            )

            # ATUALIZAR nomes das campanhas: substituir UTMs desatualizados por nomes atuais da Meta
            logger.info("    Atualizando nomes das campanhas (UTMs  Meta API)...")
            campaign_stats['campaign'] = campaign_stats['campaign'].apply(
                lambda camp: self._get_campaign_current_name(camp, costs_hierarchy)
            )
            logger.info("    Nomes atualizados com sucesso")

            # optimization_goal já é retornado como string por _get_campaign_optimization_goals()
            # Não precisa converter, apenas garantir que "-" vire ""
            campaign_stats['optimization_goal'] = campaign_stats['optimization_goal'].replace('-', '')

            total_spend = campaign_stats['spend'].sum()
            logger.info(f"    Custos obtidos: R$ {total_spend:,.2f}")
        else:
            campaign_stats['spend'] = 0.0
            campaign_stats['budget'] = 0.0
            campaign_stats['num_creatives'] = 0
            campaign_stats['optimization_goal'] = "-"
            campaign_stats['account_id'] = ""

        # 2.5. Filtrar campanhas sem spend (não ativas no período)
        # IMPORTANTE: NUNCA remover campanhas com conversões > 0!
        # Só remover se: spend=0 AND leads=0 AND conversions=0
        campaigns_before_filter = len(campaign_stats)
        conversions_before_filter = campaign_stats['conversions'].sum()

        # Identificar campanhas que serão removidas
        removed_campaigns = campaign_stats[
            (campaign_stats['spend'] == 0) &
            (campaign_stats['leads'] == 0) &
            (campaign_stats['conversions'] == 0)
        ].copy()

        campaign_stats = campaign_stats[
            (campaign_stats['spend'] > 0) |
            (campaign_stats['leads'] > 0) |
            (campaign_stats['conversions'] > 0)
        ]
        campaigns_filtered = campaigns_before_filter - len(campaign_stats)
        conversions_after_filter = campaign_stats['conversions'].sum()

        if campaigns_filtered > 0:
            logger.info(f"    {campaigns_filtered} campanhas removidas (spend = 0 E leads = 0, não ativas no período)")
            conversions_removed = conversions_before_filter - conversions_after_filter
            if conversions_removed > 0:
                logger.warning(f"    {int(conversions_removed)} vendas removidas junto com essas campanhas!")
                logger.warning(f"    Campanhas removidas com vendas:")
                for _, row in removed_campaigns[removed_campaigns['conversions'] > 0].iterrows():
                    grupo = row.get('comparison_group', 'N/A')
                    logger.warning(f"       {int(row['conversions'])} vendas [{grupo}]: {row['campaign'][:70]}")

        # DEBUG: Verificar Eventos ML no campaign_stats após filtro
        if 'comparison_group' in campaign_stats.columns:
            eventos_ml_stats = campaign_stats[campaign_stats['comparison_group'] == 'Champion']
            if len(eventos_ml_stats) > 0:
                total_leads_eventos_ml_stats = eventos_ml_stats['leads'].sum()
                total_vendas_eventos_ml_stats = eventos_ml_stats['conversions'].sum()
                logger.info(f"    DEBUG - Eventos ML no campaign_stats (após filtro): {len(eventos_ml_stats)} campanhas, {int(total_leads_eventos_ml_stats)} leads, {int(total_vendas_eventos_ml_stats)} vendas")

        # 3. Calcular métricas finais
        logger.info("   Calculando CPL, ROAS e Margem...")

        # Verificar se temos campanhas para calcular
        if len(campaign_stats) == 0:
            logger.warning("    Nenhuma campanha com dados para calcular métricas")
            return pd.DataFrame()

        # Garantir que as colunas numéricas sejam do tipo correto
        numeric_columns = ['spend', 'total_revenue', 'leads', 'conversions', 'respostas_pesquisa']
        for col in numeric_columns:
            if col in campaign_stats.columns:
                campaign_stats[col] = pd.to_numeric(campaign_stats[col], errors='coerce').fillna(0)

        # CPL - usar 'leads' no denominador
        # Nota: 'leads' já foi ajustado para incluir leads artificiais na campanha especial
        campaign_stats['cpl'] = campaign_stats.apply(
            lambda row: calculate_cpl(row['spend'], row['leads']) if row['leads'] > 0 else 0,
            axis=1
        ).round(2)

        # ROAS
        campaign_stats['roas'] = campaign_stats.apply(
            lambda row: (row['total_revenue'] / row['spend']) if row['spend'] > 0 else 0,
            axis=1
        ).round(2)

        # Margem de Contribuição
        campaign_stats['contribution_margin'] = (
            campaign_stats['total_revenue'] - campaign_stats['spend']
        ).round(2)

        # Margem %
        campaign_stats['margin_percent'] = campaign_stats.apply(
            lambda row: (row['contribution_margin'] / row['spend'] * 100) if row['spend'] > 0 else 0,
            axis=1
        ).round(2)

        # Ordenar por margem de contribuição (maior para menor)
        campaign_stats = campaign_stats.sort_values('contribution_margin', ascending=False)

        logger.info(f"    Métricas calculadas para {len(campaign_stats)} campanhas")

        # Adicionar métricas ajustadas por TMB
        logger.info(f"    Calculando métricas ajustadas por TMB...")
        campaign_stats = add_adjusted_metrics_to_campaign_stats(
            campaign_stats,
            matched_df,
            fator=FATOR_TMB_MEDIO
        )

        return campaign_stats

    def _normalize_campaign_name(self, campaign_name: str) -> str:
        """
        Normaliza nome da campanha removendo o ID para matching.

        Remove o Campaign ID do final para permitir consolidação de variações
        da mesma campanha (com e sem ID).

        Args:
            campaign_name: Nome da campanha (com ou sem ID)

        Returns:
            Nome normalizado sem ID

        Examples:
            >>> _normalize_campaign_name("DEVLF | CAP | FRIO | ML | 2025-05-28|120234748179990390")
            "DEVLF | CAP | FRIO | ML | 2025-05-28"
            >>> _normalize_campaign_name("DEVLF | CAP | FRIO | ML | 2025-05-28")
            "DEVLF | CAP | FRIO | ML | 2025-05-28"
        """
        if not campaign_name or pd.isna(campaign_name):
            return None

        import re

        # Remover ID (sequência de 15+ dígitos precedida opcionalmente por |)
        name = re.sub(r'\|?\s*1\d{14,}', '', str(campaign_name))

        # Remover pipes e espaços extras no final
        name = name.rstrip('| ').strip()

        return name

    def _extract_campaign_id(self, campaign_name: str) -> str:
        """
        Extrai o Campaign ID do nome da campanha.

        Formato esperado: "NOME DA CAMPANHA|CAMPAIGN_ID"
        Exemplo: "DEVLF | CAP | FRIO | FASE 01 | ABERTO ADV+ | PG2 | 2025-04-15|120220370119870390"

        MELHORIA: Agora busca o ID em qualquer parte do nome (não apenas no final)
        para lidar com IDs truncados no Google Sheets.

        Args:
            campaign_name: Nome completo da campanha com ID

        Returns:
            Campaign ID (string) ou None se não encontrar
        """
        if not campaign_name or pd.isna(campaign_name):
            return None

        import re

        # Tentar extrair o ID do final primeiro (método padrão)
        parts = str(campaign_name).split('|')
        if len(parts) >= 2:
            last_part = parts[-1].strip()
            if last_part.isdigit() and len(last_part) > 10:  # IDs do Meta têm ~18 dígitos
                return last_part

        # Fallback: Buscar sequência de 15+ dígitos em QUALQUER lugar do nome
        # IDs do Meta têm 18 dígitos geralmente, mas aceitar 15+ para IDs truncados
        match = re.search(r'1\d{14,}', str(campaign_name))  # Começa com '1' e tem 15+ dígitos
        if match:
            return match.group(0)

        return None

    def _get_campaign_spend(self, campaign_name: str, costs_hierarchy: Dict) -> float:
        """
        Busca o gasto de uma campanha específica na hierarquia de custos.

        NOVO: Usa Campaign ID extraído do nome para matching preciso.

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            costs_hierarchy: Dicionário retornado por get_costs_hierarchy()

        Returns:
            Valor gasto (float)
        """
        if not costs_hierarchy:
            return 0.0

        campaigns = costs_hierarchy.get('campaigns', {})
        if not campaigns:
            return 0.0

        # MÉTODO 1: Tentar match por Campaign ID (mais preciso)
        campaign_id = self._extract_campaign_id(campaign_name)

        if campaign_id:
            # Match exato primeiro
            if campaign_id in campaigns:
                spend = float(campaigns[campaign_id].get('spend', 0))
                logger.debug(f"    Match por ID: {campaign_id}  R$ {spend:.2f}")
                return spend

            # FALLBACK: Match pelos primeiros 15 dígitos (ignora últimos 3 dígitos)
            # Isso resolve o problema de IDs que terminam em 390 vs 000
            campaign_id_prefix = campaign_id[:15] if len(campaign_id) >= 15 else campaign_id

            for cost_id, cost_data in campaigns.items():
                cost_id_prefix = cost_id[:15] if len(cost_id) >= 15 else cost_id
                if campaign_id_prefix == cost_id_prefix:
                    spend = float(cost_data.get('spend', 0))
                    logger.debug(f"    Match por ID (15 dígitos): {campaign_id_prefix}  R$ {spend:.2f}")
                    return spend

        # MÉTODO 2: Fallback - match por nome EXATO (para campanhas sem ID no nome)
        # Remover ID do final para comparação
        campaign_name_clean = campaign_name
        if campaign_id:
            campaign_name_clean = '|'.join(campaign_name.split('|')[:-1]).strip()

        # Procurar por nome exato (case-insensitive)
        campaign_lower = campaign_name_clean.lower().strip()
        for camp_id, camp_data in campaigns.items():
            camp_name_lower = camp_data.get('name', '').lower().strip()
            if campaign_lower == camp_name_lower:
                spend = float(camp_data.get('spend', 0))
                logger.debug(f"    Match por nome: {campaign_name_clean}  R$ {spend:.2f}")
                return spend

        # Não encontrou - retornar 0 (REMOVIDO match parcial que causava duplicatas)
        logger.debug(f"    Campanha não encontrada: {campaign_name}")
        return 0.0

    def _get_campaign_budget(self, campaign_name: str, costs_hierarchy: Dict) -> float:
        """
        Busca o orçamento de uma campanha específica na hierarquia de custos.
        Para campanhas ABO (budget=0), soma os budgets dos adsets.

        NOVO: Usa Campaign ID extraído do nome para matching preciso.

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            costs_hierarchy: Dicionário retornado por get_costs_hierarchy()

        Returns:
            Valor do orçamento (float) - prioriza daily_budget, senão lifetime_budget
        """
        if not costs_hierarchy:
            return 0.0

        campaigns = costs_hierarchy.get('campaigns', {})
        if not campaigns:
            return 0.0

        # MÉTODO 1: Tentar match por Campaign ID (mais preciso)
        campaign_id = self._extract_campaign_id(campaign_name)
        camp_data = None

        if campaign_id and campaign_id in campaigns:
            camp_data = campaigns[campaign_id]
        else:
            # MÉTODO 2: Fallback - match por nome
            campaign_name_clean = campaign_name
            if campaign_id:
                campaign_name_clean = '|'.join(campaign_name.split('|')[:-1]).strip()

            # Procurar por nome exato
            for camp_id, data in campaigns.items():
                if data.get('name', '').strip() == campaign_name_clean.strip():
                    camp_data = data
                    break

        if camp_data:
            # Retornar apenas daily_budget (não usar lifetime_budget pois é total, não diário)
            daily = float(camp_data.get('daily_budget', 0) or 0)
            campaign_budget = daily

            # Se budget da campanha é 0, pode ser ABO - somar budgets dos adsets
            if campaign_budget == 0 and not camp_data.get('has_campaign_budget', False):
                adsets = camp_data.get('adsets', {})
                if adsets and self.meta_api:
                    # Buscar budget dos adsets via Meta API (apenas daily_budget)
                    total_adset_budget = 0.0
                    for adset_id in adsets.keys():
                        try:
                            budget_info = self.meta_api.get_adset_budget_info(adset_id)
                            adset_daily = float(budget_info.get('daily_budget', 0) or 0)
                            # Somar apenas daily_budget (não usar lifetime_budget)
                            total_adset_budget += adset_daily
                        except Exception as e:
                            logger.debug(f"Erro ao buscar budget do adset {adset_id}: {e}")
                            continue
                    if total_adset_budget > 0:
                        return total_adset_budget

            return campaign_budget

        return 0.0

    def _get_campaign_num_creatives(self, campaign_name: str, costs_hierarchy: Dict) -> int:
        """
        Busca o número de criativos (ads) de uma campanha específica na hierarquia de custos.
        Conta todos os ads em todos os adsets da campanha.

        NOVO: Usa Campaign ID extraído do nome para matching preciso.

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            costs_hierarchy: Dicionário retornado por get_costs_hierarchy()

        Returns:
            Número de criativos (int)
        """
        if not costs_hierarchy:
            return 0

        campaigns = costs_hierarchy.get('campaigns', {})
        if not campaigns:
            return 0

        # MÉTODO 1: Tentar match por Campaign ID (mais preciso)
        campaign_id = self._extract_campaign_id(campaign_name)
        camp_data = None

        if campaign_id and campaign_id in campaigns:
            camp_data = campaigns[campaign_id]
        else:
            # MÉTODO 2: Fallback - match por nome
            campaign_name_clean = campaign_name
            if campaign_id:
                campaign_name_clean = '|'.join(campaign_name.split('|')[:-1]).strip()

            # Procurar por nome exato
            for camp_id, data in campaigns.items():
                if data.get('name', '').strip() == campaign_name_clean.strip():
                    camp_data = data
                    break

        if camp_data:
            # Contar todos os ads em todos os adsets
            adsets = camp_data.get('adsets', {})
            total_ads = 0
            for adset_id, adset_data in adsets.items():
                ads = adset_data.get('ads', {})
                total_ads += len(ads)
            return total_ads

        return 0

    def _get_campaign_optimization_goals(self, campaign_name: str, costs_hierarchy: Dict) -> str:
        """
        Busca os optimization_goals dos adsets de uma campanha específica.
        Como uma campanha pode ter múltiplos adsets com diferentes goals, retorna todos únicos.

        NOVO: Usa Campaign ID extraído do nome para matching preciso.

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            costs_hierarchy: Dicionário retornado por get_costs_hierarchy()

        Returns:
            String com optimization_goals únicos separados por vírgula
            Ex: "LeadQualifiedHighQuality", "LeadQualified, LEAD", etc.
            Retorna "-" se não encontrar nenhum goal
        """
        if not costs_hierarchy:
            return "-"

        campaigns = costs_hierarchy.get('campaigns', {})
        if not campaigns:
            return "-"

        # MÉTODO 1: Tentar match por Campaign ID (mais preciso)
        campaign_id = self._extract_campaign_id(campaign_name)
        camp_data = None
        match_method = None

        if campaign_id:
            # Match exato primeiro
            if campaign_id in campaigns:
                camp_data = campaigns[campaign_id]
                match_method = "exact_id"
            else:
                # FALLBACK: Match pelos primeiros 15 dígitos (ignora últimos 3)
                # Isso resolve o problema de IDs que terminam em 390 vs 000
                campaign_id_prefix = campaign_id[:15] if len(campaign_id) >= 15 else campaign_id

                for cost_id, cost_data in campaigns.items():
                    cost_id_prefix = cost_id[:15] if len(cost_id) >= 15 else cost_id
                    if campaign_id_prefix == cost_id_prefix:
                        camp_data = cost_data
                        match_method = f"prefix_id ({campaign_id_prefix})"
                        break

        # MÉTODO 2: Fallback - match por nome (se ainda não achou)
        if not camp_data:
            campaign_name_clean = campaign_name
            if campaign_id:
                campaign_name_clean = '|'.join(campaign_name.split('|')[:-1]).strip()

            # Procurar por nome exato
            for camp_id, data in campaigns.items():
                if data.get('name', '').strip() == campaign_name_clean.strip():
                    camp_data = data
                    match_method = "name"
                    break

        if not camp_data:
            # DEBUG: Campanha não encontrada em costs_hierarchy
            logger.debug(f"    Campanha não encontrada em costs_hierarchy: {campaign_name[:60]}")
            logger.debug(f"      Extracted ID: {campaign_id}")
            return "-"

        if camp_data:
            # Coletar optimization_goals únicos de todos os adsets
            adsets = camp_data.get('adsets', {})
            optimization_goals = set()

            for adset_id, adset_data in adsets.items():
                goal = adset_data.get('optimization_goal')
                if goal:
                    # Mapear OFFSITE_CONVERSIONS para "Lead" quando não for evento personalizado
                    if goal == 'OFFSITE_CONVERSIONS':
                        goal = 'Lead'
                    optimization_goals.add(goal)

            if optimization_goals:
                # Ordenar para consistência e retornar como string
                return ", ".join(sorted(optimization_goals))
            else:
                # DEBUG: Se não encontrou goals, logar informação
                logger.debug(f"    Nenhum optimization_goal encontrado para campanha: {campaign_name[:60]}")
                logger.debug(f"      Campaign ID: {campaign_id}")
                logger.debug(f"      Adsets encontrados: {len(adsets)}")

        return "-"

    def _get_campaign_account_id(self, campaign_name: str, costs_hierarchy: Dict) -> str:
        """
        Busca o account_id de uma campanha específica na hierarquia de custos.

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            costs_hierarchy: Dicionário retornado por get_costs_hierarchy()

        Returns:
            Account ID (string) ou vazio se não encontrar
        """
        if not costs_hierarchy:
            return ""

        campaigns = costs_hierarchy.get('campaigns', {})
        if not campaigns:
            return ""

        # MÉTODO 1: Tentar match por Campaign ID (mais preciso)
        campaign_id = self._extract_campaign_id(campaign_name)
        camp_data = None

        if campaign_id and campaign_id in campaigns:
            camp_data = campaigns[campaign_id]
        elif campaign_id:
            # MÉTODO 1.5: Match pelos primeiros 15 dígitos (costs_hierarchy trunca IDs)
            # Campaign IDs no campaign_stats têm 18 dígitos, mas costs_hierarchy tem 15
            campaign_id_short = str(campaign_id)[:15]
            if campaign_id_short in campaigns:
                camp_data = campaigns[campaign_id_short]

        if not camp_data:
            # MÉTODO 2: Fallback - match por nome
            campaign_name_clean = campaign_name
            if campaign_id:
                campaign_name_clean = '|'.join(campaign_name.split('|')[:-1]).strip()

            # Procurar por nome exato
            for camp_id, data in campaigns.items():
                if data.get('name', '').strip() == campaign_name_clean.strip():
                    camp_data = data
                    break

        if camp_data:
            return camp_data.get('account_id', '')

        return ""

    def _get_campaign_current_name(self, campaign_name: str, costs_hierarchy: Dict) -> str:
        """
        Busca o nome ATUAL de uma campanha na Meta (do costs_hierarchy).

        Isso substitui nomes desatualizados dos UTMs pelos nomes atuais da Meta API.

        Args:
            campaign_name: Nome da campanha dos UTMs (pode incluir |ID no final)
            costs_hierarchy: Dicionário retornado por get_costs_hierarchy()

        Returns:
            Nome atual da campanha na Meta, ou nome original se não encontrar
        """
        if not costs_hierarchy:
            return campaign_name

        campaigns = costs_hierarchy.get('campaigns', {})
        if not campaigns:
            return campaign_name

        # MÉTODO 1: Tentar match por Campaign ID (mais preciso)
        campaign_id = self._extract_campaign_id(campaign_name)
        camp_data = None

        if campaign_id and campaign_id in campaigns:
            camp_data = campaigns[campaign_id]
        elif campaign_id:
            # MÉTODO 1.5: Match pelos primeiros 15 dígitos (costs_hierarchy trunca IDs)
            # Campaign IDs no campaign_stats têm 18 dígitos, mas costs_hierarchy tem 15
            campaign_id_short = str(campaign_id)[:15]
            if campaign_id_short in campaigns:
                camp_data = campaigns[campaign_id_short]

        if not camp_data:
            # MÉTODO 2: Fallback - match por nome
            campaign_name_clean = campaign_name
            if campaign_id:
                campaign_name_clean = '|'.join(campaign_name.split('|')[:-1]).strip()

            # Procurar por nome exato
            for camp_id, data in campaigns.items():
                if data.get('name', '').strip() == campaign_name_clean.strip():
                    camp_data = data
                    break

        if camp_data:
            current_name = camp_data.get('name', '')
            if current_name:
                # Retornar nome atual + ID (para manter formato consistente)
                # Usar campaign_id_short (15 dígitos) se disponível
                if campaign_id:
                    campaign_id_short = str(campaign_id)[:15]
                    return f"{current_name}|{campaign_id_short}"
                else:
                    return current_name

        # Fallback: retornar nome original
        return campaign_name

    def _get_campaign_leads_from_costs(self, campaign_name: str, costs_hierarchy: Dict) -> int:
        """
        Busca o número de leads de uma campanha específica do costs_hierarchy (dados Excel).

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            costs_hierarchy: Dicionário retornado por build_costs_hierarchy()

        Returns:
            Número de leads (int)
        """
        if not costs_hierarchy:
            return 0

        campaigns = costs_hierarchy.get('campaigns', {})
        if not campaigns:
            return 0

        # MÉTODO 1: Tentar match por Campaign ID (mais preciso)
        campaign_id = self._extract_campaign_id(campaign_name)

        if campaign_id:
            # Match exato primeiro
            if campaign_id in campaigns:
                return campaigns[campaign_id].get('leads', 0)

            # FALLBACK: Match pelos primeiros 15 dígitos (ignora últimos 3 dígitos)
            # Isso resolve o problema de IDs que terminam em 390 vs 000
            campaign_id_prefix = campaign_id[:15] if len(campaign_id) >= 15 else campaign_id

            for cost_id, cost_data in campaigns.items():
                cost_id_prefix = cost_id[:15] if len(cost_id) >= 15 else cost_id
                if campaign_id_prefix == cost_id_prefix:
                    return cost_data.get('leads', 0)

        return 0

    def _get_campaign_custom_event_from_costs(
        self,
        campaign_name: str,
        costs_hierarchy: Dict,
        event_name: str
    ) -> int:
        """
        Busca a contagem de um evento customizado do costs_hierarchy (dados Excel).

        Args:
            campaign_name: Nome da campanha (pode incluir |ID no final)
            costs_hierarchy: Dicionário retornado por build_costs_hierarchy()
            event_name: Nome do evento (ex: 'LeadQualified', 'LeadQualifiedHighQuality')

        Returns:
            Contagem do evento (int)
        """
        if not costs_hierarchy:
            return 0

        campaigns = costs_hierarchy.get('campaigns', {})
        if not campaigns:
            return 0

        # MÉTODO 1: Tentar match por Campaign ID (mais preciso)
        campaign_id = self._extract_campaign_id(campaign_name)

        if campaign_id:
            # Match exato primeiro
            if campaign_id in campaigns:
                return campaigns[campaign_id].get(event_name, 0)

            # FALLBACK: Match pelos primeiros 15 dígitos (ignora últimos 3 dígitos)
            # Isso resolve o problema de IDs que terminam em 390 vs 000
            campaign_id_prefix = campaign_id[:15] if len(campaign_id) >= 15 else campaign_id

            for cost_id, cost_data in campaigns.items():
                cost_id_prefix = cost_id[:15] if len(cost_id) >= 15 else cost_id
                if campaign_id_prefix == cost_id_prefix:
                    return cost_data.get(event_name, 0)

        return 0


class DecileMetricsCalculator:
    """
    Calcula métricas de performance por decil (D1-D10).

    IMPORTANTE: Modelo foi treinado APENAS com vendas Guru.
    Por isso calculamos métricas separadas:
    - Guru: Performance nos dados de treinamento
    - Guru+TMB: Performance em todos os dados (generalização)
    """

    def __init__(self, conversion_rates: Optional[Dict[str, float]] = None):
        """Inicializa calculadora de métricas de decil.

        Args:
            conversion_rates: taxas de conversão esperadas por decil (ClientConfig.business.conversion_rates).
                              Se None, usa CONVERSION_RATES de business_config.py (devclub legacy).
        """
        self.expected_rates = conversion_rates if conversion_rates is not None else CONVERSION_RATES

    def calculate_decile_performance(
        self,
        matched_df: pd.DataFrame,
        product_value: float
    ) -> pd.DataFrame:
        """
        Calcula métricas reais por decil separando Guru vs Guru+TMB.

        Args:
            matched_df: DataFrame com matching realizado
            product_value: Valor do produto

        Returns:
            DataFrame com métricas por decil:
            - decile: D1-D10
            - leads: Total de leads
            - conversions_guru: Conversões Guru
            - conversions_total: Conversões Total (Guru+TMB)
            - conversion_rate_guru: Taxa conversão Guru (%)
            - conversion_rate_total: Taxa conversão Total (%)
            - expected_conversion_rate: Taxa esperada do modelo (%)
            - performance_ratio_guru: Guru / Esperado
            - performance_ratio_total: Total / Esperado
            - revenue_guru: Receita Guru
            - revenue_total: Receita Total
        """
        logger.info(" Calculando performance por decil...")

        # Filtrar apenas leads com decil definido
        df_with_decile = matched_df[matched_df['decile'].notna()].copy()

        if len(df_with_decile) == 0:
            logger.warning(" Nenhum lead com decil definido")
            return pd.DataFrame()

        logger.info(f"   {len(df_with_decile)} leads com decil definido")

        decile_metrics = []

        for decile in ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9', 'D10']:
            decile_df = df_with_decile[df_with_decile['decile'] == decile]

            # Total de leads
            leads = len(decile_df)

            if leads == 0:
                # Pular decil sem leads
                continue

            # Conversões separadas por origem
            conversions_guru = len(decile_df[
                (decile_df['converted'] == True) &
                (decile_df['sale_origin'] == 'guru')
            ])

            conversions_total = len(decile_df[decile_df['converted'] == True])

            # Taxas de conversão
            conversion_rate_guru = (conversions_guru / leads * 100) if leads > 0 else 0
            conversion_rate_total = (conversions_total / leads * 100) if leads > 0 else 0

            # Taxa esperada do modelo (em %)
            expected_rate = self.expected_rates.get(decile, 0) * 100

            # Performance ratios (real / esperado)
            performance_ratio_guru = (
                (conversion_rate_guru / expected_rate) if expected_rate > 0 else 0
            )
            performance_ratio_total = (
                (conversion_rate_total / expected_rate) if expected_rate > 0 else 0
            )

            # Receitas
            revenue_guru = conversions_guru * product_value
            revenue_total = conversions_total * product_value

            decile_metrics.append({
                'decile': decile,
                'leads': leads,
                'conversions_guru': conversions_guru,
                'conversions_total': conversions_total,
                'conversion_rate_guru': round(conversion_rate_guru, 2),
                'conversion_rate_total': round(conversion_rate_total, 2),
                'expected_conversion_rate': round(expected_rate, 2),
                'performance_ratio_guru': round(performance_ratio_guru, 2),
                'performance_ratio_total': round(performance_ratio_total, 2),
                'revenue_guru': round(revenue_guru, 2),
                'revenue_total': round(revenue_total, 2),
            })

        df_metrics = pd.DataFrame(decile_metrics)

        if len(df_metrics) > 0:
            logger.info(f"    Métricas calculadas para {len(df_metrics)} decis")

            # Log summary
            total_guru = df_metrics['revenue_guru'].sum()
            total_all = df_metrics['revenue_total'].sum()
            logger.info(f"      Receita Guru: R$ {total_guru:,.2f}")
            logger.info(f"      Receita Total: R$ {total_all:,.2f}")
        else:
            logger.warning("    Nenhum decil com leads suficientes")

        return df_metrics


def compare_ml_vs_non_ml(campaign_metrics: pd.DataFrame) -> Dict:
    """
    Compara agregado de campanhas COM_ML vs SEM_ML.

    Args:
        campaign_metrics: DataFrame retornado por CampaignMetricsCalculator

    Returns:
        Dicionário com comparação:
        {
            'com_ml': {leads, conversions, conversion_rate, revenue, spend, cpl, roas, margin},
            'sem_ml': {leads, conversions, conversion_rate, revenue, spend, cpl, roas, margin},
            'difference': {leads_diff, conversions_diff, conversion_rate_diff, revenue_diff, spend_diff, cpl_diff, roas_diff, margin_diff}
        }
    """
    logger.info(" Comparando COM_ML vs SEM_ML...")

    # Separar por tipo
    com_ml = campaign_metrics[campaign_metrics['ml_type'] == 'COM_ML']
    sem_ml = campaign_metrics[campaign_metrics['ml_type'] == 'SEM_ML']

    def aggregate_metrics(df: pd.DataFrame) -> Dict:
        """Agrega métricas de múltiplas campanhas."""
        if len(df) == 0:
            return {
                'leads': 0,
                'conversions': 0,
                'conversion_rate': 0,
                'revenue': 0,
                'spend': 0,
                'cpl': 0,
                'roas': 0,
                'margin': 0,
                'revenue_adjusted': 0,
                'roas_adjusted': 0,
                'margin_adjusted': 0,
            }

        total_leads = df['leads'].sum()
        total_conversions = df['conversions'].sum()
        total_revenue = df['total_revenue'].sum()
        total_spend = df['spend'].sum()

        conversion_rate = (total_conversions / total_leads * 100) if total_leads > 0 else 0
        cpl = (total_spend / total_leads) if total_leads > 0 else 0
        roas = (total_revenue / total_spend) if total_spend > 0 else 0
        margin = total_revenue - total_spend

        # Métricas ajustadas por TMB (se disponíveis)
        total_revenue_adjusted = df['total_revenue_adjusted'].sum() if 'total_revenue_adjusted' in df.columns else total_revenue
        roas_adjusted = (total_revenue_adjusted / total_spend) if total_spend > 0 else 0
        margin_adjusted = total_revenue_adjusted - total_spend

        return {
            'leads': int(total_leads),
            'conversions': int(total_conversions),
            'conversion_rate': round(conversion_rate, 2),
            'revenue': round(total_revenue, 2),
            'spend': round(total_spend, 2),
            'cpl': round(cpl, 2),
            'roas': round(roas, 2),
            'margin': round(margin, 2),
            'revenue_adjusted': round(total_revenue_adjusted, 2),
            'roas_adjusted': round(roas_adjusted, 2),
            'margin_adjusted': round(margin_adjusted, 2),
        }

    com_ml_agg = aggregate_metrics(com_ml)
    sem_ml_agg = aggregate_metrics(sem_ml)

    # Calcular diferenças percentuais
    def calc_diff(com, sem, key):
        """Calcula diferença percentual."""
        if sem == 0:
            return 0
        return round(((com - sem) / sem * 100), 2)

    difference = {
        'leads_diff': calc_diff(com_ml_agg['leads'], sem_ml_agg['leads'], 'leads'),
        'conversions_diff': calc_diff(com_ml_agg['conversions'], sem_ml_agg['conversions'], 'conversions'),
        'conversion_rate_diff': calc_diff(
            com_ml_agg['conversion_rate'],
            sem_ml_agg['conversion_rate'],
            'conversion_rate'
        ),
        'revenue_diff': calc_diff(com_ml_agg['revenue'], sem_ml_agg['revenue'], 'revenue'),
        'spend_diff': calc_diff(com_ml_agg['spend'], sem_ml_agg['spend'], 'spend'),
        'cpl_diff': calc_diff(com_ml_agg['cpl'], sem_ml_agg['cpl'], 'cpl'),
        'roas_diff': calc_diff(com_ml_agg['roas'], sem_ml_agg['roas'], 'roas'),
        'margin_diff': calc_diff(com_ml_agg['margin'], sem_ml_agg['margin'], 'margin'),
        'revenue_adjusted_diff': calc_diff(com_ml_agg['revenue_adjusted'], sem_ml_agg['revenue_adjusted'], 'revenue_adjusted'),
        'roas_adjusted_diff': calc_diff(com_ml_agg['roas_adjusted'], sem_ml_agg['roas_adjusted'], 'roas_adjusted'),
        'margin_adjusted_diff': calc_diff(com_ml_agg['margin_adjusted'], sem_ml_agg['margin_adjusted'], 'margin_adjusted'),
    }

    logger.info(f"   COM_ML: {com_ml_agg['leads']} leads, {com_ml_agg['conversions']} conversões, ROAS {com_ml_agg['roas']:.2f}x")
    logger.info(f"   SEM_ML: {sem_ml_agg['leads']} leads, {sem_ml_agg['conversions']} conversões, ROAS {sem_ml_agg['roas']:.2f}x")

    if com_ml_agg['roas'] > sem_ml_agg['roas']:
        improvement = difference['roas_diff']
        logger.info(f"    VENCEDOR: COM_ML (ROAS {improvement:.1f}% maior)")
    elif sem_ml_agg['roas'] > com_ml_agg['roas']:
        decline = abs(difference['roas_diff'])
        logger.warning(f"    SEM_ML performou {decline:.1f}% melhor")
    else:
        logger.info(f"    Empate técnico")

    return {
        'com_ml': com_ml_agg,
        'sem_ml': sem_ml_agg,
        'difference': difference
    }


def calculate_overall_stats(
    matched_df: pd.DataFrame,
    campaign_metrics: pd.DataFrame,
    lead_period: tuple = None,
    sales_period: tuple = None,
    sales_df: pd.DataFrame = None,
    product_value: float = 2000.0,
    excluded_leads: int = 0,
    campaign_calc: 'CampaignMetricsCalculator' = None,
    lead_source_stats: Dict = None
) -> Dict:
    """
    Calcula estatísticas gerais do sistema.

    IMPORTANTE: Métricas de receita/conversão usam TODAS as vendas do período,
    não apenas as identificadas/matched. Apenas a taxa de tracking usa vendas matched.

    Args:
        matched_df: DataFrame com matching (para calcular tracking rate)
        campaign_metrics: DataFrame com métricas de campanhas
        lead_period: Tupla (start_date, end_date) do período de captação
        sales_period: Tupla (start_date, end_date) do período de vendas
        sales_df: DataFrame com TODAS as vendas do período (não apenas matched)
        product_value: Valor do produto (para calcular receita se sale_value não disponível)

    Returns:
        Dicionário com estatísticas gerais
    """
    total_leads = len(matched_df)
    total_spend = campaign_metrics['spend'].sum()

    # Conversões IDENTIFICADAS (matched)
    matched_conversions = len(matched_df[matched_df['converted'] == True])

    # Se sales_df fornecido, usar TODAS as vendas do período
    # Caso contrário, fallback para vendas matched
    if sales_df is not None and not sales_df.empty:
        # TOTAL de vendas do período (não apenas matched)
        total_conversions = len(sales_df)

        # Conversões por origem (TODAS, não apenas matched)
        # Coluna 'origem' vem do data_loader.py (linhas 291 e 398)
        if 'origem' in sales_df.columns:
            conversions_guru_total = len(sales_df[sales_df['origem'] == 'guru'])
            conversions_tmb_total = len(sales_df[sales_df['origem'] == 'tmb'])
        else:
            logger.warning(" Coluna 'origem' não encontrada em sales_df")
            conversions_guru_total = 0
            conversions_tmb_total = 0

        # Conversões IDENTIFICADAS por origem (somente matched)
        if 'sale_origin' in matched_df.columns:
            conversions_guru_matched = len(matched_df[
                (matched_df['converted'] == True) &
                (matched_df['sale_origin'] == 'guru')
            ])
            conversions_tmb_matched = len(matched_df[
                (matched_df['converted'] == True) &
                (matched_df['sale_origin'] == 'tmb')
            ])
        else:
            logger.warning(" Coluna 'sale_origin' não encontrada em matched_df")
            conversions_guru_matched = 0
            conversions_tmb_matched = 0

        # Receita TOTAL do período
        if 'sale_value' in sales_df.columns:
            total_revenue = sales_df['sale_value'].sum()
        else:
            # Se não tiver sale_value, usar product_value * quantidade
            total_revenue = len(sales_df) * product_value

    else:
        # Fallback: usar apenas vendas matched
        logger.warning(" sales_df não fornecido, usando apenas vendas matched para estatísticas gerais")
        total_conversions = matched_conversions
        total_revenue = matched_df[matched_df['converted'] == True]['sale_value'].sum()

        conversions_guru_total = len(matched_df[
            (matched_df['converted'] == True) &
            (matched_df['sale_origin'] == 'guru')
        ])
        conversions_tmb_total = len(matched_df[
            (matched_df['converted'] == True) &
            (matched_df['sale_origin'] == 'tmb')
        ])
        conversions_guru_matched = conversions_guru_total
        conversions_tmb_matched = conversions_tmb_total

    # Calcular total de leads da Meta (soma de todas as campanhas)
    # IMPORTANTE: Usar valor salvo ANTES de filtrar campanhas com spend=0
    # Isso garante que o total esteja correto mesmo se campanhas foram removidas
    total_leads_meta = 0

    # Tentar obter do CampaignMetricsCalculator (salvo antes do filtro)
    if campaign_calc and hasattr(campaign_calc, 'total_leads_meta_before_filter'):
        total_leads_meta = campaign_calc.total_leads_meta_before_filter
        logger.info(f"    Usando total de leads salvo antes do filtro: {total_leads_meta}")
    # Fallback: usar campaign_metrics (pode estar incorreto se campanhas foram filtradas)
    elif 'leads' in campaign_metrics.columns and not campaign_metrics.empty:
        total_leads_meta = campaign_metrics['leads'].sum()
    else:
        logger.warning(" 'leads' não encontrado ou campaign_metrics vazio")

    # Métricas gerais (baseadas em TODAS as vendas)
    conversion_rate = (total_conversions / total_leads * 100) if total_leads > 0 else 0
    roas = (total_revenue / total_spend) if total_spend > 0 else 0
    margin = total_revenue - total_spend

    result = {
        'total_leads_meta': int(total_leads_meta),  # Leads da Meta (cadastros)
        'total_leads': total_leads,  # Respostas da pesquisa (apenas com UTM Meta válida)
        'total_leads_including_excluded': total_leads + excluded_leads,  # TODAS as respostas (incluindo sem UTM)
        'excluded_leads': excluded_leads,  # Leads sem UTM válida (excluídos)
        'total_conversions': total_conversions,  # TODAS as vendas do período
        'matched_conversions': matched_conversions,  # Apenas vendas identificadas
        'conversion_rate': round(conversion_rate, 2),
        'total_revenue': round(total_revenue, 2),
        'total_spend': round(total_spend, 2),
        'roas': round(roas, 2),
        'margin': round(margin, 2),
        'conversions_guru_total': conversions_guru_total,          # Total Guru (todas)
        'conversions_guru_matched': conversions_guru_matched,      # Guru identificadas
        'conversions_tmb_total': conversions_tmb_total,            # Total TMB (todas)
        'conversions_tmb_matched': conversions_tmb_matched,        # TMB identificadas
    }

    # Adicionar estatísticas de fonte de leads se fornecidas
    if lead_source_stats:
        result['capi_leads_total'] = lead_source_stats.get('capi_leads_total', 0)
        result['capi_leads_extras'] = lead_source_stats.get('capi_leads_extras', 0)

    # IMPORTANTE: Usar total de respostas DO PERÍODO (survey_leads do data loader)
    # Este é o número de pessoas que responderam a pesquisa no período de captação
    if lead_source_stats:
        # Priorizar: usar total do período (métrica independente)
        result['survey_leads'] = lead_source_stats.get('survey_leads', 0)
        logger.info(f"    Respostas na pesquisa (período): {result['survey_leads']}")
    elif campaign_calc and hasattr(campaign_calc, 'total_respostas_before_filter'):
        # Fallback: usar respostas das campanhas analisadas
        result['survey_leads'] = campaign_calc.total_respostas_before_filter
        logger.warning(f"    Usando respostas das campanhas analisadas (não do período todo): {result['survey_leads']}")
    else:
        result['survey_leads'] = 0

    # Adicionar períodos se fornecidos
    if lead_period:
        result['lead_period_start'] = lead_period[0]
        result['lead_period_end'] = lead_period[1]
    if sales_period:
        result['sales_period_start'] = sales_period[0]
        result['sales_period_end'] = sales_period[1]

    return result


def calculate_comparison_group_metrics(
    matched_df: pd.DataFrame,
    campaign_metrics: pd.DataFrame
) -> pd.DataFrame:
    """
    Calcula métricas agregadas por comparison_group (Eventos ML, Otimização ML, Controle, Outro).

    Args:
        matched_df: DataFrame com matching e coluna 'comparison_group'
        campaign_metrics: DataFrame com métricas e custos por campanha

    Returns:
        DataFrame com métricas por grupo:
        - comparison_group: Eventos ML, Otimização ML, Controle, Outro
        - leads: Total de leads
        - conversions: Total de conversões
        - conversion_rate: Taxa de conversão (%)
        - total_revenue: Receita total
        - spend: Gasto total
        - cpl: Custo por lead
        - roas: Return on Ad Spend
        - margin: Margem de contribuição
    """
    # Verificar se a coluna comparison_group existe
    if 'comparison_group' not in matched_df.columns:
        logger.warning(" Coluna 'comparison_group' não encontrada. Retornando DataFrame vazio.")
        return pd.DataFrame()

    # DEBUG: Verificar quantas conversões existem no matched_df
    total_conversoes_linhas = len(matched_df[matched_df['converted'] == True])
    total_conversoes_unicas = matched_df[matched_df['converted'] == True]['email'].nunique()
    logger.info(f" Calculando métricas por grupo de comparação...")
    logger.info(f"    DEBUG - matched_df: {len(matched_df)} total de linhas, {total_conversoes_linhas} conversões, {total_conversoes_unicas} emails únicos convertidos")

    # Criar mapeamento campaign  spend
    campaign_spend_map = dict(zip(
        campaign_metrics['campaign'],
        campaign_metrics['spend']
    ))

    groups_metrics = []

    for group in ['Champion', 'Otimização ML', 'Challenger', 'Outro']:
        group_df = matched_df[matched_df['comparison_group'] == group]

        if len(group_df) == 0:
            continue

        # Métricas básicas
        leads = len(group_df)
        # IMPORTANTE: Contar emails únicos para conversões (consistente com campaign_metrics)
        converted_df = group_df[group_df['converted'] == True]
        conversions = converted_df['email'].nunique()

        # DEBUG: Ver total de linhas vs emails únicos
        total_converted_rows = len(converted_df)
        if total_converted_rows != conversions:
            logger.info(f"    DEBUG [{group}]: {total_converted_rows} linhas convertidas  {conversions} emails únicos")

        conversion_rate = (conversions / leads * 100) if leads > 0 else 0
        total_revenue = converted_df['sale_value'].sum()

        # Calcular spend total do grupo
        group_campaigns = group_df['campaign'].unique()
        spend = sum(campaign_spend_map.get(camp, 0) for camp in group_campaigns)

        # Métricas derivadas
        cpl = (spend / leads) if leads > 0 else 0
        roas = (total_revenue / spend) if spend > 0 else 0
        margin = total_revenue - spend

        groups_metrics.append({
            'comparison_group': group,
            'leads': leads,
            'conversions': conversions,
            'conversion_rate': round(conversion_rate, 2),
            'total_revenue': round(total_revenue, 2),
            'spend': round(spend, 2),
            'cpl': round(cpl, 2),
            'roas': round(roas, 2),
            'margin': round(margin, 2),
        })

    df_result = pd.DataFrame(groups_metrics)

    if len(df_result) > 0:
        logger.info("    Métricas calculadas por grupo:")
        for _, row in df_result.iterrows():
            logger.info(f"      {row['comparison_group']}: {row['leads']} leads, "
                       f"{row['conversions']} conversões ({row['conversion_rate']:.2f}%), "
                       f"ROAS {row['roas']:.2f}x")

    return df_result
