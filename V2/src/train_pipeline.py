"""
Pipeline de treino - Reproduz notebook DevClub célula por célula.

Integra funções modularizadas conforme são aprovadas.
"""

import sys
import os
import logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import yaml
import glob
import logging
import argparse
import pandas as pd
import atexit
from datetime import datetime
from src.data_processing.ingestion import (
    read_excel_files,
    read_all_training_sources,
    filter_sheets,
    remove_duplicates_per_sheet,
    remove_unnecessary_columns,
    consolidate_datasets
)
from src.data_processing.column_unification_refactored import (
    unificar_colunas_pesquisa,
    unificar_colunas_vendas,
    aplicar_filtro_temporal,
    remover_colunas_utm_ausentes,
    aplicar_filtro_status_risco
)
from src.data_processing.category_unification import unificar_categorias_completo, gerar_relatorio_final_categorias
from src.data_processing.feature_removal import remover_features_desnecessarias, listar_colunas_restantes
from src.data_processing.utm_training import unificar_utm_source_term, verificar_consistencia_utm
from src.data_processing.medium_training import extrair_publico_medium, relatorio_final_medium
from src.data_processing.medium_production_training import unificar_medium_para_producao, relatorio_unificacao_producao
from src.data_processing.dataset_versioning_training import criar_dataset_pos_cutoff, disponibilizar_dataset
from src.matching.matching_training import fazer_matching_robusto as fazer_matching_variantes
from src.matching.matching_robusto import fazer_matching_robusto
from src.matching.matching_email_only import fazer_matching_email_only
from src.matching.matching_email_with_validation import fazer_matching_email_with_validation
from src.matching.matching_email_telefone import fazer_matching_email_telefone
from src.matching.matching_unified import match_leads_to_sales_unified
from src.data_processing.devclub_filtering_training import criar_dataset_devclub
from src.data_processing.conversion_window import aplicar_janela_conversao
from src.features.feature_engineering_training import criar_features_derivadas
from src.features.encoding_training import aplicar_encoding_estrategico
from src.model.training_model import registrar_features_e_modelo_devclub
from src.model.hyperparameter_tuning import hyperparameter_tuning
from src.monitoring.data_quality import capture_training_categories, capture_training_distributions, calculate_missing_rate

# Logging será configurado no main() via setup_logging(verbosity)


