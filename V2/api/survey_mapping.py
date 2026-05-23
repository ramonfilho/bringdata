"""I2 — Adaptador `lead_surveys` (+ enriquecimento) → dicionário do scorer.

Contexto: a captação migrou de `Lead` para `lead_surveys`. Para scorear esses
leads com o MESMO modelo, sem reimplementar normalização, este módulo monta um
dict no **formato de uma linha de `Lead`** a partir de:

  - `survey`  : linha da `lead_surveys` (respostas da pesquisa + id/email/ip)
  - `utm`     : linha do `UTMTracking` casada por email (I3)
  - `enrich`  : campos recuperados de `integration_logs` (I3): `computador`,
                `telefone`, `nome`, `fbp`, `fbc`, `ip`, `user_agent`

…e delega à função canônica `railway_lead_to_sheets_row` (em
`api/railway_mapping.py`) — a MESMA usada pelo pipeline do `Lead`, com os mapas
semânticos já validados. Resultado: o scorer vê features idênticas; nenhuma
transformação é reimplementada fora do caminho canônico.

Função **pura**: sem DB, sem efeito colateral, sem I/O. O JOIN que produz `utm`
e `enrich` é o I3; o skip por dado faltante (sem `computador`/fbp/fbc) e o envio
CAPI são o I4. Este módulo entrega especificamente o **dict do scorer**.

Campos que `railway_lead_to_sheets_row` lê (contrato de entrada, todos via
`.get()`): `pesquisa` (dict) + os 9 diretos `email, nomeCompleto, telefone,
data, source, medium, campaign, term, content`. Não toca id/pageUrl/fbc/fbp/
remoteIp/userAgent — esses não são input do scorer (vão ao CAPI no I4).
"""
from typing import Dict, Optional

from api.railway_mapping import railway_lead_to_sheets_row

# Respostas da pesquisa que vivem como colunas na `lead_surveys`.
# `computador` NÃO está na lead_surveys — vem do enriquecimento (integration_logs).
_SURVEY_PESQUISA_KEYS = (
    "genero",
    "idade",
    "ocupacao",
    "faixaSalarial",
    "cartaoCredito",
    "interesseEvento",
    "estudouProgramacao",
    "faculdade",
    "investiuCurso",
    "atracaoProfissao",
)


def survey_to_lead_shaped(
    survey: Dict,
    utm: Optional[Dict] = None,
    enrich: Optional[Dict] = None,
) -> Dict:
    """Monta um dict no formato de uma linha de `Lead` a partir do survey lead
    enriquecido. Não normaliza nada — só remapeia campos. Pura.

    `utm`/`enrich` podem ser None/{} (lead sem match) — campos viram None, e
    `railway_lead_to_sheets_row` lida com None nativamente.
    """
    utm = utm or {}
    enrich = enrich or {}

    pesquisa: Dict = {k: survey.get(k) for k in _SURVEY_PESQUISA_KEYS}
    # `computador` é a feature principal do modelo e NÃO existe na lead_surveys;
    # vem do enriquecimento (integration_logs n8n_onboarding OU activecampaign 144).
    pesquisa["computador"] = enrich.get("computador")

    return {
        "id": survey.get("id"),
        "data": survey.get("submittedAt"),
        "email": survey.get("clientEmail"),
        "nomeCompleto": enrich.get("nome"),
        "telefone": enrich.get("telefone"),
        "source": utm.get("source"),
        "medium": utm.get("medium"),
        "campaign": utm.get("campaign"),
        "content": utm.get("content"),
        "term": utm.get("term"),
        "pesquisa": pesquisa,
    }


def survey_lead_to_sheets_row(
    survey: Dict,
    utm: Optional[Dict] = None,
    enrich: Optional[Dict] = None,
    client_config=None,
) -> Dict:
    """Survey lead enriquecido → dicionário de entrada do scorer.

    Equivalente, por construção, ao que o pipeline do `Lead` produz: monta o
    formato-`Lead` e chama a função canônica `railway_lead_to_sheets_row`.
    """
    lead_shaped = survey_to_lead_shaped(survey, utm, enrich)
    return railway_lead_to_sheets_row(lead_shaped, client_config=client_config)
