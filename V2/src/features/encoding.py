"""
Módulo de encoding categórico para o pipeline de lead scoring.
Mantém a lógica EXATA do notebook original para garantir reprodutibilidade.
"""

import pandas as pd
from typing import Dict
import logging
import json
from pathlib import Path

logger = logging.getLogger(__name__)


def load_ordinal_mappings_from_training(model_path: str) -> Dict[str, list]:
    """
    Carrega mapeamentos ordinais a partir das categorias salvas no treino.

    Args:
        model_path: Caminho para pasta do modelo (ex: files/20260115_080140)

    Returns:
        Dict com mapeamentos ordinais {coluna: [ordem_das_categorias]}
    """
    categories_file = Path(model_path) / "categorias_esperadas.json"

    if not categories_file.exists():
        logger.warning(f"Arquivo de categorias não encontrado: {categories_file}")
        logger.warning("Usando mapeamentos ordinais hardcoded (fallback)")
        return None

    with open(categories_file, 'r', encoding='utf-8') as f:
        categorias = json.load(f)

    ordinal_mappings = {}

    # Idade: ordem por faixa etária crescente
    if 'Qual a sua idade?' in categorias:
        idade_cats = categorias['Qual a sua idade?']
        # Ordenar por idade: menos de 18, 18-24, 25-34, 35-44, 45-54, mais de 55
        ordem_idade = []
        for cat in ['menos de 18 anos', '18 24 anos', '25 34 anos', '35 44 anos', '45 54 anos', 'mais de 55 anos']:
            if cat in idade_cats:
                ordem_idade.append(cat)
        ordinal_mappings['Qual a sua idade?'] = ordem_idade

    # Salário: ordem por faixa salarial crescente
    if 'Atualmente, qual a sua faixa salarial?' in categorias:
        salario_cats = categorias['Atualmente, qual a sua faixa salarial?']
        # Ordenar por salário: sem renda, r1000-2000, r2001-3000, r3001-5000, r5001+
        ordem_salario = []
        for cat in ['nao tenho renda', 'entre r1000 a r2000 reais ao mes', 'entre r2001 a r3000 reais ao mes',
                    'entre r3001 a r5000 reais ao mes', 'mais de r5001 reais ao mes']:
            if cat in salario_cats:
                ordem_salario.append(cat)
        ordinal_mappings['Atualmente, qual a sua faixa salarial?'] = ordem_salario

    # dia_semana sempre numérico
    ordinal_mappings['dia_semana'] = [0, 1, 2, 3, 4, 5, 6]

    return ordinal_mappings


