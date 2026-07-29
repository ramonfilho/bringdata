"""reference_reader — leitor único da referência rolante (Repositório).

Os relatórios (decis, funil, tabelas de característica) pedem a referência a ESTE
módulo em vez de ler arquivo/tabela direto. Assim, trocar a fonte é trocar aqui, e
o rollback é uma flag — não um deploy.

Estrangulamento (rollback por flag, sem backend "congelado" no leitor):
  - `REFERENCE_SOURCE=rolling` → o consumidor usa este leitor (a tabela viva).
  - `REFERENCE_SOURCE=frozen` (default no rollout) → o consumidor IGNORA este leitor
    e segue o caminho ANTIGO dele (JSON congelado / métrica %D9-D10). O caminho velho
    fica vivo até a rolante provar valor; então some.

A conversão de referência e a curva do calibrador vêm da tabela
`analytics.reference_rolling` (materializada pelo job semanal). O leitor reconstrói a
conversão ESPERADA de um lead com `np.interp` sobre a curva — sem sklearn na leitura.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def reference_source() -> str:
    """Fonte da referência: 'rolling' (tabela viva) ou 'frozen' (caminho antigo do
    consumidor). Default 'frozen' durante o rollout → rollback instantâneo sem deploy."""
    return os.environ.get("REFERENCE_SOURCE", "frozen").strip().lower()


def rolling_enabled() -> bool:
    return reference_source() == "rolling"


def read_rolling_reference(client_id: str = "devclub", *, conn=None) -> Optional[dict]:
    """Lê a referência rolante mais recente de analytics.reference_rolling.

    Returns:
        dict {window_start, window_end, as_of, ruler_run_id, n_leads, conversion,
        calibration} ou None se não houver linha (o consumidor degrada pro caminho
        congelado — nunca quebra por falta de referência).
    """
    own = conn is None
    if own:
        try:
            from src.data.analytics_connection import open_analytics_connection
            conn = open_analytics_connection()
        except Exception as e:
            logger.warning("[reference_reader] conexão falhou: %s", e)
            return None
    try:
        rows = conn.run(
            "SELECT window_start, window_end, as_of, ruler_run_id, n_leads, "
            "       conversion, calibration "
            "FROM reference_rolling WHERE client_id = :c AND source = 'rolling' "
            "ORDER BY window_end DESC LIMIT 1",
            c=client_id,
        )
    except Exception as e:
        logger.warning("[reference_reader] leitura falhou (tabela ausente?): %s", e)
        return None
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass

    if not rows:
        logger.info("[reference_reader] sem referência rolante pra client=%s", client_id)
        return None
    r = rows[0]
    # jsonb volta como dict pelo pg8000; se vier string (driver diferente), parseia.
    import json
    conv = r[5] if isinstance(r[5], dict) else json.loads(r[5])
    cal = r[6] if isinstance(r[6], dict) else json.loads(r[6])
    return {
        "window_start": str(r[0]), "window_end": str(r[1]), "as_of": str(r[2]),
        "ruler_run_id": r[3], "n_leads": int(r[4]),
        "conversion": conv, "calibration": cal,
    }


def expected_conversion(calibration: dict, scores) -> "list":
    """Conversão ESPERADA de leads: aplica a curva do calibrador (score→P) por
    interpolação. `scores` é array-like de score_challenger em [0,1]. Devolve a P de
    compra de cada lead — a média disso é a "conversão esperada" de um grupo."""
    import numpy as np
    x = calibration.get("x") or []
    y = calibration.get("y") or []
    if not x or not y:
        return [0.0 for _ in scores]
    return np.interp(np.asarray(scores, dtype=float), x, y).tolist()
