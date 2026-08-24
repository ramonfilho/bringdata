"""reference_reader — leitor único da referência rolante (Repositório).

Os relatórios (decis, funil, tabelas de característica) pedem a referência a ESTE
módulo em vez de ler arquivo/tabela direto. Assim, trocar a fonte é trocar aqui, e
o rollback é uma flag — não um deploy.

Estrangulamento (rollback por flag, sem backend "congelado" no leitor):
  - `REFERENCE_SOURCE=rolling` → o consumidor usa este leitor (a tabela viva).
  - `REFERENCE_SOURCE=frozen` (default no rollout) → o consumidor IGNORA este leitor
    e segue o caminho ANTIGO dele (JSON congelado / métrica %D9-D10). O caminho velho
    fica vivo até a rolante provar valor; então some.

A conversão de referência e a curva do calibrador vêm da tabela
`analytics.reference_rolling` (materializada pelo job semanal). O leitor reconstrói a
conversão ESPERADA de um lead com `np.interp` sobre a curva — sem sklearn na leitura.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def reference_source() -> str:
    """Fonte da referência: 'rolling' (tabela viva) ou 'frozen' (caminho antigo do
    consumidor). Default 'frozen' durante o rollout → rollback instantâneo sem deploy."""
    return os.environ.get("REFERENCE_SOURCE", "frozen").strip().lower()


def rolling_enabled() -> bool:
    return reference_source() == "rolling"


def read_rolling_reference(client_id: str = "devclub", *, conn=None,
                           window_end_max=None, generated_at_max=None) -> Optional[dict]:
    """Lê a referência rolante de analytics.reference_rolling (a mais recente por
    default; POINT-IN-TIME quando os cortes são passados).

    POR QUE OS DOIS CORTES, E QUAL É QUAL (duas sessões já confundiram):

      `generated_at_max` = corte POINT-IN-TIME de verdade. Responde "que linha JÁ
        EXISTIA naquele instante", porque `generated_at` é o carimbo de quando o
        refresh gravou a linha. É o que reproduz o número que a produção SERVIA
        num dia passado. Medido em 24/08/2026: com generated_at_max='2026-08-07'
        (dia em que o LF64 começou a captar) a linha servida era window_end
        2026-07-13, e não a de hoje (2026-08-03, gravada em 24/08).
      `window_end_max` = corte de CONTEÚDO. Responde "referência que só enxerga
        lead/venda até tal data", independente de quando foi calculada. Serve pra
        cravar a janela de dados, não pra reconstruir o passado.

    Sem os dois parâmetros o SQL e o resultado são IDÊNTICOS aos de sempre (nenhum
    chamador de produção muda de número). Com qualquer um deles entra também o
    desempate `generated_at DESC`: em 03/08/2026 duas reconstruções gravaram a
    MESMA `as_of` com políticas de maturação diferentes, e um backtest não pode
    depender de qual delas o banco devolve primeiro.

    Args:
        window_end_max: date/datetime/str. Acrescenta `AND window_end <= :we`.
        generated_at_max: date/datetime/str. Acrescenta `AND generated_at <= :ga`
            (timestamptz; data sem hora vira meia-noite UTC, que é o timezone do
            servidor).

    Returns:
        dict {window_start, window_end, as_of, ruler_run_id, n_leads, conversion,
        calibration, audience_profile} ou None se não houver linha (o consumidor
        degrada pro caminho congelado — nunca quebra por falta de referência).
        `audience_profile` pode ser None (janela sem perfil de comprador).
    """
    own = conn is None
    if own:
        try:
            from src.data.analytics_connection import open_analytics_connection
            conn = open_analytics_connection()
        except Exception as e:
            logger.warning("[reference_reader] conexão falhou: %s", e)
            return None
    # Montado por concatenação pra que a chamada SEM os cortes produza a string
    # byte a byte igual à de antes deles existirem (o teste de identidade compara
    # o SQL literal, não só o resultado).
    sql = ("SELECT window_start, window_end, as_of, ruler_run_id, n_leads, "
           "       conversion, calibration, audience_profile, generated_at "
           "FROM reference_rolling WHERE client_id = :c AND source = 'rolling' ")
    params = {"c": client_id}
    if window_end_max is not None:
        sql += "AND window_end <= CAST(:we AS date) "
        params["we"] = str(window_end_max)
    if generated_at_max is not None:
        sql += "AND generated_at <= CAST(:ga AS timestamptz) "
        params["ga"] = str(generated_at_max)
    sql += ("ORDER BY window_end DESC LIMIT 1" if len(params) == 1
            else "ORDER BY window_end DESC, generated_at DESC LIMIT 1")
    try:
        rows = conn.run(sql, **params)
    except Exception as e:
        logger.warning("[reference_reader] leitura falhou (tabela ausente?): %s", e)
        return None
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass

    if not rows:
        logger.info("[reference_reader] sem referência rolante pra client=%s", client_id)
        return None
    r = rows[0]
    # jsonb volta como dict pelo pg8000; se vier string (driver diferente), parseia.
    import json

    def _as_dict(v):
        if v is None:
            return None
        return v if isinstance(v, dict) else json.loads(v)

    # `as_of` NÃO identifica a linha: em 03/08/2026 duas reconstruções diferentes
    # gravaram a mesma data — uma com 86.141 leads (a servida) e outra com 107.986,
    # feitas com políticas de maturação diferentes. Um recibo que aponta para as duas
    # não é recibo. `generated_at` é único e resolve, e por isso vira o identificador.
    gerado = str(r[8])[:16] if r[8] is not None else None
    return {
        "window_start": str(r[0]), "window_end": str(r[1]), "as_of": str(r[2]),
        "ruler_run_id": r[3], "n_leads": int(r[4]),
        "conversion": _as_dict(r[5]), "calibration": _as_dict(r[6]),
        "audience_profile": _as_dict(r[7]),
        "generated_at": gerado,
        # O identificador que viaja nos recibos: legível (a data salta) e único (o
        # instante desempata). Ex.: "2026-08-03T19:15".
        "referencia_id": (f"{str(r[2])}T{gerado[11:16]}" if gerado and len(gerado) >= 16
                          else str(r[2])),
    }


def credito_do_nao_respondente(ref: Optional[dict]) -> Optional[float]:
    """O crédito do cadastro que NÃO respondeu a pesquisa, MEDIDO pelo refresh
    semanal (`conversion.survey_coverage`), ou None quando a referência não tem
    a medida válida, e aí o chamador degrada pro comportamento antigo.

    Só devolve número com `valido=True`: medida marcada inválida (janela curta,
    poucos cadastros) não vira moeda. Ver Decisão 12 e `push_scores_zanelato`,
    que trata o não-respondente como valendo `credito ×` o respondente em vez de
    zero (medido em 343k cadastros: 33% a 45%).
    """
    sc = ((ref or {}).get("conversion") or {}).get("survey_coverage") or {}
    try:
        if sc.get("valido") and sc.get("credito"):
            return float(sc["credito"])
    except (TypeError, ValueError):
        logger.warning("[reference_reader] survey_coverage.credito ilegível: %r",
                       sc.get("credito"))
    return None


def fator_de_rastreamento(conv: Optional[dict]) -> tuple:
    """(fator, procedência) do rastreamento, normalizando os DOIS formatos de
    payload que a tabela guarda. Normalização na BORDA: o consumidor recebe um
    número e a origem dele, e não precisa saber que existiram dois formatos.

    Ordem de busca:
      1. `conversion.tracking.factor`      → procedência 'tracking' (formato de
         hoje; ex.: 1.2312 na linha window_end 2026-08-03).
      2. `conversion.economics.late_purchase_uplift` → 'late_purchase_uplift_legado'
         (formato antigo; ex.: 1.2105 na linha window_end 2026-07-13). Nenhuma
         linha tem as duas chaves, então não há conflito a resolver.
      3. nada disso → (1.0, 'ausente').

    O caso 3 é o perigoso e por isso é NOMEADO: até 24/08/2026 o teto lia só a
    chave 1 com `or 1.0`, e contra uma linha do formato antigo saía fator 1,0 em
    silêncio: todo teto ~17% menor sem erro e sem log. Quem consome deve tratar
    'ausente' como defeito, não como default.
    """
    conv = conv or {}
    candidatos = (
        ("tracking", (conv.get("tracking") or {}).get("factor")),
        ("late_purchase_uplift_legado",
         (conv.get("economics") or {}).get("late_purchase_uplift")),
    )
    for procedencia, bruto in candidatos:
        if bruto is None:
            continue
        try:
            f = float(bruto)
        except (TypeError, ValueError):
            logger.warning("[reference_reader] fator de rastreamento ilegível em "
                           "%s: %r (ignorando)", procedencia, bruto)
            continue
        if f <= 0:
            logger.warning("[reference_reader] fator de rastreamento inválido em "
                           "%s (%s), ignorando", procedencia, f)
            continue
        return f, procedencia
    return 1.0, "ausente"


def expected_conversion(calibration: dict, scores) -> "list":
    """Conversão ESPERADA de leads: aplica a curva do calibrador (score→P) por
    interpolação. `scores` é array-like de score_challenger em [0,1]. Devolve a P de
    compra de cada lead — a média disso é a "conversão esperada" de um grupo."""
    import numpy as np
    x = calibration.get("x") or []
    y = calibration.get("y") or []
    if not x or not y:
        return [0.0 for _ in scores]
    return np.interp(np.asarray(scores, dtype=float), x, y).tolist()
