"""Interface de estratégia de decil + implementação da propensão pura.

Bloco C do EVENTOS_E_DECIS_PLANO. Prepara o caminho do scoring pra aceitar
múltiplas estratégias de decil rodando em paralelo — Propensão hoje (única
em produção), Roas V1 depois (quando o calibrador estiver pronto).

A propensão pura é a estratégia em produção desde sempre: ordena leads por
probabilidade de compra (`leadScore` do Random Forest) e atribui decil
D01-D10 via thresholds fixos do test set do treino. Esta classe extrai essa
lógica do caminho atual (`atribuir_decil_por_threshold` em
`src/model/decil_thresholds.py` + leitura de campos da
`ABTestVariantConfig` espalhada em `api/capi_integration.py`) e devolve um
`DecileAssignment` único agregando decil + nome do evento HQ + pixel +
faixa de decis HQ. Paridade 100% com o caminho atual é critério de aceite.

Catálogo do "como" deste subsistema: V2/docs/EVENTOS_E_DECIS_PLANO.md
(Bloco C).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, runtime_checkable

from src.core.client_config import ABTestVariantConfig
from src.model.decil_thresholds import atribuir_decil_por_threshold

# Tipos auxiliares
from typing import Mapping

logger = logging.getLogger(__name__)


# Faixa default de decis que disparam o evento HQ quando a variante não
# declara `capi_high_quality_decils`. Mesma constante que vive hoje em
# `api/capi_integration.send_lead_qualified_high_quality` (linha 515).
# Mover pra cá quando o consumidor migrar — por enquanto duplicado pra
# garantir paridade byte-a-byte sem mexer no caller.
DEFAULT_HQ_DECILS: List[str] = ['D09', 'D10']


@dataclass(frozen=True)
class DecileAssignment:
    """O que uma estratégia de decil decide pra um lead. Imutável.

    Agrega num só objeto o que hoje vive distribuído entre o pipeline
    (decil) e o capi_integration (event_name_base, event_name_hq, pixel,
    hq_decils, conversion_rates):

      - decile → vem de `atribuir_decil_por_threshold(score, thresholds)`
      - event_name_base → vem de `variant_config.capi_event_name`
                          ("LeadQualified" no Champion, "HQLB_LQ" no
                          Challenger). Evento que carrega o `value`.
      - event_name_hq → vem de `variant_config.capi_event_name_high_quality`
                        ("LeadQualifiedHighQuality" | "HQLB" | ...)
      - pixel_id → vem de `variant_config.pixel_id_override` (None = usa o
                    pixel default do `CAPIConfig` na hora do envio)
      - hq_decils → vem de `variant_config.capi_high_quality_decils` ou
                    `DEFAULT_HQ_DECILS` se a variante não declarar
      - conversion_rates → vem de `variant_config.conversion_rates`. Tabela
                            decil → conversion_rate que multiplica o
                            ticket pra gerar o `value` enviado ao Meta.
      - is_hq_eligible → `decil in hq_decils` — caller usa pra decidir se
                          dispara HQ ou só o evento base

    O caller (Bloco D, `send_all_lead_events`) itera sobre uma lista de
    `DecileAssignment` e dispara o(s) evento(s) primário(s) — o laço de
    fan-out atual roda em cima sem alteração, lendo
    `capi.extra_hq_destinations` por nome do evento.
    """
    decile: str                            # "D01".."D10"
    strategy_id: str                       # "propensity" | "roas_v1" | ...
    event_name_base: str                   # "LeadQualified" | "HQLB_LQ" | ...
    event_name_hq: str                     # "LeadQualifiedHighQuality" | "HQLB" | ...
    pixel_id: Optional[str]                # None = caller usa pixel default do CAPIConfig
    hq_decils: List[str]                   # ex.: ["D09", "D10"] | ["D08", "D09", "D10"]
    conversion_rates: Mapping[str, float]  # tabela decil → conversion_rate p/ value
    is_hq_eligible: bool                   # decile in hq_decils


@runtime_checkable
class DecileStrategy(Protocol):
    """Quem traduz score do modelo em decil + evento + pixel pra uma variante."""

    strategy_id: str

    def assign(
        self,
        score: float,
        variant_config: ABTestVariantConfig,
        thresholds: Dict[str, Dict],
    ) -> DecileAssignment:
        """Devolve o `DecileAssignment` pra um lead.

        Args:
            score: probabilidade predita pelo modelo (0-1).
            variant_config: variante A/B que esse lead caiu (Champion ou
                Challenger), via `ABTestConfig.match_variant`.
            thresholds: dict de thresholds D01-D10 da variante, carregado
                do `model_metadata.json` do MLflow run. Mesma estrutura
                consumida por `atribuir_decil_por_threshold`.
        """
        ...


class PropensityDecileStrategy:
    """Estratégia atual: decil = thresholds fixos sobre o score do RF.

    Paridade 100% com o caminho que hoje vive distribuído entre
    `LeadScoringPipeline.predict_batch` (decil) e
    `send_lead_qualified_high_quality` (event_name, pixel, hq_decils).
    Nenhuma matemática nova — só agregação.
    """

    strategy_id: str = "propensity"

    def assign(
        self,
        score: float,
        variant_config: ABTestVariantConfig,
        thresholds: Dict[str, Dict],
    ) -> DecileAssignment:
        decile = atribuir_decil_por_threshold(score, thresholds)
        hq_decils = variant_config.capi_high_quality_decils or DEFAULT_HQ_DECILS
        return DecileAssignment(
            decile=decile,
            strategy_id=self.strategy_id,
            event_name_base=variant_config.capi_event_name,
            event_name_hq=variant_config.capi_event_name_high_quality,
            pixel_id=variant_config.pixel_id_override,
            hq_decils=hq_decils,
            conversion_rates=variant_config.conversion_rates,
            is_hq_eligible=decile in hq_decils,
        )
