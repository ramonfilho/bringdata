"""
Integração com Meta Ads API
Busca dados de custo para enriquecer análise UTM
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd

logger = logging.getLogger(__name__)


class MetaAdsIntegration:
    """Cliente para integração com Meta Ads API"""

    def __init__(self, access_token: str, api_version: str = "v24.0"):
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{api_version}"

    def get_insights(
        self,
        account_id: str,
        level: str = "campaign",
        days: int = 7,
        fields: Optional[List[str]] = None,
        since_date: Optional[str] = None,
        until_date: Optional[str] = None,
        action_breakdowns: Optional[List[str]] = None,
        action_attribution_windows: Optional[List[str]] = None,
        filtering: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Busca insights (métricas) de uma conta de anúncios

        Args:
            account_id: ID da conta (formato: act_XXXXXXXXX ou apenas o número)
            level: Nível de agregação (campaign, adset, ad)
            days: Número de dias para buscar dados (ignorado se since_date/until_date forem fornecidos)
            fields: Campos a retornar (padrão: campaign_name, spend, impressions, clicks, actions)
            since_date: Data início (formato YYYY-MM-DD), se None usa days
            until_date: Data fim EXCLUSIVA (formato YYYY-MM-DD), se None usa ontem
            action_breakdowns: Breakdowns para ações (ex: ['action_type'] para eventos detalhados)
            action_attribution_windows: Janelas de atribuição (ex: ['7d_click', '1d_view'] - padrão do Meta Ads Manager)
            filtering: Filtros para aplicar (ex: [{'field': 'delivery_info', 'operator': 'IN', 'value': ['active']}])

        Returns:
            Lista de dicts com dados de cada campanha/adset/ad
        """
        # Normalizar account_id (adicionar prefixo act_ se necessário)
        if not account_id.startswith('act_'):
            account_id = f'act_{account_id}'

        if fields is None:
            fields = ['campaign_name', 'adset_name', 'ad_name', 'spend', 'impressions', 'clicks', 'actions']

        url = f"{self.base_url}/{account_id}/insights"

        # Calcular período
        if since_date and until_date:
            since = since_date
            # Meta API: until é INCLUSIVO na interface mas EXCLUSIVO na API
            # Usar until_date diretamente (já vem como o dia seguinte ao desejado)
            until = until_date
        else:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            until = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')  # Ontem, não hoje!

        params = {
            'access_token': self.access_token,
            'level': level,
            'fields': ','.join(fields),
            'time_range': f'{{"since":"{since}","until":"{until}"}}',
            'limit': 1000
        }

        # Adicionar breakdowns se fornecidos
        if action_breakdowns:
            params['action_breakdowns'] = ','.join(action_breakdowns)

        # Adicionar janelas de atribuição se fornecidas
        if action_attribution_windows:
            params['action_attribution_windows'] = str(action_attribution_windows).replace("'", '"')

        # Adicionar filtros se fornecidos
        if filtering:
            import json
            params['filtering'] = json.dumps(filtering)

        logger.info(f"Buscando insights: account={account_id}, level={level}, days={days}, attribution={action_attribution_windows or 'default'}, filtering={bool(filtering)}")

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            results = data.get('data', [])

            logger.info(f"✅ Insights obtidos: {len(results)} registros")
            return results

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Erro ao buscar insights: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            return []

    def get_campaign_budget_info(self, campaign_id: str) -> Dict:
        """
        Busca informações de orçamento e otimização de uma campanha específica

        Args:
            campaign_id: ID da campanha

        Returns:
            Dict com informações de budget e otimização:
            {
                'has_campaign_budget': bool,  # True se CBO, False se ABO
                'daily_budget': float ou None,
                'lifetime_budget': float ou None,
                'bid_strategy': str,
                'objective': str,  # Ex: OUTCOME_LEADS, OUTCOME_TRAFFIC
                'status': str  # ACTIVE, PAUSED, etc
            }
        """
        url = f"{self.base_url}/{campaign_id}"

        params = {
            'access_token': self.access_token,
            'fields': 'daily_budget,lifetime_budget,bid_strategy,objective,status'
        }

        try:
            response = requests.get(url, params=params, timeout=3)
            response.raise_for_status()
            data = response.json()

            # Verificar se tem budget na campaign (CBO)
            has_campaign_budget = bool(data.get('daily_budget') or data.get('lifetime_budget'))

            # Meta API retorna budgets em centavos - converter para reais
            daily_budget = float(data.get('daily_budget', 0) or 0) / 100 if data.get('daily_budget') else None
            lifetime_budget = float(data.get('lifetime_budget', 0) or 0) / 100 if data.get('lifetime_budget') else None

            return {
                'has_campaign_budget': has_campaign_budget,
                'daily_budget': daily_budget,
                'lifetime_budget': lifetime_budget,
                'bid_strategy': data.get('bid_strategy'),
                'objective': data.get('objective'),
                'status': data.get('status')
            }

        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️  Erro ao buscar budget info da campaign {campaign_id}: {e}")
            # Default: assumir que tem budget (comportamento atual)
            return {
                'has_campaign_budget': True,
                'daily_budget': None,
                'lifetime_budget': None,
                'bid_strategy': None,
                'objective': None,
                'status': None
            }

    def get_adset_optimization_goal(self, adset_id: str) -> str:
        """
        Busca o evento de conversão customizado de um adset.

        Prioriza promoted_object.custom_event_str (evento específico como LeadQualified)
        sobre optimization_goal genérico (OFFSITE_CONVERSIONS).

        Args:
            adset_id: ID do adset

        Returns:
            String com evento de conversão (ex: 'LeadQualified', 'LeadQualifiedHighQuality', 'Faixa A')
            ou optimization_goal se não houver evento customizado
            ou None se não encontrado
        """
        url = f"{self.base_url}/{adset_id}"

        params = {
            'access_token': self.access_token,
            'fields': 'optimization_goal,promoted_object'
        }

        try:
            response = requests.get(url, params=params, timeout=3)
            response.raise_for_status()
            data = response.json()

            # Priorizar promoted_object.custom_event_str (evento específico)
            promoted_obj = data.get('promoted_object', {})
            custom_event = promoted_obj.get('custom_event_str')

            if custom_event:
                # Evento customizado encontrado (LeadQualified, LeadQualifiedHighQuality, etc.)
                return custom_event
            else:
                # Fallback para optimization_goal genérico
                return data.get('optimization_goal')

        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️  Erro ao buscar dados do adset {adset_id}: {e}")
            return None

    def batch_get_adset_optimization_goals(
        self,
        adset_ids: List[str],
    ) -> Dict[str, Optional[str]]:
        """Versão em batch de `get_adset_optimization_goal` para N adsets.

        Reduz N GETs sequenciais a ⌈N/50⌉ HTTP calls. Mantém mesma semântica:
        prioriza `promoted_object.custom_event_str` sobre `optimization_goal`.

        Returns:
            Dict {adset_id: optimization_goal | None}. `None` indica que o
            request falhou ou que o adset não tem nem custom_event nem
            optimization_goal. Caller decide como tratar.
        """
        import json as _json

        BATCH_LIMIT = 50
        result: Dict[str, Optional[str]] = {}
        ids = list(adset_ids)

        for batch_start in range(0, len(ids), BATCH_LIMIT):
            chunk = ids[batch_start:batch_start + BATCH_LIMIT]
            batch = [
                {
                    "method": "GET",
                    "relative_url": (
                        f"{self.api_version}/{aid}"
                        f"?fields=optimization_goal,promoted_object"
                    ),
                }
                for aid in chunk
            ]
            try:
                r = requests.post(
                    "https://graph.facebook.com/",
                    data={
                        "access_token": self.access_token,
                        "batch": _json.dumps(batch),
                    },
                    timeout=30,
                )
                r.raise_for_status()
                responses = r.json()
            except Exception as e:
                logger.warning(
                    "[batch_get_adset_optimization_goals] batch falhou (%d adsets): %s",
                    len(chunk), e,
                )
                for aid in chunk:
                    result[aid] = None
                continue

            for aid, resp in zip(chunk, responses):
                if not resp:
                    result[aid] = None
                    continue
                try:
                    code = int(resp.get("code") or 0)
                except (TypeError, ValueError):
                    code = 0
                if code != 200:
                    logger.warning(
                        "[batch_get_adset_optimization_goals] adset %s falhou (code=%s): %s",
                        aid, code, (resp.get("body") or "")[:200],
                    )
                    result[aid] = None
                    continue
                try:
                    body = _json.loads(resp["body"])
                except Exception as e:
                    logger.warning(
                        "[batch_get_adset_optimization_goals] adset %s parse falhou: %s",
                        aid, e,
                    )
                    result[aid] = None
                    continue
                promoted = body.get("promoted_object") or {}
                result[aid] = promoted.get("custom_event_str") or body.get("optimization_goal")

        return result

    def batch_get_adsets(
        self,
        campaign_ids: List[str],
        fields: Optional[List[str]] = None,
        limit_per_campaign: int = 100,
    ) -> Dict[str, Optional[List[Dict]]]:
        """Busca adsets de várias campanhas via Graph Batch API.

        Reduz N requests sequenciais a 1 HTTP call (chunks de 50, limite Meta).
        Encapsula versão da API, parsing por cid e tolerância a erro por cid.

        Args:
            campaign_ids: lista de campaign_ids (15-18 dígitos).
            fields: campos do adset a retornar. Default: optimization_goal + promoted_object.
            limit_per_campaign: paginação Meta por campanha (default 100).

        Returns:
            Dict {cid: [adsets] | None}. `None` indica que o request falhou
            para aquele cid (parse error, code != 200, response vazio). Lista
            vazia indica campanha sem adsets. Caller decide como tratar `None`
            (não cachear, omitir do resultado, etc.).

        Docs: https://developers.facebook.com/docs/graph-api/making-multiple-requests
        """
        import json as _json

        if fields is None:
            fields = ['optimization_goal', 'promoted_object']
        fields_str = ','.join(fields)

        BATCH_LIMIT = 50  # hard limit Meta Graph API
        result: Dict[str, Optional[List[Dict]]] = {}
        cids = list(campaign_ids)

        for batch_start in range(0, len(cids), BATCH_LIMIT):
            chunk = cids[batch_start:batch_start + BATCH_LIMIT]
            batch = [
                {
                    "method": "GET",
                    "relative_url": (
                        f"{self.api_version}/{cid}/adsets"
                        f"?fields={fields_str}&limit={limit_per_campaign}"
                    ),
                }
                for cid in chunk
            ]
            try:
                r = requests.post(
                    "https://graph.facebook.com/",
                    data={
                        "access_token": self.access_token,
                        "batch": _json.dumps(batch),
                    },
                    timeout=30,
                )
                r.raise_for_status()
                responses = r.json()
            except Exception as e:
                logger.warning(
                    "[batch_get_adsets] batch falhou (%d cids): %s", len(chunk), e
                )
                for cid in chunk:
                    result[cid] = None
                continue

            for cid, resp in zip(chunk, responses):
                if not resp:
                    result[cid] = None
                    continue
                try:
                    code = int(resp.get("code") or 0)
                except (TypeError, ValueError):
                    code = 0
                if code != 200:
                    logger.warning(
                        "[batch_get_adsets] campaign %s falhou (code=%s): %s",
                        cid, code, (resp.get("body") or "")[:200],
                    )
                    result[cid] = None
                    continue
                try:
                    body = _json.loads(resp["body"])
                except Exception as e:
                    logger.warning(
                        "[batch_get_adsets] campaign %s parse falhou: %s", cid, e
                    )
                    result[cid] = None
                    continue
                result[cid] = body.get("data", []) or []

        return result

    def get_adset_budget_info(self, adset_id: str) -> Dict:
        """
        Busca informações de orçamento e otimização de um adset específico

        Args:
            adset_id: ID do adset

        Returns:
            Dict com informações de budget e otimização:
            {
                'has_adset_budget': bool,  # True se ABO (adset tem budget próprio), False se CBO (usa budget da campanha)
                'daily_budget': float ou None,
                'lifetime_budget': float ou None,
                'optimization_goal': str,  # Ex: 'LEAD', 'LeadQualified', 'LeadQualifiedHighQuality'
                'status': str  # ACTIVE, PAUSED, etc
            }
        """
        url = f"{self.base_url}/{adset_id}"

        params = {
            'access_token': self.access_token,
            'fields': 'daily_budget,lifetime_budget,optimization_goal,status'
        }

        try:
            response = requests.get(url, params=params, timeout=3)
            response.raise_for_status()
            data = response.json()

            # Verificar se tem budget no adset (ABO)
            # Se não tem budget, significa que usa o budget da campanha (CBO)
            has_adset_budget = bool(data.get('daily_budget') or data.get('lifetime_budget'))

            # Meta API retorna budgets em centavos - converter para reais
            daily_budget = float(data.get('daily_budget', 0) or 0) / 100 if data.get('daily_budget') else None
            lifetime_budget = float(data.get('lifetime_budget', 0) or 0) / 100 if data.get('lifetime_budget') else None

            return {
                'has_adset_budget': has_adset_budget,
                'daily_budget': daily_budget,
                'lifetime_budget': lifetime_budget,
                'optimization_goal': data.get('optimization_goal'),
                'status': data.get('status')
            }

        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️  Erro ao buscar budget info do adset {adset_id}: {e}")
            # Default: assumir que tem budget próprio (comportamento conservador)
            return {
                'has_adset_budget': True,
                'daily_budget': None,
                'lifetime_budget': None,
                'optimization_goal': None,
                'status': None
            }

    def get_costs_hierarchy(
        self,
        account_id: str,
        days: int = 7,
        since_date: Optional[str] = None,
        until_date: Optional[str] = None
    ) -> Dict[str, Dict]:
        """
        Busca hierarquia completa: Campaign → Adsets → Ads com custos individuais

        Args:
            account_id: ID da conta (formato: act_XXXXXXXXX ou apenas o número)
            days: Número de dias (ignorado se since_date/until_date forem fornecidos)
            since_date: Data início (formato YYYY-MM-DD)
            until_date: Data fim EXCLUSIVA (formato YYYY-MM-DD)

        Returns:
            {
                'campaigns': {
                    campaign_id: {
                        'id': campaign_id,
                        'name': campaign_name,
                        'spend': campaign_spend,
                        'has_campaign_budget': bool,  # True se CBO, False se ABO
                        'adsets': {
                            adset_id: {
                                'id': adset_id,
                                'name': adset_name,
                                'spend': adset_spend,
                                'ads': {
                                    ad_id: {
                                        'id': ad_id,
                                        'name': ad_name,
                                        'spend': ad_spend
                                    }
                                }
                            }
                        }
                    }
                }
            }
        """
        # Normalizar account_id (adicionar prefixo act_ se necessário)
        if not account_id.startswith('act_'):
            account_id = f'act_{account_id}'

        logger.info("🔍 Buscando hierarquia completa de campanhas...")

        hierarchy = {'campaigns': {}}

        # 1. Buscar todos os Ads (nível mais granular)
        fields = [
            'campaign_id', 'campaign_name',
            'adset_id', 'adset_name',
            'ad_id', 'ad_name',
            'spend'
        ]

        ads_data = self.get_insights(
            account_id,
            level='ad',
            days=days,
            fields=fields,
            since_date=since_date,
            until_date=until_date
        )

        logger.info(f"   Processando {len(ads_data)} ads...")

        # DEBUG: Log primeiros 5 ads retornados pela API
        if len(ads_data) > 0:
            logger.info("   📋 DEBUG - Primeiros 5 ads retornados pela API Meta:")
            for i, ad in enumerate(ads_data[:5]):
                logger.info(f"      Ad #{i+1}: campaign_id={ad.get('campaign_id')}, spend={ad.get('spend')}, ad_name={ad.get('ad_name', 'N/A')[:40]}")

        # 2. Construir hierarquia bottom-up
        for ad_item in ads_data:
            campaign_id = ad_item.get('campaign_id')
            campaign_name = ad_item.get('campaign_name')
            adset_id = ad_item.get('adset_id')
            adset_name = ad_item.get('adset_name')
            ad_id = ad_item.get('ad_id')
            ad_name = ad_item.get('ad_name')
            spend = float(ad_item.get('spend', 0))

            # Criar estrutura de campaign se não existe
            if campaign_id not in hierarchy['campaigns']:
                hierarchy['campaigns'][campaign_id] = {
                    'id': campaign_id,
                    'name': campaign_name,
                    'spend': 0,
                    'adsets': {}
                }

            # Criar estrutura de adset se não existe
            if adset_id not in hierarchy['campaigns'][campaign_id]['adsets']:
                hierarchy['campaigns'][campaign_id]['adsets'][adset_id] = {
                    'id': adset_id,
                    'name': adset_name,
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'spend': 0,
                    'ads': {}
                }

            # Adicionar ad
            hierarchy['campaigns'][campaign_id]['adsets'][adset_id]['ads'][ad_id] = {
                'id': ad_id,
                'name': ad_name,
                'spend': spend
            }

            # Acumular spend nos níveis superiores
            hierarchy['campaigns'][campaign_id]['adsets'][adset_id]['spend'] += spend
            hierarchy['campaigns'][campaign_id]['spend'] += spend

        logger.info(f"✅ Hierarquia construída: {len(hierarchy['campaigns'])} campanhas")

        # 3. Buscar informações de budget e objective para cada campaign
        logger.info("   🔍 Buscando informações de orçamento das campanhas...")
        for campaign_id in hierarchy['campaigns'].keys():
            budget_info = self.get_campaign_budget_info(campaign_id)
            hierarchy['campaigns'][campaign_id]['has_campaign_budget'] = budget_info['has_campaign_budget']
            hierarchy['campaigns'][campaign_id]['daily_budget'] = budget_info['daily_budget']
            hierarchy['campaigns'][campaign_id]['lifetime_budget'] = budget_info['lifetime_budget']
            hierarchy['campaigns'][campaign_id]['objective'] = budget_info['objective']
            hierarchy['campaigns'][campaign_id]['status'] = budget_info['status']

            budget_type = "CBO (Campaign Budget)" if budget_info['has_campaign_budget'] else "ABO (AdSet Budget)"
            logger.info(f"      {campaign_id}: {budget_type}")

        # 4. Buscar optimization_goal para cada adset (CAPI detection)
        logger.info("   🎯 Buscando optimization_goal dos adsets (detecção CAPI)...")
        adset_count = 0
        capi_adsets = 0

        for campaign_id, campaign_data in hierarchy['campaigns'].items():
            for adset_id in campaign_data['adsets'].keys():
                adset_count += 1
                optimization_goal = self.get_adset_optimization_goal(adset_id)
                hierarchy['campaigns'][campaign_id]['adsets'][adset_id]['optimization_goal'] = optimization_goal

                # Contar adsets usando eventos CAPI customizados
                if optimization_goal and optimization_goal in ['LeadQualified', 'LeadQualifiedHighQuality']:
                    capi_adsets += 1

        logger.info(f"   ✅ {adset_count} adsets verificados")
        logger.info(f"   🎯 {capi_adsets} adsets usando eventos CAPI customizados")
        logger.info(f"   📊 {adset_count - capi_adsets} adsets usando eventos padrão")

        # Código original comentado para referência:
        # logger.info("   🔍 Buscando informações de orçamento dos adsets...")
        # adset_count = 0
        # abo_count = 0
        # cbo_count = 0
        #
        # for campaign_id, campaign_data in hierarchy['campaigns'].items():
        #     for adset_id in campaign_data['adsets'].keys():
        #         adset_count += 1
        #         budget_info = self.get_adset_budget_info(adset_id)
        #         hierarchy['campaigns'][campaign_id]['adsets'][adset_id]['has_adset_budget'] = budget_info['has_adset_budget']
        #         hierarchy['campaigns'][campaign_id]['adsets'][adset_id]['daily_budget'] = budget_info['daily_budget']
        #         hierarchy['campaigns'][campaign_id]['adsets'][adset_id]['lifetime_budget'] = budget_info['lifetime_budget']
        #
        #         if budget_info['has_adset_budget']:
        #             abo_count += 1
        #         else:
        #             cbo_count += 1
        #
        # logger.info(f"      Total: {adset_count} adsets | ABO: {abo_count} | CBO: {cbo_count}")

        # DEBUG: Log hierarquia final
        logger.info("   📋 DEBUG - Hierarquia final (Campaign ID → Spend → Budget Type):")
        for camp_id, camp_data in sorted(hierarchy['campaigns'].items()):
            budget_type = "CBO" if camp_data.get('has_campaign_budget', True) else "ABO"
            logger.info(f"      {camp_id}: R$ {camp_data['spend']:.2f} ({len(camp_data['adsets'])} adsets) - {budget_type}")

        return hierarchy

    def get_costs_by_utm(
        self,
        account_id: str,
        days: int = 7
    ) -> Dict[str, Dict[str, Dict]]:
        """
        LEGADO: Mantido para compatibilidade
        Busca custos agregados por dimensões UTM com IDs

        Returns:
            {
                'campaign': {
                    'by_id': {campaign_id: {'spend': X, 'name': Y}},
                    'by_name': {campaign_name: spend}
                },
                'adset': {...},
                'ad': {...}
            }
        """
        results = {
            'campaign': {'by_id': {}, 'by_name': {}},
            'adset': {'by_id': {}, 'by_name': {}},
            'ad': {'by_id': {}, 'by_name': {}}
        }

        # Buscar em cada nível com IDs
        for level in ['campaign', 'adset', 'ad']:
            fields = [
                'campaign_id', 'campaign_name',
                'adset_id', 'adset_name',
                'ad_id', 'ad_name',
                'spend'
            ]

            insights = self.get_insights(account_id, level=level, days=days, fields=fields)

            for item in insights:
                id_key = f"{level}_id"
                name_key = f"{level}_name"

                item_id = item.get(id_key)
                name = item.get(name_key)
                spend = float(item.get('spend', 0))

                # Armazenar por ID
                if item_id:
                    if item_id in results[level]['by_id']:
                        results[level]['by_id'][item_id]['spend'] += spend
                    else:
                        results[level]['by_id'][item_id] = {'spend': spend, 'name': name}

                # Armazenar por nome (fallback)
                if name:
                    if name in results[level]['by_name']:
                        results[level]['by_name'][name] += spend
                    else:
                        results[level]['by_name'][name] = spend

        return results

    def get_costs_multiple_periods(
        self,
        account_id: str,
        periods: List[int] = [1, 3, 7]
    ) -> Dict[str, Dict[str, Dict[str, float]]]:
        """
        Busca custos para múltiplos períodos

        Args:
            periods: Lista de períodos em dias (ex: [1, 3, 7])

        Returns:
            {
                '1D': {'campaign': {...}, 'adset': {...}, 'ad': {...}},
                '3D': {'campaign': {...}, 'adset': {...}, 'ad': {...}},
                '7D': {'campaign': {...}, 'adset': {...}, 'ad': {...}}
            }
        """
        results = {}

        for days in periods:
            period_key = f"{days}D"
            logger.info(f"📅 Buscando custos para período: {period_key}")
            results[period_key] = self.get_costs_by_utm(account_id, days=days)

        return results


