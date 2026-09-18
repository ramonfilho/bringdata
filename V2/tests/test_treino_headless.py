"""Etapa 1 do treino contínuo: o pipeline roda num Cloud Run Job, sem `.env` e sem gcloud.

O que a imagem da API não tinha (mlflow, pyarrow) entra numa etapa `treino` do mesmo
Dockerfile; a credencial do MLflow chega como MLFLOW_DB_HOST + MLFLOW_DB_PASSWORD e a
URI é montada no código; a checagem do Cloud SQL que chamava gcloud vira aviso quando
não há SDK. Ver V2/docs/TREINO_CONTINUO_DESENHO.md.
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

V2 = Path(__file__).resolve().parents[1]
RAIZ = V2.parent
sys.path.insert(0, str(V2))


def _limpa_env(monkeypatch):
    for k in ("MLFLOW_TRACKING_URI", "MLFLOW_DB_HOST", "MLFLOW_DB_PASSWORD", "MLFLOW_DB_USER",
              "MLFLOW_DB_PORT", "MLFLOW_DB_NAME"):
        monkeypatch.delenv(k, raising=False)


def test_uri_do_mlflow_montada_de_host_e_senha(monkeypatch):
    from src.core import mlflow_setup as m
    _limpa_env(monkeypatch)
    monkeypatch.setenv("MLFLOW_DB_HOST", "10.0.0.5")
    monkeypatch.setenv("MLFLOW_DB_PASSWORD", "s3nh@ com/coisas")
    # Montada em partes: a guarda de credencial casa a forma `://usuário:senha@` numa linha só.
    assert m._uri_das_partes() == "postgresql+psycopg2://postgres:" + "s3nh%40%20com%2Fcoisas" + "@10.0.0.5:5432/mlflow"
    assert m.resolve_tracking_uri() == m._uri_das_partes()


def test_uri_explicita_ganha_das_partes(monkeypatch):
    from src.core import mlflow_setup as m
    _limpa_env(monkeypatch)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "sqlite:///x.db")
    monkeypatch.setenv("MLFLOW_DB_HOST", "10.0.0.5")
    monkeypatch.setenv("MLFLOW_DB_PASSWORD", "x")
    assert m.resolve_tracking_uri() == "sqlite:///x.db"


def test_sem_host_ou_senha_nao_monta_nada(monkeypatch):
    from src.core import mlflow_setup as m
    _limpa_env(monkeypatch)
    monkeypatch.setenv("MLFLOW_DB_HOST", "10.0.0.5")
    assert m._uri_das_partes() == ""


def test_sem_gcloud_a_checagem_do_backend_avisa_e_segue(monkeypatch):
    from src.model import training_model as t

    def sem_gcloud(*a, **k):
        raise FileNotFoundError("gcloud")

    import subprocess
    monkeypatch.setattr(subprocess, "run", sem_gcloud)
    assert t.assert_mlflow_backend_running() is None


def test_dockerfile_tem_etapa_treino_e_a_api_continua_sendo_a_ultima():
    linhas = [l for l in (V2 / "api/Dockerfile").read_text().splitlines() if l.startswith("FROM ")]
    assert linhas[0].endswith(" AS base")
    assert "FROM base AS treino" in linhas
    assert linhas[-1] == "FROM base AS api", "a última etapa tem que ser a API (build sem --target)"
    treino = (V2 / "api/Dockerfile").read_text().split("FROM base AS treino")[1].split("FROM base AS api")[0]
    assert "requirements-treino.txt" in treino and 'ENTRYPOINT ["python", "-m", "src.train_pipeline"]' in treino
    req = (V2 / "api/requirements-treino.txt").read_text()
    assert re.search(r"^mlflow==", req, re.M) and re.search(r"^pyarrow==", req, re.M)


def test_deploy_publica_a_imagem_de_treino_com_a_tag_da_api():
    d = yaml.safe_load((RAIZ / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))
    passos = d["jobs"]["canary"]["steps"]
    p = next(p for p in passos if "smart-ads-treino" in p.get("run", ""))
    assert "--target treino" in p["run"] and p.get("continue-on-error") is True


def test_setup_do_job_usa_segredos_e_fontes_do_banco():
    s = (RAIZ / "scripts/setup_retreino_job.sh").read_text()
    assert "MLFLOW_DB_PASSWORD=mlflow-db-password:latest" in s
    assert "LEDGER_DB_PASSWORD=ledger-db-password:latest" in s
    assert "--leads-source=db,--sales-source=db,--no-api-data" in s
    assert "MLFLOW_TRACKING_URI" not in s, "a URI com senha nunca passa pelo script"



def test_sem_nenhum_caminho_completo_a_mensagem_serve_para_o_job(monkeypatch, tmp_path):
    """Cenário do Job com o bind do segredo falhando: só o host chegou, sem `.env`."""
    from src.core import mlflow_setup as m
    _limpa_env(monkeypatch)
    monkeypatch.setenv("MLFLOW_DB_HOST", "10.0.0.5")
    monkeypatch.setattr(m, "_V2_ROOT", tmp_path)          # sem .env para carregar
    with pytest.raises(RuntimeError) as e:
        m.resolve_tracking_uri()
    msg = str(e.value)
    assert "MLFLOW_DB_HOST e MLFLOW_DB_PASSWORD" in msg and "mlflow-db-password" in msg
    assert "setup_retreino_job.sh" in msg


def test_modo_banco_e_so_quando_tudo_vem_do_cloud_sql():
    from src import train_pipeline as t
    assert t.modo_banco("db", "db", False)
    assert not t.modo_banco("db", "files", False)
    assert not t.modo_banco("files", "db", False)
    assert not t.modo_banco("db", "db", True)


def test_no_modo_banco_sem_planilha_a_celula_1_nao_le_arquivos():
    """Primeira execução do job (17/09/2026, retreino-mensal-mwmb2): a imagem não tem
    planilha e `read_excel_files([])` levantou ValueError antes de tocar no banco."""
    src = (V2 / "src" / "train_pipeline.py").read_text(encoding="utf-8")
    trecho = src.split("CÉLULA 1: LEITURA DE ARQUIVOS")[1].split("CÉLULA 2")[0]
    assert "elif modo_banco(leads_source, sales_source, include_api_data) and not filepaths:" in trecho
    assert "all_data = {}" in trecho
    ordem = trecho.index("modo_banco(") < trecho.index("all_data = read_all_training_sources(")
    assert ordem, "o modo banco tem que ser decidido antes da leitura de arquivos"
