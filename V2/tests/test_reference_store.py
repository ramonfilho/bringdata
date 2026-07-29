"""Materialização da referência rolante (Fase 0c): a curva de calibração
serializada (sample_calibration_curve) e o upsert idempotente em
analytics.reference_rolling (reference_store). Tudo com conexão fake (sem banco).

Rodável:  PYTHONPATH=. python tests/test_reference_store.py
"""
import json

import numpy as np

from src.monitoring.rolling_reference import sample_calibration_curve
from src.data.reference_store import upsert_reference


class _FakeCal:
    method = "isotonic"
    def transform(self, x):
        return np.asarray(x, dtype=float) * 0.5  # linear só pra testar a amostragem


class CapConn:
    """Captura (sql, params) de cada run — sem banco."""
    def __init__(self):
        self.calls = []
    def run(self, sql, **params):
        self.calls.append((sql, params))
        return []


def test_sample_calibration_curve():
    c = sample_calibration_curve(_FakeCal(), n=11)
    assert c["method"] == "isotonic"
    assert len(c["x"]) == 11 and len(c["y"]) == 11
    assert c["x"][0] == 0.0 and c["x"][-1] == 1.0
    assert c["y"][-1] == 0.5  # transform(1.0) = 0.5
    assert c["y"][0] == 0.0


def test_upsert_idempotente_e_jsonb():
    conn = CapConn()
    upsert_reference(
        conn, client_id="devclub", window_start="2026-03-01", window_end="2026-05-30",
        as_of="2026-07-29", ruler_run_id="abr28", n_leads=113752,
        conversion={"overall": {"rate": 0.0084}}, calibration={"method": "isotonic", "x": [0, 1], "y": [0, 0.5]},
    )
    # 1a chamada cria a tabela (idempotente), 2a faz o upsert
    assert len(conn.calls) == 2
    ddl, _ = conn.calls[0]
    up, params = conn.calls[1]
    assert "CREATE TABLE IF NOT EXISTS reference_rolling" in ddl
    assert "ON CONFLICT (client_id, window_end, source) DO UPDATE" in up
    # conversão e calibração vão como jsonb serializado
    assert json.loads(params["conversion"])["overall"]["rate"] == 0.0084
    assert json.loads(params["calibration"])["method"] == "isotonic"
    assert params["source"] == "rolling" and params["n_leads"] == 113752


def test_ruler_run_id_vazio_vira_string():
    conn = CapConn()
    upsert_reference(
        conn, client_id="devclub", window_start="2026-03-01", window_end="2026-05-30",
        as_of="2026-07-29", ruler_run_id=None, n_leads=1,
        conversion={}, calibration={},
    )
    assert conn.calls[1][1]["ruler_run_id"] == ""  # None → "" (coluna NOT NULL)


if __name__ == "__main__":
    for fn in (test_sample_calibration_curve, test_upsert_idempotente_e_jsonb,
               test_ruler_run_id_vazio_vira_string):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
