"""Regressão do curinga `.*` de variante no PAYLOAD_SCHEMA.

Contexto: os agrupamentos `operational_routines.*_by_variant_24h*` têm folha =
NOME DE VARIANTE do A/B (dado que muda a cada teste). Declará-las por nome literal
derrubava o digest (500) a cada troca de A/B (reincidiu em #48/#61/#108). O curinga
`.*` (resolvido em digest.py::_schema_decision) tolera qualquer folha DIRETA desses
containers, MAS o fail-loud continua de pé pra todo o resto.
"""
from src.monitoring.digest import (
    audit_payload_schema, PayloadSchemaDriftError, _schema_decision,
)
from src.monitoring.payload_schema import FieldDecision

GROUPS = [
    'operational_routines.leads_scored_by_variant_24h',
    'operational_routines.leads_capi_by_variant_24h',
    'operational_routines.spend_by_variant_24h_brl',
    'operational_routines.cpl_by_variant_24h_brl',
]


def _payload(op_extra: dict) -> dict:
    """Payload mínimo: só o bloco operational_routines com o que o teste injeta.

    audit_payload_schema só reclama de path NÃO declarado; ausência de path
    declarado não é erro. Então um payload parcial é suficiente pra exercitar o
    guard sem montar o daily-check inteiro.
    """
    return {'operational_routines': op_extra}


def test_variante_nova_sob_agrupamento_passa():
    # Nome de variante nunca visto antes, em cada um dos 4 agrupamentos.
    for g in GROUPS:
        leaf = g.rsplit('.', 1)[1]
        audit_payload_schema(_payload({leaf: {'challenger_set2099': 42}}))


def test_chave_nova_fora_dos_agrupamentos_derruba():
    import pytest
    with pytest.raises(PayloadSchemaDriftError):
        audit_payload_schema(_payload({'coisa_totalmente_nova_2099': 1}))


def test_nivel_mais_fundo_sob_agrupamento_derruba():
    # Se o VALOR da variante virar dict (mudança de shape), o nível extra tem que
    # cair no fail-loud — o curinga cobre só 1 nível.
    import pytest
    with pytest.raises(PayloadSchemaDriftError):
        audit_payload_schema(_payload({
            'leads_scored_by_variant_24h': {'challenger_x': {'foo': 1}},
        }))


def test_schema_decision_exato_curinga_e_none():
    # exato (container declarado)
    d = _schema_decision('operational_routines.leads_capi_by_variant_24h')
    assert d is not None and d[0] == FieldDecision.RENDERED
    # curinga (folha de variante qualquer)
    d = _schema_decision('operational_routines.leads_capi_by_variant_24h.qualquer_variante')
    assert d is not None and d[0] == FieldDecision.RENDERED
    # não declarado
    assert _schema_decision('operational_routines.coisa_inexistente') is None
    # curinga NÃO vaza pra nível mais fundo
    assert _schema_decision('operational_routines.leads_capi_by_variant_24h.v.extra') is None
