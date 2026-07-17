"""Normalização de payload Pub/Sub → vocabulário interno (formato Railway).

Camada anti-corrupção: o payload do front usa slugs (`"sim"`, `"clt"`,
`"transicao_carreira"`, `"firstName"`, `"hasComputer"`, ...). Nada disso
entra na lógica de scoring. Aqui é onde a tradução acontece — o resto do
sistema só conhece o vocabulário canônico (PT-Long do schema antigo
`lead_surveys`).

Três funções puras, sem efeitos colaterais, sem dependência de banco. Cada
uma transforma um dict em outro dict.

Quem importa: `api/pubsub_branch.py` (consumer Pub/Sub) e, daqui pra frente,
`src/scoring/` (casa do scoring de um lead).
"""
from typing import Dict, Optional
from urllib.parse import urlparse

from api.railway_mapping import traduzir_survey_slugs


def payload_to_survey_dict(payload: Dict) -> Dict:
    """Mapeia payload Pub/Sub → dict no shape `lead_surveys row` que o I2 espera.

    Aplica `traduzir_survey_slugs` no objeto `survey` antes de retornar.
    Pode levantar `ValueError` se o payload trouxer slug fora do vocabulário.
    """
    survey_in = payload.get("survey") or {}
    survey_traduzido = traduzir_survey_slugs(survey_in)
    return {
        "id":          payload.get("eventId"),
        "submittedAt": payload.get("submittedAt"),
        "clientEmail": payload.get("email"),
        "ip":          payload.get("ip4"),
        **survey_traduzido,
    }


def payload_to_enrich(payload: Dict) -> Dict:
    """Payload Pub/Sub já carrega hasComputer/fbp/fbc/etc direto.

    Nenhum JOIN, nenhum parse de log — só renomeia campos pra forma `enrich`
    que `survey_lead_to_sheets_row` espera (compat com I2).
    """
    fn = (payload.get("firstName") or "").strip()
    ln = (payload.get("lastName") or "").strip()
    nome = f"{fn} {ln}".strip() or None
    return {
        "computador": payload.get("hasComputer"),
        "telefone":   payload.get("phone"),
        "nome":       nome,
        "fbp":        payload.get("fbp"),
        "fbc":        payload.get("fbc"),
        "ip":         payload.get("ip4"),
        "user_agent": payload.get("userAgent"),
    }


def payload_to_utm(
    payload: Dict,
    source_from_url_slug: Optional[Dict[str, str]] = None,
) -> Dict:
    """Cópia rasa do bloco `utm` do payload. Dict vazio se ausente.

    Fallback de origem: quando o front NÃO manda `utm.source` mas a URL de
    captura carrega o canal no próprio slug da landing page (ex.: `/cap-meta-a-v1/`
    é tráfego Meta; `/cap-go-.../` é Google), deriva `source` do path da URL.

    `source_from_url_slug` (opcional): mapa {trecho-do-path: source RAW}, vindo de
    `ClientConfig.utm.source_from_url_slug`. O primeiro trecho contido no path
    vence. NUNCA sobrescreve origem já presente — só preenche a vazia. Sem o mapa
    (None/vazio) o comportamento é idêntico ao legado (só a cópia rasa).
    """
    utm = dict(payload.get("utm") or {})
    if not source_from_url_slug:
        return utm
    if (utm.get("source") or "").strip():
        return utm  # origem presente é autoritativa — nunca sobrescreve
    url = utm.get("url")
    if not url:
        return utm
    try:
        path = (urlparse(str(url)).path or "").lower()
    except Exception:
        return utm  # URL malformada: degrada pro legado (source segue vazio)
    for slug, source in source_from_url_slug.items():
        if slug and slug.lower() in path:
            utm["source"] = source
            break
    return utm
