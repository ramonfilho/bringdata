#!/usr/bin/env bash
# worktree-janitor.sh — poda worktrees e branches de feature cujo trabalho JÁ está
# na main, mantendo a main como fonte única de execução do projeto.
#
# NUNCA toca produção (Cloud Run / Cloud SQL / schedulers / dados). NUNCA apaga
# `main` (local ou remoto). NUNCA força: na menor dúvida, POUPA e reporta.
#
# Uma sala (worktree) / branch só é auto-fechável se TODAS valerem:
#   (1) o trabalho está na main, comprovado por UMA via:
#         a) o tip do branch é ancestral de origin/main, ou
#         b) `git cherry origin/main <branch>` sem nenhuma linha '+' (patch já na main), ou
#         c) existe PR MERGEADO desse branch (gh — pega squash-merge);
#   (2) [worktree] working tree 100% limpo (nada não-commitado nem não-rastreado);
#   (3) não é `main`, nem a worktree/branch ATUAL de onde o script roda.
# Sala com trabalho não salvo, ou branch não comprovado na main, é POUPADA.
#
# Uso:
#   bash scripts/worktree-janitor.sh                 # DRY-RUN (default) — só mostra o que faria
#   bash scripts/worktree-janitor.sh --apply         # remove worktrees + branches LOCAIS seguros
#   bash scripts/worktree-janitor.sh --apply --prune-remote  # + apaga branch REMOTO (só se PR mergeado)
#   bash scripts/worktree-janitor.sh --stale-days=N  # idade mínima s/ commit p/ considerar (default 14)
set -euo pipefail

APPLY=0 ; PRUNE_REMOTE=0 ; STALE_DAYS=14
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --prune-remote) PRUNE_REMOTE=1 ;;
    --stale-days=*) STALE_DAYS="${a#*=}" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "flag desconhecida: $a (use -h)" >&2; exit 2 ;;
  esac
done

REPO="/Users/ramonmoreira/Desktop/bring_data"
GH_REPO="ramonfilho/bringdata"
MAIN="origin/main"
CUR_TOP="$(git rev-parse --show-toplevel 2>/dev/null || echo '')"

git -C "$REPO" fetch origin main --quiet 2>/dev/null || true
now=$(date +%s) ; cutoff=$((now - STALE_DAYS*86400))
mode="DRY-RUN — nada será alterado (use --apply)"; [ "$APPLY" = 1 ] && mode="APPLY — removendo de verdade"
echo "════ worktree-janitor — $mode | stale ≥ ${STALE_DAYS}d ════"

# Pré-carrega os head-branches de PRs MERGEADOS numa única chamada gh → checagem local.
MERGED_HEADS=""
if command -v gh >/dev/null 2>&1; then
  MERGED_HEADS=$(gh pr list --repo "$GH_REPO" --state merged --limit 500 --json headRefName --jq '.[].headRefName' 2>/dev/null || echo '')
fi
pr_merged() { [ -n "$MERGED_HEADS" ] && grep -qxF "$1" <<<"$MERGED_HEADS"; }

# work_in_main <branch> → 0 se o trabalho já está na main (local primeiro, rede por último)
work_in_main() {
  local br="$1" plus
  git -C "$REPO" merge-base --is-ancestor "$br" "$MAIN" 2>/dev/null && return 0        # a) ancestral
  plus=$(git -C "$REPO" cherry "$MAIN" "$br" 2>/dev/null | grep -c '^+' || true)       # b) patch-equivalente
  [ "${plus:-1}" = 0 ] && return 0
  pr_merged "$br" && return 0                                                          # c) PR mergeado (squash)
  return 1
}

# ───────────────────────── PASSO 1: worktrees ─────────────────────────
echo; echo "── Worktrees ──"
while IFS= read -r line; do
  p=$(awk '{print $1}' <<<"$line")
  br=$(sed -n 's/.*\[\(.*\)\].*/\1/p' <<<"$line")
  [ "$p" = "$REPO" ] && continue                                   # nunca a main
  if [ "$p" = "$CUR_TOP" ]; then echo "  ⏭️  $(basename "$p") — worktree ATUAL (não se auto-remove)"; continue; fi
  [ -z "$br" ] && { echo "  ⏸️  $(basename "$p") — detached HEAD → POUPA"; continue; }
  ct=$(git -C "$p" show -s --format=%ct HEAD 2>/dev/null || echo "$now")
  [ "$ct" -ge "$cutoff" ] && { echo "  ⏭️  $(basename "$p") [$br] — ativa (<${STALE_DAYS}d) → poupa"; continue; }
  if [ -n "$(git -C "$p" status --porcelain 2>/dev/null | head -1)" ]; then
    echo "  ⚠️  $(basename "$p") [$br] — TEM não-commitado → POUPA (resgate manual)"; continue
  fi
  if work_in_main "$br"; then
    if [ "$APPLY" = 1 ]; then
      git -C "$REPO" worktree remove "$p" 2>/dev/null && echo "  ✅ removida: $(basename "$p") [$br]" || echo "  ❌ falhou: $(basename "$p")"
    else
      echo "  🧹 FECHARIA: $(basename "$p") [$br] — trabalho na main + limpa"
    fi
  else
    echo "  ⚠️  $(basename "$p") [$br] — commits FORA da main → POUPA (revisar/PR)"
  fi
done < <(git -C "$REPO" worktree list)

# ───────────────────────── PASSO 2: branches locais órfãos ─────────────────────────
echo; echo "── Branches locais sem worktree (trabalho na main) ──"
wt_branches=$(git -C "$REPO" worktree list | sed -n 's/.*\[\(.*\)\].*/\1/p')
while IFS= read -r br; do
  [ "$br" = "main" ] && continue                                  # nunca a main
  grep -qxF "$br" <<<"$wt_branches" && continue                   # tem worktree → passo 1
  if work_in_main "$br"; then
    if [ "$APPLY" = 1 ]; then
      git -C "$REPO" branch -D "$br" >/dev/null 2>&1 && echo "  ✅ local podado: $br" || echo "  ❌ local: $br"
      if [ "$PRUNE_REMOTE" = 1 ] && pr_merged "$br"; then
        git -C "$REPO" push origin --delete "$br" >/dev/null 2>&1 && echo "     ↳ remoto apagado: origin/$br (PR mergeado)"
      fi
    else
      extra=""; { [ "$PRUNE_REMOTE" = 1 ] && pr_merged "$br"; } && extra=" (+ remoto: PR mergeado)"
      echo "  🧹 PODARIA local: $br$extra"
    fi
  else
    echo "  ⏸️  $br — não comprovado na main → POUPA"
  fi
done < <(git -C "$REPO" for-each-ref --format='%(refname:short)' refs/heads/)

echo
[ "$APPLY" = 1 ] && echo "✔ concluído." || echo "ℹ️  DRY-RUN: nada mudou. Rode --apply (e --prune-remote p/ remotos) quando aprovar."
