#!/usr/bin/env bash
# deploy-gate.sh — Orquestrador/gatekeeper de deploys. Envelopa (não substitui) o
# deploy_capi.sh e adiciona as travas que faltavam para acabar com "revisão/imagem
# antiga em produção" e deploys concorrentes colidindo.
#
# Garantias:
#   A. LOCK/FILA        — um deploy por vez (lock distribuído no GCS; cross-máquina/sessão).
#   B. FRESCOR = TOPO   — só deploya se HEAD == origin/main (o TOPO), não só ancestral.
#   C. MONOTONICIDADE   — recusa subir/promover um SHA que está ATRÁS do que já está vivo.
#   D. LOCKSTEP         - ao promover o api, alinha TODOS os espelhos (monitoring + webhook) à MESMA imagem.
#   E. LEDGER + VERIFY  — registra todo deploy (durável, compartilhado) e confere pós-promote.
#
# NUNCA toca produção em `status` nem em `--dry-run`. NUNCA remove allUsers/main.
#
# Uso:
#   deploy-gate.sh status                          # visão única: SHA vivo/serviço, relação c/ main, drift, lock, ledger
#   deploy-gate.sh deploy [--dry-run] [--yes]      # trava+frescor+monotonicidade -> deploy_capi (canary api) -> ledger
#   deploy-gate.sh promote --revision R [--to N] [--no-sync] [--dry-run]   # promove api + LOCKSTEP de TODOS os espelhos + verifica
#   deploy-gate.sh sync-monitoring [--dry-run]     # cria revisão do monitoring na imagem viva do api, ROTEIA tráfego, Ready, rollback
#   deploy-gate.sh unlock                          # quebra lock preso (confirmação)
# Overrides (uso consciente): --allow-behind (canary fora do topo)  --rollback (promover atrás do vivo)  --no-sync (não alinhar monitoring)
set -uo pipefail

REPO="/Users/ramonmoreira/Desktop/bring_data"
PROJECT="smart-ads-451319"; REGION="us-central1"
API_SVC="smart-ads-api"; MON_SVC="smart-ads-monitoring"
# Serviços que rodam a MESMA imagem do scorer e precisam andar junto com ele.
# ESTA LISTA TEM QUE CASAR com a do `lib/sync_espelhos_cron.sh`. Em 06/08/2026 elas
# divergiram: o cron do dia já conhecia o `smart-ads-webhook` (PR #153) e o gate NÃO,
# então `promote` alinhava só o monitoring e deixava o webhook num commit anterior até
# o cron do dia seguinte passar. Janela de horas com o serviço PÚBLICO que atende a
# Hotmart rodando código diferente do resto. Serviço novo que espelhe a imagem entra AQUI.
ESPELHOS="${ESPELHOS:-$MON_SVC smart-ads-webhook}"
# Papel de cada espelho (a env SERVICE_ROLE que api/auth.py lê). Vazio = papel `full`,
# o default do código, que não precisa ser escrito. O `smart-ads-webhook` é o único
# serviço público: sem SERVICE_ROLE=webhook ele volta a servir as 36 rotas da API.
# `papel_do_servico()` cai em `full` quando a env falta, então o valor ausente ABRE a
# superfície em silêncio. GÊMEA da função em lib/sync_espelhos_cron.sh: mudou aqui,
# muda lá (aquele arquivo roda do GCS, sem o repo, e não pode sourcear este).
papel_do_espelho(){ case "$1" in smart-ads-webhook) echo "webhook";; *) echo "";; esac; }
DEPLOY_CAPI="$REPO/V2/api/deploy_capi.sh"
GS_BASE="gs://smart-ads-mlflow/deploy-gate"; LOCK_OBJ="$GS_BASE/lock.json"; LOCK_TTL_MIN=45

