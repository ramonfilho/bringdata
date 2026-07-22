"""Leitura da curadoria de rótulos de campanha (analytics.campaign_labels).

Fonte única da rotulagem manual de campanha por assinatura de tag → categoria
(Controle / Champion / Challenger / Lead / Excluir), curada em 2026-07-22.
Consumida pelo peso de controle do treino (`_compute_control_weights`), que
tokeniza cada `utm_campaign` com `validation.campaign_classifier.tag_signature`
e busca a categoria aqui.

Repositório fino (padrão dos demais readers de src/data): só isola o "de onde
vêm os rótulos". Devolve `{assinatura: categoria}`; vazio se a tabela não existe
ou está vazia → o chamador cai no classificador por substring legado.
"""
from __future__ import annotations

import logging
from typing import Dict

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)


def read_campaign_labels(client_id: str = "devclub", conn=None) -> Dict[str, str]:
    """Devolve `{tag_signature: categoria}` de analytics.campaign_labels.

    Args:
        client_id: cliente (default 'devclub').
        conn: conexão analytics já aberta (opcional). Se None, abre/fecha uma.

    Returns:
        Dict assinatura → categoria. Vazio se a tabela não existir ou não tiver
        linhas para o cliente (o chamador trata como "usar classificador legado").
    """
    own = conn is None
    try:
        conn = conn or open_analytics_connection()
        rows = conn.run(
            "SELECT tag_signature, categoria FROM analytics.campaign_labels "
            "WHERE client_id = :c",
            c=client_id,
        )
    except Exception as e:  # conexão/tabela ausente / erro de leitura → fallback legado
        logger.warning("[campaign_labels_reader] leitura falhou (%s) — "
                       "chamador usará classificador legado", e)
        return {}
    finally:
        if own and conn is not None:
            conn.close()

    labels = {r[0]: r[1] for r in rows}
    if not labels:
        logger.warning("[campaign_labels_reader] 0 rótulos (client_id=%s)", client_id)
    else:
        from collections import Counter
        dist = dict(Counter(labels.values()))
        logger.info("[campaign_labels_reader] %d assinaturas rotuladas (client_id=%s): %s",
                    len(labels), client_id, dist)
    return labels
