"""Teto de CPL (Fase 3): valor por venda pela mistura real de gateways (cartão 2k +
boleto 50%) e teto = conversão × valor ÷ roas_alvo (breakeven). Puro (sem banco).

Rodável:  PYTHONPATH=. python tests/test_teto.py
"""
import pandas as pd

from src.monitoring.teto import value_per_sale_from_sales, teto_cpl, CARTAO_VALUE


def test_value_per_sale_mistura_real():
    # 2 cartão (guru/hotmart) + 3 boleto (asaas/tmb/boletex) → pct_cartao 0.4
    sales = pd.DataFrame({"gateway": ["guru", "hotmart", "asaas", "tmb", "boletex"]})
    r = value_per_sale_from_sales(sales)
    assert r["n_sales"] == 5
    assert r["pct_cartao"] == 0.4
    # 0.4×2000 + 0.6×1000 = 1400
    assert r["value_per_sale"] == 1400.0
    assert r["cartao_value"] == 2000.0 and r["boleto_value"] == 1000.0


def test_gateway_desconhecido_ignorado():
    sales = pd.DataFrame({"gateway": ["guru", "asaas", "pix_misterioso", None]})
    r = value_per_sale_from_sales(sales)
    assert r["n_sales"] == 2                 # só guru + asaas contam
    assert r["value_per_sale"] == 1500.0     # 0.5×2000 + 0.5×1000


def test_sem_vendas_vira_none():
    assert value_per_sale_from_sales(pd.DataFrame({"gateway": []}))["value_per_sale"] is None
    assert value_per_sale_from_sales(None)["value_per_sale"] is None


def test_teto_cpl_breakeven():
    # conversão 0.84% · valor R$1.357 · breakeven (roas 1) → teto ≈ R$11.40
    t = teto_cpl(0.0084, 1357.0, roas_alvo=1.0)
    assert round(t, 2) == 11.40
    # roas alvo 8 → teto 8× menor
    assert round(teto_cpl(0.0084, 1357.0, roas_alvo=8.0), 3) == round(11.3988 / 8, 3)
    # ingrediente ausente → None
    assert teto_cpl(None, 1357.0) is None
    assert teto_cpl(0.0084, None) is None


if __name__ == "__main__":
    for fn in (test_value_per_sale_mistura_real, test_gateway_desconhecido_ignorado,
               test_sem_vendas_vira_none, test_teto_cpl_breakeven):
        fn()
        print(f"ok: {fn.__name__}")
    print("PASS")
