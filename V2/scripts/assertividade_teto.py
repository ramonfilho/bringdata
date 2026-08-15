"""ASSERTIVIDADE DO TETO no grão criativo×campanha, com CAIXA REAL (passo 3).

A pergunta do Ramon: quando apontamos um teto, pagar abaixo dele gerou lucro?
Pagar acima gerou prejuízo?

Desenho acordado (16/08):
  - Unidade = criativo×campanha num lançamento fechado. Gasto REAL da unidade vem
    de analytics.ad_insights (ad_id×campaign_id×dia), casado por criativo_id_map.
  - TUDO fora do tempo: pra julgar o lançamento L, o mapa de conversão por decil,
    o valor por venda, o fator de rastreamento e o histórico do criativo usam SÓ
    lançamentos fechados ANTES de L.
  - DISCRIMINAÇÃO dentro do lançamento: unidades que pagaram CPL <= teto vs > teto
    do MESMO lançamento (a maré afeta os dois grupos igual). Num lançamento todo
    ruim vira "quem perdeu menos" — e continua respondível.
  - CALIBRAÇÃO entre lançamentos: o nível do teto acompanhou as épocas
    (termostato com atraso declarado: lê a época pelos lançamentos anteriores).
  - A matriz simples aparece POR lançamento, nunca agregada crua.

ROAS realizado da unidade = compradores casados (regra do calendário) × valor por
venda da época × fator da época ÷ gasto real. O fator entra igual nos dois lados
(teto e ROAS), então não fabrica vitória: só corrige o nível dos dois juntos.
"""
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

V2 = Path("/Users/ramonmoreira/Desktop/bring_data/V2")
sys.path.insert(0, str(V2))
from dotenv import load_dotenv
load_dotenv(V2 / ".env")

from src.data.analytics_connection import open_analytics_connection  # noqa: E402
from src.data.ledger_connection import open_ledger_read_connection  # noqa: E402
from src.core.payment_method import forma_pagamento, CARTAO  # noqa: E402

ROAS_ALVO = 2.0
K = 2000
MIN_LEADS, MIN_GASTO = 100, 300.0
MIN_UNIDADES_LF = 6


def t8(t):
    d = "".join(c for c in str(t or "") if c.isdigit())
    return d[-8:] if len(d) >= 8 else None


def cid_de(u):
    x = str(u or "").split("|")[-1].strip()
    return x if x.isdigit() and len(x) >= 10 else None


an = open_analytics_connection(timeout=900)
try:
    cal = {r[0]: r[1:] for r in an.run(
        "SELECT lf_name, cap_start, cap_end, vendas_start, vendas_end FROM launch_calendar "
        "WHERE client_id='devclub' AND vendas_end IS NOT NULL AND vendas_end < CURRENT_DATE")}
    cap = an.run("SELECT lf, utm_content, utm_campaign, lower(trim(email)), phone, captured_at "
                 "FROM captacoes WHERE lf IS NOT NULL AND utm_content IS NOT NULL "
                 "AND email IS NOT NULL")
    ven = an.run("SELECT lower(trim(email)), phone, sale_date, gateway FROM sales "
                 "WHERE sale_date IS NOT NULL")
    ads = an.run("SELECT ad_id, ad_name, campaign_id, insight_date, spend FROM ad_insights")
    cad = an.run("SELECT lower(trim(email)), phone FROM cadastros WHERE email IS NOT NULL")
finally:
    an.close()
lg = open_ledger_read_connection()
try:
    dec = {r[0]: r[1] for r in lg.run(
        "SELECT lower(email), decil FROM registros_ml WHERE decil IS NOT NULL")}
    for em, dz in lg.run(
        "SELECT lower(email), (substring(decil_challenger from 2))::int "
        "FROM scores_historicos WHERE challenger_run_id LIKE '5d158f0a%' "
        "AND decil_challenger ~ '^D[0-9]+$'"):
        dec.setdefault(em, dz)   # ledger vence; a ponte cobre o passado
