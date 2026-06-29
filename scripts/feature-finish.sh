#!/usr/bin/env bash
# Fecha a feature: push da branch atual + abre PR contra main.
# Roda de DENTRO da worktree da feature.
#
# Uso:  bash scripts/feature-finish.sh
set -euo pipefail

wt="$(git rev-parse --show-toplevel)"
branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD)"

if [ "$branch" = "main" ]; then
  echo "Você está na main — feature-finish roda DENTRO da worktree da feature." >&2
  exit 1
fi

echo "→ push origin $branch…"
git -C "$wt" push -u origin "$branch"

echo "→ abrindo PR contra main…"
gh pr create --repo ramonfilho/bringdata --base main --head "$branch" --fill

echo ""
echo "✅ PR aberto para $branch."
