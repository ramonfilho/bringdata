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

# Identidade nas chamadas ao Cloud Run. Este gate falava com o serviço SEM
# credencial, o que só funcionava porque o serviço aceitava chamada anônima.
# Ver scripts/gcp_auth.py.
#
# O import aceita as DUAS formas de execução. O `deploy_capi.sh` invoca por CAMINHO
# (`python V2/api/../scripts/smoke_test_revision.py`), e nesse modo `scripts` não é
# pacote importável. Sem este fallback o gate morre com ModuleNotFoundError, que foi
# exatamente o que aconteceu no primeiro deploy depois desta mudança.
try:  # como módulo: python -m scripts.x, a partir de V2/
    from scripts.gcp_auth import instalar_auth_gcp  # noqa: E402
except ModuleNotFoundError:  # por caminho: python V2/scripts/x.py
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from gcp_auth import instalar_auth_gcp  # noqa: E402
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# =============================================================================
# Config padrão — sobrescrever via CLI se necessário
# =============================================================================

SERVICE_NAME = 'smart-ads-api'
REGION = 'us-central1'
PROJECT = 'smart-ads-451319'

# Critérios por estágio (T1-9 em PLANO_SAFEGUARD.md).
#
# `janela_horas` é a JANELA DE EVIDÊNCIA: quantas horas para trás o gate olha ao pedir o
# feature-report, o daily-check e a taxa de 5xx da revisão. Não é tempo mínimo de espera.
# Até 15/09/2026 a chave se chamava `min_hours_observed` e o estágio 100 tinha
# `min_days_observed: 7`, que nenhuma linha lia: o gate nunca esperou 24h nem 7 dias, só
# olhava 24h para trás. O nome novo diz o que o código faz. A espera entre degraus é a
# aprovação humana no environment do GitHub (canary-10, canary-50, production).
#
# Taxas (`min_capi_sent_rate`, `min_meta_acceptance_rate`) são FRAÇÕES (0.50 = 50%). O
# daily-check devolve porcentagem (66.6 = 66,6%); check_daily_report normaliza. Até 15/09
# a comparação era feita sem normalizar (66.6 < 0.90 é falso), então esses dois critérios
# nunca seguraram nada.
STAGE_CRITERIA = {
    10: {
        # Desde #274 o degrau 0 -> 10 no deploy.yml passa pelo smoke, não por este gate.
        # Fica para uso manual (--from 0 --to 10) e para o check logo depois do Gate C.
        'janela_horas': 1,
        'max_5xx_rate': 0.01,              # 1%
        'required_feature_report_status': ['OK', 'INFO'],  # WARNING bloqueia progressão
    },
    50: {
        'janela_horas': 24,
        'max_5xx_rate': 0.01,
        'required_feature_report_status': ['OK', 'INFO'],  # alinhado com PLANO_SAFEGUARD § "Como tráfego cresce após o deploy" (10→50: feature_report ∈ {OK, INFO})
        # Piso MEDIDO em 17/09/2026 (registros_ml, 90 dias, 90.361 leads, taxa por dia):
        # mínimo 4,0%, p10 53,5%, p25 69,2%, mediana 79,0%, p75 85,2%, máximo 92,7%. Os 90%
        # do plano de abril nunca aconteceram num dia sequer. O piso em 50% (p10) segura a
        # promoção só quando o serviço inteiro está mandando menos da metade dos leads para
        # a Meta, que é o retrato de um incidente (4 a 12/08: 4% a 35%; 8 a 11/09: 12% a
        # 37%). HOLD, não rollback: o critério é do serviço, não da revisão.
        'min_capi_sent_rate': 0.50,
        'min_meta_acceptance_rate': 0.85,
        'max_d10_divergence_pp': 10.0,
    },
    100: {
        'janela_horas': 24,
        'required_feature_report_status': ['OK'],
        'min_capi_sent_rate': 0.50,        # mesmo piso medido do estágio 50
        'max_5xx_rate': 0.01,
        'note': 'Main unificada aguarda DEV20 fechar (17/05+) para ROAS consolidado',
    },
}


def _fracao(v):
    """Taxa em fração (0-1). O daily-check manda porcentagem (66.6); 1.0 e abaixo já é fração."""
    if v is None:
        return None
    v = float(v)
    return v / 100.0 if v > 1.0 else v


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