finally:
    lg.close()

# vendas indexadas
v = pd.DataFrame(ven, columns=["email", "tel", "dt", "gw"])
v["dt"] = pd.to_datetime(v["dt"], errors="coerce").dt.tz_localize(None)
v["t8"] = v["tel"].map(t8)
pe = v.dropna(subset=["email"]).groupby("email").apply(
    lambda s: list(zip(s["dt"], s["gw"]))).to_dict()
pt = v.dropna(subset=["t8"]).groupby("t8").apply(
    lambda s: list(zip(s["dt"], s["gw"]))).to_dict()

# leads com compra pela regra do calendário (+ gateway da 1ª compra na janela)
d = pd.DataFrame(cap, columns=["lf", "criativo", "campanha", "email", "tel", "cap_dt"])
d = d[d["lf"].isin(cal)].drop_duplicates(["lf", "criativo", "email"])
d["criativo"] = d["criativo"].astype(str).str.strip()
d["cap_dt"] = pd.to_datetime(d["cap_dt"], errors="coerce").dt.tz_localize(None)
d = d.dropna(subset=["cap_dt"])
lim = {lf: pd.Timestamp(c[3]) + pd.Timedelta(days=1) for lf, c in cal.items()}
buys, gws = [], []
for lf, e, t, c0 in zip(d["lf"], d["email"], d["tel"], d["cap_dt"]):
    ok = sorted([(s, g) for s, g in (pe.get(e, []) + pt.get(t8(t), []))
                 if c0 <= s <= lim[lf]])
    buys.append(int(bool(ok)))
    gws.append(ok[0][1] if ok else None)
d["buy"], d["gw"] = buys, gws
d["decil"] = d["email"].map(dec)
d["cid"] = d["campanha"].map(cid_de)
print(f"{len(d):,} leads · {int(d['buy'].sum()):,} compradores casados")

# fator por lançamento (decomposição das vendas da janela de vendas)
cad_df = pd.DataFrame(cad, columns=["email", "tel"])
cad_em = set(cad_df["email"].dropna())
cad_t8 = {t8(x) for x in cad_df["tel"] if t8(x)}
cap_em = set(d["email"].dropna())
cap_t8 = {t8(x) for x in d["tel"] if t8(x)}
fator_lf = {}
for lf, c in cal.items():
    vi, vf = pd.Timestamp(c[2]), pd.Timestamp(c[3]) + pd.Timedelta(days=1)
    jan = v[(v["dt"] >= vi) & (v["dt"] < vf)].drop_duplicates(["email"])
    if len(jan) < 30:
        continue
    em_lf = set(d[d["lf"] == lf]["email"])
    t8_lf = {t8(x) for x in d[d["lf"] == lf]["tel"] if t8(x)}
    cas = con = sum_ = 0
    for em, tt in zip(jan["email"], jan["t8"]):
        if (em in em_lf) or (tt and tt in t8_lf):
            cas += 1
        elif (em in cad_em) or (em in cap_em) or (tt and (tt in cad_t8 or tt in cap_t8)):
            con += 1
        else:
            sum_ += 1
    if cas >= 20:
        fator_lf[lf] = dict(cas=cas, sum=sum_)

# gasto por unidade: nome->ad_id (id_map) e ad_insights por dia
adf = pd.DataFrame(ads, columns=["ad_id", "ad_name", "cid", "dia", "spend"])
adf["dia"] = pd.to_datetime(adf["dia"], errors="coerce")
def _norm(x):
    return " ".join(str(x or "").split()).casefold()

nome2ad = defaultdict(set)
for ad_id, nome in adf[["ad_id", "ad_name"]].drop_duplicates().itertuples(index=False):
    if nome:
        nome2ad[_norm(nome)].add(ad_id)
gasto_idx = adf.groupby(["ad_id", "cid", "dia"])["spend"].sum()


