"""Formato interno do lead — contrato estável entre adaptadores e consumidores.

Adicionar campo é livre (consumidores antigos ignoram). Renomear ou remover é
decisão consciente que migra todos os consumidores no mesmo movimento.

Nomes em português pra não vazar vocabulário físico das tabelas (camelCase do
schema antigo, snake_case do ledger novo, etc.) pra dentro da lógica de
negócio.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# Valores válidos de `status_envio`. Adaptadores traduzem o vocabulário da
# fonte física pra esses valores; consumidores comparam contra estas constantes.
STATUS_SUCCESS = 'success'
STATUS_ERROR = 'error'
STATUS_SKIPPED_ALLOWLIST = 'skipped_allowlist'      # source fora da allowlist Meta
STATUS_SKIPPED_MISSING_DATA = 'skipped_missing_data' # faltou fbp/fbc/hasComputer

STATUS_VALORES_VALIDOS = frozenset({
    STATUS_SUCCESS,
    STATUS_ERROR,
    STATUS_SKIPPED_ALLOWLIST,
    STATUS_SKIPPED_MISSING_DATA,
})


@dataclass(frozen=True)
class LeadRecord:
    """Snapshot de um lead processado pelo pipeline. Imutável."""

    # Identidade e tempo — sempre presentes
    event_id: str
    email: str
    criado_em: datetime
    status_envio: str

    # Scoring — populados quando o lead chega a ser scoreado
    decil: Optional[int] = None
    score: Optional[float] = None
    variant: Optional[str] = None  # 'champion' | 'challenger' | None

    # Origem da campanha
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    utm_term: Optional[str] = None
    utm_url: Optional[str] = None

    # Envio CAPI ao Meta
    capi_enviado_em: Optional[datetime] = None
    erro: Optional[str] = None
