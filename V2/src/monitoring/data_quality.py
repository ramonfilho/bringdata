"""
Monitor de qualidade de dados e detecção de drift.

Detecta:
- Novas categorias não vistas no treino (category drift)
- Mudanças drásticas nas proporções de categorias (distribution drift)
- Mudanças drásticas nas distribuições de features numéricas
- Missing rate alto em colunas
- Mudanças na distribuição de scores/decis
"""

import json
import pandas as pd
import numpy as np
import logging
from typing import Dict, Set, List, Tuple
from pathlib import Path
from unidecode import unidecode
import re

logger = logging.getLogger(__name__)


def normalizar_categoria_para_comparacao(texto):
    """
    Normaliza categoria para comparação no drift detection.

    Aplica MESMA normalização que limpar_texto() usa no treino/produção:
    - Lowercase
    - Remove acentos
    - Remove pontuação
    - Normaliza espaços

    IMPORTANTE: Esta normalização é aplicada APENAS para comparação no monitoramento.
    Os dados reais não são alterados. Isso evita alertas falsos onde "Sou autonomo"
    (sem acento, em produção) seria detectado como categoria nova vs "Sou autônomo"
    (com acento, no treino).

    Args:
        texto: String a ser normalizada

    Returns:
        String normalizada ou None se NaN
    """
    if pd.isna(texto):
        return None

    texto_norm = str(texto)
    texto_norm = texto_norm.strip()
    texto_norm = texto_norm.lower()
    texto_norm = unidecode(texto_norm)
    texto_norm = re.sub(r'[^\w\s]', '', texto_norm)
    texto_norm = re.sub(r'\s+', ' ', texto_norm)
    texto_norm = texto_norm.strip()

    return texto_norm if texto_norm else None


def calculate_missing_rate(df: pd.DataFrame, col: str) -> float:
    """
    Calcula taxa de valores ausentes em uma coluna.

    Considera ausente:
    - NaN / None (pd.isna())
    - Strings vazias após strip ('', '  ', etc)

    Esta função é usada em múltiplos lugares para garantir consistência:
    - Quality Gate no pipeline de retreino (train_pipeline.py)
    - Monitoramento de produção (data_quality.py)
    - Validação de dados

    Args:
        df: DataFrame
        col: Nome da coluna

    Returns:
        Float entre 0.0 e 1.0 (proporção de valores ausentes)
        Retorna 0.0 se coluna não existir ou DataFrame vazio

    Examples:
        >>> df = pd.DataFrame({'A': [1, None, 3], 'B': ['a', '', 'c']})
        >>> calculate_missing_rate(df, 'A')
        0.3333333333333333
        >>> calculate_missing_rate(df, 'B')
        0.3333333333333333
    """
    if col not in df.columns:
        return 0.0

    total_rows = len(df)
    if total_rows == 0:
        return 0.0

    # Contar NaN/None
    missing_count = int(df[col].isna().sum())

    # Adicionar strings vazias (após strip)
    # Importante: só verificar strings vazias se a coluna tiver tipo object
    if df[col].dtype == 'object':
        missing_count += int((df[col].astype(str).str.strip() == '').sum())

    return float(missing_count / total_rows)


def capture_training_categories(df: pd.DataFrame, output_path: str = None) -> Dict[str, List[str]]:
    """
    Captura categorias únicas de colunas categóricas ANTES do encoding.

    Identifica automaticamente colunas categóricas (object ou <= 20 valores únicos)
    e salva suas categorias para comparação futura em produção.

    Args:
        df: DataFrame ANTES do encoding (com colunas categóricas originais)
        output_path: Caminho para salvar JSON (opcional)

    Returns:
        Dict com {coluna: [categorias]}
    """
    logger.debug("\n Identificando colunas categóricas automaticamente...")

    categorias_por_coluna = {}

    # Colunas a ignorar (apenas campos removidos, não features derivadas)
    # Features derivadas (nome_valido, email_valido, etc) SÃO rastreadas
    # para detectar mudanças na qualidade dos dados
    colunas_ignorar = {
        'target',
        'Data',  # será removida no FE
        'Nome Completo',  # será removida no FE
        'E-mail',  # será removida no FE
        'Telefone'  # será removida no FE
    }

    for col in df.columns:
        # Pular colunas ignoradas
        if col in colunas_ignorar:
            continue

        # Identificar colunas categóricas:
        # 1. Tipo object (string)
        # 2. Tipo bool (booleanas - features de qualidade)
        # 3. OU numérica com poucos valores únicos (<=20) - pode ser ordinal encoding já aplicado
        is_categorical = (
            df[col].dtype == 'object' or
            df[col].dtype == 'bool' or
            (df[col].dtype in ['int64', 'float64'] and df[col].nunique() <= 20)
        )

        if is_categorical:
            # Pegar valores únicos (excluindo NaN)
            valores_unicos = df[col].dropna().unique()

            # Converter para string para garantir JSON serialização
            # (importante para ordinais numéricos)
            valores_unicos_str = [str(v) for v in valores_unicos]

            categorias_por_coluna[col] = sorted(valores_unicos_str)

            logger.debug(f"    {col}: {len(valores_unicos_str)} categorias")

    logger.debug(f"\n Total: {len(categorias_por_coluna)} colunas categóricas identificadas")

    # Salvar se caminho fornecido
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(categorias_por_coluna, f, indent=2, ensure_ascii=False)
        logger.debug(f" Categorias salvas em: {output_path}")

    return categorias_por_coluna


