"""
core/ab_arm.py — Resolvedor único do braço do A/B (Champion / Challenger / Controle).

Fonte de verdade do braço que scoreou/otimizou cada lead, em ordem de prioridade:
  1. `registros_ml.variant` (gravado por produção no scoring) — quando existe (>= ~17/05/2026)
  2. reconstrução pelo padrão de campanha vigente na DATA de captura — pré-ledger
  3. fail-loud: janela ambígua + sem `variant` -> INDETERMINADO (nunca cai em Controle calado)

Função PURA: recebe os sinais já lidos (variant, utm_campaign, nome_campanha,
data_captura) e devolve o braço. NÃO consulta banco — a leitura do `variant` é
responsabilidade da camada de dados (injeção de dependência). Consumida hoje pela
validação; exposta para o monitoramento adotar quando houver necessidade.

Convenções e histórico de marcadores: V2/docs/DEFINICAO_ESCOPO_LFS.md
Espelha o histórico do `ab_test` em configs/active_models/devclub.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Tuple

# --- Rótulos canônicos (contrato estável) ---
CHAMPION = "Champion"
CHALLENGER = "Challenger"
CONTROLE = "Controle"
EXTERNO = "Externo"
INDETERMINADO = "Indeterminado"

# `registros_ml.variant` -> braço. Verdade gravada por produção.
_VARIANT_TO_ARM = {
    "champion_jan30": CHAMPION,
    "challenger_abr28": CHALLENGER,
}

# Marcadores (substring, case-insensitive) que sinalizam ML de Champion no nome/utm.
_CHAMPION_MARKERS: Tuple[str, ...] = ("leadqualified", "machine learning", "| ml |")
# `LQ` isolado (LeadQualified abreviado) também é Champion, mas só quando NÃO faz
# parte de um marcador Challenger da época (ex.: ML_MAR|LQC). Tratado em código.

# Marcadores de Controle: captação SEM evento ML (Lead puro, score, faixa).
_CONTROLE_MARKERS: Tuple[str, ...] = (
    "escala score", "aberto adv", "faixa ", "score",
)

_CAP_PREFIX = "devlf | cap | frio"  # captação Meta

# Marcadores INEQUÍVOCOS de Challenger (valem em qualquer data — só significam Challenger):
#   ml_mar   = teste Challenger mar/2026 (eventos LeadQualifiedCha*)
#   leadhqlb / hqlb = Challenger formalizado (abr/2026+)
#   utm_pixel = tag transitória (27/05)
_CHALLENGER_GLOBAL_MARKERS: Tuple[str, ...] = ("ml_mar", "leadhqlb", "hqlb", "utm_pixel")


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


def _is_captacao(text_lower: str) -> bool:
    return text_lower.startswith(_CAP_PREFIX)


def resolve_arm(
    *,
    variant: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    campaign_name: Optional[str] = None,
    captured_at=None,
) -> str:
    """
    Resolve o braço do A/B de um lead. Argumentos keyword-only (evita troca posicional).

    Args:
        variant: valor de `registros_ml.variant` (ex.: 'champion_jan30',
                 'challenger_abr28') ou None. **Verdade de produção quando presente.**
        utm_campaign: utm_campaign do lead (ledger/banco).
        campaign_name: nome da campanha (relatório Meta). Usado se utm ausente.
        captured_at: data de captura do lead (date/datetime/str). Necessária para
                 reconstrução por época quando não há `variant`.

    Returns:
        CHAMPION | CHALLENGER | CONTROLE | EXTERNO | INDETERMINADO
    """
    # 1. Verdade de produção: variant do ledger (NaN/None/'' = ausente)
    v = _clean_str(variant)
    if v:
        v = v.lower()
        for key, arm in _VARIANT_TO_ARM.items():
            if key in v:
                return arm
        # variant presente mas desconhecido -> fail-loud
        return INDETERMINADO

    # 2. Reconstrução por nome/utm + época
    text = _clean_str(utm_campaign) or _clean_str(campaign_name)
    if not text:
        return EXTERNO
    t = text.lower()
    if not _is_captacao(t):
        return EXTERNO  # Google/orgânico/sem campanha/outro lançamento

    d = _coerce_date(captured_at)

    # 2a. Marcador Challenger inequívoco (vale em qualquer data)
    if any(m in t for m in _CHALLENGER_GLOBAL_MARKERS):
        return CHALLENGER

    # 2b. Janela ambígua (PIXEL NOVO API): marcador presente, sem `variant` -> fail-loud
    if _ambiguous_marker_hit(t, d):
        return INDETERMINADO

    # 2c. Marcador Champion (ML de produção)
    if any(m in t for m in _CHAMPION_MARKERS) or _has_lq(t):
        return CHAMPION

    # 2d. Captação sem evento ML -> Controle
    if any(m in t for m in _CONTROLE_MARKERS) or "| lead |" in t or t.rstrip().endswith("lead"):
        return CONTROLE

    # 2e. Captação reconhecida mas sem nenhum marcador conhecido -> fail-loud
    return INDETERMINADO


def _has_lq(t: str) -> bool:
    """`LQ`/`LQC` isolado (LeadQualified) = Champion, fora de contexto ML_MAR (Challenger)."""
    if "ml_mar" in t:
        return False  # ML_MAR|LQC é Challenger, tratado pela era
    import re
    return bool(re.search(r"\b(lq|lqc)\b", t))
