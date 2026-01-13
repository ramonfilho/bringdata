"""
Módulo de monitoramento centralizado.

Inclui:
- Data Quality: category drift, distribution drift, missing rate, score distribution
- Operational: 6h sem leads, 6h sem CAPI
- CAPI Quality: missing rate fbp/fbc, rejection rate
"""

# Funções standalone (legacy - para compatibilidade com pipelines)
from .data_quality import (
    capture_training_categories,
    check_category_drift,
    load_training_categories,
    capture_training_distributions,
    check_distribution_drift,
    load_training_distributions
)

# Monitors (nova arquitetura)
from .data_quality import DataQualityMonitor
from .operational_monitor import OperationalMonitor
from .capi_monitor import CAPIQualityMonitor
from .orchestrator import MonitoringOrchestrator

# Models
from .models import Alert, Severity, AlertCategory

__all__ = [
    # Funções standalone (legacy)
    'capture_training_categories',
    'check_category_drift',
    'load_training_categories',
    'capture_training_distributions',
    'check_distribution_drift',
    'load_training_distributions',
    # Monitors
    'DataQualityMonitor',
    'OperationalMonitor',
    'CAPIQualityMonitor',
    'MonitoringOrchestrator',
    # Models
    'Alert',
    'Severity',
    'AlertCategory'
]
