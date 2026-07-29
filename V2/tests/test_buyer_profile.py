"""buyer_profile (Fase 1a): perfil categórico dos compradores da janela rolante.

Cobre: mapeamento slug→canônico + has_computer, régua de categoria compartilhada,
cobertura medida, fail-loud em vazio. Conexão fake (sem banco).

Rodável:  PYTHONPATH=. python tests/test_buyer_profile.py
"""
from datetime import date

from src.monitoring.buyer_profile import build_buyer_profile, PROFILE_FEATURES


class FakeConn:
    """Roteia por SQL: COUNT devolve total de compradores; o JOIN devolve os
    surveys (jsonb, has_computer)."""
    def __init__(self, *, n_total, survey_rows):
        self._n_total = n_total
        self._survey_rows = survey_rows
        self.closed = False

    def run(self, sql, **params):
        if "count(DISTINCT" in sql:
            return [[self._n_total]]
        return list(self._survey_rows)

    def close(self):
        self.closed = True


def _rows():
    # 4 compradores: slug + PT-Long misturados, has_computer da coluna e do survey.
    return [
        ({"genero": "Masculino", "idade": "25 34 anos", "ocupacao": "Sou autônomo",
          "cartaoCredito": "Sim", "estudouProgramacao": "Não"}, "SIM"),
        ({"genero": "Masculino", "idade": "18 24 anos"}, "SIM"),
        ({"O seu gênero:": "Feminino", "Qual a sua idade?": "mais de 55 anos"}, None),
        ({"genero": "masculino"}, "NAO"),
    ]


def test_perfil_normaliza_e_conta():
    conn = FakeConn(n_total=10, survey_rows=_rows())
    prof = build_buyer_profile(as_of=date(2026, 7, 29), conn=conn)
    assert prof["n_buyers_total"] == 10
    assert prof["n_buyers_surveyed"] == 4
    assert prof["coverage"] == 0.4  # 4/10
    genero = prof["categorical_features"]["O seu gênero:"]["proportions"]
    # 3 masculino (inclui 'masculino' minúsculo unificado) + 1 feminino
    assert round(genero["Masculino"], 4) == 0.75
    assert round(genero["Feminino"], 4) == 0.25
    idade = prof["categorical_features"]["Qual a sua idade?"]["proportions"]
    assert "25-34" in idade and "18-24" in idade and "55+" in idade  # unificado
    comp = prof["categorical_features"]["Tem computador/notebook?"]
    # 3º comprador sem has_computer e sem chave no survey → (nulo), fora da conta.
    assert comp["n_responses"] == 3  # 2 SIM + 1 NAO (o None sai)
    assert round(comp["proportions"]["Sim"], 4) == 0.6667
    assert round(comp["proportions"]["Não"], 4) == 0.3333


def test_conexao_injetada_nao_fecha():
    conn = FakeConn(n_total=10, survey_rows=_rows())
    build_buyer_profile(as_of=date(2026, 7, 29), conn=conn)
    assert conn.closed is False  # dono da conexão é quem injetou


def test_fail_loud_em_vazio():
    conn = FakeConn(n_total=5, survey_rows=[])
    try:
        build_buyer_profile(as_of=date(2026, 7, 29), conn=conn)
    except ValueError as e:
        assert "0 compradores com survey" in str(e)
    else:
        raise AssertionError("esperava ValueError em janela sem survey")


def test_allow_empty_nao_quebra():
    conn = FakeConn(n_total=5, survey_rows=[])
    prof = build_buyer_profile(as_of=date(2026, 7, 29), conn=conn, allow_empty=True)
    assert prof["n_buyers_surveyed"] == 0 and prof["coverage"] == 0.0
    assert set(prof["categorical_features"]) == set(PROFILE_FEATURES)


if __name__ == "__main__":
    for fn in (test_perfil_normaliza_e_conta, test_conexao_injetada_nao_fecha,
               test_fail_loud_em_vazio, test_allow_empty_nao_quebra):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
