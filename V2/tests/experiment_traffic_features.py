"""
Experimento: Impacto de Features de Tráfego Meta no Lead Scoring.

Treina modelo COM features de tráfego e registra no MLflow para comparação.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import yaml
import glob
import logging
import pandas as pd
import mlflow

from src.data_processing.ingestion import (
    read_excel_files,
    filter_sheets,
    remove_duplicates_per_sheet,
    remove_unnecessary_columns,
    consolidate_datasets
)
from src.data_processing.column_unification import unificar_colunas_datasets
from src.data_processing.category_unification import unificar_categorias_completo
from src.data_processing.feature_removal import remover_features_desnecessarias
from src.data_processing.utm_training import unificar_utm_source_term
from src.data_processing.medium_training import extrair_publico_medium
from src.data_processing.medium_production_training import unificar_medium_para_producao
from src.data_processing.dataset_versioning_training import criar_dataset_pos_cutoff
from src.matching.matching_email_telefone import fazer_matching_email_telefone
from src.data_processing.devclub_filtering_training import criar_dataset_devclub
from src.data_processing.conversion_window import aplicar_janela_conversao
from src.features.feature_engineering_training import criar_features_derivadas
from src.features.encoding_training import aplicar_encoding_estrategico
from src.model.training_model import registrar_features_e_modelo_devclub

# ADICIONAR: importar função de features de tráfego
from src.data_processing.traffic_features import adicionar_features_trafego_meta

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def run_experiment_with_traffic_features(
    initial_matching='email_telefone',
    save_files=False,
    split_method='temporal',
    pasta_trafego='/Users/ramonmoreira/Desktop/smart_ads/data/devclub/treino/features_trafego'
):
    """
    Executa experimento com features de tráfego Meta.

    Replica pipeline de treino + adiciona features de tráfego antes do modelo.
    MLflow registra automaticamente todas as métricas.

    Args:
        initial_matching: Método de matching ('email_telefone' padrão)
        save_files: Se True, salva arquivos locais
        split_method: Método de split ('temporal' padrão)
        pasta_trafego: Caminho para pasta com CSVs Meta

    Returns:
        Dicionário com resultados do experimento
    """

    print("\n" + "="*80)
    print("🧪 EXPERIMENTO: FEATURES DE TRÁFEGO META")
    print("="*80)
    print(f"\n🔧 CONFIGURAÇÃO:")
    print(f"   Matching: {initial_matching}")
    print(f"   Split: {split_method}")
    print(f"   Features de tráfego: {pasta_trafego}")
    print("="*80)

    # Carregar configuração
    config_path = os.path.join(os.path.dirname(__file__), '../configs/devclub.yaml')
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # =========================================================================
    # PIPELINE DE TREINO (até feature engineering)
    # =========================================================================

    # CÉLULA 1: Leitura
    print("\n📤 CÉLULA 1: LEITURA DE ARQUIVOS")
    data_dir = config['ingestion']['training_data_dir']

    def notebook_sort_key(filepath):
        basename = os.path.basename(filepath).lower()
        return basename.replace('[', '!')

    filepaths = sorted(glob.glob(os.path.join(data_dir, "*.xlsx")), key=notebook_sort_key)

    # Filtro GURU only (se configurado)
    use_guru_only = config['ingestion'].get('use_guru_only', False)
    if use_guru_only:
        filepaths = [f for f in filepaths if 'guru' in os.path.basename(f).lower()
                     or 'pesquisa' in os.path.basename(f).lower()
                     or 'lead' in os.path.basename(f).lower()]

    print(f"Arquivos: {len(filepaths)}")
    all_data = read_excel_files(filepaths)

    # CÉLULA 2: Filtragem + Duplicatas
    print("\n🔄 CÉLULA 2: FILTRAGEM + DUPLICATAS")
    filtered_data, _ = filter_sheets(
        all_data,
        termos_manter=config['ingestion']['termos_manter'],
        termos_remover=config['ingestion']['termos_remover'],
        min_linhas=config['ingestion']['min_linhas']
    )
    clean_data, _ = remove_duplicates_per_sheet(filtered_data)

    # CÉLULA 3: Remoção de colunas
    print("\n🧹 CÉLULA 3: REMOÇÃO DE COLUNAS")
    clean_data_cols, _ = remove_unnecessary_columns(
        clean_data,
        colunas_remover=config['cleaning']['colunas_remover']
    )

    # CÉLULA 4: Consolidação
    print("\n📦 CÉLULA 4: CONSOLIDAÇÃO")
    df_pesquisa, df_vendas = consolidate_datasets(
        clean_data_cols,
        pesquisa_keywords=config['consolidation']['pesquisa_keywords'],
        vendas_keywords=config['consolidation']['vendas_keywords']
    )

    # CÉLULA 5: Unificação de colunas
    print("\n🔗 CÉLULA 5: UNIFICAÇÃO DE COLUNAS")
    df_pesquisa_final, df_vendas_final = unificar_colunas_datasets(df_pesquisa, df_vendas)

    # CÉLULA 7: Unificação de categorias
    print("\n📋 CÉLULA 7: CATEGORIAS")
    df_pesquisa_final_unificado = unificar_categorias_completo(df_pesquisa_final)

    # CÉLULA 8: Remoção de features
    print("\n🗑️  CÉLULA 8: REMOÇÃO DE FEATURES")
    df_features_removidas = remover_features_desnecessarias(df_pesquisa_final_unificado)

    # CÉLULA 10: UTM Source/Term
    print("\n🏷️  CÉLULA 10: UTM SOURCE/TERM")
    df_utm_unificado = unificar_utm_source_term(df_features_removidas)

    # CÉLULA 11: UTM Medium
    print("\n🎯 CÉLULA 11: UTM MEDIUM")
    df_medium_unificado = extrair_publico_medium(df_utm_unificado)

    # CÉLULA 11.1: Medium Produção
    print("\n🏭 CÉLULA 11.1: MEDIUM PRODUÇÃO")
    df_medium_producao = unificar_medium_para_producao(df_medium_unificado)

    # CÉLULA 13: Pós-cutoff
    print("\n📅 CÉLULA 13: PÓS-CUTOFF")
    df_pos_cutoff = criar_dataset_pos_cutoff(df_medium_producao)

    # CÉLULA 15: Matching
    print(f"\n🔍 CÉLULA 15: MATCHING ({initial_matching})")
    dataset_v1_final = fazer_matching_email_telefone(df_pos_cutoff, df_vendas_final)

    # CÉLULA 17: DevClub + Janela
    print("\n🎓 CÉLULA 17: DEVCLUB + JANELA")
    dataset_v1_devclub = criar_dataset_devclub(dataset_v1_final, df_vendas_final)
    dataset_v1_devclub = aplicar_janela_conversao(
        df_leads=dataset_v1_devclub,
        df_vendas=df_vendas_final,
        janela_dias=20
    )

    # Salvar cópia ANTES do feature engineering (para ter Data e Medium originais)
    dataset_antes_fe = dataset_v1_devclub.copy()

    # CÉLULA 18: Feature Engineering
    print("\n⚙️  CÉLULA 18: FEATURE ENGINEERING")
    dataset_v1_devclub_fe = criar_features_derivadas(dataset_v1_devclub)

    # =========================================================================
    # ✨ ADICIONAR FEATURES DE TRÁFEGO META ✨
    # =========================================================================

    print("\n" + "="*80)
    print("✨ ADICIONANDO FEATURES DE TRÁFEGO META")
    print("="*80)

    # Adicionar features de tráfego ANTES do encoding
    dataset_v1_devclub_fe_traffic = adicionar_features_trafego_meta(
        df_leads=dataset_v1_devclub_fe,
        pasta_trafego=pasta_trafego,
        coluna_medium='Medium'
    )

    print(f"\n✅ Features de tráfego adicionadas!")
    print(f"   Colunas antes: {len(dataset_v1_devclub_fe.columns)}")
    print(f"   Colunas depois: {len(dataset_v1_devclub_fe_traffic.columns)}")

    colunas_novas = set(dataset_v1_devclub_fe_traffic.columns) - set(dataset_v1_devclub_fe.columns)
    print(f"   Novas features ({len(colunas_novas)}): {sorted(colunas_novas)}")

    # =========================================================================
    # CÉLULA 20: Encoding
    # =========================================================================

    print("\n🔢 CÉLULA 20: ENCODING")
    dataset_v1_devclub_encoded = aplicar_encoding_estrategico(dataset_v1_devclub_fe_traffic)

    # =========================================================================
    # PREPARAÇÃO FINAL: ALINHAR ÍNDICES
    # =========================================================================

    # CRÍTICO: Resetar índices para garantir alinhamento entre datasets
    dataset_antes_fe = dataset_antes_fe.reset_index(drop=True)
    dataset_v1_devclub_encoded = dataset_v1_devclub_encoded.reset_index(drop=True)

    print(f"\n✅ Índices alinhados:")
    print(f"   Dataset original: {len(dataset_antes_fe)} registros")
    print(f"   Dataset encoded: {len(dataset_v1_devclub_encoded)} registros")

    # =========================================================================
    # TREINO DO MODELO (com MLflow)
    # =========================================================================

    print("\n" + "="*80)
    print("🤖 TREINANDO MODELO COM FEATURES DE TRÁFEGO")
    print("="*80)

    # Treinar modelo (MLflow registra automaticamente dentro de training_model.py)
    resultado = registrar_features_e_modelo_devclub(
        dataset_devclub_encoded=dataset_v1_devclub_encoded,
        dataset_devclub_original=dataset_antes_fe,  # Com Data e Medium originais
        save_files=save_files,
        matching_method=initial_matching,
        custom_hyperparams=None,
        split_method=split_method,
        set_active=False  # Não tornar ativo automaticamente
    )

    # Adicionar informações extras ao resultado
    resultado['traffic_features_count'] = len(colunas_novas)
    resultado['traffic_features'] = sorted(colunas_novas)
    resultado['mlflow_run_id'] = resultado.get('run_id', 'N/A')

    # Adicionar tags específicas do experimento ao run MLflow
    run_id = resultado.get('run_id')
    if run_id:
        with mlflow.start_run(run_id=run_id):
            mlflow.set_tag("experiment_type", "traffic_features")
            mlflow.set_tag("traffic_features", "enabled")
            mlflow.log_param("traffic_features_count", len(colunas_novas))

    # =========================================================================
    # RESUMO FINAL
    # =========================================================================

    print("\n" + "="*80)
    print("🎉 EXPERIMENTO CONCLUÍDO")
    print("="*80)
    print(f"MLflow Run ID: {resultado['mlflow_run_id']}")
    print(f"\n📊 MÉTRICAS:")
    print(f"   AUC: {resultado['auc']:.4f}")
    print(f"   Top 3 Decis: {resultado['top3']:.2f}%")
    print(f"   Lift Máximo: {resultado['lift']:.2f}x")
    print(f"   Monotonia: {resultado['monotonia']:.1f}%")
    print(f"\n🔢 FEATURES:")
    print(f"   Total: {resultado['features_count']}")
    print(f"   Traffic: {resultado['traffic_features_count']}")

    print(f"\n💡 PRÓXIMOS PASSOS:")
    print(f"   1. Comparar com baseline no MLflow UI:")
    print(f"      mlflow ui --backend-store-uri sqlite:///mlflow.db")
    print(f"   2. Ou usar: python tests/compare_mlflow_runs.py")

    return resultado


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Experimento com features de tráfego Meta')
    parser.add_argument(
        '--initial-matching',
        type=str,
        choices=['email_only', 'email_telefone', 'variantes', 'robusto', 'validation'],
        default='email_telefone',
        help='Método de matching'
    )
    parser.add_argument(
        '--save-files',
        action='store_true',
        help='Salvar arquivos locais'
    )
    parser.add_argument(
        '--split-method',
        type=str,
        choices=['temporal', 'temporal_leads', 'stratified'],
        default='temporal',
        help='Método de split'
    )
    parser.add_argument(
        '--pasta-trafego',
        type=str,
        default='/Users/ramonmoreira/Desktop/smart_ads/data/devclub/treino/features_trafego',
        help='Caminho para pasta com CSVs Meta'
    )

    args = parser.parse_args()

    resultado = run_experiment_with_traffic_features(
        initial_matching=args.initial_matching,
        save_files=args.save_files,
        split_method=args.split_method,
        pasta_trafego=args.pasta_trafego
    )

    print(f"\n✅ Experimento finalizado com sucesso!")
    print(f"   Run ID: {resultado['mlflow_run_id']}")
