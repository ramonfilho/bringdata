"""Trava do comportamento: com conversion_action_id_with_value=None (desligado
29/06, prioridade máxima), o envio Google NÃO dispara o evento com valor —
só o D9+D10 (high_quality). Não-HQ fica 'skipped', não 'sent' nem 'error'.

Rodável sem pytest:  python tests/test_google_value_event_off.py
"""
import contextlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api.google_ads_integration as G


class _Cfg:
    enabled = True
    customer_id = "123"
    login_customer_id = None
    conversion_action_id_with_value = None        # <== DESLIGADO
    conversion_action_id_high_quality = "999"
    currency = "BRL"
    high_quality_decils = ["D09", "D10"]
    source_allowlist = ["google-ads"]


@contextlib.contextmanager
def _stub():
    """Isola a lógica de dispatch (o que mudou); sem rede. E DESFAZ no fim.

    Antes isto era uma função que sobrescrevia os cinco nomes do módulo por
    atribuição direta e NUNCA restaurava. Consequência medida em 08/08/2026: depois
    que este arquivo rodava, `G.is_eligible` continuava devolvendo (True, 'ok') para
    o resto da suíte. No `test_pubsub_branch`, isso fazia TODO lead virar elegível
    pro Google, o caminho do Google Ads ligar onde não devia, e os três testes de
    scoring em lote morrerem com `'_Cfg' object has no attribute 'business'`.

    O sintoma era o pior tipo: os três passavam rodando sozinhos e só quebravam na
    suíte completa, o que faz parecer flakiness e não vazamento. Pior ainda, um stub
    que sobrevive pode fazer um teste PASSAR quando deveria falhar.

    Context manager em vez de `monkeypatch` de propósito: o arquivo se propõe a
    rodar sem pytest (ver docstring do topo), e `monkeypatch` é fixture.
    """
    _orig = {n: getattr(G, n) for n in
             ("is_eligible", "compute_value", "build_event",
              "build_ingest_request", "_post_ingest")}
    G.is_eligible = lambda lead, cfg: (True, "ok")
    G.compute_value = lambda *a, **k: 1.0
    G.build_event = lambda **k: {"transaction_id": k.get("transaction_id")}
    G.build_ingest_request = lambda **k: {"conversion_action_id": k.get("conversion_action_id")}
    G._post_ingest = lambda req: {"status": "sent"}
    try:
        yield
    finally:
        for n, v in _orig.items():
            setattr(G, n, v)


def _leads():
    return [
        {"email": "a@a", "phone": "1", "decil": "D05", "event_id": "e1", "source": "google-ads", "event_timestamp_iso": "t"},
        {"email": "b@b", "phone": "2", "decil": "D10", "event_id": "e2", "source": "google-ads", "event_timestamp_iso": "t"},
    ]


def test_value_off_nao_envia_value_so_hq():
    with _stub():
        out = G.send_batch_events(_leads(), google_config=_Cfg(), business_config=None, dry_run=False)
    res = out["results"]
    # NENHUM evento 'value' foi enviado (todos os 'value' são skipped)
    value_res = [r for r in res if r.get("destination") == "value"]
    assert value_res and all(r["status"] == "skipped" for r in value_res), value_res
    assert not any(r.get("destination") == "value" and r.get("status") == "sent" for r in res)
    # o D10 disparou o HQ
    hq = [r for r in res if r.get("destination") == "high_quality"]
    assert len(hq) == 1 and hq[0]["status"] == "sent", hq
    # o D05 (não-HQ) NÃO disparou HQ
    assert all(r.get("decil") != "D05" for r in res if r.get("destination") == "high_quality")


def test_value_off_nao_marca_erro_falso():
    # contadores: nada de 'sent' do value; o único 'sent' é o HQ do D10
    with _stub():
        out = G.send_batch_events(_leads(), google_config=_Cfg(), business_config=None, dry_run=False)
    assert out["sent"] == 1      # só o HQ do D10
    assert out["errors"] == 0    # value desligado não é erro
    assert out["skipped"] == 2   # os 2 'value' pulados


tests = [test_value_off_nao_envia_value_so_hq, test_value_off_nao_marca_erro_falso]

if __name__ == "__main__":
    fails = 0
    for t in tests:
        try:
            t(); print(f"  ok  {t.__name__}")
        except Exception as e:
            fails += 1; print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - fails}/{len(tests)} passaram")
    sys.exit(1 if fails else 0)