def check_category_drift(df_producao: pd.DataFrame,
                         categorias_esperadas: Dict[str, List[str]]) -> List[Dict]:
    """
    Verifica se há categorias novas em produção não vistas no treino.

    Args:
        df_producao: DataFrame de produção ANTES do encoding
        categorias_esperadas: Dict carregado do JSON do treino

    Returns:
        Lista de alertas (vazia se tudo OK)
    """
    alertas = []

    for col, categorias_treino in categorias_esperadas.items():
        if col not in df_producao.columns:
            # Coluna esperada não existe em produção
            alertas.append({
                'type': 'missing_column',
                'column': col,
                'severity': 'HIGH',
                'message': f" Coluna '{col}' esperada mas não encontrada em produção"
            })
            continue

        # Pegar categorias atuais
        categorias_producao = df_producao[col].dropna().unique()
        categorias_producao_str = [str(v) for v in categorias_producao]

        # Filtrar strings vazias e 'nan' (não são categorias reais)
        categorias_producao_str = [
            v for v in categorias_producao_str
            if v.strip() and v.lower() != 'nan'
        ]

        # NOVO: Normalizar ambas as listas para comparação
        # Isso evita falsos positivos onde "Sou autonomo" (sem acento) é detectado
        # como nova categoria vs "Sou autônomo" (com acento)
        categorias_producao_norm = [normalizar_categoria_para_comparacao(v) for v in categorias_producao_str]
        categorias_treino_norm = [normalizar_categoria_para_comparacao(v) for v in categorias_treino]

        # Remover None (valores que viraram vazios após normalização)
        categorias_producao_norm = [v for v in categorias_producao_norm if v]
        categorias_treino_norm = [v for v in categorias_treino_norm if v]

        # Encontrar novas categorias (comparando versões normalizadas)
        set_treino_norm = set(categorias_treino_norm)
        set_producao_norm = set(categorias_producao_norm)
        novas_categorias_norm = set_producao_norm - set_treino_norm

        # Se houver categorias novas após normalização, pegar os valores ORIGINAIS correspondentes
        if len(novas_categorias_norm) > 0:
            # Criar mapeamento: normalizado  original
            norm_to_original = {}
            for orig in categorias_producao_str:
                norm = normalizar_categoria_para_comparacao(orig)
                if norm and norm in novas_categorias_norm:
                    norm_to_original[norm] = orig

            novas_categorias = set(norm_to_original.values())
        else:
            novas_categorias = set()

        if len(novas_categorias) > 0:
            # Calcular % de leads com novas categorias
            total_leads = len(df_producao)
            leads_com_novas = df_producao[df_producao[col].astype(str).isin(novas_categorias)].shape[0]
            percentual = (leads_com_novas / total_leads) * 100 if total_leads > 0 else 0

            # Determinar severidade
            if percentual > 20:
                severity = 'HIGH'
            elif percentual > 10:
                severity = 'MEDIUM'
            else:
                severity = 'LOW'

            # Limitar quantidade de categorias exibidas
            novas_exibir = sorted(list(novas_categorias))[:5]
            mais_msg = f" (e mais {len(novas_categorias) - 5})" if len(novas_categorias) > 5 else ""

            alertas.append({
                'type': 'new_categories',
                'column': col,
                'new_categories': sorted(list(novas_categorias)),
                'count': leads_com_novas,
                'percentage': percentual,
                'severity': severity,
                'message': f" {col}: {len(novas_categorias)} nova(s) categoria(s) - {percentual:.1f}% dos leads\n"
                          f"   Novas: {', '.join(novas_exibir)}{mais_msg}"
            })

    return alertas


