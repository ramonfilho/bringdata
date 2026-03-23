"""
core/utils.py — Utilitários genéricos sem hardcodes.

Consolida funções presentes em múltiplos arquivos:
  - normalizar_telefone_robusto: matching_*.py (4 arquivos) + engineering.py
  - normalizar_email: matching_*.py (5 arquivos)
  - limpar_texto / normalizar_para_comparacao: category_unification.py + medium_training.py
  - remove_columns: feature_removal.py + preprocessing.py + column_unification_refactored.py
  - detect_problematic_columns: feature_removal.py:38-70 + preprocessing.py:176-181
  - clean_column_names: training_model.py:179-182 + encoding.py:238-240
  - align_features: prediction.py:179-229
  - UnionFind: training_model.py:410-428
"""

from __future__ import annotations

import re
from typing import List

import pandas as pd


def normalizar_telefone_robusto(telefone, country_code: int = 55,
                                phone_digits: List[int] = None) -> str:
    """
    Normaliza número de telefone para dígitos apenas, sem código de país.

    Aceita floats (notação científica), strings com pontuação, códigos de país.
    Retorna string de dígitos ou None se inválido.

    phone_digits: lista de comprimentos válidos após normalização (ex: [10, 11]).
                  None = aceita [8, 9, 10, 11].
    """
    if pd.isna(telefone):
        return None

    if isinstance(telefone, float):
        tel_str = str(int(telefone))
    else:
        tel_str = str(telefone)

    if 'e+' in tel_str.lower():
        try:
            tel_str = str(int(float(tel_str)))
        except Exception:
            pass

    tel_str = tel_str.replace('.0', '')
    digitos = re.sub(r'\D', '', tel_str)

    if len(digitos) < 8:
        return None

    country_prefix = str(country_code)
    if digitos.startswith(country_prefix) and len(digitos) > len(country_prefix) + 8:
        digitos = digitos[len(country_prefix):]

    valid_lengths = phone_digits if phone_digits else [8, 9, 10, 11]
    if len(digitos) in valid_lengths:
        return digitos

    return None


def normalizar_email(email) -> str:
    """Normaliza email: strip + lowercase. Retorna None se inválido."""
    if pd.isna(email):
        return None
    s = str(email).strip().lower()
    if '@' in s and s != 'nan' and len(s) > 5:
        return s
    return None


def limpar_texto(texto: str) -> str:
    """Remove acentos, converte para lowercase e strip."""
    raise NotImplementedError


def remove_columns(df: pd.DataFrame, columns: List[str],
                   errors: str = "ignore") -> pd.DataFrame:
    """Remove colunas do DataFrame. errors='ignore' ignora colunas ausentes."""
    return df.drop(columns=columns, errors=errors)


def detect_problematic_columns(df: pd.DataFrame) -> List[str]:
    """Detecta colunas com nome vazio, None, NaN ou comprimento <= 2."""
    problematic = []
    for col in df.columns:
        try:
            is_nan = pd.isna(col)
        except (TypeError, ValueError):
            is_nan = False

        if col is None or is_nan:
            problematic.append(col)
        elif col == '' or (isinstance(col, str) and col.strip() == ''):
            problematic.append(col)

    # Fallback: se nenhum claramente problemático, inclui nomes muito curtos
    if not problematic:
        for col in df.columns:
            if isinstance(col, str) and len(col.strip()) <= 2:
                problematic.append(col)

    return problematic


def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica regex [^A-Za-z0-9_] → '_' nos nomes de colunas."""
    raise NotImplementedError


def align_features(df: pd.DataFrame, expected_features: List[str]) -> pd.DataFrame:
    """Preenche features ausentes com 0 e reordena para expected_features."""
    raise NotImplementedError


class UnionFind:
    """Algoritmo de componentes conectados — consolida training_model.py:410-428."""

    def __init__(self, n: int):
        raise NotImplementedError

    def find(self, x: int) -> int:
        raise NotImplementedError

    def union(self, x: int, y: int) -> None:
        raise NotImplementedError
