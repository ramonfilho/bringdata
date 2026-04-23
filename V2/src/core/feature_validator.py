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
