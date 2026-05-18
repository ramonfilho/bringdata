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
# [T1-10] Feature coverage check
# ---------------------------------------------------------------------------

def _load_top_features(artifacts: Dict[str, Any], min_importance: float = 0.01) -> List[Dict[str, Any]]:
    """
    [T1-10] Carrega top features (importância >= min_importance) do feature_registry.

    Reutiliza a mesma lógica de resolução de path que _load_feature_registry.
    Retorna lista vazia se não disponível — o check degrada graciosamente,
    sem impedir o encoding de rodar.

    Returns:
        Lista de dicts: [{'name': str, 'importance': float, 'rank': int}, ...]
    """
    mlflow_run_id = artifacts.get('mlflow_run_id')
    model_path = artifacts.get('model_path')
    registry_path: Optional[Path] = None

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

    if (registry_path is None or not registry_path.exists()) and model_path:
        for candidate in list(Path(model_path).glob("feature_registry*.json"))[:1]:
            registry_path = candidate
            break

    if registry_path is None or not registry_path.exists():
        return []

    try:
        with open(registry_path, 'r') as f:
            data = json.load(f)
        top = data.get('feature_importance', {}).get('top_10_features', [])
        result = []
        for item in top:
            imp = item.get('importance', 0)
            if imp >= min_importance:
                result.append({
                    'name': item.get('feature_clean') or item.get('feature_original', ''),
                    'importance': imp,
                    'rank': item.get('rank', 0),
                })
        return result
    except Exception as e:
        logger.warning(f"  [T1-10] Erro ao ler top features de {registry_path}: {e}")
        return []


# ---------------------------------------------------------------------------
# Merge de configs de encoding (DT-12)
# ---------------------------------------------------------------------------

