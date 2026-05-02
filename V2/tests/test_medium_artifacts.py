"""
[E2] Integration test do unify_medium em modo whitelist (artifacts reais).

Cobre o caminho que o parity_audit não cobre: garante que produção
realmente carrega valid_categories do artifact do modelo ativo (e não
cai silenciosamente no fallback de frequência por batch).

Foi exatamente esse o bug consertado em d711227 — o parity sintético
passava porque ambos os lados (treino e produção) tinham o mesmo path
errado e ambos retornavam None, então o batch era idêntico no fixture
mas a whitelist canônica nunca era exercitada.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from src.core.client_config import ClientConfig
from src.core.medium import _load_valid_categories, unify_medium


def _active_run_id() -> str:
    # Tenta o padrão por-cliente primeiro (estado atual do refactor),
    # depois o legado single-file. Mantém o teste robusto a essa migração.
    candidates = [
        ROOT / 'configs' / 'active_models' / 'devclub.yaml',
        ROOT / 'configs' / 'active_model.yaml',
    ]
    cfg_path = next((p for p in candidates if p.exists()), None)
    if cfg_path is None:
        pytest.skip(f"active_model yaml não encontrado em {[str(p) for p in candidates]}")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    run_id = (cfg.get('active_model') or {}).get('mlflow_run_id')
    if not run_id:
        pytest.skip(f"{cfg_path.name} sem mlflow_run_id")
    artifact_dir = ROOT / 'mlruns' / '1' / run_id / 'artifacts' / 'model'
    if not artifact_dir.exists():
        pytest.skip(f"Artifact local do modelo ativo não disponível: {artifact_dir}")
    return run_id


def test_load_valid_categories_active_model_returns_canonical_whitelist():
    """Modelo ativo deve carregar pelo menos 4 categorias canônicas."""
    run_id = _active_run_id()
    valid = _load_valid_categories({'mlflow_run_id': run_id})

    assert valid is not None, (
        "_load_valid_categories devolveu None para o modelo ativo — "
        "_load no path errado mascarou esse bug por 6 semanas (commit 2df0671)."
    )
    assert len(valid) >= 4, f"Whitelist suspeita ({len(valid)} categorias): {valid}"
    # 'Outros' e 'nan' NÃO devem estar na whitelist (ficam de fora por design).
    assert 'Outros' not in valid
    assert 'nan' not in valid


def test_load_valid_categories_failloud_when_path_missing():
    """E1: produção pediu artifacts mas path não existe → exceção alta."""
    with pytest.raises(FileNotFoundError, match="Medium whitelist não encontrada"):
        _load_valid_categories({'mlflow_run_id': 'run_id_inexistente_xxxxx'})


def test_load_valid_categories_training_mode_returns_none():
    """Modo treino (artifacts={}) continua retornando None — sem exceção."""
    assert _load_valid_categories({}) is None


def test_unify_medium_active_artifacts_clamps_unknown_to_outros():
    """
    Smoke real: chamar unify_medium em modo produção (artifacts) faz com
    que valores Medium fora da whitelist canônica virem 'Outros'.

    Antes do fix do path em d711227, esse teste falharia: o lado produção
    silenciosamente caía em modo treino-frequência e o lixo passava cru.
    """
    run_id = _active_run_id()
    cfg_path = ROOT / 'configs' / 'clients' / 'devclub.yaml'
    if not cfg_path.exists():
        pytest.skip(f"devclub.yaml não encontrado em {cfg_path}")
    client_cfg = ClientConfig.from_yaml(str(cfg_path))

    # Pega 1 categoria canônica conhecida do whitelist real do modelo
    whitelist = _load_valid_categories({'mlflow_run_id': run_id})
    canonical_sample = whitelist[0]
    rogue_value = 'DEV-AD9999-tag-fake-vid-captacao-V0-ST_TestSmoke.mov'

    df = pd.DataFrame({
        'Medium': [canonical_sample, rogue_value, canonical_sample, rogue_value]
    })
    out = unify_medium(df, client_cfg.medium, {'mlflow_run_id': run_id})

    # Canônica preservada
    assert (out['Medium'] == canonical_sample).sum() == 2, (
        f"Categoria canônica '{canonical_sample}' deveria ter sido preservada — "
        f"resultado: {out['Medium'].tolist()}"
    )
    # Lixo virou 'Outros'
    assert (out['Medium'] == 'Outros').sum() == 2, (
        f"Valor fora da whitelist deveria ter virado 'Outros' — "
        f"resultado: {out['Medium'].tolist()}. Se ficou cru, suspeitar de "
        f"regressão no caminho do artifact (cf. d711227)."
    )
    # Garantia explícita: não pode ter sobrado Medium não-canônico
    extras = set(out['Medium'].unique()) - set(whitelist) - {'Outros'}
    assert not extras, f"Valores não esperados em Medium pós-unify: {extras}"
