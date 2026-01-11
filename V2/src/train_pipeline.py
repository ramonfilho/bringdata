"""
Pipeline de treino - Reproduz notebook DevClub célula por célula.

Integra funções modularizadas conforme são aprovadas.
"""

import sys
import os
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
    filter_sheets,
    remove_duplicates_per_sheet,
    remove_unnecessary_columns,
    consolidate_datasets
)
from src.data_processing.column_unification import unificar_colunas_datasets
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
from src.data_processing.devclub_filtering_training import criar_dataset_devclub
from src.data_processing.conversion_window import aplicar_janela_conversao
from src.features.feature_engineering_training import criar_features_derivadas
from src.features.encoding_training import aplicar_encoding_estrategico
from src.model.training_model import registrar_features_e_modelo_devclub
from src.model.hyperparameter_tuning import hyperparameter_tuning

# Configurar logging
# WARNING: Suprime logger.info() dos módulos para output limpo
# Os módulos já usam print() para mostrar informações importantes
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


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


def setup_output_logging():
    """Configura redirecionamento automático de output para arquivo timestampado."""
    # Criar diretório outputs se não existir
    outputs_dir = os.path.join(os.path.dirname(__file__), '../outputs')
    os.makedirs(outputs_dir, exist_ok=True)

    # Gerar timestamp no formato YYYYMMDD_HHMMSS
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(outputs_dir, f'{timestamp}.log')

    # Redirecionar stdout e stderr para Tee
    tee = Tee(log_path)
    sys.stdout = tee
    sys.stderr = tee

    return log_path, tee


