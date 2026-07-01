"""Guarda: as chaves `by_source_challenger` (bucket Google na régua Challenger)
estão DECLARADAS no payload_schema — senão o audit_payload_schema falha alto e o
daily-check/digest inteiro retorna 500 (foi o que aconteceu no 1º deploy do PR #48,
pego só no render live porque os gates B/C não montam o payload completo).

Rodável sem pytest:  python tests/test_payload_schema_by_source_challenger.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.digest import audit_payload_schema, PayloadSchemaDriftError


def _decil():
    return {f"D{i:02d}": i for i in range(1, 11)}


def _window(by_source_challenger):
    return {
        "by_source_challenger": by_source_challenger,
    }


def _payload(prev_bsc, launch_bsc):
    return {
        "lead_quality_metrics": {
            "decil_distribution_previous_day": _window(prev_bsc),
            "decil_distribution_current_launch": _window(launch_bsc),
        }
    }


def test_by_source_challenger_populado_passa():
    g = {"google": {"distribution": _decil(), "total": 118}}
    # não deve levantar — todas as chaves declaradas
    audit_payload_schema(_payload(g, g))


def test_by_source_challenger_none_passa():
    # régua indisponível → None; a chave leaf aparece mas está declarada
    audit_payload_schema(_payload(None, None))


def test_chave_nao_declarada_ainda_falha():
    # sanity: o audit continua pegando chave realmente nova (não regrediu)
    p = _payload({"google": {"distribution": _decil(), "total": 1}}, None)
    p["lead_quality_metrics"]["decil_distribution_previous_day"]["by_source_challenger"]["google"]["gremio_inventado"] = 1
    try:
        audit_payload_schema(p)
    except PayloadSchemaDriftError:
        return
    raise AssertionError("audit deveria ter falhado com chave não declarada")


if __name__ == "__main__":
    for fn in (test_by_source_challenger_populado_passa,
               test_by_source_challenger_none_passa,
               test_chave_nao_declarada_ainda_falha):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
