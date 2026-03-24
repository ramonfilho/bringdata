"""
core/validation.py — Validação de schema e qualidade de dados pré-treino.

Dois pontos de uso no train_pipeline.py:
  1. validate_ingestion(): após Célula 4
     Valida colunas obrigatórias, tamanho do dataset e parseabilidade de datas
     no df_pesquisa e df_vendas brutos. É o ponto crítico para detectar
     problemas de ingestão de um novo cliente (formulário diferente, nomes
     de colunas distintos, encoding errado).

  2. validate_features(): após Célula 8
     Valida missing rates das features críticas contra thresholds configurados.
     Substitui o bloco colunas_criticas_modelo hardcoded no pipeline.

Hardcodes migrados:
  colunas_criticas_modelo (train_pipeline.py) → ValidationConfig.feature_missing_thresholds
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .client_config import ValidationConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def log(self, label: str) -> None:
        if self.errors:
            for msg in self.errors:
                logger.error(f"  ❌ {msg}")
        if self.warnings:
            for msg in self.warnings:
                logger.warning(f"  ⚠️  {msg}")
        if self.passed and not self.warnings:
            logger.info(f"  ✅ {label}: OK")


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _check_required_columns(df: pd.DataFrame, required: List[str], label: str) -> List[str]:
    """Retorna lista de erros para colunas ausentes."""
    missing = [c for c in required if c not in df.columns]
    return [f"{label}: coluna obrigatória ausente — '{c}'" for c in missing]


def _check_date_parseability(df: pd.DataFrame, col: str, min_rate: float) -> Optional[str]:
    """Retorna erro se menos de min_rate das datas são parseáveis."""
    if col not in df.columns:
        return None
    parsed = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
    rate = parsed.notna().mean()
    if rate < min_rate:
        return (
            f"Coluna '{col}': apenas {rate*100:.1f}% das datas são parseáveis "
            f"(mínimo: {min_rate*100:.0f}%)"
        )
    return None


def _check_missing_rates(
    df: pd.DataFrame,
    thresholds: Dict[str, float],
) -> tuple[List[str], List[str]]:
    """
    Retorna (erros, avisos) para colunas com missing rate acima do threshold.

    Aviso quando coluna não existe no DataFrame (pode ter sido removida
    legitimamente pela Célula 8 — não é erro fatal).
    """
    errors: List[str] = []
    warnings: List[str] = []

    for col, max_rate in thresholds.items():
        # Busca exata primeiro, depois por prefixo (nomes truncados)
        if col in df.columns:
            rate = df[col].isnull().mean()
            if rate > max_rate:
                errors.append(
                    f"Feature '{col}': missing rate {rate*100:.1f}% > threshold {max_rate*100:.0f}%"
                )
        else:
            # Tenta prefixo (colunas com nomes longos truncados)
            candidates = [c for c in df.columns if c.startswith(col[:30])]
            if candidates:
                rate = df[candidates[0]].isnull().mean()
                if rate > max_rate:
                    errors.append(
                        f"Feature '{candidates[0]}' (via prefixo de '{col}'): "
                        f"missing rate {rate*100:.1f}% > threshold {max_rate*100:.0f}%"
                    )
            else:
                warnings.append(f"Feature '{col}' não encontrada após Célula 8 (pode ter sido removida)")

    return errors, warnings


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def validate_ingestion(
    df_pesquisa: pd.DataFrame,
    df_vendas: pd.DataFrame,
    config: ValidationConfig,
) -> ValidationResult:
    """
    Valida schema bruto de df_pesquisa e df_vendas (pós-Célula 4, pré-Célula 5).

    Verifica:
    - Colunas obrigatórias presentes
    - Dataset não vazio (>= min_survey_records)
    - Coluna de data com taxa mínima de parseabilidade
    - Coluna de email com missing rate abaixo do threshold

    Args:
        df_pesquisa: DataFrame de leads (respostas do formulário)
        df_vendas:   DataFrame de vendas (Guru + TMB)
        config:      ValidationConfig do ClientConfig

    Returns:
        ValidationResult com passed=True se nenhum erro fatal foi encontrado.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Colunas obrigatórias
    if config.required_survey_columns:
        errors += _check_required_columns(df_pesquisa, config.required_survey_columns, "df_pesquisa")
    if config.required_sales_columns:
        errors += _check_required_columns(df_vendas, config.required_sales_columns, "df_vendas")

    # 2. Tamanho mínimo
    if len(df_pesquisa) < config.min_survey_records:
        errors.append(
            f"df_pesquisa tem apenas {len(df_pesquisa):,} registros "
            f"(mínimo: {config.min_survey_records:,}) — possível falha na ingestão"
        )

    # 3. Parseabilidade de datas
    date_col = 'Data' if 'Data' in df_pesquisa.columns else None
    if date_col:
        err = _check_date_parseability(df_pesquisa, date_col, config.min_date_parse_rate)
        if err:
            errors.append(err)
    else:
        warnings.append("Coluna 'Data' não encontrada em df_pesquisa")

    # 4. Missing rate de email
    email_col = next((c for c in df_pesquisa.columns if c.lower() in ('e-mail', 'email')), None)
    if email_col:
        rate = df_pesquisa[email_col].isnull().mean()
        if rate > config.max_email_missing_rate:
            errors.append(
                f"Coluna '{email_col}': missing rate de email {rate*100:.1f}% "
                f"> threshold {config.max_email_missing_rate*100:.0f}% — matching será prejudicado"
            )
    else:
        warnings.append("Coluna de email não encontrada em df_pesquisa")

    return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)


def validate_features(
    df: pd.DataFrame,
    config: ValidationConfig,
) -> ValidationResult:
    """
    Valida missing rates das features críticas (pós-Célula 8, pré-quality gate).

    Substitui o bloco colunas_criticas_modelo hardcoded no train_pipeline.py.
    Os thresholds vêm de ValidationConfig.feature_missing_thresholds no YAML.

    Args:
        df:     DataFrame pós-remoção de features desnecessárias (Célula 8)
        config: ValidationConfig do ClientConfig

    Returns:
        ValidationResult. Se feature_missing_thresholds for None, retorna passed=True sem checks.
    """
    if not config.feature_missing_thresholds:
        return ValidationResult(passed=True)

    errors, warnings = _check_missing_rates(df, config.feature_missing_thresholds)
    return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)
