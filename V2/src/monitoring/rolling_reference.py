"""Builder da referência rolante — lado CONVERSÃO/CALIBRAÇÃO.

Transforma a "janela madura rotulada" (`src/data/matured_window.py`) em:
  - conversão REALIZADA por decil / canal (Meta/Google) / balde (Lead/Champion/
    Challenger), a barra móvel que substitui o "Top5 ROAS" congelado;
  - o CALIBRADOR re-ajustado (score→P(compra) real) na mesma janela, pra a métrica
    exibida ser conversão ESPERADA nos leads de hoje.

Uma matched-df, dois usos (a conversão e o calibrador consomem o MESMO casamento).

Reuso (não duplica o join lead↔venda — o incidente fundador da /sw-architect):
  - `build_matched_df` + `read_analytics_sales` (validation): matcher canônico
    email+tel+last6, point-in-time, devolve `converted`.
  - `channel_from_source` / `bucket_from_utm` (campaign_classifier): mesmos
    classificadores do painel de decis (fonte única do split).
  - `make_calibrator` (model.calibration): a Estratégia isotônica que já existe.

Limite conhecido (MVP): a fatia da PONTE (`scores_historicos`, < cutover) não tem
UTM, então canal/balde contam só a fatia do LEDGER (senão os leads sem UTM virariam
'organic' falso). Total e por-decil usam tudo. Isso melhora conforme o ledger
aprofunda e a ponte encolhe.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from src.data.matured_window import (
    build_matured_window, limites_de_compra, matured_bounds, resolve_ruler_run_id,
    DEFAULT_MATURATION_DAYS, MATURACAO_MAXIMA_DIAS, MATURACAO_MINIMA_DIAS,
)
# NOTE(sw-architect): build_matched_df/read_analytics_sales moram hoje em
# src/validation/model_performance. É reuso (não duplicação); a limpeza de camada
# (mover o join pra src/data e os dois consumirem de lá) fica pra um passo próprio.
from src.validation.model_performance import build_matched_df, read_analytics_sales
from src.monitoring.campaign_classifier import bucket_from_utm, channel_from_source
from src.model.calibration import make_calibrator

logger = logging.getLogger(__name__)


# Faixa esperada do fator de rastreamento (Decisão 9). Medido em 15/08/2026 sobre 25
# lançamentos: mediana 1,18, recentes 1,27. Fora da faixa não bloqueia (o número é
# gravado do mesmo jeito), mas grita: ou o funil mudou, ou o casamento quebrou.
FATOR_RASTREAMENTO_FAIXA = (1.05, 1.40)


def _t8(t) -> Optional[str]:
    d = "".join(c for c in str(t or "") if c.isdigit())
    return d[-8:] if len(d) >= 8 else None


def identidades_conhecidas(conn) -> tuple[set, set]:
    """Emails e telefones-8 de TODO MUNDO que já passou pela base (espinha de
    cadastros + captações históricas). É o 'quem a gente conhece' da decomposição
    do fator de rastreamento — venda não-casada de pessoa conhecida comprou por
    outro caminho e não corrige a conversão por lead."""
    emails: set = set()
    t8s: set = set()
    for sql in (
        "SELECT lower(trim(email)), phone FROM cadastros WHERE email IS NOT NULL",
        "SELECT lower(trim(email)), phone FROM captacoes WHERE email IS NOT NULL",
    ):
        for em, tel in conn.run(sql):
            if em:
                emails.add(em)
            t = _t8(tel)
            if t:
                t8s.add(t)
    return emails, t8s


def fator_de_rastreamento(sales_df: pd.DataFrame, leads_df: pd.DataFrame,
                          conhecidos_emails: set, conhecidos_t8: set) -> Optional[dict]:
    """Decompõe as vendas da janela e mede o fator de correção do rastreamento.

    Cada venda cai num de três baldes:
      casada    — a identidade (email/tel-8) pertence a um lead da janela madura
      conhecida — não é lead da janela, mas existe na base (outro funil/aluno antigo);
                  NUNCA corrige a conversão por lead
      sumida    — não existe em lugar nenhum; teto superior da falha de casamento

        fator = (casadas + sumidas) ÷ casadas

    Identidade simples (email/tel-8), não o matcher canônico completo: o fator é uma
    razão entre contagens grandes, e o refinamento de last6/temporal muda as duas
    pontas quase igual. Devolve None (e loga) se não houver venda casada — gravar um
    fator sem base seria pior que não ter fator.
    """
    if sales_df is None or sales_df.empty or leads_df is None or leads_df.empty:
        logger.warning("[rolling_reference] sem vendas ou sem leads — fator de "
                       "rastreamento não calculado")
        return None
    em_janela = set(leads_df["email"].dropna().astype(str).str.lower())
    tel_col = (leads_df["telefone"] if "telefone" in leads_df.columns
               else pd.Series(dtype=object))
    t8_janela = {t for t in tel_col.map(_t8) if t}
    # 1 venda por PESSOA: dedup pela identidade (email, senão tel-8). Venda sem
    # identidade nenhuma fica — vai cair em "sumida", que é o que ela é.
    v = sales_df.copy()
    v["_em"] = (v["email"].astype(str).str.lower().str.strip()
                .where(v["email"].notna()))
    v["_t8"] = v["telefone"].map(_t8) if "telefone" in v.columns else None
    v["_key"] = v["_em"].fillna(v["_t8"])
    vendas = pd.concat([v[v["_key"].notna()].drop_duplicates("_key"),
                        v[v["_key"].isna()]])
    casadas = conhecidas = sumidas = 0
    for em, t in zip(vendas["_em"], vendas["_t8"]):
        em = em if isinstance(em, str) and em else None
        if (em and em in em_janela) or (t and t in t8_janela):
            casadas += 1
        elif (em and em in conhecidos_emails) or (t and t in conhecidos_t8):
            conhecidas += 1
        else:
            sumidas += 1
    if casadas <= 0:
        logger.warning("[rolling_reference] nenhuma venda casada na janela — fator de "
                       "rastreamento não calculado (%d conhecidas, %d sumidas)",
                       conhecidas, sumidas)
        return None
    fator = (casadas + sumidas) / casadas
    lo, hi = FATOR_RASTREAMENTO_FAIXA
    if not (lo <= fator <= hi):
        logger.warning("[rolling_reference] fator de rastreamento %.3f FORA da faixa "
                       "esperada [%.2f, %.2f] — funil mudou ou casamento quebrou; "
                       "gravado mesmo assim, investigar", fator, lo, hi)
    logger.info("[rolling_reference] fator de rastreamento %.3f (%d casadas, %d "
                "conhecidas, %d sumidas)", fator, casadas, conhecidas, sumidas)
    return {"factor": round(fator, 4), "casadas": casadas, "conhecidas": conhecidas,
            "sumidas": sumidas, "faixa_esperada": list(FATOR_RASTREAMENTO_FAIXA),
            "metodo": "sumidas-only"}


def _aplica_janela_do_calendario(matched: pd.DataFrame, *, as_of: date,
                                 launches: Optional[dict] = None) -> pd.DataFrame:
    """Aperta o `converted` pro prazo do CALENDÁRIO e tira lead de janela aberta.

    Regra por lead (a mesma de `compra_conta_para_o_lead`): a compra conta da
    captação até o `vendas_end` do lançamento em que o lead entrou; sem lançamento,
    piso de `MATURACAO_MINIMA_DIAS`. Lead cujo limite ainda não passou (janela
    ABERTA) sai do resultado: ele ainda pode comprar, e contá-lo agora gravaria uma
    taxa subestimada na referência.

    Medição que motivou (14/08/2026, 26 lançamentos fechados): com ciclo de 21d a
    diferença é zero, mas DEV19 (ciclo de 40d) tem 15,4% dos compradores DEPOIS do
    dia 21 — o prazo fixo de 21d jogava esses compradores fora.
    """
    if matched.empty:
        return matched
    lim = limites_de_compra(matched["data_captura"], launches)
    lim_ts = pd.to_datetime(lim["limite"])

    sd = pd.to_datetime(matched["sale_date"], errors="coerce")
    try:
        sd = sd.dt.tz_localize(None)
    except TypeError:
        pass  # já era naive
    dentro = (sd.dt.normalize() <= lim_ts).fillna(False)

    out = matched.copy()
    out["converted"] = (out["converted"].fillna(False) & dentro).astype(bool)

    fechada = lim_ts.notna() & (lim_ts <= pd.Timestamp(as_of))
    n_abertos = int((~fechada).sum())
    if n_abertos:
        logger.info("[rolling_reference] %d leads de janela ainda aberta fora da "
                    "referência (limite > %s)", n_abertos, as_of)
    logger.info("[rolling_reference] janela de compra por calendário: %d leads com "
                "lançamento, %d no piso de %dd",
                int(lim["lf"].notna().sum()), int(lim["lf"].isna().sum()),
                MATURACAO_MINIMA_DIAS)
    return out[fechada].copy()


def label_matured(matured_df: pd.DataFrame, sales_df: pd.DataFrame, *,
                  as_of: Optional[date] = None,
                  launches: Optional[dict] = None,
                  conversion_window_days: Optional[int] = None) -> pd.DataFrame:
    """Casa a janela madura com as vendas (matcher canônico) e devolve os leads de
    janela FECHADA + coluna `converted` (venda dentro da janela de compra do LEAD).

    A janela de compra vem do CALENDÁRIO, não de um prazo fixo: da captação até o
    `vendas_end` do lançamento do lead (depois disso a compra pertence ao lançamento
    seguinte). O casamento roda com `window_days=MATURACAO_MAXIMA_DIAS` só como teto
    de sanidade contra `vendas_end` absurdo na planilha.

    `conversion_window_days` (diagnóstico): prazo FIXO igual pra todo lead, ignorando
    o calendário. Serve pra reproduzir números antigos; nunca em produção.
    """
    if conversion_window_days is not None:
        return build_matched_df(matured_df, sales_df, window_days=conversion_window_days)
    matched = build_matched_df(matured_df, sales_df, window_days=MATURACAO_MAXIMA_DIAS)
    return _aplica_janela_do_calendario(matched, as_of=as_of or date.today(),
                                        launches=launches)


# Base mínima pra um SEGMENTO (canal ou balde) publicar taxa de conversão própria.
# Abaixo disso o segmento não entra em by_channel/by_bucket, e o consumidor degrada
# pra "—" (é o que o painel de decis já faz com balde ausente).
#
# Por que existe: em 02/08/2026 o teto de CPL do Champion saiu R$20,81 no relatório
# porque a taxa dele vinha de 7 vendas em 438 leads (1,598%, quase o dobro da
# população). O operador identificou na hora que o teto real é menos da metade
# disso. Uma taxa de conversão de ordem 1% precisa de centenas de leads e dezenas de
# vendas pra ter erro tolerável; com 7 vendas o intervalo de confiança cobre de
# ~0,8% a ~3,3%, e qualquer Δ ou teto derivado dali é ruído com aparência de número.
MIN_SEGMENT_CONV = 30      # vendas na janela madura
MIN_SEGMENT_LEADS = 1000   # leads na janela madura


def _conv_by(df: pd.DataFrame, key, *, min_conv: int = 0, min_leads: int = 0) -> dict:
    """conversão por grão: {chave: {leads, conv, rate}} a partir da coluna `converted`.

    `min_conv`/`min_leads` cortam segmento de base fina (ver MIN_SEGMENT_*): ele fica
    FORA do dict em vez de publicar taxa de ruído. Quem sai é logado, nunca silencioso.
    """
    out, cortados = {}, []
    g = df.groupby(key)["converted"]
    for k, s in g:
        n = int(s.size)
        c = int(s.sum())
        if c < min_conv or n < min_leads:
            cortados.append(f"{k}({c}v/{n}l)")
            continue
        out[k] = {"leads": n, "conv": c, "rate": (c / n) if n else 0.0}
    if cortados:
        logger.warning("[rolling_reference] segmentos sem base mínima (%dv/%dl), fora da "
                       "referência: %s", min_conv, min_leads, " · ".join(cortados))
    return out


def conversion_reference(matched_df: pd.DataFrame, *, bucket_map=None,
                        min_segment_conv: int = MIN_SEGMENT_CONV,
                        min_segment_leads: int = MIN_SEGMENT_LEADS) -> dict:
    """Conversão realizada por decil (tudo), e por canal/balde (só a fatia com UTM).

    by_decile / overall usam a janela inteira (o decil é da régua, vale pra ponte e
    ledger). by_channel / by_bucket usam só linhas COM utm_source (o ledger) — a
    ponte sem UTM não pode virar canal falso.

    `min_segment_conv`/`min_segment_leads`: piso de base pra um segmento publicar taxa
    própria (ver MIN_SEGMENT_*). Zerar os dois desliga o corte: serve pra teste de
    agregação com fixture pequena, NÃO pra produção.
    """
    if matched_df.empty:
        return {"overall": {"leads": 0, "conv": 0, "rate": 0.0},
                "by_decile": {}, "by_channel": {}, "by_bucket": {},
                "channel_bucket_coverage": {"leads_com_utm": 0, "leads_total": 0}}

    m = matched_df.copy()
    m["converted"] = m["converted"].fillna(False).astype(bool)
    n = len(m)
    c = int(m["converted"].sum())
    overall = {"leads": n, "conv": c, "rate": (c / n) if n else 0.0}

    # por decil (int 1..10 → chave "D01".."D10")
    dec = m.dropna(subset=["decil_challenger"]).copy()
    dec["_dk"] = dec["decil_challenger"].astype(int).map(lambda d: f"D{d:02d}")
    by_decile = _conv_by(dec, "_dk")

    # canal/balde só onde há UTM (fatia do ledger), e só com base mínima. Segmento
    # fino sai fora e o consumidor mostra "—" em vez de taxa de ruído.
    utm = m[m["utm_source"].notna()].copy()
    utm["channel"] = utm["utm_source"].apply(channel_from_source)
    by_channel = _conv_by(utm, "channel",
                          min_conv=min_segment_conv, min_leads=min_segment_leads)
    # Balde Lead/Champion/Challenger é conceito da CAPTAÇÃO META: 'Lead padrão'
    # = captação fria da Meta sem etiqueta de modelo. Antes o balde era
    # calculado sobre TODOS os canais e o 'Lead' saía com ~47% de google e
    # orgânico dentro (medido em 16/08: 16.615 meta + 12.831 google + 1.800
    # outros na janela de 90d) — e essa taxa contaminada virava o teto de CPL
    # da linha Lead no relatório diário. Google/orgânico têm a própria linha
    # em by_channel; no balde, só Meta entra.
    meta = utm[utm["channel"] == "meta"].copy()
    meta["bucket"] = meta["utm_campaign"].apply(lambda x: bucket_from_utm(x, bucket_map))
    by_bucket = _conv_by(meta, "bucket",
                         min_conv=min_segment_conv, min_leads=min_segment_leads)

    logger.info(
        "[rolling_reference] conversão: overall %.3f%% (%d/%d) · canal/balde de %d leads c/ UTM",
        overall["rate"] * 100, c, n, len(utm),
    )
    return {"overall": overall, "by_decile": by_decile, "by_channel": by_channel,
            "by_bucket": by_bucket,
            "channel_bucket_coverage": {"leads_com_utm": len(utm), "leads_total": n}}


# Faixa em que o lift medido é confiável; fora dela (ou sem massa) o payload
# marca inválido e o teto usa 1,0. Estudo 18/08 (24 lançamentos fechados):
# google agregado 1,31 estável; espalhamento por lançamento 0,7-2,0.
LIFT_PLATAFORMA_FAIXA = (0.8, 1.8)
LIFT_PLATAFORMA_MIN_LEADS = 2000
LIFT_PLATAFORMA_MIN_COMPRADORES = 15


def lift_de_plataforma(matched: pd.DataFrame):
    """Razão conversão REAL ÷ prevista-pelos-decis dos leads GOOGLE, na mesma
    janela madura da referência.

    Por que existe (estudo 18/08, 24 lançamentos): o lead google converte ~31%
    acima do que a mistura de decis dele prevê (a pesquisa dele parece mediana,
    a compra não) — o teto google saía ~R$6,80 onde a prática sustenta ~R$8,90.
    A Meta mediu 0,96 (calibrada): não recebe fator. Linhas da ponte sem UTM
    ficam fora da medição (não dá pra saber a plataforma)."""
    df = matched
    for col in ("utm_source", "utm_campaign", "utm_content",
                "decil_challenger", "converted"):
        if col not in df.columns:
            return None
    base = df[df["utm_source"].notna() & df["decil_challenger"].notna()].copy()
    if base.empty:
        return None
    google = (base["utm_source"].astype(str).str.contains("google", case=False)
              | base["utm_content"].astype(str).str.match(r"^\d{10,}$")
              | (base["utm_campaign"].astype(str) == "devlf"))
    g = base[google]
    conv_por_decil = base.groupby("decil_challenger")["converted"].mean()
    n, compradores = len(g), int(g["converted"].sum())
    if n < LIFT_PLATAFORMA_MIN_LEADS or compradores < LIFT_PLATAFORMA_MIN_COMPRADORES:
        return {"google": {"lift": None, "valido": False, "n": n,
                           "compradores": compradores, "motivo": "sem_massa"}}
    prevista = float(g["decil_challenger"].map(conv_por_decil).mean())
    real = float(g["converted"].mean())
    lift = real / prevista if prevista > 0 else None
    valido = (lift is not None
              and LIFT_PLATAFORMA_FAIXA[0] <= lift <= LIFT_PLATAFORMA_FAIXA[1])
    return {"google": {"lift": (round(lift, 4) if lift else None),
                       "valido": bool(valido), "n": n,
                       "compradores": compradores,
                       "real": round(real, 6), "prevista": round(prevista, 6),
                       "faixa": list(LIFT_PLATAFORMA_FAIXA)}}


def fit_calibrator(matched_df: pd.DataFrame, *, method: str = "isotonic"):
    """Re-ajusta o calibrador (score_challenger → P(compra) real) na janela madura.
    É o passo que mantém a conversão ESPERADA fiel quando o mercado se move."""
    m = matched_df.dropna(subset=["score_challenger"]).copy()
    y_prob = pd.to_numeric(m["score_challenger"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    y_true = m["converted"].fillna(False).astype(int).to_numpy()
    if y_prob.size == 0:
        raise ValueError("[rolling_reference] sem score na janela — não dá pra calibrar.")
    cal = make_calibrator(method).fit(y_prob, y_true)
    logger.info("[rolling_reference] calibrador %s ajustado em %d leads (%d compras)",
                method, y_prob.size, int(y_true.sum()))
    return cal


def sample_calibration_curve(cal, *, n: int = 101) -> dict:
    """Serializa o calibrador como uma curva amostrada score→P num grid [0,1]. O
    leitor reconstrói a conversão ESPERADA de um lead com np.interp — portável, sem
    depender de sklearn na leitura (jsonb na tabela da referência)."""
    import numpy as np
    x = np.linspace(0.0, 1.0, n)
    y = cal.transform(x)
    return {"method": getattr(cal, "method", "unknown"),
            "x": [round(float(v), 4) for v in x.tolist()],
            "y": [round(float(v), 6) for v in y.tolist()]}


def build_conversion_reference(
    *,
    as_of: Optional[date] = None,
    window_days: int = 90,
    maturation_days: int = DEFAULT_MATURATION_DAYS,
    client_id: str = "devclub",
    ruler_run_id: Optional[str] = None,
    bucket_map=None,
    launches: Optional[dict] = None,
    conn=None,
) -> dict:
    """Orquestra: janela madura → casa vendas UMA vez → conversão de referência +
    calibrador. Devolve o dict pronto pra materializar na tabela da referência.

    `maturation_days` é o RECUO da janela de captação (garante que todo lead já teve
    o mínimo de dias pra comprar). O prazo de compra de cada lead vem do calendário
    (`label_matured`); leads de lançamento ainda aberto saem lá.
    """
    as_of = as_of or date.today()
    run_id = ruler_run_id or resolve_ruler_run_id(client_id)
    win_start, win_end = matured_bounds(window_days=window_days,
                                        maturation_days=maturation_days, as_of=as_of)

    own = conn is None
    from src.data.analytics_connection import open_analytics_connection
    conn = conn or open_analytics_connection(timeout=180)
    try:
        matured = build_matured_window(
            window_days=window_days, maturation_days=maturation_days, as_of=as_of,
            client_id=client_id, ruler_run_id=run_id, conn=conn,
        )
        # Vendas de [win_start, as_of]: o limite de compra por lead é <= as_of (lead
        # de janela aberta sai), então esse range cobre tudo. end exclusivo → +1 dia.
        sales = read_analytics_sales(conn, win_start.date(), as_of + timedelta(days=1))
        # Identidades de toda a base, pra decompor as vendas não-casadas (fator de
        # rastreamento). Carregado dentro do MESMO conn — depois ele pode fechar.
        conhecidos_emails, conhecidos_t8 = identidades_conhecidas(conn)
    finally:
        if own:
            conn.close()

    matched = label_matured(matured, sales, as_of=as_of, launches=launches)
    conv = conversion_reference(matched, bucket_map=bucket_map)
    # Fator de rastreamento MEDIDO na mesma janela (Decisão 9): a fatia de venda
    # "sumida" pertence aos leads; o teto lê conversion.tracking.factor do payload.
    tracking = fator_de_rastreamento(sales, matured, conhecidos_emails, conhecidos_t8)
    if tracking:
        conv["tracking"] = tracking
    # Proveniência da regra de contagem (valor no payload, não config implícita):
    # quem ler a referência sabe COMO a compra foi contada, sem arqueologia de git.
    conv["conversion_window"] = {
        "mode": "calendar",
        "floor_days": MATURACAO_MINIMA_DIAS,
        "cap_days": MATURACAO_MAXIMA_DIAS,
    }
    # Economia do teto (Fase 3): valor por venda da janela (cartão 2k + boleto 50%,
    # mistura REAL de gateways). Vive dentro do `conversion` jsonb → sem coluna nova.
    from src.monitoring.teto import value_per_sale_from_sales
    conv["economics"] = value_per_sale_from_sales(sales)
    # Lift de PLATAFORMA medido na mesma janela (google ~1,31; ver estudo 18/08).
    pl = lift_de_plataforma(matched)
    if pl:
        conv["platform_lift"] = pl
    cal = fit_calibrator(matched)
    return {
        "window_start": win_start.date().isoformat(),
        "window_end": win_end.date().isoformat(),
        "as_of": as_of.isoformat(),
        "ruler_run_id": run_id,
        "n_leads": len(matched),
        "conversion": conv,
        "calibrator": cal,
    }