def gasto_unidade(lf, cid, criativo):
    cs, ce = pd.Timestamp(cal[lf][0]), pd.Timestamp(cal[lf][1])
    total = 0.0
    alvo = nome2ad.get(_norm(criativo), set())
    cru = str(criativo).strip()
    if cru.isdigit() and len(cru) >= 10:
        alvo = alvo | {cru}   # macro do nome falhou e o utm trouxe o ad_id
    for ad in alvo:
        try:
            s = gasto_idx.loc[ad, cid]
        except KeyError:
            continue
        total += float(s[(s.index >= cs) & (s.index <= ce)].sum())
    return total


ordem = sorted(cal, key=lambda s: cal[s][0])


def monta_epoca(janela_dias):
    """Insumos de NÍVEL (mapa/geral/vps/fator) dos lançamentos anteriores dentro
    da janela; histórico do criativo fica acumulado (a ordem é estável)."""
    epoca = {}
    hist = defaultdict(lambda: [0, 0, 0.0])
    for i, lf in enumerate(ordem):
        cs_l = pd.Timestamp(cal[lf][0])
        dec_ac = defaultdict(lambda: [0, 0]); vps_ac = [0, 0]; fat_ac = [0, 0]
        for lp in ordem[:i]:
            if janela_dias and (cs_l - pd.Timestamp(cal[lp][0])).days > janela_dias:
                continue
            gp = d[d["lf"] == lp]
            gd = gp.dropna(subset=["decil"])
            for dc, sx in gd.groupby(gd["decil"].astype(int)):
                dec_ac[int(dc)][0] += len(sx); dec_ac[int(dc)][1] += int(sx["buy"].sum())
            for gw in gp[gp["buy"] == 1]["gw"]:
                if forma_pagamento(gw) == CARTAO: vps_ac[0] += 1
                else: vps_ac[1] += 1
            if lp in fator_lf:
                fat_ac[0] += fator_lf[lp]["cas"]; fat_ac[1] += fator_lf[lp]["sum"]
        mapa = {k: (b / n if n >= 300 else None) for k, (n, b) in dec_ac.items()}
        tn = sum(n for n, _ in dec_ac.values()); tb = sum(b for _, b in dec_ac.values())
        epoca[lf] = dict(mapa=mapa, geral=(tb / tn if tn else None),
            vps=(2000*vps_ac[0]+1000*vps_ac[1])/(vps_ac[0]+vps_ac[1]) if (vps_ac[0]+vps_ac[1])>=30 else 1350.0,
            fator=max(1.0,(fat_ac[0]+fat_ac[1])/fat_ac[0]) if fat_ac[0]>=100 else 1.2,
            hist={cr: tuple(a) for cr, a in hist.items()})
        g = d[d["lf"] == lf]; conv_lf = g["buy"].mean()
        for cr, sx in g.groupby("criativo"):
            hist[cr][0] += len(sx); hist[cr][1] += int(sx["buy"].sum()); hist[cr][2] += len(sx)*conv_lf
    return epoca

_OLD_BELOW = True

from scipy.stats import spearmanr

