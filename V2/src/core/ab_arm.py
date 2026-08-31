"""
core/ab_arm.py — Resolvedor único do braço do A/B (Champion / Challenger / Controle).

Fonte de verdade do braço que scoreou/otimizou cada lead, em ordem de prioridade:
  1. `registros_ml.variant` (gravado por produção no scoring) — quando existe (>= ~17/05/2026)
  2. reconstrução pela TAG da campanha, com o papel vigente na DATA de captura
  3. fail-loud: janela ambígua + sem `variant` -> INDETERMINADO (nunca cai em Controle calado)

Função PURA: recebe os sinais já lidos (variant, utm_campaign, nome_campanha,
data_captura) e devolve o braço. NÃO consulta banco — a leitura do `variant` é
responsabilidade da camada de dados (injeção de dependência).

DE ONDE VEM A VERDADE (fonte única, decisão de 30/07/2026)
----------------------------------------------------------
Modelos ATIVOS: lidos de `configs/active_models/{cliente}.yaml`, bloco `ab_test.variants`
(campos `role`, `role_history`, `campaign_tag`). Promover um modelo = editar UM lugar;
todos os consumidores herdam. Antes desta mudança este módulo ESPELHAVA o YAML à mão e
ficou desatualizado: dizia que o abr28 era Challenger cinco dias depois de ele ter sido
promovido a Champion, e não conhecia o challenger jul_24 (devolvia INDETERMINADO).

Modelos APOSENTADOS: tabela congelada aqui no código (`_RETIRED_*`). São fatos imutáveis
sobre modelos que saíram do ar (o jan30, o teste ML_MAR de março). Não vão para o YAML
porque o YAML é o config que o scoring carrega em produção — histórico morto não precisa
viajar dentro da imagem. Como o fato nunca muda, não há risco de divergir.

PAPEL TEM DATA (por que `role_history` existe)
----------------------------------------------
O abr28 era Challenger até 24/07/2026 e virou Champion em 25/07. Um relatório de junho
tem que continuar chamando aquelas campanhas de Challenger. Resolver sempre pelo papel de
HOJE reescreveria o passado a cada promoção — silenciosamente. Por isso o papel é datado:
`resolve_arm(..., captured_at=<data do lead>)`. Sem data, vale o papel de hoje.

Convenções e histórico de marcadores: V2/docs/DEFINICAO_ESCOPO_LFS.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# --- Rótulos canônicos (contrato estável — não renomear, há consumidores) ---
CHAMPION = "Champion"
CHALLENGER = "Challenger"
CONTROLE = "Controle"
EXTERNO = "Externo"
INDETERMINADO = "Indeterminado"

# `role` do YAML -> rótulo canônico deste módulo.
_ROLE_TO_LABEL: Dict[str, str] = {"champion": CHAMPION, "challenger": CHALLENGER}

_DEFAULT_ACTIVE_MODELS = (
    Path(__file__).resolve().parents[2] / "configs" / "active_models" / "devclub.yaml"
)

# Marcador que identifica campanha de CAPTAÇÃO Meta, casado por SUBSTRING (não por
# prefixo). Duas decisões aqui, cada uma com dinheiro medido atrás:
#
#   1. NÃO inclui o público. Era "devlf | cap | frio", e a campanha
#      "DEVLF | CAP | QUENTE | ... | LEADHQLB" (R$ 2.271 em 29/07/2026) caía em EXTERNO,
#      desaparecendo dos relatórios. Público (FRIO/QUENTE/MORNO) é escolha de mídia,
#      não muda o fato de ser captação.
#   2. SUBSTRING, não prefixo. Existe campanha real com caractere antes do nome:
#      "*DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO | LEAD | PG2" (R$ 7.383 e
#      1.813 leads em 01-07/05/2026). Com `startswith` ela vira EXTERNO e o gasto sai
#      do funil calado. `validation.is_captacao_campaign` sempre usou substring; a
#      divergência de operador entre os dois módulos era um bug latente.
_CAP_MARKER_DEFAULT = "devlf | cap |"

# Em 09/08/2026 o gestor virou a nomenclatura pro formato de COLCHETES
# ("[17][DEVLF][CAP][LEADS][SITE][FRIO]...[JUL_24_TOP50]|<id>") e o funil por
# variante ZEROU por 7 dias sem ninguém ver: o marcador acima é substring com
# pipes, e "[DEVLF][CAP]" não o contém — tudo virava EXTERNO calado, com
# R$ 10,7k/dia de gasto classificado como campanha externa. A normalização
# abaixo traduz colchetes pro formato canônico de pipes ANTES de qualquer
# casamento, então os dois formatos (e o próximo que inventarem com
# separadores) passam pelo MESMO teste. Decisão de desenho (Ramon, 16/08):
# a ETIQUETA do modelo é o que decide; o formato do nome não pode cegar o
# relatório de novo.
_SEPARADORES_RE = re.compile(r"[\[\]]+")
_PIPES_RE = re.compile(r"\s*\|[\s|]*")


def _normaliza_nome(t: str) -> str:
    """Formato canônico pra casamento: colchetes viram pipes, pipes colapsam.

    '[17][DEVLF][CAP][LEADS]' -> '| 17 | devlf | cap | leads |'
    'DEVLF | CAP | FRIO'      -> 'devlf | cap | frio' (inalterado na essência)
    """
    t = _SEPARADORES_RE.sub(" | ", t.lower())
    t = _PIPES_RE.sub(" | ", t)
    return t.strip()


def _tokens(t_norm: str) -> list:
    """Tokens do nome normalizado (pedaços entre pipes, sem vazios)."""
    return [p.strip() for p in t_norm.split("|") if p.strip()]


# ─────────────────── temperatura (público) da campanha ────────────────────────
# Rótulo de quem não declara público no nome: campanhas do Google, orgânico e
# Meta sem QUENTE/FRIO. É o mesmo balde "sem rótulo" da análise do DEV21.
TEMPERATURA_SEM_PUBLICO = "sem público no nome"

_TEMPERATURA_TOKENS = (("quente", ("quente",)),
                       ("morno", ("morno", "morna")),
                       ("frio", ("frio", "fria")))


def temperatura_da_campanha(nome) -> str:
    """Público da campanha pelo NOME: 'quente' | 'morno' | 'frio' | sem rótulo.

    Vive aqui (e não no relatório) porque é vocabulário de nome de campanha,
    como o marcador de captação: passa pela MESMA normalização de colchetes →
    pipes, então '[DEVLF][CAP][QUENTE]' e 'DEVLF | CAP | QUENTE' caem no mesmo
    balde. Token exato entre pipes, não substring — 'requente' não vira quente.

    Diferente da etiqueta de modelo, o público NÃO some quando há etiqueta:
    'QUENTE ... LEADHQLB' é modelo abr_28 E público quente ao mesmo tempo
    (público é escolha de mídia; modelo é quem otimiza — decisão de 16/08).
    Virou dimensão fixa do relatório por lançamento em 31/08/2026.
    """
    toks = set(_tokens(_normaliza_nome(str(nome or ""))))
    for rotulo, aliases in _TEMPERATURA_TOKENS:
        if toks.intersection(aliases):
            return rotulo
    return TEMPERATURA_SEM_PUBLICO


# Campanhas que NÃO entram no balde 'Lead' padrão mesmo sendo captação sem
# etiqueta de modelo (decisão do Ramon, 16/08/2026): público quente e campanha
# interna têm economia própria e poluiriam o CPL da captação fria padrão.
# Etiqueta de modelo VENCE (campanha quente COM etiqueta segue pro modelo —
# regra 2a roda antes): público é escolha de mídia, o modelo é quem otimiza.
_FORA_DO_LEAD_TOKENS = ("quente", "interno", "interna")

# ─────────────────── vocabulário dos agregadores (contrato de saída) ───────────────────
# Os relatórios chamam de 'Lead' o que aqui é CONTROLE, e não conhecem INDETERMINADO.
# Isto NÃO é cosmético: `daily_check_aggregations` cria o dict com exatamente 3 chaves e
# faz `if bucket in agg` sem `else`. Rótulo fora do vocabulário não levanta erro, ele
# ZERA o balde em silêncio — o funil sai no Slack com aparência normal e sem as linhas
# por variante. Todo invólucro traduz por aqui antes de devolver.
BUCKET_LEAD = "Lead"

_ARM_TO_BUCKET: Dict[str, str] = {
    CHAMPION: CHAMPION,
    CHALLENGER: CHALLENGER,
    CONTROLE: BUCKET_LEAD,
}
# INDETERMINADO NÃO entra no mapa de propósito: "não sei" não pode virar uma linha do
# relatório. Quem chama trata como fora do escopo (o `classify_variant` devolve EXTERNO),
# que é o mesmo destino que essas campanhas já tinham. Mapear pra 'Lead' seria trocar uma
# afirmação errada (Champion) por outra (Controle).

# ─────────────────────── modelos APOSENTADOS (fatos congelados) ───────────────────────
# `registros_ml.variant` de modelos que saíram do ar. Não estão no YAML de ativos.
_RETIRED_VARIANT_ROLES: Dict[str, str] = {
    "champion_jan30": CHAMPION,   # champion até a promoção do abr28
}
# Marcadores de nome de modelos aposentados (substring, lower). Só valem quando a TAG do
# YAML não casou — modelo ativo sempre ganha.
_RETIRED_CHAMPION_MARKERS: Tuple[str, ...] = ("leadqualified", "machine learning", "| ml |")
# "pixel novo api" é mais específico que "pixel novo" e precisa ser testado ANTES do
# marcador de Champion — por isso mora aqui (o passo 2b roda antes do 2d).
#
# COMO SE SABE (medição de 30/07/2026, não suposição): os backups do Railway guardam o
# decil que a PRODUÇÃO gravou (`public.lead_legado`), e `public.scores_historicos` tem os
# dois modelos recalculados sobre os mesmos leads. O modelo cujo decil bate com o de
# produção é o que scoreou. Entre os leads em que os dois modelos DISCORDAM:
#
#   referência Champion (MACHINE LEARNING puro, n=24.764):  58,6% champion /  ~0% challenger
#   referência Challenger (ML_MAR, n=4.137):                15,4% champion /  4,0% challenger
#   PIXEL NOVO API (n=1.664):                               14,7% champion / 41,6% challenger
#   PIXEL NOVO sem API (n=16.985):                          65,0% champion / -0,2% challenger
#   NOVO PIXEL (n=15.430):                                  54,6% champion / -1,0% challenger
#
# Ou seja: as três grafias NÃO são a mesma campanha. "API" é o discriminador — só ela é
# Challenger. As outras duas seguem para o marcador de Champion via "machine learning",
# que é o comportamento correto e já era o de antes.
_RETIRED_CHALLENGER_MARKERS: Tuple[str, ...] = ("ml_mar", "utm_pixel", "pixel novo api")

# Marcadores de Controle: captação SEM evento ML (Lead puro, score, faixa).
# (Os marcadores explícitos de Controle — "escala score", "| lead |" etc. —
# saíram em 16/08/2026: captação sem etiqueta de modelo agora cai em Controle
# por DEFAULT, então listar sinônimos de "sem etiqueta" virou redundância.)


@dataclass(frozen=True)
class _AmbiguousEra:
    """Janela em que um marcador apareceu nos DOIS arms — o nome não desambigua."""
    start: date                       # inclusivo
    end: date                         # exclusivo
    markers: Tuple[str, ...]


# VAZIO hoje. A única época ambígua que existia aqui ("pixel novo api", 29/04–27/05/2026)
# foi RESOLVIDA por evidência em 30/07/2026 — ver `_RETIRED_CHALLENGER_MARKERS`. O
# mecanismo fica de pé porque a próxima janela ambígua vai aparecer, e o contrato dele
# (marcador presente + época + sem `variant` -> INDETERMINADO) é o certo pra ela.
_AMBIGUOUS_ERAS: Tuple[_AmbiguousEra, ...] = ()


# ───────────────────────────── config dos modelos ATIVOS ─────────────────────────────
@dataclass(frozen=True)
class ArmConfig:
    """Papéis dos modelos ativos, lidos do YAML. Imutável; construir 1x e injetar."""
    variant_roles: Tuple[Tuple[str, Tuple[Tuple[date, str], ...]], ...]
    tag_variants: Tuple[Tuple[str, str], ...]   # (TAG_UPPER, variant_key), em precedência
    display_names: Tuple[Tuple[str, str], ...]  # (variant_key, rótulo humano)
    cap_marker: str = _CAP_MARKER_DEFAULT

    def role_at(self, variant_key: str, as_of: Optional[date] = None) -> Optional[str]:
        """Papel ('champion'/'challenger') do variant NA DATA. None se não conhecido.

        Sem `as_of`, vale o papel mais recente (o de hoje). Percorre o histórico e pega
        a última vigência cujo início é <= a data.
        """
        hist = dict(self.variant_roles).get(variant_key)
        if not hist:
            return None
        if as_of is None:
            return hist[-1][1]
        atual = None
        for inicio, role in hist:          # já vem ordenado por data
            if inicio <= as_of:
                atual = role
            else:
                break
        # Data anterior à primeira vigência: o modelo ainda não existia nesse papel.
        return atual

    def variant_for_role(self, role: str, as_of: Optional[date] = None) -> Optional[str]:
        """Qual variant ocupava o papel na data. Resolve por PAPEL, não por nome da chave.

        Existe porque a chave do variant no YAML é histórica e engana: as duas variantes
        se chamam `challenger_abr28` e `challenger_jul_24`, então procurar a substring
        'champion' no nome da chave não acha ninguém e cai no primeiro da lista — foi
        assim que champion e challenger viraram o MESMO modelo em relatório.
        """
        alvo = str(role).strip().lower()
        for key, _hist in self.variant_roles:
            if self.role_at(key, as_of) == alvo:
                return key
        return None

    def display_name(self, variant_key: str) -> Optional[str]:
        return dict(self.display_names).get(variant_key)


def _parse_role_history(v: dict) -> Tuple[Tuple[date, str], ...]:
    """`role_history` do YAML -> ((data_inicio, role), ...) ordenado. Sem histórico,
    deriva do `role` atual com vigência aberta (data mínima) — compatível com config
    antigo que só tem `role`."""
    hist = []
    for item in (v.get("role_history") or []):
        d = _coerce_date((item or {}).get("from"))
        r = str((item or {}).get("role", "")).strip().lower()
        if d and r in _ROLE_TO_LABEL:
            hist.append((d, r))
    if hist:
        return tuple(sorted(hist, key=lambda x: x[0]))
    role = str(v.get("role", "")).strip().lower()
    if role in _ROLE_TO_LABEL:
        return ((date.min, role),)
    return ()


def load_arm_config(path: Optional[Path] = None) -> ArmConfig:
    """Lê o YAML de modelos ativos e devolve os papéis datados. Fail-safe: YAML ausente
    ou ilegível devolve config vazio (o resolvedor cai nos marcadores aposentados)."""
    import yaml

    p = Path(path or _DEFAULT_ACTIVE_MODELS)
    try:
        with open(p) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001 — config ausente não derruba scoring/relatório
        return ArmConfig(variant_roles=(), tag_variants=(), display_names=())

    variants = ((cfg.get("ab_test") or {}).get("variants") or {})
    roles, tags, names = [], [], []
    for key, v in variants.items():
        v = v or {}
        hist = _parse_role_history(v)
        if hist:
            roles.append((key, hist))
        # Etiquetas: campaign_tag + a lista utm_pattern.utm_campaign — a MESMA
        # que o roteamento do scoring usa (ABTestConfig.match_variant). Antes
        # este leitor só via o campaign_tag ('HQLB', 'JUL24'), então as
        # etiquetas novas 'ABR_28_TOP30' e 'JUL_24_TOP30/50' eram invisíveis
        # pro relatório enquanto o scoring as roteava normalmente: os dois
        # lados liam CAMPOS diferentes do mesmo YAML e divergiram em 09/08.
        # Fonte única de agora em diante: o que roteia é o que classifica.
        etiquetas = [str(v.get("campaign_tag", "")).strip().upper()]
        utm_pat = (v.get("utm_pattern") or {}).get("utm_campaign") or []
        if isinstance(utm_pat, str):
            # O campo aceita string OU lista (o match_variant do scoring trata
            # os dois). Iterar uma string daria etiquetas de 1 letra que casam
            # com qualquer nome — envenenaria o mapa inteiro.
            utm_pat = [utm_pat]
        etiquetas += [str(p).strip().upper() for p in utm_pat]
        if hist:
            for tag in etiquetas:
                if tag and (tag, key) not in tags:
                    tags.append((tag, key))
        if v.get("display_name"):
            names.append((key, str(v["display_name"])))

    # Precedência das tags: challenger antes de champion (desempate histórico do
    # projeto — campanha com as duas tags conta como challenger).
    hist_by_key = dict(roles)

    def _prio(item):
        _tag, key = item
        h = hist_by_key.get(key) or ()
        return 0 if (h and h[-1][1] == "challenger") else 1

    tags.sort(key=_prio)
    return ArmConfig(variant_roles=tuple(roles), tag_variants=tuple(tags),
                     display_names=tuple(names))


_CONFIG_CACHE: Dict[str, ArmConfig] = {}


def _default_config() -> ArmConfig:
    """Config do cliente default, memoizado (o YAML não muda em runtime)."""
    k = str(_DEFAULT_ACTIVE_MODELS)
    if k not in _CONFIG_CACHE:
        _CONFIG_CACHE[k] = load_arm_config()
    return _CONFIG_CACHE[k]


# ─────────────────────────────── helpers ───────────────────────────────
def _clean_str(v) -> Optional[str]:
    """Normaliza p/ str não-vazia ou None. Trata NaN (float) e None como ausente —
    crítico: colunas pandas trazem NaN (float, truthy) p/ campos faltantes."""
    if v is None or isinstance(v, float):   # float cobre NaN (np.float64 inclusive)
        return None
    s = str(v).strip()
    return s or None


def _coerce_date(value) -> Optional[date]:
    """Normaliza date/datetime/str(YYYY-MM-DD...) -> date. None se não der."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:19].replace("Z", "")).date()
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _ambiguous_marker_hit(t: str, d: Optional[date]) -> bool:
    """True se o texto bate um marcador ambíguo e a data NÃO descarta a janela dele.

    Sem data, bater o marcador já conta como ambíguo: não se pode afirmar que estamos FORA
    da janela, e o custo de errar pra menos (INDETERMINADO, que a guarda
    `seed_campaign_labels_faltantes --check` acusa) é menor que o de afirmar um braço
    errado calado. `_AMBIGUOUS_ERAS` está vazia hoje, então isto só volta a valer quando
    uma nova época ambígua for declarada.
    """
    for era in _AMBIGUOUS_ERAS:
        if not any(m in t for m in era.markers):
            continue
        if d is None or era.start <= d < era.end:
            return True
    return False


