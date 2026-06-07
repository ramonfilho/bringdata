"""Interface do bibliotecário de custo por adset + função de composição.

`CplRepository` é a interface que cada adaptador implementa. Consumidores
recebem um `CplRepository` (injeção de dependência) e chamam seus métodos
sem saber qual adaptador está por trás.

Padrão idêntico ao `src/data/lead_repository.py`. Adicionar método na
interface é decisão consciente: só quando 2+ consumidores precisam da
mesma coisa.

Dois adapters previstos:
  - `railway`   — fonte de verdade (tabelas `cpl_adset` e `ad_to_adset_map`).
                  Lê uma vez no startup do scoring container ou consultas
                  ad-hoc do refresh job.
  - `in_memory` — cache pro hot path do scoring. Recebe um snapshot do
                  `railway` no startup e responde com dict lookup (μs).
"""
from typing import Optional, Protocol, runtime_checkable

from .cpl_record import AdMapping, CplRecord


@runtime_checkable
class CplRepository(Protocol):
    """Devolve custo por adset e mapeamento ad→adset no formato interno."""

    def cpl_by_adset(self, client_id: str, adset_id: str) -> Optional[CplRecord]:
        """Custo médio do adset nos últimos 30 dias. None se sem histórico."""
        ...

    def cpl_campaign_average(
        self, client_id: str, campaign_id: str,
    ) -> Optional[float]:
        """Fallback 1: média de CPL dos adsets ativos da mesma campanha.

        Usado quando o adset que trouxe o lead não tem 30d de histórico
        próprio. Retorna None se a campanha inteira não tem nenhum adset
        registrado (fallback ainda mais baixo cai pra `cpl_global_average`).
        """
        ...

    def cpl_global_average(self, client_id: str) -> Optional[float]:
        """Fallback 2: média de CPL de todos os adsets ativos do cliente.

        Último recurso antes de declarar `cpl_source = missing` e cair pra
        ordenação só por propensão. Retorna None se o cliente ainda não
        tem nenhum adset registrado (refresh job nunca rodou pra ele).
        """
        ...

    def resolve_adset(
        self, client_id: str, campaign_id: str, ad_name: str,
    ) -> Optional[AdMapping]:
        """Traduz `(campaign_id, ad_name)` → `adset_id`. None se não casar."""
        ...


def compose_repository(source: str = 'railway', **conn_kwargs) -> CplRepository:
    """Monta o adaptador certo pro contexto.

    Chamado pelos pontos de entrada (endpoint de scoring, refresh job,
    scripts ad-hoc). Consumidor não chama — recebe o repositório pronto.

    Args:
        source: identificador da fonte. Valores aceitos:
            - 'railway' (default): adapter que lê das tabelas `cpl_adset`
              e `ad_to_adset_map` no Railway. Fonte de verdade.
            - 'in_memory': cache em RAM populado por snapshot do railway,
              pro hot path do scoring. Requer `snapshot` (instância
              `CplSnapshot` pré-carregada) nos `conn_kwargs`.
        conn_kwargs: kwargs específicos do adaptador (ex.:
                     `railway_conn=conn_pg8000`, `snapshot=...`).

    Raises:
        ValueError: se a fonte não for reconhecida.
    """
    if source == 'railway':
        from .adapters.railway import RailwayCplAdapter
        return RailwayCplAdapter(**conn_kwargs)
    if source == 'in_memory':
        from .adapters.in_memory import InMemoryCplAdapter
        return InMemoryCplAdapter(**conn_kwargs)
    raise ValueError(
        f"fonte desconhecida: {source!r}. Valores aceitos: 'railway', 'in_memory'."
    )
