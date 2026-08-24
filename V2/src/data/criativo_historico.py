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
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

TABELA = "criativo_historico"

_PREFIXO_GOOGLE = re.compile(r"^\[G\]\s*", re.IGNORECASE)
_ESPACOS = re.compile(r"\s+")


def chave_canonica(criativo) -> str:
    """A grafia única de um criativo, pra somar a evidência dele numa gaveta só.

    Três coisas, e cada uma existe por um vazamento MEDIDO em 19/08/2026:

    1. **Prefixo `[G] `**. Quem resolve o id numérico do Google na API põe esse
       carimbo no nome (`ingest_ad_insights._resolve_google`). O MESMO vídeo já
       rodou na Meta e tem passado gravado sem o carimbo, então `[G] DEV-AD0140`
       nunca achava os 960 leads de `DEV-AD0140`. Medido no LF64: 4 dos 14
       criativos vivos liam histórico ZERO tendo de 502 a 6.451 leads.
    2. **Forma Unicode**. "captação" tem ç e ã, e cada acentuada existe em duas
       grafias: um caractere só (NFC) ou letra + acento invisível (NFD). Iguais na
       tela, diferentes em byte. A tabela abria DUAS linhas pro mesmo anúncio: 806
       chaves cruas que são 769 criativos, 37 pares partidos. Pior que o caso 1
       porque a busca ACHA uma das gavetas e devolve metade da evidência sem erro
       nenhum — o peso `n/(n+2000)` cai e o teto afrouxa em silêncio.
    3. **Caixa e espaço**. Mesma família dos dois acima, custo zero.

    Aplicada só na LEITURA (`le_historico`), igual ao estrangulamento de id→nome
    que já existia: o refresh semanal segue gravando por chave crua e a tabela não
    muda de forma.
    """
    s = _PREFIXO_GOOGLE.sub("", str(criativo or "").strip())
    return _ESPACOS.sub(" ", unicodedata.normalize("NFC", s)).casefold()


def tem_carimbo_google(chave) -> bool:
    """A chave publicada é de anúncio do GOOGLE? (carrega o carimbo `[G] `)

    Mora aqui, junto de `chave_canonica`, para o padrão do carimbo existir num
    lugar só: quem PÕE é o resolvedor da ingestão, quem TIRA é a canônica acima,
    e quem PERGUNTA (a moeda do gerenciador, no push da agência) passa por esta
    função. Três cópias da mesma expressão regular divergiriam no primeiro dia em
    que o carimbo mudasse, e o consumidor que ficasse para trás falharia calado.

    O caso que a criou (19/08/2026): a conversão do teto para a moeda do
    gerenciador decidia "é da Meta" procurando um `|` na campanha (marca do
    formato `nome|id` de lá). As campanhas do Google se chamam
    `DEVLF | CAP | Dgen | Cold | ...` — 18 das 35 têm barra vertical no nome —,
    então a linha do Google passava por linha da Meta, não achava par no
    gerenciador e caía na razão AGREGADA de lá: 37 linhas publicadas a 0,77 do
    valor devido, o teto do Google 23% mais apertado do que a régua manda.
    """
    return bool(_PREFIXO_GOOGLE.match(str(chave or "").strip()))


def mapa_de_nomes(conn, client_id: str = "devclub") -> dict:
    """{ad_id: nome do anúncio} da `analytics.criativo_id_map`.

    Por que existe como FUNÇÃO: a macro de nome falha em alguns anúncios e o
    `utm_content` chega como o ID numérico cru; publicar número numa linha e nome
    na outra é falha de consistência que corrói a confiança na métrica (Ramon,
    16/08). O passo id->nome já vivia em três lugares: esta consulta LITERAL em
    `le_historico` (aqui) e em `scripts/push_scores_zanelato._mapa_de_nomes`, e
    uma terceira versão em `scripts/assertividade_teto` que monta o mesmo
    mapeamento pelos pares (ad_id, ad_name) da própria `ad_insights`, sem passar
    pela `criativo_id_map`. Três grafias da mesma regra divergem no primeiro dia
    em que ela mudar. Aqui é extração, não cópia nova: `le_historico` passou a
    CONSUMIR esta função; os dois scripts seguem com a cópia deles, intocados.

    Nome normalizado com espaço único, como as três cópias já faziam. A grafia
    canônica NÃO é aplicada aqui de propósito: quem canoniza é quem indexa
    (`le_historico`, `criativo_do_lead`), e o mapa continua servindo quem quer o
    nome como está publicado.

    Falha de leitura degrada para `{}` (mapa ausente = cada chave fica como está,
    o comportamento de antes de o mapa existir), nunca derruba o consumidor.

    Filtro por `client_id`: medido em 24/08/2026, a tabela tem 3.795 linhas e
    TODAS são devclub, então o mapa devolvido é idêntico ao de antes do filtro.
    """
    try:
        return {str(r[0]): " ".join(str(r[1]).split())
                for r in conn.run("SELECT ad_id, ad_name FROM criativo_id_map "
                                  "WHERE ad_name IS NOT NULL AND client_id = :c",
                                  c=client_id)}
    except Exception:
        return {}   # sem mapa, cada chave fica como está (comportamento antigo)


