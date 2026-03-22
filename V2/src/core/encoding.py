"""
core/encoding.py — Encoding categórico e ordinal.

Consolida encoding_training.py e encoding.py.
Canonical: produção (encoding.py).

Divergências resolvidas vs treino (encoding_training.py):
  - Nomes ordinais longos (survey) vs curtos (pós-category_unification):
    config suporta ambas as formas durante migração (#49)
  - clean_column_names() adicionado ao treino (produção canonical)
  - mapeamentos_especificos adicionado ao treino via config.column_name_corrections (#70)
  - feature registry: treino passa a alinhar features como produção

Componente 3 da Fase 2.
Hardcodes migrados: #49, #51, #64, #70 → EncodingConfig.
Artifacts contract: {'mlflow_run_id': str} ou {'model_path': str}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .client_config import EncodingConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature registry
# ---------------------------------------------------------------------------

def _load_feature_registry(artifacts: Dict[str, Any]) -> Optional[List[str]]:
    """
    Carrega lista ordenada de features do modelo ativo.

    artifacts keys (em ordem de prioridade):
        'mlflow_run_id': str — ID do MLflow run (preferencial)
        'model_path':    str — path para pasta do modelo (deprecated, backward compat)

    Returns:
        Lista ordenada de features, ou None se não disponível.
    """
    mlflow_run_id = artifacts.get('mlflow_run_id')
    model_path = artifacts.get('model_path')

    if mlflow_run_id:
        try:
            import mlflow as _mlflow
            experiment_id = _mlflow.get_run(mlflow_run_id).info.experiment_id
        except Exception:
            experiment_id = artifacts.get('mlflow_experiment_id', '1')
        registry_path = (
            Path(__file__).parent.parent.parent
            / "mlruns" / experiment_id / mlflow_run_id / "artifacts" / "feature_registry.json"
        )
        if registry_path.exists():
            try:
                with open(registry_path, 'r') as f:
                    data = json.load(f)
                order = data.get('model_input_features', {}).get('ordered_list')
                if order:
                    logger.debug(f"  Encoding: {len(order)} features carregadas do MLflow run {mlflow_run_id}")
                    return order
            except Exception as e:
                logger.warning(f"  Encoding: erro ao ler feature_registry do MLflow: {e}")
        else:
            logger.warning(f"  Encoding: feature_registry não encontrado: {registry_path}")

    if model_path:
        model_path = Path(model_path)
        # Prioridade 1: feature_registry.json (novo formato)
        for pattern in [
            "feature_registry_v1_devclub_rf_temporal_leads_single.json",
            "feature_registry*.json",
        ]:
            for candidate in list(model_path.glob(pattern))[:1]:
                try:
                    with open(candidate, 'r') as f:
                        data = json.load(f)
                    order = data.get('model_input_features', {}).get('ordered_list')
                    if order:
                        logger.debug(f"  Encoding: {len(order)} features de {candidate.name}")
                        return order
                except Exception as e:
                    logger.warning(f"  Encoding: erro ao ler {candidate}: {e}")

        # Prioridade 2: features_ordenadas.json (formato antigo)
        for candidate in list(model_path.glob("features_ordenadas*.json"))[:1]:
            try:
                with open(candidate, 'r') as f:
                    data = json.load(f)
                order = data.get('feature_names', [])
                if order:
                    logger.debug(f"  Encoding: {len(order)} features de {candidate.name} (legacy)")
                    return order
            except Exception as e:
                logger.warning(f"  Encoding: erro ao ler {candidate}: {e}")

    return None


# ---------------------------------------------------------------------------
# Encoding principal
# ---------------------------------------------------------------------------

def apply_encoding(
    df: pd.DataFrame,
    config: EncodingConfig,
    artifacts: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Aplica encoding estratégico: ordinal → one-hot → clean_column_names → feature registry.

    Args:
        df:        DataFrame após feature engineering.
        config:    EncodingConfig carregada do YAML do cliente.
        artifacts: Dict com referência ao modelo ativo para feature registry.
                   Keys: 'mlflow_run_id' (preferencial) ou 'model_path'.
                   Pode ser None/vazio para treino sem alinhamento de features.

    Returns:
        DataFrame encodado e alinhado.
    """
    if artifacts is None:
        artifacts = {}

    df = df.copy()
    logger.debug(f"  Encoding: {len(df.columns)} colunas antes")

    # -----------------------------------------------------------------------
    # 1. Ordinal encoding
    # -----------------------------------------------------------------------
    variaveis_ordinais = config.ordinal_variables or {}

    for var, ordem in variaveis_ordinais.items():
        if var not in df.columns:
            continue
        if var == 'dia_semana':
            logger.debug(f"  Encoding ordinal: {var} já é numérico")
            continue
        mapeamento = {cat: i for i, cat in enumerate(ordem)}
        n_unmapped = (~df[var].isin(mapeamento) & df[var].notna()).sum()
        if n_unmapped > 0:
            logger.warning(f"  Encoding ordinal: {var} — {n_unmapped} valores não mapeados → NaN")
        df[var] = df[var].map(mapeamento)
        logger.debug(f"  Encoding ordinal: {var} → 0-{len(ordem)-1}")

    # -----------------------------------------------------------------------
    # 2. One-hot encoding — identificar variáveis categóricas
    # -----------------------------------------------------------------------
    max_unique = config.categorical_detection_max_unique or 20

    variaveis_one_hot = [
        col for col in df.columns
        if col not in ['target']
        and col not in variaveis_ordinais
        and col != 'nome_comprimento'
        and (df[col].dtype == 'object' or df[col].nunique() <= max_unique)
    ]

    logger.debug(f"  Encoding OHE: {len(variaveis_one_hot)} variáveis")
    df_encoded = pd.get_dummies(df, columns=variaveis_one_hot, prefix_sep='_', dtype=int)

    # -----------------------------------------------------------------------
    # 3. Remover features após encoding (#51)
    # -----------------------------------------------------------------------
    for col in (config.features_to_drop_after_encoding or []):
        if col in df_encoded.columns:
            df_encoded = df_encoded.drop(columns=[col])
            logger.debug(f"  Encoding: {col!r} removida (features_to_drop_after_encoding)")

    # -----------------------------------------------------------------------
    # 4. Remover colunas duplicadas
    # -----------------------------------------------------------------------
    n_antes = len(df_encoded.columns)
    df_encoded = df_encoded.loc[:, ~df_encoded.columns.duplicated()]
    n_dup = n_antes - len(df_encoded.columns)
    if n_dup > 0:
        logger.debug(f"  Encoding: {n_dup} colunas duplicadas removidas")

    # -----------------------------------------------------------------------
    # 5. Normalizar nomes das colunas (clean_column_names — produção canonical)
    # -----------------------------------------------------------------------
    df_encoded.columns = df_encoded.columns.str.replace('[^A-Za-z0-9_]', '_', regex=True)
    df_encoded.columns = df_encoded.columns.str.replace('__+', '_', regex=True)
    df_encoded.columns = df_encoded.columns.str.strip('_')

    # -----------------------------------------------------------------------
    # 6. Correções específicas de nome de coluna (#70 — mapeamentos_especificos)
    # -----------------------------------------------------------------------
    corrections = config.column_name_corrections or {}
    if corrections:
        current = set(df_encoded.columns)
        new_names = []
        for col in df_encoded.columns:
            new = corrections.get(col, col)
            if new in current and new != col:
                logger.warning(f"  Encoding: pulando correção {col!r} → {new!r} (coluna destino já existe)")
                new_names.append(col)
            else:
                new_names.append(new)
        df_encoded.columns = new_names

    logger.debug(f"  Encoding: {len(df_encoded.columns)} colunas após OHE + clean")

    # -----------------------------------------------------------------------
    # 7. Feature registry — garantir features esperadas e reordenar
    # -----------------------------------------------------------------------
    ordem_esperada = _load_feature_registry(artifacts)

    if ordem_esperada:
        missing = [col for col in ordem_esperada if col not in df_encoded.columns]
        if missing:
            logger.debug(f"  Encoding: {len(missing)} features faltantes criadas com 0")
            for col in missing:
                df_encoded[col] = 0

        ordered = [col for col in ordem_esperada if col in df_encoded.columns]
        extras = [col for col in df_encoded.columns if col not in ordem_esperada]
        if extras:
            logger.debug(f"  Encoding: {len(extras)} features extras (serão ignoradas pelo modelo)")
        df_encoded = df_encoded[ordered + extras]
        logger.debug(f"  Encoding: alinhado com feature registry — {len(df_encoded.columns)} colunas")
    else:
        logger.debug("  Encoding: feature registry não disponível — sem alinhamento de features")

    # -----------------------------------------------------------------------
    # 8. Preencher NaN remanescentes com 0
    # -----------------------------------------------------------------------
    nan_cols = df_encoded.columns[df_encoded.isna().any()].tolist()
    if nan_cols:
        logger.warning(f"  Encoding: {len(nan_cols)} colunas com NaN → preenchidas com 0")
        df_encoded = df_encoded.fillna(0)

    logger.debug(f"  Encoding: {len(df_encoded.columns)} colunas finais")
    return df_encoded
