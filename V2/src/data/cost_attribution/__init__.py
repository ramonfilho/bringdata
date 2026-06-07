"""Atribuição de custo Meta por lead — base do lookup que alimenta a fórmula
ROAS (`retorno_esperado = (probabilidade × ticket à vista) ÷ custo_por_lead`).

Estrutura:
  - `cpl_record`     — formato interno (`CplRecord`, `AdMapping`) — contrato
                       estável entre adaptadores e consumidores.
  - `cpl_repository` — interface `CplRepository` + composer dos adapters.
  - `adapters/`      — implementações: Railway (fonte de verdade) e
                       InMemory (cache no startup do scoring).

Catálogo do "como" deste subsistema: V2/docs/EVENTOS_E_DECIS_PLANO.md (Bloco B).
"""
from .cpl_record import CplRecord, AdMapping  # noqa: F401
from .cpl_repository import CplRepository  # noqa: F401