def _has_lq(t: str) -> bool:
    """`LQ`/`LQC` isolado (LeadQualified) = Champion aposentado, fora de ML_MAR."""
    if "ml_mar" in t:
        return False  # ML_MAR|LQC é Challenger, tratado pelos marcadores aposentados
    return bool(re.search(r"\b(lq|lqc)\b", t))


def is_captacao(text: Optional[str], config: Optional[ArmConfig] = None) -> bool:
    """True se o nome é de campanha de CAPTAÇÃO Meta, independente do público.

    Exposto porque o mesmo teste está duplicado em validation.campaign_classifier
    (`is_captacao_campaign`), que exige o público 'FRIO' cravado e por isso perde as
    campanhas QUENTE. Ver `_CAP_MARKER_DEFAULT` para por que é substring e não prefixo.
    """
    t = _clean_str(text)
    if not t:
        return False
    cfg = config or _default_config()
    # Normaliza ANTES do teste: '[DEVLF][CAP]' e 'DEVLF | CAP |' são a mesma
    # campanha em formatos diferentes; o marcador é um só.
    return cfg.cap_marker in _normaliza_nome(t) + " | "


def arm_to_bucket(arm: str, *, contexto: str = "") -> Optional[str]:
    """Traduz o rótulo do miolo pro vocabulário de 3 baldes dos agregadores.

    CONTROLE -> 'Lead'. INDETERMINADO -> None (não há balde honesto): quem chama decide
    excluir. Devolver 'Lead' seria trocar uma afirmação errada por outra, e devolver um
    quarto rótulo zeraria o balde em silêncio nos consumidores (ver BUCKET_LEAD).
    O caso é LOGADO: indeterminado é o sinal de que apareceu campanha que a régua não
    conhece, e perder esse sinal foi o que deixou R$ 3.250 de gasto sem rótulo por dias.
    """
    if arm == INDETERMINADO:
        warn_once("arm indeterminado, campanha excluida do recorte por variante", contexto)
        return None
    # EXTERNO e qualquer rótulo desconhecido NÃO caem no 'Lead' por default:
    # 'Lead padrão' = captação fria da Meta, e o default antigo faria um
    # chamador novo que passasse EXTERNO direto (google/orgânico) contar como
    # Meta em silêncio. O único chamador de produção (classify_variant) trata
    # EXTERNO antes de chamar — para ele nada muda.
    if arm not in _ARM_TO_BUCKET:
        warn_once("arm fora do vocabulario, excluido do recorte por variante",
                  f"{arm}:{contexto}")
        return None
    return _ARM_TO_BUCKET[arm]


