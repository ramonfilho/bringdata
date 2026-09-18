"""Etapa 5 do treino contínuo: o drift de score chama o job de retreino, com cooldown (18/09/2026)."""
from datetime import datetime, timedelta, timezone

import src.retreino.gatilho as g

AGORA = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def test_cooldown_de_14_dias():
    assert g.deve_disparar(None, AGORA)
    assert g.deve_disparar({"ts": (AGORA - timedelta(days=14)).isoformat()}, AGORA)
    assert not g.deve_disparar({"ts": (AGORA - timedelta(days=13, hours=23)).isoformat()}, AGORA)
    assert g.deve_disparar({"ts": "lixo"}, AGORA)


def test_dispara_grava_o_marcador_e_respeita_o_cooldown(monkeypatch):
    marcador = {}
    monkeypatch.setattr(g, "_ler_marcador", lambda: marcador.get("d"))
    monkeypatch.setattr(g, "_gravar_marcador", lambda d: marcador.__setitem__("d", d))
    monkeypatch.setattr(g, "_executar_job", lambda: 200)
    r = g.disparar_retreino("score_drift: teste", agora=AGORA)
    assert r["disparado"] and marcador["d"]["motivo"] == "score_drift: teste" and marcador["d"]["http"] == 200
    r2 = g.disparar_retreino("score_drift: de novo", agora=AGORA + timedelta(days=1))
    assert r2["disparado"] is False and "cooldown" in r2["motivo"]


def test_erro_nunca_sobe_para_o_ciclo_de_alertas(monkeypatch):
    monkeypatch.setattr(g, "_ler_marcador", lambda: (_ for _ in ()).throw(RuntimeError("bucket fora")))
    r = g.disparar_retreino("x", agora=AGORA)
    assert r["disparado"] is False and "RuntimeError" in r["erro"]
