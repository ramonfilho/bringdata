"""Escrita do selo do HotLeads (analytics.hotleads_seal) — dono ÚNICO da tabela.

Irmão do `hotleads_seal_reader`, que só lê. Existe porque o selo tinha DOIS
escritores com chaves e políticas de conflito diferentes, e nenhum dono:

    lote histórico → analytics.hotleads_seal, por email     (alimenta o público)
    ciclo diário   → registros_ml.hotleads_*, por event_id  (dispara o evento)

Ninguém sincronizava os dois. Medido em 14/08/2026: a tabela do público estava
congelada em 31/07 com 323.134 linhas, enquanto o ciclo diário já tinha selado
19.872 emails que nunca chegaram lá. O público "COMPRADORES HOTMART" ficou duas
semanas sem receber ninguém novo, sem nada gritar — porque o evento, que é a
outra ponta, continuou saindo normalmente.

POLÍTICA DE CONFLITO, e ela é única de propósito: **o retrato mais novo vence**.
Era a intenção declarada no escritor antigo ("o selo é um retrato datado"), mas
o código sobrescrevia sem condição — o que só não dava problema porque aquele
caminho carimbava NOW() e era sempre o mais novo. O caminho do ledger carrega a
data real do selo, que pode ser anterior à que já está na tabela, então sem a
guarda um selo velho apagaria um novo.
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# Teto por chamada. Um webhook traz até 1.000 selos, mas nada impede alguém
# chamar com uma lista maior; sem limite, um dia alguém pede tudo e trava a
# tabela que o treino lê.
MAX_POR_CHAMADA = 5_000

# Miolo compartilhado pelos dois modos de alimentação. É aqui que a política de
# "mais novo vence" mora, num lugar só.
_ON_CONFLICT = """
    ON CONFLICT (email) DO UPDATE
      SET hot = EXCLUDED.hot,
          sealed_at = EXCLUDED.sealed_at,
          execution_id = EXCLUDED.execution_id
      WHERE EXCLUDED.sealed_at > analytics.hotleads_seal.sealed_at
"""


def upsert_seals(conn, seals: Iterable[Dict],
                 execution_id: Optional[str] = None) -> int:
    """Grava selos vindos de uma LISTA em memória (lote histórico).

    Cada item precisa de `email` e `hot`. `sealed_at` vira NOW() — é o retrato
    do momento em que a Hotmart respondeu.

    Returns:
        Quantos selos foram apresentados à tabela (não quantos mudaram: o
        `ON CONFLICT` pode descartar o que for mais velho que o de lá).
    """
    n = 0
    for s in seals:
        email = (s.get("email") or "").strip().lower()
        if not email:
            continue
        if n >= MAX_POR_CHAMADA:
            logger.warning("[hotleads_seal_writer] teto de %d selos por chamada "
                           "atingido — o excedente NÃO foi gravado", MAX_POR_CHAMADA)
            break
        conn.run(
            """
            INSERT INTO analytics.hotleads_seal (email, hot, sealed_at, execution_id)
            VALUES (:email, :hot, NOW(), :exec_id)
            """ + _ON_CONFLICT,
            email=email, hot=bool(s.get("hot")), exec_id=execution_id,
        )
        n += 1
    return n


def upsert_seals_from_ledger(conn, event_ids: List[str]) -> int:
    """Espelha no público os selos que o ciclo diário acabou de gravar no ledger.

    Uma instrução só, sem trazer email para o Python: `analytics.hotleads_seal` e
    `registros_ml` moram no MESMO banco (schemas diferentes), então dá para ler e
    escrever na mesma conexão e na mesma transação de quem chamou.

    `DISTINCT ON` resolve a pessoa que aparece em mais de um lead: vence o selo
    mais recente dela, coerente com a política da tabela.

    Args:
        conn: conexão do ledger (a MESMA do `store_seal`, de propósito).
        event_ids: os event_id que acabaram de receber selo.

    Returns:
        Quantas linhas foram apresentadas à tabela.
    """
    ids = [e for e in (event_ids or []) if e][:MAX_POR_CHAMADA]
    if not ids:
        return 0

    # pg8000 não expande lista em IN — um placeholder por item.
    params = {f"e{i}": eid for i, eid in enumerate(ids)}
    placeholders = ", ".join(f":{k}" for k in params)

    conn.run(
        f"""
        WITH mais_recente AS (
          SELECT DISTINCT ON (lower(trim(email)))
                 lower(trim(email)) AS email,
                 hotleads_hot       AS hot,
                 hotleads_scored_at AS sealed_at,
                 hotleads_execution_id AS execution_id
          FROM registros_ml
          WHERE event_id IN ({placeholders})
            AND hotleads_scored_at IS NOT NULL
            AND hotleads_hot IS NOT NULL
            AND email IS NOT NULL AND email <> ''
          ORDER BY lower(trim(email)), hotleads_scored_at DESC
        )
        INSERT INTO analytics.hotleads_seal (email, hot, sealed_at, execution_id)
        SELECT email, hot, sealed_at, execution_id FROM mais_recente
        {_ON_CONFLICT}
        """,
        **params,
    )
    return len(ids)
