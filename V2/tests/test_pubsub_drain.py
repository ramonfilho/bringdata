"""Testes do laço de drenagem do consumer Pub/Sub (`drain_pending_pubsub`).

POR QUE ISTO EXISTE
-------------------
Uma invocação do cron puxava no máximo `DEFAULT_BATCH` mensagens e ia embora, mesmo com
a fila cheia. O resto só era olhado no tick seguinte, 5 minutos depois. Duas consequências
que o operador sentia:

  1. mensagem antiga envelhecia em degrau, e o alerta de "oldest unacked > 30min"
     disparava com a fila drenando normalmente;
  2. depois de qualquer parada (o apagão de 23/07 foi o caso extremo), a única forma de
     recuperar em tempo hábil era disparar POST na mão num laço.

O laço resolve isso, mas a parte que os testes protegem é o CONTRÁRIO: que ele SAIA.
Um drenador sem freio dentro de uma request com prazo é troca de um problema de operação
por uma queda. Por isso três saídas explícitas e um campo dizendo por qual delas saiu —
"processou 2.000" não distingue fila drenada de teto batido, e essa é justamente a
diferença entre estar tudo bem e precisar de ação.

Rodar: python3 -m pytest V2/tests/test_pubsub_drain.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

import pytest

from api import pubsub_branch as pb


def _rodada(processed, **extra):
    """Resposta de uma rodada no mesmo formato de `process_pending_pubsub`."""
    base = {"processed": processed, "sent": processed, "skipped_allowlist": 0,
            "skipped_missing_data": 0, "errors": 0, "dry_run": False}
    base.update(extra)
    return base


def _fake(respostas, registro=None):
    """Substitui `process_pending_pubsub` por uma sequência fixa de respostas."""
    seq = list(respostas)

    def _f(*a, **kw):
        if registro is not None:
            registro.append(kw)
        return seq.pop(0) if seq else _rodada(0)

    return _f


def test_drena_ate_a_fila_esvaziar(monkeypatch):
    """Caso normal: continua puxando enquanto vier mensagem, para no primeiro vazio."""
    monkeypatch.setattr(pb, "process_pending_pubsub",
                        _fake([_rodada(250), _rodada(250), _rodada(37), _rodada(0)]))
    r = pb.drain_pending_pubsub(None, None, None)

    assert r["rounds"] == 4                    # 3 com carga + 1 que achou vazio
    assert r["drain_stop"] == "fila_vazia"
    assert r["processed"] == 537               # soma, não sobrescreve
    assert r["sent"] == 537


def test_uma_rodada_quando_a_fila_ja_esta_vazia(monkeypatch):
    """Dia normal (fluxo baixo): não pode custar rodada extra à toa."""
    monkeypatch.setattr(pb, "process_pending_pubsub", _fake([_rodada(0)]))
    r = pb.drain_pending_pubsub(None, None, None)

    assert r["rounds"] == 1
    assert r["drain_stop"] == "fila_vazia"
    assert r["processed"] == 0


def test_para_no_teto_de_rodadas_e_avisa(monkeypatch):
    """Fila que nunca esvazia (publisher em loop) não pode prender a request."""
    monkeypatch.setattr(pb, "process_pending_pubsub", _fake([_rodada(250)] * 50))
    r = pb.drain_pending_pubsub(None, None, None, max_rounds=3)

    assert r["rounds"] == 3
    assert r["drain_stop"] == "teto_de_rodadas"
    assert r["processed"] == 750


def test_para_no_teto_de_tempo(monkeypatch):
    """O prazo do Scheduler é 180s; estourar faria ele contar falha e reentregar.
    Sobrar mensagem pro próximo tick é o desfecho barato, e é o escolhido."""
    monkeypatch.setattr(pb, "process_pending_pubsub", _fake([_rodada(250)] * 50))
    r = pb.drain_pending_pubsub(None, None, None, max_seconds=0.0, max_rounds=99)

    assert r["rounds"] == 1                    # sai já na 1ª checagem de tempo
    assert r["drain_stop"] == "teto_de_tempo"


def test_repassa_os_argumentos_de_cada_rodada(monkeypatch):
    """dry_run/batch/ledger_conn têm que chegar em TODA rodada — se o laço perdesse o
    dry_run a partir da 2ª, um smoke em canary passaria a escrever de verdade."""
    reg = []
    monkeypatch.setattr(pb, "process_pending_pubsub",
                        _fake([_rodada(250), _rodada(0)], registro=reg))
    sentinela = object()
    pb.drain_pending_pubsub(None, None, None, dry_run=True, batch=77,
                            ledger_conn=sentinela)

    assert len(reg) == 2
    for kw in reg:
        assert kw["dry_run"] is True
        assert kw["batch"] == 77
        assert kw["ledger_conn"] is sentinela


def test_nao_soma_campos_booleanos(monkeypatch):
    """`dry_run` é bool; somar viraria 2 e o consumidor leria como verdadeiro estranho."""
    monkeypatch.setattr(pb, "process_pending_pubsub",
                        _fake([_rodada(10, dry_run=True), _rodada(0, dry_run=True)]))
    r = pb.drain_pending_pubsub(None, None, None, dry_run=True)

    assert r["dry_run"] is True
    assert r["processed"] == 10


def test_tetos_padrao_cabem_no_prazo_do_scheduler():
    """Guarda de configuração: o teto de tempo tem que deixar folga pro attemptDeadline
    de 180s do cron `pubsub-process-pending`. Se alguém subir _DRAIN_SECONDS pra perto
    de 180, a request passa a estourar o prazo e o Scheduler reentrega."""
    assert pb._DRAIN_SECONDS <= 150.0
    assert 1 <= pb._DRAIN_MAX_ROUNDS <= 20


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
