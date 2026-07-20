"""api/meta_audiences.py — automação dos Públicos Personalizados (Custom Audiences)
da Meta: substitui os membros de um público por email+telefone hasheados (SHA-256),
lendo das tabelas já frescas do Cloud SQL/Railway (via `src/data/audience_reader.py`).

Objetivo: o gestor de tráfego para de baixar relatório e subir CSV na mão. Dois
públicos na conta do DevClub:
  - LEADS  (todos os leads, respondentes ou não)
  - ALUNOS (todos os compradores)

Separado do `capi_integration.py` (evento em tempo real) e do `meta_integration.py`
(leitura de insights) por design: aqui é gestão de LISTA estática (endpoint
`/{audience_id}/usersreplace`), outra finalidade e outro ciclo (batch diário, não
por-lead). Reusa o hasher canônico (`api/pii_hashing.py`) e a redação de segredo
(`meta_integration._redact`) — não duplica nenhum dos dois.

⚠️ ESCRITA É EXTERNA E IRREVERSÍVEL (conta do cliente). Disciplina obrigatória:
  1. `dry_run=True` (default) monta o payload e resume SEM enviar nada.
  2. Escrever membros exige a permissão `ads_management` no token — o System User
     atual só tem escopos de leitura (ads_read etc.). Enquanto o cliente não
     conceder `ads_management` no Business Manager, o replace real vai falhar 400.
  3. `usersreplace` SUBSTITUI o público inteiro. Se a lista vier curta/vazia, zera
     o público — por isso o reader tem piso de sanidade (fail-loud) antes daqui.

Graph API (customer file custom audience):
  POST /{audience_id}/usersreplace
    payload = {"schema": ["EMAIL","PHONE"], "data": [[emailhash, phonehash], ...]}
    session = {"session_id": <int>, "batch_seq": <n>, "last_batch_flag": <bool>,
               "estimated_num_total": <total>}
  Lotes de até 10.000 usuários por request.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from api.meta_integration import _redact           # fonte única da redação de token (PR #65)
from api.pii_hashing import hash_email, hash_phone  # hasher canônico (formato Meta)

logger = logging.getLogger(__name__)

# Máximo de usuários por request no endpoint de users da Custom Audience.
MAX_USERS_PER_BATCH = 10_000
# Schema multi-chave: cada linha de `data` casa posicionalmente com este vetor.
_SCHEMA = ["EMAIL", "PHONE"]


class MetaCustomAudienceClient:
    """Cliente fino da Graph API para gerir membros de um Custom Audience."""

    def __init__(self, access_token: str, api_version: str = "v24.0"):
        if not access_token:
            raise ValueError("META_ACCESS_TOKEN ausente — não dá pra falar com a Graph API.")
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{api_version}"

    # ---------------------------------------------------------------- leitura
    def get_audience(self, audience_id: str) -> Dict:
        """GET dos metadados do público (nome, tamanho aproximado, status). Read-only —
        usado pra CONFIRMAR o alvo antes de substituir."""
        r = requests.get(
            f"{self.base_url}/{audience_id}",
            params={
                "fields": "id,name,subtype,approximate_count_lower_bound,operation_status,permission_for_actions",
                "access_token": self.access_token,
            },
            timeout=30,
        )
        if r.status_code >= 400:
            return {"status": "error", "http_status": r.status_code, "message": _redact(r.text)[:400]}
        return {"status": "ok", **r.json()}

    # -------------------------------------------------------------- payload
    @staticmethod
    def build_rows(members: pd.DataFrame) -> List[List[str]]:
        """DataFrame {email, phone} → linhas de `data` hasheadas [emailhash, phonehash].
        Telefone ausente vira "" (a Meta aceita chave vazia numa linha multi-chave).
        Descarta a linha se o email E o telefone forem inválidos (nada pra casar)."""
        rows: List[List[str]] = []
        for email, phone in zip(members.get("email", []), members.get("phone", [])):
            eh = hash_email(email) or ""
            ph = hash_phone(phone) or ""
            if not eh and not ph:
                continue
            rows.append([eh, ph])
        return rows

    # -------------------------------------------------------------- escrita
    def replace_users(
        self,
        audience_id: str,
        members: pd.DataFrame,
        *,
        dry_run: bool = True,
    ) -> Dict:
        """Substitui TODOS os membros do público pelos de `members` ({email, phone}).

        dry_run=True (default): monta os lotes hasheados e devolve um resumo
        (contagens, nº de lotes, amostra de hash) SEM enviar nada.
        dry_run=False: executa o `usersreplace` batelado. Requer `ads_management`.
        """
        rows = self.build_rows(members)
        total = len(rows)
        n_email = sum(1 for r in rows if r[0])
        n_phone = sum(1 for r in rows if r[1])
        n_batches = (total + MAX_USERS_PER_BATCH - 1) // MAX_USERS_PER_BATCH

        summary = {
            "audience_id": audience_id,
            "total_members": total,
            "rows_with_email": n_email,
            "rows_with_phone": n_phone,
            "n_batches": n_batches,
            "schema": _SCHEMA,
            "sample_row_hashed": rows[0] if rows else None,  # já hasheado — seguro de logar
            "dry_run": dry_run,
        }

        if total == 0:
            # Nunca substituir por vazio — zeraria o público na conta do cliente.
            summary["status"] = "aborted_empty"
            logger.error("[meta_audiences] 0 membros pra %s — abortado (não zero o público).", audience_id)
            return summary

        if dry_run:
            summary["status"] = "dry_run_ok"
            logger.info("[meta_audiences] DRY-RUN %s: %d membros, %d lotes (NADA enviado).",
                        audience_id, total, n_batches)
            return summary

        # ---- escrita real (só chega aqui com dry_run=False explícito) ----
        session_id = int(time.time())  # id único desta operação de replace
        results = []
        for i in range(n_batches):
            batch = rows[i * MAX_USERS_PER_BATCH:(i + 1) * MAX_USERS_PER_BATCH]
            session = {
                "session_id": session_id,
                "batch_seq": i + 1,
                "last_batch_flag": (i + 1 == n_batches),
                "estimated_num_total": total,
            }
            payload = {"schema": _SCHEMA, "data": batch}
            r = requests.post(
                f"{self.base_url}/{audience_id}/usersreplace",
                data={
                    "payload": json.dumps(payload),
                    "session": json.dumps(session),
                    "access_token": self.access_token,
                },
                timeout=60,
            )
            if r.status_code >= 400:
                msg = _redact(r.text)[:500]
                logger.error("[meta_audiences] lote %d/%d falhou (%s): %s", i + 1, n_batches, r.status_code, msg)
                results.append({"batch": i + 1, "status": "error", "http_status": r.status_code, "message": msg})
                summary["status"] = "error"
                summary["results"] = results
                return summary  # aborta na 1ª falha (não deixa o público meio-substituído em silêncio)
            results.append({"batch": i + 1, "status": "sent", "response": r.json() if r.content else {}})
            logger.info("[meta_audiences] lote %d/%d enviado (%d membros).", i + 1, n_batches, len(batch))

        summary["status"] = "replaced"
        summary["results"] = results
        summary["session_id"] = session_id
        return summary
