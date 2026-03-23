"""
Data Validation - Retreino Mensal

Wrapper do DataQualityMonitor (produção) + validações específicas de retreino.

Valida:
    - Category drift (via monitor existente)
    - Distribution drift (via monitor existente)
    - Missing rate (via monitor existente)
    - Volume mínimo de dados (específico retreino)
    - Taxa de conversão esperada (específico retreino)
    - Período de dados válido (específico retreino)

Status:  Implementado (Sprint 1)
"""

import logging
import pandas as pd
from typing import Dict, List
from datetime import datetime, timedelta
from pathlib import Path

# Imports do monitoramento existente
from src.monitoring.data_quality import DataQualityMonitor
from src.monitoring.config import THRESHOLDS

logger = logging.getLogger(__name__)


class RetrainingDataValidator:
    """
    Validador de dados para retreino mensal.

    Reusa DataQualityMonitor (produção) e adiciona validações específicas.
    """

    def __init__(self, model_path: str, config: dict):
        """
        Inicializa validador.

        Args:
            model_path: Caminho do modelo ativo (ex: files/20260117_123456)
            config: Dict de configuração do retreino (validation section)
        """
        self.model_path = model_path
        self.config = config

        # Inicializar monitor de produção (reusa código existente!)
        try:
            self.monitor = DataQualityMonitor(model_path)
            logger.info(f" DataQualityMonitor inicializado (model: {model_path})")
        except Exception as e:
            logger.warning(f"  Não foi possível inicializar monitor: {e}")
            self.monitor = None

    def validate(self, df: pd.DataFrame) -> Dict:
        """
        Executa todas as validações de dados.

        Args:
            df: DataFrame com dados para treino (antes do preprocessing)

        Returns:
            Dict estruturado:
            {
                'passed': bool,
                'has_critical_failures': bool,
                'critical_count': int,
                'warning_count': int,
                'validations': [
                    {
                        'type': str,
                        'severity': 'HIGH|MEDIUM|LOW',
                        'passed': bool,
                        'message': str,
                        'details': dict
                    },
                    ...
                ]
            }
        """
        logger.info(" Executando validações de dados...")

        validations = []

        # ========================================
        # 1. DRIFT CHECKS (reusa monitor)
        # ========================================
        if self.monitor and self.config.get('reuse_monitoring_thresholds', True):
            logger.info("   Executando drift checks (via DataQualityMonitor)...")
            try:
                drift_alerts = self.monitor.check(df)

                # Converter formato do monitor para formato de validação
                for alert in drift_alerts:
                    validations.append({
                        'type': alert.get('type', 'unknown'),
                        'severity': alert.get('severity', 'MEDIUM'),
                        'passed': alert.get('severity') != 'HIGH',
                        'message': alert.get('message', ''),
                        'details': alert.get('details', {})
                    })

                logger.info(f"       {len(drift_alerts)} alertas de drift detectados")

            except Exception as e:
                logger.warning(f"        Erro ao executar drift checks: {e}")
        else:
            logger.info("   Drift checks desabilitados ou monitor indisponível")

        # ========================================
        # 2. VALIDAÇÕES ESPECÍFICAS DE RETREINO
        # ========================================
        logger.info("   Executando validações específicas de retreino...")

        # Volume mínimo
        volume_result = self._validate_volume(df)
        validations.append(volume_result)

        # Taxa de conversão
        conversion_result = self._validate_conversion_rate(df)
        validations.append(conversion_result)

        # Período de dados
        date_range_result = self._validate_date_range(df)
        validations.append(date_range_result)

        # ========================================
        # 3. RESUMO E CLASSIFICAÇÃO
        # ========================================
        critical_failures = self.config.get('critical_failures', ['HIGH'])

        critical = [v for v in validations if v['severity'] in critical_failures and not v['passed']]
        warnings = [v for v in validations if v['severity'] not in critical_failures and not v['passed']]
        passed = [v for v in validations if v['passed']]

        result = {
            'passed': len(critical) == 0,
            'has_critical_failures': len(critical) > 0,
            'critical_count': len(critical),
            'warning_count': len(warnings),
            'passed_count': len(passed),
            'total_validations': len(validations),
            'validations': validations
        }

        # Log resumo
        logger.info(f"\n Resumo de Validações:")
        logger.info(f"   Total: {len(validations)}")
        logger.info(f"    Passou: {len(passed)}")
        logger.info(f"     Warnings: {len(warnings)}")
        logger.info(f"    Críticos: {len(critical)}")

        if critical:
            logger.error(f"\n VALIDAÇÃO FALHOU - {len(critical)} falha(s) crítica(s):")
            for fail in critical:
                logger.error(f"    {fail['message']}")
        else:
            logger.info(f" Validação passou - dados OK para retreino")

        return result

    def _validate_volume(self, df: pd.DataFrame) -> Dict:
        """
        Valida volume mínimo de dados para treino.

        Args:
            df: DataFrame com dados

        Returns:
            Dict com resultado da validação
        """
        min_records = self.config.get('min_records', 1000)
        actual_records = len(df)

        passed = actual_records >= min_records
        severity = 'HIGH' if not passed else 'LOW'

        return {
            'type': 'volume_check',
            'severity': severity,
            'passed': passed,
            'message': (
                f"Volume de dados: {actual_records:,} registros "
                f"({'' if passed else ''} mínimo: {min_records:,})"
            ),
            'details': {
                'actual': actual_records,
                'minimum': min_records,
                'delta': actual_records - min_records
            }
        }

    def _validate_conversion_rate(self, df: pd.DataFrame) -> Dict:
        """
        Valida taxa de conversão dentro do esperado.

        Args:
            df: DataFrame com dados (deve ter coluna 'target')

        Returns:
            Dict com resultado da validação
        """
        if 'target' not in df.columns:
            return {
                'type': 'conversion_rate',
                'severity': 'HIGH',
                'passed': False,
                'message': " Coluna 'target' não encontrada nos dados",
                'details': {'error': 'missing_target_column'}
            }

        conv_rate = df['target'].mean()
        min_rate = self.config.get('conversion_rate_min', 0.005)  # 0.5%
        max_rate = self.config.get('conversion_rate_max', 0.05)   # 5%

        passed = min_rate <= conv_rate <= max_rate
        severity = 'HIGH' if not passed else 'LOW'

        return {
            'type': 'conversion_rate',
            'severity': severity,
            'passed': passed,
            'message': (
                f"Taxa de conversão: {conv_rate:.2%} "
                f"({'' if passed else ''} esperado: {min_rate:.2%} - {max_rate:.2%})"
            ),
            'details': {
                'actual': float(conv_rate),
                'min_expected': min_rate,
                'max_expected': max_rate,
                'conversions': int(df['target'].sum()),
                'total_records': len(df)
            }
        }

    def _validate_date_range(self, df: pd.DataFrame) -> Dict:
        """
        Valida período de dados (mínimo de dias).

        Args:
            df: DataFrame com dados (deve ter coluna 'Data')

        Returns:
            Dict com resultado da validação
        """
        if 'Data' not in df.columns:
            return {
                'type': 'date_range',
                'severity': 'MEDIUM',
                'passed': False,
                'message': "  Coluna 'Data' não encontrada - não foi possível validar período",
                'details': {'error': 'missing_date_column'}
            }

        # Converter para datetime se necessário
        if not pd.api.types.is_datetime64_any_dtype(df['Data']):
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce')

        # Filtrar datas válidas
        dates_valid = df['Data'].dropna()

        if len(dates_valid) == 0:
            return {
                'type': 'date_range',
                'severity': 'HIGH',
                'passed': False,
                'message': " Nenhuma data válida encontrada nos dados",
                'details': {'error': 'no_valid_dates'}
            }

        min_date = dates_valid.min()
        max_date = dates_valid.max()
        date_range_days = (max_date - min_date).days

        min_days = self.config.get('min_date_range_days', 30)
        passed = date_range_days >= min_days
        severity = 'MEDIUM' if not passed else 'LOW'

        return {
            'type': 'date_range',
            'severity': severity,
            'passed': passed,
            'message': (
                f"Período de dados: {date_range_days} dias "
                f"({'' if passed else ''} mínimo: {min_days} dias)\n"
                f"   De {min_date.strftime('%Y-%m-%d')} até {max_date.strftime('%Y-%m-%d')}"
            ),
            'details': {
                'min_date': min_date.isoformat(),
                'max_date': max_date.isoformat(),
                'days': date_range_days,
                'min_required': min_days,
                'records_with_date': len(dates_valid),
                'records_without_date': len(df) - len(dates_valid)
            }
        }


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def get_active_model_path(client_id: str = "devclub") -> str:
    """
    Obtém path do modelo ativo de configs/active_models/{client_id}.yaml.

    Args:
        client_id: Identificador do cliente (default: "devclub")

    Returns:
        Path do modelo ativo (ex: files/20260117_123456)

    Raises:
        FileNotFoundError: Se active_models/{client_id}.yaml não existir
        ValueError: Se path não estiver configurado
    """
    import yaml

    config_path = Path(__file__).parent.parent.parent / 'configs' / 'active_models' / f'{client_id}.yaml'

    if not config_path.exists():
        raise FileNotFoundError(
            f"Arquivo active_models/{client_id}.yaml não encontrado: {config_path}\n"
            "Execute um treino com --set-active para configurar."
        )

    with open(config_path, 'r') as f:
        active_config = yaml.safe_load(f)

    model_path = active_config.get('active_model', {}).get('model_path')

    if not model_path:
        raise ValueError(f"model_path não configurado em active_models/{client_id}.yaml")

    return model_path
