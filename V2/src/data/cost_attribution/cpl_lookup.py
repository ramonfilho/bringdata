"""Helper que combina `CplRepository` + `AdResolver` num único objeto de
consumo pelo scoring container.

O scoring container instancia um `CplLookup` no startup, populado por
snapshot do `RailwayCplAdapter`. O `InMemoryCplAdapter` resultante responde
lookups em microssegundos.

API exposta:
  - `lookup.cost_context_for(utm_campaign, utm_content) → LeadCostContext`
    Resolve `(campaign_id, ad_name)` → `adset_id` → `cpl_30d` com cascata
    de fallback (adset → campaign → global → missing).

`CplLookup.from_railway(conn, client_id)` é o construtor canônico — pega
um snapshot do Railway uma vez e devolve um `CplLookup` populado.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.data.cost_attribution.cpl_repository import CplRepository
from src.data.cost_attribution.adapters.railway import RailwayCplAdapter
from src.data.cost_attribution.adapters.in_memory import InMemoryCplAdapter

logger = logging.getLogger(__name__)


class CplLookup:
    """Composição CplRepository + utility de resolução."""

    def __init__(self, repo: CplRepository, client_id: str):
        self.repo = repo
        self.client_id = client_id

    @classmethod
    def from_railway(cls, railway_conn, client_id: str) -> "CplLookup":
        """Lê snapshot completo do Railway e devolve `CplLookup` com InMemory cache.

        Recomendado pra hot path do scoring (μs por lookup).

        Args:
            railway_conn: conexão `pg8000.native.Connection` aberta pro Railway.
            client_id: identificador do cliente — `cpl_adset` e `ad_to_adset_map`
                       são multi-tenant via PK composta com `client_id`.
        """
        railway = RailwayCplAdapter(railway_conn=railway_conn)
        cpl_records, ad_mappings = railway.snapshot_all(client_id)
        in_memory = InMemoryCplAdapter(cpl_records=cpl_records, ad_mappings=ad_mappings)
        logger.info(
            "[cpl_lookup] inicializado pro cliente '%s': %d CPLs, %d ad→adset",
            client_id, len(cpl_records), len(ad_mappings),
        )
        return cls(repo=in_memory, client_id=client_id)

    def cost_context_for(
        self,
        utm_campaign: Optional[str],
        utm_content: Optional[str],
    ):
        """Resolve `LeadCostContext` pra um lead. Delegação pra `resolve_cost_context`.

        Importação tardia pra evitar ciclo com `src.model.decile_strategy`.
        """
        from src.model.decile_strategy import resolve_cost_context
        return resolve_cost_context(
            cpl_repo=self.repo,
            client_id=self.client_id,
            utm_campaign=utm_campaign,
            utm_content=utm_content,
        )