if [ -t 1 ]; then c_red=$'\e[31m'; c_grn=$'\e[32m'; c_yel=$'\e[33m'; c_cya=$'\e[36m'; c_off=$'\e[0m'
else c_red=""; c_grn=""; c_yel=""; c_cya=""; c_off=""; fi
info(){ echo "${c_cya}i${c_off}  $*"; }
ok(){   echo "${c_grn}ok${c_off} $*"; }
warn(){ echo "${c_yel}!!${c_off} $*"; }
err(){  echo "${c_red}xx${c_off} $*" >&2; }
now_utc(){ date -u +%Y-%m-%dT%H:%M:%SZ; }

# ───────── helpers read-only ─────────
live_revision(){ gcloud run services describe "$1" --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null \
  | python3 -c "import json,sys
try:
  d=json.load(sys.stdin)
  for t in d.get('status',{}).get('traffic',[]):
    if t.get('percent')==100: print(t.get('revisionName') or ''); break
except Exception: pass"; }
rev_field(){ gcloud run revisions describe "$1" --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null \
  | python3 -c "import json,sys
try:
  d=json.load(sys.stdin); c=d['spec']['containers'][0]
  e={x['name']:x.get('value') for x in c.get('env',[]) if 'value' in x}
  print({'sha':e.get('DEPLOY_GIT_SHA') or 'unknown','image':c.get('image',''),'papel':e.get('SERVICE_ROLE') or ''}.get('$2',''))
except Exception: pass"; }
rev_ready(){ gcloud run revisions describe "$1" --region="$REGION" --project="$PROJECT" --format='value(status.conditions[0].status)' 2>/dev/null; }
rel_to_main(){ local sha="$1"
  { [ -z "$sha" ] || [ "$sha" = "unknown" ]; } && { echo "SHA desconhecido (overlay/label velho)"; return; }
  git -C "$REPO" cat-file -e "${sha}^{commit}" 2>/dev/null || { echo "SHA não existe neste repo"; return; }
  if [ "$(git -C "$REPO" rev-parse "$sha")" = "$(git -C "$REPO" rev-parse origin/main)" ]; then echo "== topo da main"
  elif git -C "$REPO" merge-base --is-ancestor "$sha" origin/main 2>/dev/null; then echo "$(git -C "$REPO" rev-list --count "${sha}..origin/main") commits ATRÁS do topo"
  else echo "NÃO está na main (divergente)"; fi; }

# ───────── ledger (1 objeto por evento no GCS = sem corrida) ─────────
ledger_write(){ local ts; ts=$(now_utc); local obj="$GS_BASE/events/${ts//:/-}_$2_$1.json"
  printf '{"ts":"%s","host":"%s","action":"%s","service":"%s","from_sha":"%s","to_sha":"%s","result":"%s","reason":"%s"}\n' \
    "$ts" "$(hostname -s 2>/dev/null)" "$1" "$2" "$3" "$4" "$5" "${6:-}" \
    | gcloud storage cp - "$obj" --project="$PROJECT" >/dev/null 2>&1 && info "ledger: $1/$2 -> $5" || warn "ledger: falha (segue)"; }
ledger_tail(){ gcloud storage ls "$GS_BASE/events/" --project="$PROJECT" 2>/dev/null | sort | tail -"${1:-6}" \
  | while read -r o; do gcloud storage cat "$o" --project="$PROJECT" 2>/dev/null; done \
  | python3 -c "import json,sys
for l in sys.stdin:
  try:
    d=json.loads(l); print('   %s %8s/%s %s->%s %s %s'%(d['ts'],d['action'],d['service'].replace('smart-ads-',''),d['from_sha'][:7],d['to_sha'][:7],d['result'],d.get('reason','')))
  except Exception: pass"; }

# ───────── lock distribuído (GCS, atômico via if-generation-match=0) ─────────
lock_holder(){ gcloud storage cat "$LOCK_OBJ" --project="$PROJECT" 2>/dev/null; }
lock_acquire(){ local j; j=$(printf '{"host":"%s","ts":"%s","pid":%s}' "$(hostname -s)" "$(now_utc)" "$$")
  for a in 1 2 3; do
    if printf '%s\n' "$j" | gcloud storage cp - "$LOCK_OBJ" --if-generation-match=0 --project="$PROJECT" >/dev/null 2>&1; then ok "lock adquirido."; return 0; fi
    local held ts; held=$(lock_holder); ts=$(printf '%s' "$held" | python3 -c "import json,sys;print(json.load(sys.stdin).get('ts',''))" 2>/dev/null)
    if [ -n "$ts" ]; then local age; age=$(python3 -c "import datetime as d;t=d.datetime.fromisoformat('$ts'.replace('Z','+00:00'));print(int((d.datetime.now(d.timezone.utc)-t).total_seconds()//60))" 2>/dev/null || echo 0)
      if [ "${age:-0}" -ge "$LOCK_TTL_MIN" ]; then warn "lock preso há ${age}min ($held) — quebrando."; gcloud storage rm "$LOCK_OBJ" --project="$PROJECT" >/dev/null 2>&1; continue; fi
      warn "deploy concorrente ativo ($held). $a/3, aguardando 20s…"; else warn "lock sem info. $a/3, 20s…"; fi
    sleep 20
  done; err "não consegui o lock. Rode 'status' ou 'unlock' se preso."; return 1; }
lock_release(){ gcloud storage rm "$LOCK_OBJ" --project="$PROJECT" >/dev/null 2>&1 && info "lock liberado." || true; }

# ───────── comandos ─────────
cmd_status(){ git -C "$REPO" fetch origin main --quiet 2>/dev/null || warn "git fetch falhou"
  echo "==== deploy-status ====  (origin/main topo = $(git -C "$REPO" rev-parse --short origin/main 2>/dev/null))"
  # Percorre o scorer E TODOS os espelhos. Antes olhava só api+monitoring, então o
  # `smart-ads-webhook` podia estar numa imagem antiga e o status dizia "drift: nenhum".
  local img_api="" divergentes=""
  for s in "$API_SVC" $ESPELHOS; do local rev sha img; rev=$(live_revision "$s"); sha=$(rev_field "$rev" sha); img=$(rev_field "$rev" image)
    echo "- $s"; echo "    revisão : ${rev:-?}"; echo "    SHA     : ${sha:-?}   [$(rel_to_main "$sha")]"; echo "    imagem  : ${img##*/}"
    if [ "$s" = "$API_SVC" ]; then img_api="$img"
    elif [ "$img" != "$img_api" ]; then divergentes="$divergentes $s"; fi; done
  [ -z "$divergentes" ] && echo "- drift : nenhum (todos os espelhos na imagem do api)" \
    || echo "- ${c_yel}DRIFT${c_off}:$divergentes != imagem do api  ->  rode: deploy-gate.sh sync-monitoring"
  local h; h=$(lock_holder); echo "- lock  : $([ -n "$h" ] && echo "EM DEPLOY: $h" || echo "livre")"
  echo "- últimos deploys (ledger):"; ledger_tail 6; }

precheck(){ HEAD_SHA=$(git -C "$PWD" rev-parse --short HEAD 2>/dev/null); git -C "$PWD" fetch origin main --quiet 2>/dev/null || warn "git fetch falhou"
  TIP_SHA=$(git -C "$PWD" rev-parse --short origin/main 2>/dev/null)
  [ -n "$(git -C "$PWD" status --porcelain --untracked-files=no 2>/dev/null)" ] && { err "árvore suja (código não-commitado). Commit/stash antes."; return 1; }
  if [ "$(git -C "$PWD" rev-parse HEAD)" = "$(git -C "$PWD" rev-parse origin/main)" ]; then ok "frescor OK: HEAD ($HEAD_SHA) == topo da origin/main."
  else
    if git -C "$PWD" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then err "sua sala está $(git -C "$PWD" rev-list --count HEAD..origin/main) commits ATRÁS do topo (HEAD=$HEAD_SHA, topo=$TIP_SHA)."; echo "      Atualize: git pull --ff-only  (ou nova sala: scripts/feature-start.sh <nome>)"
    else err "HEAD ($HEAD_SHA) NÃO está na origin/main (não mergeado). Abra PR e mergeie."; fi
    [ "${ALLOW_BEHIND:-false}" = true ] && { warn "ALLOW_BEHIND=true — SÓ canary, NÃO promova."; return 0; }; return 1; fi; }

behind_live(){ local target="$1" live; live=$(rev_field "$(live_revision "$API_SVC")" sha)
  { [ -z "$live" ] || [ "$live" = unknown ]; } && { warn "SHA vivo indeterminável — pulo monotonicidade."; return 1; }
  git -C "$PWD" cat-file -e "${live}^{commit}" 2>/dev/null || { warn "SHA vivo ($live) fora do repo — pulo."; return 1; }
  [ "$(git -C "$PWD" rev-parse "$target")" != "$(git -C "$PWD" rev-parse "$live")" ] && git -C "$PWD" merge-base --is-ancestor "$target" "$live" 2>/dev/null; }

cmd_deploy(){ [ -f "$DEPLOY_CAPI" ] || { err "deploy_capi.sh não achado"; exit 1; }
  info "gate de deploy (serviço-base: $API_SVC; monitoring alinha no promote via lockstep)"
  precheck || exit 1
  if behind_live HEAD; then err "REGRESSÃO: HEAD ($HEAD_SHA) está ATRÁS do vivo. Reverteria produção."; [ "${ROLLBACK:-false}" = true ] || { echo "      rollback intencional? --rollback"; exit 1; }; warn "ROLLBACK=true — seguindo."; else ok "monotonicidade OK."; fi
  if [ "${DRY_RUN:-false}" = true ]; then echo "── PLANO (dry-run) ──"; echo "  1) lock  2) deploy_capi.sh (canary $API_SVC de $HEAD_SHA)  3) ledger"; echo "  (promoção: deploy-gate.sh promote --revision <canary> — já faz o lockstep do monitoring)"; return 0; fi
  [ "${YES:-false}" = true ] || { read -r -p "Confirmar canary de $HEAD_SHA? [y/N] " a; [ "$a" = y ] || { warn abortado.; exit 1; }; }
  lock_acquire || exit 1; trap lock_release EXIT
  local from; from=$(rev_field "$(live_revision "$API_SVC")" sha)
  if ( cd "$PWD" && DEPLOY_VIA_GATE=1 bash "$DEPLOY_CAPI" --yes ); then ok "canary do $API_SVC criado (0% tráfego)."; ledger_write deploy "$API_SVC" "${from:-?}" "$HEAD_SHA" ok "canary criado"; info "próximo: deploy-gate.sh promote --revision <canary> (promove api + alinha monitoring)."
  else err "deploy_capi.sh falhou."; ledger_write deploy "$API_SVC" "${from:-?}" "$HEAD_SHA" fail deploy_capi; exit 1; fi; }

cmd_promote(){ local rev="${PROMOTE_REV:-}" svc="${PROMOTE_SVC:-$API_SVC}" to="${PROMOTE_TO:-100}"
  [ -n "$rev" ] || { err "informe --revision <rev>"; exit 1; }
  git -C "$PWD" fetch origin main --quiet 2>/dev/null || true
  local rsha live; rsha=$(rev_field "$rev" sha); live=$(rev_field "$(live_revision "$svc")" sha)
  info "promover $rev ($rsha) -> ${to}% em $svc (vivo: $live)"
  if behind_live "$rsha"; then err "REGRESSÃO: promover $rsha reverteria o vivo ($live)."; [ "${ROLLBACK:-false}" = true ] || { echo "      rollback intencional? --rollback"; exit 1; }; warn "ROLLBACK=true — seguindo."; fi
  if [ "${DRY_RUN:-false}" = true ]; then echo "── PLANO (dry-run) ── update-traffic $svc --to-revisions=$rev=$to"; [ "$svc" = "$API_SVC" ] && [ "${NO_SYNC:-false}" != true ] && echo "  + LOCKSTEP: alinha [$ESPELHOS] à mesma imagem depois"; return 0; fi
  [ "${YES:-false}" = true ] || { read -r -p "Promover $rev a ${to}% em $svc? [y/N] " a; [ "$a" = y ] || { warn abortado.; exit 1; }; }
  lock_acquire || exit 1; trap lock_release EXIT
  gcloud run services update-traffic "$svc" --region="$REGION" --project="$PROJECT" --to-revisions="$rev=$to" >/dev/null 2>&1 || { err "update-traffic falhou."; ledger_write promote "$svc" "${live:-?}" "$rsha" fail update-traffic; exit 1; }
  sleep 3; local nl; nl=$(rev_field "$(live_revision "$svc")" sha)
  if [ "$nl" = "$rsha" ]; then ok "VERIFICADO: vivo == $rsha."; ledger_write promote "$svc" "${live:-?}" "$rsha" ok "to=$to verificado"
  else warn "vivo=$nl != pretendido=$rsha — confira."; ledger_write promote "$svc" "${live:-?}" "$rsha" warn verify-mismatch; fi
  # LOCKSTEP: promoveu o api a 100% → alinha o monitoring à MESMA imagem (não-fatal; api já está de pé).
  if [ "$svc" = "$API_SVC" ] && [ "$to" = 100 ] && [ "$nl" = "$rsha" ] && [ "${NO_SYNC:-false}" != true ]; then
    info "lockstep: alinhando os espelhos [$ESPELHOS] à imagem promovida ($rsha)…"
    ( _GATE_LOCKED=1; YES=true; cmd_sync_monitoring ) || warn "lockstep falhou em ao menos um espelho — api OK; rode 'deploy-gate.sh sync-monitoring' na mão."
  fi; }

# Alinha UM espelho à imagem viva do scorer. Devolve != 0 se falhar.
sync_um_espelho(){ local svc="$1" ai="$2" as="$3" mr mi mp papel img envs precisa="" newrev ready
  mr=$(live_revision "$svc"); mi=$(rev_field "$mr" image)
  [ -n "$mr" ] || { warn "$svc: não achei revisão viva — pulo."; return 0; }
  info "$svc vivo: $(rev_field "$mr" sha) ($mr)"
  papel=$(papel_do_espelho "$svc"); mp=$(rev_field "$mr" papel)
  # Imagem atrasada e papel ausente são drifts INDEPENDENTES. Um serviço recriado do
  # zero nasce na imagem certa e sem SERVICE_ROLE, e nesse dia não há drift de imagem
  # nenhum para carregar o conserto de carona.
  [ "$ai" != "$mi" ] && precisa="imagem"
  [ -n "$papel" ] && [ "$mp" != "$papel" ] && precisa="${precisa:+$precisa+}papel"
  [ -n "$precisa" ] || { ok "$svc: mesma imagem e papel '${papel:-full}' correto — nada a fazer."; return 0; }
  # Quando o buraco é só o papel, a revisão nova nasce da MESMA imagem que já serve:
  # consertar env não é desculpa para empurrar imagem nova num serviço que não pediu.
  img="$mi"; [ "$ai" != "$mi" ] && img="$ai"
  envs="DEPLOY_GIT_SHA=$as"; [ -n "$papel" ] && envs="$envs,SERVICE_ROLE=$papel"
  if [ "${DRY_RUN:-false}" = true ]; then echo "── PLANO (dry-run) ── $svc [$precisa] -> imagem $img (env: $envs): cria revisão, ROTEIA tráfego 100%, verifica Ready, rollback p/ $mr se falhar"; return 0; fi
  # 1) cria a revisão nova (imagem certa + label + papel do serviço). Tráfego pinado => nasce a 0%.
  newrev=$(gcloud run services update "$svc" --region="$REGION" --project="$PROJECT" --image="$img" --update-env-vars="$envs" --format='value(status.latestCreatedRevisionName)' 2>/dev/null)
  [ -n "$newrev" ] || { err "não criei a revisão nova do $svc."; ledger_write sync "$svc" "$mi" "$as" fail update; return 1; }
  info "$svc: revisão nova $newrev"
  # 2) ROTEIA o tráfego (o passo que faltava: trata o tráfego pinado)
  gcloud run services update-traffic "$svc" --region="$REGION" --project="$PROJECT" --to-revisions="$newrev=100" >/dev/null 2>&1 || { err "$svc: update-traffic falhou."; ledger_write sync "$svc" "$mi" "$as" fail route; return 1; }
  # 3) verifica Ready (a imagem é a viva do api, já comprovada em prod); rollback se não subir
  sleep 4; ready=$(rev_ready "$newrev")
  if [ "$ready" != "True" ]; then err "$svc: revisão nova não ficou Ready ($ready) — ROLLBACK p/ $mr."
    gcloud run services update-traffic "$svc" --region="$REGION" --project="$PROJECT" --to-revisions="$mr=100" >/dev/null 2>&1
    ledger_write sync "$svc" "$mi" "$as" fail rollback-not-ready; return 1; fi
  ok "$svc roteado p/ $newrev ($as), Ready [$precisa]."
  ledger_write sync "$svc" "$mi" "$as" ok "route+ready:$precisa"
  [ "$precisa" = papel ] && warn "$svc estava SEM SERVICE_ROLE=$papel: enquanto faltou, ele servia as rotas todas."
  info "rollback (se precisar): gcloud run services update-traffic $svc --region=$REGION --to-revisions=$mr=100"; }

cmd_sync_monitoring(){ local ar ai as falhou=0; ar=$(live_revision "$API_SVC"); ai=$(rev_field "$ar" image); as=$(rev_field "$ar" sha)
  [ -n "$ai" ] || { err "não obtive a imagem do scorer — abortando sem tocar."; return 1; }
  info "api vivo: $as ($ar)  espelhos: $ESPELHOS"
  [ "${YES:-false}" = true ] || [ "${DRY_RUN:-false}" = true ] || { read -r -p "Alinhar [$ESPELHOS] à imagem do api ($as)? [y/N] " a; [ "$a" = y ] || { warn abortado.; exit 1; }; }
  # lock: pula se já sob o lock do promote (lockstep)
  [ "${DRY_RUN:-false}" = true ] || [ "${_GATE_LOCKED:-0}" = 1 ] || { lock_acquire || exit 1; trap lock_release EXIT; }
  # Um espelho que falha NÃO impede os outros: melhor um alinhado do que nenhum.
  for _svc in $ESPELHOS; do sync_um_espelho "$_svc" "$ai" "$as" || falhou=1; done
  [ "$falhou" = 0 ] && ok "todos os espelhos alinhados." || { err "ao menos um espelho falhou."; return 1; }; }

cmd_unlock(){ local h; h=$(lock_holder); [ -z "$h" ] && { info "nenhum lock ativo."; return 0; }
  warn "lock atual: $h"; read -r -p "Quebrar? (só se NENHUM deploy roda) [y/N] " a; [ "$a" = y ] && { lock_release; ok "quebrado."; } || info mantido.; }

# ───────── main ─────────
CMD="${1:-status}"; shift 2>/dev/null || true
DRY_RUN=false; YES=false; ALLOW_BEHIND=false; ROLLBACK=false; NO_SYNC=false; PROMOTE_REV=""; PROMOTE_SVC="$API_SVC"; PROMOTE_TO=100
while [ $# -gt 0 ]; do case "$1" in
  --dry-run) DRY_RUN=true;; --yes|-y) YES=true;; --allow-behind) ALLOW_BEHIND=true;; --rollback) ROLLBACK=true;; --no-sync) NO_SYNC=true;;
  --revision) PROMOTE_REV="${2:-}"; shift;; --service) PROMOTE_SVC="${2:-}"; shift;; --to) PROMOTE_TO="${2:-}"; shift;;
  -h|--help) sed -n '2,30p' "$0"; exit 0;; *) err "flag desconhecida: $1"; exit 2;;
esac; shift; done
case "$CMD" in
  status) cmd_status;; deploy) cmd_deploy;; promote) cmd_promote;; sync-monitoring) cmd_sync_monitoring;; unlock) cmd_unlock;;
  *) err "comando: status|deploy|promote|sync-monitoring|unlock"; exit 2;;
esac
