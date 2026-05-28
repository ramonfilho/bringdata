"""Classifica Meta campaign_ids por optimization_goal em 3 buckets excludentes.

Helper compartilhado entre:
  - `src/monitoring/data_quality.py` — Drift por A/B (3 colunas excludentes)
  - `api/app.py` — Distribuição de decis (split por campanha alongside fonte)

Cache em nível de módulo: garante 1 única classificação por campaign_id por
TTL, mesmo entre requests do mesmo worker. Evita pressão Meta API quando
múltiplos call sites pedem a mesma classificação.

Buckets (precedência em campanhas mistas: Challenger > Champion > Lead):
  - Challenger → adsets otimizam pra HQLB ou HQLB_LQ
  - Champion   → adsets otimizam pra LeadQualified ou LeadQualifiedHighQuality
  - Lead       → resto (Lead padrão Meta, sem evento ML)
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# {campaign_id: (timestamp, bucket)}; bucket é 'Lead' | 'Champion' | 'Challenger'.
_BUCKET_CACHE: dict[str, tuple[float, str]] = {}
_BUCKET_CACHE_TTL_SECONDS = 1800  # 30 min

_CID_RE = re.compile(r"(\d{15,18})\s*$")
_CHAMPION_GOALS = frozenset({"LeadQualified", "LeadQualifiedHighQuality"})
_CHALLENGER_GOALS = frozenset({"HQLB", "HQLB_LQ"})


def extract_campaign_id(utm_campaign) -> Optional[str]:
    """Extrai o trailing 15-18-digit ID do utm_campaign. None se não casar.

    Exemplo: 'DEVLF | ... | 2025-04-30|120243354440640390' → '120243354440640390'.
    """
    if utm_campaign is None:
        return None
    try:
        # pandas NaN
        import pandas as _pd  # type: ignore

        if _pd.isna(utm_campaign):
            return None
    except Exception:
        pass
    m = _CID_RE.search(str(utm_campaign).strip())
    return m.group(1) if m else None


def classify_campaign_buckets(utm_campaigns: Iterable) -> dict[str, str]:
    """Pra cada campaign_id único em `utm_campaigns`, devolve seu bucket.

    Args:
        utm_campaigns: iterable de strings utm_campaign (pode conter None/NaN).
            Cada string vai passar por `extract_campaign_id` pra resolver o cid.

    Returns:
        Dict {campaign_id: 'Lead'|'Champion'|'Challenger'}. Cids não consultáveis
        (Meta API error, sem token) ficam fora do dict — o caller trata como
        'Lead' por default (catch-all: "se não tem evento ML detectado, cai
        em Lead").

    Cache TTL 30min: chamadas subsequentes pro mesmo cid no mesmo worker são
    free. Reduz drasticamente pressão Meta API.

    Tolerante a falhas:
      - META_ACCESS_TOKEN ausente → dict só com cache acumulado (parcial)
      - Meta API timeout/error por cid → log WARNING, cid omitido
    """
    cids: set[str] = set()
    for s in utm_campaigns:
        cid = extract_campaign_id(s)
        if cid:
            cids.add(cid)
    if not cids:
        return {}

    now_ts = time.time()
    result: dict[str, str] = {}
    to_fetch: set[str] = set()
    for cid in cids:
        entry = _BUCKET_CACHE.get(cid)
        if entry and (now_ts - entry[0]) < _BUCKET_CACHE_TTL_SECONDS:
            result[cid] = entry[1]
        else:
            to_fetch.add(cid)

    if not to_fetch:
        logger.info(
            "[campaign_classifier] cache hit total: %s de %d campanhas",
            dict(Counter(result.values())), len(cids),
        )
        return result

    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        logger.warning(
            "[campaign_classifier] META_ACCESS_TOKEN ausente — retornando só "
            "cache parcial (%d/%d cids), restantes viram 'Lead' no caller",
            len(result), len(cids),
        )
        return result

    try:
        from api.meta_integration import MetaAdsIntegration

        meta = MetaAdsIntegration(access_token=token)
    except Exception as e:
        logger.warning("[campaign_classifier] MetaAdsIntegration falhou: %s", e)
        return result

    # Meta Graph Batch API — empacota até 50 requests num único HTTP call.
    # Para 15 cids/dia tipo do projeto, vira 1 request em vez de 15. Reduz
    # drasticamente pressão de rate limit (origem dos 400 Client Error de
    # 2026-05-28 10:10 BRT) e bate Meta em paralelo no lado do servidor.
    # Docs: https://developers.facebook.com/docs/graph-api/making-multiple-requests
    import json as _json
    import requests

    BATCH_LIMIT = 50  # hard limit Meta Graph API
    adsets_by_cid: dict[str, list] = {}
    n_errors = 0
    to_fetch_list = sorted(to_fetch)
    for batch_start in range(0, len(to_fetch_list), BATCH_LIMIT):
        chunk = to_fetch_list[batch_start:batch_start + BATCH_LIMIT]
        batch = [
            {
                "method": "GET",
                "relative_url": (
                    f"{cid}/adsets?fields=optimization_goal,promoted_object&limit=100"
                ),
            }
            for cid in chunk
        ]
        try:
            r = requests.post(
                "https://graph.facebook.com/",
                data={"access_token": token, "batch": _json.dumps(batch)},
                timeout=30,
            )
            r.raise_for_status()
            responses = r.json()
        except Exception as e:
            n_errors += len(chunk)
            logger.warning(
                "[campaign_classifier] batch falhou (%d cids): %s", len(chunk), e
            )
            continue
        for cid, resp in zip(chunk, responses):
            if not resp:
                n_errors += 1
                continue
            try:
                code = int(resp.get("code") or 0)
            except (TypeError, ValueError):
                code = 0
            if code != 200:
                n_errors += 1
                logger.warning(
                    "[campaign_classifier] campaign %s falhou (code=%s): %s",
                    cid, code, (resp.get("body") or "")[:200],
                )
                continue
            try:
                body = _json.loads(resp["body"])
            except Exception as e:
                n_errors += 1
                logger.warning(
                    "[campaign_classifier] campaign %s parse falhou: %s", cid, e
                )
                continue
            adsets_by_cid[cid] = body.get("data", []) or []

    # Classifica a partir dos adsets recebidos
    for cid in to_fetch:
        adsets = adsets_by_cid.get(cid)
        if adsets is None:
            # request falhou — não cacheia, próxima chamada tenta de novo
            continue
        if not adsets:
            _BUCKET_CACHE[cid] = (now_ts, "Lead")
            result[cid] = "Lead"
            continue
        has_challenger = has_champion = False
        for a in adsets:
            promoted = a.get("promoted_object") or {}
            goal = promoted.get("custom_event_str") or a.get("optimization_goal")
            if goal in _CHALLENGER_GOALS:
                has_challenger = True
            elif goal in _CHAMPION_GOALS:
                has_champion = True
        if has_challenger:
            bucket = "Challenger"
        elif has_champion:
            bucket = "Champion"
        else:
            bucket = "Lead"
        _BUCKET_CACHE[cid] = (now_ts, bucket)
        result[cid] = bucket

    logger.info(
        "[campaign_classifier] buckets: %s (fetched=%d via batch, cache_hit=%d, errors=%d)",
        dict(Counter(result.values())),
        len(to_fetch),
        len(cids) - len(to_fetch),
        n_errors,
    )
    return result
