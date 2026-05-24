"""Monitor de qualidade CAPI — verifica saúde dos envios ao Meta.

Verifica:
- Taxa alta de leads pulados por dado faltando (`fbp`/`fbc`/`hasComputer`)
  entre os elegíveis Meta — substitui o antigo "missing rate de fbp/fbc"
  com vocabulário do ledger novo.
- Taxa alta de rejeição CAPI (`status_envio='error'`).
- Decis sem nenhum evento CAPI bem-sucedido em 24h — herdado do bug
  histórico em que o decil 9 ficou 2 meses invisível ao Meta.

Migrado para `LeadRepository` em 2026-05-24 (Etapa 4 do refator do
monitoramento). Lia direto da tabela morta `leads_capi` via ORM; agora
recebe um repositório por injeção.
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict

logger = logging.getLogger(__name__)


class CAPIQualityMonitor:
    """Saúde dos envios CAPI lendo via `LeadRepository`."""

    def __init__(self, repo, client_config=None):
        """
        Args:
            repo:          `LeadRepository` (injetado pelo orchestrator).
            client_config: ClientConfig opcional — thresholds.
        """
        from .config import THRESHOLDS
        self.repo = repo
        monitoring = client_config.monitoring if client_config else None
        self._thresholds = (
            monitoring.thresholds if monitoring and monitoring.thresholds else THRESHOLDS
        )

    def check(self) -> List[Dict]:
        """Executa todos os checks de qualidade CAPI."""
        if self.repo is None:
            return []

        alerts = []
        if self._thresholds['capi_quality']['enabled']:
            alerts.extend(self._check_missing_data_rate())
            alerts.extend(self._check_rejection_rate())
            alerts.extend(self._check_zero_decil_events())
        return alerts

    # ─ checks ─────────────────────────────────────────────────────────────

    def _check_missing_data_rate(self) -> List[Dict]:
        """% de leads Meta-elegíveis pulados por dado faltando (24h).

        Meta-elegível = qualquer lead que não foi pulado pela allowlist (i.e.,
        chegou a ser considerado pra envio). Sinal equivalente ao antigo
        "fbp/fbc missing rate alto".
        """
        threshold = self._thresholds['capi_quality']['missing_rate']
        lookback_hours = 24
        try:
            leads = self.repo.recent_leads(window_minutes=lookback_hours * 60)
        except Exception:
            return []

        eligible = [l for l in leads if l.status_envio != 'skipped_allowlist']
        if not eligible:
            return []

        missing = [l for l in eligible if l.status_envio == 'skipped_missing_data']
        rate = len(missing) / len(eligible)
        if rate <= threshold:
            return []

        severity = _severity_by_rate(rate, [0.75, 0.60])
        now = datetime.now(timezone.utc)
        return [{
            'type': 'capi_missing_data_high',
            'severity': severity,
            'category': 'capi_quality',
            'message': (
                f"{rate*100:.1f}% dos leads Meta-elegíveis pulados por dado "
                f"faltando (fbp/fbc/hasComputer) ({len(missing)}/{len(eligible)} "
                f"em {lookback_hours}h)"
            ),
            'details': {
                'eligible': len(eligible),
                'missing_count': len(missing),
                'rate': rate,
                'period_hours': lookback_hours,
            },
            'timestamp': now.isoformat(),
            'metric_value': rate,
            'threshold': threshold,
        }]

    def _check_rejection_rate(self) -> List[Dict]:
        """Taxa de erro entre envios tentados em 24h."""
        threshold = self._thresholds['capi_quality'].get('rejection_rate', 0.10)
        lookback_hours = 24
        try:
            leads = self.repo.recent_leads(window_minutes=lookback_hours * 60)
        except Exception:
            return []

        attempted = [l for l in leads if l.status_envio in ('success', 'error')]
        if not attempted:
            return []

        errors = [l for l in attempted if l.status_envio == 'error']
        rate = len(errors) / len(attempted)
        if rate <= threshold:
            return []

        severity = _severity_by_rate(rate, [0.25, 0.15])
        now = datetime.now(timezone.utc)
        return [{
            'type': 'capi_rejection_rate_high',
            'severity': severity,
            'category': 'capi_quality',
            'message': (
                f"Taxa de erro CAPI alta: {rate*100:.1f}% "
                f"({len(errors)}/{len(attempted)} em {lookback_hours}h)"
            ),
            'details': {
                'attempted': len(attempted),
                'errors': len(errors),
                'rate': rate,
                'period_hours': lookback_hours,
            },
            'timestamp': now.isoformat(),
            'metric_value': rate,
            'threshold': threshold,
        }]

    def _check_zero_decil_events(self) -> List[Dict]:
        """Decis D01–D10 sem nenhum CAPI bem-sucedido em 24h.

        Histórico: o decil 9 ficou 2 meses com zero eventos sem alerta nenhum
        (Meta cego pra esse decil). Esta verificação garante que se algum
        decil ficar invisível, dispara.

        Limiar de volume mínimo subido de 20 → 100 em 2026-05-24: campanhas do
        gestor de tráfego sobem em 25/05, antes disso o ledger só tem dados de
        QA/load-test. Sem volume real, a regra dispararia em falso por meses.
        """
        lookback_hours = self._thresholds['capi_quality'].get('zero_decil_lookback_hours', 24)
        min_leads = self._thresholds['capi_quality'].get('zero_decil_min_leads', 100)
        try:
            leads = self.repo.recent_leads(window_minutes=lookback_hours * 60)
        except Exception:
            return []

        sent = [l for l in leads if l.status_envio == 'success' and l.decil is not None]
        if len(sent) < min_leads:
            logger.debug(
                "[zero_decil] %d sucessos em %dh — abaixo do mínimo (%d), check ignorado",
                len(sent), lookback_hours, min_leads,
            )
            return []

        decil_counts = {d: 0 for d in range(1, 11)}
        for l in sent:
            if l.decil in decil_counts:
                decil_counts[l.decil] += 1

        zero_decils = [f'D{d:02d}' for d in range(1, 11) if decil_counts[d] == 0]
        if not zero_decils:
            return []

        now = datetime.now(timezone.utc)
        return [{
            'type': 'capi_zero_decil_events',
            'severity': 'HIGH',
            'category': 'capi_quality',
            'message': (
                f"Decis sem eventos CAPI nas últimas {lookback_hours}h: "
                f"{', '.join(zero_decils)} — possível bug silencioso "
                f"(histórico: D9 por 2 meses)"
            ),
            'details': {
                'zero_decils': zero_decils,
                'decil_counts': {f'D{d:02d}': c for d, c in decil_counts.items()},
                'total_success_events': len(sent),
                'period_hours': lookback_hours,
                'min_leads_threshold': min_leads,
            },
            'timestamp': now.isoformat(),
            'metric_value': len(zero_decils),
            'threshold': 0,
        }]


# ─ helpers ────────────────────────────────────────────────────────────────

def _severity_by_rate(rate: float, ladder: list[float]) -> str:
    """Severidade por taxa: [HIGH_cut, MEDIUM_cut]. Resto = LOW."""
    if rate >= ladder[0]:
        return 'HIGH'
    if rate >= ladder[1]:
        return 'MEDIUM'
    return 'LOW'
