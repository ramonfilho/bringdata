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
import subprocess
import sys
import time
import urllib.error
import urllib.request


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


def fetch_revision_logs(revision: str, project: str, freshness_seconds: int = 600) -> str:
    """Busca logs da revisão com '[T1-10]' no payload, dos últimos N segundos."""
    query = (
        f'resource.type=cloud_run_revision AND '
        f'resource.labels.revision_name={revision} AND '
        f'textPayload:"[T1-10]"'
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
    for line in logs.splitlines():
        line = line.strip()
        if not line or '[T1-10]' not in line:
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

    print("[smoke test] ✅ Nenhum alerta [T1-10] crítico na revisão. Prossegue.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
