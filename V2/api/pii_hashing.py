"""api/pii_hashing.py — normalização + hash SHA-256 de PII (email/telefone) no
formato que a Meta espera para casar usuários (Custom Audiences E Conversions API).

FONTE ÚNICA (por design). Hoje esta regra está DUPLICADA em três lugares que
nasceram antes deste módulo:
  - `capi_integration.hash_data` (Meta CAPI) — lower/strip + sha256 (só email; pro
    telefone ele NÃO tira pontuação, depende do dado já vir em dígitos).
  - `google_ads_integration._normalize_email/_normalize_phone_e164/_sha256` — o
    telefone lá sai em E.164 COM '+', que é o formato do Google (a Meta quer SEM '+').
Este módulo é o destino canônico. NÃO refatorei os dois acima neste PR de propósito:
o CAPI é produção intocável (ver V2/CLAUDE.md "O que não tocar") e a regra de escopo
restrito manda não consertar de passagem. Ficam como dívida registrada pra migrar
quando houver janela — quando migrarem, viram wrappers finos sobre estas funções.

Regra de normalização da Meta (advanced matching / customer file):
  - EMAIL:    trim + lowercase, depois SHA-256.
  - TELEFONE: só dígitos, COM código do país (Brasil = 55), SEM '+', SEM zero à
              esquerda, depois SHA-256. Ex.: "(11) 99999-8888" → "5511999998888".
Ref.: developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences
(seção "Hashing & Normalization") e .../conversions-api (customer_information_parameters).
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

# País default pra completar telefone que vier sem DDI (DevClub = BR). Espelha o
# _DEFAULT_PHONE_CC do google_ads_integration — mesmo valor, mesma intenção.
_DEFAULT_PHONE_CC = "55"


def normalize_email(email: Optional[str]) -> Optional[str]:
    """trim + lowercase. None se vazio. (Não removemos pontos/'+' de gmail: casar
    exatamente o que o formulário coletou dá match rate melhor que 'consertar'.)"""
    if not email:
        return None
    e = str(email).strip().lower()
    return e or None


def normalize_phone_br(phone: Optional[str]) -> Optional[str]:
    """Telefone no formato da Meta: só dígitos, com DDI 55, SEM '+'. Best-effort:
      - tira tudo que não é dígito;
      - 12-13 dígitos começando com 55 (DDI já presente): mantém;
      - 10-11 dígitos (DDD + número, sem DDI): prepend 55;
      - qualquer outro tamanho: None (não arrisca match errado).
    Retorna ex. "5519994137133". None se não normalizável.

    OBS: o formato canônico da Meta é SEM '+' — diferente do E.164 do Google, que
    leva '+'. Por isso esta função é irmã (não igual) do _normalize_phone_e164 de lá.
    """
    if not phone:
        return None
    s = str(phone).strip()
    # Telefone guardado como float em algum ponto do pipeline vira texto com sufixo
    # decimal ("5531975766341.0"): o ".0" injeta um dígito 0 a mais e quebra o
    # tamanho (13→14). Remove a parte decimal ANTES de extrair dígitos — recupera
    # ~44k dos ~45k telefones de leads que antes caíam. (Nº de telefone não tem
    # casa decimal legítima, então tirar "\.\d+$" é seguro.)
    s = re.sub(r"\.\d+$", "", s)
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if digits.startswith(_DEFAULT_PHONE_CC) and len(digits) in (12, 13):
        return digits                      # já tem DDI 55
    if len(digits) in (10, 11):            # DDD + número, sem DDI
        return _DEFAULT_PHONE_CC + digits
    return None                            # formato inesperado — descarta


def sha256_hex(value: Optional[str]) -> Optional[str]:
    """SHA-256 hex de uma string JÁ normalizada. None entra, None sai."""
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_email(email: Optional[str]) -> Optional[str]:
    """Email normalizado (trim+lower) → SHA-256 hex, ou None."""
    return sha256_hex(normalize_email(email))


def hash_phone(phone: Optional[str]) -> Optional[str]:
    """Telefone normalizado (dígitos+DDI, sem '+') → SHA-256 hex, ou None."""
    return sha256_hex(normalize_phone_br(phone))
