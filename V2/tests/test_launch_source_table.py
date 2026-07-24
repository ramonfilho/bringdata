"""Testes da fonte de LF table-backed (analytics.launch_calendar).

Cobrem o seam `core.launches.load_launches` (env LAUNCHES_SOURCE, fallback yaml),
o projetor de linha do store e o parse do reader — TUDO sem tocar banco real
(conexão fake). Rodar:
  python3 -m pytest V2/tests/test_launch_source_table.py
ou: python3 V2/tests/test_launch_source_table.py
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

from src.core import launches as L
from src.data import launch_calendar_store as store
from src.data import launch_calendar_reader as reader


# ───────────────────────── helpers ──────────────────────────────────────────
class _FakeConn:
    """Conexão pg8000-like: `.run(sql, **p)` devolve `rows` fixos ou levanta."""
    def __init__(self, rows=None, raises=None):
        self._rows, self._raises = rows, raises
        self.closed = False

    def run(self, sql, **params):
        if self._raises:
            raise self._raises
        return self._rows

    def close(self):
        self.closed = True


def _set_source(monkeyless_value):
    """Seta/limpa LAUNCHES_SOURCE, devolve o valor anterior pra restaurar."""
    prev = os.environ.get("LAUNCHES_SOURCE")
    if monkeyless_value is None:
        os.environ.pop("LAUNCHES_SOURCE", None)
    else:
        os.environ["LAUNCHES_SOURCE"] = monkeyless_value
    return prev


def _restore_source(prev):
    if prev is None:
        os.environ.pop("LAUNCHES_SOURCE", None)
    else:
        os.environ["LAUNCHES_SOURCE"] = prev


# ───────────────────────── _launches_source (flag) ──────────────────────────
def test_source_default_yaml_and_invalid_falls_back():
    prev = _set_source(None)
    try:
        assert L._launches_source() == "yaml"          # default
        os.environ["LAUNCHES_SOURCE"] = "TABLE"          # case-insensitive
        assert L._launches_source() == "table"
        os.environ["LAUNCHES_SOURCE"] = "banco"           # inválido → seguro
        assert L._launches_source() == "yaml"
    finally:
        _restore_source(prev)


# ───────────────────────── load_launches: seam ──────────────────────────────
def test_default_does_not_touch_table():
    """LAUNCHES_SOURCE ausente → nunca chama a tabela (lê só o yaml)."""
    prev = _set_source(None)
    called = {"n": 0}
    orig = L._load_launches_from_table
    L._load_launches_from_table = lambda: (called.__setitem__("n", called["n"] + 1) or {})
    try:
        res = L.load_launches()
        assert called["n"] == 0                          # tabela não tocada
        assert isinstance(res, dict) and res             # yaml real tem LFs
    finally:
        L._load_launches_from_table = orig
        _restore_source(prev)


def test_source_table_uses_table_when_present():
    """LAUNCHES_SOURCE=table + tabela com dados → usa a tabela; o resolvedor acha o LF."""
    prev = _set_source("table")
    orig = L._load_launches_from_table
    L._load_launches_from_table = lambda: {
        "DEV21": {"cap_start": "2026-07-21", "cap_end": "2026-08-03"}
    }
    try:
        res = L.load_launches()
        assert set(res) == {"DEV21"}
        active = L.resolve_active_launch_brt(today=date(2026, 7, 24), launches=res)
        assert active is not None and active.name == "DEV21"
    finally:
        L._load_launches_from_table = orig
        _restore_source(prev)


def test_source_table_falls_back_to_yaml_when_empty():
    """LAUNCHES_SOURCE=table mas tabela vazia/indisponível → cai no yaml (não vazio)."""
    prev = _set_source("table")
    orig = L._load_launches_from_table
    L._load_launches_from_table = lambda: {}
    try:
        res = L.load_launches()
        assert isinstance(res, dict) and res             # veio do yaml real
    finally:
        L._load_launches_from_table = orig
        _restore_source(prev)


def test_explicit_path_forces_yaml_even_if_source_table(tmp_path=None):
    """path explícito ignora a tabela (usado por testes e pelo --sync)."""
    prev = _set_source("table")
    orig = L._load_launches_from_table
    L._load_launches_from_table = lambda: {"FROMTABLE": {"cap_start": "2026-01-01", "cap_end": "2026-01-07"}}
    tmp = Path(__file__).resolve().parent / "_tmp_launches_forcepath.yaml"
    tmp.write_text("LFX:\n  cap_start: '2026-02-01'\n  cap_end: '2026-02-07'\n")
    try:
        res = L.load_launches(path=tmp)
        assert "FROMTABLE" not in res                     # tabela ignorada
        assert "LFX" in res
    finally:
        tmp.unlink(missing_ok=True)
        L._load_launches_from_table = orig
        _restore_source(prev)


# ───────────────────────── store: projeção de linha ─────────────────────────
def test_store_row_params_projects_dates_and_jsonb():
    import json
    entry = {"cap_start": "2026-07-21", "cap_end": "2026-08-03",
             "vendas_start": "2026-08-08", "vendas_end": "2026-08-14",
             "excluded_from_reference": True}
    p = store._row_params("DEV21", entry, client_id="devclub", source="sheet_sync")
    assert p["lf_name"] == "DEV21" and p["client_id"] == "devclub"
    assert p["cap_start"] == "2026-07-21" and p["cap_end"] == "2026-08-03"
    assert p["vendas_start"] == "2026-08-08"
    parsed = json.loads(p["entry"])                       # entry preserva curadoria
    assert parsed["excluded_from_reference"] is True and parsed["cap_start"] == "2026-07-21"


def test_store_row_params_rejects_blank_name():
    assert store._row_params("  ", {"cap_start": "2026-01-01"}, "devclub", "s") is None


def test_store_upsert_empty_is_noop():
    assert store.upsert_launch_calendar({}, conn=_FakeConn()) == {"attempted": 0, "written": 0}


# ───────────────────────── reader: parse + fallback ─────────────────────────
def test_reader_parses_jsonb_dict_and_str():
    rows = [
        ["DEV21", {"cap_start": "2026-07-21", "cap_end": "2026-08-03"}],   # pg8000 já dict
        ["LF62", '{"cap_start": "2026-07-06", "cap_end": "2026-07-20"}'],  # str por robustez
    ]
    out = reader.read_calendar_from_table(conn=_FakeConn(rows=rows))
    assert out["DEV21"]["cap_end"] == "2026-08-03"
    assert out["LF62"]["cap_start"] == "2026-07-06"        # str parseada


def test_reader_returns_empty_on_failure():
    out = reader.read_calendar_from_table(conn=_FakeConn(raises=RuntimeError("no table")))
    assert out == {}                                       # chamador cai no yaml


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
