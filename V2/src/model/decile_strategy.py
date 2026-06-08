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
from src.data.cost_attribution.cpl_record import (
    CPL_SOURCE_ADSET, CPL_SOURCE_CAMPAIGN, CPL_SOURCE_GLOBAL, CPL_SOURCE_MISSING,
)
from src.data.cost_attribution.cpl_repository import CplRepository
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


# Regex pra extrair campaign_id do sufixo de utm_campaign (Meta grava como
# "DEVLF | CAP | … | LEADQUALIFIED|120245402719300390"). Mesma forma que a
# análise offline usa.
import re as _re
_CAMPAIGN_ID_FROM_UTM_RE = _re.compile(r"\|\s*(\d{10,})\s*$")


def _extract_campaign_id(utm_campaign: Optional[str]) -> Optional[str]:
    """Devolve o id Meta da campanha (10+ dígitos) do sufixo do utm_campaign."""
    if not utm_campaign:
        return None
    m = _CAMPAIGN_ID_FROM_UTM_RE.search(utm_campaign.strip())
    return m.group(1) if m else None


@dataclass(frozen=True)
class LeadCostContext:
    """Informação sobre custo do lead que a RoasV1DecileStrategy consome.

    Construído pelo caller a partir do CplLookup (composição de CplRepository
    + AdResolver). O caller resolve adset → CPL antes de chamar
    `strategy.assign` pra deixar o método da estratégia puramente determinístico
    (sem efeitos colaterais de I/O).

    `cpl_source` registra qual fallback foi usado pra cobertura/auditoria
    (gravado na coluna `cpl_source` do `registros_ml`).
    """
    cpl: Optional[float]   # None = nenhum CPL recuperado (cpl_source='missing')
    cpl_source: str        # CPL_SOURCE_ADSET | _CAMPAIGN | _GLOBAL | _MISSING


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
    # Campos opcionais — só populados por RoasV1DecileStrategy. Vão direto
    # pras colunas de observabilidade `decile_roas_v1` / `cpl_source` /
    # `expected_return_roas_v1` do `registros_ml`.
    expected_return: Optional[float] = None  # (prob × ticket) ÷ cpl
    cpl_used: Optional[float] = None
    cpl_source: Optional[str] = None


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


