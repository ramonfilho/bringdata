"""Casa do scoring de um lead — fachada stateless sobre `LeadScoringPipeline`.

O `LeadScoringPipeline` em `src/production_pipeline.py` opera em lote: recebe
caminho de CSV, escreve em `self.data` e modifica esse atributo a cada passo.
Funciona para o consumer Pub/Sub, que roda 1× a cada 5min e antes da chamada
materializa o batch em disco. Mas:

  - força quem quer scorear 1 lead a criar um CSV temporário no disco;
  - expõe estado mutável a quem chama de fora (endpoint REST, backtest), o
    que vira bug de concorrência sob requisições paralelas;
  - esconde os intermediários (dict no formato Railway, vetor encodado de
    52 colunas) que são justamente o que a auditoria quer inspecionar.

Esta camada resolve os três. Recebe um payload Pub/Sub, faz toda a sequência
em memória, devolve um pacote `ScoringExplanation` com **todos os
intermediários expostos** — incluindo score, decil e variante.

Como o pipeline interno ainda muta `self.data`, esta camada serializa o uso
com um lock de módulo. É a forma minimamente invasiva de proteger contra
concorrência sem mexer no `LeadScoringPipeline` (que continua sendo a peça
canônica usada por treino, monitoramento e jobs batch).
"""
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from api.survey_mapping import survey_lead_to_sheets_row
from src.core.payload_normalization import (
    payload_to_enrich,
    payload_to_survey_dict,
    payload_to_utm,
)
from src.data.lead_record import LeadRecord
from src.model.decil_thresholds import atribuir_decil_por_threshold
from src.production_pipeline import LeadScoringPipeline


@dataclass(frozen=True)
class ScoringExplanation:
    """Pacote completo de um scoring, com intermediários expostos.

    Quem só quer o resultado final: use `lead_score`, `decil`, `variant`.
    Quem quer auditar o caminho: use `payload_normalizado`, `dataframe_row`,
    `encoded_features`.
    """
    # Payload Pub/Sub pós-tradução slug → PT-Long (formato `lead_surveys` antigo).
    payload_normalizado: Dict[str, Any]

    # Dict no formato que o pipeline ML espera (chaves do schema Railway).
    dataframe_row: Dict[str, Any]

    # Vetor encodado: 52 colunas alinhadas com `feature_registry.json` do modelo.
    # Cada valor é 0/1 (binárias e OHE) ou float (numéricas como `nome_comprimento`).
    encoded_features: Dict[str, float]

    # Resultado da inferência.
    lead_score: float
    decil: int                    # 1..10
    variant: Optional[str]        # 'champion' | 'challenger' | None (fora do A/B)


# `LeadScoringPipeline` tem estado mutável (`self.data`, `self.original_data`)
# que muda a cada chamada de `preprocess`. Para usar a mesma instância sob
# múltiplas threads (endpoint REST, /explain), serializamos o acesso.
_pipeline_lock = threading.RLock()


def _variant_name(pipeline: LeadScoringPipeline, ab_variant) -> Optional[str]:
    """Nome da variante a partir do objeto. Mesma lógica de pubsub_branch._variant_name."""
    if not ab_variant:
        return None
    return next(
        (n for n, v in pipeline._ab_test_config.variants.items() if v is ab_variant),
        None,
    )


