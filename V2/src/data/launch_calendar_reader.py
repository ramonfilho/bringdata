"""launch_calendar_reader.py — leitura do calendário de LFs de analytics.launch_calendar.

Repositório fino (padrão dos demais readers de src/data): isola o "de onde vêm as
datas de lançamento". Devolve `{lf_name: entry}` no MESMO shape que o yaml/
`core.launches.load_launches()` — a coluna `entry` (jsonb) guarda o dict completo
do LF (datas + curadoria).

Vazio (`{}`) se a tabela não existe, está vazia, ou a conexão falha → quem chama
(`core.launches.load_launches`) cai no `configs/launches.yaml` (fallback). É o
mesmo contrato de degradação do campaign_labels_reader: nunca levanta, nunca
inventa data.
"""
from __future__ import annotations

import json
import logging
from typing import Dict

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)


def read_calendar_from_table(client_id: str = "devclub", conn=None) -> Dict[str, dict]:
    """Devolve `{lf_name: entry}` de analytics.launch_calendar (shape do yaml).

    Args:
        client_id: cliente (default 'devclub').
        conn: conexão analytics já aberta (opcional). Se None, abre/fecha uma.

    Returns:
        Dict lf_name → entry (dict com cap_start/cap_end/vendas_*/curadoria).
        Vazio se a tabela não existir/estiver vazia ou a leitura falhar — o
        chamador trata como "usar o yaml".
    """
    own = conn is None
    try:
        conn = conn or open_analytics_connection()
        rows = conn.run(
            "SELECT lf_name, entry FROM launch_calendar "
            "WHERE client_id = :c ORDER BY lf_name",
            c=client_id,
        )
    except Exception as e:  # tabela ausente / conexão / erro de leitura → fallback yaml
        logger.warning("[launch_calendar_reader] leitura falhou (%s) — "
                       "chamador usará configs/launches.yaml", e)
        return {}
    finally:
        if own and conn is not None:
            conn.close()

    out: Dict[str, dict] = {}
    for lf_name, entry in rows:
        # pg8000 costuma devolver jsonb já parseado (dict); tolera str por robustez.
        out[lf_name] = entry if isinstance(entry, dict) else json.loads(entry)
    if not out:
        logger.warning("[launch_calendar_reader] 0 LFs (client_id=%s) — fallback yaml", client_id)
    else:
        logger.info("[launch_calendar_reader] %d LFs lidos da tabela (client_id=%s)",
                    len(out), client_id)
    return out
