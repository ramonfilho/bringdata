#!/usr/bin/env python3
"""Resolução de URLs de revisões/serviço Cloud Run — FONTE ÚNICA.

Antes desta consolidação, a mesma lógica de "descrever o serviço e achar a URL
certa" vivia copiada em 3 scripts de deploy (progression_gate.py,
test_revision_equivalence.py, smoke_test_revision.py), com pequenas divergências
de robustez (só uma tinha o fallback pro URL do serviço quando a revisão está a
100% sem tag). Copiar de novo seria uma quarta divergência silenciosa.

Consumidores:
    - scripts/progression_gate.py       (get_revision_url + get_service_url)
    - scripts/test_revision_equivalence.py (get_revision_url + get_prod_revision)
    - scripts/smoke_test_revision.py    (get_revision_url)

Import: os scripts rodam como `python3 V2/scripts/<x>.py`, então o diretório
`scripts/` fica em sys.path[0] e `from cloud_run_urls import ...` resolve o
módulo irmão.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict


DEFAULT_SERVICE = 'smart-ads-api'


def describe_service(service: str, region: str, project: str,
                     timeout: int = 30) -> Dict[str, Any]:
    """Descreve o serviço Cloud Run e devolve o JSON parseado.

    Ponto único onde o `gcloud run services describe` é invocado — todas as
    resoluções de URL derivam deste dict.
    """
    res = subprocess.run(
        ['gcloud', 'run', 'services', 'describe', service,
         '--region', region, '--project', project, '--format=json'],
        capture_output=True, text=True, check=True, timeout=timeout,
    )
    return json.loads(res.stdout)


def get_service_url(service: str, region: str, project: str) -> str:
    """URL principal do serviço — roteia pra quem estiver servindo tráfego (100%).

    Assinatura preservada do progression_gate.py original (service primeiro).
    """
    return describe_service(service, region, project).get('status', {}).get('url', '')


def get_revision_url(revision: str, region: str, project: str,
                     service: str = DEFAULT_SERVICE) -> str:
    """URL pra chamar uma revisão DIRETAMENTE (instâncias próprias da revisão).

    Caminho 1: a revisão tem tag → devolve a URL prefixada com a tag
    (ex.: ``https://canary-1713xxxx---<svc>.run.app``). É o caminho de uma
    revisão canary (0% de tráfego, mas com min-instance=1 pela tag).

    Caminho 2 (fallback p/ a revisão que está a 100%): se a revisão alvo serve
    100% de tráfego e não tem tag, devolve a URL principal do serviço — que por
    definição roteia pra quem está a 100%. Cobre o estado natural pós-promoção
    manual (tag ``prod`` não fica necessariamente na revisão de 100%).

    Levanta RuntimeError se a revisão não tem tag nem serve 100% (sem URL
    acessível).
    """
    svc = describe_service(service, region, project)
    status = svc.get('status', {})
    traffic = status.get('traffic', [])
    main_url = status.get('url') or svc.get('status', {}).get('address', {}).get('url')

    for entry in traffic:
        if entry.get('revisionName') != revision:
            continue
        # Caminho 1: tag presente → URL tagged
        if entry.get('url'):
            return entry['url']
        # Caminho 2: revisão de 100% sem tag → URL principal do serviço
        if entry.get('percent') == 100 and main_url:
            return main_url

    summary = [f"{e.get('revisionName')} (tag={e.get('tag', '-')}, pct={e.get('percent', 0)})"
               for e in traffic]
    raise RuntimeError(
        f"Revisão '{revision}' sem URL acessível "
        f"(sem tag e sem 100% de tráfego).\nTráfego atual: {summary}"
    )


def get_prod_revision(region: str, project: str,
                      service: str = DEFAULT_SERVICE) -> str:
    """Retorna a revisão com 100% de tráfego (rolling baseline)."""
    svc = describe_service(service, region, project)
    traffic = svc.get('status', {}).get('traffic', [])
    candidates = [e for e in traffic if e.get('percent') == 100]
    if len(candidates) == 1:
        return candidates[0]['revisionName']
    raise RuntimeError(f"Não consegui identificar revisão 100%. Candidatos: {candidates}")
