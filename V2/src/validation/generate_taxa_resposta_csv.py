"""
Script para gerar CSV com taxa de resposta diária (Leads CAPI vs Respostas Pesquisa)

Gera arquivo CSV com:
- Data
- Dia_Semana
- Leads_CAPI (contados do banco PostgreSQL via API)
- Respostas_Pesquisa (contados das 2 primeiras abas do Google Sheets)
- Taxa_Resposta_% (Respostas ÷ Leads_CAPI × 100)

Uso:
    python generate_taxa_resposta_csv.py --start-date 2025-12-30 --end-date 2026-01-21
"""

import pandas as pd
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta
import subprocess
import json
from typing import Dict, List
import argparse

# Adicionar path do projeto
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.validation.data_loader import LeadDataLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

API_URL = "https://smart-ads-api-12955519745.us-central1.run.app"


def get_capi_leads_by_day(start_date: str, end_date: str) -> Dict[str, int]:
    """
    Busca leads do banco CAPI via API e conta por dia.

    Args:
        start_date: Data início (YYYY-MM-DD)
        end_date: Data fim (YYYY-MM-DD)

    Returns:
        Dict {data: count} com contagem de leads únicos por dia
    """
    logger.info(f"📊 Buscando leads CAPI ({start_date} a {end_date})")

    url = f"{API_URL}/webhook/lead_capture/recent?start_date={start_date}&end_date={end_date}&limit=10000"

    try:
        # Usar curl (mais confiável que requests neste ambiente)
        result = subprocess.run(
            ['curl', '-s', '--max-time', '60', url],
            capture_output=True,
            text=True,
            timeout=65
        )

        if result.returncode != 0:
            logger.error(f"❌ Curl falhou: {result.stderr}")
            return {}

        response_data = json.loads(result.stdout)
        leads = response_data.get('leads', [])

        logger.info(f"   ✅ {len(leads)} leads encontrados no CAPI")

        # Converter para DataFrame
        df = pd.DataFrame(leads)

        if len(df) == 0:
            logger.warning("   ⚠️ Nenhum lead no período")
            return {}

        # Parsear created_at e extrair data
        df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce')
        df['date'] = df['created_at'].dt.date

        # Contar EMAILS ÚNICOS por dia (deduplicar por email + data)
        # IMPORTANTE: Mesmo email pode aparecer múltiplas vezes (duplicatas no banco)
        df_unique = df[['email', 'date']].drop_duplicates()

        # Contar por dia
        daily_counts = df_unique['date'].value_counts().to_dict()

        # Converter date objects para strings
        daily_counts_str = {str(date): count for date, count in daily_counts.items()}

        logger.info(f"   📊 Leads CAPI distribuídos em {len(daily_counts_str)} dias")

        return daily_counts_str

    except Exception as e:
        logger.error(f"❌ Erro ao buscar leads CAPI: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}


def get_survey_responses_by_day(start_date: str, end_date: str) -> Dict[str, int]:
    """
    Busca respostas da pesquisa do Google Sheets (2 primeiras abas) e conta por dia.

    Args:
        start_date: Data início (YYYY-MM-DD)
        end_date: Data fim (YYYY-MM-DD)

    Returns:
        Dict {data: count} com contagem de respostas por dia
    """
    logger.info(f"📋 Buscando respostas da pesquisa ({start_date} a {end_date})")

    try:
        loader = LeadDataLoader()

        # Carregar leads do Google Sheets (2 primeiras abas)
        # IMPORTANTE: use_cache=False para garantir dados atualizados
        df = loader.load_leads_from_sheets(
            start_date=start_date,
            end_date=end_date,
            use_cache=False
        )

        if len(df) == 0:
            logger.warning("   ⚠️ Nenhuma resposta no período")
            return {}

        logger.info(f"   ✅ {len(df)} respostas encontradas no Google Sheets")

        # Extrair data da coluna data_captura
        df['date'] = df['data_captura'].dt.date

        # Contar EMAILS ÚNICOS por dia (mesma lógica do CAPI)
        df_unique = df[['email', 'date']].drop_duplicates()

        # Contar por dia
        daily_counts = df_unique['date'].value_counts().to_dict()

        # Converter date objects para strings
        daily_counts_str = {str(date): count for date, count in daily_counts.items()}

        logger.info(f"   📊 Respostas distribuídas em {len(daily_counts_str)} dias")

        return daily_counts_str

    except Exception as e:
        logger.error(f"❌ Erro ao buscar respostas da pesquisa: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}


def generate_daily_report(start_date: str, end_date: str, output_path: str):
    """
    Gera CSV com taxa de resposta diária.

    Args:
        start_date: Data início (YYYY-MM-DD)
        end_date: Data fim (YYYY-MM-DD)
        output_path: Caminho do arquivo CSV de saída
    """
    logger.info("="*80)
    logger.info("📊 GERANDO RELATÓRIO DE TAXA DE RESPOSTA DIÁRIA")
    logger.info("="*80)
    logger.info(f"   Período: {start_date} a {end_date}")
    logger.info(f"   Output: {output_path}")

    # 1. Buscar dados CAPI
    capi_by_day = get_capi_leads_by_day(start_date, end_date)

    # 2. Buscar respostas da pesquisa
    survey_by_day = get_survey_responses_by_day(start_date, end_date)

    # 3. Gerar range de datas
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')

    date_range = []
    current_dt = start_dt
    while current_dt <= end_dt:
        date_range.append(current_dt)
        current_dt += timedelta(days=1)

    logger.info(f"   📅 Gerando dados para {len(date_range)} dias")

    # 4. Montar DataFrame
    rows = []
    for dt in date_range:
        date_str = dt.strftime('%Y-%m-%d')
        date_display = dt.strftime('%d/%m/%Y')
        weekday = dt.strftime('%A')  # Monday, Tuesday, etc.

        # Contar leads CAPI e respostas
        capi_count = capi_by_day.get(date_str, 0)
        survey_count = survey_by_day.get(date_str, 0)

        # Calcular taxa de resposta
        if capi_count > 0:
            taxa = round(survey_count / capi_count * 100, 1)
        else:
            # Se não há leads CAPI mas há respostas, algo está errado
            taxa = 0 if survey_count == 0 else 0

        rows.append({
            'Data': date_display,
            'Dia_Semana': weekday,
            'Leads_CAPI': capi_count,
            'Respostas_Pesquisa': survey_count,
            'Taxa_Resposta_%': taxa
        })

    df = pd.DataFrame(rows)

    # 5. Salvar CSV
    df.to_csv(output_path, index=False)

    logger.info("="*80)
    logger.info("✅ RELATÓRIO GERADO COM SUCESSO")
    logger.info("="*80)
    logger.info(f"   Arquivo: {output_path}")
    logger.info(f"   Total de dias: {len(df)}")
    logger.info(f"   Total Leads CAPI: {df['Leads_CAPI'].sum()}")
    logger.info(f"   Total Respostas Pesquisa: {df['Respostas_Pesquisa'].sum()}")

    # Calcular taxa média (ponderada)
    total_capi = df['Leads_CAPI'].sum()
    total_survey = df['Respostas_Pesquisa'].sum()
    if total_capi > 0:
        taxa_media = round(total_survey / total_capi * 100, 1)
        logger.info(f"   Taxa Resposta Média: {taxa_media}%")

    # Mostrar primeiras 5 linhas
    logger.info("\n   📋 Primeiras 5 linhas:")
    print(df.head(5).to_string(index=False))

    # Estatísticas de qualidade
    dias_com_dados = len(df[(df['Leads_CAPI'] > 0) | (df['Respostas_Pesquisa'] > 0)])
    dias_sem_capi = len(df[df['Leads_CAPI'] == 0])
    dias_taxa_anormal = len(df[df['Taxa_Resposta_%'] > 100])

    logger.info(f"\n   📊 Estatísticas:")
    logger.info(f"      Dias com dados: {dias_com_dados}/{len(df)}")
    logger.info(f"      Dias sem CAPI (possível problema): {dias_sem_capi}")
    logger.info(f"      Dias com taxa >100% (possível duplicação): {dias_taxa_anormal}")


def merge_with_existing_csv(old_csv_path: str, new_csv_path: str, merged_csv_path: str):
    """
    Mescla CSV antigo com novo CSV, removendo duplicatas e ordenando por data.

    Args:
        old_csv_path: Caminho do CSV antigo
        new_csv_path: Caminho do CSV novo gerado
        merged_csv_path: Caminho do CSV mesclado final
    """
    logger.info("="*80)
    logger.info("🔗 MESCLANDO CSV ANTIGO + NOVO")
    logger.info("="*80)

    # Ler ambos CSVs
    df_old = pd.read_csv(old_csv_path)
    df_new = pd.read_csv(new_csv_path)

    logger.info(f"   CSV antigo: {len(df_old)} linhas ({old_csv_path})")
    logger.info(f"   CSV novo: {len(df_new)} linhas ({new_csv_path})")

    # Combinar
    df_merged = pd.concat([df_old, df_new], ignore_index=True)

    # Parsear datas para poder ordenar e deduplicar
    df_merged['Data_dt'] = pd.to_datetime(df_merged['Data'], format='%d/%m/%Y')

    # Remover duplicatas (manter mais recente)
    before = len(df_merged)
    df_merged = df_merged.sort_values('Data_dt').drop_duplicates(subset=['Data'], keep='last')
    after = len(df_merged)

    if before != after:
        logger.info(f"   🔄 Removidas {before - after} duplicatas")

    # Ordenar por data
    df_merged = df_merged.sort_values('Data_dt')

    # Remover coluna auxiliar
    df_merged = df_merged.drop(columns=['Data_dt'])

    # Salvar
    df_merged.to_csv(merged_csv_path, index=False)

    logger.info("="*80)
    logger.info("✅ CSV MESCLADO COM SUCESSO")
    logger.info("="*80)
    logger.info(f"   Arquivo: {merged_csv_path}")
    logger.info(f"   Total de dias: {len(df_merged)}")
    logger.info(f"   Período: {df_merged['Data'].iloc[0]} a {df_merged['Data'].iloc[-1]}")


def main():
    parser = argparse.ArgumentParser(description='Gera CSV com taxa de resposta diária')
    parser.add_argument('--start-date', required=True, help='Data início (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='Data fim (YYYY-MM-DD)')
    parser.add_argument('--output', default=None, help='Caminho do arquivo CSV de saída')
    parser.add_argument('--merge-with', default=None, help='CSV antigo para mesclar (opcional)')

    args = parser.parse_args()

    # Determinar output path
    if args.output:
        output_path = args.output
    else:
        files_dir = Path(__file__).parent.parent.parent / 'files'
        output_path = str(files_dir / f'devclub_taxa_resposta_{args.start_date}_to_{args.end_date}.csv')

    # Gerar relatório
    generate_daily_report(args.start_date, args.end_date, output_path)

    # Mesclar com CSV antigo se especificado
    if args.merge_with:
        merged_path = output_path.replace('.csv', '_merged.csv')
        merge_with_existing_csv(args.merge_with, output_path, merged_path)
        logger.info(f"\n   💾 CSV final mesclado: {merged_path}")


if __name__ == '__main__':
    main()
