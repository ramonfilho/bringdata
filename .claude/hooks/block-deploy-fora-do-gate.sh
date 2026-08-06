#!/usr/bin/env bash
# PreToolUse hook — bloqueia os dois jeitos de mexer em produção por fora do
# gatekeeper de deploy:
#
#   1. chamar `deploy_capi.sh` direto (o certo é `deploy-gate.sh deploy`)
#   2. promover tráfego na mão com `gcloud run services update-traffic` no
#      smart-ads-api (o certo é `deploy-gate.sh promote --revision <canary>`)
#
# Por que existe: em 05-06/08/2026 o `deploy_capi.sh` foi chamado direto SEIS
# vezes, com promoção de tráfego na mão. Os seis deploys ficaram FORA do ledger,
# o lockstep nunca rodou, e o serviço de monitoramento ficou numa imagem diferente
# da do scorer sem ninguém notar. Nada impedia: o hook que existia só olhava
# Edit/Write, e comando de shell passava livre.
#
# Camada dupla de propósito: o `deploy_capi.sh` também tem trava própria, que vale
# para qualquer chamador (pessoa, CI, outro script). Este hook pega ANTES da
# execução e explica o caminho certo, que é mais barato que descobrir depois.
#
# Escape hatch: prefixar `DEPLOY_SEM_GATE=1`. Grita no log e fica no histórico.
#
# Saída: exit 2 = bloqueia a tool e devolve o stderr ao agente.

input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c "import sys,json
try:
    print(json.load(sys.stdin).get('tool_input',{}).get('command',''))
except Exception:
    print('')" 2>/dev/null)

[ -z "$cmd" ] && exit 0

# Emergência declarada: deixa passar. A decisão fica registrada no próprio comando.
case "$cmd" in *DEPLOY_SEM_GATE=1*|*DEPLOY_VIA_GATE=1*) exit 0 ;; esac

# 1) deploy_capi.sh chamado direto. O gatekeeper chama por caminho absoluto de
#    dentro dele mesmo, e nesses casos o DEPLOY_VIA_GATE=1 acima já liberou.
case "$cmd" in
  *deploy_capi.sh*)
    cat >&2 <<'MSG'
🚫 BLOQUEADO: deploy_capi.sh não é a porta de entrada do deploy.

   Use:    bash V2/api/deploy-gate.sh deploy
   Depois: bash V2/api/deploy-gate.sh promote --revision <canary>
   (ou a skill /deploy)

   O gatekeeper adiciona cinco coisas que o script sozinho não tem:
   lock compartilhado, checagem de frescor, monotonicidade (não regride o
   que está vivo), registro no ledger durável, e o LOCKSTEP que alinha o
   serviço de monitoramento à mesma imagem na promoção.

   Em 05-06/08/2026 isso foi contornado seis vezes e o resultado foi seis
   deploys fora do ledger e o monitoring numa imagem divergente.

   Emergência de verdade: DEPLOY_SEM_GATE=1 bash V2/api/deploy_capi.sh …
MSG
    exit 2
    ;;
esac

# 2) promoção de tráfego na mão no serviço do scorer. `describe` e `list` seguem
#    livres: o que se barra é MUDAR o roteamento, não olhar.
case "$cmd" in
  *"run services update-traffic"*)
    case "$cmd" in
      *smart-ads-api*)
        cat >&2 <<'MSG'
🚫 BLOQUEADO: promoção de tráfego do smart-ads-api na mão.

   Use:  bash V2/api/deploy-gate.sh promote --revision <canary>

   O `update-traffic` cru pula o LOCKSTEP (o monitoring fica numa imagem
   diferente do scorer) e não escreve no ledger, então o histórico de "o que
   está em produção e desde quando" fica com buraco.

   Emergência de verdade: prefixe DEPLOY_SEM_GATE=1.
MSG
        exit 2
        ;;
    esac
    ;;
esac

exit 0
