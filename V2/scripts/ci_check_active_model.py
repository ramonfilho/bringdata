#!/usr/bin/env python3
"""
Gate do modelo no CI: julga o run que a PR TROCA no YAML de produção.

Compara configs/active_models/<cliente>.yaml entre a base (origin/main) e o HEAD e,
para cada run_id que ENTRA (champion trocado, variante do A/B nova ou trocada), confere:

  1. o run existe no MLflow e está FINISHED;
  2. os três arquivos que o deploy exige estão no bucket
     (model/MLmodel, model_metadata.json, feature_registry.json);
  3. métricas do run acima dos pisos de configs/retreino_mensal.yaml
     (comparison.min_auc, comparison.min_monotonia);
  4. lineage: `git_commit` gravado no run e `git_dirty` diferente de "true"
     (o modelo tem que ser reproduzível a partir do git);
  5. se o CHAMPION foi trocado: delta de AUC contra o champion anterior >=
     comparison.manual_approval_threshold (abaixo disso a política do retreino diz
     "manter champion"). >= auto_approve_threshold vira nota "auto"; entre os dois,
     "manual", e a revisão da PR é a aprovação manual.

Runs que já estavam no YAML não são rejulgados: a régua vale para quem entra. (O
champion de hoje, abr28, tem monotonia 77,8% no run e não passaria no piso de 80%;
ele não é candidato, é o incumbente.)

Fonte das métricas: o run no servidor de tracking, o mesmo de onde o model card
(src/model/model_card.py) lê. Não o YAML, que carregava números digitados à mão.

Uso:
  python3 V2/scripts/ci_check_active_model.py --base-ref origin/main
  python3 V2/scripts/ci_check_active_model.py --base-file antes.yaml --head-file depois.yaml

Saída: exit 0 aprovado ou nada a julgar; 1 reprovado; 2 erro de infra (MLflow, bucket).

MLFLOW_TRACKING_URI: do ambiente ou do V2/.env (src/core/mlflow_setup). No runner do
CI, sem .env, a URI é montada a partir do Secret Manager (mlflow-db-password) e do host
MLFLOW_DB_HOST (default: o Cloud SQL do projeto).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

_V2 = Path(__file__).resolve().parents[1]
BUCKET = os.environ.get("MLFLOW_ARTIFACTS_BUCKET", "gs://smart-ads-mlflow/artifacts")
PROJETO = os.environ.get("PROJECT_ID", "smart-ads-451319")
ARQUIVOS_DO_DEPLOY = ("model/MLmodel", "model_metadata.json", "feature_registry.json")


# ----------------------------------------------------------------- parte pura
def runs_do_yaml(cfg: dict) -> Dict[str, str]:
    """{papel: run_id}. Papel é 'champion' ou 'variante:<nome>'."""
    out: Dict[str, str] = {}
    rid = ((cfg or {}).get("active_model") or {}).get("mlflow_run_id")
    if rid:
        out["champion"] = str(rid)
    ab = (cfg or {}).get("ab_test") or {}
    if ab.get("enabled"):
        for nome, v in (ab.get("variants") or {}).items():
            if (v or {}).get("run_id"):
                out[f"variante:{nome}"] = str(v["run_id"])
    return out


def runs_que_entram(base: dict, head: dict) -> List[Tuple[str, str, Optional[str]]]:
    """[(papel, run_novo, run_anterior_no_mesmo_papel)] só para o que mudou ou nasceu."""
    a, b = runs_do_yaml(base), runs_do_yaml(head)
    return [(papel, rid, a.get(papel)) for papel, rid in b.items() if a.get(papel) != rid]


def julgar(papel: str, metricas: Dict[str, float], params: Dict[str, Any], status: str,
           artefatos_ok: bool, limiares: Dict[str, float],
           metricas_anterior: Optional[Dict[str, float]] = None) -> Tuple[bool, List[str], str]:
    """Aplica a régua a UM run. Devolve (aprovado, motivos, nota)."""
    motivos: List[str] = []
    nota = "ok"
    if status != "FINISHED":
        motivos.append(f"run não está FINISHED (status={status})")
    if not artefatos_ok:
        motivos.append("faltam artefatos no bucket: " + ", ".join(ARQUIVOS_DO_DEPLOY))
    auc = metricas.get("auc")
    mono = metricas.get("monotonia_percentage")
    if auc is None or mono is None:
        motivos.append("run sem as métricas auc/monotonia_percentage")
    else:
        if auc < limiares["min_auc"]:
            motivos.append(f"AUC {auc:.4f} abaixo do piso {limiares['min_auc']:.2f}")
        if mono / 100.0 < limiares["min_monotonia"]:
            motivos.append(f"monotonia {mono:.1f}% abaixo do piso {limiares['min_monotonia'] * 100:.0f}%")
    if not params.get("git_commit"):
        motivos.append("run sem git_commit (treinado sem o carimbo de lineage)")
    if str(params.get("git_dirty", "")).lower() == "true":
        motivos.append("run treinado de árvore suja (git_dirty=true): não é reproduzível a partir do git")
    if papel == "champion" and auc is not None:
        if metricas_anterior and metricas_anterior.get("auc") is not None:
            delta = auc - float(metricas_anterior["auc"])
            if delta < limiares["manual_approval_threshold"]:
                motivos.append(
                    f"delta de AUC {delta:+.4f} vs champion anterior abaixo de "
                    f"{limiares['manual_approval_threshold']:+.3f}: política diz manter champion")
            elif delta >= limiares["auto_approve_threshold"]:
                nota = f"auto (delta AUC {delta:+.4f})"
            else:
                nota = f"manual (delta AUC {delta:+.4f}); a revisão da PR é a aprovação"
        else:
            nota = "sem champion anterior com métricas: só os pisos valem"
    return (not motivos), motivos, nota


def limiares_de(retreino_cfg: dict) -> Dict[str, float]:
    c = (retreino_cfg or {}).get("comparison") or {}
    return {
        "min_auc": float(c.get("min_auc", 0.65)),
        "min_monotonia": float(c.get("min_monotonia", 0.80)),
        "manual_approval_threshold": float(c.get("manual_approval_threshold", 0.005)),
        "auto_approve_threshold": float(c.get("auto_approve_threshold", 0.02)),
    }


# ----------------------------------------------------------------- I/O
def yaml_no_ref(ref: str, caminho_rel: str) -> dict:
    """Conteúdo do arquivo em um ref do git (raiz do repositório = pai de V2)."""
    raiz = _V2.parent
    r = subprocess.run(["git", "-C", str(raiz), "show", f"{ref}:{caminho_rel}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    return yaml.safe_load(r.stdout) or {}


def _uri_mlflow() -> str:
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if uri:
        return uri
    try:
        from dotenv import load_dotenv
        load_dotenv(_V2 / ".env")
        uri = os.environ.get("MLFLOW_TRACKING_URI")
        if uri:
            return uri
    except ImportError:
        pass
    host = os.environ.get("MLFLOW_DB_HOST", "104.197.138.129")
    r = subprocess.run(["gcloud", "secrets", "versions", "access", "latest",
                        "--secret=mlflow-db-password", f"--project={PROJETO}"],
                       capture_output=True, text=True)
    senha = r.stdout.strip()
    if r.returncode != 0 or not senha:
        raise RuntimeError("sem MLFLOW_TRACKING_URI e o Secret Manager não devolveu mlflow-db-password")
    return f"postgresql+psycopg2://postgres:{senha}@{host}:5432/mlflow?sslmode=require"


def ler_run(run_id: str) -> Tuple[str, Dict[str, float], Dict[str, Any]]:
    import mlflow
    mlflow.set_tracking_uri(_uri_mlflow())
    run = mlflow.tracking.MlflowClient().get_run(run_id)
    return run.info.status, dict(run.data.metrics), dict(run.data.params)


def artefatos_no_bucket(run_id: str) -> bool:
    r = subprocess.run(["gcloud", "storage", "ls", "-r", f"{BUCKET}/{run_id}/artifacts/**",
                        f"--project={PROJETO}"], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    listados = r.stdout
    return all(f"{BUCKET}/{run_id}/artifacts/{a}" in listados for a in ARQUIVOS_DO_DEPLOY)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", default="devclub")
    ap.add_argument("--base-ref", default=None, help="ref do git com o YAML ANTES (ex: origin/main)")
    ap.add_argument("--base-file", default=None, help="arquivo com o YAML ANTES (alternativa ao ref)")
    ap.add_argument("--head-file", default=None, help="arquivo com o YAML DEPOIS (default: o do checkout)")
    args = ap.parse_args()

    rel = f"V2/configs/active_models/{args.client}.yaml"
    if args.base_file:
        base = yaml.safe_load(Path(args.base_file).read_text()) or {}
    elif args.base_ref:
        base = yaml_no_ref(args.base_ref, rel)
    else:
        print("informe --base-ref ou --base-file", file=sys.stderr)
        return 2
    head_path = Path(args.head_file) if args.head_file else (_V2 / "configs" / "active_models" / f"{args.client}.yaml")
    head = yaml.safe_load(head_path.read_text()) or {}

    entram = runs_que_entram(base, head)
    if not entram:
        print("gate do modelo: nenhum run novo no YAML de produção; nada a julgar.")
        return 0

    limiares = limiares_de(yaml.safe_load((_V2 / "configs" / "retreino_mensal.yaml").read_text()) or {})
    reprovou = False
    for papel, rid, anterior in entram:
        try:
            status, metricas, params = ler_run(rid)
            artefatos = artefatos_no_bucket(rid)
            m_ant = None
            if anterior:
                try:
                    m_ant = ler_run(anterior)[1]
                except Exception as e:  # incumbente sem run legível não bloqueia o candidato
                    print(f"  aviso: não li o run anterior {anterior[:8]} ({type(e).__name__}); delta não avaliado")
        except Exception as e:
            print(f"ERRO de infra ao ler o run {rid[:8]} ({papel}): {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return 2
        ok, motivos, nota = julgar(papel, metricas, params, status, artefatos, limiares, m_ant)
        print(f"[{papel}] run {rid[:8]}: AUC {metricas.get('auc', float('nan')):.4f} | "
              f"monotonia {metricas.get('monotonia_percentage', float('nan')):.1f}% | "
              f"lift {metricas.get('lift_maximum', float('nan')):.2f} | commit {params.get('git_commit') or '-'}"
              f"{' (sujo)' if str(params.get('git_dirty', '')).lower() == 'true' else ''} -> "
              f"{'APROVADO' if ok else 'REPROVADO'} [{nota}]")
        for mtv in motivos:
            print(f"    - {mtv}")
        reprovou |= not ok
    return 1 if reprovou else 0


if __name__ == "__main__":
    sys.exit(main())
