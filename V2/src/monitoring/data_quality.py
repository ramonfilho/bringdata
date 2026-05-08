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

    def __init__(self, model_path: str, client_config=None, db=None, expected_decil_dist=None):
        """
        Args:
            model_path:    Caminho para pasta do modelo ativo
            client_config: ClientConfig opcional — usado para encoding via core/,
                           carregamento do modelo correto por client_id, e
                           overrides de thresholds/missing_rate_ignore_columns
            db:            SQLAlchemy session opcional (legacy Cloud SQL). Mantido pra outras queries.
                           NÃO é usado para rolling 30d porque a tabela Lead vive no Railway.
            expected_decil_dist: Dict {'D1':0.10,'D2':0.10,...,'D10':0.30} pré-computado pelo
                           caller (Railway) para servir como baseline E6 (rolling 30d). Quando None,
                           _check_score_distribution cai em E5 (model_metadata) ou hardcoded uniform.
        """
        from .config import THRESHOLDS, MISSING_RATE_IGNORE_COLUMNS
        self.model_path = model_path
        self.client_config = client_config
        self.db = db
        self.expected_decil_dist = expected_decil_dist
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

        # 7. [T1-10 surface] Top-N features por importância ausentes — espelha
        #    a lógica de logger.error/warning emitida em apply_encoding pra
        #    que o daily-check / monitoring report enxergue ausências críticas
        #    sem precisar do operador grep nos logs do Cloud Run.
        alerts.extend(self._check_critical_features_coverage(df))

        # 8. [T1-13] Audience profile drift — compara o último dia completo
        #    BRT contra snapshot de referência (Top 5 ROAS) por categoria
        #    canônica (gênero, idade, ocupação, faixa salarial, cartão,
        #    programação, computador). Pré-encoding e independente de modelo.
        if self._thresholds.get('audience_profile_drift', {}).get('enabled', False):
            alerts.extend(self._check_audience_profile_drift(df))

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

        # Tentativa 1: rolling 30d pré-computado pelo caller (E6)
        # Caller (app.py:daily-check/railway) tem acesso ao Railway e passa a distribuição
        # já normalizada pra cá. Antes tentávamos via self.db, mas db é Cloud SQL legacy
        # e não tem a tabela Lead — query falhava silenciosamente.
        if self.expected_decil_dist:
            try:
                ed = self.expected_decil_dist
                if isinstance(ed, dict) and len(ed) >= 10:
                    expected_dist = {f'D{i}': float(ed.get(f'D{i}', 0.0)) for i in range(1, 11)}
                    baseline_source = ed.get('_source', 'rolling_30d_precomputed')
            except Exception as _e:
                logger.warning(f"  [E6] falha ao usar expected_decil_dist injetado: {_e}")

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
                    'total_leads': total_leads,
                    'baseline_source': baseline_source
                },
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metric_value': max_diff,
                'threshold': threshold
            })

        return alerts

    def _iter_active_variants(self):
        """
        Yields (variant_name, predictor, effective_encoding) para cada modelo
        "ativo" que recebe tráfego em produção:

          - Champion default (active_model.yaml) — sempre presente, mesmo com AB
            desabilitado. Se há variant cujo run_id == active_model.mlflow_run_id
            (DT-12 Champion shim), seu nome e encoding_overrides são adotados aqui;
            essa variant NÃO vira um yield separado.
          - Cada variant em ab_test.variants com run_id distinto do Champion
            (Challenger e companhia) — instanciada com mlflow_run_id próprio.

        Cada variant carrega seu próprio feature_names + (potencialmente) seu
        próprio encoding via DT-12 encoding_overrides. Os checks de monitoring
        precisam rodar contra TODAS as variants pra cobrir leads que possam ser
        roteados pra qualquer uma delas em produção.

        Falha ao carregar uma variant é loggada e a iteração segue (variant
        offline não deve mascarar checks das outras). Falha no Champion é fatal
        (sem Champion não há monitoring) e encerra a iteração.

        Quando self.client_config.encoding é None (legacy path sem core/),
        emite só o Champion com effective_encoding=None — caller usa fallback
        legacy (apply_categorical_encoding).
        """
        from model.prediction import LeadScoringPredictor

        # Legacy path — apenas Champion, sem encoding via core/
        if not (self.client_config and self.client_config.encoding):
            try:
                predictor = LeadScoringPredictor(use_active_model=True, client_config=self.client_config)
                yield ('champion (legacy)', predictor, None)
            except Exception as _e:
                logger.error(f" monitoring: falha ao carregar Champion (legacy): {_e}")
            return

        from core.encoding import merge_encoding
        from core.client_config import ABTestConfig
        import os as _os

        # 1. Champion default
        try:
            champion_predictor = LeadScoringPredictor(use_active_model=True, client_config=self.client_config)
        except Exception as _e:
            logger.error(f" monitoring: falha ao carregar Champion (active_model): {_e}")
            return

        # 2. AB config (opcional)
        ab = ABTestConfig(enabled=False)
        try:
            _active_path = _os.path.abspath(_os.path.join(
                _os.path.dirname(__file__), '..', '..', 'configs', 'active_models',
                f'{self.client_config.client_id}.yaml',
            ))
            ab = ABTestConfig.from_active_model_yaml(_active_path)
        except Exception as _e:
            logger.debug(f"  monitoring: ABTestConfig não carregado: {_e}")

        # 3. Champion: nome + encoding via shim (se houver variant com mesmo run_id)
        champion_name = 'champion'
        champion_encoding = self.client_config.encoding
        if ab.enabled and champion_predictor.mlflow_run_id:
            for vname, v in ab.variants.items():
                if v.run_id == champion_predictor.mlflow_run_id:
                    champion_name = vname
                    if v.encoding_overrides:
                        champion_encoding = merge_encoding(self.client_config.encoding, v.encoding_overrides)
                    break

        yield (champion_name, champion_predictor, champion_encoding)
        seen = {champion_predictor.mlflow_run_id}

        # 4. Variants challenger (run_id distinto do Champion)
        if not ab.enabled:
            return
        for vname, v in ab.variants.items():
            if v.run_id in seen:
                continue
            try:
                predictor = LeadScoringPredictor(
                    mlflow_run_id=v.run_id,
                    use_active_model=False,
                    client_config=self.client_config,
                )
                encoding = self.client_config.encoding
                if v.encoding_overrides:
                    encoding = merge_encoding(self.client_config.encoding, v.encoding_overrides)
                yield (vname, predictor, encoding)
                seen.add(v.run_id)
            except Exception as _e:
                logger.error(f" monitoring: falha ao carregar variant {vname} (run {v.run_id}): {_e}")

    def _check_missing_features(self, df: pd.DataFrame) -> List[Dict]:
        """
        Verifica se todas as features esperadas por CADA variant ativa seriam
        criadas após encoding.

        Itera sobre _iter_active_variants() (Champion + Challenger quando AB
        ativo); cada variant pode ter feature_names e encoding distintos, então
        o check é por-variant. Cada alerta carrega `variant_name` no payload.

        Args:
            df: DataFrame ANTES do encoding (após feature engineering)

        Returns:
            Lista de alertas para features que estariam ausentes (1 alerta por
            variant com features faltando)
        """
        from datetime import datetime, timezone

        alerts = []

        for variant_name, predictor, effective_encoding in self._iter_active_variants():
            try:
                if effective_encoding is not None:
                    from core.encoding import apply_encoding
                    artifacts = {}
                    if predictor.mlflow_run_id:
                        artifacts['mlflow_run_id'] = predictor.mlflow_run_id
                    elif predictor.model_path:
                        artifacts['model_path'] = str(predictor.model_path)
                    df_encoded = apply_encoding(df.copy(), effective_encoding, artifacts=artifacts)
                else:
                    from features.encoding import apply_categorical_encoding
                    df_encoded = apply_categorical_encoding(df.copy(), versao='v1', medium_strategy='binary_top3', model_path=self.model_path)

                validation = predictor.validate_features(df_encoded)
                if validation['is_valid']:
                    continue

                missing_features = validation['missing_features']
                alerts.append({
                    'type': 'missing_expected_features',
                    'severity': 'HIGH',
                    'category': 'data_quality',
                    'message': f" [{variant_name}] {len(missing_features)} feature(s) esperada(s) pelo modelo ausente(s) após encoding",
                    'details': {
                        'variant_name': variant_name,
                        'missing_count': len(missing_features),
                        'missing_features': missing_features,
                        'total_expected': validation['total_expected'],
                        'total_created': validation['total_received'],
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': len(missing_features),
                    'threshold': 0,
                })
            except Exception as _e:
                logger.error(f" ERRO em _check_missing_features() para variant '{variant_name}': {_e}")

        return alerts

    def _check_extra_features(self, df: pd.DataFrame) -> List[Dict]:
        """
        Verifica se apareceram features/colunas que não são esperadas por
        NENHUMA variant ativa (Champion ∪ Challenger…).

        Para evitar falso positivo quando uma feature é esperada por uma variant
        mas não pela outra, o conjunto "expected" é a UNIÃO dos feature_names
        de todas as variants. Mas o encoding aplicado pode diferir por variant
        (DT-12 ordinal vs OHE), então o df_encoded é gerado por-variant e o
        conjunto "actual" é a UNIÃO das colunas pós-encoding de todas elas.

        Args:
            df: DataFrame ANTES do encoding (após feature engineering)

        Returns:
            Lista com no máximo 1 alerta (extra = actual_union - expected_union)
        """
        from datetime import datetime, timezone

        alerts = []

        logger.debug(" DEBUG: _check_extra_features() INICIADO")
        logger.debug(f"DataFrame recebido: {df.shape[0]} linhas, {df.shape[1]} colunas")

        expected_union: Set[str] = set()
        actual_union: Set[str] = set()
        variants_checked = []

        for variant_name, predictor, effective_encoding in self._iter_active_variants():
            try:
                if effective_encoding is not None:
                    from core.encoding import apply_encoding
                    artifacts = {}
                    if predictor.mlflow_run_id:
                        artifacts['mlflow_run_id'] = predictor.mlflow_run_id
                    elif predictor.model_path:
                        artifacts['model_path'] = str(predictor.model_path)
                    df_encoded = apply_encoding(df.copy(), effective_encoding, artifacts=artifacts)
                else:
                    from features.encoding import apply_categorical_encoding
                    df_encoded = apply_categorical_encoding(df.copy(), versao='v1', medium_strategy='binary_top3', model_path=self.model_path)

                if predictor.feature_names is None:
                    predictor.load_model()

                expected_union |= set(predictor.feature_names)
                actual_union |= set(df_encoded.columns) - {'target'}
                variants_checked.append(variant_name)

            except Exception as _e:
                logger.error(f" ERRO em _check_extra_features() para variant '{variant_name}': {_e}")

        if not variants_checked:
            return alerts

        extra_features = actual_union - expected_union

        logger.debug(f"\n Variants checadas: {variants_checked}")
        logger.debug(f" Features esperadas (união): {len(expected_union)}")
        logger.debug(f" Features encontradas (união): {len(actual_union)}")
        logger.debug(f" Features extras: {len(extra_features)}")

        if not extra_features:
            return alerts

        extra_features_list = sorted(list(extra_features))

        # Severity escala com magnitude — mas se o df está vazio (zero variants
        # produziram encoded com valor) consideramos LOW por default.
        if len(extra_features) > 10:
            severity = 'MEDIUM'
        else:
            severity = 'LOW'

        features_to_show = extra_features_list[:5]
        mais_msg = f" (e mais {len(extra_features) - 5})" if len(extra_features) > 5 else ""
        alert_msg = (
            f"ℹ {len(extra_features)} feature(s) nova(s) não esperada(s) por NENHUMA "
            f"variant ativa ({', '.join(variants_checked)}) — serão ignoradas pelo modelo\n"
            f"   Exemplos: {', '.join(features_to_show)}{mais_msg}"
        )

        alerts.append({
            'type': 'extra_unexpected_features',
            'severity': severity,
            'category': 'data_quality',
            'message': alert_msg,
            'details': {
                'variants_checked': variants_checked,
                'extra_count': len(extra_features),
                'extra_features': extra_features_list,
                'total_expected_union': len(expected_union),
                'total_received_union': len(actual_union),
            },
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'metric_value': len(extra_features),
            'threshold': 0,
        })

        return alerts

    def _check_critical_features_coverage(self, df: pd.DataFrame) -> List[Dict]:
        """
        [T1-10 surface] Por VARIANT ativa, verifica cobertura das features TOP-N
        (por importância) que estariam ausentes do DataFrame após encoding+
        alignment.

        Cada variant tem seu próprio MLflow run (e portanto sua própria lista
        TOP-N de importância) — não dá pra tomar a união que nem em
        _check_extra_features. O check é por-variant; cada alerta carrega
        `variant_name`.

        Espelha a lógica em src/core/encoding.py:330-348 mas, em vez de só
        emitir logger.error/warning (que ficam invisíveis fora do Cloud Run),
        gera alerta formal pro daily-check / monitoring report.

        Severidade segue a regra do T1-10:
          - importância >= 5% → severity 'HIGH'  (era logger.error)
          - importância <  5% → severity 'MEDIUM' (era logger.warning)

        Args:
            df: DataFrame após feature engineering (mesmo input dos checks irmãos)

        Returns:
            Lista de alertas, um por (variant, feature TOP-N ausente).
        """
        from datetime import datetime, timezone

        alerts = []

        # Sem core encoding, nada a checar (legacy path) — top_features vive em artifacts MLflow.
        if not (self.client_config and self.client_config.encoding):
            return alerts

        from core.encoding import apply_encoding, _load_top_features

        for variant_name, predictor, effective_encoding in self._iter_active_variants():
            try:
                artifacts = {}
                if predictor.mlflow_run_id:
                    artifacts['mlflow_run_id'] = predictor.mlflow_run_id
                elif predictor.model_path:
                    artifacts['model_path'] = str(predictor.model_path)

                df_encoded = apply_encoding(df.copy(), effective_encoding, artifacts=artifacts)

                validation = predictor.validate_features(df_encoded)
                missing_features = set(validation.get('missing_features', []))
                if not missing_features:
                    continue

                top_features = _load_top_features(artifacts, min_importance=0.01)
                critical_missing = [f for f in top_features if f['name'] in missing_features]

                for f in critical_missing:
                    severity = 'HIGH' if f['importance'] >= 0.05 else 'MEDIUM'
                    alerts.append({
                        'type': 'critical_feature_coverage',
                        'severity': severity,
                        'category': 'data_quality',
                        'message': (
                            f"[T1-10][{variant_name}] Feature CRÍTICA ausente: '{f['name']}' "
                            f"(rank {f['rank']}, importância {f['importance']*100:.2f}%) "
                            f"— preenchida com 0, modelo cego para esse sinal"
                        ),
                        'details': {
                            'variant_name': variant_name,
                            'feature_name': f['name'],
                            'rank': f['rank'],
                            'importance_pct': round(f['importance'] * 100, 2),
                        },
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'metric_value': float(f['importance']),
                        'threshold': 0.05,
                    })
            except Exception as _e:
                logger.error(f" ERRO em _check_critical_features_coverage() para variant '{variant_name}': {_e}")

        return alerts

    # ------------------------------------------------------------------
    # [T1-13] Audience profile drift
    # ------------------------------------------------------------------

    # Mapeamento canônico de variantes do formulário → label canônico.
    # Mantido em paralelo com scripts/perfil_audiencia.py:UNIFICATION para que
    # o monitoring não dependa de scripts/. Mantenha sincronizado.
    _AUDIENCE_UNIFICATION = {
        'Qual a sua idade?': {
            'menos de 18 anos': '<18', 'menos de 18': '<18',
            '18 24 anos': '18-24', '18 24': '18-24',
            '25 34 anos': '25-34', '25 34': '25-34',
            '35 44 anos': '35-44', '35 44': '35-44',
            '45 54 anos': '45-54', '45 54': '45-54',
            'mais de 55 anos': '55+', '55': '55+',
        },
        'O que você faz atualmente?': {
            'sou cltfuncionario publico': 'CLT/funcionário público',
            'clt funcionario publico':    'CLT/funcionário público',
            'sou autonomo':               'Autônomo',
            'autonomo empreendedor':      'Autônomo',
            'sou apenas estudante':       'Estudante',
            'estudante':                  'Estudante',
            'sou aposentado':             'Aposentado',
            'aposentado':                 'Aposentado',
            'nao trabalho e nem estudo':  'Não trabalho/nem estudo',
            'desempregado':               'Não trabalho/nem estudo',
        },
        'Atualmente, qual a sua faixa salarial?': {
            'entre r1000 a r2000 reais ao mes': 'Até R$2.000',
            'ate r 2000':                       'Até R$2.000',
            'entre r2001 a r3000 reais ao mes': 'R$2.001-3.000',
            'r 2001 a 3000':                    'R$2.001-3.000',
            'entre r3001 a r5000 reais ao mes': 'R$3.001-5.000',
            'r 3001 a 5000':                    'R$3.001-5.000',
            'mais de r5001 reais ao mes':       'Acima de R$5.000',
            'acima de r 5000':                  'Acima de R$5.000',
            'nao tenho renda':                  'Sem renda',
            'nenhuma renda':                    'Sem renda',
        },
        'O seu gênero:':                  {'masculino': 'Masculino', 'feminino': 'Feminino'},
        'Você possui cartão de crédito?': {'sim': 'Sim', 'nao': 'Não'},
        'Já estudou programação?':        {'sim': 'Sim', 'nao': 'Não'},
        'Tem computador/notebook?':       {'sim': 'Sim', 'nao': 'Não'},
    }

    def _load_reference_audience_profile(self):
        """
        Carrega o snapshot de referência de
        configs/reference_audience_profiles/{client_id}.json.

        Retorna (snapshot_dict, None) em sucesso, ou (None, error_dict) se
        ausente / corrompido. error_dict tem chaves 'reason' e 'tried_paths'.
        """
        if not (self.client_config and getattr(self.client_config, 'client_id', None)):
            return None, {'reason': 'client_id_missing', 'tried_paths': []}
        client_id = self.client_config.client_id
        candidates = [
            Path('configs/reference_audience_profiles') / f'{client_id}.json',
            Path(__file__).resolve().parents[2] / 'configs' / 'reference_audience_profiles' / f'{client_id}.json',
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            return None, {
                'reason': 'snapshot_file_not_found',
                'tried_paths': [str(p) for p in candidates],
            }
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f), None
        except Exception as e:
            return None, {'reason': f'load_error: {e}', 'tried_paths': [str(path)]}

    def _normalize_audience_series(self, s: pd.Series, col: str) -> pd.Series:
        """Normaliza categoria + aplica mapeamento canônico para a coluna."""
        s = s.fillna('(nulo)').astype(str).str.strip()
        s = s.replace({'': '(nulo)', 'None': '(nulo)', 'nan': '(nulo)'})
        s = s.apply(lambda v: '(nulo)' if v == '(nulo)' else (normalizar_categoria_para_comparacao(v) or '(nulo)'))
        mapping = self._AUDIENCE_UNIFICATION.get(col)
        if mapping:
            s = s.map(lambda v: mapping.get(v, v))
        return s

    def _query_railway_previous_full_brt_day(self) -> pd.DataFrame:
        """
        Query Railway diretamente pra pegar o último dia completo BRT
        (00:00→23:59 do dia anterior à data corrente, em horário de São Paulo).

        O df que `data_quality.check()` recebe via `orchestrator.run_daily_check`
        já passou por feature_engineering, que remove a coluna 'Data' (config
        `columns_to_drop_after_fe` em `configs/clients/{client}.yaml`). Por isso
        o check faz sua própria query — independe do estado do df transformado.

        Retorna df com colunas no formato Sheets (esperado pelo snapshot de
        referência), ou df vazio em caso de erro / sem dados / config ausente.
        """
        from datetime import datetime, timedelta, timezone
        import os

        brt = timezone(timedelta(hours=-3))
        now_brt = datetime.now(brt)
        yesterday_brt = (now_brt - timedelta(days=1)).date()
        # Janela em UTC: 00:00→23:59 BRT = 03:00 UTC do dia → 03:00 UTC do dia+1
        start_utc = datetime(yesterday_brt.year, yesterday_brt.month, yesterday_brt.day,
                             3, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(days=1)

        required_env = ['RAILWAY_DB_HOST', 'RAILWAY_DB_PORT', 'RAILWAY_DB_USER',
                        'RAILWAY_DB_PASSWORD', 'RAILWAY_DB_NAME']
        missing = [k for k in required_env if not os.environ.get(k)]
        if missing:
            logger.warning(
                f"[audience_profile_drift] Env vars Railway ausentes: {missing}. "
                f"Skip — check requer acesso direto ao banco."
            )
            return pd.DataFrame()

        try:
            import pg8000.native
            conn = pg8000.native.Connection(
                host=os.environ['RAILWAY_DB_HOST'],
                port=int(os.environ['RAILWAY_DB_PORT']),
                user=os.environ['RAILWAY_DB_USER'],
                password=os.environ['RAILWAY_DB_PASSWORD'],
                database=os.environ['RAILWAY_DB_NAME'],
                ssl_context=True,
                timeout=15,
            )
            rows = conn.run(
                'SELECT data, '
                "  pesquisa->>'genero'             AS \"O seu gênero:\", "
                "  pesquisa->>'idade'              AS \"Qual a sua idade?\", "
                "  pesquisa->>'ocupacao'           AS \"O que você faz atualmente?\", "
                "  pesquisa->>'faixaSalarial'      AS \"Atualmente, qual a sua faixa salarial?\", "
                "  pesquisa->>'cartaoCredito'      AS \"Você possui cartão de crédito?\", "
                "  pesquisa->>'estudouProgramacao' AS \"Já estudou programação?\", "
                "  pesquisa->>'computador'         AS \"Tem computador/notebook?\" "
                'FROM "Lead" '
                'WHERE "createdAt" >= :s AND "createdAt" < :e',
                s=start_utc, e=end_utc,
            )
            conn.close()
        except Exception as e:
            logger.error(f"[audience_profile_drift] Erro ao consultar Railway: {e}")
            return pd.DataFrame()

        cols = [
            'data', 'O seu gênero:', 'Qual a sua idade?', 'O que você faz atualmente?',
            'Atualmente, qual a sua faixa salarial?', 'Você possui cartão de crédito?',
            'Já estudou programação?', 'Tem computador/notebook?',
        ]
        return pd.DataFrame(rows, columns=cols)

    def _check_audience_profile_drift(self, df: pd.DataFrame) -> List[Dict]:
        """
        [T1-13] Compara o último dia completo BRT contra o snapshot de
        referência (Top 5 ROAS) carregado de
        configs/reference_audience_profiles/{client_id}.json.

        Output: 1 alerta agregado com 2 sublistas:
          - top_list:  |Δpp| ≥ top_threshold_pp     (críticos)
          - down_list: down_min_pp ≤ |Δpp| < top_threshold_pp  (menores)
          - < down_min_pp ignorado como ruído

        Severity (NÃO depende de feature crítica):
          - HIGH se top_list não-vazia
          - MEDIUM se só down_list
          - Nenhum alerta de drift se ambos vazios

        Cada item das listas leva `is_critical` como flag informativa.

        Skip que SIM gera alerta (config_missing):
          - snapshot ausente / corrompido → emite alerta MEDIUM
            audience_profile_drift_config_missing pra forçar visibilidade

        Skip silencioso (info-level):
          - df do dia anterior tem menos respostas que `min_responses`
            (raramente acontece em produção; quando acontece é evidente)

        O check é independente de modelo (pré-encoding), portanto NÃO usa
        `_iter_active_variants`.
        """
        from datetime import datetime, timezone

        alerts: List[Dict] = []
        cfg = self._thresholds.get('audience_profile_drift', {})
        top_threshold_pp = float(cfg.get('top_threshold_pp', 5.0))
        down_min_pp = float(cfg.get('down_min_pp', 2.0))
        min_responses = int(cfg.get('min_responses', 50))
        now_iso = datetime.now(timezone.utc).isoformat()

        snapshot, error = self._load_reference_audience_profile()
        if snapshot is None:
            client_id = getattr(self.client_config, 'client_id', '?') if self.client_config else '?'
            alerts.append({
                'type': 'audience_profile_drift_config_missing',
                'severity': 'MEDIUM',
                'category': 'data_quality',
                'message': (
                    f" Audience profile drift desativado para client_id={client_id}: "
                    f"{error['reason']}. Gere o snapshot via "
                    f"`python -m scripts.build_reference_audience_profile --client {client_id}`."
                ),
                'details': {
                    'client_id': client_id,
                    'reason': error['reason'],
                    'tried_paths': error.get('tried_paths', []),
                },
                'timestamp': now_iso,
                'metric_value': 0.0,
                'threshold': 0.0,
            })
            return alerts

        # NOTE: o df que chega via check() já passou por feature_engineering,
        # que remove a coluna 'Data' (columns_to_drop_after_fe). Por isso o
        # check consulta o Railway diretamente — independe do df transformado.
        df_day = self._query_railway_previous_full_brt_day()
        n_day = len(df_day)
        if n_day < min_responses:
            logger.info(
                f"[audience_profile_drift] Janela do dia anterior tem {n_day} leads "
                f"(< min_responses={min_responses}). Skip."
            )
            return alerts

        critical = set(snapshot.get('is_critical', []))
        ref_pool = snapshot.get('reference_pool', {})
        ref_label = ref_pool.get('label', 'reference')
        ref_n = ref_pool.get('n_leads', 0)

        top_list: List[Dict] = []
        down_list: List[Dict] = []
        total_responses_day = 0

        for col, ref_entry in snapshot.get('categorical_features', {}).items():
            if col not in df_day.columns:
                continue
            s = self._normalize_audience_series(df_day[col], col)
            s = s[s != '(nulo)']
            if len(s) == 0:
                continue
            total_responses_day = max(total_responses_day, int(len(s)))
            day_proportions = (s.value_counts() / len(s)).to_dict()
            ref_proportions = ref_entry.get('proportions', {})
            label = ref_entry.get('label', col)
            is_critical_feat = col in critical

            for cat in set(ref_proportions) | set(day_proportions):
                ref_p = float(ref_proportions.get(cat, 0.0))
                day_p = float(day_proportions.get(cat, 0.0))
                delta_pp = (day_p - ref_p) * 100.0
                abs_delta = abs(delta_pp)
                if abs_delta < down_min_pp:
                    continue
                item = {
                    'feature_column': col,
                    'feature_label': label,
                    'is_critical': is_critical_feat,
                    'category': cat,
                    'reference_pct': round(ref_p * 100, 1),
                    'day_pct': round(day_p * 100, 1),
                    'delta_pp': round(delta_pp, 1),
                }
                if abs_delta >= top_threshold_pp:
                    top_list.append(item)
                else:
                    down_list.append(item)

        # Sem nenhum drift relevante — não emite alerta
        if not top_list and not down_list:
            logger.info(
                f"[audience_profile_drift] Sem drift relevante em {total_responses_day} respostas/dia "
                f"(threshold {top_threshold_pp}pp / down_min {down_min_pp}pp)."
            )
            return alerts

        # Ordenar por |Δ| desc dentro de cada lista
        top_list.sort(key=lambda x: -abs(x['delta_pp']))
        down_list.sort(key=lambda x: -abs(x['delta_pp']))

        severity = 'HIGH' if top_list else 'MEDIUM'
        max_abs_delta = max(
            (abs(it['delta_pp']) for it in (top_list + down_list)),
            default=0.0
        )

        # Período comparado — explicitar no alerta (último dia completo BRT vs pool de referência)
        from datetime import timedelta as _td, timezone as _tz
        brt = _tz(_td(hours=-3))
        compared_day_brt = (datetime.now(brt) - _td(days=1)).date().isoformat()
        compared_window_label = f"{compared_day_brt} BRT (último dia completo)"

        # Mensagem compacta para Slack/dashboard
        def _fmt(items, n=5):
            head = ', '.join(
                f"{it['feature_label']}: {it['category']} — "
                f"{it['reference_pct']}%→{it['day_pct']}% ({it['delta_pp']:+.1f}pp)"
                for it in items[:n]
            )
            tail = f" (+{len(items) - n})" if len(items) > n else ''
            return head + tail

        msg_parts = []
        if top_list:
            msg_parts.append(f"TOP ({len(top_list)} ≥{top_threshold_pp}pp): {_fmt(top_list)}")
        if down_list:
            msg_parts.append(f"DOWN ({len(down_list)} {down_min_pp}–{top_threshold_pp}pp): {_fmt(down_list)}")

        alerts.append({
            'type': 'audience_profile_drift',
            'severity': severity,
            'category': 'data_quality',
            'message': (
                f" Drift de perfil — comparando {compared_window_label} (n={total_responses_day}) "
                f"vs {ref_label} (n={ref_n}). " + ' | '.join(msg_parts)
            ),
            'details': {
                'compared_window': compared_window_label,
                'compared_window_kind': 'previous_full_brt_day',
                'reference_pool_label': ref_label,
                'reference_pool_n': ref_n,
                'day_n_responses': total_responses_day,
                'top_threshold_pp': top_threshold_pp,
                'down_min_pp': down_min_pp,
                'top_list': top_list,
                'down_list': down_list,
                'top_count': len(top_list),
                'down_count': len(down_list),
            },
            'timestamp': now_iso,
            'metric_value': float(max_abs_delta),
            'threshold': top_threshold_pp,
        })

        return alerts