def score_lead_from_payload(
    payload: Dict,
    pipeline: LeadScoringPipeline,
) -> ScoringExplanation:
    """Pega um payload Pub/Sub e devolve o pacote completo de scoring.

    Não acessa banco. Não envia CAPI. Não persiste nada. Função stateless do
    ponto de vista do chamador — qualquer estado mutável fica protegido pelo
    lock interno.

    Pode levantar:
      - `ValueError` se o payload tiver slug fora do vocabulário.
      - `RuntimeError` se o pipeline retornar resultado vazio.
    """
    # 1. Normalizar payload → dicts no vocabulário interno (PT-Long).
    survey_dict = payload_to_survey_dict(payload)
    enrich = payload_to_enrich(payload)
    utm = payload_to_utm(payload)

    # 2. Montar a linha do DataFrame no formato Railway.
    dataframe_row = survey_lead_to_sheets_row(
        survey_dict, utm, enrich, client_config=pipeline._client_config)

    # 3. Resolver variante A/B e escolher predictor + encoding_overrides.
    ab_v = pipeline.get_ab_variant(
        {"utm_campaign": utm.get("campaign"),
         "utm_content":  utm.get("content"),
         "utm_source":   utm.get("source"),
         "utm_medium":   utm.get("medium"),
         "utm_term":     utm.get("term")},
        event_source_url=utm.get("url"),
    )
    variant_name = _variant_name(pipeline, ab_v)

    if variant_name:
        predictor = pipeline.get_variant_predictor(variant_name)
        vcfg = pipeline._ab_test_config.variants.get(variant_name)
        encoding_overrides = vcfg.encoding_overrides if vcfg else None
    else:
        predictor = pipeline.predictor
        encoding_overrides = None

    # 4. Rodar preprocess + predict em memória, com lock contra concorrência.
    df_in = pd.DataFrame([dataframe_row])

    with _pipeline_lock:
        pipeline.data = df_in
        pipeline.original_data = df_in.copy()
        encoded_df = pipeline.preprocess(
            encoding_overrides=encoding_overrides,
            predictor_override=predictor,
        )
        # Capturar o vetor encodado antes do predict — preprocess já retornou
        # self.data com as 52 colunas alinhadas com o feature_registry do
        # predictor escolhido.
        encoded_features = (
            {k: _to_python_scalar(v) for k, v in encoded_df.iloc[0].to_dict().items()}
            if len(encoded_df) > 0 else {}
        )
        result = pipeline.predict(predictor_override=predictor)

    # 5. Extrair score e decil.
    if result is None or len(result) == 0:
        raise RuntimeError("pipeline retornou resultado vazio")

    lead_score = float(result["lead_score"].iloc[0])
    thresholds = predictor.metadata.get("decil_thresholds", {}).get("thresholds", {})
    decil_str = atribuir_decil_por_threshold(lead_score, thresholds) if thresholds else "D05"
    decil = int(decil_str[1:])

    return ScoringExplanation(
        payload_normalizado=survey_dict,
        dataframe_row=dataframe_row,
        encoded_features=encoded_features,
        lead_score=lead_score,
        decil=decil,
        variant=variant_name,
    )


def _to_python_scalar(v):
    """numpy.int64/float64 → int/float nativos pra serialização JSON."""
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    return v


def payload_from_record(record: LeadRecord) -> Dict[str, Any]:
    """Reconstrói o payload Pub/Sub a partir de um `LeadRecord` persistido.

    Inversa de `score_lead_from_payload` — pega o lead já guardado (no ledger
    ou na tabela Lead antiga) e devolve o dict que o consumer Pub/Sub teria
    recebido. `survey_responses` é mantido como veio no banco (slugs originais
    do front no ledger novo, ou pesquisa em PT-Long na Lead antiga).

    Usos: endpoint /predict/explain (auditoria) e script de backtest
    (re-scoring de lead histórico com modelo atual).
    """
    fn = (record.first_name or "").strip()
    ln = (record.last_name or "").strip()
    return {
        "eventId":      record.event_id,
        "submittedAt":  record.criado_em.isoformat() if record.criado_em else None,
        "email":        record.email,
        "firstName":    fn or None,
        "lastName":     ln or None,
        "phone":        record.phone,
        "hasComputer":  record.has_computer,
        "fbp":          record.fbp,
        "fbc":          record.fbc,
        "userAgent":    record.user_agent,
        "ip4":          record.ip,
        "survey":       dict(record.survey_responses) if record.survey_responses else {},
        "utm": {
            "source":   record.utm_source,
            "medium":   record.utm_medium,
            "campaign": record.utm_campaign,
            "content":  record.utm_content,
            "term":     record.utm_term,
            "url":      record.utm_url,
        },
    }
