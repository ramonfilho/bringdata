"""Testes do I3 — lógica pura de montagem/cobertura de api/survey_enrichment.

Rodável sem pytest:  python tests/test_survey_enrichment.py
Sem alarme aqui (migrou pro I5, rolling sobre o ledger). Testa: escolha de
UTM por recência, precedência eventId>email p/ fbp/fbc, computador
n8n>ac144, flag meta_eligible, e fbp+fbc medido SÓ entre Meta-elegíveis.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.survey_enrichment import _assemble, _pick_utm, _is_meta

D = datetime


def test_pick_utm_recencia():
    sub = D(2026, 5, 18, 12, 0, 0)
    antes = (D(2026, 5, 18, 9, 0, 0), {"source": "fb-antes"})
    velho = (D(2026, 5, 17, 9, 0, 0), {"source": "fb-velho"})
    depois = (D(2026, 5, 18, 15, 0, 0), {"source": "fb-depois"})
    assert _pick_utm([velho, antes, depois], sub)["source"] == "fb-antes"
    assert _pick_utm([depois], sub)["source"] == "fb-depois"
    assert _pick_utm([], sub) == {}


def test_is_meta():
    for s in ("facebook-ads", "FB", " ig ", "Facebook-Ads"):
        assert _is_meta(s) is True, s
    for s in ("google-ads", "manychat", "", None, "tiktok"):
        assert _is_meta(s) is False, s


def test_fbpfbc_eventid_precede_email_e_meta_flag():
    rows = [{"id": "A", "clientEmail": "a@x.com", "eventId": "survey_A",
             "submittedAt": D(2026, 5, 18, 12, 0), "ip": "9.9.9.9"}]
    by_id, _ = _assemble(
        rows,
        utm_by_email={"a@x.com": [(D(2026, 5, 18, 10, 0),
                                   {"source": "facebook-ads"})]},
        mc_by_eventid={"survey_A": {"fbp": "EV_fbp", "fbc": "EV_fbc",
                                    "ip": "1.1.1.1", "user_agent": "UA-ev"}},
        mc_by_email={"a@x.com": {"fbp": "EM_fbp", "fbc": "EM_fbc",
                                 "ip": "2.2.2.2", "user_agent": "UA-em"}},
        n8_by_email={"a@x.com": {"tem_computador": "SIM",
                                 "telefone": "+551199", "nome": "Ana"}},
        ac_by_email={},
    )
    a = by_id["A"]
    assert a["enrich"]["fbp"] == "EV_fbp" and a["enrich"]["fbc"] == "EV_fbc"
    assert a["enrich"]["ip"] == "1.1.1.1" and a["enrich"]["user_agent"] == "UA-ev"
    assert a["meta_eligible"] is True


def test_fallback_email_computador_ac144_ip_survey_e_naometa():
    rows = [{"id": "B", "clientEmail": "b@x.com", "eventId": "survey_B_semmatch",
             "submittedAt": D(2026, 5, 18, 12, 0), "ip": "8.8.8.8"}]
    by_id, _ = _assemble(
        rows,
        utm_by_email={"b@x.com": [(D(2026, 5, 18, 10, 0), {"source": "google-ads"})]},
        mc_by_eventid={},
        mc_by_email={"b@x.com": {"fbp": "EM_fbp", "fbc": None,
                                 "ip": None, "user_agent": "UA"}},
        n8_by_email={},
        ac_by_email={"b@x.com": "NAO"},
    )
    b = by_id["B"]
    assert b["enrich"]["fbp"] == "EM_fbp", "fallback por email"
    assert b["enrich"]["computador"] == "NAO", "computador via activecampaign 144"
    assert b["enrich"]["ip"] == "8.8.8.8", "ip cai pro da lead_surveys"
    assert b["meta_eligible"] is False, "google-ads não é Meta-elegível"


def test_computador_n8n_precede_ac144():
    rows = [{"id": "C", "clientEmail": "c@x.com", "eventId": None,
             "submittedAt": D(2026, 5, 18, 12, 0), "ip": None}]
    by_id, _ = _assemble(
        rows, {}, {}, {},
        n8_by_email={"c@x.com": {"tem_computador": "SIM",
                                 "telefone": None, "nome": None}},
        ac_by_email={"c@x.com": "NAO"},
    )
    assert by_id["C"]["enrich"]["computador"] == "SIM"


def test_cobertura_fbpfbc_so_entre_meta_elegiveis():
    # 2 meta (fb/ig) com fbp+fbc completos; 3 google-ads sem fbc.
    # fbp+fbc GLOBAL seria 2/5=40%, mas medido SÓ entre meta = 2/2 = 100%.
    rows = []
    utm = {}
    mc = {}
    for i in range(2):
        em = f"m{i}@x.com"
        rows.append({"id": f"M{i}", "clientEmail": em, "eventId": f"ev_m{i}",
                     "submittedAt": D(2026, 5, 18, 12, 0), "ip": None})
        utm[em] = [(D(2026, 5, 18, 10, 0), {"source": "facebook-ads"})]
        mc[f"ev_m{i}"] = {"fbp": "f", "fbc": "c", "ip": "1", "user_agent": "u"}
    for i in range(3):
        em = f"g{i}@x.com"
        rows.append({"id": f"G{i}", "clientEmail": em, "eventId": f"ev_g{i}",
                     "submittedAt": D(2026, 5, 18, 12, 0), "ip": None})
        utm[em] = [(D(2026, 5, 18, 10, 0), {"source": "google-ads"})]
        mc[f"ev_g{i}"] = {"fbp": "f", "fbc": None, "ip": "1", "user_agent": "u"}
    n8 = {r["clientEmail"]: {"tem_computador": "SIM", "telefone": "t", "nome": "n"}
          for r in rows}
    by_id, cov = _assemble(rows, utm, mc, {}, n8, {})
    assert cov["n"] == 5 and cov["meta_n"] == 2
    assert cov["fbpfbc_meta_pct"] == 1.0, "fbp+fbc só entre meta-elegíveis = 100%"
    assert cov["utm_pct"] == 1.0 and cov["computador_pct"] == 1.0  # globais
    assert "alarm" not in cov, "I3 não decide alarme (migrou pro I5)"
    assert by_id["M0"]["meta_eligible"] is True
    assert by_id["G0"]["meta_eligible"] is False


def test_sem_meta_no_lote_fbpfbc_none():
    rows = [{"id": "Z", "clientEmail": "z@x.com", "eventId": None,
             "submittedAt": D(2026, 5, 18, 12, 0), "ip": None}]
    _, cov = _assemble(
        rows,
        utm_by_email={"z@x.com": [(D(2026, 5, 18, 10, 0), {"source": "google-ads"})]},
        mc_by_eventid={}, mc_by_email={}, n8_by_email={}, ac_by_email={},
    )
    assert cov["meta_n"] == 0
    assert cov["fbpfbc_meta_pct"] is None, "sem meta no lote → None, sem crash"


def _run():
    tests = [
        test_pick_utm_recencia,
        test_is_meta,
        test_fbpfbc_eventid_precede_email_e_meta_flag,
        test_fallback_email_computador_ac144_ip_survey_e_naometa,
        test_computador_n8n_precede_ac144,
        test_cobertura_fbpfbc_so_entre_meta_elegiveis,
        test_sem_meta_no_lote_fbpfbc_none,
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
