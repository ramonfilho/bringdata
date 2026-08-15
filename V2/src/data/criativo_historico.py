"""Histórico maduro por CRIATIVO — a memória que alimenta a fórmula da unidade.

A fórmula lift (Decisão 9, `conversao_prevista_da_unidade`) precisa, por criativo:
  leads        quantos leads maduros ele já trouxe (lançamentos FECHADOS)
  compradores  quantos compraram dentro da janela do lançamento deles
  esperados    quantos teriam comprado se o criativo fosse MÉDIO na época de cada
               lançamento (Σ leads_no_lançamento × conversão geral do lançamento) —
               o denominador do lift, que tira o efeito de o mercado subir/descer

Recalcular isso do zero custa ~4 min de banco (315k leads × vendas). O push da
agência roda de hora em hora, e o histórico só muda quando um lançamento FECHA
(a compra conta até o vendas_end) — relógio semanal, o mesmo da referência
rolante. Então: o refresh semanal GRAVA aqui, o push só LÊ.

A tabela é também a CASA DO TEXTO (item 5 do plano): `prior_conversao` e
`prior_fonte` são o palpite do estreante, NULL até o módulo de transcrição
existir. O refresh semanal NUNCA toca nessas duas colunas — elas pertencem ao
módulo do texto, e sobrescrever no upsert apagaria o palpite toda segunda.

Reversível: tabela nova, aditiva; nenhum consumidor existente muda.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

TABELA = "criativo_historico"

# DDL aditivo, aplicado com lock_timeout (regra da casa pra DDL no analytics).
# PK (client_id, criativo): 1 linha por criativo por cliente.
DDL = f"""
SET lock_timeout = '5s';
CREATE TABLE IF NOT EXISTS {TABELA} (
    client_id        text        NOT NULL,
    criativo         text        NOT NULL,
    leads            integer     NOT NULL DEFAULT 0,
    compradores      integer     NOT NULL DEFAULT 0,
    esperados        numeric     NOT NULL DEFAULT 0,
    lancamentos      integer     NOT NULL DEFAULT 0,
    prior_conversao  numeric     NULL,
    prior_fonte      text        NULL,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, criativo)
);
"""

_UPSERT = f"""
INSERT INTO {TABELA} (client_id, criativo, leads, compradores, esperados,
                      lancamentos, updated_at)
VALUES (:client_id, :criativo, :leads, :compradores, :esperados, :lancamentos, now())
ON CONFLICT (client_id, criativo) DO UPDATE SET
    leads = EXCLUDED.leads,
    compradores = EXCLUDED.compradores,
    esperados = EXCLUDED.esperados,
    lancamentos = EXCLUDED.lancamentos,
    updated_at = EXCLUDED.updated_at
