"""A repesca do HotLeads não pode derrubar a submissão.

O `/hotleads/submit-batch` faz dois trabalhos na mesma chamada, nesta ordem:

  1. repesca — reenvia o evento dos quentes que ficaram em 'error'
  2. submissão — manda os leads NOVOS pra Hotmart carimbar  ← o trabalho principal

Em 11-12/08/2026 o passo 1 derrubou o passo 2 vinte e três vezes em 24h. A consulta
da repesca varria 220 MB (Seq Scan) e estourava o timeout de 30s da conexão; a
exceção subia, a request morria em 500 e os leads novos não eram submetidos naquela
rodada. Como o cron repete de 15 em 15 minutos o efeito foi atraso, não perda, mas o
desenho estava invertido: o trabalho secundário decidindo o destino do principal.

A causa daquele timeout foi corrigida com um índice parcial (21s → 0,046ms). Estes
testes travam a OUTRA metade: mesmo que a repesca volte a falhar por qualquer motivo
(Hotmart fora, soluço de rede, bug novo), a submissão tem que acontecer.

É o mesmo princípio que `run_process_webhook` já aplica um nível abaixo ("falha de um
lead não derruba o lote"), agora no nível do passo.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# `api.app` monta o engine do SQLAlchemy no import e aborta sem credencial. Estes
# valores são dummy de propósito: o teste não abre conexão nenhuma (a de verdade é
# trocada por _FakeConn), só precisa que o import não morra. Setar antes do import.
os.environ.setdefault("RAILWAY_DB_HOST", "localhost")
os.environ.setdefault("RAILWAY_DB_PASSWORD", "dummy-para-teste")

import api.routers.webhooks as app_mod  # o handler e o helper _hotleads_webhook_url vivem no router
import api.hotleads_integration as hl
import src.data.ledger_connection as ledger_conn


class _FakeConn:
    def close(self):
        pass


class _Pipeline:
    class _Cfg:
        class _HL:
            enabled = True
        hotleads = _HL()
    _client_config = _Cfg()


def _rodar(retry_fn, submit_fn):
    """Chama o endpoint real com a repesca e a submissão trocadas."""
    orig = (hl.run_retry_failed, hl.run_submit_batch,
            ledger_conn.open_cloudsql_ledger_connection,
            app_mod._hotleads_webhook_url)
    hl.run_retry_failed = retry_fn
    hl.run_submit_batch = submit_fn
    ledger_conn.open_cloudsql_ledger_connection = lambda: _FakeConn()
    app_mod._hotleads_webhook_url = lambda: "https://exemplo.invalid/webhook"
    try:
        return asyncio.run(app_mod.hotleads_submit_batch(
            request=None, pipeline=_Pipeline(), limit=None, dry_run=False))
    finally:
        (hl.run_retry_failed, hl.run_submit_batch,
         ledger_conn.open_cloudsql_ledger_connection,
         app_mod._hotleads_webhook_url) = orig


def test_repesca_quebrada_nao_impede_submissao():
    """O caso do incidente: repesca explode, submissão TEM que rodar assim mesmo."""
    chamou = {"submit": False}

    def _retry_explode(conn, cfg, dry_run=False):
        raise RuntimeError("network error")

    def _submit(conn, cfg, webhook_url=None, limit=None, dry_run=False):
        chamou["submit"] = True
        return {"status": "ok", "submitted": 42}

    out = _rodar(_retry_explode, _submit)

    assert chamou["submit"], "submissão tinha que rodar mesmo com a repesca quebrada"
    assert out["submitted"] == 42, out
    # Conter não é engolir: o erro precisa VOLTAR no payload, senão a falha some.
    assert out["retry"]["status"] == "failed", out
    assert "RuntimeError" in out["retry"]["error"], out


def test_repesca_ok_segue_reportando_normalmente():
    """Caminho feliz intocado: o resultado da repesca continua no payload."""
    def _retry(conn, cfg, dry_run=False):
        return {"status": "ok", "candidates": 3, "sent": 3}

    def _submit(conn, cfg, webhook_url=None, limit=None, dry_run=False):
        return {"status": "ok", "submitted": 7}

    out = _rodar(_retry, _submit)

    assert out["submitted"] == 7, out
    assert out["retry"]["status"] == "ok", out
    assert out["retry"]["sent"] == 3, out


def test_falha_da_submissao_continua_subindo():
    """A submissão é o trabalho principal: se ELA falha, a rota tem que falhar.

    Sem este teste, "isolar a repesca" poderia virar "engolir tudo", e o cron
    passaria a devolver 200 com nada sendo submetido — falha silenciosa, que é
    pior do que a barulhenta que acabamos de consertar.
    """
    def _retry(conn, cfg, dry_run=False):
        return {"status": "ok"}

    def _submit(conn, cfg, webhook_url=None, limit=None, dry_run=False):
        raise RuntimeError("hotmart fora")

    try:
        _rodar(_retry, _submit)
    except RuntimeError:
        return
    raise AssertionError("falha na submissão deveria ter subido, não sido contida")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
