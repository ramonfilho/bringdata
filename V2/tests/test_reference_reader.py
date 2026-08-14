"""reference_reader (Fase 0d): leitor único da referência rolante + flag de fonte +
conversão esperada por interpolação da curva do calibrador. Conexão fake (sem banco).

Rodável:  PYTHONPATH=. python tests/test_reference_reader.py
"""
import os

from src.data.reference_reader import (
    expected_conversion, read_rolling_reference, reference_source, rolling_enabled,
)


class FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.closed = False
    def run(self, sql, **params):
        return list(self._rows)
    def close(self):
        self.closed = True


def test_flag_de_fonte():
    saved = os.environ.pop("REFERENCE_SOURCE", None)
    try:
        assert reference_source() == "frozen" and rolling_enabled() is False  # default = rollback
        os.environ["REFERENCE_SOURCE"] = "rolling"
        assert rolling_enabled() is True
    finally:
        if saved is None:
            os.environ.pop("REFERENCE_SOURCE", None)
        else:
            os.environ["REFERENCE_SOURCE"] = saved


def test_read_devolve_dict_e_nao_fecha_conn_injetada():
    row = ("2026-03-01", "2026-05-30", "2026-07-29", "abr28", 113752,
           {"overall": {"rate": 0.0084}}, {"method": "isotonic", "x": [0, 0.5, 1], "y": [0, 0.01, 0.08]},
           {"categorical_features": {"O seu gênero:": {"proportions": {"Masculino": 0.9}}}},
           "2026-07-29 20:23:16")
    conn = FakeConn([row])
    r = read_rolling_reference(conn=conn)
    assert r["n_leads"] == 113752 and r["conversion"]["overall"]["rate"] == 0.0084
    # `as_of` NÃO identifica a linha: em 03/08/2026 duas reconstruções gravaram a
    # mesma data com políticas de maturação diferentes. O instante desempata.
    assert r["referencia_id"] == "2026-07-29T20:23"
    assert r["calibration"]["method"] == "isotonic"
    assert r["audience_profile"]["categorical_features"]["O seu gênero:"]["proportions"]["Masculino"] == 0.9
    assert conn.closed is False


def test_read_audience_profile_null_ok():
    # janela sem perfil de comprador → audience_profile None, não quebra
    row = ("2026-03-01", "2026-05-30", "2026-07-29", "abr28", 100,
           {"overall": {"rate": 0.01}}, {"method": "isotonic", "x": [0, 1], "y": [0, 0.1]},
           None, "2026-07-29 20:23:16")
    r = read_rolling_reference(conn=FakeConn([row]))
    assert r["audience_profile"] is None


def test_read_none_quando_vazio():
    assert read_rolling_reference(conn=FakeConn([])) is None


def test_expected_conversion_interpola():
    cal = {"x": [0.0, 0.5, 1.0], "y": [0.0, 0.01, 0.08]}
    p = expected_conversion(cal, [0.0, 0.25, 0.5, 1.0])
    assert abs(p[0] - 0.0) < 1e-9
    assert abs(p[2] - 0.01) < 1e-9
    assert abs(p[3] - 0.08) < 1e-9
    assert abs(p[1] - 0.005) < 1e-9  # metade do caminho 0→0.01
    # curva ausente → zeros (degrada limpo)
    assert expected_conversion({}, [0.3, 0.7]) == [0.0, 0.0]


if __name__ == "__main__":
    for fn in (test_flag_de_fonte, test_read_devolve_dict_e_nao_fecha_conn_injetada,
               test_read_audience_profile_null_ok,
               test_read_none_quando_vazio, test_expected_conversion_interpola):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