def criativo_do_lead(utm_content, mapa: dict) -> str:
    """A chave de criativo de UM lead, a partir do `utm_content` que ele trouxe.

    Duas etapas, nesta ordem:
      1. id numérico (só dígitos, 6 ou mais) vira nome pelo `mapa_de_nomes`. Sem
         achar no mapa, fica o próprio id: melhor uma gaveta com o número do que
         jogar o lead fora. Medido no LF64 (24/08/2026): 39 utm_content numéricos
         distintos de fonte google nos cadastros do Railway (40 pela
         `analytics.captacoes`, que carrega um id a mais na borda de 18/08), e
         TODOS estão na `criativo_id_map`, cobertura 100%.
      2. `chave_canonica` por cima, sempre. É o que faz o lead do Google
         (`[G] DEV-AD0140`) cair na mesma gaveta do passado dele na Meta.

    Vazio ou None devolve string vazia: lead sem criativo é lead sem criativo,
    não é o criativo de nome "None". O piso de 6 dígitos também protege o lead
    orgânico: no LF64 o `utm_content` do grupo antigo do WhatsApp é "2907", e ele
    tem que continuar sendo a chave "2907", não virar anúncio nenhum.

    NÃO decide plataforma. Quem precisa saber se é Google ou Meta pergunta a quem
    sabe o canal (a fonte do lead, o carimbo `[G] ` da chave publicada via
    `tem_carimbo_google`), porque o id numérico sozinho não diz de onde veio: o
    `utm_content` numérico existe nas duas plataformas.
    """
    cru = str(utm_content or "").strip()
    if not cru:
        return ""
    if cru.isdigit() and len(cru) >= 6:
        cru = (mapa or {}).get(cru, cru)
    return chave_canonica(cru)


class _HistoricoPorCriativo(dict):
    """Dicionário do histórico que casa por grafia canônica.

    Por que não devolver um dict cru com todas as grafias como apelido: a gente só
    conhece as grafias que ESTÃO na tabela. O criativo do lead pode chegar do ledger
    numa terceira grafia (NFD onde a tabela só tem NFC), e aí nenhum apelido salva.
    Canonizando na consulta, qualquer grafia do mesmo nome cai na mesma gaveta.

    Continua um `dict` de verdade: iterar, `len()` e as chaves cruas seguem
    funcionando pra quem já consumia (o `== {}` do teste de tabela ausente inclusive).
    """

    __slots__ = ("_por_canonica",)

    def __init__(self, gavetas: dict, por_canonica: dict):
        super().__init__(gavetas)
        self._por_canonica = por_canonica

    def get(self, chave, default=None):
        g = super().get(chave)
        if g is not None:
            return g
        return self._por_canonica.get(chave_canonica(chave), default)

    def __getitem__(self, chave):
        try:
            return super().__getitem__(chave)
        except KeyError:
            return self._por_canonica[chave_canonica(chave)]

    def __contains__(self, chave):
        return (super().__contains__(chave)
                or chave_canonica(chave) in self._por_canonica)

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


