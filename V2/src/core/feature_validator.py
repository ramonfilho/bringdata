"""
core/feature_validator.py — Validador pré-encoding de features [T1-11].

Valida que, antes do encoding, o DataFrame tem as features esperadas pela
pipeline, com os tipos corretos e valores dentro do domínio conhecido do
treino. Detecta a causa-raiz de bugs silenciosos como o histórico
Medium_Linguagem_programacao zerada por semanas.

Fluxo de uso:
    1. production_pipeline.py chama feature_engineering → cria features derivadas
    2. production_pipeline.py chama validate_pre_encoding(df, schema) → verifica integridade
    3. validate_pre_encoding emite log JSON estruturado com event=feature_validator
    4. production_pipeline.py chama apply_encoding → transforma em OHE/ordinal

Arquitetura em 3 camadas:
    - validate_pre_encoding(df, schema) → ValidationResult (runtime check)
    - build_schema_from_snapshot(snapshot_path, model_run_id) → PreEncodingSchema
      (builda contrato offline, uma vez, a partir do snapshot do treino)
    - PreEncodingSchema + PreEncodingColumnSchema (dataclasses de contrato)

Log estruturado (Cloud Logging):
    {
      "event": "feature_validator",
      "timestamp": "...",
      "model_run_id": "...",
      "batch_size": N,
      "features_checked": N,
      "issues": [...],
      "severity": "OK" | "INFO" | "WARNING" | "ERROR"
    }

Filtros Cloud Run Logs Explorer:
    - Só erros:     jsonPayload.event="feature_validator" AND jsonPayload.severity="ERROR"
    - Por feature:  jsonPayload.issues.feature="nome_valido"
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Contrato de schema
# ---------------------------------------------------------------------------

@dataclass
class PreEncodingColumnSchema:
    """Contrato de UMA coluna esperada pré-encoding."""
    name: str
    dtype_category: str  # 'numeric', 'bool', 'categorical', 'datetime', 'unknown'
    known_values: Optional[List[Any]] = None          # categorical: domínio do treino
    value_range: Optional[Tuple[float, float]] = None  # numeric: min/max observado no treino
    max_null_rate: float = 0.3                         # taxa de null tolerada


@dataclass
class PreEncodingSchema:
    """Contrato completo — todas as colunas esperadas pré-encoding."""
    columns: Dict[str, PreEncodingColumnSchema]
    model_run_id: str
    source: str  # ex: 'snapshot_encoding_input.pkl'
    generated_at: str


@dataclass
class ValidationIssue:
    """Uma instância de problema detectado em uma feature."""
    feature: str
    problem: str       # 'missing_column' | 'wrong_dtype' | 'null_rate_high' | 'new_categories' | 'value_out_of_range'
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Resultado de uma validação — consumido pelo production_pipeline."""
    severity: str      # 'OK' | 'INFO' | 'WARNING' | 'ERROR'
    issues: List[ValidationIssue]
    batch_size: int
    features_checked: int

    @property
    def has_errors(self) -> bool:
        return self.severity == 'ERROR'


# ---------------------------------------------------------------------------
# Construção do schema a partir de um snapshot
# ---------------------------------------------------------------------------

def _infer_dtype_category(series: pd.Series) -> str:
    """Classifica uma série em 'numeric', 'bool', 'categorical', 'datetime', 'unknown'."""
    if pd.api.types.is_bool_dtype(series):
        return 'bool'
    if pd.api.types.is_numeric_dtype(series):
        return 'numeric'
    if pd.api.types.is_datetime64_any_dtype(series):
        return 'datetime'
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_categorical_dtype(series):
        return 'categorical'
    return 'unknown'