def load_training_categories(model_path: str) -> Dict[str, List[str]]:
    """
    Carrega categorias esperadas do arquivo JSON do modelo.

    Args:
        model_path: Caminho da pasta do modelo (ex: files/20260109_110657)

    Returns:
        Dict com categorias esperadas

    Raises:
        FileNotFoundError: Se arquivo não existir
    """
    # mlflow.sklearn.log_model salva artifacts em subdir 'model/'.
    # Tenta esse path primeiro; mantém o legado (raiz de model_path) como
    # fallback para artifacts antigos / modelos não-mlflow.
    candidates = [
        Path(model_path) / "model" / "categorias_esperadas.json",
        Path(model_path) / "categorias_esperadas.json",
    ]
    json_path = next((p for p in candidates if p.exists()), None)

    if json_path is None:
        raise FileNotFoundError(
            f"Arquivo de categorias não encontrado. Tentei: {[str(p) for p in candidates]}\n"
            f"Execute o treino novamente para gerar este arquivo."
        )

    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def capture_training_distributions(df: pd.DataFrame, output_path: str = None) -> Dict:
    """
    Captura distribuições completas (proporções categóricas + estatísticas numéricas).

    Args:
        df: DataFrame ANTES do encoding (com colunas originais)
        output_path: Caminho para salvar JSON (opcional)

    Returns:
        Dict com estrutura:
        {
            "categorical": {
                "coluna1": {"categoria1": 0.45, "categoria2": 0.55, ...}
            },
            "numerical": {
                "coluna1": {"mean": 10.5, "median": 9.0, "std": 3.2, ...}
            }
        }
    """
    logger.debug("\n Capturando distribuições de treino...")

    distribuicoes = {
        "categorical": {},
        "numerical": {}
    }

    # Colunas a ignorar (features derivadas, target, etc)
    colunas_ignorar = {
        'target',
        'Data',  # será removida no FE
        'Nome Completo',  # será removida no FE
        'E-mail',  # será removida no FE
        'Telefone'  # será removida no FE
    }

    for col in df.columns:
        if col in colunas_ignorar:
            continue

        # Contar valores não-nulos
        total_nao_nulos = df[col].notna().sum()
        if total_nao_nulos == 0:
            continue

        # Identificar tipo de coluna
        is_categorical = (
            df[col].dtype == 'object' or
            df[col].dtype == 'bool' or  # Booleanas são categóricas
            (df[col].dtype in ['int64', 'float64'] and df[col].nunique() <= 20)
        )

        if is_categorical:
            # Capturar proporções de categorias
            contagens = df[col].value_counts()
            proporcoes = (contagens / total_nao_nulos).to_dict()

            # Converter keys para string (importante para JSON)
            proporcoes_str = {str(k): float(v) for k, v in proporcoes.items()}

            distribuicoes["categorical"][col] = proporcoes_str
            logger.debug(f"    {col}: {len(proporcoes)} categorias")

        else:
            # Capturar estatísticas numéricas (apenas para numéricas reais, não booleanas)
            try:
                stats = {
                    "mean": float(df[col].mean()),
                    "median": float(df[col].median()),
                    "std": float(df[col].std()),
                    "min": float(df[col].min()),
                    "max": float(df[col].max()),
                    "q25": float(df[col].quantile(0.25)),
                    "q75": float(df[col].quantile(0.75)),
                    "missing_rate": float((df[col].isna().sum() / len(df)))
                }

                distribuicoes["numerical"][col] = stats
                logger.debug(f"    {col}: μ={stats['mean']:.2f}, σ={stats['std']:.2f}")
            except (TypeError, ValueError) as e:
                # Se não conseguir calcular estatísticas, tratar como categórica
                logger.debug(f"    {col}: não foi possível calcular estatísticas numéricas, tratando como categórica")
                contagens = df[col].value_counts()
                proporcoes = (contagens / total_nao_nulos).to_dict()
                proporcoes_str = {str(k): float(v) for k, v in proporcoes.items()}
                distribuicoes["categorical"][col] = proporcoes_str

    logger.debug(f"\n Total: {len(distribuicoes['categorical'])} categóricas, "
          f"{len(distribuicoes['numerical'])} numéricas")

    # Salvar se caminho fornecido
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(distribuicoes, f, indent=2, ensure_ascii=False)
        logger.debug(f" Distribuições salvas em: {output_path}")

    return distribuicoes


