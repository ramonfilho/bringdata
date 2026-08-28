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

# Papel de cada espelho (a env SERVICE_ROLE que api/auth.py lê). Vazio = papel
# `full`, que é o default do código e não precisa ser escrito.
#
# Por que isto mora aqui: o IAM do Cloud Run é por SERVIÇO, não por rota. O
# `smart-ads-webhook` é o único público (a Hotmart não assina token do Google), e
# sem SERVICE_ROLE=webhook ele volta a servir as 36 rotas da API, que é exatamente
# o que a separação de 05/08/2026 existe para evitar. `papel_do_servico()` cai em
# `full` quando a env falta, então o valor ausente ABRE a superfície em silêncio.
#
# Duplicado de propósito no deploy-gate.sh (sync_um_espelho): este arquivo roda num
# Cloud Run Job a partir do GCS, sem o repositório por perto, e não pode sourcear
# config.sh. Mudou aqui, muda lá, e o teste test_papel_do_espelho.py cobra os dois.
papel_do_espelho(){ case "$1" in smart-ads-webhook) echo "webhook";; *) echo "";; esac; }

live_rev(){ gcloud run services describe "$1" --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null \
  | python3 -c "import json,sys
try:
 d=json.load(sys.stdin)
 print(next((t['revisionName'] for t in d['status']['traffic'] if t.get('percent')==100),''))
except Exception: pass"; }
rev_img(){ gcloud run revisions describe "$1" --region="$REGION" --project="$PROJECT" --format='value(spec.containers[0].image)' 2>/dev/null; }
rev_env(){ gcloud run revisions describe "$1" --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null \
  | ENV_KEY="$2" ENV_FALLBACK="${3:-unknown}" python3 -c "import json,os,sys
try:
 d=json.load(sys.stdin); e={x['name']:x.get('value') for x in d['spec']['containers'][0].get('env',[]) if 'value' in x}
 print(e.get(os.environ['ENV_KEY'], os.environ['ENV_FALLBACK']))
except Exception: print(os.environ['ENV_FALLBACK'])"; }
rev_sha(){ rev_env "$1" DEPLOY_GIT_SHA unknown; }
# Papel VIVO do serviço. Fallback vazio de propósito: env ausente é exatamente o
# estado que precisa ser corrigido, e 'unknown' aqui viraria um papel inventado.
rev_papel(){ rev_env "$1" SERVICE_ROLE ""; }
alert(){ [ -n "${SLACK_WEBHOOK:-}" ] && curl -sS -m 10 -X POST -H 'Content-type: application/json' -d "{\"text\":\"$1\"}" "$SLACK_WEBHOOK" >/dev/null 2>&1 || true; }
ledger(){ local svc="$1" ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"ts":"%s","host":"cron","action":"sync","service":"%s","from_sha":"%s","to_sha":"%s","result":"%s","reason":"%s"}\n' \
    "$ts" "$svc" "$2" "$3" "$4" "$5" | gcloud storage cp - "$GS/events/${ts//:/-}_${svc}_sync.json" --project="$PROJECT" >/dev/null 2>&1 || true; }

ar=$(live_rev "$API"); ai=$(rev_img "$ar"); as=$(rev_sha "$ar")
[ -z "$ai" ] && { echo "não obtive a imagem do scorer — abortando sem tocar."; exit 0; }
echo "[deploy-gate-cron] scorer=$as ($ai)  espelhos: $ESPELHOS"

alinhar(){
  local svc="$1" mr mi mp papel img envs precisa="" newrev ready motivo err_tmp
  mr=$(live_rev "$svc"); mi=$(rev_img "$mr")
  if [ -z "$mr" ]; then echo "  $svc: não achei revisão viva — pulo."; return 0; fi
  papel=$(papel_do_espelho "$svc"); mp=$(rev_papel "$mr")

  # DOIS motivos independentes para mexer, e o segundo não é consequência do
  # primeiro: um serviço recriado do zero nasce na imagem CERTA e sem SERVICE_ROLE.
  # Reafirmar o papel só quando há drift de imagem não seria auto-cura nenhuma,
  # porque o dia em que o papel some é justamente um dia sem drift de imagem.
  [ "$ai" != "$mi" ] && precisa="imagem"
  [ -n "$papel" ] && [ "$mp" != "$papel" ] && precisa="${precisa:+$precisa+}papel"
  if [ -z "$precisa" ]; then echo "  $svc: sem drift."; return 0; fi

  # Só troca de imagem quem está atrasado. Quando o buraco é só o papel, a revisão
  # nova nasce da MESMA imagem que já está servindo: consertar a env não é desculpa
  # para empurrar imagem nova num serviço que não pediu.
  img="$mi"; [ "$ai" != "$mi" ] && img="$ai"
  envs="DEPLOY_GIT_SHA=$as"; [ -n "$papel" ] && envs="$envs,SERVICE_ROLE=$papel"

  echo "  $svc: DRIFT em [$precisa] (sha $(rev_sha "$mr") vs $as; papel '${mp:-ausente}' vs '${papel:-full}'). Alinhando…"
  # O erro do gcloud é CAPTURADO e impresso. Antes ia pra /dev/null e a mensagem
  # era só "falha ao criar revisão", sem dizer por quê: em 06/08/2026 isso escondeu
  # uma falta de permissão trivial (a conta deste job não tinha
  # `iam.serviceAccountUser` sobre a conta com que o serviço EXECUTA, que é outra).
  # Pior: como todo dia anterior era no-op, o job passava verde sem nunca ter
  # criado revisão. A primeira vez que teve trabalho real, falhou.
  err_tmp=$(mktemp)
  newrev=$(gcloud run services update "$svc" --region="$REGION" --project="$PROJECT" \
             --image="$img" --update-env-vars="$envs" \
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

  echo "  $svc: OK, alinhado a $as ($newrev) [$precisa]."
  ledger "$svc" "$mi" "$as" ok "cron-align:$precisa"
  # Papel restaurado é alarme de outra natureza que imagem atrasada: significa que
  # o serviço público rodou sem a lista de rotas reduzida até este job passar.
  if [ "$precisa" = papel ]; then
    alert "deploy-gate cron: $svc estava SEM SERVICE_ROLE=$papel e foi restaurado. Enquanto faltou, ele servia as rotas todas. Alguém recriou o serviço?"
  else
    alert "deploy-gate cron: $svc estava atrás e foi realinhado ao scorer ($as) [$precisa]. Alguém deployou por fora do gate?"
  fi
  return 0
}

# Um espelho que falha NÃO impede os outros de alinhar: o resultado final é a
# soma, e o exit code diz se algum ficou para trás.
falhas=0
for svc in $ESPELHOS; do alinhar "$svc" || falhas=$((falhas+1)); done
[ "$falhas" -eq 0 ] || { echo "$falhas espelho(s) não alinharam."; exit 1; }
echo "todos os espelhos alinhados."
exit 0
