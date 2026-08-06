#!/usr/bin/env bash
# sync_espelhos_cron.sh (era sync_monitoring_cron.sh): rede de segurança do gate.
#
# ESTE ARQUIVO É A FONTE. Ele roda a partir do GCS
# (gs://smart-ads-mlflow/deploy-gate/sync_monitoring_cron.sh), e até 06/08/2026
# existia SÓ lá: não estava versionado em lugar nenhum, então mudança nele não tinha
# revisão, histórico nem como voltar atrás. Ao editar aqui, publicar com:
#   gsutil cp V2/api/lib/sync_espelhos_cron.sh \
#     gs://smart-ads-mlflow/deploy-gate/sync_monitoring_cron.sh
#
# rede de segurança do deploy-gate. Roda no Cloud Run Job
# (imagem cloud-sdk) 1x/dia. Se o monitoring estiver numa imagem DIFERENTE do scorer
# (drift, ex.: alguém deployou o scorer por fora do gate), alinha o monitoring à
# imagem VIVA do scorer com segurança: cria revisão -> roteia -> verifica Ready ->
# rollback se não subir. Se estiverem iguais, não faz nada.
#
# NUNCA mexe em IAM/allUsers (a SA só tem run.developer). Idempotente. Sem drift = no-op.
set -uo pipefail
PROJECT="${PROJECT:-smart-ads-451319}"; REGION="${REGION:-us-central1}"
API="${API_SVC:-smart-ads-api}"; MON="${MON_SVC:-smart-ads-monitoring}"
# Serviços que rodam a MESMA imagem do scorer e precisam andar junto. O
# `smart-ads-webhook` nasceu em 05/08/2026 (hospeda só o callback da Hotmart, para
# o serviço principal poder ficar fechado) e ficou de fora deste script, que só
# conhecia dois. Divergiu no dia seguinte, em silêncio. Serviço novo que espelhe a
# imagem entra AQUI.
ESPELHOS="${ESPELHOS:-$MON smart-ads-webhook}"
GS="${GS_BASE:-gs://smart-ads-mlflow/deploy-gate}"

live_rev(){ gcloud run services describe "$1" --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null \
  | python3 -c "import json,sys
try:
 d=json.load(sys.stdin)
 print(next((t['revisionName'] for t in d['status']['traffic'] if t.get('percent')==100),''))
except Exception: pass"; }
rev_img(){ gcloud run revisions describe "$1" --region="$REGION" --project="$PROJECT" --format='value(spec.containers[0].image)' 2>/dev/null; }
rev_sha(){ gcloud run revisions describe "$1" --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null \
  | python3 -c "import json,sys
try:
 d=json.load(sys.stdin); e={x['name']:x.get('value') for x in d['spec']['containers'][0].get('env',[]) if 'value' in x}
 print(e.get('DEPLOY_GIT_SHA','unknown'))
except Exception: print('unknown')"; }
alert(){ [ -n "${SLACK_WEBHOOK:-}" ] && curl -sS -m 10 -X POST -H 'Content-type: application/json' -d "{\"text\":\"$1\"}" "$SLACK_WEBHOOK" >/dev/null 2>&1 || true; }
ledger(){ local svc="$1" ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"ts":"%s","host":"cron","action":"sync","service":"%s","from_sha":"%s","to_sha":"%s","result":"%s","reason":"%s"}\n' \
    "$ts" "$svc" "$2" "$3" "$4" "$5" | gcloud storage cp - "$GS/events/${ts//:/-}_${svc}_sync.json" --project="$PROJECT" >/dev/null 2>&1 || true; }

ar=$(live_rev "$API"); ai=$(rev_img "$ar"); as=$(rev_sha "$ar")
[ -z "$ai" ] && { echo "não obtive a imagem do scorer — abortando sem tocar."; exit 0; }
echo "[deploy-gate-cron] scorer=$as ($ai)  espelhos: $ESPELHOS"

alinhar(){
  local svc="$1" mr mi newrev ready motivo err_tmp
  mr=$(live_rev "$svc"); mi=$(rev_img "$mr")
  if [ -z "$mr" ]; then echo "  $svc: não achei revisão viva — pulo."; return 0; fi
  if [ "$ai" = "$mi" ]; then echo "  $svc: sem drift."; return 0; fi

  echo "  $svc: DRIFT ($(rev_sha "$mr") != $as). Alinhando…"
  # O erro do gcloud é CAPTURADO e impresso. Antes ia pra /dev/null e a mensagem
  # era só "falha ao criar revisão", sem dizer por quê: em 06/08/2026 isso escondeu
  # uma falta de permissão trivial (a conta deste job não tinha
  # `iam.serviceAccountUser` sobre a conta com que o serviço EXECUTA, que é outra).
  # Pior: como todo dia anterior era no-op, o job passava verde sem nunca ter
  # criado revisão. A primeira vez que teve trabalho real, falhou.
  err_tmp=$(mktemp)
  newrev=$(gcloud run services update "$svc" --region="$REGION" --project="$PROJECT" \
             --image="$ai" --update-env-vars="DEPLOY_GIT_SHA=$as" \
             --format='value(status.latestCreatedRevisionName)' 2>"$err_tmp")
  if [ -z "$newrev" ]; then
    motivo=$(tail -3 "$err_tmp" | tr '\n' ' '); rm -f "$err_tmp"
    echo "  $svc: falha ao criar revisão: $motivo"
    ledger "$svc" "$mi" "$as" fail "create: $motivo"
    alert "deploy-gate cron: falhei ao criar revisão de $svc pra $as. Motivo: $motivo"
    return 1
  fi
  rm -f "$err_tmp"

  if ! gcloud run services update-traffic "$svc" --region="$REGION" --project="$PROJECT" \
         --to-revisions="$newrev=100" >/dev/null 2>&1; then
    echo "  $svc: falha ao rotear."
    ledger "$svc" "$mi" "$as" fail route
    alert "deploy-gate cron: falhei ao rotear $svc pra $newrev."
    return 1
  fi

  sleep 5
  ready=$(gcloud run revisions describe "$newrev" --region="$REGION" --project="$PROJECT" \
            --format='value(status.conditions[0].status)' 2>/dev/null)
  if [ "$ready" != "True" ]; then
    echo "  $svc: revisão nova não ficou Ready ($ready) — ROLLBACK pra $mr."
    gcloud run services update-traffic "$svc" --region="$REGION" --project="$PROJECT" \
      --to-revisions="$mr=100" >/dev/null 2>&1
    ledger "$svc" "$mi" "$as" fail rollback-not-ready
    alert "deploy-gate cron: revisão nova de $svc não subiu, revertido pra $mr. Verifique."
    return 1
  fi

  echo "  $svc: OK, alinhado a $as ($newrev)."
  ledger "$svc" "$mi" "$as" ok cron-align
  alert "deploy-gate cron: $svc estava atrás e foi realinhado ao scorer ($as). Alguém deployou por fora do gate?"
  return 0
}

# Um espelho que falha NÃO impede os outros de alinhar: o resultado final é a
# soma, e o exit code diz se algum ficou para trás.
falhas=0
for svc in $ESPELHOS; do alinhar "$svc" || falhas=$((falhas+1)); done
[ "$falhas" -eq 0 ] || { echo "$falhas espelho(s) não alinharam."; exit 1; }
echo "todos os espelhos alinhados."
exit 0
