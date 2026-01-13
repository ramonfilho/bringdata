"""
Orquestrador central de monitoramento.

Coordena execução de todos os monitors e consolida alertas.
"""

import logging
import pandas as pd
from typing import List, Dict
from sqlalchemy.orm import Session

from .data_quality import DataQualityMonitor
from .operational_monitor import OperationalMonitor
from .capi_monitor import CAPIQualityMonitor
from .models import Alert

logger = logging.getLogger(__name__)


class MonitoringOrchestrator:
    """
    Orquestrador central que executa todos os monitors e consolida alertas.
    """

    def __init__(self, model_path: str, db: Session):
        """
        Args:
            model_path: Caminho para pasta do modelo ativo
            db: Sessão SQLAlchemy do PostgreSQL
        """
        self.model_path = model_path
        self.db = db

        # Inicializar monitors
        self.monitors = {
            'data_quality': DataQualityMonitor(model_path),
            'operational': OperationalMonitor(db),
            'capi_quality': CAPIQualityMonitor(db)
        }

    def run_daily_check(self, leads_data: List[Dict]) -> Dict:
        """
        Executa check diário completo.

        Args:
            leads_data: Lista de dicts com dados do Sheets (últimas 24h)

        Returns:
            {
                'total_alerts': int,
                'alerts_by_severity': {'HIGH': 2, 'MEDIUM': 1, 'LOW': 2},
                'alerts_by_category': {'data_quality': 3, 'operational': 1, 'capi_quality': 1},
                'alerts': [Alert.to_dict(), ...]
            }
        """
        all_alerts_dict = []

        # 1. Data Quality (usa JSON do Sheets)
        if leads_data:
            df = pd.DataFrame(leads_data)

            # Logar range de leads analisados (para facilitar debug com arquivo local)
            primeiro_email = df.iloc[0].get('E-mail', 'N/A') if len(df) > 0 else 'N/A'
            primeiro_data = df.iloc[0].get('Data', 'N/A') if len(df) > 0 else 'N/A'
            ultimo_email = df.iloc[-1].get('E-mail', 'N/A') if len(df) > 0 else 'N/A'
            ultimo_data = df.iloc[-1].get('Data', 'N/A') if len(df) > 0 else 'N/A'

            logger.info(f"📧 Primeiro lead: {primeiro_email} (Data: {primeiro_data})")
            logger.info(f"📧 Último lead: {ultimo_email} (Data: {ultimo_data})")

            all_alerts_dict.extend(self.monitors['data_quality'].check(df))

        # 2. Operational (usa PostgreSQL)
        all_alerts_dict.extend(self.monitors['operational'].check())

        # 3. CAPI Quality (usa PostgreSQL)
        all_alerts_dict.extend(self.monitors['capi_quality'].check())

        # Converter para objetos Alert
        alerts = [Alert.from_dict(alert_dict) for alert_dict in all_alerts_dict]

        # Gerar sumário
        summary = self._generate_summary(alerts)

        return {
            'total_alerts': len(alerts),
            'alerts_by_severity': summary['by_severity'],
            'alerts_by_category': summary['by_category'],
            'alerts': [alert.to_dict() for alert in alerts]
        }

    def _generate_summary(self, alerts: List[Alert]) -> Dict:
        """Gera sumário de alertas por severidade e categoria"""
        by_severity = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        by_category = {'data_quality': 0, 'operational': 0, 'capi_quality': 0}

        for alert in alerts:
            by_severity[alert.severity.value] += 1
            by_category[alert.category.value] += 1

        return {
            'by_severity': by_severity,
            'by_category': by_category
        }
