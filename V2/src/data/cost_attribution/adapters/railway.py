"""Adaptador que lê custo por adset das tabelas `cpl_adset` e
`ad_to_adset_map` no Railway.

Fonte de verdade do lookup. Refresh job (Bloco B/3) escreve aqui 1×/dia;
scoring container lê uma vez no startup pra popular o `InMemoryCplAdapter`,
e scripts ad-hoc consultam direto pra debug/auditoria.

Schema físico em `scripts/create_cpl_tables.py`. Este módulo é a tradução
entre o schema físico (NUMERIC/DATE/TIMESTAMP do PostgreSQL) e o formato
interno (`CplRecord`, `AdMapping`).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..cpl_record import AdMapping, CplRecord

logger = logging.getLogger(__name__)


class RailwayCplAdapter:
    """Implementa `CplRepository` lendo das tabelas Railway.

    Cada método é uma query única — esta classe não cacheia. Quem precisa
    de cache (scoring container) recebe um `InMemoryCplAdapter` populado
    a partir desta classe.
    """

    # Colunas selecionadas em ordem fixa — `_row_to_cpl_record` depende dessa ordem.
    _CPL_COLUMNS = (
        'client_id', 'adset_id',
        'cpl_30d', 'n_leads_30d', 'spend_30d',
        'campaign_id',
        'window_start', 'window_end',
        'updated_at',
    )

    # Idem pra ad_to_adset_map.
    _MAP_COLUMNS = (
        'client_id', 'campaign_id', 'ad_name',
        'adset_id', 'updated_at',
    )

    def __init__(self, railway_conn):
        """`railway_conn`: conexão `pg8000.native.Connection` aberta pro Railway."""
        self.conn = railway_conn

    # ─ interface pública ──────────────────────────────────────────────────

    def cpl_by_adset(self, client_id: str, adset_id: str) -> Optional[CplRecord]:
        sql = (
            f"SELECT {', '.join(self._CPL_COLUMNS)} "
            f"FROM cpl_adset "
            f"WHERE client_id = :cid AND adset_id = :aid LIMIT 1"
        )
        rows = self.conn.run(sql, cid=client_id, aid=adset_id)
        return self._row_to_cpl_record(rows[0]) if rows else None

    def cpl_campaign_average(
        self, client_id: str, campaign_id: str,
    ) -> Optional[float]:
        """Média ponderada de CPL dos adsets ativos da mesma campanha.

        Ponderação por `n_leads_30d` — um adset com 2 leads não puxa o número
        pra cima ou pra baixo de um adset com 2 mil leads.
        """
        sql = (
            "SELECT SUM(spend_30d)::float / NULLIF(SUM(n_leads_30d), 0)::float "
            "FROM cpl_adset "
            "WHERE client_id = :cid AND campaign_id = :camp"
        )
        rows = self.conn.run(sql, cid=client_id, camp=campaign_id)
        if not rows or rows[0][0] is None:
            return None
        return float(rows[0][0])

    def cpl_global_average(self, client_id: str) -> Optional[float]:
        """Média ponderada por leads de todo o cliente — último fallback."""
        sql = (
            "SELECT SUM(spend_30d)::float / NULLIF(SUM(n_leads_30d), 0)::float "
            "FROM cpl_adset "
            "WHERE client_id = :cid"
        )
        rows = self.conn.run(sql, cid=client_id)
        if not rows or rows[0][0] is None:
            return None
        return float(rows[0][0])

    def resolve_adset(
        self, client_id: str, campaign_id: str, ad_name: str,
    ) -> Optional[AdMapping]:
        sql = (
            f"SELECT {', '.join(self._MAP_COLUMNS)} "
            f"FROM ad_to_adset_map "
            f"WHERE client_id = :cid AND campaign_id = :camp AND ad_name = :name "
            f"LIMIT 1"
        )
        rows = self.conn.run(sql, cid=client_id, camp=campaign_id, name=ad_name)
        return self._row_to_ad_mapping(rows[0]) if rows else None

    # ─ snapshot pro InMemoryCplAdapter ────────────────────────────────────

    def snapshot_all(self, client_id: str) -> tuple[list[CplRecord], list[AdMapping]]:
        """Devolve TODOS os CPLs e mapeamentos do cliente, em duas listas.

        Usado pelo startup do scoring container pra popular o cache em
        memória. Ordem de magnitude esperada: ~1k linhas em `cpl_adset` e
        ~900 em `ad_to_adset_map` (medido no snapshot 120d em 2026-06-07).
        """
        cpl_sql = (
            f"SELECT {', '.join(self._CPL_COLUMNS)} "
            f"FROM cpl_adset WHERE client_id = :cid"
        )
        map_sql = (
            f"SELECT {', '.join(self._MAP_COLUMNS)} "
            f"FROM ad_to_adset_map WHERE client_id = :cid"
        )
        cpl_rows = self.conn.run(cpl_sql, cid=client_id)
        map_rows = self.conn.run(map_sql, cid=client_id)
        records = [self._row_to_cpl_record(r) for r in cpl_rows]
        mappings = [self._row_to_ad_mapping(r) for r in map_rows]
        logger.info(
            "[railway_cpl_adapter] snapshot %s: %d CPLs, %d mapeamentos ad→adset",
            client_id, len(records), len(mappings),
        )
        return records, mappings

    # ─ interno ────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_cpl_record(row: Any) -> CplRecord:
        (client_id, adset_id,
         cpl_30d, n_leads_30d, spend_30d,
         campaign_id,
         window_start, window_end,
         updated_at) = row
        return CplRecord(
            client_id=client_id,
            adset_id=adset_id,
            cpl_30d=float(cpl_30d),
            n_leads_30d=int(n_leads_30d),
            spend_30d=float(spend_30d),
            campaign_id=campaign_id,
            window_start=window_start,
            window_end=window_end,
            updated_at=updated_at,
        )

    @staticmethod
    def _row_to_ad_mapping(row: Any) -> AdMapping:
        client_id, campaign_id, ad_name, adset_id, updated_at = row
        return AdMapping(
            client_id=client_id,
            campaign_id=campaign_id,
            ad_name=ad_name,
            adset_id=adset_id,
            updated_at=updated_at,
        )
