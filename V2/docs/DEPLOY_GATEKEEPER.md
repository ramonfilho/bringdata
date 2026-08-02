# Deploy Gatekeeper — `deploy-gate.sh`

Orquestrador que envelopa o `deploy_capi.sh` para acabar com "revisão/imagem antiga em produção" e deploys concorrentes colidindo. **Todo deploy de produção deve passar por ele** (nunca `deploy_capi.sh` direto, nunca overlay na mão).

Arquivo: `V2/api/deploy-gate.sh`.

## Por que existe
O `deploy_capi.sh` (gate de procedência) já barra branch não-autorizada, árvore suja e código não-mergeado. Mas restavam 3 furos, que causaram o incidente de 30/07:
1. Aceita código **velho-mas-mergeado** — checa `is-ancestor` (ancestral), não o **topo** → dava pra promover uma sala de semanas atrás.
2. Não serializa deploys concorrentes (duas sessões colidiam).
3. Não governa o `smart-ads-monitoring` (deploy manual = overlay que fica pra trás; label `DEPLOY_GIT_SHA` mente).

## As 5 garantias
- **A. Lock/fila** — lock distribuído no GCS (`gs://smart-ads-mlflow/deploy-gate/lock.json`, criação atômica). Um deploy por vez, cross-sessão/máquina. `unlock` quebra lock preso (TTL 45min).
- **B. Frescor = topo** — só deploya se `HEAD == origin/main` (o topo), não só ancestral. Sala atrás → recusa com "git pull / feature-start".
- **C. Monotonicidade** — recusa subir/promover um SHA **atrás do que já está vivo** (regressão). `--rollback` libera de propósito.
- **D. Anti-drift** — `status` flagra quando `api` e `monitoring` estão em imagens diferentes; `sync-monitoring` alinha o monitoring à imagem viva do api, com o label correto.
- **E. Ledger + verify** — todo deploy real grava um evento no GCS (`deploy-gate/events/`, fonte única compartilhada) e a promoção **confere** que o vivo == pretendido.

## Fluxo (o padrão agora)
```
scripts/feature-start.sh <nome>        # sala nova da origin/main
  ...trabalhar...  ->  scripts/feature-finish.sh   # push + PR  ->  merge
git pull --ff-only                     # na main, pega o topo
V2/api/deploy-gate.sh status           # estado: vivo/serviço, drift, lock, ledger
V2/api/deploy-gate.sh deploy --dry-run # prévia
V2/api/deploy-gate.sh deploy           # canary do api (lock+B+C+deploy_capi+ledger)
V2/api/deploy-gate.sh promote --revision <canary>   # promoção governada + verify
V2/api/deploy-gate.sh sync-monitoring  # alinha o monitoring (mata o overlay)
```

## Comandos
| Comando | O que faz | Toca prod? |
|---|---|---|
| `status` | Visão única: SHA vivo/serviço, relação c/ main, drift, lock, ledger | não |
| `deploy [--dry-run] [--yes]` | Lock → frescor(B) → monotonicidade(C) → `deploy_capi.sh` (canary api) → ledger | só sem `--dry-run` |
| `promote --revision R [--to N] [--no-sync]` | Lock → C → update-traffic → **verify** → **LOCKSTEP: alinha o monitoring** à mesma imagem → ledger | só sem `--dry-run` |
| `sync-monitoring [--dry-run]` | Cria revisão do monitoring na imagem viva do api, **ROTEIA o tráfego** (trata tráfego pinado), verifica Ready, faz rollback se não subir | só sem `--dry-run` |
| `unlock` | Quebra lock preso (confirmação) | remove só o lock |

Overrides (uso consciente): `--allow-behind` (canary fora do topo, não promova), `--rollback` (promover atrás do vivo).

## Segurança e reversibilidade
- É **wrapper**: não chamar = comportamento antigo. O `deploy_capi.sh` segue intacto como defesa interna. Rollback = parar de usar / apagar o script.
- `status`, `--dry-run` e o lock **nunca** tocam produção. Nunca remove `allUsers` nem `main`.
- **Limitação conhecida:** o SHA vivo vem do label `DEPLOY_GIT_SHA`. Overlays antigos têm label velho (o gate corrige ao deployar). Enquanto o monitoring estiver no overlay pré-gate, o "N atrás" reflete o label velho — mas o sinal (monitoring precisa de deploy) continua certo; um `sync-monitoring` conserta o label junto.
