"""matured_window: janela madura rotulada na régua do Challenger, costurando o
ledger vivo `registros_ml` (>= cutover) com a `scores_historicos` congelada
(< cutover). Testa a costura, o dedup preferindo o ledger, a coerção de tipos e o
fail-loud em janela vazia — tudo com conexão fake (sem banco).

Rodável:  PYTHONPATH=. python tests/test_matured_window.py
"""
from datetime import date, datetime
from pathlib import Path

from src.data.matured_window import (
    CANONICAL_COLS, build_matured_window, matured_bounds, resolve_ruler_run_id,
)


class FakeConn:
    """conn.run devolve, em ordem, as listas de linhas enfileiradas (1 batch por
    query). build_matured_window faz DUAS queries (ledger, depois ponte)."""
    def __init__(self, *row_batches):
        self._batches = list(row_batches)
        self.closed = False
        self.calls = 0

    def run(self, sql, **params):
        self.calls += 1
        return list(self._batches.pop(0)) if self._batches else []

    def close(self):
        self.closed = True


def _row(email, source, decil, cap, utm="facebook-ads", score=0.4):
    # ordem de CANONICAL_COLS: email, telefone, data_captura, score_challenger,
    # decil_challenger, utm_source, utm_campaign, utm_content, source
    return (email, None, cap, score, decil, utm, "camp", "ad", source)


def test_matured_bounds_recuo_e_largura():
    ws, we = matured_bounds(window_days=90, maturation_days=60, as_of=date(2026, 7, 29))
    assert we == datetime(2026, 5, 30) and ws == datetime(2026, 3, 1)


def test_costura_e_coercao():
    led = [_row("a@x", "ledger", 10, datetime(2026, 5, 25))]
    brg = [_row("b@x", "bridge", 3, datetime(2026, 4, 1))]
    conn = FakeConn(led, brg)
    df = build_matured_window(as_of=date(2026, 7, 29), ruler_run_id="abr28", conn=conn)
    assert conn.calls == 2 and conn.closed is False  # 2 queries; conn injetada não fecha
    assert set(df.columns) == set(CANONICAL_COLS)
    assert len(df) == 2
    assert str(df["decil_challenger"].dtype) == "Int64"
    assert df["data_captura"].dt.tz is None  # tz-naive p/ o matcher casar com sale_date


def test_dedup_prefere_ledger():
    # mesmo email nas duas fontes → fica o do ledger (produção > snapshot).
    led = [_row("dup@x", "ledger", 9, datetime(2026, 5, 25), utm="google-ads")]
    brg = [_row("dup@x", "bridge", 2, datetime(2026, 4, 1), utm=None)]
    conn = FakeConn(led, brg)
    df = build_matured_window(as_of=date(2026, 7, 29), ruler_run_id="abr28", conn=conn)
    assert len(df) == 1
    r = df.iloc[0]
    assert r["source"] == "ledger" and int(r["decil_challenger"]) == 9 and r["utm_source"] == "google-ads"


def test_fail_loud_em_vazio():
    raised = False
    try:
        build_matured_window(as_of=date(2026, 7, 29), ruler_run_id="abr28", conn=FakeConn([], []))
    except ValueError:
        raised = True
    assert raised, "janela madura vazia deve FALHAR ALTO"
    # allow_empty=True → devolve vazio sem levantar
    df = build_matured_window(as_of=date(2026, 7, 29), ruler_run_id="abr28",
                              conn=FakeConn([], []), allow_empty=True)
    assert df.empty


def test_sem_run_id_falha():
    # ruler_run_id vazio + cliente inexistente → resolve devolve None → guarda levanta.
    raised = False
    try:
        build_matured_window(ruler_run_id="", client_id="__nao_existe__", conn=FakeConn([], []))
    except ValueError:
        raised = True
    assert raised


def test_resolve_run_id_le_active_model(tmp_path=None):
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "configs" / "active_models").mkdir(parents=True)
    (d / "configs" / "active_models" / "devclub.yaml").write_text(
        "active_model:\n  mlflow_run_id: abc123\n")
    assert resolve_ruler_run_id("devclub", config_root=d) == "abc123"
    assert resolve_ruler_run_id("__nao_existe__", config_root=d) is None


if __name__ == "__main__":
    for fn in (test_matured_bounds_recuo_e_largura, test_costura_e_coercao,
               test_dedup_prefere_ledger, test_fail_loud_em_vazio,
               test_sem_run_id_falha, test_resolve_run_id_le_active_model):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
