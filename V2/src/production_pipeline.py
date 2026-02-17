"""
Pipeline principal de lead scoring em produção.
APENAS orquestra componentes, sem conter lógica própria.
Reproduz EXATAMENTE a lógica do notebook com parâmetros configuráveis.
"""

import sys
import os
import pandas as pd
import logging
import atexit
from datetime import datetime
from .data_processing.preprocessing import remove_duplicates, clean_columns, remove_campaign_features, remove_technical_fields, rename_long_column_names
from .data_processing.utm_unification import unify_utm_columns
from .data_processing.medium_unification import unify_medium_columns
from .data_processing.category_unification import unificar_categorias_completo
from .features.engineering import create_derived_features
from .features.encoding import apply_categorical_encoding
from .model.prediction import LeadScoringPredictor
from .monitoring.data_quality import check_category_drift, load_training_categories, check_distribution_drift, load_training_distributions

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
    # Criar diretório outputs/production se não existir
    outputs_dir = os.path.join(os.path.dirname(__file__), '../outputs/production')
    os.makedirs(outputs_dir, exist_ok=True)

    # Gerar timestamp no formato YYYYMMDD_HHMMSS
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(outputs_dir, f'production_{timestamp}.log')

    # Redirecionar stdout e stderr para Tee
    tee = Tee(log_path)
    sys.stdout = tee
    sys.stderr = tee

    # Configurar logging para usar o Tee também
    # Remover handlers existentes
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Adicionar novo handler que escreve em stdout (que agora é o Tee)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    return log_path, tee


