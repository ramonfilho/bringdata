"""O histórico do criativo tem que casar por GRAFIA, não por bytes.

Trava os dois vazamentos medidos em 19/08/2026 montando o backtest do teto no DEV21:

  1. o carimbo `[G] ` que o resolvedor do Google põe no nome fazia `[G] DEV-AD0140`
     não achar os 960 leads gravados como `DEV-AD0140`;
  2. o acento em "captação" existe em duas formas Unicode, e a tabela abria DUAS
     linhas pro mesmo anúncio (806 chaves cruas que são 769 criativos). Esse é o
     pior dos dois: a busca ACHA uma das gavetas e devolve metade da evidência sem
     erro nenhum, o peso `n/(n+2000)` cai e o teto afrouxa em silêncio.

O caso de CONTROLE é o que separa "consertou" de "fundiu demais": criativo sem
acento e sem carimbo tem que sair com o MESMO número de antes.
"""
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.criativo_historico import chave_canonica, le_historico  # noqa: E402

NOME = "DEV-AD0150-vid-captação-VARIAÇÃO-AD07-Briefing-AnaLaura"
NFC = unicodedata.normalize("NFC", NOME)
NFD = unicodedata.normalize("NFD", NOME)


class _Conn:
    """Conexão de mentira: devolve as linhas do histórico e um mapa de id vazio."""

    def __init__(self, linhas, mapa=()):
        self._linhas, self._mapa = linhas, list(mapa)

    def run(self, sql, **kw):
        return self._mapa if "criativo_id_map" in sql else self._linhas


def _linha(criativo, leads, compradores, esperados):
    return [criativo, leads, compradores, esperados, None, None]


def test_nfc_e_nfd_sao_o_mesmo_criativo():
    assert NFC != NFD, "o fixture precisa das duas formas Unicode pra ter sentido"
    h = le_historico(_Conn([_linha(NFC, 6000, 40, 30.0),
                            _linha(NFD, 4000, 20, 25.0)]))
    for grafia in (NFC, NFD):
        assert h.get(grafia)["leads"] == 10000, "gaveta partida por acento"
        assert h.get(grafia)["compradores"] == 60
        assert h.get(grafia)["esperados"] == 55.0


def test_grafia_ausente_da_tabela_ainda_acha():
    """O ledger pode trazer uma grafia que a tabela não tem. É o caso que apelido
    nenhum resolve, e o motivo de a consulta canonizar."""
    h = le_historico(_Conn([_linha(NFC, 6000, 40, 30.0)]))
    assert h.get(NFD)["leads"] == 6000
    assert NFD in h


def test_carimbo_do_google_acha_o_historico_da_meta():
    h = le_historico(_Conn([_linha("DEV-AD0140-vid-captacao-V0-PODCAST", 960, 7, 5.0)]))
    assert h.get("[G] DEV-AD0140-vid-captacao-V0-PODCAST")["leads"] == 960


def test_id_numerico_do_google_continua_funcionando():
    """A fusão de 18/08 (id → nome via criativo_id_map) não pode ter regredido."""
    h = le_historico(_Conn(
        [_linha("804418131085", 500, 3, 2.0), _linha("DEV-AD0140", 460, 4, 3.0)],
        mapa=[["804418131085", "[G] DEV-AD0140"]]))
    for chave in ("804418131085", "DEV-AD0140", "[G] DEV-AD0140"):
        assert h.get(chave)["leads"] == 960, f"{chave} caiu na gaveta errada"


def test_controle_criativo_sem_acento_nao_muda():
    """Sem acento e sem carimbo, o número tem que ser byte a byte o de antes."""
    h = le_historico(_Conn([_linha("DEV-AD0027-vid-V0-DEV", 38101, 300, 290.0)]))
    g = h.get("DEV-AD0027-vid-V0-DEV")
    assert (g["leads"], g["compradores"], g["esperados"]) == (38101, 300, 290.0)
    assert len(h) == 1, "não pode inventar chave pra quem já era único"


def test_nomes_de_verdade_diferentes_nao_fundem():
    """A canonização não pode colapsar anúncios que só PARECEM parecidos."""
    h = le_historico(_Conn([_linha("DEV-AD0139-vid-captação-V0-PODCAST", 502, 4, 3.0),
                            _linha("DEV-AD0140-vid-captação-V0-PODCAST", 960, 7, 5.0)]))
    assert h.get("DEV-AD0139-vid-captação-V0-PODCAST")["leads"] == 502
    assert h.get("DEV-AD0140-vid-captação-V0-PODCAST")["leads"] == 960


def test_tabela_ausente_continua_degradando_pra_vazio():
    class _Quebra:
        def run(self, *a, **k):
            raise RuntimeError("relation does not exist")

    assert le_historico(_Quebra()) == {}


def test_chave_canonica_tira_carimbo_acento_caixa_e_espaco():
    assert chave_canonica("[G] DEV-AD0140") == chave_canonica("dev-ad0140")
    assert chave_canonica(NFC) == chave_canonica(NFD)
    assert chave_canonica("  DEV  AD0140 ") == chave_canonica("dev ad0140")
    assert chave_canonica(None) == ""
