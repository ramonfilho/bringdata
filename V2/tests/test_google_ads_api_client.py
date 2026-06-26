"""Testes do cliente de leitura Google Ads (`src/validation/google_ads_api_client`).

Rodável sem pytest:  python tests/test_google_ads_api_client.py

Injeta um `ga_service` fake (sem rede) e valida:
  - parsing/anti-corrupção: cost_micros → spend BRL, status.name, agregação
    por campanha quando a API devolve 1 linha por (campanha, dia);
  - filtro por nome de ação em get_campaign_conversions_by_action.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.validation.google_ads_api_client import GoogleAdsReportingClient


def _row_campaign(cid, name, status, cost_micros, clicks, conv, all_conv):
    return SimpleNamespace(
        campaign=SimpleNamespace(id=cid, name=name, status=SimpleNamespace(name=status)),
        metrics=SimpleNamespace(
            cost_micros=cost_micros, clicks=clicks,
            conversions=conv, all_conversions=all_conv,
        ),
    )


def _row_action(cid, name, action_name, conv, all_conv):
    return SimpleNamespace(
        campaign=SimpleNamespace(id=cid, name=name),
        segments=SimpleNamespace(conversion_action_name=action_name),
        metrics=SimpleNamespace(conversions=conv, all_conversions=all_conv),
    )


class _FakeGA:
    """Fake do GoogleAdsService: devolve linhas pré-fabricadas, ignora a query."""
    def __init__(self, rows):
        self._rows = rows

    def search_stream(self, customer_id=None, query=None):
        # um único batch com todas as linhas
        return [SimpleNamespace(results=self._rows)]


def test_campaign_metrics_micros_para_brl_e_status():
    rows = [_row_campaign(1, "Camp A", "ENABLED", 4_730_060_000, 2411, 527.5, 922.5)]
    c = GoogleAdsReportingClient("6266441811", ga_service=_FakeGA(rows))
    out = c.get_campaign_metrics("2026-06-20", "2026-06-26")
    assert len(out) == 1, out
    r = out[0]
    assert r["campaign_id"] == "1"
    assert r["spend"] == 4730.06, r["spend"]          # micros → BRL
    assert r["status"] == "ENABLED"
    assert r["clicks"] == 2411
    assert r["all_conversions"] == 922.5


def test_campaign_metrics_agrega_dias_da_mesma_campanha():
    # API devolve 1 linha por (campanha, dia) → cliente soma na campanha
    rows = [
        _row_campaign(7, "Camp B", "ENABLED", 1_000_000, 10, 1.0, 2.0),
        _row_campaign(7, "Camp B", "ENABLED", 2_000_000, 20, 3.0, 4.0),
    ]
    c = GoogleAdsReportingClient("x", ga_service=_FakeGA(rows))
    out = c.get_campaign_metrics("2026-06-20", "2026-06-26")
    assert len(out) == 1, out
    r = out[0]
    assert r["spend"] == 3.0
    assert r["clicks"] == 30
    assert r["conversions"] == 4.0
    assert r["all_conversions"] == 6.0


def test_conversions_by_action_filtra_nomes():
    rows = [
        _row_action(1, "Camp A", "LeadQualifiedHighQuality", 2.0, 2.0),
        _row_action(1, "Camp A", "DEV16 | Lead", 50.0, 50.0),
        _row_action(2, "Camp B", "LeadQualified", 5.0, 5.0),
    ]
    c = GoogleAdsReportingClient("x", ga_service=_FakeGA(rows))
    out = c.get_campaign_conversions_by_action(
        "2026-06-20", "2026-06-26",
        action_names=("LeadQualified", "LeadQualifiedHighQuality"),
    )
    names = sorted(r["conversion_action_name"] for r in out)
    assert names == ["LeadQualified", "LeadQualifiedHighQuality"], names
    assert all(r["conversion_action_name"] != "DEV16 | Lead" for r in out)


def test_conversions_by_action_sem_filtro_traz_tudo():
    rows = [
        _row_action(1, "Camp A", "LeadQualifiedHighQuality", 2.0, 2.0),
        _row_action(1, "Camp A", "DEV16 | Lead", 50.0, 50.0),
    ]
    c = GoogleAdsReportingClient("x", ga_service=_FakeGA(rows))
    out = c.get_campaign_conversions_by_action("2026-06-20", "2026-06-26")
    assert len(out) == 2, out


tests = [
    test_campaign_metrics_micros_para_brl_e_status,
    test_campaign_metrics_agrega_dias_da_mesma_campanha,
    test_conversions_by_action_filtra_nomes,
    test_conversions_by_action_sem_filtro_traz_tudo,
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
