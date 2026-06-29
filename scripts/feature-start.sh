#!/usr/bin/env bash
# Abre uma worktree nova para uma feature, SEMPRE a partir do origin/main atual.
# Resolve o bug recorrente de base velha (worktree nascendo de um HEAD local
# desatualizado quando outro terminal já avançou a main).
#
# Uso:  bash scripts/feature-start.sh <nome-da-feature>
set -euo pipefail

name="${1:-}"
if [ -z "$name" ]; then
  echo "uso: bash scripts/feature-start.sh <nome-da-feature>" >&2
  exit 1
fi

repo="/Users/ramonmoreira/Desktop/bring_data"
wt="$HOME/bring_data.worktrees/$name"

if [ -e "$wt" ]; then
  echo "Já existe uma worktree em: $wt" >&2
  exit 1
fi

echo "→ git fetch origin (garantindo base atual)…"
git -C "$repo" fetch origin

echo "→ criando worktree a partir de origin/main…"
git -C "$repo" worktree add "$wt" -b "feat/$name" origin/main

# .env (creds de DB) é gitignored — copiar para a worktree rodar ETLs/queries
if [ -f "$repo/V2/.env" ]; then
  cp "$repo/V2/.env" "$wt/V2/.env"
  echo "→ [.env copiado p/ creds de DB]"
fi

echo ""
echo "✅ Worktree pronta: $wt"
echo "   branch feat/$name  (base = origin/main atual)"
echo "   próximo:  cd $wt"
echo "   ao terminar:  bash scripts/feature-finish.sh   (push + PR)"
