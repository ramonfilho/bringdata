"""Leitura do selo do HotLeads (analytics.hotleads_seal) para uso como feature.

O selo é um rótulo binário devolvido pela Hotmart: `hot=1` significa "esta pessoa
já comprou ALGUM produto na Hotmart" (de qualquer produtor), não propensão. É um
sinal EXTERNO — a pesquisa do lançamento não pergunta nada equivalente.

Repositório fino (padrão dos demais readers de src/data): só isola o "de onde vem
o selo". Devolve `{email_normalizado: bool}`.

DIFERENÇA DELIBERADA em relação ao `campaign_labels_reader`: aqui NÃO há fallback
silencioso. Um rótulo de campanha ausente degrada pro classificador legado; um
selo ausente viraria uma coluna toda nula, e o treino comparativo mediria "sem
ganho" quando na verdade o dado nunca chegou. Isso é exatamente a falha silenciosa
que o CLAUDE.md proíbe em transform novo — então a função levanta.

Cobertura medida em 31/07/2026: ~95% do universo de treino, uniforme de dez/2024
a jul/2026 (sem buraco temporal que enviesasse coorte antiga contra recente).
"""
from __future__ import annotations

import logging
from typing import Dict

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

# Abaixo disto algo está errado na origem (tabela truncada, enriquecimento pela
# metade) e treinar em cima produziria uma comparação sem sentido.
_MIN_SELOS = 100_000


def read_hotleads_seals(conn=None) -> Dict[str, bool]:
    """Devolve `{email: hot}` de analytics.hotleads_seal.

    Args:
        conn: conexão analytics já aberta (opcional). Se None, abre/fecha uma.

    Returns:
        Dict email (minúsculo, sem espaço) → True se a pessoa já comprou na
        Hotmart, False caso contrário.

    Raises:
        RuntimeError: se a leitura falhar ou vier menos que `_MIN_SELOS` linhas.
            Fail-loud proposital — ver docstring do módulo.
    """
    own = conn is None
    try:
        conn = conn or open_analytics_connection()
        rows = conn.run(
            "SELECT email, hot FROM analytics.hotleads_seal "
            "WHERE email IS NOT NULL AND email <> ''"
        )
    except Exception as e:
        raise RuntimeError(
            f"[hotleads_seal_reader] leitura de analytics.hotleads_seal falhou: {e}. "
            "Sem o selo a feature vira coluna nula e o treino comparativo mente. "
            "Rode sem a flag da feature ou conserte o acesso ao banco."
        ) from e
    finally:
        if own and conn is not None:
            conn.close()

    selos = {str(r[0]).strip().lower(): bool(r[1]) for r in rows if r[0]}

    if len(selos) < _MIN_SELOS:
        raise RuntimeError(
            f"[hotleads_seal_reader] só {len(selos):,} selos em analytics.hotleads_seal "
            f"(esperado >= {_MIN_SELOS:,}). Enriquecimento incompleto ou tabela truncada — "
            "abortando em vez de treinar com feature pela metade."
        )

    n_hot = sum(selos.values())
    logger.info("[hotleads_seal_reader] %d selos lidos · %d quentes (%.1f%%)",
                len(selos), n_hot, n_hot / len(selos) * 100)
    return selos
