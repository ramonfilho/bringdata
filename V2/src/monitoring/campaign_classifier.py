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

Arquitetura: I/O Meta API mora no adapter `MetaAdsIntegration.batch_get_adsets`.
Aqui só vive a regra de negócio "dado um conjunto de adsets, qual bucket?".
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from typing import Iterable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from api.meta_integration import MetaAdsIntegration

logger = logging.getLogger(__name__)

# {campaign_id: (timestamp, bucket)}; bucket é 'Lead' | 'Champion' | 'Challenger'.
_BUCKET_CACHE: dict[str, tuple[float, str]] = {}
_BUCKET_CACHE_TTL_SECONDS = 1800  # 30 min
_MAX_FETCH_RETRIES = 2  # retries com backoff p/ falha transitória da Meta API (429/timeout)

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


def _bucket_from_adsets(adsets: list) -> str:
    """Aplica precedência Challenger > Champion > Lead nos adsets de uma campanha."""
    has_challenger = has_champion = False
    for a in adsets:
        promoted = a.get("promoted_object") or {}
        goal = promoted.get("custom_event_str") or a.get("optimization_goal")
        if goal in _CHALLENGER_GOALS:
            has_challenger = True
        elif goal in _CHAMPION_GOALS:
            has_champion = True
    if has_challenger:
        return "Challenger"
    if has_champion:
        return "Champion"
    return "Lead"


# Tags textuais que o objetivo de otimização deixa NO NOME da campanha
# (utm_campaign) — espelham _CHAMPION_GOALS/_CHALLENGER_GOALS. O gestor tagueia
# o nome: "DEVLF | ... | 2026-06-04 | LEADQUALIFIED|<id>" (Champion),
# "... | LEADHQLB|<id>" (Challenger), sem tag = Lead/otimização padrão.
# As tags por variante vivem no YAML (campos campaign_tag/role) e chegam aqui via
# bucket_map (ABTestConfig.campaign_bucket_map) — fonte única (Frente 2/DT-19).


def bucket_from_utm(utm_campaign, bucket_map=None) -> str:
    """Bucket A/B (Lead/Champion/Challenger) pela TAG no nome da campanha — SEM Meta API.

    O objetivo de otimização já vem escrito no `utm_campaign` (o gestor tagueia
    o nome). Espelha `_bucket_from_adsets` (que lê o mesmo objetivo via Graph
    API), mas lendo a tag local do ledger → não rate-limita, nunca vem vazio.
    Precedência Challenger > Champion > Lead (igual ao adset-based).

    Esta é a fonte do split Champion/Challenger das tabelas de decis e drift
    por A/B. A Meta API fica reservada só pro funil/insights (spend/CPL), que
    não tem outra fonte.

    `bucket_map` (de ABTestConfig.campaign_bucket_map — fonte única no YAML, campos
    campaign_tag/role por variante) define tag→balde, na ordem de precedência
    (challenger antes de champion). Formato: {'tags': [(TAG_UPPER, bucket), ...],
    'fallback': 'Lead'}. Sem bucket_map, tudo cai em 'Lead' (default seguro) — todos
    os consumidores de produção (data_quality, app.py) injetam o mapa.
    """
    c = (str(utm_campaign) if utm_campaign is not None else "").upper()
    if not bucket_map:
        return "Lead"
    for tag, bucket in bucket_map.get("tags", []):
        if tag in c:
            return bucket
    return bucket_map.get("fallback", "Lead")


def classify_campaign_buckets(
    utm_campaigns: Iterable,
    *,
    meta: Optional["MetaAdsIntegration"] = None,
) -> dict[str, str]:
    """Pra cada campaign_id único em `utm_campaigns`, devolve seu bucket.

    Args:
        utm_campaigns: iterable de strings utm_campaign (pode conter None/NaN).
            Cada string vai passar por `extract_campaign_id` pra resolver o cid.
        meta: adapter `MetaAdsIntegration` injetado. Se None, instancia um
            default a partir de `META_ACCESS_TOKEN` (backwards-compat com
            callers antigos). Composição única no caller (endpoint/scheduler)
            é a forma preferida.

    Returns:
        Dict {campaign_id: 'Lead'|'Champion'|'Challenger'}. Cids não consultáveis
        (Meta API error, sem token) ficam fora do dict — o caller trata como
        'Lead' por default (catch-all: "se não tem evento ML detectado, cai
        em Lead").

    Cache TTL 30min: chamadas subsequentes pro mesmo cid no mesmo worker são
    free. Reduz drasticamente pressão Meta API.

    Tolerante a falhas:
      - meta None + META_ACCESS_TOKEN ausente → dict só com cache acumulado
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

    if meta is None:
        token = os.environ.get("META_ACCESS_TOKEN")
        if not token:
            logger.warning(
                "[campaign_classifier] META_ACCESS_TOKEN ausente e meta não "
                "injetado — retornando só cache parcial (%d/%d cids), restantes "
                "viram 'Lead' no caller",
                len(result), len(cids),
            )
            return result
        try:
            from api.meta_integration import MetaAdsIntegration

            meta = MetaAdsIntegration(access_token=token)
        except Exception as e:
            logger.warning("[campaign_classifier] MetaAdsIntegration falhou: %s", e)
            return result

    adsets_by_cid = meta.batch_get_adsets(sorted(to_fetch))

    # Retry transitório: um 429/timeout faz batch_get_adsets devolver None pro
    # chunk inteiro. Sem retry, as campanhas desse chunk somem do dict e o
    # caller as joga em 'Lead' (`classification.get(cid, 'Lead')`) — foi assim
    # que o Champion zerou e o relatório saiu "vazio" em 2026-06-13. Retry com
    # backoff resolve a falha transitória antes de desistir.
    failed = [cid for cid in to_fetch if adsets_by_cid.get(cid) is None]
    for attempt in range(1, _MAX_FETCH_RETRIES + 1):
        if not failed:
            break
        time.sleep(min(2 ** attempt, 5))  # backoff 2s, 4s
        logger.warning(
            "[campaign_classifier] retry %d/%d para %d cid(s) sem classificação",
            attempt, _MAX_FETCH_RETRIES, len(failed),
        )
        retry_res = meta.batch_get_adsets(sorted(failed))
        for cid, adsets in retry_res.items():
            if adsets is not None:
                adsets_by_cid[cid] = adsets
        failed = [cid for cid in failed if adsets_by_cid.get(cid) is None]

    for cid in to_fetch:
        adsets = adsets_by_cid.get(cid)
        if adsets is None:
            # ainda falhou após retries — não cacheia (tenta de novo na próxima
            # chamada) e fica fora do dict.
            continue
        bucket = _bucket_from_adsets(adsets) if adsets else "Lead"
        _BUCKET_CACHE[cid] = (now_ts, bucket)
        result[cid] = bucket

    n_errors = len(failed)
    if n_errors:
        # Fail-loud: cids sem classificação viram 'Lead' silenciosamente no
        # caller, subestimando Champion/Challenger. Logar ERROR pra o degrade
        # ser visível no monitoramento em vez de passar batido.
        logger.error(
            "[campaign_classifier] %d/%d campanha(s) sem classificação após %d "
            "retries — caller as tratará como 'Lead' (Champion/Challenger podem "
            "sair subestimados). cids=%s",
            n_errors, len(cids), _MAX_FETCH_RETRIES, sorted(failed)[:10],
        )
    logger.info(
        "[campaign_classifier] buckets: %s (fetched=%d via batch, cache_hit=%d, errors=%d)",
        dict(Counter(result.values())),
        len(to_fetch),
        len(cids) - len(to_fetch),
        n_errors,
    )
    return result
