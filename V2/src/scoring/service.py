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
from typing import Any, Dict, List, Optional

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
from src.scoring.variants import resolve_champion_challenger


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
    #
    # ATENÇÃO ao scorear em LOTE (`score_leads_from_payloads` com N>1): o conjunto de
    # CHAVES depende de quem mais estava no lote. O one-hot cria uma coluna por
    # categoria presente no DataFrame, então um lead pode vir com colunas de
    # categorias que são de OUTRO lead (valor 0, porque ele não tem aquela
    # categoria). Os VALORES das colunas em comum são idênticos ao caminho de 1
    # lead — verificado em 400 leads reais por scripts/validar_scoring_em_lote.py —
    # e o score não muda, porque o alinhamento com o feature_registry descarta o
    # excedente e preenche o que falta com 0 antes de chegar no modelo.
    #
    # Quem consome este campo (endpoint /explain e auditar_integridade_pipeline)
    # chama pelo caminho de 1 lead, onde o comportamento é o de sempre. Se algum dia
    # alguém auditar a partir do lote, precisa saber que a AUSÊNCIA de uma chave aqui
    # não significa que a feature não existe para o modelo.
    encoded_features: Dict[str, float]

    # Resultado da inferência.
    lead_score: float
    decil: int                    # 1..10
    variant: Optional[str]        # 'champion' | 'challenger' | None (fora do A/B)
    # Bloco F do EVENTOS_E_DECIS_PLANO — score calibrado pra fórmula ROAS V1.
    # None quando a variante (ou o predictor base) não declarou `calibrated_run_id`
    # no YAML → caminho ROAS V1 desligado por construção pra esse lead.
    lead_score_calibrated: Optional[float] = None

    # Régua no ledger: decil pelos DOIS modelos (champion + challenger), gravados
    # no `registros_ml` no scoreamento online — o que aposenta o refresh diário e
    # a `scores_historicos`. None quando o A/B não resolve os dois papéis (degrada:
    # colunas ficam nulas, relatórios caem no fallback). `run_id` por lead = qual
    # régua produziu o decil (comparabilidade a prova de retreino).
    score_champion: Optional[float] = None
    decil_champion: Optional[int] = None
    score_challenger: Optional[float] = None
    decil_challenger: Optional[int] = None
    champion_run_id: Optional[str] = None
    challenger_run_id: Optional[str] = None


# `LeadScoringPipeline` tem estado mutável (`self.data`, `self.original_data`)
# que muda a cada chamada de `preprocess`. Para usar a mesma instância sob
# múltiplas threads (endpoint REST, /explain), serializamos o acesso.
_pipeline_lock = threading.RLock()


class LinhasPerdidasNoPreprocess(RuntimeError):
    """O preprocess devolveu menos linhas do que recebeu — lead sumiu no caminho.

    Acontece porque `core/preprocessing.preprocess` faz `drop_duplicates(keep='first')`
    sobre TODAS as colunas. Com 1 lead por chamada isso nunca aparece; scoreando em
    lote, dois leads idênticos (mesmo e-mail, nome, telefone e data) colapsam num só.

    Fail-loud de propósito: um lead que some silenciosamente é um lead que não é
    scoreado, não vai pro CAPI e não entra no ledger, e ninguém descobre. Quem captura
    esta exceção deve cair no caminho lead-a-lead, que é imune por construção.
    """


def _score_variant_batch(pipeline, df_in, predictor, encoding_overrides):
    """Scoreia N leads por UMA variante: preprocess + predict + decil, em UMA passada.

    Primitivo ÚNICO do scoreamento por variante. `_score_variant` (1 lead) é um
    wrapper fino sobre este — não existe lógica duplicada entre os dois caminhos.

    Devolve `(scores, decis, encoded_df)`, com `scores`/`decis` na MESMA ORDEM das
    linhas de `df_in`. Essa ordem é o contrato: quem chama casa resultado com lead
    por posição, então qualquer linha perdida no meio corromperia o pareamento.
    Daí o guard de contagem levantar em vez de seguir.

    Serializa o estado mutável do pipeline no `_pipeline_lock` (RLock reentrante).
    """
    n_in = len(df_in)
    with _pipeline_lock:
        pipeline.data = df_in
        pipeline.original_data = df_in.copy()
        encoded_df = pipeline.preprocess(
            encoding_overrides=encoding_overrides,
            predictor_override=predictor,
        )
        result = pipeline.predict(predictor_override=predictor)
    if result is None or len(result) == 0:
        raise RuntimeError("pipeline retornou resultado vazio")
    if len(result) != n_in or len(encoded_df) != n_in:
        raise LinhasPerdidasNoPreprocess(
            f"entraram {n_in} leads, saíram {len(result)} scores e "
            f"{len(encoded_df)} linhas encodadas — pareamento por posição "
            f"não é mais confiável"
        )
    thresholds = predictor.metadata.get("decil_thresholds", {}).get("thresholds", {})
    scores = [float(v) for v in result["lead_score"].tolist()]
    decis = [
        int((atribuir_decil_por_threshold(s, thresholds) if thresholds else "D05")[1:])
        for s in scores
    ]
    return scores, decis, encoded_df


