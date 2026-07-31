# /deploy — deploy governado (gatekeeper)

Todo deploy de produção passa pelo `V2/api/deploy-gate.sh` — nunca `deploy_capi.sh` direto, nunca overlay (`gcloud run services update --image`) na mão. Doc completa: `V2/docs/DEPLOY_GATEKEEPER.md`.

## Como agir quando esta skill for invocada
1. **SEMPRE** comece pelo estado: `bash V2/api/deploy-gate.sh status`
2. **Prévia** antes de agir: `... deploy --dry-run` / `... promote --revision R --dry-run`
3. Só com **OK explícito** do usuário, execute (sem `--dry-run`).
4. Se o status mostrar **DRIFT** do monitoring: `... sync-monitoring`.

## Garantias (o script força; nunca burlar)
Lock (um deploy por vez) · frescor `HEAD == topo da origin/main` (não só ancestral) · monotonicidade (não regride o SHA vivo) · anti-drift api/monitoring · ledger + verificação pós-promote. **Nunca toca produção em `status`/`--dry-run`; nunca remove `allUsers`/`main`.**

## Regras de ouro
- Deploy só da **main atualizada** (`git pull --ff-only` antes). Sala atrás → o gate recusa: **atualize, não force**.
- Nunca use `--rollback`/`--allow-behind` sem intenção explícita do usuário.
- Promoção de tráfego é passo **separado e governado** (`promote`), com verificação pós.
- Na dúvida do que está vivo, a resposta é `deploy-gate.sh status` (fonte única), não arqueologia de openapi/revisões.
