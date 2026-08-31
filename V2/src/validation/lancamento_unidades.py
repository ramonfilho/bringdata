"""lancamento_unidades — a tabela-fato da UNIDADE do lançamento (criativo×campanha).

É a peça que faltava para o relatório por lançamento (o do DEV21) ser máquina em
vez de 19 scripts ad-hoc: NENHUM módulo de produção ligava o gasto por anúncio
(`analytics.ad_insights`) ao teto por unidade (`teto_por_chave`) e ao casamento
lead→venda (`model_performance`). Este módulo é SÓ junção e apresentação:

  o que ele NÃO reimplementa (tudo importado, decisão dos 3 arquitetos, 23/08):
    - conta de dinheiro (haircut de boleto, imposto Meta, CPL/ROAS/lucro)
        → `model_performance._bucket_metrics`
    - casamento lead→venda e as duas bases (negócio=cadastros, modelo=ledger)
        → `model_performance._load_matched`
    - fórmula do teto e composição com histórico → `teto_por_chave.tetos_completos`
    - chave de criativo → `criativo_historico.criativo_do_lead`/`chave_canonica`
    - rótulo de campanha → `core.ab_arm.first_match` (MODELO, identidade estável)
    - id da campanha no UTM → `utm_quality._campaign_id_from_utm` (Meta) e
      `google_variant.campaign_id_from_utm_term` (Google)

REGRA DE OURO das células: número que não existe é None, NUNCA 0. Um lançamento
com carrinho aberto e zero venda ingerida sai com faturamento None ("ainda não
medido"), não 0,00 ("medido e deu zero") — as duas coisas contam histórias
opostas para quem lê.

Canal antes de rótulo: as campanhas do Google passam no `is_captacao` do
`resolve_arm` (medido: R$ 11.186,81 do LF64 cairiam no balde da Meta), então o
canal (`platform` no gasto, `channel_from_source` no lead) decide PRIMEIRO e o
rotulador só vê o que é Meta.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from src.core.ab_arm import (_default_config, first_match,
                             temperatura_da_campanha)
from src.data.criativo_historico import chave_canonica, criativo_do_lead
from src.monitoring.campaign_classifier import channel_from_source
from src.monitoring.google_variant import campaign_id_from_utm_term
from src.monitoring.utm_quality import _campaign_id_from_utm
from src.validation.model_performance import _bucket_metrics

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))

# Rótulos fixos dos baldes que não são campanha da Meta. 'Lead Padrão (Meta)' é
# a captação FRIA da Meta sem tag de modelo (regra fixada em 16/08, PRs #220/221).
ROTULO_GOOGLE = "Google Ads"
ROTULO_LEAD_PADRAO = "Lead Padrão (Meta)"
ROTULO_ORGANICO = "Orgânico/Outro"

# Colunas de DINHEIRO da tabela: são as que viram None em bloco quando o
# lançamento ainda não tem venda ingerida (regra de ouro acima).
_COLS_DINHEIRO = ["vendas", "vendas_cartao", "vendas_boleto", "faturamento",
                  "roas", "lucro", "conversao"]


# ───────────────────────── estado do lançamento ──────────────────────────────
def estado_do_lancamento(cap_start: Optional[date], cap_end: Optional[date],
                         vendas_start: Optional[date], vendas_end: Optional[date],
                         *, as_of: date, window_days: int = 60,
                         sales_max: Optional[date] = None) -> str:
    """Em que momento do ciclo o lançamento está, derivado do calendário.

    Cinco estados, sempre os mesmos, sem ramo de código diferente por estado —
    quem muda é o CONTEÚDO das células (dinheiro None antes da venda):

      'captacao_aberta'                    as_of ainda dentro da captação
      'captacao_fechada_venda_nao_aberta'  captou tudo, carrinho ainda não abriu
      'venda_aberta'                       carrinho aberto (dinheiro PROVISÓRIO)
      'venda_fechada_imatura'              carrinho fechou, mas a janela de
                                           conversão (window_days da captação)
                                           ou a ingestão ainda não cobrem tudo
      'maduro'                             nada mais muda

    `sales_max` (última venda em `analytics.sales`) só REBAIXA 'maduro' para
    'venda_fechada_imatura' quando a ingestão está atrás do carrinho — o guard
    de subcontagem do `_obs_gap_days`, aplicado ao estado.
    """
    if cap_end is None or vendas_start is None or vendas_end is None:
        return "captacao_aberta" if (cap_start and as_of >= cap_start) else "indefinido"
    if as_of <= cap_end:
        return "captacao_aberta"
    if as_of < vendas_start:
        return "captacao_fechada_venda_nao_aberta"
    if as_of <= vendas_end:
        return "venda_aberta"
    maduro = (as_of - cap_end).days >= window_days
    if maduro and (sales_max is None or sales_max >= vendas_end):
        return "maduro"
    return "venda_fechada_imatura"


# ───────────────────────── rótulo do modelo ──────────────────────────────────
def rotulo_do_modelo(nome_campanha, plataforma: str, cfg=None) -> str:
    """Rótulo do MODELO da campanha (identidade estável), nunca do papel.

    Papel (champion/challenger/controle) muda com a data; modelo não: HQLB,
    LEADHQLB e ABR_28_TOP30 são a MESMA campanha de modelo (challenger_abr28)
    em três batismos. A série entre lançamentos só faz sentido por modelo —
    duas sessões já erraram rotulando por papel (`resolve_arm` cru).

    Canal decide primeiro: google → 'Google Ads' sem olhar o nome (as campanhas
    de lá passam no is_captacao e cairiam num balde Meta).
    """
    if str(plataforma).strip().lower() == "google":
        return ROTULO_GOOGLE
    cfg = cfg or _default_config()
    key = first_match(str(nome_campanha or ""), cfg.tag_variants)
    if key:
        return dict(cfg.display_names).get(key, key)
    return ROTULO_LEAD_PADRAO


# ───────────────────────── lado do LEAD ──────────────────────────────────────
def prepara_leads(neg: pd.DataFrame, mapa_nomes: dict) -> pd.DataFrame:
    """Acrescenta ao matched de NEGÓCIO as três chaves de junção da unidade:

      canal      'meta' | 'google' | 'organic' (channel_from_source)
      cid        id da campanha: sufixo `|id` do utm_campaign (Meta) ou 1º
                 segmento do ValueTrack no utm_term (Google)
      criativo   chave canônica do criativo (id numérico → nome → canônica)

    Não filtra nenhuma linha: lead sem cid ou sem criativo fica com '' e cai
    nos baldes nomeados ('sem campanha paga', 'criativo não identificado') —
    descartar em silêncio foi vetado pelo arquiteto de dados.
    """
    df = neg.copy()
    src = df.get("utm_source", pd.Series([None] * len(df), index=df.index))
    df["canal"] = src.map(lambda s: channel_from_source(s))
    camp = df.get("utm_campaign", pd.Series([None] * len(df), index=df.index))
    term = df.get("utm_term", pd.Series([None] * len(df), index=df.index))
    df["cid"] = [
        (campaign_id_from_utm_term(t) if c == "google" else _campaign_id_from_utm(u)) or ""
        for c, u, t in zip(df["canal"], camp, term)
    ]
    cont = df.get("utm_content", pd.Series([None] * len(df), index=df.index))
    df["criativo"] = [criativo_do_lead(x, mapa_nomes) for x in cont]
    if "decile" not in df.columns:
        # `_bucket_metrics` espera a coluna (o casamento real sempre a traz);
        # cadastro não tem decil — None, como no matched de NEGÓCIO da produção.
        df["decile"] = None
    return df


# ───────────────────────── item (a): tabela por campanha ─────────────────────
def tabela_campanhas(neg: pd.DataFrame, spend_df: Optional[pd.DataFrame], *,
                     haircut: float, meta_gross_up: float = 1.0,
                     tem_venda: bool = True, cfg=None) -> pd.DataFrame:
    """Uma linha por campanha da META (campaign_id do gasto) + Google agregado +
    orgânico — gasto, leads, CPL, vendas, ROAS, lucro, rótulo de modelo.

    O Google entra AGREGADO porque o cadastro só carrega o id de campanha de lá
    no utm_term, e o gasto dele é grão campanha; a régua de canal proíbe fundir
    lead de um canal com gasto de outro. `neg` é o retorno de `prepara_leads`.

    `tem_venda=False` (carrinho sem venda ingerida) anula as colunas de dinheiro
    da venda (None), mantendo gasto/leads/CPL — que já existem na captação.
    """
    cfg = cfg or _default_config()
    if spend_df is None or spend_df.empty:
        sp = pd.DataFrame(columns=["cid", "plat", "gasto", "nome"])
    else:
        sp = spend_df.copy()
        sp["plat"] = sp["platform"].astype(str).str.strip().str.lower()
        sp["gasto"] = (pd.to_numeric(sp["spend"], errors="coerce").fillna(0.0)
                       * sp["plat"].map(lambda p: meta_gross_up if p == "meta" else 1.0))
        sp["cid"] = sp["campaign_id"].astype(str).str.strip()
    gasto = (sp.groupby(["cid", "plat"], dropna=False)
             .agg(gasto=("gasto", "sum"), nome=("campaign_name", "last"))
             .reset_index() if len(sp) else
             pd.DataFrame(columns=["cid", "plat", "gasto", "nome"]))

    def _met(bdf: pd.DataFrame, inv: Optional[float], rot: str) -> dict:
        b = _bucket_metrics(bdf, rot, rot, investimento=inv, haircut=haircut)
        return dict(leads=b.n_leads, cpl=b.cpl,
                    conversao=b.conversion_rate, vendas=b.n_conversions,
                    vendas_cartao=b.compradores_cartao,
                    vendas_boleto=b.compradores_boleto,
                    faturamento=b.faturamento, roas=b.roas, lucro=b.lucro,
                    gasto=b.investimento)

    linhas = []
    meta_g = gasto[gasto["plat"] == "meta"]
    for cid, g in meta_g.groupby("cid"):
        nome = g["nome"].iloc[-1]
        r = _met(neg[(neg["canal"] == "meta") & (neg["cid"] == cid)],
                 float(g["gasto"].sum()), nome)
        r.update(cid=cid, campanha=nome, plataforma="meta",
                 modelo=rotulo_do_modelo(nome, "meta", cfg),
                 temperatura=temperatura_da_campanha(nome))
        linhas.append(r)
    gg = gasto[gasto["plat"] == "google"]
    if len(gg):
        r = _met(neg[neg["canal"] == "google"], float(gg["gasto"].sum()),
                 ROTULO_GOOGLE)
        r.update(cid="", campanha="Google Ads (agregado)", plataforma="google",
                 modelo=ROTULO_GOOGLE, temperatura=None)
        linhas.append(r)
    usados = set(meta_g["cid"])
    orf = neg[((neg["canal"] == "meta") & (~neg["cid"].isin(usados)))
              | (neg["canal"] == "organic")]
    if len(orf):
        r = _met(orf, None, ROTULO_ORGANICO)
        r.update(cid="", campanha="Orgânico / sem campanha paga", plataforma="",
                 modelo=ROTULO_ORGANICO, temperatura=None)
        linhas.append(r)
    df = pd.DataFrame(linhas)
    if not tem_venda and len(df):
        df[_COLS_DINHEIRO] = None
        df["lucro"] = None
    return df


# ───────────────────────── a tabela-fato da unidade ──────────────────────────
def tabela_unidades(neg: pd.DataFrame, por_unidade: list, gasto_unid: dict, *,
                    haircut: float, tem_venda: bool = True) -> pd.DataFrame:
    """Uma linha por unidade (campanha × criativo): leads das DUAS contagens,
    gasto, CPL, teto, folga, decomposição do teto e (com venda) o dinheiro.

    As três fontes se encontram pela chave (cid, criativo_canônico):
      `neg`          cadastros (Railway) já passados por `prepara_leads`
      `por_unidade`  saída de `tetos_completos` (teto + decomposição, ledger)
      `gasto_unid`   saída de `gasto_por_unidade` (ad_insights, Meta apenas)

    Google: o gasto por criativo NÃO existe (ad_insights é Meta pura), então a
    unidade do Google sai com gasto/cpl/folga None e `motivo_sem_gasto`
    preenchido — nunca herda gasto da Meta (guarda de canal; medido: a fusão
    derrubava o CPL do DEV-AD0138 em 52%).
    """
    # lado do lead: cadastros por unidade
    cad = (neg.groupby(["canal", "cid", "criativo"], dropna=False)
           .size().to_dict()) if len(neg) else {}
    # dinheiro por unidade (só faz sentido com venda)
    conv = neg[neg.get("converted", pd.Series(dtype=bool)).fillna(False).astype(bool)] \
        if (tem_venda and len(neg)) else neg.iloc[0:0]

    linhas = []
    for u in por_unidade:
        cid = _campaign_id_from_utm(u["campanha"]) or ""
        criativo = str(u["criativo"])
        google = bool(u["campanha"] == "devlf" or cid == "")
        canal = "google" if google else "meta"
        g = gasto_unid.get((cid, criativo)) if not google else None
        gasto = float(g["spend"]) if g else None
        leads_ger = int(g["leads_gerenciador"]) if g else None
        n_cad = cad.get((canal, cid, criativo))
        t = u["teto"]
        teto = float(t.valor) if t.ok else None
        cpl = (gasto / u["n"]) if (gasto is not None and u["n"]) else None
        linha = dict(
            cid=cid, campanha=u["campanha"], canal=canal, criativo=criativo,
            temperatura=(temperatura_da_campanha(u["campanha"])
                         if canal == "meta" else None),
            leads_ledger=int(u["n"]), cadastros=(int(n_cad) if n_cad else None),
            leads_gerenciador=leads_ger, pct_d9_d10=float(u["pct"]),
            gasto=gasto, cpl=cpl, teto=teto,
            folga=((teto - cpl) if (teto is not None and cpl is not None) else None),
            dentro_do_teto=((cpl <= teto) if (teto is not None and cpl is not None)
                            else None),
            motivo_sem_gasto=("google_sem_gasto_por_criativo" if google
                              else (None if g else "sem_par_no_gerenciador")),
            # decomposição do teto (chaves aditivas de tetos_completos)
            n_hist=u.get("n_hist"), lift_criativo=u.get("lift_criativo"),
            peso_historico=u.get("peso"),
            compradores_hist=u.get("compradores_hist"),
            esperados_hist=u.get("esperados"),
        )
        if tem_venda and n_cad:
            sub = conv[(conv["canal"] == canal) & (conv["cid"] == cid)
                       & (conv["criativo"] == criativo)]
            b = _bucket_metrics(sub, criativo, criativo,
                                investimento=gasto, haircut=haircut)
            linha.update(vendas=b.n_conversions, faturamento=b.faturamento,
                         roas=b.roas, lucro=b.lucro,
                         conversao=(b.n_conversions / n_cad if n_cad else None))
        else:
            linha.update(vendas=None, faturamento=None, roas=None, lucro=None,
                         conversao=None)
        linhas.append(linha)
    return pd.DataFrame(linhas)


# ───────────────────────── item (c): dentro vs acima do teto ─────────────────
def julga_dentro_vs_acima(unidades: pd.DataFrame, *,
                          tolerancia_meta: float = 0.02,
                          alvo_roas: float = 2.0) -> dict:
    """Compara as unidades que respeitaram o teto com as que estouraram.

    Sem venda (colunas de dinheiro None) devolve só a fotografia: quantas
    unidades, quanto gasto e quantos leads de cada lado — modo PREVISÃO,
    rotulado. Com venda entram os quatro julgamentos:

      'bateu_meta'        ROAS >= alvo×(1−tolerância). A tolerância existe por
                          decisão do Ramon (24/08): um ROAS de 1,97 contra alvo
                          2,0 é erro marginal e conta como meta batida.
      'lucro_acima_1000'  lucro > R$ 1.000 (pedido de 24/08: lucro substancial)
      'roas_positivo'     lucro > 0 (deu mais do que gastou)
      fisher_p / mannwhitney_p  os dois testes do relatório do DEV21

    Devolve None nos campos sem base (nunca número fabricado).
    """
    j = unidades[unidades["dentro_do_teto"].notna()] if len(unidades) else unidades
    out = {"julgaveis": int(len(j)),
           "sem_julgamento": int(len(unidades) - len(j)),
           "tolerancia_meta": tolerancia_meta, "alvo_roas": alvo_roas}
    for rotulo, lado in (("dentro", True), ("acima", False)):
        s = j[j["dentro_do_teto"] == lado] if len(j) else j
        gasto = float(pd.to_numeric(s.get("gasto"), errors="coerce").sum()) if len(s) else 0.0
        bloco = {"n": int(len(s)), "gasto": gasto,
                 "leads": int(pd.to_numeric(s.get("leads_ledger"), errors="coerce")
                              .fillna(0).sum()) if len(s) else 0}
        roas = pd.to_numeric(s.get("roas"), errors="coerce") if len(s) else pd.Series(dtype=float)
        lucro = pd.to_numeric(s.get("lucro"), errors="coerce") if len(s) else pd.Series(dtype=float)
        com_dinheiro = roas.notna().any() if len(roas) else False
        if com_dinheiro:
            fat = pd.to_numeric(s.get("faturamento"), errors="coerce").fillna(0.0)
            bloco.update(
                vendas=int(pd.to_numeric(s.get("vendas"), errors="coerce")
                           .fillna(0).sum()),
                faturamento=float(fat.sum()),
                roas_ponderado=(float(fat.sum() / gasto) if gasto else None),
                lucro=float(lucro.fillna(0.0).sum()),
                bateu_meta=int((roas >= alvo_roas * (1 - tolerancia_meta)).sum()),
                lucro_acima_1000=int((lucro > 1000.0).sum()),
                roas_positivo=int((lucro > 0.0).sum()),
            )
        else:
            bloco.update(vendas=None, faturamento=None, roas_ponderado=None,
                         lucro=None, bateu_meta=None, lucro_acima_1000=None,
                         roas_positivo=None)
        out[rotulo] = bloco

    out["fisher_p"] = out["mannwhitney_p"] = None
    d, a = out["dentro"], out["acima"]
    if (d["n"] and a["n"] and d["vendas"] is not None and a["vendas"] is not None):
        try:
            from scipy.stats import fisher_exact, mannwhitneyu
            tab = [[d["vendas"], max(d["leads"] - d["vendas"], 0)],
                   [a["vendas"], max(a["leads"] - a["vendas"], 0)]]
            out["fisher_p"] = float(fisher_exact(tab)[1])
            # Igualdade explícita, não máscara booleana: a coluna carrega
            # True/False/None (dtype object), e `~` em object faz conta de bit
            # nos ints (-1/-2) em vez de negar — quebrou o Mann-Whitney na
            # primeira rodada MEDIDA do LF64 (24/08).
            ra = pd.to_numeric(j[j["dentro_do_teto"] == True]["roas"],   # noqa: E712
                               errors="coerce").dropna()
            rb = pd.to_numeric(j[j["dentro_do_teto"] == False]["roas"],  # noqa: E712
                               errors="coerce").dropna()
            if len(ra) and len(rb):
                out["mannwhitney_p"] = float(mannwhitneyu(ra, rb,
                                                          alternative="two-sided")[1])
        except Exception as e:  # scipy ausente não derruba o relatório
            logger.warning("[lancamento_unidades] testes estatísticos indisponíveis: %s", e)
    return out


# ───────────────────────── separação por temperatura ─────────────────────────
def separacao_por_temperatura(ledger_matched: Optional[pd.DataFrame], *,
                              tem_venda: bool = True,
                              decil_topo: int = 9) -> list:
    """Quanto o modelo SEPARA dentro de cada público (quente/frio/sem rótulo):
    taxa de conversão do topo (D9-D10) contra a base (D1-D8) e o lift entre elas.

    Existe porque a descoberta do DEV21 (10/08) foi estrutural: dentro do público
    FRIO nenhum modelo separava (lift 1,06× no abr_28, 1,01× no jul_24) — o lift
    agregado vinha de ordenar PÚBLICOS, não pessoas do mesmo público. Esta função
    torna essa medição uma seção fixa de todo lançamento, em vez de análise avulsa.

    `ledger_matched` é o matched de MODELO (`_load_matched`): respondentes do
    ledger com `decil`, `utm_campaign`, `utm_source` e `converted`. O balde nasce
    do CANAL antes do nome (nota do Ramon, 31/08: no LF65 o rótulo único "sem
    público no nome" escondia 1.078 leads do Google, 89 de rastro quebrado e 91
    de orgânico/manychat, tudo somado como se fosse um público):

      google                       → 'Google'
      organic                      → 'orgânico / sem rastro'
      meta com QUENTE/FRIO no nome → 'quente' / 'frio' / 'morno'
      meta sem token de público    → 'Meta, sem público no nome'

    Sem a coluna `utm_source` (contrato antigo, teste sintético) vale só o nome
    da campanha, como antes. Sem venda ingerida, taxas e lift saem None (regra
    de ouro: nunca 0 fabricado). Lift com base zerada também sai None.
    """
    from src.core.ab_arm import TEMPERATURA_SEM_PUBLICO
    out: list = []
    if ledger_matched is None or len(ledger_matched) == 0:
        return out
    df = ledger_matched
    camp = df.get("utm_campaign", pd.Series([None] * len(df), index=df.index))
    temp = pd.Series([temperatura_da_campanha(c) for c in camp], index=df.index)
    if "utm_source" in df.columns:
        canal = df["utm_source"].map(lambda s: channel_from_source(s))

        def _balde(c_, t_):
            if c_ == "google":
                return "Google"
            if c_ != "meta":
                return "orgânico / sem rastro"
            return ("Meta, sem público no nome"
                    if t_ == TEMPERATURA_SEM_PUBLICO else t_)

        temp = pd.Series([_balde(c_, t_) for c_, t_ in zip(canal, temp)],
                         index=df.index)
    dec = pd.to_numeric(df.get("decil"), errors="coerce")
    conv = (df.get("converted", pd.Series(False, index=df.index))
            .fillna(False).astype(bool))
    ok = dec.notna()
    for t in temp[ok].unique():
        g = ok & (temp == t)
        topo, base = g & (dec >= decil_topo), g & (dec < decil_topo)
        n, n_topo, n_base = int(g.sum()), int(topo.sum()), int(base.sum())
        linha = dict(temperatura=str(t), leads=n, leads_topo=n_topo,
                     pct_topo=(100.0 * n_topo / n if n else None))
        if tem_venda and n:
            vt, vb = int(conv[topo].sum()), int(conv[base].sum())
            tx_t = (vt / n_topo) if n_topo else None
            tx_b = (vb / n_base) if n_base else None
            linha.update(vendas_topo=vt, vendas_base=vb, taxa_topo=tx_t,
                         taxa_base=tx_b,
                         lift=((tx_t / tx_b)
                               if (tx_t is not None and tx_b) else None))
        else:
            linha.update(vendas_topo=None, vendas_base=None, taxa_topo=None,
                         taxa_base=None, lift=None)
        out.append(linha)
    out.sort(key=lambda r: -r["leads"])
    return out


# ───────────────────────── item (b): criativo × tipo de campanha ─────────────
def criativos_por_tipo(unidades: pd.DataFrame, campanhas: pd.DataFrame) -> pd.DataFrame:
    """Agrega a tabela-fato no grão criativo × MODELO de campanha (o grão de
    julgamento do item b, decisão do sw-architect): que criativos levaram mais
    verba em cada tipo, e a conversão deles em cada um.

    O rótulo de modelo vem da tabela de campanhas (item a) pelo cid — a unidade
    não re-rotula nada. Unidade sem cid casado no gasto herda o canal.
    """
    if unidades.empty:
        return unidades.copy()
    rot = dict(zip(campanhas["cid"], campanhas["modelo"])) if len(campanhas) else {}
    u = unidades.copy()
    u["modelo"] = [
        (ROTULO_GOOGLE if c == "google" else rot.get(cid, ROTULO_LEAD_PADRAO))
        for c, cid in zip(u["canal"], u["cid"])
    ]
    agg = (u.groupby(["modelo", "criativo"], dropna=False)
           .agg(unidades=("criativo", "size"),
                leads_ledger=("leads_ledger", "sum"),
                cadastros=("cadastros", lambda s: s.sum(min_count=1)),
                gasto=("gasto", lambda s: s.sum(min_count=1)),
                pct_d9_d10=("pct_d9_d10", "mean"),
                lift_criativo=("lift_criativo", "mean"),
                n_hist=("n_hist", "max"),
                vendas=("vendas", lambda s: s.sum(min_count=1)),
                faturamento=("faturamento", lambda s: s.sum(min_count=1)),
                lucro=("lucro", lambda s: s.sum(min_count=1)))
           .reset_index())
    agg["cpl"] = agg["gasto"] / agg["leads_ledger"].where(agg["leads_ledger"] > 0)
    agg["conversao"] = agg["vendas"] / agg["cadastros"].where(agg["cadastros"] > 0)
    return agg.sort_values(["modelo", "gasto"], ascending=[True, False],
                           na_position="last").reset_index(drop=True)


def linha_naobase(naobase_sales, haircut: float) -> Optional[dict]:
    """A linha 'Não está na base' da tabela de campanhas: vendas do lançamento
    que NÃO casaram nenhum cadastro da captação (compra por indicação, cadastro
    antigo, e-mail/telefone diferentes). Sem ela o faturamento da tabela não
    fecha com o debriefing do cliente — o relatório do DEV21 sempre a teve.
    Sem lead e sem gasto: leads=0, CPL/ROAS/lucro None (nunca 0)."""
    from src.validation.model_performance import _naobase_bucket
    nb = _naobase_bucket(naobase_sales, haircut)
    if nb is None:
        return None
    return dict(cid="", campanha="Não está na base (venda sem cadastro na captação)",
                plataforma="", modelo="Não está na base", gasto=None,
                leads=0, cpl=None, conversao=None,
                vendas=nb.n_conversions, vendas_cartao=nb.compradores_cartao,
                vendas_boleto=nb.compradores_boleto, faturamento=nb.faturamento,
                roas=None, lucro=None)


# ───────────────────────── composição (I/O real) ─────────────────────────────
def _historico_para_consulta(hist_df: pd.DataFrame, mapa_nomes: dict) -> dict:
    """O acumulado point-in-time (`calcula_historico`) na forma que o teto consome
    (`{criativo: {leads, compradores, esperados, ...}}`), com as grafias FUNDIDAS
    pela mesma chave dos leads (`criativo_do_lead`: id→nome→canônica).

    A fusão importa: a tabela grava chave crua, e id numérico + nome + acento
    NFD do mesmo anúncio viram gavetas separadas que diluem o peso do histórico
    (o bug do PR #237). Como o `chave_criativo` injetado no teto canoniza do
    mesmo jeito, consulta e gaveta caem sempre no mesmo lugar — dict simples,
    sem precisar da classe de apelidos do `le_historico`.
    """
    out: dict = {}
    if hist_df is None or hist_df.empty:
        return out
    for r in hist_df.itertuples(index=False):
        k = criativo_do_lead(r.criativo, mapa_nomes)
        if not k:
            continue
        g = out.get(k)
        if g is None:
            out[k] = {"leads": int(r.leads), "compradores": int(r.compradores),
                      "esperados": float(r.esperados), "prior_conversao": None,
                      "prior_fonte": None}
        else:
            g["leads"] += int(r.leads)
            g["compradores"] += int(r.compradores)
            g["esperados"] += float(r.esperados)
    return out


def constroi_lancamento(lf: str, *, as_of: Optional[date] = None,
                        window_days: int = 60, client_id: str = "devclub",
                        referencia: Optional[dict] = None,
                        corte_leads: int = 100, corte_gasto: float = 300.0,
                        tolerancia_meta: float = 0.02) -> dict:
    """Monta o relatório inteiro de UM lançamento, numa passada, ponto único de
    composição (quem decide as fontes é aqui; as funções acima são puras).

    Fontes, na ordem em que entram:
      calendário     `load_launches()` (exige LAUNCHES_SOURCE=table no ambiente)
      referência     a de PRODUÇÃO ATUAL (decisão do Ramon, 24/08) — ou a
                     injetada em `referencia` (backtest ancora aqui)
      histórico      `calcula_historico(corte=cap_start)` — point-in-time: o
                     lançamento anterior (DEV21) fica FORA do teto deste
      teto           `tetos_completos` com calc+histórico+chave injetados
      leads/vendas   `_load_matched` (cadastros Railway com UTMs completas,
                     ledger, vendas analytics, gasto por campanha)
      gasto fino     `read_ad_insights` + `gasto_por_unidade` (Meta, por anúncio)

    Devolve dict com 'campanhas', 'unidades', 'criativos_por_tipo', 'julgamento',
    'meta' (janelas, estado, referência congelada, coberturas, produtos da
    janela de vendas com a flag de régua). NÃO escreve em banco nem em arquivo.

    `corte_leads`/`corte_gasto`: os literais do DEV21 (>=100 leads, >=R$ 300).
    Aplicados SÓ ao julgamento do teto — a tabela-fato guarda todas as linhas
    com a coluna `no_corte` dizendo quem entrou.
    """
    from src.core.launches import load_launches
    from src.data.ad_insights_reader import gasto_por_unidade, read_ad_insights
    from src.data.ad_spend_reader import read_ad_spend
    from src.data.analytics_connection import open_analytics_connection
    from src.data.cadastro_records import open_railway_connection, read_cadastros
    from src.data.criativo_historico import calcula_historico, mapa_de_nomes
    from src.data.ledger_connection import open_ledger_read_connection
    from src.data.reference_reader import (credito_do_nao_respondente,
                                           fator_de_rastreamento,
                                           read_rolling_reference)
    from src.monitoring.teto import CalculadoraDeTeto
    from src.monitoring.teto_por_chave import tetos_completos
    from src.validation.model_performance import (_load_boleto_haircut,
                                                  _load_launch_products,
                                                  _load_matched,
                                                  _load_meta_gross_up,
                                                  build_matched_df,
                                                  read_analytics_sales,
                                                  read_ledger_leads,
                                                  read_sales_coverage)

    as_of = as_of or datetime.now(BRT).date()
    launches = load_launches()
    cfg_lf = launches.get(lf)
    if not cfg_lf:
        raise KeyError(f"LF {lf!r} não está no calendário")

    def _d(k):
        v = cfg_lf.get(k)
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date() if v else None

    cap_start, cap_end = _d("cap_start"), _d("cap_end")
    vendas_start, vendas_end = _d("vendas_start"), _d("vendas_end")

    an = open_analytics_connection(timeout=900)
    lg = open_ledger_read_connection()
    rc = open_railway_connection()
    try:
        # referência: a que a produção serve AGORA (ou a injetada)
        ref = referencia or read_rolling_reference(client_id, conn=an)
        if not ref:
            raise RuntimeError("sem referência rolante — o teto não tem âncora")
        run_id = ref.get("ruler_run_id")
        assert run_id, "referência sem ruler_run_id — a régua de decis não tem dono"
        calc = CalculadoraDeTeto.de_referencia_carregada(ref)
        fator, fator_proc = fator_de_rastreamento(ref.get("conversion"))

        # histórico do criativo POINT-IN-TIME (só lançamentos fechados ANTES da captação)
        mapa = mapa_de_nomes(an, client_id=client_id)
        hist = _historico_para_consulta(
            calcula_historico(an, client_id=client_id, corte=cap_start), mapa)

        def _chave(c):
            return criativo_do_lead(c, mapa)

        # teto por unidade (janela de captação em BRT → UTC naive, como o ledger)
        ws = datetime.combine(cap_start, datetime.min.time(), BRT).astimezone(timezone.utc).replace(tzinfo=None)
        we = datetime.combine(cap_end + timedelta(days=1), datetime.min.time(), BRT).astimezone(timezone.utc).replace(tzinfo=None)
        _, por_unidade, _ = tetos_completos(
            an, lg, run_id=run_id, win_start=ws, win_end=we,
            client_id=client_id, calc=calc, historico=hist, chave_criativo=_chave)

        # as duas bases casadas + gasto por campanha
        haircut = _load_boleto_haircut()
        gross_up = _load_meta_gross_up()
        m = _load_matched(
            lf,
            ledger_reader=lambda cs, ce: read_ledger_leads(lg, cs, ce),
            sales_reader=lambda s, e: read_analytics_sales(an, s, e),
            spend_reader=lambda s, e: read_ad_spend(s, e, conn=an),
            cadastro_reader=lambda cs, ce: read_cadastros(rc, cs, ce, utms_extras=True),
            as_of=as_of, window_days=window_days, launches=launches)

        # gasto por anúncio (Meta) na mesma janela de captação
        insights = read_ad_insights(cap_start, cap_end + timedelta(days=1), conn=an)
        gasto_unid = gasto_por_unidade(insights, gross_up=gross_up)

        cobertura_vendas = read_sales_coverage(an)
        estado = estado_do_lancamento(cap_start, cap_end, vendas_start, vendas_end,
                                      as_of=as_of, window_days=window_days,
                                      sales_max=cobertura_vendas.get("overall"))
        neg = prepara_leads(m["matched_negocio"], mapa)
        tem_venda = bool(neg.get("converted", pd.Series(dtype=bool))
                         .fillna(False).astype(bool).any())

        campanhas = tabela_campanhas(neg, m["spend_df"], haircut=haircut,
                                     meta_gross_up=gross_up, tem_venda=tem_venda)
        nb = linha_naobase(m["naobase_sales"], haircut) if tem_venda else None
        if nb is not None:
            campanhas = pd.concat([campanhas, pd.DataFrame([nb])],
                                  ignore_index=True)
        unidades = tabela_unidades(neg, por_unidade, gasto_unid,
                                   haircut=haircut, tem_venda=tem_venda)
        if len(unidades):
            unidades["no_corte"] = (
                (unidades["leads_ledger"] >= corte_leads)
                & (pd.to_numeric(unidades["gasto"], errors="coerce") >= corte_gasto))
        julg = julga_dentro_vs_acima(
            unidades[unidades.get("no_corte", pd.Series(dtype=bool)).fillna(False)]
            if len(unidades) else unidades,
            tolerancia_meta=tolerancia_meta)
        por_tipo = criativos_por_tipo(unidades, campanhas)
        sep_temp = separacao_por_temperatura(m["matched_modelo"],
                                             tem_venda=tem_venda)

        # De onde veio o comprador (nota 8 do Ramon, 31/08): a tabela de
        # campanhas casa venda SÓ com cadastro da captação DESTE LF; as vendas
        # 'Não está na base' são re-casadas aqui contra os cadastros dos 90
        # dias ANTERIORES à captação. O render monta a tabela: este LF /
        # captação dos 90d anteriores / sem cadastro nos 90d. Mesmo matcher
        # canônico e mesmo haircut de boleto das outras contas.
        naobase_90d = None
        if tem_venda and m["naobase_sales"] is not None and len(m["naobase_sales"]):
            antigos = read_cadastros(rc, cap_start - timedelta(days=90),
                                     cap_start - timedelta(days=1))
            m90 = build_matched_df(antigos, m["naobase_sales"], window_days=180)
            b90 = _bucket_metrics(m90, "cadastro 90d", "cadastro 90d",
                                  investimento=None, haircut=haircut)
            naobase_90d = dict(vendas=b90.n_conversions,
                               faturamento=b90.faturamento,
                               cadastros_antigos=int(len(antigos)))

        # RÉGUA DE PRODUTO — enumerado obrigatório da janela de vendas: cada
        # produto vendido, com a flag "casou algum padrão do yaml". Produto órfão
        # (vendeu e não casou) é o buraco de 36% do DEV21; aqui ele fica VISÍVEL
        # e o CLI decide se grita.
        produtos = []
        if vendas_start and vendas_end and estado not in (
                "captacao_aberta", "captacao_fechada_venda_nao_aberta"):
            vj = read_analytics_sales(an, vendas_start, vendas_end + timedelta(days=1))
            pats = _load_launch_products()
            if len(vj):
                g = (vj.assign(produto=vj["produto"].astype(str))
                     .groupby(["produto", "origem"])
                     .agg(n=("sale_value", "size"), valor=("sale_value", "sum"))
                     .reset_index())
                for r in g.itertuples(index=False):
                    produtos.append(dict(
                        produto=r.produto, gateway=r.origem, n=int(r.n),
                        valor=float(r.valor),
                        casou_padrao=any(p in r.produto.lower() for p in pats)))

        # coberturas medidas (o relatório imprime; o CLI aplica o piso)
        gasto_meta_total = float(insights["spend"].sum()) * gross_up if len(insights) else 0.0
        gasto_casado = float(pd.to_numeric(
            unidades[unidades["canal"] == "meta"]["gasto"], errors="coerce")
            .sum()) if len(unidades) else 0.0
        crit = neg["criativo"].astype(str)
        ids_nao_resolvidos = int((crit.str.isdigit() & (crit.str.len() >= 6)).sum())

        meta = dict(
            lf=lf, client_id=client_id, as_of=str(as_of), gerado_em=str(datetime.now(BRT)),
            cap_start=str(cap_start), cap_end=str(cap_end),
            vendas_start=str(vendas_start), vendas_end=str(vendas_end),
            estado=estado, tem_venda=tem_venda, window_days=window_days,
            sales_max=str(cobertura_vendas.get("overall")),
            referencia_id=ref.get("referencia_id"), ruler_run_id=run_id,
            referencia_snapshot=ref,          # o payload INTEIRO, congelado
            fator_rastreamento=fator, fator_procedencia=fator_proc,
            credito_nao_respondente=credito_do_nao_respondente(ref),
            boleto_haircut=haircut, meta_gross_up=gross_up,
            corte_leads=corte_leads, corte_gasto=corte_gasto,
            tolerancia_meta=tolerancia_meta,
            historico_criativos=len(hist), historico_corte=str(cap_start),
            devolvidos_n=0,                   # LF64: debriefing ainda não existe
            cobertura=dict(
                gasto_meta_total=gasto_meta_total, gasto_meta_casado=gasto_casado,
                pct_gasto_casado=(gasto_casado / gasto_meta_total
                                  if gasto_meta_total else None),
                cadastros=int(len(neg)),
                leads_sem_criativo=int((crit == "").sum()),
                leads_criativo_macro=int(crit.isin(("{{ad.name}}", "{{adset.name}}")).sum()),
                ids_nao_resolvidos=ids_nao_resolvidos),
            produtos_janela=produtos,
            naobase_90d=naobase_90d,
        )
        return dict(campanhas=campanhas, unidades=unidades,
                    criativos_por_tipo=por_tipo, julgamento=julg,
                    separacao_temperatura=sep_temp, meta=meta)
    finally:
        for c in (lg, an, rc):
            try:
                c.close()
            except Exception:
                pass