def _score_variant(pipeline, df_in, predictor, encoding_overrides):
    """Scoreia UM lead por UMA variante. Wrapper fino sobre `_score_variant_batch`.

    Mantido porque é o contrato que os consumidores existentes já usam; o miolo
    mora no `_batch` para que o caminho de 1 lead e o de N leads não possam divergir.
    """
    scores, decis, encoded_df = _score_variant_batch(
        pipeline, df_in, predictor, encoding_overrides)
    return scores[0], decis[0], encoded_df


def _variant_name(pipeline: LeadScoringPipeline, ab_variant) -> Optional[str]:
    """Nome da variante a partir do objeto. Mesma lógica de pubsub_branch._variant_name."""
    if not ab_variant:
        return None
    return next(
        (n for n, v in pipeline._ab_test_config.variants.items() if v is ab_variant),
        None,
    )


def _contexto_do_lead(payload: Dict, pipeline: LeadScoringPipeline) -> Dict:
    """Tudo que se resolve por lead ANTES de encostar no modelo.

    Normalização, montagem da linha e escolha de predictor/encoding são row-wise e
    baratas — o custo do scoring está no preprocess+predict, não aqui. Isolar este
    pedaço é o que permite o caminho de 1 lead e o de N leads compartilharem
    exatamente a mesma resolução de variante, sem lógica duplicada.

    Levanta `ValueError` se o payload tiver slug fora do vocabulário.
    """
    # 1. Normalizar payload → dicts no vocabulário interno (PT-Long).
    survey_dict = payload_to_survey_dict(payload)
    enrich = payload_to_enrich(payload)
    utm = payload_to_utm(
        payload, pipeline._client_config.utm.source_from_url_slug)

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
        # Lead fora do A/B → usa predictor base. Mas se o predictor base tem o
        # mesmo run_id de alguma variante do YAML, herda o encoding_overrides
        # dessa variante. Espelha o consumer Pub/Sub em api/pubsub_branch.py:388-393
        # — sem isso, leads default escoram com encoding diferente do treino e
        # features críticas ficam zeradas no alinhamento com o feature_registry.
        # Dívida arquitetural: encoding_overrides deveria viver no predictor/modelo,
        # não na variante A/B. Resolver no próximo retreino ou refactor do A/B.
        predictor = pipeline.predictor
        base_run_id = getattr(predictor, 'mlflow_run_id', None)
        vcfg = next(
            (v for v in pipeline._ab_test_config.variants.values()
             if v.run_id == base_run_id),
            None,
        ) if base_run_id else None
        encoding_overrides = vcfg.encoding_overrides if vcfg else None

    return {
        "survey_dict": survey_dict,
        "dataframe_row": dataframe_row,
        "variant_name": variant_name,
        "predictor": predictor,
        "encoding_overrides": encoding_overrides,
        "routed_run": getattr(predictor, "mlflow_run_id", None),
    }


