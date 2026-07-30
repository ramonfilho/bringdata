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
    INDETERMINADO: BUCKET_LEAD,   # colapsa, mas loga (ver `arm_to_bucket`)
}

# ─────────────────────── modelos APOSENTADOS (fatos congelados) ───────────────────────
# `registros_ml.variant` de modelos que saíram do ar. Não estão no YAML de ativos.
_RETIRED_VARIANT_ROLES: Dict[str, str] = {
    "champion_jan30": CHAMPION,   # champion até a promoção do abr28
}
# Marcadores de nome de modelos aposentados (substring, lower). Só valem quando a TAG do
# YAML não casou — modelo ativo sempre ganha.
_RETIRED_CHAMPION_MARKERS: Tuple[str, ...] = ("leadqualified", "machine learning", "| ml |")
_RETIRED_CHALLENGER_MARKERS: Tuple[str, ...] = ("ml_mar", "utm_pixel")

# Marcadores de Controle: captação SEM evento ML (Lead puro, score, faixa).
_CONTROLE_MARKERS: Tuple[str, ...] = ("escala score", "aberto adv", "faixa ", "score")


@dataclass(frozen=True)
class _AmbiguousEra:
    """Janela em que um marcador apareceu nos DOIS arms — o nome não desambigua."""
    start: date                       # inclusivo
    end: date                         # exclusivo
    markers: Tuple[str, ...]


# `PIXEL NOVO API` foi a chave de routing do Challenger de 29/04–27/05, mas o mesmo
# nome aparece em campanha Champion — então sozinho não classifica. Exige `variant`.
_AMBIGUOUS_ERAS: Tuple[_AmbiguousEra, ...] = (
    _AmbiguousEra(date(2026, 4, 29), date(2026, 5, 27), ("pixel novo api",)),
)


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
        tag = str(v.get("campaign_tag", "")).strip().upper()
        if tag and hist:
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
    """True se o texto bate um marcador ambíguo dentro da janela dele."""
    if d is None:
        return False
    for era in _AMBIGUOUS_ERAS:
        if era.start <= d < era.end and any(m in t for m in era.markers):
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
    return cfg.cap_marker in t.lower()


def arm_to_bucket(arm: str, *, contexto: str = "") -> str:
    """Traduz o rótulo do miolo pro vocabulário de 3 baldes dos agregadores.

    CONTROLE -> 'Lead'. INDETERMINADO -> 'Lead' também, porque devolver um quarto rótulo
    zeraria o balde em silêncio nos consumidores (ver BUCKET_LEAD). Mas o colapso é
    LOGADO: indeterminado é o sinal de que apareceu campanha que a régua não conhece, e
    perder esse sinal foi exatamente o que deixou R$ 3.250 de gasto sem rótulo por dias.
    """
    if arm == INDETERMINADO:
        warn_once(f"arm indeterminado colapsado em '{BUCKET_LEAD}'", contexto)
    return _ARM_TO_BUCKET.get(arm, BUCKET_LEAD)


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

    Porta SEPARADA do `resolve_arm`, de propósito. Os painéis de decil e o drift por A/B
    atribuem balde a QUALQUER campanha Meta (o filtro de canal já aconteceu antes, na
    fonte), sem exigir nome de captação. Passar por `is_captacao` aqui jogaria em 'Lead'
    toda campanha cujo nome fuja do padrão, ou seja, perderia campanha real e mexeria em
    número publicado. Quem precisa do filtro de captação é `classify_variant`, que separa
    Meta de Google/orgânico — lá a porta é o `resolve_arm` completo.
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

    # 2e. Captação sem evento ML -> Controle
    if any(m in t for m in _CONTROLE_MARKERS) or "| lead |" in t or t.rstrip().endswith("lead"):
        return CONTROLE

    # 2f. Captação reconhecida mas sem nenhum marcador conhecido -> fail-loud
    return INDETERMINADO
