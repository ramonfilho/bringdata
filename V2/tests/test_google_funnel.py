"""Testes da função pura do funil Google (`daily_check_aggregations.compute_google_funnel`).

Rodável sem pytest:  python tests/test_google_funnel.py

Valida: junção por campaign_id entre spend e nossas ações; filtro das ações
(ignora lead form do gestor); CPL agregado = spend ÷ leads; ordenação por
spend desc; bordas (sem leads → cpl None).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.daily_check_aggregations import compute_google_funnel

OUR = ("LeadQualified", "LeadQualifiedHighQuality")


def test_junta_spend_e_nossas_acoes_por_campanha():
    campaign_rows = [
        {"campaign_id": "1", "campaign_name": "Captação A", "spend": 4730.06, "clicks": 2411},
        {"campaign_id": "2", "campaign_name": "Captação B", "spend": 1690.37, "clicks": 925},
    ]
    conv_rows = [
        {"campaign_id": "1", "conversion_action_name": "LeadQualifiedHighQuality", "all_conversions": 3.0},
        {"campaign_id": "1", "conversion_action_name": "DEV16 | Lead", "all_conversions": 527.0},  # ignorada
        {"campaign_id": "2", "conversion_action_name": "LeadQualified", "all_conversions": 12.0},
    ]
    out = compute_google_funnel(campaign_rows, conv_rows, our_action_names=OUR, total_google_leads=200)

    # ordenado por spend desc → campanha 1 primeiro
    assert [c["campaign_id"] for c in out["por_campanha"]] == ["1", "2"]
    c1 = out["por_campanha"][0]
    assert c1["conv_por_acao"] == {"LeadQualifiedHighQuality": 3.0}, c1["conv_por_acao"]
    # lead form do gestor não entra
    assert "DEV16 | Lead" not in c1["conv_por_acao"]
    assert out["total_spend"] == round(4730.06 + 1690.37, 2)
    assert out["total_clicks"] == 2411 + 925
    assert out["total_por_acao"] == {"LeadQualified": 12.0, "LeadQualifiedHighQuality": 3.0}


def test_cpl_agregado():
    rows = [{"campaign_id": "1", "campaign_name": "A", "spend": 1000.0, "clicks": 100}]
    out = compute_google_funnel(rows, [], our_action_names=OUR, total_google_leads=200)
    assert out["cpl_agregado"] == 5.0      # 1000 / 200
    assert out["n_leads"] == 200


def test_sem_leads_cpl_none():
    rows = [{"campaign_id": "1", "campaign_name": "A", "spend": 1000.0, "clicks": 100}]
    out = compute_google_funnel(rows, [], our_action_names=OUR, total_google_leads=None)
    assert out["cpl_agregado"] is None
    out0 = compute_google_funnel(rows, [], our_action_names=OUR, total_google_leads=0)
    assert out0["cpl_agregado"] is None    # divisão por zero evitada


def test_estado_zero_realista():
    # cenário de hoje: spend existe, mas 0 conversões das nossas ações
    rows = [{"campaign_id": "1", "campaign_name": "A", "spend": 4730.06, "clicks": 2411}]
    out = compute_google_funnel(rows, [], our_action_names=OUR, total_google_leads=786)
    assert out["total_por_acao"] == {"LeadQualified": 0.0, "LeadQualifiedHighQuality": 0.0}
    assert out["por_campanha"][0]["conv_por_acao"] == {}


tests = [
    test_junta_spend_e_nossas_acoes_por_campanha,
    test_cpl_agregado,
    test_sem_leads_cpl_none,
    test_estado_zero_realista,
]


if __name__ == "__main__":
    fails = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception as e:
            fails += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - fails}/{len(tests)} passaram")
    sys.exit(1 if fails else 0)
