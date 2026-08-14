"""
core/git_info.py — Introspecção do repositório Git (versão do código).

Fonte única para "de qual commit este processo saiu". Usado pelo treino para
carimbar o commit no run do MLflow (lineage código→modelo, tornando o vínculo
automático em vez de escrito à mão no changelog) e pelo gerador do model card.

Fail-soft por design: em ambiente sem git (container, tarball, cópia sem .git)
todas as funções retornam None em vez de levantar — nunca derrubam o treino.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional

# Carimbo assado na imagem no momento do build. EXISTE PORQUE O CONTÊINER NÃO TEM GIT:
# o `.dockerignore` exclui `.git/` (corretamente — a pasta não serve pra nada em
# execução), então toda função deste módulo devolvia None em produção, que é justamente
# onde o carimbo faz falta.
#
# Descoberto em 14/08/2026 ao tentar registrar "de qual código saiu este teto": o job
# da referência rodava imagem de 31/07 enquanto a `main` dizia outra coisa, e só dava
# pra saber disso conferindo o digest da imagem à mão. Data não leva a commit quando o
# que roda não é a `main`.
_ENV_COMMIT = "APP_COMMIT"
_ENV_DIRTY = "APP_COMMIT_DIRTY"

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
    """SHA do HEAD atual (curto por padrão). None se não houver git NEM carimbo.

    A ordem é deliberada: git primeiro, carimbo depois. Onde há git (máquina de
    desenvolvimento, treino, worktree) ele é a verdade do instante; o carimbo é uma
    foto do build e ficaria velho assim que alguém commitasse por cima. Onde não há
    git (contêiner), o carimbo é a única resposta possível — e é melhor que None.
    """
    sha = _run_git(["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"])
    if sha:
        return sha
    assado = (os.environ.get(_ENV_COMMIT) or "").strip()
    if not assado:
        return None
    return assado[:7] if short else assado


def git_is_dirty() -> Optional[bool]:
    """True se há mudança de código commitável (tracked) não-commitada. None se
    não houver git NEM carimbo.

    Ignora untracked de propósito (mlruns/.env copiados na worktree de deploy são
    build artifacts, não código) — mesmo critério do check de árvore limpa do deploy.
    """
    out = _run_git(["status", "--porcelain", "--untracked-files=no"])
    if out is not None:
        return bool(out)
    assado = (os.environ.get(_ENV_DIRTY) or "").strip().lower()
    if assado in ("1", "true", "sim"):
        return True
    if assado in ("0", "false", "nao", "não"):
        return False
    return None


def versao_do_codigo() -> dict:
    """`{commit, dirty, origem}` — de qual código este processo saiu.

    `origem` diz COMO a resposta foi obtida, e isso importa: 'git' significa "lido do
    repositório agora"; 'imagem' significa "assado no build", que é o que vale em
    produção; 'desconhecida' significa que não há nem um nem outro, e aí quem gravar
    isso numa linha está gravando um buraco — melhor que ele apareça nomeado.
    """
    sha = _run_git(["rev-parse", "--short", "HEAD"])
    if sha:
        return {"commit": sha, "dirty": git_is_dirty(), "origem": "git"}
    assado = (os.environ.get(_ENV_COMMIT) or "").strip()
    if assado:
        return {"commit": assado[:7], "dirty": git_is_dirty(), "origem": "imagem"}
    return {"commit": None, "dirty": None, "origem": "desconhecida"}


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
