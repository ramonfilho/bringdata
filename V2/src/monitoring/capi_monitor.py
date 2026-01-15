"""
Monitor de qualidade CAPI - verifica qualidade dos dados de Conversion API.

Verifica:
- Missing rate alto de fbp/fbc (> 50%)
- Alta taxa de rejeição de eventos CAPI (futuro - via logs)
"""

from datetime import datetime, timedelta
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
            # Futuro: alerts.extend(self._check_capi_rejection_rate())

        return alerts

    def _check_capi_missing_rate(self) -> List[Dict]:
        """Verifica missing rate de fbp/fbc nas últimas 24h"""
        from .config import THRESHOLDS
        from api.database import LeadCAPI

        alerts = []

        print("\n" + "="*80)
        print("🔍 CHECK: Missing rate alto de dados CAPI (fbp/fbc > 50%)")
        print("="*80)

        threshold = THRESHOLDS['capi_quality']['missing_rate']
        lookback_hours = 24
        lookback_time = datetime.now() - timedelta(hours=lookback_hours)

        print(f"Threshold: {threshold*100:.1f}% (máximo permitido)")
        print(f"Período: últimas {lookback_hours} horas")

        try:
            # Buscar leads das últimas 24h
            recent_leads = self.db.query(LeadCAPI).filter(
                LeadCAPI.created_at >= lookback_time
            ).all()

            if not recent_leads:
                # Sem leads recentes
                print("❌ Status: ERRO - Sem leads nas últimas 24h")
                return alerts

            total_leads = len(recent_leads)

            # Contar missing por campo
            missing_fbp = sum(1 for lead in recent_leads if not lead.fbp or lead.fbp == '')
            missing_fbc = sum(1 for lead in recent_leads if not lead.fbc or lead.fbc == '')

            fbp_missing_rate = missing_fbp / total_leads
            fbc_missing_rate = missing_fbc / total_leads

            print(f"Total de leads: {total_leads}")
            print(f"FBP missing: {fbp_missing_rate*100:.1f}% ({missing_fbp}/{total_leads})")
            print(f"FBC missing: {fbc_missing_rate*100:.1f}% ({missing_fbc}/{total_leads})")

            campos_acima_threshold = []

            # Verificar FBP
            if fbp_missing_rate > threshold:
                campos_acima_threshold.append(('FBP', fbp_missing_rate))

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
                    'timestamp': datetime.now().isoformat(),
                    'metric_value': fbp_missing_rate,
                    'threshold': threshold
                })

            # Verificar FBC
            if fbc_missing_rate > threshold:
                campos_acima_threshold.append(('FBC', fbc_missing_rate))

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
                    'timestamp': datetime.now().isoformat(),
                    'metric_value': fbc_missing_rate,
                    'threshold': threshold
                })

            # Mostrar resumo
            if campos_acima_threshold:
                print(f"\n⚠️  Status: ALERTA - {len(campos_acima_threshold)} campo(s) CAPI com missing alto")
                for campo, rate in campos_acima_threshold:
                    print(f"   • {campo}: {rate*100:.1f}%")
            else:
                print(f"✅ Status: OK - FBP e FBC com missing < {threshold*100:.1f}%")

        except Exception as e:
            # Log erro mas não interrompe
            print(f"❌ Status: ERRO - {str(e)}")

        return alerts

    def _check_capi_rejection_rate(self) -> List[Dict]:
        """
        Verifica taxa de rejeição de eventos CAPI.

        TODO: Implementar leitura de logs do Cloud Run para detectar
        erros de envio CAPI (status 400, 500, etc).
        """
        alerts = []
        # Implementação futura
        return alerts
