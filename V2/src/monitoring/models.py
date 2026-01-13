"""
Modelos de dados para sistema de monitoramento.
"""

from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional


class Severity(Enum):
    """Severidade de um alerta"""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AlertCategory(Enum):
    """Categoria de um alerta"""
    DATA_QUALITY = "data_quality"
    OPERATIONAL = "operational"
    CAPI_QUALITY = "capi_quality"


@dataclass
class Alert:
    """
    Representa um alerta de monitoramento.

    Attributes:
        type: Tipo do alerta (ex: 'category_drift', 'no_leads_6h')
        severity: Severidade (HIGH, MEDIUM, LOW)
        category: Categoria (DATA_QUALITY, OPERATIONAL, CAPI_QUALITY)
        message: Mensagem user-friendly
        details: Dados técnicos adicionais
        timestamp: Quando o alerta foi gerado
        metric_value: Valor da métrica que gerou o alerta
        threshold: Threshold que foi ultrapassado
    """
    type: str
    severity: Severity
    category: AlertCategory
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    metric_value: Optional[float] = None
    threshold: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário (para JSON)"""
        return {
            'type': self.type,
            'severity': self.severity.value,
            'category': self.category.value,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp.isoformat(),
            'metric_value': self.metric_value,
            'threshold': self.threshold
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Alert':
        """Cria Alert a partir de dicionário"""
        return cls(
            type=data['type'],
            severity=Severity(data['severity']),
            category=AlertCategory(data['category']),
            message=data['message'],
            details=data['details'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            metric_value=data.get('metric_value'),
            threshold=data.get('threshold')
        )
