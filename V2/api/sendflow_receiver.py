"""
Receiver do Sendhook do SendFlow — feature "entrou no grupo de WhatsApp".

Camada anti-corrupção: traduz o payload do SendFlow (evento de membro adicionado ao
grupo) para o nosso formato interno e grava em `whatsapp_group_joins` (Railway).
Reusa a chave canônica única `core.utils.telefone_chave_grupo` (DDD + últimos 8) e
grava `joined_at` SEMPRE em UTC. Insert idempotente (ON CONFLICT).

NÃO consome o cliente live por lead — só recebe o push do Sendhook e persiste.
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from typing import List, Optional

from src.core.utils import telefone_chave_grupo


def _railway_conn():
    import pg8000.native as pg
    return pg.Connection(
        host=os.environ["RAILWAY_DB_HOST"], port=int(os.environ["RAILWAY_DB_PORT"]),
        database=os.environ["RAILWAY_DB_NAME"], user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"],
    )


def _to_utc(s: Optional[str]) -> datetime:
    """ISO8601 -> datetime tz-aware em UTC. Sem data utilizável -> now(UTC)."""
    if not s:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def parse_sendhook(body: dict, client_id: str = "devclub") -> List[dict]:
    """
    Traduz o payload do Sendhook -> linhas para `whatsapp_group_joins`.
    Só processa eventos de ENTRADA no grupo (members.added); ignora o resto.
    Aceita `data` como objeto único ou lista de membros. Telefones inválidos são pulados.
    """
    if not isinstance(body, dict):
        return []
    event = (body.get("event") or "").lower()
    if "added" not in event and "entrou" not in event:
        return []  # não é entrada no grupo (ex.: members.removed / outros)

    data = body.get("data", body)
    members = data if isinstance(data, list) else [data]
    grp_default = data if isinstance(data, dict) else {}

    rows: List[dict] = []
    for m in members:
        if not isinstance(m, dict):
            continue
        number = m.get("number") or m.get("phone") or m.get("telefone")
        phone = telefone_chave_grupo(number)
        if not phone:
            continue
        rows.append({
            "client_id": client_id,
            "phone_canonical": phone,
            "phone_raw": str(number) if number is not None else None,
            "group_id": m.get("groupId") or m.get("groupJid") or m.get("groupName"),
            "group_name": m.get("groupName"),
            "joined_at": _to_utc(m.get("createdAt") or grp_default.get("createdAt")),
            "source": "sendhook",
            "raw_payload": json.dumps(m, ensure_ascii=False),
        })
    return rows


def store_group_joins(rows: List[dict], conn=None) -> int:
    """Grava as linhas em whatsapp_group_joins (idempotente). Retorna nº inserido."""
    if not rows:
        return 0
    own = conn is None
    c = conn or _railway_conn()
    inserted = 0
    try:
        for r in rows:
            res = c.run(
                """INSERT INTO whatsapp_group_joins
                   (client_id, phone_canonical, phone_raw, group_id, group_name,
                    joined_at, source, raw_payload)
                   VALUES (:client_id,:phone_canonical,:phone_raw,:group_id,:group_name,
                           :joined_at,:source, CAST(:raw_payload AS jsonb))
                   ON CONFLICT (client_id, phone_canonical, group_id) DO NOTHING
                   RETURNING id""",
                **r,
            )
            if res:
                inserted += 1
    finally:
        if own:
            c.close()
    return inserted
