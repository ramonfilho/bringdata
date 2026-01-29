"""
Model Comparison - Retreino Mensal

Comparação entre modelo champion e challenger para decisão de deploy.

TODO Sprint 2:
    - Comparar métricas (AUC, lift, monotonia)
    - Calcular delta percentual
    - Aplicar regras de decisão
    - Gerar relatório de comparação

Status: NOT_IMPLEMENTED (Sprint 2)
"""

from typing import Dict, Literal


class ModelComparator:
    """
    Comparador de modelos champion vs challenger.

    TODO Sprint 2: Implementar
    """

    def __init__(self, config: dict):
        """Initialize comparator with config."""
        self.config = config
        self.auto_approve_threshold = config['comparison']['auto_approve_threshold']
        self.manual_approval_threshold = config['comparison']['manual_approval_threshold']
        self.min_monotonia = config['comparison']['min_monotonia']

    def compare(self, champion_metadata: Dict, challenger_metadata: Dict) -> Dict:
        """
        Compara champion vs challenger.

        Args:
            champion_metadata: Metadata do modelo atual em produção
            challenger_metadata: Metadata do modelo recém-treinado

        Returns:
            Dict com comparação:
            {
                'champion': {...},
                'challenger': {...},
                'auc_delta': 0.025,
                'auc_delta_pct': 3.5,
                'lift_delta': 0.5,
                'monotonia_delta': 2.0,
                'decision': 'AUTO_APPROVE',
                'reason': 'AUC improvement > 2%'
            }
        """
        raise NotImplementedError("Sprint 2")

    def decide_deployment(
        self,
        comparison: Dict
    ) -> Literal['AUTO_APPROVE', 'HUMAN_APPROVAL', 'KEEP_CHAMPION', 'REJECT']:
        """
        Decide se faz deploy baseado nas métricas.

        Regras:
            - Monotonia < 80%: REJECT
            - AUC delta >= 2.0%: AUTO_APPROVE
            - AUC delta 0.5% - 2.0%: HUMAN_APPROVAL
            - AUC delta < 0.5%: KEEP_CHAMPION

        Returns:
            Decisão de deploy
        """
        raise NotImplementedError("Sprint 2")

    def _calculate_metrics_delta(self, champion: Dict, challenger: Dict) -> Dict:
        """TODO: Calcular delta de métricas."""
        raise NotImplementedError("Sprint 2")

    def _format_comparison_report(self, comparison: Dict) -> str:
        """TODO: Formatar relatório para Slack/Excel."""
        raise NotImplementedError("Sprint 2")
