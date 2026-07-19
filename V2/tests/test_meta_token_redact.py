"""Redação de access_token nos logs do cliente Meta (api/meta_integration.py).

O Meta Graph API põe o access_token na query string; a exceção do requests
ecoa a URL inteira, vazando a credencial nos logs do Cloud Run. _redact()
raspa isso antes de logar.
"""
from api.meta_integration import _redact

# String de erro REAL observada no log do Cloud Run (token encurtado)
REAL_ERR = (
    "400 Client Error: Bad Request for url: "
    "https://graph.facebook.com/v24.0/act_188005769808959/insights"
    "?access_token=EAAS9hlWC7lkBRKQh8BacVmj5HJxdjuCACN94LZBIprB"
    "&level=campaign&fields=campaign_name%2Cspend&limit=1000"
)


def test_raspa_token_do_erro_real():
    out = _redact(REAL_ERR)
    assert "EAAS9hlWC7lk" not in out          # o token some
    assert "access_token=<REDACTED>" in out    # marcado como redigido
    assert "level=campaign" in out             # resto da URL intacto
    assert "act_188005769808959" in out        # account id não é segredo


def test_string_sem_token_inalterada():
    s = "conexão recusada: timeout after 10s"
    assert _redact(s) == s


def test_multiplos_segredos():
    s = "url?access_token=ABC123&client_secret=XYZ789&level=campaign"
    out = _redact(s)
    assert "ABC123" not in out and "XYZ789" not in out
    assert "access_token=<REDACTED>" in out and "client_secret=<REDACTED>" in out
    assert "level=campaign" in out


def test_token_no_fim_sem_ampersand():
    out = _redact("for url: https://x/insights?access_token=SECRETVALUE")
    assert "SECRETVALUE" not in out
    assert out.endswith("access_token=<REDACTED>")


def test_aceita_objeto_excecao_nao_string():
    class FakeExc(Exception):
        def __str__(self):
            return "boom for url: https://x?access_token=LEAKME&a=1"
    out = _redact(FakeExc())
    assert "LEAKME" not in out and "access_token=<REDACTED>" in out


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn(); print(f"  [OK ] {fn.__name__}"); ok += 1
        except AssertionError as e:
            print(f"  [FALHOU] {fn.__name__}: {e!r}")
    print(f"\n{ok}/{len(fns)} passaram")
    raise SystemExit(0 if ok == len(fns) else 1)