"""
# prior_conversao/prior_fonte ficam FORA do upsert de propósito (ver docstring).


def _t8(t) -> Optional[str]:
    d = "".join(c for c in str(t or "") if c.isdigit())
    return d[-8:] if len(d) >= 8 else None


def calcula_historico(conn, client_id: str = "devclub") -> pd.DataFrame:
    """Acumulado por criativo sobre TODOS os lançamentos fechados.

    A compra conta da captação até o `vendas_end` do lançamento do lead (a regra
    do calendário, a mesma da referência e da trava). Lançamento aberto fica fora
    inteiro: ele ainda não é história.
    """
    # `vendas_end < hoje - 2`: a folga de 2 dias cobre o atraso de ingestão da
    # analytics.sales (~1 dia). Sem ela, lançamento que fecha no domingo entraria na
    # segunda com as vendas do fim de semana ainda fora do banco e ficaria uma semana
    # subcontado. A entrada é POR LANÇAMENTO FECHADO, nunca por idade do lead — um
    # ciclo longo (LF45, 33d) entra inteiro e maduro de uma vez, ou não entra.
    cal = {r[0]: r[1:] for r in conn.run(
        "SELECT lf_name, cap_start, cap_end, vendas_start, vendas_end "
        "FROM launch_calendar WHERE client_id = :c "
        "  AND vendas_end IS NOT NULL AND vendas_end < CURRENT_DATE - 2",
        c=client_id)}
    if not cal:
        logger.warning("[criativo_historico] calendário vazio — nada a acumular")
        return pd.DataFrame(columns=["criativo", "leads", "compradores",
                                     "esperados", "lancamentos"])
    cap = conn.run(
        "SELECT lf, utm_content, lower(trim(email)), phone, captured_at "
        "FROM captacoes WHERE lf IS NOT NULL AND utm_content IS NOT NULL "
        "AND email IS NOT NULL")
    ven = conn.run("SELECT lower(trim(email)), phone, sale_date FROM sales "
                   "WHERE sale_date IS NOT NULL")

    v = pd.DataFrame(ven, columns=["email", "tel", "dt"])
    v["dt"] = pd.to_datetime(v["dt"], errors="coerce").dt.tz_localize(None)
    v["t8"] = v["tel"].map(_t8)
    por_email = v.dropna(subset=["email"]).groupby("email")["dt"].apply(list).to_dict()
    por_t8 = v.dropna(subset=["t8"]).groupby("t8")["dt"].apply(list).to_dict()

    d = pd.DataFrame(cap, columns=["lf", "criativo", "email", "tel", "cap_dt"])
    d = d[d["lf"].isin(cal)].drop_duplicates(["lf", "criativo", "email"])
    d["criativo"] = d["criativo"].astype(str).str.strip()
    d["cap_dt"] = pd.to_datetime(d["cap_dt"], errors="coerce").dt.tz_localize(None)
    d = d.dropna(subset=["cap_dt"])
    limite = {lf: pd.Timestamp(c[3]) + pd.Timedelta(days=1) for lf, c in cal.items()}
    d["buy"] = [int(any(c0 <= s <= limite[lf]
                        for s in (por_email.get(e, []) + por_t8.get(_t8(t), []))))
                for lf, e, t, c0 in zip(d["lf"], d["email"], d["tel"], d["cap_dt"])]

    conv_lf = d.groupby("lf")["buy"].mean().to_dict()
    acum = defaultdict(lambda: [0, 0, 0.0, 0])
    for (lf, cr), s in d.groupby(["lf", "criativo"]):
        a = acum[cr]
        a[0] += len(s)
        a[1] += int(s["buy"].sum())
        a[2] += len(s) * conv_lf[lf]
        a[3] += 1
    out = pd.DataFrame(
        [dict(criativo=cr, leads=a[0], compradores=a[1],
              esperados=round(a[2], 4), lancamentos=a[3])
         for cr, a in acum.items()])
    logger.info("[criativo_historico] %d criativos · %d lançamentos fechados · "
                "%d leads · %d compradores", len(out), len(cal),
                int(out["leads"].sum()), int(out["compradores"].sum()))
    return out


def grava_historico(conn, historico: pd.DataFrame, client_id: str = "devclub") -> int:
    """Upsert do acumulado. Fail-loud se vier vazio: histórico zerado em produção é
    fonte quebrada, não estado válido (há 26 lançamentos fechados na base)."""
    assert historico is not None and not historico.empty, \
        "[criativo_historico] acumulado vazio — fonte quebrada, não gravar"
    for stmt in DDL.strip().split(";"):
        if stmt.strip():
            conn.run(stmt)
    n = 0
    for r in historico.itertuples(index=False):
        conn.run(_UPSERT, client_id=client_id, criativo=r.criativo,
                 leads=int(r.leads), compradores=int(r.compradores),
                 esperados=float(r.esperados), lancamentos=int(r.lancamentos))
        n += 1
    logger.info("[criativo_historico] %d criativos gravados", n)
    return n


def le_historico(conn, client_id: str = "devclub") -> dict:
    """{criativo: {leads, compradores, esperados, prior_conversao, prior_fonte}} —
    o que o push consome. Tabela ausente devolve {} (o consumidor degrada pro
    modelo puro, que é o comportamento sem histórico)."""
    try:
        rows = conn.run(
            f"SELECT criativo, leads, compradores, esperados, prior_conversao, "
            f"prior_fonte FROM {TABELA} WHERE client_id = :c", c=client_id)
    except Exception as e:  # tabela ainda não criada neste ambiente
        logger.warning("[criativo_historico] leitura falhou (%s) — degradando pra "
                       "sem histórico", e)
        return {}
    return {r[0]: {"leads": int(r[1]), "compradores": int(r[2]),
                   "esperados": float(r[3]),
                   "prior_conversao": (float(r[4]) if r[4] is not None else None),
                   "prior_fonte": r[5]}
            for r in rows}