class Tee:
    """Duplica output para console e arquivo (como comando tee do Unix)."""
    def __init__(self, file_path):
        self.terminal = sys.stdout
        self.log = open(file_path, 'w', encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()  # Força escrita imediata

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


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

    # Redirecionar stdout e stderr para Tee
    tee = Tee(log_path)
    sys.stdout = tee
    sys.stderr = tee

    return log_path, tee



def setup_logging(verbosity='normal'):
    """
    Configura logging com níveis de verbosidade

    Args:
        verbosity: Nível de verbosidade
            - 'silent': Apenas erros críticos
            - 'minimal': Warnings + erros
            - 'normal': Info + warnings + erros (padrão)
            - 'debug': Todos os logs incluindo análises detalhadas
    """
    LEVEL_MAP = {
        'silent': logging.ERROR,
        'minimal': logging.WARNING,
        'normal': logging.INFO,
        'debug': logging.DEBUG
    }

    logging.basicConfig(
        level=LEVEL_MAP.get(verbosity, logging.INFO),
        format='%(asctime)s [%(levelname)-8s] %(message)s',
        datefmt='%H:%M:%S'
    )

# Logger global do módulo
logger = logging.getLogger(__name__)


def main(initial_matching='email_telefone', save_files=False, tune_hyperparams=False, grid_size='small', split_method='temporal_leads', tmb_risk_filter='all', set_active=False, medium_strategy='binary_top3', validation_hook=None, quality_gate_hook=None, include_api_data=False, api_start_date=None, api_end_date=None, output_subdir='training', verbosity='normal'):
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
        include_api_data: Se True, busca dados adicionais de API/Sheets (usado no retreino)
        api_start_date: Data início para buscar dados da API (YYYY-MM-DD)
        api_end_date: Data fim para buscar dados da API (YYYY-MM-DD)
        output_subdir: Subdiretório para logs ('training' ou 'retraining')
    """

    # Configurar redirecionamento de output para arquivo PRIMEIRO
    log_path, tee = setup_output_logging(output_subdir)

    # Configurar logging com nível de verbosidade DEPOIS do redirect
    setup_logging(verbosity)

    # Registrar função de cleanup para fechar arquivo ao terminar
    def cleanup():
        logger.info("")
        logger.info(f" Pipeline concluído! Output salvo em: {log_path}")
        tee.close()
        sys.stdout = tee.terminal
        sys.stderr = tee.terminal

    atexit.register(cleanup)

    logger.info("")
    logger.info("PIPELINE DE TREINO")
    logger.info("")
    logger.info(f"    Output sendo salvo em: {log_path}")
    logger.info("")
    logger.info(f"  CONFIGURAÇÃO:")
    logger.info(f"    Método de matching inicial (célula 15): {initial_matching}")
    logger.info(f"    Salvar arquivos locais: {save_files}")
    logger.info(f"    Hyperparameter tuning: {tune_hyperparams}")
    if tune_hyperparams:
        logger.info(f"    Grid size: {grid_size}")

    logger.info("=" * 80)

    # Carregar configuração
    config_path = os.path.join(os.path.dirname(__file__), '../configs/devclub.yaml')
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # === CÉLULA 1: Upload/Leitura de arquivos ===
    logger.info("")
    logger.info("CÉLULA 1: LEITURA DE ARQUIVOS")
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
    logger.info("")
    logger.info(f"  Arquivos carregados: {len(filepaths)}")

    # Fonte de dados
    if include_api_data:
        logger.info(f"  Fonte de dados: Arquivos locais + Google Sheets API")
        if api_start_date or api_end_date:
            logger.debug(f"   Período API: {api_start_date or 'início'} até {api_end_date or 'hoje'}")
    else:
        logger.info(f"  Fonte de dados: Arquivos locais")

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
    all_data = read_all_training_sources(
        filepaths,
        include_api_data=include_api_data,
        api_start_date=api_start_date,
        api_end_date=api_end_date,
        num_sheets_api=1  # Retreino: apenas aba 0 do Google Sheets
    )

    logger.info("=" * 80)
    # === CÉLULA 2: Filtragem + Remoção de Duplicatas ===
    logger.info("")
    logger.info("CÉLULA 2: FILTRAGEM DE ABAS + REMOÇÃO DE DUPLICATAS")

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
    logger.info("")
    logger.info(f"  RESUMO:")
    logger.info(f"    Arquivos processados: {len(clean_data)}")
    logger.info(f"    Abas mantidas: {abas_mantidas}")
    logger.info(f"    Abas removidas: {abas_removidas}")
    logger.info(f"    Linhas totais após processamento: {total_final:,}")
    logger.info(f"    Duplicatas removidas: {total_duplicatas:,}")
    if total_original > 0:
        logger.info(f"    Redução por duplicatas: {(total_duplicatas/total_original*100):.2f}%")
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

    # === CÉLULA 3: Remoção de colunas desnecessárias ===
    logger.info("=" * 80)
    logger.info("")
    logger.info("CÉLULA 3: REMOÇÃO DE COLUNAS DESNECESSÁRIAS")

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

    logger.info("")
    logger.info(f"  RESUMO:")
    logger.info(f"    Total de colunas removidas: {total_removidas_cols}")

    # === CÉLULA 4: Consolidação de datasets ===
    logger.info("=" * 80)
    logger.info("")
    logger.info("CÉLULA 4: CONSOLIDAÇÃO DE DATASETS - PESQUISA E VENDAS")

    df_pesquisa, df_vendas = consolidate_datasets(
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

    logger.info("")
    logger.info(f"  RESUMO:")
    logger.info(f"    Dataset Pesquisa: {len(df_pesquisa):,} registros, {len(df_pesquisa.columns)} colunas")
    logger.info(f"    Dataset Vendas: {len(df_vendas):,} registros, {len(df_vendas.columns)} colunas")

    logger.info("=" * 80)
    # === CÉLULA 5: Unificação de colunas duplicadas ===
    logger.info("")
    logger.info("CÉLULA 5: UNIFICAÇÃO DE COLUNAS DUPLICADAS")

    # Parte 1: Unificar colunas de PESQUISA
    df_pesquisa_unificado = unificar_colunas_pesquisa(df_pesquisa)

    # Parte 2: Unificar colunas de VENDAS
    df_vendas_unificado = unificar_colunas_vendas(df_vendas)

    logger.info("=" * 80)
    # === CÉLULA 5.1: Filtro temporal ===
    logger.info("")
    logger.info("CÉLULA 5.1: FILTRO TEMPORAL")

    df_vendas_temporal = aplicar_filtro_temporal(df_vendas_unificado, df_pesquisa_unificado)

    logger.info("=" * 80)
    # === CÉLULA 5.2: Remoção de colunas UTM ===
    logger.info("")
    logger.info("CÉLULA 5.2: REMOÇÃO DE COLUNAS UTM COM ALTA % AUSENTES")

    df_vendas_sem_utm = remover_colunas_utm_ausentes(df_vendas_temporal)

    logger.info("=" * 80)
    # === CÉLULA 5.3: Filtro de status e risco ===
    logger.info("")
    logger.info("CÉLULA 5.3: FILTRO DE STATUS E RISCO")

    df_vendas_final = aplicar_filtro_status_risco(df_vendas_sem_utm, tmb_risk_filter=tmb_risk_filter)

    # Usar os datasets finais
    df_pesquisa_final = df_pesquisa_unificado

    # Gerar relatórios finais (apenas em DEBUG)
    gerar_relatorio_colunas(df_pesquisa_final, "DATASET PESQUISA")
    gerar_relatorio_colunas(df_vendas_final, "DATASET VENDAS")

    logger.info("=" * 80)
    # === CÉLULA 7: Unificação completa de categorias ===
    logger.info("")
    logger.info("CÉLULA 7: UNIFICAÇÃO COMPLETA DE CATEGORIAS")

    df_pesquisa_final_unificado = unificar_categorias_completo(df_pesquisa_final)

    # Gerar relatório final
    gerar_relatorio_final_categorias(df_pesquisa_final_unificado)

    logger.info("=" * 80)
    # === CÉLULA 8: Remoção de features desnecessárias ===
    logger.info("")
    logger.info("CÉLULA 8: REMOÇÃO DE FEATURES DESNECESSÁRIAS")

    # Determinar se deve remover Medium (opção 3)
    remover_medium = (medium_strategy == 'remove')
    df_features_removidas = remover_features_desnecessarias(df_pesquisa_final_unificado, remover_medium=remover_medium)

    # Listar colunas restantes
    listar_colunas_restantes(df_features_removidas)

    # === CAPTURAR MISSING RATES PARA MONITORAMENTO (QUALITY GATE) ===
    # IMPORTANTE: Captura APÓS célula 8 (remoção de features) para monitorar apenas colunas que vão para o modelo
    # Colunas críticas usadas no modelo - monitorar mudanças em qualidade de dados
    colunas_criticas_modelo = [
        'O seu gênero:',
        'Qual a sua idade?',
        'O que você faz atualmente?',
        'Atualmente, qual a sua faixa salarial?',  # Nome completo esperado
        'Você possui cartão de crédito?',
        'O que mais você quer ver no evento?',
        'Já estudou programação?',
        'Você já fez/faz/pretende fazer faculdade?',
        'investiu_curso_online',
        'interesse_programacao',
        'Tem computador/notebook?'
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

    df_utm_unificado = unificar_utm_source_term(df_features_removidas)

    # Verificar consistência
    verificar_consistencia_utm(df_utm_unificado)

    logger.info("=" * 80)
    # === CÉLULA 11: Unificação de UTM Medium - Extração de Públicos ===
    # (Pulada se medium_strategy='remove')
    if 'Medium' in df_utm_unificado.columns:
        logger.info("")
        logger.info("CÉLULA 11: UNIFICAÇÃO DE UTM MEDIUM - EXTRAÇÃO DE PÚBLICOS")

        df_medium_unificado = extrair_publico_medium(df_utm_unificado)

        # Gerar relatório final
        relatorio_final_medium(df_medium_unificado)
    else:
        logger.info("")
        logger.info("CÉLULA 11: Pulando (Medium foi removido na célula 8 - strategy='remove')")
        df_medium_unificado = df_utm_unificado.copy()

    logger.info("=" * 80)
    # === CÉLULA 11.1: Unificação de Medium para Produção ===
    if 'Medium' in df_medium_unificado.columns:
        logger.info("")
        logger.info("CÉLULA 11.1: UNIFICAÇÃO DE UTM MEDIUM PARA PRODUÇÃO")

        logger.info("  Iniciando processo de unificação para produção...")
        df_original = df_medium_unificado.copy()
        df_medium_producao = unificar_medium_para_producao(df_medium_unificado)

        # Gerar relatório
        relatorio_unificacao_producao(df_original, df_medium_producao)
    else:
        logger.info("")
        logger.info("CÉLULA 11.1: Pulando (Medium foi removido na célula 8 - strategy='remove')")
        df_medium_producao = df_medium_unificado.copy()

    logger.info("=" * 80)
    # === CÉLULA 13: Criação de versão do dataset por missing rate ===
    logger.info("")
    logger.info("CÉLULA 13: CRIAÇÃO DE VERSÕES DO DATASET POR MISSING RATE")

    df_pos_cutoff = criar_dataset_pos_cutoff(df_medium_producao)

    # Disponibilizar dataset
    disponibilizar_dataset(df_pos_cutoff)

    logger.info("=" * 80)
    # === CÉLULA 15: Matching robusto por email e telefone ===
    logger.info("")
    logger.info(f"CÉLULA 15: MATCHING DE LEADS COM VENDAS ({initial_matching.upper().replace('_', ' ')})")

    # Filtro TMB já foi aplicado em unificar_colunas_datasets
    df_vendas_matching = df_vendas_final.copy()

    if initial_matching == 'email_only':
        dataset_v1_final = fazer_matching_email_only(df_pos_cutoff, df_vendas_matching)
    elif initial_matching == 'email_telefone':
        dataset_v1_final = fazer_matching_email_telefone(df_pos_cutoff, df_vendas_matching)
    elif initial_matching == 'variantes':
        dataset_v1_final = fazer_matching_variantes(df_pos_cutoff, df_vendas_matching)
    elif initial_matching == 'robusto':
        dataset_v1_final = fazer_matching_robusto(df_pos_cutoff, df_vendas_matching)
    elif initial_matching == 'validation':
        dataset_v1_final = fazer_matching_email_with_validation(df_pos_cutoff, df_vendas_matching)
    elif initial_matching == 'unified_last6':
        dataset_v1_final = match_leads_to_sales_unified(
            df_pos_cutoff,
            df_vendas_matching,
            mode='training'
        )
    else:
        raise ValueError(f"Método de matching inicial inválido: {initial_matching}. Use 'email_only', 'email_telefone', 'variantes', 'robusto', 'validation' ou 'unified_last6'")

    logger.info("=" * 80)
    # === CÉLULA 17: Filtragem DevClub ===
    logger.info("=" * 80)
    logger.info("")
    logger.info(f"CÉLULA 17: FILTRAGEM DEVCLUB")

    dataset_v1_devclub = criar_dataset_devclub(dataset_v1_final, df_vendas_final)

    # === LOG: VERIFICAÇÃO DE PRODUTOS DEVCLUB ===
    logger.debug("\n" + "=" * 80)
    logger.debug("VERIFICAÇÃO DE PRODUTOS DEVCLUB - Análise Completa")
    logger.debug("=" * 80)

    # 1. Listar TODOS os produtos que contêm "devclub"
    logger.debug("\n TODOS OS PRODUTOS COM 'DEVCLUB' NO NOME:")
    logger.debug("-" * 80)

    produtos_com_devclub = df_vendas_final[
        df_vendas_final['produto'].fillna('').str.lower().str.contains('devclub', na=False)
    ]['produto'].value_counts()

    logger.debug(f"\nTotal de variações encontradas: {len(produtos_com_devclub)}")
    logger.debug("\nProdutos e quantidade de vendas:")
    for produto, count in produtos_com_devclub.items():
        logger.debug(f"  {count:>5} vendas | {produto}")

    # 2. Lista atual de produtos que estamos usando (SINCRONIZADA com devclub_filtering_training.py)
    produtos_devclub_lista_atual = [
        'DevClub - Full Stack 2025',
        'DevClub FullStack Pro - OFICIAL',
        'Formação DevClub FullStack Pro - OFICI',
        'Formação DevClub FullStack Pro - OFICIAL',  # Nome completo (não truncado)
        'DevClub - Full Stack 2025 - EV',
        'DevClub - FS - Vitalício',
        '[Vitalício] Formação DevClub FullStack',
        '[Vitalício] Formação DevClub FullStack Pro - OFICIAL',  # Vitalício completo
        'Formação DevClub FullStack Pro - COMER',
        'Formação DevClub FullStack Pro - COMERCIAL',  # Nome completo (não truncado)
        'Formação DevClub FullStack Pro',  # Sem sufixo
        'DevClub Vitalício',
        'DevClub 3.0 - 2024',
        '(Desativado) DevClub 3.0 - 2024',
        '(Desativado) DevClub 3.0 - 2024 - Novo'
    ]

    # 3. Verificar produtos que EXISTEM mas NÃO estão na lista
    logger.debug("\n" + "=" * 80)
    logger.debug("  PRODUTOS NÃO CONTABILIZADOS (existem mas não estão na lista):")
    logger.debug("-" * 80)

    produtos_nao_contabilizados = []
    vendas_perdidas = 0

    for produto in produtos_com_devclub.index:
        if produto not in produtos_devclub_lista_atual:
            produtos_nao_contabilizados.append(produto)
            vendas_perdidas += produtos_com_devclub[produto]
            logger.debug(f"  {produtos_com_devclub[produto]:>5} vendas | {produto}")

    if not produtos_nao_contabilizados:
        logger.debug("   Nenhum produto perdido! Todos estão sendo contabilizados.")
    else:
        logger.debug(f"\n    TOTAL DE VENDAS PERDIDAS: {vendas_perdidas}")

    # 4. Verificar produtos na lista que NÃO existem
    logger.debug("\n" + "=" * 80)
    logger.debug(" PRODUTOS NA LISTA MAS SEM VENDAS:")
    logger.debug("-" * 80)

    produtos_sem_vendas = []
    for produto in produtos_devclub_lista_atual:
        if produto not in produtos_com_devclub.index:
            produtos_sem_vendas.append(produto)
            logger.debug(f"    {produto}")

    if not produtos_sem_vendas:
        logger.debug("   Todos os produtos da lista têm vendas!")

    # 5. Usar lista hardcoded (investigada manualmente)
    produtos_devclub = produtos_devclub_lista_atual

    logger.debug("\n" + "=" * 80)
    logger.debug(" USANDO LISTA HARDCODED (investigada manualmente)")
    logger.debug("=" * 80)
    logger.debug(f"Total de produtos na lista: {len(produtos_devclub)}")

    if produtos_nao_contabilizados:
        logger.debug(f"\n  ATENÇÃO: {vendas_perdidas} vendas de produtos não contabilizados serão IGNORADAS")
        logger.debug(f"   (Produtos descobertos automaticamente mas não na lista hardcoded)")

    if produtos_sem_vendas:
        logger.debug(f"\n  ATENÇÃO: {len(produtos_sem_vendas)} produtos na lista NÃO têm vendas no período")
        logger.debug(f"   (Produtos hardcoded mas sem vendas encontradas)")

    # === LOG: CÁLCULO DE RECALL E FATOR DE CORREÇÃO ===
    logger.debug("\n" + "=" * 80)
    logger.debug("CÁLCULO DE RECALL - Conversões Observadas vs Vendas Reais")
    logger.debug("=" * 80)

    # Contar conversões observadas (matches)
    conversoes_observadas = dataset_v1_devclub['target'].sum()
    total_leads = len(dataset_v1_devclub)

    # Filtrar vendas DevClub
    vendas_devclub = df_vendas_final[
        df_vendas_final['produto'].isin(produtos_devclub)
    ].copy()

    # Filtrar por período (mesmo período dos leads + janela de conversão)
    if 'data' in vendas_devclub.columns:
        vendas_devclub['data_dt'] = pd.to_datetime(vendas_devclub['data'], errors='coerce', dayfirst=True)
        # Período dos leads: 2025-03-01 a 2025-11-04
        # Janela de conversão: +20 dias após última data dos leads
        periodo_inicio = pd.to_datetime('2025-03-01')
        periodo_fim = pd.to_datetime('2025-11-04') + pd.Timedelta(days=20)  # 2025-11-24
        vendas_periodo = vendas_devclub[
            (vendas_devclub['data_dt'] >= periodo_inicio) &
            (vendas_devclub['data_dt'] <= periodo_fim)
        ].copy()
    else:
        vendas_periodo = vendas_devclub.copy()

    # Remover duplicatas (mesmo email/telefone + produto + data + valor)
    vendas_periodo['email_lower'] = vendas_periodo['email'].fillna('').astype(str).str.lower().str.strip()
    vendas_periodo['telefone_clean'] = vendas_periodo['telefone'].fillna('').astype(str).str.strip()
    vendas_periodo['produto_clean'] = vendas_periodo['produto'].fillna('').astype(str).str.strip()
    vendas_periodo['data_str'] = vendas_periodo['data_dt'].astype(str) if 'data_dt' in vendas_periodo.columns else vendas_periodo['data'].astype(str)
    vendas_periodo['valor_str'] = vendas_periodo['valor'].fillna(0).astype(str)

    vendas_periodo['chave_dedup'] = (
        vendas_periodo['email_lower'] + '|' +
        vendas_periodo['telefone_clean'] + '|' +
        vendas_periodo['produto_clean'] + '|' +
        vendas_periodo['data_str'] + '|' +
        vendas_periodo['valor_str']
    )
    vendas_unicas = vendas_periodo.drop_duplicates(subset='chave_dedup', keep='first')

    # Calcular métricas
    vendas_reais = len(vendas_unicas)
    recall = conversoes_observadas / vendas_reais if vendas_reais > 0 else 0
    fator_correcao = 1 / recall if recall > 0 else 0

    taxa_observada = conversoes_observadas / total_leads if total_leads > 0 else 0
    taxa_real = vendas_reais / total_leads if total_leads > 0 else 0

    logger.debug(f"\n DADOS:")
    logger.debug(f"  Total de leads: {total_leads:,}")
    logger.debug(f"  Conversões OBSERVADAS (matches): {conversoes_observadas}")
    logger.debug(f"  Vendas REAIS (sem duplicatas): {vendas_reais:,}")

    logger.debug(f"\n TAXAS:")
    logger.debug(f"  Taxa OBSERVADA: {taxa_observada*100:.4f}%")
    logger.debug(f"  Taxa REAL: {taxa_real*100:.4f}%")

    logger.debug(f"\n MÉTRICAS:")
    logger.debug(f"  Recall: {recall*100:.1f}%")
    logger.debug(f"  Fator de correção: {fator_correcao:.3f}x")

    if fator_correcao > 1:
        logger.debug(f"\n IMPACTO:")
        logger.debug(f"  Estamos SUBESTIMANDO em {fator_correcao:.3f}x")
        logger.debug(f"  Valores CAPI deveriam ser {(fator_correcao-1)*100:.0f}% maiores")

    logger.debug("=" * 80)

    # Criar dicionário com métricas de recall para passar ao registro do modelo
    recall_metrics = {
        'vendas_devclub_total': vendas_reais,
        'vendas_matched': conversoes_observadas,
        'recall': recall,
        'fator_correcao': fator_correcao
    }

    logger.info("=" * 80)
    # === CÉLULA 17.1: Janela de Conversão ===
    logger.info("")
    logger.info(f"CÉLULA 17.1: JANELA DE CONVERSÃO")

    # Aplicar janela de conversão de 20 dias (captação + CPL + carrinho)
    # Captação: 7 dias (terça-segunda) + CPL: 6 dias (terça-domingo) + Carrinho: 7 dias (segunda-domingo) = 20 dias
    dataset_v1_devclub = aplicar_janela_conversao(
        df_leads=dataset_v1_devclub,
        df_vendas=df_vendas_final,
        janela_dias=20
    )

    logger.info("=" * 80)
    # === CÉLULA 18: Feature Engineering ===
    logger.info("")
    logger.info(f"CÉLULA 18: FEATURE ENGINEERING")
    # IMPORTANTE: FE será aplicado no dataset COM ou SEM temporais
    # Se temporais foram adicionadas, FE vai criar 7 features E remover Data/Nome/etc
    # Resultado final: 4 temporais + 7 FE + 15 base = 26 colunas
    dataset_v1_devclub_fe = criar_features_derivadas(dataset_v1_devclub)

    # === VALIDATION HOOK (opcional - usado pelo retreino mensal) ===
    if validation_hook:
        logger.info("")
        logger.info(f"  VALIDATION HOOK: Validando dados antes de prosseguir...")
        should_continue = validation_hook(dataset_v1_devclub_fe)
        if not should_continue:
            logger.error("    Validação falhou - abortando treino")
            return {'status': 'ABORTED_BY_VALIDATION'}
        logger.info("    Validação passou - prosseguindo com treino")

    logger.info("=" * 80)
    # === CÉLULA 18.5: Capturar categorias para monitoramento ===
    logger.info("")
    logger.info(f"CAPTURANDO CATEGORIAS E DISTRIBUIÇÕES PARA MONITORAMENTO (DRIFT DETECTION)")
    logger.info("  Identificando e salvando categorias únicas para detecção de drift...")

    # Salvar categorias apenas se save_files=True
    # O arquivo será salvo na mesma pasta do modelo pelo registrar_features_e_modelo_devclub
    # Por enquanto, apenas capturar - salvaremos depois junto com o modelo
    categorias_capturadas = capture_training_categories(dataset_v1_devclub_fe, output_path=None)

    logger.info("")
    logger.info("  Capturando distribuições completas (proporções + estatísticas)...")
    distribuicoes_capturadas = capture_training_distributions(dataset_v1_devclub_fe, output_path=None)

    logger.info("=" * 80)
    # === CÉLULA 20: Encoding Estratégico ===
    logger.info("=" * 80)
    logger.info("")
    logger.info(f"CÉLULA 20: ENCODING ESTRATÉGICO")
    dataset_v1_devclub_encoded = aplicar_encoding_estrategico(dataset_v1_devclub_fe, medium_strategy=medium_strategy)

    # === HYPERPARAMETER TUNING (opcional) ===
    melhores_params = None
    if tune_hyperparams:
        logger.info("")
        logger.info("EXECUTANDO HYPERPARAMETER TUNING")

        resultado_tuning = hyperparameter_tuning(
            dataset_v1_devclub_encoded,
            dataset_v1_devclub,
            grid_size=grid_size
        )

        if resultado_tuning and resultado_tuning['usar_tunado']:
            melhores_params = resultado_tuning['melhores_params']
            logger.info("")
            logger.info(f"  Usando hiperparâmetros tunados no treino final")
        else:
            logger.warning(f"\n  Mantendo hiperparâmetros baseline (tuning não trouxe ganho significativo)")

    logger.info("=" * 80)
    # === CÉLULA 21: Treino e Registro do Modelo ===
    logger.info("")
    logger.info(f"CÉLULA 21: TREINO E REGISTRO DO MODELO")

    resultado_registro_devclub = registrar_features_e_modelo_devclub(
        dataset_v1_devclub_encoded,
        dataset_v1_devclub,
        save_files=save_files,
        categorias_treino=categorias_capturadas,
        distribuicoes_treino=distribuicoes_capturadas,
        matching_method=initial_matching,
        custom_hyperparams=melhores_params,
        split_method=split_method,
        set_active=set_active,
        recall_metrics=recall_metrics,
        missing_rates_baseline=missing_rates_baseline
    )

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
        help='Salvar arquivos locais em files/{timestamp} (padrão: False - apenas MLflow)'
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
        help='Definir este modelo como ativo em configs/active_model.yaml (requer --save-files)'
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

    args = parser.parse_args()

    main(
        initial_matching=args.initial_matching,
        save_files=args.save_files,
        tune_hyperparams=args.tune_hyperparams,
        grid_size=args.grid_size,
        split_method=args.split_method,
        tmb_risk_filter=args.tmb_risk_filter,
        set_active=args.set_active,
        medium_strategy=args.medium_strategy,
        verbosity=args.verbosity
    )
