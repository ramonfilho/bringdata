"""Depois do treino headless: julgar o run, avisar no Slack e abrir a PR do modelo.

Etapas 3 e 4 do treino contínuo (V2/docs/TREINO_CONTINUO_DESENHO.md), entregues em
18/09/2026. O job `retreino-mensal` roda `python -m src.train_pipeline ... --pos-treino`;
no fim do treino, `executar(run_id)`:

  1. julga o run novo com a MESMA régua do gate do CI (`scripts/ci_check_active_model.julgar`):
     FINISHED, artefatos do deploy e do retrato no run, pisos de AUC e monotonia, lineage
     (git_commit, git_dirty), conjunto congelado (dataset_hash), delta de AUC contra o
     champion do YAML de produção;
  2. monta o card (métricas, delta, hash do conjunto, motivos) e manda por DM no Slack
     (SLACK_USER_DM + SLACK_BOT_TOKEN, os mesmos do monitoring), em qualquer veredito;
  3. se passou, abre a PR do modelo pela API do GitHub (segredo GITHUB_PR_TOKEN): ramo
     `modelo/<run8>`, o bloco active_model do YAML reescrito por
     `reescrever_active_model_yaml` (o mesmo de `--activate-run`), corpo com o card.
     Sem o segredo, o DM traz o comando manual (`scripts/abrir_pr_modelo.sh <run>`).

A aprovação humana continua sendo o merge da PR: o CI julga o run de novo pelo gate.
Nada aqui derruba um treino que já terminou: quem chama envolve em try/except.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

V2 = Path(__file__).resolve().parents[2]
REPO = os.environ.get("GITHUB_REPO", "ramonfilho/bringdata")
YAML_REL = "V2/configs/active_models/devclub.yaml"
API = "https://api.github.com"


def _gate():
    """O módulo do gate do CI (V2/scripts), importado tarde: puxa mlflow e yaml."""
    if str(V2) not in sys.path:
        sys.path.insert(0, str(V2))
    from scripts import ci_check_active_model as g
    return g


def artefatos_no_run(run_id: str) -> bool:
    """Os arquivos do deploy e do retrato, pelo cliente do MLflow (o job não tem gcloud)."""
    import mlflow
    g = _gate()
    c = mlflow.tracking.MlflowClient()
    raiz = {a.path for a in c.list_artifacts(run_id)}
    modelo = {a.path for a in c.list_artifacts(run_id, "model")}
    return all(p in raiz or p in modelo for p in g.ARQUIVOS_DO_DEPLOY + g.ARQUIVOS_DO_RETRATO)


def julgar_candidato(run_id: str, client: str = "devclub") -> Dict[str, Any]:
    """Aplica a régua do CI ao run novo, como candidato a champion contra o champion do YAML."""
    import yaml
    g = _gate()
    cfg = yaml.safe_load((V2 / "configs" / "active_models" / f"{client}.yaml").read_text(encoding="utf-8")) or {}
    champion = (cfg.get("active_model") or {}).get("mlflow_run_id")
    limiares = g.limiares_de(yaml.safe_load((V2 / "configs" / "retreino_mensal.yaml").read_text(encoding="utf-8")) or {})
    status, metricas, params = g.ler_run(run_id)
    artefatos = artefatos_no_run(run_id)
    m_ant = None
    if champion and champion != run_id:
        try:
            m_ant = g.ler_run(champion)[1]
        except Exception:
            m_ant = None
    ok, motivos, nota = g.julgar("champion", metricas, params, status, artefatos, limiares, m_ant)
    return {"run_id": run_id, "champion": champion, "status": status, "metricas": metricas,
            "params": params, "artefatos_ok": artefatos, "metricas_champion": m_ant,
            "ok": ok, "motivos": motivos, "nota": nota}


def _f(m: Dict[str, Any], k: str, casas: int = 4) -> str:
    v = m.get(k)
    return f"{float(v):.{casas}f}" if v is not None else "-"


def montar_card(v: Dict[str, Any]) -> str:
    """Texto do veredito em markdown simples (vale no Slack e no corpo da PR)."""
    m, p = v["metricas"], v["params"]
    ks = next((m[k] for k in ("ks", "ks_statistic", "ks_stat") if m.get(k) is not None), None)
    linhas = [
        f"*Retreino: run {v['run_id'][:8]} {'APROVADO' if v['ok'] else 'REPROVADO'}* [{v['nota']}]",
        f"AUC {_f(m, 'auc')} | monotonia {_f(m, 'monotonia_percentage', 1)}% | lift {_f(m, 'lift_maximum', 2)}"
        + (f" | KS {float(ks):.3f}" if ks is not None else ""),
    ]
    ant = v.get("metricas_champion") or {}
    if ant.get("auc") is not None and m.get("auc") is not None:
        delta = float(m["auc"]) - float(ant["auc"])
        linhas.append(f"delta de AUC contra o champion {str(v.get('champion') or '')[:8]}: {delta:+.4f}")
    sujo = " (sujo)" if str(p.get("git_dirty", "")).lower() == "true" else ""
    linhas.append(f"conjunto congelado: hash {str(p.get('dataset_hash') or '-')[:12]}, "
                  f"{p.get('dataset_linhas') or '-'} linhas; commit {p.get('git_commit') or '-'}{sujo}")
    if v["motivos"]:
        linhas.append("motivos:")
        linhas.extend(f"  - {x}" for x in v["motivos"])
    return "\n".join(linhas)


def avisar_slack(texto: str) -> Dict[str, Any]:
    """DM para SLACK_USER_DM pelo mesmo cliente do monitoring (fail-soft: devolve ok=False)."""
    canal = os.environ.get("SLACK_USER_DM")
    if not canal:
        return {"ok": False, "error": "SLACK_USER_DM missing"}
    try:
        from src.monitoring.slack_client import post_blocks
        return post_blocks(canal, [{"type": "section", "text": {"type": "mrkdwn", "text": texto[:2900]}}],
                           texto.splitlines()[0][:150])
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------ PR do modelo
def _sessao(token: str):
    import requests
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                      "X-GitHub-Api-Version": "2022-11-28"})
    return s


def _model_info(run_id: str) -> Dict[str, Any]:
    """model_info do model_metadata.json do run (o mesmo que --activate-run usa)."""
    import mlflow
    c = mlflow.tracking.MlflowClient()
    with tempfile.TemporaryDirectory() as tmp:
        caminho = c.download_artifacts(run_id, "model_metadata.json", tmp)
        with open(caminho, encoding="utf-8") as f:
            return (json.load(f) or {}).get("model_info", {}) or {}


def yaml_com_run_novo(texto_yaml: str, run_id: str, model_info: Dict[str, Any]) -> str:
    """O YAML de produção com o bloco active_model apontando para o run (resto intacto)."""
    from src.model.training_model import reescrever_active_model_yaml
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "devclub.yaml"
        p.write_text(texto_yaml, encoding="utf-8")
        reescrever_active_model_yaml(p, run_id, model_info)
        return p.read_text(encoding="utf-8")


def abrir_pr(v: Dict[str, Any], card: str, *, sessao=None,
             model_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Abre a PR de promoção pela API do GitHub. Sem GITHUB_PR_TOKEN, devolve ok=False e o motivo."""
    token = os.environ.get("GITHUB_PR_TOKEN")
    if not token and sessao is None:
        return {"ok": False, "motivo": "GITHUB_PR_TOKEN ausente (segredo github-pr-token no Secret Manager)"}
    run_id = v["run_id"]
    ramo = f"modelo/{run_id[:8]}"
    s = sessao or _sessao(token)
    try:
        base = s.get(f"{API}/repos/{REPO}/git/ref/heads/main", timeout=30)
        base.raise_for_status()
        sha_main = base.json()["object"]["sha"]
        r = s.post(f"{API}/repos/{REPO}/git/refs", json={"ref": f"refs/heads/{ramo}", "sha": sha_main}, timeout=30)
        if r.status_code not in (201, 422):      # 422 = o ramo já existe (tentativa anterior)
            r.raise_for_status()
        arq = s.get(f"{API}/repos/{REPO}/contents/{YAML_REL}", params={"ref": "main"}, timeout=30)
        arq.raise_for_status()
        atual = base64.b64decode(arq.json()["content"]).decode("utf-8")
        novo = yaml_com_run_novo(atual, run_id, model_info if model_info is not None else _model_info(run_id))
        if novo == atual:
            return {"ok": False, "motivo": f"o run {run_id[:8]} já é o modelo ativo"}
        put = s.put(f"{API}/repos/{REPO}/contents/{YAML_REL}", json={
            "message": f"modelo: ativa o run {run_id[:8]} (retreino automático)",
            "content": base64.b64encode(novo.encode("utf-8")).decode("ascii"),
            "sha": arq.json()["sha"], "branch": ramo}, timeout=30)
        put.raise_for_status()
        corpo = (card + "\n\nPR aberta pelo job `retreino-mensal` (etapa 4 do treino contínuo). O gate do CI "
                 "julga o run de novo; o merge é a aprovação humana. As taxas de conversão em "
                 "business_config.py e configs/clients não foram tocadas: para o ajuste de recall, rodar "
                 f"`python -m src.train_pipeline --activate-run {run_id}` antes do merge.")
        pr = s.post(f"{API}/repos/{REPO}/pulls", json={"title": f"modelo: ativa o run {run_id[:8]} (retreino automático)",
                                                        "head": ramo, "base": "main", "body": corpo}, timeout=30)
        pr.raise_for_status()
        return {"ok": True, "url": pr.json().get("html_url"), "ramo": ramo}
    except Exception as e:
        return {"ok": False, "motivo": f"{type(e).__name__}: {str(e)[:200]}"}


def executar(run_id: str) -> Dict[str, Any]:
    """Julga, abre a PR se passou, e avisa no Slack em qualquer caso."""
    v = julgar_candidato(run_id)
    card = montar_card(v)
    pr = abrir_pr(v, card) if v["ok"] else None
    if pr and pr.get("ok"):
        rodape = f"PR: {pr['url']}"
    elif v["ok"]:
        rodape = f"PR não aberta: {pr['motivo']}. Na mão: bash V2/scripts/abrir_pr_modelo.sh {run_id}"
    else:
        rodape = "Sem PR: o run não passou na régua."
    slack = avisar_slack(card + "\n\n" + rodape)
    print(f"[pos-treino] {card}\n[pos-treino] {rodape}\n[pos-treino] slack ok={slack.get('ok')} {slack.get('error') or ''}")
    return {"veredito": v, "pr": pr, "slack": slack}
