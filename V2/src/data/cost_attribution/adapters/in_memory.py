"""Adaptador em memória — cache pro hot path do scoring.

Recebe um snapshot completo do `RailwayCplAdapter` no startup do container
de scoring. Responde lookups por dict em microssegundos, sem nenhuma ida
ao banco quando o lead chega.

TTL implícito: o snapshot é recarregado quando o container reinicia
(novo deploy, Cloud Run autoscaler). O job de refresh diário roda 1×/dia,
então leads que chegam até ~24h depois do último refresh veem dados
consistentes. Drift maior que isso só acontece em janelas raras (problemas
no refresh + container vivo por muito tempo); a observabilidade do Bloco E
detecta via coluna `updated_at` de cada `CplRecord` carregado.

Idêntico em comportamento ao `RailwayCplAdapter` na interface — diferença
é só a fonte (dict vs query). Quem chama recebe `CplRepository` e não
distingue.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..cpl_record import AdMapping, CplRecord

logger = logging.getLogger(__name__)


class InMemoryCplAdapter:
    """Implementa `CplRepository` a partir de snapshot pré-carregado.

    Os dois fallbacks (`cpl_campaign_average`, `cpl_global_average`) são
    pré-calculados na construção e cacheados — não recomputam a cada chamada.
    Custo de memória desprezível (~50KB pra ~1k linhas).
    """

    def __init__(
        self,
        cpl_records: list[CplRecord],
        ad_mappings: list[AdMapping],
    ):
        self._cpl_by_adset: dict[tuple[str, str], CplRecord] = {
            (r.client_id, r.adset_id): r for r in cpl_records
        }
        self._ad_to_adset: dict[tuple[str, str, str], AdMapping] = {
            (m.client_id, m.campaign_id, m.ad_name): m for m in ad_mappings
        }
        self._campaign_avg = self._precompute_campaign_avg(cpl_records)
        self._global_avg = self._precompute_global_avg(cpl_records)
        logger.info(
            "[in_memory_cpl_adapter] carregado: %d CPLs, %d mapeamentos, "
            "%d campanhas com média, %d clientes com média global",
            len(self._cpl_by_adset), len(self._ad_to_adset),
            len(self._campaign_avg), len(self._global_avg),
        )

    # ─ interface pública ──────────────────────────────────────────────────

    def cpl_by_adset(self, client_id: str, adset_id: str) -> Optional[CplRecord]:
        return self._cpl_by_adset.get((client_id, adset_id))

    def cpl_campaign_average(
        self, client_id: str, campaign_id: str,
    ) -> Optional[float]:
        return self._campaign_avg.get((client_id, campaign_id))

    def cpl_global_average(self, client_id: str) -> Optional[float]:
        return self._global_avg.get(client_id)

    def resolve_adset(
        self, client_id: str, campaign_id: str, ad_name: str,
    ) -> Optional[AdMapping]:
        return self._ad_to_adset.get((client_id, campaign_id, ad_name))

    # ─ interno ────────────────────────────────────────────────────────────

    @staticmethod
    def _precompute_campaign_avg(
        records: list[CplRecord],
    ) -> dict[tuple[str, str], float]:
        """Média ponderada por leads por (client_id, campaign_id).

        Mesmo cálculo do `RailwayCplAdapter.cpl_campaign_average` —
        `SUM(spend) / SUM(n_leads)` agrupado, mas feito em Python uma vez
        só no startup.
        """
        spend: dict[tuple[str, str], float] = {}
        leads: dict[tuple[str, str], int] = {}
        for r in records:
            k = (r.client_id, r.campaign_id)
            spend[k] = spend.get(k, 0.0) + r.spend_30d
            leads[k] = leads.get(k, 0) + r.n_leads_30d
        return {
            k: spend[k] / leads[k]
            for k in spend
            if leads[k] > 0
        }

    @staticmethod
    def _precompute_global_avg(records: list[CplRecord]) -> dict[str, float]:
        """Média ponderada por leads por client_id."""
        spend: dict[str, float] = {}
        leads: dict[str, int] = {}
        for r in records:
            spend[r.client_id] = spend.get(r.client_id, 0.0) + r.spend_30d
            leads[r.client_id] = leads.get(r.client_id, 0) + r.n_leads_30d
        return {
            cid: spend[cid] / leads[cid]
            for cid in spend
            if leads[cid] > 0
        }