def check_distribution_drift(df_producao: pd.DataFrame,
                             distribuicoes_esperadas: Dict,
                             threshold_categorical: float = 0.15,
                             threshold_numerical: float = 2.0) -> List[Dict]:
    """
    Detecta mudanças drásticas nas distribuições.

    Args:
        df_producao: DataFrame de produção ANTES do encoding
        distribuicoes_esperadas: Dict carregado do JSON do treino
        threshold_categorical: Mudança mínima em % para alertar (padrão: 15pp)
        threshold_numerical: Mudança em desvios padrão para alertar (padrão: 2.0σ)

    Returns:
        Lista de alertas (vazia se tudo OK)
    """
    alertas = []

    # 1. Verificar mudanças em distribuições categóricas
    for col, proporcoes_treino in distribuicoes_esperadas.get("categorical", {}).items():
        if col not in df_producao.columns:
            continue

        # Calcular proporções atuais
        total_nao_nulos = df_producao[col].notna().sum()
        if total_nao_nulos == 0:
            continue

        contagens = df_producao[col].value_counts()
        proporcoes_producao = (contagens / total_nao_nulos).to_dict()

        # Normalizar keys de produção para comparação com treino
        # Ex: "25 - 34 anos" → "25 34 anos", "Sou CLT/Funcionário Público" → "sou cltfuncionario publico"
        proporcoes_producao_norm = {}
        for k, v in proporcoes_producao.items():
            norm_key = normalizar_categoria_para_comparacao(str(k))
            if norm_key:
                proporcoes_producao_norm[norm_key] = proporcoes_producao_norm.get(norm_key, 0.0) + float(v)

        # Normalizar também as keys de treino para comparação simétrica.
        # distribuicoes_esperadas.json armazena keys originais ('Não', 'Sim', 'Feminino'),
        # mas proporcoes_producao_norm já está normalizado ('nao', 'sim', 'feminino').
        # Sem essa normalização, 'Não' (treino) nunca encontra match em 'nao' (produção)
        # e gera diff = prop_treino → alerta HIGH falso sempre.
        proporcoes_treino_norm = {}
        for k, v in proporcoes_treino.items():
            norm_key = normalizar_categoria_para_comparacao(str(k))
            if norm_key:
                proporcoes_treino_norm[norm_key] = proporcoes_treino_norm.get(norm_key, 0.0) + float(v)

        # Comparar cada categoria
        mudancas_significativas = []
        for categoria, prop_treino in proporcoes_treino_norm.items():
            prop_producao = proporcoes_producao_norm.get(categoria, 0.0)
            diff = abs(prop_producao - prop_treino)

            # Alertar se mudança > threshold
            if diff >= threshold_categorical:
                mudancas_significativas.append({
                    'categoria': categoria,
                    'treino': prop_treino,
                    'producao': prop_producao,
                    'diff': diff
                })

        if mudancas_significativas:
            # Ordenar por maior diferença
            mudancas_significativas.sort(key=lambda x: x['diff'], reverse=True)

            # Formatar mensagem com todas as mudanças
            mudancas_msg = []
            for m in mudancas_significativas:
                mudancas_msg.append(
                    f"'{m['categoria']}': {m['treino']*100:.1f}%→{m['producao']*100:.1f}% "
                    f"({m['diff']*100:+.1f}pp)"
                )

            # Determinar severidade pela maior mudança
            max_diff = mudancas_significativas[0]['diff']
            if max_diff >= 0.30:  # 30pp
                severity = 'HIGH'
            elif max_diff >= 0.20:  # 20pp
                severity = 'MEDIUM'
            else:
                severity = 'LOW'

            alertas.append({
                'type': 'categorical_distribution_drift',
                'column': col,
                'changes': mudancas_significativas,
                'severity': severity,
                'message': f" {col}: {len(mudancas_significativas)} mudança(s) significativa(s) nas proporções\n"
                          f"   {', '.join(mudancas_msg)}"
            })

    # 2. Verificar mudanças em distribuições numéricas
    for col, stats_treino in distribuicoes_esperadas.get("numerical", {}).items():
        if col not in df_producao.columns:
            continue

        # Calcular estatísticas atuais
        if df_producao[col].notna().sum() == 0:
            continue

        mean_treino = stats_treino['mean']
        std_treino = stats_treino['std']
        mean_producao = float(df_producao[col].mean())
        std_producao = float(df_producao[col].std())

        # Calcular mudança em desvios padrão
        if std_treino > 0:
            mean_diff_sigma = abs(mean_producao - mean_treino) / std_treino
        else:
            mean_diff_sigma = 0.0

        # Alertar se mudança > threshold
        if mean_diff_sigma >= threshold_numerical:
            # Determinar severidade
            if mean_diff_sigma >= 3.0:
                severity = 'HIGH'
            elif mean_diff_sigma >= 2.5:
                severity = 'MEDIUM'
            else:
                severity = 'LOW'

            alertas.append({
                'type': 'numerical_distribution_drift',
                'column': col,
                'mean_treino': mean_treino,
                'mean_producao': mean_producao,
                'std_treino': std_treino,
                'std_producao': std_producao,
                'sigma_diff': mean_diff_sigma,
                'severity': severity,
                'message': f" {col}: média mudou {mean_diff_sigma:.1f}σ\n"
                          f"   Treino: μ={mean_treino:.2f} (σ={std_treino:.2f})\n"
                          f"   Produção: μ={mean_producao:.2f} (σ={std_producao:.2f})"
            })

    return alertas


def load_training_distributions(model_path: str) -> Dict:
    """
    Carrega distribuições esperadas do arquivo JSON do modelo.

    Args:
        model_path: Caminho da pasta do modelo (ex: files/20260109_110657)

    Returns:
        Dict com distribuições esperadas

    Raises:
        FileNotFoundError: Se arquivo não existir
    """
    # Mesma justificativa de path do load_training_categorias acima.
    candidates = [
        Path(model_path) / "model" / "distribuicoes_esperadas.json",
        Path(model_path) / "distribuicoes_esperadas.json",
    ]
    json_path = next((p for p in candidates if p.exists()), None)

    if json_path is None:
        raise FileNotFoundError(
            f"Arquivo de distribuições não encontrado. Tentei: {[str(p) for p in candidates]}\n"
            f"Execute o treino novamente para gerar este arquivo."
        )

    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# =============================================================================
# MONITOR DE QUALIDADE DE DADOS
# =============================================================================

