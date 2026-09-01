"""Lucro por decil de LF56 pra cá, na régua MISTA (a nota que foi USADA na época).
Antes de 25/07 as colunas por modelo não são confiáveis; a coluna `decil` é a nota
que o lead recebeu de quem o atendeu, e é ela que virou valor enviado pro Meta.
Só leitura: não toca contrato nem painel."""
import json, sys
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from src.data.analytics_connection import open_analytics_connection
from src.data.criativo_historico import criativo_do_lead, mapa_de_nomes
from src.data.ledger_connection import open_ledger_read_connection
from src.monitoring.campaign_classifier import channel_from_source
from src.monitoring.utm_quality import _campaign_id_from_utm
from src.validation.model_performance import build_matched_df, read_analytics_sales
from src.validation.lancamento_unidades import temperatura_da_campanha

def bloco(contrato):
    meta = contrato["meta"]
    if not meta.get("tem_venda"):
        return None
    cs = date.fromisoformat(str(meta["cap_start"])[:10])
    ce = date.fromisoformat(str(meta["cap_end"])[:10])
    cpl_un = {}
    for u in contrato["tabelas"]["unidades"]:
        if (u.get("canal") == "meta" and u.get("gasto")
                and int(u.get("leads_ledger") or 0) > 0):
            cpl_un[(u.get("cid") or "", str(u.get("criativo")))] = (
                float(u["gasto"]) / int(u["leads_ledger"]))
    if not cpl_un:
        return None
    an = open_analytics_connection(timeout=300)
    lg = open_ledger_read_connection()
    try:
        cols = ["email", "telefone", "data_captura", "decil", "decil_champion",
                "decil_challenger", "utm_campaign", "utm_content", "utm_source"]
        rows = lg.run(
            "SELECT email, phone, created_at, decil, decil_champion, decil_challenger, "
            "utm_campaign, utm_content, utm_source FROM registros_ml "
            "WHERE created_at >= :s AND created_at < (CAST(:e AS date) + INTERVAL '1 day') "
            "AND lead_score IS NOT NULL", s=cs.isoformat(), e=ce.isoformat())
        leads = pd.DataFrame(rows, columns=cols)
        leads["data_captura"] = pd.to_datetime(leads["data_captura"], utc=True,
                                               errors="coerce").dt.tz_localize(None)
        sales = read_analytics_sales(an, cs, ce + timedelta(days=22))
        mapa = mapa_de_nomes(an, client_id=meta.get("client_id", "devclub"))
    finally:
        for c in (lg, an):
            try: c.close()
            except Exception: pass
    if leads.empty:
        return None
    m = build_matched_df(leads, sales, window_days=21)
    camp = m.get("utm_campaign")
    m["_cid"] = [(_campaign_id_from_utm(c) or "") for c in camp]
    cont = m.get("utm_content", pd.Series([None] * len(m), index=m.index))
    m["_cria"] = [criativo_do_lead(x, mapa) for x in cont]
    m["_cpl"] = [cpl_un.get((c, k)) for c, k in zip(m["_cid"], m["_cria"])]
    canal = m.get("utm_source").map(lambda s_: channel_from_source(s_))
    temp = camp.map(lambda c: temperatura_da_campanha(c))
    base = (canal == "meta") & (temp != "quente") & m["_cpl"].notna()
    conv = m.get("converted").fillna(False).astype(bool)
    val = pd.to_numeric(m.get("sale_value_realizado", m.get("sale_value")),
                        errors="coerce").fillna(0.0)
    def _res(g):
        custo = float(m.loc[g, "_cpl"].sum()); fat = float(val[g & conv].sum())
        return dict(leads=int(g.sum()), custo=custo, vendas=int(conv[g].sum()),
                    faturamento=fat, lucro=fat - custo,
                    roas=(fat / custo if custo else None))
    out = {}
    for chave, col in (("misto", "decil"), ("champion", "decil_champion"),
                       ("challenger", "decil_challenger")):
        if col not in m.columns:
            continue
        dec = pd.to_numeric(m[col], errors="coerce")
        if not dec.notna().any():
            continue
        out[chave] = {"top30": _res(base & dec.between(8, 10)),
                      "bottom50": _res(base & dec.between(1, 5)),
                      "total": _res(base & dec.notna())}
    return out

fontes = {}
for q in sorted(Path("docs/relatorios/_corrida").glob("LF*/contrato.json")):
    fontes[q.parent.name.upper()] = q
for q in sorted(Path("docs/relatorios").glob("lf6*_resultado/contrato.json")):
    fontes[q.parent.name[:-10].upper()] = q
res = {}
for lf, q in sorted(fontes.items(), key=lambda kv: kv[0]):
    try:
        b = bloco(json.loads(q.read_text()))
    except Exception as e:
        print(f"{lf}: ERRO {type(e).__name__}: {e}", flush=True); continue
    if not b:
        print(f"{lf}: sem bloco (sem venda ou sem unidades)", flush=True); continue
    res[lf] = b
    mi = b.get("misto", {})
    t, f = mi.get("top30", {}), mi.get("bottom50", {})
    print(f"{lf}: MISTO top30 lucro R$ {t.get('lucro',0):,.0f} ROAS {t.get('roas') or 0:.2f} "
          f"({t.get('leads')} leads, {t.get('vendas')} vendas) | bottom50 lucro "
          f"R$ {f.get('lucro',0):,.0f} ROAS {f.get('roas') or 0:.2f}", flush=True)
Path("/private/tmp/claude-501/-Users-ramonmoreira-Desktop-bring-data/17c52d93-34f6-4816-9c2a-c1fb406c5e4b/scratchpad/lucro_decil_serie.json").write_text(json.dumps(res, indent=1))
print("\n=== SÉRIE (soma) ===")
for grp in ("top30", "bottom50"):
    cu = sum(res[l]["misto"][grp]["custo"] for l in res if "misto" in res[l])
    fa = sum(res[l]["misto"][grp]["faturamento"] for l in res if "misto" in res[l])
    print(f"{grp}: custo R$ {cu:,.0f} | faturamento R$ {fa:,.0f} | lucro R$ {fa-cu:,.0f} | ROAS {fa/cu if cu else 0:.2f}")
print("LFs:", ", ".join(sorted(res)))
