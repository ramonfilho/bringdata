"""Fase 3 do refator dual-decil: os read-models leem do ledger (registros_ml)
quando LEDGER_DECIL_READ_SOURCE=ledger, e da scores_historicos (legado) senão.

Injeta um conn falso que captura o SQL — sem banco. Verifica que:
  - o caminho 'ledger' consulta registros_ml, SEM join com scores_historicos, e
    formata o decil INT→'D0x' (lpad).
  - o caminho legado consulta scores_historicos (join).
  - _decil_read_source() respeita a env (default scores_historicos).

Rodável sem pytest:  python tests/test_dual_decil_read_switch.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.scores_historicos import (
    _decil_read_source, challenger_decils_in_window, challenger_quality_by_utm,
)

CHALL = "5d158f0aa6e54b489498470446194a6c"


class _CapConn:
    def __init__(self):
        self.sql = None
        self.params = None

    def run(self, sql, **params):
        self.sql = sql
        self.params = params
        return []  # sem linhas — o read-model devolve lista vazia


def test_decil_read_source_env():
    old = os.environ.pop("LEDGER_DECIL_READ_SOURCE", None)
    try:
        assert _decil_read_source() == "scores_historicos"  # default
        os.environ["LEDGER_DECIL_READ_SOURCE"] = "LEDGER"
        assert _decil_read_source() == "ledger"  # normaliza case
    finally:
        if old is None:
            os.environ.pop("LEDGER_DECIL_READ_SOURCE", None)
        else:
            os.environ["LEDGER_DECIL_READ_SOURCE"] = old


def test_decils_in_window_ledger_sql():
    c = _CapConn()
    challenger_decils_in_window(
        challenger_run_id=CHALL, win_start="2026-06-22", win_end="2026-07-01",
        source="ledger", conn=c)
    assert "registros_ml" in c.sql
    assert "scores_historicos" not in c.sql, "caminho ledger não pode tocar scores_historicos"
    assert "lpad" in c.sql.lower(), "decil INT deve virar 'D0x' via lpad"
    assert "lf = :lf" not in c.sql, "ledger não filtra lf (não tem a coluna)"


def test_decils_in_window_legacy_sql():
    c = _CapConn()
    challenger_decils_in_window(
        challenger_run_id=CHALL, win_start="2026-06-22", win_end="2026-07-01",
        source="scores_historicos", conn=c)
    assert "scores_historicos" in c.sql, "caminho legado usa scores_historicos"


def test_quality_by_utm_ledger_sql():
    c = _CapConn()
    os.environ["LEDGER_DECIL_READ_SOURCE"] = "ledger"
    try:
        challenger_quality_by_utm(
            "LF60", level="creative", challenger_run_id=CHALL,
            win_start="2026-06-22", win_end="2026-07-01", pin_lf=True, conn=c)
    finally:
        os.environ.pop("LEDGER_DECIL_READ_SOURCE", None)
    assert "registros_ml" in c.sql and "scores_historicos" not in c.sql
    assert "utm_content" in c.sql  # level=creative → coluna certa


if __name__ == "__main__":
    for fn in (test_decil_read_source_env, test_decils_in_window_ledger_sql,
               test_decils_in_window_legacy_sql, test_quality_by_utm_ledger_sql):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
