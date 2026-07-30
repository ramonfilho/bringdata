"""Teto de CPL — derivado da referência rolante (NÃO é fonte nova).

    teto_cpl(grupo) = conversão(grupo) × valor_por_venda ÷ roas_alvo

- roas_alvo = 1.0 → BREAKEVEN: o CPL máximo pra não dar prejuízo (a pedido). Acima
  do teto, o grupo queima dinheiro; abaixo, sobra.
- valor_por_venda: fórmula da planilha devclub geral — cartão a R$2.000, boleto a
  50% (R$1.000) — ponderado pela mistura REAL cartão/boleto da janela da referência.
  A mistura vem das vendas de fato (não do pct histórico do config, que estava
  desatualizado: ~46,8% vs ~35,7% real recente → teto ~10% menor).

Reuso (/sw-architect): `forma_pagamento` (core.payment_method) é a fonte única de
gateway→forma; não reclassifico gateway aqui.
"""
from __future__ import annotations

import logging

from src.core.payment_method import forma_pagamento, CARTAO, BOLETO

logger = logging.getLogger(__name__)

CARTAO_VALUE = 2000.0   # "cartão a 2k" (planilha devclub geral; ≠ ticket_contracted 2200)
BOLETO_HAIRCUT = 0.5    # boleto conta a 50% (risco de calote), convenção do debriefing


def value_per_sale_from_sales(sales_df, *, cartao_value: float = CARTAO_VALUE,
                              boleto_haircut: float = BOLETO_HAIRCUT) -> dict:
    """Valor médio por venda da janela, ponderado pela mistura REAL de gateways.

    Devolve dict {value_per_sale, pct_cartao, n_sales, cartao_value, boleto_value}.
    value_per_sale=None quando não há vendas classificáveis (o teto degrada pra None).
    """
    boleto_value = cartao_value * boleto_haircut
    empty = {"value_per_sale": None, "pct_cartao": None, "n_sales": 0,
             "cartao_value": cartao_value, "boleto_value": boleto_value}
    if sales_df is None or len(sales_df) == 0:
        return empty
    cols = list(getattr(sales_df, "columns", []))
    # read_analytics_sales renomeia gateway→origem; aceita os dois nomes.
    gw_col = "origem" if "origem" in cols else ("gateway" if "gateway" in cols else None)
    if gw_col is None:
        return empty

    formas = sales_df[gw_col].apply(forma_pagamento)
    known = formas[formas.isin([CARTAO, BOLETO])]
    n_known = int(len(known))
    if n_known == 0:
        return empty
    n_cartao = int((known == CARTAO).sum())
    n_boleto = n_known - n_cartao
    vps = (n_cartao * cartao_value + n_boleto * boleto_value) / n_known
    pct_cartao = n_cartao / n_known
    logger.info("[teto] valor_por_venda R$%.0f (cartão %.1f%% × R$%.0f + boleto %.1f%% × R$%.0f) "
                "sobre %d vendas", vps, pct_cartao * 100, cartao_value,
                (1 - pct_cartao) * 100, boleto_value, n_known)
    return {"value_per_sale": round(vps, 2), "pct_cartao": round(pct_cartao, 4),
            "n_sales": n_known, "cartao_value": cartao_value, "boleto_value": boleto_value}


def teto_cpl(conversion_rate, value_per_sale, roas_alvo: float = 1.0):
    """CPL máximo pra bater `roas_alvo` dado conversão e valor por venda.
    None se faltar ingrediente. roas_alvo=1.0 = breakeven."""
    if conversion_rate is None or value_per_sale is None or not roas_alvo or roas_alvo <= 0:
        return None
    return conversion_rate * value_per_sale / roas_alvo