_WARNED: set = set()


def warn_once(msg: str, contexto: str = "") -> None:
    """Loga uma vez por (mensagem, contexto). Nome de campanha é conjunto pequeno e
    estável, então o cache não cresce sem limite; sem o `once` isto viraria uma linha
    de log por lead."""
    import logging

    k = (msg, contexto)
    if k in _WARNED:
        return
    _WARNED.add(k)
    logging.getLogger(__name__).warning("[ab_arm] %s | contexto=%r", msg, contexto)


def first_match(text: Optional[str], pares) -> Optional[str]:
    """Primeiro valor cuja chave aparece como substring em `text` (case-insensitive).

    Miolo do casamento de TAG, compartilhado por `resolve_arm`, `resolve_bucket_by_tag` e
    `monitoring.bucket_from_utm`. Existia copiado nos três — a precedência (challenger
    antes de champion) mora na ORDEM da lista, então três loops iguais é convite pra três
    precedências diferentes.
    """
    t = _clean_str(text)
    if not t:
        return None
    t = t.upper()
    for chave, valor in pares:
        if str(chave).upper() in t:
            return valor
    return None


def bucket_map_for(*, as_of: Optional[date] = None,
                   config: Optional[ArmConfig] = None) -> Dict:
    """Mapa tag->balde no formato que os consumidores já esperam, resolvido NA DATA.

    Formato: {'tags': [(TAG_UPPER, balde), ...] em precedência, 'display': {balde: rótulo},
    'fallback': 'Lead'}. Construtor ÚNICO: `ABTestConfig.campaign_bucket_map` e
    `ModelRegistry.bucket_map` eram duas implementações independentes do mesmo mapa, o que
    é a definição de duas fontes de verdade para o mesmo conceito.
    """
    # Ressalva ao usar `as_of` no passado: o `display_name` do YAML embute o PAPEL de hoje
    # ("Champion (abr_28)"), então o rótulo do balde de um mapa histórico sai trocado
    # (balde Challenger rotulado "Champion (abr_28)"). Nenhum consumidor passa `as_of`
    # ainda; quem for wirar precisa antes separar nome do modelo de papel no display_name.
    cfg = config or _default_config()
    tags, display = [], {}
    for tag, key in cfg.tag_variants:
        role = cfg.role_at(key, as_of)
        if not role:
            continue                       # variante ainda não vigente nessa data
        balde = _ROLE_TO_LABEL[role]
        tags.append((tag, balde))
        nome = cfg.display_name(key)
        if nome:
            display[balde] = nome
    return {"tags": tags, "display": display, "fallback": BUCKET_LEAD}


