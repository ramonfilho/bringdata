"""Drift entre payload_schema (monitoring) e DailyCheckResponse (Pydantic).

Cobre o cheiro arquitetural identificado em 2026-05-25:

  O daily-check tem 2 declarações da forma do payload:
    1. PAYLOAD_SCHEMA em src/monitoring/payload_schema.py (paths canônicos)
    2. DailyCheckResponse em api/app.py (Pydantic response_model)

  Os dois precisam ficar em sync manualmente. Se alguém adiciona um sumário
  novo (ex: pubsub_24h_summary) no orchestrator + payload_schema mas esquece
  de declarar no Pydantic, FastAPI dropa silenciosamente — a chave some do
  JSON e o digest do Slack não renderiza o bloco. Foi o bug que travou o
  bloco "📨 Pub/Sub 24h" e "🎯 Paridade treino × produção".

Este teste itera as chaves top-level do PAYLOAD_SCHEMA e exige que TODAS
estejam declaradas no DailyCheckResponse. Falha alto se houver drift.

Rodável sem pytest:  python tests/test_daily_check_schema_drift.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _load_dotenv_if_present():
    """Carrega V2/.env nas env vars se ainda não estiverem setadas. Necessário
    porque importar api.app dispara init de banco (DATABASE_URL/RAILWAY_DB_*).
    """
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if not os.path.exists(env_path) or os.environ.get('RAILWAY_DB_HOST'):
        return
    with open(env_path) as f:
        for raw in f:
            ln = raw.strip()
            if not ln or ln.startswith('#') or '=' not in ln:
                continue
            k, _, v = ln.partition('=')
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


_load_dotenv_if_present()

from src.monitoring.payload_schema import PAYLOAD_SCHEMA


def _top_level_keys(schema: dict) -> set[str]:
    """Extrai a primeira parte de cada path (antes de `.` ou `[`)."""
    keys = set()
    for path in schema.keys():
        # Corta no primeiro `.` ou `[`
        head = path.split('.', 1)[0].split('[', 1)[0]
        if head:
            keys.add(head)
    return keys


def _daily_check_response_fields() -> set[str]:
    """Extrai os fields declarados no DailyCheckResponse via Pydantic."""
    from api.app import DailyCheckResponse
    return set(DailyCheckResponse.model_fields.keys())


def test_payload_schema_todas_top_level_keys_no_pydantic():
    schema_keys = _top_level_keys(PAYLOAD_SCHEMA)
    pydantic_keys = _daily_check_response_fields()

    missing = schema_keys - pydantic_keys
    if missing:
        raise AssertionError(
            f"PAYLOAD_SCHEMA declara {len(missing)} chave(s) top-level que "
            f"NÃO existem em DailyCheckResponse: {sorted(missing)}.\n"
            f"Adicione cada uma como `<chave>: Optional[Dict[str, Any]] = None` "
            f"(ou tipo apropriado) em api/app.py:DailyCheckResponse. "
            f"Sem isso, FastAPI dropa o campo silenciosamente na serialização."
        )


def test_pydantic_nao_tem_chave_extra_alem_do_schema():
    """Inverso: chaves no Pydantic que NÃO estão no PAYLOAD_SCHEMA."""
    schema_keys = _top_level_keys(PAYLOAD_SCHEMA)
    pydantic_keys = _daily_check_response_fields()

    extra = pydantic_keys - schema_keys
    if extra:
        raise AssertionError(
            f"DailyCheckResponse declara {len(extra)} chave(s) que NÃO estão "
            f"no PAYLOAD_SCHEMA: {sorted(extra)}.\n"
            f"Ou o orchestrator não produz mais esses campos (remover do "
            f"Pydantic) ou faltou declarar no payload_schema.py."
        )


if __name__ == "__main__":
    tests = [
        test_payload_schema_todas_top_level_keys_no_pydantic,
        test_pydantic_nao_tem_chave_extra_alem_do_schema,
    ]
    n_pass = n_fail = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            n_pass += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}:\n        {e}")
            n_fail += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            n_fail += 1
    print(f"\n{n_pass}/{len(tests)} passaram")
    sys.exit(0 if n_fail == 0 else 1)
