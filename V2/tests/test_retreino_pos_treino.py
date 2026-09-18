"""Etapas 3 e 4 do treino contínuo: card, DM e PR do modelo pela API do GitHub (18/09/2026).

Sem rede: a sessão do GitHub é falsa e o MLflow não é tocado. O YAML de produção usado
é o real, para provar que o bloco ab_test sobrevive à reescrita.
"""
import base64
from pathlib import Path

import src.retreino.pos_treino as pt

RUN = "f" * 32
V = {"run_id": RUN, "champion": "5d158f0aa6e54b489498470446194a6c", "status": "FINISHED",
     "metricas": {"auc": 0.7221, "monotonia_percentage": 100.0, "lift_maximum": 3.1, "ks": 0.316},
     "params": {"git_commit": "bb23587", "git_dirty": "false", "dataset_hash": "77bc2ac9a17270ec", "dataset_linhas": "382128"},
     "artefatos_ok": True, "metricas_champion": {"auc": 0.7531}, "ok": False,
     "motivos": ["delta de AUC -0.0310 vs champion anterior abaixo de +0.005: política diz manter champion"],
     "nota": "ok"}


def test_card_traz_veredito_metricas_delta_hash_e_motivos():
    c = pt.montar_card(V)
    assert "run ffffffff REPROVADO" in c and "AUC 0.7221" in c and "KS 0.316" in c
    assert "delta de AUC contra o champion 5d158f0a: -0.0310" in c
    assert "hash 77bc2ac9a172, 382128 linhas" in c and "manter champion" in c


def test_sem_token_a_pr_nao_abre_e_o_motivo_diz_o_segredo(monkeypatch):
    monkeypatch.delenv("GITHUB_PR_TOKEN", raising=False)
    r = pt.abrir_pr({**V, "ok": True}, "card")
    assert r["ok"] is False and "github-pr-token" in r["motivo"]


def test_sem_canal_o_slack_nao_e_chamado(monkeypatch):
    monkeypatch.delenv("SLACK_USER_DM", raising=False)
    assert pt.avisar_slack("x")["ok"] is False


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._d = status, data

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Sessao:
    def __init__(self, yaml_texto):
        self.chamadas, self.yaml = [], yaml_texto

    def get(self, url, **k):
        self.chamadas.append(("GET", url, None))
        if url.endswith("/git/ref/heads/main"):
            return _Resp(200, {"object": {"sha": "abc123"}})
        if "/contents/" in url:
            return _Resp(200, {"content": base64.b64encode(self.yaml.encode("utf-8")).decode("ascii"), "sha": "filesha"})
        return _Resp(404, {})

    def post(self, url, json=None, **k):
        self.chamadas.append(("POST", url, json))
        if url.endswith("/git/refs"):
            return _Resp(201, {})
        if url.endswith("/pulls"):
            return _Resp(201, {"html_url": "https://github.com/ramonfilho/bringdata/pull/999"})
        return _Resp(500, {})

    def put(self, url, json=None, **k):
        self.chamadas.append(("PUT", url, json))
        return _Resp(200, {})


def test_pr_troca_so_o_bloco_active_model_e_abre_no_ramo_do_run():
    yaml_real = (Path(__file__).resolve().parents[1] / "configs" / "active_models" / "devclub.yaml").read_text(encoding="utf-8")
    s = _Sessao(yaml_real)
    mi = {"model_name": "rf_retreino_teste", "trained_at": "2026-10-01T06:00:00", "split_type": "temporal_leads"}
    r = pt.abrir_pr({**V, "ok": True}, "card do teste", sessao=s, model_info=mi)
    assert r["ok"] and r["url"].endswith("/pull/999") and r["ramo"] == "modelo/ffffffff"
    put = next(c for c in s.chamadas if c[0] == "PUT")
    novo = base64.b64decode(put[2]["content"]).decode("utf-8")
    assert f"mlflow_run_id: {RUN}" in novo and "ab_test:" in novo and "model_name: rf_retreino_teste" in novo
    assert put[2]["branch"] == "modelo/ffffffff"
    pr = next(c for c in s.chamadas if c[1].endswith("/pulls"))
    assert pr[2]["head"] == "modelo/ffffffff" and "card do teste" in pr[2]["body"] and "--activate-run" in pr[2]["body"]


def test_executar_reprovado_avisa_sem_abrir_pr(monkeypatch):
    enviados = []
    monkeypatch.setattr(pt, "julgar_candidato", lambda rid: V)
    monkeypatch.setattr(pt, "abrir_pr", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia abrir PR")))
    monkeypatch.setattr(pt, "avisar_slack", lambda t: enviados.append(t) or {"ok": True})
    r = pt.executar(RUN)
    assert r["pr"] is None and "Sem PR" in enviados[0] and "REPROVADO" in enviados[0]


def test_executar_aprovado_abre_pr_e_manda_o_link(monkeypatch):
    enviados = []
    monkeypatch.setattr(pt, "julgar_candidato", lambda rid: {**V, "ok": True, "motivos": [], "nota": "auto (delta AUC +0.0300)"})
    monkeypatch.setattr(pt, "abrir_pr", lambda v, c: {"ok": True, "url": "https://github.com/x/pull/1", "ramo": "modelo/ffffffff"})
    monkeypatch.setattr(pt, "avisar_slack", lambda t: enviados.append(t) or {"ok": True})
    r = pt.executar(RUN)
    assert r["pr"]["ok"] and "PR: https://github.com/x/pull/1" in enviados[0] and "APROVADO" in enviados[0]
