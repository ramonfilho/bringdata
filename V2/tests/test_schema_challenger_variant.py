"""Guarda de schema para a chave `challenger_variant` do painel de decis (desvio jul_24).

O fix da régua própria (88cb1d5) injeta `challenger_variant` em
lead_quality_metrics.decil_distribution_{previous_day,current_launch}. Como o
audit_payload_schema casa chave EXATA e o `_walk_paths` emite a leaf mesmo com
valor None, a chave PRECISA estar declarada nas duas janelas — senão o cron do
digest cai com 500 (PayloadSchemaDriftError). Os testes de render NÃO pegam isso
(chamam _slack_decis_window direto, sem passar pelo audit). Este pega.

Rodável:  PYTHONPATH=. python tests/test_schema_challenger_variant.py
"""
from src.monitoring.digest import audit_payload_schema, PayloadSchemaDriftError


def _decil(v=0):
    return {f'D{i:02d}': v for i in range(1, 11)}


def _cv_dict():
    """Forma que _challenger_variant_payload devolve quando o braço está configurado."""
    return {
        'run_id': 'b085b636',
        'total': 322,
        'distribution': _decil(32),
        'baseline': {'pct': {f'D{i:02d}': 7.0 for i in range(1, 11)},
                     'n_leads': 49407, 'label': 'Top5 régua jul_24'},
    }


def _payload(cv_prev, cv_cur):
    return {'lead_quality_metrics': {
        'decil_distribution_previous_day':   {'challenger_variant': cv_prev},
        'decil_distribution_current_launch': {'challenger_variant': cv_cur},
    }}


def test_challenger_variant_dict_passa_o_audit():
    # dict cheio nas duas janelas → todas as leafs declaradas → sem drift
    audit_payload_schema(_payload(_cv_dict(), _cv_dict()))


def test_challenger_variant_none_passa_o_audit():
    # None (braço não configurado) → só a leaf `challenger_variant` aparece → declarada
    audit_payload_schema(_payload(None, None))


def _audience_alert_payload(rrp):
    """Payload com um alerta de drift de característica cujo top_list carrega
    `rolling_reference_pct` (a coluna da referência rolante da Fase 1a). Em frozen
    sai None; em rolling sai o pct do comprador 90d. Nas 2 formas a chave existe."""
    return {'alerts': [{'type': 'category_drift', 'details': {'top_list': [{
        'feature_column': 'O que você faz atualmente?', 'category': 'Autônomo',
        'reference_pct': 12.3, 'rolling_reference_pct': rrp, 'day_pct': 10.0,
    }]}}]}


def test_rolling_reference_pct_none_passa_o_audit():
    # frozen: rolling_map vazio → rolling_reference_pct None em cada item
    audit_payload_schema(_audience_alert_payload(None))


def test_rolling_reference_pct_valor_passa_o_audit():
    # rolling: item ganha o pct do comprador 90d
    audit_payload_schema(_audience_alert_payload(41.2))


def test_guarda_esta_viva():
    # controle negativo: uma chave irmã NÃO declarada tem que derrubar o audit,
    # provando que a passagem acima não é por o guard estar inerte.
    bad = _payload(None, None)
    bad['lead_quality_metrics']['decil_distribution_current_launch']['chave_inventada'] = 1
    try:
        audit_payload_schema(bad)
    except PayloadSchemaDriftError:
        return
    raise AssertionError("audit deveria ter falhado na chave inventada")


if __name__ == "__main__":
    for fn in (test_challenger_variant_dict_passa_o_audit,
               test_challenger_variant_none_passa_o_audit,
               test_rolling_reference_pct_none_passa_o_audit,
               test_rolling_reference_pct_valor_passa_o_audit,
               test_guarda_esta_viva):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
