"""Rede do refactor do app.py: a tabela de rotas e o schema OpenAPI da API são
congelados em fixtures, e qualquer mudança acidental (rota que sumiu, método que
mudou, body que perdeu um campo) falha aqui antes de chegar ao canário.

Por que existe: o app.py tinha 6.122 linhas num arquivo só; a quebra em routers
(api/routers/*) move cada handler de lugar sem mudar comportamento. Este teste é
a prova mecânica de que nada mudou na superfície HTTP.

Regerar as fixtures (SÓ quando uma mudança de rota for intencional):
    cd V2 && python3 tests/test_app_rotas_congeladas.py --regravar
"""
import json
import os
import sys
from pathlib import Path

# api.app monta o engine do SQLAlchemy no import (api/database.py lê DATABASE_URL);
# um URL sintático basta, create_engine não conecta.
os.environ.setdefault("DATABASE_URL", "postgresql://teste:teste@localhost:5432/teste")

# Pasta própria (tests/fixtures/ está no .gitignore e engoliu a primeira versão destas fixtures).
FIXTURES = Path(__file__).resolve().parent / "rotas_congeladas"
ROTAS = FIXTURES / "rotas_app.json"
OPENAPI = FIXTURES / "openapi_app.json"


def _carregar_app():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import api.app as app_mod
    return app_mod


def _achatar(rotas, prefixo=""):
    """Rotas folha (as que têm `methods`), atravessando routers incluídos.

    Até o Starlette 0.27 `app.routes` já vinha achatado (uma APIRoute por rota, com o
    prefixo aplicado). No Starlette 1.x (FastAPI 0.141, produção desde 18/09/2026)
    `app.routes` devolve um wrapper por `include_router` (`original_router` + contexto
    com o prefixo) e as rotas ficam dentro dele; sem atravessar, a tabela saía vazia e o
    teste passava só em máquina com a versão velha.
    """
    for r in rotas:
        if hasattr(r, "methods"):
            yield r, prefixo
            continue
        interno = getattr(r, "original_router", None) or getattr(r, "router", None)
        filhas = getattr(interno, "routes", None) if interno is not None else getattr(r, "routes", None)
        if not filhas:
            continue
        ctx = getattr(r, "include_context", None)
        sub = (getattr(ctx, "prefix", None) or getattr(r, "prefix", None)
               or getattr(interno, "prefix", None) or "")
        yield from _achatar(filhas, prefixo + sub)


def tabela_de_rotas(app) -> list:
    linhas = []
    for r, prefixo in _achatar(app.routes):
        caminho = r.path if (not prefixo or r.path.startswith(prefixo)) else prefixo + r.path
        r = type("R", (), {"path": caminho, "methods": r.methods, "name": r.name, "endpoint": r.endpoint})()
        linhas.append({
            "path": r.path,
            "methods": sorted(r.methods),
            "name": r.name,
            "endpoint": r.endpoint.__name__,
        })
    return sorted(linhas, key=lambda x: (x["path"], x["methods"]))


def _openapi(app) -> dict:
    return json.loads(json.dumps(app.openapi(), sort_keys=True))


def test_tabela_de_rotas_congelada():
    app_mod = _carregar_app()
    esperado = json.loads(ROTAS.read_text())
    atual = tabela_de_rotas(app_mod.app)
    assert atual == esperado, (
        "a tabela de rotas mudou; se foi intencional, regrave com "
        "`python3 tests/test_app_rotas_congeladas.py --regravar`"
    )


def test_openapi_congelado():
    app_mod = _carregar_app()
    esperado = json.loads(OPENAPI.read_text())
    atual = _openapi(app_mod.app)
    if atual != esperado:
        difs = []
        for chave in ("paths", "components"):
            e, a = esperado.get(chave, {}), atual.get(chave, {})
            for k in sorted(set(e) | set(a)):
                if e.get(k) != a.get(k):
                    difs.append(f"{chave}.{k}")
        raise AssertionError("OpenAPI mudou em: " + ", ".join(difs[:20]))


def test_contrato_de_nomes_exportados_pelo_app():
    """Consumidores fora do app.py leem estes nomes de `api.app`
    (pubsub_branch importa get_cpl_lookup; testes importam DailyCheckResponse)."""
    app_mod = _carregar_app()
    for nome in ("app", "pipelines", "cpl_lookups", "get_cpl_lookup",
                 "initialize_pipelines", "initialize_cpl_lookups",
                 "get_active_pipeline", "PipelineDep", "PipelineOptDep",
                 "DailyCheckResponse", "startup_event"):
        assert hasattr(app_mod, nome), f"api.app perdeu o nome `{nome}`"


if __name__ == "__main__":
    if "--regravar" in sys.argv:
        m = _carregar_app()
        FIXTURES.mkdir(exist_ok=True)
        ROTAS.write_text(json.dumps(tabela_de_rotas(m.app), indent=1, ensure_ascii=False) + "\n")
        OPENAPI.write_text(json.dumps(_openapi(m.app), indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"gravado: {ROTAS.name} ({len(tabela_de_rotas(m.app))} rotas), {OPENAPI.name} ({OPENAPI.stat().st_size} bytes)")
