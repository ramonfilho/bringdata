"""Testes do classificador de variante do Google (`monitoring.google_variant`)
+ integração com a função pura compartilhada (`compute_variant_cpl_conv`) +
render do bloco "Por variante (Google)" idêntico ao Meta + schema estrito.

Rodável sem pytest:  python tests/test_google_variant.py

Valida:
  - parse do campaign_id do utm_term ValueTrack (e bordas);
  - estado de HOJE: mapa goal→variante vazio → TODO lead/spend cai em 'Lead'
    (Champion/Challenger zerados), sem inventar A/B que o Google ainda não roda;
  - estado FUTURO: mapa preenchido → leads/spend se dividem em Champion/Challenger;
  - reuso de compute_variant_cpl_conv com dados Google (spend por campaign_id +
    leads por campaign_id do utm_term, lpv=clicks, tax=0);
  - render do bloco no MESMO formato do Meta;
  - todos os paths novos do payload declarados no schema estrito.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.google_variant import (
    campaign_id_from_utm_term,
    build_campaign_variant_map,
    make_classifier,
    DEFAULT_BUCKET,
)
from src.monitoring.daily_check_aggregations import compute_variant_cpl_conv
from src.monitoring.digest import _ab_bucket_label as _ab_label


# ── parse do elo lead→campanha ────────────────────────────────────────────────

def test_campaign_id_from_utm_term():
    assert campaign_id_from_utm_term("23731741326--203657325788--804381914388") == "23731741326"
    assert campaign_id_from_utm_term("23731741326") == "23731741326"           # só campaign_id
    assert campaign_id_from_utm_term("  111--222  ") == "111"                   # trim
    assert campaign_id_from_utm_term(None) is None
    assert campaign_id_from_utm_term("") is None
    assert campaign_id_from_utm_term("   ") is None


# ── estado de hoje: mapa vazio → tudo Lead ───────────────────────────────────

def test_mapa_vazio_tudo_lead():
    cvm = build_campaign_variant_map(None, None)
    assert cvm == {}
    cvm2 = build_campaign_variant_map([{"campaign_id": "1", "goal_ids": ["g1"]}], {})
    assert cvm2 == {}
    classify = make_classifier(cvm)
    assert classify("1") == "Lead"
    assert classify("qualquer") == "Lead"
    assert classify(None) == "Lead"


# ── estado futuro: mapa preenchido → Champion/Challenger ─────────────────────

def test_mapa_cheio_popula_buckets():
    goal_rows = [
        {"campaign_id": "1", "goal_ids": ["g_champ"]},
        {"campaign_id": "2", "goal_ids": ["g_chal", "g_outro"]},
        {"campaign_id": "3", "goal_ids": ["g_outro"]},   # não casa → fica Lead (default)
    ]
    vgm = {"g_champ": "Champion", "g_chal": "Challenger"}
    cvm = build_campaign_variant_map(goal_rows, vgm)
    assert cvm == {"1": "Champion", "2": "Challenger"}
    classify = make_classifier(cvm)
    assert classify("1") == "Champion"
    assert classify("2") == "Challenger"
    assert classify("3") == "Lead"      # campanha fora do mapa


# ── integração: compute_variant_cpl_conv com dados Google (hoje = tudo Lead) ──

def _google_spend_rows(cmp_rows):
    # mesma transformação que o app.py faz: campaign_name=campaign_id, lpv=clicks
    return [{"campaign_name": r["campaign_id"], "spend": r["spend"], "lpv": r["clicks"]}
            for r in cmp_rows]


def test_integra_tudo_lead_hoje():
    cmp_rows = [
        {"campaign_id": "1", "spend": 1000.0, "clicks": 500},
        {"campaign_id": "2", "spend": 800.0, "clicks": 400},
    ]
    # 3 leads, todos com campaign_id no utm_term
    lead_cids = ["1", "2", "1"]
    classify = make_classifier(build_campaign_variant_map(None, {}))
    out = compute_variant_cpl_conv(
        meta_rows=_google_spend_rows(cmp_rows),
        client_campaigns=lead_cids,
        classify_fn=classify,
        tax_rate=0.0,
    )
    # tudo em Lead
    assert out["Lead"]["leads"] == 3
    assert out["Lead"]["spend"] == 1800.0
    assert out["Lead"]["cpl"] == round(1800.0 / 3, 2)
    assert out["Lead"]["conv_lp"] == round(3 / 900 * 100, 1)   # leads ÷ cliques
    # Champion/Challenger zerados (somem no render)
    assert out["Champion"]["leads"] == 0 and out["Champion"]["cpl"] is None
    assert out["Challenger"]["leads"] == 0 and out["Challenger"]["cpl"] is None


def test_integra_split_futuro():
    cmp_rows = [
        {"campaign_id": "1", "spend": 1000.0, "clicks": 500},   # Champion
        {"campaign_id": "2", "spend": 600.0, "clicks": 300},    # Challenger
        {"campaign_id": "3", "spend": 200.0, "clicks": 100},    # Lead
    ]
    lead_cids = ["1", "1", "2", "3"]    # 2 champ, 1 chal, 1 lead
    vgm = {"gc": "Champion", "gh": "Challenger"}
    goal_rows = [
        {"campaign_id": "1", "goal_ids": ["gc"]},
        {"campaign_id": "2", "goal_ids": ["gh"]},
    ]
    classify = make_classifier(build_campaign_variant_map(goal_rows, vgm))
    out = compute_variant_cpl_conv(
        meta_rows=_google_spend_rows(cmp_rows),
        client_campaigns=lead_cids,
        classify_fn=classify,
        tax_rate=0.0,
    )
    assert out["Champion"]["leads"] == 2 and out["Champion"]["spend"] == 1000.0
    assert out["Challenger"]["leads"] == 1 and out["Challenger"]["spend"] == 600.0
    assert out["Lead"]["leads"] == 1 and out["Lead"]["spend"] == 200.0
    assert out["Champion"]["cpl"] == 500.0   # 1000 / 2


def test_lead_sem_campaign_id_conta_em_lead():
    # lead Google com utm_term que não parseou → campaign_id None → Lead (default)
    classify = make_classifier({})
    cmp_rows = [{"campaign_id": "1", "spend": 100.0, "clicks": 50}]
    out = compute_variant_cpl_conv(
        meta_rows=_google_spend_rows(cmp_rows),
        client_campaigns=["1", None, None],
        classify_fn=classify, tax_rate=0.0,
    )
    assert out["Lead"]["leads"] == 3      # os 3 contam em Lead


# ── render: bloco "Por variante (Google)" no MESMO formato do Meta ───────────

def _min_view(google_funnel):
    return {
        "funnel": {
            "unified_funnel": {"window": {"label": "ontem", "date_brt": "27/06"}, "pipeline": {}},
            "data_quality": {"fbp_fbc_rolling": {}},
        },
        "traffic": {"dia_anterior": {"spend": 0, "clicks": 0}},
        "google_funnel": google_funnel,
    }


def test_render_bloco_por_variante_google():
    from src.monitoring.digest import _slack_unified_funnel
    classify = make_classifier({})
    cmp_rows = [{"campaign_id": "1", "spend": 1814.0, "clicks": 900}]
    pv = compute_variant_cpl_conv(
        meta_rows=_google_spend_rows(cmp_rows),
        client_campaigns=["1"] * 192, classify_fn=classify, tax_rate=0.0,
    )
    gf = {
        "total_spend": 1814.0, "total_clicks": 900, "cpl_agregado": 9.45,
        "n_leads": 192, "por_campanha": [], "total_with_value": 0.0,
        "total_high_quality": 0.0, "por_variante": pv, "por_variante_lf": pv,
    }
    B = []
    _slack_unified_funnel(_min_view(gf), B)
    txt = " ".join(
        b.get("text", {}).get("text", "") if b["type"] == "section" else b["elements"][0]["text"]
        for b in B
    )
    assert "── Google ──" in txt, txt    # seção Google unificada (spend/cliques + variante)
    assert "192" in txt           # leads do bucket Lead
    # Champion/Challenger (0 leads) não devem aparecer como linha de variante Google
    # (some igual ao Meta); só o cabeçalho + a linha Lead.


def test_render_esconde_balde_fantasma():
    # balde com 0 lead ontem E LF cpl=0,00 (campanha antiga desligada, sem spend)
    # NÃO deve aparecer; balde com LF cpl real (>0) aparece.
    from src.monitoring.digest import _slack_unified_funnel
    pv = {
        'Lead': {'leads': 100, 'cpl': 5.0, 'conv_lp': 30.0, 'spend': 500.0, 'lpv': 333},
        'Champion': {'leads': 0, 'cpl': None, 'conv_lp': None, 'spend': 0.0, 'lpv': 0},
        'Challenger': {'leads': 0, 'cpl': None, 'conv_lp': None, 'spend': 0.0, 'lpv': 0},
    }
    pv_lf = {
        'Lead': {'leads': 700, 'cpl': 5.2, 'conv_lp': 31.0, 'spend': 3640.0, 'lpv': 2258},
        'Champion': {'leads': 3, 'cpl': 0.0, 'conv_lp': None, 'spend': 0.0, 'lpv': 0},   # FANTASMA
        'Challenger': {'leads': 0, 'cpl': None, 'conv_lp': None, 'spend': 0.0, 'lpv': 0},
    }
    v = {
        "funnel": {"unified_funnel": {"window": {}, "pipeline": {}}, "data_quality": {"fbp_fbc_rolling": {}}},
        "traffic": {"dia_anterior": {"spend": 1000, "clicks": 500, "por_variante": pv}, "por_variante_lf": pv_lf},
        "google_funnel": {},
    }
    B = []
    _slack_unified_funnel(v, B)
    txt = " ".join(
        b.get("text", {}).get("text", "") if b["type"] == "section" else b["elements"][0]["text"]
        for b in B
    )
    assert "── Meta ──" in txt
    lead_lbl = _ab_label('Lead'); champ_lbl = _ab_label('Champion')
    assert lead_lbl in txt, "Lead (com dado) deve aparecer"
    assert champ_lbl not in txt, "Champion fantasma (0 ontem + LF cpl 0) deve sumir"


# ── schema estrito: todos os paths novos declarados ──────────────────────────

def test_schema_declara_por_variante_google():
    from src.monitoring.payload_schema import PAYLOAD_SCHEMA
    from src.monitoring.digest import _walk_paths
    classify = make_classifier({})
    cmp_rows = [{"campaign_id": "1", "spend": 10.0, "clicks": 5}]
    pv = compute_variant_cpl_conv(
        meta_rows=_google_spend_rows(cmp_rows),
        client_campaigns=["1"], classify_fn=classify, tax_rate=0.0,
    )
    funnel = {
        "por_campanha": [], "total_spend": 10.0, "total_clicks": 5,
        "total_with_value": 0.0, "total_high_quality": 0.0, "n_leads": 1,
        "cpl_agregado": 10.0, "por_variante": pv, "por_variante_lf": pv,
    }
    payload = {"operational_routines": {"google_funnel": funnel}}
    produced = set(_walk_paths(payload))
    faltando = [p for p in produced if p not in PAYLOAD_SCHEMA]
    assert not faltando, f"paths não declarados em PAYLOAD_SCHEMA: {faltando}"


tests = [
    test_campaign_id_from_utm_term,
    test_mapa_vazio_tudo_lead,
    test_mapa_cheio_popula_buckets,
    test_integra_tudo_lead_hoje,
    test_integra_split_futuro,
    test_lead_sem_campaign_id_conta_em_lead,
    test_render_bloco_por_variante_google,
    test_render_esconde_balde_fantasma,
    test_schema_declara_por_variante_google,
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
