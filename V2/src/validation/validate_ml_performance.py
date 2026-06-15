#!/usr/bin/env python3
"""
Script CLI para Validação de Performance do Modelo de ML de Lead Scoring.

Compara campanhas COM ML vs SEM ML e valida performance por decil D1-D10.

Uso:
    # Forma mais simples — datas automáticas de configs/launches.yaml
    python scripts/validate_ml_performance.py --lf LF49

    python scripts/validate_ml_performance.py \
        --periodo periodo_1 \
        --account-id act_XXXXXXXXX

    python scripts/validate_ml_performance.py \
        --start-date 2025-11-11 \
        --end-date 2025-12-01 \
        --account-id act_XXXXXXXXX \
        --product-value 2000
"""

import argparse
import sys
import os
from pathlib import Path

# Carregar variáveis de ambiente do V2/.env automaticamente
_env_file = Path(__file__).parent.parent.parent / '.env'
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())
from datetime import datetime, timedelta
from glob import glob
import yaml
import logging
import time
import pandas as pd
import numpy as np
from tabulate import tabulate

# Adicionar V2/ ao path para imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Imports dos módulos de validação
from src.validation.data_loader import LeadDataLoader, SalesDataLoader, CAPILeadDataLoader, get_active_model_path, _cache_is_fresh
from src.validation.campaign_classifier import add_ml_classification
from src.validation.matching import (
    match_leads_to_sales,
    get_matching_stats,
    filter_by_period
)
from src.validation.metrics_calculator import (
    CampaignMetricsCalculator,
    DecileMetricsCalculator,
    compare_ml_vs_non_ml,
    calculate_overall_stats,
    calculate_comparison_group_metrics
)
from src.validation.report_generator import ValidationReportGenerator
# from src.validation.visualization import ValidationVisualizer  # REMOVIDO: visualizações desabilitadas, import causava delay de ~6min
from src.validation.period_calculator import PeriodCalculator
from src.validation.meta_reports_loader import MetaReportsLoader
from src.validation.ml_monitoring_calculator import MLMonitoringCalculator

# Imports de integrações existentes
from api.meta_integration import MetaAdsIntegration
from api.meta_config import META_CONFIG

# Para exibição de tabelas no terminal
try:
    from tabulate import tabulate
except ImportError:
    print(" Biblioteca 'tabulate' não encontrada. Instale com: pip install tabulate")
    sys.exit(1)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURAÇÃO: CAMPANHAS EXCLUÍDAS DA ANÁLISE
# ============================================================================
# Lista de IDs de campanhas (15 dígitos) que devem ser excluídas da análise.
# Útil para remover temporariamente campanhas de teste ou com comportamento atípico.
#
# Formato: IDs de 15 dígitos (primeiros 15 dígitos do Campaign ID)
# Exemplo: '120220370119870' para campanha 120220370119870390
# DESABILITADO: Campanha de teste removida da exclusão para ver dados totais
# EXCLUDE_CAMPAIGN_IDS = [
#     '120220370119870',  # DEVLF | CAP | FRIO | FASE 01 | ABERTO ADV+ | PG2 | SCORE (fase de teste)
# ]

# Para desabilitar a exclusão, deixe a lista vazia:
EXCLUDE_CAMPAIGN_IDS = []
# ============================================================================


def validate_tmb_sales_freshness(sales_df, sales_start, sales_end):
    """
    Valida se as vendas TMB estão atualizadas para o período de análise.

    Regras:
    1. Se não houver NENHUMA venda TMB no período  ERRO CRÍTICO (para execução)
    2. Se houver vendas TMB mas a mais recente é ANTES do fim do período  WARNING (continua com aviso)

    Args:
        sales_df: DataFrame com todas as vendas (Guru + TMB) já filtradas por período
        sales_start: Data início do período de vendas (string 'YYYY-MM-DD')
        sales_end: Data fim do período de vendas (string 'YYYY-MM-DD')

    Returns:
        dict com status e mensagem
    """
    # Filtrar vendas TMB
    tmb_sales = sales_df[sales_df['origem'] == 'tmb'] if 'origem' in sales_df.columns else pd.DataFrame()

    if tmb_sales.empty:
        logger.info(" Nenhuma venda TMB no período — normal quando vendas são via Guru/Hotmart/Asaas")
        return {
            'status': 'ok',
            'message': 'Sem vendas TMB no período',
            'stop_execution': False
        }

    # Verificar data mais recente das vendas TMB
    tmb_latest_date = tmb_sales['sale_date'].max()
    sales_end_dt = pd.to_datetime(sales_end)

    logger.info(f" Vendas TMB no período: {len(tmb_sales)}")
    logger.info(f"   Data mais recente TMB: {tmb_latest_date.strftime('%Y-%m-%d')}")
    logger.info(f"   Fim do período esperado: {sales_end}")

    # Se a data mais recente é antes do fim do período
    if tmb_latest_date < sales_end_dt:
        days_missing = (sales_end_dt - tmb_latest_date).days

        logger.warning("  AVISO: Vendas TMB podem estar DESATUALIZADAS!")
        logger.warning(f"   Última venda TMB: {tmb_latest_date.strftime('%Y-%m-%d')}")
        logger.warning(f"   Fim do período: {sales_end}")
        logger.warning(f"   Diferença: {days_missing} dias")
        logger.warning("   ")
        logger.warning(f"   ℹ  O relatório será gerado com vendas TMB até {tmb_latest_date.strftime('%d/%m/%Y')}")
        logger.warning("   ")

        return {
            'status': 'warning',
            'message': f'Vendas TMB até {tmb_latest_date.strftime("%Y-%m-%d")} (faltam {days_missing} dias)',
            'stop_execution': False,
            'tmb_latest_date': tmb_latest_date.strftime('%Y-%m-%d'),
            'days_missing': days_missing
        }

    # Vendas TMB estão atualizadas
    logger.info(" Vendas TMB atualizadas até o fim do período")

    return {
        'status': 'ok',
        'message': 'Vendas TMB atualizadas',
        'stop_execution': False
    }


def get_periodo_folder_from_dates(start_date: str, end_date: str) -> str:
    """
    Deriva o nome da pasta do período a partir das datas.

    Formato: DD:MM - DD:MM
    Exemplo: 2025-12-16 a 2026-01-12  "16:12 - 12:01"

    Args:
        start_date: Data início no formato YYYY-MM-DD
        end_date: Data fim no formato YYYY-MM-DD

    Returns:
        Nome da pasta no formato DD:MM - DD:MM
    """
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')

    # Formato: DD:MM - DD:MM
    folder_name = f"{start_dt.day:02d}:{start_dt.month:02d} - {end_dt.day:02d}:{end_dt.month:02d}"

    return folder_name


def get_month_folder_from_date(start_date: str) -> str:
    """
    Retorna a pasta de mês (YYYY-MM) baseada na data de início do período de vendas.

    Estrutura: outputs/validation/YYYY-MM/{periodo_folder}/
    Exemplo: 2026-03-30 → "2026-03"

    Args:
        start_date: Data início no formato YYYY-MM-DD

    Returns:
        Nome da pasta de mês no formato YYYY-MM
    """
    dt = datetime.strptime(start_date, '%Y-%m-%d')
    return f"{dt.year}-{dt.month:02d}"


