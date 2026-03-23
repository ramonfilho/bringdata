"""
Pipeline de treino - Reproduz notebook DevClub célula por célula.

Integra funções modularizadas conforme são aprovadas.
"""

import sys
import os
import logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Carregar variáveis de ambiente do .env (deve ser ANTES de qualquer import que use os.getenv)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
except ImportError:
    pass

import json
import yaml
import glob
import logging
import argparse
import pandas as pd
import atexit
import time
from datetime import datetime
from src.data_processing.ingestion import (
    read_excel_files,
    read_all_training_sources,
    filter_sheets,
    remove_duplicates_per_sheet,
    remove_unnecessary_columns,
    consolidate_datasets
)
from src.core.column_unification import (
    unify_survey_columns as _unify_survey,
    unify_sales_columns as _unify_sales,
    aplicar_filtro_temporal as _filtro_temporal,
    remover_colunas_utm_ausentes as _remover_utm,
)
from src.core.ingestion import (
    aplicar_filtro_status_risco as _filtro_status_risco,
    filter_sales_by_product as _filtrar_produto,
)
from src.core.category_unification import unify_categories as _unify_categories
from src.data_processing.feature_removal import remover_features_desnecessarias, listar_colunas_restantes
from src.core.client_config import ClientConfig
from src.core.utm import unify_utm
from src.core.medium import unify_medium
from src.core.dataset_versioning import criar_dataset_pos_cutoff, aplicar_janela_conversao as _aplicar_janela_conversao
from src.core.matching import match_leads as _match_leads
from src.core.feature_engineering import create_features as _create_features
from src.core.encoding import apply_encoding as _apply_encoding
from src.model.training_model import registrar_features_e_modelo_devclub
from src.model.hyperparameter_tuning import hyperparameter_tuning
from src.monitoring.data_quality import capture_training_categories, capture_training_distributions, calculate_missing_rate

# Logging será configurado no main() via setup_logging(verbosity)



def setup_output_logging(output_subdir='training'):
    """
    Configura redirecionamento automático de output para arquivo timestampado.

    Args:
        output_subdir: Subdiretório dentro de outputs/ (default: 'training')
                      Ex: 'retraining' para outputs/retraining/
    """
    # Criar diretório outputs/{subdir} se não existir
    outputs_dir = os.path.join(os.path.dirname(__file__), f'../outputs/{output_subdir}')
    os.makedirs(outputs_dir, exist_ok=True)

    # Gerar timestamp no formato YYYYMMDD_HHMMSS
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_prefix = 'retraining' if output_subdir == 'retraining' else 'training'
    log_path = os.path.join(outputs_dir, f'{log_prefix}_{timestamp}.log')

    return log_path



class _TrainingFormatter(logging.Formatter):
    """
    Formatter que garante que todas as linhas tenham timestamp.

    Mensagens com \\n inicial eram usadas para adicionar separação visual,
    mas causavam linhas sem timestamp no log. Este formatter detecta esse
    padrão e emite uma linha em branco (com timestamp) antes do conteúdo.
    """

    def format(self, record):
        import copy
        if isinstance(record.msg, str) and record.msg.startswith('\n'):
            blank = copy.copy(record)
            blank.msg = ''
            blank.args = ()
            content = copy.copy(record)
            content.msg = record.msg.lstrip('\n')
            return super().format(blank) + '\n' + super().format(content)
        return super().format(record)


def setup_logging(verbosity='normal', log_file=None):
    """
    Configura logging com níveis de verbosidade

    Args:
        verbosity: Nível de verbosidade
            - 'silent': Apenas erros críticos
            - 'minimal': Warnings + erros
            - 'normal': Info + warnings + erros (padrão)
            - 'debug': Todos os logs incluindo análises detalhadas
        log_file: Caminho do arquivo de log (opcional)
    """
    LEVEL_MAP = {
        'silent': logging.ERROR,
        'minimal': logging.WARNING,
        'normal': logging.INFO,
        'debug': logging.DEBUG
    }

    # Limpar handlers existentes para evitar duplicação
    root_logger = logging.getLogger()
    root_logger.handlers = []

    # Formato de log
    log_format = '%(asctime)s [%(levelname)-8s] %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # Handler para arquivo (obrigatório — garante que o log vai para outputs/training/)
    # Usar FileHandler diretamente evita qualquer redirecionamento de shell (> /tmp/...)
    if log_file:
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setFormatter(_TrainingFormatter(log_format, datefmt=date_format))
        root_logger.addHandler(file_handler)

    # Handler para stderr (não afetado por redirecionamento de stdout)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(_TrainingFormatter(log_format, datefmt=date_format))
    root_logger.addHandler(stderr_handler)

    # Configurar nível
    root_logger.setLevel(LEVEL_MAP.get(verbosity, logging.INFO))

    # Suprimir loggers verbosos de bibliotecas externas
    for noisy_logger in ('urllib3', 'urllib3.connectionpool', 'urllib3.util.retry',
                         'requests', 'google.auth', 'google.auth._default',
                         'google.auth.transport', 'googleapiclient'):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# Logger global do módulo
logger = logging.getLogger(__name__)


