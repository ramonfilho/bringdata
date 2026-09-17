"""O token de identidade do Google vale 60 minutos; o cache renova aos 50.

Medido em 17/09/2026 (run #8 do deploy): o vigia de 60 minutos guardou o token da
primeira rodada, e a rodada dos 61 minutos levou 401 no feature-report (log do Cloud
Run, 15:31:56Z), ficando cega sem avisar.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gcp_auth  # noqa: E402

AUD = "https://smart-ads-api-x-uc.a.run.app"


class _Saida:
    def __init__(self, tok):
        self.stdout = tok + "\n"
        self.stderr = ""
        self.returncode = 0


def _prepara(monkeypatch):
    chamadas = []
    tokens = iter(["A" * 120, "B" * 120, "C" * 120])

    def falso_run(cmd, **kw):
        chamadas.append(cmd)
        return _Saida(next(tokens))

    relogio = {"t": 1000.0}
    monkeypatch.setattr(gcp_auth.subprocess, "run", falso_run)
    monkeypatch.setattr(gcp_auth, "_CACHE", {})
    monkeypatch.setattr(gcp_auth, "_agora", lambda: relogio["t"])
    return chamadas, relogio


def test_reusa_o_token_dentro_da_validade(monkeypatch):
    chamadas, relogio = _prepara(monkeypatch)
    primeiro = gcp_auth.token_de_identidade(AUD)
    relogio["t"] += 49 * 60
    assert gcp_auth.token_de_identidade(AUD) == primeiro
    assert len(chamadas) == 1


def test_renova_o_token_depois_de_50_min(monkeypatch):
    chamadas, relogio = _prepara(monkeypatch)
    primeiro = gcp_auth.token_de_identidade(AUD)
    relogio["t"] += 51 * 60
    segundo = gcp_auth.token_de_identidade(AUD)
    assert segundo != primeiro
    assert len(chamadas) == 2


def test_validade_fica_abaixo_da_vida_do_token():
    assert 30 * 60 <= gcp_auth.VALIDADE_S < 60 * 60
