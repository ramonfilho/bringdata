"""Resolução de papéis A/B (champion / challenger) a partir do pipeline.

Fonte ÚNICA da lógica "quem é champion, quem é challenger" — vive em `src/`
porque o caminho de scoring online (`src/scoring/service.py`) e o refresh em lote
(`api/scores_refresh.py`) precisam da mesma resolução, e `src/` não pode importar
de `api/` (direção de dependência). Antes esta função morava em
`api/scores_refresh._resolve_variantes` (cópia local); agora ambos consomem daqui.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def resolve_champion_challenger(pipeline) -> Optional[Dict[str, Dict[str, Any]]]:
    """Mapeia champion/challenger → (variant_name, run_id, encoding_overrides) a
    partir do A/B config do pipeline.

    Champion = variante cujo run_id == o do active_model (`pipeline.predictor`);
    challenger = a outra. Retorna None se o A/B não está habilitado ou não dá pra
    identificar os dois papéis — o caller degrada (não grava os decis dos 2).
    """
    ab = getattr(pipeline, "_ab_test_config", None)
    if not ab or not getattr(ab, "enabled", False):
        return None
    variants = getattr(ab, "variants", None) or {}
    if len(variants) < 2:
        return None
    champ_run = getattr(getattr(pipeline, "predictor", None), "mlflow_run_id", None)
    if not champ_run:
        return None

    champion = challenger = None
    for vname, v in variants.items():
        run_id = getattr(v, "run_id", None)
        info = {
            "variant_name": vname,
            "run_id": run_id,
            "encoding_overrides": getattr(v, "encoding_overrides", None),
        }
        if run_id == champ_run and champion is None:
            champion = info
        else:
            challenger = info
    if not champion or not challenger or not challenger["run_id"]:
        return None
    return {"champion": champion, "challenger": challenger}
