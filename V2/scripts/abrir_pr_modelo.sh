#!/usr/bin/env bash
# abrir_pr_modelo.sh <run_id>: transforma um run do MLflow numa PR de promoção.
#
# O modelo entra em produção pela MESMA porta que o código: uma PR na main. Este script
# faz a parte mecânica, em cima dos helpers que já existem:
#   1. abre uma worktree a partir de origin/main (scripts/feature-start.sh);
#   2. roda `train_pipeline --activate-run <run_id>`, que reescreve o bloco active_model
#      do YAML de produção (preservando o A/B), o api/business_config.py e o
#      configs/clients/devclub.yaml (taxas de conversão por decil, com PAV);
#   3. gera o model card do run e o insere no topo do docs/MODEL_CHANGELOG.md
#      (scripts/gen_model_card.py --append), no mesmo commit;
#   4. commita os quatro arquivos, faz push e abre a PR com o card no corpo
#      (scripts/feature-finish.sh).
#
# Na PR, o CI roda a suíte e o gate do modelo (scripts/ci_check_active_model.py): run
# FINISHED, artefatos no bucket, pisos de AUC/monotonia, lineage (git_commit, árvore
# limpa) e, se for champion, delta contra o anterior. O merge cozinha os artefatos na
# imagem (deploy.yml). Promover a 100% continua passando pelo canary e pela aprovação.
#
# Uso:  bash V2/scripts/abrir_pr_modelo.sh b085b63681bc4d0d90bdbd466106763a
# Precisa de: V2/.env com MLFLOW_TRACKING_URI (o feature-start copia), gh autenticado.
set -euo pipefail
RUN="${1:?uso: bash V2/scripts/abrir_pr_modelo.sh <run_id>}"
[[ "$RUN" =~ ^[0-9a-f]{32}$ ]] || { echo "run_id inválido (esperado: 32 hex): $RUN" >&2; exit 2; }
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NOME="modelo-${RUN:0:8}"
WT="$HOME/bring_data.worktrees/$NOME"

echo "→ worktree $NOME a partir de origin/main"
bash "$RAIZ/scripts/feature-start.sh" "$NOME" >/dev/null

cd "$WT/V2"
echo "→ ativando o run no YAML de produção (bloco active_model; A/B preservado)"
python -m src.train_pipeline --activate-run "$RUN"
echo "→ model card no topo do MODEL_CHANGELOG.md"
python scripts/gen_model_card.py "$RUN" --append

cd "$WT"
git add V2/configs/active_models V2/configs/clients V2/api/business_config.py V2/docs/MODEL_CHANGELOG.md
if git diff --cached --quiet; then
  echo "nada mudou: o run $RUN já é o modelo ativo?" >&2; exit 1
fi
CARD="$(python3 - "$WT/V2/docs/MODEL_CHANGELOG.md" <<'PY'
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"^## .*?(?=^## |\Z)", t, re.S | re.M)   # primeira entrada (a mais nova)
print((m.group(0) if m else "").strip()[:6000])
PY
)"
git commit -q -m "modelo: ativa o run ${RUN:0:8} (PR de promoção)" -m "$CARD"
echo "→ push + PR"
bash "$RAIZ/scripts/feature-finish.sh"