# Resolução de URL (revisão canary + serviço) vem da fonte única cloud_run_urls.py
# — mesma lógica antes copiada em 3 scripts de deploy.
from cloud_run_urls import get_revision_url, get_service_url  # noqa: E402


# Último status HTTP visto por URL (200, 500, ...; None = não respondeu). Quem julga
# precisa distinguir "o canário respondeu 500" de "o canário não respondeu".
ULTIMO_HTTP: Dict[str, Optional[int]] = {}


def fetch_json(url: str, timeout: int = 180) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ULTIMO_HTTP[url] = resp.status
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        ULTIMO_HTTP[url] = e.code
        body = e.read().decode('utf-8', errors='replace')[:200] if hasattr(e, 'read') else ''
        print(f"  [gate] HTTP {e.code} em {url}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        ULTIMO_HTTP[url] = None
        print(f"  [gate] Erro em {url}: {e}", file=sys.stderr)
        return None


def diferencial(sinal: Dict[str, Any], base_viva: Optional[str], fetch=None) -> Optional[str]:
    """Defeito da revisão, não do serviço: o canário respondeu 5xx num endpoint que a
    revisão viva responde 200.

    Medido em 17/09/2026 (canário 01179-jux): o daily-check devolveu 500 por um caminho
    de arquivo errado na refatoração das rotas; a viva respondia 200. O gate tratou como
    "inacessível" (HOLD) e deixou 10% do tráfego na revisão quebrada. Timeout ou
    conexão recusada (http None) NÃO entram aqui: isso é o serviço, não a revisão.
    Devolve o motivo do ROLLBACK, ou None.
    """
    http = (sinal or {}).get('http')
    caminho = (sinal or {}).get('path')
    if not base_viva or not caminho or not isinstance(http, int) or http < 500:
        return None
    fetch = fetch or fetch_json
    if fetch(f"{base_viva}{caminho}") is None:
        return None
    return (f"[diferencial] canário HTTP {http} em {caminho}; a revisão viva responde 200: "
            f"defeito da revisão, não do serviço")


# Abaixo disto a taxa de 5xx não é julgada: 1 erro em 10 requisições é 10% e não é sinal.
MIN_REQUISICOES_5XX = 30


def get_5xx_rate(revision: str, project: str, hours: int) -> Dict[str, Any]:
    """Taxa de 5xx da revisão nos logs de requisição: {'rate', 'n_5xx', 'total'}.

    rate é None quando não houve requisição (ou o gcloud falhou). Até 15/09/2026 esta função
    devolvia só a taxa e NINGUÉM a chamava: max_5xx_rate estava nos critérios sem efeito.
    """
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
            return {'rate': None, 'n_5xx': 0, 'total': 0}
        return {'rate': n_5xx / total, 'n_5xx': n_5xx, 'total': total}
    except Exception as e:
        print(f"  [gate] erro calculando 5xx: {e}", file=sys.stderr)
        return {'rate': None, 'n_5xx': 0, 'total': 0}


# =============================================================================
# Checks por critério
# =============================================================================

def check_feature_report(base_url: str, revision: str, hours: int) -> Dict[str, Any]:
    url = f"{base_url}/monitoring/feature-report?hours={hours}&revision={revision}"
    print(f"  [gate] consultando {url}")
    report = fetch_json(url, timeout=120)
    if report is None:
        return {'ok': False, 'reason': 'feature-report inacessível', 'status': None,
                'http': ULTIMO_HTTP.get(url), 'path': url[len(base_url):]}

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
        return {'ok': False, 'reason': 'daily-check inacessível',
                'http': ULTIMO_HTTP.get(url), 'path': url[len(base_url):]}

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
        'capi_sent_rate': _fracao(capi_sent.get('send_rate')),
        'meta_acceptance_rate': _fracao(meta_resp.get('acceptance_rate')),
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
    diferenciais: Optional[List[str]] = None,
) -> GateResult:
    reasons = []
    verdict = 'PROMOTE'
    signals = {'feature_report': feat_signals, 'daily': daily_signals}

    # Canário 5xx onde a viva responde 200: é a revisão, e ela sai (ver `diferencial`).
    if diferenciais:
        verdict = 'ROLLBACK'
        reasons.extend(diferenciais)

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

    # 5xx da revisão (logs de requisição). Só com amostra: MIN_REQUISICOES_5XX.
    cinco = daily_signals.get('cinco_xx') or {}
    max_5xx = stage_criteria.get('max_5xx_rate')
    taxa_5xx = cinco.get('rate')
    if max_5xx and taxa_5xx is not None and int(cinco.get('total') or 0) >= MIN_REQUISICOES_5XX and taxa_5xx > max_5xx:
        verdict = 'ROLLBACK'
        reasons.append(f"[5xx] {cinco.get('n_5xx', 0)} de {cinco.get('total')} requisições ({taxa_5xx:.2%}) > {max_5xx:.2%}")

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