def _data(v) -> date:
    """Aceita `date` ou texto 'YYYY-MM-DD' e devolve `date`. O parâmetro tem que
    chegar no banco como DATA de verdade: pg8000 manda string como texto, e
    `date < text` não é comparação que o Postgres aceite (erro de operador)."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def _t8(t) -> Optional[str]:
    d = "".join(c for c in str(t or "") if c.isdigit())
    return d[-8:] if len(d) >= 8 else None


def calcula_historico(conn, client_id: str = "devclub",
                      corte=None) -> pd.DataFrame:
    """Acumulado por criativo sobre TODOS os lançamentos fechados.

    A compra conta da captação até o `vendas_end` do lançamento do lead (a regra
    do calendário, a mesma da referência e da trava). Lançamento aberto fica fora
    inteiro: ele ainda não é história.

    `corte=None` (default) = relógio de HOJE, byte a byte o comportamento de
    sempre: entra o lançamento com `vendas_end < CURRENT_DATE - 2`. É o que o
    refresh semanal quer, porque ele grava a memória do agora.

    `corte=<date>` = relógio congelado naquela data: entra só o lançamento com
    `vendas_end < corte`. Existe para o BACKTEST de um lançamento poder
    reconstruir o histórico point-in-time, sem enxergar a si mesmo nem os
    posteriores. Medido em 24/08/2026: o DEV21 fechou vendas em 16/08 e por isso
    já conta como fechado desde 22/08 (27 lançamentos); com `corte=2026-08-07`
    (captação do LF64) são 26, e o DEV21 sai. Sem o corte, o teto do LF64 sairia
    calculado com a memória do lançamento anterior dentro dele.
    """
    # `vendas_end < hoje - 2`: a folga de 2 dias cobre o atraso de ingestão da
    # analytics.sales (~1 dia). Sem ela, lançamento que fecha no domingo entraria na
    # segunda com as vendas do fim de semana ainda fora do banco e ficaria uma semana
    # subcontado. A entrada é POR LANÇAMENTO FECHADO, nunca por idade do lead — um
    # ciclo longo (LF45, 33d) entra inteiro e maduro de uma vez, ou não entra.
    # O filtro de maturidade é UM dos dois, nunca os dois: com corte o relógio é
    # o da data pedida (o "hoje" daquele lançamento), sem corte é o de agora.
    if corte is None:
        cal = {r[0]: r[1:] for r in conn.run(
            "SELECT lf_name, cap_start, cap_end, vendas_start, vendas_end "
            "FROM launch_calendar WHERE client_id = :c "
            "  AND vendas_end IS NOT NULL AND vendas_end < CURRENT_DATE - 2",
            c=client_id)}
    else:
        cal = {r[0]: r[1:] for r in conn.run(
            "SELECT lf_name, cap_start, cap_end, vendas_start, vendas_end "
            "FROM launch_calendar WHERE client_id = :c "
            "  AND vendas_end IS NOT NULL AND vendas_end < :corte",
            c=client_id, corte=_data(corte))}
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
    modelo puro, que é o comportamento sem histórico).

    UNIFICAÇÃO POR NOME (18/08, regra "cópia é o mesmo anúncio"): a chave
    gravada é o texto da UTM, e no Google o mesmo vídeo vive como VÁRIOS ids
    numéricos (AD0139 = 9 ids) — o histórico picado zerava o peso do lift
    justamente no canal onde o modelo não ordena (+0,05) e o histórico é o
    único sinal (+0,35). Aqui, na LEITURA: id vira nome via criativo_id_map,
    gavetas do mesmo nome SOMAM, e o id fica como APELIDO apontando pra MESMA
    gaveta fundida — quem consulta por id ou por nome cai no mesmo lugar.
    A tabela não muda (estrangulamento na leitura; o refresh semanal segue
    gravando por chave crua).

    UNIFICAÇÃO POR GRAFIA (19/08): a fusão acima era por nome CRU, e por isso ainda
    partia o mesmo anúncio quando a grafia mudava — carimbo `[G] ` do resolvedor do
    Google e forma Unicode do acento. Agora a soma é por `chave_canonica`, e a
    consulta também canoniza (ver `_HistoricoPorCriativo`). Medido antes de mudar:
    806 chaves cruas viram 769 criativos, e no LF64 quatro dos catorze criativos
    vivos liam histórico ZERO tendo de 502 a 6.451 leads, o que inflava o teto deles
    em até 81%."""
    try:
        rows = conn.run(
            f"SELECT criativo, leads, compradores, esperados, prior_conversao, "
            f"prior_fonte FROM {TABELA} WHERE client_id = :c", c=client_id)
    except Exception as e:  # tabela ainda não criada neste ambiente
        logger.warning("[criativo_historico] leitura falhou (%s) — degradando pra "
                       "sem histórico", e)
        return {}
    mapa = mapa_de_nomes(conn, client_id=client_id)

    por_canonica: dict = {}
    grafias: list = []      # (grafia vista na tabela, gaveta canônica dela)
    for r in rows:
        cru = str(r[0]).strip()
        nome = mapa.get(cru, cru) if (cru.isdigit() and len(cru) >= 10) else cru
        k = chave_canonica(nome)
        grafias.append((cru, k))
        if nome != cru:
            grafias.append((nome, k))
        g = por_canonica.get(k)
        if g is None:
            por_canonica[k] = {"leads": int(r[1]), "compradores": int(r[2]),
                               "esperados": float(r[3]),
                               "prior_conversao": (float(r[4]) if r[4] is not None
                                                   else None),
                               "prior_fonte": r[5]}
        else:   # gaveta do mesmo anúncio: SOMA a evidência; prior existente fica
            g["leads"] += int(r[1])
            g["compradores"] += int(r[2])
            g["esperados"] += float(r[3])
            if g["prior_conversao"] is None and r[4] is not None:
                g["prior_conversao"] = float(r[4])
                g["prior_fonte"] = r[5]
    # As grafias cruas ficam como APELIDO apontando pro MESMO objeto da gaveta
    # canônica: quem consulta pelo texto exato da tabela continua achando na hora,
    # sem pagar a canonização. Quem chega com uma grafia que a tabela não tem cai
    # no `get` canonizado do `_HistoricoPorCriativo`.
    gavetas = {grafia: por_canonica[k] for grafia, k in grafias}
    if len(gavetas) != len(por_canonica):
        logger.info("[criativo_historico] %d grafias fundidas em %d criativos",
                    len(gavetas), len(por_canonica))
    return _HistoricoPorCriativo(gavetas, por_canonica)
