"""Nota do criativo como feature numérica, calculada ponto a ponto no tempo.

O pipeline remove `Content` (o nome do anúncio) de propósito, em
`feature_removal.remover_features_desnecessarias`, com o motivo certo: identidade de
anúncio como categoria faz o modelo decorar lançamento em vez de aprender sobre a pessoa.

Esta é a versão segura daquilo. Em vez da identidade, entra UM NÚMERO: quanto aquele
criativo convertia **antes da semana em que o lead entrou**. Não é categoria, não guarda
qual anúncio era, e não pode conter o futuro.

    lift  = conversão do criativo ÷ conversão do período
    peso  = n ÷ (n + K)                    <- encolhimento empírico de Bayes
    NOTA  = peso × lift + (1 − peso) × 1,0

O encolhimento é o que faz funcionar: sem ele (K=0) a nota fica PIOR que chutar a média,
porque criativo com 300 leads e 9 compradores receberia nota 3,0 e sequestraria o ranking.

Validação offline que motivou esta feature (sessão 083c887b, 03-05/08/2026):
  · leave-one-launch-out, 224 pares criativo×lançamento: erro −28%, separação 1,83x
  · composto com o modelo: lift do D10 de 1,69x para 2,93x, top 10% de 65 para 88
    compradores, positivo em 100% de 400 reamostras de criativos inteiros
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

K_ENCOLHIMENTO = 4000     # varrido em [0, 250, ..., 16000]; 4000 foi o melhor, 2000 empata
MIN_HIST = 50             # histórico mínimo do criativo para ele ganhar nota própria
MIN_HIST_PERIODO = 20_000  # leads mínimos no passado para a semana ser calculável
# VAZAMENTO SUTIL: o histórico precisa de desfecho, e desfecho de W dias só existe W dias
# depois. Um lead captado 3 dias antes da semana W ainda não teria esse desfecho na vida
# real. Sem carência, o modelo enxerga um pedaço de futuro e o ganho sai inflado.
#
# JANELA e CARENCIA são o MESMO número por construção, e é por isso que a carência deriva
# da janela em vez de ser constante própria. Carência menor que a janela do desfecho (ex.:
# carência de 21 dias lendo o `bought_45d` já pronto da tabela) devolve o vazamento pela
# porta dos fundos: faltariam 24 dias para aquele desfecho existir.
#
# 21 e não 45: a compra tem mediana de 13 dias, e 21 já cobre 73% delas contra 85,8% de 45.
# Como a nota é uma RAZÃO (conversão do criativo ÷ conversão do período), perder comprador
# tardio no numerador e no denominador se cancela. O que 45 custava era cobertura: derrubava
# a fração de leads com nota de 82,5% para 49,8%, e metade dos leads em nota neutra é onde
# o ganho morria. Medido offline em 67 mil leads: com 45 o composto dava AUC 0,6510 e 71
# compradores no top 10%; com 21 dá 0,6763 e 79 (modelo sozinho: 0,6348 e 61).
JANELA_DESFECHO_DIAS = 21
CARENCIA_DIAS = JANELA_DESFECHO_DIAS
NOTA_NEUTRA = 1.0         # criativo sem histórico não é bom nem ruim


def _canal(source) -> str:
    """Meta e Google convertem diferente; a nota por canal tira essa variação de dentro."""
    v = str(source or "").lower()
    if "google" in v or "youtube" in v:
        return "google"
    if any(x in v for x in ("facebook", "fb", "meta", "ig", "instagram")):
        return "meta"
    return "outro"


def _carrega_transcricoes() -> dict:
    """Fala dos vídeos, de `analytics.transcricoes`. Vazio se a tabela não existir."""
    from src.data.analytics_connection import open_analytics_connection

    conn = open_analytics_connection(timeout=300)
    try:
        linhas = conn.run("SELECT criativo, texto, palavras, dur_s FROM transcricoes")
    except Exception as e:                       # tabela ausente não pode derrubar o treino
        logger.warning(f"  [nota_criativo] sem transcrições ({type(e).__name__}); "
                       f"a nota de texto sai neutra")
        return {}
    finally:
        conn.close()
    out = {}
    for cr, txt, pal, dur in linhas:
        if txt and len(str(txt).split()) >= 40:
            out[str(cr).strip()] = {"texto": str(txt),
                                    "ritmo": (pal / dur) if (pal and dur) else None}
    return out


def _tel8(t) -> str | None:
    d = "".join(c for c in str(t or "") if c.isdigit())
    return d[-8:] if len(d) >= 8 else None


def _carrega_historico() -> pd.DataFrame:
    """Histórico de captação com desfecho na janela curta, de `analytics.captacoes`.

    NÃO usa a coluna `bought_45d` pronta: ela é um desfecho de 45 dias, e a carência aqui
    é de JANELA_DESFECHO_DIAS. Ler os 45 com carência de 21 deixaria 24 dias de futuro
    dentro da nota. O desfecho é recalculado casando com `analytics.sales` por e-mail e
    pelos 8 últimos dígitos do telefone, as mesmas chaves do resto do projeto.
    """
    from src.data.analytics_connection import open_analytics_connection

    conn = open_analytics_connection(timeout=900)
    try:
        # utm_content, não ad_name: a coluna do treino também é utm_content, e casar por
        # ela cobre 61% dos leads contra 54% do ad_name (que é uma versão normalizada,
        # com 1.287 nomes distintos contra 1.969). A união não acrescenta nada.
        linhas = conn.run("""
            SELECT utm_content, utm_source, captured_at::date,
                   lower(trim(email)), phone
            FROM captacoes
            WHERE utm_content IS NOT NULL AND captured_at IS NOT NULL
        """)
        vendas = conn.run("""
            SELECT lower(trim(email)), phone, sale_date::date
            FROM sales WHERE sale_date IS NOT NULL
        """)
    finally:
        conn.close()

    hist = pd.DataFrame(linhas, columns=["criativo", "source", "dia", "email", "tel"])
    hist["canal"] = hist["source"].map(_canal)
    hist["dia"] = pd.to_datetime(hist["dia"])
    hist["criativo"] = hist["criativo"].astype(str).str.strip()

    v = pd.DataFrame(vendas, columns=["email", "tel", "dt"])
    v["dt"] = pd.to_datetime(v["dt"])
    v["tel8"] = v["tel"].map(_tel8)
    por_email = v.dropna(subset=["email"]).groupby("email")["dt"].apply(list).to_dict()
    por_tel = v.dropna(subset=["tel8"]).groupby("tel8")["dt"].apply(list).to_dict()

    janela = pd.Timedelta(days=JANELA_DESFECHO_DIAS)
    hist["buy"] = [
        int(any(d0 <= s <= d0 + janela
                for s in (por_email.get(e, []) + por_tel.get(_tel8(t), []))))
        for e, t, d0 in zip(hist["email"], hist["tel"], hist["dia"])
    ]
    if hist["buy"].sum() == 0:
        raise ValueError(
            "[nota_criativo] histórico saiu com ZERO compradores em "
            f"{JANELA_DESFECHO_DIAS} dias sobre {len(hist):,} captações. A nota inteira "
            "viraria neutra em silêncio. Verificar o cruzamento com `analytics.sales`."
        )
    return hist.drop(columns=["email", "tel"])


def _notas_da_semana(hist_ate_aqui: pd.DataFrame, alvo: dict = None) -> dict:
    """NOTA por criativo, usando SÓ o histórico passado como argumento.

    `alvo` é para onde o encolhimento puxa quem tem pouco histórico. Sem ele, puxa para
    o neutro (1,0), que é o mesmo que dizer "não faço ideia". Com ele, puxa para o que a
    fala e o ritmo do vídeo sugerem, que é bem melhor que não fazer ideia.
    """
    if len(hist_ate_aqui) < MIN_HIST_PERIODO:
        return {}
    nivel = hist_ate_aqui["buy"].mean()
    if nivel <= 0:
        return {}
    g = hist_ate_aqui.groupby("criativo").agg(n=("buy", "size"), k=("buy", "sum"))
    g = g[g["n"] >= MIN_HIST]
    if g.empty:
        return {}
    lift = (g["k"] / g["n"]) / nivel
    peso = g["n"] / (g["n"] + K_ENCOLHIMENTO)
    destino = (g.index.map(lambda c: (alvo or {}).get(c, NOTA_NEUTRA))
               if alvo else NOTA_NEUTRA)
    return (peso * lift + (1 - peso) * destino).to_dict()


def _notas_por_canal(hist_ate_aqui: pd.DataFrame, alvo: dict = None) -> dict:
    """A mesma NOTA, mas calculada DENTRO de cada canal. Chave = (canal, criativo).

    O `alvo` do encolhimento é compartilhado entre os canais de propósito: a fala do vídeo
    não muda quando ele roda no Google em vez da Meta. O que muda por canal é o LIFT, que
    é medido contra a conversão daquele canal.
    """
    out = {}
    for cn, bloco in hist_ate_aqui.groupby("canal"):
        for cr, val in _notas_da_semana(bloco, alvo=alvo).items():
            out[(cn, cr)] = val
    return out


def _prior_por_texto(notas: dict, volumes: dict, transcricoes: dict) -> dict:
    """O que a FALA e o RITMO do vídeo sugerem, pelos vizinhos que já rodaram.

    Serve de alvo do encolhimento no lugar do 1,0 cego: criativo com pouco histórico é
    puxado para o que vídeos parecidos entregaram, em vez de para a média geral. Texto e
    ritmo entram como DUAS medidas de semelhança independentes (a correlação entre as
    previsões delas é +0,10, então cada uma vê uma coisa).

    Nenhum parâmetro é estimado a partir da conversão: só semelhança e média ponderada.
    """
    if len(transcricoes) < 15:
        return {}
    import re
    import unicodedata

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    def _limpa(t):
        t = unicodedata.normalize("NFD", str(t))
        t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", t)).strip()

    def _familia(c):
        u = unicodedata.normalize("NFD", str(c)).upper()
        m = re.search(r"AD0*(\d+)", u)
        if not m:
            return str(c)
        return (re.sub(r"[^A-Z]", "", u[:m.start()]) or "SEM") + f"-AD{int(m.group(1)):04d}"

    nomes = sorted(transcricoes)
    S_txt = cosine_similarity(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=6000, sublinear_tf=True)
        .fit_transform([_limpa(transcricoes[c]["texto"]) for c in nomes]))
    np.fill_diagonal(S_txt, 0.0)
    rit = np.array([transcricoes[c]["ritmo"] or np.nan for c in nomes], dtype=float)
    dist = np.abs(rit[:, None] - rit[None, :])
    desv = np.nanstd(rit) or 1.0
    S_rit = np.where(np.isnan(dist), 0.0, 1.0 / (1.0 + dist / desv))
    np.fill_diagonal(S_rit, 0.0)

    fam = np.array([_familia(c) for c in nomes])
    alvo = np.array([notas.get(c, np.nan) for c in nomes])
    vol = np.array([volumes.get(c, 0.0) for c in nomes])
    tem = ~np.isnan(alvo)
    out = {}
    for i, cr in enumerate(nomes):
        vals = []
        for S in (S_txt, S_rit):
            sim = S[i].copy()
            sim[fam == fam[i]] = 0.0     # parente não prevê parente
            sim[sim >= 0.90] = 0.0       # nem o mesmo vídeo sob outro nome
            sim[~tem] = 0.0
            cand = np.array([j for j in np.argsort(-sim) if tem[j] and sim[j] > 0])
            if not len(cand):
                continue
            p = [np.average(alvo[cand[:kv]], weights=sim[cand[:kv]] * vol[cand[:kv]])
                 for kv in (3, 5, 8, 12) if (sim[cand[:kv]] * vol[cand[:kv]]).sum() > 0]
            if p:
                vals.append(float(np.mean(p)))
        if vals:
            out[cr] = float(np.mean(vals))
    return out


def adicionar_nota_criativo(df: pd.DataFrame, *, col_criativo: str = "Content",
                            col_data: str = "Data", col_source: str = "Source",
                            nome_saida: str = "nota_criativo",
                            historico: pd.DataFrame | None = None,
                            transcricoes: dict | None = None,
                            cobertura_minima: float = 0.30) -> pd.DataFrame:
    """Devolve o df com TRÊS colunas de nota, todas calculadas ponto a ponto no tempo.

    `nota_criativo`        conversão passada, encolhida para 1,0
    `nota_criativo_canal`  a mesma, mas calculada dentro de Meta e Google separados
    `nota_criativo_texto`  encolhida para o que a fala e o ritmo do vídeo sugerem,
                           em vez de para o 1,0 cego

    As três são correlacionadas de propósito. Árvore lida bem com isso, e a importância de
    cada uma responde qual variante o modelo de fato usa — o que a combinação por fora
    (produto, média de postos) não consegue perguntar.

    Para cada SEMANA presente no df, a nota sai só das captações anteriores àquela semana.
    Um lead de junho recebe a nota que o criativo dele tinha em junho, nunca a de hoje.

    Falha alto se as colunas de origem sumirem ou se a cobertura vier abaixo do piso: nota
    neutra em quase todo mundo significa feature inerte, e isso tem que aparecer no log em
    vez de virar uma coluna de 1,0 que ninguém percebe.
    """
    faltando = [c for c in (col_criativo, col_data) if c not in df.columns]
    if faltando:
        raise KeyError(
            f"[nota_criativo] coluna(s) ausente(s): {faltando}. A nota precisa do nome do "
            f"anúncio e da data do lead, e ambas somem na Célula 8 — chame esta função ANTES "
            f"de remover_features_desnecessarias()."
        )

    hist = _carrega_historico() if historico is None else historico.copy()
    logger.info(f"  [nota_criativo] histórico: {len(hist):,} captações · "
                f"{hist['criativo'].nunique():,} criativos · "
                f"{int(hist['buy'].sum()):,} compradores")

    data = pd.to_datetime(df[col_data], errors="coerce")
    criativo = df[col_criativo].astype(str).str.strip()
    semana = data.dt.to_period("W")

    canal = (df[col_source].map(_canal) if col_source in df.columns
             else pd.Series(["outro"] * len(df), index=df.index))
    if col_source not in df.columns:
        logger.warning(f"  [nota_criativo] coluna '{col_source}' ausente; a nota por canal "
                       f"vai sair igual à geral")
    trs = _carrega_transcricoes() if transcricoes is None else transcricoes

    por_semana, por_semana_canal, por_semana_texto = {}, {}, {}
    por_semana_canal_texto = {}
    for sem in sorted(s for s in semana.dropna().unique()):
        # só histórico já MADURO: o desfecho de 45 dias precisa ter tido tempo de existir
        corte = sem.start_time - pd.Timedelta(days=CARENCIA_DIAS)
        passado = hist[hist["dia"] < corte]
        base = _notas_da_semana(passado)
        por_semana[sem] = base
        por_semana_canal[sem] = _notas_por_canal(passado)
        if base and trs:
            g = passado.groupby("criativo")["buy"].size()
            prior = _prior_por_texto(base, g.to_dict(),
                                     {k: v for k, v in trs.items() if k in g.index})
            # encolhe para o que o vídeo sugere, no lugar do 1,0 cego
            n = g.reindex(base.keys()).fillna(0)
            peso = n / (n + K_ENCOLHIMENTO)
            comb = {}
            for cr, nota_base in base.items():
                pv = prior.get(cr)
                if pv is None:
                    comb[cr] = nota_base
                else:
                    p = float(peso.get(cr, 0.0))
                    lift = (nota_base - (1 - p) * NOTA_NEUTRA) / p if p > 0 else NOTA_NEUTRA
                    comb[cr] = p * lift + (1 - p) * pv
            for cr, pv in prior.items():
                comb.setdefault(cr, pv)      # estreante ganha a nota que o vídeo sugere
            por_semana_texto[sem] = comb
            # A QUARTA VARIANTE: canal E texto na mesma nota. As duas anteriores foram
            # construídas como ALTERNATIVAS, e a comparação entre elas trocava duas coisas
            # de uma vez (adicionava o canal e removia o texto), então não dava para
            # atribuir a diferença a nenhuma das duas. Aqui o lift é medido dentro do
            # canal e o encolhimento puxa para o que o vídeo sugere, em vez do 1,0 cego.
            por_semana_canal_texto[sem] = _notas_por_canal(passado, alvo=prior)
        else:
            por_semana_texto[sem] = base
            por_semana_canal_texto[sem] = por_semana_canal[sem]

    def _monta(mapa, chave_canal=False):
        return np.array([
            (mapa.get(s, {}).get((cn, c) if chave_canal else c, np.nan)
             if pd.notna(s) else np.nan)
            for s, c, cn in zip(semana, criativo, canal)
        ], dtype=float)

    nota = np.nan_to_num(_monta(por_semana), nan=NOTA_NEUTRA)
    nota_canal = _monta(por_semana_canal, chave_canal=True)
    nota_canal = np.where(np.isnan(nota_canal), nota, nota_canal)   # sem canal → a geral
    nota_texto = np.nan_to_num(_monta(por_semana_texto), nan=NOTA_NEUTRA)
    nota_canal_texto = _monta(por_semana_canal_texto, chave_canal=True)
    # sem canal → cai na de texto, que já tem o prior; nem aí volta pro 1,0 cego
    nota_canal_texto = np.where(np.isnan(nota_canal_texto), nota_texto, nota_canal_texto)

    out = df.copy()
    out[nome_saida] = nota
    out[f"{nome_saida}_canal"] = nota_canal
    out[f"{nome_saida}_texto"] = nota_texto
    out[f"{nome_saida}_canal_texto"] = nota_canal_texto
    for rot, v in (("canal", nota_canal), ("texto", nota_texto),
                   ("canal_texto", nota_canal_texto)):
        logger.info(f"  [nota_criativo] {nome_saida}_{rot}: cobertura "
                    f"{(v != NOTA_NEUTRA).mean()*100:.1f}% · mediana {np.median(v):.2f}")
    cobertura = float((nota != NOTA_NEUTRA).mean())
    logger.info(f"  [nota_criativo] {len(out):,} leads · cobertura {cobertura*100:.1f}% "
                f"(o resto fica em {NOTA_NEUTRA:.1f}, que é neutro)")
    logger.info(f"  [nota_criativo] nota: mediana {np.median(nota):.2f} · "
                f"p5 {np.percentile(nota, 5):.2f} · p95 {np.percentile(nota, 95):.2f}")
    if cobertura < cobertura_minima:
        raise ValueError(
            f"[nota_criativo] cobertura {cobertura*100:.1f}% abaixo do piso de "
            f"{cobertura_minima*100:.0f}%. Com quase todo mundo em nota neutra a feature é "
            f"inerte e o treino sairia igual ao sem ela. Verifique se `{col_criativo}` "
            f"casa com `captacoes.utm_content` (mesma nomenclatura de anúncio)."
        )
    return out