class LeadScoringPipeline:
    """
    Pipeline de produção para lead scoring.

    Reproduz EXATAMENTE a lógica do notebook com parâmetros configuráveis.
    """

    def __init__(self, model_name: str = None, model_path: str = None):
        """
        Inicializa o pipeline com configuração fixa.

        Args:
            model_name: Nome do modelo a usar para predições (default: None = usa active_model.yaml)
            model_path: Caminho customizado para a pasta do modelo (opcional)

        Configuração:
        - Mantém features UTM (com_utm=True)
        - Dataset V1 (versao="v1")
        - Sem cutoff temporal
        - Se model_name e model_path forem None, usa o modelo ativo do configs/active_model.yaml
        """
        self.data = None
        self.original_data = None  # Preservar dados originais
        self.predictor = LeadScoringPredictor(model_name, model_path=model_path, use_active_model=True)

        # Carregar modelo e metadados automaticamente
        self.predictor.load_model()

    def load_data(self, filepath: str) -> pd.DataFrame:
        """
        Carrega arquivo de leads no formato Excel ou CSV.

        Args:
            filepath: Caminho para o arquivo Excel ou CSV

        Returns:
            DataFrame com os dados carregados
        """
        logger.info(f"Carregando arquivo: {filepath}")

        # Detectar formato do arquivo pela extensão
        if filepath.lower().endswith('.csv'):
            self.data = pd.read_csv(filepath)
        elif filepath.lower().endswith(('.xlsx', '.xls')):
            self.data = pd.read_excel(filepath)
        else:
            # Tentar CSV primeiro, depois Excel
            try:
                self.data = pd.read_csv(filepath)
            except:
                self.data = pd.read_excel(filepath)

        self.original_data = self.data.copy()  # Preservar cópia original
        logger.info(f"Arquivo carregado: {len(self.data)} linhas, {len(self.data.columns)} colunas")
        return self.data

    def check_category_drift(self) -> list:
        """
        Verifica se há novas categorias não vistas no treino.

        Returns:
            Lista de alertas (vazia se tudo OK)
        """
        try:
            # Carregar categorias esperadas do modelo ativo
            model_path = self.predictor.model_path or self.predictor._get_active_model_path()
            categorias_esperadas = load_training_categories(model_path)

            # Verificar drift
            alertas = check_category_drift(self.data, categorias_esperadas)

            return alertas

        except FileNotFoundError as e:
            # Modelo antigo sem arquivo de categorias
            logger.warning(f" Arquivo de categorias não encontrado: {e}")
            logger.warning("   Execute retreino para gerar categorias_esperadas.json")
            return []
        except Exception as e:
            logger.error(f" Erro ao verificar category drift: {e}")
            return []

    def preprocess(self) -> pd.DataFrame:
        """
        Aplica pré-processamento aos dados.

        Returns:
            DataFrame pré-processado
        """
        if self.data is None:
            raise ValueError("Dados não carregados. Use load_data() primeiro.")

        initial_rows = len(self.data)
        initial_cols = len(self.data.columns)

        logger.info(f" INÍCIO DO PIPELINE: {initial_rows} linhas, {initial_cols} colunas")

        # 1. Remover duplicatas (usando componente importado)
        logger.info(" [1/11] Removendo duplicatas...")
        self.data = remove_duplicates(self.data)

        duplicates_removed = initial_rows - len(self.data)
        logger.info(f"    Duplicatas removidas: {duplicates_removed}")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 2. Limpar colunas desnecessárias (usando componente importado)
        logger.info(" [2/11] Removendo colunas score/faixa...")
        cols_before_clean = len(self.data.columns)
        self.data = clean_columns(self.data)

        columns_removed = cols_before_clean - len(self.data.columns)
        logger.info(f"    Colunas de score/faixa removidas: {columns_removed}")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 3. Remover features de campanha (usando componente importado)
        logger.info(" [3/11] Removendo features de campanha...")
        cols_before_campaign = len(self.data.columns)
        self.data = remove_campaign_features(self.data)

        campaign_cols_removed = cols_before_campaign - len(self.data.columns)
        logger.info(f"    Features de campanha removidas: {campaign_cols_removed}")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 4. Unificar categorias UTM (usando componente importado)
        logger.info(" [4/11] Unificando categorias UTM...")
        utm_source_before = self.data['Source'].nunique() if 'Source' in self.data.columns else 0
        utm_term_before = self.data['Term'].nunique() if 'Term' in self.data.columns else 0

        self.data = unify_utm_columns(self.data)

        utm_source_after = self.data['Source'].nunique() if 'Source' in self.data.columns else 0
        utm_term_after = self.data['Term'].nunique() if 'Term' in self.data.columns else 0
        logger.info(f"    Source: {utm_source_before}{utm_source_after} categorias")
        logger.info(f"    Term: {utm_term_before}{utm_term_after} categorias")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 5. Unificar categorias Medium (usando componente importado)
        logger.info(" [5/11] Unificando categorias Medium...")
        medium_before = self.data['Medium'].nunique() if 'Medium' in self.data.columns else 0

        self.data = unify_medium_columns(self.data)

        medium_after = self.data['Medium'].nunique() if 'Medium' in self.data.columns else 0
        logger.info(f"    Medium: {medium_before}{medium_after} categorias")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 5.5. Renomear colunas longas (usando componente importado)
        # IMPORTANTE: Deve vir ANTES da unificação de categorias pois cria as colunas:
        # - 'interesse_programacao' (de 'O que mais te chama atenção na profissão de Programador?')
        # - 'investiu_curso_online' (de 'Já investiu em algum curso online...')
        logger.info(" [5.5/11] Renomeando colunas longas...")
        self.data = rename_long_column_names(self.data)

        # Número de colunas deveria permanecer o mesmo (renomeação não adiciona/remove)
        logger.info(f"    Colunas renomeadas (mantém total): {len(self.data.columns)}")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 6. Unificar categorias de pesquisa (usando componente importado)
        logger.info(" [6/11] Unificando categorias de pesquisa...")

        # Contar categorias antes para tracking
        categorias_antes = {}
        colunas_pesquisa = [
            'interesse_programacao', 'tem_computador',
            'o_que_quer_ver_evento', 'tem_cartao_credito',
            'faixa_salarial', 'o_que_faz_atualmente',
            'idade', 'fez_faculdade'
        ]
        for col in colunas_pesquisa:
            if col in self.data.columns:
                categorias_antes[col] = self.data[col].nunique()

        self.data = unificar_categorias_completo(self.data)

        # Contar categorias depois
        categorias_normalizadas = 0
        for col in colunas_pesquisa:
            if col in self.data.columns:
                depois = self.data[col].nunique()
                antes = categorias_antes.get(col, depois)
                if antes != depois:
                    categorias_normalizadas += (antes - depois)

        logger.info(f"    Categorias normalizadas: {categorias_normalizadas}")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 7. Remover campos técnicos (usando componente importado)
        logger.info(" [7/11] Removendo campos técnicos...")
        cols_before_tech = len(self.data.columns)
        self.data = remove_technical_fields(self.data)

        tech_cols_removed = cols_before_tech - len(self.data.columns)
        logger.info(f"    Campos técnicos removidos: {tech_cols_removed}")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 8. Verificar category drift ANTES do encoding
        logger.info(" [8/12] Verificando category drift...")
        drift_alerts = self.check_category_drift()

        if drift_alerts:
            logger.warning(f"  {len(drift_alerts)} alertas de category drift detectados:")
            for alert in drift_alerts:
                logger.warning(f"   {alert['message']}")

            # Armazenar alertas para enviar depois (implementação futura)
            if not hasattr(self, 'alerts'):
                self.alerts = []
            self.alerts.extend(drift_alerts)
        else:
            logger.info("    Nenhuma categoria nova detectada")

        # 8.5. Verificar distribution drift (mudanças nas proporções)
        logger.info(" [8.5/12] Verificando distribution drift...")
        try:
            # Carregar distribuições esperadas do modelo ativo
            model_path = self.predictor.model_path or self.predictor._get_active_model_path()
            distribuicoes_esperadas = load_training_distributions(model_path)

            # Verificar drift nas distribuições
            distribution_alerts = check_distribution_drift(self.data, distribuicoes_esperadas)

            if distribution_alerts:
                logger.warning(f"  {len(distribution_alerts)} alertas de distribution drift detectados:")
                for alert in distribution_alerts:
                    logger.warning(f"   {alert['message']}")

                # Armazenar alertas
                if not hasattr(self, 'alerts'):
                    self.alerts = []
                self.alerts.extend(distribution_alerts)
            else:
                logger.info("    Nenhuma mudança drástica nas distribuições")

        except FileNotFoundError as e:
            # Modelo antigo sem arquivo de distribuições
            logger.warning(f" Arquivo de distribuições não encontrado: {e}")
            logger.warning("   Execute retreino para gerar distribuicoes_esperadas.json")
        except Exception as e:
            logger.error(f" Erro ao verificar distribution drift: {e}")

        # 9. Engenharia de features (usando componente importado)
        logger.info(" [9/12] Aplicando engenharia de features...")
        cols_before_fe = len(self.data.columns)

        # Verificar se colunas necessárias existem
        fe_input_cols = ['Data', 'Nome Completo', 'E-mail', 'Telefone']
        available_fe_cols = [col for col in fe_input_cols if col in self.data.columns]
        logger.info(f"    Colunas disponíveis para FE: {available_fe_cols}")

        self.data = create_derived_features(self.data)


        cols_added = len(self.data.columns) - cols_before_fe
        logger.info(f"    Features criadas/processadas: {cols_added} novas colunas")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 10. Encoding categórico (usando componente importado)
        logger.info(" [10/12] Aplicando encoding categórico...")
        cols_before_encoding = len(self.data.columns)

        # Priorizar mlflow_run_id, fallback para model_path (backward compatibility)
        mlflow_run_id = self.predictor.mlflow_run_id if hasattr(self.predictor, 'mlflow_run_id') else None
        model_path = str(self.predictor.model_path) if self.predictor.model_path and not mlflow_run_id else None

        self.data = apply_categorical_encoding(
            self.data,
            versao="v1",
            medium_strategy="binary_top3",
            mlflow_run_id=mlflow_run_id,
            model_path=model_path
        )

        encoding_cols_added = len(self.data.columns) - cols_before_encoding
        logger.info(f"    Colunas adicionadas pelo encoding: {encoding_cols_added}")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 11. Manter features UTM (configuração fixa)
        logger.info(" [11/12] Mantendo features UTM")

        # Resumo final
        final_rows = len(self.data)
        final_cols = len(self.data.columns)
        total_rows_removed = initial_rows - final_rows
        net_cols_change = final_cols - initial_cols

        logger.info(f" RESUMO FINAL (v1, com UTM):")
        logger.info(f"    Linhas: {initial_rows}{final_rows} (removidas: {total_rows_removed})")
        logger.info(f"    Colunas: {initial_cols}{final_cols} (variação: {net_cols_change:+d})")

        return self.data

    def predict(self, df: pd.DataFrame = None) -> pd.DataFrame:
        """
        Realiza predições no DataFrame processado.

        Args:
            df: DataFrame a ser usado (se None, usa self.data)

        Returns:
            DataFrame original com scores de predição
        """
        if df is None:
            if self.data is None:
                raise ValueError("Nenhum dado disponível para predição. Execute preprocess() primeiro.")
            df = self.data

        logger.info("=== Iniciando Predições ===")
        # Passar tanto o DataFrame processado quanto o original
        result = self.predictor.predict(df, self.original_data)
        logger.info("=== Predições Concluídas ===")

        return result

    def run(self, filepath: str, with_predictions: bool = False) -> pd.DataFrame:
        """
        Executa o pipeline completo.

        Args:
            filepath: Caminho para o arquivo de entrada
            with_predictions: Se True, inclui predições no resultado

        Returns:
            DataFrame processado (com predições se solicitado)
        """
        # Configurar redirecionamento de output para arquivo
        log_path, tee = setup_output_logging()

        # Registrar função de cleanup para fechar arquivo ao terminar
        def cleanup():
            tee.close()
            sys.stdout = tee.terminal
            sys.stderr = tee.terminal

        atexit.register(cleanup)

        print(f"\n Output sendo salvo em: {log_path}\n")

        logger.info("=== Iniciando Pipeline de Lead Scoring (Produção) ===")

        # Carregar dados
        self.load_data(filepath)

        # Pré-processar
        self.preprocess()

        # Fazer predições se solicitado
        if with_predictions:
            self.data = self.predict()

        logger.info("=== Pipeline concluído ===")
        print(f"\n Output completo salvo em: {log_path}\n")

        return self.data