for rot, jan in (("90 dias", 90),):
    epoca = monta_epoca(jan)
    rows, funil = [], defaultdict(int)
    for (lf, cid, cr), sub in d[d["cid"].notna()].groupby(["lf", "cid", "criativo"]):
        if len(sub) < MIN_LEADS: continue
        funil["100+ leads"] += 1
        ep = epoca[lf]
        if not ep["geral"]: funil["sem época"] += 1; continue
        sp = gasto_unidade(lf, cid, cr)
        if sp < MIN_GASTO: funil["sem gasto casado"] += 1; continue
        dd = sub["decil"].dropna().astype(int)
        if len(dd) < 30: funil["sem decil"] += 1; continue
        convs = [ep["mapa"].get(x2) or ep["geral"] for x2 in dd]
        cm = float(np.mean(convs))
        nh, kh, E = ep["hist"].get(cr, (0, 0, 0.0))
        conv = cm * ((nh/(nh+K)) * (kh/E) + (1 - nh/(nh+K))) if (nh > 0 and E > 0) else cm
        teto = conv * ep["vps"] * ep["fator"] / ROAS_ALVO
        rows.append(dict(lf=lf, n=len(sub), gasto=sp, teto=teto, cpl=sp/len(sub),
                         roas=int(sub["buy"].sum())*ep["vps"]*ep["fator"]/sp,
                         abaixo=(sp/len(sub)) <= teto))
    x = pd.DataFrame(rows)
    m = [0,0,0,0]; dt_, pos, tot_lf = [], 0, 0
    for lf in ordem:
        sl = x[x["lf"] == lf]
        if len(sl) < 4: continue
        a, b = sl[sl["abaixo"]], sl[~sl["abaixo"]]
        if len(a) == 0 or len(b) == 0: continue
        tot_lf += 1
        ta, tb2 = (a["roas"]>=ROAS_ALVO).mean(), (b["roas"]>=ROAS_ALVO).mean()
        dt_.append(ta - tb2); pos += int(ta > tb2)
        m[0]+=int((a["roas"]>=ROAS_ALVO).sum()); m[1]+=int((a["roas"]<ROAS_ALVO).sum())
        m[2]+=int((b["roas"]>=ROAS_ALVO).sum()); m[3]+=int((b["roas"]<ROAS_ALVO).sum())
        print(f"    {lf:<8} abaixo: {len(a):>3} unid · {100*ta:>3.0f}% batem · ROAS méd {np.average(a['roas'],weights=a['gasto']):>5.2f}   "
              f"acima: {len(b):>3} unid · {100*tb2:>3.0f}% · {np.average(b['roas'],weights=b['gasto']):>5.2f}")
    calr = [(np.average(sl["teto"], weights=sl["n"]), float(np.median(sl["roas"])))
            for lf in ordem for sl in [x[x["lf"]==lf]] if len(sl) >= 4]
    sp_cal = spearmanr([c[0] for c in calr], [c[1] for c in calr]).statistic if len(calr)>=5 else float("nan")
    ab, ac = m[0]+m[1], m[2]+m[3]
    print(f"\n=== época {rot}: {len(x)} unidades · {x['lf'].nunique()} lançamentos · "
          f"{tot_lf} com os 2 grupos (piso 4 unid.) ===")
    if rot == "acumulada":
        print(f"  funil de corte: {dict(funil)}")
    print(f"  ABAIXO do teto: {ab:>3} unid · {100*m[0]/ab:.0f}% bateram ROAS 2   "
          f"ACIMA: {ac:>3} unid · {100*m[2]/ac:.0f}%")
    d_ = np.array(dt_)
    print(f"  Δtaxa por lançamento: média {100*d_.mean():+.0f}pp · melhor em {pos}/{tot_lf}"
          + (f" · Wilcoxon p={wilcoxon(d_).pvalue:.3f}" if len(d_)>2 and np.any(d_!=0) else ""))
    print(f"  calibração entre lançamentos (Spearman teto×ROAS): {sp_cal:+.2f}")

print(f"\n  gasto coberto pelas unidades julgadas: R$ {x['gasto'].sum():,.0f}")
xa, xb = x[x["abaixo"]], x[~x["abaixo"]]
print(f"  AGREGADO dentro do teto: {len(xa)} unid · R$ {xa['gasto'].sum():,.0f} · "
      f"{100*(xa['roas']>=ROAS_ALVO).mean():.0f}% batem · ROAS méd {np.average(xa['roas'], weights=xa['gasto']):.2f}")
print(f"  AGREGADO acima do teto : {len(xb)} unid · R$ {xb['gasto'].sum():,.0f} · "
      f"{100*(xb['roas']>=ROAS_ALVO).mean():.0f}% batem · ROAS méd {np.average(xb['roas'], weights=xb['gasto']):.2f}")
