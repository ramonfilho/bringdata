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
from typing import Dict, Set, List, Tuple, Optional
from pathlib import Path
from unidecode import unidecode
import re

logger = logging.getLogger(__name__)


def _pick_survey_value(survey: Dict[str, str], *keys: str) -> Optional[str]:
    """Pega o primeiro valor não-vazio em `survey` entre as chaves dadas.

    Existe pra cobrir os 2 vocabulários do `LeadRecord.survey_responses`:
      - PT-Long (ledger novo via consumer Pub/Sub): "O seu gênero:", ...
      - slug (adapter legado lendo `Lead.pesquisa`): "genero", "idade", ...

    Devolve None se nenhuma chave resolver pra valor útil. Mantém o contrato
    do DataFrame canônico (coluna pode ser NULL).
    """
    if not survey:
        return None
    for k in keys:
        v = survey.get(k)
        if v is not None and v != '':
            return v
    return None


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

    def __init__(self, model_path: str, client_config=None, db=None, expected_decil_dist=None,
                 lead_scoring_pipeline=None, repo=None):
        """
        Args:
            model_path:    Caminho para pasta do modelo ativo
            client_config: ClientConfig opcional — usado para encoding via core/,
                           carregamento do modelo correto por client_id, e
                           overrides de thresholds/missing_rate_ignore_columns
            db:            SQLAlchemy session opcional (legacy Cloud SQL). Mantido pra
                           outras queries. NÃO é usado para rolling 30d porque a tabela
                           Lead vive no Railway.
            expected_decil_dist: Dict {'D1':0.10,...,'D10':0.30} pré-computado pelo
                           caller (Railway) para servir como baseline rolling 30d. Quando
                           None, _check_score_distribution cai em fallback.
            lead_scoring_pipeline: LeadScoringPipeline opcional já inicializado (de
                           api/app.py). Usado por _check_audience_quality_signal para
                           re-scorear leads do LF atual com chain de produção.
            repo:          `LeadRepository` (injetado pelo orchestrator). Fonte canônica
                           dos leads pros 7 helpers `_query_railway_*`. Quando None,
                           esses helpers retornam DataFrames vazios silenciosamente.
                           Migrado em 2026-05-24 (Sub-etapa 5.3 do refator do
                           monitoramento).
        """
        from .config import THRESHOLDS, MISSING_RATE_IGNORE_COLUMNS
        self.model_path = model_path
        self.client_config = client_config
        self.db = db
        self.repo = repo
        self.expected_decil_dist = expected_decil_dist
        self.lead_scoring_pipeline = lead_scoring_pipeline
        monitoring = client_config.monitoring if client_config else None
        self._thresholds = (
            monitoring.thresholds if monitoring and monitoring.thresholds else THRESHOLDS
        )
        self.include_today_partial = False  # /monitoring/* flag — coluna "Hoje" no audience_drift
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
            _audience_alerts = self._check_audience_profile_drift(df)
            alerts.extend(_audience_alerts)
            # 8b. Drift de público por variante A/B (Champion vs Challenger vs Top6),
            #     uma tabela por janela (ontem + lançamento atual). Reusa o top_list
            #     do alerta principal pra falar das mesmas features.
            for _a in _audience_alerts:
                if _a.get('type') == 'audience_profile_drift':
                    _tl = (_a.get('details') or {}).get('top_list') or []
                    if _tl:
                        alerts.extend(self._check_audience_drift_by_variant(_tl))
                        alerts.extend(self._check_audience_drift_by_source(_tl))

        # 9. Audience quality signal — re-scoreia leads do LF atual com Challenger
        #    via mesma chain de produção (LeadScoringPipeline.run) e compara
        #    %D10/%D9-D10/score médio contra baseline pré-computado dos Top5
        #    ROAS realized. Captura interação multivariada que o drift de mix
        #    sozinho não pega.
        if self._thresholds.get('audience_quality_signal', {}).get('enabled', True):
            alerts.extend(self._check_audience_quality_signal())

        # 10. Outros bucket inflado — independente de drift, checa quanto cada
        #     coluna unificada (Source/Term/Medium) está caindo no bucket
        #     'outros' nas últimas 24h. Se outros > 2% do total, emite breakdown
        #     ordenado por contribuição ao bucket. Sinal informativo, não bloqueia.
        if self._thresholds.get('outros_buckets', {}).get('enabled', True):
            alerts.extend(self._check_outros_buckets())

        return alerts

    def _resolve_variant_artifacts_dir(self, predictor) -> Path | None:
        """
        Resolve a pasta de artifacts pra um predictor (Champion ou Challenger).
        Necessário pra carregar `categorias_esperadas.json` e
        `distribuicoes_esperadas.json` de cada variant.

        Estratégia:
          1. predictor.model_path se já estiver setado (Champion via active_model.yaml)
          2. glob em mlruns/*/{run_id}/artifacts/ (Challenger via mlflow_run_id)
          3. None (logado, alerta é skipado pra essa variant)
        """
        if getattr(predictor, 'model_path', None):
            p = Path(predictor.model_path)
            if p.exists():
                return p
        if getattr(predictor, 'mlflow_run_id', None):
            base = Path(__file__).resolve().parents[2] / 'mlruns'
            if base.exists():
                for exp_dir in base.iterdir():
                    if not exp_dir.is_dir():
                        continue
                    candidate = exp_dir / predictor.mlflow_run_id / 'artifacts'
                    if candidate.exists():
                        return candidate
        return None

    def _check_category_drift(self, df: pd.DataFrame) -> List[Dict]:
        """
        Verifica categorias não vistas no treino, POR VARIANT ativa.

        Cada variant tem seu próprio `categorias_esperadas.json` (capturado no
        treino correspondente), então as categorias "esperadas" diferem entre
        Champion e Challenger. Iterar sobre _iter_active_variants() garante que
        o monitoring detecta drift contra qualquer modelo servindo tráfego.

        Cada alerta carrega `variant_name` e `mlflow_run_id` pra facilitar
        filtragem downstream.
        """
        from datetime import datetime, timezone
        alerts = []

        for variant_name, predictor, _enc in self._iter_active_variants():
            artifacts_dir = self._resolve_variant_artifacts_dir(predictor)
            if artifacts_dir is None:
                logger.warning(
                    f"[category_drift] variant '{variant_name}' (run {predictor.mlflow_run_id}) — "
                    f"artifacts_dir não localizado. Skip."
                )
                continue

            try:
                categorias_esperadas = load_training_categories(str(artifacts_dir))
            except FileNotFoundError as e:
                logger.warning(f"[category_drift] variant '{variant_name}': {e}")
                continue
            except Exception as e:
                logger.error(f"[category_drift] variant '{variant_name}' erro carregando categorias: {e}")
                continue

            try:
                drift_results = check_category_drift(df, categorias_esperadas)
            except Exception as e:
                logger.error(f"[category_drift] variant '{variant_name}' erro check: {e}")
                continue

            for result in drift_results:
                alerts.append({
                    'type': 'category_drift',
                    'severity': result['severity'],
                    'category': 'data_quality',
                    'message': f"[{variant_name}]{result['message']}",
                    'details': {
                        'variant_name': variant_name,
                        'mlflow_run_id': getattr(predictor, 'mlflow_run_id', None),
                        'column': result['column'],
                        'new_categories': result.get('new_categories', []),
                        'affected_count': result.get('count', 0),
                        'percentage': result.get('percentage', 0),
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': result.get('percentage', 0),
                    'threshold': None,
                })

        return alerts

    @staticmethod
    def _normalize_for_silence_match(s) -> str:
        """Normaliza categoria pra comparação case+accent-insensitive contra
        silenced_drift_changes. Delega pro mesmo normalizador canônico usado
        em `check_distribution_drift` (`normalizar_categoria_para_comparacao`)
        — lower + unidecode + strip pontuação + collapse whitespace. Garante
        que o que sai da silenced list cas a com o `categoria` que vai no payload.
        """
        if s is None:
            return ''
        return normalizar_categoria_para_comparacao(str(s)) or ''

    def _silenced_changes_for_column(self, column: str) -> Set[str]:
        """Retorna set de categorias (normalizadas) marcadas como silenciadas
        no client_config.monitoring.silenced_drift_changes para a coluna dada.
        Cache implícito via lookup linear — a lista é pequena (<20 entradas).
        """
        if not (self.client_config and self.client_config.monitoring):
            return set()
        items = getattr(self.client_config.monitoring, 'silenced_drift_changes', None) or []
        out: Set[str] = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            if (it.get('column') or '') != column:
                continue
            cat_norm = self._normalize_for_silence_match(it.get('categoria', ''))
            if cat_norm:
                out.add(cat_norm)
        return out

    def _check_distribution_drift(self, df: pd.DataFrame) -> List[Dict]:
        """
        Verifica mudanças drásticas nas proporções, POR VARIANT ativa.

        Mesmo padrão do _check_category_drift: cada variant tem suas
        `distribuicoes_esperadas.json` (proporções de cada categoria no treino),
        então a baseline contra a qual o drift é medido difere entre Champion
        e Challenger.

        Cada alerta carrega `variant_name` e `mlflow_run_id`.
        """
        from datetime import datetime, timezone
        alerts = []
        threshold_cat = self._thresholds['distribution_drift']['categorical']
        threshold_num = self._thresholds['distribution_drift']['numerical']

        for variant_name, predictor, _enc in self._iter_active_variants():
            artifacts_dir = self._resolve_variant_artifacts_dir(predictor)
            if artifacts_dir is None:
                logger.warning(
                    f"[distribution_drift] variant '{variant_name}' (run {predictor.mlflow_run_id}) — "
                    f"artifacts_dir não localizado. Skip."
                )
                continue

            try:
                distribuicoes_esperadas = load_training_distributions(str(artifacts_dir))
            except FileNotFoundError as e:
                logger.warning(f"[distribution_drift] variant '{variant_name}': {e}")
                continue
            except Exception as e:
                logger.error(f"[distribution_drift] variant '{variant_name}' erro carregando distribs: {e}")
                continue

            try:
                drift_results = check_distribution_drift(
                    df, distribuicoes_esperadas,
                    threshold_categorical=threshold_cat,
                    threshold_numerical=threshold_num,
                )
            except Exception as e:
                logger.error(f"[distribution_drift] variant '{variant_name}' erro check: {e}")
                continue

            for result in drift_results:
                drift_type = result['type']
                if drift_type == 'categorical_distribution_drift':
                    column = result['column']
                    changes = result['changes']

                    # Filtrar drifts conhecidos e estáveis (silenced_drift_changes
                    # do client_config.monitoring). Cada item da lista define
                    # (column, categoria) a silenciar — match case+accent-insensitive.
                    # Se todas as mudanças desta (coluna, variante) caírem na lista,
                    # o alerta inteiro é dropado silenciosamente (sem log).
                    n_silenced = 0
                    silenced_list = self._silenced_changes_for_column(column)
                    if silenced_list and changes:
                        kept = []
                        for c in changes:
                            cat_norm = self._normalize_for_silence_match(c.get('categoria', ''))
                            if cat_norm in silenced_list:
                                n_silenced += 1
                                continue
                            kept.append(c)
                        changes = kept
                    if not changes:
                        continue  # alerta inteiro silenciado — não emite

                    # Enriquecer changes que são 'outros' com breakdown raw
                    has_outros = any(c.get('categoria') == 'outros' for c in changes)
                    if has_outros and column in ('Source', 'Term', 'Medium'):
                        try:
                            outros_breakdown = self._query_railway_outros_breakdown(column)
                        except Exception as _e:
                            logger.warning(f"[distribution_drift] outros_breakdown falhou para {column}: {_e}")
                            outros_breakdown = []
                        for c in changes:
                            if c.get('categoria') == 'outros':
                                c['outros_breakdown'] = outros_breakdown
                    details = {
                        'variant_name': variant_name,
                        'mlflow_run_id': getattr(predictor, 'mlflow_run_id', None),
                        'column': column,
                        'changes': changes,
                    }
                    if n_silenced > 0:
                        details['n_silenced'] = n_silenced
                    metric_value = changes[0]['diff'] if changes else 0
                    threshold_used = threshold_cat
                else:
                    details = {
                        'variant_name': variant_name,
                        'mlflow_run_id': getattr(predictor, 'mlflow_run_id', None),
                        'column': result['column'],
                        'mean_treino': result['mean_treino'],
                        'mean_producao': result['mean_producao'],
                        'std_treino': result['std_treino'],
                        'std_producao': result['std_producao'],
                        'sigma_diff': result['sigma_diff'],
                    }
                    metric_value = result['sigma_diff']
                    threshold_used = threshold_num

                alerts.append({
                    'type': 'distribution_drift',
                    'severity': result['severity'],
                    'category': 'data_quality',
                    'message': f"[{variant_name}]{result['message']}",
                    'details': details,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': metric_value,
                    'threshold': threshold_used,
                })

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

    def _load_direction_map(self):
        """Carrega configs/audience_direction_map.json. Retorna {} se ausente
        (degradação graceful: sem direction map, drift fica sem classificação
        bom/ruim — só marca 'unknown'). Ver docs/METODOLOGIA_TOP5_ROAS.md."""
        candidates = [
            Path('configs/audience_direction_map.json'),
            Path(__file__).resolve().parents[2] / 'configs' / 'audience_direction_map.json',
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f).get('direction_map', {})
        except Exception as e:
            logger.warning(f"[audience_direction_map] Erro ao carregar: {e}")
            return {}

    def _classify_drift_quality(self, direction: str, delta_pp: float) -> str:
        """Combina direção da categoria (do direction_map) com sinal do Δpp
        pra retornar quality ∈ {'bom', 'ruim', 'neutro', 'unknown'}.

        Regras:
          Δpp +  &  positive/very_positive   → bom
          Δpp +  &  negative/very_negative   → ruim
          Δpp −  &  negative/very_negative   → bom (faltar gente ruim = bom)
          Δpp −  &  positive/very_positive   → ruim (faltar gente boa = ruim)
          neutral/uncertain/insufficient     → neutro
        """
        if delta_pp is None or direction in (None, 'neutral', 'uncertain', 'insufficient_data'):
            return 'neutro'
        positive = direction in ('positive', 'very_positive')
        negative = direction in ('negative', 'very_negative')
        if delta_pp > 0 and positive:
            return 'bom'
        if delta_pp > 0 and negative:
            return 'ruim'
        if delta_pp < 0 and negative:
            return 'bom'
        if delta_pp < 0 and positive:
            return 'ruim'
        return 'neutro'

    def _normalize_audience_series(self, s: pd.Series, col: str) -> pd.Series:
        """Normaliza categoria + aplica mapeamento canônico para a coluna."""
        s = s.fillna('(nulo)').astype(str).str.strip()
        s = s.replace({'': '(nulo)', 'None': '(nulo)', 'nan': '(nulo)'})
        s = s.apply(lambda v: '(nulo)' if v == '(nulo)' else (normalizar_categoria_para_comparacao(v) or '(nulo)'))
        mapping = self._AUDIENCE_UNIFICATION.get(col)
        if mapping:
            s = s.map(lambda v: mapping.get(v, v))
        return s

    def _railway_pesquisa_columns_select(self) -> str:
        """SQL fragment com SELECT da pesquisa em formato canônico (mesmas colunas do snapshot).

        Inclui UTMs e pageUrl pra suporte a split por variante A/B (match_variant).
        """
        return (
            'SELECT data, '
            "  pesquisa->>'genero'             AS \"O seu gênero:\", "
            "  pesquisa->>'idade'              AS \"Qual a sua idade?\", "
            "  pesquisa->>'ocupacao'           AS \"O que você faz atualmente?\", "
            "  pesquisa->>'faixaSalarial'      AS \"Atualmente, qual a sua faixa salarial?\", "
            "  pesquisa->>'cartaoCredito'      AS \"Você possui cartão de crédito?\", "
            "  pesquisa->>'estudouProgramacao' AS \"Já estudou programação?\", "
            "  pesquisa->>'computador'         AS \"Tem computador/notebook?\", "
            '  source, medium, campaign, content, term, "pageUrl" '
            'FROM "Lead" '
            'WHERE "createdAt" >= :s AND "createdAt" < :e'
        )

    def _railway_pesquisa_columns(self) -> List[str]:
        return [
            'data', 'O seu gênero:', 'Qual a sua idade?', 'O que você faz atualmente?',
            'Atualmente, qual a sua faixa salarial?', 'Você possui cartão de crédito?',
            'Já estudou programação?', 'Tem computador/notebook?',
            'source', 'medium', 'campaign', 'content', 'term', 'pageUrl',
        ]

    def _query_railway_pesquisa_window(self, start_utc, end_utc) -> pd.DataFrame:
        """
        Devolve leads numa janela arbitrária [start_utc, end_utc) no formato
        DataFrame canônico (mesmas colunas de `_railway_pesquisa_columns()`).

        Migrado em 2026-05-24 para usar `self.repo` em vez de abrir conexão
        Railway própria. Quando `self.repo` é None ou o range é inválido,
        retorna DataFrame vazio silenciosamente.

        Origem das respostas:
          - Ledger novo (`registros_ml.survey_responses`): chaves em PT-Long.
          - Adaptador legado (`Lead.pesquisa`): chaves em slug.
          `_records_to_pesquisa_df` cobre os dois formatos via fallback de chave.
        """
        if self.repo is None:
            return pd.DataFrame(columns=self._railway_pesquisa_columns())
        try:
            records = self.repo.leads_in_range(start_utc, end_utc)
        except Exception as e:
            logger.error(f"[audience_profile_drift] Erro ao consultar repo: {e}")
            return pd.DataFrame(columns=self._railway_pesquisa_columns())
        return self._records_to_pesquisa_df(records)

    def _records_to_pesquisa_df(self, records) -> pd.DataFrame:
        """Converte `List[LeadRecord]` no DataFrame canônico de pesquisa.

        Cobre chaves PT-Long (ledger novo) e slug (adaptador legado) via
        `_pick_survey_value`. Valores ausentes viram `None`.
        """
        rows = []
        for r in records:
            s = r.survey_responses or {}
            rows.append({
                'data': r.criado_em,
                'O seu gênero:':                       _pick_survey_value(s, 'O seu gênero:', 'genero'),
                'Qual a sua idade?':                   _pick_survey_value(s, 'Qual a sua idade?', 'idade'),
                'O que você faz atualmente?':          _pick_survey_value(s, 'O que você faz atualmente?', 'ocupacao'),
                'Atualmente, qual a sua faixa salarial?': _pick_survey_value(s, 'Atualmente, qual a sua faixa salarial?', 'faixaSalarial'),
                'Você possui cartão de crédito?':      _pick_survey_value(s, 'Você possui cartão de crédito?', 'cartaoCredito'),
                'Já estudou programação?':             _pick_survey_value(s, 'Já estudou programação?', 'estudouProgramacao'),
                # `has_computer` vive em coluna top-level no ledger novo (não
                # dentro de `survey_responses`, que é o vocabulário do Pub/Sub).
                # Fallback pra survey cobre o adaptador legado, que ainda tem
                # `computador` dentro de pesquisa.
                'Tem computador/notebook?':            (r.has_computer if r.has_computer else _pick_survey_value(s, 'Tem computador/notebook?', 'computador')),
                'source':   r.utm_source,
                'medium':   r.utm_medium,
                'campaign': r.utm_campaign,
                'content':  r.utm_content,
                'term':     r.utm_term,
                'pageUrl':  r.utm_url,
            })
        return pd.DataFrame(rows, columns=self._railway_pesquisa_columns())

    def _query_railway_previous_full_brt_day(self, anchor_date=None) -> pd.DataFrame:
        """
        Janela: 00:00→23:59 BRT do dia anterior. Usa _query_railway_pesquisa_window.

        `anchor_date` permite simular outro "hoje" — útil pra dashboards que
        consultam o estado histórico do drift. Quando None, usa hoje BRT.
        """
        from datetime import datetime, timedelta, timezone
        brt = timezone(timedelta(hours=-3))
        today_brt = anchor_date if anchor_date is not None else datetime.now(brt).date()
        yesterday_brt = today_brt - timedelta(days=1)
        start_utc = datetime(yesterday_brt.year, yesterday_brt.month, yesterday_brt.day,
                             3, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(days=1)
        return self._query_railway_pesquisa_window(start_utc, end_utc)

    def _query_railway_two_full_brt_days_ago(self, anchor_date=None) -> pd.DataFrame:
        """
        Janela: 00:00→23:59 BRT de anteontem (D-2). Usa _query_railway_pesquisa_window.

        `anchor_date` permite simular outro "hoje" — D-2 fica relativo a ele.
        """
        from datetime import datetime, timedelta, timezone
        brt = timezone(timedelta(hours=-3))
        today_brt = anchor_date if anchor_date is not None else datetime.now(brt).date()
        prev_brt = today_brt - timedelta(days=2)
        start_utc = datetime(prev_brt.year, prev_brt.month, prev_brt.day,
                             3, 0, 0, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(days=1)
        return self._query_railway_pesquisa_window(start_utc, end_utc)

    def _query_railway_outros_breakdown(self, column: str, hours: int = 24, top_n: int = 8) -> List[Dict]:
        """
        Pra Source/Term/Medium: consulta o Railway nas últimas `hours` horas
        com os valores RAW da coluna correspondente, aplica `unify_utm` ou
        `unify_medium` (mesma rotina canônica) e devolve a lista dos raw_values
        que viram 'outros' após unify, agrupados por valor (top_n maiores).

        Output: [{'raw_value': str, 'count': int}, ...] — sem categorização,
        sem interpretação. Cliente decide o que mostrar.

        Mantido com assinatura antiga pra não quebrar o caller em
        _check_distribution_drift. Quem quiser totais/percentuais usa
        `_query_railway_outros_breakdown_enriched`.

        Skip silencioso (devolve []) se:
          - column não é Source/Term/Medium
          - env vars Railway ausentes
          - client_config sem utm/medium config
          - erro de query
        """
        result = self._query_railway_outros_breakdown_enriched(column, hours=hours, top_n=top_n)
        if not result:
            return []
        return [{'raw_value': it['raw_value'], 'count': it['count']}
                for it in result.get('breakdown', [])]

    def _query_railway_outros_breakdown_enriched(self, column: str, hours: int = 24,
                                                  top_n: int = 8,
                                                  restrict_to_sources: List[str] | None = None) -> Dict:
        """
        Versão enriquecida do breakdown. Retorna dict com:
          - 'column'
          - 'total_count'           — leads na janela com a coluna não-nula
          - 'outros_count'          — leads que caíram em 'outros' após unify
          - 'outros_pct_of_total'   — outros_count / total_count
          - 'breakdown'             — lista de dicts:
              {'raw_value': str, 'count': int, 'pct_total': float}
            ordenada por count desc, limitada a top_n.
          - 'window_hours'
          - 'restrict_to_sources'   — eco do filtro aplicado (ou None)

        Param `restrict_to_sources` filtra os leads ANTES da contagem por valor
        do Source canônico (pós-unify). Usado pra Term, onde leads não-Meta
        legitimamente caem em 'outros' (Google Ads passa IDs no term, etc.).
        Restringindo a `['facebook-ads']`, o alerta foca em misconfig real do
        Meta (placeholders `{{...}}`, etc.) e ignora ruído estrutural.

        Retorna dict vazio {} em qualquer falha (env, config, query, etc.).
        """
        import os
        from datetime import datetime, timedelta, timezone

        if column not in ('Source', 'Term', 'Medium'):
            return {}
        if not (self.client_config and (self.client_config.utm or self.client_config.medium)):
            return {}

        if self.repo is None:
            return {}

        end_utc = datetime.now(timezone.utc)
        start_utc = end_utc - timedelta(hours=hours)

        # Migrado em 2026-05-24: usa `self.repo` em vez de abrir conn própria.
        # Fonte hoje: ledger novo (`registros_ml`) via RegistrosMLAdapter.
        try:
            records = self.repo.leads_in_range(start_utc, end_utc)
        except Exception as e:
            logger.error(f"[outros_breakdown] {column} erro repo: {e}")
            return {}

        if not records:
            return {}

        df_raw = pd.DataFrame(
            [{'Source': r.utm_source, 'Term': r.utm_term, 'Medium': r.utm_medium}
             for r in records],
            columns=['Source', 'Term', 'Medium'],
        )
        df_unified = df_raw.copy()

        # Aplicar unify canônico — mesma rotina do orchestrator/produção
        try:
            if column in ('Source', 'Term') and self.client_config.utm:
                from core.utm import unify_utm
                df_unified = unify_utm(df_unified, self.client_config.utm)
            elif column == 'Medium' and self.client_config.medium:
                from core.medium import unify_medium
                df_unified = unify_medium(df_unified, self.client_config.medium)
        except Exception as e:
            logger.error(f"[outros_breakdown] {column} erro unify: {e}")
            return {}

        if column not in df_unified.columns:
            return {}

        # Filtro de Source: aplica antes de tudo. Necessário pro Term porque
        # leads não-Meta (Google passa IDs no term, etc.) caem em 'outros' por
        # design — não é misconfig. Restringir a Meta foca o alerta no que
        # realmente importa.
        if restrict_to_sources:
            if 'Source' not in df_unified.columns:
                return {}
            keep_mask = df_unified['Source'].isin(restrict_to_sources)
            df_raw = df_raw.loc[keep_mask].reset_index(drop=True)
            df_unified = df_unified.loc[keep_mask].reset_index(drop=True)

        # Total da coluna na janela = leads com valor não-nulo no raw
        # (alinha com a definição de "% do volume" do usuário).
        total_count = int(df_raw[column].notna().sum())
        if total_count == 0:
            return {}

        mask = df_unified[column] == 'outros'
        outros_count = int(mask.sum())
        outros_pct_of_total = (outros_count / total_count) if total_count > 0 else 0.0

        breakdown: List[Dict] = []
        if outros_count > 0:
            raw_values = df_raw.loc[mask, column].fillna('(vazio)').astype(str)
            # Case-fold pra agrupamento estável (Sheets vs banco podem variar)
            counts = raw_values.str.lower().value_counts().head(top_n)
            breakdown = [
                {'raw_value': v, 'count': int(n),
                 'pct_total': float(n) / total_count}
                for v, n in counts.items()
            ]

        return {
            'column': column,
            'total_count': total_count,
            'outros_count': outros_count,
            'outros_pct_of_total': outros_pct_of_total,
            'breakdown': breakdown,
            'window_hours': hours,
            'restrict_to_sources': list(restrict_to_sources) if restrict_to_sources else None,
        }

    def _check_outros_buckets(self) -> List[Dict]:
        """
        Independente do `categorical_distribution_drift`: pra cada coluna
        monitorada (Source, Term, Medium), checa o tamanho do bucket 'outros'
        na janela de 24h. Se outros_count / total_count > min_pct_threshold,
        emite alerta `outros_bucket_inflated` com o breakdown raw_value→count
        ordenado por contribuição ao bucket Outros.

        Configurável via self._thresholds['outros_buckets']:
          - 'enabled'            (bool, default True)
          - 'min_pct_threshold'  (float, default 0.02 — emite quando >2%)
          - 'window_hours'       (int, default 24)
          - 'top_n'              (int, default 8 — top raw_values do breakdown)
          - 'columns'            (list, default ['Source','Term','Medium'])
          - 'restrict_to_sources_by_column' (dict, default {'Term': ['facebook-ads']})
            Por que: Term só faz sentido como sub-source no Meta (IG vs FB);
            Google/TikTok/YouTube colocando IDs/strings no term cai em 'outros'
            por design, não é misconfig. Restringir Term a `['facebook-ads']`
            mantém o alerta sensível ao que importa (placeholders `{{...}}`,
            criativos Meta mal-tageados) e ignora o ruído estrutural.

        Severity:
          - LOW se outros_pct < 5%
          - MEDIUM se outros_pct >= 5%
          (não bloqueia pipeline; é sinal informativo)
        """
        from datetime import datetime, timezone

        cfg = self._thresholds.get('outros_buckets', {}) if hasattr(self, '_thresholds') else {}
        min_pct = float(cfg.get('min_pct_threshold', 0.02))
        hours = int(cfg.get('window_hours', 24))
        top_n = int(cfg.get('top_n', 8))
        columns = cfg.get('columns', ['Source', 'Term', 'Medium'])
        restrict_map = cfg.get('restrict_to_sources_by_column',
                                {'Term': ['facebook-ads']})

        alerts: List[Dict] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for column in columns:
            restrict = restrict_map.get(column)
            data = self._query_railway_outros_breakdown_enriched(
                column, hours=hours, top_n=top_n, restrict_to_sources=restrict
            )
            if not data:
                continue
            pct = float(data.get('outros_pct_of_total', 0.0))
            if pct <= min_pct:
                continue

            severity = 'MEDIUM' if pct >= 0.05 else 'LOW'
            alerts.append({
                'type': 'outros_bucket_inflated',
                'severity': severity,
                'category': 'data_quality',
                'message': (
                    f"Bucket 'outros' inflado em {column}: "
                    f"{data.get('outros_count', 0)}/{data.get('total_count', 0)} "
                    f"({pct*100:.1f}% do total) — janela {data.get('window_hours', hours)}h"
                ),
                'details': {
                    'column': column,
                    'window_hours': data.get('window_hours', hours),
                    'total_count': data.get('total_count', 0),
                    'outros_count': data.get('outros_count', 0),
                    'outros_pct_of_total': pct,
                    'min_pct_threshold': min_pct,
                    'restrict_to_sources': data.get('restrict_to_sources'),
                    'breakdown': data.get('breakdown', []),
                },
                'metric_value': pct,
                'threshold': min_pct,
                'timestamp': now_iso,
                'column': column,
                'window_hours': data.get('window_hours', hours),
                'total_count': data.get('total_count', 0),
                'outros_count': data.get('outros_count', 0),
                'outros_pct_of_total': pct,
                'min_pct_threshold': min_pct,
                'restrict_to_sources': data.get('restrict_to_sources'),
                'breakdown': data.get('breakdown', []),
                'timestamp_utc': now_iso,
            })

        return alerts

    def _query_railway_today_partial_brt(self) -> tuple[pd.DataFrame, str]:
        """
        Janela: 00:00 BRT de hoje até agora. Retorna (df, label_humano da janela).
        Label inclui horário pra deixar claro que é parcial.
        """
        from datetime import datetime, timedelta, timezone
        brt = timezone(timedelta(hours=-3))
        now_brt = datetime.now(brt)
        today_brt = now_brt.date()
        start_utc = datetime(today_brt.year, today_brt.month, today_brt.day,
                             3, 0, 0, tzinfo=timezone.utc)
        end_utc = now_brt.astimezone(timezone.utc)
        df = self._query_railway_pesquisa_window(start_utc, end_utc)
        label = f"{today_brt.isoformat()} BRT 00:00→{now_brt.strftime('%H:%M')} (parcial)"
        return df, label

    def _resolve_current_launch_brt(self):
        """
        Wrapper de compatibilidade pra `src.core.launches.resolve_active_launch_brt`.

        Retorna (lf_name, cap_start_str, cap_end_str) do LF cujo período de
        captação inclui hoje BRT, ou None se não houver. **Não** cai em fallback
        ao último encerrado por design — usa `core.launches.resolve_launch_window_brt`
        quando precisar de uma janela garantida.
        """
        from src.core.launches import resolve_active_launch_brt
        active = resolve_active_launch_brt()
        if active is None:
            return None
        return (active.name, active.cap_start.isoformat(), active.cap_end.isoformat())

    def _query_railway_current_launch_brt(self, anchor_date=None) -> tuple[pd.DataFrame, Dict]:
        """
        Janela do "lançamento atual" via `src.core.launches.resolve_launch_window_brt`:

          1. LF do YAML com `cap_start ≤ hoje ≤ cap_end` → janela cap_start → now
             (se em captação) ou cap_start → cap_end (se já encerrado mas o LF
             ainda é o ativo no YAML, caso improvável).
          2. Fallback explícito: heurística "desde a última terça BRT" → terça → now,
             com label sinalizando que o YAML está desatualizado.

        Por design **não cai mais** no último LF encerrado — esse fallback
        escondia gap no `launches.yaml` (bug detectado em 13/05/2026: LF54
        aparecia rotulado como atual porque LF55 não estava cadastrado).

        `anchor_date` permite resolver o LF ativo em outro dia (útil pra
        dashboards mostrarem o estado do drift num dia passado).

        Retorna (df, info dict com lf_name/label/cap_start/cap_end/source/error).
        """
        from datetime import datetime, timedelta, timezone
        from src.core.launches import resolve_launch_window_brt, BRT

        info: Dict = {
            'lf_name': None, 'label': None,
            'cap_start': None, 'cap_end': None,
            'source': None, 'error': None,
        }

        window = resolve_launch_window_brt(today=anchor_date)
        info['lf_name'] = window.lf_name
        info['cap_start'] = window.cap_start.isoformat()
        info['cap_end'] = window.cap_end.isoformat() if window.cap_end else None
        info['source'] = window.source
        info['label'] = window.label

        # cap_start 00:00 BRT → UTC
        start_utc = datetime(window.cap_start.year, window.cap_start.month, window.cap_start.day,
                             0, 0, 0, tzinfo=BRT).astimezone(timezone.utc)

        today_brt = anchor_date if anchor_date is not None else datetime.now(BRT).date()
        if window.cap_end is not None and window.cap_end < today_brt:
            # cap_end 23:59:59 BRT → UTC
            end_utc = datetime(window.cap_end.year, window.cap_end.month, window.cap_end.day,
                               23, 59, 59, tzinfo=BRT).astimezone(timezone.utc)
        elif anchor_date is not None:
            # anchor histórico em captação ainda corrente — fim do anchor BRT
            end_utc = datetime(anchor_date.year, anchor_date.month, anchor_date.day,
                               23, 59, 59, tzinfo=BRT).astimezone(timezone.utc)
        else:
            # captação em curso (ou fallback de terça): janela até agora
            end_utc = datetime.now(timezone.utc)

        df = self._query_railway_pesquisa_window(start_utc, end_utc)
        return df, info

    def _check_audience_profile_drift(self, df: pd.DataFrame, *, raw: bool = False,
                                       anchor_date=None) -> List[Dict]:
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
        df_day = self._query_railway_previous_full_brt_day(anchor_date=anchor_date)
        n_day = len(df_day)
        if n_day < min_responses:
            logger.info(
                f"[audience_profile_drift] Janela do dia anterior tem {n_day} leads "
                f"(< min_responses={min_responses}). Skip."
            )
            return alerts

        # Anteontem completo (D-2 00:00→23:59 BRT) — coluna adicional pra cada categoria.
        # Sempre puxa: dois dias completos lado a lado dão tendência sem oscilação de sample size.
        df_prev_day = self._query_railway_two_full_brt_days_ago(anchor_date=anchor_date)
        n_prev_day = len(df_prev_day)

        # Hoje parcial (00:00 BRT → agora) — opt-in via self.include_today_partial.
        # Default OFF: o cron das 6 AM caía com sample insignificante (~6h madrugada);
        # chamadas manuais (ex: às 14h) podem ligar com ?include_today_partial=true.
        # Quando `anchor_date` está setado, today_partial NÃO é computado — não
        # faz sentido "hoje parcial" pra uma data histórica.
        if self.include_today_partial and anchor_date is None:
            df_today, today_window_label = self._query_railway_today_partial_brt()
            n_today = len(df_today)
        else:
            import pandas as _pd
            df_today, today_window_label = _pd.DataFrame(), ''
            n_today = 0

        # Lançamento atual (cap_start → agora). Pode estar vazio se não houver
        # lançamento ativo no launches.yaml (info['error'] == 'no_active_launch').
        df_launch, launch_info = self._query_railway_current_launch_brt(anchor_date=anchor_date)
        n_launch = len(df_launch)

        critical = set(snapshot.get('is_critical', []))
        ref_pool = snapshot.get('reference_pool', {})
        ref_label = ref_pool.get('label', 'reference')
        ref_n = ref_pool.get('n_leads', 0)

        # Direction map (bom/ruim por categoria) — carrega 1x.
        # Sem map, classify_drift_quality retorna 'unknown' / 'neutro'.
        direction_map = self._load_direction_map()

        top_list: List[Dict] = []
        total_responses_day = 0
        total_responses_prev_day = 0
        total_responses_today = 0
        total_responses_launch = 0

        for col, ref_entry in snapshot.get('categorical_features', {}).items():
            if col not in df_day.columns:
                continue
            # Proporções ontem (full)
            s_day = self._normalize_audience_series(df_day[col], col)
            s_day = s_day[s_day != '(nulo)']
            if len(s_day) == 0:
                continue
            total_responses_day = max(total_responses_day, int(len(s_day)))
            day_proportions = (s_day.value_counts() / len(s_day)).to_dict()

            # Proporções anteontem (full D-2). Pode estar vazia se DB ainda não tinha leads.
            prev_day_proportions = {}
            if n_prev_day > 0 and col in df_prev_day.columns:
                s_prev = self._normalize_audience_series(df_prev_day[col], col)
                s_prev = s_prev[s_prev != '(nulo)']
                if len(s_prev) > 0:
                    total_responses_prev_day = max(total_responses_prev_day, int(len(s_prev)))
                    prev_day_proportions = (s_prev.value_counts() / len(s_prev)).to_dict()

            # Proporções hoje (partial). Pode estar vazia (default OFF, ou se ninguém respondeu).
            today_proportions = {}
            if n_today > 0 and col in df_today.columns:
                s_today = self._normalize_audience_series(df_today[col], col)
                s_today = s_today[s_today != '(nulo)']
                if len(s_today) > 0:
                    total_responses_today = max(total_responses_today, int(len(s_today)))
                    today_proportions = (s_today.value_counts() / len(s_today)).to_dict()

            # Proporções lançamento atual desde cap_start. Pode estar vazia.
            launch_proportions = {}
            if n_launch > 0 and col in df_launch.columns:
                s_launch = self._normalize_audience_series(df_launch[col], col)
                s_launch = s_launch[s_launch != '(nulo)']
                if len(s_launch) > 0:
                    total_responses_launch = max(total_responses_launch, int(len(s_launch)))
                    launch_proportions = (s_launch.value_counts() / len(s_launch)).to_dict()

            ref_proportions = ref_entry.get('proportions', {})
            label = ref_entry.get('label', col)
            is_critical_feat = col in critical

            cats = set(ref_proportions) | set(day_proportions) | set(prev_day_proportions) | set(launch_proportions)
            for cat in cats:
                ref_p = float(ref_proportions.get(cat, 0.0))
                day_p = float(day_proportions.get(cat, 0.0))
                delta_pp = (day_p - ref_p) * 100.0

                # Lançamento atual desde cap_start
                if launch_proportions:
                    launch_p = float(launch_proportions.get(cat, 0.0))
                    launch_delta = (launch_p - ref_p) * 100.0
                    launch_pct = round(launch_p * 100, 1)
                    launch_delta_pp = round(launch_delta, 1)
                else:
                    launch_pct = None
                    launch_delta_pp = None

                # Anteontem (D-2 full) — coluna adicional pra tendência ontem×anteontem.
                # NÃO entra como gatilho (mesma lógica do ontem — só uma das duas dispara).
                if prev_day_proportions:
                    prev_day_p = float(prev_day_proportions.get(cat, 0.0))
                    prev_day_delta = (prev_day_p - ref_p) * 100.0
                    prev_day_pct = round(prev_day_p * 100, 1)
                    prev_day_delta_pp = round(prev_day_delta, 1)
                else:
                    prev_day_pct = None
                    prev_day_delta_pp = None

                # Hoje parcial — pode não ter dado pra essa categoria.
                # Hoje NÃO entra como gatilho (amostra parcial pode oscilar muito
                # de manhã); fica só como enriquecimento na tabela.
                if today_proportions:
                    today_p = float(today_proportions.get(cat, 0.0))
                    today_delta = (today_p - ref_p) * 100.0
                    today_pct = round(today_p * 100, 1)
                    today_delta_pp = round(today_delta, 1)
                else:
                    today_pct = None
                    today_delta_pp = None

                # Gatilho: max(|day_Δ|, |launch_Δ|) >= top_threshold_pp.
                # Anteontem/Hoje ficam de fora pra evitar duplicidade de trigger.
                # Modo `raw=True` (endpoint dashboard) ignora o filtro e devolve
                # todas as categorias — quem consome decide o corte.
                if not raw:
                    trigger_deltas = [abs(delta_pp)]
                    if launch_delta_pp is not None:
                        trigger_deltas.append(abs(launch_delta_pp))
                    if max(trigger_deltas) < top_threshold_pp:
                        continue

                # Direção da categoria + quality (bom/ruim) pra cada janela
                # comparada. Usa direction_map (Top 5 ROAS atribuível 60d).
                direction = (direction_map.get(col, {}).get(cat, {}) or {}).get('direction')
                quality_day = self._classify_drift_quality(direction, delta_pp)
                quality_launch = (
                    self._classify_drift_quality(direction, launch_delta_pp)
                    if launch_delta_pp is not None else None
                )

                top_list.append({
                    'feature_column': col,
                    'feature_label': label,
                    'is_critical': is_critical_feat,
                    'category': cat,
                    'reference_pct': round(ref_p * 100, 1),
                    'launch_pct': launch_pct,
                    'launch_delta_pp': launch_delta_pp,
                    'launch_quality': quality_launch,
                    'prev_day_pct': prev_day_pct,
                    'prev_day_delta_pp': prev_day_delta_pp,
                    'day_pct': round(day_p * 100, 1),
                    'delta_pp': round(delta_pp, 1),
                    'day_quality': quality_day,
                    'today_pct': today_pct,
                    'today_delta_pp': today_delta_pp,
                    'direction': direction,
                })

        if not top_list:
            logger.info(
                f"[audience_profile_drift] Sem drift relevante em {total_responses_day} respostas/dia "
                f"(threshold {top_threshold_pp}pp)."
            )
            return alerts

        # Dedup binárias: pra cada feature do snapshot com exatamente 2 categorias
        # (Sim/Não, Masculino/Feminino), Sim e Não são informação redundante
        # (somam 100% — uma é o complemento da outra).
        #
        # Critério de escolha (cientificamente correto): manter a categoria com
        # direction MAIS INFORMATIVA — ou seja, aquela cujo lift histórico está
        # mais distante de 1.0 (sinal estatístico real). A categoria complementar
        # tipicamente tem lift próximo de 1.0 (= "comportamento médio" da base) e
        # direction `uncertain`, o que faria a cor virar ⚪ apesar do impacto real
        # ser claro pela contraparte.
        #
        # Exemplo: 'Tem computador/notebook?' — "Não" tem lift=0.29 (very_negative),
        # "Sim" tem lift=1.11 (uncertain, CI cruza 1.0). Quando "Não" sobe 11pp =
        # "Sim" desce 11pp (mesmo evento), o critério antigo (maior |Δpp| com
        # tie-break arbitrário) podia mostrar qualquer um. Agora prefere "Não" →
        # cor reflete o sinal real (subiu população de baixo lift = ruim).
        #
        # Ordenação por (direction_rank desc, |lift-1.0| desc):
        #   3 = very_negative / very_positive (sinal forte)
        #   2 = negative / positive (sinal moderado)
        #   1 = uncertain (CI cruza 1.0)
        #   0 = insufficient_data / None
        _DIR_RANK = {
            'very_negative': 3, 'very_positive': 3,
            'negative': 2, 'positive': 2,
            'uncertain': 1, 'insufficient_data': 0,
        }
        def _informativeness_key(it):
            col_ = it.get('feature_column')
            cat_ = it.get('category')
            entry = (direction_map.get(col_, {}) or {}).get(cat_, {}) or {}
            d_rank = _DIR_RANK.get(entry.get('direction'), -1)
            lift = entry.get('lift')
            lift_dist = abs(float(lift) - 1.0) if lift is not None else -1.0
            return (-d_rank, -lift_dist, -abs(it.get('delta_pp') or 0))

        _binary_features = {
            col for col, entry in snapshot.get('categorical_features', {}).items()
            if len((entry.get('proportions') or {})) == 2
        }
        # Modo `raw=True` mantém Sim e Não juntos — dashboard quer ver as duas
        # categorias mesmo sendo complementares.
        if _binary_features and not raw:
            _by_feature_col: dict[str, list] = {}
            for _it in top_list:
                _by_feature_col.setdefault(_it.get('feature_column'), []).append(_it)
            _kept = []
            for _col, _items in _by_feature_col.items():
                if _col in _binary_features and len(_items) == 2:
                    _items.sort(key=_informativeness_key)
                    _kept.append(_items[0])
                else:
                    _kept.extend(_items)
            top_list = _kept

        # Ordenar: agrupa por feature_label (idade junto, ocupação junto), e dentro
        # do grupo aplica ordem semântica (idade do menor pro maior, faixa salarial
        # do menor pro maior). Features sem ordem natural ficam por |Δpp| desc.
        # Ordem dos grupos segue o |Δ| máx do grupo.
        _ORDINAL_CATS = {
            'Qual a sua idade?':
                ['<18', '18-24', '25-34', '35-44', '45-54', '55+'],
            'Atualmente, qual a sua faixa salarial?':
                ['Sem renda', 'Até R$2.000', 'R$2.001-3.000', 'R$3.001-5.000', 'Acima de R$5.000'],
        }
        def _trigger_abs(it):
            d = abs(it['delta_pp'])
            l = it.get('launch_delta_pp')
            return max(d, abs(l)) if l is not None else d
        _groups: dict[str, list] = {}
        for _it in top_list:
            _groups.setdefault(_it.get('feature_column', '?'), []).append(_it)
        # Ordem dos grupos pelo |Δ| máx
        _group_order = sorted(_groups.keys(), key=lambda g: -max(_trigger_abs(x) for x in _groups[g]))
        top_list = []
        for _gcol in _group_order:
            _items = _groups[_gcol]
            _ord = _ORDINAL_CATS.get(_gcol)
            if _ord:
                # Sort por ordem semântica; categorias fora da lista vão pro fim (estável)
                _idx = {cat: i for i, cat in enumerate(_ord)}
                _items.sort(key=lambda x: _idx.get(x.get('category'), len(_ord) + 1))
            else:
                _items.sort(key=lambda x: -_trigger_abs(x))
            top_list.extend(_items)
        max_abs_delta = max((_trigger_abs(it) for it in top_list), default=0.0)

        # Período comparado
        from datetime import timedelta as _td, timezone as _tz
        brt = _tz(_td(hours=-3))
        _today_brt = anchor_date if anchor_date is not None else datetime.now(brt).date()
        compared_day_brt = (_today_brt - _td(days=1)).isoformat()
        compared_window_label = f"{compared_day_brt} BRT (último dia completo)"

        def _fmt(items, n=5):
            head = ', '.join(
                f"{it['feature_label']}: {it['category']} — "
                f"{it['reference_pct']}%→{it['day_pct']}% ({it['delta_pp']:+.1f}pp)"
                for it in items[:n]
            )
            tail = f" (+{len(items) - n})" if len(items) > n else ''
            return head + tail

        today_clause = (
            f" · hoje parcial: {today_window_label}, n={total_responses_today}"
            if total_responses_today > 0 else ''
        )
        launch_clause = (
            f" · lançamento {launch_info.get('lf_name')}: n={total_responses_launch}"
            if total_responses_launch > 0 and launch_info.get('lf_name') else ''
        )

        alerts.append({
            'type': 'audience_profile_drift',
            'severity': 'HIGH',
            'category': 'data_quality',
            'message': (
                f" Drift de perfil — comparando {compared_window_label} (n={total_responses_day}) "
                f"vs {ref_label} (n={ref_n}){launch_clause}{today_clause}. "
                f"TOP ({len(top_list)} ≥{top_threshold_pp}pp): {_fmt(top_list)}"
            ),
            'details': {
                'compared_window': compared_window_label,
                'compared_window_kind': 'previous_full_brt_day',
                'reference_pool_label': ref_label,
                'reference_pool_n': ref_n,
                'day_n_responses': total_responses_day,
                'prev_day_n_responses': total_responses_prev_day,
                'today_window': today_window_label,
                'today_n_responses': total_responses_today,
                'launch_window': launch_info.get('label'),
                'launch_n_responses': total_responses_launch,
                'launch_lf_name': launch_info.get('lf_name'),
                'launch_cap_start': launch_info.get('cap_start'),
                'launch_cap_end': launch_info.get('cap_end'),
                'top_threshold_pp': top_threshold_pp,
                'top_list': top_list,
                'top_count': len(top_list),
            },
            'timestamp': now_iso,
            'metric_value': float(max_abs_delta),
            'threshold': top_threshold_pp,
        })

        return alerts

    def _classify_campaign_buckets(self, utm_campaign_series) -> dict:
        """Wrapper local que delega ao módulo compartilhado
        `src/monitoring/campaign_classifier`. Mantido por compat com chamadas
        existentes em `_check_audience_drift_by_variant`.

        Cria o adapter Meta uma vez aqui (composição) e injeta no classifier.
        Cache de classificação por campaign_id vive no módulo (não nesta
        instância) pra ser compartilhado com `app.py` (decile distribution
        by_optgoal usa a mesma classificação).
        """
        import os as _os
        from src.monitoring.campaign_classifier import classify_campaign_buckets

        _token = _os.environ.get("META_ACCESS_TOKEN")
        if not _token:
            return classify_campaign_buckets(utm_campaign_series)
        try:
            from api.meta_integration import MetaAdsIntegration
            _meta = MetaAdsIntegration(access_token=_token)
        except Exception:
            return classify_campaign_buckets(utm_campaign_series)
        return classify_campaign_buckets(utm_campaign_series, meta=_meta)

    def _check_audience_drift_by_variant(self, top_list: List[Dict]) -> List[Dict]:
        """
        Drift de público segmentado em 3 buckets pelo *optimization_goal* das
        campanhas Meta (NÃO pelo model routing do nosso código). Os 3 buckets
        são mutuamente exclusivos — cada lead cai em UM só:

          - Lead       → campanhas SEM evento ML (Lead padrão Meta)
          - Champion   → campanhas com optimization_goal = LeadQualified ou
                         LeadQualifiedHighQuality
          - Challenger → campanhas com optimization_goal = HQLB ou HQLB_LQ

        Soma Lead + Champion + Challenger ≈ total de leads na janela
        (excluindo leads sem campaign_id no utm — Google/orgânico, que
        viram bucket "Lead" como catch-all per definição do usuário).

        Substitui split anterior por `ABTestConfig.match_variant` (model
        routing) — ver discussão 2026-05-28 sobre por que o split por modelo
        misturava Lead-padrão e ML-Champion na mesma coluna Champion.

        Produz 2 alertas (1 por janela: ontem + lançamento atual). Cada alerta
        carrega `lead_pct/champion_pct/challenger_pct` + deltas + qualities
        por linha do top_list. `lead_n/champion_n/challenger_n` no header.
        """
        from datetime import datetime, timezone
        alerts: List[Dict] = []
        if not top_list:
            return alerts

        snapshot, _ = self._load_reference_audience_profile()
        if snapshot is None:
            return alerts

        direction_map = self._load_direction_map()
        now_iso = datetime.now(timezone.utc).isoformat()

        def _split_df_by_optgoal(df: pd.DataFrame, classification: dict) -> Dict[str, pd.DataFrame]:
            """Divide df em {'Lead': df_l, 'Champion': df_ch, 'Challenger': df_cl}
            via classification {cid: bucket}. Leads sem cid extraível ou cid
            não classificado → bucket 'Lead' (catch-all).

            Quando `classification` é vazio (Meta API falhou totalmente),
            retorna todos os 3 buckets vazios — alerta correspondente não vai
            ter dado e o renderer vai mostrar "—" em vez de pretender que
            "tudo é Lead" (falso quando a fonte do problema é Meta indisponível).
            """
            import re as _re
            empty = pd.DataFrame()
            if df is None or len(df) == 0:
                return {'Lead': empty, 'Champion': empty, 'Challenger': empty}
            # Classificação Meta API falhou totalmente — não distorcer
            if not classification:
                return {'Lead': empty, 'Champion': empty, 'Challenger': empty}
            if 'campaign' not in df.columns:
                return {'Lead': df, 'Champion': empty, 'Challenger': empty}
            _CID_RE = _re.compile(r"(\d{15,18})\s*$")
            buckets = {'Lead': [], 'Champion': [], 'Challenger': []}
            for i, row in df.iterrows():
                c = row.get('campaign')
                cid = None
                if c is not None:
                    try:
                        if not pd.isna(c):
                            m = _CID_RE.search(str(c).strip())
                            if m:
                                cid = m.group(1)
                    except Exception:
                        m = _CID_RE.search(str(c).strip())
                        if m:
                            cid = m.group(1)
                bucket = classification.get(cid, 'Lead') if cid else 'Lead'
                buckets[bucket].append(i)
            return {
                'Lead':       df.loc[buckets['Lead']],
                'Champion':   df.loc[buckets['Champion']],
                'Challenger': df.loc[buckets['Challenger']],
            }

        def _category_pct(df: pd.DataFrame, col: str, cat: str) -> Optional[float]:
            """% de leads em (col, cat) dentro do df (excluindo nulos). None se sample vazio."""
            if df is None or len(df) == 0 or col not in df.columns:
                return None
            s = self._normalize_audience_series(df[col], col)
            s = s[s != '(nulo)']
            if len(s) == 0:
                return None
            return float((s == cat).sum()) / len(s) * 100.0

        # Janela 1: ontem (full BRT day anterior)
        df_day = self._query_railway_previous_full_brt_day()
        # Janela 2: lançamento atual
        df_launch, launch_info = self._query_railway_current_launch_brt()

        # Classifica todas as campanhas únicas (ambas janelas) em 3 buckets
        # uma única vez. Reusa cache de classe (TTL 30min) entre invocações.
        _campaign_series_combined = pd.concat([
            (df_day['campaign'] if df_day is not None and 'campaign' in df_day.columns
             else pd.Series([], dtype=str)),
            (df_launch['campaign'] if df_launch is not None and 'campaign' in df_launch.columns
             else pd.Series([], dtype=str)),
        ], ignore_index=True)
        classification = self._classify_campaign_buckets(_campaign_series_combined)

        for window_key, window_df, window_label in [
            ('previous_day', df_day, 'Ontem (dia BRT anterior)'),
            ('current_launch', df_launch, launch_info.get('label') or 'Lançamento atual'),
        ]:
            split = _split_df_by_optgoal(window_df, classification)
            df_lead = split['Lead']
            df_ch = split['Champion']
            df_cl = split['Challenger']
            n_lead = int(len(df_lead))
            n_champion = int(len(df_ch))
            n_challenger = int(len(df_cl))

            rows = []
            for entry in top_list:
                col = entry.get('feature_column')
                cat = entry.get('category')
                ref_pct = entry.get('reference_pct')
                if col is None or cat is None or ref_pct is None:
                    continue
                # 3 colunas excludentes
                lead_pct = _category_pct(df_lead, col, cat)
                ch_pct   = _category_pct(df_ch,   col, cat)
                cl_pct   = _category_pct(df_cl,   col, cat)
                lead_delta = round(lead_pct - ref_pct, 1) if lead_pct is not None else None
                ch_delta   = round(ch_pct   - ref_pct, 1) if ch_pct   is not None else None
                cl_delta   = round(cl_pct   - ref_pct, 1) if cl_pct   is not None else None
                # Winner Champion vs Challenger (não inclui Lead — ele é a referência
                # "controle sem ML", os outros 2 é que disputam qual ML é melhor)
                if ch_delta is None and cl_delta is None:
                    winner = None
                elif ch_delta is None:
                    winner = 'challenger'
                elif cl_delta is None:
                    winner = 'champion'
                else:
                    winner = 'champion' if abs(ch_delta) <= abs(cl_delta) else 'challenger'
                direction = (direction_map.get(col, {}).get(cat, {}) or {}).get('direction')
                lead_quality = self._classify_drift_quality(direction, lead_delta) if lead_delta is not None else None
                ch_quality   = self._classify_drift_quality(direction, ch_delta)   if ch_delta   is not None else None
                cl_quality   = self._classify_drift_quality(direction, cl_delta)   if cl_delta   is not None else None
                rows.append({
                    'feature_column': col,
                    'feature_label': entry.get('feature_label', col),
                    'category': cat,
                    'is_critical': entry.get('is_critical', False),
                    'reference_pct': ref_pct,
                    'lead_pct': round(lead_pct, 1) if lead_pct is not None else None,
                    'lead_delta_pp': lead_delta,
                    'lead_quality': lead_quality,
                    'champion_pct': round(ch_pct, 1) if ch_pct is not None else None,
                    'champion_delta_pp': ch_delta,
                    'champion_quality': ch_quality,
                    'challenger_pct': round(cl_pct, 1) if cl_pct is not None else None,
                    'challenger_delta_pp': cl_delta,
                    'challenger_quality': cl_quality,
                    'winner': winner,
                    'direction': direction,
                })
            alerts.append({
                'type': 'audience_profile_drift_by_variant',
                'severity': 'LOW',
                'category': 'data_quality',
                'message': f'Drift de público por campanha — {window_label}',
                'details': {
                    'window': window_key,
                    'window_label': window_label,
                    'reference_pool_label': snapshot.get('reference_pool', {}).get('label', 'reference'),
                    'lead_n': n_lead,
                    'champion_n': n_champion,
                    'challenger_n': n_challenger,
                    'top_list': rows,
                },
                'timestamp': now_iso,
                'metric_value': 0.0,
                'threshold': 0.0,
            })

        return alerts

    def _check_audience_drift_by_source(self, top_list: List[Dict]) -> List[Dict]:
        """Drift de público segmentado por fonte de tráfego (Meta vs Google).

        Mesma forma de `_check_audience_drift_by_variant` mas o split é por
        `utm_source` em vez de variante A/B. Reusa `top_list` (top features do
        baseline ROAS) e o snapshot de referência. Duas alertas por chamada
        (uma por janela: ontem + lançamento atual). Cada alerta carrega
        `meta_pct/meta_delta_pp/meta_quality` e `google_pct/google_delta_pp/
        google_quality` por feature.

        Classificação de fonte segue o mesmo bucketing do unified_funnel
        (`daily_check_aggregations._classify_source`): Meta = facebook-ads/fb/ig,
        Google = google-ads. Outras fontes (orgânico, tiktok, sem_utm) ficam
        de fora — drift "geral" continua atendendo elas.

        Skip silencioso (devolve []) se top_list vazio ou snapshot ausente.
        Diferente do by_variant, **não depende de ABTestConfig** — corta direto
        no campo utm_source que está em todo lead.
        """
        from datetime import datetime, timezone
        alerts: List[Dict] = []
        if not top_list:
            return alerts

        snapshot, _ = self._load_reference_audience_profile()
        if snapshot is None:
            return alerts

        direction_map = self._load_direction_map()

        _SRC_META = {'facebook-ads', 'fb', 'ig'}
        _SRC_GGL  = {'google-ads'}

        def _split_df_by_source(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
            """Divide df em {'meta': df_meta, 'google': df_google} por utm_source."""
            if df is None or len(df) == 0:
                return {'meta': pd.DataFrame(), 'google': pd.DataFrame()}
            if 'source' not in df.columns:
                df['source'] = ''
            s_norm = df['source'].astype(str).str.strip().str.lower()
            return {
                'meta':   df[s_norm.isin(_SRC_META)],
                'google': df[s_norm.isin(_SRC_GGL)],
            }

        def _category_pct(df: pd.DataFrame, col: str, cat: str) -> Optional[float]:
            if df is None or len(df) == 0 or col not in df.columns:
                return None
            s = self._normalize_audience_series(df[col], col)
            s = s[s != '(nulo)']
            if len(s) == 0:
                return None
            return float((s == cat).sum()) / len(s) * 100.0

        now_iso = datetime.now(timezone.utc).isoformat()

        df_day = self._query_railway_previous_full_brt_day()
        df_launch, launch_info = self._query_railway_current_launch_brt()

        for window_key, window_df, window_label in [
            ('previous_day', df_day, 'Ontem (dia BRT anterior)'),
            ('current_launch', df_launch, launch_info.get('label') or 'Lançamento atual'),
        ]:
            split = _split_df_by_source(window_df)
            df_meta = split['meta']
            df_ggl  = split['google']
            n_meta = int(len(df_meta))
            n_ggl  = int(len(df_ggl))

            rows = []
            for entry in top_list:
                col = entry.get('feature_column')
                cat = entry.get('category')
                ref_pct = entry.get('reference_pct')
                if col is None or cat is None or ref_pct is None:
                    continue
                meta_pct = _category_pct(df_meta, col, cat)
                ggl_pct  = _category_pct(df_ggl,  col, cat)
                meta_delta = round(meta_pct - ref_pct, 1) if meta_pct is not None else None
                ggl_delta  = round(ggl_pct  - ref_pct, 1) if ggl_pct  is not None else None
                direction = (direction_map.get(col, {}).get(cat, {}) or {}).get('direction')
                meta_quality = self._classify_drift_quality(direction, meta_delta) if meta_delta is not None else None
                ggl_quality  = self._classify_drift_quality(direction, ggl_delta)  if ggl_delta  is not None else None
                rows.append({
                    'feature_column': col,
                    'feature_label': entry.get('feature_label', col),
                    'category': cat,
                    'is_critical': entry.get('is_critical', False),
                    'reference_pct': ref_pct,
                    'meta_pct': round(meta_pct, 1) if meta_pct is not None else None,
                    'meta_delta_pp': meta_delta,
                    'meta_quality': meta_quality,
                    'google_pct': round(ggl_pct, 1) if ggl_pct is not None else None,
                    'google_delta_pp': ggl_delta,
                    'google_quality': ggl_quality,
                    'direction': direction,
                })
            alerts.append({
                'type': 'audience_profile_drift_by_source',
                'severity': 'LOW',
                'category': 'data_quality',
                'message': f'Drift de público por fonte — {window_label}',
                'details': {
                    'window': window_key,
                    'window_label': window_label,
                    'reference_pool_label': snapshot.get('reference_pool', {}).get('label', 'reference'),
                    'meta_n': n_meta,
                    'google_n': n_ggl,
                    'top_list': rows,
                },
                'timestamp': now_iso,
                'metric_value': 0.0,
                'threshold': 0.0,
            })

        return alerts

    def _load_audience_quality_baseline(self):
        """Lê configs/reference_audience_profiles/{client_id}_quality_signal.json.

        Retorna (baseline_dict, None) em sucesso, (None, error_dict) em falha.
        """
        client_id = getattr(self.client_config, 'client_id', 'devclub') if self.client_config else 'devclub'
        candidate = Path(__file__).resolve().parents[2] / 'configs' / 'reference_audience_profiles' / f'{client_id}_quality_signal.json'
        if not candidate.exists():
            return None, {'reason': 'baseline_file_missing', 'tried_paths': [str(candidate)]}
        try:
            import json
            with open(candidate) as f:
                baseline = json.load(f)
            return baseline, None
        except Exception as e:
            return None, {'reason': f'baseline_parse_error: {e}', 'tried_paths': [str(candidate)]}

    def _check_audience_quality_signal(self) -> List[Dict]:
        """
        Re-scoreia leads do LF atual com Challenger via mesma chain de produção
        (LeadScoringPipeline.run com CSV tempfile, igual api/app.py:345/959) e
        compara %D10/%D9-D10/score_médio com baseline pré-computado dos Top5
        ROAS realized salvo em configs/reference_audience_profiles/{client}_quality_signal.json.

        Captura interação multivariada que o drift de mix categórico sozinho
        (_check_audience_profile_drift) não consegue ver: 5 features cada uma
        movendo 1pp combinam pelo modelo num drift de 5pp em D9-D10, e este
        check pega.

        Skip silencioso (com log INFO) se:
          - lead_scoring_pipeline não foi injetado (rodando local sem API)
          - baseline JSON ausente
          - nenhum LF ativo
          - n_leads do LF < min_n
          - modelo Challenger não encontrado no ABTestConfig (run_id do baseline
            não bate com nenhum variant)

        Severity:
          - HIGH se Δ%D9-D10 ≤ alert_threshold OU Δscore_pct ≤ alert_threshold
          - MEDIUM se Δ%D9-D10 ≤ warn_threshold OU Δscore_pct ≤ warn_threshold
          - Nenhum alerta crítico se ambos dentro do padrão (info-level com snapshot)
        """
        from datetime import datetime, timezone
        import os, tempfile

        alerts: List[Dict] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        pipeline = self.lead_scoring_pipeline
        if pipeline is None:
            logger.info("[audience_quality_signal] lead_scoring_pipeline=None — skip.")
            return alerts

        baseline, error = self._load_audience_quality_baseline()
        if baseline is None:
            logger.info(f"[audience_quality_signal] baseline indisponível: {error['reason']}.")
            return alerts

        bl_metrics = baseline.get('metrics', {})
        bl_thresholds = baseline.get('thresholds', {})
        baseline_run_id = baseline.get('model', {}).get('run_id')
        baseline_pool_label = baseline.get('reference_pool', {}).get('label', 'Top5 ROAS realized')
        baseline_n = baseline.get('reference_pool', {}).get('n_leads', 0)

        # Resolver LF atual + leads via mesma origem que api/app.py usa em produção
        # (SalesDataLoader.load_railway_leads devolve formato Sheets canônico).
        current = self._resolve_current_launch_brt()
        if current is None:
            logger.info("[audience_quality_signal] sem LF ativo no momento — skip.")
            return alerts
        lf_name, cs_str, ce_str = current

        try:
            from src.validation.data_loader import SalesDataLoader
            df_launch = SalesDataLoader().load_railway_leads(start_date=cs_str, end_date=ce_str,
                                                              client_config=self.client_config)
        except Exception as e:
            logger.warning(f"[audience_quality_signal] load_railway_leads falhou: {e}")
            return alerts

        cfg = self._thresholds.get('audience_quality_signal', {})
        min_n = int(cfg.get('min_n_leads', 200))
        if len(df_launch) < min_n:
            logger.info(f"[audience_quality_signal] LF {lf_name} com {len(df_launch)} leads "
                        f"< min_n_leads={min_n}, skip.")
            return alerts

        # Localizar Challenger predictor + encoding_overrides via ABTestConfig
        # (mesma lógica de api/app.py:937-947 ao decidir Champion shim).
        ab_cfg = getattr(pipeline, '_ab_test_config', None)
        if ab_cfg is None or not getattr(ab_cfg, 'enabled', False):
            logger.info("[audience_quality_signal] ab_test não habilitado no pipeline — skip.")
            return alerts
        target_variant = None
        target_variant_name = None
        for vname, v in ab_cfg.variants.items():
            if v.run_id == baseline_run_id:
                target_variant = v
                target_variant_name = vname
                break
        if target_variant is None:
            logger.warning(f"[audience_quality_signal] run_id {baseline_run_id} do baseline não "
                           f"está em ab_test.variants — skip.")
            return alerts
        try:
            predictor = pipeline.get_variant_predictor(target_variant_name)
        except Exception as e:
            logger.warning(f"[audience_quality_signal] get_variant_predictor({target_variant_name}) "
                           f"falhou: {e}")
            return alerts
        encoding_overrides = target_variant.encoding_overrides

        # Re-scorear via mesma chain de produção: CSV tempfile + pipeline.run().
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
                tmp_path = tmp.name
            df_launch.to_csv(tmp_path, index=False)
            scored = pipeline.run(
                filepath=tmp_path,
                with_predictions=True,
                predictor_override=predictor,
                encoding_overrides=encoding_overrides,
            )
        except Exception as e:
            logger.error(f"[audience_quality_signal] pipeline.run falhou: {e}")
            return alerts
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        if scored is None or 'lead_score' not in scored.columns:
            logger.warning("[audience_quality_signal] pipeline.run não retornou lead_score.")
            return alerts

        # Atribuir decil usando thresholds do modelo (mesma função de produção)
        try:
            from src.model.decil_thresholds import atribuir_decis_batch
            thresholds_dict = predictor.metadata.get('decil_thresholds', {}).get('thresholds', {})
            if not thresholds_dict:
                logger.warning("[audience_quality_signal] decil_thresholds ausente no predictor.")
                return alerts
            scored['decil'] = atribuir_decis_batch(scored['lead_score'].values, thresholds_dict)
        except Exception as e:
            logger.warning(f"[audience_quality_signal] decil assignment falhou: {e}")
            return alerts

        # Métricas atuais do LF
        n_launch = len(scored)
        score_mean_cur = float(scored['lead_score'].mean())
        # Decil pode vir como "D10" ou "D01" (mesma convenção do baseline)
        def _norm_dec(s):
            s = str(s).strip().lstrip('D')
            try: return f"D{int(float(s)):02d}"
            except: return None
        decis_norm = scored['decil'].apply(_norm_dec)
        pct_d10_cur    = float((decis_norm == 'D10').mean())
        pct_d9_d10_cur = float(decis_norm.isin(['D09', 'D10']).mean())
        pct_d8_d10_cur = float(decis_norm.isin(['D08', 'D09', 'D10']).mean())

        # Deltas vs baseline
        bl_score    = float(bl_metrics.get('score_mean', 0.0))
        bl_d10      = float(bl_metrics.get('pct_d10', 0.0))
        bl_d9_d10   = float(bl_metrics.get('pct_d9_d10', 0.0))
        bl_d8_d10   = float(bl_metrics.get('pct_d8_d10', 0.0))

        d_score_pct = (score_mean_cur - bl_score) / bl_score if bl_score > 0 else 0.0
        d_d10       = pct_d10_cur - bl_d10
        d_d9_d10    = pct_d9_d10_cur - bl_d9_d10
        d_d8_d10    = pct_d8_d10_cur - bl_d8_d10

        # Thresholds (negativos: queda em relação ao baseline)
        warn_d9_d10  = float(bl_thresholds.get('delta_pct_d9_d10_warn',     -0.03))
        alert_d9_d10 = float(bl_thresholds.get('delta_pct_d9_d10_alert',    -0.05))
        warn_score   = float(bl_thresholds.get('delta_score_mean_pct_warn', -0.05))
        alert_score  = float(bl_thresholds.get('delta_score_mean_pct_alert',-0.10))

        # Classificação
        if d_d9_d10 <= alert_d9_d10 or d_score_pct <= alert_score:
            severity = 'HIGH'
            sinal = 'ABAIXO do padrão'
        elif d_d9_d10 <= warn_d9_d10 or d_score_pct <= warn_score:
            severity = 'MEDIUM'
            sinal = 'levemente ABAIXO do padrão'
        elif d_d9_d10 >= 0.03 and d_score_pct >= 0.05:
            severity = 'LOW'
            sinal = 'ACIMA do padrão'
        else:
            severity = 'LOW'
            sinal = 'DENTRO do padrão'

        details = {
            'lf_name': lf_name,
            'cap_start': cs_str,
            'cap_end': ce_str,
            'n_leads_launch': n_launch,
            'model': baseline.get('model', {}),
            'baseline_pool_label': baseline_pool_label,
            'baseline_n_leads': baseline_n,
            'current': {
                'score_mean': round(score_mean_cur, 4),
                'pct_d10': round(pct_d10_cur, 4),
                'pct_d9_d10': round(pct_d9_d10_cur, 4),
                'pct_d8_d10': round(pct_d8_d10_cur, 4),
            },
            'baseline': {
                'score_mean': bl_score,
                'pct_d10': bl_d10,
                'pct_d9_d10': bl_d9_d10,
                'pct_d8_d10': bl_d8_d10,
            },
            'delta': {
                'score_pct': round(d_score_pct, 4),
                'pct_d10_pp':    round(d_d10, 4),
                'pct_d9_d10_pp': round(d_d9_d10, 4),
                'pct_d8_d10_pp': round(d_d8_d10, 4),
            },
            'sinal': sinal,
        }

        alerts.append({
            'type': 'audience_quality_signal',
            'severity': severity,
            'category': 'data_quality',
            'message': (
                f" Audiência {lf_name} (n={n_launch:,}) — {sinal} vs {baseline_pool_label} "
                f"(n={baseline_n:,}). Δ%D9-D10={d_d9_d10*100:+.1f}pp · "
                f"Δscore={d_score_pct*100:+.1f}% · %D10={pct_d10_cur*100:.1f}%"
            ),
            'details': details,
            'timestamp': now_iso,
            'metric_value': float(d_d9_d10),
            'threshold': warn_d9_d10,
        })
        return alerts
