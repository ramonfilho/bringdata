"""Testes das 3 regras novas de critical_alerts (Pub/Sub consumer).

Rodável sem pytest:  python tests/test_critical_alerts_pubsub.py

Cobre:
  - rule_pubsub_consumer_stalled (R1)
  - rule_pubsub_error_rate_high (R2)
  - rule_pubsub_skipped_missing_data_high (R3)

Não cobre conexão real ao Railway — `conn` é mockado com FakeConn que devolve
linhas pré-programadas. Isso é teste das condições e do shape do RuleResult,
não da query SQL em si.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.critical_alerts import (
    rule_pubsub_consumer_stalled,
    rule_pubsub_error_rate_high,
    rule_pubsub_skipped_missing_data_high,
)


class FakeConn:
    """Conn mock: cada `run()` pega a próxima linha da fila."""

    def __init__(self, rows_per_query):
        self._queue = list(rows_per_query)
        self.queries = []

    def run(self, sql, **kwargs):
        self.queries.append((sql, kwargs))
        if not self._queue:
            raise AssertionError(
                f"conn.run chamado mais vezes que o mock cobre: sql={sql!r}"
            )
        return self._queue.pop(0)


def _env(name, value):
    """Setter idempotente de env var; devolve closure de cleanup."""
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value

    def restore():
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old

    return restore


# ──────────────────────────────────────────────────────────────────────────
# R1 — rule_pubsub_consumer_stalled
# ──────────────────────────────────────────────────────────────────────────


def test_r1_skipped_quando_flag_desligada():
    restore = _env("PUBSUB_CAPI_ENABLED", "false")
    try:
        # conn não deve ser tocado — passo None pra falhar se for usado.
        r = rule_pubsub_consumer_stalled(None)
        assert r.fired is False
        assert r.skipped_reason and "PUBSUB_CAPI_ENABLED" in r.skipped_reason
    finally:
        restore()


def test_r1_skipped_quando_ledger_vazio():
    restore = _env("PUBSUB_CAPI_ENABLED", "true")
    try:
        conn = FakeConn([[(0, 0, None)]])  # recent=0, total=0, last_at=None
        r = rule_pubsub_consumer_stalled(conn)
        assert r.fired is False
        assert r.skipped_reason and "vazio" in r.skipped_reason
    finally:
        restore()


def test_r1_not_fired_quando_ha_linhas_recentes():
    restore = _env("PUBSUB_CAPI_ENABLED", "true")
    try:
        last = datetime.datetime.utcnow()
        conn = FakeConn([[(5, 100, last)]])  # recent=5, total=100
        r = rule_pubsub_consumer_stalled(conn)
        assert r.fired is False
        assert r.skipped_reason is None
    finally:
        restore()


def test_r1_fired_quando_zero_recente_mas_ledger_nao_vazio():
    restore = _env("PUBSUB_CAPI_ENABLED", "true")
    try:
        last = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
        conn = FakeConn([[(0, 100, last)]])  # recent=0, total=100
        r = rule_pubsub_consumer_stalled(conn)
        assert r.fired is True
        assert r.severity == "HIGH"
        assert r.rule_name == "pubsub_consumer_stalled"
        assert "parado" in r.message.lower()
        assert r.details["recent_60min"] == 0
        assert r.details["total"] == 100
    finally:
        restore()


# ──────────────────────────────────────────────────────────────────────────
# R2 — rule_pubsub_error_rate_high
# ──────────────────────────────────────────────────────────────────────────


def test_r2_skipped_quando_amostra_pequena():
    conn = FakeConn([[(19, 5)]])  # n=19 < 20
    r = rule_pubsub_error_rate_high(conn)
    assert r.fired is False
    assert "insuficiente" in (r.skipped_reason or "")


def test_r2_not_fired_quando_taxa_abaixo_do_limite():
    conn = FakeConn([[(100, 9)]])  # 9% < 10%
    r = rule_pubsub_error_rate_high(conn)
    assert r.fired is False
    assert r.skipped_reason is None


def test_r2_fired_quando_taxa_passa_de_10pct():
    conn = FakeConn([[(100, 15)]])  # 15% > 10%
    r = rule_pubsub_error_rate_high(conn)
    assert r.fired is True
    assert r.severity == "HIGH"
    assert r.rule_name == "pubsub_error_rate_high"
    assert r.details == {"n": 100, "err": 15, "rate_pct": 15.0}


# ──────────────────────────────────────────────────────────────────────────
# R3 — rule_pubsub_skipped_missing_data_high
# ──────────────────────────────────────────────────────────────────────────


def test_r3_skipped_quando_amostra_pequena():
    conn = FakeConn([[(19, 10)]])  # eligible=19 < 20
    r = rule_pubsub_skipped_missing_data_high(conn)
    assert r.fired is False
    assert "insuficiente" in (r.skipped_reason or "")


def test_r3_not_fired_quando_taxa_abaixo_do_limite():
    conn = FakeConn([[(100, 25)]])  # 25% < 30%
    r = rule_pubsub_skipped_missing_data_high(conn)
    assert r.fired is False
    assert r.skipped_reason is None


def test_r3_fired_quando_taxa_passa_de_30pct():
    conn = FakeConn([[(100, 35)]])  # 35% > 30%
    r = rule_pubsub_skipped_missing_data_high(conn)
    assert r.fired is True
    assert r.severity == "HIGH"
    assert r.rule_name == "pubsub_skipped_missing_data_high"
    assert r.details == {"eligible": 100, "missing": 35, "pct": 35.0}


def _run():
    tests = [
        test_r1_skipped_quando_flag_desligada,
        test_r1_skipped_quando_ledger_vazio,
        test_r1_not_fired_quando_ha_linhas_recentes,
        test_r1_fired_quando_zero_recente_mas_ledger_nao_vazio,
        test_r2_skipped_quando_amostra_pequena,
        test_r2_not_fired_quando_taxa_abaixo_do_limite,
        test_r2_fired_quando_taxa_passa_de_10pct,
        test_r3_skipped_quando_amostra_pequena,
        test_r3_not_fired_quando_taxa_abaixo_do_limite,
        test_r3_fired_quando_taxa_passa_de_30pct,
    ]
    fails = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {t.__name__}\n        {e}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - fails}/{len(tests)} passaram")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_run())