def resolve_bucket_by_tag(text: Optional[str], *, captured_at=None,
                          config: Optional[ArmConfig] = None) -> str:
    """Balde do A/B pela TAG apenas: 'Lead' | 'Champion' | 'Challenger'.

    ⚠️ PRÉ-CONDIÇÃO NÃO NEGOCIÁVEL: o chamador JÁ filtrou o tráfego para
    SÓ META antes de chamar. O default aqui é 'Lead', e 'Lead padrão' =
    captação fria da Meta — um lead de google/orgânico que chegue aqui vira
    'Lead' em silêncio. (Auditoria de 16/08/2026: esta função NÃO tem nenhum
    chamador de produção hoje — os painéis usam `monitoring.bucket_from_utm`,
    cujos chamadores filtram canal na fonte. Se você for o primeiro consumidor
    novo: filtre `utm_source` pela allowlist Meta ANTES, ou use o
    `resolve_arm` completo, cuja porta de captação faz isso por você.)

    Porta SEPARADA do `resolve_arm`, de propósito: passar por `is_captacao`
    aqui jogaria em 'Lead' toda campanha Meta cujo nome fuja do padrão, ou
    seja, perderia campanha real e mexeria em número publicado.
    """
    cfg = config or _default_config()
    mapa = bucket_map_for(as_of=_coerce_date(captured_at), config=cfg)
    return first_match(text, mapa["tags"]) or BUCKET_LEAD


