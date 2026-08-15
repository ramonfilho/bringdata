"""TRAVA DE ORDENAÇÃO do teto por unidade (criativo × campanha) — Decisão 7.

O portão que roda ANTES de popular as colunas de teto e antes de cada mudança que
altere o valor entregue. Julga ORDEM, não nível: dentro de um lançamento, taxa de
rastreamento e valor por venda multiplicam todas as unidades pelo mesmo fator, então
a ordenação é imune às duas constantes — e é a decisão que o gestor toma ("qual
unidade merece o próximo real").

Consome as MESMAS funções de produção que entregam o teto (não uma reimplementação):
  - `CalculadoraDeTeto.por_mistura_de_decis` — o braço "público" (mistura de decis
    da campanha na referência rolante)
  - `conversao_prevista_da_unidade` — a fórmula lift da Decisão 9 (K=2000)

Regra de ouro: o histórico do criativo usa só lançamentos ANTERIORES ao julgado.

Vereditos e critério de PASSAGEM (exit 0 = passou; 1 = reprovou):
  A. Spearman previsto×realizado por lançamento: composto > 0 e >= só-modelo
  B. campanhas com 3+ criativos: "evita o desastre" (o previsto-pior nunca é o
     melhor real) >= 90%
  C. terços empilhados: razão do composto >= a do só-modelo

Referência de calibração (14-15/08/2026, 534 unidades, 26 lançamentos):
  modelo ρ+0,29 · composto ρ+0,37-0,39 · melhor-da-campanha 46-50% (chute 29%) ·
  evita-desastre 96% · terços 2,25-2,33x. Queda relevante contra esses números é
  sinal de regressão mesmo com o portão formalmente verde.

Rodável:  python -m scripts.trava_ordenacao_teto            (janela toda)
          python -m scripts.trava_ordenacao_teto --min-leads 100 --k 2000
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, wilcoxon

from src.data.analytics_connection import open_analytics_connection
from src.data.ledger_connection import open_ledger_read_connection
from src.data.reference_reader import read_rolling_reference
from src.monitoring.teto import (
    CalculadoraDeTeto, conversao_prevista_da_unidade, K_HISTORICO_CRIATIVO,
)

MIN_UNIDADES_LF = 5


def _t8(t):
    d = "".join(c for c in str(t or "") if c.isdigit())
    return d[-8:] if len(d) >= 8 else None


def _campaign_id(u):
    s = str(u or "").split("|")[-1].strip()
    return s if s.isdigit() and len(s) >= 10 else None


def carrega_unidades(min_leads: int) -> pd.DataFrame:
    """Unidades criativo×campanha dos lançamentos FECHADOS, com o realizado (compra
    da captação até o vendas_end do lançamento, a regra do calendário) e os insumos
    de previsão: mistura de decis da campanha + histórico do criativo até ali."""
    an = open_analytics_connection(timeout=900)
    try:
        cal = {r[0]: r[1:] for r in an.run(
            "SELECT lf_name, cap_start, cap_end, vendas_start, vendas_end "
            "FROM launch_calendar WHERE client_id='devclub' "
            "  AND vendas_end IS NOT NULL AND vendas_end < CURRENT_DATE")}
        cap = an.run(
            "SELECT lf, utm_content, utm_campaign, lower(trim(email)), phone, captured_at "
            "FROM captacoes WHERE lf IS NOT NULL AND utm_content IS NOT NULL "
            "AND email IS NOT NULL")
        ven = an.run("SELECT lower(trim(email)), phone, sale_date FROM sales "
                     "WHERE sale_date IS NOT NULL")
        ref = read_rolling_reference("devclub", conn=an)
    finally:
        an.close()
    lg = open_ledger_read_connection()
    try:
        dec = {r[0]: r[1] for r in lg.run(
            "SELECT lower(email), decil FROM registros_ml WHERE decil IS NOT NULL")}
    finally:
        lg.close()

    v = pd.DataFrame(ven, columns=["email", "tel", "dt"])
    v["dt"] = pd.to_datetime(v["dt"], errors="coerce").dt.tz_localize(None)
    v["t8"] = v["tel"].map(_t8)
    por_email = v.dropna(subset=["email"]).groupby("email")["dt"].apply(list).to_dict()
    por_t8 = v.dropna(subset=["t8"]).groupby("t8")["dt"].apply(list).to_dict()

    d = pd.DataFrame(cap, columns=["lf", "criativo", "campanha", "email", "tel", "cap_dt"])
    d = d[d["lf"].isin(cal)].drop_duplicates(["lf", "criativo", "email"])
    d["criativo"] = d["criativo"].astype(str).str.strip()
    d["cap_dt"] = pd.to_datetime(d["cap_dt"], errors="coerce").dt.tz_localize(None)
    d = d.dropna(subset=["cap_dt"])
    limite = {lf: pd.Timestamp(c[3]) + pd.Timedelta(days=1) for lf, c in cal.items()}
    d["buy"] = [int(any(c0 <= s <= limite[lf]
                        for s in (por_email.get(e, []) + por_t8.get(_t8(t), []))))
                for lf, e, t, c0 in zip(d["lf"], d["email"], d["tel"], d["cap_dt"])]
    d["decil"] = d["email"].map(dec)
    d["cid"] = d["campanha"].map(_campaign_id)

    ordem = sorted(cal, key=lambda s: cal[s][0])
    conv_lf = {lf: d[d["lf"] == lf]["buy"].mean() for lf in ordem}

    # histórico do criativo ATÉ cada lançamento: leads, compradores e compradores
    # ESPERADOS na média da época (o denominador do lift da Decisão 9)
    acum = defaultdict(lambda: [0, 0, 0.0])
    hist_ate = {}
    for lf in ordem:
        g = d[d["lf"] == lf]
        for cr in g["criativo"].unique():
            hist_ate[(lf, cr)] = tuple(acum[cr])
        for cr, s in g.groupby("criativo"):
            acum[cr][0] += len(s)
            acum[cr][1] += int(s["buy"].sum())
            acum[cr][2] += len(s) * conv_lf[lf]

    calc = CalculadoraDeTeto.de_referencia_carregada(ref)
    linhas = []
    for (lf, cid, cr), sub in d[d["cid"].notna()].groupby(["lf", "cid", "criativo"]):
        if len(sub) < min_leads:
            continue
        dist = sub["decil"].dropna().astype(int).value_counts().to_dict()
        t = calc.por_mistura_de_decis({f"D{k:02d}": vv for k, vv in dist.items()})
        if not t.ok:
            continue
        nh, kh, esperados = hist_ate.get((lf, cr), (0, 0, 0.0))
        linhas.append(dict(
            lf=lf, cid=cid, criativo=cr, n=len(sub), buys=int(sub["buy"].sum()),
            real=sub["buy"].mean(), ordem=ordem.index(lf),
            p_modelo=t.conversao,
            p_composto=conversao_prevista_da_unidade(
                t.conversao, nh, kh, esperados, k=K_HISTORICO_CRIATIVO),
        ))
    x = pd.DataFrame(linhas)
    print(f"[trava] {len(d):,} leads · {int(d['buy'].sum()):,} compradores · "
          f"{len(x)} unidades ({min_leads}+ leads) · {x['lf'].nunique()} lançamentos · "
          f"referência {calc.referencia_as_of}")
    return x


def veredito(x: pd.DataFrame) -> bool:
    rhos = {"p_modelo": [], "p_composto": []}
    pesos = []
    for lf, s in x.groupby("lf"):
        if len(s) < MIN_UNIDADES_LF:
            continue
        for col in rhos:
            r = spearmanr(s[col], s["real"]).statistic
            rhos[col].append(0.0 if np.isnan(r) else r)
        pesos.append(len(s))
    rho_m = float(np.mean(rhos["p_modelo"]))
    rho_c = float(np.mean(rhos["p_composto"]))
    dif = np.array(rhos["p_composto"]) - np.array(rhos["p_modelo"])
    p_wx = float(wilcoxon(dif).pvalue) if np.any(dif != 0) else 1.0

    ac = tot = evita = 0
    for (lf, cid), s in x.groupby(["lf", "cid"]):
        if len(s) < 3 or s["real"].nunique() < 2:
            continue
        tot += 1
        melhor = s["real"].idxmax()
        ac += int(s["p_composto"].idxmax() == melhor)
        evita += int(s["p_composto"].idxmin() != melhor)

    def _tercos(col):
        fat = {0: [0, 0], 2: [0, 0]}
        for lf, s in x.groupby("lf"):
            if len(s) < MIN_UNIDADES_LF:
                continue
            q = pd.qcut(s[col].rank(method="first"), 3, labels=False)
            for terc, ss in s.groupby(q):
                if int(terc) in fat:
                    fat[int(terc)][0] += int(ss["n"].sum())
                    fat[int(terc)][1] += int(ss["buys"].sum())
        lo = fat[0][1] / fat[0][0] if fat[0][0] else np.nan
        hi = fat[2][1] / fat[2][0] if fat[2][0] else np.nan
        return hi / lo if lo else np.nan

    t_m, t_c = _tercos("p_modelo"), _tercos("p_composto")

    print(f"\nA. Spearman médio por lançamento: modelo {rho_m:+.3f} · "
          f"composto {rho_c:+.3f} (Wilcoxon p={p_wx:.3f}, n={len(dif)} lançamentos)")
    print(f"B. campanhas 3+ criativos (n={tot}): aponta o melhor {100*ac/tot:.0f}% · "
          f"evita o desastre {100*evita/tot:.0f}%")
    print(f"C. terços (melhor÷pior): modelo {t_m:.2f}x · composto {t_c:.2f}x")

    criterios = [
        ("composto ordena (ρ > 0)", rho_c > 0),
        ("composto >= só-modelo em ρ", rho_c >= rho_m - 1e-9),
        ("evita o desastre >= 90%", tot > 0 and evita / tot >= 0.90),
        ("terços do composto >= só-modelo", t_c >= t_m - 1e-9),
    ]
    passou = all(ok for _, ok in criterios)
    print("\nCRITÉRIOS:")
    for nome, ok in criterios:
        print(f"  [{'PASS' if ok else 'FAIL'}] {nome}")
    print(f"\nVEREDITO: {'PASSOU' if passou else 'REPROVOU'}")
    return passou


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-leads", type=int, default=100,
                    help="piso de leads por unidade (default 100)")
    args = ap.parse_args()
    x = carrega_unidades(args.min_leads)
    if x.empty:
        print("[trava] sem unidades — não há o que julgar; REPROVA por segurança.")
        return 1
    return 0 if veredito(x) else 1


if __name__ == "__main__":
    sys.exit(main())
