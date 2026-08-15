"""Teto por CHAVE (criativo ou campanha) — o que o push da agência traduz.

O push (`push_scores_zanelato`) é tradutor, não calculadora. Este módulo é a
calculadora: pra cada chave que o push publica, monta a distribuição de decis dos
leads DELA na janela e devolve um `Teto` pronto, com a Decisão 9 inteira dentro:

  campanha  conv = mistura de decis da campanha            (braço público puro)
  criativo  conv = composto lift: mistura de decis do criativo × histórico dele
            (`analytics.criativo_historico`, semanal; estreante cai no prior do
            texto quando existir, senão no modelo puro)

O fator de rastreamento e o valor por venda entram sozinhos pela CalculadoraDeTeto
(lidos do payload da referência). Carimbo completo em cada Teto (referência, fator,
commit, config) → vira a coluna `teto_referencia`.

A distribuição de decis busca a régua pelo run_id NAS DUAS duplas de colunas do
ledger (champion/challenger trocam de papel; ver fix #204).
"""
from __future__ import annotations

import logging
from typing import Optional

from src.data.criativo_historico import le_historico
from src.monitoring.teto import (
    CalculadoraDeTeto, Teto, conversao_prevista_da_unidade, K_HISTORICO_CRIATIVO,
)

logger = logging.getLogger(__name__)

_SQL_DIST = """
SELECT {chave} AS chave,
       CASE WHEN challenger_run_id = :run_id
                 AND decil_challenger IS NOT NULL THEN decil_challenger
            ELSE decil_champion END AS decil,
       count(*) AS n
FROM public.registros_ml
WHERE created_at >= :ws AND created_at < :we
  AND ((challenger_run_id = :run_id AND decil_challenger IS NOT NULL)
    OR (champion_run_id  = :run_id AND decil_champion  IS NOT NULL))
  AND {chave} IS NOT NULL AND {chave} <> ''
GROUP BY 1, 2
"""
_COLUNA = {"creative": "utm_content", "campaign": "utm_campaign"}


def distribuicoes(ledger_conn, *, run_id: str, win_start, win_end) -> dict:
    """{('creative'|'campaign', chave): {'D01': n, ...}} na janela, régua por run_id."""
    out: dict = {}
    for nivel, col in _COLUNA.items():
        rows = ledger_conn.run(_SQL_DIST.format(chave=col), run_id=run_id,
                               ws=win_start, we=win_end)
        for chave, decil, n in rows:
            d = out.setdefault((nivel, str(chave).strip()), {})
            d[f"D{int(decil):02d}"] = d.get(f"D{int(decil):02d}", 0) + int(n)
    logger.info("[teto_por_chave] distribuições: %d chaves", len(out))
    return out


def teto_da_chave(nivel: str, chave: str, dist: Optional[dict],
                  calc: CalculadoraDeTeto, historico: dict) -> Teto:
    """O Teto de uma chave. Campanha = mistura pura; criativo = composto lift.

    O composto entra ANTES da montagem: calculo a conversão do modelo pela mistura,
    aplico a Decisão 9 com o histórico do criativo, e passo a conversão composta de
    volta pela calculadora (que aplica fator, valor por venda, ROAS e carimbos).
    """
    base = calc.por_mistura_de_decis(dist)
    if nivel != "creative" or not base.ok:
        return base
    h = historico.get(chave)
    if not h:
        return base  # estreante sem prior: modelo puro (o slot do texto entra aqui)
    conv_medida = base.conversao / base.fator_rastreamento  # desfaz pra recompor
    if h["leads"] > 0:
        composta = conversao_prevista_da_unidade(
            conv_medida, h["leads"], h["compradores"], h["esperados"],
            k=K_HISTORICO_CRIATIVO)
    elif h.get("prior_conversao"):
        composta = float(h["prior_conversao"])  # o palpite do TEXTO (escala medida)
    else:
        return base
    return calc.de_conversao_medida(composta, origem=f"composto:{chave}")


def tetos_por_chave(analytics_conn, ledger_conn, *, run_id: str,
                    win_start, win_end, client_id: str = "devclub") -> dict:
    """Tudo junto: {(nivel, chave): Teto}. Uma leitura de referência, uma de
    histórico, uma varredura de distribuições — o push só faz lookup."""
    calc = CalculadoraDeTeto.da_referencia(client_id, conn=analytics_conn)
    historico = le_historico(analytics_conn, client_id=client_id)
    dists = distribuicoes(ledger_conn, run_id=run_id,
                          win_start=win_start, win_end=win_end)
    return {k: teto_da_chave(k[0], k[1], d, calc, historico)
            for k, d in dists.items()}
