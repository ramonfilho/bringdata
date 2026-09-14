#!/usr/bin/env bash
# baixar_artefatos_modelo.sh: garante em V2/mlruns/1/<run_id>/artifacts/ os artefatos de
# TODOS os runs que o YAML de produção declara (champion + variantes do A/B), baixando do
# bucket do MLflow quando não estão no disco.
#
# Por que existe: o build da imagem (deploy_capi.sh, stage_model_artifacts) e o teste
# `test_medium_artifacts.py` liam só o V2/mlruns LOCAL, que existe num Mac e em nenhum
# runner. O bucket `gs://smart-ads-mlflow/artifacts/<run_id>/artifacts/` é onde o MLflow
# grava (artifact_uri do run), então ele é a fonte; o disco é cache. Cada run tem ~9 MB.
#
# Idempotente: run já presente (model/ + model_metadata.json + feature_registry.json) não
# é baixado de novo.
# Uso:  bash V2/scripts/baixar_artefatos_modelo.sh            (cliente devclub)
#       CLIENT_ID=outro bash V2/scripts/baixar_artefatos_modelo.sh
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENTE="${CLIENT_ID:-devclub}"
YAML="$RAIZ/configs/active_models/$CLIENTE.yaml"
BUCKET="${MLFLOW_ARTIFACTS_BUCKET:-gs://smart-ads-mlflow/artifacts}"
PROJETO="${PROJECT_ID:-smart-ads-451319}"
[ -f "$YAML" ] || { echo "YAML de produção não encontrado: $YAML" >&2; exit 1; }

runs=$(python3 - "$YAML" <<'PY'
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1])) or {}
ids = [(cfg.get('active_model') or {}).get('mlflow_run_id')]
ab = cfg.get('ab_test') or {}
if ab.get('enabled'):
    ids += [v.get('run_id') for v in (ab.get('variants') or {}).values()]
print('\n'.join(sorted({i for i in ids if i})))
PY
)
[ -n "$runs" ] || { echo "nenhum run_id no $YAML" >&2; exit 1; }

for r in $runs; do
  dest="$RAIZ/mlruns/1/$r/artifacts"
  if [ -d "$dest/model" ] && [ -f "$dest/model_metadata.json" ] && [ -f "$dest/feature_registry.json" ]; then
    echo "ok (disco)  $r"; continue
  fi
  mkdir -p "$dest"
  gcloud storage cp -r "$BUCKET/$r/artifacts/*" "$dest/" --project="$PROJETO" >/dev/null
  for f in model/MLmodel model_metadata.json feature_registry.json; do
    [ -e "$dest/$f" ] || { echo "run $r: faltou $f depois do download de $BUCKET/$r/artifacts/" >&2; exit 1; }
  done
  echo "ok (bucket) $r"
done
