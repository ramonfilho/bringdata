"""reference_reader (Fase 0d): leitor único da referência rolante + flag de fonte +
conversão esperada por interpolação da curva do calibrador. Conexão fake (sem banco).

Rodável:  PYTHONPATH=. python tests/test_reference_reader.py
"""
import os

from src.data.reference_reader import (
    credito_do_nao_respondente, expected_conversion, read_rolling_reference,
    reference_source, rolling_enabled,
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


# ===========================================================================
# Leitura POINT-IN-TIME (24/08/2026)
# ===========================================================================
# Sem corte, o leitor devolve a linha mais recente, e por isso rodar o mesmo
# lançamento daqui a dois meses usaria a referência de daqui a dois meses: o
# relatório era irreproduzível por construção. Os cortes consertam isso, mas o
# caminho de produção (sem parâmetro) tem que continuar idêntico, SQL inclusive.

SQL_DE_SEMPRE = (
    "SELECT window_start, window_end, as_of, ruler_run_id, n_leads, "
    "       conversion, calibration, audience_profile, generated_at "
    "FROM reference_rolling WHERE client_id = :c AND source = 'rolling' "
    "ORDER BY window_end DESC LIMIT 1")

# As 11 linhas reais de devclub (window_end, generated_at), congeladas em
# docs/relatorios/_ancoras/reference_rolling_devclub_congelado_2026-08-24.json.
# Repare que a de 2026-06-11 foi GRAVADA depois da de 2026-07-13: por isso o
# corte por `generated_at` e o corte por `window_end` não são o mesmo corte.
LINHAS_REAIS = [
    ("2026-08-03", "2026-08-24 06:32:26"), ("2026-07-31", "2026-08-21 09:16:28"),
    ("2026-07-28", "2026-08-18 20:04:44"), ("2026-07-27", "2026-08-17 06:33:10"),
    ("2026-07-26", "2026-08-16 17:26:29"), ("2026-07-25", "2026-08-15 13:11:28"),
    ("2026-07-13", "2026-08-03 19:15:53"), ("2026-06-11", "2026-08-10 06:32:27"),
    ("2026-06-04", "2026-08-03 11:27:53"), ("2026-05-31", "2026-07-30 21:48:12"),
    ("2026-05-30", "2026-07-29 20:23:16"),
]


class FakeConnFiltra:
    """Emula o WHERE/ORDER BY do banco sobre as 11 linhas reais."""

    def __init__(self, linhas=LINHAS_REAIS):
        self.linhas = linhas
        self.sql = None

    def run(self, sql, **params):
        self.sql = sql
        linhas = [(we, ga) for we, ga in self.linhas
                  if (":we" not in sql or we <= params["we"])
                  and (":ga" not in sql or ga <= params["ga"])]
        linhas.sort(reverse=True)
        return [[f"{we}-inicio", we, we, "abr28", 1000,
                 {"overall": {"rate": 0.01}}, {}, None, ga]
                for we, ga in linhas[:1]]

    def close(self):
        pass


def test_sql_sem_os_cortes_e_o_de_sempre():
    conn = FakeConnFiltra()
    r = read_rolling_reference(conn=conn)
    assert conn.sql == SQL_DE_SEMPRE          # byte a byte
    assert r["window_end"] == "2026-08-03"    # a linha de hoje, como sempre


def test_generated_at_max_devolve_a_linha_que_a_producao_servia_naquele_dia():
    """MEDIDO no banco em 24/08/2026: em 07/08 (dia em que o LF64 começou a
    captar) a referência servida era a de window_end 2026-07-13, e não a de
    hoje. Sem este corte, refazer o LF64 usaria a referência de agora."""
    conn = FakeConnFiltra()
    r = read_rolling_reference(conn=conn, generated_at_max="2026-08-07")
    assert r["window_end"] == "2026-07-13"
    assert "AND generated_at <= CAST(:ga AS timestamptz)" in conn.sql
    # o desempate por instante entra junto: 03/08/2026 teve DUAS reconstruções
    assert "ORDER BY window_end DESC, generated_at DESC LIMIT 1" in conn.sql


def test_window_end_max_corta_CONTEUDO_e_nao_o_instante():
    """A distinção que já confundiu duas sessões: `window_end` é até onde a
    referência ENXERGA; `generated_at` é quando ela passou a existir. Com corte
    de conteúdo em 11/06 sai a linha de 2026-06-11, que só foi GRAVADA em 10/08,
    ou seja depois da de 13/07 que o corte point-in-time devolve."""
    conn = FakeConnFiltra()
    assert read_rolling_reference(
        conn=conn, window_end_max="2026-06-11")["window_end"] == "2026-06-11"
    assert "AND window_end <= CAST(:we AS date)" in conn.sql
    assert read_rolling_reference(
        conn=FakeConnFiltra(), generated_at_max="2026-08-10")["window_end"] == "2026-07-13"


def test_corte_antes_de_tudo_nao_acha_nada():
    assert read_rolling_reference(conn=FakeConnFiltra(),
                                  generated_at_max="2026-01-01") is None


def test_credito_do_nao_respondente_so_com_valido():
    # medido na linha de 2026-08-03: credito 0,4102
    ref = {"conversion": {"survey_coverage": {"credito": 0.4102, "valido": True}}}
    assert credito_do_nao_respondente(ref) == 0.4102
    # inválido, ausente ou zerado: None, e o chamador mantém a moeda antiga
    assert credito_do_nao_respondente(
        {"conversion": {"survey_coverage": {"credito": 0.4102, "valido": False}}}) is None
    assert credito_do_nao_respondente({"conversion": {}}) is None
    assert credito_do_nao_respondente(None) is None


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
               test_read_none_quando_vazio, test_sql_sem_os_cortes_e_o_de_sempre,
               test_generated_at_max_devolve_a_linha_que_a_producao_servia_naquele_dia,
               test_window_end_max_corta_CONTEUDO_e_nao_o_instante,
               test_corte_antes_de_tudo_nao_acha_nada,
               test_credito_do_nao_respondente_so_com_valido,
               test_expected_conversion_interpola):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
