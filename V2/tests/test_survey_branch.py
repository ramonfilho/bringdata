"""Testes do I4 — lógica pura de api/survey_branch (sem DB, sem pipeline, sem Meta).

Rodável sem pytest:  python tests/test_survey_branch.py
A integração (scoring/CAPI/ledger) é validada no canary em dry-run, como o
fluxo Lead — aqui testamos só as decisões puras.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.survey_branch import classify, survey_event_id, ledger_row, is_enabled

FULL = {"computador": "SIM", "fbp": "fb.1", "fbc": "fb.2"}


def test_classify_allowlist():
    assert classify(False, FULL) == "skipped_allowlist"
    assert classify(False, {}) == "skipped_allowlist"


def test_classify_missing_data():
    assert classify(True, {"computador": None, "fbp": "x", "fbc": "y"}) == "skipped_missing_data"
    assert classify(True, {"computador": "SIM", "fbp": None, "fbc": "y"}) == "skipped_missing_data"
    assert classify(True, {"computador": "SIM", "fbp": "x", "fbc": None}) == "skipped_missing_data"
    assert classify(True, {}) == "skipped_missing_data"


def test_classify_send():
    assert classify(True, FULL) == "send"


def test_survey_event_id():
    assert survey_event_id("cmp_abc123") == "survey_cmp_abc123"


def test_ledger_row_skip():
    r = ledger_row("L1", "a@x.com", None, None, None, "skipped_allowlist")
    assert r["lead_id"] == "L1" and r["base_status"] == "skipped_allowlist"
    assert r["capi_sent_at_now"] is False
    assert r["base_meta_event_id"] is None and r["hq_meta_event_id"] is None
    assert set(r) == {
        "lead_id", "email", "variant", "lead_score", "decil",
        "base_meta_event_id", "base_status", "hq_meta_event_id",
        "hq_status", "capi_sent_at_now", "error_message",
    }


def test_ledger_row_sent_d10():
    r = ledger_row("L2", "b@x.com", "champion", 0.93, 10, "success",
                   base_meta_event_id="qualified_survey_L2",
                   hq_meta_event_id="hq_survey_L2", hq_status="success",
                   capi_sent_at_now=True)
    assert r["variant"] == "champion" and r["decil"] == 10
    assert r["base_meta_event_id"] == "qualified_survey_L2"
    assert r["hq_meta_event_id"] == "hq_survey_L2" and r["hq_status"] == "success"
    assert r["capi_sent_at_now"] is True


def test_is_enabled_env():
    old = os.environ.get("SURVEY_CAPI_ENABLED")
    try:
        os.environ.pop("SURVEY_CAPI_ENABLED", None)
        assert is_enabled() is False, "default off"
        os.environ["SURVEY_CAPI_ENABLED"] = "false"
        assert is_enabled() is False
        os.environ["SURVEY_CAPI_ENABLED"] = "true"
        assert is_enabled() is True
        os.environ["SURVEY_CAPI_ENABLED"] = "TRUE"
        assert is_enabled() is True
        os.environ["SURVEY_CAPI_ENABLED"] = "1"
        assert is_enabled() is False, "só 'true' liga (explícito)"
    finally:
        if old is None:
            os.environ.pop("SURVEY_CAPI_ENABLED", None)
        else:
            os.environ["SURVEY_CAPI_ENABLED"] = old


def _run():
    tests = [
        test_classify_allowlist, test_classify_missing_data, test_classify_send,
        test_survey_event_id, test_ledger_row_skip, test_ledger_row_sent_d10,
        test_is_enabled_env,
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
