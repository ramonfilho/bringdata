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
from typing import Dict, Set, List, Tuple
from pathlib import Path
from unidecode import unidecode
import re


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
    print("\n🔍 Identificando colunas categóricas automaticamente...")

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

            print(f"   ✓ {col}: {len(valores_unicos_str)} categorias")

    print(f"\n📊 Total: {len(categorias_por_coluna)} colunas categóricas identificadas")

    # Salvar se caminho fornecido
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(categorias_por_coluna, f, indent=2, ensure_ascii=False)
        print(f"✅ Categorias salvas em: {output_path}")

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
                'message': f"⚠️ Coluna '{col}' esperada mas não encontrada em produção"
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
            # Criar mapeamento: normalizado → original
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
                'message': f"⚠️ {col}: {len(novas_categorias)} nova(s) categoria(s) - {percentual:.1f}% dos leads\n"
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
    json_path = Path(model_path) / "categorias_esperadas.json"

    if not json_path.exists():
        raise FileNotFoundError(
            f"Arquivo de categorias não encontrado: {json_path}\n"
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
    print("\n📊 Capturando distribuições de treino...")

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
            print(f"   ✓ {col}: {len(proporcoes)} categorias")

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
                print(f"   ✓ {col}: μ={stats['mean']:.2f}, σ={stats['std']:.2f}")
            except (TypeError, ValueError) as e:
                # Se não conseguir calcular estatísticas, tratar como categórica
                print(f"   ⚠️ {col}: não foi possível calcular estatísticas numéricas, tratando como categórica")
                contagens = df[col].value_counts()
                proporcoes = (contagens / total_nao_nulos).to_dict()
                proporcoes_str = {str(k): float(v) for k, v in proporcoes.items()}
                distribuicoes["categorical"][col] = proporcoes_str

    print(f"\n📊 Total: {len(distribuicoes['categorical'])} categóricas, "
          f"{len(distribuicoes['numerical'])} numéricas")

    # Salvar se caminho fornecido
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(distribuicoes, f, indent=2, ensure_ascii=False)
        print(f"✅ Distribuições salvas em: {output_path}")

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
        proporcoes_producao_str = {str(k): float(v) for k, v in proporcoes_producao.items()}

        # Comparar cada categoria
        mudancas_significativas = []
        for categoria, prop_treino in proporcoes_treino.items():
            prop_producao = proporcoes_producao_str.get(categoria, 0.0)
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

            # Formatar mensagem
            mudancas_msg = []
            for m in mudancas_significativas[:3]:  # Mostrar top 3
                mudancas_msg.append(
                    f"'{m['categoria']}': {m['treino']*100:.1f}%→{m['producao']*100:.1f}% "
                    f"({m['diff']*100:+.1f}pp)"
                )
            mais_msg = f" (e mais {len(mudancas_significativas)-3})" if len(mudancas_significativas) > 3 else ""

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
                'message': f"⚠️ {col}: {len(mudancas_significativas)} mudança(s) significativa(s) nas proporções\n"
                          f"   {', '.join(mudancas_msg)}{mais_msg}"
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
                'message': f"⚠️ {col}: média mudou {mean_diff_sigma:.1f}σ\n"
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
    json_path = Path(model_path) / "distribuicoes_esperadas.json"

    if not json_path.exists():
        raise FileNotFoundError(
            f"Arquivo de distribuições não encontrado: {json_path}\n"
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

    def __init__(self, model_path: str):
        """
        Args:
            model_path: Caminho para pasta do modelo ativo
        """
        self.model_path = model_path

    def check(self, df: pd.DataFrame) -> List[Dict]:
        """
        Executa todos os checks de qualidade de dados.

        Args:
            df: DataFrame com dados das últimas 24h do Sheets

        Returns:
            Lista de alertas no formato dict (compatível com Alert.from_dict)
        """
        from .config import THRESHOLDS, EXPECTED_DECIL_DISTRIBUTION
        from datetime import datetime

        alerts = []

        # 1. Category drift
        if THRESHOLDS['category_drift']['enabled']:
            alerts.extend(self._check_category_drift(df))

        # 2. Distribution drift
        if THRESHOLDS['distribution_drift']['enabled']:
            alerts.extend(self._check_distribution_drift(df))

        # 3. Missing rate
        if THRESHOLDS['missing_rate']['enabled']:
            alerts.extend(self._check_missing_rate(df))

        # 4. Score distribution
        if THRESHOLDS['score_distribution']['enabled']:
            alerts.extend(self._check_score_distribution(df))

        # 5. Missing features (colunas esperadas não encontradas)
        alerts.extend(self._check_missing_features(df))

        return alerts

    def _check_category_drift(self, df: pd.DataFrame) -> List[Dict]:
        """Verifica categorias não vistas no treino"""
        from datetime import datetime
        alerts = []

        print("\n" + "="*80)
        print("🔍 CHECK: Novas categorias não vistas no treino")
        print("="*80)

        try:
            categorias_esperadas = load_training_categories(self.model_path)
            drift_results = check_category_drift(df, categorias_esperadas)

            total_colunas_verificadas = len(categorias_esperadas)
            colunas_com_drift = len(drift_results)

            print(f"Colunas verificadas: {total_colunas_verificadas}")
            print(f"Colunas com categorias novas: {colunas_com_drift}")

            if drift_results:
                print(f"\n⚠️  Status: ALERTA - {colunas_com_drift} coluna(s) com categorias novas")
                for result in drift_results:
                    print(f"   • {result['column']}: {len(result.get('new_categories', []))} nova(s) categoria(s)")
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
                        'timestamp': datetime.now().isoformat(),
                        'metric_value': result.get('percentage', 0),
                        'threshold': None
                    })
            else:
                print(f"✅ Status: OK - Todas as categorias conhecidas")

        except (FileNotFoundError, Exception) as e:
            print(f"❌ Status: ERRO - Não foi possível carregar categorias esperadas")

        return alerts

    def _check_distribution_drift(self, df: pd.DataFrame) -> List[Dict]:
        """Verifica mudanças drásticas nas proporções"""
        from .config import THRESHOLDS
        from datetime import datetime
        alerts = []

        print("\n" + "="*80)
        print("🔍 CHECK: Mudanças drásticas nas distribuições")
        print("="*80)

        try:
            distribuicoes_esperadas = load_training_distributions(self.model_path)
            threshold_cat = THRESHOLDS['distribution_drift']['categorical']
            threshold_num = THRESHOLDS['distribution_drift']['numerical']

            print(f"Threshold categórico: {threshold_cat*100:.1f}% (mudança máxima permitida)")
            print(f"Threshold numérico: {threshold_num} sigmas (desvio permitido)")
            print(f"Colunas a verificar: {len(distribuicoes_esperadas)}")

            drift_results = check_distribution_drift(
                df, distribuicoes_esperadas,
                threshold_categorical=threshold_cat,
                threshold_numerical=threshold_num
            )

            colunas_com_drift = len(drift_results)
            print(f"Colunas com drift detectado: {colunas_com_drift}")

            # Mostrar detalhes de mudanças por categoria (TODAS as colunas, não só as com drift)
            print(f"\n📊 DETALHES DAS MUDANÇAS POR FEATURE:")
            print("-" * 80)

            # 1. Features categóricas
            for col, proporcoes_treino in distribuicoes_esperadas.get("categorical", {}).items():
                if col not in df.columns:
                    continue

                # Calcular proporções atuais
                total_nao_nulos = df[col].notna().sum()
                if total_nao_nulos == 0:
                    continue

                contagens = df[col].value_counts()
                proporcoes_producao = (contagens / total_nao_nulos).to_dict()
                proporcoes_producao_str = {str(k): float(v) for k, v in proporcoes_producao.items()}

                # Calcular mudanças para TODAS as categorias
                mudancas = []
                for categoria, prop_treino in proporcoes_treino.items():
                    prop_producao = proporcoes_producao_str.get(categoria, 0.0)
                    diff = prop_producao - prop_treino  # Signed difference
                    mudancas.append({
                        'categoria': categoria,
                        'treino': prop_treino,
                        'producao': prop_producao,
                        'diff': diff
                    })

                # Ordenar por maior mudança absoluta
                mudancas.sort(key=lambda x: abs(x['diff']), reverse=True)

                # Verificar se tem drift
                tem_drift = any(result['column'] == col for result in drift_results)
                status_icon = "⚠️" if tem_drift else "✅"

                print(f"\n{status_icon} {col}:")
                for m in mudancas:
                    diff_abs = abs(m['diff'])
                    excede = "⚠️" if diff_abs >= threshold_cat else "  "
                    print(f"   {excede} '{m['categoria']}': {m['treino']*100:5.1f}% → {m['producao']*100:5.1f}% ({m['diff']*100:+6.1f}pp)")

            # 2. Features numéricas
            for col, stats_treino in distribuicoes_esperadas.get("numerical", {}).items():
                if col not in df.columns:
                    continue

                if df[col].notna().sum() == 0:
                    continue

                mean_treino = stats_treino['mean']
                std_treino = stats_treino['std']
                mean_producao = float(df[col].mean())
                std_producao = float(df[col].std())

                # Calcular mudança em desvios padrão
                if std_treino > 0:
                    mean_diff_sigma = abs(mean_producao - mean_treino) / std_treino
                else:
                    mean_diff_sigma = 0.0

                tem_drift = any(result['column'] == col for result in drift_results)
                status_icon = "⚠️" if tem_drift else "✅"
                excede = "⚠️" if mean_diff_sigma >= threshold_num else "  "

                print(f"\n{status_icon} {col} (numérica):")
                print(f"   {excede} Treino:    μ={mean_treino:7.2f}, σ={std_treino:7.2f}")
                print(f"   {excede} Produção:  μ={mean_producao:7.2f}, σ={std_producao:7.2f}")
                print(f"   {excede} Mudança:   {mean_diff_sigma:.2f}σ")

            print("-" * 80)

            if drift_results:
                print(f"\n⚠️  Status: ALERTA - {colunas_com_drift} coluna(s) com mudanças significativas")
                print("-" * 80)

                for result in drift_results:
                    drift_type = result['type']
                    severity = result.get('severity', 'MEDIUM')

                    print(f"\n📊 {result['column']}")
                    print(f"   Tipo: {drift_type}")
                    print(f"   Severidade: {severity}")

                    if drift_type == 'categorical_distribution_drift':
                        # Mostrar top 3 categorias com maior mudança
                        changes = result.get('changes', [])
                        if changes:
                            print(f"   Top 3 categorias com maior mudança:")
                            for i, change in enumerate(changes[:3], 1):
                                categoria = change['categoria']
                                treino_pct = change['treino'] * 100
                                producao_pct = change['producao'] * 100
                                # Calcular diferença com sinal (+ ou -)
                                diff_pp_signed = (change['producao'] - change['treino']) * 100
                                print(f"      {i}. '{categoria}': {treino_pct:.1f}% → {producao_pct:.1f}% ({diff_pp_signed:+.1f}pp)")

                    elif drift_type == 'numerical_distribution_drift':
                        # Mostrar métricas numéricas
                        mean_treino = result.get('mean_treino', 0)
                        mean_producao = result.get('mean_producao', 0)
                        std_treino = result.get('std_treino', 0)
                        std_producao = result.get('std_producao', 0)
                        sigma_diff = result.get('sigma_diff', 0)

                        print(f"   Treino: μ={mean_treino:.2f}, σ={std_treino:.2f}")
                        print(f"   Produção: μ={mean_producao:.2f}, σ={std_producao:.2f}")
                        print(f"   Mudança: {sigma_diff:.2f}σ (threshold: {threshold_num:.1f}σ)")

                print("-" * 80)
            else:
                print(f"\n✅ Status: OK - Distribuições dentro do esperado")

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
                    'timestamp': datetime.now().isoformat(),
                    'metric_value': metric_value,
                    'threshold': threshold_used
                })

        except (FileNotFoundError, Exception):
            pass

        return alerts

    def _check_missing_rate(self, df: pd.DataFrame) -> List[Dict]:
        """Verifica colunas com missing rate alto"""
        from .config import THRESHOLDS, MISSING_RATE_IGNORE_COLUMNS
        from datetime import datetime
        alerts = []
        threshold = THRESHOLDS['missing_rate']['threshold']

        print("\n" + "="*80)
        print("🔍 CHECK: Missing rate alto em colunas")
        print("="*80)

        total_rows = len(df)
        if total_rows == 0:
            return alerts

        print(f"Threshold: {threshold*100:.1f}% (máximo permitido)")
        print(f"Total de linhas: {total_rows}")

        colunas_acima_threshold = []
        missing_rates = {}

        for col in df.columns:
            # Ignorar colunas da whitelist
            if col in MISSING_RATE_IGNORE_COLUMNS:
                continue
            # Contar NaN + strings vazias (converter para int nativo para serialização JSON)
            missing_count = int(df[col].isna().sum())
            missing_count += int((df[col].astype(str).str.strip() == '').sum())
            missing_rate = missing_count / total_rows

            missing_rates[col] = missing_rate

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
                    'message': f"⚠️ {col}: {missing_rate*100:.1f}% missing ({missing_count}/{total_rows} leads)",
                    'details': {
                        'column': col,
                        'missing_count': missing_count,
                        'total_rows': total_rows,
                        'missing_rate': missing_rate
                    },
                    'timestamp': datetime.now().isoformat(),
                    'metric_value': missing_rate,
                    'threshold': threshold
                })

        # Mostrar resumo
        colunas_verificadas = len(missing_rates)
        max_missing = max(missing_rates.values()) if missing_rates else 0

        print(f"Colunas verificadas: {colunas_verificadas}")
        print(f"Colunas acima do threshold: {len(colunas_acima_threshold)}")
        print(f"Missing rate máximo: {max_missing*100:.1f}%")

        if colunas_acima_threshold:
            print(f"\n⚠️  Status: ALERTA - {len(colunas_acima_threshold)} coluna(s) com missing alto")
            for col, rate in sorted(colunas_acima_threshold, key=lambda x: x[1], reverse=True)[:5]:
                print(f"   • {col}: {rate*100:.1f}%")
        else:
            print(f"✅ Status: OK - Todas as colunas com missing < {threshold*100:.1f}%")

        return alerts

    def _check_score_distribution(self, df: pd.DataFrame) -> List[Dict]:
        """Verifica mudanças na distribuição de decis"""
        from .config import THRESHOLDS, EXPECTED_DECIL_DISTRIBUTION
        from datetime import datetime
        alerts = []

        print("\n" + "="*80)
        print("🔍 CHECK: Mudança significativa nas proporções de score/decil")
        print("="*80)

        if 'decil' not in df.columns:
            print("⚠️  Status: SKIP - Coluna 'decil' não encontrada no dataset")
            print("   Verifique se a coluna existe no Google Sheets (pipeline de produção)")
            print("   Colunas disponíveis:", sorted([c for c in df.columns if 'score' in c.lower() or 'decil' in c.lower()]))
            return alerts

        threshold = THRESHOLDS['score_distribution']['threshold']
        total_leads = len(df)

        print(f"Threshold: {threshold*100:.1f}% (mudança máxima permitida)")
        print(f"Total de leads: {total_leads}")

        if total_leads == 0:
            return alerts

        # Normalizar formato dos decis (D01 → D1, D02 → D2, etc)
        # Google Sheets pode ter 'D01' enquanto esperamos 'D1'
        df['decil_normalized'] = df['decil'].astype(str).str.replace(r'^D0(\d)$', r'D\1', regex=True)

        decil_counts = df['decil_normalized'].value_counts()
        distribuicao_atual = {
            decil: decil_counts.get(decil, 0) / total_leads
            for decil in EXPECTED_DECIL_DISTRIBUTION.keys()
        }

        diferencas_significativas = []
        for decil, prop_esperada in EXPECTED_DECIL_DISTRIBUTION.items():
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
                f"{c['decil']}: {c['esperado']*100:.0f}%→{c['atual']*100:.0f}% ({c['diff']*100:+.1f}pp)"
                for c in top_changes
            ])
            mais_msg = f" (e mais {len(diferencas_significativas)-3})" if len(diferencas_significativas) > 3 else ""

            alerts.append({
                'type': 'score_distribution_change',
                'severity': severity,
                'category': 'data_quality',
                'message': f"⚠️ Distribuição de decis mudou: {changes_msg}{mais_msg}",
                'details': {
                    'changes': diferencas_significativas,
                    'total_leads': total_leads
                },
                'timestamp': datetime.now().isoformat(),
                'metric_value': max_diff,
                'threshold': threshold
            })

        # Mostrar resumo
        print(f"Decis verificados: {len(EXPECTED_DECIL_DISTRIBUTION)}")
        print(f"Decis com mudança significativa: {len(diferencas_significativas)}")

        # Mostrar TODOS os decis (não apenas os que excedem threshold)
        print(f"\n📊 Distribuição completa de decis:")
        print("-" * 80)

        # Ordenar decis numericamente (D1, D2, ..., D10 ao invés de D1, D10, D2, ...)
        decis_ordenados = sorted(EXPECTED_DECIL_DISTRIBUTION.keys(), key=lambda x: int(x[1:]))

        for decil in decis_ordenados:
            prop_esperada = EXPECTED_DECIL_DISTRIBUTION[decil]
            prop_atual = distribuicao_atual.get(decil, 0)
            diff_signed = (prop_atual - prop_esperada) * 100  # Signed difference in pp

            # Marcar decis que excedem threshold
            excede = "⚠️" if abs(prop_atual - prop_esperada) > threshold else "  "
            print(f"{excede} {decil}: {prop_esperada*100:5.1f}% → {prop_atual*100:5.1f}% ({diff_signed:+6.1f}pp)")
        print("-" * 80)

        if diferencas_significativas:
            print(f"\n⚠️  Status: ALERTA - {len(diferencas_significativas)} decil(is) com mudança > {threshold*100:.1f}%")
        else:
            print(f"\n✅ Status: OK - Distribuição de decis dentro do esperado")

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
        from datetime import datetime

        alerts = []

        print("\n" + "="*80)
        print("🔍 CHECK: Features esperadas pelo modelo")
        print("="*80)

        try:
            # 1. Aplicar encoding nos dados (necessário para validar features finais)
            from features.encoding import apply_categorical_encoding
            df_encoded = apply_categorical_encoding(df.copy(), versao='v1', medium_strategy='binary_top3')

            print(f"Features após encoding: {len(df_encoded.columns)}")

            # 2. Usar Predictor para validar features
            from model.prediction import LeadScoringPredictor
            # Extrair model_name do caminho (último componente antes de features_ordenadas)
            model_name = "v1_devclub_rf_temporal_leads_single"  # Nome padrão do modelo ativo
            predictor = LeadScoringPredictor(model_name=model_name, model_path=self.model_path)

            # 3. Validar features (NÃO faz predição, só valida)
            # validate_features() carrega feature_names automaticamente se necessário
            validation = predictor.validate_features(df_encoded)

            print(f"Features esperadas pelo modelo: {validation['total_expected']}")

            print(f"Features ausentes: {validation['missing_count']}")

            if not validation['is_valid']:
                missing_features = validation['missing_features']

                print(f"\n⚠️  Status: ALERTA - {len(missing_features)} feature(s) ausente(s)")

                # Mostrar primeiras 5 features ausentes
                for feat in missing_features[:5]:
                    print(f"   • {feat}")
                if len(missing_features) > 5:
                    print(f"   ... e mais {len(missing_features)-5}")

                # Criar alerta
                alerts.append({
                    'type': 'missing_expected_features',
                    'severity': 'HIGH',
                    'category': 'data_quality',
                    'message': f"⚠️ {len(missing_features)} feature(s) esperada(s) pelo modelo ausente(s) após encoding",
                    'details': {
                        'missing_count': len(missing_features),
                        'missing_features': missing_features,
                        'total_expected': validation['total_expected'],
                        'total_created': validation['total_received']
                    },
                    'timestamp': datetime.now().isoformat(),
                    'metric_value': len(missing_features),
                    'threshold': 0  # Qualquer feature faltando é problema
                })
            else:
                print(f"✅ Status: OK - Todas as features esperadas presentes")

        except Exception as e:
            print(f"❌ Status: ERRO - {str(e)}")
            import traceback
            traceback.print_exc()

        return alerts
