"""Gatilho do retreino por drift (etapa 5 do treino contínuo, 18/09/2026).

Quando a regra `score_drift` dos alertas críticos dispara (score médio de 60 minutos fora
do baseline de 30 dias), o orquestrador chama `disparar_retreino(motivo)`, que executa o
Cloud Run Job `retreino-mensal` pela API (`jobs.run`) com a identidade do próprio serviço.
Um marcador em `gs://smart-ads-mlflow/retreino/ultimo_gatilho.json` guarda o último
disparo; dentro do cooldown (14 dias) nada roda de novo, porque drift que persiste
dispararia o alerta a cada ciclo de 5 minutos.

O cron mensal (dia 1 às 06:00, `retreino-mensal-cron` no Cloud Scheduler) não passa por
aqui: é o Scheduler chamando o mesmo job.

Fail-soft por construção: qualquer erro vira {"disparado": False, "erro": ...}; o ciclo
de alertas nunca cai por causa do gatilho.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

PROJETO = os.environ.get("PROJECT_ID", "smart-ads-451319")
REGIAO = os.environ.get("RETREINO_REGIAO", "us-central1")
JOB = os.environ.get("RETREINO_JOB", "retreino-mensal")
MARCADOR = os.environ.get("RETREINO_MARCADOR", "gs://smart-ads-mlflow/retreino/ultimo_gatilho.json")
COOLDOWN_DIAS = int(os.environ.get("RETREINO_COOLDOWN_DIAS", "14"))


def deve_disparar(ultimo: Optional[Dict[str, Any]], agora: datetime, cooldown_dias: int = COOLDOWN_DIAS) -> bool:
    """Sem marcador, dispara; com marcador, só depois do cooldown."""
    if not ultimo or not ultimo.get("ts"):
        return True
    try:
        ts = datetime.fromisoformat(str(ultimo["ts"]))
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return agora - ts >= timedelta(days=cooldown_dias)


def _blob():
    from google.cloud import storage
    bucket, caminho = MARCADOR[len("gs://"):].split("/", 1)
    return storage.Client().bucket(bucket).blob(caminho)


def _ler_marcador() -> Optional[Dict[str, Any]]:
    b = _blob()
    if not b.exists():
        return None
    return json.loads(b.download_as_text())


def _gravar_marcador(d: Dict[str, Any]) -> None:
    _blob().upload_from_string(json.dumps(d, ensure_ascii=False), content_type="application/json")


def _executar_job() -> int:
    """POST jobs.run na API do Cloud Run com a identidade do serviço. Devolve o HTTP."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    r = AuthorizedSession(creds).post(
        f"https://run.googleapis.com/v2/projects/{PROJETO}/locations/{REGIAO}/jobs/{JOB}:run", json={}, timeout=30)
    return r.status_code


def disparar_retreino(motivo: str, agora: Optional[datetime] = None,
                      cooldown_dias: int = COOLDOWN_DIAS) -> Dict[str, Any]:
    agora = agora or datetime.now(timezone.utc)
    try:
        ultimo = _ler_marcador()
        if not deve_disparar(ultimo, agora, cooldown_dias):
            return {"disparado": False,
                    "motivo": f"cooldown de {cooldown_dias} dias: último gatilho em {str(ultimo.get('ts'))[:10]}"}
        http = _executar_job()
        _gravar_marcador({"ts": agora.isoformat(), "motivo": motivo[:300], "http": http})
        return {"disparado": 200 <= http < 300, "http": http, "motivo": motivo[:300]}
    except Exception as e:
        return {"disparado": False, "erro": f"{type(e).__name__}: {str(e)[:200]}"}
