"""Testes do parser de gclid da URL (anti-corrupção do click-id na ingestão).

Rodável sem pytest:  python tests/test_gclid_parse.py

O front embute o gclid na utm_url (?gclid=...). `parse_gclid_from_url` traduz
isso pro nosso gclid na borda, pra alimentar o envio de conversão sem depender
do front mandar um campo próprio.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.google_ads_integration import (
    parse_gclid_from_url as P,
    parse_click_ids_from_url as PC,
    build_event,
)


def _ad_ids(**kw):
    """adIdentifiers do evento montado com os click-ids passados (ou {} se nenhum)."""
    ev = build_event(email="a@b.com", phone=None, value=1.0, currency="BRL",
                     event_timestamp_iso="2026-07-03T00:00:00Z", transaction_id="t1", **kw)
    return ev.get("adIdentifiers", {})


def test_url_real_com_gclid():
    assert P("https://lp.devclub.com.br/cap-go-a-v2/?gclid=Cj0KCQjwr4jSBhCabc123") == "Cj0KCQjwr4jSBhCabc123"


def test_lead_teste_gclid_fake():
    assert P("https://lp.devclub.com.br/cap-go-a-v2/?gclid=AAAAAAAAAAAAAAAAA") == "AAAAAAAAAAAAAAAAA"


def test_gclid_no_meio_de_outros_params():
    assert P("https://x.com/lp/?utm_source=google-ads&gclid=ABC999&utm_campaign=devlf") == "ABC999"


def test_sem_gclid_retorna_none():
    assert P("https://x.com/lp/?utm_source=google-ads&utm_campaign=devlf") is None
    assert P("https://x.com/lp/") is None


def test_bordas():
    assert P(None) is None
    assert P("") is None
    assert P("   ") is None
    assert P("not a url at all") is None


def test_gclid_vazio_vira_none():
    assert P("https://x.com/lp/?gclid=") is None
    assert P("https://x.com/lp/?gclid=%20") is None   # só espaço (decodificado) → None


def test_gclid_url_encoded():
    # urllib decodifica %2D etc; gclid normalmente não tem encoding, mas garante robustez
    assert P("https://x.com/?gclid=A%2DB%5FC") == "A-B_C"


def test_click_ids_extrai_os_tres():
    # gbraid = clique iOS app; wbraid = clique iOS web/Safari (substituem o gclid)
    assert PC("https://x.com/?gbraid=GB123") == {"gclid": None, "gbraid": "GB123", "wbraid": None}
    assert PC("https://x.com/?wbraid=WB456") == {"gclid": None, "gbraid": None, "wbraid": "WB456"}
    assert PC("https://x.com/?gclid=G1&wbraid=W1") == {"gclid": "G1", "gbraid": None, "wbraid": "W1"}


def test_click_ids_bordas():
    vazio = {"gclid": None, "gbraid": None, "wbraid": None}
    assert PC(None) == vazio and PC("") == vazio and PC("https://x.com/lp/") == vazio
    assert PC("https://x.com/?gbraid=") == vazio   # vazio → None


def test_gclid_wrapper_ainda_bate_com_a_base():
    assert P("https://x.com/?gclid=G9&gbraid=GB9") == "G9" == PC("https://x.com/?gclid=G9&gbraid=GB9")["gclid"]


def test_build_event_adidentifiers_prioridade():
    # só gclid
    assert _ad_ids(gclid="G1") == {"gclid": "G1"}
    # só iOS → manda o id de iOS (recupera atribuição que hoje se perde)
    assert _ad_ids(gbraid="GB1") == {"gbraid": "GB1"}
    assert _ad_ids(wbraid="WB1") == {"wbraid": "WB1"}
    # gclid tem prioridade quando há mais de um (id de clique é único por evento)
    assert _ad_ids(gclid="G1", wbraid="WB1") == {"gclid": "G1"}
    assert _ad_ids(gbraid="GB1", wbraid="WB1") == {"gbraid": "GB1"}
    # sem nenhum → sem adIdentifiers (casa só por email/telefone hash)
    assert _ad_ids() == {}


tests = [
    test_url_real_com_gclid,
    test_lead_teste_gclid_fake,
    test_gclid_no_meio_de_outros_params,
    test_sem_gclid_retorna_none,
    test_bordas,
    test_gclid_vazio_vira_none,
    test_gclid_url_encoded,
    test_click_ids_extrai_os_tres,
    test_click_ids_bordas,
    test_gclid_wrapper_ainda_bate_com_a_base,
    test_build_event_adidentifiers_prioridade,
]

if __name__ == "__main__":
    fails = 0
    for t in tests:
        try:
            t(); print(f"  ok  {t.__name__}")
        except Exception as e:
            fails += 1; print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - fails}/{len(tests)} passaram")
    sys.exit(1 if fails else 0)
