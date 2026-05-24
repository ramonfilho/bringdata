"""Sumário operacional do consumer Pub/Sub — alimenta o bloco "📨 Pub/Sub 24h"
do resumo diário do Slack e a resposta JSON do `/monitoring/daily-check/railway`.

Mede 4 dimensões em janela rolling de 24h, lendo do `LeadRepository`:

  - Total de leads processados pelo consumer (qualquer status).
  - Quebra por status do envio (sucesso, erro, pulado por allowlist, pulado
    por dado faltando).
  - Distribuição por decil dos enviados com sucesso (D01–D10).
  - Top mensagens de erro com suas contagens.

Sem regras de negócio aqui — só agregação em cima do raw que o repositório
devolve. Criado em 2026-05-24 (Etapa 7 do refator do monitoramento).
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


# Janela canônica do bloco. Não é configurável por design — o bloco do
# digest sempre fala em "últimas 24h", então a fonte trava aí.
WINDOW_MINUTES = 24 * 60

# Quantas mensagens de erro mais frequentes incluir no top.
TOP_ERRORS_LIMIT = 5

# Status canônicos — usados pra garantir que TODOS apareçam no breakdown
# (zerados quando não houver casos), facilita renderização e payload schema.
_STATUS_CANONICOS = (
    'success',
    'error',
    'skipped_allowlist',
    'skipped_missing_data',
)

# Decis canônicos — D01 a D10 sempre presentes (zerados se não houver leads
# desse decil), simplifica a renderização do bloco.
_DECIS_CANONICOS = tuple(f'D{i:02d}' for i in range(1, 11))


def compute_pubsub_summary(repo) -> Dict[str, Any]:
    """Sumariza atividade do consumer Pub/Sub nas últimas 24h.

    Args:
        repo: `LeadRepository` (injetado pelo orchestrator).

    Returns:
        Dict com 4 chaves canônicas: `total`, `by_status`, `decil_distribution`,
        `top_errors`. Quando `repo` é None ou retorna lista vazia, devolve
        o esqueleto com zeros (não levanta) — comportamento backwards-compatible
        com renderizadores existentes.
    """
    skeleton = _empty_summary()
    if repo is None:
        return skeleton

    try:
        leads = repo.recent_leads(window_minutes=WINDOW_MINUTES)
    except Exception:
        return skeleton

    total = len(leads)
    if total == 0:
        return skeleton

    # Quebra por status — garante que todas as chaves canônicas apareçam.
    status_counter = Counter(l.status_envio for l in leads)
    by_status = {s: int(status_counter.get(s, 0)) for s in _STATUS_CANONICOS}

    # Distribuição por decil dos enviados com sucesso.
    decil_counter = Counter(
        l.decil for l in leads
        if l.status_envio == 'success' and l.decil is not None
    )
    decil_distribution = {
        d: int(decil_counter.get(int(d[1:]), 0)) for d in _DECIS_CANONICOS
    }

    # Top erros — agrupa mensagens iguais, ordena por contagem desc.
    top_errors = _top_error_messages(leads, TOP_ERRORS_LIMIT)

    return {
        'total': total,
        'by_status': by_status,
        'decil_distribution': decil_distribution,
        'top_errors': top_errors,
    }


# ─ helpers ────────────────────────────────────────────────────────────────

def _empty_summary() -> Dict[str, Any]:
    return {
        'total': 0,
        'by_status': {s: 0 for s in _STATUS_CANONICOS},
        'decil_distribution': {d: 0 for d in _DECIS_CANONICOS},
        'top_errors': [],
    }


def _top_error_messages(leads, limit: int) -> List[Dict[str, Any]]:
    """Conta as mensagens de erro mais frequentes. Mensagens vazias/None
    (inclusive só whitespace após strip) são ignoradas. Retorna lista de
    dicts `{'message': str, 'count': int}` em ordem decrescente.
    """
    errs: List[str] = []
    for l in leads:
        if l.status_envio != 'error' or not l.erro:
            continue
        msg = l.erro.strip()
        if not msg:
            continue
        errs.append(msg)
    if not errs:
        return []
    counter = Counter(errs)
    return [
        {'message': msg, 'count': int(n)}
        for msg, n in counter.most_common(limit)
    ]
