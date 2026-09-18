"""Passo de workflow que passa por pipe declara `shell: bash` (liga -o pipefail).

De 17/09 a 18/09/2026 o job de pytest do CI ficou verde com testes falhando: o passo
terminava em `| tee pytest.out` e, sem `shell: bash`, o exit era o do `tee`.
"""
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]


def _passos(arquivo):
    wf = yaml.safe_load((RAIZ / ".github" / "workflows" / arquivo).read_text(encoding="utf-8"))
    for nome, job in wf["jobs"].items():
        for p in job.get("steps") or []:
            yield nome, p


def test_pytest_do_ci_roda_com_pipefail():
    passo = next(p for _, p in _passos("ci.yml") if "pytest" in (p.get("run") or "") and "| tee" in p["run"])
    assert passo.get("shell") == "bash"


def test_alvo_de_rollback_do_deploy_roda_com_pipefail():
    passo = next(p for _, p in _passos("deploy.yml") if p.get("id") == "before")
    assert passo.get("shell") == "bash"
