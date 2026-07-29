"""Materialização da referência rolante → analytics.reference_rolling.

Uma linha por (client_id, window_end, source). A referência ROLANTE substitui a
barra congelada "Top5 ROAS": o job semanal calcula e faz upsert; os relatórios só
LÊEM (via reference_reader). Guarda a conversão de referência (jsonb) e a curva do
calibrador (jsonb) — o leitor reconstrói a conversão esperada sem sklearn.

Idempotente `ON CONFLICT (client_id, window_end, source) DO UPDATE`: re-rodar o
mesmo window_end SOBRESCREVE. Reversível: `DELETE WHERE source='rolling'` (ou DROP).
Espelha launch_calendar_store / ad_spend_store. Escrita SEMPRE no nosso Cloud SQL.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# DDL idempotente — o job cria a tabela sozinho no 1º run.
# audience_profile é NULLABLE: o perfil de comprador (Fase 1) pode faltar/vir fino
# sem invalidar a conversão/calibração da mesma janela.
_DDL = """
CREATE TABLE IF NOT EXISTS reference_rolling (
    client_id       VARCHAR(64)  NOT NULL DEFAULT 'devclub',
    window_end      DATE         NOT NULL,
    window_start    DATE         NOT NULL,
    as_of           DATE         NOT NULL,
    ruler_run_id    VARCHAR(64)  NOT NULL,
    source          VARCHAR(32)  NOT NULL DEFAULT 'rolling',
    n_leads         INTEGER      NOT NULL,
    conversion      JSONB        NOT NULL,
    calibration     JSONB        NOT NULL,
    audience_profile JSONB,
    generated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, window_end, source)
)
"""

# Adição idempotente da coluna em tabelas já criadas na Fase 0 (antes da Fase 1).
_MIGRATE_AUDIENCE = (
    "ALTER TABLE reference_rolling ADD COLUMN IF NOT EXISTS audience_profile JSONB"
)


def ensure_reference_table(conn) -> None:
    """Cria analytics.reference_rolling se não existir e garante audience_profile
    (idempotente — cobre a tabela materializada na Fase 0 sem a coluna)."""
    conn.run(_DDL)
    conn.run(_MIGRATE_AUDIENCE)


def upsert_reference(
    conn,
    *,
    client_id: str,
    window_start: str,
    window_end: str,
    as_of: str,
    ruler_run_id: str,
    n_leads: int,
    conversion: dict,
    calibration: dict,
    audience_profile: dict = None,
    source: str = "rolling",
) -> None:
    """Grava/atualiza a referência de uma janela (upsert idempotente por window_end).

    `audience_profile` (perfil de comprador, Fase 1) é opcional → grava NULL se None.
    """
    ensure_reference_table(conn)
    sql = (
        "INSERT INTO reference_rolling "
        "(client_id, window_end, window_start, as_of, ruler_run_id, source, n_leads, "
        " conversion, calibration, audience_profile) "
        "VALUES (:client_id, CAST(:window_end AS date), CAST(:window_start AS date), "
        "        CAST(:as_of AS date), :ruler_run_id, :source, :n_leads, "
        "        CAST(:conversion AS jsonb), CAST(:calibration AS jsonb), "
        "        CAST(:audience_profile AS jsonb)) "
        "ON CONFLICT (client_id, window_end, source) DO UPDATE SET "
        "  window_start = EXCLUDED.window_start, as_of = EXCLUDED.as_of, "
        "  ruler_run_id = EXCLUDED.ruler_run_id, n_leads = EXCLUDED.n_leads, "
        "  conversion = EXCLUDED.conversion, calibration = EXCLUDED.calibration, "
        "  audience_profile = EXCLUDED.audience_profile, "
        "  generated_at = now()"
    )
    conn.run(
        sql,
        client_id=client_id, window_end=window_end, window_start=window_start,
        as_of=as_of, ruler_run_id=ruler_run_id or "", source=source, n_leads=int(n_leads),
        conversion=json.dumps(conversion, ensure_ascii=False, sort_keys=True),
        calibration=json.dumps(calibration, ensure_ascii=False, sort_keys=True),
        audience_profile=(json.dumps(audience_profile, ensure_ascii=False, sort_keys=True)
                          if audience_profile is not None else None),
    )
    logger.info("[reference_store] upsert reference_rolling window_end=%s source=%s n=%d",
                window_end, source, n_leads)