def build_schema_from_snapshot(
    snapshot_path: str,
    model_run_id: str,
    null_rate_buffer: float = 0.1,
    max_known_values_categorical: int = 500,
) -> PreEncodingSchema:
    """
    Constrói PreEncodingSchema inspecionando um snapshot do input de encoding.

    Args:
        snapshot_path: caminho para um .pkl ou .parquet do DataFrame pós-FE
                       (ex: 'V2/tests/fixtures/snapshot_encoding_input.pkl')
        model_run_id:  ID do run MLflow do modelo para o qual esse schema é válido
        null_rate_buffer: margem adicionada sobre o null rate observado
                       (ex: se snapshot tem 2% null e buffer=0.1, tolera até 12%)
        max_known_values_categorical: limite para guardar known_values (evita
                       dicionários enormes para colunas quase-únicas)

    Returns:
        PreEncodingSchema pronto para usar em validate_pre_encoding().
    """
    snapshot_path = Path(snapshot_path)

    if snapshot_path.suffix == '.pkl':
        with open(snapshot_path, 'rb') as f:
            df: pd.DataFrame = pickle.load(f)
    elif snapshot_path.suffix == '.parquet':
        df = pd.read_parquet(snapshot_path)
    else:
        raise ValueError(f"Formato não suportado: {snapshot_path.suffix}")

    columns: Dict[str, PreEncodingColumnSchema] = {}

    for col_name in df.columns:
        series = df[col_name]
        dtype_cat = _infer_dtype_category(series)
        null_rate_observed = float(series.isna().mean())
        max_null = min(1.0, null_rate_observed + null_rate_buffer)

        col_schema = PreEncodingColumnSchema(
            name=col_name,
            dtype_category=dtype_cat,
            max_null_rate=max_null,
        )

        if dtype_cat == 'categorical':
            unique_values = series.dropna().unique().tolist()
            if len(unique_values) <= max_known_values_categorical:
                col_schema.known_values = sorted([str(v) for v in unique_values])
            else:
                logger.warning(
                    f"  [T1-11] {col_name}: {len(unique_values)} valores únicos "
                    f"(> {max_known_values_categorical}) — known_values não registrado; "
                    f"check de domínio será ignorado em runtime."
                )
        elif dtype_cat == 'numeric':
            col_schema.value_range = (
                float(series.min()),
                float(series.max()),
            )

        columns[col_name] = col_schema

    return PreEncodingSchema(
        columns=columns,
        model_run_id=model_run_id,
        source=str(snapshot_path),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Validação em runtime
# ---------------------------------------------------------------------------

def validate_pre_encoding(
    df: pd.DataFrame,
    schema: PreEncodingSchema,
    emit_log: bool = True,
) -> ValidationResult:
    """
    Valida um DataFrame contra um schema pré-encoding. Retorna ValidationResult
    e (opcionalmente) emite um log JSON estruturado.

    Severidades:
        - ERROR:   missing_column OU wrong_dtype OU null_rate_high em feature
                   listada no schema (modelo cego pra ela)
        - WARNING: new_categories em feature categórica (valor novo que o modelo
                   não viu — ainda scoreia mas o sinal é incerto)
        - INFO:    value_out_of_range em feature numérica (fora do range do
                   treino mas pode ser drift legítimo)
        - OK:      nenhuma issue

    Args:
        df:         DataFrame pós-feature_engineering, pré-apply_encoding
        schema:     Contrato construído via build_schema_from_snapshot
        emit_log:   Se True, emite log JSON filtrável no Cloud Logging

    Returns:
        ValidationResult com severity agregada + lista de issues detalhadas.
    """
    issues: List[ValidationIssue] = []

    for col_name, col_schema in schema.columns.items():
        # (1) Existência
        if col_name not in df.columns:
            issues.append(ValidationIssue(
                feature=col_name,
                problem='missing_column',
                details={'expected_dtype': col_schema.dtype_category},
            ))
            continue

        series = df[col_name]

        # (2) Dtype — compatibilidade ampla
        observed_dtype = _infer_dtype_category(series)
        if observed_dtype != col_schema.dtype_category:
            # Tolerância: numeric aceita bool (bool → 0/1 no encoding), e vice-versa limitadamente
            compatible = (
                (observed_dtype == 'bool' and col_schema.dtype_category == 'numeric') or
                (observed_dtype == 'numeric' and col_schema.dtype_category == 'bool')
            )
            if not compatible:
                issues.append(ValidationIssue(
                    feature=col_name,
                    problem='wrong_dtype',
                    details={
                        'expected': col_schema.dtype_category,
                        'observed': observed_dtype,
                    },
                ))

        # (3) Taxa de null
        null_rate = float(series.isna().mean())
        if null_rate > col_schema.max_null_rate:
            issues.append(ValidationIssue(
                feature=col_name,
                problem='null_rate_high',
                details={
                    'null_rate': null_rate,
                    'max_allowed': col_schema.max_null_rate,
                },
            ))

        # (4) Domínio (categorical)
        if col_schema.dtype_category == 'categorical' and col_schema.known_values:
            observed_values = set(str(v) for v in series.dropna().unique())
            unknown = observed_values - set(col_schema.known_values)
            if unknown:
                issues.append(ValidationIssue(
                    feature=col_name,
                    problem='new_categories',
                    details={
                        'unknown_values': sorted(list(unknown))[:20],  # limita para não poluir log
                        'known_count': len(col_schema.known_values),
                    },
                ))

        # (5) Range (numeric) — só INFO (pode ser drift legítimo)
        if col_schema.dtype_category == 'numeric' and col_schema.value_range and not series.dropna().empty:
            lo, hi = col_schema.value_range
            obs_lo = float(series.min())
            obs_hi = float(series.max())
            if obs_lo < lo or obs_hi > hi:
                issues.append(ValidationIssue(
                    feature=col_name,
                    problem='value_out_of_range',
                    details={
                        'expected_range': [lo, hi],
                        'observed_range': [obs_lo, obs_hi],
                    },
                ))

    # Agrega severidade
    if any(i.problem in ('missing_column', 'wrong_dtype', 'null_rate_high') for i in issues):
        severity = 'ERROR'
    elif any(i.problem == 'new_categories' for i in issues):
        severity = 'WARNING'
    elif any(i.problem == 'value_out_of_range' for i in issues):
        severity = 'INFO'
    else:
        severity = 'OK'

    result = ValidationResult(
        severity=severity,
        issues=issues,
        batch_size=len(df),
        features_checked=len(schema.columns),
    )

    if emit_log:
        _emit_structured_log(result, schema)

    return result


def load_zero_rate_baseline(run_id: str, baselines_dir: Optional[Path] = None) -> Optional[Dict[str, Dict[str, float]]]:
    """
    Carrega o baseline de "fração esperada de zero por coluna OHE" gerado por
    `scripts/generate_feature_zero_baselines.py` para um modelo específico.

    Returns:
        Dict {coluna_OHE: {'expected_nonzero_rate': float, 'expected_zero_rate': float, ...}}
        ou None se o baseline não existir (o validador deve degradar pra noop).
    """
    if baselines_dir is None:
        baselines_dir = Path(__file__).parent.parent.parent / 'configs' / 'feature_zero_baselines'
    path = baselines_dir / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        return payload.get('baselines', {}) or None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[T1-16] Falha ao ler baseline {path}: {e}")
        return None


def validate_post_encoding_zero_rates(
    df: pd.DataFrame,
    baseline: Dict[str, Dict[str, float]],
    min_batch_size: int = 50,
    min_expected_nonzero_rate: float = 0.15,
    max_drop_ratio: float = 0.3,
    emit_log: bool = True,
    model_run_id: str = '',
) -> ValidationResult:
    """
    [T1-16] Valida que as colunas OHE pós-encoding não estão massivamente
    zeradas em comparação com a distribuição esperada do treino.

    Cobre o caso onde o pipeline gera a coluna OHE mas todos (ou quase todos)
    os leads recebem 0 — sintoma de feature pré-OHE quebrada (mudança de
    casing do front, categoria sumindo, parsing JSONB falhando). Esse foi o
    mecanismo do Cluster 3 (Medium_Linguagem_programacao zerada por semanas),
    Cluster 4 e Cluster 5 do Erro 2.

    Disparo (`high_zero_rate`) ocorre quando:
      • a coluna OHE existe no baseline E
      • `expected_nonzero_rate ≥ min_expected_nonzero_rate` (filtro de ruído:
        categorias raras com expected 1-5% têm sample noise alto em batches
        pequenos; ignorá-las evita falso positivo) E
      • `observed_nonzero_rate < expected_nonzero_rate × max_drop_ratio`
        (categoria comum caiu pra menos da metade do esperado → bug provável).

    Args:
        df: DataFrame pós-`apply_encoding` (colunas OHE alinhadas ao registry).
        baseline: Dict carregado de `configs/feature_zero_baselines/{run_id}.json`.
        min_batch_size: tamanho mínimo do batch pra rodar a validação. Batches
                        menores que isso têm sample noise dominante; retorna OK
                        sem checar. Default 50 (= batch típico do polling Railway).
        min_expected_nonzero_rate: só checa colunas com expected ≥ esse valor.
                                   Default 15% — abaixo disso, sample noise>signal
                                   mesmo em batches de 50.
        max_drop_ratio: gatilho de queda relativa. Default 0.3 = "feature caiu
                        pra menos de 30% do esperado dispara alerta". Em batch=50
                        com expected=20%, sample noise ~6pp; threshold em 6%
                        (0.3*0.2) é claro o suficiente pra distinguir noise de bug.
        emit_log: se True, emite log estruturado tipo [FV_JSON].
        model_run_id: incluído no log estruturado pra rastreabilidade.

    Returns:
        ValidationResult com severity='ERROR' se houver coluna com queda > limite,
        'OK' caso contrário (ou batch pequeno demais pra avaliar).
    """
    if len(df) < min_batch_size:
        result = ValidationResult(severity='OK', issues=[], batch_size=len(df), features_checked=0)
        # Sem log nesse caso — batch pequeno é esperado em smoke / single
        return result

    issues: List[ValidationIssue] = []
    checked = 0

    for col, info in baseline.items():
        expected_nonzero = float(info.get('expected_nonzero_rate', 0.0))
        if expected_nonzero < min_expected_nonzero_rate:
            continue
        if col not in df.columns:
            continue
        checked += 1
        # Coluna OHE — qualquer valor != 0 conta como "ativa". Tolerância pra
        # numéricos float: != 0 quase sempre é exato porque OHE produz int 0/1.
        observed_nonzero = float((df[col] != 0).mean())
        if observed_nonzero < expected_nonzero * max_drop_ratio:
            issues.append(ValidationIssue(
                feature=col,
                problem='high_zero_rate',
                details={
                    'expected_nonzero_rate': round(expected_nonzero, 4),
                    'observed_nonzero_rate': round(observed_nonzero, 4),
                    'drop_ratio': round(observed_nonzero / expected_nonzero if expected_nonzero else 0.0, 3),
                    'category': info.get('category'),
                    'feature_pre_ohe': info.get('feature'),
                },
            ))

    severity = 'ERROR' if issues else 'OK'
    result = ValidationResult(severity=severity, issues=issues, batch_size=len(df), features_checked=checked)

    if emit_log:
        payload = {
            'event': 'feature_validator_post_encoding',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'model_run_id': model_run_id,
            'batch_size': result.batch_size,
            'features_checked': result.features_checked,
            'severity': result.severity,
            'min_expected_nonzero_rate': min_expected_nonzero_rate,
            'max_drop_ratio': max_drop_ratio,
            'issues': [asdict(i) for i in issues],
        }
        json_line = "[FV_JSON] " + json.dumps(payload, default=str, separators=(',', ':'))
        logger.info(json_line)
        if severity == 'ERROR':
            preview = ', '.join(f"{i.feature}={i.details['observed_nonzero_rate']:.3f}<{i.details['expected_nonzero_rate']:.3f}" for i in issues[:3])
            logger.error(
                f"[T1-16] feature zerada em massa pós-encoding ({len(issues)} colunas, batch={result.batch_size}): {preview}"
            )

    return result


def validate_post_encoding_all_zero_groups(
    df: pd.DataFrame,
    baseline: Dict[str, Dict[str, float]],
    min_batch_size: int = 50,
    min_group_size: int = 2,
    max_all_zero_rate: float = 0.02,
    emit_log: bool = True,
    model_run_id: str = '',
    df_pre_ohe: Optional[pd.DataFrame] = None,
) -> ValidationResult:
    """
    [DT-19 pré-req C] Valida que, para cada grupo de colunas OHE derivado da
    mesma feature pré-OHE (ex.: `Source_facebook_ads`, `Source_google_ads`,
    `Source_outros`), NÃO existe uma fração significativa de leads com TODAS
    as colunas do grupo simultaneamente zeradas.

    Diferença do T1-16: o T1-16 dispara quando UMA coluna OHE específica caiu
    pra perto de zero em comparação com o esperado. Este checker dispara quando
    um lead recebe zero em TODAS as colunas do grupo OHE — sintoma do bug
    "categoria nova passou pela unificação sem cair em `_outros`". Exatamente
    o caso do Source TikTok no path Champion (cenário 1.2 da auditoria de
    quebra de produção): `unify_utm` não é variant-aware ainda, então um lead
    `Source=tiktok` cruzando o Champion (que só conhece facebook_ads/google_ads/
    outros) acaba com Source_facebook_ads=0, Source_google_ads=0, Source_outros=0.

    O agrupamento usa o campo `feature` do baseline gerado por
    `scripts/generate_feature_zero_baselines.py`. Grupos com <`min_group_size`
    colunas (≥2 por default) são ignorados — feature binária pura não tem
    "todas zeradas" patológico (a única coluna OHE = 0 já é o valor de "Não").

    Qualificação "bruto presente" (Correção 2 — 2026-05-19): quando `df_pre_ohe`
    é fornecido, só conta como violação de conservação o lead cujo valor BRUTO
    pré-OHE daquele grupo CHEGOU PREENCHIDO. Lead que chegou sem o valor (ex.:
    UTM vazia/ausente — `unify_utm` transforma vazio em nulo de propósito via a
    guarda `.notna()`) tem o grupo zerado como saída ESPERADA, não como bug de
    encoding. Sem `df_pre_ohe` (ou para grupos cujo nome pré-OHE não bate com
    uma coluna de `df_pre_ohe`) o comportamento é o histórico (conta todo
    lead com o grupo zerado). Causa-raiz e dado real: registro_erros_ml.md
    § V.6; o bug que se quer pegar = bruto presente mas nenhuma coluna acendeu
    (Cluster 3 / cenário 1.2).

    Args:
        df: DataFrame pós-`apply_encoding` (colunas OHE).
        baseline: dict {coluna_OHE: {'feature': str, 'category': str, ...}}.
        min_batch_size: tamanho mínimo do batch (default 50, igual T1-16).
        min_group_size: número mínimo de colunas OHE no grupo pra checar.
        max_all_zero_rate: fração máxima de leads com todas as colunas do grupo
                           zeradas. Default 2% — tolerante a leads legítimos
                           sem aquela feature, mas pega bug arquitetural.
        df_pre_ohe: DataFrame pré-`get_dummies` (pós-unify), mesma ordem de
                    linhas de `df`. Habilita a qualificação "bruto presente".

    Returns:
        ValidationResult com severity='ERROR' se algum grupo ultrapassa o
        limiar, 'OK' caso contrário.
    """
    if len(df) < min_batch_size:
        return ValidationResult(severity='OK', issues=[], batch_size=len(df), features_checked=0)

    # Agrupar colunas OHE pelo nome da feature pré-OHE (campo 'feature' do baseline).
    groups: Dict[str, List[str]] = {}
    for col, info in baseline.items():
        feat = info.get('feature')
        if not feat or col not in df.columns:
            continue
        groups.setdefault(feat, []).append(col)

    issues: List[ValidationIssue] = []
    checked = 0
    batch_size = len(df)

    for feat, cols in groups.items():
        if len(cols) < min_group_size:
            continue
        checked += 1
        # Todas zeradas = soma da linha == 0 em todas as colunas do grupo.
        # OHE produz 0/1 inteiros, então sum() == 0 sse todas == 0.
        all_zero = (df[cols].sum(axis=1) == 0)

        # [Correção 2 — 2026-05-19] Qualificação "bruto presente": só conta
        # como violação o lead cujo valor bruto pré-OHE daquele grupo chegou
        # PREENCHIDO. UTM vazia/ausente → grupo zerado é esperado, não bug.
        # Sem df_pre_ohe ou grupo sem coluna bruta correspondente → histórico.
        raw_qualified = False
        if df_pre_ohe is not None and feat in df_pre_ohe.columns:
            raw = df_pre_ohe[feat].reindex(df.index)
            raw_present = raw.notna() & (raw.astype(str).str.strip() != '')
            violating = (all_zero & raw_present)
            raw_qualified = True
        else:
            violating = all_zero

        n_all_zero = int(all_zero.sum())
        n_violating = int(violating.sum())
        # Taxa que o gating usa = fração QUALIFICADA (bruto presente + zerado).
        all_zero_rate = float(violating.mean())
        if all_zero_rate > max_all_zero_rate:
            issues.append(ValidationIssue(
                feature=feat,
                problem='all_zero_group',
                details={
                    'feature_pre_ohe': feat,
                    'group_columns': cols,
                    'all_zero_rate': round(all_zero_rate, 4),
                    'threshold': max_all_zero_rate,
                    'leads_with_group_zeroed': n_all_zero,
                    'leads_raw_present_but_zeroed': n_violating,
                    'raw_presence_qualified': raw_qualified,
                },
            ))

    severity = 'ERROR' if issues else 'OK'
    result = ValidationResult(severity=severity, issues=issues, batch_size=batch_size, features_checked=checked)

    if emit_log:
        payload = {
            'event': 'feature_validator_all_zero_group',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'model_run_id': model_run_id,
            'batch_size': batch_size,
            'groups_checked': checked,
            'severity': severity,
            'max_all_zero_rate': max_all_zero_rate,
            'issues': [asdict(i) for i in issues],
        }
        logger.info("[FV_JSON] " + json.dumps(payload, default=str, separators=(',', ':')))
        if severity == 'ERROR':
            preview = ', '.join(f"{i.feature}={i.details['all_zero_rate']:.3f}" for i in issues[:3])
            logger.error(
                f"[DT-19 cross-col] {len(issues)} grupo(s) OHE com fração de leads "
                f"todo-zerados acima do limiar (batch={batch_size}): {preview}"
            )

    return result


def save_schema_to_json(schema: PreEncodingSchema, path: str) -> None:
    """Serializa um PreEncodingSchema para JSON (versionável no git)."""
    payload = {
        'model_run_id': schema.model_run_id,
        'source': schema.source,
        'generated_at': schema.generated_at,
        'columns': {
            name: {
                'dtype_category': col.dtype_category,
                'known_values': col.known_values,
                'value_range': list(col.value_range) if col.value_range else None,
                'max_null_rate': col.max_null_rate,
            }
            for name, col in schema.columns.items()
        },
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(payload, f, indent=2, sort_keys=True, default=str)


def load_schema_from_json(path: str) -> PreEncodingSchema:
    """Carrega um PreEncodingSchema serializado em JSON."""
    with open(path, 'r') as f:
        payload = json.load(f)

    columns = {}
    for name, col_data in payload['columns'].items():
        range_ = col_data.get('value_range')
        columns[name] = PreEncodingColumnSchema(
            name=name,
            dtype_category=col_data['dtype_category'],
            known_values=col_data.get('known_values'),
            value_range=tuple(range_) if range_ else None,
            max_null_rate=col_data.get('max_null_rate', 0.3),
        )

    return PreEncodingSchema(
        columns=columns,
        model_run_id=payload['model_run_id'],
        source=payload['source'],
        generated_at=payload['generated_at'],
    )


def _emit_structured_log(result: ValidationResult, schema: PreEncodingSchema) -> None:
    """
    Emite log JSON estruturado para Cloud Logging.

    Formato: sempre emite uma linha prefixada com [FV_JSON] contendo JSON válido,
    para facilitar parsing via `gcloud logging read` + grep + json.loads.
    Linha legível (severity + resumo) vai separadamente no nível apropriado do logger.
    """
    payload = {
        'event': 'feature_validator',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'model_run_id': schema.model_run_id,
        'batch_size': result.batch_size,
        'features_checked': result.features_checked,
        'severity': result.severity,
        'issues': [asdict(i) for i in result.issues],
    }

    json_line = "[FV_JSON] " + json.dumps(payload, default=str, separators=(',', ':'))
    human_msg = f"[T1-11] feature_validator severity={result.severity} batch={result.batch_size} issues={len(result.issues)}"

    # Linha JSON sempre em INFO (visível e filtrável); severity específica na linha humana
    logger.info(json_line)

    if result.severity == 'ERROR':
        logger.error(human_msg)
    elif result.severity == 'WARNING':
        logger.warning(human_msg)
    elif result.severity == 'INFO':
        logger.info(human_msg)
    else:
        logger.debug(human_msg)
