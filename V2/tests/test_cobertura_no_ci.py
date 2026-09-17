"""A cobertura e medida no CI e tem piso.

Piso = o valor medido no dia em que entrou (14% em 17/09/2026, 972 testes, 52.449 linhas).
Nao e meta, e trava: a suite nao pode ficar menos abrangente sem alguem ver.
"""
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]


def test_ci_roda_pytest_com_cobertura_e_piso():
    ci = (_RAIZ / ".github" / "workflows" / "ci.yml").read_text()
    m = re.search(r"pytest --cov .*--cov-fail-under=(\d+)", ci)
    assert m, "pytest no ci.yml sem --cov e --cov-fail-under"
    assert int(m.group(1)) >= 14


def test_pytest_cov_esta_no_requirements_dev():
    req = (_RAIZ / "V2" / "requirements-dev.txt").read_text()
    assert re.search(r"^pytest-cov==", req, re.M)


def test_coveragerc_mede_src_api_scripts_e_ignora_testes():
    rc = (_RAIZ / "V2" / ".coveragerc").read_text()
    assert "source = src, api, scripts" in rc and "*/tests/*" in rc and "*/mlruns/*" in rc