class RoasV1DecileStrategy:
    """Estratégia ROAS V1: decil = thresholds fixos sobre `retorno_esperado`.

    `retorno_esperado = (prob_calibrada × ticket) ÷ CPL_adset`.

    Quem chama é responsável por:
      - calcular a `prob_calibrada` (predict_proba do modelo calibrado, run
        com sufixo `-calibrated-isotonic`);
      - resolver o `cpl` do adset que trouxe o lead via `CplLookup` (composição
        de `CplRepository` + `AdResolver`) e empacotar no `LeadCostContext`,
        incluindo a cascata de fallback (`adset` → `campaign` → `global` →
        `missing`);
      - passar o `cost_context` no `assign()`.

    Quando `cost_context.cpl` é None (`cpl_source=missing`), a fórmula não
    roda. A estratégia retorna um `DecileAssignment` com `decile=D01`,
    `is_hq_eligible=False`, e `cpl_source='missing'` registrado. O caller
    pode optar por NÃO emitir o evento ROAS_V1 desse lead (recomendado) ou
    enviá-lo no decil mais baixo (default).

    Os `thresholds_roas_v1` recebidos têm o mesmo schema dos thresholds da
    Propensão (`{D01: {threshold_min, threshold_max}, ...}`), porém aplicados
    sobre `retorno_esperado` (escala R$ × prob ÷ R$ = adimensional). Eles são
    derivados de uma análise offline (`scripts/derive_roas_v1_thresholds.py`)
    sobre uma janela representativa de leads scoreados com probabilidade
    calibrada × CPL real.

    O `event_name_base` e `event_name_hq` ganham o sufixo configurado em
    `variant_config.roas_v1_event_name_suffix` (default `_ROAS_V1`). Quem
    cria as campanhas Meta usa esses nomes pra otimizar separadamente.
    """

    strategy_id: str = "roas_v1"

    def __init__(
        self,
        ticket: float,
        event_name_suffix: str = "_ROAS_V1",
    ):
        """`ticket` = valor médio recebido por venda (à vista), pra usar na fórmula."""
        self.ticket = ticket
        self.event_name_suffix = event_name_suffix

    def assign(
        self,
        score: float,                              # = prob_calibrada (caller passa calibrado)
        variant_config: ABTestVariantConfig,
        thresholds: Dict[str, Dict],               # thresholds_roas_v1, escala retorno_esperado
        cost_context: LeadCostContext,             # cpl resolvido + source
    ) -> DecileAssignment:
        hq_decils = variant_config.capi_high_quality_decils or DEFAULT_HQ_DECILS

        # Cascata de fallback do CPL — quando missing, fórmula não roda.
        if cost_context.cpl is None or cost_context.cpl <= 0:
            return DecileAssignment(
                decile="D01",
                strategy_id=self.strategy_id,
                event_name_base=variant_config.capi_event_name + self.event_name_suffix,
                event_name_hq=variant_config.capi_event_name_high_quality + self.event_name_suffix,
                pixel_id=variant_config.pixel_id_override,
                hq_decils=hq_decils,
                conversion_rates=variant_config.conversion_rates,
                is_hq_eligible=False,
                expected_return=None,
                cpl_used=None,
                cpl_source=CPL_SOURCE_MISSING,
            )

        retorno = (score * self.ticket) / cost_context.cpl
        decile = atribuir_decil_por_threshold(retorno, thresholds)
        return DecileAssignment(
            decile=decile,
            strategy_id=self.strategy_id,
            event_name_base=variant_config.capi_event_name + self.event_name_suffix,
            event_name_hq=variant_config.capi_event_name_high_quality + self.event_name_suffix,
            pixel_id=variant_config.pixel_id_override,
            hq_decils=hq_decils,
            conversion_rates=variant_config.conversion_rates,
            is_hq_eligible=decile in hq_decils,
            expected_return=retorno,
            cpl_used=cost_context.cpl,
            cpl_source=cost_context.cpl_source,
        )


def resolve_cost_context(
    cpl_repo: CplRepository,
    client_id: str,
    utm_campaign: Optional[str],
    utm_content: Optional[str],
) -> LeadCostContext:
    """Resolve `LeadCostContext` consultando `CplRepository` com cascata de fallback.

    Hierarquia da cascata:
      1. `cpl_adset[adset_id]` — via `resolve_adset(campaign_id, ad_name)`
      2. `cpl_campaign_average(campaign_id)`
      3. `cpl_global_average(client_id)`
      4. None (cpl_source='missing')

    Esta função fica fora da `RoasV1DecileStrategy` pra deixar a estratégia
    pura (sem I/O); ela é orquestrada pelo caller no scoring container.
    """
    campaign_id = _extract_campaign_id(utm_campaign)
    if campaign_id is None or not utm_content:
        return LeadCostContext(cpl=None, cpl_source=CPL_SOURCE_MISSING)

    ad_name = utm_content.strip()
    mapping = cpl_repo.resolve_adset(client_id, campaign_id, ad_name)
    if mapping is not None:
        record = cpl_repo.cpl_by_adset(client_id, mapping.adset_id)
        if record is not None:
            return LeadCostContext(cpl=record.cpl_30d, cpl_source=CPL_SOURCE_ADSET)

    # Adset novo ou sem 30d de histórico → média da campanha
    camp_avg = cpl_repo.cpl_campaign_average(client_id, campaign_id)
    if camp_avg is not None:
        return LeadCostContext(cpl=camp_avg, cpl_source=CPL_SOURCE_CAMPAIGN)

    # Campanha também sem histórico → média do cliente
    global_avg = cpl_repo.cpl_global_average(client_id)
    if global_avg is not None:
        return LeadCostContext(cpl=global_avg, cpl_source=CPL_SOURCE_GLOBAL)

    return LeadCostContext(cpl=None, cpl_source=CPL_SOURCE_MISSING)