def main(initial_matching='email_telefone', save_files=False, tune_hyperparams=False, grid_size='small', split_method='temporal_leads', use_guru_only=None, set_active=False, medium_strategy='binary_top3'):
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
        use_guru_only: Se True, usa apenas GURU. Se False, usa GURU+TMB. Se None, usa valor do config.
        set_active: Se True, atualiza configs/active_model.yaml com este modelo (requer save_files=True)
    """

    # Configurar redirecionamento de output para arquivo
    log_path, tee = setup_output_logging()

    # Registrar função de cleanup para fechar arquivo ao terminar
    def cleanup():
        print(f"\n✅ Pipeline concluído! Output salvo em: {log_path}")
        tee.close()
        sys.stdout = tee.terminal
        sys.stderr = tee.terminal

    atexit.register(cleanup)

    print("\n" + "=" * 80)
    print("PIPELINE DE TREINO")
    print("=" * 80)
    print(f"\n📝 Output sendo salvo em: {log_path}")
    print(f"\n🔧 CONFIGURAÇÃO:")
    print(f"   Método de matching inicial (célula 15): {initial_matching}")
    print(f"   Salvar arquivos locais: {save_files}")
    print(f"   Hyperparameter tuning: {tune_hyperparams}")
    if tune_hyperparams:
        print(f"   Grid size: {grid_size}")
    print("=" * 80)

    # Carregar configuração
    config_path = os.path.join(os.path.dirname(__file__), '../configs/devclub.yaml')
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # === CÉLULA 1: Upload/Leitura de arquivos ===
    print("\n📤 CÉLULA 1: LEITURA DE ARQUIVOS")
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

    # IMPORTANTE: Sempre carregar TODOS os arquivos (incluindo TMB) para calcular recall correto
    # O filtro guru_only será aplicado APENAS nos matchings para treino
    if use_guru_only is None:
        use_guru_only = config['ingestion'].get('use_guru_only', False)

    print(f"\nTotal de arquivos encontrados: {len(filepaths)}")
    if use_guru_only:
        print(f"💡 GURU ONLY MODE ativado:")
        print(f"   - Vendas Guru + TMB serão usadas para cálculo do recall")
        print(f"   - Apenas vendas Guru serão usadas para matching/treino do modelo")

    for f in filepaths:
        print(f"  - {os.path.basename(f)}")

    # Ler TODOS os arquivos (incluindo TMB)
    all_data = read_excel_files(filepaths)

    # === CÉLULA 2: Filtragem + Remoção de Duplicatas ===
    print("\n🔄 CÉLULA 2: FILTRAGEM DE ABAS + REMOÇÃO DE DUPLICATAS")
    print("=" * 60)

    # Filtrar abas
    filtered_data, filter_report = filter_sheets(
        all_data,
        termos_manter=config['ingestion']['termos_manter'],
        termos_remover=config['ingestion']['termos_remover'],
        min_linhas=config['ingestion']['min_linhas']
    )

    # Remover duplicatas
    clean_data, dup_stats = remove_duplicates_per_sheet(filtered_data)

    # === RELATÓRIO (linhas 96-127 do notebook) ===
    print(f"\n📊 ABAS MANTIDAS E PROCESSADAS")
    print("=" * 80)
    print(f"{'ARQUIVO':<35} {'ABA':<20} {'ORIGINAL':>10} {'FINAL':>10} {'REMOVIDAS':>10}")
    print("-" * 80)

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

            print(f"{filename[:34]:<35} {sheet_name[:19]:<20} "
                  f"{linhas_original:>10,} {linhas_final:>10,} {duplicatas:>10,}")

            total_original += linhas_original
            total_final += linhas_final
            total_duplicatas += duplicatas

    print("-" * 80)
    print(f"{'TOTAL':<35} {'':<20} {total_original:>10,} {total_final:>10,} {total_duplicatas:>10,}")

    # Resumo final
    abas_mantidas = sum(1 for item in filter_report if item['status'] == 'MANTIDA')
    abas_removidas = len(filter_report) - abas_mantidas

    print(f"\n📈 RESUMO FINAL:")
    print(f"Arquivos processados: {len(clean_data)}")
    print(f"Abas mantidas: {abas_mantidas}")
    print(f"Abas removidas: {abas_removidas}")
    print(f"Linhas totais após processamento: {total_final:,}")
    print(f"Duplicatas removidas: {total_duplicatas:,}")
    if total_original > 0:
        print(f"Redução por duplicatas: {(total_duplicatas/total_original*100):.2f}%")

    print(f"\n✅ Dados processados disponíveis na variável 'arquivos_filtrados'")
    print("=" * 80)

    # === CÉLULA 3: Remoção de colunas desnecessárias ===
    print("\n🧹 CÉLULA 3: REMOÇÃO DE COLUNAS DESNECESSÁRIAS")
    print("=" * 60)

    clean_data_cols, cols_report = remove_unnecessary_columns(
        clean_data,
        colunas_remover=config['cleaning']['colunas_remover']
    )

    print(f"\n📊 COLUNAS REMOVIDAS POR ABA")
    print("=" * 80)
    print(f"{'ARQUIVO':<35} {'ABA':<20} {'ANTES':>10} {'DEPOIS':>10} {'REMOVIDAS':>10}")
    print("-" * 80)

    total_antes = 0
    total_depois = 0
    total_removidas_cols = 0

    for item in cols_report:
        print(f"{item['arquivo'][:34]:<35} {item['aba'][:19]:<20} "
              f"{item['colunas_antes']:>10} {item['colunas_depois']:>10} {item['removidas']:>10}")
        total_antes += item['colunas_antes']
        total_depois += item['colunas_depois']
        total_removidas_cols += item['removidas']

    print("-" * 80)
    print(f"{'TOTAL':<35} {'':<20} {total_antes:>10} {total_depois:>10} {total_removidas_cols:>10}")

    print(f"\n📈 RESUMO:")
    print(f"Total de colunas removidas: {total_removidas_cols}")
    print(f"\n✅ Dados sem colunas desnecessárias disponíveis")
    print("=" * 80)

    # === CÉLULA 4: Consolidação de datasets ===
    print("\n📊 CÉLULA 4: CONSOLIDAÇÃO DE DATASETS - PESQUISA E VENDAS")
    print("=" * 60)

    df_pesquisa, df_vendas = consolidate_datasets(
        clean_data_cols,
        pesquisa_keywords=config['consolidation']['pesquisa_keywords'],
        vendas_keywords=config['consolidation']['vendas_keywords']
    )

    # Função para gerar relatório de colunas (igual ao notebook)
    def gerar_relatorio_colunas(df, nome_dataset):
        """Gera relatório detalhado das colunas de um dataset"""

        print(f"\n{nome_dataset.upper()} - {len(df)} registros")
        print("=" * 70)
        print(f"{'COLUNA':<35} {'ÚNICOS':>10} {'% AUSENTES':>12} {'TOTAL':>10}")
        print("-" * 70)

        for col in df.columns:
            valores_unicos = df[col].nunique()
            valores_ausentes = df[col].isnull().sum()
            pct_ausentes = (valores_ausentes / len(df)) * 100 if len(df) > 0 else 0
            total_registros = len(df)

            print(f"{col[:34]:<35} {valores_unicos:>10,} {pct_ausentes:>11.1f}% {total_registros:>10,}")

    # Gerar relatórios
    gerar_relatorio_colunas(df_pesquisa, "DATASET PESQUISA")
    gerar_relatorio_colunas(df_vendas, "DATASET VENDAS")

    print(f"\nRESUMO:")
    print(f"Dataset Pesquisa: {len(df_pesquisa):,} registros, {len(df_pesquisa.columns)} colunas")
    print(f"Dataset Vendas: {len(df_vendas):,} registros, {len(df_vendas.columns)} colunas")

    print(f"\nDatasets consolidados disponíveis nas variáveis:")
    print(f"- dataset_pesquisa_final")
    print(f"- dataset_vendas_final")

    # === CÉLULA 5: Unificação de colunas duplicadas ===
    print("\n🔗 CÉLULA 5: UNIFICAÇÃO DE COLUNAS DUPLICADAS")
    print("=" * 60)

    df_pesquisa_final, df_vendas_final = unificar_colunas_datasets(df_pesquisa, df_vendas)

    print(f"\nRESULTADO:")
    print(f"Pesquisa: {len(df_pesquisa_final)} registros, {len(df_pesquisa_final.columns)} colunas")
    print(f"Vendas: {len(df_vendas_final)} registros, {len(df_vendas_final.columns)} colunas")

    # Gerar relatórios finais
    gerar_relatorio_colunas(df_pesquisa_final, "DATASET PESQUISA")
    gerar_relatorio_colunas(df_vendas_final, "DATASET VENDAS")

    # === CÉLULA 6: Pulada (exploratória) ===
    print("\n⏭️  CÉLULA 6: Pulando célula exploratória/informativa do notebook original de treino")

    # === CÉLULA 7: Unificação completa de categorias ===
    print("\n🏷️  CÉLULA 7: UNIFICAÇÃO COMPLETA DE CATEGORIAS")
    print("=" * 60)

    df_pesquisa_final_unificado = unificar_categorias_completo(df_pesquisa_final)

    # Gerar relatório final
    gerar_relatorio_final_categorias(df_pesquisa_final_unificado)

    # === CÉLULA 8: Remoção de features desnecessárias ===
    print("\n🗑️  CÉLULA 8: REMOÇÃO DE FEATURES DESNECESSÁRIAS")
    print("=" * 60)

    # Determinar se deve remover Medium (opção 3)
    remover_medium = (medium_strategy == 'remove')
    df_features_removidas = remover_features_desnecessarias(df_pesquisa_final_unificado, remover_medium=remover_medium)

    # Listar colunas restantes
    listar_colunas_restantes(df_features_removidas)

    # === CÉLULA 9: Pulada (exploratória) ===
    print("\n⏭️  CÉLULA 9: Pulando célula exploratória/informativa do notebook original de treino")

    # === CÉLULA 10: Unificação de UTM Source e Term ===
    print("\n🔤 CÉLULA 10: UNIFICAÇÃO DE UTM SOURCE E TERM")
    print("=" * 60)

    df_utm_unificado = unificar_utm_source_term(df_features_removidas)

    # Verificar consistência
    verificar_consistencia_utm(df_utm_unificado)

    # === CÉLULA 11: Unificação de UTM Medium - Extração de Públicos ===
    # (Pulada se medium_strategy='remove')
    if 'Medium' in df_utm_unificado.columns:
        print("\n🎯 CÉLULA 11: UNIFICAÇÃO DE UTM MEDIUM - EXTRAÇÃO DE PÚBLICOS")
        print("=" * 60)

        df_medium_unificado = extrair_publico_medium(df_utm_unificado)

        # Gerar relatório final
        relatorio_final_medium(df_medium_unificado)

        # === ANÁLISE TEMPORAL TEMPORÁRIA - MEDIUM ===
        print("\n" + "="*120)
        print("📊 ANÁLISE TEMPORAL TEMPORÁRIA - MEDIUM (ANTES DO MAPEAMENTO PARA 8 CATEGORIAS)")
        print("="*120)

        # Top 20 valores de Medium (após extração, antes do mapeamento)
        top_20_medium = df_medium_unificado['Medium'].value_counts(dropna=False).head(20)

        print(f"\nAnalisando top 20 categorias Medium...")
        print(f"Total de categorias únicas: {df_medium_unificado['Medium'].nunique()}")

        # Verificar se temos coluna de data
        if 'Data' in df_medium_unificado.columns:
            from pathlib import Path

            # Converter data se necessário
            if df_medium_unificado['Data'].dtype == 'object':
                df_medium_unificado['Data'] = pd.to_datetime(df_medium_unificado['Data'], errors='coerce')

            # Ler dados do Meta Ads para verificar produção
            print("\n🔍 Verificando categorias em produção (Meta Ads)...")
            meta_dir = Path("files/validation/meta_reports")
            subdirs = sorted([d for d in meta_dir.iterdir() if d.is_dir()],
                             key=lambda x: x.stat().st_mtime, reverse=True)

            meta_mediums_gestor = set()
            meta_mediums_rodolfo = set()
            relatorio_usado = "N/A"

            if subdirs:
                relatorio_usado = subdirs[0].name

                # Função para extrair público (mesma da célula 11)
                def extrair_publico_meta(medium_value):
                    if pd.isna(medium_value):
                        return medium_value
                    medium_str = str(medium_value).strip()
                    if '|' in medium_str:
                        partes = medium_str.split('|')
                        if len(partes) >= 2:
                            if partes[0].strip().upper() in ['ADV', 'ADV ']:
                                return partes[1].strip()
                            elif partes[0].strip().upper() in ['ABERTO']:
                                return 'Aberto'
                            else:
                                return partes[0].strip()
                    return medium_str

                # Ler Gestor de IA
                adset_files_gestor = list(subdirs[0].glob("**/*Gestor-de-IA*Conjuntos*.csv"))
                if adset_files_gestor:
                    df_meta = pd.read_csv(adset_files_gestor[0])
                    col = "Nome do conjunto de anúncios"
                    if col in df_meta.columns:
                        df_meta['Medium_extracted'] = df_meta[col].apply(extrair_publico_meta)
                        meta_mediums_gestor = set(df_meta['Medium_extracted'].dropna().unique())

                # Ler Rodolfo Mori
                adset_files_rodolfo = list(subdirs[0].glob("**/*Rodolfo-Mori*Conjuntos*.csv"))
                if adset_files_rodolfo:
                    df_meta = pd.read_csv(adset_files_rodolfo[0])
                    col = "Nome do conjunto de anúncios"
                    if col in df_meta.columns:
                        df_meta['Medium_extracted'] = df_meta[col].apply(extrair_publico_meta)
                        meta_mediums_rodolfo = set(df_meta['Medium_extracted'].dropna().unique())

            print(f"Relatório Meta usado: {relatorio_usado}")
            print(f"  Gestor de IA: {len(meta_mediums_gestor)} públicos")
            print(f"  Rodolfo Mori: {len(meta_mediums_rodolfo)} públicos")

            # Criar tabela de análise
            print(f"\n{'#':<3} {'MEDIUM':<42} {'COUNT':<8} {'%':<6} {'INÍCIO':<12} {'FIM':<12} {'GESTOR':<8} {'RODOLFO':<9}")
            print("-"*120)

            for i, (medium_val, count) in enumerate(top_20_medium.items(), 1):
                # Calcular percentual
                pct = count / len(df_medium_unificado) * 100

                # Filtrar dados desta categoria
                if pd.notna(medium_val):
                    df_cat = df_medium_unificado[df_medium_unificado['Medium'] == medium_val]
                else:
                    df_cat = df_medium_unificado[df_medium_unificado['Medium'].isna()]

                # Extrair datas
                dates = df_cat['Data'].dropna()
                if len(dates) > 0:
                    data_inicio = dates.min().strftime('%Y-%m-%d')
                    data_fim = dates.max().strftime('%Y-%m-%d')
                else:
                    data_inicio = 'N/A'
                    data_fim = 'N/A'

                # Verificar se está em produção
                em_gestor = 'Sim' if medium_val in meta_mediums_gestor else 'Não'
                em_rodolfo = 'Sim' if medium_val in meta_mediums_rodolfo else 'Não'

                # Preparar string do medium
                medium_str = str(medium_val) if pd.notna(medium_val) else 'nan'
                medium_display = medium_str[:39] + '...' if len(medium_str) > 39 else medium_str

                print(f"{i:<3} {medium_display:<42} {count:<8,} {pct:<6.1f} {data_inicio:<12} {data_fim:<12} {em_gestor:<8} {em_rodolfo:<9}")

            # Resumo
            print("\n" + "="*120)
            print("RESUMO DA ANÁLISE")
            print("="*120)

            em_prod_gestor = sum(1 for val, _ in top_20_medium.items() if val in meta_mediums_gestor)
            em_prod_rodolfo = sum(1 for val, _ in top_20_medium.items() if val in meta_mediums_rodolfo)
            em_prod_ambos = sum(1 for val, _ in top_20_medium.items()
                                if val in meta_mediums_gestor and val in meta_mediums_rodolfo)
            nao_em_prod = sum(1 for val, _ in top_20_medium.items()
                              if val not in meta_mediums_gestor and val not in meta_mediums_rodolfo)

            print(f"Top 20 categorias analisadas (após extração, ANTES do mapeamento)")
            print(f"  Em produção (Gestor de IA): {em_prod_gestor}/20")
            print(f"  Em produção (Rodolfo Mori): {em_prod_rodolfo}/20")
            print(f"  Em produção (ambas contas): {em_prod_ambos}/20")
            print(f"  NÃO em produção: {nao_em_prod}/20")
            print(f"\nRelatório Meta utilizado: {relatorio_usado}")
            print("="*120 + "\n")
        else:
            print("⚠️  Coluna 'Data' não encontrada - análise temporal não disponível")
    else:
        print("\n⏭️  CÉLULA 11: Pulando (Medium foi removido na célula 8 - strategy='remove')")
        df_medium_unificado = df_utm_unificado.copy()

    # === CÉLULA 11.1: Unificação de Medium para Produção ===
    if 'Medium' in df_medium_unificado.columns:
        print("\n🔧 CÉLULA 11.1: UNIFICAÇÃO DE UTM MEDIUM PARA PRODUÇÃO")
        print("=" * 60)

        print("Iniciando processo de unificação para produção...")
        df_original = df_medium_unificado.copy()
        df_medium_producao = unificar_medium_para_producao(df_medium_unificado)

        # Gerar relatório
        relatorio_unificacao_producao(df_original, df_medium_producao)

        print(f"\nProcesso concluído!")
        print(f"Dataset final disponível em: pesquisa_medium_producao_unificado")
        print(f"Este dataset está pronto para o pipeline de produção e não gerará incompatibilidades!")
    else:
        print("\n⏭️  CÉLULA 11.1: Pulando (Medium foi removido na célula 8 - strategy='remove')")
        df_medium_producao = df_medium_unificado.copy()

    # === CÉLULA 12: Pulada (exploratória) ===
    print("\n⏭️  CÉLULA 12: Pulando célula exploratória/informativa do notebook original de treino")

    # === CÉLULA 13: Criação de versão do dataset por missing rate ===
    print("\n📋 CÉLULA 13: CRIAÇÃO DE VERSÕES DO DATASET POR MISSING RATE")
    print("=" * 60)

    print("Iniciando criação das versões...")
    df_pos_cutoff = criar_dataset_pos_cutoff(df_medium_producao)

    # Disponibilizar dataset
    disponibilizar_dataset(df_pos_cutoff)

    print(f"\nProcesso concluído!")
    print(f"Duas versões do dataset criadas com sucesso.")

    # === CÉLULA 14: Pulada (exploratória) ===
    print("\n⏭️  CÉLULA 14: Pulando célula exploratória/informativa do notebook original de treino")

    # === CÉLULA 15: Matching robusto por email e telefone ===
    print(f"\n🔍 CÉLULA 15: MATCHING DE LEADS COM VENDAS ({initial_matching.upper().replace('_', ' ')})")
    print("=" * 60)

    # APLICAR FILTRO GURU ONLY apenas para matching (treino do modelo)
    # Manter df_vendas_final completo (Guru + TMB) para cálculo do recall
    df_vendas_matching = df_vendas_final.copy()

    if use_guru_only and 'arquivo_origem' in df_vendas_matching.columns:
        before_filter = len(df_vendas_matching)
        # Filtrar apenas vendas Guru para matching/treino
        df_vendas_matching = df_vendas_matching[
            df_vendas_matching['arquivo_origem'].str.lower().str.contains('guru', na=False)
        ].copy()
        after_filter = len(df_vendas_matching)

        if before_filter != after_filter:
            print(f"\n🔧 GURU ONLY - Filtro aplicado ao matching:")
            print(f"   Vendas Guru para matching: {after_filter:,}")
            print(f"   Vendas TMB excluídas do matching: {before_filter - after_filter:,}")
            print(f"   (Vendas TMB serão incluídas no cálculo do recall)\n")

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
    else:
        raise ValueError(f"Método de matching inicial inválido: {initial_matching}. Use 'email_only', 'email_telefone', 'variantes', 'robusto' ou 'validation'")

    # === CÉLULA 16: Pulada (exploratória) ===
    print("\n⏭️  CÉLULA 16: Pulando célula exploratória/informativa do notebook original de treino")

    # === CÉLULA 17: Filtragem DevClub ===
    print(f"\n🎓 CÉLULA 17: FILTRAGEM DEVCLUB + JANELA DE CONVERSÃO")
    print("=" * 60)

    dataset_v1_devclub = criar_dataset_devclub(dataset_v1_final, df_vendas_final)

    # Aplicar janela de conversão de 20 dias (captação + CPL + carrinho)
    # Captação: 7 dias (terça-segunda) + CPL: 6 dias (terça-domingo) + Carrinho: 7 dias (segunda-domingo) = 20 dias
    dataset_v1_devclub = aplicar_janela_conversao(
        df_leads=dataset_v1_devclub,
        df_vendas=df_vendas_final,
        janela_dias=20
    )

    # === ANÁLISE TEMPORÁRIA: TAXA DE CONVERSÃO POR MEDIUM ===
    if 'Medium' in dataset_v1_devclub.columns and 'target' in dataset_v1_devclub.columns:
        print("\n" + "="*100)
        print("📊 ANÁLISE TEMPORÁRIA: TAXA DE CONVERSÃO POR CATEGORIA MEDIUM")
        print("="*100)

        analysis = dataset_v1_devclub.groupby('Medium').agg({
            'target': ['count', 'sum', 'mean']
        })
        analysis.columns = ['Total_Leads', 'Conversões', 'Taxa_Conversão']
        analysis['Pct_Leads'] = (analysis['Total_Leads'] / analysis['Total_Leads'].sum() * 100)
        analysis['Taxa_Conv_%'] = (analysis['Taxa_Conversão'] * 100)
        analysis = analysis.sort_values('Total_Leads', ascending=False)

        taxa_global = (analysis['Conversões'].sum() / analysis['Total_Leads'].sum() * 100)

        print(f"\n{'CATEGORIA':<50} {'LEADS':>10} {'%TOTAL':>7} {'CONV':>7} {'TAXA':>7} {'vs MÉDIA':>10}")
        print("-"*100)

        for idx, row in analysis.iterrows():
            categoria = str(idx)[:48]
            leads = int(row['Total_Leads'])
            pct = row['Pct_Leads']
            conv = int(row['Conversões'])
            taxa = row['Taxa_Conv_%']
            diff = taxa - taxa_global
            diff_str = f"{diff:+.2f}pp"
            print(f"{categoria:<50} {leads:>10,} {pct:>6.1f}% {conv:>7,} {taxa:>6.2f}% {diff_str:>10}")

        print("\n" + "-"*100)
        print(f"{'MÉDIA GLOBAL':<50} {int(analysis['Total_Leads'].sum()):>10,} {'100.0%':>7} {int(analysis['Conversões'].sum()):>7,} {taxa_global:>6.2f}%")

        # Análise TOP 3 vs OUTROS
        print("\n" + "="*100)
        print("🎯 COMPARAÇÃO: TOP 3 (binary_top3) vs OUTROS (agrupados como [0,0,0])")
        print("="*100)

        top3 = ['Linguagem de programação', 'Aberto', 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses']
        top3_data = analysis[analysis.index.isin(top3)]
        outros_data = analysis[~analysis.index.isin(top3)]

        top3_leads = top3_data['Total_Leads'].sum()
        top3_conv = top3_data['Conversões'].sum()
        top3_taxa = (top3_conv / top3_leads * 100)

        outros_leads = outros_data['Total_Leads'].sum()
        outros_conv = outros_data['Conversões'].sum()
        outros_taxa = (outros_conv / outros_leads * 100) if outros_leads > 0 else 0

        print(f"\nTOP 3: {int(top3_leads):,} leads ({top3_leads/analysis['Total_Leads'].sum()*100:.1f}%) - Taxa: {top3_taxa:.2f}%")
        print(f"OUTROS: {int(outros_leads):,} leads ({outros_leads/analysis['Total_Leads'].sum()*100:.1f}%) - Taxa: {outros_taxa:.2f}%")
        print(f"DIFERENÇA: {top3_taxa - outros_taxa:+.2f}pp")

        if abs(top3_taxa - outros_taxa) < 0.1:
            print("\n✅ Taxas muito similares - agrupar OUTROS como [0,0,0] parece razoável")
        elif abs(top3_taxa - outros_taxa) > 0.2:
            print(f"\n⚠️  ATENÇÃO: Diferença significativa ({abs(top3_taxa - outros_taxa):.2f}pp)!")
            print("   Considerar adicionar categorias importantes de OUTROS ao encoding")

            # Mostrar categorias OUTROS com maior volume ou taxa discrepante
            print("\n   Categorias OUTROS ordenadas por volume:")
            for idx, row in outros_data.head(5).iterrows():
                categoria = str(idx)[:45]
                leads = int(row['Total_Leads'])
                taxa = row['Taxa_Conv_%']
                diff = taxa - outros_taxa
                print(f"     • {categoria:<45} {leads:>8,} leads - {taxa:.2f}% ({diff:+.2f}pp vs média OUTROS)")

        print("="*100 + "\n")

    # === LOG: VERIFICAÇÃO DE PRODUTOS DEVCLUB ===
    print("\n" + "=" * 80)
    print("VERIFICAÇÃO DE PRODUTOS DEVCLUB - Análise Completa")
    print("=" * 80)

    # 1. Listar TODOS os produtos que contêm "devclub"
    print("\n📋 TODOS OS PRODUTOS COM 'DEVCLUB' NO NOME:")
    print("-" * 80)

    produtos_com_devclub = df_vendas_final[
        df_vendas_final['produto'].fillna('').str.lower().str.contains('devclub', na=False)
    ]['produto'].value_counts()

    print(f"\nTotal de variações encontradas: {len(produtos_com_devclub)}")
    print("\nProdutos e quantidade de vendas:")
    for produto, count in produtos_com_devclub.items():
        print(f"  {count:>5} vendas | {produto}")

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
    print("\n" + "=" * 80)
    print("⚠️  PRODUTOS NÃO CONTABILIZADOS (existem mas não estão na lista):")
    print("-" * 80)

    produtos_nao_contabilizados = []
    vendas_perdidas = 0

    for produto in produtos_com_devclub.index:
        if produto not in produtos_devclub_lista_atual:
            produtos_nao_contabilizados.append(produto)
            vendas_perdidas += produtos_com_devclub[produto]
            print(f"  {produtos_com_devclub[produto]:>5} vendas | {produto}")

    if not produtos_nao_contabilizados:
        print("  ✅ Nenhum produto perdido! Todos estão sendo contabilizados.")
    else:
        print(f"\n  ⚠️  TOTAL DE VENDAS PERDIDAS: {vendas_perdidas}")

    # 4. Verificar produtos na lista que NÃO existem
    print("\n" + "=" * 80)
    print("🔍 PRODUTOS NA LISTA MAS SEM VENDAS:")
    print("-" * 80)

    produtos_sem_vendas = []
    for produto in produtos_devclub_lista_atual:
        if produto not in produtos_com_devclub.index:
            produtos_sem_vendas.append(produto)
            print(f"  ⚠️  {produto}")

    if not produtos_sem_vendas:
        print("  ✅ Todos os produtos da lista têm vendas!")

    # 5. Usar lista hardcoded (investigada manualmente)
    produtos_devclub = produtos_devclub_lista_atual

    print("\n" + "=" * 80)
    print("✅ USANDO LISTA HARDCODED (investigada manualmente)")
    print("=" * 80)
    print(f"Total de produtos na lista: {len(produtos_devclub)}")

    if produtos_nao_contabilizados:
        print(f"\n⚠️  ATENÇÃO: {vendas_perdidas} vendas de produtos não contabilizados serão IGNORADAS")
        print(f"   (Produtos descobertos automaticamente mas não na lista hardcoded)")

    if produtos_sem_vendas:
        print(f"\n⚠️  ATENÇÃO: {len(produtos_sem_vendas)} produtos na lista NÃO têm vendas no período")
        print(f"   (Produtos hardcoded mas sem vendas encontradas)")

    # === LOG: CÁLCULO DE RECALL E FATOR DE CORREÇÃO ===
    print("\n" + "=" * 80)
    print("CÁLCULO DE RECALL - Conversões Observadas vs Vendas Reais")
    print("=" * 80)

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

    print(f"\n📊 DADOS:")
    print(f"  Total de leads: {total_leads:,}")
    print(f"  Conversões OBSERVADAS (matches): {conversoes_observadas}")
    print(f"  Vendas REAIS (sem duplicatas): {vendas_reais:,}")

    print(f"\n📈 TAXAS:")
    print(f"  Taxa OBSERVADA: {taxa_observada*100:.4f}%")
    print(f"  Taxa REAL: {taxa_real*100:.4f}%")

    print(f"\n🔧 MÉTRICAS:")
    print(f"  Recall: {recall*100:.1f}%")
    print(f"  Fator de correção: {fator_correcao:.3f}x")

    if fator_correcao > 1:
        print(f"\n💡 IMPACTO:")
        print(f"  Estamos SUBESTIMANDO em {fator_correcao:.3f}x")
        print(f"  Valores CAPI deveriam ser {(fator_correcao-1)*100:.0f}% maiores")

    print("=" * 80)

    # Criar dicionário com métricas de recall para passar ao registro do modelo
    recall_metrics = {
        'vendas_devclub_total': vendas_reais,
        'vendas_matched': conversoes_observadas,
        'recall': recall,
        'fator_correcao': fator_correcao
    }

    # === CÉLULA 18: Feature Engineering ===
    print(f"\n⚙️  CÉLULA 18: FEATURE ENGINEERING")
    print("=" * 60)
    # IMPORTANTE: FE será aplicado no dataset COM ou SEM temporais
    # Se temporais foram adicionadas, FE vai criar 7 features E remover Data/Nome/etc
    # Resultado final: 4 temporais + 7 FE + 15 base = 26 colunas
    dataset_v1_devclub_fe = criar_features_derivadas(dataset_v1_devclub)

    # === CÉLULA 19: Pulada (exploratória) ===
    print("\n⏭️  CÉLULA 19: Pulando célula exploratória/informativa do notebook original de treino")

    # === CÉLULA 20: Encoding Estratégico ===
    print(f"\n🔢 CÉLULA 20: ENCODING ESTRATÉGICO")
    print("=" * 60)
    dataset_v1_devclub_encoded = aplicar_encoding_estrategico(dataset_v1_devclub_fe, medium_strategy=medium_strategy)

    # === HYPERPARAMETER TUNING (opcional) ===
    melhores_params = None
    if tune_hyperparams:
        print("\n" + "=" * 80)
        print("EXECUTANDO HYPERPARAMETER TUNING")
        print("=" * 80)

        resultado_tuning = hyperparameter_tuning(
            dataset_v1_devclub_encoded,
            dataset_v1_devclub,
            grid_size=grid_size
        )

        if resultado_tuning and resultado_tuning['usar_tunado']:
            melhores_params = resultado_tuning['melhores_params']
            print(f"\n✅ Usando hiperparâmetros tunados no treino final")
        else:
            print(f"\n⚠️  Mantendo hiperparâmetros baseline (tuning não trouxe ganho significativo)")

    # === CÉLULA MODELAGEM: Treino e Registro do Modelo ===
    resultado_registro_devclub = registrar_features_e_modelo_devclub(
        dataset_v1_devclub_encoded,
        dataset_v1_devclub,
        save_files=save_files,
        matching_method=initial_matching,
        custom_hyperparams=melhores_params,
        split_method=split_method,
        set_active=set_active,
        recall_metrics=recall_metrics
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Pipeline de treino DevClub')
    parser.add_argument(
        '--initial-matching',
        type=str,
        choices=['email_only', 'email_telefone', 'variantes', 'robusto', 'validation'],
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
        '--use-guru-only',
        type=str,
        choices=['true', 'false'],
        default=None,
        help='Filtro de produtos: true (apenas GURU), false (GURU+TMB) - padrão: usar config'
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

    args = parser.parse_args()

    # Converter string para bool se fornecido
    use_guru_only = None
    if args.use_guru_only:
        use_guru_only = args.use_guru_only.lower() == 'true'

    main(
        initial_matching=args.initial_matching,
        save_files=args.save_files,
        tune_hyperparams=args.tune_hyperparams,
        grid_size=args.grid_size,
        split_method=args.split_method,
        use_guru_only=use_guru_only,
        set_active=args.set_active,
        medium_strategy=args.medium_strategy
    )
