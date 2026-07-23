"""
core/git_info.py — Introspecção do repositório Git (versão do código).

Fonte única para "de qual commit este processo saiu". Usado pelo treino para
carimbar o commit no run do MLflow (lineage código→modelo, tornando o vínculo
automático em vez de escrito à mão no changelog) e pelo gerador do model card.

Fail-soft por design: em ambiente sem git (container, tarball, cópia sem .git)
todas as funções retornam None em vez de levantar — nunca derrubam o treino.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

# Rodar os comandos a partir do diretório deste arquivo garante que, quando o
# treino é importado de uma worktree, o commit lido é o da worktree (o código
# que realmente produziu o modelo), não o do working tree principal.
_REPO_DIR = str(Path(__file__).resolve().parent)


def _run_git(args: List[str]) -> Optional[str]:
    """Executa `git <args>` no repo e devolve o stdout strip. None em qualquer erro."""
    try:
        return subprocess.check_output(
            ["git", *args], cwd=_REPO_DIR, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def git_commit(short: bool = True) -> Optional[str]:
    """SHA do HEAD atual (curto por padrão). None se git indisponível."""
    return _run_git(["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"])


def git_is_dirty() -> Optional[bool]:
    """True se há mudança de código commitável (tracked) não-commitada. None se git indisponível.

    Ignora untracked de propósito (mlruns/.env copiados na worktree de deploy são
    build artifacts, não código) — mesmo critério do check_clean_tree do deploy_capi.sh.
    """
    out = _run_git(["status", "--porcelain", "--untracked-files=no"])
    if out is None:
        return None
    return bool(out)


def git_log_between(since: str, until: str = "HEAD", no_merges: bool = True) -> Optional[List[str]]:
    """Lista `git log --oneline since..until` (mais recente primeiro). None se git falhar
    ou os refs não existirem. Usada pelo model card pra rascunhar 'mudanças desde o
    modelo anterior' automaticamente (a curadoria do que é relevante fica com o humano)."""
    args = ["log", "--oneline", "--no-decorate"]
    if no_merges:
        args.append("--no-merges")
    args.append(f"{since}..{until}")
    out = _run_git(args)
    if out is None or out == "":
        return [] if out == "" else None
    return out.splitlines()
