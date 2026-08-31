#!/usr/bin/env bash
# O PAINEL do lançamento em UM botão: gera o contrato e renderiza o HTML.
#
# Envolve o par relatorio_lancamento.py + render_painel_lancamento.py com os
# pré-requisitos que, esquecidos, quebram a rodada:
#   1. LAUNCHES_SOURCE=table → o LF novo mora em analytics.launch_calendar
#      (planilha PC FORMULÁRIOS via job 05:30), não no launches.yaml congelado.
#   2. A MESMA pasta nos dois passos (docs/relatorios/<lf>_resultado).
#
# Uso:
#   bash scripts/painel_lancamento.sh LF65                # rodada normal
#   bash scripts/painel_lancamento.sh LF65 --sem-etl      # sem puxar vendas antes
#   (qualquer flag extra vai direto pro relatorio_lancamento.py)
#
# Re-rodar quando as vendas caírem é apertar o MESMO botão: o contrato é
# reescrito e o painel re-renderizado; o único delta legítimo é a receita.
#
# ATENÇÃO à saída do primeiro passo: a linha "ids não resolvidos" é a cobertura
# do mapa de criativos. Se ela crescer num LF novo, o criativo_id_map precisa
# de manutenção ANTES de publicar o painel.
set -euo pipefail

LF="${1:-}"
if [ -z "$LF" ]; then
  echo "uso: bash scripts/painel_lancamento.sh <LF> [flags do relatorio_lancamento.py]" >&2
  exit 1
fi
shift || true

cd "$(dirname "${BASH_SOURCE[0]}")/.."
export LAUNCHES_SOURCE=table

OUT="docs/relatorios/$(echo "$LF" | tr '[:upper:]' '[:lower:]')_resultado"
python3 scripts/relatorio_lancamento.py --lf "$LF" --out "$OUT" "$@"
python3 scripts/render_painel_lancamento.py "$OUT"
echo "✓ painel do $LF em $OUT"