def merge_encoding(
    base: "EncodingConfig",
    override: Optional["EncodingConfig"],
) -> "EncodingConfig":
    """
    Retorna um EncodingConfig efetivo: copia base e aplica campos não-None do override.

    ordinal_variables é merged (union de dicts — override vence conflitos de chave),
    para que o override adicione/substitua mapeamentos sem perder os do cliente base
    (ex: dia_semana do cliente + Qual a sua idade? da variante).

    Usado por production_pipeline.preprocess(encoding_overrides) — DT-12.
    """
    if override is None:
        return base

    from .client_config import EncodingConfig as _EC

    merged_ordinal = dict(base.ordinal_variables or {})
    if override.ordinal_variables:
        merged_ordinal.update(override.ordinal_variables)

    return _EC(
        ordinal_variables=merged_ordinal if merged_ordinal else None,
        categorical_detection_max_unique=(
            override.categorical_detection_max_unique
            if override.categorical_detection_max_unique != 20
            else base.categorical_detection_max_unique
        ),
        features_to_drop_after_encoding=(
            override.features_to_drop_after_encoding
            if override.features_to_drop_after_encoding is not None
            else base.features_to_drop_after_encoding
        ),
        column_name_corrections=(
            override.column_name_corrections
            if override.column_name_corrections is not None
            else base.column_name_corrections
        ),
    )


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
            raise KeyError(
                f"[T1-1] Encoding ordinal: '{var}' não encontrada no DataFrame. "
                f"Verificar yaml vs nomes reais das colunas. "
                f"Colunas candidatas: {[c for c in df.columns if 'idade' in c.lower() or 'salar' in c.lower()]}"
            )
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

        # [T1-10] Feature coverage check — ANTES do fill com 0.
        # Motivação: uma vez preenchida com 0, a feature parece existir mas o
        # modelo está cego para seu sinal. Detectar ausência de features críticas
        # (top 10 por importância no modelo ativo) antes da homogeneização.
        if missing:
            top_features = _load_top_features(artifacts, min_importance=0.01)
            if top_features:
                missing_set = set(missing)
                critical_missing = [f for f in top_features if f['name'] in missing_set]
                for f in critical_missing:
                    msg = (
                        f"  [T1-10] Feature CRÍTICA ausente do DataFrame: '{f['name']}' "
                        f"(rank {f['rank']}, importância {f['importance']*100:.2f}%) "
                        f"— será preenchida com 0, modelo fica cego para esse sinal"
                    )
                    if f['importance'] >= 0.05:
                        logger.error(msg)
                    else:
                        logger.warning(msg)

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

    # -----------------------------------------------------------------------
    # 9. [T1-16] Sensor pós-encoding "feature caiu vs distribuição do treino"
    #    — OBSERVA, NÃO BLOQUEIA (rebaixado em 2026-05-18, ver § abaixo).
    # -----------------------------------------------------------------------
    # Mede o quanto a taxa de ativação de cada coluna OHE caiu em relação à
    # distribuição capturada NO TREINO. Esse critério confunde duas causas
    # opostas: feature quebrada por bug E mix de tráfego que mudou de verdade
    # (campanha trocou de Facebook pra Google). Por isso ele NÃO bloqueia mais
    # o batch — só emite o log estruturado [FV_JSON] como sensor observável.
    #
    # Quem bloqueia agora é o passo 9b (grupo OHE todo-zerado): esse SIM é o
    # teste de conservação pré-OHE↔pós-OHE — independe da distribuição de
    # treino e só dispara quando um lead com valor válido não ativa NENHUMA
    # coluna do grupo (parsing/casing/categoria sumindo = Cluster 3/4/5).
    # Causa-raiz do falso positivo e desenho da correção: registro_erros_ml.md
    # § V.5 e PLANO_SAFEGUARD "Validador pós-encoding" (revisão 18/05/2026).
    _mlflow_run_id = artifacts.get('mlflow_run_id') if artifacts else None
    if _mlflow_run_id:
        try:
            from .feature_validator import (
                load_zero_rate_baseline as _load_zero_baseline,
                validate_post_encoding_zero_rates as _validate_zero_rates,
            )
            _baseline = _load_zero_baseline(_mlflow_run_id)
            if _baseline:
                _zr_result = _validate_zero_rates(
                    df_encoded, _baseline,
                    model_run_id=_mlflow_run_id,
                    emit_log=True,
                )
                if _zr_result.severity == 'ERROR':
                    # Observa-mas-não-bloqueia: pode ser bug OU shift legítimo
                    # de mix de tráfego. O log [FV_JSON] (emit_log=True acima)
                    # mantém o sinal pra investigação; o bloqueio fica a cargo
                    # do teste de conservação no passo 9b.
                    preview = ', '.join(
                        f"{i.feature} (obs={i.details['observed_nonzero_rate']:.3f} "
                        f"vs exp={i.details['expected_nonzero_rate']:.3f})"
                        for i in _zr_result.issues[:5]
                    )
                    logger.warning(
                        f"  [T1-16] (observa, NÃO bloqueia) {len(_zr_result.issues)} colunas OHE "
                        f"caíram vs distribuição do treino (batch={_zr_result.batch_size}, "
                        f"mlflow_run_id={_mlflow_run_id[:8]}). Exemplos: {preview}. "
                        f"Conformidade com o treino ≠ bug (mix de tráfego pode ter mudado) "
                        f"— ver registro_erros_ml.md § V.5. Bloqueio fica no passo 9b (conservação)."
                    )
            else:
                logger.debug(
                    f"  [T1-16] baseline de zero-rate não encontrado pro run_id={_mlflow_run_id[:8]} "
                    f"(gere com `python -m V2.scripts.generate_feature_zero_baselines`)"
                )
        except Exception as _e:
            # Sensor é defensivo — qualquer falha dele NÃO deve quebrar scoring.
            logger.warning(f"  [T1-16] sensor post-encoding falhou: {type(_e).__name__}: {_e}")

    # -----------------------------------------------------------------------
    # 9b. [DT-19 pré-req C] Validador cross-coluna "grupo OHE todo-zerado"
    # -----------------------------------------------------------------------
    # Detecta o sintoma do cenário 1.2 da AUDITORIA_QUEBRA_PRODUCAO: lead com
    # categoria nova (ex.: Source=tiktok no path Champion) acaba com TODAS as
    # colunas Source_* zeradas porque a unificação não jogou pra _outros.
    # Sensor aditivo (não bloqueia o caminho do T1-16). Default 2% de tolerância
    # cobre leads legítimos sem aquela feature mas pega bug arquitetural.
    if _mlflow_run_id:
        try:
            from .feature_validator import (
                validate_post_encoding_all_zero_groups as _validate_zero_groups,
            )
            if _baseline:
                _zg_result = _validate_zero_groups(
                    df_encoded, _baseline,
                    model_run_id=_mlflow_run_id,
                    emit_log=True,
                )
                if _zg_result.severity == 'ERROR':
                    preview = ', '.join(
                        f"{i.feature}={i.details['all_zero_rate']:.3f} ({i.details['leads_with_group_zeroed']} leads)"
                        for i in _zg_result.issues[:5]
                    )
                    raise ValueError(
                        f"[DT-19] {len(_zg_result.issues)} grupo(s) OHE com leads "
                        f"todo-zerados acima do limiar (batch={_zg_result.batch_size}, "
                        f"mlflow_run_id={_mlflow_run_id[:8]}). Exemplos: {preview}. "
                        f"Cenário 1.2 da auditoria — categoria fora da whitelist da variante."
                    )
        except ValueError:
            raise
        except Exception as _e:
            logger.warning(f"  [DT-19 cross-col] validador falhou: {type(_e).__name__}: {_e}")

    logger.debug(f"  Encoding: {len(df_encoded.columns)} colunas finais")
    return df_encoded