def parse_args():
    """
    Parse argumentos da linha de comando.

    Returns:
        Namespace com argumentos
    """
    parser = argparse.ArgumentParser(
        description='Sistema de Validação de Performance ML - Lead Scoring',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:

  # Usar lançamento do launches.yaml (recomendado)
  python scripts/validate_ml_performance.py --lf LF49

  # Usar período pré-configurado
  python scripts/validate_ml_performance.py --periodo periodo_1 --account-id act_123456789

  # Usar datas customizadas
  python scripts/validate_ml_performance.py \\
    --start-date 2025-11-11 \\
    --end-date 2025-12-01 \\
    --account-id act_123456789

  # Sobrescrever parâmetros do config
  python scripts/validate_ml_performance.py \\
    --periodo periodo_1 \\
    --account-id act_123456789 \\
    --product-value 2500 \\
    --max-match-days 45
        """
    )

    # Período
    period_group = parser.add_mutually_exclusive_group()
    period_group.add_argument(
        '--lf',
        type=str,
        metavar='LFxx',
        help='Identificador do lançamento (ex: LF46, DEV19). Carrega todas as datas de configs/launches.yaml automaticamente.'
    )
    period_group.add_argument(
        '--periodo',
        type=str,
        help='Período pré-configurado (periodo_1, periodo_2, periodo_3)'
    )
    period_group.add_argument(
        '--start-date',
        type=str,
        help='Data início (YYYY-MM-DD) - usa com --end-date'
    )

    parser.add_argument(
        '--end-date',
        type=str,
        help='Data fim (YYYY-MM-DD) - usa com --start-date'
    )

    # Período de vendas (opcional, separado do período de captação)
    parser.add_argument(
        '--sales-start-date',
        type=str,
        help='Data início das vendas para matching (YYYY-MM-DD) - opcional'
    )

    parser.add_argument(
        '--sales-end-date',
        type=str,
        help='Data fim das vendas para matching (YYYY-MM-DD) - opcional'
    )

    # Filtro de produto (Guru/Hotmart). Default = excluir "Mentoria".
    # Passe substrings (case-insensitive) a excluir, separadas por espaço.
    parser.add_argument(
        '--product-exclude',
        type=str,
        nargs='+',
        default=None,
        help='Substrings (case-insensitive) no nome do produto a excluir (Guru/Hotmart). Default: ["Mentoria"]. Tudo o mais passa.'
    )

    # Tipo de relatório
    parser.add_argument(
        '--report-type',
        type=str,
        choices=['fechamento', 'pos-devolucoes'],
        default='fechamento',
        help='Tipo de relatório: fechamento (vendas ainda em prazo de devolução) ou pos-devolucoes (vendas com devoluções já processadas)'
    )

    # Cálculo automático de datas (para campanhas padrão)
    parser.add_argument(
        '--auto-calculate-dates',
        action='store_true',
        help='Calcular datas automaticamente para campanha padrão (3 semanas). Assumindo execução toda segunda-feira.'
    )

    # Meta Ads API
    parser.add_argument(
        '--account-id',
        type=str,
        nargs='+',
        required=False,
        help='IDs das contas Meta Ads, separados por espaço (ex: act_123456789 act_987654321). Se não fornecido, usa os IDs do arquivo de configuração.'
    )

    # Caminhos
    parser.add_argument(
        '--leads-path',
        type=str,
        help='[Opcional] Caminho para CSV de leads (default: usar Google Sheets produção)'
    )

    parser.add_argument(
        '--vendas-path',
        type=str,
        help='Caminho para pasta com arquivos TMB (default: files/validation/{periodo}/)'
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        help='Diretório de saída (default: files/validation/{periodo}/)'
    )

    parser.add_argument(
        '--ml-monitoring-output',
        type=str,
        help='Diretório alternativo para relatórios ML Monitoring (se não especificado, usa --output-dir)'
    )

    parser.add_argument(
        '--periodo-folder',
        type=str,
        help='Nome da pasta do período (ex: "16:12 - 12:01"). Se não especificado, deriva automaticamente de --start-date e --end-date'
    )

    parser.add_argument(
        '--lf-name',
        type=str,
        required=False,
        default=None,
        help='Identificador do lançamento (ex: LF49, LF50, DEV19). Usado como prefixo do arquivo de saída. Inferido automaticamente quando --lf é especificado.'
    )

    # Configurações
    parser.add_argument(
        '--config',
        type=str,
        default='configs/validation_config.yaml',
        help='Caminho para arquivo de configuração YAML'
    )

    parser.add_argument(
        '--product-value',
        type=float,
        help='Valor do produto em R$ (sobrescreve config)'
    )

    parser.add_argument(
        '--max-match-days',
        type=int,
        help='Janela máxima para matching em dias (sobrescreve config)'
    )

    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Desabilita cache de chamadas à Meta API (força buscar dados novos)'
    )

    parser.add_argument(
        '--clear-cache',
        action='store_true',
        help='Limpa todo o cache antes de executar'
    )

    # Meta Access Token
    parser.add_argument(
        '--meta-token',
        type=str,
        help='Token de acesso Meta API (sobrescreve config)'
    )

    # Fair Comparison (HABILITADO POR PADRÃO)
    parser.add_argument(
        '--disable-fair-comparison',
        action='store_true',
        help='Desabilita comparação justa (usa comparação total COM ML vs SEM ML)'
    )

    # Nível de Comparação - Evento ML
    parser.add_argument(
        '--comparison-level',
        type=str,
        choices=['adsets_iguais', 'todos', 'both'],
        default='both',
        help='Nível de comparação: adsets_iguais (apenas ADV estrutura idêntica), todos (todas campanhas ML), both (gera ambos) - default: both'
    )

    # Método de Matching
    parser.add_argument(
        '--matching-method',
        type=str,
        choices=['default', 'unified_last6'],
        default='default',
        help='Método de matching leads-vendas: default (email+telefone completo) ou unified_last6 (email+telefone+últimos 6 dígitos) - default: default'
    )

    # Purchase events CAPI
    parser.add_argument(
        '--send-purchase-events',
        action='store_true',
        help='Após validação, envia eventos Purchase ao Meta CAPI para o período de vendas'
    )

    parser.add_argument(
        '--purchase-test-event-code',
        type=str,
        default=None,
        help='Código de teste do Meta para purchase events (ex: TEST51740). Implica dry-run no Meta.'
    )

    # Evolução DevClub
    parser.add_argument(
        '--update-evolution',
        action='store_true',
        help='Após validação, regenera a planilha Evolução DevClub incluindo este lançamento'
    )

    parser.add_argument(
        '--evolution-name',
        type=str,
        default=None,
        help='Nome do lançamento para a planilha de evolução (ex: LF48). Se omitido, gerado automaticamente.'
    )

    args = parser.parse_args()

    # Validações
    if args.start_date and not args.end_date:
        parser.error("--start-date requer --end-date")
    if args.end_date and not args.start_date:
        parser.error("--end-date requer --start-date")

    if not args.lf and not args.periodo and not args.start_date and not args.auto_calculate_dates:
        parser.error("É necessário especificar --lf LFxx OU --periodo OU --start-date/--end-date (ou usar --auto-calculate-dates)")
    if not args.lf and not args.lf_name:
        parser.error("--lf-name é obrigatório quando --lf não é especificado")

    return args


def load_config(config_path: str) -> dict:
    """
    Carrega configuração do arquivo YAML.

    Args:
        config_path: Caminho para validation_config.yaml

    Returns:
        Dicionário com configurações
    """
    if not Path(config_path).exists():
        logger.error(f" Arquivo de configuração não encontrado: {config_path}")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config


def print_summary_table(ml_comparison: dict):
    """
    Exibe tabela de comparação ML vs Não-ML no terminal.

    Args:
        ml_comparison: Dict retornado por compare_ml_vs_non_ml()
    """
    com_ml = ml_comparison.get('com_ml', {})
    sem_ml = ml_comparison.get('sem_ml', {})
    diff = ml_comparison.get('difference', {})

    data = [
        ['Total de Leads', f"{com_ml.get('leads', 0):,}", f"{sem_ml.get('leads', 0):,}"],
        ['Conversões', f"{com_ml.get('conversions', 0):,}", f"{sem_ml.get('conversions', 0):,}"],
        ['Taxa Conversão', f"{com_ml.get('conversion_rate', 0):.2f}%", f"{sem_ml.get('conversion_rate', 0):.2f}%"],
        ['Receita Total', f"R$ {com_ml.get('revenue', 0):,.2f}", f"R$ {sem_ml.get('revenue', 0):,.2f}"],
        ['Receita Ajustada TMB', f"R$ {com_ml.get('revenue_adjusted', 0):,.2f}", f"R$ {sem_ml.get('revenue_adjusted', 0):,.2f}"],
        ['Gasto Total', f"R$ {com_ml.get('spend', 0):,.2f}", f"R$ {sem_ml.get('spend', 0):,.2f}"],
        ['CPL', f"R$ {com_ml.get('cpl', 0):,.2f}", f"R$ {sem_ml.get('cpl', 0):,.2f}"],
        ['ROAS (nominal)', f"{com_ml.get('roas', 0):.2f}x", f"{sem_ml.get('roas', 0):.2f}x"],
        ['ROAS Ajustado TMB', f"{com_ml.get('roas_adjusted', 0):.2f}x", f"{sem_ml.get('roas_adjusted', 0):.2f}x"],
        ['Margem Contrib.', f"R$ {com_ml.get('margin', 0):,.2f}", f"R$ {sem_ml.get('margin', 0):,.2f}"],
        ['Margem Ajustada TMB', f"R$ {com_ml.get('margin_adjusted', 0):,.2f}", f"R$ {sem_ml.get('margin_adjusted', 0):,.2f}"],
    ]

    headers = ['Métrica', 'COM ML', 'SEM ML']
    print(tabulate(data, headers=headers, tablefmt='grid'), flush=True)

    # Mostrar vencedor (usando ROAS ajustado TMB)
    print(flush=True)
    if com_ml.get('roas_adjusted', 0) > sem_ml.get('roas_adjusted', 0):
        improvement = diff.get('roas_adjusted_diff', 0)
        print(f" VENCEDOR: COM ML (ROAS Ajustado TMB {improvement:.1f}% maior)", flush=True)
    elif sem_ml.get('roas_adjusted', 0) > com_ml.get('roas_adjusted', 0):
        decline = abs(diff.get('roas_adjusted_diff', 0))
        print(f" VENCEDOR: SEM ML (ROAS Ajustado TMB {decline:.1f}% maior)", flush=True)
    else:
        print(" Empate técnico em ROAS Ajustado TMB", flush=True)


def print_decile_table(decile_metrics):
    """
    Exibe tabela de performance por decil no terminal (Guru vs Guru+TMB).

    Args:
        decile_metrics: DataFrame retornado por DecileMetricsCalculator
    """
    if decile_metrics.empty:
        print(" Nenhuma métrica de decil disponível", flush=True)
        return

    # Formatar dados para exibição
    table_data = []
    for _, row in decile_metrics.iterrows():
        table_data.append([
            row['decile'],
            row['leads'],
            row['conversions_guru'],
            row['conversions_total'],
            f"{row['conversion_rate_guru']:.2f}%",
            f"{row['conversion_rate_total']:.2f}%",
            f"{row['expected_conversion_rate']:.2f}%",
            f"{row['performance_ratio_guru']:.2f}x",
            f"{row['performance_ratio_total']:.2f}x",
            f"R$ {row['revenue_guru']:,.0f}",
            f"R$ {row['revenue_total']:,.0f}"
        ])

    headers = [
        'Decil', 'Leads',
        'Conv\nGuru', 'Conv\nTotal',
        'Taxa\nGuru', 'Taxa\nTotal',
        'Taxa\nEsperada',
        'Perf\nGuru', 'Perf\nTotal',
        'Receita\nGuru', 'Receita\nTotal'
    ]
    print(tabulate(table_data, headers=headers, tablefmt='grid'), flush=True)

    # Resumo de performance
    total_guru = decile_metrics['revenue_guru'].sum()
    total_tmb_only = decile_metrics['revenue_total'].sum() - total_guru
    print(flush=True)
    print(f" Receita Total Guru: R$ {total_guru:,.2f}", flush=True)
    print(f" Receita Total TMB: R$ {total_tmb_only:,.2f}", flush=True)
    print(f" Receita Total (Guru+TMB): R$ {decile_metrics['revenue_total'].sum():,.2f}", flush=True)


def enrich_campaign_ids(leads_df: pd.DataFrame, account_ids: list, access_token: str) -> pd.DataFrame:
    """
    Enriquece IDs de campanha/adset com nomes reais da Meta API.

    Identifica linhas onde a coluna 'campaign' contém apenas um ID numérico
    e busca o nome real da campanha ou adset na Meta API.

    Args:
        leads_df: DataFrame com leads
        account_ids: Lista de IDs das contas Meta
        access_token: Token de acesso Meta API

    Returns:
        DataFrame com nomes de campanha enriquecidos
    """
    logger.info("    Procurando IDs de campanha/adset sem nomes...")

    # Identificar linhas com apenas ID numérico
    def is_numeric_id(value):
        if pd.isna(value):
            return False
        value_str = str(value).strip()
        return value_str.isdigit() and len(value_str) > 10  # IDs Meta têm 15+ dígitos

    mask = leads_df['campaign'].apply(is_numeric_id)
    ids_to_enrich = leads_df.loc[mask, 'campaign'].unique()

    if len(ids_to_enrich) == 0:
        logger.info("    Nenhum ID sem nome encontrado")
        return leads_df

    logger.info(f"    Encontrados {len(ids_to_enrich)} IDs únicos para enriquecer ({mask.sum()} respostas)")

    # Inicializar Meta API
    meta_api = MetaAdsIntegration(access_token=access_token)

    # Mapa ID  Nome
    id_to_name = {}

    for campaign_id in ids_to_enrich:
        # Evitar conversão para float que perde precisão em IDs grandes
        campaign_id_str = str(campaign_id).strip()
        # Remover .0 se houver
        if campaign_id_str.endswith('.0'):
            campaign_id_str = campaign_id_str[:-2]

        try:
            import requests

            # Buscar nome via API direta
            url = f"{meta_api.base_url}/{campaign_id_str}"
            params = {
                'access_token': access_token,
                'fields': 'name'
            }

            response = requests.get(url, params=params, timeout=1)  # Timeout reduzido para 1s

            if response.status_code == 200:
                data = response.json()
                name = data.get('name', campaign_id_str)
                id_to_name[campaign_id] = name
                logger.info(f"       {campaign_id_str[:15]}...  {name[:60]}...")
            else:
                logger.info(f"       ID {campaign_id_str}: status {response.status_code} (pode ser adset ou campanha de outra conta)")
                id_to_name[campaign_id] = campaign_id_str

        except Exception as e:
            logger.info(f"       Erro ao buscar {campaign_id_str}: {e}")
            id_to_name[campaign_id] = campaign_id_str

    # Atualizar DataFrame
    enriched_count = 0
    for old_id, new_name in id_to_name.items():
        # Converter old_id para string sem perder precisão
        old_id_str = str(old_id).strip()
        if old_id_str.endswith('.0'):
            old_id_str = old_id_str[:-2]

        if new_name != old_id_str:  # Se mudou
            leads_df.loc[leads_df['campaign'] == old_id, 'campaign'] = new_name
            enriched_count += 1

    logger.info(f"    {enriched_count}/{len(ids_to_enrich)} IDs enriquecidos com sucesso")

    return leads_df


LOCAL_CPA_HISTORICO_PATH = Path(__file__).parent.parent.parent / 'outputs' / 'validation' / 'historico' / 'cpa_historico.csv'


def _download_cpa_historico(bucket_name: str) -> pd.DataFrame:
    """
    Baixa o histórico de CPA. Tenta GCS primeiro; usa arquivo local como fallback.
    Retorna DataFrame vazio se nenhuma fonte estiver disponível.
    """
    # 1. Tentar GCS
    if bucket_name:
        try:
            import io
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob('historico/cpa_historico.csv')
            if blob.exists():
                content = blob.download_as_bytes()
                df = pd.read_csv(io.BytesIO(content))
                print(f"    Histórico de CPA carregado do GCS ({len(df)} registros)", flush=True)
                return df
            print("    Histórico de CPA não encontrado no GCS (arquivo novo será criado)", flush=True)
        except Exception as e:
            print(f"    Aviso: GCS indisponível ({e}), tentando fallback local...", flush=True)

    # 2. Fallback: arquivo local
    if LOCAL_CPA_HISTORICO_PATH.exists():
        df = pd.read_csv(LOCAL_CPA_HISTORICO_PATH)
        print(f"    Histórico de CPA carregado do arquivo local ({len(df)} registros)", flush=True)
        return df

    return pd.DataFrame()


def _build_cpa_rows(
    campaign_metrics: pd.DataFrame,
    start_date: str,
    end_date: str,
    sales_start: str,
    sales_end: str,
    tracking_rate_pct: float
) -> pd.DataFrame:
    """Constrói linhas do histórico de CPA para o período atual (somente Eventos ML)."""
    import re

    if campaign_metrics is None or campaign_metrics.empty:
        return pd.DataFrame()
    if 'comparison_group' not in campaign_metrics.columns:
        return pd.DataFrame()

    ml_df = campaign_metrics[campaign_metrics['comparison_group'] == 'Champion']
    if ml_df.empty:
        return pd.DataFrame()

    tracking_rate = tracking_rate_pct / 100.0 if tracking_rate_pct > 0 else 0.5

    def extract_short_name(camp):
        if '|' in str(camp):
            parts = str(camp).split('|')
            if parts[-1].strip().isdigit() and len(parts[-1].strip()) >= 15:
                return '|'.join(parts[:-1]).strip()
        return str(camp)

    def extract_campaign_id(camp):
        m = re.search(r'1\d{14,}', str(camp))
        return m.group(0)[:15] if m else ''

    rows = []
    for _, r in ml_df.iterrows():
        conv_traqueadas = int(r.get('conversions', 0))
        conv_reais = conv_traqueadas / tracking_rate if tracking_rate > 0 else conv_traqueadas
        gasto = float(r.get('spend', 0))
        cpa = gasto / conv_reais if conv_reais > 0 else 0
        rows.append({
            'periodo_captacao': f"{start_date} a {end_date}",
            'periodo_vendas': f"{sales_start} a {sales_end}",
            'campaign_id': extract_campaign_id(r['campaign']),
            'campaign_name': extract_short_name(r['campaign']),
            'gasto': round(gasto, 2),
            'leads': int(r.get('leads', 0)),
            'conversoes_traqueadas': conv_traqueadas,
            'taxa_tracking_pct': round(tracking_rate_pct, 1),
            'conversoes_reais_est': round(conv_reais, 2),
            'cpa': round(cpa, 2),
            'roas': round(float(r.get('roas', 0)), 2),
            'roas_adj_tmb': round(float(r.get('roas_adjusted', r.get('roas', 0))), 2),
            'receita_traqueada': round(float(r.get('total_revenue', 0)), 2),
            'margem': round(float(r.get('contribution_margin', 0)), 2),
            'gerado_em': datetime.now().strftime('%Y-%m-%d %H:%M'),
        })
    return pd.DataFrame(rows)


def _upload_cpa_historico(df: pd.DataFrame, bucket_name: str):
    """
    Salva o histórico de CPA atualizado. Tenta GCS primeiro; salva localmente como fallback.
    """
    csv_bytes = df.to_csv(index=False).encode('utf-8')

    # 1. Tentar GCS
    gcs_ok = False
    if bucket_name:
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob('historico/cpa_historico.csv')
            blob.upload_from_string(csv_bytes, content_type='text/csv')
            print(f"    Histórico de CPA salvo no GCS ({len(df)} registros)", flush=True)
            gcs_ok = True
        except Exception as e:
            print(f"    Aviso: não foi possível salvar no GCS ({e}), salvando localmente...", flush=True)

    # 2. Sempre salvar localmente (garante fallback para próxima execução)
    try:
        LOCAL_CPA_HISTORICO_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_CPA_HISTORICO_PATH.write_bytes(csv_bytes)
        if not gcs_ok:
            print(f"    Histórico de CPA salvo localmente: {LOCAL_CPA_HISTORICO_PATH} ({len(df)} registros)", flush=True)
    except Exception as e:
        print(f"    Aviso: não foi possível salvar histórico localmente: {e}", flush=True)


def main():
    """
    Função principal do CLI.
    """
    start_time = time.time()

    print(" SISTEMA DE VALIDAÇÃO DE PERFORMANCE ML - LEAD SCORING", flush=True)
    print(flush=True)

    # 1. Parse argumentos
    args = parse_args()

    # 1.1. Carregar datas de launches.yaml quando --lf for especificado
    if args.lf:
        _launches_path = Path(__file__).parent.parent.parent / 'configs' / 'launches.yaml'
        if not _launches_path.exists():
            logger.error(f" configs/launches.yaml não encontrado em {_launches_path}")
            sys.exit(1)
        with open(_launches_path, 'r') as _f:
            _launches = yaml.safe_load(_f)
        if args.lf not in _launches:
            logger.error(f" Lançamento '{args.lf}' não encontrado em launches.yaml. Disponíveis: {', '.join(_launches.keys())}")
            sys.exit(1)
        _lf_cfg = _launches[args.lf]
        args.start_date = _lf_cfg['cap_start']
        args.end_date   = _lf_cfg['cap_end']
        # Defaults do launches.yaml — só aplicar se CLI não forneceu override explícito.
        # Permite rodar `--lf LF53 --sales-end-date 2026-04-29` pra first peak.
        if not args.sales_start_date:
            args.sales_start_date = _lf_cfg['vendas_start']
        if not args.sales_end_date:
            args.sales_end_date   = _lf_cfg['vendas_end']
        if not args.lf_name:
            args.lf_name = args.lf
        logger.info(f" Lançamento {args.lf} carregado de launches.yaml:")
        logger.info(f"   Captação: {args.start_date} a {args.end_date}")
        logger.info(f"   Vendas:   {args.sales_start_date} a {args.sales_end_date}")

    # 1.2. Calcular datas automaticamente se solicitado
    if args.auto_calculate_dates:
        hoje = datetime.now()

        # Calcular baseado no tipo de relatório
        if args.report_type == 'pos-devolucoes':
            # Pós-devoluções: campanha de 1 semana atrás
            # Se hoje é segunda 23/02, validar campanha que fechou em 15/02
            vendas_fim = hoje - timedelta(days=8)  # Domingo de 1 semana atrás
            vendas_inicio = vendas_fim - timedelta(days=6)  # Segunda dessa semana

            captacao_fim = vendas_inicio - timedelta(days=1)  # Domingo anterior
            captacao_inicio = captacao_fim - timedelta(days=6)  # Segunda dessa semana
        else:
            # Fechamento: campanha que fechou ontem (domingo)
            # Se hoje é segunda 23/02, validar campanha que fechou 22/02
            vendas_fim = hoje - timedelta(days=1)  # Domingo (ontem)
            vendas_inicio = vendas_fim - timedelta(days=6)  # Segunda da semana passada

            captacao_fim = vendas_inicio - timedelta(days=1)  # Domingo anterior
            captacao_inicio = captacao_fim - timedelta(days=6)  # Segunda dessa semana

        # Sobrescrever argumentos
        args.start_date = captacao_inicio.strftime('%Y-%m-%d')
        args.end_date = captacao_fim.strftime('%Y-%m-%d')
        args.sales_start_date = vendas_inicio.strftime('%Y-%m-%d')
        args.sales_end_date = vendas_fim.strftime('%Y-%m-%d')

        logger.info(f" Datas calculadas automaticamente ({args.report_type}):")
        logger.info(f"   Captação: {args.start_date} a {args.end_date}")
        logger.info(f"   Vendas: {args.sales_start_date} a {args.sales_end_date}")

    # DEBUG: Verificar o que foi parseado

    # 1.5. Gerenciar cache se solicitado
    if args.clear_cache:
        import shutil
        cache_dir = Path(__file__).parent.parent.parent / 'files' / 'validation' / 'cache'
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            print("  Cache limpo com sucesso!", flush=True)
            print(flush=True)
        else:
            print("  Nenhum cache encontrado para limpar", flush=True)
            print(flush=True)

    # 2. Carregar configuração
    logger.info(f" Carregando configuração de {args.config}...")
    config = load_config(args.config)

    # Sobrescrever com argumentos CLI
    if args.product_value:
        config['product_value'] = args.product_value
    if args.max_match_days:
        config['max_match_days'] = args.max_match_days
    if args.meta_token:
        config['meta_access_token'] = args.meta_token

    # Account IDs: usar config como fallback se não fornecidos via CLI
    if not args.account_id:
        if 'meta_account_ids' in config:
            # Ler IDs do config e remover prefixo "act_" se presente
            # (o código adiciona automaticamente depois)
            config_ids = config['meta_account_ids']
            args.account_id = [
                id.replace('act_', '') if isinstance(id, str) and id.startswith('act_') else str(id)
                for id in config_ids
            ]
            logger.info(f"    Usando account IDs do config: {', '.join(args.account_id)}")
        else:
            logger.error(" Nenhum account ID fornecido via CLI ou config")
            sys.exit(1)

    # Determinar período
    if args.periodo:
        if args.periodo not in config.get('periodos', {}):
            logger.error(f" Período '{args.periodo}' não encontrado no config")
            sys.exit(1)
        period_config = config['periodos'][args.periodo]
        start_date = period_config['start_date']
        end_date = period_config['end_date']
        period_name = period_config['name']
        logger.info(f"   Período: {period_name} ({start_date} a {end_date})")

        # Usar sales dates do config se não foram especificados via CLI
        if not args.sales_start_date and 'sales_start_date' in period_config:
            args.sales_start_date = period_config['sales_start_date']
            logger.info(f"    Período de vendas do config: {args.sales_start_date} a {period_config.get('sales_end_date')}")
        if not args.sales_end_date and 'sales_end_date' in period_config:
            args.sales_end_date = period_config['sales_end_date']
    else:
        start_date = args.start_date
        end_date = args.end_date
        period_name = f"Período {start_date} a {end_date}"
        logger.info(f"   Período customizado: {start_date} a {end_date}")

    # Derivar pasta do período automaticamente se não fornecida
    # Usa datas de VENDAS quando disponíveis (padrão histórico), senão captação
    if args.periodo_folder:
        periodo_folder = args.periodo_folder
        logger.info(f"    Pasta do período (manual): {periodo_folder}")
    elif args.sales_start_date and args.sales_end_date:
        periodo_folder = get_periodo_folder_from_dates(args.sales_start_date, args.sales_end_date)
        logger.info(f"    Pasta do período (derivada de vendas): {periodo_folder}")
    else:
        periodo_folder = get_periodo_folder_from_dates(start_date, end_date)
        logger.info(f"    Pasta do período (derivada de captação): {periodo_folder}")

    # Determinar caminhos baseados na pasta do período
    # Usa caminho absoluto baseado na localização do script (independe do cwd)
    _V2_ROOT = Path(__file__).parent.parent.parent

    # Pasta de mês: YYYY-MM baseado no início do período de vendas (ou captação como fallback)
    _month_ref = args.sales_start_date if args.sales_start_date else start_date
    month_folder = get_month_folder_from_date(_month_ref)

    periodo_base_path = str(_V2_ROOT / 'outputs' / 'validation' / month_folder / periodo_folder)

    # vendas_path: se especificado via CLI, usa; senão, usa pasta de dados devclub
    if args.vendas_path:
        vendas_path = args.vendas_path
    else:
        vendas_path = str(_V2_ROOT / 'data' / 'devclub')

    # output_dir: usa pasta mensal (YYYY-MM), sem subpasta de período
    _month_output = str(_V2_ROOT / 'outputs' / 'validation' / month_folder)
    if args.ml_monitoring_output:
        output_dir = args.ml_monitoring_output
    elif args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = _month_output

    # meta_reports_dir: também usa pasta validation raiz
    meta_reports_dir = str(_V2_ROOT / 'files' / 'validation')

    logger.info(f"   Vendas (TMB): {vendas_path}")
    logger.info(f"   Meta Reports: {meta_reports_dir}")
    logger.info(f"   Output: {output_dir}")
    logger.info(f"   Valor do produto: R$ {config['product_value']:,.2f}")
    logger.info(f"   Janela de matching: {config['max_match_days']} dias")
    print(flush=True)

    # 3. Carregar dados
    print(" CARREGANDO DADOS...", flush=True)
    print(flush=True)

    # Leads - PADRÃO: Google Sheets (produção), FALLBACK: CSV se --leads-path fornecido
    fbp_fbc_map = {}
    if args.leads_path:
        # Modo CSV (legacy)
        logger.info(f"    Usando CSV: {args.leads_path}")
        capi_loader = CAPILeadDataLoader()

        if not Path(args.leads_path).exists():
            logger.error(f" Arquivo de leads não encontrado: {args.leads_path}")
            sys.exit(1)

        leads_df, lead_source_stats = capi_loader.load_combined_leads(
            csv_path=args.leads_path,
            start_date=start_date if isinstance(start_date, str) else start_date.strftime('%Y-%m-%d'),
            end_date=end_date if isinstance(end_date, str) else end_date.strftime('%Y-%m-%d')
        )
        logger.info(f"    {len(leads_df)} leads carregados do CSV")
        logger.info(f"    Estatísticas: {lead_source_stats['survey_leads']} pesquisa + {lead_source_stats['capi_leads_extras']} CAPI extras")
    else:
        # Modo Google Sheets (PADRÃO - dados de produção em tempo real)
        logger.info(f"    Usando Google Sheets (produção)")

        # Limpar cache se solicitado
        if args.clear_cache:
            cache_file = Path.home() / '.cache' / 'bring_data' / 'sheets_leads_cache.csv'
            if cache_file.exists():
                cache_file.unlink()
                logger.info(f"     Cache limpo: {cache_file}")

        lead_loader = LeadDataLoader()
        use_cache = not args.no_cache

        # Carregar Pesquisa do Google Sheets sem filtro de data — deduplicar sobre o
        # dataset completo e filtrar por período depois (garante contagem consistente)
        survey_df_all = lead_loader.load_leads_from_sheets(use_cache=use_cache)
        _s = start_date if isinstance(start_date, str) else start_date.strftime('%Y-%m-%d')
        _e = end_date   if isinstance(end_date,   str) else end_date.strftime('%Y-%m-%d')
        # Estender janela de leads para 60 dias antes do início da captação
        # para capturar compradores que se cadastraram em lançamentos anteriores
        _s_extended = (pd.to_datetime(_s) - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
        if not survey_df_all.empty and 'data_captura' in survey_df_all.columns:
            survey_df = survey_df_all[
                (survey_df_all['data_captura'] >= pd.to_datetime(_s_extended)) &
                (survey_df_all['data_captura'] <  pd.to_datetime(_e) + pd.Timedelta(days=1))
            ].copy()
        else:
            survey_df = survey_df_all
        logger.info(f"    {len(survey_df_all)} leads totais nas planilhas → {len(survey_df)} no período (janela 60d)")

        # Fonte 1 (Google Sheets) é opcional — Railway/ledger rodam mesmo quando vazia
        if survey_df.empty or 'email' not in survey_df.columns:
            logger.warning("    Nenhum lead carregado do Google Sheets — seguindo só com Railway/ledger.")
            survey_df = pd.DataFrame(columns=['email', 'data_captura'])
            survey_emails = set()
        else:
            survey_emails = set(survey_df['email'].unique())
            logger.info(f"    {len(survey_emails)} emails únicos na pesquisa")
        if True:  # bloco a seguir preserva indentação original; Railway/ledger sempre rodam

            # Buscar leads CAPI extras (Cloud SQL backup + Railway PostgreSQL)
            import re

            # Railway começa em 18/02/2026 — antes disso usar o backup do Cloud SQL
            RAILWAY_CUTOVER = '2026-02-18'
            CLOUDSQL_BACKUP = Path(__file__).parent.parent.parent / 'data' / 'backups' / 'cloud-sql-final-export-20260225.sql'

            start_str = start_date if isinstance(start_date, str) else start_date.strftime('%Y-%m-%d')
            end_str   = end_date   if isinstance(end_date,   str) else end_date.strftime('%Y-%m-%d')
            # Janela de leads vai ATÉ vendas_end pra capturar compradores que se cadastraram
            # durante a semana de vendas (Client/VIP novo) — não só durante a captação oficial.
            # Mantém cap_start - 60d no início (já tratado abaixo via `_lead_start_ext`).
            _leads_end_str = (args.sales_end_date
                              if hasattr(args, 'sales_end_date') and args.sales_end_date
                              else end_str)

            # Cache CAPI (Cloud SQL + Railway combinados)
            _capi_cache_dir = Path(__file__).parent.parent.parent / 'files' / 'validation' / 'cache'
            _capi_cache_dir.mkdir(parents=True, exist_ok=True)
            _capi_cache_file = _capi_cache_dir / f"capi_{start_str}_{end_str}.parquet"

            if use_cache and _cache_is_fresh(_capi_cache_file, end_str):
                logger.info(f"    Cache HIT CAPI: {_capi_cache_file.name}")
                capi_norm = pd.read_parquet(_capi_cache_file)
                capi_leads_data = []  # skip DB queries
                _capi_from_cache = True
            else:
                _capi_from_cache = False
                capi_leads_data = []

            # --- Fonte 1: Cloud SQL backup (para datas < 18/02/2026) ---
            if start_str < RAILWAY_CUTOVER and CLOUDSQL_BACKUP.exists():
                backup_end = min(end_str, '2026-02-17')
                logger.info(f"    Buscando leads no Cloud SQL backup ({start_str} a {backup_end})...")

                # Colunas: id,email,name,phone,fbp,fbc,event_id,user_agent,client_ip,
                #          event_source_url,utm_source,utm_medium,utm_campaign,utm_term,
                #          utm_content,tem_comp,created_at,...,lead_score,decil,...
                COL = dict(email=1, name=2, phone=3, fbp=4, fbc=5,
                           utm_source=10, utm_medium=11, utm_campaign=12,
                           utm_term=13, utm_content=14, created_at=16,
                           lead_score=36, decil=37)

                in_copy = False
                backup_count = 0
                with open(CLOUDSQL_BACKUP, 'r', encoding='utf-8') as bf:
                    for line in bf:
                        if 'COPY public.leads_capi' in line:
                            in_copy = True
                            continue
                        if not in_copy:
                            continue
                        if line.strip() == '\\.':
                            break
                        cols = line.rstrip('\n').split('\t')
                        if len(cols) <= COL['created_at']:
                            continue
                        dt = cols[COL['created_at']][:10]
                        if dt < start_str or dt > backup_end:
                            continue
                        def _val(c):
                            v = cols[c] if c < len(cols) else '\\N'
                            return None if v == '\\N' else v
                        decil_raw = _val(COL['decil'])
                        ls_raw    = _val(COL['lead_score'])
                        capi_leads_data.append({
                            'email':        _val(COL['email']),
                            'name':         _val(COL['name']),
                            'phone':        _val(COL['phone']),
                            'utm_campaign': _val(COL['utm_campaign']),
                            'utm_medium':   _val(COL['utm_medium']),
                            'utm_source':   _val(COL['utm_source']),
                            'utm_content':  _val(COL['utm_content']),
                            'utm_term':     _val(COL['utm_term']),
                            'lead_score':   float(ls_raw) if ls_raw else None,
                            'decil':        f"D{decil_raw}" if decil_raw else None,
                            'fbc':          _val(COL['fbc']),
                            'fbp':          _val(COL['fbp']),
                            'created_at':   _val(COL['created_at']),
                        })
                        backup_count += 1
                logger.info(f"    Cloud SQL backup: {backup_count} leads encontrados")
            elif start_str < RAILWAY_CUTOVER and not CLOUDSQL_BACKUP.exists():
                logger.warning(f"    Backup Cloud SQL não encontrado em {CLOUDSQL_BACKUP}")

            # --- Fonte 2: Railway tabela `Lead` (histórico pré-17/05/2026) ---
            # Lead parou de receber em ~17/05/2026 (migração de schema). Mesma janela 60d
            # do Sheets/ledger pra cobrir compradores de LFs anteriores. Se a janela do
            # pipeline (start - 60d) começa DEPOIS da morte da Lead, skipar — Lead não tem
            # nada útil nessa janela e pull do Railway é caro (~76k linhas).
            LEAD_DEATH_DATE = '2026-05-17'
            _lead_start_ext = (pd.to_datetime(start_str) - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
            if _leads_end_str >= RAILWAY_CUTOVER and _lead_start_ext < LEAD_DEATH_DATE:
                railway_start = max(_lead_start_ext, RAILWAY_CUTOVER)
                # End da Lead = min(janela_pipeline, lead_death) — não puxa dados pós-morte
                _lead_end_str = min(_leads_end_str, LEAD_DEATH_DATE)
                end_excl = (pd.to_datetime(_lead_end_str) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                logger.info(f"    Buscando leads no Railway/Lead ({railway_start} a {_lead_end_str})...")
            elif _leads_end_str >= RAILWAY_CUTOVER and _lead_start_ext >= LEAD_DEATH_DATE:
                logger.info(f"    Skip Lead antiga: janela {_lead_start_ext}+ é toda pós-morte ({LEAD_DEATH_DATE})")
            if _leads_end_str >= RAILWAY_CUTOVER and _lead_start_ext < LEAD_DEATH_DATE:
                try:
                    import pg8000.native
                    railway_conn = pg8000.native.Connection(
                        host=os.environ.get('RAILWAY_DB_HOST', 'shortline.proxy.rlwy.net'),
                        port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
                        database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
                        user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
                        password=os.environ['RAILWAY_DB_PASSWORD'],
                    )
                    rows = railway_conn.run(
                        """
                        SELECT email, "nomeCompleto", telefone,
                               campaign, medium, source, content, term,
                               "leadScore", decil, fbc, fbp, "createdAt"
                        FROM "Lead"
                        WHERE "createdAt" >= :start_date
                          AND "createdAt" <  :end_date_excl
                        ORDER BY "createdAt" DESC
                        """,
                        start_date=railway_start,
                        end_date_excl=end_excl,
                    )
                    # fbp/fbc na tabela Lead são sempre NULL — buscamos de leads_capi
                    try:
                        capi_fbp_rows = railway_conn.run(
                            """
                            SELECT LOWER(email), fbp, fbc
                            FROM leads_capi
                            WHERE created_at >= :start_date
                              AND created_at <  :end_date_excl
                              AND email IS NOT NULL
                              AND (fbp IS NOT NULL OR fbc IS NOT NULL)
                            """,
                            start_date=railway_start,
                            end_date_excl=end_excl,
                        )
                        for _email, _fbp, _fbc in capi_fbp_rows:
                            if _email:
                                fbp_fbc_map[_email.strip()] = {'fbp': _fbp, 'fbc': _fbc}
                        logger.info(f"    Railway leads_capi: {len(fbp_fbc_map)} emails com fbp/fbc")
                    except Exception as _ce:
                        logger.warning(f"    Aviso: não foi possível ler leads_capi do Railway: {_ce}")
                    railway_conn.close()
                    railway_leads = [
                        {
                            'email':        r[0],
                            'name':         r[1],
                            'phone':        r[2],
                            'utm_campaign': r[3],
                            'utm_medium':   r[4],
                            'utm_source':   r[5],
                            'utm_content':  r[6],
                            'utm_term':     r[7],
                            'lead_score':   float(r[8]) if r[8] is not None else None,
                            'decil':        f"D{r[9]}" if r[9] is not None else None,
                            'fbc':          r[10],
                            'fbp':          r[11],
                            'created_at':   r[12],
                        }
                        for r in rows
                    ]
                    logger.info(f"    Railway: {len(railway_leads)} leads encontrados")
                    capi_leads_data.extend(railway_leads)
                except Exception as e:
                    logger.warning(f"    Erro ao conectar com Railway: {e}")

            # --- Fonte 3: Railway `registros_ml` (ledger ML — fonte canônica pós-17/05/2026) ---
            # A tabela "Lead" parou de receber em ~17/05; o ledger é populado pelo consumer
            # Pub/Sub e é onde leads do sistema novo vivem. Sem isso o pipeline retorna 0
            # leads pra qualquer LF a partir de 17/05.
            if _leads_end_str >= '2026-05-17':
                # Janela estendida 60d antes do cap_start pra capturar compradores
                # que vieram de LFs anteriores (mesma lógica de _s_extended do Sheets).
                # Limite inferior é 2026-05-17 — antes disso o ledger ainda não existia.
                _ledger_start_ext = (pd.to_datetime(start_str) - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
                ledger_start = max(_ledger_start_ext, '2026-05-17')
                logger.info(f"    Buscando leads no Railway/registros_ml ({ledger_start} a {_leads_end_str})...")
                _ledger_loader = SalesDataLoader()
                ledger_dfs = []
                for vf in (None, 'champion_jan30', 'challenger_abr28'):
                    df_v = _ledger_loader.load_ml_ledger(
                        ledger_start, _leads_end_str,
                        variant_filter=vf,
                        only_with_score=False,
                        only_with_survey=False,
                    )
                    if not df_v.empty:
                        ledger_dfs.append(df_v)
                if ledger_dfs:
                    ledger_df = pd.concat(ledger_dfs, ignore_index=True)
                    def _strip(v): return v.strip() if isinstance(v, str) else ''
                    def _get(r, k): return r[k] if (k in r and pd.notna(r[k])) else None
                    ledger_leads = [
                        {
                            'email':        r['email'],
                            'name':         (f"{_strip(_get(r,'first_name'))} {_strip(_get(r,'last_name'))}".strip() or None),
                            'phone':        _get(r, 'telefone'),
                            'utm_campaign': _get(r, 'utm_campaign'),
                            'utm_medium':   _get(r, 'utm_medium'),
                            'utm_source':   _get(r, 'utm_source'),
                            'utm_content':  _get(r, 'utm_content'),
                            'utm_term':     _get(r, 'utm_term'),
                            'lead_score':   float(r['lead_score']) if pd.notna(_get(r, 'lead_score')) else None,
                            'decil':        f"D{int(r['decil']):02d}" if pd.notna(_get(r, 'decil')) else None,
                            'fbc':          _get(r, 'fbc'),
                            'fbp':          _get(r, 'fbp'),
                            'created_at':   r['data_captura'],
                            'variant':      _get(r, 'variant'),
                            'base_status':  _get(r, 'base_status'),
                        }
                        for _, r in ledger_df.iterrows()
                    ]
                    logger.info(f"    Ledger: {len(ledger_leads)} leads encontrados")
                    capi_leads_data.extend(ledger_leads)
                else:
                    logger.info(f"    Ledger: 0 leads no período")

            # --- Fonte 4: Railway `Client` + `UTMTracking` (front novo, superset do ledger) ---
            # `registros_ml` só recebe leads que disparam evento Pub/Sub (Meta-elegíveis,
            # com fbp/fbc, etc.). `Client` recebe TODO lead que toca o sistema — inclusive
            # quem chega via Google Ads/orgânico ou nunca preencheu a pesquisa.
            # JOIN com `UTMTracking` traz os UTMs (última atribuição por email).
            # Filtra fora leads que já estão no ledger pra evitar duplicação.
            if _leads_end_str >= '2026-05-17':
                _client_start = (pd.to_datetime(start_str) - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
                _client_start = max(_client_start, '2026-05-17')
                logger.info(f"    Buscando leads em Client+UTMTracking ({_client_start} → {_leads_end_str})...")
                try:
                    import pg8000.native as _pg
                    from src.data.ledger_connection import open_ledger_read_connection
                    _end_excl = (pd.to_datetime(_leads_end_str) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

                    # Anti-join cross-banco: `Client`/`UTMTracking` só existem no Railway,
                    # mas o set de e-mails do ledger vem da fonte escolhida por
                    # LEDGER_READ_SOURCE (railway|cloudsql) — assim sobrevive ao DROP do
                    # `registros_ml` no Railway (Etapa 5). Filtro em Python, não em SQL.
                    _ledger_conn = open_ledger_read_connection()
                    try:
                        _ledger_email_rows = _ledger_conn.run(
                            '''SELECT LOWER(email) FROM registros_ml
                               WHERE created_at >= :s AND created_at < :e AND email IS NOT NULL''',
                            s=_client_start, e=_end_excl,
                        )
                    finally:
                        _ledger_conn.close()
                    _ledger_emails = {r[0] for r in _ledger_email_rows if r[0]}

                    _conn = _pg.Connection(
                        host=os.environ.get('RAILWAY_DB_HOST', 'shortline.proxy.rlwy.net'),
                        port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
                        database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
                        user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
                        password=os.environ['RAILWAY_DB_PASSWORD'],
                    )
                    _client_rows = _conn.run(
                        '''
                        SELECT c.email, c."firstName", c."lastName", c.phone,
                               c.fbp, c.fbc, c."firstSeenAt",
                               u.source, u.medium, u.campaign, u.content, u.term
                        FROM "Client" c
                        LEFT JOIN LATERAL (
                            SELECT source, medium, campaign, content, term
                            FROM "UTMTracking"
                            WHERE LOWER("clientEmail") = LOWER(c.email)
                            ORDER BY "trackedAt" DESC
                            LIMIT 1
                        ) u ON true
                        WHERE c."firstSeenAt" >= :s AND c."firstSeenAt" < :e
                          AND c.email IS NOT NULL AND c.email != ''
                        ''',
                        s=_client_start, e=_end_excl,
                    )
                    _conn.close()
                    # Anti-join em Python: descarta quem já está no ledger.
                    _client_rows = [
                        r for r in _client_rows
                        if (r[0] or '').strip().lower() not in _ledger_emails
                    ]
                    def _ss(v): return v.strip() if isinstance(v, str) else ''
                    client_leads = [
                        {
                            'email':        r[0],
                            'name':         (f"{_ss(r[1])} {_ss(r[2])}".strip() or None),
                            'phone':        r[3],
                            'utm_campaign': r[9],
                            'utm_medium':   r[8],
                            'utm_source':   r[7],
                            'utm_content':  r[10],
                            'utm_term':     r[11],
                            'lead_score':   None,
                            'decil':        None,
                            'fbc':          r[5],
                            'fbp':          r[4],
                            'created_at':   r[6],
                            'variant':      None,
                            'base_status':  None,
                        }
                        for r in _client_rows
                    ]
                    logger.info(f"    Client+UTMTracking: {len(client_leads)} leads complementares (não estão no ledger)")
                    capi_leads_data.extend(client_leads)
                except Exception as _ce:
                    logger.warning(f"    Aviso: erro Client+UTMTracking: {_ce}")

            # --- Fonte 5: VIP xlsx local (lead magnet, fora do funil padrão) ---
            # Esses leads vêm de captação separada (formulário VIP), não passam pelo
            # Pub/Sub e geralmente não têm UTM Meta. Marcamos com `lead_source='vip'`
            # pra preservar do filtro `campaign_id_meta` mais à frente.
            import glob as _glob
            _vip_files = sorted(_glob.glob('data/devclub/vip_*.xlsx'))
            if _vip_files:
                _vip_xlsx = _vip_files[-1]
                try:
                    _vip_df = pd.read_excel(_vip_xlsx)
                    _email_col = next((c for c in _vip_df.columns if 'mail' in str(c).lower()), None)
                    _nome_col = next((c for c in _vip_df.columns if 'nome' in str(c).lower()), None)
                    _tel_col = next((c for c in _vip_df.columns if 'tel' in str(c).lower() or 'phone' in str(c).lower()), None)
                    _data_col = next((c for c in _vip_df.columns if 'data' in str(c).lower() or 'date' in str(c).lower()), None)
                    _utm_col = next((c for c in _vip_df.columns if 'utm' in str(c).lower()), None)
                    vip_leads = []
                    for _, r in _vip_df.iterrows():
                        em = r.get(_email_col) if _email_col else None
                        if pd.isna(em) or not em:
                            continue
                        vip_leads.append({
                            'email':        str(em).lower().strip(),
                            'name':         str(r.get(_nome_col, '')).strip() or None if _nome_col else None,
                            'phone':        str(r.get(_tel_col)) if _tel_col and pd.notna(r.get(_tel_col)) else None,
                            'utm_campaign': str(r.get(_utm_col)) if _utm_col and pd.notna(r.get(_utm_col)) else None,
                            'utm_medium':   None,
                            'utm_source':   'vip',  # marcador pra origem
                            'utm_content':  None,
                            'utm_term':     None,
                            'lead_score':   None,
                            'decil':        None,
                            'fbc':          None,
                            'fbp':          None,
                            'created_at':   pd.to_datetime(r.get(_data_col), errors='coerce') if _data_col else pd.NaT,
                            'variant':      None,
                            'base_status':  None,
                            'lead_source':  'vip',  # PRESERVA do filtro campaign_id_meta
                        })
                    logger.info(f"    VIP ({Path(_vip_xlsx).name}): {len(vip_leads)} leads")
                    capi_leads_data.extend(vip_leads)
                except Exception as _ve:
                    logger.warning(f"    Aviso: erro VIP: {_ve}")

            if _capi_from_cache:
                logger.info(f"    Cache HIT CAPI: {len(capi_norm)} leads (do cache)")
            elif capi_leads_data:
                logger.info(f"    CAPI total (backup + Railway): {len(capi_leads_data)} leads")
                from src.validation.data_loader import normalizar_email, normalizar_telefone_robusto

                capi_df = pd.DataFrame(capi_leads_data)
                capi_norm = pd.DataFrame()
                capi_norm['email'] = capi_df['email'].apply(lambda x: normalizar_email(x) if pd.notna(x) else None)
                capi_norm['nome'] = capi_df.get('name', np.nan)
                capi_norm['telefone'] = capi_df.get('phone', np.nan).apply(
                    lambda x: normalizar_telefone_robusto(str(x)) if pd.notna(x) else None
                )
                capi_norm['data_captura'] = pd.to_datetime(capi_df['created_at'], errors='coerce')
                capi_norm['campaign'] = capi_df.get('utm_campaign', np.nan)
                capi_norm['source'] = capi_df.get('utm_source', np.nan)
                capi_norm['medium'] = capi_df.get('utm_medium', np.nan)
                capi_norm['term'] = capi_df.get('utm_term', np.nan)
                capi_norm['content'] = capi_df.get('utm_content', np.nan)
                capi_norm['lead_score'] = capi_df.get('lead_score', np.nan)
                capi_norm['decile'] = capi_df.get('decil', None)
                # Bloco F — split Champion vs Challenger só faz sentido pra leads
                # do ledger novo (registros_ml). Leads da tabela Lead antiga não
                # têm essas colunas → ficam None e caem em "fora do A/B".
                capi_norm['variant'] = capi_df.get('variant', None)
                capi_norm['base_status'] = capi_df.get('base_status', None)
                # `lead_source` marca origem alternativa (VIP, etc.) — usado pra
                # preservar do filtro `campaign_id_meta` abaixo.
                capi_norm['lead_source'] = capi_df.get('lead_source', None)
                capi_norm['source_type'] = 'capi'
                capi_norm = capi_norm[capi_norm['email'].notna()].copy()

                def extract_campaign_id_meta(utm_campaign):
                    if pd.isna(utm_campaign):
                        return None
                    match = re.search(r'\|\s*(\d{10,})\s*$', str(utm_campaign))
                    return match.group(1)[:15] if match else None  # primeiros 15, igual ao campaigns_df

                capi_norm['campaign_id_meta'] = capi_norm['campaign'].apply(extract_campaign_id_meta)
                # NÃO DROPAR aqui: o `campaign_id_meta` serve pra **classificação Meta**
                # (cruzamento com Meta API por campaign_id). Pro **matching com vendas**, leads
                # de Google Ads / orgânicos / VIP (com utm_campaign='devlf', 'encurtadoraprendacomigo'
                # etc.) também devem entrar no pool — caso contrário ~7 compradores do LF56 que
                # vieram via canais não-Meta ficavam de fora silenciosamente. Quem precisa só do
                # subset Meta faz `df[df['campaign_id_meta'].notna()]` no consumidor.
                n_sem_meta = int(capi_norm['campaign_id_meta'].isna().sum())
                if n_sem_meta:
                    logger.info(f"    {n_sem_meta} leads sem campaign_id Meta (preservados — classificação Meta vai ignorar)")

                # Salvar CAPI no cache
                if use_cache:
                    try:
                        capi_norm.to_parquet(_capi_cache_file, index=False)
                        logger.info(f"    Cache SAVED CAPI: {_capi_cache_file.name}")
                    except Exception as ce:
                        logger.warning(f"    Não foi possível salvar cache CAPI: {ce}")
            else:
                capi_norm = None

            # Contar respostas de pesquisa apenas dentro da janela real de captação
            # (survey_df usa _s_extended de 60d para matching de compradores, mas
            # "Respostas na pesquisa" deve refletir só o período de captação _s→_e)
            if not survey_df_all.empty and 'data_captura' in survey_df_all.columns:
                survey_df_captacao = survey_df_all[
                    (survey_df_all['data_captura'] >= pd.to_datetime(_s)) &
                    (survey_df_all['data_captura'] <  pd.to_datetime(_e) + pd.Timedelta(days=1))
                ]
                survey_leads_count = len(survey_df_captacao)
            else:
                survey_leads_count = len(survey_df)

            if capi_norm is not None:
                capi_emails = set(capi_norm['email'].unique())
                capi_extras = capi_emails - survey_emails
                capi_extra_leads = capi_norm[capi_norm['email'].isin(capi_extras)].copy()
                logger.info(f"    Leads extras do CAPI: {len(capi_extra_leads)} (não estão na pesquisa)")

                if len(capi_extra_leads) > 0:
                    leads_df = pd.concat([survey_df, capi_extra_leads], ignore_index=True)
                    logger.info(f"    Total combinado: {len(leads_df)} ({len(survey_df)} pesquisa + {len(capi_extra_leads)} CAPI)")
                else:
                    leads_df = survey_df
                    logger.info(f"    Total: {len(leads_df)} (apenas pesquisa)")

                lead_source_stats = {
                    'survey_leads': survey_leads_count,
                    'capi_leads_extras': len(capi_extra_leads),
                    'capi_leads_total': len(capi_norm['email'].unique()),
                }
            else:
                logger.info("    Nenhum lead CAPI encontrado")
                leads_df = survey_df
                lead_source_stats = {'survey_leads': survey_leads_count, 'capi_leads_extras': 0, 'capi_leads_total': 0}

        logger.info(f"    Estatísticas: {lead_source_stats['survey_leads']} pesquisa + {lead_source_stats['capi_leads_extras']} CAPI extras")

        # --- Fonte primária opcional: xlsx de leads (auto-detecção por sobreposição de datas) ---
        # Quando encontrado, o xlsx define quais leads pertencem ao lançamento.
        # Sheets/Railway são usados apenas para enriquecimento (campaign_id_meta, lead_score, decil).
        capi_norm  = locals().get('capi_norm')   # pode não estar definido se survey_df estava vazio
        survey_df  = locals().get('survey_df', pd.DataFrame())
        xlsx_leads_folder = _V2_ROOT / 'outputs' / 'validation' / 'arquivos_leads'
        if not xlsx_leads_folder.exists():
            xlsx_leads_folder = _V2_ROOT / 'outputs' / 'validation'
        xlsx_candidates = sorted(xlsx_leads_folder.glob('* Leads.xlsx')) + \
                          sorted(xlsx_leads_folder.glob('*Leads.xlsx'))
        xlsx_candidates = list(dict.fromkeys(xlsx_candidates))  # dedup mantendo ordem

        if xlsx_candidates:
            logger.info(f"    Verificando {len(xlsx_candidates)} arquivo(s) xlsx de leads...")
            from src.validation.data_loader import normalizar_email, normalizar_telefone_robusto
            period_start = pd.to_datetime(_s)
            period_end   = pd.to_datetime(_e) + pd.Timedelta(days=1)

            # Selecionar o arquivo xlsx com maior sobreposição com o período de captação
            best_xlsx = None
            best_overlap_count = 0

            for xlsx_path in xlsx_candidates:
                try:
                    xlsx_df_dates = pd.read_excel(xlsx_path, sheet_name='LEADS', usecols=['DATA'])
                    dates = pd.to_datetime(xlsx_df_dates['DATA'], errors='coerce')
                    in_period = ((dates >= period_start) & (dates < period_end)).sum()
                    logger.info(f"    {xlsx_path.name}: {in_period} leads no período")
                    if in_period > best_overlap_count:
                        best_overlap_count = in_period
                        best_xlsx = xlsx_path
                except Exception as e:
                    logger.warning(f"    Erro ao verificar {xlsx_path.name}: {e}")

            # Limiar mínimo: xlsx só é fonte primária se tiver sobreposição expressiva.
            # Um overlap muito pequeno (ex.: 81 leads em um ficheiro do lançamento anterior)
            # indica leads residuais no limite de data, não o ficheiro correto do período.
            # Limiar = 500 leads ou 5% dos leads Railway, o que for maior.
            _min_xlsx_overlap = max(500, int(lead_source_stats.get('capi_leads_total', 0) * 0.05))
            if best_xlsx is not None and best_overlap_count >= _min_xlsx_overlap:
                logger.info(f"    Usando como fonte primária: {best_xlsx.name} ({best_overlap_count} leads no período)")
                try:
                    xlsx_df = pd.read_excel(best_xlsx, sheet_name='LEADS',
                                            usecols=lambda c: c in
                                            ['NOME','E-MAIL','TELEFONE','SOURCE','MEDIUM',
                                             'CAMPAIGN','TERM','CONTENT','DATA'])
                    dates_full = pd.to_datetime(xlsx_df['DATA'], errors='coerce')

                    xlsx_primary = pd.DataFrame()
                    xlsx_primary['email'] = xlsx_df['E-MAIL'].apply(
                        lambda x: normalizar_email(x) if pd.notna(x) else None)
                    xlsx_primary['nome']     = xlsx_df.get('NOME',    pd.Series(dtype=str))
                    xlsx_primary['telefone'] = xlsx_df['TELEFONE'].apply(
                        lambda x: normalizar_telefone_robusto(str(x)) if pd.notna(x) else None
                    ) if 'TELEFONE' in xlsx_df.columns else pd.Series(dtype=str)
                    xlsx_primary['data_captura'] = dates_full
                    xlsx_primary['campaign'] = xlsx_df.get('CAMPAIGN', pd.Series(dtype=str))
                    xlsx_primary['source']   = xlsx_df.get('SOURCE',   pd.Series(dtype=str))
                    xlsx_primary['medium']   = xlsx_df.get('MEDIUM',   pd.Series(dtype=str))
                    xlsx_primary['term']     = xlsx_df.get('TERM',     pd.Series(dtype=str))
                    xlsx_primary['content']  = xlsx_df.get('CONTENT',  pd.Series(dtype=str))
                    xlsx_primary['lead_score']  = np.nan
                    xlsx_primary['decile']      = None
                    xlsx_primary['campaign_id_meta'] = None
                    xlsx_primary['source_type'] = 'xlsx'

                    xlsx_primary = xlsx_primary[
                        xlsx_primary['email'].notna() &
                        (xlsx_primary['data_captura'] >= period_start) &
                        (xlsx_primary['data_captura'] <  period_end)
                    ].copy()
                    xlsx_primary = xlsx_primary.drop_duplicates(subset=['email']).copy()

                    # Enriquecer com Railway/Cloud SQL: campaign_id_meta, lead_score, decil
                    # ORDEM IMPORTA: survey_df primeiro (tem lead_score) → capi_norm depois (sem score).
                    # drop_duplicates(keep='first') preserva o score do survey quando o mesmo email
                    # aparece nas duas fontes. Inverter a ordem descartaria os scores.
                    enrichment_sources = []
                    if not survey_df.empty and 'email' in survey_df.columns:
                        survey_enrich = survey_df[['email'] + [c for c in ['campaign','lead_score','decile'] if c in survey_df.columns]].copy()
                        enrichment_sources.append(survey_enrich)
                    if capi_norm is not None and len(capi_norm) > 0:
                        enrichment_sources.append(capi_norm[['email','campaign','campaign_id_meta','lead_score','decile']].copy())

                    if enrichment_sources:
                        enrich_df = pd.concat(enrichment_sources, ignore_index=True)
                        enrich_df = enrich_df.drop_duplicates(subset=['email'], keep='first')
                        xlsx_primary = xlsx_primary.merge(
                            enrich_df.rename(columns={
                                'campaign': 'campaign_enrich',
                                'lead_score': 'lead_score_enrich',
                                'decile': 'decile_enrich',
                                'campaign_id_meta': 'campaign_id_meta_enrich',
                            }),
                            on='email', how='left'
                        )
                        # Preencher com valores do enriquecimento onde o xlsx não tem
                        if 'campaign_enrich' in xlsx_primary.columns:
                            mask_no_camp = xlsx_primary['campaign'].isna() | (xlsx_primary['campaign'] == '')
                            xlsx_primary.loc[mask_no_camp, 'campaign'] = xlsx_primary.loc[mask_no_camp, 'campaign_enrich']
                            xlsx_primary.drop(columns=['campaign_enrich'], inplace=True, errors='ignore')
                        if 'lead_score_enrich' in xlsx_primary.columns:
                            xlsx_primary['lead_score'] = xlsx_primary['lead_score_enrich']
                            xlsx_primary.drop(columns=['lead_score_enrich'], inplace=True, errors='ignore')
                        if 'decile_enrich' in xlsx_primary.columns:
                            xlsx_primary['decile'] = xlsx_primary['decile_enrich']
                            xlsx_primary.drop(columns=['decile_enrich'], inplace=True, errors='ignore')
                        if 'campaign_id_meta_enrich' in xlsx_primary.columns:
                            xlsx_primary['campaign_id_meta'] = xlsx_primary['campaign_id_meta_enrich']
                            xlsx_primary.drop(columns=['campaign_id_meta_enrich'], inplace=True, errors='ignore')

                    leads_df = xlsx_primary
                    lead_source_stats['xlsx_primary'] = len(xlsx_primary)
                    lead_source_stats['xlsx_enriched'] = int(xlsx_primary['campaign_id_meta'].notna().sum())
                    logger.info(f"    Fonte primária xlsx: {len(xlsx_primary)} leads únicos no período")
                    logger.info(f"    Enriquecidos com campaign_id_meta: {lead_source_stats['xlsx_enriched']}")

                except Exception as e:
                    logger.warning(f"    Erro ao usar xlsx como fonte primária ({best_xlsx.name}): {e} — mantendo Sheets/Railway")
                    lead_source_stats['xlsx_leads_extras'] = 0
            else:
                logger.info("    Nenhum xlsx com leads no período — mantendo Sheets/Railway como fonte")
                lead_source_stats['xlsx_leads_extras'] = 0
        else:
            lead_source_stats['xlsx_leads_extras'] = 0

        # Enriquecer leads_df com fbp/fbc do Railway para todos os leads
        if fbp_fbc_map:
            leads_df['fbp'] = leads_df['email'].map({k: v.get('fbp') for k, v in fbp_fbc_map.items()})
            leads_df['fbc'] = leads_df['email'].map({k: v.get('fbc') for k, v in fbp_fbc_map.items()})
        else:
            leads_df['fbp'] = None
            leads_df['fbc'] = None

    # Vendas
    sales_loader = SalesDataLoader()

    # Configuração de fonte de dados Guru: "local" (arquivos) ou "api" (Guru API)
    # Pode ser controlada via variável de ambiente GURU_DATA_SOURCE
    # PADRÃO: API (produção)
    guru_data_source = os.environ.get('GURU_DATA_SOURCE', 'api').lower()
    logger.info(f" Fonte de dados Guru: {guru_data_source.upper()}")

    # Determinar se deve incluir vendas canceladas baseado no tipo de relatório
    include_canceled = (args.report_type == 'fechamento')
    if include_canceled:
        logger.info(f"    Modo FECHAMENTO: incluindo vendas Aprovadas + Canceladas")
    else:
        logger.info(f"    Modo PÓS-DEVOLUÇÕES: incluindo apenas vendas Aprovadas")

    # Carregar vendas Guru (via API ou arquivos locais)
    if guru_data_source == 'api':
        # Determinar período de vendas para buscar via API
        if args.sales_start_date and args.sales_end_date:
            api_sales_start = args.sales_start_date
            api_sales_end = args.sales_end_date
        else:
            # Usar PeriodCalculator para calcular o período de vendas
            period_calc = PeriodCalculator()
            calculated_periods = period_calc.calculate_periods(start_date)
            api_sales_start = calculated_periods['sales']['start']
            api_sales_end = calculated_periods['sales']['end']

        logger.info(f"    Buscando via API: {api_sales_start} a {api_sales_end}")

        # Buscar via API (sem salvar Excel duplicado)
        guru_df = sales_loader.load_guru_sales_from_api(
            start_date=api_sales_start,
            end_date=api_sales_end,
            save_excel=False,
            include_canceled=include_canceled
        )
    else:
        # Modo local (arquivos Excel)
        # Buscar arquivos Guru com qualquer capitalização e formato: guru*, Guru*, GURU*
        guru_files = sorted(glob(f"{vendas_path}/[Gg][Uu][Rr][Uu]*.xlsx"))
        logger.info(f"   Arquivos Guru encontrados: {len(guru_files)}")

        guru_df = sales_loader.load_guru_sales(guru_files, include_canceled=include_canceled) if guru_files else None

    # Detectar arquivos TMB por estrutura de colunas
    # Hotmart agora é carregado via API; arquivos HotPay legados ainda são detectados como fallback
    all_vendas_files = sorted(glob(f"{vendas_path}/*.xlsx")) + sorted(glob(f"{vendas_path}/*.xls"))
    tmb_files = []
    hotpay_files = []
    for fpath in all_vendas_files:
        if any(x in Path(fpath).name.lower() for x in ['guru']):
            continue
        try:
            cols = pd.read_excel(fpath, nrows=0).columns.tolist()
            if 'Pedido' in cols and 'Parcela' in cols and 'Grau de risco' in cols:
                tmb_files.append(fpath)
                logger.info(f"   TMB detectado por colunas: {Path(fpath).name}")
            elif 'chave' in cols and 'Data de Confirmação' in cols and 'Código do Produto' in cols:
                hotpay_files.append(fpath)
                logger.info(f"   HotPay (arquivo legado) detectado: {Path(fpath).name}")
        except Exception:
            pass

    # Hotmart via API (usa sales_start_date / sales_end_date)
    hotmart_start = args.sales_start_date if args.sales_start_date else None
    hotmart_end   = args.sales_end_date   if args.sales_end_date   else None
    if hotmart_start and hotmart_end:
        logger.info(f"   Hotmart API: buscará vendas de {hotmart_start} a {hotmart_end}")
        # Se a API está ativa, ignorar arquivos HotPay para evitar double-counting
        if hotpay_files:
            logger.info(f"   Hotmart API ativa — ignorando {len(hotpay_files)} arquivo(s) HotPay (mesmos dados)")
            hotpay_files = []

    # Asaas via API — ativo se ASAAS_API_KEY estiver definida e período de vendas fornecido
    asaas_start = args.sales_start_date if args.sales_start_date else None
    asaas_end   = args.sales_end_date   if args.sales_end_date   else None
    asaas_key = os.environ.get('ASAAS_API_KEY', '')
    if asaas_key and asaas_start and asaas_end:
        logger.info(f"   Asaas API: buscará vendas de {asaas_start} a {asaas_end}")
    elif not asaas_key:
        logger.info("   Asaas API: ASAAS_API_KEY não definida — fonte ignorada")
        asaas_start = asaas_end = None

    if args.report_type == 'fechamento':
        logger.info(f"   Arquivos TMB encontrados: {len(tmb_files)} (incluirá Efetivado + Cancelado)")
    else:
        logger.info(f"   Arquivos TMB encontrados: {len(tmb_files)} (incluirá apenas Efetivado)")

    # Combinar vendas Guru + TMB + HotPay (legado) + Hotmart (API) + Asaas (API)
    # Blacklist de produtos (substring case-insensitive) — exclui upsells distintos do principal.
    # Default: "Mentoria" (Programa de Aceleração de Carreira — Mentoria para Devs).
    # Variantes do produto principal (Formação DevClub FullStack Pro, [Vitalício] Plano Dev,
    # DevClub FullStack Pro - OFICIAL, COMBOs etc.) passam todas — só dropamos o que é upsell
    # confirmadamente separado. Aplicado em canais com `product_name` (Guru/Hotmart);
    # Asaas/TMB passam direto (gateways de parcelamento sem nome).
    product_exclude = getattr(args, 'product_exclude', None) or ['Mentoria']

    sales_df = sales_loader.combine_sales(
        guru_df=guru_df,
        tmb_paths=tmb_files if tmb_files else None,
        hotpay_paths=hotpay_files if hotpay_files else None,
        hotmart_api_start=hotmart_start,
        hotmart_api_end=hotmart_end,
        asaas_api_start=asaas_start,
        asaas_api_end=asaas_end,
        asaas_product_value=config.get('ticket_contracted'),  # None = usar valor real da API Asaas
        asaas_customer_created_from=start_date,  # cap_start — conta para mais, evita perder compradores reais
        boletex_api_start=asaas_start,  # mesma janela de vendas
        boletex_api_end=asaas_end,
        report_type=args.report_type,
        include_canceled=include_canceled,
        product_exclude_substrings=product_exclude,
    )

    if sales_df.empty:
        logger.error(" Nenhuma venda carregada. Verifique os arquivos de vendas.")
        sys.exit(1)

    logger.info(f"    {len(sales_df)} vendas carregadas (Guru + TMB + HotPay + Hotmart + Asaas + Boletex)")
    print(flush=True)

    # 4. Filtrar por período
    # Período de vendas pode ser diferente do período de captação
    # Se não foram fornecidos, calcular usando a lógica documentada (3 semanas)
    if args.sales_start_date and args.sales_end_date:
        sales_start = args.sales_start_date
        sales_end = args.sales_end_date
        logger.info(f"    Usando período de vendas customizado: {sales_start} a {sales_end}")
    else:
        # Usar PeriodCalculator para calcular o período de vendas correto
        period_calc = PeriodCalculator()
        calculated_periods = period_calc.calculate_periods(start_date)
        sales_start = calculated_periods['sales']['start']
        sales_end = calculated_periods['sales']['end']
        logger.info(f"    Período de vendas calculado automaticamente: {sales_start} a {sales_end}")

    print(flush=True)
    print(f" FILTRANDO DADOS...", flush=True)
    print(f"   Período de Captação (Leads/Campanhas): {start_date} a {end_date}", flush=True)
    print(f"   Período de Vendas (Matching): {sales_start} a {sales_end}", flush=True)
    print(flush=True)

    # Armazenar estatísticas antes do filtro
    sales_before = len(sales_df)
    sales_guru_before = len(sales_df[sales_df['origem'] == 'guru']) if 'origem' in sales_df.columns else 0
    sales_tmb_before = len(sales_df[sales_df['origem'] == 'tmb']) if 'origem' in sales_df.columns else 0

    # Janela de leads: 60d antes do cap_start até vendas_end — pra incluir compradores
    # que se cadastraram em LFs anteriores OU durante a semana de vendas do próprio LF
    # (lista VIP, lead magnet, captação tardia, etc.). Sem essa extensão, perdíamos ~8
    # compradores reais por turno (8 de 44 no LF56).
    _leads_filter_start = (pd.to_datetime(start_date) - pd.Timedelta(days=60))
    _leads_filter_end = pd.to_datetime(sales_end) if sales_end else end_date
    leads_df = filter_by_period(leads_df, _leads_filter_start, _leads_filter_end, 'data_captura')
    sales_df = filter_by_period(sales_df, sales_start, sales_end, 'sale_date')

    # Mostrar estatísticas detalhadas após filtro de vendas
    sales_after = len(sales_df)
    sales_guru_after = len(sales_df[sales_df['origem'] == 'guru']) if 'origem' in sales_df.columns else 0
    sales_tmb_after = len(sales_df[sales_df['origem'] == 'tmb']) if 'origem' in sales_df.columns else 0

    logger.info(f" Vendas após filtro de período:")
    logger.info(f"   Total: {sales_before}  {sales_after} vendas ({sales_after/sales_before*100:.1f}%)")
    logger.info(f"   Guru: {sales_guru_before}  {sales_guru_after} vendas")
    logger.info(f"   TMB: {sales_tmb_before}  {sales_tmb_after} vendas")

    # =========================================================================
    # VALIDAÇÃO: Verificar se vendas TMB estão atualizadas
    # =========================================================================
    print(flush=True)
    print(" VALIDANDO ATUALIZAÇÃO DAS VENDAS TMB...", flush=True)
    print(flush=True)

    tmb_validation = validate_tmb_sales_freshness(sales_df, sales_start, sales_end)

    if tmb_validation['stop_execution']:
        # ERRO CRÍTICO: Sem vendas TMB no período
        logger.error(" Execução interrompida devido a vendas TMB faltantes")

        # Enviar notificação Slack de erro
        slack_webhook = os.getenv('SLACK_WEBHOOK_URL')
        if slack_webhook:
            try:
                import requests

                error_message = (
                    f" *ERRO CRÍTICO: Validação ML Interrompida*\n\n"
                    f"*Motivo:* Nenhuma venda TMB encontrada no período\n"
                    f"*Período analisado:* {sales_start} a {sales_end}\n\n"
                    f"*Ação necessária:*\n"
                    f"1. Baixar arquivo TMB atualizado\n"
                    f"2. Fazer novo deploy\n"
                )

                response = requests.post(slack_webhook, json={"text": error_message})
                if response.status_code == 200:
                    logger.info("    Notificação de erro enviada para Slack")
                else:
                    logger.warning(f"     Falha ao enviar Slack (status {response.status_code})")
            except Exception as e:
                logger.warning(f"     Erro ao enviar notificação Slack: {e}")

        sys.exit(1)

    elif tmb_validation['status'] == 'warning':
        # WARNING: Vendas TMB desatualizadas, mas continua
        # (já logou o warning dentro da função)
        pass

    print(flush=True)
    # =========================================================================

    if leads_df.empty:
        logger.error(" Nenhum lead no período especificado")
        sys.exit(1)

    # 4.5. Enriquecer IDs de campanha/adset com nomes reais
    # DESABILITADO: Usando MetaReportsLoader ao invés de API
    # print(" ENRIQUECENDO NOMES DE CAMPANHA...", flush=True)
    # print(flush=True)
    # leads_df = enrich_campaign_ids(leads_df, args.account_id, META_CONFIG['access_token'])

    # 5. Classificar campanhas
    print(" CLASSIFICANDO CAMPANHAS...", flush=True)
    print(flush=True)
    leads_df, excluded_count = add_ml_classification(leads_df, campaign_col='campaign')

    com_ml_count = len(leads_df[leads_df['ml_type'] == 'COM_ML'])
    sem_ml_count = len(leads_df[leads_df['ml_type'] == 'SEM_ML'])
    logger.info(f"    COM ML: {com_ml_count} leads ({com_ml_count/len(leads_df)*100:.1f}%)")
    logger.info(f"    SEM ML: {sem_ml_count} leads ({sem_ml_count/len(leads_df)*100:.1f}%)")
    print(flush=True)

    # 5.5. Carregar relatórios Meta para criar grupos de comparação refinados
    print(" CARREGANDO RELATÓRIOS META PARA CLASSIFICAÇÃO...", flush=True)
    print(flush=True)

    # Carregar relatórios Meta locais ou via API
    # IMPORTANTE: Usar pasta específica com relatórios oficiais do período (não adsets_analysis)
    # Configuração de fonte de dados: "local" (arquivos) ou "api" (Meta Marketing API)
    # PRIORIDADE: Se --account-id foi passado, FORÇA uso da API (ignora arquivos locais)
    if args.account_id:
        data_source = 'api'
        logger.info("    --account-id fornecido: FORÇANDO uso da Meta API")
    else:
        # Pode ser controlada via variável de ambiente META_DATA_SOURCE
        data_source = os.environ.get('META_DATA_SOURCE', 'local').lower()
    print(f" Fonte de dados Meta: {data_source.upper()}", flush=True)

    # DEBUG: Verificar args.account_id

    # Passar account_ids para o loader (necessário no modo API para buscar múltiplas contas)
    # Usar meta_reports_dir definido anteriormente (baseado na pasta do período)
    loader = MetaReportsLoader(meta_reports_dir, data_source=data_source, account_ids=args.account_id if data_source == 'api' else None, use_cache=use_cache)
    costs_hierarchy_temp = loader.build_costs_hierarchy(start_date, end_date)

    # Obter DataFrame de campanhas
    reports = loader.load_all_reports(start_date, end_date)
    campaigns_df = reports.get('campaigns', pd.DataFrame())

    # 5.6. Criar grupos de comparação REFINADOS (distingue Eventos ML vs Otimização ML)
    print(" CRIANDO GRUPOS DE COMPARAÇÃO...", flush=True)
    print(flush=True)

    comparison_group_map_15 = {}  # Mapa com IDs de 15 dígitos

    if 'ml_type' in leads_df.columns and not campaigns_df.empty:
        # Identificar campanhas Champion vs Challenger usando classificação correta
        from src.validation.campaign_classifier import classify_campaign

        # Classificar cada campanha
        campaigns_df['ml_classification'] = campaigns_df['campaign_name'].apply(classify_campaign)

        # Filtrar campanhas válidas (excluir as que não são de captação)
        campaigns_df_filtered = campaigns_df[campaigns_df['ml_classification'].isin(['COM_ML', 'SEM_ML'])]

        # Separar ML e Controle
        ml_campaigns = campaigns_df_filtered[campaigns_df_filtered['ml_classification'] == 'COM_ML']
        ml_campaign_ids = ml_campaigns['campaign_id'].unique().tolist()

        control_campaigns = campaigns_df_filtered[campaigns_df_filtered['ml_classification'] == 'SEM_ML']
        control_campaign_ids = control_campaigns['campaign_id'].unique().tolist()

        logger.info(f"    Classificação de campanhas:")
        logger.info(f"      COM_ML: {len(ml_campaign_ids)} campanhas")
        logger.info(f"      SEM_ML (Controle): {len(control_campaign_ids)} campanhas")
        logger.info(f"      EXCLUÍDAS: {len(campaigns_df) - len(campaigns_df_filtered)} campanhas")

        # =====================================================================
        # FILTRO UTM: remover leads de outros lançamentos que vazaram pela janela de datas
        # Usa IDs reais da Meta API (campaigns_df), que coincidem com os IDs no UTM do Railway.
        # Leads sem campaign_id (Sheets sem UTM numérico) são mantidos conservadoramente.
        # Ativar: filter_leads_by_campaign_id: true no validation_config.yaml
        # =====================================================================
        if config.get('filter_leads_by_campaign_id', False):
            # ml_campaign_ids e control_campaign_ids já são strings de 15 dígitos (campaigns_df[:15])
            # campaign_id_meta em leads_df também é 15 dígitos (extract_campaign_id_meta[:15])
            # → comparação direta, sem transformação adicional
            allowed_ids = set(str(i)[:15] for i in ml_campaign_ids + control_campaign_ids)

            if 'campaign_id_meta' not in leads_df.columns:
                def _extract_utm_id_15(camp):
                    if pd.isna(camp):
                        return None
                    m = re.search(r'\|\s*(\d{10,})\s*$', str(camp))
                    return m.group(1)[:15] if m else None
                leads_df['campaign_id_meta'] = leads_df['campaign'].apply(_extract_utm_id_15)

            before = len(leads_df)
            has_id = leads_df['campaign_id_meta'].notna()
            id_matches = leads_df['campaign_id_meta'].isin(allowed_ids)
            # Mantém: sem ID (Sheets sem UTM numérico) OU ID pertence ao lançamento atual
            leads_df = leads_df[~has_id | id_matches].copy()
            removed = before - len(leads_df)
            logger.info(f"   Filtro UTM (filter_leads_by_campaign_id=True):")
            logger.info(f"     IDs permitidos: {len(allowed_ids)} campanhas ({len(ml_campaign_ids)} ML + {len(control_campaign_ids)} Controle)")
            logger.info(f"     Leads com campaign_id identificável: {has_id.sum()}")
            logger.info(f"     Removidos (outro lançamento): {removed}")
            logger.info(f"     Restaram: {len(leads_df)}")

        if ml_campaign_ids and control_campaign_ids:
            # Usar função refinada que distingue Eventos ML vs Otimização ML
            from src.validation.fair_campaign_comparison import create_refined_campaign_map

            comparison_group_map_15 = create_refined_campaign_map(
                campaigns_df=campaigns_df,
                ml_campaign_ids=ml_campaign_ids,
                control_campaign_ids=control_campaign_ids
            )

            # Mapear leads para grupos refinados usando campaign_id (primeiros 15 dígitos)
            def map_to_refined_group(row):
                # Tentar obter campaign_id de várias fontes
                campaign_id = None

                # Fonte 1: campaign_id_meta (leads CAPI)
                if pd.notna(row.get('campaign_id_meta')):
                    campaign_id = str(row['campaign_id_meta'])

                # Fonte 2: Extrair do nome da campanha (formato: "nome|ID")
                elif pd.notna(row.get('campaign')):
                    campaign_str = str(row['campaign'])
                    # Procurar por ID de 18 dígitos após o último "|"
                    if '|' in campaign_str:
                        parts = campaign_str.split('|')
                        last_part = parts[-1].strip()
                        # Verificar se é um ID numérico de 18 dígitos
                        if last_part.isdigit() and len(last_part) == 18:
                            campaign_id = last_part

                # Se conseguimos um campaign_id, mapear usando os primeiros 15 dígitos
                if campaign_id:
                    cid_15 = campaign_id[:15]
                    grupo = comparison_group_map_15.get(cid_15)
                    if grupo:
                        return grupo

                # Fallback para ml_type
                # SEM_ML = Controle puro (DEVLF sem sufixo ML)
                # COM_ML = ML genérico (preferimos identificar Champion ML vs Challenger ML via map acima;
                # fallback aqui ocorre quando não conseguimos o campaign_id pra olhar no map)
                if row.get('ml_type') == 'SEM_ML':
                    return 'Controle'
                elif row.get('ml_type') == 'COM_ML':
                    return 'Champion'  # Default — sem ID não dá pra distinguir Champion vs Challenger ML
                else:
                    return 'Outro'

            leads_df['comparison_group'] = leads_df.apply(map_to_refined_group, axis=1)

            group_counts = leads_df['comparison_group'].value_counts()
            logger.info(f"    Grupos refinados criados:")
            for group, count in group_counts.items():
                logger.info(f"      {group}: {count} leads")
        else:
            # Fallback: usar mapeamento simples
            # SEM_ML = Controle puro; COM_ML = ML genérico (sem distinção Champion vs Challenger por falta de map)
            logger.warning("    Não foi possível criar mapeamento refinado, usando simples")
            leads_df['comparison_group'] = leads_df['ml_type'].map({
                'COM_ML': 'Champion',
                'SEM_ML': 'Controle'
            }).fillna('Outro')
    else:
        logger.warning("    Coluna ml_type não encontrada, pulando criação de grupos")

    print(flush=True)

    # 6. Matching
    print(" VINCULANDO LEADS COM VENDAS...", flush=True)
    print(flush=True)

    # Usar método de matching selecionado
    if args.matching_method == 'unified_last6':
        logger.info("    Usando método: EMAIL + TELEFONE + ÚLTIMOS 6 DÍGITOS")
        from src.core.matching import match_leads_to_sales_unified
        matched_df = match_leads_to_sales_unified(
            leads_df,
            sales_df,
            mode='validation',
            use_temporal_validation=False  # Results analysis mode - match against full history
        )
    else:
        logger.info("    Usando método padrão: EMAIL + TELEFONE COMPLETO")
        matched_df = match_leads_to_sales(
            leads_df,
            sales_df,
            use_temporal_validation=False  # Results analysis mode - match against full history
        )

    # INVESTIGAÇÃO: Onde estão as vendas que não fizeram match?
    print(" INVESTIGAÇÃO: ANÁLISE DAS VENDAS SEM MATCH")

    conversions = matched_df[matched_df['converted'] == True]
    num_conversions = len(conversions)
    num_sales = len(sales_df)

    logger.info(f" Vendas totais no período: {num_sales}")
    logger.info(f" Vendas com match nos leads classificados: {num_conversions}")
    logger.info(f" Vendas SEM match: {num_sales - num_conversions}")

    if num_sales > num_conversions:
        # Buscar vendas que não fizeram match nos leads classificados
        sales_emails = set(sales_df['email'].str.lower().str.strip())
        matched_emails = set(conversions['email'].str.lower().str.strip()) if num_conversions > 0 else set()
        unmatched_sales_emails = sales_emails - matched_emails

        logger.info(f"\n Investigando {len(unmatched_sales_emails)} vendas sem match...")

        # Carregar dataset COMPLETO de leads do Google Sheets (SEM filtro de período para ver histórico)
        temp_loader = LeadDataLoader()

        # Reusar survey_df_all já carregado no início (evita chamadas repetidas ao Sheets)
        try:
            period_leads_df = survey_df_all[
                (survey_df_all['data_captura'] >= pd.to_datetime(_s)) &
                (survey_df_all['data_captura'] <  pd.to_datetime(_e) + pd.Timedelta(days=1))
            ].copy() if not survey_df_all.empty and 'data_captura' in survey_df_all.columns else survey_df_all
        except Exception:
            period_leads_df = pd.DataFrame()

        historical_leads_df = survey_df_all

        logger.info(f"   Dataset do período: {len(period_leads_df)} leads")
        logger.info(f"   Dataset histórico: {len(historical_leads_df)} leads")
        logger.info(f"   Dataset classificado: {len(leads_df)} leads (apenas com UTM válida)")

        # Verificar cada venda não matched
        print("\n" + "-"*80)
        print(f"{'EMAIL':<35} {'DATA CADASTRO':<20} {'GRUPO':<15} {'CAMPANHA'[:30]}")
        print("-"*80)

        found_in_excluded = 0
        found_before_period = 0
        not_found = 0

        for sale_email in list(unmatched_sales_emails)[:20]:  # Limitar a 20 para não poluir
            # Buscar primeiro no dataset do período
            if period_leads_df.empty or 'email' not in period_leads_df.columns:
                lead_match = period_leads_df  # vazio — vai cair em "not found"
            else:
                lead_match = period_leads_df[period_leads_df['email'].str.lower().str.strip() == sale_email]

            if len(lead_match) > 0:
                # Encontrado NO PERÍODO
                lead_row = lead_match.iloc[0]
                data_cadastro = lead_row.get('data_captura', 'N/A')
                campaign = str(lead_row.get('campaign', 'N/A'))[:30]
                source = lead_row.get('source', 'N/A')

                # Verificar se está nos leads classificados
                in_classified = lead_row['email'] in leads_df['email'].values

                if in_classified:
                    grupo = "CLASSIFICADO"  # Estranho - deveria ter matched
                else:
                    # Está nos excluídos
                    if pd.isna(source) or source != 'facebook-ads':
                        grupo = "EXCLUIR (sem UTM)"
                        found_in_excluded += 1
                    else:
                        grupo = "EXCLUIR (outro)"
                        found_in_excluded += 1

                # Formatar data
                if pd.notna(data_cadastro):
                    if isinstance(data_cadastro, str):
                        data_str = data_cadastro[:16]  # Pegar apenas data e hora
                    else:
                        data_str = data_cadastro.strftime('%Y-%m-%d %H:%M')
                else:
                    data_str = 'N/A'

                email_display = sale_email[:32] + "..." if len(sale_email) > 32 else sale_email
                print(f"{email_display:<35} {data_str:<20} {grupo:<15} {campaign}")
            else:
                # Não encontrado no período - buscar no histórico
                if historical_leads_df.empty or 'email' not in historical_leads_df.columns:
                    historical_match = historical_leads_df
                else:
                    historical_match = historical_leads_df[historical_leads_df['email'].str.lower().str.strip() == sale_email]

                if len(historical_match) > 0:
                    # Encontrado no HISTÓRICO (período anterior)
                    hist_row = historical_match.iloc[0]
                    data_cadastro = hist_row.get('data_captura', 'N/A')
                    campaign = str(hist_row.get('campaign', 'N/A'))[:30]

                    # Formatar data
                    if pd.notna(data_cadastro):
                        if isinstance(data_cadastro, str):
                            data_str = data_cadastro[:10]  # Apenas data
                        else:
                            data_str = data_cadastro.strftime('%Y-%m-%d')
                    else:
                        data_str = 'N/A'

                    email_display = sale_email[:32] + "..." if len(sale_email) > 32 else sale_email
                    print(f"{email_display:<35} {data_str:<20} {'PERÍODO ANTERIOR':<15} {campaign}")
                    found_before_period += 1
                else:
                    # Não encontrado nem no histórico
                    email_display = sale_email[:32] + "..." if len(sale_email) > 32 else sale_email
                    print(f"{email_display:<35} {'NÃO ENCONTRADO':<20} {'???':<15} {'N/A'}")
                    not_found += 1

        print("-"*80)
        logger.info(f"\n RESUMO DA INVESTIGAÇÃO:")
        logger.info(f"   Vendas nos leads EXCLUÍDOS (sem UTM): {found_in_excluded}")
        logger.info(f"   Vendas de PERÍODO ANTERIOR: {found_before_period}")
        logger.info(f"   Vendas NÃO ENCONTRADAS: {not_found}")


    # 6.1. Filtrar conversões por período de captura
    print(" FILTRANDO CONVERSÕES POR PERÍODO DE CAPTURA...", flush=True)
    print(flush=True)
    from src.validation.matching import filter_conversions_by_capture_period
    # Janela igual ao filter_by_period de leads acima: 60d antes do cap_start até sales_end,
    # pra preservar compradores capturados em LFs anteriores ou durante a semana de vendas.
    _conv_filter_start = (pd.to_datetime(start_date) - pd.Timedelta(days=60))
    _conv_filter_end = pd.to_datetime(sales_end) if sales_end else end_date
    matched_df = filter_conversions_by_capture_period(
        matched_df,
        period_start=_conv_filter_start,
        period_end=_conv_filter_end,
    )

    # 6.2. Remover duplicatas artificiais
    print(" REMOVENDO DUPLICATAS ARTIFICIAIS...", flush=True)
    print(flush=True)
    from src.validation.matching import deduplicate_conversions
    matched_df = deduplicate_conversions(matched_df)

    matching_stats = get_matching_stats(matched_df, total_sales=len(sales_df))

    logger.info(f"    Conversões: {matching_stats['total_conversions']}")
    logger.info(f"    Taxa de conversão geral: {matching_stats['conversion_rate']:.2f}%")
    logger.info(f"    Match por email: {matching_stats['matched_by_email']}")
    logger.info(f"    Match por telefone: {matching_stats['matched_by_phone']}")
    print(flush=True)

    # Split A/B Champion vs Challenger — só aplica em leads vindos do `registros_ml`
    # (têm `variant` + `base_status`). Leads pré-17/05 (tabela Lead antiga) ficam
    # em 'fora_do_ab' por construção. Critério acordado:
    #   champion   = variant IS NULL AND base_status='success' AND lead_score NOT NULL
    #   challenger = variant='challenger_abr28' AND base_status='success' AND lead_score NOT NULL
    if 'variant' in matched_df.columns or 'base_status' in matched_df.columns:
        def _ab_model(r):
            ls = r.get('lead_score')
            if pd.isna(ls): return 'fora_do_ab'
            bs = r.get('base_status')
            if bs != 'success': return 'fora_do_ab'
            v = r.get('variant')
            if v == 'challenger_abr28': return 'challenger'
            if pd.isna(v) or v is None: return 'champion'
            return 'fora_do_ab'

        matched_df['ab_model'] = matched_df.apply(_ab_model, axis=1)
        ab_counts = matched_df['ab_model'].value_counts().to_dict()
        print(" SPLIT A/B — Champion vs Challenger (origem: registros_ml.variant)", flush=True)
        print(f"   Distribuição: {ab_counts}", flush=True)
        print(flush=True)

        for modelo in ['champion', 'challenger']:
            sub = matched_df[matched_df['ab_model'] == modelo]
            if sub.empty:
                print(f"   {modelo}: 0 leads — pulado", flush=True)
                continue
            conv = sub[sub['converted'] == True]
            rev_col = 'sale_value_realizado' if 'sale_value_realizado' in conv.columns else 'sale_value'
            rev = conv[rev_col].sum() if not conv.empty else 0
            print(f"   {modelo:10}: {len(sub):>6,} leads | {len(conv):>3} vendas | "
                  f"taxa {len(conv)/len(sub)*100:>5.2f}% | receita R${rev:>9,.0f}", flush=True)
            if 'decile' in sub.columns and not sub['decile'].dropna().empty:
                for d in ['D10', 'D09', 'D08']:
                    sd = sub[sub['decile'] == d]
                    if sd.empty: continue
                    sd_conv = sd[sd['converted'] == True]
                    sd_rev = sd_conv[rev_col].sum() if not sd_conv.empty else 0
                    print(f"     {d}: {len(sd):>5,} leads | {len(sd_conv):>3} vendas | "
                          f"taxa {len(sd_conv)/max(len(sd),1)*100:>5.2f}% | receita R${sd_rev:>8,.0f}", flush=True)

        # Persistir os 2 sub-dataframes pra inspeção/análise futura (ROAS por decil etc.)
        try:
            from pathlib import Path as _P
            _split_dir = _P(output_dir)
            _split_dir.mkdir(parents=True, exist_ok=True)
            for modelo in ['champion', 'challenger', 'fora_do_ab']:
                _sub = matched_df[matched_df['ab_model'] == modelo]
                if not _sub.empty:
                    _sub.to_parquet(_split_dir / f"matched_{modelo}.parquet", index=False)
            print(f"   Parquets salvos em {output_dir}/matched_{{champion,challenger,fora_do_ab}}.parquet", flush=True)
        except Exception as _e:
            logger.warning(f"   Aviso: não foi possível salvar parquets do split A/B: {_e}")
        print(flush=True)

    # 7. Reutilizar custos dos relatórios Meta já carregados
    print(" REUTILIZANDO CUSTOS DOS RELATÓRIOS META...", flush=True)
    print(flush=True)

    meta_api = None  # Não usar API, apenas relatórios locais
    costs_hierarchy_consolidated = costs_hierarchy_temp  # Reutilizar dados já carregados

    num_campaigns = len(costs_hierarchy_consolidated.get('campaigns', {}))
    if num_campaigns > 0:
        logger.info(f"    {num_campaigns} campanhas reutilizadas dos relatórios")
    else:
        logger.warning("    Nenhuma campanha encontrada nos relatórios")

    print(flush=True)

    # 8. Calcular métricas
    print(" CALCULANDO MÉTRICAS...", flush=True)
    print(flush=True)

    # Por campanha
    use_cache = not args.no_cache  # Usar cache por padrão, desabilitar se --no-cache
    campaign_calc = CampaignMetricsCalculator(
        meta_api if meta_api else None,
        config['product_value'],
        use_cache=use_cache
    )

    if not use_cache:
        logger.info("    Cache desabilitado - forçando busca de dados novos da Meta API")

    # Usar TODAS as contas para buscar leads (não apenas a primeira)
    all_account_ids = ','.join(args.account_id) if isinstance(args.account_id, list) else args.account_id

    campaign_metrics = campaign_calc.calculate_campaign_metrics(
        matched_df,
        all_account_ids,
        start_date,
        end_date,
        global_tracking_rate=matching_stats.get('tracking_rate', 100.0),
        costs_hierarchy_consolidated=costs_hierarchy_consolidated
    )
    logger.info(f"    Métricas calculadas para {len(campaign_metrics)} campanhas")

    # FILTRAR CAMPANHAS EXCLUÍDAS (se configurado)
    if EXCLUDE_CAMPAIGN_IDS and len(campaign_metrics) > 0:
        import re
        def extract_campaign_id_15(campaign_name):
            """Extrai primeiros 15 dígitos do campaign_id do nome"""
            if pd.isna(campaign_name):
                return None
            match = re.search(r'1\d{14,}', str(campaign_name))
            if match:
                return match.group(0)[:15]
            return None

        # Extrair IDs das campanhas
        campaign_metrics['_temp_id'] = campaign_metrics['campaign'].apply(extract_campaign_id_15)

        # Identificar campanhas excluídas
        excluded_mask = campaign_metrics['_temp_id'].isin(EXCLUDE_CAMPAIGN_IDS)
        excluded_campaigns = campaign_metrics[excluded_mask]

        if len(excluded_campaigns) > 0:
            logger.info(f"    Excluindo {len(excluded_campaigns)} campanha(s) de teste da análise:")
            for idx, row in excluded_campaigns.iterrows():
                logger.info(f"       {row['campaign'][:70]}...")
                logger.info(f"        Gasto: R$ {row['spend']:,.2f} | Leads: {int(row['leads'])} | Conversões: {int(row['conversions'])}")

            # Filtrar campanhas
            campaign_metrics = campaign_metrics[~excluded_mask].copy()
            logger.info(f"    {len(campaign_metrics)} campanhas restantes após exclusão")

        # Cleanup: remover coluna temporária
        campaign_metrics = campaign_metrics.drop(columns=['_temp_id'])

    # Adicionar comparison_group ao campaign_metrics (se disponível)
    if 'comparison_group' in matched_df.columns and len(campaign_metrics) > 0:
        # IMPORTANTE: Fazer mapeamento por campaign_id (15 dígitos), não por nome
        # Motivo: Nomes de campanhas podem ter sido atualizados (UTMs  Meta API)

        # Extrair campaign_id (15 dígitos) do matched_df
        import re
        def extract_campaign_id_15(campaign_name):
            """Extrai primeiros 15 dígitos do campaign_id do nome"""
            if pd.isna(campaign_name):
                return None
            match = re.search(r'1\d{14,}', str(campaign_name))
            if match:
                return match.group(0)[:15]  # Primeiros 15 dígitos
            return None

        matched_df['campaign_id_15'] = matched_df['campaign'].apply(extract_campaign_id_15)
        campaign_metrics['campaign_id_15'] = campaign_metrics['campaign'].apply(extract_campaign_id_15)

        # Criar mapeamento campaign_id_15  comparison_group
        campaign_id_to_group = matched_df[matched_df['campaign_id_15'].notna()].groupby('campaign_id_15')['comparison_group'].first().to_dict()

        # Mapear usando campaign_id_15
        campaign_metrics['comparison_group'] = campaign_metrics['campaign_id_15'].map(campaign_id_to_group)

        # Cleanup: remover coluna temporária
        campaign_metrics = campaign_metrics.drop(columns=['campaign_id_15'])

        # === OVERRIDE LEADS COM EMAILS ÚNICOS DA TABELA UTMTracking (Railway) ===
        # O Meta reporta o campo "leads_standard" contando TODOS os eventos do pixel
        # (`Lead` + `LeadQualified` + `LeadHighQuality` etc), então uma única pessoa
        # que preencheu a pesquisa aparece como 2 ou 3 "leads" na contagem do Meta.
        # Resultado prático: CPL e Taxa de Conversão saem ~metade do valor real.
        # Fonte certa = UTMTracking (1 linha = 1 (email, UTM) único), que tem 97,6%
        # de cobertura dos leads da pesquisa no LF56.
        # Aqui rescalamos `leads` proporcionalmente por comparison_group para que o
        # total por grupo bata com o emails únicos no Railway, preservando o peso
        # relativo de cada campanha dentro do grupo.
        try:
            import ssl as _ssl
            import pg8000.native as _pg
            from collections import defaultdict
            _ssl_ctx = _ssl.create_default_context()
            _ssl_ctx.check_hostname = False
            _ssl_ctx.verify_mode = _ssl.CERT_NONE
            _conn = _pg.Connection(
                host=os.environ['RAILWAY_DB_HOST'], port=int(os.environ['RAILWAY_DB_PORT']),
                user=os.environ['RAILWAY_DB_USER'], password=os.environ['RAILWAY_DB_PASSWORD'],
                database=os.environ['RAILWAY_DB_NAME'], ssl_context=_ssl_ctx,
            )
            _rows = _conn.run(
                """SELECT LOWER("clientEmail") AS email, campaign
                   FROM "UTMTracking"
                   WHERE "trackedAt"::date BETWEEN :s AND :e""",
                s=start_date, e=end_date,
            )
            _conn.close()
            _utm_df = pd.DataFrame(_rows, columns=['email', 'utm_campaign']).drop_duplicates('email')

            # Classifica cada email pela mesma lógica de comparison_group
            def _classify_utm(name):
                if not isinstance(name, str):
                    return 'Outro'
                up = name.upper()
                if 'LEADHQLB' in up or 'HQLB' in up:
                    return 'Challenger'
                if 'LEADQUALIFIED' in up or 'MACHINE LEARNING' in up or '| ML |' in up:
                    return 'Champion'
                if 'DEVLF' in up and 'PG1' in up:
                    return 'Controle'
                return 'Outro'
            _utm_df['_group'] = _utm_df['utm_campaign'].apply(_classify_utm)
            _target_per_group = _utm_df['_group'].value_counts().to_dict()
            logger.info(f"    Leads únicos (UTMTracking) por grupo: {_target_per_group}")

            # Rescala leads por grupo no campaign_metrics
            for _grp, _target in _target_per_group.items():
                _mask = campaign_metrics['comparison_group'] == _grp
                _current_sum = float(campaign_metrics.loc[_mask, 'leads'].sum())
                if _current_sum > 0 and _target > 0:
                    _scale = _target / _current_sum
                    campaign_metrics.loc[_mask, 'leads'] = (
                        campaign_metrics.loc[_mask, 'leads'].astype(float) * _scale
                    )
                    logger.info(
                        f"      {_grp}: {int(_current_sum)} leads Meta → {_target} emails únicos "
                        f"(scale ×{_scale:.3f})"
                    )
        except Exception as _e:
            logger.warning(f"    Não foi possível sobrescrever leads via UTMTracking: {_e}")
            logger.warning(f"    CPL e Taxa de Conversão vão usar leads do Meta (inflado ~2×)")

        # Log de sucesso/falha
        mapped_count = campaign_metrics['comparison_group'].notna().sum()
        total_count = len(campaign_metrics)
        logger.info(f"    Grupos de comparação adicionados: {mapped_count}/{total_count} campanhas mapeadas")

        if mapped_count < total_count:
            unmapped = campaign_metrics[campaign_metrics['comparison_group'].isna()]['campaign'].tolist()
            logger.warning(f"    {total_count - mapped_count} campanhas SEM comparison_group:")
            for camp in unmapped[:5]:  # Mostrar até 5
                camp_str = camp if isinstance(camp, str) else '(sem nome)'
                logger.warning(f"       {camp_str[:70]}")
    elif len(campaign_metrics) == 0:
        logger.warning("    Nenhuma métrica de campanha disponível - DataFrame vazio")

    # Por decil
    decile_calc = DecileMetricsCalculator()
    decile_metrics = decile_calc.calculate_decile_performance(
        matched_df,
        config['product_value']
    )
    logger.info(f"    Performance calculada para todos os decis (D1-D10)")

    # ML Model Performance Monitoring
    print(flush=True)
    print(" CALCULANDO MÉTRICAS DE MONITORAMENTO DO MODELO...", flush=True)
    print(flush=True)

    # Carregar modelo ativo do active_model.yaml
    active_model_path = get_active_model_path()
    # Suporta tanto o nome legado (files/) quanto o nome MLflow (model_metadata.json)
    _legacy = active_model_path / "model_metadata_v1_devclub_rf_temporal_leads_single.json"
    _mlflow = active_model_path / "model_metadata.json"
    model_metadata_path = str(_legacy if _legacy.exists() else _mlflow)

    ml_monitoring_calc = MLMonitoringCalculator(
        model_metadata_path=model_metadata_path
    )

    ml_monitoring_metrics = ml_monitoring_calc.calculate_all_metrics(
        matched_df=matched_df
    )

    # Log resumo no console
    logger.info(f" AUC Produção: {ml_monitoring_metrics['auc']['production']:.4f} "
               f"(Test Set: {ml_monitoring_metrics['auc']['test_set']:.4f})")
    logger.info(f" Top 3 Decis: {ml_monitoring_metrics['concentration']['top3_production']:.1f}% "
               f"(Test Set: {ml_monitoring_metrics['concentration']['top3_test_set']:.1f}%)")
    print(flush=True)

    # Análise temporal de degradação do AUC (correlação com vendas TMB)
    # Chamado DEPOIS de calculate_all_metrics e com cópias dos DataFrames para isolamento total
    temporal_auc_snapshots = ml_monitoring_calc.calculate_temporal_auc_snapshots(
        matched_df=matched_df.copy(deep=True),
        sales_df=sales_df.copy(deep=True),
        start_date=sales_start,
        end_date=sales_end
    )

    # Adicionar ao dict de métricas sem modificar estrutura existente
    ml_monitoring_metrics['temporal_auc_snapshots'] = temporal_auc_snapshots
    print(flush=True)

    # Comparação ML
    ml_comparison = compare_ml_vs_non_ml(campaign_metrics) if len(campaign_metrics) > 0 else None

    # Estatísticas gerais (usando TODAS as vendas do período, não apenas matched)
    overall_stats = calculate_overall_stats(
        matched_df,
        campaign_metrics,
        lead_period=(start_date, end_date),
        sales_period=(sales_start, sales_end),
        sales_df=sales_df,  # Todas as vendas do período
        product_value=config['product_value'],
        excluded_leads=excluded_count,
        campaign_calc=campaign_calc,  # Para acessar total_leads_meta_before_filter
        lead_source_stats=lead_source_stats  # Estatísticas de pesquisa vs CAPI
    )

    # Comparação por grupo
    comparison_group_metrics = None
    if 'comparison_group' in matched_df.columns and len(campaign_metrics) > 0:
        comparison_group_metrics = calculate_comparison_group_metrics(matched_df, campaign_metrics)
        logger.info(f"    Métricas calculadas por grupo de comparação")

    # Fair comparison info (legacy - não usado mais)
    fair_comparison_info = None

    # 8.5. COMPARAÇÕES DE ADSETS E ADS (usando relatórios locais)
    all_adsets_comparison = None
    adset_level_comparisons = None
    ad_level_comparisons = None
    ad_in_matched_adsets_comparisons = None
    matched_ads_in_matched_adsets_comparisons = None
    matched_adsets_faixa_a = None
    faixa_a_instances_detail = None

    if not args.disable_fair_comparison and len(campaign_metrics) > 0:
        try:
            from src.validation.fair_campaign_comparison import (
                compare_all_adsets_performance,
                identify_matched_adset_pairs,
                compare_adset_performance,
                compare_ads_in_matched_adsets,
                compare_matched_ads_in_matched_adsets,
                identify_matched_adsets_faixa_a,
                get_faixa_a_instances_detail
            )

            print("\n COMPARAÇÃO DE ADSETS E ADS (relatórios locais)...", flush=True)
            print(flush=True)

            # Carregar adsets e ads dos relatórios Meta locais
            reports = loader.load_all_reports(start_date, end_date)
            adsets_df = reports.get('adsets', pd.DataFrame())
            ads_df = reports.get('ads', pd.DataFrame())

            if not adsets_df.empty:
                logger.info(f"    {len(adsets_df)} adsets carregados dos relatórios")

                # DEBUG: Verificar se total_spend existe
                if 'total_spend' in adsets_df.columns:
                    total_spend_sum = adsets_df['total_spend'].sum()
                    spend_sum = adsets_df['spend'].sum()
                    logger.info(f"    DEBUG: total_spend existe em adsets_df")
                    logger.info(f"      Total spend (histórico): R$ {total_spend_sum:,.2f}")
                    logger.info(f"      Total spend (filtrado): R$ {spend_sum:,.2f}")
                else:
                    logger.warning(f"    DEBUG: total_spend NÃO existe em adsets_df")

                # Extrair campaign IDs do matched_df
                def extract_campaign_id(campaign_name):
                    if pd.isna(campaign_name) or not isinstance(campaign_name, str):
                        return None
                    parts = campaign_name.split('|')
                    if len(parts) >= 2:
                        campaign_id = parts[-1].strip()
                        # Validar que é numérico e tem tamanho de ID da Meta
                        if campaign_id.isdigit() and len(campaign_id) >= 15:
                            return campaign_id
                    return None

                matched_df['campaign_id'] = matched_df['campaign'].apply(extract_campaign_id)

                # Reutilizar comparison_group_map criado anteriormente
                comparison_group_map = comparison_group_map_15  # Já criado na seção 5.6

                # Extrair IDs de campanhas por grupo (Eventos ML, Otimização ML, Controle)
                eventos_ml_campaign_ids = []
                otimizacao_ml_campaign_ids = []
                control_campaign_ids = []

                if comparison_group_map:
                    for cid_15, group in comparison_group_map.items():
                        # Buscar o ID completo (18 dígitos) nos relatórios
                        matching_campaigns = campaigns_df[campaigns_df['campaign_id'].astype(str).str.startswith(cid_15)]
                        if not matching_campaigns.empty:
                            full_id = matching_campaigns.iloc[0]['campaign_id']
                            if group == 'Champion':
                                eventos_ml_campaign_ids.append(full_id)
                            elif group == 'Otimização ML':
                                otimizacao_ml_campaign_ids.append(full_id)
                            elif group == 'Challenger':
                                control_campaign_ids.append(full_id)

                    logger.info(f"    Campanhas por grupo:")
                    logger.info(f"      Eventos ML: {len(eventos_ml_campaign_ids)}")
                    logger.info(f"      Otimização ML: {len(otimizacao_ml_campaign_ids)}")
                    logger.info(f"      Controle: {len(control_campaign_ids)}")

                    # Criar ml_type_map para compatibilidade (COM_ML para Eventos e Otimização)
                    ml_type_map = {}
                    for cid_15, group in comparison_group_map.items():
                        if group in ['Champion', 'Otimização ML']:
                            ml_type_map[cid_15] = 'COM_ML'
                        elif group == 'Challenger':
                            ml_type_map[cid_15] = 'SEM_ML'
                else:
                    ml_type_map = {}
                    logger.warning("    comparison_group_map vazio, não será possível fazer comparação")

                # 1. Comparação de TODOS os adsets (Eventos Champion vs Challenger)
                all_adsets_comparison = compare_all_adsets_performance(
                    adsets_df=adsets_df,
                    matched_df=matched_df,
                    comparison_group_map=comparison_group_map,
                    product_value=config['product_value'],
                    min_spend=0.0,
                    config=config
                )
                logger.info(f"    Comparação de todos adsets concluída")

                # 2. Identificar matched adset pairs (Eventos Champion vs Challenger apenas)
                # IMPORTANTE: Usar apenas eventos_ml_campaign_ids (excluir Otimização ML)
                matched_adsets, matched_adsets_df = identify_matched_adset_pairs(
                    adsets_df=adsets_df,
                    ml_campaign_ids=eventos_ml_campaign_ids,  # Apenas Eventos ML!
                    control_campaign_ids=control_campaign_ids,
                    min_spend=0.0,
                    use_dynamic_matching=True  # Usar detecção dinâmica em vez de lista hardcoded
                )

                if matched_adsets:
                    logger.info(f"    {len(matched_adsets)} adsets matched identificados (Eventos Champion vs Challenger)")

                    # IMPORTANTE: Usar matched_adsets_df retornado por identify_matched_adset_pairs
                    # Este DataFrame já tem a coluna 'leads' criada a partir de 'leads_standard'
                    logger.info(f"      Total de adsets: {len(matched_adsets_df)}")
                    logger.info(f"      Tem 'leads'? {'leads' in matched_adsets_df.columns}")
                    if 'leads' in matched_adsets_df.columns:
                        logger.info(f"      Total de leads: {matched_adsets_df['leads'].sum():.0f}")

                    if not matched_adsets_df.empty:
                        adset_level_comparisons = compare_adset_performance(
                            adsets_metrics_df=matched_adsets_df,  # Usar DF com 'leads' já criado!
                            matched_df=matched_df,
                            ml_type_map=ml_type_map,
                            product_value=config['product_value'],
                            comparison_group_map=comparison_group_map
                        )
                        logger.info(f"    Comparação de matched adsets concluída ({len(matched_adsets_df)} adsets)")
                    else:
                        logger.warning("    Nenhum adset matched encontrado após filtragem")
                        adset_level_comparisons = None
                else:
                    logger.warning("    Nenhum matched adset identificado")
                    adset_level_comparisons = None

                # 3. Identificar matched adsets Faixa A (Eventos ML vs Faixa A)
                try:
                    matched_adsets_faixa_a_list, matched_adsets_faixa_a = identify_matched_adsets_faixa_a(
                        adsets_df=adsets_df,
                        campaign_metrics=campaign_metrics,
                        eventos_ml_campaign_ids=eventos_ml_campaign_ids,
                        matched_df=matched_df
                    )
                    if matched_adsets_faixa_a_list:
                        logger.info(f"    {len(matched_adsets_faixa_a_list)} adsets matched identificados (Eventos ML vs Faixa A)")
                    else:
                        logger.info("   ℹ Nenhum adset matched encontrado entre Eventos ML e Faixa A")
                except Exception as e:
                    logger.warning(f"    Erro ao identificar matched adsets Faixa A: {e}")
                    matched_adsets_faixa_a = None

                # 3.1. Obter detalhes de cada instância de adset (Faixa A)
                try:
                    faixa_a_instances_detail = get_faixa_a_instances_detail(
                        eventos_ml_campaign_ids=eventos_ml_campaign_ids,
                        matched_df=matched_df
                    )
                    if not faixa_a_instances_detail.empty:
                        logger.info(f"    {len(faixa_a_instances_detail)} instâncias de adsets processadas (Eventos ML vs Faixa A)")
                    else:
                        logger.info("   ℹ Nenhuma instância de adset encontrada")
                except Exception as e:
                    logger.warning(f"    Erro ao obter detalhes de instâncias Faixa A: {e}")
                    import traceback
                    traceback.print_exc()
                    faixa_a_instances_detail = None

                # COMENTADO: Comparação de ads desabilitada temporariamente
                # # 3. Comparar TODOS os ads (se houver ads_df)
                # if not ads_df.empty:
                #     from src.validation.fair_campaign_comparison import compare_ad_performance
                #
                #     # Preparar ads_df: adicionar ml_type usando primeiros 15 dígitos
                #     ads_df_prep = ads_df.copy()
                #     ads_df_prep['campaign_id_15'] = ads_df_prep['campaign_id'].astype(str).str[:15]
                #     ads_df_prep['ml_type'] = ads_df_prep['campaign_id_15'].map(ml_type_map)
                #
                #     # Criar ml_type_map expandido com IDs completos (18 dígitos)
                #     # para compatibilidade com compare_ad_performance
                #     ml_type_map_full = {}
                #     for _, row in ads_df_prep[['campaign_id', 'ml_type']].drop_duplicates().iterrows():
                #         if pd.notna(row['ml_type']):
                #             ml_type_map_full[row['campaign_id']] = row['ml_type']
                #
                #     ad_level_comparisons = compare_ad_performance(
                #         ad_metrics_df=ads_df,
                #         matched_df=matched_df,
                #         ml_type_map=ml_type_map_full
                #     )
                #
                #     logger.info(f"    Comparação de ads concluída ({len(ad_level_comparisons.get('detailed_matched', pd.DataFrame()))} linhas)")
                #
                # # 4. Comparar ads dentro dos matched adsets (reutilizar matched_adsets já identificado)
                # if matched_adsets and not ads_df.empty:
                #     try:
                #         ad_in_matched_adsets_comparisons = compare_ads_in_matched_adsets(
                #             ad_metrics_df=ads_df,
                #             matched_df=matched_df,
                #             ml_type_map=ml_type_map_full if 'ml_type_map_full' in locals() else ml_type_map,
                #             product_value=config['product_value'],
                #             comparison_group_map=comparison_group_map,
                #             filtered_matched_adsets=matched_adsets
                #         )
                #         logger.info(f"    Comparação de ads em adsets matched concluída")
                #     except Exception as e:
                #         logger.warning(f"     Erro na comparação de ads em adsets matched: {e}")
                #         ad_in_matched_adsets_comparisons = None
                #
                #     # 6. Comparar matched ads dentro dos matched adsets
                #     try:
                #         matched_ads_in_matched_adsets_comparisons = compare_matched_ads_in_matched_adsets(
                #             ad_metrics_df=ads_df,
                #             matched_df=matched_df,
                #             ml_type_map=ml_type_map_full if 'ml_type_map_full' in locals() else ml_type_map,
                #             product_value=config['product_value'],
                #             comparison_group_map=comparison_group_map,
                #             filtered_matched_adsets=matched_adsets
                #         )
                #         logger.info(f"    Comparação de matched ads em adsets matched concluída")
                #     except Exception as e:
                #         logger.warning(f"     Erro na comparação de matched ads em adsets matched: {e}")
                #         matched_ads_in_matched_adsets_comparisons = None
                # else:
                #     logger.warning("    Nenhum adset matched encontrado (comparações específicas não disponíveis)")
            else:
                logger.warning("    Nenhum adset carregado dos relatórios")

        except Exception as e:
            logger.error(f"    Erro na comparação de adsets/ads: {e}")
            import traceback
            traceback.print_exc()

    print(flush=True)

    # 9. EXIBIR RESUMO NO TERMINAL
    print(" RESUMO EXECUTIVO - COMPARAÇÃO ML vs NÃO-ML", flush=True)
    print(flush=True)
    print_summary_table(ml_comparison)

    print(flush=True)
    print(" PERFORMANCE POR DECIL (Real vs Esperado)", flush=True)
    print("IMPORTANTE: Modelo treinado APENAS com vendas Guru", flush=True)
    print(" Guru = Dados de treinamento | Total = Guru + TMB (generalização)", flush=True)
    print(flush=True)
    print_decile_table(decile_metrics)

    print(flush=True)

    # 9.5. Exibir métricas por campanha
    print(" MÉTRICAS DETALHADAS POR CAMPANHA", flush=True)
    print(flush=True)

    # Formatar nome das campanhas
    def format_campaign_name(row):
        campaign = str(row['campaign'])

        # Identificador ML/não-ML
        if 'MACHINE LEARNING' in campaign:
            prefix = '[ML]'
        elif 'ESCALA SCORE' in campaign:
            prefix = '[ESCALA]'
        elif 'FAIXA A' in campaign:
            prefix = '[FAIXA-A]'
        elif 'FAIXA B' in campaign:
            prefix = '[FAIXA-B]'
        elif 'FAIXA C' in campaign:
            prefix = '[FAIXA-C]'
        else:
            prefix = '[OUTRO]'

        # Data
        parts = campaign.split('|')
        date_part = parts[-1].strip()[:10] if len(parts) > 1 and '2025' in parts[-1] else ''

        # Tipo/Temperatura
        tipo = 'CAP' if 'CAP' in campaign else 'RET' if 'RET' in campaign else ''
        temp = 'FRIO' if 'FRIO' in campaign else 'MORNO' if 'MORNO' in campaign else ''

        desc = f'{tipo}/{temp}' if tipo and temp else tipo if tipo else temp if temp else ''

        return f'{prefix:10} {desc:10} {date_part:10}'.strip()

    campaign_display = campaign_metrics.copy()
    campaign_display['brief_name'] = campaign_display.apply(format_campaign_name, axis=1)

    # Ordenar por ROAS
    campaign_display = campaign_display.sort_values('roas', ascending=False)

    # Preparar dados para exibição
    display_data = []
    for _, row in campaign_display.iterrows():
        display_data.append([
            row['ml_type'],
            row['brief_name'],
            f"{row['leads']:,}",
            f"{row['conversions']:,}",
            f"{row['conversion_rate']:.2f}%",  # Já está em porcentagem
            f"R$ {row['total_revenue']:,.0f}",
            f"R$ {row['spend']:,.0f}",
            f"R$ {row['cpl']:.2f}",
            f"{row['roas']:.2f}x",
            f"R$ {row['contribution_margin']:,.0f}"
        ])

    headers = ['Tipo', 'Campanha', 'Leads', 'Conv', 'Taxa', 'Receita', 'Gasto', 'CPL', 'ROAS', 'Margem']
    print(tabulate(display_data, headers=headers, tablefmt='grid'), flush=True)
    print(flush=True)
    print(f"Total de campanhas: {len(campaign_display)}", flush=True)
    print(flush=True)

    # 10. Gerar relatório Excel
    print(" Gerando relatório Excel...", flush=True)
    os.makedirs(output_dir, exist_ok=True)

    # Nome do arquivo: {LF} - {DD:MM} a {DD:MM}.xlsx
    # Sem timestamp — re-rodar sobrescreve o arquivo anterior (sempre a versão mais recente).
    _file_start = args.sales_start_date if args.sales_start_date else start_date
    _file_end   = args.sales_end_date   if args.sales_end_date   else end_date
    _periodo_label = get_periodo_folder_from_dates(_file_start, _file_end).replace(' - ', ' a ')
    excel_filename = f"{args.lf_name} - {_periodo_label}.xlsx"
    excel_path = str(Path(output_dir) / excel_filename)
    logger.info(f"    Criando relatório: {excel_filename}")

    # Formatar account IDs para exibição
    account_ids_display = ', '.join(args.account_id) if isinstance(args.account_id, list) else args.account_id

    # Determinar fonte dos leads
    leads_source = 'CSV' if args.leads_path else 'Google Sheets (Produção)'

    config_params = {
        'Período': period_name,
        'Data Início': start_date,
        'Data Fim': end_date,
        'Fonte de Leads': leads_source,
        'Valor do Produto': f"R$ {config['product_value']:,.2f}",
        'Janela de Matching': f"{config['max_match_days']} dias",
        'Account IDs': account_ids_display,
        'Total de Leads': len(leads_df),
        'Total de Conversões': matching_stats['total_conversions'],
        'Gerado em': datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        'merge_otimizacao_ml_with_controle': config.get('merge_otimizacao_ml_with_controle', False)
    }

    # Histórico de CPA: baixar do GCS (ou fallback local), montar linhas do período atual e combinar
    _bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET')
    print("  Carregando histórico de CPA...", flush=True)
    cpa_historico_df = _download_cpa_historico(_bucket_name)

    _tracking_rate_pct = matching_stats.get('tracking_rate', 100.0) if matching_stats else 100.0
    _sales_start = getattr(args, 'sales_start_date', None) or start_date
    _sales_end = getattr(args, 'sales_end_date', None) or end_date
    _new_rows = _build_cpa_rows(
        campaign_metrics, start_date, end_date,
        _sales_start, _sales_end, _tracking_rate_pct
    )
    if not _new_rows.empty:
        cpa_historico_df = pd.concat([cpa_historico_df, _new_rows], ignore_index=True)
        # Manter apenas a entrada mais recente por (período, campanha)
        cpa_historico_df = cpa_historico_df.drop_duplicates(
            subset=['periodo_captacao', 'periodo_vendas', 'campaign_id'], keep='last'
        ).reset_index(drop=True)

    report_gen = ValidationReportGenerator()
    report_gen.generate_excel_report(
        campaign_metrics,
        decile_metrics,
        ml_comparison,
        matching_stats,
        overall_stats,
        config_params,
        excel_path,
        comparison_group_metrics=comparison_group_metrics,
        fair_comparison_info=fair_comparison_info,
        matched_df=matched_df,
        sales_df=sales_df,
        all_adsets_comparison=all_adsets_comparison,
        adset_level_comparisons=adset_level_comparisons,
        ad_level_comparisons=ad_level_comparisons,
        ad_in_matched_adsets_comparisons=ad_in_matched_adsets_comparisons,
        matched_ads_in_matched_adsets_comparisons=matched_ads_in_matched_adsets_comparisons,
        matched_adsets_faixa_a=matched_adsets_faixa_a,
        faixa_a_instances_detail=faixa_a_instances_detail,
        ml_monitoring_metrics=ml_monitoring_metrics,
        cpa_historico_df=cpa_historico_df if not cpa_historico_df.empty else None,
        fbp_fbc_map=fbp_fbc_map
    )
    print(f"    Excel salvo: {excel_path}", flush=True)
    print(flush=True)

    # 11. Gerar gráficos
    # DESABILITADO: Gerando apenas análise em console até finalizar formato
    # print(" Gerando visualizações...")
    # viz = ValidationVisualizer()
    # viz.generate_all_charts(
    #     campaign_metrics,
    #     decile_metrics,
    #     ml_comparison,
    #     output_dir
    # )
    # print()

    # 12. Finalização
    end_time = time.time()
    elapsed_time = end_time - start_time

    print(" VALIDAÇÃO CONCLUÍDA COM SUCESSO!", flush=True)
    print(flush=True)
    print(f" Análise exibida no console acima", flush=True)
    print(f" Excel atualizado: {excel_path}", flush=True)
    print(f"  Tempo de execução: {elapsed_time:.1f} segundos ({elapsed_time/60:.1f} minutos)", flush=True)
    print(flush=True)

    # 13. Upload para Cloud Storage (se configurado)
    excel_url = None
    bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET')

    if bucket_name:
        try:
            from google.cloud import storage

            print("  Fazendo upload para Cloud Storage...", flush=True)

            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)

            # Nome do blob: validation/YYYY/MM/filename.xlsx
            excel_filename = Path(excel_path).name
            blob_name = f"validation/{datetime.now().year}/{datetime.now().month:02d}/{excel_filename}"
            blob = bucket.blob(blob_name)

            # Upload
            blob.upload_from_filename(excel_path)
            blob.make_public()

            excel_url = blob.public_url
            print(f"    Upload concluído: {excel_url}", flush=True)

        except Exception as storage_error:
            print(f"     Erro no upload Cloud Storage: {storage_error}", flush=True)
            excel_url = None
    else:
        print("   ℹ  VALIDATION_REPORTS_BUCKET não configurado, upload ignorado", flush=True)

    # Salvar histórico de CPA (GCS + fallback local)
    if not cpa_historico_df.empty:
        _upload_cpa_historico(cpa_historico_df, bucket_name)

    print(flush=True)

    # 14. Upload para Google Sheets (se configurado)
    sheets_url = None
    upload_to_sheets = os.getenv('UPLOAD_VALIDATION_TO_SHEETS', 'false').lower() == 'true'
    sheets_share_emails = os.getenv('SHEETS_SHARE_EMAILS', '')  # Emails separados por vírgula

    if upload_to_sheets:
        try:
            from src.validation.sheets_uploader import ValidationSheetsUploader

            print(" Fazendo upload para Google Sheets...", flush=True)

            uploader = ValidationSheetsUploader()

            # Preparar emails para compartilhamento
            share_with = None
            if sheets_share_emails:
                share_with = [email.strip() for email in sheets_share_emails.split(',') if email.strip()]

            # Fazer upload
            sheets_url = uploader.upload_excel_to_sheets(
                excel_path=excel_path,
                spreadsheet_title=None,  # Usa nome do arquivo
                share_with_emails=share_with
            )

            print(f"    Google Sheets criado: {sheets_url}", flush=True)

        except Exception as sheets_error:
            print(f"     Erro no upload Google Sheets: {sheets_error}", flush=True)
            logger.warning(f"Erro no upload Google Sheets: {sheets_error}")
            sheets_url = None
    else:
        print("   ℹ  UPLOAD_VALIDATION_TO_SHEETS não habilitado, upload ignorado", flush=True)

    print(flush=True)

    # 15. Enviar notificação Slack (se configurado)
    slack_webhook = os.getenv('SLACK_WEBHOOK_URL')

    if slack_webhook:
        try:
            from src.validation.slack_notifier import ValidationSlackNotifier

            print(" Enviando notificação Slack...", flush=True)

            notifier = ValidationSlackNotifier(webhook_url=slack_webhook)

            # Preparar métricas para Slack
            slack_metrics = {
                'status': 'success',
                'total_leads': len(leads_df) if 'leads_df' in locals() else 0,
                'total_conversions': conversions_count if 'conversions_count' in locals() else 0,
                'total_campaigns': len(costs_hierarchy_temp) if 'costs_hierarchy_temp' in locals() else 0
            }

            # Preparar período
            slack_period = {
                'start': start_date,
                'end': end_date,
                'sales_start': args.sales_start_date if hasattr(args, 'sales_start_date') else None,
                'sales_end': args.sales_end_date if hasattr(args, 'sales_end_date') else None,
                'report_type': args.report_type
            }

            success = notifier.send_validation_summary(
                metrics=slack_metrics,
                excel_url=excel_url,
                sheets_url=sheets_url,
                period=slack_period
            )

            if success:
                print("    Notificação Slack enviada", flush=True)
            else:
                print("     Falha ao enviar notificação Slack", flush=True)

        except Exception as slack_error:
            print(f"     Erro ao enviar Slack: {slack_error}", flush=True)
    else:
        print("   ℹ  SLACK_WEBHOOK_URL não configurado, notificação ignorada", flush=True)

    # Envio de Purchase events ao Meta CAPI
    if args.send_purchase_events:
        if not args.sales_start_date or not args.sales_end_date:
            print("   ⚠  --send-purchase-events requer --sales-start-date e --sales-end-date", flush=True)
        else:
            print(flush=True)
            print(" ENVIANDO PURCHASE EVENTS AO META CAPI", flush=True)
            try:
                from src.validation.send_purchase_events import send_purchase_events
                result = send_purchase_events(
                    sales_start_date=args.sales_start_date,
                    sales_end_date=args.sales_end_date,
                    dry_run=False,
                    test_event_code=args.purchase_test_event_code,
                )
                print(f"   Enviados:  {result.get('enviados')}", flush=True)
                print(f"   Anomalias: {result.get('anomalias')}  (sem FBP/FBC no Railway)", flush=True)
                print(f"   Erros:     {result.get('erros')}", flush=True)
            except Exception as e:
                print(f"   ❌  Erro ao enviar purchase events: {e}", flush=True)

    # Atualizar planilha Evolução DevClub
    if args.update_evolution:
        if not (args.start_date and args.end_date and args.sales_start_date and args.sales_end_date):
            print("   ⚠  --update-evolution requer --start-date, --end-date, --sales-start-date e --sales-end-date", flush=True)
        else:
            print(flush=True)
            print(" ATUALIZANDO PLANILHA EVOLUÇÃO DEVCLUB", flush=True)
            try:
                import sys as _sys
                from pathlib import Path as _Path
                _scripts_dir = str(_Path(__file__).parent.parent.parent / 'scripts')
                if _scripts_dir not in _sys.path:
                    _sys.path.insert(0, _scripts_dir)
                import ml_evolution_report as _evol

                # Nome do lançamento: --evolution-name ou gerado pelo período de vendas
                ev_name = args.evolution_name
                if not ev_name:
                    ev_name = f"LF_{args.sales_start_date}"

                extra_period = {
                    'name':         ev_name,
                    'cap_start':    args.start_date,
                    'cap_end':      args.end_date,
                    'vendas_start': args.sales_start_date,
                    'vendas_end':   args.sales_end_date,
                }

                output = _evol.run(extra_period=extra_period)
                print(f"   Planilha gerada: {output}", flush=True)
            except Exception as e:
                print(f"   ❌  Erro ao gerar evolução: {e}", flush=True)

    print(flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n Operação cancelada pelo usuário")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n ERRO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
