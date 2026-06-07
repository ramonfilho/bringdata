"""Formato interno do custo por adset — contrato estável entre adaptadores
e consumidores da fórmula ROAS.

Adicionar campo é livre (consumidores antigos ignoram). Renomear ou remover
é decisão consciente que migra todos os consumidores no mesmo movimento.

Mesma filosofia de `src/data/lead_record.py`: nomes em português pra não
vazar vocabulário físico das tabelas Railway pra dentro da lógica de
negócio. As constantes de `cpl_source` documentam de onde o número veio
quando o lookup tem que cair em fallback.
"""
from dataclasses import dataclass
from datetime import date, datetime


# Valores válidos de `cpl_source` registrado no `registros_ml` por lead.
# Mede cobertura da atribuição em produção e ordena a cascata de fallback.
#
# Cascata (do melhor pro pior):
#   adset    — achou linha em `cpl_adset` pro adset que trouxe o lead
#   campaign — adset novo (sem 30d de histórico), caiu pra média da campanha
#   global   — campanha também é nova, caiu pra média do cliente
#   missing  — lead não tem `campaign_id` resolvível no UTM → fórmula ROAS
#              não roda; lead cai pra ordenação só por propensão.
CPL_SOURCE_ADSET = 'adset'
CPL_SOURCE_CAMPAIGN = 'campaign'
CPL_SOURCE_GLOBAL = 'global'
CPL_SOURCE_MISSING = 'missing'

CPL_SOURCES_VALIDOS = frozenset({
    CPL_SOURCE_ADSET,
    CPL_SOURCE_CAMPAIGN,
    CPL_SOURCE_GLOBAL,
    CPL_SOURCE_MISSING,
})


@dataclass(frozen=True)
class CplRecord:
    """Custo médio do adset nos últimos 30 dias. Imutável.

    Uma linha em `cpl_adset` por (client_id, adset_id). Refrescado 1×/dia
    pelo job batch que consulta a Meta Insights API e agrega spend ÷ leads
    na janela móvel.
    """
    client_id: str
    adset_id: str
    cpl_30d: float                  # R$ gastos ÷ leads trazidos
    n_leads_30d: int
    spend_30d: float
    campaign_id: str                # referência p/ fallback "média da campanha"
    window_start: date
    window_end: date
    updated_at: datetime


@dataclass(frozen=True)
class AdMapping:
    """Tradutor `(campaign_id, ad_name) → adset_id`. Imutável.

    Uma linha em `ad_to_adset_map` por (client_id, campaign_id, ad_name).
    Chave composta resolve a ambiguidade de nome de anúncio reaproveitado
    em campanhas distintas — caso comum quando o gestor de tráfego copia
    criativo entre testes.

    Necessário porque o UTM que a Meta grava no lead carrega só
    `utm_campaign` (com `campaign_id` no sufixo) e `utm_content` (com o
    `ad_name`); o `adset_id` — granularidade econômica do Meta — só sai
    dessa tradução.
    """
    client_id: str
    campaign_id: str
    ad_name: str
    adset_id: str
    updated_at: datetime
