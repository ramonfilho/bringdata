"""O deploy.yml não depende mais de clique: janela de deploy antes do primeiro tráfego,
cron de retomada e escada que para quando a janela está fechada (17/09/2026).
"""
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]


def _wf():
    return yaml.safe_load((RAIZ / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))


def _on(d):
    # PyYAML lê a chave `on` como o booleano True.
    return d.get("on") or d.get(True)


def test_cron_de_retomada_as_9h05_de_sao_paulo_em_dia_util():
    crons = [c["cron"] for c in _on(_wf())["schedule"]]
    assert crons == ["5 12 * * 1-5"]


def test_modo_retomar_existe_no_dispatch():
    modo = _on(_wf())["workflow_dispatch"]["inputs"]["modo"]
    assert "retomar" in modo["options"]


def test_primeiro_trafego_consulta_a_janela_e_so_promove_se_aberta():
    job = _wf()["jobs"]["canary-10"]
    passos = job["steps"]
    janela = next(p for p in passos if p.get("id") == "janela")
    assert "janela_de_deploy.py" in janela["run"]
    promove = next(p for p in passos if "promover_com_rollback.sh" in p.get("run", ""))
    assert promove["if"] == "steps.janela.outputs.aberta == 'true'"
    marcador = next(p for p in passos if p.get("if") == "steps.janela.outputs.aberta == 'false'")
    assert "MARCADOR" in marcador["run"] and "gcloud storage cp" in marcador["run"]
    assert "aguardando_janela.json" in job["env"]["MARCADOR"]
    assert "adiado" in job["outputs"]


def test_degraus_seguintes_param_quando_a_janela_adiou():
    jobs = _wf()["jobs"]
    assert "needs.canary-10.outputs.adiado != 'true'" in jobs["canary-50"]["if"]
    for nome in ("canary-10", "canary-50", "production", "vigia"):
        assert "retomar" in jobs[nome]["needs"], nome
        assert "!cancelled()" in jobs[nome]["if"], nome


def test_retomar_so_no_cron_ou_no_dispatch_e_confere_que_a_revisao_e_mais_nova():
    r = _wf()["jobs"]["retomar"]
    assert "schedule" in r["if"] and "retomar" in r["if"]
    corpo = next(p for p in r["steps"] if p.get("id") == "alvo")["run"]
    assert "não é mais nova que a viva" in corpo
    assert "aguardando_janela.json" in next(p for p in r["steps"] if p.get("id") == "alvo")["env"]["MARCADOR"]


def test_terraform_nao_tem_mais_reviewer_nos_environments():
    tf = (RAIZ / "infra/terraform/github.tf").read_text(encoding="utf-8")
    assert "reviewers {" not in tf
    assert 'github_repository_environment" "stage"' in tf
