#!/usr/bin/env python3
"""
Script CLI para Validação de Performance do Modelo de ML de Lead Scoring.

Compara campanhas COM ML vs SEM ML e valida performance por decil D1-D10.

Uso:
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
from datetime import datetime
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
from src.validation.data_loader import LeadDataLoader, SalesDataLoader, CAPILeadDataLoader, get_active_model_path
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
    print("⚠️ Biblioteca 'tabulate' não encontrada. Instale com: pip install tabulate")
    sys.exit(1)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def validate_tmb_sales_freshness(sales_df, sales_start, sales_end):
    """
    Valida se as vendas TMB estão atualizadas para o período de análise.

    Regras:
    1. Se não houver NENHUMA venda TMB no período → ERRO CRÍTICO (para execução)
    2. Se houver vendas TMB mas a mais recente é ANTES do fim do período → WARNING (continua com aviso)

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
        logger.error("❌ ERRO CRÍTICO: Nenhuma venda TMB encontrada no período!")
        logger.error(f"   Período analisado: {sales_start} a {sales_end}")
        logger.error("   ")
        logger.error("   ⚠️  AÇÃO NECESSÁRIA:")
        logger.error("   1. Baixar arquivo TMB atualizado")
        logger.error("   2. Fazer upload do arquivo para: files/validation/vendas/")
        logger.error("   3. Fazer novo deploy do job ou rodar localmente")
        logger.error("   ")
        return {
            'status': 'error',
            'message': 'Nenhuma venda TMB no período',
            'stop_execution': True
        }

    # Verificar data mais recente das vendas TMB
    tmb_latest_date = tmb_sales['sale_date'].max()
    sales_end_dt = pd.to_datetime(sales_end)

    logger.info(f"📊 Vendas TMB no período: {len(tmb_sales)}")
    logger.info(f"   Data mais recente TMB: {tmb_latest_date.strftime('%Y-%m-%d')}")
    logger.info(f"   Fim do período esperado: {sales_end}")

    # Se a data mais recente é antes do fim do período
    if tmb_latest_date < sales_end_dt:
        days_missing = (sales_end_dt - tmb_latest_date).days

        logger.warning("⚠️  AVISO: Vendas TMB podem estar DESATUALIZADAS!")
        logger.warning(f"   Última venda TMB: {tmb_latest_date.strftime('%Y-%m-%d')}")
        logger.warning(f"   Fim do período: {sales_end}")
        logger.warning(f"   Diferença: {days_missing} dias")
        logger.warning("   ")
        logger.warning(f"   ℹ️  O relatório será gerado com vendas TMB até {tmb_latest_date.strftime('%d/%m/%Y')}")
        logger.warning("   ")

        return {
            'status': 'warning',
            'message': f'Vendas TMB até {tmb_latest_date.strftime("%Y-%m-%d")} (faltam {days_missing} dias)',
            'stop_execution': False,
            'tmb_latest_date': tmb_latest_date.strftime('%Y-%m-%d'),
            'days_missing': days_missing
        }

    # Vendas TMB estão atualizadas
    logger.info("✅ Vendas TMB atualizadas até o fim do período")

    return {
        'status': 'ok',
        'message': 'Vendas TMB atualizadas',
        'stop_execution': False
    }


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
        help='Caminho para pasta com arquivos de vendas (default: files/validation/vendas/)'
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        help='Diretório de saída (default: files/validation/resultados/)'
    )

    parser.add_argument(
        '--ml-monitoring-output',
        type=str,
        help='Diretório alternativo para relatórios ML Monitoring (se não especificado, usa --output-dir)'
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

    args = parser.parse_args()

    # Validações
    if args.start_date and not args.end_date:
        parser.error("--start-date requer --end-date")
    if args.end_date and not args.start_date:
        parser.error("--end-date requer --start-date")

    if not args.periodo and not args.start_date:
        parser.error("É necessário especificar --periodo OU --start-date/--end-date")

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
        logger.error(f"❌ Arquivo de configuração não encontrado: {config_path}")
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
        print(f"🏆 VENCEDOR: COM ML (ROAS Ajustado TMB {improvement:.1f}% maior)", flush=True)
    elif sem_ml.get('roas_adjusted', 0) > com_ml.get('roas_adjusted', 0):
        decline = abs(diff.get('roas_adjusted_diff', 0))
        print(f"⚠️ VENCEDOR: SEM ML (ROAS Ajustado TMB {decline:.1f}% maior)", flush=True)
    else:
        print("➖ Empate técnico em ROAS Ajustado TMB", flush=True)


def print_decile_table(decile_metrics):
    """
    Exibe tabela de performance por decil no terminal (Guru vs Guru+TMB).

    Args:
        decile_metrics: DataFrame retornado por DecileMetricsCalculator
    """
    if decile_metrics.empty:
        print("⚠️ Nenhuma métrica de decil disponível", flush=True)
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
    print(f"💰 Receita Total Guru: R$ {total_guru:,.2f}", flush=True)
    print(f"💰 Receita Total TMB: R$ {total_tmb_only:,.2f}", flush=True)
    print(f"💰 Receita Total (Guru+TMB): R$ {decile_metrics['revenue_total'].sum():,.2f}", flush=True)


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
    logger.info("   🔍 Procurando IDs de campanha/adset sem nomes...")

    # Identificar linhas com apenas ID numérico
    def is_numeric_id(value):
        if pd.isna(value):
            return False
        value_str = str(value).strip()
        return value_str.isdigit() and len(value_str) > 10  # IDs Meta têm 15+ dígitos

    mask = leads_df['campaign'].apply(is_numeric_id)
    ids_to_enrich = leads_df.loc[mask, 'campaign'].unique()

    if len(ids_to_enrich) == 0:
        logger.info("   ✅ Nenhum ID sem nome encontrado")
        return leads_df

    logger.info(f"   📋 Encontrados {len(ids_to_enrich)} IDs únicos para enriquecer ({mask.sum()} respostas)")

    # Inicializar Meta API
    meta_api = MetaAdsIntegration(access_token=access_token)

    # Mapa ID → Nome
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
                logger.info(f"      ✅ {campaign_id_str[:15]}... → {name[:60]}...")
            else:
                logger.info(f"      ⚠️ ID {campaign_id_str}: status {response.status_code} (pode ser adset ou campanha de outra conta)")
                id_to_name[campaign_id] = campaign_id_str

        except Exception as e:
            logger.info(f"      ⚠️ Erro ao buscar {campaign_id_str}: {e}")
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

    logger.info(f"   ✅ {enriched_count}/{len(ids_to_enrich)} IDs enriquecidos com sucesso")

    return leads_df


def main():
    """
    Função principal do CLI.
    """
    start_time = time.time()

    print("=" * 80, flush=True)
    print("🚀 SISTEMA DE VALIDAÇÃO DE PERFORMANCE ML - LEAD SCORING", flush=True)
    print("=" * 80, flush=True)
    print(flush=True)

    # 1. Parse argumentos
    args = parse_args()

    # 1.2. Calcular datas automaticamente se solicitado
    if args.auto_calculate_dates:
        from datetime import datetime, timedelta

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

        logger.info(f"📅 Datas calculadas automaticamente ({args.report_type}):")
        logger.info(f"   Captação: {args.start_date} a {args.end_date}")
        logger.info(f"   Vendas: {args.sales_start_date} a {args.sales_end_date}")

    # DEBUG: Verificar o que foi parseado

    # 1.5. Gerenciar cache se solicitado
    if args.clear_cache:
        import shutil
        cache_dir = Path(__file__).parent.parent.parent / 'files' / 'validation' / 'cache'
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            print("🗑️  Cache limpo com sucesso!", flush=True)
            print(flush=True)
        else:
            print("⚠️  Nenhum cache encontrado para limpar", flush=True)
            print(flush=True)

    # 2. Carregar configuração
    logger.info(f"⚙️ Carregando configuração de {args.config}...")
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
            logger.info(f"   📊 Usando account IDs do config: {', '.join(args.account_id)}")
        else:
            logger.error("❌ Nenhum account ID fornecido via CLI ou config")
            sys.exit(1)

    # Determinar período
    if args.periodo:
        if args.periodo not in config.get('periodos', {}):
            logger.error(f"❌ Período '{args.periodo}' não encontrado no config")
            sys.exit(1)
        period_config = config['periodos'][args.periodo]
        start_date = period_config['start_date']
        end_date = period_config['end_date']
        period_name = period_config['name']
        logger.info(f"   Período: {period_name} ({start_date} a {end_date})")

        # Usar sales dates do config se não foram especificados via CLI
        if not args.sales_start_date and 'sales_start_date' in period_config:
            args.sales_start_date = period_config['sales_start_date']
            logger.info(f"   📅 Período de vendas do config: {args.sales_start_date} a {period_config.get('sales_end_date')}")
        if not args.sales_end_date and 'sales_end_date' in period_config:
            args.sales_end_date = period_config['sales_end_date']
    else:
        start_date = args.start_date
        end_date = args.end_date
        period_name = f"Período {start_date} a {end_date}"
        logger.info(f"   Período customizado: {start_date} a {end_date}")

    # Determinar caminhos
    vendas_path = args.vendas_path or config['paths']['vendas']

    # Usar ml-monitoring-output se especificado, senão usar output-dir padrão
    if args.ml_monitoring_output:
        output_dir = args.ml_monitoring_output
    else:
        output_dir = args.output_dir or 'files/validation/resultados'

    logger.info(f"   Vendas: {vendas_path}")
    logger.info(f"   Output: {output_dir}")
    logger.info(f"   Valor do produto: R$ {config['product_value']:,.2f}")
    logger.info(f"   Janela de matching: {config['max_match_days']} dias")
    print(flush=True)

    # 3. Carregar dados
    print("📂 CARREGANDO DADOS...", flush=True)
    print(flush=True)

    # Leads - PADRÃO: Google Sheets (produção), FALLBACK: CSV se --leads-path fornecido
    if args.leads_path:
        # Modo CSV (legacy)
        logger.info(f"   📄 Usando CSV: {args.leads_path}")
        capi_loader = CAPILeadDataLoader()

        if not Path(args.leads_path).exists():
            logger.error(f"❌ Arquivo de leads não encontrado: {args.leads_path}")
            sys.exit(1)

        leads_df, lead_source_stats = capi_loader.load_combined_leads(
            csv_path=args.leads_path,
            start_date=start_date if isinstance(start_date, str) else start_date.strftime('%Y-%m-%d'),
            end_date=end_date if isinstance(end_date, str) else end_date.strftime('%Y-%m-%d')
        )
        logger.info(f"   ✅ {len(leads_df)} leads carregados do CSV")
        logger.info(f"   📊 Estatísticas: {lead_source_stats['survey_leads']} pesquisa + {lead_source_stats['capi_leads_extras']} CAPI extras")
    else:
        # Modo Google Sheets (PADRÃO - dados de produção em tempo real)
        logger.info(f"   📊 Usando Google Sheets (produção)")

        # Limpar cache se solicitado
        if args.clear_cache:
            cache_file = Path.home() / '.cache' / 'smart_ads' / 'sheets_leads_cache.csv'
            if cache_file.exists():
                cache_file.unlink()
                logger.info(f"   🗑️  Cache limpo: {cache_file}")

        lead_loader = LeadDataLoader()
        use_cache = not args.no_cache

        # Carregar Pesquisa do Google Sheets (carrega AMBAS as abas)
        survey_df = lead_loader.load_leads_from_sheets(
            start_date=start_date if isinstance(start_date, str) else start_date.strftime('%Y-%m-%d'),
            end_date=end_date if isinstance(end_date, str) else end_date.strftime('%Y-%m-%d'),
            use_cache=use_cache
        )
        logger.info(f"   ✅ {len(survey_df)} leads da pesquisa carregados do Google Sheets")

        survey_emails = set(survey_df['email'].unique())
        logger.info(f"   📧 {len(survey_emails)} emails únicos na pesquisa")

        # Buscar e combinar com leads CAPI extras (mesma lógica do modo CSV)
        # WORKAROUND: usar curl (requests estava travando)
        import subprocess
        import json as json_module
        import re

        logger.info("   🔍 Buscando leads no CAPI...")

        try:
            # Usar localhost se rodando dentro do container (chamado via endpoint /validation/weekly)
            # Senão usar URL pública (execução standalone)
            API_URL = os.getenv('INTERNAL_API_URL', 'https://smart-ads-api-12955519745.us-central1.run.app')

            start_str = start_date if isinstance(start_date, str) else start_date.strftime('%Y-%m-%d')
            end_str = end_date if isinstance(end_date, str) else end_date.strftime('%Y-%m-%d')

            url = f"{API_URL}/webhook/lead_capture/recent?start_date={start_str}&end_date={end_str}&limit=10000"
            logger.info(f"   📡 URL CAPI: {url}")

            result_curl = subprocess.run(
                ['curl', '-s', '--max-time', '30', url],
                capture_output=True,
                text=True,
                timeout=35
            )


            if result_curl.returncode == 0:
                result = json_module.loads(result_curl.stdout)
                capi_leads_data = result.get('leads', [])

                logger.info(f"   📊 CAPI: {len(capi_leads_data)} leads encontrados")

                if capi_leads_data:
                    # Converter para DataFrame
                    capi_df = pd.DataFrame(capi_leads_data)

                    # Normalizar
                    from src.validation.data_loader import normalizar_email, normalizar_telefone_robusto

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
                    capi_norm['lead_score'] = np.nan
                    capi_norm['decile'] = None
                    capi_norm['source_type'] = 'capi'

                    # Remover leads sem email
                    capi_norm = capi_norm[capi_norm['email'].notna()].copy()

                    # FILTRO: campaign_id Meta válido
                    def extract_campaign_id_meta(utm_campaign):
                        if pd.isna(utm_campaign):
                            return None
                        match = re.search(r'\|(\d{15,})$', str(utm_campaign))
                        return match.group(1)[:15] if match else None

                    total_antes = len(capi_norm)
                    capi_norm['campaign_id_meta'] = capi_norm['campaign'].apply(extract_campaign_id_meta)
                    capi_norm = capi_norm[capi_norm['campaign_id_meta'].notna()].copy()

                    removidos = total_antes - len(capi_norm)
                    if removidos > 0:
                        logger.info(f"   🔍 Filtrado: {removidos} sem campaign_id Meta ({len(capi_norm)} restaram)")

                    # Leads CAPI que NÃO estão na pesquisa
                    capi_emails = set(capi_norm['email'].unique())
                    capi_extras = capi_emails - survey_emails
                    capi_extra_leads = capi_norm[capi_norm['email'].isin(capi_extras)].copy()

                    logger.info(f"   ➕ Leads extras do CAPI: {len(capi_extra_leads)} (não estão na pesquisa)")

                    # Combinar
                    if len(capi_extra_leads) > 0:
                        leads_df = pd.concat([survey_df, capi_extra_leads], ignore_index=True)
                        logger.info(f"   ✅ Total combinado: {len(leads_df)} ({len(survey_df)} pesquisa + {len(capi_extra_leads)} CAPI)")
                    else:
                        leads_df = survey_df
                        logger.info(f"   ✅ Total: {len(leads_df)} (apenas pesquisa)")

                    # Estatísticas
                    lead_source_stats = {
                        'survey_leads': len(survey_df),
                        'capi_leads_extras': len(capi_extra_leads),
                        'capi_leads_total': len(capi_norm['email'].unique())
                    }
                else:
                    logger.info("   ⚠️ Nenhum lead CAPI encontrado")
                    leads_df = survey_df
                    lead_source_stats = {
                        'survey_leads': len(survey_df),
                        'capi_leads_extras': 0,
                        'capi_leads_total': 0
                    }
            else:
                logger.warning(f"   ⚠️ Curl para API CAPI falhou")
                leads_df = survey_df
                lead_source_stats = {
                    'survey_leads': len(survey_df),
                    'capi_leads_extras': 0,
                    'capi_leads_total': 0
                }

        except Exception as e:
            logger.warning(f"   ⚠️ Erro ao buscar CAPI: {e}")
            leads_df = survey_df
            lead_source_stats = {
                'survey_leads': len(survey_df),
                'capi_leads_extras': 0,
                'capi_leads_total': 0
            }

        logger.info(f"   📊 Estatísticas: {lead_source_stats['survey_leads']} pesquisa + {lead_source_stats['capi_leads_extras']} CAPI extras")

    # Vendas
    sales_loader = SalesDataLoader()

    # Configuração de fonte de dados Guru: "local" (arquivos) ou "api" (Guru API)
    # Pode ser controlada via variável de ambiente GURU_DATA_SOURCE
    guru_data_source = os.environ.get('GURU_DATA_SOURCE', 'local').lower()
    logger.info(f"📊 Fonte de dados Guru: {guru_data_source.upper()}")

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

        logger.info(f"   🌐 Buscando via API: {api_sales_start} a {api_sales_end}")

        # Buscar via API (sem salvar Excel duplicado)
        guru_df = sales_loader.load_guru_sales_from_api(
            start_date=api_sales_start,
            end_date=api_sales_end,
            save_excel=False
        )
    else:
        # Modo local (arquivos Excel)
        # Buscar arquivos Guru com qualquer capitalização e formato: guru*, Guru*, GURU*
        guru_files = sorted(glob(f"{vendas_path}/[Gg][Uu][Rr][Uu]*.xlsx"))
        logger.info(f"   Arquivos Guru encontrados: {len(guru_files)}")

        guru_df = sales_loader.load_guru_sales(guru_files) if guru_files else None

    # Buscar arquivos TMB com qualquer capitalização e formato: tmb*, Tmb*, TMB*
    tmb_files = sorted(glob(f"{vendas_path}/[Tt][Mm][Bb]*.xlsx"))
    logger.info(f"   Arquivos TMB encontrados: {len(tmb_files)}")

    # Combinar vendas Guru + TMB
    sales_df = sales_loader.combine_sales(
        guru_df=guru_df,
        tmb_paths=tmb_files if tmb_files else None
    )

    if sales_df.empty:
        logger.error("❌ Nenhuma venda carregada. Verifique os arquivos de vendas.")
        sys.exit(1)

    logger.info(f"   ✅ {len(sales_df)} vendas carregadas (Guru + TMB)")
    print(flush=True)

    # 4. Filtrar por período
    # Período de vendas pode ser diferente do período de captação
    # Se não foram fornecidos, calcular usando a lógica documentada (3 semanas)
    if args.sales_start_date and args.sales_end_date:
        sales_start = args.sales_start_date
        sales_end = args.sales_end_date
        logger.info(f"   📅 Usando período de vendas customizado: {sales_start} a {sales_end}")
    else:
        # Usar PeriodCalculator para calcular o período de vendas correto
        period_calc = PeriodCalculator()
        calculated_periods = period_calc.calculate_periods(start_date)
        sales_start = calculated_periods['sales']['start']
        sales_end = calculated_periods['sales']['end']
        logger.info(f"   📅 Período de vendas calculado automaticamente: {sales_start} a {sales_end}")

    print(flush=True)
    print(f"📅 FILTRANDO DADOS...", flush=True)
    print(f"   Período de Captação (Leads/Campanhas): {start_date} a {end_date}", flush=True)
    print(f"   Período de Vendas (Matching): {sales_start} a {sales_end}", flush=True)
    print(flush=True)

    # Armazenar estatísticas antes do filtro
    sales_before = len(sales_df)
    sales_guru_before = len(sales_df[sales_df['origem'] == 'guru']) if 'origem' in sales_df.columns else 0
    sales_tmb_before = len(sales_df[sales_df['origem'] == 'tmb']) if 'origem' in sales_df.columns else 0

    leads_df = filter_by_period(leads_df, start_date, end_date, 'data_captura')
    sales_df = filter_by_period(sales_df, sales_start, sales_end, 'sale_date')

    # Mostrar estatísticas detalhadas após filtro de vendas
    sales_after = len(sales_df)
    sales_guru_after = len(sales_df[sales_df['origem'] == 'guru']) if 'origem' in sales_df.columns else 0
    sales_tmb_after = len(sales_df[sales_df['origem'] == 'tmb']) if 'origem' in sales_df.columns else 0

    logger.info(f"📊 Vendas após filtro de período:")
    logger.info(f"   Total: {sales_before} → {sales_after} vendas ({sales_after/sales_before*100:.1f}%)")
    logger.info(f"   Guru: {sales_guru_before} → {sales_guru_after} vendas")
    logger.info(f"   TMB: {sales_tmb_before} → {sales_tmb_after} vendas")

    # =========================================================================
    # VALIDAÇÃO: Verificar se vendas TMB estão atualizadas
    # =========================================================================
    print(flush=True)
    print("🔍 VALIDANDO ATUALIZAÇÃO DAS VENDAS TMB...", flush=True)
    print(flush=True)

    tmb_validation = validate_tmb_sales_freshness(sales_df, sales_start, sales_end)

    if tmb_validation['stop_execution']:
        # ERRO CRÍTICO: Sem vendas TMB no período
        logger.error("❌ Execução interrompida devido a vendas TMB faltantes")

        # Enviar notificação Slack de erro
        slack_webhook = os.getenv('SLACK_WEBHOOK_URL')
        if slack_webhook:
            try:
                import requests

                error_message = (
                    f"❌ *ERRO CRÍTICO: Validação ML Interrompida*\n\n"
                    f"*Motivo:* Nenhuma venda TMB encontrada no período\n"
                    f"*Período analisado:* {sales_start} a {sales_end}\n\n"
                    f"*Ação necessária:*\n"
                    f"1. Baixar arquivo TMB atualizado\n"
                    f"2. Fazer novo deploy\n"
                )

                response = requests.post(slack_webhook, json={"text": error_message})
                if response.status_code == 200:
                    logger.info("   📱 Notificação de erro enviada para Slack")
                else:
                    logger.warning(f"   ⚠️  Falha ao enviar Slack (status {response.status_code})")
            except Exception as e:
                logger.warning(f"   ⚠️  Erro ao enviar notificação Slack: {e}")

        sys.exit(1)

    elif tmb_validation['status'] == 'warning':
        # WARNING: Vendas TMB desatualizadas, mas continua
        # (já logou o warning dentro da função)
        pass

    print(flush=True)
    # =========================================================================

    if leads_df.empty:
        logger.error("❌ Nenhum lead no período especificado")
        sys.exit(1)

    # 4.5. Enriquecer IDs de campanha/adset com nomes reais
    # DESABILITADO: Usando MetaReportsLoader ao invés de API
    # print("🔗 ENRIQUECENDO NOMES DE CAMPANHA...", flush=True)
    # print(flush=True)
    # leads_df = enrich_campaign_ids(leads_df, args.account_id, META_CONFIG['access_token'])

    # 5. Classificar campanhas
    print("🏷️ CLASSIFICANDO CAMPANHAS...", flush=True)
    print(flush=True)
    leads_df, excluded_count = add_ml_classification(leads_df, campaign_col='campaign')

    com_ml_count = len(leads_df[leads_df['ml_type'] == 'COM_ML'])
    sem_ml_count = len(leads_df[leads_df['ml_type'] == 'SEM_ML'])
    logger.info(f"   ✅ COM ML: {com_ml_count} leads ({com_ml_count/len(leads_df)*100:.1f}%)")
    logger.info(f"   ✅ SEM ML: {sem_ml_count} leads ({sem_ml_count/len(leads_df)*100:.1f}%)")
    print(flush=True)

    # 5.5. Carregar relatórios Meta para criar grupos de comparação refinados
    print("💰 CARREGANDO RELATÓRIOS META PARA CLASSIFICAÇÃO...", flush=True)
    print(flush=True)

    # Carregar relatórios Meta locais ou via API
    # IMPORTANTE: Usar pasta específica com relatórios oficiais do período (não adsets_analysis)
    # Construir caminho dinamicamente baseado nas datas fornecidas
    from datetime import datetime
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    start_str = start_dt.strftime('%d:%m')
    end_str = end_dt.strftime('%d:%m')
    reports_dir = f'files/validation/meta_reports/{start_str} - {end_str}'

    # Configuração de fonte de dados: "local" (arquivos) ou "api" (Meta Marketing API)
    # Pode ser controlada via variável de ambiente META_DATA_SOURCE
    data_source = os.environ.get('META_DATA_SOURCE', 'local').lower()
    print(f"📊 Fonte de dados Meta: {data_source.upper()}", flush=True)

    # DEBUG: Verificar args.account_id

    # Passar account_ids para o loader (necessário no modo API para buscar múltiplas contas)
    loader = MetaReportsLoader(reports_dir, data_source=data_source, account_ids=args.account_id if data_source == 'api' else None)
    costs_hierarchy_temp = loader.build_costs_hierarchy(start_date, end_date)

    # Obter DataFrame de campanhas
    reports = loader.load_all_reports(start_date, end_date)
    campaigns_df = reports.get('campaigns', pd.DataFrame())

    # 5.6. Criar grupos de comparação REFINADOS (distingue Eventos ML vs Otimização ML)
    print("🎯 CRIANDO GRUPOS DE COMPARAÇÃO...", flush=True)
    print(flush=True)

    comparison_group_map_15 = {}  # Mapa com IDs de 15 dígitos

    if 'ml_type' in leads_df.columns and not campaigns_df.empty:
        # Identificar campanhas ML vs Controle usando classificação correta
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

        logger.info(f"   📊 Classificação de campanhas:")
        logger.info(f"      COM_ML: {len(ml_campaign_ids)} campanhas")
        logger.info(f"      SEM_ML (Controle): {len(control_campaign_ids)} campanhas")
        logger.info(f"      EXCLUÍDAS: {len(campaigns_df) - len(campaigns_df_filtered)} campanhas")

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
                if row.get('ml_type') == 'SEM_ML':
                    return 'Controle'
                elif row.get('ml_type') == 'COM_ML':
                    return 'Eventos ML'  # Apenas se não conseguimos o ID
                else:
                    return 'Outro'

            leads_df['comparison_group'] = leads_df.apply(map_to_refined_group, axis=1)

            group_counts = leads_df['comparison_group'].value_counts()
            logger.info(f"   ✅ Grupos refinados criados:")
            for group, count in group_counts.items():
                logger.info(f"      {group}: {count} leads")
        else:
            # Fallback: usar mapeamento simples
            logger.warning("   ⚠️ Não foi possível criar mapeamento refinado, usando simples")
            leads_df['comparison_group'] = leads_df['ml_type'].map({
                'COM_ML': 'Eventos ML',
                'SEM_ML': 'Controle'
            }).fillna('Outro')
    else:
        logger.warning("   ⚠️ Coluna ml_type não encontrada, pulando criação de grupos")

    print(flush=True)

    # 6. Matching
    print("🔗 VINCULANDO LEADS COM VENDAS...", flush=True)
    print(flush=True)
    matched_df = match_leads_to_sales(
        leads_df,
        sales_df,
        use_temporal_validation=False  # Results analysis mode - match against full history
    )

    # INVESTIGAÇÃO: Onde estão as vendas que não fizeram match?
    print("\n" + "="*80)
    print("🔍 INVESTIGAÇÃO: ANÁLISE DAS VENDAS SEM MATCH")
    print("="*80)

    conversions = matched_df[matched_df['converted'] == True]
    num_conversions = len(conversions)
    num_sales = len(sales_df)

    logger.info(f"📊 Vendas totais no período: {num_sales}")
    logger.info(f"📊 Vendas com match nos leads classificados: {num_conversions}")
    logger.info(f"📊 Vendas SEM match: {num_sales - num_conversions}")

    if num_sales > num_conversions:
        # Buscar vendas que não fizeram match nos leads classificados
        sales_emails = set(sales_df['email'].str.lower().str.strip())
        matched_emails = set(conversions['email'].str.lower().str.strip()) if num_conversions > 0 else set()
        unmatched_sales_emails = sales_emails - matched_emails

        logger.info(f"\n🔍 Investigando {len(unmatched_sales_emails)} vendas sem match...")

        # Carregar dataset COMPLETO de leads do Google Sheets (SEM filtro de período para ver histórico)
        temp_loader = LeadDataLoader()

        # Primeiro: dataset do período atual (com filtro)
        period_leads_df = temp_loader.load_leads_from_sheets(
            start_date=start_date if isinstance(start_date, str) else start_date.strftime('%Y-%m-%d'),
            end_date=end_date if isinstance(end_date, str) else end_date.strftime('%Y-%m-%d')
        )

        # Segundo: dataset histórico completo (SEM filtro de período)
        historical_leads_df = temp_loader.load_leads_from_sheets(
            start_date='2020-01-01',  # Data antiga para pegar todo o histórico
            end_date='2030-12-31'
        )

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
        logger.info(f"\n📊 RESUMO DA INVESTIGAÇÃO:")
        logger.info(f"   Vendas nos leads EXCLUÍDOS (sem UTM): {found_in_excluded}")
        logger.info(f"   Vendas de PERÍODO ANTERIOR: {found_before_period}")
        logger.info(f"   Vendas NÃO ENCONTRADAS: {not_found}")

    print("="*80 + "\n")

    # 6.1. Filtrar conversões por período de captura
    print("📅 FILTRANDO CONVERSÕES POR PERÍODO DE CAPTURA...", flush=True)
    print(flush=True)
    from src.validation.matching import filter_conversions_by_capture_period
    matched_df = filter_conversions_by_capture_period(
        matched_df,
        period_start=start_date,
        period_end=end_date
    )

    # 6.2. Remover duplicatas artificiais
    print("🧹 REMOVENDO DUPLICATAS ARTIFICIAIS...", flush=True)
    print(flush=True)
    from src.validation.matching import deduplicate_conversions
    matched_df = deduplicate_conversions(matched_df)

    matching_stats = get_matching_stats(matched_df, total_sales=len(sales_df))

    logger.info(f"   ✅ Conversões: {matching_stats['total_conversions']}")
    logger.info(f"   ✅ Taxa de conversão geral: {matching_stats['conversion_rate']:.2f}%")
    logger.info(f"   ✅ Match por email: {matching_stats['matched_by_email']}")
    logger.info(f"   ✅ Match por telefone: {matching_stats['matched_by_phone']}")
    print(flush=True)

    # 7. Reutilizar custos dos relatórios Meta já carregados
    print("💰 REUTILIZANDO CUSTOS DOS RELATÓRIOS META...", flush=True)
    print(flush=True)

    meta_api = None  # Não usar API, apenas relatórios locais
    costs_hierarchy_consolidated = costs_hierarchy_temp  # Reutilizar dados já carregados

    num_campaigns = len(costs_hierarchy_consolidated.get('campaigns', {}))
    if num_campaigns > 0:
        logger.info(f"   ✅ {num_campaigns} campanhas reutilizadas dos relatórios")
    else:
        logger.warning("   ⚠️ Nenhuma campanha encontrada nos relatórios")

    print(flush=True)

    # 8. Calcular métricas
    print("📊 CALCULANDO MÉTRICAS...", flush=True)
    print(flush=True)

    # Por campanha
    use_cache = not args.no_cache  # Usar cache por padrão, desabilitar se --no-cache
    campaign_calc = CampaignMetricsCalculator(
        meta_api if meta_api else None,
        config['product_value'],
        use_cache=use_cache
    )

    if not use_cache:
        logger.info("   ⚠️ Cache desabilitado - forçando busca de dados novos da Meta API")

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
    logger.info(f"   ✅ Métricas calculadas para {len(campaign_metrics)} campanhas")

    # Adicionar comparison_group ao campaign_metrics (se disponível)
    if 'comparison_group' in matched_df.columns and len(campaign_metrics) > 0:
        # Criar mapeamento campanha → comparison_group
        campaign_to_group = matched_df.groupby('campaign')['comparison_group'].first().to_dict()
        campaign_metrics['comparison_group'] = campaign_metrics['campaign'].map(campaign_to_group)
        logger.info(f"   ✅ Grupos de comparação adicionados às métricas de campanha")
    elif len(campaign_metrics) == 0:
        logger.warning("   ⚠️ Nenhuma métrica de campanha disponível - DataFrame vazio")

    # Por decil
    decile_calc = DecileMetricsCalculator()
    decile_metrics = decile_calc.calculate_decile_performance(
        matched_df,
        config['product_value']
    )
    logger.info(f"   ✅ Performance calculada para todos os decis (D1-D10)")

    # ML Model Performance Monitoring
    print(flush=True)
    print("📊 CALCULANDO MÉTRICAS DE MONITORAMENTO DO MODELO...", flush=True)
    print(flush=True)

    # Carregar modelo ativo do active_model.yaml
    active_model_path = get_active_model_path()
    model_metadata_path = str(active_model_path / "model_metadata_v1_devclub_rf_temporal_leads_single.json")

    ml_monitoring_calc = MLMonitoringCalculator(
        model_metadata_path=model_metadata_path
    )

    ml_monitoring_metrics = ml_monitoring_calc.calculate_all_metrics(
        matched_df=matched_df
    )

    # Log resumo no console
    logger.info(f"📈 AUC Produção: {ml_monitoring_metrics['auc']['production']:.4f} "
               f"(Test Set: {ml_monitoring_metrics['auc']['test_set']:.4f})")
    logger.info(f"📊 Top 3 Decis: {ml_monitoring_metrics['concentration']['top3_production']:.1f}% "
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
        logger.info(f"   ✅ Métricas calculadas por grupo de comparação")

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

            print("\n📊 COMPARAÇÃO DE ADSETS E ADS (relatórios locais)...", flush=True)
            print(flush=True)

            # Carregar adsets e ads dos relatórios Meta locais
            reports = loader.load_all_reports(start_date, end_date)
            adsets_df = reports.get('adsets', pd.DataFrame())
            ads_df = reports.get('ads', pd.DataFrame())

            if not adsets_df.empty:
                logger.info(f"   ✅ {len(adsets_df)} adsets carregados dos relatórios")

                # DEBUG: Verificar se total_spend existe
                if 'total_spend' in adsets_df.columns:
                    total_spend_sum = adsets_df['total_spend'].sum()
                    spend_sum = adsets_df['spend'].sum()
                    logger.info(f"   📊 DEBUG: total_spend existe em adsets_df")
                    logger.info(f"      Total spend (histórico): R$ {total_spend_sum:,.2f}")
                    logger.info(f"      Total spend (filtrado): R$ {spend_sum:,.2f}")
                else:
                    logger.warning(f"   ⚠️ DEBUG: total_spend NÃO existe em adsets_df")

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
                            if group == 'Eventos ML':
                                eventos_ml_campaign_ids.append(full_id)
                            elif group == 'Otimização ML':
                                otimizacao_ml_campaign_ids.append(full_id)
                            elif group == 'Controle':
                                control_campaign_ids.append(full_id)

                    logger.info(f"   📊 Campanhas por grupo:")
                    logger.info(f"      Eventos ML: {len(eventos_ml_campaign_ids)}")
                    logger.info(f"      Otimização ML: {len(otimizacao_ml_campaign_ids)}")
                    logger.info(f"      Controle: {len(control_campaign_ids)}")

                    # Criar ml_type_map para compatibilidade (COM_ML para Eventos e Otimização)
                    ml_type_map = {}
                    for cid_15, group in comparison_group_map.items():
                        if group in ['Eventos ML', 'Otimização ML']:
                            ml_type_map[cid_15] = 'COM_ML'
                        elif group == 'Controle':
                            ml_type_map[cid_15] = 'SEM_ML'
                else:
                    ml_type_map = {}
                    logger.warning("   ⚠️ comparison_group_map vazio, não será possível fazer comparação")

                # 1. Comparação de TODOS os adsets (Eventos ML vs Controle)
                all_adsets_comparison = compare_all_adsets_performance(
                    adsets_df=adsets_df,
                    matched_df=matched_df,
                    comparison_group_map=comparison_group_map,
                    product_value=config['product_value'],
                    min_spend=0.0,
                    config=config
                )
                logger.info(f"   ✅ Comparação de todos adsets concluída")

                # 2. Identificar matched adset pairs (Eventos ML vs Controle apenas)
                # IMPORTANTE: Usar apenas eventos_ml_campaign_ids (excluir Otimização ML)
                matched_adsets, matched_adsets_df = identify_matched_adset_pairs(
                    adsets_df=adsets_df,
                    ml_campaign_ids=eventos_ml_campaign_ids,  # Apenas Eventos ML!
                    control_campaign_ids=control_campaign_ids,
                    min_spend=0.0,
                    use_dynamic_matching=True  # Usar detecção dinâmica em vez de lista hardcoded
                )

                if matched_adsets:
                    logger.info(f"   ✅ {len(matched_adsets)} adsets matched identificados (Eventos ML vs Controle)")

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
                        logger.info(f"   ✅ Comparação de matched adsets concluída ({len(matched_adsets_df)} adsets)")
                    else:
                        logger.warning("   ⚠️ Nenhum adset matched encontrado após filtragem")
                        adset_level_comparisons = None
                else:
                    logger.warning("   ⚠️ Nenhum matched adset identificado")
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
                        logger.info(f"   ✅ {len(matched_adsets_faixa_a_list)} adsets matched identificados (Eventos ML vs Faixa A)")
                    else:
                        logger.info("   ℹ️ Nenhum adset matched encontrado entre Eventos ML e Faixa A")
                except Exception as e:
                    logger.warning(f"   ⚠️ Erro ao identificar matched adsets Faixa A: {e}")
                    matched_adsets_faixa_a = None

                # 3.1. Obter detalhes de cada instância de adset (Faixa A)
                try:
                    faixa_a_instances_detail = get_faixa_a_instances_detail(
                        eventos_ml_campaign_ids=eventos_ml_campaign_ids,
                        matched_df=matched_df
                    )
                    if not faixa_a_instances_detail.empty:
                        logger.info(f"   ✅ {len(faixa_a_instances_detail)} instâncias de adsets processadas (Eventos ML vs Faixa A)")
                    else:
                        logger.info("   ℹ️ Nenhuma instância de adset encontrada")
                except Exception as e:
                    logger.warning(f"   ⚠️ Erro ao obter detalhes de instâncias Faixa A: {e}")
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
                #     logger.info(f"   ✅ Comparação de ads concluída ({len(ad_level_comparisons.get('detailed_matched', pd.DataFrame()))} linhas)")
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
                #         logger.info(f"   ✅ Comparação de ads em adsets matched concluída")
                #     except Exception as e:
                #         logger.warning(f"   ⚠️  Erro na comparação de ads em adsets matched: {e}")
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
                #         logger.info(f"   ✅ Comparação de matched ads em adsets matched concluída")
                #     except Exception as e:
                #         logger.warning(f"   ⚠️  Erro na comparação de matched ads em adsets matched: {e}")
                #         matched_ads_in_matched_adsets_comparisons = None
                # else:
                #     logger.warning("   ⚠️ Nenhum adset matched encontrado (comparações específicas não disponíveis)")
            else:
                logger.warning("   ⚠️ Nenhum adset carregado dos relatórios")

        except Exception as e:
            logger.error(f"   ❌ Erro na comparação de adsets/ads: {e}")
            import traceback
            traceback.print_exc()

    print(flush=True)

    # 9. EXIBIR RESUMO NO TERMINAL
    print("=" * 80, flush=True)
    print("📊 RESUMO EXECUTIVO - COMPARAÇÃO ML vs NÃO-ML", flush=True)
    print("=" * 80, flush=True)
    print(flush=True)
    print_summary_table(ml_comparison)

    print(flush=True)
    print("=" * 80, flush=True)
    print("📈 PERFORMANCE POR DECIL (Real vs Esperado)", flush=True)
    print("=" * 80, flush=True)
    print("IMPORTANTE: Modelo treinado APENAS com vendas Guru", flush=True)
    print("→ Guru = Dados de treinamento | Total = Guru + TMB (generalização)", flush=True)
    print(flush=True)
    print_decile_table(decile_metrics)

    print(flush=True)

    # 9.5. Exibir métricas por campanha
    print("=" * 80, flush=True)
    print("📊 MÉTRICAS DETALHADAS POR CAMPANHA", flush=True)
    print("=" * 80, flush=True)
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
    print("📄 Gerando relatório Excel...", flush=True)
    os.makedirs(output_dir, exist_ok=True)

    # Sempre adicionar timestamp no nome do arquivo (nunca sobrescreve)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Adicionar prefixo baseado no tipo de relatório
    report_type_prefix = args.report_type.upper().replace('-', '_')
    excel_filename = f"validation_report_{report_type_prefix}_{start_date}_to_{end_date}_{timestamp}.xlsx"
    excel_path = str(Path(output_dir) / excel_filename)
    logger.info(f"   📌 Criando relatório: {excel_filename}")

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
        ml_monitoring_metrics=ml_monitoring_metrics
    )
    print(f"   ✅ Excel salvo: {excel_path}", flush=True)
    print(flush=True)

    # 11. Gerar gráficos
    # DESABILITADO: Gerando apenas análise em console até finalizar formato
    # print("📈 Gerando visualizações...")
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

    print("=" * 80, flush=True)
    print("✅ VALIDAÇÃO CONCLUÍDA COM SUCESSO!", flush=True)
    print("=" * 80, flush=True)
    print(flush=True)
    print(f"📊 Análise exibida no console acima", flush=True)
    print(f"📄 Excel atualizado: {excel_path}", flush=True)
    print(f"⏱️  Tempo de execução: {elapsed_time:.1f} segundos ({elapsed_time/60:.1f} minutos)", flush=True)
    print(flush=True)

    # 13. Upload para Cloud Storage (se configurado)
    excel_url = None
    bucket_name = os.getenv('VALIDATION_REPORTS_BUCKET')

    if bucket_name:
        try:
            from google.cloud import storage

            print("☁️  Fazendo upload para Cloud Storage...", flush=True)

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
            print(f"   ✅ Upload concluído: {excel_url}", flush=True)

        except Exception as storage_error:
            print(f"   ⚠️  Erro no upload Cloud Storage: {storage_error}", flush=True)
            excel_url = None
    else:
        print("   ℹ️  VALIDATION_REPORTS_BUCKET não configurado, upload ignorado", flush=True)

    print(flush=True)

    # 14. Enviar notificação Slack (se configurado)
    slack_webhook = os.getenv('SLACK_WEBHOOK_URL')

    if slack_webhook:
        try:
            from src.validation.slack_notifier import ValidationSlackNotifier

            print("📱 Enviando notificação Slack...", flush=True)

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
                period=slack_period
            )

            if success:
                print("   ✅ Notificação Slack enviada", flush=True)
            else:
                print("   ⚠️  Falha ao enviar notificação Slack", flush=True)

        except Exception as slack_error:
            print(f"   ⚠️  Erro ao enviar Slack: {slack_error}", flush=True)
    else:
        print("   ℹ️  SLACK_WEBHOOK_URL não configurado, notificação ignorada", flush=True)

    print(flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Operação cancelada pelo usuário")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
