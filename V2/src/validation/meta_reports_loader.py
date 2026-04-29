"""
Módulo para carregar dados dos relatórios Excel exportados do Meta Ads.

Lê os arquivos de campanhas, conjuntos de anúncios e anúncios exportados
manualmente do Meta Ads Manager.
"""

import os
import sys
import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import pandas as pd
from glob import glob

logger = logging.getLogger(__name__)

# Importar MetaAPIClient para modo API
try:
    from src.validation.meta_api_client import MetaAPIClient
    META_API_AVAILABLE = True
except ImportError:
    META_API_AVAILABLE = False
    logger.warning("MetaAPIClient não disponível. Modo API desabilitado.")

from src.validation.data_loader import _cache_is_fresh


def normalize_unicode(text: str) -> str:
    """
    Normaliza texto Unicode para NFC (composed form).

    Isso resolve problemas onde "ú" pode estar como:
    - NFC: "ú" (1 caractere)
    - NFD: "u" + "´" (2 caracteres: base + combining accent)
    """
    return unicodedata.normalize('NFC', text)


def normalize_whitespace(text: str) -> str:
    """
    Normaliza espaços em branco em nomes para matching consistente.

    - Colapsa múltiplos espaços em um único espaço
    - Remove espaços no início e fim

    Args:
        text: Texto a normalizar

    Returns:
        Texto normalizado
    """
    if pd.isna(text):
        return text
    # Colapsar múltiplos espaços em um único
    normalized = re.sub(r'\s+', ' ', str(text))
    # Remover espaços no início e fim
    return normalized.strip()