class DataQualityMonitor:
    """
    Monitor de qualidade de dados.

    Verifica:
    - Category drift (categorias não vistas no treino)
    - Distribution drift (mudanças nas proporções)
    - Missing rate alto
    - Mudanças na distribuição de scores/decis
    """

    def __init__(self, model_path: str, client_config=None, db=None):
        """
        Args:
            model_path:    Caminho para pasta do modelo ativo
            client_config: ClientConfig opcional — usado para encoding via core/,
                           carregamento do modelo correto por client_id, e
                           overrides de thresholds/missing_rate_ignore_columns
            db:            SQLAlchemy session opcional. Quando presente, _check_score_distribution
                           usa rolling baseline 30d (produção atual vs produção recente) em vez
                           de comparar contra treino — mais robusto para falsos positivos crônicos
                           quando a distribuição de produção diverge estruturalmente da do treino.
        """
        from .config import THRESHOLDS, MISSING_RATE_IGNORE_COLUMNS
        self.model_path = model_path
        self.client_config = client_config
        self.db = db
        monitoring = client_config.monitoring if client_config else None
        self._thresholds = (
            monitoring.thresholds if monitoring and monitoring.thresholds else THRESHOLDS
        )
        self._missing_rate_ignore_columns = (
            monitoring.missing_rate_ignore_columns
            if monitoring and monitoring.missing_rate_ignore_columns
            else MISSING_RATE_IGNORE_COLUMNS
        )

    def check(self, df: pd.DataFrame) -> List[Dict]:
        """
        Executa todos os checks de qualidade de dados.

        Args:
            df: DataFrame com dados das últimas 24h do Sheets

        Returns:
            Lista de alertas no formato dict (compatível com Alert.from_dict)
        """
        from .config import EXPECTED_DECIL_DISTRIBUTION
        from datetime import datetime, timezone

        alerts = []

        # 1. Category drift
        if self._thresholds['category_drift']['enabled']:
            alerts.extend(self._check_category_drift(df))

        # 2. Distribution drift
        if self._thresholds['distribution_drift']['enabled']:
            alerts.extend(self._check_distribution_drift(df))

        # 3. Missing rate
        if self._thresholds['missing_rate']['enabled']:
            alerts.extend(self._check_missing_rate(df))

        # 4. Score distribution
        if self._thresholds['score_distribution']['enabled']:
            alerts.extend(self._check_score_distribution(df))

        # Remover colunas de output do modelo ANTES do check de features
        # Estas colunas (decil, lead_score) existem no Google Sheets porque foram
        # adicionadas pela produção, mas NÃO existiam quando a produção fez encoding.
        # O check de features precisa ver os dados EXATAMENTE como produção viu.
        colunas_output_modelo = ['decil', 'decil_normalized', 'lead_score']
        colunas_output_presentes = [col for col in colunas_output_modelo if col in df.columns]

        if colunas_output_presentes:
            df = df.drop(columns=colunas_output_presentes)

        # 5. Missing features (colunas esperadas não encontradas)
        # Agora df contém apenas as features que produção viu no encoding
        alerts.extend(self._check_missing_features(df))

        # 6. Extra features (colunas novas não esperadas pelo modelo)
        alerts.extend(self._check_extra_features(df))

        return alerts

    def _check_category_drift(self, df: pd.DataFrame) -> List[Dict]:
        """Verifica categorias não vistas no treino"""
        from datetime import datetime, timezone
        alerts = []

        try:
            categorias_esperadas = load_training_categories(self.model_path)
            drift_results = check_category_drift(df, categorias_esperadas)

            if drift_results:
                for result in drift_results:
                    alerts.append({
                        'type': 'category_drift',
                        'severity': result['severity'],
                        'category': 'data_quality',
                        'message': result['message'],
                        'details': {
                            'column': result['column'],
                            'new_categories': result.get('new_categories', []),
                            'affected_count': result.get('count', 0),
                            'percentage': result.get('percentage', 0)
                        },
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'metric_value': result.get('percentage', 0),
                        'threshold': None
                    })

        except (FileNotFoundError, Exception):
            pass

        return alerts

    def _check_distribution_drift(self, df: pd.DataFrame) -> List[Dict]:
        """Verifica mudanças drásticas nas proporções"""
        from datetime import datetime, timezone
        alerts = []

        try:
            distribuicoes_esperadas = load_training_distributions(self.model_path)
            threshold_cat = self._thresholds['distribution_drift']['categorical']
            threshold_num = self._thresholds['distribution_drift']['numerical']

            drift_results = check_distribution_drift(
                df, distribuicoes_esperadas,
                threshold_categorical=threshold_cat,
                threshold_numerical=threshold_num
            )

            # Criar alertas para drift results
            for result in drift_results:
                drift_type = result['type']

                if drift_type == 'categorical_distribution_drift':
                    details = {
                        'column': result['column'],
                        'changes': result['changes']
                    }
                    metric_value = result['changes'][0]['diff'] if result['changes'] else 0
                    threshold_used = threshold_cat
                else:
                    details = {
                        'column': result['column'],
                        'mean_treino': result['mean_treino'],
                        'mean_producao': result['mean_producao'],
                        'std_treino': result['std_treino'],
                        'std_producao': result['std_producao'],
                        'sigma_diff': result['sigma_diff']
                    }
                    metric_value = result['sigma_diff']
                    threshold_used = threshold_num

                alerts.append({
                    'type': 'distribution_drift',
                    'severity': result['severity'],
                    'category': 'data_quality',
                    'message': result['message'],
                    'details': details,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': metric_value,
                    'threshold': threshold_used
                })

        except (FileNotFoundError, Exception):
            pass

        return alerts

    def _check_missing_rate(self, df: pd.DataFrame) -> List[Dict]:
        """Verifica colunas com missing rate alto"""
        from datetime import datetime, timezone
        alerts = []
        threshold = self._thresholds['missing_rate']['threshold']

        total_rows = len(df)
        if total_rows == 0:
            return alerts

        missing_rates = {}
        colunas_acima_threshold = []

        for col in df.columns:
            # Ignorar colunas da whitelist
            if col in self._missing_rate_ignore_columns:
                continue

            # Usar função centralizada para calcular missing rate
            missing_rate = calculate_missing_rate(df, col)
            missing_rates[col] = missing_rate

            # Calcular missing_count para mensagem de alerta
            missing_count = int(missing_rate * total_rows)

            if missing_rate > threshold:
                colunas_acima_threshold.append((col, missing_rate))

                if missing_rate >= 0.50:
                    severity = 'HIGH'
                elif missing_rate >= 0.35:
                    severity = 'MEDIUM'
                else:
                    severity = 'LOW'

                alerts.append({
                    'type': 'missing_rate_high',
                    'severity': severity,
                    'category': 'data_quality',
                    'message': f" {col}: {missing_rate*100:.1f}% missing ({missing_count}/{total_rows} leads)",
                    'details': {
                        'column': col,
                        'missing_count': missing_count,
                        'total_rows': total_rows,
                        'missing_rate': missing_rate
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': missing_rate,
                    'threshold': threshold
                })

        return alerts

    def _check_score_distribution(self, df: pd.DataFrame) -> List[Dict]:
        """Verifica mudanças na distribuição de decis"""
        from .config import EXPECTED_DECIL_DISTRIBUTION
        from datetime import datetime, timezone
        import json as _json, os as _os
        alerts = []

        if 'decil' not in df.columns:
            return alerts

        threshold = self._thresholds['score_distribution']['threshold']
        total_leads = len(df)

        if total_leads == 0:
            return alerts

        # E5+E6: precedência de baseline para "esperado":
        #   1. Rolling 30d em produção (E6) — quando self.db disponível, mais robusto
        #      contra divergência estrutural treino × produção (D10 ~30% em prod vs ~10% no treino)
        #   2. model_metadata.json:decil_analysis (E5) — distribuição real do conjunto de
        #      calibração do treino
        #   3. EXPECTED_DECIL_DISTRIBUTION hardcoded (uniforme 10%) — fallback final
        expected_dist = dict(EXPECTED_DECIL_DISTRIBUTION)
        baseline_source = 'hardcoded_uniform'

        # Tentativa 1: rolling 30d em produção (E6)
        if self.db is not None:
            try:
                from sqlalchemy import text as _sa_text
                # Janela: últimos 30 dias antes da janela analisada (assume df = 24h atual)
                rows = self.db.execute(_sa_text(
                    'SELECT decil, COUNT(*) FROM "Lead" '
                    'WHERE "createdAt" >= NOW() - INTERVAL \'31 days\' '
                    '  AND "createdAt" <  NOW() - INTERVAL \'1 day\' '
                    '  AND decil IS NOT NULL '
                    'GROUP BY decil'
                )).fetchall()
                if rows:
                    total_30d = sum(int(r[1]) for r in rows)
                    if total_30d >= 1000:  # mínimo de amostra pra ser confiável
                        rolling = {f'D{int(r[0])}': int(r[1]) / total_30d for r in rows}
                        # Garantir que todas as 10 chaves existam (ausentes = 0)
                        rolling = {f'D{i}': rolling.get(f'D{i}', 0.0) for i in range(1, 11)}
                        expected_dist = rolling
                        baseline_source = f'rolling_30d_n={total_30d}'
            except Exception as _e:
                logger.warning(f"  [E6] falha ao calcular rolling 30d: {_e}")

        # Tentativa 2: model_metadata.json:decil_analysis (E5) — só se rolling não funcionou
        if baseline_source == 'hardcoded_uniform':
            try:
                for cand in ('model_metadata.json', 'model/model_metadata.json'):
                    p = _os.path.join(self.model_path, cand)
                    if _os.path.exists(p):
                        md = _json.load(open(p))
                        da = md.get('decil_analysis') or {}
                        if da:
                            total_train = sum(int(v.get('total_leads', 0)) for v in da.values() if isinstance(v, dict))
                            if total_train > 0:
                                real_dist = {}
                                for k, v in da.items():
                                    if not isinstance(v, dict): continue
                                    idx = str(k).replace('decil_', '')
                                    real_dist[f'D{idx}'] = int(v.get('total_leads', 0)) / total_train
                                if len(real_dist) == 10:
                                    expected_dist = real_dist
                                    baseline_source = f'training_metadata:{cand}'
                                    break
            except Exception as _e:
                logger.warning(f"  [E5] falha ao carregar decil_analysis: {_e}")

        logger.debug(f"  [score_distribution] baseline_source={baseline_source}")

        # Normalizar formato dos decis (D01  D1, D02  D2, etc)
        # Google Sheets pode ter 'D01' enquanto esperamos 'D1'
        df['decil_normalized'] = df['decil'].astype(str).str.replace(r'^D0(\d)$', r'D\1', regex=True)

        decil_counts = df['decil_normalized'].value_counts()
        distribuicao_atual = {
            decil: decil_counts.get(decil, 0) / total_leads
            for decil in expected_dist.keys()
        }

        diferencas_significativas = []
        for decil, prop_esperada in expected_dist.items():
            prop_atual = distribuicao_atual.get(decil, 0)
            diff = abs(prop_atual - prop_esperada)

            if diff > threshold:
                diferencas_significativas.append({
                    'decil': decil,
                    'esperado': prop_esperada,
                    'atual': prop_atual,
                    'diff': diff
                })

        if diferencas_significativas:
            diferencas_significativas.sort(key=lambda x: x['diff'], reverse=True)
            max_diff = diferencas_significativas[0]['diff']

            if max_diff >= 0.20:
                severity = 'HIGH'
            elif max_diff >= 0.15:
                severity = 'MEDIUM'
            else:
                severity = 'LOW'

            top_changes = diferencas_significativas[:3]
            changes_msg = ', '.join([
                f"{c['decil']}: {c['esperado']*100:.0f}%{c['atual']*100:.0f}% ({c['diff']*100:+.1f}pp)"
                for c in top_changes
            ])
            mais_msg = f" (e mais {len(diferencas_significativas)-3})" if len(diferencas_significativas) > 3 else ""

            alerts.append({
                'type': 'score_distribution_change',
                'severity': severity,
                'category': 'data_quality',
                'message': f" Distribuição de decis mudou: {changes_msg}{mais_msg}",
                'details': {
                    'changes': diferencas_significativas,
                    'total_leads': total_leads
                },
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metric_value': max_diff,
                'threshold': threshold
            })

        return alerts

    def _check_missing_features(self, df: pd.DataFrame) -> List[Dict]:
        """
        Verifica se todas as features esperadas pelo modelo seriam criadas após encoding.

        Usa o método Predictor.validate_features() para detectar features ausentes
        SEM fazer predição (apenas validação).

        Args:
            df: DataFrame ANTES do encoding (após feature engineering)

        Returns:
            Lista de alertas para features que estariam ausentes
        """
        from datetime import datetime, timezone

        alerts = []

        try:
            # 1. Criar predictor primeiro para obter run_id antes do encoding
            from model.prediction import LeadScoringPredictor
            predictor = LeadScoringPredictor(use_active_model=True, client_config=self.client_config)

            # 2. Aplicar encoding com artifacts para que step 7 (registry alignment) execute
            #    — sem artifacts, step 7 é pulado e categorias OHE ausentes viram falsos alertas
            if self.client_config and self.client_config.encoding:
                from core.encoding import apply_encoding
                artifacts = {}
                if predictor.mlflow_run_id:
                    artifacts['mlflow_run_id'] = predictor.mlflow_run_id
                elif predictor.model_path:
                    artifacts['model_path'] = str(predictor.model_path)
                df_encoded = apply_encoding(df.copy(), self.client_config.encoding, artifacts=artifacts)
            else:
                from features.encoding import apply_categorical_encoding
                df_encoded = apply_categorical_encoding(df.copy(), versao='v1', medium_strategy='binary_top3', model_path=self.model_path)

            # 3. Validar features (NÃO faz predição, só valida)
            validation = predictor.validate_features(df_encoded)

            if not validation['is_valid']:
                missing_features = validation['missing_features']

                # Criar alerta
                alerts.append({
                    'type': 'missing_expected_features',
                    'severity': 'HIGH',
                    'category': 'data_quality',
                    'message': f" {len(missing_features)} feature(s) esperada(s) pelo modelo ausente(s) após encoding",
                    'details': {
                        'missing_count': len(missing_features),
                        'missing_features': missing_features,
                        'total_expected': validation['total_expected'],
                        'total_created': validation['total_received']
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': len(missing_features),
                    'threshold': 0  # Qualquer feature faltando é problema
                })

        except Exception:
            pass

        return alerts

    def _check_extra_features(self, df: pd.DataFrame) -> List[Dict]:
        """
        Verifica se apareceram features/colunas novas que não existiam no treino.

        Detecta colunas extras que foram criadas mas não são esperadas pelo modelo.
        Isso pode indicar mudanças no formulário ou adição de novos campos.

        Args:
            df: DataFrame ANTES do encoding (após feature engineering)

        Returns:
            Lista de alertas para features extras detectadas
        """
        from datetime import datetime, timezone

        alerts = []

        logger.debug(" DEBUG: _check_extra_features() INICIADO")
        logger.debug(f"DataFrame recebido: {df.shape[0]} linhas, {df.shape[1]} colunas")
        logger.debug(f"Colunas: {sorted(df.columns.tolist())[:10]}...")

        try:
            # 1. Criar predictor primeiro para obter run_id antes do encoding
            from model.prediction import LeadScoringPredictor
            predictor = LeadScoringPredictor(use_active_model=True, client_config=self.client_config)

            # 2. Aplicar encoding com artifacts para que step 7 (registry alignment) execute
            #    — sem artifacts, step 7 é pulado e categorias OHE ausentes viram falsos alertas.
            #    Usa encoding_overrides do Champion (se definidos no AB test config) para que
            #    o check reflita o encoding real que o modelo recebe em produção.
            if self.client_config and self.client_config.encoding:
                from core.encoding import apply_encoding, merge_encoding
                artifacts = {}
                if predictor.mlflow_run_id:
                    artifacts['mlflow_run_id'] = predictor.mlflow_run_id
                elif predictor.model_path:
                    artifacts['model_path'] = str(predictor.model_path)

                # Buscar encoding_overrides do Champion via ABTestConfig
                effective_encoding = self.client_config.encoding
                try:
                    from core.client_config import ABTestConfig
                    import os as _os
                    _active_path = _os.path.abspath(_os.path.join(
                        _os.path.dirname(__file__), '..', '..', 'configs', 'active_models',
                        f'{self.client_config.client_id}.yaml',
                    ))
                    _ab = ABTestConfig.from_active_model_yaml(_active_path)
                    if _ab.enabled and predictor.mlflow_run_id:
                        _champion_v = next(
                            (v for v in _ab.variants.values() if v.run_id == predictor.mlflow_run_id),
                            None,
                        )
                        if _champion_v and _champion_v.encoding_overrides:
                            effective_encoding = merge_encoding(self.client_config.encoding, _champion_v.encoding_overrides)
                except Exception as _e:
                    logger.debug(f"  monitoring: encoding_overrides do champion não carregados: {_e}")

                df_encoded = apply_encoding(df.copy(), effective_encoding, artifacts=artifacts)
            else:
                from features.encoding import apply_categorical_encoding
                df_encoded = apply_categorical_encoding(df.copy(), versao='v1', medium_strategy='binary_top3', model_path=self.model_path)

            # Garantir que feature_names está carregado
            if predictor.feature_names is None:
                predictor.load_model()

            # 3. Identificar features extras (presentes no df mas não esperadas pelo modelo)
            expected_features = set(predictor.feature_names)

            # Remover 'target' se presente (só existe em treino, não em produção)
            actual_features = set(df_encoded.columns) - {'target'}

            extra_features = actual_features - expected_features

            logger.debug(f"\n Features esperadas: {len(expected_features)}")
            logger.debug(f" Features encontradas: {len(actual_features)}")
            logger.debug(f" Features extras: {len(extra_features)}")

            if extra_features:
                extra_features_list = sorted(list(extra_features))

                logger.debug(f"\n  DETECTOU {len(extra_features)} FEATURES EXTRAS:")
                for feat in extra_features_list[:10]:
                    logger.debug(f"   - {feat}")
                if len(extra_features) > 10:
                    logger.debug(f"   ... e mais {len(extra_features) - 10}")

                # Determinar severidade baseado na quantidade
                if len(extra_features) > 10:
                    severity = 'MEDIUM'
                elif len(extra_features) > 5:
                    severity = 'LOW'
                else:
                    severity = 'LOW'

                # Limitar quantidade exibida na mensagem
                features_to_show = extra_features_list[:5]
                mais_msg = f" (e mais {len(extra_features) - 5})" if len(extra_features) > 5 else ""

                # Criar alerta
                alert_msg = f"ℹ {len(extra_features)} feature(s) nova(s) detectada(s) após encoding (serão ignoradas pelo modelo)\n   Exemplos: {', '.join(features_to_show)}{mais_msg}"

                alerts.append({
                    'type': 'extra_unexpected_features',
                    'severity': severity,
                    'category': 'data_quality',
                    'message': alert_msg,
                    'details': {
                        'extra_count': len(extra_features),
                        'extra_features': extra_features_list,
                        'total_expected': len(expected_features),
                        'total_received': len(actual_features)
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': len(extra_features),
                    'threshold': 0  # Qualquer feature extra merece atenção
                })

                logger.debug(f"\n Alerta criado: {alert_msg}")
            else:
                logger.debug(f"\n Nenhuma feature extra detectada")


        except Exception as e:
            logger.error(f"\n ERRO em _check_extra_features(): {e}")
            import traceback
            traceback.print_exc()

        return alerts
