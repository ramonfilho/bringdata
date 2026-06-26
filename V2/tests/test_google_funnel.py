"""Testes da função pura do funil Google (`daily_check_aggregations.compute_google_funnel`)
+ do renderer Slack (`digest._slack_google_funnel`).

Rodável sem pytest:  python tests/test_google_funnel.py

Valida: junção por campaign_id entre spend e nossas ações mapeadas a PAPEL
(with_value/high_quality); ignora ação de terceiro; CPL agregado = spend ÷
leads; ordenação por spend desc; bordas (sem leads → cpl None); renderer
no-op sem dados e monta bloco com dados.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.daily_check_aggregations import compute_google_funnel

WV = "LeadQualified"             # papel with_value
HQ = "LeadQualifiedHighQuality"  # papel high_quality


def test_junta_spend_e_papeis_por_campanha():
    campaign_rows = [
        {"campaign_id": "1", "campaign_name": "Captação A", "spend": 4730.06, "clicks": 2411},
        {"campaign_id": "2", "campaign_name": "Captação B", "spend": 1690.37, "clicks": 925},
    ]
    conv_rows = [
        {"campaign_id": "1", "conversion_action_name": HQ, "all_conversions": 3.0},
        {"campaign_id": "1", "conversion_action_name": "DEV16 | Lead", "all_conversions": 527.0},  # ignorada
        {"campaign_id": "2", "conversion_action_name": WV, "all_conversions": 12.0},
    ]
    out = compute_google_funnel(
        campaign_rows, conv_rows,
        action_with_value=WV, action_high_quality=HQ, total_google_leads=200,
    )
    # ordenado por spend desc → campanha 1 primeiro
    assert [c["campaign_id"] for c in out["por_campanha"]] == ["1", "2"]
    c1 = out["por_campanha"][0]
    assert c1["conv_high_quality"] == 3.0
    assert c1["conv_with_value"] == 0.0     # ação de terceiro não entra
    c2 = out["por_campanha"][1]
    assert c2["conv_with_value"] == 12.0
    assert out["total_spend"] == round(4730.06 + 1690.37, 2)
    assert out["total_clicks"] == 2411 + 925
    assert out["total_with_value"] == 12.0
    assert out["total_high_quality"] == 3.0


def test_cpl_agregado():
    rows = [{"campaign_id": "1", "campaign_name": "A", "spend": 1000.0, "clicks": 100}]
    out = compute_google_funnel(rows, [], action_with_value=WV, action_high_quality=HQ, total_google_leads=200)
    assert out["cpl_agregado"] == 5.0      # 1000 / 200
    assert out["n_leads"] == 200


def test_sem_leads_cpl_none():
    rows = [{"campaign_id": "1", "campaign_name": "A", "spend": 1000.0, "clicks": 100}]
    out = compute_google_funnel(rows, [], action_with_value=WV, action_high_quality=HQ, total_google_leads=None)
    assert out["cpl_agregado"] is None
    out0 = compute_google_funnel(rows, [], action_with_value=WV, action_high_quality=HQ, total_google_leads=0)
    assert out0["cpl_agregado"] is None    # divisão por zero evitada


def test_estado_zero_realista():
    # cenário de hoje: spend existe, mas 0 conversões das nossas ações
    rows = [{"campaign_id": "1", "campaign_name": "A", "spend": 4730.06, "clicks": 2411}]
    out = compute_google_funnel(rows, [], action_with_value=WV, action_high_quality=HQ, total_google_leads=786)
    assert out["total_with_value"] == 0.0
    assert out["total_high_quality"] == 0.0
    assert out["por_campanha"][0]["conv_with_value"] == 0.0
    assert out["por_campanha"][0]["conv_high_quality"] == 0.0


def test_renderer_noop_sem_funil():
    from src.monitoring.digest import _slack_google_funnel
    B = []
    _slack_google_funnel({}, B)                       # sem chave google_funnel
    _slack_google_funnel({"google_funnel": {}}, B)    # vazio
    assert B == [], B


def test_renderer_monta_bloco_com_dados():
    from src.monitoring.digest import _slack_google_funnel
    funnel = compute_google_funnel(
        [{"campaign_id": "1", "campaign_name": "Captação Cold A", "spend": 4730.0, "clicks": 2411}],
        [{"campaign_id": "1", "conversion_action_name": HQ, "all_conversions": 3.0}],
        action_with_value=WV, action_high_quality=HQ, total_google_leads=200,
    )
    B = []
    _slack_google_funnel({"google_funnel": funnel}, B)
    assert B, "deveria ter gerado blocos"
    txt = " ".join(
        b.get("text", {}).get("text", "")
        if b["type"] == "section"
        else b["elements"][0]["text"]
        for b in B
    )
    assert "Funil Google" in txt
    assert "Captação Cold A" in txt
    assert "LQHQ 3" in txt          # papel HQ + contagem
    assert "gclid" in txt           # nota de rodapé sobre atribuição


def test_schema_declara_paths_do_funil():
    # o digest tem schema ESTRITO (raise em chave nova). Garante que todo path
    # produzido pelo google_funnel está declarado em PAYLOAD_SCHEMA.
    from src.monitoring.payload_schema import PAYLOAD_SCHEMA
    from src.monitoring.digest import _walk_paths
    funnel = compute_google_funnel(
        [{"campaign_id": "1", "campaign_name": "A", "spend": 10.0, "clicks": 5}],
        [{"campaign_id": "1", "conversion_action_name": HQ, "all_conversions": 2.0}],
        action_with_value=WV, action_high_quality=HQ, total_google_leads=100,
    )
    payload = {"operational_routines": {"google_funnel": funnel}}
    produced = set(_walk_paths(payload))
    faltando = [p for p in produced if p not in PAYLOAD_SCHEMA]
    assert not faltando, f"paths não declarados em PAYLOAD_SCHEMA: {faltando}"


tests = [
    test_junta_spend_e_papeis_por_campanha,
    test_cpl_agregado,
    test_sem_leads_cpl_none,
    test_estado_zero_realista,
    test_renderer_noop_sem_funil,
    test_renderer_monta_bloco_com_dados,
    test_schema_declara_paths_do_funil,
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
