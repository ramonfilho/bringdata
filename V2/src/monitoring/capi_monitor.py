"""
Monitor de qualidade CAPI - verifica qualidade dos dados de Conversion API.

Verifica:
- Missing rate alto de fbp/fbc (> 50%)
- Alta taxa de rejeição de eventos CAPI (futuro - via logs)
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict
from sqlalchemy.orm import Session


class CAPIQualityMonitor:
    """
    Monitor de qualidade CAPI.
    Verifica qualidade dos dados de Conversion API do Facebook.
    """

    def __init__(self, db: Session):
        """
        Args:
            db: Sessão SQLAlchemy do PostgreSQL
        """
        self.db = db

    def check(self) -> List[Dict]:
        """
        Executa todos os checks de qualidade CAPI.

        Returns:
            Lista de alertas no formato dict
        """
        from .config import THRESHOLDS

        alerts = []

        if THRESHOLDS['capi_quality']['enabled']:
            alerts.extend(self._check_capi_missing_rate())
            alerts.extend(self._check_capi_rejection_rate())

        return alerts

    def _check_capi_missing_rate(self) -> List[Dict]:
        """Verifica missing rate de fbp/fbc nas últimas 24h"""
        from .config import THRESHOLDS
        from api.database import LeadCAPI

        alerts = []

        threshold = THRESHOLDS['capi_quality']['missing_rate']
        lookback_hours = 24
        lookback_time = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        try:
            # Buscar leads das últimas 24h
            recent_leads = self.db.query(LeadCAPI).filter(
                LeadCAPI.created_at >= lookback_time
            ).all()

            if not recent_leads:
                return alerts

            total_leads = len(recent_leads)

            # Contar missing por campo
            missing_fbp = sum(1 for lead in recent_leads if not lead.fbp or lead.fbp == '')
            missing_fbc = sum(1 for lead in recent_leads if not lead.fbc or lead.fbc == '')

            fbp_missing_rate = missing_fbp / total_leads
            fbc_missing_rate = missing_fbc / total_leads

            # Verificar FBP
            if fbp_missing_rate > threshold:
                if fbp_missing_rate >= 0.75:
                    severity = 'HIGH'
                elif fbp_missing_rate >= 0.60:
                    severity = 'MEDIUM'
                else:
                    severity = 'LOW'

                alerts.append({
                    'type': 'capi_fbp_missing_high',
                    'severity': severity,
                    'category': 'capi_quality',
                    'message': f"⚠️ FBP missing em {fbp_missing_rate*100:.1f}% dos leads ({missing_fbp}/{total_leads} últimas 24h)",
                    'details': {
                        'field': 'fbp',
                        'missing_count': missing_fbp,
                        'total_leads': total_leads,
                        'missing_rate': fbp_missing_rate,
                        'period_hours': lookback_hours
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': fbp_missing_rate,
                    'threshold': threshold
                })

            # Verificar FBC
            if fbc_missing_rate > threshold:
                if fbc_missing_rate >= 0.75:
                    severity = 'HIGH'
                elif fbc_missing_rate >= 0.60:
                    severity = 'MEDIUM'
                else:
                    severity = 'LOW'

                alerts.append({
                    'type': 'capi_fbc_missing_high',
                    'severity': severity,
                    'category': 'capi_quality',
                    'message': f"⚠️ FBC missing em {fbc_missing_rate*100:.1f}% dos leads ({missing_fbc}/{total_leads} últimas 24h)",
                    'details': {
                        'field': 'fbc',
                        'missing_count': missing_fbc,
                        'total_leads': total_leads,
                        'missing_rate': fbc_missing_rate,
                        'period_hours': lookback_hours
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': fbc_missing_rate,
                    'threshold': threshold
                })

        except Exception:
            pass

        return alerts

    def _check_capi_rejection_rate(self) -> List[Dict]:
        """
        Verifica taxa de rejeição de eventos CAPI pela Meta.

        Query no banco: leads enviados nas últimas 24h com resposta da Meta
        """
        from .config import THRESHOLDS
        from api.database import LeadCAPI

        alerts = []

        # Threshold configurável (padrão: 10%)
        threshold = THRESHOLDS['capi_quality'].get('rejection_rate', 0.10)
        lookback_hours = 24
        lookback_time = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        try:
            # Buscar leads com CAPI enviado nas últimas 24h
            recent_capi = self.db.query(LeadCAPI).filter(
                LeadCAPI.capi_sent_at >= lookback_time,
                LeadCAPI.capi_response_status.isnot(None)  # Só leads com resposta registrada
            ).all()

            if not recent_capi:
                return alerts

            total_eventos = len(recent_capi)

            # Contar por status
            status_counts = {}
            eventos_rejeitados_total = 0

            for lead in recent_capi:
                status = lead.capi_response_status or 'unknown'
                status_counts[status] = status_counts.get(status, 0) + 1

                # Somar eventos rejeitados
                if lead.capi_events_rejected:
                    eventos_rejeitados_total += lead.capi_events_rejected

            success_count = status_counts.get('success', 0)
            error_count = status_counts.get('error', 0)
            partial_count = status_counts.get('partial', 0)

            # Taxa de erro (error + partial)
            error_rate = (error_count + partial_count) / total_eventos if total_eventos > 0 else 0

            if error_rate > threshold:
                # Determinar severidade
                if error_rate >= 0.25:  # 25% ou mais
                    severity = 'HIGH'
                elif error_rate >= 0.15:  # 15% ou mais
                    severity = 'MEDIUM'
                else:
                    severity = 'LOW'

                alerts.append({
                    'type': 'capi_rejection_rate_high',
                    'severity': severity,
                    'category': 'capi_quality',
                    'message': f"⚠️ Taxa de erro CAPI alta: {error_rate*100:.1f}% ({error_count + partial_count}/{total_eventos} últimas 24h)",
                    'details': {
                        'total_leads': total_eventos,
                        'success_count': success_count,
                        'error_count': error_count,
                        'partial_count': partial_count,
                        'events_rejected': eventos_rejeitados_total,
                        'error_rate': error_rate,
                        'period_hours': lookback_hours
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': error_rate,
                    'threshold': threshold
                })

        except Exception:
            pass

        return alerts
