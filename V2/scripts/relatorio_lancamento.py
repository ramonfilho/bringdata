#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""relatorio_lancamento — o relatório por lançamento em UM comando.

    python3 scripts/relatorio_lancamento.py --lf LF64 --out docs/relatorios/lf64_resultado

Roda a máquina (`src.validation.lancamento_unidades.constroi_lancamento`) e
congela TUDO num `contrato.json`: as tabelas, os julgamentos e — crucial — o
payload inteiro da referência usada, porque a tabela viva é sobrescrita pelo
refresh semanal e o relatório não pode depender de a linha continuar lá.

O renderizador do painel lê SÓ o contrato (não toca em banco): re-rodar o
relatório quando as vendas caírem é rodar o MESMO comando de novo — o único
delta legítimo entre os dois contratos é a receita.

Saídas de falha (silêncio é proibido):
  exit 2  sem referência rolante (o teto não tem âncora)
  exit 3  cobertura de gasto casado abaixo do piso (--piso-gasto, default 90%)
"""
import argparse
import json
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))
os.chdir(_V2)
os.environ.setdefault("LAUNCHES_SOURCE", "table")   # LF novo mora na tabela

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_V2 / ".env")       # nunca `source .env` (mutila credenciais)


def _jsonable(o):
    """Contrato 100% JSON: datas viram texto, NaN vira null (NaN não é JSON e
    quebraria o renderizador no primeiro parse), DataFrame vira lista de linhas."""
    import pandas as pd
    if isinstance(o, (datetime, date)):
        return str(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, pd.DataFrame):
        return json.loads(o.to_json(orient="records", force_ascii=False))
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def _janela_de_etl(cap_start, cap_end, vendas_start, vendas_end, hoje, sales_max):
    """Decide SE o relatório puxa vendas novas antes de montar, e o intervalo.

    Puxa só com carrinho aberto ou recém-fechado ainda imaturo (histórico maduro
    não muda). Começa na última venda já ingerida — o upsert é idempotente, então
    re-ler o dia da última venda não duplica nada. Devolve (estado, inicio, fim)
    ou None quando não há o que puxar. Pura: testável sem banco."""
    from src.validation.lancamento_unidades import estado_do_lancamento
    estado = estado_do_lancamento(cap_start, cap_end, vendas_start, vendas_end,
                                  as_of=hoje, sales_max=sales_max)
    if estado not in ("venda_aberta", "venda_fechada_imatura"):
        return None
    inicio = max(d for d in (vendas_start, sales_max) if d)
    return estado, inicio, hoje


def _atualiza_vendas(lf: str, as_of) -> None:
    """Gerar o relatório = gerar com vendas atualizadas: com carrinho aberto,
    roda o ETL dos gateways ANTES de montar o contrato. `--sem-etl` desliga."""
    from src.core.launches import load_launches
    from src.data.analytics_connection import open_analytics_connection
    from src.validation.etl_sales import run_sales_etl
    from src.validation.lancamento_unidades import BRT
    from src.validation.model_performance import read_sales_coverage

    cfg = load_launches().get(lf)
    if not cfg:
        return  # constroi_lancamento falha alto com a mensagem certa

    def _d(k):
        v = cfg.get(k)
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date() if v else None

    hoje = as_of or datetime.now(BRT).date()
    an = open_analytics_connection()
    try:
        sales_max = read_sales_coverage(an)["overall"]
    finally:
        an.close()
    janela = _janela_de_etl(_d("cap_start"), _d("cap_end"),
                            _d("vendas_start"), _d("vendas_end"), hoje, sales_max)
    if not janela:
        return
    estado, inicio, fim = janela
    print(f"[vendas] {estado.replace('_', ' ')} — puxando gateways {inicio} → {fim} "
          f"antes de montar (desligue com --sem-etl)")
    res = run_sales_etl(str(inicio), str(fim))
    print(f"[vendas] ingerido por gateway: {res.get('loaded', res)}")


def _lucro_por_decil(contrato: dict) -> dict | None:
    """Lucro por decil (decisão do Ramon, 01/09): o custo de um lead é o CPL
    POR LEAD DO LEDGER da dupla criativo×campanha que o trouxe — a verba sai
    antes de o modelo dar a nota, então custo do decil = soma desses CPLs, e
    lucro = faturamento casado menos isso. Réguas SEPARADAS por modelo (nota
    mista dilui). Só Meta não-quente, casamento de 21 dias.

    Pré-condições (fora delas devolve None, e a seção não sai no painel):
    captação >= 25/07/2026 (antes disso as colunas por-modelo do ledger vieram
    trocadas em parte dos registros) e venda ingerida.
    """
    from datetime import timedelta

    import pandas as pd

    from src.core.ab_arm import temperatura_da_campanha
    from src.data.analytics_connection import open_analytics_connection
    from src.data.criativo_historico import criativo_do_lead, mapa_de_nomes
    from src.data.ledger_connection import open_ledger_read_connection
    from src.monitoring.campaign_classifier import channel_from_source
    from src.monitoring.utm_quality import _campaign_id_from_utm
    from src.validation.model_performance import (build_matched_df,
                                                  read_analytics_sales)

    meta = contrato["meta"]
    if not meta.get("tem_venda"):
        return None
    # A partir de 01/09 a medição sai SEMPRE que houver venda. O corte de 25/07
    # vale só para as colunas POR MODELO (antes disso champion/challenger vinham
    # trocadas em parte dos registros); a régua MISTA (`decil` = a nota que o
    # lead recebeu de quem o atendeu, a mesma que virou valor enviado pro Meta)
    # é confiável em toda a série e é o que sustenta o lucro do topo LF56+.
    por_modelo_ok = str(meta["cap_start"]) >= "2026-07-25"
    cs = date.fromisoformat(str(meta["cap_start"])[:10])
    ce = date.fromisoformat(str(meta["cap_end"])[:10])

    # CPL por LEAD DO LEDGER re-derivado das unidades (gasto ÷ leads_ledger):
    # independe da base do CPL publicado (que desde 01/09 é por cadastro).
    un = contrato["tabelas"]["unidades"]
    if hasattr(un, "to_dict"):          # na emissão ainda é DataFrame
        un = un.to_dict("records")
    cpl_un = {}
    for u in un:
        if (u.get("canal") == "meta" and u.get("gasto")
                and int(u.get("leads_ledger") or 0) > 0):
            cpl_un[(u.get("cid") or "", str(u.get("criativo")))] = (
                float(u["gasto"]) / int(u["leads_ledger"]))
    if not cpl_un:
        return None

    an = open_analytics_connection(timeout=300)
    lg = open_ledger_read_connection()
    try:
        # projeção própria: a padrão do ledger não traz utm_content, e sem ele
        # não dá pra achar a dupla (criativo) de cada lead.
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
            try:
                c.close()
            except Exception:
                pass
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

    def _resumo(g) -> dict:
        n = int(g.sum())
        custo = float(m.loc[g, "_cpl"].sum())
        v = int(conv[g].sum())
        fat = float(val[g & conv].sum())
        return dict(leads=n, custo=custo, vendas=v, faturamento=fat,
                    lucro=fat - custo, roas=(fat / custo if custo else None))

    out = {"janela": f"{cs} a {ce} (+21d de casamento)",
           "filtro": "meta_nao_quente", "custo_base": "cpl_por_lead_do_ledger",
           "por_modelo": por_modelo_ok}
    for chave, col in (("misto", "decil"),
                       ("champion", "decil_champion"),
                       ("challenger", "decil_challenger")):
        if chave != "misto" and not por_modelo_ok:
            out[chave] = None
            continue
        dec = pd.to_numeric(m[col], errors="coerce") if col in m.columns else None
        if dec is None or not dec.notna().any():
            out[chave] = None
            continue
        b = base & dec.notna()
        decis = []
        for d in range(1, 11):
            r = _resumo(b & (dec == d))
            r["decil"] = d
            decis.append(r)
        out[chave] = dict(
            decis=decis,
            total=_resumo(b),
            top30=_resumo(b & (dec >= 8)),
            resto=_resumo(b & (dec < 8)),
            top20=_resumo(b & (dec >= 9)),
            fundo=_resumo(b & (dec <= 5)),
        )
    return out



def _paginas_do_lancamento(contrato: dict) -> dict | None:
    """Conversão por PÁGINA de captação (decisão do Ramon, 01/09): a página é a
    URL que o lead abriu pra se cadastrar (`analytics.captacoes.utm_url`, ~98%
    preenchida de LF56 em diante; conferida contra o ledger: 100% igual onde as
    duas fontes se cruzam).

    Enquanto o RODÍZIO estiver ligado (o mesmo anúncio espalha os leads em
    várias páginas, em proporção fixa), a comparação entre páginas é limpa
    (mesmo público, mesmo criativo), mas o gasto NÃO é atribuível a página:
    isto é medição, não julgamento de teto. `rodizio_share` mede isso no
    próprio lançamento (fração dos cadastros Meta, em pares campanha×anúncio
    com ≥30 cadastros, cujo par alimentou 2+ páginas), e o render troca o texto quando o rodízio desligar.

    Vendas na MESMA régua do bloco NEGÓCIO: produtos do lançamento na janela
    de carrinho, casamento email+telefone. Sem venda ingerida → vendas e
    conversão None (regra de ouro: nunca 0 fabricado).
    """
    from datetime import timedelta

    import pandas as pd

    from src.data.analytics_connection import open_analytics_connection
    from src.data.ledger_connection import open_ledger_read_connection
    from src.monitoring.campaign_classifier import channel_from_source
    from src.validation.model_performance import (_filter_launch_sales,
                                                  _load_launch_rules,
                                                  build_matched_df,
                                                  read_analytics_sales)

    meta = contrato["meta"]
    cs = date.fromisoformat(str(meta["cap_start"])[:10])
    ce = date.fromisoformat(str(meta["cap_end"])[:10])
    vs = date.fromisoformat(str(meta["vendas_start"])[:10]) if meta.get("vendas_start") else None
    ve = date.fromisoformat(str(meta["vendas_end"])[:10]) if meta.get("vendas_end") else None
    tem_venda = bool(meta.get("tem_venda"))

    an = open_analytics_connection(timeout=300)
    lg = open_ledger_read_connection()
    try:
        # UMA linha por PESSOA: desde 11/08/2026 a `captacoes` tem grão por
        # INSCRIÇÃO (chave lf+email+origem_id) — sem o DISTINCT ON, quem se
        # cadastra em 2 páginas viraria 2 leads e a venda dele contaria 2x
        # (achado da revisão de 01/09). Fica a PRIMEIRA inscrição com URL.
        rows = an.run(
            "SELECT DISTINCT ON (lower(email)) lower(email), phone, captured_at, "
            "  regexp_replace(regexp_replace(regexp_replace(lower(utm_url),"
            "    '^https?://',''),'[?#].*$',''),'/+$','') AS url_norm, "
            "  utm_source, utm_campaign, coalesce(ad_name, utm_content) "
            "FROM captacoes WHERE lf = :lf "
            "ORDER BY lower(email), (coalesce(utm_url,'') = ''), captured_at",
            lf=contrato["lf"])
        total = len(rows)
        # decil MISTO (a nota de quem atendeu o lead; confiável na série toda),
        # pra mostrar se alguma página atrai lead pior aos olhos do modelo.
        dec_rows = lg.run(
            # ORDER BY: email repetido fica com o decil MAIS RECENTE, sempre o
            # mesmo em toda reemissão (contrato congelado tem que reproduzir).
            "SELECT lower(email), decil FROM registros_ml "
            "WHERE created_at >= :s AND created_at < (CAST(:e AS date) + INTERVAL '1 day') "
            "AND decil IS NOT NULL ORDER BY created_at", s=cs.isoformat(), e=ce.isoformat())
        sales = read_analytics_sales(an, cs, min(date.today(), ce + timedelta(days=60))
                                     + timedelta(days=1))
    finally:
        for c in (lg, an):
            try:
                c.close()
            except Exception:
                pass
    if not total:
        return None
    cols = ["email", "telefone", "data_captura", "url", "utm_source",
            "utm_campaign", "ad"]
    df = pd.DataFrame(rows, columns=cols)
    df = df[df["url"].fillna("") != ""].copy()
    com_url = len(df)
    if not com_url:
        return None
    # slug = 1º trecho do path; URL sem barra (rótulo solto de planilha) fica inteira
    df["pagina"] = [u.split("/", 1)[1].split("/")[0] if "/" in u else u
                    for u in df["url"]]
    df["data_captura"] = pd.to_datetime(df["data_captura"], utc=True,
                                        errors="coerce").dt.tz_localize(None)

    # vendas: régua de produto do lançamento na janela de carrinho (igual NEGÓCIO)
    rules = _load_launch_rules()
    ls = (_filter_launch_sales(sales, rules, vs, ve)
          if any(rules.values()) else sales)
    janela = max(60, (ve - cs).days + 3) if (ve and cs) else 60
    # `pagina` viaja DENTRO do df casado: agrupar no próprio `m` dispensa
    # alinhamento de índice com o df original (robusto a matcher que reindexe).
    m = build_matched_df(df[["email", "telefone", "data_captura", "pagina"]].copy(),
                         ls, window_days=janela)
    m["_conv"] = m["converted"].fillna(False).astype(bool)
    dmap = {r[0]: int(r[1]) for r in dec_rows}
    m["_dec"] = m["email"].map(dmap)

    # rodízio: fração dos cadastros META cujo par campanha×anúncio alimentou
    # 2+ páginas (cada uma com ≥20% do par). ≥50% = rodízio ligado.
    canal = df["utm_source"].map(lambda s_: channel_from_source(s_))
    mm = df[(canal == "meta") & df["ad"].notna()]
    rodizio_share = None
    if len(mm):
        tam = mm.groupby(["utm_campaign", "ad"])["pagina"].agg(["size"])
        pares_ok = tam[tam["size"] >= 30].index
        n_dup = n_rod = 0
        for chave in pares_ok:
            g = mm[(mm["utm_campaign"] == chave[0]) & (mm["ad"] == chave[1])]
            partes = g["pagina"].value_counts(normalize=True)
            n_dup += len(g)
            if (partes >= 0.20).sum() >= 2:
                n_rod += len(g)
        rodizio_share = (n_rod / n_dup) if n_dup else None

    linhas, sobra = [], dict(pagina=None, cadastros=0, vendas=0, dec_n=0, dec_topo=0)
    for pg, g in m.groupby("pagina"):
        n = len(g)
        v = int(g["_conv"].sum())
        d_ = g["_dec"].dropna()
        item = dict(cadastros=n, vendas=v, dec_n=int(len(d_)),
                    dec_topo=int((d_ >= 9).sum()))
        if n >= 50:
            linhas.append(dict(pagina=pg, **item))
        else:
            sobra["cadastros"] += n
            sobra["vendas"] += v
            sobra["dec_n"] += item["dec_n"]
            sobra["dec_topo"] += item["dec_topo"]
            sobra["n_paginas"] = sobra.get("n_paginas", 0) + 1
    linhas.sort(key=lambda x: -x["cadastros"])
    if sobra["cadastros"]:
        sobra["pagina"] = f"outras ({sobra.pop('n_paginas')} páginas)"
        linhas.append(sobra)

    out_l = []
    for x in linhas:
        n = x["cadastros"]
        out_l.append(dict(
            pagina=x["pagina"], cadastros=n,
            pct_trafego=100.0 * n / com_url,
            pct_d9_d10=(100.0 * x["dec_topo"] / x["dec_n"] if x["dec_n"] else None),
            vendas=(x["vendas"] if tem_venda else None),
            conversao=(100.0 * x["vendas"] / n if (tem_venda and n) else None),
        ))
    return dict(cobertura_url=100.0 * com_url / total, cadastros_total=total,
                cadastros_com_url=com_url, rodizio_share=rodizio_share,
                tem_venda=tem_venda, linhas=out_l)


def main() -> int:
    ap = argparse.ArgumentParser(description="Relatório por lançamento (um comando)")
    ap.add_argument("--lf", required=True, help="Nome do lançamento (ex.: LF64)")
    ap.add_argument("--as-of", default=None, help="Data de referência (default: hoje BRT)")
    ap.add_argument("--out", default=None,
                    help="Pasta de saída (default: docs/relatorios/<lf>_resultado)")
    ap.add_argument("--piso-gasto", type=float, default=0.90,
                    help="Piso da fração do gasto Meta casado por unidade (exit 3 abaixo)")
    ap.add_argument("--sem-etl", action="store_true",
                    help="NÃO puxar vendas novas antes de montar (default: puxa "
                         "enquanto o carrinho está aberto ou imaturo)")
    args = ap.parse_args()

    from src.validation.lancamento_unidades import constroi_lancamento

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    if not args.sem_etl:
        _atualiza_vendas(args.lf, as_of)
    r = constroi_lancamento(args.lf, as_of=as_of)
    meta, cob = r["meta"], r["meta"]["cobertura"]

    # ── linha de cobertura (obrigatória, é a prova de que o relatório viu tudo)
    pct = cob["pct_gasto_casado"]
    print(f"\n{args.lf}  cap {meta['cap_start']}→{meta['cap_end']}  vendas "
          f"{meta['vendas_start']}→{meta['vendas_end']}  estado={meta['estado']}")
    print(f"referência {meta['referencia_id']}  fator {meta['fator_rastreamento']:.4f} "
          f"({meta['fator_procedencia']})  crédito {meta['credito_nao_respondente']}  "
          f"régua {meta['ruler_run_id'][:8]}")
    print(f"cadastros {cob['cadastros']:,}  unidades {len(r['unidades'])}  "
          f"campanhas {len(r['campanhas'])}")
    print(f"gasto Meta R$ {cob['gasto_meta_total']:,.2f}  casado por unidade "
          f"R$ {cob['gasto_meta_casado']:,.2f}"
          + (f"  ({100*pct:.1f}%)" if pct is not None else ""))
    print(f"sem criativo {cob['leads_sem_criativo']}  macro quebrada "
          f"{cob['leads_criativo_macro']}  ids não resolvidos {cob['ids_nao_resolvidos']}")

    # ── régua de produto: produto órfão (vendeu, não casou padrão) GRITA
    orfaos = [p for p in meta["produtos_janela"] if not p["casou_padrao"]]
    if orfaos:
        print("\n⚠ PRODUTOS FORA DA RÉGUA (vendidos na janela, sem padrão no yaml):")
        for p in orfaos:
            print(f"   {p['produto']}  [{p['gateway']}]  n={p['n']}  R$ {p['valor']:,.2f}")
        print("   → decidir com o dono se entram, antes de publicar faturamento.")

    j = r["julgamento"]
    modo = "PREVISÃO (sem venda ingerida)" if not meta["tem_venda"] else "MEDIDO"
    # A régua é só o gasto desde 31/08/2026; o piso de leads virou 0. Imprimir
    # "≥0 leads" seria ruído, então só sai quando alguém reativar o piso.
    _corte = (f"≥{meta['corte_leads']} leads e ≥R$ {meta['corte_gasto']:.0f}"
              if meta.get("corte_leads") else f"≥R$ {meta['corte_gasto']:.0f} de gasto")
    print(f"\nteto ({modo}): {j['julgaveis']} unidades julgáveis "
          f"(corte {_corte}) — "
          f"dentro {j['dentro']['n']} (R$ {j['dentro']['gasto']:,.2f}) · "
          f"acima {j['acima']['n']} (R$ {j['acima']['gasto']:,.2f})")
    if meta["tem_venda"]:
        # lado vazio (0 unidades) tem ROAS/lucro None — imprimir o traço, não quebrar
        _n = lambda v, spec: format(v, spec) if v is not None else "—"  # noqa: E731
        for lado in ("dentro", "acima"):
            b = j[lado]
            print(f"  {lado:>6}: vendas {b['vendas']}  ROAS {_n(b['roas_ponderado'], '.2f')}  "
                  f"lucro R$ {_n(b['lucro'], ',.2f')}  | bateu meta {b['bateu_meta']}  "
                  f"lucro>1000 {b['lucro_acima_1000']}  positivo {b['roas_positivo']}")
        if j["fisher_p"] is not None:
            print(f"  Fisher p={j['fisher_p']:.4f}  Mann-Whitney p={j['mannwhitney_p']}")

    # ── separação por público (a descoberta do DEV21 virou medição fixa)
    sep = r.get("separacao_temperatura") or []
    if sep:
        print("\nseparação do modelo por público (conversão D9-D10 vs D1-D8, respondentes):")
        for s in sep:
            _p = lambda v: f"{100*v:.2f}%" if v is not None else "—"  # noqa: E731
            lift = f"{s['lift']:.2f}x" if s.get("lift") is not None else "—"
            print(f"  {s['temperatura']:<22} leads {s['leads']:>7,}  "
                  f"topo {_p(s.get('taxa_topo'))}  base {_p(s.get('taxa_base'))}  lift {lift}")

    # ── contrato congelado
    out = Path(args.out or f"docs/relatorios/{args.lf.lower()}_resultado")
    out.mkdir(parents=True, exist_ok=True)
    contrato = dict(
        lf=args.lf, meta=meta, julgamento=j,
        separacao_temperatura=sep,
        tabelas=dict(
            campanhas=r["campanhas"],
            unidades=r["unidades"],
            criativos_por_tipo=r["criativos_por_tipo"],
        ),
    )
    # lucro por decil (01/09): melhor esforço — falha vira None e aviso, o
    # contrato sai do mesmo jeito (a seção do painel simplesmente não aparece).
    try:
        contrato["tabelas"]["lucro_decil"] = _lucro_por_decil(contrato)
        ld = contrato["tabelas"]["lucro_decil"]
        if ld and ld.get("champion"):
            t30 = ld["champion"]["top30"]
            print(f"lucro por decil: top30 Champion R$ {t30['lucro']:,.0f} "
                  f"({t30['leads']} leads)")
    except Exception as e:
        contrato["tabelas"]["lucro_decil"] = None
        print(f"⚠ lucro por decil indisponível: {e}", file=sys.stderr)

    # páginas de captação (01/09): mesmo contrato de falha do lucro por decil:
    # melhor esforço, None nunca derruba a emissão.
    try:
        contrato["tabelas"]["paginas"] = _paginas_do_lancamento(contrato)
        pg = contrato["tabelas"]["paginas"]
        if pg:
            rz = pg.get("rodizio_share")
            print(f"páginas: {len(pg['linhas'])} linhas, cobertura de URL "
                  f"{pg['cobertura_url']:.1f}%"
                  + (f", rodízio {100*rz:.0f}%" if rz is not None else ""))
    except Exception as e:
        contrato["tabelas"]["paginas"] = None
        print(f"⚠ páginas indisponíveis: {e}", file=sys.stderr)

    dst = out / "contrato.json"
    dst.write_text(json.dumps(contrato, ensure_ascii=False, indent=1,
                              default=_jsonable))
    print(f"\ncontrato congelado em {dst}  ({dst.stat().st_size:,} bytes)")

    # ── pisos (depois de gravar: o contrato existe mesmo quando o piso grita,
    #    senão o diagnóstico do problema fica sem o dado que o mostraria)
    if pct is not None and pct < args.piso_gasto:
        print(f"\n✗ cobertura de gasto casado {100*pct:.1f}% abaixo do piso "
              f"{100*args.piso_gasto:.0f}% — investigar antes de publicar", file=sys.stderr)
        return 3
    # teto do casado: mais de 102% = a MESMA verba contada duas vezes no join
    # (foi assim que R$ 381 mil de gasto fantasma entraram nos contratos da
    # corrida em ago/26 com a cobertura imprimindo 149-197% sem travar nada)
    if pct is not None and pct > 1.02:
        print(f"\n✗ GASTO CASADO {100*pct:.1f}% > 102% do gasto real: verba "
              f"DUPLICADA no casamento unidade x insights. NÃO PUBLICAR — "
              f"contrato gravado só para diagnóstico.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
