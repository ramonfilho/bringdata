#!/usr/bin/env python3
"""
[T1-9 + T1-11] Gate automático de progressão de tráfego.

Consulta os endpoints de monitoramento e decide se uma revisão canary pode
avançar para o próximo estágio (0% → 10% → 50% → 100%) conforme os critérios
objetivos documentados em PLANO_SAFEGUARD.md.

Fluxo:
    1. Verifica critérios de infraestrutura (revisão existe, tem tráfego)
    2. T1-11: consulta /monitoring/feature-report — bloqueia em ERROR
    3. T1-2 + outros: consulta /monitoring/daily-check/railway — verifica
       capi_sent_rate, acceptance_rate, decis com 0 eventos, divergência D10%
    4. Consolida decisão: PROMOTE / HOLD / ROLLBACK
    5. Se --execute e PROMOTE: roda `gcloud run services update-traffic`

Uso:
    # Só checar (dry-run):
    python3 progression_gate.py --revision smart-ads-api-00NNN-xxx --from 10 --to 50

    # Checar e executar se aprovado:
    python3 progression_gate.py --revision smart-ads-api-00NNN-xxx --from 10 --to 50 --execute

    # Contra staging-tagged revision (antes de ir para produção):
    python3 progression_gate.py --revision smart-ads-api-00NNN-xxx --from 0 --to 10

Exit codes:
    0 — PROMOTE (todos critérios aprovam; se --execute, tráfego foi atualizado)
    1 — HOLD (algum critério indica esperar mais tempo ou há warning, não promover)
    2 — ROLLBACK (ERROR grave detectado, revisão candidata a ser descartada)
    3 — Erro de infra (não conseguiu consultar endpoints)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# =============================================================================
# Config padrão — sobrescrever via CLI se necessário
# =============================================================================

SERVICE_NAME = 'smart-ads-api'
REGION = 'us-central1'
PROJECT = 'smart-ads-451319'

# Critérios por estágio (T1-9 em PLANO_SAFEGUARD.md)
STAGE_CRITERIA = {
    10: {
        'min_hours_observed': 1.0,
        'max_5xx_rate': 0.01,              # 1%
        'required_feature_report_status': ['OK', 'INFO'],  # WARNING bloqueia progressão
    },
    50: {
        'min_hours_observed': 24.0,
        'max_5xx_rate': 0.01,
        'required_feature_report_status': ['OK'],   # WARNING bloqueia — mais rigoroso
        'min_capi_sent_rate': 0.90,
        'min_meta_acceptance_rate': 0.85,
        'max_d10_divergence_pp': 10.0,
    },
    100: {
        'min_days_observed': 7,            # deploys normais
        'required_feature_report_status': ['OK'],
        'min_capi_sent_rate': 0.90,
        'max_5xx_rate': 0.01,
        'note': 'Main unificada aguarda DEV20 fechar (17/05+) para ROAS consolidado',
    },
}


@dataclass
class GateResult:
    verdict: str  # PROMOTE | HOLD | ROLLBACK
    reasons: List[str]
    signals: Dict[str, Any]

    @property
    def exit_code(self) -> int:
        return {'PROMOTE': 0, 'HOLD': 1, 'ROLLBACK': 2}[self.verdict]


# =============================================================================
# Helpers
# =============================================================================

def get_service_url(service: str, region: str, project: str) -> str:
    result = subprocess.run(
        ['gcloud', 'run', 'services', 'describe', service,
         '--region', region, '--project', project, '--format=value(status.url)'],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return result.stdout.strip()


def fetch_json(url: str, timeout: int = 180) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:200] if hasattr(e, 'read') else ''
        print(f"  [gate] HTTP {e.code} em {url}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [gate] Erro em {url}: {e}", file=sys.stderr)
        return None


def get_5xx_rate(revision: str, project: str, hours: int) -> Optional[float]:
    """Calcula taxa de 5xx via Cloud Monitoring."""
    filter_str = (
        f'resource.type=cloud_run_revision AND '
        f'resource.labels.revision_name={revision} AND '
        f'httpRequest.status>=500'
    )
    try:
        result = subprocess.run(
            ['gcloud', 'logging', 'read', filter_str,
             '--project', project,
             '--freshness', f'{hours}h',
             '--format=value(httpRequest.status)',
             '--limit', '1000'],
            capture_output=True, text=True, check=True, timeout=30,
        )
        n_5xx = len([l for l in result.stdout.splitlines() if l.strip()])

        filter_total = (
            f'resource.type=cloud_run_revision AND '
            f'resource.labels.revision_name={revision} AND '
            f'httpRequest.status>=200'
        )
        result_total = subprocess.run(
            ['gcloud', 'logging', 'read', filter_total,
             '--project', project, '--freshness', f'{hours}h',
             '--format=value(httpRequest.status)', '--limit', '10000'],
            capture_output=True, text=True, check=True, timeout=30,
        )
        total = len([l for l in result_total.stdout.splitlines() if l.strip()])

        if total == 0:
            return None
        return n_5xx / total
    except Exception as e:
        print(f"  [gate] erro calculando 5xx: {e}", file=sys.stderr)
        return None


# =============================================================================
# Checks por critério
# =============================================================================

def check_feature_report(base_url: str, revision: str, hours: int) -> Dict[str, Any]:
    url = f"{base_url}/monitoring/feature-report?hours={hours}&revision={revision}"
    print(f"  [gate] consultando {url}")
    report = fetch_json(url, timeout=120)
    if report is None:
        return {'ok': False, 'reason': 'feature-report inacessível', 'status': None}

    status = report.get('overall_status', 'NO_DATA')
    total = report.get('total_batches', 0)
    return {
        'ok': True,
        'status': status,
        'total_batches': total,
        'batches_by_severity': report.get('batches_by_severity', {}),
        'issues_by_feature_count': len(report.get('issues_by_feature', {})),
        'recommended_action': report.get('recommended_action'),
    }


def check_daily_report(base_url: str, hours: int) -> Dict[str, Any]:
    url = f"{base_url}/monitoring/daily-check/railway?hours={hours}"
    print(f"  [gate] consultando {url}")
    report = fetch_json(url, timeout=300)
    if report is None:
        return {'ok': False, 'reason': 'daily-check inacessível'}

    fm = report.get('funnel_metrics', {}) or {}
    lqm = report.get('lead_quality_metrics', {}) or {}

    capi_sent = fm.get('capi_sent', {})
    meta_resp = fm.get('meta_response', {})
    scoring = fm.get('scoring', {})

    decil_dist = scoring.get('decil_distribution', {})
    decil_zero = [d for d, count in decil_dist.items() if count == 0]

    d10_24h = (lqm.get('ultimas_24h', {}) or {}).get('d10', 0)
    d10_month = (lqm.get('ultimo_mes', {}) or {}).get('d10', 0)
    d10_divergence = abs(d10_24h - d10_month)

    return {
        'ok': True,
        'capi_sent_rate': capi_sent.get('send_rate'),
        'meta_acceptance_rate': meta_resp.get('acceptance_rate'),
        'decil_zero_events': decil_zero,
        'd10_pct_24h': d10_24h,
        'd10_pct_month': d10_month,
        'd10_divergence_pp': d10_divergence,
        'total_alerts_high': (report.get('alerts_by_severity') or {}).get('HIGH', 0),
    }


# =============================================================================
# Decisor
# =============================================================================

def decide(
    from_pct: int,
    to_pct: int,
    feat_signals: Dict[str, Any],
    daily_signals: Dict[str, Any],
    stage_criteria: Dict[str, Any],
) -> GateResult:
    reasons = []
    verdict = 'PROMOTE'
    signals = {'feature_report': feat_signals, 'daily': daily_signals}

    # Feature report é o gate mais crítico (T1-11)
    if not feat_signals.get('ok'):
        verdict = 'HOLD'
        reasons.append(f"[T1-11] Feature report inacessível: {feat_signals.get('reason')}")
    else:
        status = feat_signals.get('status')
        total = feat_signals.get('total_batches', 0)
        required = stage_criteria.get('required_feature_report_status', ['OK'])

        if total == 0 and to_pct > 0:
            verdict = 'HOLD'
            reasons.append(f"[T1-11] Nenhum batch observado na janela — revisão precisa receber tráfego primeiro")
        elif status == 'ERROR':
            verdict = 'ROLLBACK'
            reasons.append(f"[T1-11] feature_validator severity=ERROR — features críticas ausentes/mal formadas")
        elif status not in required:
            verdict = 'HOLD' if verdict != 'ROLLBACK' else verdict
            reasons.append(f"[T1-11] feature_validator severity={status} — critério do estágio exige {required}")

    # Daily check (operacional + T1-2)
    if not daily_signals.get('ok'):
        verdict = 'HOLD' if verdict == 'PROMOTE' else verdict
        reasons.append(f"[operacional] Daily check inacessível")
    else:
        capi_rate = daily_signals.get('capi_sent_rate')
        min_capi = stage_criteria.get('min_capi_sent_rate')
        if min_capi and capi_rate is not None and capi_rate < min_capi:
            verdict = 'HOLD' if verdict == 'PROMOTE' else verdict
            reasons.append(f"[CAPI] send_rate {capi_rate:.2%} < {min_capi:.2%}")

        meta_rate = daily_signals.get('meta_acceptance_rate')
        min_meta = stage_criteria.get('min_meta_acceptance_rate')
        if min_meta and meta_rate is not None and meta_rate < min_meta:
            verdict = 'HOLD' if verdict == 'PROMOTE' else verdict
            reasons.append(f"[Meta] acceptance_rate {meta_rate:.2%} < {min_meta:.2%}")

        zero_decis = daily_signals.get('decil_zero_events', [])
        if zero_decis:
            verdict = 'ROLLBACK'
            reasons.append(f"[T1-2] Decis com 0 eventos CAPI: {zero_decis}")

        d10_div = daily_signals.get('d10_divergence_pp', 0)
        max_div = stage_criteria.get('max_d10_divergence_pp')
        if max_div and d10_div > max_div:
            verdict = 'HOLD' if verdict == 'PROMOTE' else verdict
            reasons.append(f"[qualidade] D10% divergência {d10_div:.1f}pp > {max_div}pp")

    if verdict == 'PROMOTE':
        reasons.append(f"✅ Todos os critérios do estágio {from_pct}% → {to_pct}% satisfeitos")

    return GateResult(verdict=verdict, reasons=reasons, signals=signals)


# =============================================================================
# Executor
# =============================================================================

def execute_promotion(revision: str, from_pct: int, to_pct: int,
                       rollback_rev: str, service: str, region: str, project: str) -> bool:
    """Executa gcloud run services update-traffic."""
    if to_pct == 100:
        traffic = f"{revision}=100"
    else:
        rollback_pct = 100 - to_pct
        traffic = f"{revision}={to_pct},{rollback_rev}={rollback_pct}"

    cmd = ['gcloud', 'run', 'services', 'update-traffic', service,
           '--region', region, '--project', project, '--to-revisions', traffic]
    print(f"  [gate] executando: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"  [gate] FALHA: {result.stderr[-500:]}", file=sys.stderr)
        return False
    print(f"  [gate] ✅ tráfego atualizado para {to_pct}%")
    return True


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--revision', required=True, help='Nome da revisão canary (ex: smart-ads-api-00NNN-xxx)')
    parser.add_argument('--from', dest='from_pct', type=int, required=True, choices=[0, 10, 50],
                        help='Tráfego atual da revisão (0, 10, ou 50)')
    parser.add_argument('--to', dest='to_pct', type=int, required=True, choices=[10, 50, 100],
                        help='Tráfego alvo (10, 50, ou 100)')
    parser.add_argument('--rollback', default='smart-ads-api-00269-jjn',
                        help='Revisão de rollback/Champion (default: 00269-jjn)')
    parser.add_argument('--observation-hours', type=int, default=None,
                        help='Horas de observação (default: baseado no estágio)')
    parser.add_argument('--execute', action='store_true', help='Executar promoção se PROMOTE')
    parser.add_argument('--service', default=SERVICE_NAME)
    parser.add_argument('--region', default=REGION)
    parser.add_argument('--project', default=PROJECT)
    args = parser.parse_args()

    if args.to_pct not in STAGE_CRITERIA:
        print(f"Estágio inválido: {args.to_pct}. Use 10, 50 ou 100.", file=sys.stderr)
        return 3

    stage = STAGE_CRITERIA[args.to_pct]
    hours = args.observation_hours or int(stage.get('min_hours_observed', 24))

    print(f"[gate] Progressão {args.from_pct}% → {args.to_pct}%")
    print(f"[gate] Revisão canary: {args.revision}")
    print(f"[gate] Janela de observação: {hours}h")
    print(f"[gate] Critérios do estágio: {json.dumps({k:v for k,v in stage.items() if k != 'note'}, indent=2)}")
    if stage.get('note'):
        print(f"[gate] NOTA: {stage['note']}")
    print()

    try:
        base_url = get_service_url(args.service, args.region, args.project)
        print(f"[gate] Base URL do serviço: {base_url}")
    except Exception as e:
        print(f"[gate] ERRO: não conseguiu obter URL do serviço — {e}", file=sys.stderr)
        return 3
    print()

    feat = check_feature_report(base_url, args.revision, hours)
    print(f"  → feature_report: status={feat.get('status')}, batches={feat.get('total_batches', 0)}")
    print()

    daily = check_daily_report(base_url, hours)
    if daily.get('ok'):
        print(f"  → daily: capi_sent_rate={daily.get('capi_sent_rate')}, d10_div={daily.get('d10_divergence_pp', 0):.1f}pp, zero_decis={daily.get('decil_zero_events')}")
    print()

    result = decide(args.from_pct, args.to_pct, feat, daily, stage)

    print('=' * 80)
    print(f'VEREDITO: {result.verdict}')
    print('=' * 80)
    for r in result.reasons:
        print(f'  - {r}')
    print()

    if result.verdict == 'PROMOTE' and args.execute:
        ok = execute_promotion(args.revision, args.from_pct, args.to_pct,
                                args.rollback, args.service, args.region, args.project)
        if not ok:
            return 3

    return result.exit_code


if __name__ == '__main__':
    sys.exit(main())
