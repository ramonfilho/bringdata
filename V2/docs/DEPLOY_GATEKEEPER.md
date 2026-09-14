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

## Pelo GitHub Actions (desde 14/09/2026)

O motor é o mesmo (`deploy-gate.sh` envelopando o `deploy_capi.sh`); o que muda é quem chama: o runner do GitHub, com a identidade federada da conta `github-deployer`, em vez de um laptop com `.env`.

| Etapa | Onde roda | O que faz |
|---|---|---|
| PR aberta | `ci.yml` | lint mínimo (ruff E9, F63, F7, F82), suíte inteira em Python 3.10 sem credencial, gate do modelo se `configs/active_models/` mudou |
| Merge na `main` | `deploy.yml`, job `canary` | suíte de novo, build da imagem do SHA mergeado, `deploy-gate.sh deploy --yes` (revisão a 0%, Gates B, D, C, check 0 → 10) |
| Promoção | jobs `canary-10`, `canary-50`, `production` | esperam aprovação no environment de mesmo nome, rodam `progression_gate` (0 = promove, 1 = HOLD e o job pode ser reexecutado, 2 = ROLLBACK) e `deploy-gate.sh promote --to N --yes`; em 100% o lockstep alinha monitoring e webhook |
| Prova da identidade | `deploy.yml` com `modo=wif-check` (workflow_dispatch) | token de identidade, bucket do gate, segredo, registro de imagens; não toca produção |

O que o script ganhou para rodar fora do Mac: raiz do repositório derivada do próprio arquivo; lock e ledger gravam `github:<ator>:run<id>`; artefatos dos runs do YAML vêm do bucket (`scripts/baixar_artefatos_modelo.sh`) quando não estão no disco; Gate C sem credencial é falha, não aviso; alvo de rollback é a revisão que serve 100% (não a mais nova) e é obrigatório no `progression_gate`.

**Trava da promoção.** Os três jobs de promoção só rodam com a variável do repositório `PROMOTION_ENABLED=true`. Num repositório privado no plano Free o GitHub não oferece required reviewers, e um environment sem proteção promoveria sem ninguém aprovar. Ligar a variável só depois de criar os environments `canary-10`, `canary-50` e `production` com reviewer.

**Uma vez, pelo dono do projeto:** `bash V2/scripts/bootstrap_identidade_ci.sh` (conta de serviço, papéis mínimos, segredo `slack-webhook-url`, pool e provider de Workload Identity Federation restritos a `ramonfilho/bringdata`, variáveis `GCP_WORKLOAD_IDENTITY_PROVIDER` e `GCP_DEPLOYER_SA` no GitHub). Nenhuma chave JSON.
