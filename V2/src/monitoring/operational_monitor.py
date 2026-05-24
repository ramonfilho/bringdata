"""Monitor operacional — verifica problemas de infraestrutura/operação.

Verifica:
- Mais de N horas sem receber leads (`_check_no_leads`)
- Mais de N horas sem enviar evento CAPI (`_check_no_capi`)

Migrado para `LeadRepository` em 2026-05-24 (Etapa 4 do refator do
monitoramento). Antes lia direto da tabela morta `leads_capi` via ORM;
agora recebe um repositório por injeção e calcula as métricas em cima de
`LeadRecord`s.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict


class OperationalMonitor:
    """Verifica saúde operacional do sistema lendo via `LeadRepository`."""

    # Janela ampla pra encontrar o último lead/CAPI mesmo se silêncio prolongado.
    # Daily-check não é hot path — custo de trazer 1 semana de leads é aceitável.
    _LOOKBACK_MINUTES = 7 * 24 * 60

    def __init__(self, repo, client_config=None):
        """
        Args:
            repo:          `LeadRepository` (injetado pelo orchestrator).
            client_config: ClientConfig opcional — thresholds de monitoring.thresholds.
        """
        from .config import THRESHOLDS
        self.repo = repo
        monitoring = client_config.monitoring if client_config else None
        self._thresholds = (
            monitoring.thresholds if monitoring and monitoring.thresholds else THRESHOLDS
        )

    def check(self) -> List[Dict]:
        """Executa todos os checks operacionais."""
        if self.repo is None:
            return []

        alerts = []
        if self._thresholds['operational']['enabled']:
            alerts.extend(self._check_no_leads())
            alerts.extend(self._check_no_capi())
        return alerts

    # ─ checks ─────────────────────────────────────────────────────────────

    def _check_no_leads(self) -> List[Dict]:
        """Sem leads novos nas últimas N horas (threshold por config)."""
        threshold_hours = self._thresholds['operational']['no_leads_hours']
        try:
            leads = self.repo.recent_leads(window_minutes=self._LOOKBACK_MINUTES)
        except Exception:
            return []

        if not leads:
            return []

        last_lead = max(leads, key=lambda l: l.criado_em)
        last_t = _as_utc(last_lead.criado_em)
        now = datetime.now(timezone.utc)
        hours_since = (now - last_t).total_seconds() / 3600

        if hours_since < threshold_hours:
            return []

        severity = _severity_by_hours(hours_since)
        return [{
            'type': 'no_leads_received',
            'severity': severity,
            'category': 'operational',
            'message': (
                f"Nenhum lead recebido nas últimas {hours_since:.1f} horas "
                f"(último: {last_t.isoformat()})"
            ),
            'details': {
                'last_lead_at': last_t.isoformat(),
                'hours_since': hours_since,
                'last_lead_email': last_lead.email,
            },
            'timestamp': now.isoformat(),
            'metric_value': hours_since,
            'threshold': float(threshold_hours),
        }]

    def _check_no_capi(self) -> List[Dict]:
        """Sem envios CAPI bem-sucedidos nas últimas N horas."""
        threshold_hours = self._thresholds['operational']['no_capi_hours']
        try:
            leads = self.repo.recent_leads(window_minutes=self._LOOKBACK_MINUTES)
        except Exception:
            return []

        sent = [l for l in leads if l.capi_enviado_em is not None]
        if not sent:
            return []

        last_capi = max(sent, key=lambda l: l.capi_enviado_em)
        last_t = _as_utc(last_capi.capi_enviado_em)
        now = datetime.now(timezone.utc)
        hours_since = (now - last_t).total_seconds() / 3600

        if hours_since < threshold_hours:
            return []

        severity = _severity_by_hours(hours_since)
        return [{
            'type': 'no_capi_sent',
            'severity': severity,
            'category': 'operational',
            'message': (
                f"Nenhum evento CAPI enviado nas últimas {hours_since:.1f} horas "
                f"(último: {last_t.isoformat()})"
            ),
            'details': {
                'last_capi_at': last_t.isoformat(),
                'hours_since': hours_since,
                'last_lead_email': last_capi.email,
            },
            'timestamp': now.isoformat(),
            'metric_value': hours_since,
            'threshold': float(threshold_hours),
        }]


# ─ helpers ────────────────────────────────────────────────────────────────

def _as_utc(dt: datetime) -> datetime:
    """Normaliza datetime pra timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _severity_by_hours(hours: float) -> str:
    if hours >= 12:
        return 'HIGH'
    if hours >= 8:
        return 'MEDIUM'
    return 'LOW'
