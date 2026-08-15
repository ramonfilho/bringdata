"""Teto por CHAVE (criativo ou campanha) — o que o push da agência traduz.

O push (`push_scores_zanelato`) é tradutor, não calculadora. Este módulo é a
calculadora, e a UNIDADE da conta é sempre criativo×campanha (Decisão 9):

  unidade   conv = composto lift: mistura de decis DOS LEADS daquele criativo
            naquela campanha × histórico do criativo (`analytics.criativo_historico`;
            estreante cai no prior do texto quando existir, senão no modelo puro)
  criativo  média das unidades DELE, ponderada pelos leads de cada uma
  campanha  média das unidades DELA, ponderada pelos leads de cada uma —
            a conversão esperada da campanha é decis + CRIATIVOS (metodologia
            fixada pelo Ramon em 16/08: mistura de decis pura para campanha é
            ERRADA, porque ignora a mistura de criativos que ela roda; foi o
            que subestimou o teto de 03/08)

O fator de rastreamento e o valor por venda entram sozinhos pela CalculadoraDeTeto
(lidos do payload da referência). Carimbo completo em cada Teto → `teto_referencia`.

A distribuição de decis busca a régua pelo run_id NAS DUAS duplas de colunas do
ledger (champion/challenger trocam de papel; ver fix #204).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from src.data.criativo_historico import le_historico
from src.monitoring.teto import (
    CalculadoraDeTeto, Teto, conversao_prevista_da_unidade, K_HISTORICO_CRIATIVO,
)

logger = logging.getLogger(__name__)

_SQL_UNIDADES = """
SELECT utm_campaign, utm_content,
       CASE WHEN challenger_run_id = :run_id
                 AND decil_challenger IS NOT NULL THEN decil_challenger
            ELSE decil_champion END AS decil,
       count(*) AS n
FROM public.registros_ml
WHERE created_at >= :ws AND created_at < :we
  AND ((challenger_run_id = :run_id AND decil_challenger IS NOT NULL)
    OR (champion_run_id  = :run_id AND decil_champion  IS NOT NULL))
  AND utm_campaign IS NOT NULL AND utm_campaign <> ''
  AND utm_content  IS NOT NULL AND utm_content  <> ''
GROUP BY 1, 2, 3
"""


def unidades(ledger_conn, *, run_id: str, win_start, win_end) -> dict:
    """{(campanha, criativo): {'D01': n, ...}} na janela, régua por run_id."""
    out: dict = {}
    for camp, cria, decil, n in ledger_conn.run(
            _SQL_UNIDADES, run_id=run_id, ws=win_start, we=win_end):
        d = out.setdefault((str(camp).strip(), str(cria).strip()), {})
        k = f"D{int(decil):02d}"
        d[k] = d.get(k, 0) + int(n)
    logger.info("[teto_por_chave] %d unidades criativo×campanha", len(out))
    return out


def _conv_composta_da_unidade(dist: dict, criativo: str,
                              calc: CalculadoraDeTeto,
                              historico: dict) -> Optional[tuple]:
    """(conversão MEDIDA composta, n de leads) da unidade — ou None sem base.

    A composição da Decisão 9, em escala MEDIDA (o fator entra depois, uma vez,
    no funil da calculadora — nunca duas)."""
    base = calc.por_mistura_de_decis(dist)
    if not base.ok:
        return None
    n = sum(dist.values())
    conv = base.conversao / base.fator_rastreamento
    h = historico.get(criativo)
    if h and h["leads"] > 0:
        conv = conversao_prevista_da_unidade(
            conv, h["leads"], h["compradores"], h["esperados"],
            k=K_HISTORICO_CRIATIVO)
    elif h and h.get("prior_conversao"):
        conv = float(h["prior_conversao"])  # o palpite do TEXTO (escala medida)
    return conv, n


def tetos_por_chave(analytics_conn, ledger_conn, *, run_id: str,
                    win_start, win_end, client_id: str = "devclub") -> dict:
    """{('creative'|'campaign', chave): Teto}. Criativo e campanha são as DUAS
    agregações das mesmas unidades, ponderadas por leads — nunca contas de
    naturezas diferentes que possam divergir."""
    calc = CalculadoraDeTeto.da_referencia(client_id, conn=analytics_conn)
    historico = le_historico(analytics_conn, client_id=client_id)
    us = unidades(ledger_conn, run_id=run_id, win_start=win_start, win_end=win_end)

    soma = {"creative": defaultdict(lambda: [0.0, 0]),
            "campaign": defaultdict(lambda: [0.0, 0])}
    for (camp, cria), dist in us.items():
        r = _conv_composta_da_unidade(dist, cria, calc, historico)
        if r is None:
            continue
        conv, n = r
        for nivel, chave in (("creative", cria), ("campaign", camp)):
            soma[nivel][chave][0] += conv * n
            soma[nivel][chave][1] += n
    out = {}
    for nivel, chaves in soma.items():
        for chave, (num, den) in chaves.items():
            if den > 0:
                out[(nivel, chave)] = calc.de_conversao_medida(
                    num / den, origem=f"{nivel}:{chave}")
    logger.info("[teto_por_chave] tetos: %d criativos · %d campanhas",
                sum(1 for k in out if k[0] == "creative"),
                sum(1 for k in out if k[0] == "campaign"))
    return out


def carimbo(t: Teto) -> str:
    """A coluna `teto_referencia` numa string: qual referência, qual fator, qual
    commit geraram o número — ou o MOTIVO de não haver número."""
    if not t.ok:
        return f"sem_teto:{t.motivo}"
    c = (t.codigo or {}).get("commit") or "?"
    return f"{t.referencia_id}·fator{t.fator_rastreamento:.4f}·{str(c)[:7]}"
