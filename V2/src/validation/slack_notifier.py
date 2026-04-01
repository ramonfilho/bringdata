"""
Notificador Slack para validação semanal do modelo ML.
Envia sumário de métricas e link para o Excel gerado.
"""

import requests
import logging
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ValidationSlackNotifier:
    """
    Envia notificações de validação semanal para Slack.
    """

    def __init__(self, webhook_url: str = None):
        """
        Args:
            webhook_url: URL do webhook Slack (usa env var se não fornecido)
        """
        import os
        self.webhook_url = webhook_url or os.getenv(
            'SLACK_WEBHOOK_URL',
            'https://hooks.slack.com/services/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'
        )

    def send_validation_summary(
        self,
        metrics: Dict,
        excel_url: Optional[str] = None,
        sheets_url: Optional[str] = None,
        period: Dict = None
    ) -> bool:
        """
        Envia sumário da validação semanal para Slack.

        Args:
            metrics: Dicionário com métricas (auc, conversoes, roas, etc)
            excel_url: URL pública do Excel no Cloud Storage
            sheets_url: URL do Google Sheets criado
            period: Dicionário com datas do período analisado

        Returns:
            True se enviou com sucesso, False caso contrário
        """
        try:
            # Formatar período
            period_text = "Período não especificado"
            report_type = None
            if period:
                period_text = (
                    f"*Captação:* {period.get('start', 'N/A')} a {period.get('end', 'N/A')}\n"
                    f"*Vendas:* {period.get('sales_start', 'N/A')} a {period.get('sales_end', 'N/A')}"
                )
                report_type = period.get('report_type', 'fechamento')

            # Formatar métricas
            metrics_text = self._format_metrics(metrics)

            # Determinar cor (verde se tudo ok, amarelo se degradação)
            color = self._determine_color(metrics)

            # Determinar título baseado no tipo de relatório
            if report_type == 'pos-devolucoes':
                title = " *Validação ML - Relatório Pós-Devoluções (Final)*"
            else:
                title = " *Validação ML - Relatório de Fechamento*"

            # Construir payload
            payload = {
                "text": title,
                "attachments": [
                    {
                        "color": color,
                        "fields": [
                            {
                                "title": " Período Analisado",
                                "value": period_text,
                                "short": False
                            },
                            {
                                "title": " Métricas de Performance",
                                "value": metrics_text,
                                "short": False
                            }
                        ],
                        "footer": "Bring Data Validation System",
                        "ts": int(datetime.now().timestamp())
                    }
                ]
            }

            # Adicionar links dos relatórios se disponíveis
            report_links = []
            if excel_url:
                report_links.append(f"<{excel_url}| Download Excel>")
            if sheets_url:
                report_links.append(f"<{sheets_url}| Ver Google Sheets>")

            if report_links:
                payload["attachments"][0]["fields"].append({
                    "title": " Relatórios",
                    "value": " | ".join(report_links),
                    "short": False
                })

            # Enviar para Slack
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10
            )

            if response.status_code == 200:
                logger.info(" Notificação Slack enviada com sucesso")
                return True
            else:
                logger.error(f" Erro ao enviar Slack: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f" Erro ao notificar Slack: {str(e)}")
            return False

    def send_error_notification(self, error_message: str, period: Dict = None) -> bool:
        """
        Envia notificação de erro na validação para Slack.

        Args:
            error_message: Mensagem de erro
            period: Período que estava sendo processado

        Returns:
            True se enviou com sucesso
        """
        try:
            period_text = "N/A"
            if period:
                period_text = f"{period.get('start', 'N/A')} (vendas: {period.get('sales_start', 'N/A')} a {period.get('sales_end', 'N/A')})"

            payload = {
                "text": " *Erro na Validação Semanal ML*",
                "attachments": [
                    {
                        "color": "#ff0000",
                        "fields": [
                            {
                                "title": "Período",
                                "value": period_text,
                                "short": False
                            },
                            {
                                "title": "Erro",
                                "value": f"```{error_message}```",
                                "short": False
                            }
                        ],
                        "footer": "Bring Data Validation System",
                        "ts": int(datetime.now().timestamp())
                    }
                ]
            }

            response = requests.post(self.webhook_url, json=payload, timeout=10)
            return response.status_code == 200

        except Exception as e:
            logger.error(f" Erro ao enviar notificação de erro: {str(e)}")
            return False

    def _format_metrics(self, metrics: Dict) -> str:
        """
        Formata métricas em texto Slack.
        """
        lines = []

        # AUC (só mostrar se > 0)
        auc_prod = metrics.get('auc_production', 0)
        auc_test = metrics.get('auc_test_set', 0)
        if auc_prod > 0 and auc_test > 0:
            auc_delta = auc_prod - auc_test
            auc_icon = "" if auc_delta >= -0.02 else "" if auc_delta >= -0.05 else ""
            lines.append(f"{auc_icon} *AUC Produção:* {auc_prod:.4f} (Test Set: {auc_test:.4f}, Δ {auc_delta:+.4f})")

        # Concentração
        top3_prod = metrics.get('top3_production', 0)
        top3_test = metrics.get('top3_test_set', 0)
        if top3_prod > 0:
            lines.append(f" *Top 3 Decis:* {top3_prod:.1f}% (Test Set: {top3_test:.1f}%)")

        # Conversões e ROAS (só mostrar conversões se > 0)
        conversoes = metrics.get('conversoes', 0)
        roas = metrics.get('roas', 0)
        if conversoes > 0:
            lines.append(f" *Conversões:* {conversoes:,}")

        if roas > 0:
            roas_icon = "" if roas >= 2.5 else "" if roas >= 1.5 else ""
            lines.append(f"{roas_icon} *ROAS:* {roas:.2f}x")

        # Leads analisados
        leads = metrics.get('leads_analisados', 0)
        if leads > 0:
            lines.append(f" *Leads Analisados:* {leads:,}")

        return "\n".join(lines)

    def _determine_color(self, metrics: Dict) -> str:
        """
        Determina cor do attachment baseado nas métricas.

        Returns:
            Hex color string
        """
        auc_prod = metrics.get('auc_production', 0)
        auc_test = metrics.get('auc_test_set', 0)
        auc_delta = auc_prod - auc_test if auc_test > 0 else 0

        roas = metrics.get('roas', 0)

        # Vermelho se AUC degradou muito ou ROAS ruim
        if auc_delta < -0.05 or (roas > 0 and roas < 1.5):
            return "#ff0000"  # Vermelho

        # Amarelo se AUC degradou um pouco ou ROAS médio
        if auc_delta < -0.02 or (roas > 0 and roas < 2.5):
            return "#ffaa00"  # Amarelo/Laranja

        # Verde se tudo ok
        return "#36a64f"  # Verde
