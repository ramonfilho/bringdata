"""Classificador de variante (Lead/Champion/Challenger) pra campanhas Google.

Espelha o PAPEL de `validation.campaign_classifier.classify_variant` (Meta),
mas por design é uma implementação DIFERENTE da mesma interface (padrão
Estratégia): o Meta lê a tag de optimization_goal no NOME da campanha; o Google
classifica pela CONVERSION GOAL que a campanha otimiza (lida da Google Ads API).

Por que diferente: o nome da campanha Google não carrega a tag, e o operador
decidiu que o mais seguro é o goal de conversão. Hoje NENHUMA campanha Google
está plugada nos nossos eventos de Champion/Challenger (o A/B de modelo ainda
não roda no Google) → o mapa `variant_goal_map` da config está vazio → tudo cai
em 'Lead'. Quando o gestor plugar campanhas nos eventos do A/B, a config mapeia
goal→variante e o split popula sozinho, sem tocar este código.

Interface entregue ao consumidor:
  - `campaign_id_from_utm_term`: elo lead→campanha (parse do ValueTrack).
  - `build_campaign_variant_map`: {campaign_id: variante} a partir do goal da
    campanha + o mapa da config.
  - `make_classifier`: devolve um `classify_fn(campaign_id) -> bucket` plugável
    direto em `compute_variant_cpl_conv` (a MESMA função pura que agrega o Meta).

Tudo aqui é PURO (sem I/O). O caller (`api/app.py`) faz os pulls (API + ledger)
e passa pronto — testável sem rede.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any, Callable

# Os 3 baldes do funil. 'Lead' é o default (campanha fora do A/B de modelo).
VARIANT_BUCKETS = ('Lead', 'Champion', 'Challenger')
DEFAULT_BUCKET = 'Lead'


def campaign_id_from_utm_term(utm_term: Optional[str]) -> Optional[str]:
    """Extrai o `campaign_id` do `utm_term` no formato ValueTrack do Google.

    O auto-tagging do Google grava `utm_term = '{campaign_id}--{adgroup_id}--{ad_id}'`.
    O 1º segmento É o campaign_id (verificado: 1285/1285 leads casaram com os IDs
    da API). Anti-corrupção: traduz o formato físico do Google pro nosso
    campaign_id na fronteira; o resto do código nunca vê o ValueTrack cru.

    Returns:
        campaign_id (str) ou None se o term for vazio/sem o formato esperado
        (fail-soft — o caller loga quando um lead Google não casa com a API).
    """
    if not utm_term:
        return None
    head = str(utm_term).strip().split('--', 1)[0].strip()
    return head or None


def build_campaign_variant_map(
    goal_rows: Optional[List[Dict[str, Any]]],
    variant_goal_map: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """`{campaign_id: bucket}` a partir do goal de cada campanha + mapa da config.

    Args:
        goal_rows: list de `{campaign_id, goal_ids: [...]}` (lida da API). Só
            precisa ser consultada quando `variant_goal_map` não está vazio —
            hoje está, então o caller nem bate na API de goals.
        variant_goal_map: `{goal_id: 'Champion'|'Challenger'}` da config do
            cliente (`GoogleAdsConfig.variant_goal_map`).

    Returns:
        `{campaign_id: 'Champion'|'Challenger'}` só pras campanhas cujo goal
        casa o mapa. Mapa vazio/None → `{}` (todo lookup cai no default 'Lead').
        Estado de hoje: `{}`.
    """
    if not variant_goal_map:
        return {}
    out: Dict[str, str] = {}
    for r in (goal_rows or []):
        cid = r.get('campaign_id')
        if cid is None:
            continue
        cid = str(cid)
        for gid in (r.get('goal_ids') or []):
            bucket = variant_goal_map.get(str(gid))
            # Só Champion/Challenger entram no mapa explícito; 'Lead' é o default
            # e não precisa de entrada (mantém o mapa enxuto).
            if bucket in ('Champion', 'Challenger'):
                out[cid] = bucket
                break
    return out


def make_classifier(
    campaign_variant_map: Optional[Dict[str, str]],
) -> Callable[[Optional[str]], str]:
    """Devolve um `classify_fn(campaign_id) -> bucket` plugável em
    `compute_variant_cpl_conv`.

    Default 'Lead' pra qualquer campanha fora do mapa (e pra `campaign_id` None —
    lead Google com `utm_term` que não parseou ainda é um lead Google, conta em
    Lead). Assim a soma dos baldes sempre bate com o total de leads Google.
    """
    cvm = campaign_variant_map or {}

    def _classify(campaign_id: Optional[str]) -> str:
        if campaign_id is None:
            return DEFAULT_BUCKET
        return cvm.get(str(campaign_id), DEFAULT_BUCKET)

    return _classify