def main(initial_matching='email_telefone', save_files=False, save_test_predictions=False, tune_hyperparams=False, grid_size='small', split_method='temporal_leads', tmb_risk_filter='all', set_active=False, medium_strategy='binary_top3', validation_hook=None, quality_gate_hook=None, include_api_data=True, include_sheets_api=True, api_start_date=None, api_end_date=None, output_subdir='training', verbosity='normal', capture_parity_snapshots=False, use_buyer_weights=True, save_encoded=False, cli_args=None, use_cached_data=False, fixed_hyperparams=None, max_date=None):
    """Executa pipeline de treino completo.

    Args:
        initial_matching: Método de matching inicial na célula 15
                         ('email_only', 'email_telefone', 'variantes', 'robusto' ou 'validation')
        medium_strategy: Estratégia para Medium ('full', 'binary_aberto', 'binary_aberto_dgen', 'remove')
        split_method: Método de split do train/test
                     - 'temporal': 70% dos DIAS para treino (split clássico por período)
                     - 'temporal_leads': 70% dos LEADS para treino (ordenados por data, test set mais recente)
                     - 'stratified': 70% dos registros com stratified split por pessoa
        save_files: Se True, salva arquivos locais em files/{timestamp}
        tune_hyperparams: Se True, executa hyperparameter tuning antes do treino
        grid_size: Tamanho do grid search ('small', 'medium', 'large')
        tmb_risk_filter: Filtro de risco para alunos TMB
                        - 'all': Todos alunos TMB (padrão)
                        - 'none': Nenhum aluno TMB (só Guru)
                        - 'low': Apenas baixo risco
                        - 'low_medium': Baixo + médio risco
        set_active: Se True, atualiza configs/active_model.yaml com este modelo (requer save_files=True)
        validation_hook: Função opcional chamada após feature engineering para validação.
                        Recebe dataset_fe e retorna True (continuar) ou False (abortar)
        include_api_data: Se True (padrão), busca dados adicionais de API/Guru e Google Sheets
        include_sheets_api: Se True (padrão), busca leads do Google Sheets quando include_api_data=True.
                            Passar False quando os leads já foram baixados manualmente como Excel.
        api_start_date: Data início para buscar dados da API (YYYY-MM-DD)
        api_end_date: Data fim para buscar dados da API (YYYY-MM-DD)
        output_subdir: Subdiretório para logs ('training' ou 'retraining')
        capture_parity_snapshots: Se True, serializa (input, output) de cada função
                                  compartilhada em tests/fixtures/ para o audit de paridade.
                                  Usar apenas uma vez para gerar os snapshots baseline.
    """

    # Configurar caminho do arquivo de log
    log_path = setup_output_logging(output_subdir)

    # Configurar logging com nível de verbosidade e arquivo de log
    setup_logging(verbosity, log_file=log_path)

    # Backward compatibility: se save_files=True, ativar save_test_predictions
    if save_files and not save_test_predictions:
        logger.warning("⚠️  --save-files está DEPRECADO, use --save-test-predictions")
        save_test_predictions = True

    # Registrar função de cleanup para mensagem final
    def cleanup():
        logger.info("")
        logger.info(f" Pipeline concluído! Output salvo em: {log_path}")
        # FileHandlers são fechados automaticamente ao finalizar

    atexit.register(cleanup)

    # Carregar ClientConfig — usado progressivamente à medida que core/ é implementado
    _config_path = os.path.join(os.path.dirname(__file__), '..', 'configs', 'clients', 'devclub.yaml')
    client_config = ClientConfig.from_yaml(os.path.abspath(_config_path))

    logger.info("")
    logger.info("PIPELINE DE TREINO")
    logger.info("")
    logger.info(f"Output sendo salvo em: {log_path}")
    logger.info("")
    logger.info(f"CONFIGURAÇÃO:")
    logger.info(f"  Método de matching inicial (célula 15): {initial_matching}")
    logger.info(f"  Salvar arquivos locais: {save_files}")
    logger.info(f"  Hyperparameter tuning: {tune_hyperparams}")
    if tune_hyperparams:
        logger.info(f"  Grid size: {grid_size}")
    logger.info("=" * 80)

    # Carregar configuração
    config_path = os.path.join(os.path.dirname(__file__), '../configs/devclub.yaml')
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Timers para cada célula
    cell_timers = {}
    pipeline_start_time = time.time()

    # === CÉLULA 1: Upload/Leitura de arquivos ===
    cell_start = time.time()
    logger.info("")
    logger.info("CÉLULA 1: LEITURA DE ARQUIVOS")
    logger.info("")
    data_dir = config['ingestion']['training_data_dir']

    # Custom sorting para replicar ordem do notebook
    # No notebook, arquivos foram carregados via upload do Colab que preserva
    # a ordem do file picker (macOS/Linux), onde "[" vem antes de letras
    def notebook_sort_key(filepath):
        """Ordena arquivos para replicar a ordem do notebook."""
        basename = os.path.basename(filepath).lower()
        # Converter '[' para um caractere que vem antes de letras na ordenação
        # Usar '!' que tem ASCII 33, bem antes de letras
        return basename.replace('[', '!')

    filepaths = sorted(glob.glob(os.path.join(data_dir, "*.xlsx")), key=notebook_sort_key)

    # NORMAL: Número de arquivos + fonte de dados
    logger.info(f"  Arquivos carregados: {len(filepaths)}")

    # Fonte de dados
    if include_api_data:
        fontes = ["Arquivos locais", "API Guru"]
        if include_sheets_api:
            fontes.append("Google Sheets API")
        logger.info(f"  Fonte de dados: {' + '.join(fontes)}")
        if api_start_date or api_end_date:
            logger.debug(f"   Período API: {api_start_date or 'início'} até {api_end_date or 'hoje'}")
    else:
        logger.info(f"  Fonte de dados: Arquivos locais")
    logger.info("")

    # DEBUG: Lista completa de arquivos
    logger.debug(f"\nLista de arquivos:")
    for f in filepaths:
        logger.debug(f"  - {os.path.basename(f)}")

    # DEBUG: Detalhes do filtro TMB
    logger.debug(f"\n FILTRO TMB (tmb_risk_filter='{tmb_risk_filter}'):")
    if tmb_risk_filter == 'none':
        logger.debug(f"   - Vendas Guru + TMB usadas para cálculo do recall")
        logger.debug(f"   - Apenas vendas Guru usadas para matching/treino")
    elif tmb_risk_filter == 'all':
        logger.debug(f"   - Usando vendas Guru + TODOS alunos TMB")
    elif tmb_risk_filter == 'low':
        logger.debug(f"   - Usando vendas Guru + alunos TMB de BAIXO risco")
    elif tmb_risk_filter == 'low_medium':
        logger.debug(f"   - Usando vendas Guru + alunos TMB de BAIXO e MÉDIO risco")

    # Ler TODOS os arquivos (incluindo TMB) + dados da API se retreino
    _cache_dir = os.path.join(os.path.dirname(__file__), '..', 'outputs', 'cache')
    _cache_key = api_end_date or 'latest'
    _cache_path = os.path.join(_cache_dir, f'raw_data_{_cache_key}.pkl')

    if use_cached_data and os.path.exists(_cache_path):
        import pickle
        logger.info(f"  Carregando dados do cache: {os.path.basename(_cache_path)}")
        with open(_cache_path, 'rb') as f:
            all_data = pickle.load(f)
    else:
        all_data = read_all_training_sources(
            filepaths,
            include_api_data=include_api_data,
            api_start_date=api_start_date,
            api_end_date=api_end_date,
            num_sheets_api=1,  # Retreino: apenas aba 0 do Google Sheets
            include_sheets_api=include_sheets_api
        )
        import pickle
        os.makedirs(_cache_dir, exist_ok=True)
        with open(_cache_path, 'wb') as f:
            pickle.dump(all_data, f)
        logger.info(f"  Cache salvo: {os.path.basename(_cache_path)}")

    cell_timers['Célula 1'] = time.time() - cell_start
    logger.info(f"   Tempo: {cell_timers['Célula 1']:.1f}s")
    logger.info("=" * 80)
    # === CÉLULA 2: Filtragem + Remoção de Duplicatas ===
    cell_start = time.time()
    logger.info("")
    logger.info("CÉLULA 2: FILTRAGEM DE ABAS + REMOÇÃO DE DUPLICATAS")
    logger.info("")

    # Filtrar abas
    filtered_data, filter_report = filter_sheets(
        all_data,
        termos_manter=config['ingestion']['termos_manter'],
        termos_remover=config['ingestion']['termos_remover'],
        min_linhas=config['ingestion']['min_linhas']
    )

    # Remover duplicatas
    clean_data, dup_stats = remove_duplicates_per_sheet(filtered_data)

    # Calcular totais
    total_original = 0
    total_final = 0
    total_duplicatas = 0

    for item in filter_report:
        if item['status'] == 'MANTIDA':
            filename = item['arquivo']
            sheet_name = item['aba']
            linhas_original = item['linhas_original']

            # Pegar estatísticas de duplicatas
            duplicatas = dup_stats.get(filename, {}).get(sheet_name, 0)
            linhas_final = linhas_original - duplicatas

            total_original += linhas_original
            total_final += linhas_final
            total_duplicatas += duplicatas

    # Contar abas
    abas_mantidas = sum(1 for item in filter_report if item['status'] == 'MANTIDA')
    abas_removidas = len(filter_report) - abas_mantidas

    # NORMAL: Apenas resumo final
    logger.info(f"  Arquivos processados: {len(clean_data)}")
    logger.info(f"  Abas mantidas: {abas_mantidas}")
    logger.info(f"  Abas removidas: {abas_removidas}")
    logger.info(f"  Linhas totais após processamento: {total_final:,}")
    logger.info(f"  Duplicatas removidas: {total_duplicatas:,}")
    if total_original > 0:
        logger.info(f"  Redução por duplicatas: {(total_duplicatas/total_original*100):.2f}%")
    logger.info("")

    # DEBUG: Tabela detalhada
    logger.debug(f"\n TABELA DETALHADA - ABAS MANTIDAS E PROCESSADAS")
    logger.debug("=" * 80)
    logger.debug(f"{'ARQUIVO':<35} {'ABA':<20} {'ORIGINAL':>10} {'FINAL':>10} {'REMOVIDAS':>10}")
    logger.debug("-" * 80)

    for item in filter_report:
        if item['status'] == 'MANTIDA':
            filename = item['arquivo']
            sheet_name = item['aba']
            linhas_original = item['linhas_original']

            # Pegar estatísticas de duplicatas
            duplicatas = dup_stats.get(filename, {}).get(sheet_name, 0)
            linhas_final = linhas_original - duplicatas

            logger.debug(f"{filename[:34]:<35} {sheet_name[:19]:<20} "
                        f"{linhas_original:>10,} {linhas_final:>10,} {duplicatas:>10,}")

    logger.debug("-" * 80)
    logger.debug(f"{'TOTAL':<35} {'':<20} {total_original:>10,} {total_final:>10,} {total_duplicatas:>10,}")
    logger.debug("=" * 80)

    cell_timers['Célula 2'] = time.time() - cell_start
    logger.info(f"   Tempo: {cell_timers['Célula 2']:.1f}s")

    # === CÉLULA 3: Remoção de colunas desnecessárias ===
    logger.info("=" * 80)
    logger.info("")
    logger.info("CÉLULA 3: REMOÇÃO DE COLUNAS DESNECESSÁRIAS")
    logger.info("")

    clean_data_cols, cols_report = remove_unnecessary_columns(
        clean_data,
        colunas_remover=config['cleaning']['colunas_remover']
    )

    # Calcular totais
    total_antes = 0
    total_depois = 0
    total_removidas_cols = 0

    for item in cols_report:
        total_antes += item['colunas_antes']
        total_depois += item['colunas_depois']
        total_removidas_cols += item['removidas']

    # DEBUG: Tabela detalhada
    logger.debug(f"\n COLUNAS REMOVIDAS POR ABA")
    logger.debug("=" * 80)
    logger.debug(f"{'ARQUIVO':<35} {'ABA':<20} {'ANTES':>10} {'DEPOIS':>10} {'REMOVIDAS':>10}")
    logger.debug("-" * 80)

    for item in cols_report:
        logger.debug(f"{item['arquivo'][:34]:<35} {item['aba'][:19]:<20} "
                    f"{item['colunas_antes']:>10} {item['colunas_depois']:>10} {item['removidas']:>10}")

    logger.debug("-" * 80)
    logger.debug(f"{'TOTAL':<35} {'':<20} {total_antes:>10} {total_depois:>10} {total_removidas_cols:>10}")

    logger.info(f"  Total de colunas removidas: {total_removidas_cols}")
    logger.info("")

    # === CÉLULA 4: Consolidação de datasets ===
    logger.info("=" * 80)
    logger.info("")
    logger.info("CÉLULA 4: CONSOLIDAÇÃO DE DATASETS - PESQUISA E VENDAS")
    logger.info("")

    df_pesquisa, df_vendas, tmb_risk_lookup = consolidate_datasets(
        clean_data_cols,
        pesquisa_keywords=config['consolidation']['pesquisa_keywords'],
        vendas_keywords=config['consolidation']['vendas_keywords']
    )

    # Função para gerar relatório de colunas (igual ao notebook)
    def gerar_relatorio_colunas(df, nome_dataset):
        """Gera relatório detalhado das colunas de um dataset"""

        logger.debug(f"\n{nome_dataset.upper()} - {len(df)} registros")
        logger.debug("=" * 70)
        logger.debug(f"{'COLUNA':<35} {'ÚNICOS':>10} {'% AUSENTES':>12} {'TOTAL':>10}")
        logger.debug("-" * 70)

        for col in df.columns:
            valores_unicos = df[col].nunique()
            valores_ausentes = df[col].isnull().sum()
            pct_ausentes = (valores_ausentes / len(df)) * 100 if len(df) > 0 else 0
            total_registros = len(df)

            logger.debug(f"{col[:34]:<35} {valores_unicos:>10,} {pct_ausentes:>11.1f}% {total_registros:>10,}")

    # Gerar relatórios
    gerar_relatorio_colunas(df_pesquisa, "DATASET PESQUISA")
    gerar_relatorio_colunas(df_vendas, "DATASET VENDAS")

    logger.info(f"  Dataset Pesquisa: {len(df_pesquisa):,} registros, {len(df_pesquisa.columns)} colunas")
    logger.info(f"  Dataset Vendas: {len(df_vendas):,} registros, {len(df_vendas.columns)} colunas")
    logger.info("")

    # Filtro de data máxima — para reproduzir runs anteriores com o mesmo corte temporal
    if max_date:
        max_date_ts = pd.Timestamp(max_date)
        if 'Data' in df_pesquisa.columns:
            df_pesquisa['Data'] = pd.to_datetime(df_pesquisa['Data'], errors='coerce', dayfirst=True)
            antes = len(df_pesquisa)
            df_pesquisa = df_pesquisa[df_pesquisa['Data'] <= max_date_ts].copy()
            logger.info(f"  --max-date {max_date}: pesquisa {antes:,} → {len(df_pesquisa):,} registros")
        if 'data' in df_vendas.columns:
            df_vendas['data'] = pd.to_datetime(df_vendas['data'], errors='coerce', dayfirst=True)
            antes = len(df_vendas)
            df_vendas = df_vendas[df_vendas['data'] <= max_date_ts].copy()
            logger.info(f"  --max-date {max_date}: vendas {antes:,} → {len(df_vendas):,} registros")
        logger.info("")

    logger.info("=" * 80)
    logger.info("")

    # === CÉLULA 5: Unificação de colunas duplicadas ===
    logger.info("CÉLULA 5: UNIFICAÇÃO DE COLUNAS DUPLICADAS")
    logger.info("")

    # Parte 1: Unificar colunas de PESQUISA
    df_pesquisa_unificado = _unify_survey(df_pesquisa, client_config.ingestion)

    # Parte 2: Unificar colunas de VENDAS
    df_vendas_unificado = _unify_sales(df_vendas, client_config.ingestion)

    logger.info("=" * 80)
    # === CÉLULA 5.1: Filtro temporal ===
    logger.info("")
    logger.info("CÉLULA 5.1: FILTRO TEMPORAL")
    logger.info("")

    df_vendas_temporal = _filtro_temporal(df_vendas_unificado, df_pesquisa_unificado, client_config.ingestion)

    logger.info("=" * 80)
    # === CÉLULA 5.2: Remoção de colunas UTM ===
    logger.info("")
    logger.info("CÉLULA 5.2: REMOÇÃO DE COLUNAS UTM COM ALTA % AUSENTES")
    logger.info("")

    df_vendas_sem_utm = _remover_utm(df_vendas_temporal, client_config.ingestion)

    logger.info("=" * 80)
    # === CÉLULA 5.3: Filtro de status e risco ===
    logger.info("")
    logger.info("CÉLULA 5.3: FILTRO DE STATUS E RISCO")
    logger.info("")

    df_vendas_filtrado = _filtro_status_risco(df_vendas_sem_utm, client_config.ingestion, tmb_risk_filter=tmb_risk_filter, tmb_risk_lookup=tmb_risk_lookup)

    logger.info("=" * 80)
    # === CÉLULA 5.4: Filtro de produtos DevClub ===
    logger.info("")
    logger.info("CÉLULA 5.4: FILTRO DE PRODUTOS DEVCLUB")
    logger.info("")

    df_vendas_final = _filtrar_produto(df_vendas_filtrado, client_config.ingestion)

    # Usar os datasets finais
    df_pesquisa_final = df_pesquisa_unificado

    logger.info("=" * 80)
    # === CÉLULA 7: Unificação completa de categorias ===
    logger.info("")
    logger.info("CÉLULA 7: UNIFICAÇÃO COMPLETA DE CATEGORIAS")
    logger.info("")

    df_pesquisa_final_unificado = _unify_categories(df_pesquisa_final, client_config.category)

    logger.info("=" * 80)
    # === CÉLULA 8: Remoção de features desnecessárias ===
    logger.info("")
    logger.info("CÉLULA 8: REMOÇÃO DE FEATURES DESNECESSÁRIAS")
    logger.info("")

    # Determinar se deve remover Medium (opção 3)
    remover_medium = (medium_strategy == 'remove')
    df_features_removidas = remover_features_desnecessarias(df_pesquisa_final_unificado, remover_medium=remover_medium)

    # Listar colunas restantes
    listar_colunas_restantes(df_features_removidas)

    # === CAPTURAR MISSING RATES PARA MONITORAMENTO (QUALITY GATE) ===
    # IMPORTANTE: Captura APÓS célula 8 (remoção de features) para monitorar apenas colunas que vão para o modelo
    # Colunas críticas usadas no modelo - monitorar mudanças em qualidade de dados
    colunas_criticas_modelo = [
        'genero',
        'idade',
        'o_que_faz_atualmente',
        'faixa_salarial',  # Nome completo esperado
        'tem_cartao_credito',
        'o_que_quer_ver_evento',
        'estudou_programacao',
        'fez_faculdade',
        'investiu_curso_online',
        'interesse_programacao',
        'tem_computador'
    ]

    missing_rates_baseline = {}
    for col in colunas_criticas_modelo:
        if col in df_features_removidas.columns:
            # Usar função centralizada de data_quality para consistência com monitoramento
            missing_rate = calculate_missing_rate(df_features_removidas, col)
            missing_rates_baseline[col] = missing_rate
        else:
            # Tentar encontrar coluna com nome similar (truncado)
            matching_cols = [c for c in df_features_removidas.columns if c.startswith(col[:30])]
            if matching_cols:
                missing_rate = calculate_missing_rate(df_features_removidas, matching_cols[0])
                missing_rates_baseline[matching_cols[0]] = missing_rate

    # === QUALITY GATE HOOK: Validar qualidade de dados antes de continuar ===
    if quality_gate_hook:
        logger.info("")
        logger.info(f"  QUALITY GATE HOOK: Validando qualidade de dados antes de continuar...")
        should_continue = quality_gate_hook(missing_rates_baseline, df_features_removidas, df_vendas_final)
        if not should_continue:
            logger.error("    Quality gate falhou - abortando treino")
            return {'status': 'ABORTED_BY_QUALITY_GATE', 'missing_rates': missing_rates_baseline}
        logger.info("    Quality gate passou - prosseguindo com treino")

    logger.info("=" * 80)
    # === CÉLULA 10: Unificação de UTM Source e Term ===
    logger.info("")
    logger.info("CÉLULA 10: UNIFICAÇÃO DE UTM SOURCE E TERM")
    logger.info("")

    if capture_parity_snapshots:
        _fixtures = os.path.join(os.path.dirname(__file__), '..', 'tests', 'fixtures')
        os.makedirs(_fixtures, exist_ok=True)
        df_features_removidas.to_pickle(os.path.join(_fixtures, 'snapshot_utm_input.pkl'))
        logger.info("  [PARITY] snapshot_utm_input.pkl salvo")

    df_utm_unificado = unify_utm(df_features_removidas, client_config.utm)

    if capture_parity_snapshots:
        df_utm_unificado.to_pickle(os.path.join(_fixtures, 'snapshot_utm_output.pkl'))
        logger.info("  [PARITY] snapshot_utm_output.pkl salvo")


    logger.info("=" * 80)
    # === CÉLULA 11: Unificação de UTM Medium ===
    logger.info("")
    logger.info("CÉLULA 11: UNIFICAÇÃO DE UTM MEDIUM")
    logger.info("")
    if 'Medium' in df_utm_unificado.columns:
        n_bruto_medium = df_utm_unificado['Medium'].nunique()
        n_leads_medium = len(df_utm_unificado)
        logger.info(f"  Input: {n_leads_medium:,} leads — {n_bruto_medium} valores brutos de Medium")
        logger.info("")

        if capture_parity_snapshots:
            df_utm_unificado.to_pickle(os.path.join(_fixtures, 'snapshot_medium_input.pkl'))
            logger.info("  [PARITY] snapshot_medium_input.pkl salvo")

        df_medium_producao = unify_medium(df_utm_unificado, client_config.medium)
    else:
        logger.info("  Pulando (Medium foi removido na célula 8 - strategy='remove')")
        df_medium_unificado = df_utm_unificado.copy()
        df_medium_producao = df_utm_unificado.copy()

    if capture_parity_snapshots:
        df_medium_producao.to_pickle(os.path.join(_fixtures, 'snapshot_medium_output.pkl'))
        logger.info("  [PARITY] snapshot_medium_output.pkl salvo")

    logger.info("=" * 80)
    # === CÉLULA 13: Criação de versão do dataset por missing rate ===
    logger.info("")
    logger.info("CÉLULA 13: FILTRO TEMPORAL POR MISSING RATE")
    logger.info("")

    df_pos_cutoff = criar_dataset_pos_cutoff(df_medium_producao, client_config.ingestion)

    logger.info("=" * 80)
    # === CÉLULA 15: Matching robusto por email e telefone ===
    cell_start = time.time()
    logger.info("")
    logger.info(f"CÉLULA 15: MATCHING DE LEADS COM VENDAS")
    logger.info("")

    # Filtro TMB já foi aplicado em unificar_colunas_datasets
    df_vendas_matching = df_vendas_final.copy()

    dataset_v1_final = _match_leads(df_pos_cutoff, df_vendas_matching, client_config.matching)

    # Vendas já foram filtradas para DevClub na CÉLULA 5.4
    # Target já reflete apenas matches com vendas DevClub
    dataset_v1_devclub = dataset_v1_final.copy()

    cell_timers['Célula 15'] = time.time() - cell_start
    logger.info(f"   Tempo: {cell_timers['Célula 15']:.1f}s")
    logger.info("=" * 80)

    # === CÉLULA 17: Janela de Conversão ===
    logger.info("")
    logger.info(f"CÉLULA 17: APLICAR JANELA DE CONVERSÃO DE 20 DIAS")
    logger.info("")

    # DEBUG: Verificar estado de df_vendas_final ANTES de passar para aplicar_janela_conversao
    logger.debug(f"  DEBUG CÉLULA 17: df_vendas_final shape: {df_vendas_final.shape}")
    logger.debug(f"  DEBUG CÉLULA 17: 'data' dtype: {df_vendas_final['data'].dtype if 'data' in df_vendas_final.columns else 'NOT FOUND'}")
    if 'data' in df_vendas_final.columns:
        logger.debug(f"  DEBUG CÉLULA 17: 'data' non-null: {df_vendas_final['data'].notna().sum()}/{len(df_vendas_final)}")
        logger.debug(f"  DEBUG CÉLULA 17: 'data' max: {df_vendas_final['data'].max()}")

    # Aplicar janela de conversão de 20 dias (captação + CPL + carrinho)
    # Captação: 7 dias (terça-segunda) + CPL: 6 dias (terça-domingo) + Carrinho: 7 dias (segunda-domingo) = 20 dias
    dataset_v1_devclub = _aplicar_janela_conversao(
        df_leads=dataset_v1_devclub,
        df_vendas=df_vendas_final,
        config=client_config.monitoring,
    )

    # Recall metrics (não calculado após reorganização - vendas já filtradas na CÉLULA 5.4)
    recall_metrics = None

    logger.info("=" * 80)
    # === CÉLULA 18: Feature Engineering ===
    cell_start = time.time()
    logger.info("")
    logger.info(f"CÉLULA 18: FEATURE ENGINEERING")
    logger.info("")
    # IMPORTANTE: FE será aplicado no dataset COM ou SEM temporais
    # Se temporais foram adicionadas, FE vai criar 7 features E remover Data/Nome/etc
    # Resultado final: 4 temporais + 7 FE + 15 base = 26 colunas

    if capture_parity_snapshots:
        dataset_v1_devclub.to_pickle(os.path.join(_fixtures, 'snapshot_fe_input.pkl'))
        logger.info("  [PARITY] snapshot_fe_input.pkl salvo")

    dataset_v1_devclub_fe = _create_features(dataset_v1_devclub, client_config.feature)

    if capture_parity_snapshots:
        dataset_v1_devclub_fe.to_pickle(os.path.join(_fixtures, 'snapshot_fe_output.pkl'))
        logger.info("  [PARITY] snapshot_fe_output.pkl salvo")

    # === VALIDATION HOOK (opcional - usado pelo retreino mensal) ===
    if validation_hook:
        logger.info("")
        logger.info(f"  VALIDATION HOOK: Validando dados antes de prosseguir...")
        should_continue = validation_hook(dataset_v1_devclub_fe)
        if not should_continue:
            logger.error("    Validação falhou - abortando treino")
            return {'status': 'ABORTED_BY_VALIDATION'}
        logger.info("    Validação passou - prosseguindo com treino")

    # === CÉLULA 18.5: Capturar categorias para monitoramento ===
    logger.info("  CAPTURANDO CATEGORIAS E DISTRIBUIÇÕES PARA MONITORAMENTO (DRIFT DETECTION)")
    logger.info("  Identificando e salvando categorias únicas para detecção de drift...")

    # Salvar categorias apenas se save_files=True
    # O arquivo será salvo na mesma pasta do modelo pelo registrar_features_e_modelo_devclub
    # Por enquanto, apenas capturar - salvaremos depois junto com o modelo
    categorias_capturadas = capture_training_categories(dataset_v1_devclub_fe, output_path=None)

    logger.info("  Capturando distribuições completas (proporções + estatísticas)...")
    logger.info("")
    distribuicoes_capturadas = capture_training_distributions(dataset_v1_devclub_fe, output_path=None)

    cell_timers['Célula 18'] = time.time() - cell_start
    logger.info(f"   Tempo: {cell_timers['Célula 18']:.1f}s")
    logger.info("=" * 80)
    # === CÉLULA 20: Encoding Estratégico ===
    cell_start = time.time()
    logger.info("")
    logger.info(f"CÉLULA 20: ENCODING ESTRATÉGICO")
    logger.info("")

    if capture_parity_snapshots:
        dataset_v1_devclub_fe.to_pickle(os.path.join(_fixtures, 'snapshot_encoding_input.pkl'))
        logger.info("  [PARITY] snapshot_encoding_input.pkl salvo")

    dataset_v1_devclub_encoded = _apply_encoding(dataset_v1_devclub_fe, client_config.encoding)

    if capture_parity_snapshots:
        dataset_v1_devclub_encoded.to_pickle(os.path.join(_fixtures, 'snapshot_encoding_output.pkl'))
        logger.info("  [PARITY] snapshot_encoding_output.pkl salvo")

    if save_encoded:
        _encoded_path = os.path.join(os.path.dirname(__file__), '..', 'compare_encoded.parquet')
        _encoded_path = os.path.abspath(_encoded_path)
        df_encoded_with_date = dataset_v1_devclub_encoded.copy()
        df_encoded_with_date['__Data__'] = pd.to_datetime(dataset_v1_devclub['Data'], errors='coerce').values
        if 'E-mail' in dataset_v1_devclub.columns:
            df_encoded_with_date['__email__'] = dataset_v1_devclub['E-mail'].str.strip().str.lower().values
        df_encoded_with_date.to_parquet(_encoded_path, index=False)
        logger.info(f"  [compare_models] Dataset encodado salvo em: {_encoded_path}")

    # === Pesos por tipo de comprador (calculado antes do tuning para uso em ambos) ===
    PESOS_COMPRADOR = {
        'guru':    1.00,   # Guru: à vista, 100% recebido
        'tmb_baixo': 0.84, # TMB Baixo: 83.5% recebido
        'tmb_medio': 0.67, # TMB Médio: 67.1% recebido
        'tmb_alto':  0.49, # TMB Alto: 48.6% recebido
        'tmb_sem':   0.42, # TMB Sem class.: 42.1% recebido
    }

    def _get_peso(row):
        if row.get('target', 0) == 0:
            return 1.0
        email = str(row.get('E-mail', '')).strip().lower()
        risk = tmb_risk_lookup.get(email)
        if risk is None:
            return PESOS_COMPRADOR['guru']   # não está no lookup TMB → Guru
        mapa = {'Baixo': 'tmb_baixo', 'Médio': 'tmb_medio', 'Alto': 'tmb_alto'}
        return PESOS_COMPRADOR.get(mapa.get(risk, 'tmb_sem'), PESOS_COMPRADOR['tmb_sem'])

    if use_buyer_weights:
        buyer_weights = dataset_v1_devclub.apply(_get_peso, axis=1)
        buyer_weights.index = dataset_v1_devclub_encoded.index
    else:
        buyer_weights = None

    # Hiperparâmetros padrão do modelo (baseline real para comparação no tuning)
    DEFAULT_HYPERPARAMS = {
        'n_estimators': 300,
        'max_depth': 8,
        'min_samples_split': 2,
        'min_samples_leaf': 1,
        'max_features': 'sqrt',
        'class_weight': 'balanced',
        'random_state': 42,
        'n_jobs': -1,
    }

    # === HYPERPARAMETER TUNING (opcional) ===
    melhores_params = None
    if fixed_hyperparams:
        melhores_params = {**DEFAULT_HYPERPARAMS, **fixed_hyperparams}
        logger.info("")
        logger.info("HIPERPARÂMETROS FIXOS (--hyperparams)")
        for k, v in fixed_hyperparams.items():
            logger.info(f"  {k}: {DEFAULT_HYPERPARAMS.get(k, '?')}  {v}")
        logger.info("")
    elif tune_hyperparams:
        logger.info("")
        logger.info("EXECUTANDO HYPERPARAMETER TUNING")

        resultado_tuning = hyperparameter_tuning(
            dataset_v1_devclub_encoded,
            dataset_v1_devclub,
            baseline_params=DEFAULT_HYPERPARAMS,
            grid_size=grid_size,
            buyer_weights=buyer_weights,
        )

        if resultado_tuning and resultado_tuning['usar_tunado']:
            melhores_params = resultado_tuning['melhores_params']
            logger.info("")
            logger.info(f"  Usando hiperparâmetros tunados no treino final")
        else:
            logger.warning(f"\n  Mantendo hiperparâmetros baseline (tuning não trouxe ganho significativo)")

    cell_timers['Célula 20'] = time.time() - cell_start
    logger.info(f"   Tempo: {cell_timers['Célula 20']:.1f}s")
    logger.info("=" * 80)
    # === CÉLULA 21: Treino e Registro do Modelo ===
    cell_start = time.time()
    logger.info("")
    logger.info(f"CÉLULA 21: TREINO E REGISTRO DO MODELO")
    logger.info("")

    if use_buyer_weights:
        compradores_mask = dataset_v1_devclub['target'] == 1
        peso_medio = buyer_weights[compradores_mask].mean()
        logger.info(f"  Pesos ativos — peso médio compradores: {peso_medio:.3f} (Guru=1.0, TMB Alto=0.49)")
    else:
        logger.info(f"  Pesos desabilitados (--no-weights) — todos compradores com peso 1.0")

    resultado_registro_devclub = registrar_features_e_modelo_devclub(
        dataset_v1_devclub_encoded,
        dataset_v1_devclub,
        save_files=save_files,  # DEPRECATED - mantido para backward compatibility
        save_test_predictions=save_test_predictions,
        categorias_treino=categorias_capturadas,
        distribuicoes_treino=distribuicoes_capturadas,
        matching_method=initial_matching,
        custom_hyperparams=melhores_params,
        split_method=split_method,
        set_active=set_active,
        recall_metrics=recall_metrics,
        missing_rates_baseline=missing_rates_baseline,
        buyer_weights=buyer_weights,
        cli_args=cli_args,
        client_config=client_config,
        tmb_risk_filter=tmb_risk_filter
    )

    cell_timers['Célula 21'] = time.time() - cell_start
    logger.info(f"   Tempo: {cell_timers['Célula 21']:.1f}s")

    # Comparação com run anterior
    try:
        import mlflow
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        _exp_name = (
            client_config.model.mlflow_experiment_name
            if client_config and client_config.model and client_config.model.mlflow_experiment_name
            else "devclub_lead_scoring"
        )
        experiment = mlflow.get_experiment_by_name(_exp_name)

        if experiment:
            # Buscar últimas 2 runs (atual + anterior)
            runs = client.search_runs(
                experiment_ids=[experiment.experiment_id],
                order_by=["start_time DESC"],
                max_results=2
            )

            if len(runs) >= 2:
                run_atual = runs[0]
                run_anterior = runs[1]

                # Buscar model_type dos artifacts
                import json
                import tempfile

                def get_model_type(run):
                    try:
                        # Download model_metadata.json artifact
                        artifact_path = client.download_artifacts(run.info.run_id, "model_metadata.json")
                        with open(artifact_path, 'r') as f:
                            metadata = json.load(f)
                            return metadata.get('model_info', {}).get('model_type', 'N/A')
                    except:
                        return 'N/A'

                model_type_atual = get_model_type(run_atual)
                model_type_anterior = get_model_type(run_anterior)

                logger.info("")
                logger.info("=" * 80)
                logger.info("COMPARAÇÃO COM RUN ANTERIOR")
                logger.info("=" * 80)

                # Run atual
                logger.info("Run atual:")
                logger.info(f"  Algoritmo: {model_type_atual}")
                logger.info(f"  Split: {run_atual.data.params.get('split_method', 'N/A')}")
                logger.info(f"  Matching: {run_atual.data.params.get('matching_method', 'N/A')}")
                logger.info(f"  AUC: {float(run_atual.data.metrics.get('auc', 0)):.3f}")
                logger.info(f"  Top 3 decis: {float(run_atual.data.metrics.get('top3_decil_concentration', 0)):.1f}%")
                logger.info(f"  Lift máximo: {float(run_atual.data.metrics.get('lift_maximum', 0)):.1f}x")
                logger.info(f"  Monotonia: {float(run_atual.data.metrics.get('monotonia_percentage', 0)):.1f}%")

                logger.info("")
                logger.info("Run anterior:")
                logger.info(f"  Algoritmo: {model_type_anterior}")
                logger.info(f"  Split: {run_anterior.data.params.get('split_method', 'N/A')}")
                logger.info(f"  Matching: {run_anterior.data.params.get('matching_method', 'N/A')}")
                logger.info(f"  AUC: {float(run_anterior.data.metrics.get('auc', 0)):.3f}")
                logger.info(f"  Top 3 decis: {float(run_anterior.data.metrics.get('top3_decil_concentration', 0)):.1f}%")
                logger.info(f"  Lift máximo: {float(run_anterior.data.metrics.get('lift_maximum', 0)):.1f}x")
                logger.info(f"  Monotonia: {float(run_anterior.data.metrics.get('monotonia_percentage', 0)):.1f}%")
    except Exception as e:
        logger.debug(f"Não foi possível comparar com run anterior: {e}")

    # Tempo total do pipeline
    pipeline_total_time = time.time() - pipeline_start_time
    logger.info("")
    logger.info("=" * 80)
    logger.info("  RESUMO DE TEMPOS")
    logger.info("=" * 80)
    for cell_name, cell_time in cell_timers.items():
        logger.info(f"  {cell_name}: {cell_time:.1f}s")
    logger.info("-" * 80)
    logger.info(f"  TEMPO TOTAL: {pipeline_total_time:.1f}s ({pipeline_total_time/60:.1f} min)")
    logger.info("=" * 80)

    # Retornar metadata completo para uso pelo orquestrador de retreino
    return resultado_registro_devclub


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Pipeline de treino DevClub')
    parser.add_argument(
        '--initial-matching',
        type=str,
        choices=['email_only', 'email_telefone', 'variantes', 'robusto', 'validation', 'unified_last6'],
        default='email_telefone',
        help='Método de matching inicial (célula 15) - padrão: email_telefone (+16.5%% dados, melhor separação D10/D1)'
    )
    parser.add_argument(
        '--save-files',
        action='store_true',
        help='[DEPRECADO] Use --save-test-predictions. Salvar arquivos locais em files/{timestamp} (padrão: False - apenas MLflow)'
    )
    parser.add_argument(
        '--save-test-predictions',
        action='store_true',
        help='Salvar predições do test set em files/{timestamp}/test_set_predictions.csv (padrão: False)'
    )
    parser.add_argument(
        '--tune-hyperparams',
        action='store_true',
        help='Executar hyperparameter tuning antes do treino (padrão: False)'
    )
    parser.add_argument(
        '--grid-size',
        type=str,
        choices=['small', 'medium', 'large'],
        default='small',
        help='Tamanho do grid search: small (6 comb), medium (48), large (96) - padrão: small'
    )
    parser.add_argument(
        '--split-method',
        type=str,
        choices=['temporal', 'temporal_leads', 'stratified'],
        default='temporal_leads',
        help='Método de split: temporal (70%% dos dias), temporal_leads (70%% dos leads), ou stratified (70%% dos registros) - padrão: temporal_leads'
    )
    parser.add_argument(
        '--tmb-risk-filter',
        type=str,
        choices=['all', 'none', 'low', 'low_medium'],
        default='all',
        help='Filtro de risco para alunos TMB: all (todos), none (nenhum, só Guru), low (baixo risco), low_medium (baixo + médio) - padrão: all'
    )
    parser.add_argument(
        '--set-active',
        action='store_true',
        help='Definir este modelo como ativo em configs/active_model.yaml (baixa arquivos do MLflow automaticamente)'
    )
    parser.add_argument(
        '--medium-strategy',
        type=str,
        choices=['full', 'binary_aberto', 'binary_aberto_dgen', 'binary_top3', 'remove'],
        default='binary_top3',
        help='Estratégia para Medium: full (one-hot completo), binary_aberto (apenas Medium_Aberto), binary_aberto_dgen (Medium_Aberto + Medium_dgen), binary_top3 (top 3 categorias mais estáveis - RECOMENDADO), remove (remover na célula 8) - padrão: binary_top3'
    )
    parser.add_argument(
        '--verbosity',
        type=str,
        choices=['silent', 'minimal', 'normal', 'debug'],
        default='normal',
        help='Nível de verbosidade dos logs: silent (apenas erros), minimal (warnings+erros), normal (info+warnings+erros), debug (tudo incluindo análises detalhadas) - padrão: normal'
    )
    parser.add_argument(
        '--no-api-data',
        action='store_true',
        default=False,
        help='Desligar busca de dados da API Guru e Google Sheets (usar apenas arquivos locais)'
    )
    parser.add_argument(
        '--no-sheets-api',
        action='store_true',
        default=False,
        help='Desligar busca de leads via Google Sheets API (usar quando os leads já foram baixados como Excel). Relevante apenas com --include-api-data'
    )
    parser.add_argument(
        '--no-weights',
        action='store_true',
        default=False,
        help='Desabilitar sample weights por tipo de comprador (treino sem ponderação, baseline)'
    )
    parser.add_argument(
        '--save-encoded',
        action='store_true',
        default=False,
        help='Salvar dataset encodado em compare_encoded.parquet para uso em compare_models.py'
    )
    parser.add_argument(
        '--api-start-date',
        type=str,
        default=None,
        help='Data de início para buscar dados da API (formato: YYYY-MM-DD). Requer --include-api-data'
    )
    parser.add_argument(
        '--api-end-date',
        type=str,
        default=None,
        help='Data de fim para buscar dados da API (formato: YYYY-MM-DD). Requer --include-api-data'
    )
    parser.add_argument(
        '--capture-parity-snapshots',
        action='store_true',
        default=False,
        help='Serializar (input, output) de cada função compartilhada em tests/fixtures/ para audit de paridade treino×produção'
    )
    parser.add_argument(
        '--use-cached-data',
        action='store_true',
        default=False,
        help='Usar cache de dados brutos de outputs/cache/raw_data_{api_end_date}.pkl (pula chamadas à API). Salva automaticamente o cache se não existir.'
    )
    parser.add_argument(
        '--hyperparams',
        type=str,
        default=None,
        help='Hiperparâmetros fixos em JSON (pula tuning). Ex: \'{"n_estimators": 200, "max_features": "log2", "min_samples_leaf": 3}\''
    )
    parser.add_argument(
        '--max-date',
        type=str,
        default=None,
        help='Data máxima dos leads (YYYY-MM-DD). Filtra pesquisa e vendas até essa data — usado para reproduzir runs anteriores com o mesmo corte temporal.'
    )

    args = parser.parse_args()

    main(
        initial_matching=args.initial_matching,
        save_files=args.save_files,  # DEPRECATED
        save_test_predictions=args.save_test_predictions,
        tune_hyperparams=args.tune_hyperparams,
        grid_size=args.grid_size,
        split_method=args.split_method,
        tmb_risk_filter=args.tmb_risk_filter,
        set_active=args.set_active,
        medium_strategy=args.medium_strategy,
        verbosity=args.verbosity,
        include_api_data=not args.no_api_data,
        include_sheets_api=not args.no_sheets_api,
        api_start_date=args.api_start_date,
        api_end_date=args.api_end_date,
        use_buyer_weights=not args.no_weights,
        save_encoded=args.save_encoded,
        capture_parity_snapshots=args.capture_parity_snapshots,
        cli_args=vars(args),
        use_cached_data=args.use_cached_data,
        fixed_hyperparams=json.loads(args.hyperparams) if args.hyperparams else None,
        max_date=args.max_date,
    )
