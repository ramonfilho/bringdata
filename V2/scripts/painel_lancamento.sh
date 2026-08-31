#!/usr/bin/env bash
# O PAINEL do lançamento em UM botão: contrato + comparativo + HTML.
#
# Envolve relatorio_lancamento.py + comparativo_lancamentos.py +
# render_painel_lancamento.py com os pré-requisitos que, esquecidos, quebram:
#   1. LAUNCHES_SOURCE=table → o LF novo mora em analytics.launch_calendar
#      (planilha PC FORMULÁRIOS via job 05:30), não no launches.yaml congelado.
#   2. A MESMA pasta nos três passos (docs/relatorios/<lf>_resultado).
#
# Uso:
#   bash scripts/painel_lancamento.sh LF65                # rodada normal
#   bash scripts/painel_lancamento.sh LF65 --sem-etl      # sem puxar vendas antes
#   (qualquer flag extra vai direto pro relatorio_lancamento.py)
#
# Nota do Ramon (31/08): emitir um relatório também ATUALIZA O ANTERIOR quando
# o carrinho dele já fechou e o contrato ficou pra trás (vendas finais). O
# bloco no fim faz isso; PAINEL_SEM_ANTERIOR=1 evita a recursão em cadeia.
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
python3 scripts/comparativo_lancamentos.py "$LF" || echo "⚠ comparativo falhou — painel sai sem a seção"
python3 scripts/render_painel_lancamento.py "$OUT"
echo "✓ painel do $LF em $OUT"

# ── atualiza o lançamento ANTERIOR se o carrinho dele fechou e o contrato é velho
if [ -z "${PAINEL_SEM_ANTERIOR:-}" ]; then
  ANT="$(python3 - "$LF" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from src.core.launches import load_launches

alvo = sys.argv[1]
ls = load_launches()
cs = str((ls.get(alvo) or {}).get("cap_start"))[:10]
ant = None
for lf, c in ls.items():
    ce = str(c.get("cap_end"))[:10]
    if lf != alvo and ce and ce != "None" and cs and ce < cs \
            and (ant is None or ce > ant[1]):
        ant = (lf, ce, str(c.get("vendas_end"))[:10])
if not ant:
    raise SystemExit(0)
lf_a, _, vend_a = ant
p = Path(f"docs/relatorios/{lf_a.lower()}_resultado/contrato.json")
if not p.exists() or not vend_a or vend_a == "None":
    raise SystemExit(0)
gerado = json.loads(p.read_text())["meta"]["gerado_em"][:10]
hoje = datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
# defasado = contrato gerado ATÉ o dia do fim do carrinho (vendas ainda caindo)
# e o carrinho já fechou: uma re-rodada pega as vendas finais.
if hoje > vend_a and gerado <= vend_a:
    print(lf_a)
PY
)"
  if [ -n "$ANT" ]; then
    echo "→ atualizando o anterior ($ANT): carrinho fechado, contrato defasado"
    PAINEL_SEM_ANTERIOR=1 bash scripts/painel_lancamento.sh "$ANT"
  fi
fi
