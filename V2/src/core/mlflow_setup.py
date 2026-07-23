"""
core/mlflow_setup.py — Fonte única da URI de tracking do MLflow.

Um só lugar define para onde treino, ativação de run e gerador de model card
leem/escrevem (backend Postgres). Antes a URI (com credencial) vivia embutida
no training_model; centralizar evita que o gerador standalone caia num MLflow
local vazio por esquecer de setá-la, e deixa um único ponto pra trocar o host.

Respeita override por ambiente (MLFLOW_TRACKING_URI), como o treino já fazia.
"""

from __future__ import annotations

import os

# Backend de tracking do projeto (mesmo host do ledger). Override via env var.
DEFAULT_TRACKING_URI = (
    "postgresql+psycopg2://postgres:SmartAds2026DB!@104.197.138.129:5432/mlflow"
)


def resolve_tracking_uri() -> str:
    """URI efetiva: env MLFLOW_TRACKING_URI se setada, senão o default do projeto."""
    return os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)


def ensure_tracking_uri() -> str:
    """Aponta o MLflow pro backend do projeto e devolve a URI usada. Idempotente."""
    import mlflow
    uri = resolve_tracking_uri()
    mlflow.set_tracking_uri(uri)
    return uri
