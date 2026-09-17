"""A auditoria da entrega Zanelato só compara as linhas que o nosso script escreve.

Desde 10/09/2026 outra integração grava o funil MBA na mesma `public.leads_inbound`,
com a data em barra (`2026/09/10`). Medido em 17/09: 108.333 linhas nossas (data
`AAAA-MM-DD`) e 652 deles. Sem filtro, as linhas deles viravam um mês `2026/09` que a
origem não tem e a auditoria falhava todo dia desde 11/09.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import push_supabase_zanelato as z  # noqa: E402

CORTE = "2026-06-19"
NOSSAS = {"2026-06": 10, "2026-07": 20, "2026-08": 30, "2026-09": 40}
DE_OUTROS = 652


class _Origem:
    def run(self, sql, **params):
        if "::text" in sql:
            return [[CORTE]]
        return [[m, n] for m, n in NOSSAS.items()]

    def close(self):
        pass


class _Destino:
    """Aplica de verdade o filtro de forma da data às linhas que finge ter."""

    def __init__(self):
        self.linhas = [(f"{m}-20", n) for m, n in NOSSAS.items()] + [("2026/09/12", DE_OUTROS)]
        self.consultas = []

    def _filtra(self, sql):
        # Reage ao texto REAL do filtro, não à constante: assim o teste que troca a
        # constante por TRUE vê o dublê contar tudo, como o Postgres faria.
        filtro = "data ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"
        so_nossas = filtro in sql
        negado = f"NOT ({filtro})" in sql
        out = []
        for data, n in self.linhas:
            nossa = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", data) is not None
            if negado and nossa:
                continue
            if so_nossas and not negado and not nossa:
                continue
            out.append((data, n))
        return out

    def run(self, sql, **params):
        self.consultas.append(sql)
        linhas = self._filtra(sql)
        if "GROUP BY" in sql:
            por_mes = {}
            for data, n in linhas:
                if data >= params["c"]:
                    por_mes[data[:7]] = por_mes.get(data[:7], 0) + n
            return [[m, n] for m, n in por_mes.items()]
        if "data <" in sql:
            return [[sum(n for d, n in linhas if d < params["c"])]]
        return [[sum(n for _, n in linhas)]]

    def close(self):
        pass


@pytest.fixture
def pontas(monkeypatch):
    dst = _Destino()
    avisos = []
    monkeypatch.setattr(z, "origem_leitura", lambda timeout=0: _Origem())
    monkeypatch.setattr(z, "destino", lambda porta=None: dst)
    monkeypatch.setattr(z, "_avisa_no_dm", lambda tabela, texto: avisos.append(texto))
    return dst, avisos


def test_linhas_de_outra_integracao_nao_derrubam_a_auditoria(pontas):
    dst, avisos = pontas
    r = z.auditar()
    assert r["linhas"] == sum(NOSSAS.values())
    assert r["de_outros"] == DE_OUTROS
    assert avisos and "conferida" in avisos[-1]


def test_a_comparacao_por_mes_filtra_pela_forma_da_data(pontas):
    dst, _ = pontas
    z.auditar()
    por_mes = [q for q in dst.consultas if "GROUP BY" in q]
    assert por_mes and z.SO_NOSSAS in por_mes[0]


def test_sem_o_filtro_o_mes_com_barra_faria_falhar(pontas, monkeypatch):
    """Prova que o filtro é o que segura: com ele desligado, a auditoria cai."""
    monkeypatch.setattr(z, "SO_NOSSAS", "TRUE")
    with pytest.raises(SystemExit, match="2026/09"):
        z.auditar()
