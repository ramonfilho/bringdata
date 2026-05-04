"""
[S1] Startup validation: cada (pixel_id, event_name) configurado tem que ser
acessível via Meta Graph API antes de aceitar tráfego.

Motivação: o A/B test rodou 5 dias enviando eventos pra pixel velho enquanto
o gestor otimizava no novo (DT-CAPI-S1). Erro silencioso porque Meta retorna
200 OK pra qualquer custom event mesmo que pixel destino não tenha o evento
cadastrado. Esta checagem falha alto no startup quando:

  - META_ACCESS_TOKEN ausente
  - pixel_id configurado não existe ou token sem acesso (4xx Meta)

Não falha em timeout/5xx (Meta instável não pode quebrar deploy).

Saída:
  - Logs `[STARTUP CHECK] ✅ pixel ... acessível` (passou)
  - Logs `[STARTUP CHECK] ❌ FATAL pixel ... inacessível` (config errada)
  - Logs `[STARTUP CHECK] ⚠️ pixel ... timeout` (Meta instável, soft pass)

O `scripts/smoke_test_revision.py` faz grep por `[STARTUP CHECK] ❌` e
bloqueia progressão de tráfego quando encontra.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

META_GRAPH_URL = "https://graph.facebook.com/v18.0"
TIMEOUT_SECONDS = 5


def _collect_pixel_event_pairs(client_config, ab_test_config) -> Dict[str, set]:
    """
    Retorna {pixel_id: {event_names}} considerando default + variants A/B.

    Default vem de client_config.capi (event_name_with_value + event_name_high_quality).
    Cada variante override pode usar pixel_id_override; se None, herda o default.
    """
    pairs: Dict[str, set] = {}

    default_pixel = (
        client_config.capi.pixel_id
        if client_config and client_config.capi and client_config.capi.pixel_id
        else None
    )
    if default_pixel:
        events = set()
        if client_config.capi.event_name_with_value:
            events.add(client_config.capi.event_name_with_value)
        if client_config.capi.event_name_high_quality:
            events.add(client_config.capi.event_name_high_quality)
        pairs[default_pixel] = events

    if ab_test_config and ab_test_config.enabled:
        for variant in ab_test_config.variants.values():
            pixel = variant.pixel_id_override or default_pixel
            if not pixel:
                continue
            pairs.setdefault(pixel, set())
            if variant.capi_event_name:
                pairs[pixel].add(variant.capi_event_name)
            if variant.capi_event_name_high_quality:
                pairs[pixel].add(variant.capi_event_name_high_quality)

    return pairs


def _validate_pixel_access(pixel_id: str, token: str) -> Tuple[str, Optional[str]]:
    """
    Retorna ('passed'|'failed'|'soft_failed', message).

    'passed': pixel existe e acessível
    'failed': hard error — pixel não existe ou token sem acesso (4xx)
    'soft_failed': Meta instável (timeout/5xx) — não bloqueia deploy
    """
    try:
        r = requests.get(
            f"{META_GRAPH_URL}/{pixel_id}",
            params={'access_token': token, 'fields': 'name'},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return 'soft_failed', f"timeout/network error: {type(e).__name__}: {e}"

    if r.status_code == 200:
        try:
            return 'passed', r.json().get('name', '?')
        except ValueError:
            return 'passed', '?'

    if 400 <= r.status_code < 500:
        try:
            err = r.json().get('error', {}).get('message', f'HTTP {r.status_code}')
        except ValueError:
            err = f'HTTP {r.status_code}'
        return 'failed', err

    return 'soft_failed', f'HTTP {r.status_code}'


def validate_capi_destinations(client_config, ab_test_config, client_id: str = 'devclub') -> bool:
    """
    Valida no startup que cada pixel destino é acessível via Meta API.

    Returns True se config está válida (todos passed ou soft_failed),
    False se algum hard fail (config errada).

    Loga `[STARTUP CHECK] ❌ FATAL` quando hard fail — esse log é gate
    do smoke_test_revision.py.
    """
    token = os.environ.get('META_ACCESS_TOKEN')
    if not token:
        logger.error(f"[STARTUP CHECK] ❌ FATAL [{client_id}] META_ACCESS_TOKEN ausente")
        return False

    pairs = _collect_pixel_event_pairs(client_config, ab_test_config)
    if not pairs:
        logger.warning(f"[STARTUP CHECK] [{client_id}] nenhum pixel configurado — pulando validação")
        return True

    logger.info(f"[STARTUP CHECK] [{client_id}] validando {len(pairs)} pixel(s)...")

    has_hard_fail = False
    for pixel_id, events in pairs.items():
        events_str = ', '.join(sorted(events)) if events else '(sem eventos)'
        result, msg = _validate_pixel_access(pixel_id, token)

        if result == 'passed':
            logger.info(
                f"[STARTUP CHECK] ✅ [{client_id}] pixel {pixel_id} ({msg}) acessível "
                f"— eventos configurados: {events_str}"
            )
        elif result == 'soft_failed':
            logger.warning(
                f"[STARTUP CHECK] ⚠️  [{client_id}] pixel {pixel_id} indisponível ({msg}) "
                f"— continuando (Meta API pode estar instável); eventos: {events_str}"
            )
        else:  # failed
            logger.error(
                f"[STARTUP CHECK] ❌ FATAL [{client_id}] pixel {pixel_id} inacessível: {msg} "
                f"— eventos configurados que NÃO serão entregues: {events_str}"
            )
            has_hard_fail = True

    return not has_hard_fail
