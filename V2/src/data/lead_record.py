"""Formato interno do lead — contrato estável entre adaptadores e consumidores.

Adicionar campo é livre (consumidores antigos ignoram). Renomear ou remover é
decisão consciente que migra todos os consumidores no mesmo movimento.

Nomes em português pra não vazar vocabulário físico das tabelas (camelCase do
schema antigo, snake_case do ledger novo, etc.) pra dentro da lógica de
negócio.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


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

    # Respostas da pesquisa que o lead preencheu — chaves são as próprias
    # perguntas (em PT-Long, canônicas do modelo) ou as chaves slug do payload
    # Pub/Sub, dependendo do adaptador. Consumidores que dependem de campos
    # específicos da pesquisa devem normalizar antes de comparar.
    # `None` = adaptador não traz pesquisa (ou lead sem pesquisa registrada).
    survey_responses: Optional[Dict[str, str]] = None

    # Identidade pessoal — vem do payload Pub/Sub. Útil pra validação cruzada
    # com Guru/Meta no relatório semanal e pra futuras features de identidade.
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

    # Meta tracking — `fbp` (browser ID) e `fbc` (click ID). Essenciais pro
    # CAPI deduplicar com o pixel e atribuir corretamente. Reaproveitar pra
    # retreino: a presença/ausência se correlaciona com qualidade do lead.
    fbp: Optional[str] = None
    fbc: Optional[str] = None

    # Sessão do navegador — base pra features futuras de qualidade de tráfego
    # (bot detection, geo, etc.). Persistido cru, sem parsing.
    user_agent: Optional[str] = None
    ip: Optional[str] = None

    # Feature crítica do modelo. Vem top-level no payload do dono (não dentro
    # de `survey`) porque é capturada antes da pesquisa no funil dele. Tipo
    # TEXT (não BOOLEAN) porque o payload real manda "SIM"/"NAO" em
    # português — decisão revisada em 2026-05-25 após bug em produção
    # (BOOLEAN derrubava o INSERT inteiro com "invalid input syntax").
    has_computer: Optional[str] = None
