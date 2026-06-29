"""Testes do parser de gclid da URL (anti-corrupção do click-id na ingestão).

Rodável sem pytest:  python tests/test_gclid_parse.py

O front embute o gclid na utm_url (?gclid=...). `parse_gclid_from_url` traduz
isso pro nosso gclid na borda, pra alimentar o envio de conversão sem depender
do front mandar um campo próprio.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.google_ads_integration import parse_gclid_from_url as P


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


tests = [
    test_url_real_com_gclid,
    test_lead_teste_gclid_fake,
    test_gclid_no_meio_de_outros_params,
    test_sem_gclid_retorna_none,
    test_bordas,
    test_gclid_vazio_vira_none,
    test_gclid_url_encoded,
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
