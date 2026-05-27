"""Adaptador que lê leads do ledger novo (tabela `registros_ml` no Railway).

`registros_ml` é populado pelo consumer Pub/Sub desde 2026-05-23. Cada linha é
1 lead processado, identificado pelo `event_id` (UUID v7 do payload). Schema
completo em `scripts/create_registros_ml.py`; documentação operacional em
`docs/PROCESSO_CAPI_LEAD_SURVEYS.md`.

Este adaptador é a tradução entre o schema físico (colunas snake_case) e o
formato interno `LeadRecord` (campos em português, contrato estável).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ..lead_record import LeadRecord
from ..lead_repository import _validate_range, _validate_window

logger = logging.getLogger(__name__)


# Tradução `registros_ml.base_status` → `LeadRecord.status_envio`.
# Hoje 1:1 (vocabulário do ledger novo já casa com o interno). Tabela existe
# pra forçar revisão consciente se a fonte introduzir status novo.
#
# Vocabulário do ciclo de vida Meta CAPI:
#   success              → Meta CAPI aceitou
#   error                → Meta CAPI rejeitou
#   skipped_missing_data → ou survey incompleto (não scoreou) ou Meta-eligível
#                          sem fbp/fbc (scoreou mas não enviou Meta por falta
#                          de tracking)
#   skipped_allowlist    → utm_source não-Meta (Google etc.). Sob
#                          SCORE_ALL_LEADS=true, o lead É scoreado mas NÃO
#                          enviado a Meta. Sob false, nem scoreia.
#
# IMPORTANTE: NÃO usar este enum pra outros destinos (Google CAPI etc.).
# Cada destino futuro tem sua própria coluna de status (ex.: google_capi_status).
# Misturar destinos no mesmo enum colapsa eixos ortogonais (foi exatamente o
# problema que motivou o desacoplamento scoring × CAPI Meta em 2026-05-27).
_STATUS_MAP = {
    'success':              'success',
    'error':                'error',
    'skipped_allowlist':    'skipped_allowlist',
    'skipped_missing_data': 'skipped_missing_data',
}


class RegistrosMLAdapter:
    """Implementa `LeadRepository` lendo do ledger novo."""

    # Colunas selecionadas em ordem fixa — `_row_to_record` depende dessa ordem.
    _COLUMNS = (
        'event_id', 'email', 'created_at', 'base_status',
        'decil', 'lead_score', 'variant',
        'utm_source', 'utm_medium', 'utm_campaign',
        'utm_content', 'utm_term', 'utm_url',
        'capi_sent_at', 'error_message',
        'survey_responses',
        'first_name', 'last_name', 'phone',
        'fbp', 'fbc',
        'user_agent', 'ip', 'has_computer',
    )

    def __init__(self, railway_conn):
        """`railway_conn`: conexão `pg8000.native.Connection` aberta pro Railway."""
        self.conn = railway_conn

    # ─ interface pública ──────────────────────────────────────────────────

    def recent_leads(
        self, window_minutes: int, limit: int = 10_000,
    ) -> list[LeadRecord]:
        _validate_window(window_minutes)
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        return self._fetch(
            'WHERE created_at >= :cutoff '
            'ORDER BY created_at DESC LIMIT :lim',
            limit_value=limit, cutoff=cutoff, lim=limit,
        )

    def leads_in_range(
        self, start: datetime, end: datetime, limit: int = 10_000,
    ) -> list[LeadRecord]:
        _validate_range(start, end)
        return self._fetch(
            'WHERE created_at >= :start AND created_at < :end '
            'ORDER BY created_at DESC LIMIT :lim',
            limit_value=limit, start=start, end=end, lim=limit,
        )

    def get_by_event_id(self, event_id: str) -> Optional[LeadRecord]:
        records = self._fetch(
            'WHERE event_id = :eid LIMIT 1',
            limit_value=2, eid=event_id,
        )
        return records[0] if records else None

    # ─ interno ────────────────────────────────────────────────────────────

    def _fetch(self, where_clause: str, *, limit_value: int, **params) -> list[LeadRecord]:
        sql = (
            f"SELECT {', '.join(self._COLUMNS)} "
            f"FROM registros_ml {where_clause}"
        )
        rows = self.conn.run(sql, **params)
        records = [self._row_to_record(r) for r in rows]
        if len(records) >= limit_value:
            logger.warning(
                "[registros_ml_adapter] retorno bateu no limite de %d linhas — "
                "resultado possivelmente truncado", limit_value
            )
        return records

    @staticmethod
    def _row_to_record(row: Any) -> LeadRecord:
        (event_id, email, created_at, base_status,
         decil, lead_score, variant,
         utm_source, utm_medium, utm_campaign,
         utm_content, utm_term, utm_url,
         capi_sent_at, error_message,
         survey_responses_raw,
         first_name, last_name, phone,
         fbp, fbc,
         user_agent, ip, has_computer) = row
        return LeadRecord(
            event_id=event_id,
            email=email,
            criado_em=created_at,
            status_envio=_STATUS_MAP.get(base_status, base_status),
            decil=int(decil) if decil is not None else None,
            score=float(lead_score) if lead_score is not None else None,
            variant=variant,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            utm_content=utm_content,
            utm_term=utm_term,
            utm_url=utm_url,
            capi_enviado_em=capi_sent_at,
            erro=error_message,
            survey_responses=_parse_survey(survey_responses_raw),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            fbp=fbp,
            fbc=fbc,
            user_agent=user_agent,
            ip=ip,
            has_computer=has_computer,
        )


# ─ helpers ────────────────────────────────────────────────────────────────

def _parse_survey(raw: Any) -> Optional[Dict[str, str]]:
    """Normaliza JSONB `survey_responses` em dict[str, str] ou None.

    pg8000 devolve JSONB às vezes como dict (parseado), às vezes como string.
    Cobre ambos. Valores não-string viram string pra contrato consistente
    com o adaptador legado.
    """
    if raw is None or raw == '':
        return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
    else:
        parsed = raw
    if not isinstance(parsed, dict):
        return None
    return {str(k): str(v) for k, v in parsed.items() if v is not None}
