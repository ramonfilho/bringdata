"""
Monitor operacional - verifica problemas de infraestrutura/operação.

Verifica:
- Mais de 6h sem receber leads
- Mais de 6h sem enviar eventos CAPI
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func


class OperationalMonitor:
    """
    Monitor operacional que verifica saúde do sistema.
    Usa PostgreSQL para verificar timestamps.
    """

    def __init__(self, db: Session):
        """
        Args:
            db: Sessão SQLAlchemy do PostgreSQL
        """
        self.db = db

    def check(self) -> List[Dict]:
        """
        Executa todos os checks operacionais.

        Returns:
            Lista de alertas no formato dict
        """
        from .config import THRESHOLDS

        alerts = []

        if THRESHOLDS['operational']['enabled']:
            alerts.extend(self._check_no_leads())
            alerts.extend(self._check_no_capi())

        return alerts

    def _check_no_leads(self) -> List[Dict]:
        """Verifica se não recebeu leads nas últimas N horas"""
        from .config import THRESHOLDS
        # Import aqui para evitar circular import
        from api.database import LeadCAPI

        alerts = []

        print("\n" + "="*80)
        print("🔍 CHECK: Mais de 6 horas sem receber leads")
        print("="*80)

        threshold_hours = THRESHOLDS['operational']['no_leads_hours']
        threshold_time = datetime.now(timezone.utc) - timedelta(hours=threshold_hours)

        print(f"Threshold: {threshold_hours} horas")

        try:
            # Buscar lead mais recente
            last_lead = self.db.query(LeadCAPI).order_by(
                LeadCAPI.created_at.desc()
            ).first()

            if not last_lead:
                # Banco vazio (pode ser normal em dev/staging)
                print("❌ Status: ERRO - Banco sem leads (dev/staging)")
                return alerts

            # Converter timestamp do banco para timezone-aware UTC
            last_lead_time = last_lead.created_at.replace(tzinfo=timezone.utc) if last_lead.created_at.tzinfo is None else last_lead.created_at

            time_since_last = datetime.now(timezone.utc) - last_lead_time
            hours_since = time_since_last.total_seconds() / 3600

            print(f"Último lead: {last_lead_time.isoformat()}")
            print(f"Tempo desde último lead: {hours_since:.1f} horas")

            if last_lead_time < threshold_time:
                print(f"\n⚠️  Status: ALERTA - Sem leads há {hours_since:.1f}h (threshold: {threshold_hours}h)")

                # Determinar severidade
                if hours_since >= 12:
                    severity = 'HIGH'
                elif hours_since >= 8:
                    severity = 'MEDIUM'
                else:
                    severity = 'LOW'

                alerts.append({
                    'type': 'no_leads_received',
                    'severity': severity,
                    'category': 'operational',
                    'message': f"⚠️ Nenhum lead recebido nas últimas {hours_since:.1f} horas (último: {last_lead_time.isoformat()})",
                    'details': {
                        'last_lead_at': last_lead_time.isoformat(),
                        'hours_since': hours_since,
                        'last_lead_email': last_lead.email
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': hours_since,
                    'threshold': float(threshold_hours)
                })
            else:
                print(f"✅ Status: OK - Leads sendo recebidos regularmente")

        except Exception as e:
            # Log erro mas não interrompe
            print(f"❌ Status: ERRO - {str(e)}")

        return alerts

    def _check_no_capi(self) -> List[Dict]:
        """Verifica se não enviou CAPI nas últimas N horas"""
        from .config import THRESHOLDS
        from api.database import LeadCAPI

        alerts = []

        print("\n" + "="*80)
        print("🔍 CHECK: Mais de 6 horas sem enviar evento CAPI")
        print("="*80)

        threshold_hours = THRESHOLDS['operational']['no_capi_hours']
        threshold_time = datetime.now(timezone.utc) - timedelta(hours=threshold_hours)

        print(f"Threshold: {threshold_hours} horas")

        try:
            # Buscar último envio CAPI
            last_capi = self.db.query(LeadCAPI).filter(
                LeadCAPI.capi_sent_at.isnot(None)
            ).order_by(
                LeadCAPI.capi_sent_at.desc()
            ).first()

            if not last_capi:
                # Nenhum CAPI enviado ainda (pode ser normal em setup novo)
                print("❌ Status: ERRO - Nenhum CAPI enviado ainda (setup novo)")
                return alerts

            # Converter timestamp do banco para timezone-aware UTC
            last_capi_time = last_capi.capi_sent_at.replace(tzinfo=timezone.utc) if last_capi.capi_sent_at.tzinfo is None else last_capi.capi_sent_at

            time_since_last = datetime.now(timezone.utc) - last_capi_time
            hours_since = time_since_last.total_seconds() / 3600

            print(f"Último CAPI: {last_capi_time.isoformat()}")
            print(f"Tempo desde último CAPI: {hours_since:.1f} horas")

            if last_capi_time < threshold_time:
                print(f"\n⚠️  Status: ALERTA - Sem CAPI há {hours_since:.1f}h (threshold: {threshold_hours}h)")
                hours_since = time_since_last.total_seconds() / 3600

                # Determinar severidade
                if hours_since >= 12:
                    severity = 'HIGH'
                elif hours_since >= 8:
                    severity = 'MEDIUM'
                else:
                    severity = 'LOW'

                alerts.append({
                    'type': 'no_capi_sent',
                    'severity': severity,
                    'category': 'operational',
                    'message': f"⚠️ Nenhum evento CAPI enviado nas últimas {hours_since:.1f} horas (último: {last_capi_time.isoformat()})",
                    'details': {
                        'last_capi_at': last_capi_time.isoformat(),
                        'hours_since': hours_since,
                        'last_lead_email': last_capi.email
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metric_value': hours_since,
                    'threshold': float(threshold_hours)
                })
            else:
                print(f"✅ Status: OK - Eventos CAPI sendo enviados regularmente")

        except Exception as e:
            # Log erro mas não interrompe
            print(f"❌ Status: ERRO - {str(e)}")

        return alerts
