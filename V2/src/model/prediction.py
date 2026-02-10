"""
Módulo de predição para lead scoring.
Carrega modelos treinados e realiza predições.
"""

import pickle
import joblib
import json
import pandas as pd
import numpy as np
from pathlib import Path
import logging
import yaml

logger = logging.getLogger(__name__)


class LeadScoringPredictor:
    """Classe para realizar predições de lead scoring."""

    def __init__(self, model_name: str = None, model_path: str = None, use_active_model: bool = True):
        """
        Inicializa o preditor com um modelo específico.

        Args:
            model_name: Nome do modelo a ser carregado (sem extensão). Se None, usa modelo ativo do config.
            model_path: Caminho customizado para a pasta do modelo (opcional). Se None, usa modelo ativo do config.
            use_active_model: Se True (padrão), carrega modelo do configs/active_model.yaml se model_name e model_path forem None
        """
        self.model = None
        self.feature_names = None
        self.metadata = None

        # Prioridade: 1) model_path/model_name fornecidos, 2) config active_model, 3) fallback padrão
        if model_path and model_name:
            # Modo explícito: usar parâmetros fornecidos
            self.model_path = Path(model_path)
            self.model_name = model_name
        elif use_active_model:
            # Modo config: carregar do active_model.yaml
            try:
                config_path = Path(__file__).parent.parent.parent / "configs" / "active_model.yaml"
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)

                self.model_name = config['active_model']['model_name']
                self.model_path = Path(__file__).parent.parent.parent / config['active_model']['model_path']
                logger.info(f"Carregando modelo ativo do config: {self.model_name} @ {self.model_path}")
            except Exception as e:
                logger.warning(f"Falha ao carregar active_model.yaml: {e}. Usando fallback padrão.")
                # Fallback para o padrão antigo
                self.model_name = model_name or "v1_devclub_rf_temporal"
                self.model_path = Path(__file__).parent.parent.parent / "arquivos_modelo"
        else:
            # Modo legacy: usar padrão antigo
            self.model_name = model_name or "v1_devclub_rf_temporal"
            self.model_path = Path(__file__).parent.parent.parent / "arquivos_modelo"

    def load_model(self):
        """Carrega o modelo pickle e seus metadados."""
        model_file = self.model_path / f"modelo_lead_scoring_{self.model_name}.pkl"
        features_file = self.model_path / f"features_ordenadas_{self.model_name}.json"
        metadata_file = self.model_path / f"model_metadata_{self.model_name}.json"

        logger.info(f"Carregando modelo: {model_file}")
        try:
            # Tentar primeiro com joblib (mais robusto)
            self.model = joblib.load(model_file)
            logger.info("Modelo carregado com joblib")
        except Exception as e:
            logger.info(f"Joblib falhou ({e}), tentando com pickle...")
            with open(model_file, 'rb') as f:
                self.model = pickle.load(f)
            logger.info("Modelo carregado com pickle")

        logger.info(f"Carregando features esperadas: {features_file}")
        with open(features_file, 'r') as f:
            features_data = json.load(f)
            # Extrair feature names - suporta dois formatos:
            # 1. 'expected_dtypes' (dict com feature: dtype) - formato antigo
            # 2. 'feature_names' (list de strings) - formato novo
            if 'expected_dtypes' in features_data:
                self.feature_names = list(features_data['expected_dtypes'].keys())
            elif 'feature_names' in features_data:
                self.feature_names = features_data['feature_names']
            else:
                raise ValueError("Arquivo de features não contém 'expected_dtypes' nem 'feature_names'")

        logger.info(f"Carregando metadados: {metadata_file}")
        with open(metadata_file, 'r') as f:
            self.metadata = json.load(f)

        # Normalizar thresholds para formato D01-D10 (causa raiz do bug D09 vs D9)
        if 'decil_thresholds' in self.metadata and 'thresholds' in self.metadata['decil_thresholds']:
            from src.model.decil_thresholds import normalizar_thresholds
            thresholds_originais = self.metadata['decil_thresholds']['thresholds']
            thresholds_normalizados = normalizar_thresholds(thresholds_originais)
            self.metadata['decil_thresholds']['thresholds'] = thresholds_normalizados
            logger.info(f"Thresholds normalizados: {list(thresholds_normalizados.keys())}")

        logger.info(f"Modelo carregado: {self.model_name}")
        logger.info(f"Features esperadas: {len(self.feature_names)}")

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepara o DataFrame para ter exatamente as features esperadas pelo modelo.

        Args:
            df: DataFrame processado pelo pipeline

        Returns:
            DataFrame com features alinhadas ao modelo
        """
        logger.info(f"Preparando features para predição...")

        # PRINT ANTES DA REORDENAÇÃO/FILTRAGEM
        print("🔍 COLUNAS ANTES DA REORDENAÇÃO/FILTRAGEM (df processado):")
        for idx, col in enumerate(sorted(df.columns), 1):
            print(f"  {idx:2d}. {col}")
        print(f"\nTotal: {len(df.columns)} features")
        print(f"Shape: {df.shape}")

        logger.info(f"Colunas recebidas: {len(df.columns)}")

        # Criar DataFrame com as features esperadas
        X = pd.DataFrame()

        missing_features = []
        for feature in self.feature_names:
            if feature in df.columns:
                X[feature] = df[feature]
            else:
                # Feature ausente - preencher com 0
                missing_features.append(feature)
                X[feature] = 0

        if missing_features:
            logger.warning(f"Features ausentes (preenchidas com 0): {len(missing_features)}")
            logger.debug(f"Features ausentes: {missing_features[:10]}...")  # Mostrar primeiras 10

        # Garantir ordem correta das colunas
        X = X[self.feature_names]

        # PRINT DEPOIS DA REORDENAÇÃO/FILTRAGEM (equivalente ao pipeline de treino)
        print("🔍 COLUNAS EXATAS PASSADAS PARA O MODELO (X.columns):")
        for idx, col in enumerate(X.columns, 1):
            print(f"  {idx:2d}. {col}")
        print(f"\nTotal: {len(X.columns)} features")
        print(f"Shape: {X.shape}")

        # Guardar lista de features ausentes para uso posterior (ex: monitoramento)
        self.last_missing_features = missing_features

        logger.info(f"Features preparadas: {X.shape}")
        return X

    def predict(self, df: pd.DataFrame, original_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        Realiza predições no DataFrame processado.

        Args:
            df: DataFrame processado pelo pipeline
            original_df: DataFrame original com todas as colunas (opcional)

        Returns:
            DataFrame com colunas de score adicionadas (original se fornecido, processado caso contrário)
        """
        if self.model is None:
            self.load_model()

        # Preparar features
        X = self.prepare_features(df)

        # Fazer predições
        logger.info("Realizando predições...")

        # Probabilidades para cada classe
        probabilities = self.model.predict_proba(X)

        # Score é a probabilidade da classe positiva (1)
        scores = probabilities[:, 1]

        # SEMPRE usar DataFrame processado (sem duplicatas)
        # O original pode ter mais linhas se houve remoção de duplicatas no pipeline
        result_df = df.copy()
        logger.info(f"Usando DataFrame processado ({len(df)} registros únicos)")

        if original_df is not None and len(original_df) != len(df):
            duplicatas_removidas = len(original_df) - len(df)
            logger.warning(f"⚠️  {duplicatas_removidas} duplicatas foram removidas no pipeline")
            logger.info("Retornando apenas registros únicos com scores")

        # Adicionar apenas score (decis serão calculados por janela de análise)
        result_df['lead_score'] = scores

        logger.info(f"Predições concluídas para {len(result_df)} registros")
        logger.info(f"Score médio: {scores.mean():.4f}")
        logger.info(f"Score min/max: {scores.min():.4f} / {scores.max():.4f}")

        return result_df

    def validate_features(self, df: pd.DataFrame) -> dict:
        """
        Valida se todas as features esperadas seriam criadas, SEM fazer predição.

        Útil para monitoramento: detecta features ausentes sem o custo de rodar o modelo.

        Args:
            df: DataFrame processado (após encoding)

        Returns:
            Dict com informações de validação:
            {
                'missing_features': List[str],  # Features que estariam ausentes
                'missing_count': int,           # Quantidade de features ausentes
                'total_expected': int,          # Total de features esperadas
                'total_received': int,          # Total de colunas recebidas
                'is_valid': bool                # True se todas as features existem
            }
        """
        # Garantir que feature_names está carregado
        if self.feature_names is None:
            self.load_model()

        # Rodar prepare_features para detectar ausentes
        # (isso preenche self.last_missing_features)
        _ = self.prepare_features(df)

        return {
            'missing_features': self.last_missing_features,
            'missing_count': len(self.last_missing_features),
            'total_expected': len(self.feature_names),
            'total_received': len(df.columns),
            'is_valid': len(self.last_missing_features) == 0
        }

    def predict_single(self, lead_data: dict) -> float:
        """
        Realiza predição para um único lead.

        Args:
            lead_data: Dicionário com os dados do lead

        Returns:
            Score de probabilidade (0-1)
        """
        if self.model is None:
            self.load_model()

        # Converter para DataFrame
        df = pd.DataFrame([lead_data])

        # Preparar features
        X = self.prepare_features(df)

        # Fazer predição
        probability = self.model.predict_proba(X)[0, 1]

        return probability

    def get_feature_importances(self, top_n: int = 20):
        """
        Retorna as feature importances do modelo RandomForest.

        Args:
            top_n: Número de features mais importantes a retornar (padrão: 20)

        Returns:
            Lista de dicts com 'feature' e 'importance', ordenados por importância decrescente
        """
        if self.model is None:
            self.load_model()

        # Verificar se o modelo tem feature_importances_
        if not hasattr(self.model, 'feature_importances_'):
            logger.warning("Modelo não possui feature_importances_")
            return []

        # Obter importâncias
        importances = self.model.feature_importances_

        # Criar lista de dicts com feature name e importance
        feature_importance_list = [
            {'feature': name, 'importance': float(imp)}
            for name, imp in zip(self.feature_names, importances)
        ]

        # Ordenar por importância decrescente
        feature_importance_list.sort(key=lambda x: x['importance'], reverse=True)

        # Retornar top N
        return feature_importance_list[:top_n]