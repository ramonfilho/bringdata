#!/usr/bin/env bash
# Relatório de resultados de um LF (NEGÓCIO + MODELO) em UM comando.
#
# Envolve `src.validation.model_performance` resolvendo os 3 pré-requisitos que,
# esquecidos, quebram ou emudecem o relatório:
#   1. LAUNCHES_SOURCE=table  → sem isso o LF novo não é achado (o launches.yaml
#      local está congelado; o calendário vivo vem da planilha PC FORMULÁRIOS via
#      analytics.launch_calendar).
#   2. SLACK_BOT_TOKEN        → puxado do Secret Manager (não fica no .env).
#   3. SLACK_USER_DM          → o DM do Ramon (mesmo default do config.sh).
#
# Uso:
#   bash scripts/relatorio_lf.sh LF64                 # preview (NÃO posta)
#   bash scripts/relatorio_lf.sh LF64 --postar        # posta no DM
#   bash scripts/relatorio_lf.sh LF64 --postar --force  # ignora a trava de tráfego
#
# Quando rodar: depois que a janela de VENDAS do LF fechar e a coleta de vendas do
# dia seguinte tiver rodado (job diário 06:30 BRT). Vendas entram com 11-24h de
# atraso — rodar no mesmo dia do fim do carrinho subconta.
set -euo pipefail

LF="${1:-}"
if [ -z "$LF" ]; then
  echo "uso: bash scripts/relatorio_lf.sh <LF> [--postar] [--force]" >&2
  exit 1
fi
shift || true

POSTAR=false
EXTRA=()
for arg in "$@"; do
  case "$arg" in
    --postar) POSTAR=true ;;
    *) EXTRA+=("$arg") ;;
  esac
done

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export LAUNCHES_SOURCE=table
export SLACK_USER_DM="${SLACK_USER_DM:-D0A9USV3XEX}"
if [ -z "${SLACK_BOT_TOKEN:-}" ]; then
  export SLACK_BOT_TOKEN="$(gcloud secrets versions access latest \
    --secret=slack-bot-token --project=smart-ads-451319 2>/dev/null || true)"
fi

MODO="--slack-dry-run"
$POSTAR && MODO="--slack"
[ "$MODO" = "--slack" ] && [ -z "${SLACK_BOT_TOKEN:-}" ] && {
  echo "SLACK_BOT_TOKEN não veio do Secret Manager — rode 'gcloud auth login' ou exporte a env." >&2
  exit 1
}

echo "→ LF=$LF · modo=$MODO · calendário=tabela (planilha PC FORMULÁRIOS)"
PYTHONPATH=. python3 -u -m src.validation.model_performance \
  --lf "$LF" --include-open-cart "$MODO" ${EXTRA[@]+"${EXTRA[@]}"}
