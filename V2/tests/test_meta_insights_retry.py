"""Retry de insights do Meta em erros transientes (api/meta_integration.py).

O Meta devolve erros transientes intermitentes (code 2 "Service temporarily
unavailable" etc.); sem retry, um soluço zera o gasto e o relatório sai sem
Meta. Estes testes fixam: transiente é re-tentado, 400 de parâmetro NÃO é, e
o retorno degrada pra [] só depois de esgotar as tentativas (nunca levanta).
"""
from unittest import mock

import requests

from api.meta_integration import MetaAdsIntegration


class FakeResp:
    def __init__(self, status_code, json_body=None, raise_it=False):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.text = str(self._json)
        self._raise_it = raise_it

    def json(self):
        return self._json

    def raise_for_status(self):
        if self._raise_it:
            raise requests.exceptions.HTTPError(response=self)


def _ok(n=4):
    return FakeResp(200, {"data": [{"i": k} for k in range(n)]})


def _meta_err(code, status=400, is_transient=False):
    return FakeResp(status, {"error": {"code": code, "is_transient": is_transient,
                                       "message": "x"}}, raise_it=True)


def _run(side_effect):
    cli = MetaAdsIntegration(access_token="tok")
    with mock.patch("api.meta_integration.requests.get") as g, \
         mock.patch("api.meta_integration.time.sleep") as slp:
        g.side_effect = side_effect
        out = cli.get_insights("act_1", since_date="2026-07-18", until_date="2026-07-19")
        return out, g.call_count, slp.call_count


def test_sucesso_primeira_tentativa():
    out, calls, sleeps = _run([_ok(4)])
    assert len(out) == 4 and calls == 1 and sleeps == 0


def test_transiente_code2_retenta_e_sucede():
    # code 2 = Service temporarily unavailable (o erro real de 19/07)
    out, calls, sleeps = _run([_meta_err(2), _ok(4)])
    assert len(out) == 4 and calls == 2 and sleeps == 1


def test_transiente_persistente_vira_lista_vazia():
    out, calls, sleeps = _run([_meta_err(2), _meta_err(2), _meta_err(2)])
    assert out == [] and calls == 3 and sleeps == 2  # esgotou MAX_RETRIES=3


def test_400_parametro_invalido_nao_retenta():
    # code 100 (param inválido) NÃO está no set retentável → falha rápido
    out, calls, sleeps = _run([_meta_err(100)])
    assert out == [] and calls == 1 and sleeps == 0


def test_5xx_retenta():
    out, calls, sleeps = _run([_meta_err(1, status=503), _ok(4)])
    assert len(out) == 4 and calls == 2 and sleeps == 1


def test_timeout_sem_response_retenta():
    out, calls, sleeps = _run([requests.exceptions.Timeout(), _ok(4)])
    assert len(out) == 4 and calls == 2 and sleeps == 1


def test_is_transient_true_mesmo_code_desconhecido():
    out, calls, sleeps = _run([_meta_err(9999, is_transient=True), _ok(4)])
    assert len(out) == 4 and calls == 2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn()
            print(f"  [OK ] {fn.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  [FALHOU] {fn.__name__}: {e!r}")
    print(f"\n{ok}/{len(fns)} passaram")
    raise SystemExit(0 if ok == len(fns) else 1)