def apply_categorical_encoding(df_original: pd.DataFrame, versao: str = "v1", medium_strategy: str = "binary_top3", model_path: str = None, mlflow_run_id: str = None) -> pd.DataFrame:
    """
    Aplica encoding em um dataset específico.

    Args:
        df_original: DataFrame original
        versao: Versão do dataset (padrão: "v1")
        medium_strategy: Estratégia para Medium
            - 'binary_top3': Features binárias para 3 categorias mais estáveis (PADRÃO)
            - 'full': One-hot completo (comportamento antigo)
        mlflow_run_id: ID do MLflow run (preferencial)
            - Se fornecido, carrega feature_registry direto do MLflow
            - Garante todas as features esperadas pelo modelo
        model_path: Caminho para pasta do modelo (DEPRECATED - usar mlflow_run_id)
            - Mantido apenas para backward compatibility
            - Se fornecido, carrega mapeamentos ordinais de categorias_esperadas.json
            - Valida features geradas contra features_ordenadas.json do modelo

    Função EXATA copiada da Seção 20 do notebook original, com suporte a medium_strategy.
    """
    # Print do cabeçalho para comparação com notebook
    logger.info("ENCODING ESTRATÉGICO DOS 4 DATASETS")
    logger.info("=" * 45)

    df = df_original.copy()

    logger.info(f"\nProcessando dataset...")
    logger.info(f"Colunas antes do encoding: {len(df.columns)}")

    # DEBUG: Listar colunas exatas que chegam no encoding
    logger.info(f"\nColunas que chegam no encoding (total: {len(df.columns)}):")
    for i, col in enumerate(sorted(df.columns), 1):
        logger.info(f"{i:2d}. {col}")
    logger.info("")

    # 1. ENCODING ORDINAL para variáveis com ordem natural
    # Se model_path fornecido, carregar categorias do treino (recomendado)
    # Senão, usar valores hardcoded (fallback para treino ou desenvolvimento)
    if model_path:
        logger.info(f"Carregando mapeamentos ordinais de: {model_path}")
        variaveis_ordinais = load_ordinal_mappings_from_training(model_path)
        if variaveis_ordinais is None:
            # Fallback para hardcoded se arquivo não existe
            logger.warning("Usando mapeamentos ordinais hardcoded (fallback)")
            variaveis_ordinais = {
                'Qual a sua idade?': ['menos de 18 anos', '18 24 anos', '25 34 anos',
                                      '35 44 anos', '45 54 anos', 'mais de 55 anos'],
                'Atualmente, qual a sua faixa salarial?': ['nao tenho renda', 'entre r1000 a r2000 reais ao mes',
                                                           'entre r2001 a r3000 reais ao mes',
                                                           'entre r3001 a r5000 reais ao mes',
                                                           'mais de r5001 reais ao mes'],
                'dia_semana': [0, 1, 2, 3, 4, 5, 6]
            }
    else:
        # Training ou desenvolvimento sem model_path
        logger.info("Usando mapeamentos ordinais hardcoded (treino)")
        variaveis_ordinais = {
            'Qual a sua idade?': ['menos de 18 anos', '18 24 anos', '25 34 anos',
                                  '35 44 anos', '45 54 anos', 'mais de 55 anos'],
            'Atualmente, qual a sua faixa salarial?': ['nao tenho renda', 'entre r1000 a r2000 reais ao mes',
                                                       'entre r2001 a r3000 reais ao mes',
                                                       'entre r3001 a r5000 reais ao mes',
                                                       'mais de r5001 reais ao mes'],
            'dia_semana': [0, 1, 2, 3, 4, 5, 6]
        }

    logger.info(f"\nAplicando ORDINAL ENCODING:")
    for var, ordem in variaveis_ordinais.items():
        if var in df.columns:
            if var == 'dia_semana':
                # Já é numérico, apenas reportar
                logger.info(f"  {var}: mantido como numérico (0-6)")
            else:
                # ANTES DO MAPEAMENTO: verificar valores que não estão no dicionário
                valores_unicos_antes = df[var].value_counts(dropna=False).head(20)
                valores_esperados_set = set(ordem)

                # Identificar valores problemáticos
                valores_problematicos = []
                for valor in df[var].unique():
                    if pd.isna(valor):
                        valores_problematicos.append(('NaN/vazio', df[var].isna().sum()))
                    elif valor not in valores_esperados_set:
                        count = (df[var] == valor).sum()
                        valores_problematicos.append((repr(valor), count))

                if valores_problematicos:
                    total_problematicos = sum(count for _, count in valores_problematicos)
                    logger.warning(f"    {var}: {total_problematicos}/{len(df)} registros com valores NÃO MAPEADOS:")
                    for valor, count in valores_problematicos[:10]:
                        pct = (count / len(df)) * 100
                        logger.warning(f"      - {valor}: {count} registros ({pct:.1f}%)")

                    if len(valores_problematicos) > 10:
                        logger.warning(f"      ... e mais {len(valores_problematicos) - 10} valores diferentes")

                # Criar mapeamento ordinal
                mapeamento = {categoria: i for i, categoria in enumerate(ordem)}
                df[var] = df[var].map(mapeamento)
                logger.info(f"  {var}: {len(ordem)} categorias  0-{len(ordem)-1}")

                # DEPOIS DO MAPEAMENTO: contar NaN resultantes
                nan_depois = df[var].isna().sum()
                if nan_depois > 0:
                    pct_nan = (nan_depois / len(df)) * 100
                    logger.warning(f"       Resultado: {nan_depois} NaN ({pct_nan:.1f}%) - serão preenchidos com 0")

    # 1.5. PROCESSAR MEDIUM CONFORME ESTRATÉGIA
    if 'Medium' in df.columns and medium_strategy != 'full':
        logger.info(f"\nProcessando Medium com estratégia: {medium_strategy}")

        if medium_strategy == 'binary_top3':
            # Criar features para as 3 categorias mais estáveis temporalmente
            df['Medium_Linguagem_programacao'] = (df['Medium'] == 'Linguagem de programação').astype(int)
            df['Medium_Aberto'] = (df['Medium'] == 'Aberto').astype(int)
            df['Medium_Lookalike_2pct_Cadastrados'] = (df['Medium'] == 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses').astype(int)
            df = df.drop(columns=['Medium'])
            logger.info(f"   Criadas features binárias (top 3 mais estáveis):")
            logger.info(f"    Linguagem de programação: {df['Medium_Linguagem_programacao'].sum():,} registros ({df['Medium_Linguagem_programacao'].mean()*100:.1f}%)")
            logger.info(f"    Aberto: {df['Medium_Aberto'].sum():,} registros ({df['Medium_Aberto'].mean()*100:.1f}%)")
            logger.info(f"    Lookalike 2% Cadastrados: {df['Medium_Lookalike_2pct_Cadastrados'].sum():,} registros ({df['Medium_Lookalike_2pct_Cadastrados'].mean()*100:.1f}%)")
            logger.info(f"   Categorias não cobertas (32% dos dados)  [0, 0, 0]")

    # 2. ONE-HOT ENCODING para variáveis categóricas nominais
    variaveis_one_hot = []

    # Identificar variáveis categóricas (excluindo ordinais já processadas e target)
    for col in df.columns:
        if col not in ['target'] and col not in variaveis_ordinais and col != 'nome_comprimento':
            # Excluir features Medium_ já criadas pelo binary_top3
            if medium_strategy == 'binary_top3' and col.startswith('Medium_'):
                continue
            # Verificar se é categórica (object ou poucos valores únicos)
            if df[col].dtype == 'object' or df[col].nunique() <= 20:
                variaveis_one_hot.append(col)

    logger.info(f"\nAplicando ONE-HOT ENCODING para {len(variaveis_one_hot)} variáveis:")
    logger.info(f"ORDEM das variáveis one-hot:")
    for i, var in enumerate(variaveis_one_hot, 1):
        logger.info(f"  {i:2d}. {var}")

    # Aplicar one-hot encoding
    df_encoded = pd.get_dummies(df, columns=variaveis_one_hot, prefix_sep='_', dtype=int)

    # REMOVER telefone_comprimento_8 (EXATO do notebook - linha 5076-5078)
    if 'telefone_comprimento_8' in df_encoded.columns:
        df_encoded = df_encoded.drop(columns=['telefone_comprimento_8'])
        logger.info(f"    telefone_comprimento_8 removida (conforme notebook)")

    # REMOVER DUPLICATAS DE COLUNAS (se houver) - CRÍTICO para evitar features extras
    colunas_antes_duplicatas = len(df_encoded.columns)
    df_encoded = df_encoded.loc[:, ~df_encoded.columns.duplicated()]
    duplicatas_removidas = colunas_antes_duplicatas - len(df_encoded.columns)
    if duplicatas_removidas > 0:
        logger.info(f"  Duplicatas removidas: {duplicatas_removidas} colunas")

    # Reportar criação de colunas
    colunas_criadas = len(df_encoded.columns) - len(df.columns)
    for var in variaveis_one_hot:
        categorias_unicas = df[var].nunique()
        logger.info(f"  {var}: {categorias_unicas} categorias  {categorias_unicas} colunas binárias")

    logger.info(f"\nResultado:")
    logger.info(f"  Colunas one-hot originais: {len(variaveis_one_hot)}")
    logger.info(f"  Colunas binárias criadas: {colunas_criadas}")

    # NORMALIZAÇÃO DOS NOMES DAS COLUNAS (linhas 4976-4978 do notebook)
    # CRÍTICO: Esta etapa estava faltando e causava incompatibilidade com o modelo
    logger.info(f"\nNormalizando nomes das colunas...")

    # Guardar nomes originais para comparação
    colunas_antes = list(df_encoded.columns)

    # Aplicar normalização EXATA do notebook
    df_encoded.columns = df_encoded.columns.str.replace('[^A-Za-z0-9_]', '_', regex=True)
    df_encoded.columns = df_encoded.columns.str.replace('__+', '_', regex=True)
    df_encoded.columns = df_encoded.columns.str.strip('_')

    # MAPEAMENTOS ESPECÍFICOS para manter consistência com arquivo de features
    mapeamentos_especificos = {
        'O_que_voc_faz_atualmente_Sou_autonomo': 'O_que_voc_faz_atualmente_Sou_aut_nomo',
        'Tem_computador_notebook_SIM': 'Tem_computador_notebook_Sim',
        'Tem_computador_notebook_N_O': 'Tem_computador_notebook_N_o',  # NÃO maiúsculo  regex remove ã
        'Medium_outros': 'Medium_Outros'  # Corrigir capitalização
    }

    # Aplicar mapeamentos (evitando colisões)
    # Se a coluna de destino já existe, pular o mapeamento
    colunas_atuais = set(df_encoded.columns)
    novos_nomes = []
    for col in df_encoded.columns:
        novo_nome = mapeamentos_especificos.get(col, col)
        # Se o novo nome já existe E não é a mesma coluna, manter o nome original
        if novo_nome in colunas_atuais and novo_nome != col:
            logger.warning(f"   Pulando mapeamento {col}  {novo_nome} (coluna destino já existe)")
            novos_nomes.append(col)
        else:
            novos_nomes.append(novo_nome)

    df_encoded.columns = novos_nomes

    # Contar quantas colunas foram alteradas
    colunas_alteradas = sum(1 for antes, depois in zip(colunas_antes, list(df_encoded.columns))
                            if antes != depois)
    logger.info(f"  Colunas normalizadas: {colunas_alteradas}")

    logger.info(f"  Total de colunas final: {len(df_encoded.columns)}")

    # GARANTIR TODAS AS FEATURES ESPERADAS
    # Prioriza MLflow (mlflow_run_id), fallback para model_path (backward compatibility)
    ordem_esperada = None

    if mlflow_run_id:
        logger.info(f"\nGarantindo features esperadas do MLflow run: {mlflow_run_id}")

        # Carregar do MLflow
        mlruns_path = Path(__file__).parent.parent.parent / "mlruns" / "1" / mlflow_run_id / "artifacts"
        feature_registry_file = mlruns_path / "feature_registry.json"

        if feature_registry_file.exists():
            try:
                with open(feature_registry_file, 'r') as f:
                    registry_data = json.load(f)
                    if 'model_input_features' in registry_data and 'ordered_list' in registry_data['model_input_features']:
                        ordem_esperada = registry_data['model_input_features']['ordered_list']
                        logger.info(f"  ✅ Carregadas {len(ordem_esperada)} features do MLflow Feature Registry")
            except Exception as e:
                logger.warning(f"  ⚠️  Erro ao ler Feature Registry do MLflow: {e}")
        else:
            logger.warning(f"  ⚠️  Feature Registry não encontrado no MLflow: {feature_registry_file}")

    elif model_path:
        logger.info(f"\nGarantindo features esperadas do model_path (DEPRECATED): {model_path}")

        # Tentar carregar do Feature Registry primeiro (novo formato)
        feature_registry_file = Path(model_path) / f"feature_registry_{versao}_devclub_rf_temporal_leads_single.json"
        features_ordenadas_file = Path(model_path) / f"features_ordenadas_{versao}_devclub_rf_temporal_leads_single.json"

        # Prioridade 1: Feature Registry (novo formato com model_input_features.ordered_list)
        if feature_registry_file.exists():
            try:
                with open(feature_registry_file, 'r') as f:
                    registry_data = json.load(f)
                    if 'model_input_features' in registry_data and 'ordered_list' in registry_data['model_input_features']:
                        ordem_esperada = registry_data['model_input_features']['ordered_list']
                        logger.info(f"  ✅ Carregadas {len(ordem_esperada)} features do Feature Registry")
            except Exception as e:
                logger.warning(f"  ⚠️  Erro ao ler Feature Registry: {e}")

        # Prioridade 2: features_ordenadas.json (formato antigo, backward compatibility)
        if ordem_esperada is None and features_ordenadas_file.exists():
            try:
                with open(features_ordenadas_file, 'r') as f:
                    features_data = json.load(f)
                    ordem_esperada = features_data.get('feature_names', [])
                    logger.info(f"  ✅ Carregadas {len(ordem_esperada)} features de features_ordenadas.json")
            except Exception as e:
                logger.warning(f"  ⚠️  Erro ao ler features_ordenadas.json: {e}")

    if ordem_esperada:
        # Verificar features faltantes
        colunas_faltando = [col for col in ordem_esperada if col not in df_encoded.columns]

        if colunas_faltando:
            logger.info(f"  📝 Criando {len(colunas_faltando)} features faltantes (preenchidas com 0)")
            for col in colunas_faltando:
                df_encoded[col] = 0

        # Reordenar colunas para seguir ordem esperada + extras no final
        colunas_ordenadas = [col for col in ordem_esperada if col in df_encoded.columns]
        colunas_extras = [col for col in df_encoded.columns if col not in ordem_esperada]
        if colunas_extras:
            logger.info(f"  ℹ️  {len(colunas_extras)} features extras (serão ignoradas pelo modelo)")
            colunas_ordenadas += colunas_extras

        df_encoded = df_encoded[colunas_ordenadas]

        logger.info(f"  ✅ Features alinhadas: {len(df_encoded.columns)} colunas ({len(ordem_esperada)} esperadas)")
    else:
        if not mlflow_run_id and not model_path:
            logger.info(f"\nGarantia de features pulada (mlflow_run_id e model_path não fornecidos)")
        else:
            logger.warning(f"  ⚠️  Não foi possível carregar features esperadas")
            logger.warning(f"  Predição pode falhar se features estiverem faltando")

    # TRATAMENTO DE NaN REMANESCENTES
    logger.info(f"\nVerificando NaN remanescentes após encoding...")

    # Identificar colunas com NaN
    colunas_com_nan = df_encoded.columns[df_encoded.isna().any()].tolist()

    if colunas_com_nan:
        logger.warning(f"  ENCONTRADOS NaN EM {len(colunas_com_nan)} COLUNAS:")

        # Detalhar cada coluna com NaN
        for col in colunas_com_nan:
            nan_count = df_encoded[col].isna().sum()
            nan_pct = (nan_count / len(df_encoded)) * 100
            logger.warning(f"  - {col}: {nan_count} NaN ({nan_pct:.1f}% dos {len(df_encoded)} registros)")

            # Mostrar alguns valores únicos não-NaN dessa coluna (para debug)
            valores_nao_nan = df_encoded[col].dropna().unique()[:5]
            if len(valores_nao_nan) > 0:
                logger.info(f"    Valores não-NaN: {valores_nao_nan}")

        # Preencher NaN com 0
        logger.info(f"\n Preenchendo {len(colunas_com_nan)} colunas com NaN...")
        df_encoded = df_encoded.fillna(0)
        logger.info(f" NaN preenchidos com 0")
    else:
        logger.info(f" Nenhum NaN encontrado - dados limpos")

    # Verificar tipos de dados finais
    tipos_dados = df_encoded.dtypes.value_counts()
    logger.info(f"\nTipos de dados no dataset final:")
    for tipo, count in tipos_dados.items():
        logger.info(f"  {tipo}: {count} colunas")

    return df_encoded


def get_encoding_summary(df_original: pd.DataFrame, df_encoded: pd.DataFrame) -> Dict:
    """
    Gera resumo do processo de encoding.

    Args:
        df_original: DataFrame original antes do encoding
        df_encoded: DataFrame após encoding

    Returns:
        Dicionário com estatísticas do encoding
    """
    summary = {
        'original_columns': len(df_original.columns),
        'encoded_columns': len(df_encoded.columns),
        'columns_added': len(df_encoded.columns) - len(df_original.columns),
        'rows': len(df_encoded)
    }

    # Tipos de dados
    original_types = df_original.dtypes.value_counts()
    encoded_types = df_encoded.dtypes.value_counts()

    summary['original_types'] = {str(tipo): int(count) for tipo, count in original_types.items()}
    summary['encoded_types'] = {str(tipo): int(count) for tipo, count in encoded_types.items()}

    return summary