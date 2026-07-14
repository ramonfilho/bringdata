"""Base única do split de decis na régua do Challenger:
`challenger_decils_in_window` faz o join `scores_historicos ⋈ registros_ml` UMA
vez e devolve uma `ChallengerDecilRec(utm_source, utm_campaign, decil)` por lead;
`challenger_decil_dist_by_source` é wrapper fino que consome a base e agrega só as
fontes pedidas (NÃO re-faz o join). Guarda contra o join ser reintroduzido em
paralelo (o bug de duplicação que motivou a refatoração).

Rodável:  PYTHONPATH=. python tests/test_challenger_decils_window.py
"""
import src.data.scores_historicos as sh
from src.data.scores_historicos import (
    ChallengerDecilRec,
    challenger_decils_in_window,
    challenger_decil_dist_by_source,
)


class FakeConn:
    """conn.run(sql, **params) devolve linhas fixas (src, campaign, decil),
    imitando o SELECT da base. Registra os params pra checagem."""
    def __init__(self, rows):
        self._rows = rows
        self.last_params = None
        self.closed = False
        self.calls = 0

    def run(self, sql, **params):
        self.calls += 1
        self.last_params = params
        return list(self._rows)

    def close(self):
        self.closed = True


_ROWS = [
    ("google-ads", "cap-go-x", "D09"),
    ("google-ads", "cap-go-x", "D02"),
    ("facebook-ads", "LEADHQLB", "D10"),
    (None, None, "D05"),          # lead sem fonte → só no Total, fora de por-fonte
]


def test_base_devolve_um_rec_por_linha():
    conn = FakeConn(_ROWS)
    recs = challenger_decils_in_window(
        challenger_run_id="abr28", win_start=1, win_end=2, conn=conn)
    assert recs is not None and len(recs) == 4
    assert all(isinstance(r, ChallengerDecilRec) for r in recs)
    assert recs[0] == ChallengerDecilRec("google-ads", "cap-go-x", "D09")
    assert conn.closed is False  # conn injetada não é fechada pela função


def test_base_guarda_config_invalida():
    # sem run_id → None (nunca cai no jan_30); pin_lf sem lf → None
    assert challenger_decils_in_window(challenger_run_id="", win_start=1, win_end=2) is None
    assert challenger_decils_in_window(
        challenger_run_id="abr28", win_start=1, win_end=2, pin_lf=True) is None


def test_wrapper_filtra_por_fonte_e_reusa_a_base(monkeypatch=None):
    conn = FakeConn(_ROWS)
    g = challenger_decil_dist_by_source(
        ["google-ads"], challenger_run_id="abr28", win_start=1, win_end=2, conn=conn)
    assert g["total"] == 2, g
    assert g["distribution"]["D09"] == 1 and g["distribution"]["D02"] == 1
    assert g["distribution"]["D10"] == 0  # facebook não conta no bucket google
    # o wrapper faz UMA chamada ao banco (delega à base, não um 2º join)
    assert conn.calls == 1, f"esperado 1 query (base única), houve {conn.calls}"


def test_wrapper_case_insensitive_e_vazio():
    conn = FakeConn(_ROWS)
    # sources com caixa/espaço são normalizados
    m = challenger_decil_dist_by_source(
        [" Facebook-Ads "], challenger_run_id="abr28", win_start=1, win_end=2, conn=conn)
    assert m["total"] == 1 and m["distribution"]["D10"] == 1
    # sources vazio curto-circuita (não bate no banco)
    conn2 = FakeConn(_ROWS)
    z = challenger_decil_dist_by_source(
        [], challenger_run_id="abr28", win_start=1, win_end=2, conn=conn2)
    assert z["total"] == 0 and conn2.calls == 0


if __name__ == "__main__":
    for fn in (test_base_devolve_um_rec_por_linha,
               test_base_guarda_config_invalida,
               test_wrapper_filtra_por_fonte_e_reusa_a_base,
               test_wrapper_case_insensitive_e_vazio):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