# ─────────────────────────────── resolvedor ───────────────────────────────
def resolve_arm(
    *,
    variant: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    campaign_name: Optional[str] = None,
    captured_at=None,
    config: Optional[ArmConfig] = None,
) -> str:
    """
    Resolve o braço do A/B de um lead. Argumentos keyword-only (evita troca posicional).

    Args:
        variant: valor de `registros_ml.variant` (ex.: 'challenger_abr28',
                 'challenger_jul_24') ou None. **Verdade de produção quando presente.**
        utm_campaign: utm_campaign do lead (ledger/banco).
        campaign_name: nome da campanha (relatório Meta). Usado se utm ausente.
        captured_at: data de captura do lead (date/datetime/str). Define QUAL PAPEL o
                 modelo tinha naquele momento. Sem ela, vale o papel de hoje.
        config: papéis já carregados (injeção). Sem isso, lê o YAML do cliente default.

    Returns:
        CHAMPION | CHALLENGER | CONTROLE | EXTERNO | INDETERMINADO
    """
    cfg = config or _default_config()
    d = _coerce_date(captured_at)

    # 1. Verdade de produção: variant do ledger (NaN/None/'' = ausente)
    v = _clean_str(variant)
    if v:
        role = cfg.role_at(v, d)
        if role:
            return _ROLE_TO_LABEL[role]
        # variant de modelo aposentado
        for key, label in _RETIRED_VARIANT_ROLES.items():
            if key in v.lower():
                return label
        # variant presente mas desconhecido -> fail-loud
        return INDETERMINADO

    # 2. Reconstrução por nome/utm + época
    text = _clean_str(utm_campaign) or _clean_str(campaign_name)
    if not text:
        return EXTERNO
    t = text.lower()
    if not is_captacao(t, cfg):
        return EXTERNO  # Google/orgânico/sem campanha/outro lançamento

    # 2a. TAG de modelo ATIVO (fonte única: YAML) — com o papel vigente na data.
    # Mesmo casamento que `resolve_bucket_by_tag` usa (miolo em `first_match`).
    balde = first_match(t, bucket_map_for(as_of=d, config=cfg)["tags"])
    if balde:
        return balde

    # 2b. Marcador de Challenger aposentado (ML_MAR de mar/2026, tag transitória)
    if any(m in t for m in _RETIRED_CHALLENGER_MARKERS):
        return CHALLENGER

    # 2c. Janela ambígua (PIXEL NOVO API): marcador presente, sem `variant` -> fail-loud
    if _ambiguous_marker_hit(t, d):
        return INDETERMINADO

    # 2d. Marcador de Champion aposentado (jan30: LEADQUALIFIED / MACHINE LEARNING / LQ)
    if any(m in t for m in _RETIRED_CHAMPION_MARKERS) or _has_lq(t):
        return CHAMPION

    # 2e. Público quente / campanha interna SEM etiqueta de modelo -> fora do
    # recorte por variante (não é a captação fria padrão; a economia é outra).
    # Etiqueta VENCE: quente com etiqueta já saiu na regra 2a.
    toks = _tokens(_normaliza_nome(t))
    if any(m in toks for m in _FORA_DO_LEAD_TOKENS):
        return EXTERNO

    # 2f. Captação sem etiqueta de modelo -> Controle ('Lead' padrão).
    # Era fail-loud (INDETERMINADO), e o resultado prático foi o oposto do
    # pretendido: quando a nomenclatura mudou em 09/08, TODA campanha nova sem
    # etiqueta sumiu do funil em silêncio. Decisão do Ramon (16/08): campanha
    # de captação sem etiqueta passa ILESA pro balde padrão, seja qual for o
    # formato do nome — só quem tem etiqueta é roteado pra um modelo.
    return CONTROLE