def base_viva_ou_none(args) -> Optional[str]:
    """URL do serviço (revisão viva), ou None se não der para obter."""
    try:
        return get_service_url(args.service, args.region, args.project)
    except Exception:
        return None


def main():
    instalar_auth_gcp()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--revision', required=True, help='Nome da revisão canary (ex: smart-ads-api-00NNN-xxx)')
    parser.add_argument('--from', dest='from_pct', type=int, required=True, choices=[0, 10, 50],
                        help='Tráfego atual da revisão (0, 10, ou 50)')
    parser.add_argument('--to', dest='to_pct', type=int, required=True, choices=[10, 50, 100],
                        help='Tráfego alvo (10, 50, ou 100)')
    # Sem default: o antigo apontava para uma revisão de meses atrás (00269), e
    # um gate que aponta rollback para revisão morta não é gate. Quem chama passa a viva.
    parser.add_argument('--rollback', required=True,
                        help='Revisão que serve 100% hoje (alvo de rollback)')
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
    hours = args.observation_hours or int(stage.get('janela_horas', 24))

    print(f"[gate] Progressão {args.from_pct}% → {args.to_pct}%")
    print(f"[gate] Revisão canary: {args.revision}")
    print(f"[gate] Janela de observação: {hours}h")
    print(f"[gate] Critérios do estágio: {json.dumps({k:v for k,v in stage.items() if k != 'note'}, indent=2)}")
    if stage.get('note'):
        print(f"[gate] NOTA: {stage['note']}")
    print()

    # [fix OOM de deploy] Os checks pesados (daily-check ~300s, feature-report)
    # rodam contra a revisão CANARY isolada — instâncias próprias (min-instance=1
    # pela tag), 0% de tráfego — em vez da revisão VIVA que serve produção +
    # scoring. Antes, base_url era o URL do serviço (roteia pra revisão de 100%):
    # a carga do gate co-locava com o scoring e derrubava a instância viva por
    # OOM a cada deploy. daily-check lê o ledger global (mesmo resultado em
    # qualquer revisão); feature-report já filtra por --revision. Fallback pro URL
    # do serviço só se a canary não tiver URL própria — não regride o antigo.
    try:
        base_url = get_revision_url(args.revision, args.region, args.project, args.service)
        print(f"[gate] Base URL (revisão canary isolada, não toca o scoring vivo): {base_url}")
    except Exception as e:
        print(f"[gate] canary '{args.revision}' sem URL própria ({e})", file=sys.stderr)
        print(f"[gate] fallback: URL do serviço (bate na revisão viva)", file=sys.stderr)
        try:
            base_url = get_service_url(args.service, args.region, args.project)
            print(f"[gate] Base URL do serviço: {base_url}")
        except Exception as e2:
            print(f"[gate] ERRO: não conseguiu obter URL — {e2}", file=sys.stderr)
            return 3
    print()

    feat = check_feature_report(base_url, args.revision, hours)
    print(f"  → feature_report: status={feat.get('status')}, batches={feat.get('total_batches', 0)}")
    print()

    daily = check_daily_report(base_url, hours)
    if daily.get('ok'):
        print(f"  → daily: capi_sent_rate={daily.get('capi_sent_rate')}, d10_div={daily.get('d10_divergence_pp', 0):.1f}pp, zero_decis={daily.get('decil_zero_events')}")
    daily['cinco_xx'] = get_5xx_rate(args.revision, args.project, hours)
    print(f"  → 5xx da revisão: {daily['cinco_xx']}")
    print()

    # Só faz sentido comparar quando o gate falou com a URL própria do canário.
    diferenciais = []
    if base_url != base_viva_ou_none(args):
        try:
            viva = get_service_url(args.service, args.region, args.project)
        except Exception as e:
            print(f"[gate] sem URL da viva para o diferencial ({e})", file=sys.stderr)
            viva = None
        diferenciais = [d for d in (diferencial(feat, viva), diferencial(daily, viva)) if d]

    result = decide(args.from_pct, args.to_pct, feat, daily, stage, diferenciais)

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
