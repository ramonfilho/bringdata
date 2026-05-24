"""Adaptador legado — lê leads da tabela `Lead` antiga no Railway.

A tabela `Lead` parou de receber leads em 2026-05-17, quando o front migrou
a captação pro sistema novo do dono (que hoje alimenta o ledger via
Pub/Sub). Mas o histórico anterior continua lá e é a única fonte com 30+
dias acumulados.

Uso atual: baseline rolling 30d da regra de desvio de score. Quando o
ledger novo (`registros_ml`) acumular 30 dias (≈22/06/2026), a regra pode
passar a usar só o adaptador novo pro baseline também e este adaptador
deixa de ter consumidor — momento de remover.

Decisão histórica registrada em
`projeto_baseline_drift_split_railway_ledger.md`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ..lead_record import LeadRecord
from ..lead_repository import _validate_range, _validate_window

logger = logging.getLogger(__name__)


# Tradução `Lead.capiStatus` → `LeadRecord.status_envio`.
# `blocked` / `skipped` viraram famílias `skipped_*` no vocabulário novo;
# `success` e `error` casam 1:1; `None` (sem capiStatus) é tratado como
# tentativa não registrada — mapeado pra `skipped_allowlist` por convenção
# (lead que existiu na Lead mas nunca chegou ao envio).
_CAPI_STATUS_MAP = {
    'success': 'success',
    'error':   'error',
    'blocked': 'skipped_missing_data',
    'skipped': 'skipped_allowlist',
}


class LegacyAdapter:
    """Implementa `LeadRepository` lendo da tabela `Lead` antiga."""

    _COLUMNS = (
        'id', 'email', '"createdAt"', '"leadScore"', 'decil', 'source',
        '"capiSentAt"', '"capiStatus"',
    )

    def __init__(self, railway_conn):
        """`railway_conn`: conexão `pg8000.native.Connection` aberta pro Railway."""
        self.conn = railway_conn

    # ─ interface pública ──────────────────────────────────────────────────

    def recent_leads(self, window_minutes: int, limit: int = 10_000) -> list[LeadRecord]:
        _validate_window(window_minutes)
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        return self._fetch(
            'WHERE "createdAt" >= :cutoff '
            'ORDER BY "createdAt" DESC LIMIT :lim',
            limit_value=limit, cutoff=cutoff, lim=limit,
        )

    def leads_in_range(self, start: datetime, end: datetime, limit: int = 10_000) -> list[LeadRecord]:
        _validate_range(start, end)
        return self._fetch(
            'WHERE "createdAt" >= :start AND "createdAt" < :end '
            'ORDER BY "createdAt" DESC LIMIT :lim',
            limit_value=limit, start=start, end=end, lim=limit,
        )

    # ─ interno ────────────────────────────────────────────────────────────

    def _fetch(self, where_clause: str, *, limit_value: int, **params) -> list[LeadRecord]:
        sql = (
            f"SELECT {', '.join(self._COLUMNS)} "
            f'FROM "Lead" {where_clause}'
        )
        rows = self.conn.run(sql, **params)
        records = [self._row_to_record(r) for r in rows]
        if len(records) >= limit_value:
            logger.warning(
                "[legacy_adapter] retorno bateu no limite de %d linhas — "
                "resultado possivelmente truncado", limit_value
            )
        return records

    @staticmethod
    def _row_to_record(row: Any) -> LeadRecord:
        (lead_id, email, created_at, lead_score, decil, source,
         capi_sent_at, capi_status) = row

        if capi_status in _CAPI_STATUS_MAP:
            status_envio = _CAPI_STATUS_MAP[capi_status]
        elif capi_sent_at is not None:
            status_envio = 'success'  # fallback otimista
        else:
            status_envio = 'skipped_allowlist'

        decil_int: int | None
        if decil is None:
            decil_int = None
        elif isinstance(decil, int):
            decil_int = decil
        else:
            # Lead.decil às vezes vem como string 'D10', 'D9', etc.
            try:
                decil_int = int(str(decil).lstrip('D'))
            except (ValueError, TypeError):
                decil_int = None

        return LeadRecord(
            event_id=f'legacy-{lead_id}',
            email=email or '',
            criado_em=created_at,
            status_envio=status_envio,
            decil=decil_int,
            score=float(lead_score) if lead_score is not None else None,
            variant=None,  # Lead não tinha coluna de variante
            utm_source=source,
            capi_enviado_em=capi_sent_at,
        )
