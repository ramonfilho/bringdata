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
       coalesce(utm_medium, '') AS conjunto,
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
GROUP BY 1, 2, 3, 4
"""


def unidades_finas(ledger_conn, *, run_id: str, win_start, win_end) -> dict:
    """{(campanha, conjunto, criativo): {'D01': n, ...}} na janela.

    O conjunto de anúncios vem da `utm_medium` ({{adset.name}} no template do
    cliente). É o grão MAIS FINO que o lead permite: o mesmo anúncio na mesma
    campanha pode rodar em dois conjuntos = dois públicos, e fundir os dois num
    número só esconde qual público sustenta o teto (Ramon, 18/08)."""
    out: dict = {}
    for camp, cria, conj, decil, n in ledger_conn.run(
            _SQL_UNIDADES, run_id=run_id, ws=win_start, we=win_end):
        d = out.setdefault((str(camp).strip(), str(conj or "").strip(),
                            str(cria).strip()), {})
        k = f"D{int(decil):02d}"
        d[k] = d.get(k, 0) + int(n)
    logger.info("[teto_por_chave] %d unidades campanha×conjunto×criativo", len(out))
    return out


def _agrega_finas(finas: dict) -> dict:
    """Soma as distribuições de decis dos conjuntos → grão criativo×campanha.
    Uma base só: `unidades` e `tetos_completos` consomem daqui (não duplicar)."""
    out: dict = {}
    for (camp, _conj, cria), dist in finas.items():
        d = out.setdefault((camp, cria), {})
        for k, n in dist.items():
            d[k] = d.get(k, 0) + n
    return out


def unidades(ledger_conn, *, run_id: str, win_start, win_end) -> dict:
    """{(campanha, criativo): {'D01': n, ...}} na janela, régua por run_id.

    Agrega as finas somando a distribuição de decis — o resultado é IDÊNTICO ao
    que esta função devolvia antes do grão de conjunto existir (mesma soma)."""
    out = _agrega_finas(unidades_finas(
        ledger_conn, run_id=run_id, win_start=win_start, win_end=win_end))
    logger.info("[teto_por_chave] %d unidades criativo×campanha", len(out))
    return out


def _eh_google(campanha: str, criativo: str) -> bool:
    """Unidade do Google: a UTM de lá chega com campanha genérica 'devlf' e/ou
    o criativo como ID numérico do ValueTrack."""
    return (str(campanha) == "devlf"
            or (str(criativo).isdigit() and len(str(criativo)) >= 10))


def _conv_composta_da_unidade(dist: dict, criativo: str,
                              calc: CalculadoraDeTeto,
                              historico: dict,
                              campanha: str = "") -> Optional[tuple]:
    """(conversão MEDIDA composta, n de leads) da unidade — ou None sem base.

    A composição da Decisão 9, em escala MEDIDA (o fator entra depois, uma vez,
    no funil da calculadora — nunca duas)."""
    base = calc.por_mistura_de_decis(dist)
    if not base.ok:
        return None
    n = sum(dist.values())
    conv = base.conversao / base.fator_rastreamento
    # NOTA POR PLATAFORMA (Ramon, 18/08): antes da composição com o histórico,
    # a mistura de decis de unidade google sobe pelo lift MEDIDO (a régua
    # inteira sobe igual; quem diferencia criativo lá dentro é o histórico).
    if _eh_google(campanha, criativo):
        conv *= calc.lift_da_plataforma("google")
    h = historico.get(criativo)
    if h and h["leads"] > 0:
        conv = conversao_prevista_da_unidade(
            conv, h["leads"], h["compradores"], h["esperados"],
            k=K_HISTORICO_CRIATIVO)
    elif h and h.get("prior_conversao"):
        conv = float(h["prior_conversao"])  # o palpite do TEXTO (escala medida)
    return conv, n


def tetos_completos(analytics_conn, ledger_conn, *, run_id: str,
                    win_start, win_end, client_id: str = "devclub") -> tuple:
    """(por_chave, por_unidade, por_conjunto) numa passada só das MESMAS unidades.

    por_chave: {('creative'|'campaign', chave): Teto} — as duas agregações.
    por_unidade: lista de {campanha, criativo, n, pct, teto} — o GRÃO DO PRODUTO
    (o mesmo criativo pode ter um teto numa campanha e outro na outra; é essa
    linha que o gestor usa pra decidir, Ramon 16/08).
    por_conjunto: lista de {campanha, conjunto, criativo, n, pct, teto} — o
    grão por PÚBLICO (18/08): quem publica decide quando exibir (o push só
    mostra quando o anúncio roda em 2+ conjuntos na mesma campanha)."""
    calc = CalculadoraDeTeto.da_referencia(client_id, conn=analytics_conn)
    historico = le_historico(analytics_conn, client_id=client_id)
    finas = unidades_finas(ledger_conn, run_id=run_id,
                           win_start=win_start, win_end=win_end)
    # O grão criativo×campanha continua calculado da distribuição SOMADA (mesma
    # conta de antes do conjunto existir — os números publicados não mudam).
    us = _agrega_finas(finas)

    por_unidade = []
    soma = {"creative": defaultdict(lambda: [0.0, 0]),
            "campaign": defaultdict(lambda: [0.0, 0])}
    for (camp, cria), dist in us.items():
        r = _conv_composta_da_unidade(dist, cria, calc, historico, campanha=camp)
        if r is None:
            continue
        conv, n = r
        topo = dist.get("D09", 0) + dist.get("D10", 0)
        por_unidade.append(dict(
            campanha=camp, criativo=cria, n=n,
            pct=(100.0 * topo / n) if n else 0.0,
            teto=calc.de_conversao_medida(conv, origem=f"unit:{cria}@{camp}")))
        for nivel, chave in (("creative", cria), ("campaign", camp)):
            soma[nivel][chave][0] += conv * n
            soma[nivel][chave][1] += n
    out = {}
    for nivel, chaves in soma.items():
        for chave, (num, den) in chaves.items():
            if den > 0:
                out[(nivel, chave)] = calc.de_conversao_medida(
                    num / den, origem=f"{nivel}:{chave}")

    # O grão do CONJUNTO: mesma composição da Decisão 9, com a distribuição de
    # decis SÓ daquele conjunto (o histórico do criativo é o mesmo — o prior é
    # por criativo, não por público).
    por_conjunto = []
    for (camp, conj, cria), dist in finas.items():
        r = _conv_composta_da_unidade(dist, cria, calc, historico, campanha=camp)
        if r is None:
            continue
        conv, n = r
        topo = dist.get("D09", 0) + dist.get("D10", 0)
        por_conjunto.append(dict(
            campanha=camp, conjunto=conj, criativo=cria, n=n,
            pct=(100.0 * topo / n) if n else 0.0,
            teto=calc.de_conversao_medida(
                conv, origem=f"adset:{cria}@{conj}@{camp}")))
    logger.info("[teto_por_chave] tetos: %d criativos · %d campanhas · %d unidades "
                "· %d unidades-conjunto",
                sum(1 for k in out if k[0] == "creative"),
                sum(1 for k in out if k[0] == "campaign"), len(por_unidade),
                len(por_conjunto))
    return out, por_unidade, por_conjunto


def tetos_por_chave(analytics_conn, ledger_conn, *, run_id: str,
                    win_start, win_end, client_id: str = "devclub") -> dict:
    """Compat: só as agregações. Ver `tetos_completos`."""
    return tetos_completos(analytics_conn, ledger_conn, run_id=run_id,
                           win_start=win_start, win_end=win_end,
                           client_id=client_id)[0]  # [0] segue valendo no trio


def carimbo(t: Teto) -> str:
    """A coluna `teto_referencia` numa string: qual referência, qual fator, qual
    commit geraram o número — ou o MOTIVO de não haver número."""
    if not t.ok:
        return f"sem_teto:{t.motivo}"
    c = (t.codigo or {}).get("commit") or "?"
    return f"{t.referencia_id}·fator{t.fator_rastreamento:.4f}·{str(c)[:7]}"
