"""
Experimento: Impacto de Features Temporais de Medium no Lead Scoring.

Treina modelo COM features temporais (densidade, tendência, rank) e registra no MLflow.
Usa apenas dados dos leads (não requer dados do Meta).
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

# ADICIONAR: importar função de features temporais
from src.data_processing.traffic_features import adicionar_features_temporais_medium

# Configurar logging - Desabilitar INFO para não poluir output
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Desabilitar INFO de todos os módulos importados
for module_name in ['src.data_processing', 'src.features', 'src.matching', 'src.model']:
    logging.getLogger(module_name).setLevel(logging.WARNING)


def run_experiment_with_temporal_features(
    initial_matching='email_telefone',
    save_files=False,
    split_method='temporal'
):
    """
    Executa experimento com features temporais de Medium.

    Replica pipeline de treino + adiciona features temporais (densidade, tendência, rank)
    antes do modelo. MLflow registra automaticamente todas as métricas.

    Args:
        initial_matching: Método de matching ('email_telefone' padrão)
        save_files: Se True, salva arquivos locais
        split_method: Método de split ('temporal' padrão)

    Returns:
        Dicionário com resultados do experimento
    """

    print("\n" + "="*80)
    print("🧪 EXPERIMENTO: FEATURES TEMPORAIS DE MEDIUM")
    print("="*80)
    print(f"\n🔧 CONFIGURAÇÃO:")
    print(f"   Matching: {initial_matching}")
    print(f"   Split: {split_method}")
    print(f"   Features: densidade_7d, densidade_30d, tendência, rank")
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

    print(f"Arquivos encontrados: {len(filepaths)}")
    for i, fp in enumerate(filepaths, 1):
        print(f"   {i}. {os.path.basename(fp)}")

    all_data = read_excel_files(filepaths)

    # Contar total de abas
    total_abas = sum(len(abas) for abas in all_data.values())
    print(f"\n✅ Total de abas lidas: {total_abas}")

    # Mostrar primeiras 5 abas de qualquer arquivo
    print(f"Primeiras 5 abas:")
    count = 0
    for arquivo, abas_dict in all_data.items():
        for aba_nome, df in abas_dict.items():
            if count < 5:
                print(f"   {count+1}. {os.path.basename(arquivo)} → {aba_nome}: {df.shape}")
                count += 1
            else:
                break
        if count >= 5:
            break

    # CÉLULA 2: Filtragem + Duplicatas
    print("\n🔄 CÉLULA 2: FILTRAGEM + DUPLICATAS")
    filtered_data, _ = filter_sheets(
        all_data,
        termos_manter=config['ingestion']['termos_manter'],
        termos_remover=config['ingestion']['termos_remover'],
        min_linhas=config['ingestion']['min_linhas']
    )
    print(f"Abas após filtragem: {len(filtered_data)} (eram {len(all_data)})")
    print(f"Removidas: {len(all_data) - len(filtered_data)}")

    clean_data, _ = remove_duplicates_per_sheet(filtered_data)
    print(f"✅ Duplicatas removidas")

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
    print(f"\n✅ Consolidação completa:")
    print(f"   📊 Pesquisa (Leads): {df_pesquisa.shape}")
    print(f"   📊 Vendas: {df_vendas.shape}")
    print(f"\n   Colunas Pesquisa ({len(df_pesquisa.columns)}): {list(df_pesquisa.columns)}")

    # CÉLULA 5: Unificação de colunas
    print("\n🔗 CÉLULA 5: UNIFICAÇÃO DE COLUNAS")
    df_pesquisa_final, df_vendas_final = unificar_colunas_datasets(df_pesquisa, df_vendas)
    print(f"✅ Colunas unificadas: {df_pesquisa.shape} → {df_pesquisa_final.shape}")

    # CÉLULA 7: Unificação de categorias
    print("\n📋 CÉLULA 7: CATEGORIAS")
    df_pesquisa_final_unificado = unificar_categorias_completo(df_pesquisa_final)
    print(f"✅ Categorias unificadas: {df_pesquisa_final.shape} → {df_pesquisa_final_unificado.shape}")

    # CÉLULA 8: Remoção de features
    print("\n🗑️  CÉLULA 8: REMOÇÃO DE FEATURES")
    df_features_removidas = remover_features_desnecessarias(df_pesquisa_final_unificado)
    colunas_removidas = set(df_pesquisa_final_unificado.columns) - set(df_features_removidas.columns)
    print(f"✅ Features removidas: {df_pesquisa_final_unificado.shape} → {df_features_removidas.shape}")
    if colunas_removidas:
        print(f"   Colunas removidas ({len(colunas_removidas)}): {sorted(colunas_removidas)}")

    # CÉLULA 10: UTM Source/Term
    print("\n🏷️  CÉLULA 10: UTM SOURCE/TERM")
    df_utm_unificado = unificar_utm_source_term(df_features_removidas)
    print(f"✅ UTM Source/Term unificados: {df_features_removidas.shape} → {df_utm_unificado.shape}")
    print(f"\n📊 Distribuição Source:")
    print(df_utm_unificado['Source'].value_counts().to_string())
    print(f"\n📊 Distribuição Term:")
    print(df_utm_unificado['Term'].value_counts().to_string())

    # CÉLULA 11: UTM Medium
    print("\n🎯 CÉLULA 11: UTM MEDIUM")
    df_medium_unificado = extrair_publico_medium(df_utm_unificado)
    print(f"✅ Público extraído: {df_utm_unificado.shape} → {df_medium_unificado.shape}")

    # CÉLULA 11.1: Medium Produção
    print("\n🏭 CÉLULA 11.1: MEDIUM PRODUÇÃO")
    df_medium_producao = unificar_medium_para_producao(df_medium_unificado)
    print(f"✅ Medium produção: {df_medium_unificado.shape} → {df_medium_producao.shape}")
    print(f"\n📊 Distribuição Medium (8 categorias produção):")
    for i, (medium, count) in enumerate(df_medium_producao['Medium'].value_counts().items(), 1):
        pct = count / len(df_medium_producao) * 100
        print(f"   {i}. {medium}: {count:,} ({pct:.1f}%)")

    # CÉLULA 13: Pós-cutoff
    print("\n📅 CÉLULA 13: PÓS-CUTOFF (2025-03-01)")
    df_pos_cutoff = criar_dataset_pos_cutoff(df_medium_producao)
    print(f"✅ Pós-cutoff: {df_medium_producao.shape} → {df_pos_cutoff.shape}")
    print(f"   Removidos: {len(df_medium_producao) - len(df_pos_cutoff):,} registros")
    if 'Data' in df_pos_cutoff.columns:
        print(f"\n📅 Range de datas:")
        print(f"   Mínima: {df_pos_cutoff['Data'].min()}")
        print(f"   Máxima: {df_pos_cutoff['Data'].max()}")

    # CÉLULA 15: Matching
    print(f"\n🔍 CÉLULA 15: MATCHING ({initial_matching})")
    dataset_v1_final = fazer_matching_email_telefone(df_pos_cutoff, df_vendas_final)
    print(f"✅ Matching completo: {df_pos_cutoff.shape} → {dataset_v1_final.shape}")
    if 'target' in dataset_v1_final.columns:
        target_1 = dataset_v1_final['target'].sum()
        target_0 = (dataset_v1_final['target'] == 0).sum()
        print(f"\n🎯 Target criado:")
        print(f"   target=1 (converteu): {target_1:,}")
        print(f"   target=0 (não converteu): {target_0:,}")
        print(f"   Taxa de conversão: {dataset_v1_final['target'].mean()*100:.2f}%")

    # CÉLULA 17: DevClub + Janela
    print("\n🎓 CÉLULA 17: DEVCLUB + JANELA")
    dataset_v1_devclub = criar_dataset_devclub(dataset_v1_final, df_vendas_final)
    print(f"✅ Filtro DevClub: {dataset_v1_final.shape} → {dataset_v1_devclub.shape}")

    dataset_v1_devclub = aplicar_janela_conversao(
        df_leads=dataset_v1_devclub,
        df_vendas=df_vendas_final,
        janela_dias=20
    )
    print(f"✅ Janela de conversão aplicada (20 dias)")

    if 'target' in dataset_v1_devclub.columns:
        target_1 = dataset_v1_devclub['target'].sum()
        target_0 = (dataset_v1_devclub['target'] == 0).sum()
        print(f"\n🎯 Target após janela:")
        print(f"   target=1: {target_1:,}")
        print(f"   target=0: {target_0:,}")
        print(f"   Taxa de conversão: {dataset_v1_devclub['target'].mean()*100:.2f}%")

    print(f"\n📊 Dataset DevClub (ANTES Feature Engineering):")
    print(f"   Shape: {dataset_v1_devclub.shape}")
    print(f"   Colunas ({len(dataset_v1_devclub.columns)}): {list(dataset_v1_devclub.columns)}")

    # Salvar cópia ANTES do feature engineering (para ter Data e Medium originais)
    dataset_antes_fe = dataset_v1_devclub.copy()

    # =========================================================================
    # ✨ ADICIONAR FEATURES TEMPORAIS DE MEDIUM (ANTES DO FE) ✨
    # =========================================================================

    print("\n" + "="*80)
    print("✨ ADICIONANDO FEATURES TEMPORAIS DE MEDIUM")
    print("="*80)

    print(f"\n📊 Dataset base (ANTES de adicionar temporais):")
    print(f"   Registros: {len(dataset_antes_fe):,}")
    print(f"   Colunas: {len(dataset_antes_fe.columns)} (inclui Data, Nome, Email, etc.)")

    # PASSO 1: Adicionar features temporais AO dataset que tem Data
    dataset_com_temporais = adicionar_features_temporais_medium(
        df_leads=dataset_antes_fe,  # TEM Data e Medium originais
        coluna_data='Data',
        coluna_medium='Medium'
    )

    print(f"\n📊 Após adicionar features temporais:")
    print(f"   Colunas: {len(dataset_com_temporais.columns)}")

    # Identificar features temporais adicionadas
    features_temporais = set(dataset_com_temporais.columns) - set(dataset_antes_fe.columns)
    print(f"   Features temporais adicionadas ({len(features_temporais)}): {sorted(features_temporais)}")

    # =========================================================================
    # CÉLULA 18: Feature Engineering COMPLETO (com temporais)
    # =========================================================================

    print("\n⚙️  CÉLULA 18: FEATURE ENGINEERING COMPLETO")
    print(f"📊 ANTES do FE (dataset COM temporais):")
    print(f"   Shape: {dataset_com_temporais.shape}")
    print(f"   Tem Data? {'Data' in dataset_com_temporais.columns}")
    print(f"   Tem features temporais? {all(f in dataset_com_temporais.columns for f in features_temporais)}")

    # PASSO 2: Aplicar FE COMPLETO (cria 7 features + remove Data, Nome, etc.)
    dataset_v1_devclub_fe_temporal = criar_features_derivadas(dataset_com_temporais)

    print(f"\n📊 DEPOIS do FE:")
    print(f"   Shape: {dataset_v1_devclub_fe_temporal.shape}")
    print(f"   Tem Data? {'Data' in dataset_v1_devclub_fe_temporal.columns}")
    print(f"   Tem features temporais? {all(f in dataset_v1_devclub_fe_temporal.columns for f in features_temporais)}")

    # Identificar features criadas pelo FE
    novas_features_fe = set(dataset_v1_devclub_fe_temporal.columns) - set(dataset_com_temporais.columns)
    print(f"\n✨ Features criadas pelo FE ({len(novas_features_fe)}): {sorted(novas_features_fe)}")

    # =========================================================================
    # RESUMO FINAL: Comparar com FE padrão (sem temporais)
    # =========================================================================

    # Para comparação, calcular FE padrão (sem temporais)
    dataset_v1_devclub_fe_padrao = criar_features_derivadas(dataset_antes_fe)

    print(f"\n" + "="*80)
    print("📊 COMPARAÇÃO: FE PADRÃO vs FE COM TEMPORAIS")
    print("="*80)
    print(f"\n1️⃣  FE PADRÃO (sem temporais):")
    print(f"   Colunas: {len(dataset_v1_devclub_fe_padrao.columns)}")

    print(f"\n2️⃣  FE COM TEMPORAIS:")
    print(f"   Colunas: {len(dataset_v1_devclub_fe_temporal.columns)}")
    print(f"   Diferença: {len(dataset_v1_devclub_fe_temporal.columns) - len(dataset_v1_devclub_fe_padrao.columns):+d} colunas")

    # Comparar colunas
    colunas_novas_vs_fe = set(dataset_v1_devclub_fe_temporal.columns) - set(dataset_v1_devclub_fe_padrao.columns)
    colunas_removidas_vs_fe = set(dataset_v1_devclub_fe_padrao.columns) - set(dataset_v1_devclub_fe_temporal.columns)

    if colunas_novas_vs_fe:
        print(f"\n   ✅ Novas features ({len(colunas_novas_vs_fe)}): {sorted(colunas_novas_vs_fe)}")
    if colunas_removidas_vs_fe:
        print(f"   ❌ Features removidas ({len(colunas_removidas_vs_fe)}): {sorted(colunas_removidas_vs_fe)}")

    print(f"\n✅ SUCESSO: Dataset com features temporais + features do FE!")

    # =========================================================================
    # CÉLULA 20: Encoding
    # =========================================================================

    print("\n🔢 CÉLULA 20: ENCODING")
    print(f"📊 ANTES do Encoding:")
    print(f"   Shape: {dataset_v1_devclub_fe_temporal.shape}")
    print(f"   Colunas: {len(dataset_v1_devclub_fe_temporal.columns)}")
    print(f"   Tipos: {dataset_v1_devclub_fe_temporal.dtypes.value_counts().to_dict()}")

    dataset_v1_devclub_encoded = aplicar_encoding_estrategico(dataset_v1_devclub_fe_temporal)

    print(f"\n📊 DEPOIS do Encoding:")
    print(f"   Shape: {dataset_v1_devclub_encoded.shape}")
    print(f"   Colunas: {len(dataset_v1_devclub_encoded.columns)}")
    print(f"   Tipos: {dataset_v1_devclub_encoded.dtypes.value_counts().to_dict()}")
    print(f"\n✨ Explosão de features: {len(dataset_v1_devclub_fe_temporal.columns)} → {len(dataset_v1_devclub_encoded.columns)} (+{len(dataset_v1_devclub_encoded.columns) - len(dataset_v1_devclub_fe_temporal.columns)})")

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
    resultado['temporal_features_count'] = len(features_temporais)
    resultado['temporal_features'] = sorted(features_temporais)
    resultado['mlflow_run_id'] = resultado.get('run_id', 'N/A')

    # Adicionar tags específicas do experimento ao run MLflow
    run_id = resultado.get('run_id')
    if run_id:
        with mlflow.start_run(run_id=run_id):
            mlflow.set_tag("experiment_type", "temporal_features")
            mlflow.set_tag("temporal_features", "enabled")
            mlflow.log_param("temporal_features_count", len(features_temporais))

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
    print(f"   Temporal: {resultado['temporal_features_count']}")

    print(f"\n💡 PRÓXIMOS PASSOS:")
    print(f"   1. Comparar com baseline no MLflow UI:")
    print(f"      mlflow ui --backend-store-uri sqlite:///mlflow.db")
    print(f"   2. Ou usar: python tests/compare_mlflow_runs.py")

    return resultado


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Experimento com features temporais de Medium')
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

    args = parser.parse_args()

    resultado = run_experiment_with_temporal_features(
        initial_matching=args.initial_matching,
        save_files=args.save_files,
        split_method=args.split_method
    )

    print(f"\n✅ Experimento finalizado com sucesso!")
    print(f"   Run ID: {resultado['mlflow_run_id']}")
