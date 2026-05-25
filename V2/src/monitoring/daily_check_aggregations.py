"""Agregações puras pro daily-check, em cima de `list[LeadRecord]`.

Substitui as queries SQL inline que antes contavam direto na tabela `Lead`
antiga (morta desde 2026-05-17). Funções aqui são puras: recebem record
list, devolvem dicts no formato esperado pelo digest. Sem efeitos colaterais,
sem acesso a banco.

Quem chama: `daily_monitoring_check_railway` em `api/app.py`. Quem alimenta:
o mesmo `_repo.leads_in_range(start, end)` que já é usado pra `scored_rows`.

Decisões de modelagem:
  - `meta_eligible` (denominador de FBP/FBC) = leads que passaram pelo CAPI
    = `status_envio != 'skipped_allowlist'`. Allowlist mata o lead antes do
    Meta — então não conta como "população Meta".
  - `capi_sent` = `status_envio in {'success', 'error'}`. Tentou enviar
    (sucesso ou erro), espelhando a definição da query antiga
    (`capiSentAt IS NOT NULL AND capiStatus NOT IN ('blocked', 'skipped')`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from ..data.lead_record import LeadRecord


_STATUS_TENTOU_CAPI = ('success', 'error')


def compute_stats_window(records: List[LeadRecord]) -> Dict[str, int]:
    """Agregação total/scored/capi_sent/success/error/with_phone numa janela.

    Equivalente à query antiga:
        SELECT COUNT(*) FILTER (...) ... FROM "Lead" WHERE createdAt IN [start, end]

    Args:
        records: leads da janela (já filtrados por start/end pelo repo).

    Returns:
        dict com chaves: total, scored, capi_sent, capi_success, capi_error, with_phone.
    """
    total = len(records)
    scored = sum(1 for r in records if r.score is not None)
    capi_sent = sum(1 for r in records if r.status_envio in _STATUS_TENTOU_CAPI)
    capi_success = sum(1 for r in records if r.status_envio == 'success')
    capi_error = sum(1 for r in records if r.status_envio == 'error')
    with_phone = sum(1 for r in records if r.phone)
    return {
        'total':         total,
        'scored':        scored,
        'capi_sent':     capi_sent,
        'capi_success':  capi_success,
        'capi_error':    capi_error,
        'with_phone':    with_phone,
    }


def compute_fbp_fbc_meta_population(records: List[LeadRecord]) -> Dict[str, int]:
    """Contagem de FBP/FBC sobre a população Meta-elegível (denominador justo).

    Equivalente à query antiga que selecionava de `leads_capi`:
        SELECT COUNT(*) FILTER (WHERE fbp IS NOT NULL) AS with_fbp, ... FROM leads_capi

    No ledger novo, "leads_capi" vira "leads que passaram pelo CAPI" =
    `status_envio != 'skipped_allowlist'`.

    Returns:
        dict com chaves: with_fbp, with_fbc, total_meta_leads.
    """
    meta_eligible = [r for r in records if r.status_envio != 'skipped_allowlist']
    with_fbp = sum(1 for r in meta_eligible if r.fbp)
    with_fbc = sum(1 for r in meta_eligible if r.fbc)
    return {
        'with_fbp':         with_fbp,
        'with_fbc':         with_fbc,
        'total_meta_leads': len(meta_eligible),
    }


def _fb_pct(num: int, den: int) -> float:
    return round(num / den * 100, 1) if den else 0.0


def compute_fbp_fbc_rolling(
    records_7d: List[LeadRecord],
    *,
    anchor: datetime,
) -> Dict[str, Dict[str, float]]:
    """FBP/FBC % em janelas rolling 1d/3d/7d, ancoradas em `anchor`.

    Equivalente à query antiga que filtrava `leads_capi` por created_at >=
    anchor - Nd. Cada janela tem `n` (total Meta-elegível), `fbp_pct` e
    `fbc_pct`.

    Args:
        records_7d: leads dos últimos 7d ancorados em `anchor` (já filtrados
                    por start/end pelo repo).
        anchor: timestamp final da janela (geralmente `window_end` do report).

    Returns:
        dict com chaves '1d', '3d', '7d', cada uma com sub-dict
        {n, fbp_pct, fbc_pct}.
    """
    from datetime import timedelta
    # `r.criado_em` vem do pg8000 como datetime offset-naive (UTC implícito);
    # `anchor` pode ser aware. Normaliza removendo tz da anchor pra que a
    # comparação `>=` funcione sem `offset-naive vs offset-aware`.
    anchor_naive = anchor.replace(tzinfo=None) if anchor.tzinfo else anchor
    d1 = anchor_naive - timedelta(days=1)
    d3 = anchor_naive - timedelta(days=3)
    d7 = anchor_naive - timedelta(days=7)
    # Considera "Meta-eligible" = passou pelo CAPI (não skipped_allowlist).
    meta_7d = [r for r in records_7d if r.status_envio != 'skipped_allowlist']

    def _bucket(lim: datetime) -> Dict[str, float]:
        bucket = [
            r for r in meta_7d
            if r.criado_em and r.criado_em.replace(tzinfo=None) >= lim
        ]
        n = len(bucket)
        return {
            'n':       n,
            'fbp_pct': _fb_pct(sum(1 for r in bucket if r.fbp), n),
            'fbc_pct': _fb_pct(sum(1 for r in bucket if r.fbc), n),
        }

    return {'1d': _bucket(d1), '3d': _bucket(d3), '7d': _bucket(d7)}
