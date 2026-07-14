"""Leitura de CADASTROS (todos os leads, respondentes da pesquisa ou não) da
base do front do cliente — tabelas `Client` + `UTMTracking` (Railway).

Papel na arquitetura: isola a dependência do Railway atrás de UMA interface. O
consumidor (funil Google do relatório das 06:00) pede "cadastros google de
ontem" e recebe registros leves (`utm_source`/`utm_term`), sem ver o SQL nem
saber que a fonte é o Railway. Quando a consolidação do Cloud SQL virar feed
VIVO (hoje `analytics.leads` é lote e fica dias atrás), troca-se a implementação
aqui, em 1 lugar — o relatório não muda (padrão Repositório/Adaptador).

Por que existe (fonte da verdade): o `registros_ml` (ledger, Cloud SQL) é a
fonte de VOLUME de leads SCOREADOS = quem RESPONDEU a pesquisa. NÃO é a fonte de
"quantos leads chegaram" — todo cadastro nasce na `Client`, respondendo ou não.
Para google, respondentes ≈ 92% dos cadastros (varia 85–101% por dia), então
contar leads pelo ledger subestima ~8%. Quem quer "leads que o Google trouxe"
(o form submit, que é o que o Google Ads conta) lê os CADASTROS daqui.

NÃO usar `ledger_connection.py` para isto — aquele lê `registros_ml` e o próprio
docstring de lá proíbe usá-lo para `Client`/`UTMTracking`.
"""
from __future__ import annotations

import os
from collections import namedtuple
from typing import Iterable, List

# Registro leve: só o que o funil Google precisa — a fonte (pra rótulo/filtro) e
# o utm_term ValueTrack (do qual sai o campaign_id no split por variante).
CadastroRec = namedtuple("CadastroRec", ["utm_source", "utm_term"])


def open_railway_connection():
    """Abre uma `pg8000.native.Connection` no Railway (base do front do cliente:
    `Client`/`UTMTracking`). O chamador é dono da conexão (deve fechá-la).

    Raises:
        KeyError: se `RAILWAY_DB_HOST`/`RAILWAY_DB_PASSWORD` não estiverem no
            ambiente (produção já as tem no Cloud Run).
    """
    import pg8000.native

    return pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
        database=os.environ.get("RAILWAY_DB_NAME", "railway"),
        user=os.environ.get("RAILWAY_DB_USER", "postgres"),
        password=os.environ["RAILWAY_DB_PASSWORD"],
        timeout=30,
    )


def google_cadastro_records(
    conn,
    brt_start: str,
    brt_end: str,
    sources: Iterable[str],
) -> List[CadastroRec]:
    """Cadastros da `Client` cujo `UTMTracking.source` está em `sources`, criados
    na janela BRT `[brt_start, brt_end]` (ambos inclusivos, 'YYYY-MM-DD'),
    deduplicados por email (UTMTracking mais recente por `trackedAt`).

    A janela fecha por `(createdAt - 3h)::date` — o mesmo dia BRT de cadastro que
    o resto do relatório usa. 1 linha por email distinto = "todos os cadastros
    google", não só os que responderam a pesquisa.

    Args:
        conn: conexão pg8000 aberta no Railway (o chamador fecha).
        brt_start, brt_end: dias BRT inclusivos ('YYYY-MM-DD'). Iguais = 1 dia.
        sources: utm_source aceitos (comparados em lower), ex. ['google-ads'].

    Returns:
        Lista de `CadastroRec` (1 por email distinto), com `utm_source` e
        `utm_term` do UTM mais recente. Vazia se não houver — o chamador decide
        o fallback (nunca deve derrubar o relatório por isto).
    """
    src = [str(s).lower() for s in sources]
    if not src:
        return []
    rows = conn.run(
        'SELECT LOWER(TRIM(c.email)) AS email, LOWER(u.source) AS source, '
        'u.term AS term, u."trackedAt" AS tracked '
        'FROM "Client" c '
        'JOIN "UTMTracking" u ON LOWER(TRIM(u."clientEmail")) = LOWER(TRIM(c.email)) '
        'WHERE (c."createdAt" - INTERVAL \'3 hours\')::date >= :s '
        'AND (c."createdAt" - INTERVAL \'3 hours\')::date <= :e '
        'AND LOWER(u.source) = ANY(:src)',
        s=brt_start, e=brt_end, src=src,
    )
    # Dedup por email: fica o UTM mais recente (mesma regra do split Meta).
    latest = {}  # email -> (tracked, source, term)
    for email, source, term, tracked in rows:
        prev = latest.get(email)
        if prev is None or (tracked is not None and (prev[0] is None or tracked >= prev[0])):
            latest[email] = (tracked, source, term)
    return [CadastroRec(utm_source=v[1], utm_term=v[2]) for v in latest.values()]
