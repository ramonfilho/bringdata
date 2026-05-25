"""Sumário de paridade treino × produção (T1-16) — alimenta o bloco
"🎯 Paridade treino × produção (24h)" do resumo diário do Slack.

A salvaguarda T1-16 em `src/core/feature_validator.py` é executada a cada
batch que o pipeline processa. Sempre que uma coluna one-hot fica com
taxa de zero acima do esperado pelo treino (mais de 2pp de afastamento),
ela emite um log textual `[T1-16] (observa, NÃO bloqueia) ...` listando
as features afetadas com seus pares `(obs vs exp)`.

Esses logs ficam no Cloud Logging e ninguém os lê rotineiramente. Este
módulo é o agregador: lê logs T1-16 das últimas 24h, faz parsing leve,
e entrega ao digest do Slack um sumário curto.

Conceito que cobre:
  - "O modelo está vendo na produção dados diferentes do que foi treinado
    a esperar?"
  - É diferente do `distribution_drift` do monitoring (que compara janela
    atual × baseline rolling 30d). Aqui a referência é fixa: a distribuição
    do TREINO do modelo, embutida em `feature_validator`.

Sem regras de negócio aqui — só agregação e formatação. Criado em
2026-05-25 (registro_erros_ml.md § V.5).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


WINDOW_HOURS = 24
TOP_FEATURES_LIMIT = 5

# Casa o conteúdo "Exemplos: FEATURE_A (obs=0.060 vs exp=0.223), FEATURE_B (obs=0.260 vs exp=0.899)"
# do log T1-16 WARNING. Captura todos os triples (feature, obs, exp) por linha.
_FEATURE_OBS_EXP_RE = re.compile(
    r"([A-Za-z_][\w]*) \(obs=([\d.]+) vs exp=([\d.]+)\)"
)


def compute_training_drift_summary(
    *,
    hours: int = WINDOW_HOURS,
    project: str = 'smart-ads-451319',
    service: str = 'smart-ads-api',
    revision: Optional[str] = None,
) -> Dict[str, Any]:
    """Sumariza warnings T1-16 das últimas N horas.

    Lê via Cloud Logging API (`google.cloud.logging`) — sem subprocess.

    Args:
        hours: janela em horas (default 24).
        project: projeto GCP.
        service: nome do Cloud Run service.
        revision: filtra só uma revisão se passado.

    Returns:
        Dict com:
          - `window_hours`: a janela usada
          - `batches_com_drift`: quantos batches dispararam T1-16
          - `total_observacoes`: soma de tuplas (feature, obs, exp) capturadas
          - `top_features`: lista [{'feature', 'obs_media', 'exp', 'delta_pp', 'count'}, ...]
            ordenada pelo `count` decrescente (top N)
          - `observacao`: texto curto explicando a semântica
          - `erro`: opcional, se a leitura do Cloud Logging falhar

    Quando não há logs T1-16 na janela, devolve as contagens em 0 — não
    é erro, é estado "sem drift detectado".
    """
    try:
        from google.cloud import logging as gcp_logging
    except ImportError:
        return {
            'window_hours': hours,
            'batches_com_drift': 0,
            'total_observacoes': 0,
            'top_features': [],
            'observacao': 'google-cloud-logging não disponível',
            'erro': 'ImportError',
        }

    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=hours)
    since_iso = since_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    filter_parts = [
        'resource.type="cloud_run_revision"',
        f'resource.labels.service_name="{service}"',
        # Captura só o WARNING legível que tem `(obs=... vs exp=...)`.
        # O ERROR companheiro tem formato diferente e os mesmos números —
        # contar os dois infla a contagem.
        'textPayload:"[T1-16] (observa"',
        f'timestamp>="{since_iso}"',
    ]
    if revision:
        filter_parts.append(f'resource.labels.revision_name="{revision}"')
    filter_str = ' AND '.join(filter_parts)

    try:
        log_client = gcp_logging.Client(project=project)
        entries = log_client.list_entries(
            filter_=filter_str,
            order_by=gcp_logging.DESCENDING,
            max_results=5000,
        )
        raw_lines = [e.payload for e in entries if isinstance(e.payload, str)]
    except Exception as e:
        logger.warning(f"[training_drift] Cloud Logging API falhou: {e}")
        return {
            'window_hours': hours,
            'batches_com_drift': 0,
            'total_observacoes': 0,
            'top_features': [],
            'observacao': 'falha ao consultar Cloud Logging',
            'erro': f'{type(e).__name__}: {str(e)[:200]}',
        }

    batches_com_drift = len(raw_lines)
    if batches_com_drift == 0:
        return {
            'window_hours': hours,
            'batches_com_drift': 0,
            'total_observacoes': 0,
            'top_features': [],
            'observacao': 'sem warnings T1-16 na janela — modelo recebendo dados consistentes com o treino',
        }

    # Acumula por feature: lista de (obs, exp) observados.
    obs_por_feature: Dict[str, List[tuple]] = defaultdict(list)
    for line in raw_lines:
        for match in _FEATURE_OBS_EXP_RE.finditer(line):
            feat, obs_s, exp_s = match.group(1), match.group(2), match.group(3)
            try:
                obs_por_feature[feat].append((float(obs_s), float(exp_s)))
            except ValueError:
                continue

    total_observacoes = sum(len(v) for v in obs_por_feature.values())

    # Top features pelo número de vezes que apareceram drifted.
    ranked = sorted(
        obs_por_feature.items(),
        key=lambda kv: len(kv[1]),
        reverse=True,
    )
    top_features = []
    for feat, pairs in ranked[:TOP_FEATURES_LIMIT]:
        obs_mean = sum(p[0] for p in pairs) / len(pairs)
        # `exp` é constante (vem do treino, fixo por feature) — pega o primeiro.
        exp_value = pairs[0][1]
        top_features.append({
            'feature': feat,
            'obs_media': round(obs_mean, 4),
            'exp': round(exp_value, 4),
            'delta_pp': round(100 * (obs_mean - exp_value), 1),
            'count': len(pairs),
        })

    return {
        'window_hours': hours,
        'batches_com_drift': batches_com_drift,
        'total_observacoes': total_observacoes,
        'top_features': top_features,
        'observacao': (
            'mix de tráfego em produção difere do que o modelo Champion viu no '
            'treino — não é bug de pipeline, é drift natural do dado'
        ),
    }
