"""
Rastreamento de categorias e distribuições vistas no treino para detecção de drift.
Detecta:
- Novas categorias não vistas no treino
- Mudanças drásticas nas proporções de categorias
- Mudanças drásticas nas distribuições de features numéricas
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Set, List, Tuple
from pathlib import Path


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

    # Colunas a ignorar (features derivadas, target, etc)
    colunas_ignorar = {
        'target',
        'Data',  # será removida no FE
        'Nome Completo',  # será removida no FE
        'E-mail',  # será removida no FE
        'Telefone',  # será removida no FE
        'nome_comprimento',  # numérica derivada
        'dia_semana',  # ordinal numérica
        'nome_tem_sobrenome',  # booleana (será one-hot)
        'nome_valido',  # booleana
        'email_valido',  # booleana
        'telefone_valido',  # booleana
        'telefone_comprimento'  # numérica
    }

    for col in df.columns:
        # Pular colunas ignoradas
        if col in colunas_ignorar:
            continue

        # Identificar colunas categóricas:
        # 1. Tipo object (string)
        # 2. OU numérica com poucos valores únicos (<=20) - pode ser ordinal encoding já aplicado
        is_categorical = (
            df[col].dtype == 'object' or
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

        # Encontrar novas categorias
        set_treino = set(categorias_treino)
        set_producao = set(categorias_producao_str)
        novas_categorias = set_producao - set_treino

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
