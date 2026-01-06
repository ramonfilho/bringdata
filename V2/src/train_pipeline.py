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
from src.data_processing.traffic_features import adicionar_features_temporais_medium
from src.model.training_model import registrar_features_e_modelo_devclub
from src.model.hyperparameter_tuning import hyperparameter_tuning

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def main(initial_matching='email_telefone', save_files=False, tune_hyperparams=False, grid_size='small', split_method='temporal', use_guru_only=None, set_active=False, temporal_features=False):
    """Executa pipeline de treino completo.

    Args:
        initial_matching: Método de matching inicial na célula 15
                         ('email_only', 'email_telefone', 'variantes', 'robusto' ou 'validation')
        split_method: Método de split do train/test
                     - 'temporal': 70% dos DIAS para treino (split clássico por período)
                     - 'temporal_leads': 70% dos LEADS para treino (ordenados por data, test set mais recente)
                     - 'stratified': 70% dos registros com stratified split por pessoa
        save_files: Se True, salva arquivos locais em files/{timestamp}
        tune_hyperparams: Se True, executa hyperparameter tuning antes do treino
        grid_size: Tamanho do grid search ('small', 'medium', 'large')
        use_guru_only: Se True, usa apenas GURU. Se False, usa GURU+TMB. Se None, usa valor do config.
        set_active: Se True, atualiza configs/active_model.yaml com este modelo (requer save_files=True)
        temporal_features: Se True, adiciona features temporais de tráfego (densidade, tendência, rank)
    """

    print("\n" + "=" * 80)
    print("PIPELINE DE TREINO")
    print("=" * 80)
    print(f"\n🔧 CONFIGURAÇÃO:")
    print(f"   Método de matching inicial (célula 15): {initial_matching}")
    print(f"   Salvar arquivos locais: {save_files}")
    print(f"   Hyperparameter tuning: {tune_hyperparams}")
    if tune_hyperparams:
        print(f"   Grid size: {grid_size}")
    print(f"   Features temporais de tráfego: {temporal_features}")
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

    # Aplicar filtro GURU only
    # Se passado via argumento, usa argumento. Caso contrário, usa config.
    if use_guru_only is None:
        use_guru_only = config['ingestion'].get('use_guru_only', False)
    if use_guru_only:
        filepaths_original = filepaths.copy()
        filepaths = [f for f in filepaths if 'guru' in os.path.basename(f).lower() or 'pesquisa' in os.path.basename(f).lower() or 'lead' in os.path.basename(f).lower()]

        # Arquivos removidos (TMB)
        removed = [f for f in filepaths_original if f not in filepaths]
        if removed:
            print(f"\n🚫 GURU ONLY MODE - Arquivos TMB excluídos:")
            for f in removed:
                print(f"  - {os.path.basename(f)}")

    print(f"\nTotal de arquivos: {len(filepaths)}")
    for f in filepaths:
        print(f"  - {os.path.basename(f)}")

    # Ler arquivos
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
    print("\nCONSOLIDAÇÃO DE DATASETS - PESQUISA E VENDAS")
    print("=" * 45)

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
    print("\nUNIFICAÇÃO DE COLUNAS DUPLICADAS")
    print("=" * 32)

    df_pesquisa_final, df_vendas_final = unificar_colunas_datasets(df_pesquisa, df_vendas)

    print(f"\nRESULTADO:")
    print(f"Pesquisa: {len(df_pesquisa_final)} registros, {len(df_pesquisa_final.columns)} colunas")
    print(f"Vendas: {len(df_vendas_final)} registros, {len(df_vendas_final.columns)} colunas")

    # Gerar relatórios finais
    gerar_relatorio_colunas(df_pesquisa_final, "DATASET PESQUISA")
    gerar_relatorio_colunas(df_vendas_final, "DATASET VENDAS")

    # === CÉLULA 7: Unificação completa de categorias ===
    print("\nUNIFICAÇÃO COMPLETA DE CATEGORIAS - NOVO CÓDIGO")
    print("=" * 52)

    df_pesquisa_final_unificado = unificar_categorias_completo(df_pesquisa_final)

    # Gerar relatório final
    gerar_relatorio_final_categorias(df_pesquisa_final_unificado)

    # === CÉLULA 8: Remoção de features desnecessárias ===
    print("\nREMOÇÃO DE FEATURES DESNECESSÁRIAS")
    print("=" * 38)

    df_features_removidas = remover_features_desnecessarias(df_pesquisa_final_unificado)

    # Listar colunas restantes
    listar_colunas_restantes(df_features_removidas)

    # === CÉLULA 10: Unificação de UTM Source e Term ===
    print("\nUNIFICAÇÃO DE UTM SOURCE E TERM")
    print("=" * 35)

    df_utm_unificado = unificar_utm_source_term(df_features_removidas)

    # Verificar consistência
    verificar_consistencia_utm(df_utm_unificado)

    # === CÉLULA 11: Unificação de UTM Medium - Extração de Públicos ===
    print("\nUNIFICAÇÃO DE UTM MEDIUM - EXTRAÇÃO DE PÚBLICOS")
    print("=" * 52)

    df_medium_unificado = extrair_publico_medium(df_utm_unificado)

    # Gerar relatório final
    relatorio_final_medium(df_medium_unificado)

    # === CÉLULA 11.1: Unificação de Medium para Produção ===
    print("\nUNIFICAÇÃO DE UTM MEDIUM BASEADA EM ACTIONS + TRATAMENTO DE PRODUÇÃO")
    print("=" * 72)

    print("Iniciando processo de unificação para produção...")
    df_original = df_medium_unificado.copy()
    df_medium_producao = unificar_medium_para_producao(df_medium_unificado)

    # Gerar relatório
    relatorio_unificacao_producao(df_original, df_medium_producao)

    print(f"\nProcesso concluído!")
    print(f"Dataset final disponível em: pesquisa_medium_producao_unificado")
    print(f"Este dataset está pronto para o pipeline de produção e não gerará incompatibilidades!")

    # === CÉLULA 13: Criação de versão do dataset por missing rate ===
    print("\nCRIAÇÃO DE VERSÕES DO DATASET POR MISSING RATE")
    print("=" * 50)

    print("Iniciando criação das versões...")
    df_pos_cutoff = criar_dataset_pos_cutoff(df_medium_producao)

    # Disponibilizar dataset
    disponibilizar_dataset(df_pos_cutoff)

    print(f"\nProcesso concluído!")
    print(f"Duas versões do dataset criadas com sucesso.")

    # === CÉLULA 15: Matching robusto por email e telefone ===
    if initial_matching == 'email_only':
        dataset_v1_final = fazer_matching_email_only(df_pos_cutoff, df_vendas_final)
    elif initial_matching == 'email_telefone':
        dataset_v1_final = fazer_matching_email_telefone(df_pos_cutoff, df_vendas_final)
    elif initial_matching == 'variantes':
        dataset_v1_final = fazer_matching_variantes(df_pos_cutoff, df_vendas_final)
    elif initial_matching == 'robusto':
        dataset_v1_final = fazer_matching_robusto(df_pos_cutoff, df_vendas_final)
    elif initial_matching == 'validation':
        dataset_v1_final = fazer_matching_email_with_validation(df_pos_cutoff, df_vendas_final)
    else:
        raise ValueError(f"Método de matching inicial inválido: {initial_matching}. Use 'email_only', 'email_telefone', 'variantes', 'robusto' ou 'validation'")

    # === CÉLULA 17: Filtragem DevClub ===
    dataset_v1_devclub = criar_dataset_devclub(dataset_v1_final, df_vendas_final)

    # Aplicar janela de conversão de 20 dias (captação + CPL + carrinho)
    # Captação: 7 dias (terça-segunda) + CPL: 6 dias (terça-domingo) + Carrinho: 7 dias (segunda-domingo) = 20 dias
    dataset_v1_devclub = aplicar_janela_conversao(
        df_leads=dataset_v1_devclub,
        df_vendas=df_vendas_final,
        janela_dias=20
    )

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

    # 2. Lista atual de produtos que estamos usando
    produtos_devclub_lista_atual = [
        'DevClub - Full Stack 2025',
        'DevClub FullStack Pro - OFICIAL',
        'Formação DevClub FullStack Pro - OFICI',
        'Formação DevClub FullStack Pro - OFICIAL',
        'DevClub - Full Stack 2025 - EV',
        'DevClub - FS - Vitalício',
        '[Vitalício] Formação DevClub FullStack',
        '[Vitalício] Formação DevClub FullStack Pro - OFICIAL',
        'Formação DevClub FullStack Pro - COMER',
        'Formação DevClub FullStack Pro - COMERCIAL',
        'Formação DevClub FullStack Pro',
        'DevClub Vitalício',
        'DevClub 3.0 - 2024',
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

    # 5. Atualizar lista completa
    produtos_devclub = list(produtos_com_devclub.index)

    print("\n" + "=" * 80)
    print("✅ LISTA ATUALIZADA - Usando TODOS os produtos DevClub encontrados")
    print("=" * 80)
    print(f"Total de produtos na lista atualizada: {len(produtos_devclub)}")

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

    # Filtrar por período (mesmo período dos leads)
    if 'data' in vendas_devclub.columns:
        vendas_devclub['data_dt'] = pd.to_datetime(vendas_devclub['data'], errors='coerce')
        # Período dos leads (aproximado - 2025-03-01 a 2025-11-04)
        periodo_inicio = pd.to_datetime('2025-03-01')
        periodo_fim = pd.to_datetime('2025-11-04')
        vendas_periodo = vendas_devclub[
            (vendas_devclub['data_dt'] >= periodo_inicio - pd.Timedelta(days=20)) &
            (vendas_devclub['data_dt'] <= periodo_fim + pd.Timedelta(days=20))
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

    # === FEATURES TEMPORAIS (OPCIONAL) ===
    if temporal_features:
        print("\n" + "=" * 80)
        print("🕒 ADICIONANDO FEATURES TEMPORAIS DE TRÁFEGO")
        print("=" * 80)

        # Salvar cópia antes das temporais
        dataset_antes_temporais = dataset_v1_devclub.copy()

        # PASSO 1: Adicionar features temporais (dataset ainda tem coluna 'Data')
        dataset_v1_devclub = adicionar_features_temporais_medium(
            df_leads=dataset_v1_devclub,
            coluna_data='Data',
            coluna_medium='Medium'
        )

        print(f"\n✅ Features temporais adicionadas!")
        print(f"   Colunas antes: {len(dataset_antes_temporais.columns)}")
        print(f"   Colunas depois: {len(dataset_v1_devclub.columns)}")
        print(f"   Novas features: {len(dataset_v1_devclub.columns) - len(dataset_antes_temporais.columns)}")

        # Listar novas features
        novas_features = [col for col in dataset_v1_devclub.columns if col not in dataset_antes_temporais.columns]
        print(f"   Features criadas: {novas_features}")
        print("=" * 80)

    # === CÉLULA 18: Feature Engineering ===
    # IMPORTANTE: FE será aplicado no dataset COM ou SEM temporais
    # Se temporais foram adicionadas, FE vai criar 7 features E remover Data/Nome/etc
    # Resultado final: 4 temporais + 7 FE + 15 base = 26 colunas
    dataset_v1_devclub_fe = criar_features_derivadas(dataset_v1_devclub)

    # === CÉLULA 20: Encoding Estratégico ===
    dataset_v1_devclub_encoded = aplicar_encoding_estrategico(dataset_v1_devclub_fe)

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
        set_active=set_active
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
        default='temporal',
        help='Método de split: temporal (70%% dos dias), temporal_leads (70%% dos leads), ou stratified (70%% dos registros) - padrão: temporal'
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
        '--temporal-features',
        action='store_true',
        help='Adicionar features temporais de tráfego (densidade, tendência, rank por Medium) - padrão: False'
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
        temporal_features=args.temporal_features
    )
