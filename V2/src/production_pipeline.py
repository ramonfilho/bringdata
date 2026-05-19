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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from .core.client_config import ClientConfig, ABTestConfig, ABTestVariantConfig
from .core.preprocessing import preprocess as _preprocess
from .core.utm import unify_utm
from .core.medium import unify_medium as _unify_medium
from .core.category_unification import unify_categories as _unify_categories
from .core.feature_engineering import create_features as _create_features
from .core.encoding import apply_encoding as _apply_encoding, merge_encoding as _merge_encoding
from .core.feature_validator import (
    load_schema_from_json as _load_fv_schema,
    validate_pre_encoding as _validate_pre_encoding,
)
from .core.startup_checks import validate_model_loaded as _validate_model_loaded
from .model.prediction import LeadScoringPredictor
from .monitoring.data_quality import check_category_drift, load_training_categories, check_distribution_drift, load_training_distributions

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _log_step_count(step: str, df_after, n_before=None, target_col: str = 'target') -> None:
    """T2-2: log estruturado de N registros por etapa do pipeline (mesmo formato do train).

    Aceita n_before (int) — produção sobrescreve self.data, então não há df_before disponível.
    """
    n_after = len(df_after)
    parts = [f"[{step}] N={n_after:,}"]
    if n_before is not None:
        delta = n_after - n_before
        pct = (delta / n_before * 100) if n_before else 0.0
        parts.append(f"Δ={delta:+,} ({pct:+.1f}%)")
    if target_col in df_after.columns:
        parts.append(f"positivos={int(df_after[target_col].sum()):,}")
    logger.info("  " + " | ".join(parts))


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
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
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

    def __init__(self, model_name: str = None, model_path: str = None, client_id: str = 'devclub'):
        """
        Inicializa o pipeline com configuração fixa.

        Args:
            model_name: Nome do modelo a usar para predições (default: None = usa active_model.yaml)
            model_path: Caminho customizado para a pasta do modelo (opcional)
            client_id: Identificador do cliente — carrega configs/clients/{client_id}.yaml (default: 'devclub')

        Configuração:
        - Mantém features UTM (com_utm=True)
        - Dataset V1 (versao="v1")
        - Sem cutoff temporal
        - Se model_name e model_path forem None, usa o modelo ativo do configs/active_model.yaml
        """
        self.data = None
        self.original_data = None  # Preservar dados originais
        self.predictor = LeadScoringPredictor(model_name, model_path=model_path, use_active_model=True)

        # Carregar ClientConfig a partir do client_id — nunca hardcodar 'devclub'
        _config_path = os.path.join(os.path.dirname(__file__), '..', 'configs', 'clients', f'{client_id}.yaml')
        self._client_config = ClientConfig.from_yaml(os.path.abspath(_config_path))

        # Carregar ABTestConfig de configs/active_models/{client_id}.yaml
        _active_models_path = os.path.join(os.path.dirname(__file__), '..', 'configs', 'active_models', f'{client_id}.yaml')
        self._ab_test_config = ABTestConfig.from_active_model_yaml(os.path.abspath(_active_models_path))

        # Carregar modelo e metadados automaticamente
        self.predictor.load_model()

        # T3-6 + T3-7: validações loud no startup. Aborta se modelo não carregou
        # ou se run_id em runtime divergir do YAML (deploy desalinhado).
        # Ler mlflow_run_id direto do YAML como fonte independente (não via predictor).
        _expected_run_id = None
        try:
            import yaml as _yaml
            with open(os.path.abspath(_active_models_path)) as _f:
                _am_yaml = _yaml.safe_load(_f)
            _expected_run_id = (_am_yaml.get('active_model') or {}).get('mlflow_run_id')
        except Exception as _exc:
            logger.warning(f"[T3-7] não foi possível ler mlflow_run_id do YAML: {_exc}")
        _validate_model_loaded(self.predictor, _expected_run_id, client_id=client_id)

        # Se A/B test habilitado, carregar predictor por variante
        self._variant_predictors: Dict[str, LeadScoringPredictor] = {}
        if self._ab_test_config.enabled:
            for variant_name, variant in self._ab_test_config.variants.items():
                vpredictor = LeadScoringPredictor(mlflow_run_id=variant.run_id)
                vpredictor.load_model()
                _validate_model_loaded(vpredictor, variant.run_id, client_id=f"{client_id}/{variant_name}")
                self._variant_predictors[variant_name] = vpredictor
                logger.info(f"A/B test: variante '{variant_name}' carregada (run_id={variant.run_id})")

    def get_ab_variant(
        self,
        lead_utms: Dict[str, Optional[str]],
        event_source_url: Optional[str] = None,
    ) -> Optional[ABTestVariantConfig]:
        """
        Retorna a variante A/B que casa com os UTMs ou URL de origem do lead (OR logic).
        Retorna None se o teste estiver desabilitado ou nenhuma variante casar
        (lead fica fora do teste e é processado normalmente).

        lead_utms: dict com chaves utm_source, utm_medium, utm_campaign,
                   utm_content, utm_term (valores podem ser None).
        event_source_url: URL da página de origem (opcional, usado p/ url_pattern da variante).
        """
        if not self._ab_test_config.enabled:
            return None
        return self._ab_test_config.match_variant(lead_utms, event_source_url=event_source_url)

    def get_variant_predictor(self, variant_name: str) -> LeadScoringPredictor:
        """Retorna o predictor carregado para a variante especificada."""
        if variant_name not in self._variant_predictors:
            raise KeyError(f"Variante '{variant_name}' não encontrada. Variantes disponíveis: {list(self._variant_predictors)}")
        return self._variant_predictors[variant_name]

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

        Pulado quando predictor não expõe model_path (modo MLflow run_id em
        produção via A/B test). O daily-check do orchestrator cobre o mesmo
        sinal com janela maior e estatística mais robusta — fixar este
        caminho não traria ganho operacional.
        """
        if not self.predictor.model_path:
            return []
        try:
            categorias_esperadas = load_training_categories(self.predictor.model_path)
            return check_category_drift(self.data, categorias_esperadas)
        except FileNotFoundError as e:
            logger.warning(f" Arquivo de categorias não encontrado: {e}")
            return []
        except Exception as e:
            logger.error(f" Erro ao verificar category drift: {e}")
            return []

    def preprocess(self, encoding_overrides=None, predictor_override=None, enforce_post_encoding: bool = True) -> pd.DataFrame:
        """
        Aplica pré-processamento aos dados.

        Args:
            encoding_overrides: EncodingConfig com overrides a mesclar (DT-12).
            predictor_override: Predictor da variante A/B. Quando fornecido, o feature
                                registry desse predictor é usado para alinhar features no
                                encoding (passo 7), em vez do predictor base da pipeline.

        Returns:
            DataFrame pré-processado
        """
        if self.data is None:
            raise ValueError("Dados não carregados. Use load_data() primeiro.")

        initial_rows = len(self.data)
        initial_cols = len(self.data.columns)

        logger.info(f" INÍCIO DO PIPELINE: {initial_rows} linhas, {initial_cols} colunas")

        # 1–3 + rename + remove_technical: sequência canônica via core/preprocessing.py
        logger.info(" [1/8] Pré-processamento (dedup + limpeza de colunas + renomeação)...")
        rows_before = len(self.data)
        cols_before = len(self.data.columns)
        self.data = _preprocess(self.data, self._client_config.ingestion, self._client_config.feature)
        logger.info(f"    Linhas: {rows_before} → {len(self.data)} (removidas: {rows_before - len(self.data)})")
        logger.info(f"    Colunas: {cols_before} → {len(self.data.columns)}")
        _log_step_count("preprocess_core", self.data, n_before=rows_before)

        # 4. Unificar categorias UTM (usando componente importado)
        logger.info(" [4/11] Unificando categorias UTM...")
        utm_source_before = self.data['Source'].nunique() if 'Source' in self.data.columns else 0
        utm_term_before = self.data['Term'].nunique() if 'Term' in self.data.columns else 0

        self.data = unify_utm(self.data, self._client_config.utm)

        utm_source_after = self.data['Source'].nunique() if 'Source' in self.data.columns else 0
        utm_term_after = self.data['Term'].nunique() if 'Term' in self.data.columns else 0
        logger.info(f"    Source: {utm_source_before}{utm_source_after} categorias")
        logger.info(f"    Term: {utm_term_before}{utm_term_after} categorias")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # Construir artifacts uma vez — reutilizado por medium e encoding.
        # Usa o predictor da variante quando fornecido (DT-12): garante que o feature
        # registry do modelo correto seja usado no passo 7 do encoding.
        _effective_predictor = predictor_override or self.predictor
        mlflow_run_id = _effective_predictor.mlflow_run_id if hasattr(_effective_predictor, 'mlflow_run_id') else None
        model_path = str(_effective_predictor.model_path) if _effective_predictor.model_path and not mlflow_run_id else None
        _artifacts = {}
        if mlflow_run_id:
            _artifacts['mlflow_run_id'] = mlflow_run_id
        elif model_path:
            _artifacts['model_path'] = model_path
        # [Correção 3] Default True = produção bloqueia (proteção de runtime).
        # Caminho de equivalência de deploy passa False (observa, não bloqueia).
        _artifacts['post_encoding_enforce'] = enforce_post_encoding

        # 5. Unificar categorias Medium (usando componente importado)
        # Guard de coluna espelha o do train_pipeline.py — se a coluna Medium não vier
        # no payload (ex: cliente sem Medium ou bug de webhook), pula a unificação em
        # vez de quebrar com KeyError. Comportamento idêntico ao treino para preservar
        # paridade. Leads com Medium=NaN seguem normalmente — viram 'Outros' no encoding.
        logger.info(" [5/11] Unificando categorias Medium...")
        if 'Medium' in self.data.columns:
            medium_before = self.data['Medium'].nunique()
            self.data = _unify_medium(self.data, self._client_config.medium, _artifacts or None)
            medium_after = self.data['Medium'].nunique()
            logger.info(f"    Medium: {medium_before}{medium_after} categorias")
        else:
            logger.warning("    Medium ausente do DataFrame — pulando unify_medium (paridade com treino)")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # 6. Unificar categorias de pesquisa (usando componente importado)
        logger.info(" [6/11] Unificando categorias de pesquisa...")

        # Contar categorias antes para tracking
        categorias_antes = {}
        colunas_pesquisa = [
            'interesse_programacao', 'Tem computador/notebook?',
            'O que mais você quer ver no evento?', 'Você possui cartão de crédito?',
            'Atualmente, qual a sua faixa salarial?', 'O que você faz atualmente?',
            'Qual a sua idade?', 'Você já fez/faz/pretende fazer faculdade?'
        ]
        for col in colunas_pesquisa:
            if col in self.data.columns:
                categorias_antes[col] = self.data[col].nunique()

        self.data = _unify_categories(self.data, self._client_config.category)

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
        # Pulado quando predictor não expõe model_path (modo MLflow run_id via A/B test).
        # Daily-check cobre o mesmo sinal com janela maior — ver check_category_drift().
        if self.predictor.model_path:
            logger.info(" [8.5/12] Verificando distribution drift...")
            try:
                distribuicoes_esperadas = load_training_distributions(self.predictor.model_path)
                distribution_alerts = check_distribution_drift(self.data, distribuicoes_esperadas)

                if distribution_alerts:
                    logger.warning(f"  {len(distribution_alerts)} alertas de distribution drift detectados:")
                    for alert in distribution_alerts:
                        logger.warning(f"   {alert['message']}")
                    if not hasattr(self, 'alerts'):
                        self.alerts = []
                    self.alerts.extend(distribution_alerts)
                else:
                    logger.info("    Nenhuma mudança drástica nas distribuições")
            except FileNotFoundError as e:
                logger.warning(f" Arquivo de distribuições não encontrado: {e}")
            except Exception as e:
                logger.error(f" Erro ao verificar distribution drift: {e}")

        # 9. Engenharia de features (usando componente importado)
        logger.info(" [9/12] Aplicando engenharia de features...")
        cols_before_fe = len(self.data.columns)

        # Verificar se colunas necessárias existem
        fe_input_cols = ['Data', 'Nome Completo', 'E-mail', 'Telefone']
        available_fe_cols = [col for col in fe_input_cols if col in self.data.columns]
        logger.info(f"    Colunas disponíveis para FE: {available_fe_cols}")

        self.data = _create_features(self.data, self._client_config.feature)


        cols_added = len(self.data.columns) - cols_before_fe
        logger.info(f"    Features criadas/processadas: {cols_added} novas colunas")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")

        # [T1-11] Validador pré-encoding — monitoramento em produção
        _fv_schema_path = Path(__file__).parent.parent / 'configs' / 'pre_encoding_schemas' / f'{self._client_config.client_id}.json'
        if _fv_schema_path.exists():
            try:
                _fv_schema = _load_fv_schema(str(_fv_schema_path))
                _fv_result = _validate_pre_encoding(self.data, _fv_schema, emit_log=True)
                logger.info(f"    [T1-11] feature_validator: severity={_fv_result.severity}, issues={len(_fv_result.issues)}")
            except Exception as _fv_err:
                logger.warning(f"    [T1-11] feature_validator falhou: {_fv_err} — seguindo sem validação")
        else:
            logger.debug(f"    [T1-11] schema não encontrado em {_fv_schema_path} — validator ignorado")

        # 10. Encoding categórico (usando componente importado)
        logger.info(" [10/12] Aplicando encoding categórico...")
        cols_before_encoding = len(self.data.columns)

        effective_encoding = _merge_encoding(self._client_config.encoding, encoding_overrides)
        rows_before_encoding = len(self.data)
        self.data = _apply_encoding(self.data, effective_encoding, _artifacts)

        encoding_cols_added = len(self.data.columns) - cols_before_encoding
        logger.info(f"    Colunas adicionadas pelo encoding: {encoding_cols_added}")
        logger.info(f"    Estado atual: {len(self.data)} linhas, {len(self.data.columns)} colunas")
        _log_step_count("encoding", self.data, n_before=rows_before_encoding)

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

    def predict(self, df: pd.DataFrame = None, predictor_override: "LeadScoringPredictor" = None) -> pd.DataFrame:
        """
        Realiza predições no DataFrame processado.

        Args:
            df: DataFrame a ser usado (se None, usa self.data)
            predictor_override: Predictor alternativo a usar (ex: variante A/B). Se None, usa self.predictor.

        Returns:
            DataFrame original com scores de predição
        """
        if df is None:
            if self.data is None:
                raise ValueError("Nenhum dado disponível para predição. Execute preprocess() primeiro.")
            df = self.data

        predictor = predictor_override or self.predictor
        logger.info("=== Iniciando Predições ===")
        result = predictor.predict(df, self.original_data)
        logger.info("=== Predições Concluídas ===")

        return result

    def run(self, filepath: str, with_predictions: bool = False, predictor_override: "LeadScoringPredictor" = None, encoding_overrides=None, enforce_post_encoding: bool = True) -> pd.DataFrame:
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

        # Pré-processar (passa predictor_override para usar o feature registry correto — DT-12)
        self.preprocess(encoding_overrides=encoding_overrides, predictor_override=predictor_override, enforce_post_encoding=enforce_post_encoding)

        # Fazer predições se solicitado
        if with_predictions:
            self.data = self.predict(predictor_override=predictor_override)

        logger.info("=== Pipeline concluído ===")
        print(f"\n Output completo salvo em: {log_path}\n")

        return self.data