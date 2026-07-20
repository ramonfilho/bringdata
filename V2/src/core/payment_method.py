"""core/payment_method.py — forma de pagamento (cartão vs boleto) por gateway.

FONTE ÚNICA da classificação, replicando o mapa oficial que o treino e a
validação já usam (client_config.py:434 "Cartão = Guru + Hotmart | Boleto =
TMB + ASAAS", train_pipeline.py:771 "gateways de boleto: asaas/boletex/tmb").
NÃO é heurística de valor — é o gateway que determina a forma.

Determinístico e closed-set: os gateways do DevClub são conhecidos. Gateway
fora do conjunto → 'desconhecido' (o consumidor sinaliza alto, não mascara).
"""
from __future__ import annotations

from typing import Iterable

# Mapa canônico (DevClub). Multi-cliente: passar os conjuntos do ClientConfig.
CARTAO_GATEWAYS = frozenset({"guru", "hotmart"})
BOLETO_GATEWAYS = frozenset({"asaas", "boletex", "tmb", "hotpay"})

CARTAO = "cartao"
BOLETO = "boleto"
DESCONHECIDO = "desconhecido"


def forma_pagamento(
    gateway,
    *,
    cartao: Iterable[str] = CARTAO_GATEWAYS,
    boleto: Iterable[str] = BOLETO_GATEWAYS,
) -> str:
    """Gateway → 'cartao' | 'boleto' | 'desconhecido'. Normaliza (lower/strip).
    Gateway não cadastrado devolve 'desconhecido' (nunca chuta cartão/boleto)."""
    g = str(gateway or "").strip().lower()
    if g in cartao:
        return CARTAO
    if g in boleto:
        return BOLETO
    return DESCONHECIDO
