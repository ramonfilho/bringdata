"""Fase 2 do refator dual-decil: os campos dos DOIS modelos entram no ledger.

- `ledger_row` inclui as 6 colunas dual (default None) + `scored_at_now` False.
- `_insert_ledger` emite as colunas novas + `scored_at`, e faz bind dos valores;
  as flags NOW() (`scored_at_now`/`capi_sent_at_now`) não vazam como param.
- blindagem: row sem as chaves dual não quebra o INSERT (setdefault).

Rodável sem pytest:  python tests/test_dual_decil_ledger.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.pubsub_branch import ledger_row, _insert_ledger


class _CapConn:
    def __init__(self):
        self.sql = None
        self.params = None

    def run(self, sql, **params):
        self.sql = sql
        self.params = params


def test_ledger_row_tem_campos_dual_default_none():
    r = ledger_row("e1", "a@b.c", "champion", 0.5, 5, "success")
    for k in ("score_champion", "decil_champion", "score_challenger",
              "decil_challenger", "champion_run_id", "challenger_run_id"):
        assert k in r and r[k] is None, f"{k} deveria existir e ser None"
    assert r["scored_at_now"] is False


def test_insert_ledger_emite_colunas_dual_e_bind():
    r = ledger_row("e2", "a@b.c", "challenger_abr28", 0.91, 10, "success")
    # Enriquecimento (o que o consumer faz por event_id pós-scoring).
    r.update({
        "score_champion": 0.30, "decil_champion": 4,
        "score_challenger": 0.91, "decil_challenger": 10,
        "champion_run_id": "d51757f5", "challenger_run_id": "5d158f0a",
        "scored_at_now": True,
    })
    c = _CapConn()
    _insert_ledger(c, r)
    for col in ("decil_champion", "decil_challenger", "champion_run_id",
                "challenger_run_id", "scored_at"):
        assert col in c.sql, f"{col} ausente no INSERT"
    assert "NOW()" in c.sql, "scored_at deveria ser NOW() em row scoreado"
    assert c.params["decil_challenger"] == 10
    assert c.params["champion_run_id"] == "d51757f5"
    # flags de NOW() não podem virar param (senão pg8000 reclama de coluna inexistente)
    assert "scored_at_now" not in c.params
    assert "capi_sent_at_now" not in c.params


def test_insert_ledger_blindado_contra_row_sem_dual():
    # Row cru (não veio de ledger_row) — não pode quebrar por param não-bound.
    row = {
        "event_id": "e3", "email": "a@b.c", "variant": None, "lead_score": None,
        "decil": None, "base_meta_event_id": None, "base_status": "error",
        "hq_meta_event_id": None, "hq_status": None, "error_message": "x",
        "utm_source": None, "utm_medium": None, "utm_campaign": None,
        "utm_content": None, "utm_term": None, "utm_url": None,
        "survey_responses": None, "first_name": None, "last_name": None,
        "phone": None, "fbp": None, "fbc": None, "user_agent": None, "ip": None,
        "has_computer": None, "google_ads_status": None, "capi_sent_at_now": False,
    }
    c = _CapConn()
    _insert_ledger(c, row)  # não deve levantar
    assert c.params["decil_challenger"] is None
    assert "NULL" in c.sql  # scored_at NULL em row não-scoreado


if __name__ == "__main__":
    for fn in (test_ledger_row_tem_campos_dual_default_none,
               test_insert_ledger_emite_colunas_dual_e_bind,
               test_insert_ledger_blindado_contra_row_sem_dual):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
