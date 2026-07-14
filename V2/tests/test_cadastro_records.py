"""Testes de `src/data/cadastro_records.py` — dedup por email + construção do
CadastroRec. Injeta uma conexão FAKE (o SQL de filtro roda no banco; aqui a
gente valida a lógica Python), no mesmo padrão dos testes que injetam um
`ga_service` fake no cliente da Google Ads API.
"""
from src.data.cadastro_records import google_cadastro_records, CadastroRec


class _FakeConn:
    """Conn fake: `.run(sql, **params)` devolve linhas pré-canned, ignorando o
    SQL (o filtro real é do banco). Guarda os params pra checagem."""

    def __init__(self, rows):
        self._rows = rows
        self.last_params = None

    def run(self, sql, **params):
        self.last_params = params
        return self._rows


def test_dedup_por_email_fica_o_mais_recente():
    # mesmo email em 2 UTMs; term do trackedAt maior deve vencer
    rows = [
        ("a@x.com", "google-ads", "111--a--b", 10),
        ("a@x.com", "google-ads", "999--c--d", 20),  # mais recente
        ("b@x.com", "google-ads", "222--e--f", 5),
    ]
    out = google_cadastro_records(_FakeConn(rows), "2026-07-01", "2026-07-01", ["google-ads"])
    assert len(out) == 2, "1 registro por email distinto"
    by = {r.utm_term for r in out}
    assert "999--c--d" in by and "111--a--b" not in by, "fica o term do UTM mais recente"
    assert all(isinstance(r, CadastroRec) for r in out)
    assert all(r.utm_source == "google-ads" for r in out)


def test_tracked_none_nao_quebra():
    rows = [
        ("a@x.com", "google-ads", "111--a--b", None),
        ("a@x.com", "google-ads", "222--c--d", 7),  # com tracked vence o None
    ]
    out = google_cadastro_records(_FakeConn(rows), "2026-07-01", "2026-07-01", ["google-ads"])
    assert len(out) == 1
    assert out[0].utm_term == "222--c--d"


def test_sources_vazio_curto_circuita():
    fc = _FakeConn([("a@x.com", "google-ads", "1--a--b", 1)])
    out = google_cadastro_records(fc, "2026-07-01", "2026-07-01", [])
    assert out == [], "sources vazio → lista vazia sem bater no banco"
    assert fc.last_params is None, "não chamou .run"


def test_params_passados_em_lower():
    fc = _FakeConn([])
    google_cadastro_records(fc, "2026-06-22", "2026-07-01", ["Google-Ads", "FB"])
    assert fc.last_params["s"] == "2026-06-22"
    assert fc.last_params["e"] == "2026-07-01"
    assert fc.last_params["src"] == ["google-ads", "fb"], "sources normalizados p/ lower"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK {name}")
    print("todos passaram")
