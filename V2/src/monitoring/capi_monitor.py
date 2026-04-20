"""
Monitor de qualidade CAPI - verifica qualidade dos dados de Conversion API.

Verifica:
- Missing rate alto de fbp/fbc (> 50%)
- Alta taxa de rejeição de eventos CAPI
- [T1-2] Decis com 0 eventos CAPI nas últimas 24h (bug histórico: D9 ficou 2 meses invisível)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class CAPIQualityMonitor:
    """
    Monitor de qualidade CAPI.
    Verifica qualidade dos dados de Conversion API do Facebook.
    """

    def __init__(self, db: Session, client_config=None):
        """
        Args:
            db:            Sessão SQLAlchemy do PostgreSQL
            client_config: ClientConfig opcional — thresholds de monitoring.thresholds
        """
        from .config import THRESHOLDS
        self.db = db
        monitoring = client_config.monitoring if client_config else None
        self._thresholds = (
            monitoring.thresholds if monitoring and monitoring.thresholds else THRESHOLDS
        )

    def check(self) -> List[Dict]:
        """
        Executa todos os checks de qualidade CAPI.

        Returns:
            Lista de alertas no formato dict
        """
        if self.db is None:
            return []

        alerts = []

        if self._thresholds['capi_quality']['enabled']:
            alerts.extend(self._check_capi_missing_rate())
            alerts.extend(self._check_capi_rejection_rate())
            alerts.extend(self._check_zero_decil_events())

        return alerts

    def _check_capi_missing_rate(self) -> List[Dict]:
        """Verifica missing rate de fbp/fbc nas últimas 24h"""
        from api.database import LeadCAPI

        alerts = []

        threshold = self._thresholds['capi_quality']['missing_rate']
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
                    'message': f" FBP missing em {fbp_missing_rate*100:.1f}% dos leads ({missing_fbp}/{total_leads} últimas 24h)",
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
                    'message': f" FBC missing em {fbc_missing_rate*100:.1f}% dos leads ({missing_fbc}/{total_leads} últimas 24h)",
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

    def _check_zero_decil_events(self) -> List[Dict]:
        """
        [T1-2] Verifica que todos os decis D01–D10 geraram eventos CAPI com sucesso.

        Motivação: D9 ficou 2 meses com 0 eventos sem nenhum alerta.
        Só dispara se o volume mínimo foi atingido no período (evita falso
        positivo em dias sem captação ativa).
        """
        from api.database import LeadCAPI

        alerts = []

        lookback_hours = self._thresholds['capi_quality'].get('zero_decil_lookback_hours', 24)
        min_leads = self._thresholds['capi_quality'].get('zero_decil_min_leads', 20)
        lookback_time = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        all_decils = [f'D{str(i).zfill(2)}' for i in range(1, 11)]

        try:
            recent_capi = self.db.query(LeadCAPI).filter(
                LeadCAPI.capi_sent_at >= lookback_time,
                LeadCAPI.capi_response_status == 'success',
                LeadCAPI.decil.isnot(None)
            ).all()

            if len(recent_capi) < min_leads:
                logger.debug(
                    f"  [T1-2] {len(recent_capi)} eventos em {lookback_hours}h "
                    f"— abaixo do mínimo ({min_leads}), check ignorado"
                )
                return alerts

            decil_counts = {d: 0 for d in all_decils}
            for lead in recent_capi:
                if lead.decil in decil_counts:
                    decil_counts[lead.decil] += 1

            zero_decils = [d for d in all_decils if decil_counts[d] == 0]

            if zero_decils:
                alerts.append({
                    'type': 'capi_zero_decil_events',
                    'severity': 'HIGH',
                    'category': 'capi_quality',
                    'message': (
                        f"[T1-2] Decis sem eventos CAPI nas últimas {lookback_hours}h: "
                        f"{', '.join(zero_decils)} — possível bug silencioso "
                        f"(histórico: D9 por 2 meses)"
                    ),
                    'details': {
                        'zero_decils': zero_decils,
                        'decil_counts': decil_counts,
                        'total_success_events': len(recent_capi),
                        'period_hours': lookback_hours,
                        'min_leads_threshold': min_leads,
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': len(zero_decils),
                    'threshold': 0,
                })

        except Exception as e:
            logger.warning(f"  [T1-2] _check_zero_decil_events: erro inesperado — {e}")

        return alerts

    def _check_capi_rejection_rate(self) -> List[Dict]:
        """
        Verifica taxa de rejeição de eventos CAPI pela Meta.

        Query no banco: leads enviados nas últimas 24h com resposta da Meta
        """
        from api.database import LeadCAPI

        alerts = []

        # Threshold configurável (padrão: 10%)
        threshold = self._thresholds['capi_quality'].get('rejection_rate', 0.10)
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
                    'message': f" Taxa de erro CAPI alta: {error_rate*100:.1f}% ({error_count + partial_count}/{total_eventos} últimas 24h)",
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
