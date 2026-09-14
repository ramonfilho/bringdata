#!/usr/bin/env bash
# Sobe uma revisão canary do smart-ads-api um degrau (0->10, 10->50, 50->100) COM ROLLBACK
# AUTOMÁTICO. É o que cada job de promoção do deploy.yml roda depois da aprovação.
#
# Uso: promover_com_rollback.sh <revisao> <revisao_anterior> <de> <para>
#   <revisao>           a canary (ex.: smart-ads-api-01144-xon)
#   <revisao_anterior>  a que tinha 100% antes do canário: é para ela que o rollback volta
#   <de> <para>         o degrau: 0 10 | 10 50 | 50 100
#
# Sequência:
#   0. Degrau 0 -> 10: o progression_gate NÃO roda aqui. A revisão a 0% não tem lote nenhum
#      na janela (só o replay do Gate C, que já saiu da janela quando alguém aprova), e o
#      gate devolve HOLD "precisa receber tráfego primeiro" para sempre: foi o que aconteceu
#      no run 34873411719 em 14/09/2026. A pergunta "essa revisão pode receber os primeiros
#      10%?" já foi respondida no deploy (Gates B, D, C e o check 0 -> 10 logo depois do
#      replay). O que cabe antes de mover os primeiros 10% é o smoke de novo.
#   1. Degraus 10 -> 50 e 50 -> 100: progression_gate (PROMOTE=0, HOLD=1, ROLLBACK=2, infra=3)
#        0 -> segue;  1 -> sai 1 SEM mexer em tráfego (falta tempo de observação, não é
#        defeito: aprovar de novo mais tarde);  2 -> rollback;  3 -> sai 1 sem mexer.
#   2. deploy-gate promote --to <para>. Falhou no meio -> rollback.
#   3. smoke na revisão DEPOIS de receber tráfego. Falhou -> rollback.
# Rollback = deploy-gate promote --revision <anterior> --to 100 --rollback --yes (a anterior
# volta a 100% e a canary cai a 0%; o --rollback libera a trava de monotonicidade do gate).
# Se até o rollback falhar, o resumo do job imprime o comando para rodar na mão.
#
# Os três comandos vêm de variáveis para o teste injetar dublês (tests/test_promover_com_rollback.py):
#   GATE_CMD, PROMOTE_CMD, SMOKE_CMD
set -euo pipefail

V2="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REV="${1:?uso: promover_com_rollback.sh <revisao> <revisao_anterior> <de> <para>}"
PREV="${2:?revisao anterior (alvo do rollback)}"
DE="${3:?de}"
PARA="${4:?para}"
GATE_CMD="${GATE_CMD:-python3 $V2/scripts/progression_gate.py}"
PROMOTE_CMD="${PROMOTE_CMD:-bash $V2/api/deploy-gate.sh promote}"
SMOKE_CMD="${SMOKE_CMD:-python3 $V2/scripts/smoke_test_revision.py}"

resumo() {
  echo "$*"
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "$*" >> "$GITHUB_STEP_SUMMARY"
  return 0
}

rollback() {
  resumo "ROLLBACK AUTOMÁTICO: $1. Devolvendo 100% para $PREV."
  if $PROMOTE_CMD --revision "$PREV" --to 100 --rollback --yes; then
    resumo "rollback feito: $PREV com 100%, $REV com 0%. Revisão $REV NÃO promovida."
  else
    resumo "ROLLBACK FALHOU. Rode na mão: bash V2/api/deploy-gate.sh promote --revision $PREV --to 100 --rollback --yes"
  fi
  exit 1
}

if [ "$DE" = 0 ]; then
  if $SMOKE_CMD "$REV"; then resumo "smoke antes dos primeiros 10%: OK (o check 0 -> 10 foi respondido no deploy, logo depois do Gate C)."
  else resumo "smoke falhou em $REV a 0%. Tráfego não mudou."; exit 1; fi
  rc=0
else
  set +e
  $GATE_CMD --revision "$REV" --from "$DE" --to "$PARA" --rollback "$PREV"
  rc=$?
  set -e
fi
case "$rc" in
  0) resumo "gate $DE -> $PARA: PROMOTE." ;;
  1) resumo "gate $DE -> $PARA: HOLD. Tráfego não mudou. Não é defeito da revisão, é tempo de observação: aprove este degrau de novo mais tarde (re-run do job)."; exit 1 ;;
  2) rollback "gate $DE -> $PARA devolveu ROLLBACK" ;;
  *) resumo "gate $DE -> $PARA: erro de infra (exit $rc). Tráfego não mudou."; exit 1 ;;
esac

$PROMOTE_CMD --revision "$REV" --to "$PARA" --yes || rollback "promote a ${PARA}% falhou no meio"

if $SMOKE_CMD "$REV"; then
  resumo "smoke depois do promote: OK. $REV com ${PARA}%."
else
  rollback "smoke falhou depois de mover ${PARA}% para $REV"
fi
