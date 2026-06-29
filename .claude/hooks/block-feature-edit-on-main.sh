#!/usr/bin/env bash
# PreToolUse hook — bloqueia edição de CÓDIGO de feature (src/ e api/) quando o
# working tree do repo bring_data está na branch `main`. Força o uso de worktree.
#
# Exceções (continuam livres na main — são infra/trivial conforme V2/CLAUDE.md):
#   docs, configs, .claude/, scripts/, CLAUDE.md, qualquer coisa fora de src/api.
# Outros repositórios (ex.: empregabilidade) não são afetados.
#
# Saída: exit 2 = bloqueia a tool e devolve o stderr ao agente.

input=$(cat)
fp=$(printf '%s' "$input" | python3 -c "import sys,json
try:
    d=json.load(sys.stdin).get('tool_input',{})
    print(d.get('file_path') or d.get('notebook_path') or '')
except Exception:
    print('')" 2>/dev/null)

[ -z "$fp" ] && exit 0
dir=$(dirname "$fp"); [ -d "$dir" ] || dir="$PWD"

top=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || exit 0
# só o working tree PRINCIPAL do bring_data termina em /bring_data
case "$top" in */bring_data) ;; *) exit 0 ;; esac
[ "$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "main" ] || exit 0

rel="${fp#"$top"/}"
case "$rel" in
  V2/src/*|V2/api/*|src/*|api/*)
    echo "🚫 BLOQUEADO: '$rel' é código de feature e o working tree está na branch main." >&2
    echo "   Abra uma worktree antes de editar:  bash scripts/feature-start.sh <nome>" >&2
    echo "   (base sempre = origin/main; ao terminar: bash scripts/feature-finish.sh para push+PR)" >&2
    exit 2 ;;
esac
exit 0