class MetaReportsLoader:
    """
    Carrega dados dos relatórios Excel do Meta Ads.

    Estrutura esperada dos arquivos:
    - Ads---[Conta]-Campanhas-[período].xlsx
    - Ads---[Conta]-Conjuntos-de-anúncios-[período].xlsx
    - Ads---[Conta]-Anúncios-[período].xlsx
    """

    def __init__(self, reports_dir: str, data_source: str = "local", account_ids: Optional[List[str]] = None, use_cache: bool = True):
        """
        Inicializa o loader.

        Args:
            reports_dir: Diretório contendo os relatórios Excel
            data_source: "local" (arquivos) ou "api" (Meta Marketing API)
            account_ids: Lista de IDs de contas Meta (usado apenas no modo API)
            use_cache: Se True, usa cache em arquivo para evitar chamadas repetidas à Meta API
        """
        self.reports_dir = Path(reports_dir)
        self.data_source = data_source.lower()
        self.account_ids = account_ids or []
        self._use_cache = use_cache

        # Validar data_source
        if self.data_source not in ["local", "api"]:
            raise ValueError(f"data_source inválido: {data_source}. Use 'local' ou 'api'.")

        # Se modo API, verificar disponibilidade
        if self.data_source == "api":
            if not META_API_AVAILABLE:
                raise ImportError("MetaAPIClient não disponível. Instale as dependências necessárias.")
            logger.info(" Modo API habilitado - dados serão extraídos da Meta Marketing API")
            logger.info(f"   Contas: {', '.join(self.account_ids) if self.account_ids else 'Padrão (Rodolfo Mori)'}")
            # API clients serão criados sob demanda em _load_from_api()
        else:
            logger.info(" Modo LOCAL habilitado - dados serão carregados de arquivos")
            if not self.reports_dir.exists():
                raise FileNotFoundError(f"Diretório de relatórios não encontrado: {reports_dir}")

    def load_all_reports(
        self,
        start_date: str,
        end_date: str
    ) -> Dict[str, pd.DataFrame]:
        """
        Carrega todos os relatórios (campanhas, adsets, ads) de todas as contas.

        Args:
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)

        Returns:
            Dict com DataFrames:
            - 'campaigns': DataFrame consolidado de campanhas
            - 'adsets': DataFrame consolidado de adsets
            - 'ads': DataFrame consolidado de ads
        """
        # Roteamento baseado no data_source
        if self.data_source == "api":
            return self._load_from_api(start_date, end_date)
        else:
            return self._load_from_local(start_date, end_date)

    def _load_from_local(
        self,
        start_date: str,
        end_date: str
    ) -> Dict[str, pd.DataFrame]:
        """
        Carrega relatórios de arquivos locais (modo original).

        Args:
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)

        Returns:
            Dict com DataFrames de campaigns, adsets, ads
        """
        logger.info(f" Carregando relatórios Meta de {self.reports_dir}...")

        # Buscar arquivos por padrão (recursivamente em subpastas)
        # Usar listagem manual para evitar problemas com Unicode em glob
        # Aceita tanto .xlsx quanto .csv
        xlsx_files = list(self.reports_dir.rglob('*.xlsx'))
        csv_files = list(self.reports_dir.rglob('*.csv'))
        all_files = xlsx_files + csv_files

        # Normalizar nomes de arquivos para resolver problemas de encoding Unicode
        campaign_files = [f for f in all_files
                         if 'Campanhas' in normalize_unicode(f.name) or 'campanhas' in normalize_unicode(f.name)]

        adset_files = [f for f in all_files
                      if 'Conjuntos' in normalize_unicode(f.name)
                      and ('anúncios' in normalize_unicode(f.name) or 'anuncios' in normalize_unicode(f.name))]

        # Para ads: deve ter "Anúncios" MAS NÃO "Conjuntos"
        ad_files = [f for f in all_files
                   if ('Anúncios' in normalize_unicode(f.name) or 'Anuncios' in normalize_unicode(f.name))
                   and 'Conjuntos' not in normalize_unicode(f.name)]

        logger.info(f"   Campanhas: {len(campaign_files)} arquivo(s)")
        logger.info(f"   Adsets: {len(adset_files)} arquivo(s)")
        logger.info(f"   Anúncios: {len(ad_files)} arquivo(s)")

        # Carregar e consolidar
        campaigns_df = self._load_and_consolidate(campaign_files, 'campaign')
        adsets_df = self._load_and_consolidate(adset_files, 'adset')
        ads_df = self._load_and_consolidate(ad_files, 'ad')

        # CRÍTICO: Carregar edge cases (adsets e ads que não aparecem nos relatórios normais)
        adsets_df = self._load_edge_cases(adsets_df, 'adset')
        ads_df = self._load_edge_cases(ads_df, 'ad')

        # IMPORTANTE: NÃO filtrar campanhas e adsets por período (manter todas as linhas)!
        # Motivo: Conversões podem ter sido atribuídas a campanhas/adsets que foram pausados/deletados
        # antes do período atual. Precisamos manter todos históricos para:
        # 1. Construir comparison_group_map completo (usado em fair_campaign_comparison.py)
        # 2. Fazer matching de conversões com adsets históricos
        logger.info(f"   ℹ  Campanhas e Adsets: mantendo histórico completo para matching")

        # CRÍTICO: Filtrar APENAS o spend por período (zerando spend fora do período)
        # Isso garante que conversões históricas sejam atribuídas, mas gasto seja apenas do período
        campaigns_df = self._filter_spend_by_period(campaigns_df, start_date, end_date, 'Campanhas')
        adsets_df = self._filter_spend_by_period(adsets_df, start_date, end_date, 'Adsets')

        # NOTA: Deduplicação de adsets é feita em compare_all_adsets_performance() e compare_adset_performance()
        # para evitar duplicação de conversões no matching (linhas 402-409 e 641-648 em fair_campaign_comparison.py)

        ads_df = self._filter_by_period(ads_df, start_date, end_date, 'Ads')

        return {
            'campaigns': campaigns_df,
            'adsets': adsets_df,
            'ads': ads_df
        }

    def _load_from_api(
        self,
        start_date: str,
        end_date: str
    ) -> Dict[str, pd.DataFrame]:
        """
        Carrega relatórios via Meta Marketing API.

        Args:
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)

        Returns:
            Dict com DataFrames de campaigns, adsets, ads (formato normalizado)
        """
        import json
        import hashlib

        # Cache: chave por contas + período
        accounts_key = '_'.join(sorted(self.account_ids or [])) if self.account_ids else 'default'
        cache_key = hashlib.md5(f"meta_{accounts_key}_{start_date}_{end_date}".encode()).hexdigest()
        cache_dir = Path(__file__).parent.parent.parent / 'files' / 'validation' / 'cache'
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"meta_api_{cache_key}.json"

        use_cache = getattr(self, '_use_cache', True)

        if use_cache and _cache_is_fresh(cache_file, end_date):
            logger.info(f"    Cache HIT Meta API: {cache_file.name}")
            with open(cache_file, 'r') as f:
                cached = json.load(f)
            return {k: pd.DataFrame(v) for k, v in cached.items()}

        logger.info(f" Extraindo relatórios da Meta API...")
        logger.info(f"   Período: {start_date} a {end_date}")

        # Se não há account_ids especificados, usar conta padrão
        accounts_to_fetch = self.account_ids if self.account_ids else [MetaAPIClient.DEFAULT_ACCOUNT_ID]

        logger.info(f"    DEBUG - self.account_ids: {self.account_ids}")
        logger.info(f"    DEBUG - accounts_to_fetch: {accounts_to_fetch}")

        all_campaigns = []
        all_adsets = []
        all_ads = []

        # Extrair dados de cada conta
        for account_id in accounts_to_fetch:
            # Garantir que account_id tenha o prefixo "act_"
            if not str(account_id).startswith('act_'):
                account_id = f"act_{account_id}"

            logger.info(f"    Extraindo dados da conta: {account_id}")

            # Criar cliente para esta conta
            api_client = MetaAPIClient(account_id=account_id)

            # Extrair dados via API (filtros já aplicados: gasto > 0, contém 'CAP')
            api_data = api_client.get_all_levels(
                date_start=start_date,
                date_end=end_date,
                apply_filters=True
            )

            all_campaigns.append(api_data['campaigns'])
            all_adsets.append(api_data['adsets'])
            all_ads.append(api_data['ads'])

        # Consolidar dados de todas as contas
        campaigns_df = pd.concat(all_campaigns, ignore_index=True) if all_campaigns else pd.DataFrame()
        adsets_df = pd.concat(all_adsets, ignore_index=True) if all_adsets else pd.DataFrame()
        ads_df = pd.concat(all_ads, ignore_index=True) if all_ads else pd.DataFrame()

        logger.info(f"    API: {len(campaigns_df)} campanhas, {len(adsets_df)} adsets, {len(ads_df)} ads (todas as contas)")

        # Normalizar DataFrames para match com formato local
        campaigns_df = self._normalize_api_data(campaigns_df, 'campaign')
        adsets_df = self._normalize_api_data(adsets_df, 'adset')
        ads_df = self._normalize_api_data(ads_df, 'ad')

        logger.info(f"    Dados normalizados e prontos para uso")

        result = {
            'campaigns': campaigns_df,
            'adsets': adsets_df,
            'ads': ads_df
        }

        # Salvar no cache
        if use_cache:
            try:
                with open(cache_file, 'w') as f:
                    json.dump({k: v.to_dict(orient='records') for k, v in result.items()}, f)
                logger.info(f"    Cache SAVED Meta API: {cache_file.name}")
            except Exception as ce:
                logger.warning(f"    Não foi possível salvar cache Meta API: {ce}")

        return result

    def _normalize_api_data(
        self,
        df: pd.DataFrame,
        report_type: str
    ) -> pd.DataFrame:
        """
        Normaliza dados da API para match com formato de arquivos locais.

        A API retorna colunas em português (ex: "Nome da campanha"),
        enquanto o loader local normaliza para inglês (ex: "campaign_name").
        Esta função aplica a mesma normalização.

        Args:
            df: DataFrame da API
            report_type: 'campaign', 'adset' ou 'ad'

        Returns:
            DataFrame normalizado
        """
        if df.empty:
            return df

        # Mapeamento de nomes da API  nomes padronizados
        # (mesmo mapeamento usado em _normalize_column_names)
        column_mapping = {
            'Nome da campanha': 'campaign_name',
            'Identificação da campanha': 'campaign_id',
            'Valor usado (BRL)': 'spend',
            'Resultados': 'results',
            'Indicador de resultados': 'optimization_goal_indicator',
            'Início dos relatórios': 'Início dos relatórios',  # Manter para filtros
            'Término dos relatórios': 'Término dos relatórios',  # Manter para filtros
            'Nome do conjunto de anúncios': 'adset_name',
            'Identificação do conjunto de anúncios': 'adset_id',
            'Nome do anúncio': 'ad_name',
            'Identificação do anúncio': 'ad_id',
            'Leads': 'leads_standard',
            'LeadQualified': 'lead_qualified',
            'LeadQualifiedHighQuality': 'lead_qualified_hq',
            'Faixa A': 'faixa_a',
        }

        df = df.rename(columns=column_mapping)

        # Normalizar whitespace em nomes (mesmo processo que arquivos locais)
        for name_col in ['campaign_name', 'adset_name', 'ad_name']:
            if name_col in df.columns:
                df[name_col] = df[name_col].apply(normalize_whitespace)

        # Converter spend para numérico
        if 'spend' in df.columns:
            df['spend'] = pd.to_numeric(df['spend'], errors='coerce')

        # Converter results para numérico
        if 'results' in df.columns:
            df['results'] = pd.to_numeric(df['results'], errors='coerce')

        # NOTA: Endpoint de insights não retorna budget (daily_budget, lifetime_budget)
        # Adicionar coluna budget com valor 0 para compatibilidade com código que espera essa coluna
        df['budget'] = 0.0

        # Converter IDs para string e normalizar para primeiros 15 dígitos
        for id_col in ['campaign_id', 'adset_id', 'ad_id']:
            if id_col in df.columns:
                df[id_col] = df[id_col].astype(str).str.replace('.0', '', regex=False)
                df[id_col] = df[id_col].apply(lambda x: str(x)[:15] if pd.notna(x) and str(x) != 'nan' else x)

        # Converter colunas de eventos para numérico
        for event_col in ['leads_standard', 'lead_qualified', 'lead_qualified_hq', 'faixa_a']:
            if event_col in df.columns:
                df[event_col] = pd.to_numeric(df[event_col], errors='coerce').fillna(0)

        # Extrair AD code do nome do anúncio
        if report_type == 'ad' and 'ad_name' in df.columns:
            df['ad_code'] = df['ad_name'].str.extract(r'(AD0\d+)', expand=False)

        # Simplificar optimization_goal_indicator (mesmo processo que arquivos locais)
        if 'optimization_goal_indicator' in df.columns:
            def simplify_optimization_goal(val):
                if pd.isna(val):
                    return 'Lead'
                val_str = str(val).lower()

                if 'leadqualifiedhighquality' in val_str or 'lead_qualified_high_quality' in val_str:
                    return 'LeadQualifiedHighQuality'
                elif 'leadqualified' in val_str or 'lead_qualified' in val_str:
                    return 'LeadQualified'
                elif 'faixa a' in val_str or 'faixa_a' in val_str:
                    return 'Faixa A'
                elif 'lead' in val_str:
                    return 'Lead'

                return str(val)

            df['optimization_goal'] = df['optimization_goal_indicator'].apply(simplify_optimization_goal)

        # Adicionar metadados (para compatibilidade com logs/debug)
        df['_source_file'] = 'META_API'

        # Mapear account_id para account_name
        # A API retorna account_id, precisamos mapear para o nome usado nos relatórios
        if 'account_id' in df.columns:
            account_name_map = {
                '188005769808959': 'Rodolfo Mori',
                '786790755803474': 'Gestor de IA'
            }
            df['_account_name'] = df['account_id'].apply(
                lambda x: account_name_map.get(str(x).replace('act_', ''), 'Unknown')
            )
            # IMPORTANTE: Manter coluna account_id (necessária para costs_hierarchy)
            # Já está presente, apenas garantir que está no formato correto (com act_ prefix)
            df['account_id'] = df['account_id'].apply(
                lambda x: x if str(x).startswith('act_') else f"act_{x}" if pd.notna(x) else ''
            )
        else:
            df['_account_name'] = 'Unknown'
            # Se não tem account_id, tentar mapear de _account_name para account_id
            df['account_id'] = df.get('_account_name', pd.Series([''] * len(df))).apply(
                self._map_account_name_to_id
            )

        # IMPORTANTE: Adicionar total_spend para matched pairs (mesmo comportamento que arquivos locais)
        if 'spend' in df.columns:
            df['total_spend'] = df['spend']

        return df

    def _load_and_consolidate(
        self,
        file_paths: List[Path],
        report_type: str
    ) -> pd.DataFrame:
        """
        Carrega e consolida múltiplos arquivos Excel.

        Args:
            file_paths: Lista de caminhos dos arquivos
            report_type: 'campaign', 'adset' ou 'ad'

        Returns:
            DataFrame consolidado
        """
        if not file_paths:
            logger.warning(f"     Nenhum arquivo encontrado para {report_type}")
            return pd.DataFrame()

        all_dfs = []

        for file_path in file_paths:
            try:
                # Detectar conta pelo nome do arquivo
                account_name = self._extract_account_name(file_path.name)

                # Ler arquivo (CSV ou Excel)
                if file_path.suffix.lower() == '.csv':
                    df = pd.read_csv(file_path)
                else:
                    df = pd.read_excel(file_path)

                # Adicionar identificação da conta
                df['_source_file'] = file_path.name
                df['_account_name'] = account_name

                # Normalizar nomes de colunas
                df = self._normalize_column_names(df, report_type)

                # Adicionar account_id baseado no _account_name
                df['account_id'] = df['_account_name'].apply(self._map_account_name_to_id)

                all_dfs.append(df)

                logger.info(f"       {file_path.name}: {len(df)} linhas")

            except Exception as e:
                logger.error(f"       Erro ao ler {file_path.name}: {e}")

        if not all_dfs:
            return pd.DataFrame()

        # Consolidar todos os DataFrames
        consolidated = pd.concat(all_dfs, ignore_index=True)

        logger.info(f"    Total consolidado: {len(consolidated)} linhas de {report_type}")

        return consolidated

    def _extract_account_name(self, filename: str) -> str:
        """
        Extrai nome da conta do nome do arquivo.

        Args:
            filename: Nome do arquivo (ex: "Ads---Rodolfo-Mori-Campanhas-...")

        Returns:
            Nome da conta (ex: "Rodolfo Mori")
        """
        # Padrão: Ads---[Nome-da-Conta]-[Tipo]-[Período]
        parts = filename.split('---')
        if len(parts) >= 2:
            # Pegar segunda parte e remover tipo do relatório
            account_part = parts[1].split('-Campanhas-')[0]
            account_part = account_part.split('-Conjuntos-')[0]
            account_part = account_part.split('-Anúncios-')[0]
            return account_part.replace('-', ' ')
        return 'Unknown'

    def _map_account_name_to_id(self, account_name: str) -> str:
        """
        Mapeia nome da conta para account_id.

        Args:
            account_name: Nome da conta (ex: "Rodolfo Mori")

        Returns:
            Account ID (ex: "act_188005769808959")
        """
        # Mapeamento hardcoded de nomes conhecidos
        # FIXME: Idealmente isso deveria vir de configuração ou ser extraído dinamicamente da API
        mapping = {
            'Rodolfo Mori': 'act_188005769808959',
            'Gestor de IA': 'act_786790755803474',
        }
        return mapping.get(account_name, '')

    def _normalize_column_names(self, df: pd.DataFrame, report_type: str) -> pd.DataFrame:
        """
        Normaliza nomes de colunas para padrão consistente.

        Args:
            df: DataFrame original
            report_type: 'campaign', 'adset' ou 'ad'

        Returns:
            DataFrame com colunas normalizadas
        """
        # Mapeamento de nomes do Excel  nomes padronizados
        column_mapping = {
            # Comum a todos
            'Nome da campanha': 'campaign_name',
            'Valor usado (BRL)': 'spend',
            'Resultados': 'results',
            'Indicador de resultados': 'optimization_goal',
            'Identificação da campanha': 'campaign_id',

            # Budget - campanhas e adsets
            'Orçamento da campanha': 'budget',  # CBO (Campaign Budget Optimization)
            'Orçamento do conjunto de anúncios': 'budget',  # ABO (Ad Set Budget Optimization)
            'Tipo de orçamento do conjunto de anúncios': 'budget_type',
            'Tipo de orçamento da campanha': 'budget_type',

            # Adsets
            'Nome do conjunto de anúncios': 'adset_name',
            'Identificação do conjunto de anúncios': 'adset_id',

            # Anúncios
            'Nome do anúncio': 'ad_name',
            'Identificação do anúncio': 'ad_id',

            # Eventos personalizados (colunas diretas nos novos relatórios)
            'Leads': 'leads_standard',
            'LeadQualified': 'lead_qualified',
            'LeadQualifiedHighQuality': 'lead_qualified_hq',
            'Faixa A': 'faixa_a',

            # Indicador de resultados (objetivo de otimização) - IMPORTANTE para classificação ML
            'Indicador de resultados': 'optimization_goal_indicator',
        }

        df = df.rename(columns=column_mapping)

        # CRÍTICO: Normalizar whitespace em nomes (adset_name, ad_name, campaign_name)
        # Isso garante matching consistente mesmo com variações de espaçamento
        for name_col in ['campaign_name', 'adset_name', 'ad_name']:
            if name_col in df.columns:
                df[name_col] = df[name_col].apply(normalize_whitespace)

        # Converter spend para numérico
        if 'spend' in df.columns:
            df['spend'] = pd.to_numeric(df['spend'].astype(str).str.replace(',', ''), errors='coerce')

        # Converter results para numérico
        if 'results' in df.columns:
            df['results'] = pd.to_numeric(df['results'], errors='coerce')

        # Converter budget para numérico
        if 'budget' in df.columns:
            df['budget'] = pd.to_numeric(df['budget'], errors='coerce')

        # Converter IDs para string (para evitar notação científica)
        for id_col in ['campaign_id', 'adset_id', 'ad_id']:
            if id_col in df.columns:
                df[id_col] = df[id_col].astype(str).str.replace('.0', '', regex=False)

                # CRÍTICO: Normalizar IDs para os primeiros 15 dígitos
                # Isso resolve o problema de edge_cases terem sufixo "390" enquanto relatórios normais têm "000"
                # Exemplo: 120234898385570390  120234898385570
                # Isso garante que a mesma campanha não seja duplicada
                df[id_col] = df[id_col].apply(lambda x: str(x)[:15] if pd.notna(x) and str(x) != 'nan' else x)

        # Converter colunas de eventos para numérico
        for event_col in ['leads_standard', 'lead_qualified', 'lead_qualified_hq', 'faixa_a']:
            if event_col in df.columns:
                df[event_col] = pd.to_numeric(df[event_col], errors='coerce').fillna(0)

        # Extrair AD code do nome do anúncio (ex: "DEV-AD0033-vid"  "AD0033")
        if report_type == 'ad' and 'ad_name' in df.columns:
            df['ad_code'] = df['ad_name'].str.extract(r'(AD0\d+)', expand=False)

        # Simplificar optimization_goal_indicator (extrair apenas o tipo de evento)
        # Ex: "actions:offsite_conversion.fb_pixel_lead"  "Lead"
        # Ex: "conversions:offsite_conversion.fb_pixel_custom.LeadQualifiedHighQuality"  "LeadQualifiedHighQuality"
        if 'optimization_goal_indicator' in df.columns:
            def simplify_optimization_goal(val):
                if pd.isna(val):
                    return 'Lead'
                val_str = str(val).lower()

                # Verificar eventos customizados CAPI (ordem importa - mais específico primeiro)
                if 'leadqualifiedhighquality' in val_str or 'lead_qualified_high_quality' in val_str:
                    return 'LeadQualifiedHighQuality'
                elif 'leadqualified' in val_str or 'lead_qualified' in val_str:
                    return 'LeadQualified'
                elif 'faixa a' in val_str or 'faixa_a' in val_str:
                    return 'Faixa A'
                elif 'lead' in val_str:
                    return 'Lead'

                return str(val)

            df['optimization_goal'] = df['optimization_goal_indicator'].apply(simplify_optimization_goal)

        return df

    def _filter_by_period(
        self,
        df: pd.DataFrame,
        start_date: str,
        end_date: str,
        report_type: str
    ) -> pd.DataFrame:
        """
        Filtra DataFrame por período usando as colunas de data do relatório.

        Args:
            df: DataFrame a filtrar
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)
            report_type: Nome do tipo de relatório (para log)

        Returns:
            DataFrame filtrado
        """
        if df.empty:
            return df

        # Verificar se as colunas de período existem
        if 'Início dos relatórios' not in df.columns or 'Término dos relatórios' not in df.columns:
            logger.warning(f"     Colunas de período não encontradas em {report_type}, não foi possível filtrar")
            return df

        before_count = len(df)

        # Filtrar: manter apenas registros onde o período do relatório SE SOBREPÕE ao período solicitado
        # Sobreposição ocorre quando:
        # - Início do relatório <= end_date (relatório começa antes ou durante o período)
        # - Término do relatório >= start_date (relatório termina depois ou durante o período)
        df_filtered = df[
            (df['Início dos relatórios'] <= end_date) &
            (df['Término dos relatórios'] >= start_date)
        ].copy()

        after_count = len(df_filtered)

        if before_count != after_count:
            logger.info(f"     {report_type} filtrados por período: {after_count}/{before_count} ({after_count/before_count*100:.1f}%)")
            logger.info(f"      Período solicitado: {start_date} a {end_date}")
        else:
            logger.info(f"    {report_type}: {after_count} registros (100% no período)")

        return df_filtered

    def _filter_spend_by_period(
        self,
        df: pd.DataFrame,
        start_date: str,
        end_date: str,
        report_type: str
    ) -> pd.DataFrame:
        """
        Zera o spend de registros FORA do período, mas mantém todas as linhas.

        Isso permite que conversões históricas sejam atribuídas a campanhas/adsets antigos,
        mas garante que o gasto considerado seja apenas do período de análise.

        Args:
            df: DataFrame a processar
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)
            report_type: Nome do tipo de relatório (para log)

        Returns:
            DataFrame com spend zerado fora do período
        """
        if df.empty or 'spend' not in df.columns:
            return df

        # Verificar se as colunas de período existem
        if 'Início dos relatórios' not in df.columns or 'Término dos relatórios' not in df.columns:
            logger.warning(f"     Colunas de período não encontradas em {report_type}, não foi possível filtrar spend")
            return df

        # Criar cópia para não modificar original
        df = df.copy()

        # NOVO: Preservar spend total ANTES de zerar (para matched pairs)
        df['total_spend'] = df['spend']

        # CRÍTICO: Converter datas para datetime para comparação correta
        df['Início dos relatórios'] = pd.to_datetime(df['Início dos relatórios'])
        df['Término dos relatórios'] = pd.to_datetime(df['Término dos relatórios'])
        start_date_dt = pd.to_datetime(start_date)
        end_date_dt = pd.to_datetime(end_date)

        # Identificar linhas FORA do período
        # Linha está fora se NÃO há sobreposição:
        # - Término do relatório < start_date (relatório terminou antes do período)
        # - Início do relatório > end_date (relatório começou depois do período)
        outside_period = (
            (df['Término dos relatórios'] < start_date_dt) |
            (df['Início dos relatórios'] > end_date_dt)
        )

        # Contar spend que será zerado
        spend_outside = df.loc[outside_period, 'spend'].sum() if outside_period.any() else 0
        spend_total = df['spend'].sum()

        # Zerar spend fora do período (mas manter total_spend intacto)
        df.loc[outside_period, 'spend'] = 0

        if spend_outside > 0 or spend_total > 0:
            logger.info(f"    {report_type}: Spend filtrado por período")
            logger.info(f"      Total: R$ {spend_total:,.2f}")
            logger.info(f"      Fora do período (zerado): R$ {spend_outside:,.2f}")
            logger.info(f"      No período: R$ {spend_total - spend_outside:,.2f}")
            logger.info(f"      Linhas outside: {outside_period.sum()} de {len(df)}")

        return df

    def _load_edge_cases(
        self,
        df: pd.DataFrame,
        report_type: str
    ) -> pd.DataFrame:
        """
        Carrega edge cases (adsets/ads) que não aparecem nos relatórios normais devido a bugs da Meta.

        Edge cases são registros que:
        - Aparecem na interface da Meta com gasto e métricas
        - MAS não são incluídos nas exportações de relatórios
        - Precisam ser exportados individualmente e colocados na pasta edge_cases/

        Args:
            df: DataFrame já carregado (adsets ou ads)
            report_type: 'adset' ou 'ad'

        Returns:
            DataFrame com edge cases adicionados
        """
        edge_case_dir = self.reports_dir / 'edge_cases'

        if not edge_case_dir.exists():
            # Pasta edge_cases não existe, retornar dados normais
            return df

        # IMPORTANTE: Usar apenas arquivos CSV (mais confiáveis e rápidos)
        all_edge_files = list(edge_case_dir.glob('*.csv'))

        # Filtrar arquivos baseado no tipo
        if report_type == 'adset':
            # Arquivos de Conjuntos de anúncios
            edge_case_files = [f for f in all_edge_files
                              if 'Conjuntos' in f.name or 'conjunto' in f.name.lower()]
        elif report_type == 'ad':
            # Arquivos de Anúncios (mas NÃO Conjuntos)
            edge_case_files = [f for f in all_edge_files
                              if ('Anúncios' in f.name or 'anuncio' in f.name.lower())
                              and 'Conjuntos' not in f.name]
        else:
            edge_case_files = []

        if not edge_case_files:
            # Nenhum edge case encontrado para este tipo
            return df

        logger.info(f"    Carregando {report_type} edge cases de {edge_case_dir.name}/...")

        edge_case_dfs = []

        for file_path in edge_case_files:
            try:
                # Ler arquivo CSV
                df_edge = pd.read_csv(file_path)

                # Verificar colunas esperadas baseado no tipo
                if report_type == 'adset':
                    expected_col = 'Nome do conjunto de anúncios'
                else:  # ad
                    expected_col = 'Nome do anúncio'

                # Pular se estiver vazio ou sem colunas esperadas
                if df_edge.empty or expected_col not in df_edge.columns:
                    continue

                # Adicionar metadados
                df_edge['_source_file'] = file_path.name
                df_edge['_account_name'] = self._extract_account_name(file_path.name)
                df_edge['_is_edge_case'] = True  # Marcar como edge case

                # Normalizar nomes de colunas usando o mesmo processo
                df_edge = self._normalize_column_names(df_edge, report_type)

                # Adicionar account_id baseado no _account_name
                df_edge['account_id'] = df_edge['_account_name'].apply(self._map_account_name_to_id)

                edge_case_dfs.append(df_edge)

                logger.info(f"       Edge case: {file_path.name} ({len(df_edge)} {report_type}(s))")

                # Log dos registros carregados
                for idx, row in df_edge.iterrows():
                    if report_type == 'adset':
                        name = row.get('adset_name', 'Unknown')
                        id_val = row.get('adset_id', 'Unknown')
                    else:  # ad
                        name = row.get('ad_name', 'Unknown')
                        id_val = row.get('ad_id', 'Unknown')

                    campaign_id = row.get('campaign_id', 'Unknown')
                    spend = row.get('spend', 0)
                    logger.info(f"          {name} (ID: {str(id_val)[:15]}..., Campaign: {str(campaign_id)[:15]}..., R$ {spend:.2f})")

            except Exception as e:
                logger.warning(f"       Erro ao ler {file_path.name}: {e}")

        if not edge_case_dfs:
            # Nenhum edge case válido carregado
            return df

        # Consolidar edge cases
        edge_cases_consolidated = pd.concat(edge_case_dfs, ignore_index=True)

        # Combinar com dados normais
        # IMPORTANTE: Edge cases têm prioridade (adicionar no final para sobrescrever duplicatas)
        if df.empty:
            combined_df = edge_cases_consolidated
        else:
            # Remover duplicatas baseado no ID (edge case tem prioridade)
            id_col = 'adset_id' if report_type == 'adset' else 'ad_id'

            if id_col in edge_cases_consolidated.columns:
                edge_case_ids = edge_cases_consolidated[id_col].astype(str).unique()
                df_filtered = df[~df[id_col].astype(str).isin(edge_case_ids)]
                combined_df = pd.concat([df_filtered, edge_cases_consolidated], ignore_index=True)
            else:
                combined_df = pd.concat([df, edge_cases_consolidated], ignore_index=True)

        logger.info(f"    Total {report_type}s com edge cases: {len(combined_df)} (+{len(edge_cases_consolidated)} edge case(s))")

        return combined_df

    def build_costs_hierarchy(
        self,
        start_date: str,
        end_date: str
    ) -> Dict:
        """
        Constrói estrutura costs_hierarchy a partir dos relatórios Excel.

        Args:
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)

        Returns:
            Dict no formato costs_hierarchy esperado pelo metrics_calculator:
            {
                'campaigns': {
                    campaign_id: {
                        'name': campaign_name,
                        'account_id': account_id,
                        'spend': total_spend,
                        'daily_budget': budget,
                        'num_creatives': num_ads,
                        'optimization_goals': set([...])
                    }
                }
            }
        """
        # Carregar relatórios já filtrados por período
        reports = self.load_all_reports(start_date, end_date)
        campaigns_df = reports['campaigns']
        adsets_df = reports['adsets']
        ads_df = reports['ads']

        # NOTA: O filtro por período já foi aplicado em load_all_reports()
        # Não é necessário filtrar novamente aqui

        costs_hierarchy = {'campaigns': {}}

        # NOVO: Criar mapeamento campaign_name  campaign_id dos relatórios de Campanhas
        # (quando disponível - arquivos novos com coluna "Identificação da campanha")
        campaign_name_to_id = {}
        skipped_campaigns = []

        if not campaigns_df.empty and 'campaign_id' in campaigns_df.columns:
            for _, row in campaigns_df.iterrows():
                camp_name = row.get('campaign_name')
                camp_id = row.get('campaign_id')

                # Debug: verificar valores
                if pd.isna(camp_id):
                    skipped_campaigns.append((camp_name, 'ID is NaN'))
                    continue
                if pd.isna(camp_name):
                    skipped_campaigns.append((str(camp_id), 'Name is NaN'))
                    continue

                # Converter ID
                camp_id_str = str(int(camp_id)) if isinstance(camp_id, float) else str(camp_id)
                campaign_name_to_id[camp_name] = camp_id_str

            if campaign_name_to_id:
                logger.info(f"    {len(campaign_name_to_id)} IDs de campanha carregados dos relatórios de Campanhas")

            if skipped_campaigns:
                logger.warning(f"     {len(skipped_campaigns)} campanhas ignoradas no mapeamento:")
                for name, reason in skipped_campaigns[:5]:
                    logger.warning(f"       {name[:60]}: {reason}")

        # Validar adsets
        if adsets_df.empty or 'campaign_id' not in adsets_df.columns:
            logger.error("    Adsets vazios ou sem campaign_id")
            return costs_hierarchy

        # Agrupar por campaign_id extraído dos adsets
        for campaign_id in adsets_df['campaign_id'].dropna().unique():
            if pd.isna(campaign_id) or campaign_id == 'nan':
                continue

            # Buscar adsets desta campanha
            campaign_adsets = adsets_df[adsets_df['campaign_id'] == campaign_id]
            if campaign_adsets.empty:
                continue

            # Nome da campanha vem do primeiro adset
            campaign_name = campaign_adsets.iloc[0]['campaign_name']

            # NOTA: NÃO sobrescrever campaign_id do adset com mapeamento por nome
            # porque pode haver campanhas com mesmo nome mas IDs diferentes.
            # O campaign_id do adset já é correto (vem da coluna "Identificação da campanha")

            # CORREÇÃO: Usar spend dos ADSETS (que tem campaign_id correto)
            # em vez de campaigns_df (que só tem nome e causa duplicação)
            total_spend = campaign_adsets['spend'].sum() if not campaign_adsets.empty else 0.0

            # Buscar ads desta campanha
            campaign_ads = ads_df[ads_df['campaign_id'] == campaign_id] if not ads_df.empty else pd.DataFrame()

            # Agregar budget dos adsets (ABO - Ad Set Budget Optimization)
            budget = campaign_adsets['budget'].sum() if not campaign_adsets.empty else 0.0

            # Se budget dos adsets é 0, pode ser CBO (Campaign Budget Optimization)
            # Buscar budget do nível da campanha
            if budget == 0:
                # Buscar do campaigns_df por nome (único lugar onde budget de campanha CBO pode estar)
                campaign_rows = campaigns_df[campaigns_df['campaign_name'] == campaign_name]
                if not campaign_rows.empty and 'budget' in campaign_rows.columns:
                    campaign_budget = campaign_rows['budget'].iloc[0] if len(campaign_rows) > 0 else 0
                    if campaign_budget > 0:
                        budget = campaign_budget

            # Número de criativos (ads únicos)
            num_creatives = len(campaign_ads) if not campaign_ads.empty else 0

            # Account ID e name do primeiro adset
            account_id_from_adset = campaign_adsets.iloc[0].get('account_id', '')
            account_name = campaign_adsets.iloc[0].get('_account_name', 'Unknown')

            # NOVO: Extrair eventos diretamente das colunas dos adsets
            # Os novos relatórios têm colunas separadas para cada tipo de evento
            total_leads_standard = 0
            lead_qualified = 0
            lead_qualified_hq = 0
            faixa_a = 0

            # Somar eventos de todos os adsets da campanha
            if 'leads_standard' in campaign_adsets.columns:
                total_leads_standard = campaign_adsets['leads_standard'].sum()
            if 'lead_qualified' in campaign_adsets.columns:
                lead_qualified = campaign_adsets['lead_qualified'].sum()
            if 'lead_qualified_hq' in campaign_adsets.columns:
                lead_qualified_hq = campaign_adsets['lead_qualified_hq'].sum()
            if 'faixa_a' in campaign_adsets.columns:
                faixa_a = campaign_adsets['faixa_a'].sum()

            # Total de leads = apenas leads padrão (não somar eventos customizados, pois são subsets)
            # Eventos customizados (LQ, LQHQ, Faixa A) são subconjuntos dos leads, não leads adicionais
            total_leads = total_leads_standard

            # EDGE CASE: Campanha 120234062599950 usa LeadQualified como leads
            # Esta campanha não reporta "Leads" padrão, apenas eventos customizados
            if campaign_id == '120234062599950' and (total_leads_standard == 0 or pd.isna(total_leads_standard)):
                total_leads = lead_qualified
                logger.info(f"     Edge case: Campanha {campaign_id} usando LeadQualified como leads ({int(lead_qualified)})")

            # Coletar optimization_goals únicos dos adsets desta campanha
            # Agora usa a coluna "Indicador de resultados" (já simplificada para "optimization_goal")
            optimization_goals = set()
            if 'optimization_goal' in campaign_adsets.columns:
                for goal in campaign_adsets['optimization_goal'].dropna().unique():
                    if goal and goal != 'nan':
                        optimization_goals.add(str(goal))

            # Se não tiver optimization_goal, usar Lead como fallback
            if not optimization_goals:
                optimization_goals.add('Lead')

            # Construir estrutura de adsets para essa campanha
            adsets_dict = {}
            for _, adset_row in campaign_adsets.iterrows():
                adset_id = adset_row.get('adset_id', 'unknown')
                adset_name = adset_row.get('adset_name', 'Unknown')

                # Usar optimization_goal do adset (já simplificado na normalização)
                adset_opt_goal = adset_row.get('optimization_goal', 'Lead')
                if pd.isna(adset_opt_goal) or adset_opt_goal == 'nan':
                    adset_opt_goal = 'Lead'

                adsets_dict[str(adset_id)] = {
                    'name': adset_name,
                    'optimization_goal': adset_opt_goal,
                    'spend': float(adset_row.get('spend', 0)),
                    'budget': float(adset_row.get('budget', 0))
                }

            # Construir entrada
            costs_hierarchy['campaigns'][campaign_id] = {
                'name': campaign_name,
                'account_id': account_id_from_adset,  # CORREÇÃO: usar account_id real, não account_name
                'spend': float(total_spend) if not pd.isna(total_spend) else 0.0,
                'daily_budget': float(budget) if not pd.isna(budget) else 0.0,
                'num_creatives': num_creatives,
                'optimization_goals': optimization_goals,
                'leads': int(total_leads) if not pd.isna(total_leads) else 0,
                'LeadQualified': int(lead_qualified) if not pd.isna(lead_qualified) else 0,
                'LeadQualifiedHighQuality': int(lead_qualified_hq) if not pd.isna(lead_qualified_hq) else 0,
                'Faixa A': int(faixa_a) if not pd.isna(faixa_a) else 0,
                'adsets': adsets_dict  # NOVO: Adicionar adsets individuais
            }

        logger.info(f"    Costs hierarchy construída: {len(costs_hierarchy['campaigns'])} campanhas")

        # DEBUG: Verificar se leads foram extraídos
        total_leads_extracted = sum(camp.get('leads', 0) for camp in costs_hierarchy['campaigns'].values())
        logger.info(f"    Total de leads extraídos: {total_leads_extracted}")

        # DEBUG: Verificar gasto total
        total_spend_extracted = sum(camp.get('spend', 0) for camp in costs_hierarchy['campaigns'].values())
        logger.info(f"    Gasto total extraído: R$ {total_spend_extracted:,.2f}")

        # DEBUG: Comparar com total nos relatórios
        total_campaigns_in_df = len(campaign_name_to_id) if campaign_name_to_id else 0
        total_adsets_unique_campaigns = len(adsets_df['campaign_id'].dropna().unique()) if not adsets_df.empty else 0
        if total_campaigns_in_df != len(costs_hierarchy['campaigns']):
            logger.warning(f"     Discrepância: {total_campaigns_in_df} IDs nos Campanhas.xlsx, mas apenas {len(costs_hierarchy['campaigns'])} processadas")
            logger.warning(f"     {total_adsets_unique_campaigns} IDs únicos de campanha encontrados nos Adsets")

        # DEBUG DETALHADO: Estatísticas por conta
        logger.info("")
        logger.info("=" * 100)
        logger.info(" DEBUG: ESTATÍSTICAS POR CONTA")
        logger.info("=" * 100)

        # Agrupar campanhas por account
        from collections import defaultdict
        stats_by_account = defaultdict(lambda: {'campaigns': 0, 'adsets': 0, 'ads': 0, 'spend': 0.0})

        # Contar campanhas por conta
        for camp_id, camp_data in costs_hierarchy['campaigns'].items():
            account = camp_data.get('account_id', 'Unknown')
            stats_by_account[account]['campaigns'] += 1
            stats_by_account[account]['spend'] += camp_data.get('spend', 0.0)

        # Contar adsets por conta (usar account_name dos relatórios)
        if not adsets_df.empty and 'account_name' in adsets_df.columns:
            adsets_by_account = adsets_df.groupby('account_name').size().to_dict()
            for account, count in adsets_by_account.items():
                stats_by_account[account]['adsets'] = count

        # Contar ads por conta (usar account_name dos relatórios)
        if not ads_df.empty and 'account_name' in ads_df.columns:
            ads_by_account = ads_df.groupby('account_name').size().to_dict()
            for account, count in ads_by_account.items():
                stats_by_account[account]['ads'] = count

        # Exibir estatísticas
        for account in sorted(stats_by_account.keys()):
            stats = stats_by_account[account]
            logger.info("")
            logger.info(f" Conta: {account}")
            logger.info(f"    Campanhas: {stats['campaigns']}")
            logger.info(f"    Adsets: {stats['adsets']}")
            logger.info(f"    Ads: {stats['ads']}")
            logger.info(f"    Gasto Total: R$ {stats['spend']:,.2f}")

        logger.info("")
        logger.info("=" * 100)
        logger.info("")

        return costs_hierarchy


    def load_adsets_for_comparison(
        self,
        ml_campaign_ids: List[str],
        control_campaign_ids: List[str]
    ) -> pd.DataFrame:
        """
        Carrega adsets de campanhas ML e Controle para comparação.

        Args:
            ml_campaign_ids: IDs das campanhas ML
            control_campaign_ids: IDs das campanhas controle

        Returns:
            DataFrame com adsets filtrados e marcados (ml_type)
        """
        reports = self.load_all_reports(start_date='2025-11-18', end_date='2025-12-01')
        adsets_df = reports['adsets']

        if adsets_df.empty:
            return pd.DataFrame()

        # Filtrar apenas campanhas relevantes
        all_campaign_ids = ml_campaign_ids + control_campaign_ids
        adsets_filtered = adsets_df[adsets_df['campaign_id'].isin(all_campaign_ids)].copy()

        # Marcar tipo (ML ou Controle)
        adsets_filtered['ml_type'] = adsets_filtered['campaign_id'].apply(
            lambda x: 'COM_ML' if x in ml_campaign_ids else 'SEM_ML'
        )

        return adsets_filtered

    def load_ads_for_comparison(
        self,
        ml_campaign_ids: List[str],
        control_campaign_ids: List[str]
    ) -> pd.DataFrame:
        """
        Carrega ads de campanhas ML e Controle para comparação.

        Args:
            ml_campaign_ids: IDs das campanhas ML
            control_campaign_ids: IDs das campanhas controle

        Returns:
            DataFrame com ads filtrados e marcados (ml_type)
        """
        reports = self.load_all_reports(start_date='2025-11-18', end_date='2025-12-01')
        ads_df = reports['ads']

        if ads_df.empty:
            return pd.DataFrame()

        # Extrair AD code do nome do anúncio
        ads_df['ad_code'] = ads_df['ad_name'].str.extract(r'(AD0\d+)', expand=False)

        # Filtrar apenas campanhas relevantes
        all_campaign_ids = ml_campaign_ids + control_campaign_ids
        ads_filtered = ads_df[ads_df['campaign_id'].isin(all_campaign_ids)].copy()

        # Marcar tipo (ML ou Controle)
        ads_filtered['ml_type'] = ads_filtered['campaign_id'].apply(
            lambda x: 'COM_ML' if x in ml_campaign_ids else 'SEM_ML'
        )

        return ads_filtered
