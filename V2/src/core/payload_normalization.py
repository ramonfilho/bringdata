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
from typing import Dict

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


def payload_to_utm(payload: Dict) -> Dict:
    """Cópia rasa do bloco `utm` do payload. Dict vazio se ausente."""
    return dict(payload.get("utm") or {})
