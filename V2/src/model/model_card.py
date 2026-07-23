"""
src/model/model_card.py — Gerador automático do model card (entrada do MODEL_CHANGELOG).

Monta a entrada do changelog JÁ PREENCHIDA a partir do que o treino logou no run
do MLflow (run_id, commit do código, fingerprint dos dados, métricas, contagens),
em vez de digitação à mão. Só a linha de "decisão" (julgamento humano) fica opcional.

Camadas separadas de propósito (testabilidade + fonte única):
  - render_card(...)      → PURA: recebe os dados por injeção, devolve markdown.
                            Não toca MLflow nem disco — testável sem infra.
  - fetch_run_data(...)   → I/O MLflow: lê params/metrics/tags do run.
  - decide_status(...)    → lê o YAML de produção pra decidir CANDIDATO vs DEPLOYADO.
  - generate_card(...)    → orquestra os três + rascunha "mudanças desde o anterior".
  - append_to_changelog() → insere a entrada no topo do MODEL_CHANGELOG.md.

Uso (CLI fino em scripts/gen_model_card.py, ou via train_pipeline --model-card):
  from src.model.model_card import generate_card, append_to_changelog
  md = generate_card(run_id)      # string markdown pronta
  append_to_changelog(md)         # grava no topo do changelog
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# V2/ = raiz do cliente (este arquivo é V2/src/model/model_card.py)
_V2_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CHANGELOG = _V2_ROOT / "docs" / "MODEL_CHANGELOG.md"
DEFAULT_ACTIVE_YAML = _V2_ROOT / "configs" / "active_models" / "devclub.yaml"

# Hiperparâmetros do modelo que valem mostrar no card (se logados como param).
_HP_KEYS = ["n_estimators", "max_depth", "min_samples_split", "min_samples_leaf",
            "max_features", "class_weight", "random_state"]


# ---------------------------------------------------------------------------
# Formatação (PURA)
# ---------------------------------------------------------------------------

def _num(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pct(x) -> str:
    """Formata como porcentagem. Aceita fração (0.63) ou já-percentual (63.07)."""
    v = _num(x)
    if v is None:
        return "?"
    if v <= 1.5:      # heurística: <=1.5 é fração; acima já está em %
        v *= 100
    return f"{v:.2f}%"


def _f4(x) -> str:
    v = _num(x)
    return f"{v:.4f}" if v is not None else "?"


def _f2(x) -> str:
    v = _num(x)
    return f"{v:.2f}" if v is not None else "?"


def render_card(data: dict, *, status_label: str, decision: str,
                prev_run_id: Optional[str] = None,
                changes: Optional[List[str]] = None) -> str:
    """Monta o bloco markdown do card a partir do dict normalizado `data`.

    PURA: não faz I/O. `data` traz run_id, trained_at, model_name, git_commit,
    git_dirty, params (dict) e metrics (dict). `status_label` ∈ {CANDIDATO,
    DEPLOYADO, REJEITADO} vai no cabeçalho; `decision` é a frase da decisão.
    """
    p = data.get("params", {}) or {}
    m = data.get("metrics", {}) or {}
    run_id = data.get("run_id", "?")
    trained_at = data.get("trained_at") or "?"
    name = data.get("model_name") or f"RF {p.get('split_method', '')}".strip()

    commit = data.get("git_commit") or "unknown"
    dirty = data.get("git_dirty")
    commit_txt = f"`{commit}`" + (" ⚠️árvore suja" if dirty in (True, "true") else "")

    prev_txt = f"`{prev_run_id}`" if prev_run_id else "?"

    # Hiperparâmetros presentes
    hp = ", ".join(f"{k}={p[k]}" for k in _HP_KEYS if k in p) or "ver run"

    header = f"## {trained_at} — {name} — {status_label}"

    linha_dados = (
        f"- **Dados:** matched **{p.get('total_records', '?')}** leads, "
        f"**{p.get('total_positives', '?')}** compradores "
        f"({_pct(p.get('positive_rate'))} positivos), fingerprint `{p.get('dataset_fingerprint', '?')}`. "
        f"Split `{p.get('split_method', '?')}`, corte {p.get('cut_date', '?')}, "
        f"período {p.get('period_start', '?')}..{p.get('period_end', '?')} "
        f"(treino {p.get('train_records', '?')} / teste {p.get('test_records', '?')})."
    )

    linha_config = (
        f"- **Config:** {hp}. "
        f"buyer_weights={p.get('use_buyer_weights', '?')}, "
        f"tmb_risk_filter={p.get('tmb_risk_filter', '?')}, "
        f"matching={p.get('matching_method', '?')}, "
        f"features={p.get('total_features', '?')}."
    )

    linha_metricas = (
        f"- **Métricas (test):** AUC **{_f4(m.get('auc'))}** · "
        f"lift **{_f2(m.get('lift_maximum'))}** · "
        f"top-3 **{_pct(m.get('top3_decil_concentration'))}** · "
        f"top-5 {_pct(m.get('top5_decil_concentration'))} · "
        f"monotonia {_pct(m.get('monotonia_percentage'))} · "
        f"baseline {_pct(m.get('baseline_conversion_rate'))}."
    )

    if changes:
        _lst = "\n".join(f"  - {c}" for c in changes[:40])
        linha_changes = f"- **Mudanças de código desde o anterior (rascunho automático, curar):**\n{_lst}"
    elif changes == []:
        linha_changes = "- **Mudanças de código desde o anterior:** (nenhum commit entre os dois modelos)."
    else:
        linha_changes = "- **Mudanças de código desde o anterior:** _(commit do anterior desconhecido — ver `git log`)_"

    linhas = [
        header,
        "",
        f"- **run_id:** `{run_id}`  ·  **código:** {commit_txt}  ·  **modelo anterior:** {prev_txt}",
        linha_dados,
        linha_config,
        linha_metricas,
        "- **Δ vs anterior:** _(preencher: comparação exige rodar o modelo anterior no mesmo test set)_",
        linha_changes,
        f"- **Decisão:** {decision}",
    ]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# I/O — MLflow, YAML de produção, changelog
# ---------------------------------------------------------------------------

def fetch_run_data(run_id: str) -> dict:
    """Lê params/metrics/tags de um run do MLflow. Levanta se o run não existir."""
    import mlflow
    from src.core.mlflow_setup import ensure_tracking_uri
    ensure_tracking_uri()   # garante o backend certo mesmo em uso standalone (CLI)
    client = mlflow.tracking.MlflowClient()
    run = client.get_run(run_id)   # levanta MlflowException se inexistente
    params = dict(run.data.params)
    metrics = dict(run.data.metrics)
    tags = dict(run.data.tags)

    trained_at = None
    if run.info.start_time:
        trained_at = datetime.fromtimestamp(
            run.info.start_time / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%d")

    model_name = tags.get("mlflow.runName") or None

    return {
        "run_id": run_id,
        "trained_at": trained_at,
        "model_name": model_name,
        "git_commit": params.get("git_commit"),
        "git_dirty": params.get("git_dirty"),
        "params": params,
        "metrics": metrics,
        "tags": tags,
    }


def decide_status(run_id: str, active_yaml_path=None) -> tuple:
    """Decide (label, detalhe) comparando o run_id com o YAML de produção.

    Retorna ('DEPLOYADO', '<como está no ar>') se for o modelo ativo ou uma variante
    do A/B; ('CANDIDATO', ...) caso contrário. Fail-soft: YAML ilegível → CANDIDATO.
    """
    path = Path(active_yaml_path or DEFAULT_ACTIVE_YAML)
    try:
        import yaml
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return ("CANDIDATO", "não ativado (YAML de produção ilegível)")

    active = ((cfg.get("active_model") or {}).get("mlflow_run_id"))
    if active == run_id:
        return ("DEPLOYADO", "modelo ativo (default) em produção")

    variants = ((cfg.get("ab_test") or {}).get("variants") or {})
    for vname, v in variants.items():
        if (v or {}).get("run_id") == run_id:
            role = (v or {}).get("role", vname)
            return ("DEPLOYADO", f"variante do A/B em produção ({role})")

    return ("CANDIDATO", "registrado no MLflow, não ativado, produção intacta")


def _default_decision(status_label: str, detalhe: str) -> str:
    if status_label == "DEPLOYADO":
        return f"DEPLOYADO — {detalhe}."
    return (f"CANDIDATO — {detalhe}. Promover exige o "
            "[`PROMOCAO_MODELO_CHECKLIST.md`](PROMOCAO_MODELO_CHECKLIST.md) + deploy com canário.")


_ENTRY_HEADER_RE = re.compile(r"^## (\d{4})-(\d{2})-(\d{2}) ", re.MULTILINE)


def read_prev_entry(changelog_path=None) -> Optional[dict]:
    """Lê a entrada datada mais recente do changelog e extrai run_id + commit dela.
    None se o arquivo não existir ou não houver entrada datada."""
    path = Path(changelog_path or DEFAULT_CHANGELOG)
    try:
        text = path.read_text()
    except Exception:
        return None
    mh = _ENTRY_HEADER_RE.search(text)
    if not mh:
        return None
    # Corpo até o próximo header datado (ou fim)
    start = mh.start()
    nxt = _ENTRY_HEADER_RE.search(text, mh.end())
    body = text[start: nxt.start() if nxt else len(text)]
    run_id = None
    commit = None
    mr = re.search(r"\*\*run_id:\*\*\s*`([^`]+)`", body)
    if mr:
        run_id = mr.group(1)
    mc = re.search(r"\*\*c[oó]digo:\*\*\s*`([^`]+)`", body)
    if mc:
        commit = mc.group(1)
    return {"run_id": run_id, "git_commit": commit}


def generate_card(run_id: str, *, decision: Optional[str] = None, name: Optional[str] = None,
                  changelog_path=None, active_yaml_path=None,
                  changes: Optional[List[str]] = None) -> str:
    """Orquestra: lê o run, decide status, rascunha mudanças e devolve o markdown."""
    data = fetch_run_data(run_id)
    if name:
        data["model_name"] = name

    status_label, detalhe = decide_status(run_id, active_yaml_path)
    if decision is None:
        decision = _default_decision(status_label, detalhe)

    prev = read_prev_entry(changelog_path)
    prev_run_id = prev.get("run_id") if prev else None

    if changes is None and prev and prev.get("git_commit"):
        from src.core.git_info import git_log_between
        changes = git_log_between(prev["git_commit"], data.get("git_commit") or "HEAD")

    return render_card(data, status_label=status_label, decision=decision,
                       prev_run_id=prev_run_id, changes=changes)


def append_to_changelog(md_block: str, changelog_path=None) -> Path:
    """Insere o bloco no topo (entrada mais recente primeiro), antes da primeira
    entrada datada existente. Devolve o caminho gravado."""
    path = Path(changelog_path or DEFAULT_CHANGELOG)
    text = path.read_text()
    bloco = md_block.rstrip() + "\n\n---\n\n"
    mh = _ENTRY_HEADER_RE.search(text)
    if mh:
        novo = text[:mh.start()] + bloco + text[mh.start():]
    else:
        novo = text.rstrip() + "\n\n---\n\n" + md_block.rstrip() + "\n"
    path.write_text(novo)
    return path