def extract_adset_name_from_campaign_utm(
    utm_value: str,
    utm_campaign_structure: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """
    Extrai nome do ADSET de um UTM de campaign

    Formato esperado:
    "DEVLF | CAP | FRIO | FASE 01 | ABERTO ADV+ | PG2 | 2025-04-15|120220370119870390"

    Estratégia:
    1. Remover Campaign ID do final (|números)
    2. Remover data (| YYYY-MM-DD)
    3. O nome do adset está entre o prefixo fixo e a data

    Args:
        utm_value: String UTM de campaign
        utm_campaign_structure: Dict com 'phase_prefix' e 'page_prefix' do ClientConfig.
                                Defaults: 'FASE ' e 'PG'.
    """
    import re

    if not utm_value or not isinstance(utm_value, str):
        return None

    phase_prefix = (utm_campaign_structure or {}).get('phase_prefix', 'FASE ')
    page_prefix = (utm_campaign_structure or {}).get('page_prefix', 'PG')

    # Remover Campaign ID do final
    clean = re.sub(r'\|\d{18}$', '', utm_value)

    # Remover data do final (formato | YYYY-MM-DD)
    clean = re.sub(r'\|\s*\d{4}-\d{2}-\d{2}$', '', clean)

    # Dividir por pipe
    parts = [p.strip() for p in clean.split('|') if p.strip()]

    if len(parts) == 0:
        return None

    # Estratégia: O UTM tem estrutura:
    # DEVLF | CAP | FRIO | FASE XX | [NOME ADSET] | PG2
    #
    # Nome do adset = tudo entre phase_prefix e page_prefix

    # Encontrar índice do segmento de fase
    fase_idx = None
    for i, part in enumerate(parts):
        if part.startswith(phase_prefix):
            fase_idx = i
            break

    # Encontrar índice do segmento de página
    pg_idx = None
    for i, part in enumerate(parts):
        if part.startswith(page_prefix):
            pg_idx = i
            break

    if fase_idx is not None and pg_idx is not None and fase_idx < pg_idx:
        # Pegar tudo entre FASE e PG
        adset_parts = parts[fase_idx + 1:pg_idx]
        if adset_parts:
            return ' | '.join(adset_parts)

    # Fallback: se tem mais de 4 partes, pegar do meio pra frente
    if len(parts) >= 5:
        # Pegar da 5ª parte em diante
        return ' | '.join(parts[4:])
    elif len(parts) >= 2:
        # Pegar últimas 2 partes
        return ' | '.join(parts[-2:])
    else:
        return clean


def extract_id_from_utm(utm_value: str) -> Optional[str]:
    """
    Extrai ID do valor UTM

    Formatos suportados:
    - Campaign: "...| 2025-04-15|120220370119870390" → "120220370119870390"
    - Bare ID: "120220370119870390" → "120220370119870390"
    - Composite: "22527413714--180108372678--750940275538" → extrai partes
    """
    import re

    if not utm_value or not isinstance(utm_value, str):
        return None

    utm_value = str(utm_value).strip()

    # Padrão 1: ID no final após "|" (ex: ...2025-04-15|120220370119870390)
    # Meta Ads IDs têm 18 dígitos
    match = re.search(r'\|(\d{18})$', utm_value)
    if match:
        return match.group(1)

    # Padrão 2: Apenas ID (18 dígitos, formato Meta Ads)
    if re.match(r'^\d{18}$', utm_value):
        return utm_value

    # Padrão 3: ID composto em Term (ex: XX--YY--ZZ, pegar última parte que é Ad ID)
    if '--' in utm_value:
        parts = utm_value.split('--')
        if len(parts) >= 3:
            # Formato: adset_id--campaign_id--ad_id
            # Retornar ad_id (última parte, 12 dígitos)
            return parts[-1]

    # Padrão 4: IDs de 11-12 dígitos (pode ser adset ou ad id)
    match = re.search(r'\b(\d{11,12})\b', utm_value)
    if match:
        return match.group(1)

    return None


def match_campaign_name(meta_name: str, utm_campaign: str) -> bool:
    """
    Faz matching entre nome da campanha do Meta e UTM campaign

    Meta retorna: "Campaign Name | 2025-04-15"
    UTM pode ter: "Campaign Name | 2025-04-15|120220370119870390"

    Remove campaign ID do final do UTM antes de comparar
    Usa fuzzy matching (85% similaridade) se match exato falhar
    """
    import re
    from difflib import SequenceMatcher

    # Validar entradas (evitar None ou tipos incorretos)
    if not meta_name or not utm_campaign:
        return False

    # Garantir que são strings
    meta_name = str(meta_name)
    utm_campaign = str(utm_campaign)

    # Remover campaign ID do final do UTM (padrão: |números)
    utm_clean = re.sub(r'\|\d+$', '', utm_campaign).strip()
    meta_clean = meta_name.strip()

    # Tentar match exato primeiro (mais rápido)
    if meta_clean.lower() == utm_clean.lower():
        return True

    # Fallback: fuzzy matching com threshold 85%
    # Útil quando campanha foi renomeada mas UTMs antigos ainda ativos
    similarity = SequenceMatcher(None, meta_clean.lower(), utm_clean.lower()).ratio()
    return similarity >= 0.85


def enrich_utm_analysis_with_costs(
    utm_analysis_df: pd.DataFrame,
    costs_data: Dict[str, Dict[str, Dict]],
    dimension: str
) -> pd.DataFrame:
    """
    Enriquece análise UTM com dados de custo do Meta (busca por ID primeiro, nome depois)

    Args:
        utm_analysis_df: DataFrame com análise UTM (colunas: value, leads, %D10, etc)
        costs_data: Dict com custos por dimensão (estrutura nova com by_id e by_name)
        dimension: Dimensão sendo analisada (campaign, adset, ad, medium, term, content)

    Returns:
        DataFrame enriquecido com coluna 'spend'
    """
    df = utm_analysis_df.copy()

    # Mapear dimensão para nível do Meta
    meta_level_map = {
        'campaign': 'campaign',
        'adset': 'adset',
        'ad': 'ad',
        'medium': 'adset',  # Medium = Público/Audiência = Adset
        'term': 'ad',  # Term pode conter Ad IDs compostos
        'content': 'ad'  # Content = Criativo = Ad
    }

    meta_level = meta_level_map.get(dimension)

    if meta_level is None or meta_level not in costs_data:
        df['spend'] = 0.0
        logger.warning(f"⚠️ Dimensão '{dimension}' não tem correspondente no Meta")
        return df

    # Buscar custo para cada valor da dimensão
    spend_values = []
    match_stats = {'by_id': 0, 'by_name': 0, 'no_match': 0}

    for value in df['value']:
        spend = 0.0
        match_method = None

        # ESTRATÉGIA 1: Tentar extrair e buscar por ID
        extracted_id = extract_id_from_utm(value)
        if extracted_id:
            # Buscar em by_id
            if extracted_id in costs_data[meta_level]['by_id']:
                spend = costs_data[meta_level]['by_id'][extracted_id]['spend']
                match_method = 'by_id'
                match_stats['by_id'] += 1
                logger.debug(f"      ✓ ID match: '{value}' → ID {extracted_id} (R$ {spend:.2f})")

        # ESTRATÉGIA 2: Se não encontrou por ID, buscar por nome exato
        if spend == 0.0 and value in costs_data[meta_level]['by_name']:
            spend = costs_data[meta_level]['by_name'][value]
            match_method = 'by_name_exact'
            match_stats['by_name'] += 1
            logger.debug(f"      ✓ Nome exato: '{value}' (R$ {spend:.2f})")

        # ESTRATÉGIA 3: Fuzzy matching por nome (fallback)
        if spend == 0.0:
            for meta_name, meta_spend in costs_data[meta_level]['by_name'].items():
                if match_campaign_name(meta_name, value):
                    spend = meta_spend
                    match_method = 'by_name_fuzzy'
                    match_stats['by_name'] += 1
                    logger.debug(f"      ✓ Nome fuzzy: '{value}' → '{meta_name}' (R$ {spend:.2f})")
                    break

        # Nenhum match encontrado
        if spend == 0.0:
            match_stats['no_match'] += 1
            logger.debug(f"      ⚠️ Sem match: '{value}' (ID: {extracted_id or 'N/A'})")

        spend_values.append(spend)

    df['spend'] = spend_values

    total_mapped = sum(spend_values)
    items_with_spend = sum(1 for s in spend_values if s > 0)

    logger.info(f"   ✅ {dimension}: R$ {total_mapped:.2f} em {items_with_spend}/{len(spend_values)} itens")
    logger.info(f"      Match por ID: {match_stats['by_id']}, por nome: {match_stats['by_name']}, sem match: {match_stats['no_match']}")

    return df


def enrich_utm_with_hierarchy(
    utm_analysis_df: pd.DataFrame,
    hierarchy: Dict,
    dimension: str,
    utm_campaign_structure: Optional[Dict[str, str]] = None
) -> pd.DataFrame:
    """
    Enriquece análise UTM usando hierarquia completa (evita duplicação de custos)

    Args:
        utm_analysis_df: DataFrame com análise UTM
        hierarchy: Hierarquia completa de campaigns/adsets/ads
        dimension: Dimensão sendo analisada
        utm_campaign_structure: Dict com 'phase_prefix' e 'page_prefix' do ClientConfig

    Returns:
        DataFrame enriquecido com coluna 'spend'
        Para campaigns, também adiciona 'has_campaign_budget' (True=CBO, False=ABO)
        Para adsets (medium), também adiciona 'has_adset_budget' (True=ABO, False=CBO)
    """
    from difflib import SequenceMatcher

    df = utm_analysis_df.copy()
    spend_values = []
    has_budget_values = []  # Para campaigns e adsets (medium)
    match_stats = {'campaign': 0, 'adset': 0, 'ad': 0, 'no_match': 0}

    for value in df['value']:
        spend = 0.0
        has_budget = True  # Default

        # Garantir que value seja string (pode vir como int do DataFrame)
        value = str(value)

        if dimension == 'campaign':
            # Value pode ser o Campaign ID direto (nova agregação) ou UTM completo (legado)
            campaign_id = value if len(value) == 18 and value.isdigit() else extract_id_from_utm(value)

            if campaign_id and campaign_id in hierarchy['campaigns']:
                campaign = hierarchy['campaigns'][campaign_id]

                # Obter informação de orçamento
                has_budget = campaign.get('has_campaign_budget', True)  # Default True (CBO)

                # Extrair nome do adset do UTM
                adset_name_candidate = extract_adset_name_from_campaign_utm(value, utm_campaign_structure)

                if adset_name_candidate:
                    # Tentar fazer matching do adset
                    best_match = None
                    best_similarity = 0

                    for adset_id, adset in campaign['adsets'].items():
                        adset_name = adset['name']

                        # Match exato
                        if adset_name_candidate.lower() == adset_name.lower():
                            best_match = adset
                            best_similarity = 1.0
                            break

                        # Fuzzy match
                        similarity = SequenceMatcher(None, adset_name_candidate.lower(), adset_name.lower()).ratio()
                        if similarity > best_similarity and similarity >= 0.75:
                            best_match = adset
                            best_similarity = similarity

                    if best_match:
                        spend = best_match['spend']
                        match_stats['adset'] += 1
                        logger.debug(f"      ✓ Adset match: '{value[:50]}...' → '{best_match['name']}' (R$ {spend:.2f}, sim: {best_similarity:.2f})")
                    else:
                        # Fallback: usar custo total da campaign
                        spend = campaign['spend']
                        match_stats['campaign'] += 1
                        logger.debug(f"      ⚠️ Adset não encontrado, usando campaign total: '{value[:50]}...' (R$ {spend:.2f})")
                else:
                    # Sem nome de adset, usar custo total da campaign
                    spend = campaign['spend']
                    match_stats['campaign'] += 1

                # Adicionar has_budget para campaigns
                has_budget_values.append(has_budget)
            else:
                match_stats['no_match'] += 1
                has_budget_values.append(True)  # Default se não encontrar
                logger.debug(f"      ❌ Campaign não encontrada: '{value[:50]}...' (ID: {campaign_id or 'N/A'})")

        elif dimension == 'medium':
            # Medium = Adset ID (agora agrupamos por ID, não mais por nome)
            # Buscar adset diretamente por ID
            adset_found = None

            for campaign in hierarchy['campaigns'].values():
                if value in campaign['adsets']:
                    adset_found = campaign['adsets'][value]
                    break

            if adset_found:
                spend = adset_found['spend']
                has_budget = adset_found.get('has_adset_budget', True)  # True = ABO (tem budget próprio)
                has_budget_values.append(has_budget)
                match_stats['adset'] += 1
                logger.debug(f"      ✓ Medium→Adset ID: {value} (R$ {spend:.2f})")
            else:
                has_budget_values.append(True)  # Default se não encontrar
                match_stats['no_match'] += 1
                logger.debug(f"      ❌ Adset ID não encontrado: {value}")

        elif dimension in ['content', 'ad', 'term']:
            # Content/Ad/Term = Ad name ou Ad ID
            ad_id = extract_id_from_utm(value)

            # Buscar por ID ou nome
            best_match = None
            best_similarity = 0

            for campaign in hierarchy['campaigns'].values():
                for adset in campaign['adsets'].values():
                    for ad in adset['ads'].values():
                        # Match por ID
                        if ad_id and ad['id'] == ad_id:
                            best_match = ad
                            best_similarity = 1.0
                            break

                        # Match por nome
                        if value.lower() == ad['name'].lower():
                            best_match = ad
                            best_similarity = 1.0
                            break

                        # Fuzzy match
                        similarity = SequenceMatcher(None, value.lower(), ad['name'].lower()).ratio()
                        if similarity > best_similarity and similarity >= 0.85:
                            best_match = ad
                            best_similarity = similarity

                    if best_similarity == 1.0:
                        break
                if best_similarity == 1.0:
                    break

            if best_match:
                spend = best_match['spend']
                match_stats['ad'] += 1
                logger.debug(f"      ✓ Ad match: '{value[:40]}...' (R$ {spend:.2f})")
            else:
                match_stats['no_match'] += 1

        spend_values.append(spend)

    df['spend'] = spend_values

    # Para campaigns, adicionar coluna has_campaign_budget
    if dimension == 'campaign' and has_budget_values:
        df['has_campaign_budget'] = has_budget_values
        cbo_count = sum(1 for x in has_budget_values if x)
        abo_count = len(has_budget_values) - cbo_count
        logger.info(f"   📊 Budget: {cbo_count} CBO (Campaign), {abo_count} ABO (AdSet)")

    # Para adsets (medium), adicionar coluna has_adset_budget
    if dimension == 'medium' and has_budget_values:
        df['has_adset_budget'] = has_budget_values
        abo_count = sum(1 for x in has_budget_values if x)  # True = ABO (tem budget)
        cbo_count = len(has_budget_values) - abo_count      # False = CBO (usa budget da campanha)
        logger.info(f"   📊 Adset Budget: {abo_count} ABO (AdSet), {cbo_count} CBO (Campaign)")

    total_mapped = sum(spend_values)
    items_with_spend = sum(1 for s in spend_values if s > 0)

    logger.info(f"   ✅ {dimension}: R$ {total_mapped:.2f} em {items_with_spend}/{len(spend_values)} itens")
    logger.info(f"      Match: campaign={match_stats['campaign']}, adset={match_stats['adset']}, ad={match_stats['ad']}, no_match={match_stats['no_match']}")

    return df