def score_leads_from_payloads(
    payloads: List[Dict],
    pipeline: LeadScoringPipeline,
) -> List[ScoringExplanation]:
    """Scoreia N leads com UMA passada de preprocess+predict por variante.

    É aqui que mora a lógica; `score_lead_from_payload` é o caso N=1. A ordem da
    saída casa com a da entrada.

    POR QUE EM LOTE: medido em produção (31/07/2026), o caminho de 1 lead custa
    0,73s, porque paga o overhead de montar DataFrame, preprocessar e chamar o
    modelo uma vez POR LEAD, 2 a 3 vezes cada. Esse overhead é praticamente fixo:
    250 leads numa passada custam quase o mesmo que 1. Em bancada contra 400 leads
    reais, o ganho foi de 188x (champion) e 240x (challenger), com score e decil
    idênticos aos do caminho individual.

    O que continua sendo POR LEAD (barato, row-wise): normalização, montagem da
    linha e resolução da variante A/B. O que virou por GRUPO: preprocess+predict.
    Leads que resolvem variantes diferentes vão em grupos diferentes, porque cada
    variante tem seu predictor e seu encoding — misturar produziria encoding errado.

    Levanta `ValueError` se ALGUM payload tiver slug fora do vocabulário: quem
    chama deve filtrar antes, ou usar o singular por lead para isolar o culpado.
    """
    if not payloads:
        return []

    ctxs = [_contexto_do_lead(p, pipeline) for p in payloads]
    df_todos = pd.DataFrame([c["dataframe_row"] for c in ctxs])
    papeis = resolve_champion_challenger(pipeline)

    # Um grupo por variante roteada: leads que compartilham predictor E encoding
    # podem ser preprocessados juntos. `variant_name=None` (fora do A/B) é um
    # grupo legítimo, com o predictor base.
    grupos: Dict[Any, List[int]] = {}
    for i, c in enumerate(ctxs):
        grupos.setdefault(c["variant_name"], []).append(i)

    # Resultado do ROTEADO (o que vai pro CAPI), por lead.
    scores: List[Optional[float]] = [None] * len(ctxs)
    decis: List[Optional[int]] = [None] * len(ctxs)
    calibrados: List[Optional[float]] = [None] * len(ctxs)
    encodadas: List[Dict[str, float]] = [{} for _ in ctxs]

    for variant_name, idxs in grupos.items():
        c0 = ctxs[idxs[0]]
        sc, dc, enc = _score_variant_batch(
            pipeline, df_todos.iloc[idxs].reset_index(drop=True),
            c0["predictor"], c0["encoding_overrides"],
        )
        for pos, i in enumerate(idxs):
            scores[i] = sc[pos]
            decis[i] = dc[pos]
            encodadas[i] = {
                k: _to_python_scalar(v) for k, v in enc.iloc[pos].to_dict().items()
            }
        # Bloco F — calibrado do roteado. `predict_proba` já é vetorizado, então o
        # lote inteiro do grupo sai numa chamada, reusando o `enc` (sem repreprocessar).
        calib_pred = (
            pipeline.get_variant_calibrated_predictor(variant_name)
            if variant_name else None
        )
        if calib_pred is not None:
            proba = calib_pred.predict_proba(enc)
            if proba is not None and len(proba) == len(idxs):
                for pos, i in enumerate(idxs):
                    calibrados[i] = float(proba[pos])

    # Régua no ledger: decil pelos DOIS papéis. Quem já foi scoreado como roteado
    # reusa; o resto entra numa passada única por papel sobre os leads que faltam.
    por_papel: Dict[str, List[Optional[float]]] = {}
    for papel in ("champion", "challenger"):
        s_papel: List[Optional[float]] = [None] * len(ctxs)
        d_papel: List[Optional[int]] = [None] * len(ctxs)
        if papeis:
            info = papeis[papel]
            faltam = [
                i for i, c in enumerate(ctxs) if c["routed_run"] != info["run_id"]
            ]
            for i, c in enumerate(ctxs):
                if c["routed_run"] == info["run_id"]:
                    s_papel[i], d_papel[i] = scores[i], decis[i]
            if faltam:
                sc, dc, _ = _score_variant_batch(
                    pipeline, df_todos.iloc[faltam].reset_index(drop=True),
                    pipeline.get_variant_predictor(info["variant_name"]),
                    info["encoding_overrides"],
                )
                for pos, i in enumerate(faltam):
                    s_papel[i], d_papel[i] = sc[pos], dc[pos]
        por_papel[f"s_{papel}"] = s_papel
        por_papel[f"d_{papel}"] = d_papel

    champ_run = papeis["champion"]["run_id"] if papeis else None
    chall_run = papeis["challenger"]["run_id"] if papeis else None

    return [
        ScoringExplanation(
            payload_normalizado=c["survey_dict"],
            dataframe_row=c["dataframe_row"],
            encoded_features=encodadas[i],
            lead_score=scores[i],
            decil=decis[i],
            variant=c["variant_name"],
            lead_score_calibrated=calibrados[i],
            score_champion=por_papel["s_champion"][i],
            decil_champion=por_papel["d_champion"][i],
            score_challenger=por_papel["s_challenger"][i],
            decil_challenger=por_papel["d_challenger"][i],
            champion_run_id=champ_run if papeis else None,
            challenger_run_id=chall_run if papeis else None,
        )
        for i, c in enumerate(ctxs)
    ]


def score_lead_from_payload(
    payload: Dict,
    pipeline: LeadScoringPipeline,
) -> ScoringExplanation:
    """Pega um payload Pub/Sub e devolve o pacote completo de scoring.

    Wrapper de `score_leads_from_payloads` com N=1 — o miolo é um só, então o
    caminho de 1 lead e o de N leads não podem divergir com o tempo.

    Não acessa banco. Não envia CAPI. Não persiste nada. Função stateless do
    ponto de vista do chamador — qualquer estado mutável fica protegido pelo
    lock interno.

    Pode levantar:
      - `ValueError` se o payload tiver slug fora do vocabulário.
      - `RuntimeError` se o pipeline retornar resultado vazio.
    """
    return score_leads_from_payloads([payload], pipeline)[0]


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
