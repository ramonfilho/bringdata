#!/usr/bin/env python3
"""
[T1-10 / Gate] Smoke test contra uma revisão Cloud Run.

Objetivo: verificar que a pipeline de encoding da revisão recém-deployada
processa leads reais do Railway sem perder features críticas do modelo.

Fluxo:
1. Resolve a URL da revisão via `gcloud run revisions describe`
2. Chama /monitoring/daily-check/railway?hours=1 na URL da revisão
   (esse endpoint aciona apply_encoding sobre leads reais do Railway,
   acionando o check de cobertura de top features do T1-10)
3. Aguarda propagação dos logs
4. Consulta os logs da revisão via `gcloud logging read`, filtrando
   por textPayload contendo "[T1-10]"
5. Exit 0 se nenhum ERROR crítico encontrado, exit 1 se encontrar

Usos:
    # Após deploy:
    python3 scripts/smoke_test_revision.py smart-ads-api-00272-abc

    # Antes de progressão de tráfego (Gate A — redundância):
    python3 scripts/smoke_test_revision.py smart-ads-api-00272-abc --wait 30

Requer:
- gcloud autenticado com acesso ao projeto smart-ads-451319
- Revisão deve ter sido deployada (não precisa estar recebendo tráfego)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Issues do feature_validator que não devem bloquear progressão de tráfego.
# 'target' é a label do treino — não existe em produção por design (é predict,
# não fit). Outras features podem ser adicionadas via --ignore-feature.
DEFAULT_IGNORE_FEATURES = frozenset(['target'])


def get_revision_url(revision: str, region: str, project: str, service: str = 'smart-ads-api') -> str:
    """
    Obtém a URL tagged da revisão via `gcloud run services describe`.

    URLs tagged (necessárias para atingir revisão com 0% de tráfego) vivem
    em status.traffic[].url do SERVIÇO, não em status.url da revisão.
    Exemplo: https://canary-1713xxxx---smart-ads-api-gazrm25mda-uc.a.run.app
    """
    import json

    try:
        result = subprocess.run(
            ['gcloud', 'run', 'services', 'describe', service,
             '--region', region, '--project', project,
             '--format=json'],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gcloud falhou ao descrever serviço: {e.stderr.strip()}")

    try:
        svc = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON inválido de gcloud: {e}")

    traffic = svc.get('status', {}).get('traffic', [])
    if not traffic:
        raise RuntimeError(f"Serviço '{service}' sem tráfego configurado")

    for entry in traffic:
        if entry.get('revisionName') == revision and entry.get('url'):
            return entry['url']

    # Não achou com URL. Listar o que tem para diagnóstico.
    summary = [
        f"{e.get('revisionName', '?')} (tag={e.get('tag', '-')}, pct={e.get('percent', 0)})"
        for e in traffic
    ]
    raise RuntimeError(
        f"Revisão '{revision}' não tem URL tagged em status.traffic.\n"
        f"Deploy precisa usar --tag para gerar URL direta.\n"
        f"Tráfego atual: {summary}"
    )


def trigger_encoding_pipeline(url: str, timeout: int = 300) -> tuple[int, str]:
    """
    Chama /monitoring/daily-check/railway?hours=1 para acionar apply_encoding
    sobre leads reais recentes. Retorna (http_status, body_snippet).
    """
    endpoint = f"{url}/monitoring/daily-check/railway?hours=1"
    print(f"[smoke test] Acionando pipeline: {endpoint}")
    try:
        req = urllib.request.Request(endpoint, method='GET')
        resp = urllib.request.urlopen(req, timeout=timeout)
        body = resp.read(2000).decode('utf-8', errors='replace')
        return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read(2000).decode('utf-8', errors='replace') if hasattr(e, 'read') else str(e)
        return e.code, body
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, f"Erro de conexão: {e}"


def check_feature_report_gate(
    url: str,
    revision: str,
    ignore_features: frozenset = DEFAULT_IGNORE_FEATURES,
    timeout: int = 60,
) -> tuple[str, dict]:
    """
    [T1-11 Gate] Bate /monitoring/feature-report?hours=1 filtrando pela revisão
    e decide se a progressão de tráfego deve ser bloqueada.

    Bloqueia quando: overall_status == 'ERROR' AND existe issue em alguma feature
    fora de ignore_features. 'target' é ignorado por default (label do treino;
    não existe em produção por design).

    Returns:
        (decision, payload) onde decision ∈ {'pass', 'block', 'no_data', 'error'}
    """
    endpoint = f"{url}/monitoring/feature-report?hours=1&revision={revision}"
    try:
        req = urllib.request.Request(endpoint, method='GET')
        resp = urllib.request.urlopen(req, timeout=timeout)
        body = resp.read().decode('utf-8', errors='replace')
        payload = json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read(2000).decode('utf-8', errors='replace') if hasattr(e, 'read') else str(e)
        return 'error', {'http_status': e.code, 'body': body[:500]}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return 'error', {'reason': str(e)[:500]}

    if payload.get('total_batches', 0) == 0:
        return 'no_data', payload

    if payload.get('overall_status') != 'ERROR':
        return 'pass', payload

    blocking = {
        feat: info
        for feat, info in payload.get('issues_by_feature', {}).items()
        if feat not in ignore_features
    }
    if not blocking:
        return 'pass', payload

    return 'block', {**payload, 'blocking_issues': blocking}


def check_ab_variants_smoke(url: str, timeout: int = 120) -> tuple[str, dict]:
    """
    [T1-14 Gate] Bate /smoke/run-variants?limit=5&hours=24 e decide se a
    progressão de tráfego deve ser bloqueada.

    Cada variante (incluindo Champion default e shims) é forçada a rodar
    com seu predictor + encoding_overrides correspondentes. Bloqueia
    quando overall_status == 'fail' (qualquer variante quebrou).

    Returns:
        (decision, payload) onde decision ∈ {'pass', 'block', 'no_data', 'error'}
    """
    endpoint = f"{url}/smoke/run-variants?limit=5&hours=24"
    try:
        req = urllib.request.Request(endpoint, method='GET')
        resp = urllib.request.urlopen(req, timeout=timeout)
        body = resp.read().decode('utf-8', errors='replace')
        payload = json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read(2000).decode('utf-8', errors='replace') if hasattr(e, 'read') else str(e)
        return 'error', {'http_status': e.code, 'body': body[:500]}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return 'error', {'reason': str(e)[:500]}

    overall = payload.get('overall_status')
    if overall == 'no_data':
        return 'no_data', payload
    if overall == 'pass':
        return 'pass', payload
    return 'block', payload


def fetch_revision_logs(revision: str, project: str, freshness_seconds: int = 600) -> str:
    """Busca logs da revisão com '[T1-10]' OU '[STARTUP CHECK]' no payload, dos últimos N segundos."""
    query = (
        f'resource.type=cloud_run_revision AND '
        f'resource.labels.revision_name={revision} AND '
        f'(textPayload:"[T1-10]" OR textPayload:"[STARTUP CHECK]")'
    )
    try:
        result = subprocess.run(
            ['gcloud', 'logging', 'read', query,
             '--project', project,
             '--freshness', f'{freshness_seconds}s',
             '--format=value(severity,textPayload)',
             '--limit', '200'],
            capture_output=True, text=True, check=True, timeout=60,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"[smoke test] Aviso: gcloud logging read falhou: {e.stderr.strip()}")
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('revision', help='Nome da revisão Cloud Run (ex: smart-ads-api-00272-abc)')
    parser.add_argument('--region', default='us-central1')
    parser.add_argument('--project', default='smart-ads-451319')
    parser.add_argument('--wait', type=int, default=20,
                        help='Segundos para aguardar logs propagarem (default: 20)')
    parser.add_argument('--timeout-trigger', type=int, default=300,
                        help='Timeout da chamada de monitoring (default: 300s)')
    parser.add_argument('--ignore-feature', action='append', default=[],
                        help='Feature do feature-report a ignorar (repetível). '
                             "Default: 'target' (label do treino, não existe em prod).")
    parser.add_argument('--skip-feature-report-gate', action='store_true',
                        help='Pula o gate do /monitoring/feature-report (T1-11).')
    parser.add_argument('--skip-ab-variants-gate', action='store_true',
                        help='Pula o gate de variantes A/B (T1-14).')
    args = parser.parse_args()

    print(f"[smoke test] Revisão: {args.revision}")
    print(f"[smoke test] Projeto: {args.project}  região: {args.region}")

    try:
        url = get_revision_url(args.revision, args.region, args.project)
    except RuntimeError as e:
        print(f"[smoke test] ERRO: {e}", file=sys.stderr)
        return 2

    print(f"[smoke test] URL direta: {url}")

    status, body = trigger_encoding_pipeline(url, timeout=args.timeout_trigger)
    if status != 200:
        print(f"[smoke test] AVISO: HTTP {status} — body snippet:")
        print(f"            {body[:300]}")
        # Não falha aqui — queremos que o gate de logs dê a palavra final

    print(f"[smoke test] Aguardando {args.wait}s para logs propagarem...")
    time.sleep(args.wait)

    logs = fetch_revision_logs(args.revision, args.project)

    critical_lines = []
    warning_lines = []
    startup_check_fatals = []
    for line in logs.splitlines():
        line = line.strip()
        if not line:
            continue
        # [S1] Gate startup check — pixel/event config inválida
        if '[STARTUP CHECK]' in line and '❌ FATAL' in line:
            parts = line.split('\t', 1)
            payload = parts[1] if len(parts) > 1 else line
            startup_check_fatals.append(payload)
            continue
        if '[T1-10]' not in line:
            continue
        if 'Feature CRÍTICA' in line:
            # Formato esperado do gcloud: "SEVERITY\tPAYLOAD"
            parts = line.split('\t', 1)
            severity = parts[0].strip().upper() if len(parts) > 1 else 'UNKNOWN'
            payload = parts[1] if len(parts) > 1 else line
            if severity == 'ERROR':
                critical_lines.append(payload)
            elif severity == 'WARNING':
                warning_lines.append(payload)

    if startup_check_fatals:
        print()
        print("╔══════════════════════════════════════════════════════════════════╗")
        print("║  🚨 SMOKE TEST FALHOU — STARTUP CHECK CAPI (S1)                ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        for line in startup_check_fatals[:10]:
            print(f"  {line[:200]}")
        print("╚══════════════════════════════════════════════════════════════════╝")
        print()
        print("Ação: não progredir tráfego. Pixel ou token CAPI inválidos —")
        print("revisar configs/clients/{cliente}.yaml + active_models/{cliente}.yaml.")
        return 1

    if critical_lines:
        print()
        print("╔══════════════════════════════════════════════════════════════════╗")
        print("║  🚨 SMOKE TEST FALHOU — FEATURES CRÍTICAS AUSENTES (T1-10)     ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        for line in critical_lines[:10]:
            print(f"  {line[:200]}")
        print("╚══════════════════════════════════════════════════════════════════╝")
        print()
        print("Ação: não progredir tráfego. Investigar por que a feature sumiu do")
        print("encoding — provável divergência entre shape de treino e produção.")
        return 1

    if warning_lines:
        print(f"[smoke test] {len(warning_lines)} alerta(s) WARNING de T1-10 (importância < 5%):")
        for line in warning_lines[:5]:
            print(f"  {line[:200]}")
        print("[smoke test] Não bloqueante — features de importância baixa ausentes.")

    # [T1-11 Gate] feature-report agregado: bloqueia se ERROR em features de scoring
    if args.skip_feature_report_gate:
        print("[smoke test] ⚠️  --skip-feature-report-gate: pulando gate T1-11.")
    else:
        ignore = DEFAULT_IGNORE_FEATURES | frozenset(args.ignore_feature)
        print(f"[smoke test] [T1-11] Consultando /monitoring/feature-report?hours=1...")
        print(f"            Ignorando features: {sorted(ignore)}")
        decision, fr_payload = check_feature_report_gate(url, args.revision, ignore_features=ignore)

        if decision == 'block':
            print()
            print("╔══════════════════════════════════════════════════════════════════╗")
            print("║  🚨 SMOKE TEST FALHOU — FEATURE-REPORT EM ERROR (T1-11)        ║")
            print("╠══════════════════════════════════════════════════════════════════╣")
            print(f"  total_batches: {fr_payload.get('total_batches')}")
            print(f"  severities:    {fr_payload.get('batches_by_severity')}")
            print(f"  bloqueantes:")
            for feat, info in fr_payload.get('blocking_issues', {}).items():
                print(f"    {feat}: count={info['count']}  problems={info['problems']}")
            print("╚══════════════════════════════════════════════════════════════════╝")
            print()
            print("Ação: não progredir tráfego. Investigar issues acima — modelo está")
            print("scoreando com sinal incompleto (missing_column/wrong_dtype/etc).")
            return 1

        if decision == 'error':
            print(f"[smoke test] ⚠️  feature-report falhou: {fr_payload}")
            print("[smoke test] Não bloqueante (gate não conseguiu opinar) — verifique manualmente.")
        elif decision == 'no_data':
            print("[smoke test] ⚠️  feature-report sem batches na janela de 1h.")
            print("[smoke test] Não bloqueante — revisão pode não ter recebido tráfego ainda.")
        else:  # 'pass'
            print(f"[smoke test] ✅ feature-report OK "
                  f"(total_batches={fr_payload.get('total_batches')}, "
                  f"overall_status={fr_payload.get('overall_status')})")

    # [T1-14 Gate] /smoke/run-variants — exercita cada variante A/B explicitamente
    if args.skip_ab_variants_gate:
        print("[smoke test] ⚠️  --skip-ab-variants-gate: pulando gate T1-14.")
    else:
        print("[smoke test] [T1-14] Consultando /smoke/run-variants...")
        ab_decision, ab_payload = check_ab_variants_smoke(url)

        if ab_decision == 'block':
            print()
            print("╔══════════════════════════════════════════════════════════════════╗")
            print("║  🚨 SMOKE TEST FALHOU — VARIANTE A/B QUEBROU (T1-14)           ║")
            print("╠══════════════════════════════════════════════════════════════════╣")
            print(f"  overall_status: {ab_payload.get('overall_status')}")
            print(f"  variants_tested: {ab_payload.get('variants_tested')}")
            for r in ab_payload.get('results', []):
                if r.get('status') == 'fail':
                    print(f"    ✗ {r.get('variant')}: {r.get('errors') or r.get('validations')}")
                    if r.get('expected_run_id') != r.get('actual_run_id'):
                        print(f"      run_id esperado={r.get('expected_run_id')}  recebido={r.get('actual_run_id')}")
            print("╚══════════════════════════════════════════════════════════════════╝")
            print()
            print("Ação: não progredir tráfego. Variante A/B quebrou — provável bug de")
            print("encoding_overrides ausente, predictor inválido ou run_id divergente.")
            return 1

        if ab_decision == 'error':
            print(f"[smoke test] ⚠️  /smoke/run-variants falhou: {ab_payload}")
            print("[smoke test] Não bloqueante (gate não conseguiu opinar) — verifique manualmente.")
        elif ab_decision == 'no_data':
            print("[smoke test] ⚠️  /smoke/run-variants sem leads recentes para testar.")
            print(f"[smoke test] Não bloqueante — {ab_payload.get('reason', '')}")
        else:  # 'pass'
            n_variants = ab_payload.get('variants_tested', 0)
            print(f"[smoke test] ✅ A/B variants OK ({n_variants} variantes testadas, "
                  f"{ab_payload.get('leads_used')} leads)")

    print("[smoke test] ✅ Todos os gates passaram. Prossegue.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
